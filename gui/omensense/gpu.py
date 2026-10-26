"""GPU telemetry with zero PCIe stall, NVML (ctypes/pynvml) acceleration, D3cold detection, and non-blocking background queries.

Strictly avoids synchronous CLI calls on the Qt GUI event loop to eliminate
PCIe micro-stalls and browser acceleration freezing on NVIDIA mobile GPUs.
Uses direct ctypes NVML or pynvml for sub-millisecond queries (temp, fan speed, power usage, clocks, utilization).
Falls back to a cached, asynchronous non-blocking worker for nvidia-smi if NVML is unavailable.
Checks sysfs power status: if the GPU is in low-power runtime suspend (D3cold),
it returns cached/idle metrics immediately without waking the bus.
"""

from __future__ import annotations

import ctypes
import glob
import os
import shutil
import subprocess
import threading
import time

#: Queried in one call - nvidia-smi startup dominates, so asking for multiple fields costs the same.
_FIELDS = ("fan.speed", "temperature.gpu", "power.draw", "clocks.gr", "utilization.gpu", "name")
_TIMEOUT_S = 2.0
_CACHE_TTL = 3.0

_available: bool | None = None
_cached_data: dict = {}
_last_fetch_time: float = 0.0
_worker_thread: threading.Thread | None = None
_lock = threading.Lock()


class _NvmlBackend:
    """Fast, direct ctypes NVML backend for NVIDIA RTX 2060 telemetry."""

    def __init__(self):
        self.available = False
        self.lib = None
        self.device = None
        self._init_nvml()

    def _init_nvml(self):
        # 1. Try pynvml if installed
        try:
            import pynvml
            pynvml.nvmlInit()
            self.device = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.pynvml = pynvml
            self.available = True
            return
        except Exception:
            self.pynvml = None

        # 2. Try direct ctypes CDLL
        for lib_name in ("libnvidia-ml.so.1", "libnvidia-ml.so"):
            try:
                self.lib = ctypes.CDLL(lib_name)
                break
            except OSError:
                continue

        if not self.lib:
            return

        try:
            init_fn = getattr(self.lib, "nvmlInit_v2", getattr(self.lib, "nvmlInit", None))
            if not init_fn or init_fn() != 0:
                return

            dev = ctypes.c_void_p()
            get_handle = getattr(self.lib, "nvmlDeviceGetHandleByIndex_v2",
                                 getattr(self.lib, "nvmlDeviceGetHandleByIndex", None))
            if not get_handle or get_handle(0, ctypes.byref(dev)) != 0:
                return

            self.device = dev
            self.available = True
        except Exception:
            self.available = False

    def query(self) -> dict | None:
        if not self.available or self.device is None:
            return None

        # Handle pynvml if loaded
        if self.pynvml is not None:
            try:
                temp = self.pynvml.nvmlDeviceGetTemperature(self.device, 0)
                try:
                    pwr_mw = self.pynvml.nvmlDeviceGetPowerUsage(self.device)
                    power_w = round(pwr_mw / 1000.0, 1)
                except Exception:
                    power_w = None
                try:
                    fan_pct = self.pynvml.nvmlDeviceGetFanSpeed(self.device)
                except Exception:
                    fan_pct = None
                try:
                    util = self.pynvml.nvmlDeviceGetUtilizationRates(self.device).gpu
                except Exception:
                    util = 0
                try:
                    clk = self.pynvml.nvmlDeviceGetClockInfo(self.device, 0)
                except Exception:
                    clk = None
                try:
                    name = self.pynvml.nvmlDeviceGetName(self.device)
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                except Exception:
                    name = "NVIDIA GeForce RTX 2060 Mobile"

                return {
                    "temp": temp,
                    "fan_percent": fan_pct,
                    "power_w": power_w,
                    "clock_mhz": clk,
                    "usage": util,
                    "name": name,
                    "suspended": False,
                }
            except Exception:
                return None

        # Handle direct ctypes
        if not self.lib:
            return None

        try:
            res: dict = {"suspended": False}

            # Device Name
            name_buf = ctypes.create_string_buffer(64)
            if self.lib.nvmlDeviceGetName(self.device, name_buf, 64) == 0:
                res["name"] = name_buf.value.decode("utf-8", errors="replace")
            else:
                res["name"] = "NVIDIA GeForce RTX 2060 Mobile"

            # Temperature
            temp = ctypes.c_uint()
            if self.lib.nvmlDeviceGetTemperature(self.device, 0, ctypes.byref(temp)) == 0:
                res["temp"] = temp.value
            else:
                res["temp"] = None

            # Power draw in milliwatts
            pwr = ctypes.c_uint()
            if self.lib.nvmlDeviceGetPowerUsage(self.device, ctypes.byref(pwr)) == 0:
                res["power_w"] = round(pwr.value / 1000.0, 1)
            else:
                res["power_w"] = None

            # Fan Speed (Note: laptops commonly return NOT_SUPPORTED since EC controls fans)
            fan = ctypes.c_uint()
            if self.lib.nvmlDeviceGetFanSpeed(self.device, ctypes.byref(fan)) == 0:
                res["fan_percent"] = fan.value
            else:
                res["fan_percent"] = None

            # Utilization Rates
            class _NvmlUtilization(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            u = _NvmlUtilization()
            if self.lib.nvmlDeviceGetUtilizationRates(self.device, ctypes.byref(u)) == 0:
                res["usage"] = u.gpu
            else:
                res["usage"] = 0

            # Clocks
            clk = ctypes.c_uint()
            if self.lib.nvmlDeviceGetClockInfo(self.device, 0, ctypes.byref(clk)) == 0:
                res["clock_mhz"] = clk.value
            else:
                res["clock_mhz"] = None

            return res
        except Exception:
            return None


_nvml_backend: _NvmlBackend | None = None


def _get_nvml_backend() -> _NvmlBackend:
    global _nvml_backend
    if _nvml_backend is None:
        _nvml_backend = _NvmlBackend()
    return _nvml_backend


def available() -> bool:
    """Whether NVIDIA GPU telemetry is available via NVML or nvidia-smi."""
    global _available
    if _available is None:
        backend = _get_nvml_backend()
        _available = backend.available or (shutil.which("nvidia-smi") is not None)
    return _available


def is_suspended() -> bool:
    """Check sysfs nodes to see if the GPU is in low-power runtime suspend (D3cold).

    Invoking tools while the GPU is in runtime suspend causes PCIe bus wakeups,
    leading to desktop stutter and browser acceleration freezes.
    """
    for path in glob.glob("/sys/class/drm/card*/device/power/runtime_status"):
        try:
            with open(path) as f:
                if f.read().strip() == "suspended":
                    return True
        except OSError:
            pass
    for path in glob.glob("/sys/class/drm/card*/device/power_state"):
        try:
            with open(path) as f:
                val = f.read().strip()
                if "D3" in val:
                    return True
        except OSError:
            pass
    return False


def _as_int(text: str):
    text = text.strip().split()[0] if text.strip() else ""
    return int(text) if text.lstrip("-").isdigit() else None


def _as_float(text: str):
    text = text.strip().split()[0] if text.strip() else ""
    try:
        return round(float(text), 1)
    except ValueError:
        return None


def _query_raw() -> dict:
    """Query telemetry via NVML first, or fallback to nvidia-smi."""
    # 1. Fast path: Direct NVML query
    backend = _get_nvml_backend()
    if backend.available:
        data = backend.query()
        if data:
            return data

    # 2. Fallback path: nvidia-smi query
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        output = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(_FIELDS)}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=_TIMEOUT_S, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return {}
    if not output:
        return {}

    parts = [p.strip() for p in output.splitlines()[0].split(",")]
    if len(parts) < len(_FIELDS):
        return {}
    return {
        "fan_percent": _as_int(parts[0]),
        "temp": _as_int(parts[1]),
        "power_w": _as_float(parts[2]),
        "clock_mhz": _as_int(parts[3]),
        "usage": _as_int(parts[4]),
        "name": parts[5],
        "suspended": False,
    }


def _worker_fetch():
    global _cached_data, _last_fetch_time, _worker_thread
    try:
        data = _query_raw()
        with _lock:
            if data:
                _cached_data = data
            _last_fetch_time = time.monotonic()
    finally:
        with _lock:
            _worker_thread = None


def read(sync: bool = False) -> dict:
    """Current GPU state, non-blocking on the GUI event loop, with 3s caching.

    If the GPU is in low-power runtime suspend (D3cold), do not wake up the bus:
    return cached or idle values immediately.
    Synchronous execution is avoided on the Qt GUI event loop; background worker
    updates the cache when expired. Direct NVML queries run synchronously when sync=True.
    """
    global _worker_thread, _last_fetch_time, _cached_data
    if not available():
        return {}

    now = time.monotonic()

    # Low-power runtime suspend check: never wake PCIe bus
    if is_suspended():
        with _lock:
            if _cached_data:
                idle = dict(_cached_data)
                idle["usage"] = 0
                idle["suspended"] = True
                return idle
            return {
                "fan_percent": None,
                "temp": None,
                "power_w": None,
                "clock_mhz": 0,
                "usage": 0,
                "name": "NVIDIA GeForce RTX 2060 Mobile",
                "suspended": True,
            }

    with _lock:
        # Cache check
        if _cached_data and (now - _last_fetch_time < _CACHE_TTL):
            return dict(_cached_data)

        if sync:
            data = _query_raw()
            if data:
                _cached_data = data
                _last_fetch_time = now
            return dict(_cached_data)

        # Offload GPU querying to an isolated, throttled non-blocking worker thread
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=_worker_fetch, daemon=True, name="GPU-Telemetry-Worker"
            )
            _worker_thread.start()

        if _cached_data:
            return dict(_cached_data)

    return dict(_cached_data) if _cached_data else {}
