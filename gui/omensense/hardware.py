"""Zero-Crash Hardware Subsystem for MyOmen (HP OMEN Laptop 15-dh1xxx / Board 8746).

Implements:
1. Dynamic Hwmon Resolution: dynamically resolves 'hp', 'coretemp', and 'pch_cometlake' hwmon nodes.
2. GPU Telemetry: direct ctypes NVML / pynvml binding with non-blocking fallback worker.
3. Power Calculation: CPU package wattage via RAPL energy delta (intel-rapl:0/energy_uj).
4. Omen Autopilot: Fan curve state machine with 0ms thermal spike reaction (>75°C) and 5s dwell buffer.
5. HardwareWorker: Dedicated QThread with adaptive polling (1000ms UI visible, 5000ms tray, 15000ms battery).
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from typing import Optional

from PySide6 import QtCore

from . import gpu, monitoring

BOARD = "8746"
FAN_LABELS = ("Fan 1", "Fan 2")
FAN_NOTE = ("The embedded controller runs both fans together, Fan 2 about "
            "200 rpm faster, so which is CPU-side and which GPU-side does not "
            "show in their speeds.")
MAX_FAN_OBSERVED = True

# Keyboard lighting sysfs references
ZONES = ("left", "wasd", "center", "right")
ZONE_TITLES = {
    "left": "Left",
    "wasd": "WASD",
    "center": "Centre",
    "right": "Right + numpad",
}
LED_PREFIX = "/sys/class/leds/hp::kbd_zoned_backlight-"
LED_MAX = 255

# Profiles
PROFILE_ORDER = ("low-power", "balanced", "performance", "max")
PROFILE_TITLES = {
    "low-power": "Quiet",
    "balanced": "Balanced",
    "performance": "Performance",
    "max": "Max",
}
PROFILE_NOTES = {
    "low-power": "OMEN Cool · GPU configurable TGP off",
    "balanced": "OMEN Default · GPU configurable TGP off",
    "performance": "OMEN Performance · GPU configurable TGP on · needs charger",
    "max": "OMEN Max / Overdrive · Max Fans · Unlocked CPU/GPU Power · needs charger",
}


# ------------------------------------------------------------- Sysfs Utilities

def _read(path: str) -> str | None:
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return None


def _write(path: str, value: str) -> str | None:
    """Return None on success, or a message suitable for showing the user."""
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return None
    except PermissionError:
        return (f"No permission to write {os.path.basename(path)} — is "
                "99-myomen.rules installed, and are you in plugdev?")
    except OSError as err:
        return f"{os.path.basename(path)}: {err.strerror or err}"


def _num(path: str) -> int | None:
    raw = _read(path)
    return int(raw) if raw and raw.lstrip("-").isdigit() else None


# --------------------------------------------------- Dynamic Hwmon Resolution

def find_hwmon_by_name(target_name: str) -> Optional[Path]:
    """Scan /sys/class/hwmon/hwmon*/name dynamically at startup. NEVER hardcodes hwmonX."""
    for candidate in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        p = Path(candidate)
        try:
            name_file = p / "name"
            if name_file.is_file() and name_file.read_text().strip() == target_name:
                return p
        except OSError:
            continue
    return None


def _hwmon(name: str) -> str | None:
    p = find_hwmon_by_name(name)
    return str(p) if p is not None else None


def board() -> str | None:
    return _read("/sys/class/dmi/id/board_name")


def hwmon_path() -> str | None:
    return _hwmon("hp")


def driver_present() -> bool:
    return hwmon_path() is not None


def profile_path() -> str | None:
    path = "/sys/firmware/acpi/platform_profile"
    if os.path.exists(path):
        return path
    for cand in glob.glob("/sys/class/platform-profile/platform-profile-*/profile"):
        return cand
    return None


def profile_choices() -> tuple[str, ...]:
    path = "/sys/firmware/acpi/platform_profile_choices"
    if not os.path.exists(path):
        for cand in glob.glob("/sys/class/platform-profile/platform-profile-*/choices"):
            path = cand
            break
    raw = _read(path)
    if not raw:
        return ("low-power", "balanced", "performance")
    choices = tuple(raw.split())
    return choices if choices else ("low-power", "balanced", "performance")


def profile() -> str | None:
    path = profile_path()
    return _read(path) if path else None


def set_profile(mode: str) -> str | None:
    if mode == "max":
        # Max mode is Performance profile + Forced Max Fans
        err_p = set_profile("performance")
        err_f = set_max_fan(True)
        return err_p or err_f
    path = profile_path()
    if not path:
        return "No platform profile available."
    err = _write(path, mode)
    if not err and max_fan():
        # Leaving Max mode: restore fans to automatic
        set_max_fan(False)
    return err


def max_fan() -> bool | None:
    hp = find_hwmon_by_name("hp")
    if not hp:
        return None
    val = _num(str(hp / "pwm1_enable"))
    if val is None:
        return None
    return val == 0


def set_max_fan(enable: bool) -> str | None:
    hp = find_hwmon_by_name("hp")
    if not hp:
        return "hp hardware monitor node not found."
    return _write(str(hp / "pwm1_enable"), "0" if enable else "2")


def driver_problems() -> list[str]:
    problems = []
    if board() != BOARD:
        problems.append(f"This is board {board() or 'unknown'}, not {BOARD}; "
                        "MyOmen is built and verified for the 8746 only.")
    if not driver_present():
        problems.append("hp-wmi is not loaded.")
        return problems
    if not profile_path():
        problems.append("No platform profile: this looks like stock hp-wmi. "
                        "Install the patched one (driver/INSTALL.md).")
    if not zones_present():
        problems.append("No keyboard zones: kbd-rgb-v11.patch is not in the loaded hp-wmi.")
    return problems


def zones_present() -> bool:
    return any(os.path.isdir(LED_PREFIX + zone) for zone in ZONES)


# ------------------------------------------------------------- Telemetry & RAPL

def sensors() -> dict:
    """Read fan RPMs, CPU Package temperature, and PCH chipset temperature.
    
    Dynamically maps:
    - 'hp' hwmon -> fan1_input (CPU Fan RPM), fan2_input (GPU Fan RPM), pwm1_enable
    - 'coretemp' hwmon -> temp1_input (CPU Package Temp)
    - 'pch_cometlake' hwmon -> temp1_input (Chipset Temp)
    """
    hp_node = find_hwmon_by_name("hp")
    fans = [None, None]
    if hp_node:
        fans = [_num(str(hp_node / f"fan{i}_input")) for i in (1, 2)]

    cpu = None
    core_node = find_hwmon_by_name("coretemp")
    if core_node:
        milli = _num(str(core_node / "temp1_input"))
        cpu = milli // 1000 if milli is not None else None

    chipset = None
    pch_node = find_hwmon_by_name("pch_cometlake")
    if pch_node:
        milli = _num(str(pch_node / "temp1_input"))
        chipset = milli // 1000 if milli is not None else None

    return {"cpu_temp": cpu, "sys_temp": chipset, "fans": fans}


def rapl_energy_uj() -> int | None:
    return _num("/sys/class/powercap/intel-rapl:0/energy_uj")


def rapl_max_range_uj() -> int | None:
    return _num("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")


class RaplMonitor:
    """Calculates live CPU package wattage via RAPL energy delta over time:
    P = (E2 - E1) / ((t2 - t1) * 1e6) from /sys/class/powercap/intel-rapl:0/energy_uj.
    """

    def __init__(self):
        self._last_energy: int | None = None
        self._last_time: float = 0.0
        self._max_range = rapl_max_range_uj()

    def sample(self) -> float | None:
        energy = rapl_energy_uj()
        now = time.monotonic()
        if energy is None:
            return None
        if self._last_energy is None:
            self._last_energy = energy
            self._last_time = now
            return None

        delta_t = now - self._last_time
        if delta_t <= 0.001:
            return None

        delta_uj = energy - self._last_energy
        if delta_uj < 0 and self._max_range:
            delta_uj += self._max_range

        self._last_energy = energy
        self._last_time = now

        if delta_uj < 0:
            return None

        watts = (delta_uj / 1_000_000.0) / delta_t
        if 0.0 <= watts <= 200.0:
            return round(watts, 1)
        return None


def power_limit_w() -> int | None:
    raw = _read("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw")
    return int(raw) // 1000000 if raw and raw.isdigit() else None


def power_source() -> dict:
    ac_path = "/sys/class/power_supply/ACAD/online"
    ac = bool(_num(ac_path)) if os.path.exists(ac_path) else None

    bat_dir = "/sys/class/power_supply/BAT1"
    pct = _num(f"{bat_dir}/capacity") if os.path.isdir(bat_dir) else None
    status = _read(f"{bat_dir}/status") if os.path.isdir(bat_dir) else None

    return {"on_ac": ac, "percent": pct, "status": status}


def ac_online() -> bool:
    """True if running on AC mains, False if running on DC battery."""
    ps = power_source()
    return bool(ps.get("on_ac", False))


class Telemetry(dict):
    """Hardware telemetry mapping supporting both dict key and attribute access."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'Telemetry' object has no attribute {name!r}")

    def __setattr__(self, name: str, value):
        self[name] = value


def read() -> Telemetry:
    """Read complete hardware telemetry including temperatures, fan RPMs, and power status."""
    s = sensors()
    fans = s.get("fans") or [None, None]
    fan1 = fans[0] if len(fans) > 0 else None
    fan2 = fans[1] if len(fans) > 1 else None
    ps = power_source()
    g = gpu.read(sync=False) if hasattr(gpu, "read") else {}

    return Telemetry({
        "cpu_temp": s.get("cpu_temp"),
        "sys_temp": s.get("sys_temp"),
        "chipset_temp": s.get("sys_temp"),
        "fan1_rpm": fan1,
        "fan2_rpm": fan2,
        "fans": fans,
        "power_status": ps.get("status"),
        "status": ps.get("status"),
        "on_ac": ps.get("on_ac"),
        "ac_online": bool(ps.get("on_ac", False)),
        "battery_percent": ps.get("percent"),
        "percent": ps.get("percent"),
        "battery_rate_w": ps.get("rate_w"),
        "gpu_temp": g.get("temp"),
        "profile": profile(),
        "max_fan": max_fan(),
    })


read_sensors = read


def cpu_frequency_mhz() -> int | None:
    for path in ("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
                 "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq"):
        khz = _num(path)
        if khz:
            return khz // 1000
    return None


# ------------------------------------------------------------- Omen Autopilot

class OmenAutopilot:
    """Fan Curve State Machine ('Omen Autopilot').
    
    Guarantees:
    - Immediate reaction (0ms) upon thermal spikes (>75°C).
    - 5-second thermal dwell buffer (hysteresis) before ramping fans down to eliminate hunting noise.
    - Adaptive profile ladder: low-power < balanced < performance < max.
    """

    LADDER = ("low-power", "balanced", "performance", "max")

    def __init__(self):
        self.enabled = False
        self.current: str | None = None
        self._restore_profile: str | None = None
        self._restore_max_fan: bool | None = None
        self._last_applied_profile: str | None = None

        # Rate of rise tracking
        self._t0: float = 0.0
        self._temp0: float | None = None
        self._t1: float = 0.0
        self._temp1: float | None = None
        self._t2: float = 0.0
        self._temp2: float | None = None

        # 10-Second Max Mode Debounce Counter
        self._sustained_90_ticks: int = 0
        self._rebound_until: float = 0.0

        # Asymmetric hysteresis: 5-second dwell buffer before spin-down
        self._pending_downshift: str | None = None
        self._downshift_deadline: float = 0.0
        self._hold_time_s: float = 5.0

    @staticmethod
    def effective_temp(cpu_temp: float | None, gpu_temp: float | None) -> float | None:
        candidates = [t for t in (cpu_temp, gpu_temp) if t is not None]
        return max(candidates) if candidates else None

    @staticmethod
    def profile_for_temp(temp: float) -> str:
        if temp < 58.0:
            return "low-power"
        if temp < 80.0:
            return "balanced"
        if temp < 90.0:
            return "performance"
        return "max"

    def start(self, now: float) -> str | None:
        if self.enabled:
            return None
        if not profile_path():
            return "No platform profile - is patched hp-wmi loaded?"
        self._restore_profile = profile()
        self._restore_max_fan = max_fan()
        self.current = self._restore_profile or "balanced"
        self._last_applied_profile = self.current

        self._t0, self._temp0 = 0.0, None
        self._t1, self._temp1 = 0.0, None
        self._t2, self._temp2 = 0.0, None
        self._sustained_90_ticks = 0
        self._rebound_until = 0.0
        self._pending_downshift = None
        self._downshift_deadline = 0.0
        self.enabled = True
        return None

    def stop(self) -> str | None:
        if not self.enabled:
            return None
        self.enabled = False
        prev = self.current
        restore_profile = self._restore_profile
        restore_max_fan = self._restore_max_fan
        self._restore_profile = None
        self._restore_max_fan = None
        self.current = None
        self._pending_downshift = None
        self._sustained_90_ticks = 0
        self._rebound_until = 0.0

        errors = []
        if prev == "max":
            err_fan = set_max_fan(False)
            if err_fan:
                errors.append(err_fan)
        elif restore_max_fan is not None and restore_max_fan != max_fan():
            err_fan = set_max_fan(restore_max_fan)
            if err_fan:
                errors.append(err_fan)

        if restore_profile and restore_profile != profile():
            err_prof = set_profile(restore_profile)
            if err_prof:
                errors.append(err_prof)

        return "; ".join(errors) if errors else None

    def update_rate_of_rise(self, temp: float, now: float):
        self._t2, self._temp2 = self._t1, self._temp1
        self._t1, self._temp1 = self._t0, self._temp0
        self._t0, self._temp0 = now, temp

    def check_thermal_spike(self, temp: float, now: float) -> bool:
        if temp < 75.0 or now < self._rebound_until:
            return False
        for t_prev, temp_prev in ((self._t1, self._temp1), (self._t2, self._temp2)):
            if temp_prev is not None:
                dt = self._t0 - t_prev
                if 0.1 <= dt <= 3.0:
                    delta_temp = temp - temp_prev
                    if delta_temp >= 7.0:
                        return True
        return False

    def tick(self, cpu_temp: float | None, gpu_temp: float | None, now: float) -> str | None:
        if not self.enabled:
            return None

        eff_temp = self.effective_temp(cpu_temp, gpu_temp)
        if eff_temp is None:
            return None

        self.update_rate_of_rise(eff_temp, now)
        target = self.profile_for_temp(eff_temp)

        # 10s Debounce for Max mode
        if target == "max":
            self._sustained_90_ticks += 1
            if self._sustained_90_ticks < 10:
                target = "performance"
        else:
            self._sustained_90_ticks = 0

        # Immediate reaction (0ms) upon thermal spikes (>75°C)
        is_spike = self.check_thermal_spike(eff_temp, now)
        current = self.current or "balanced"
        idx_curr = self.LADDER.index(current) if current in self.LADDER else 1

        if is_spike:
            if current == "low-power":
                target = "balanced"
            elif current == "balanced":
                target = "performance"

        idx_target = self.LADDER.index(target) if target in self.LADDER else 1

        # State transition: Immediate step-up, 5s dwell buffer on step-down
        if idx_target > idx_curr:
            self._pending_downshift = None
            self._downshift_deadline = 0.0
            return self._apply(target, now)
        elif idx_target < idx_curr:
            if self._pending_downshift != target:
                self._pending_downshift = target
                self._downshift_deadline = now + self._hold_time_s
                return None
            elif now >= self._downshift_deadline:
                self._pending_downshift = None
                self._downshift_deadline = 0.0
                self._rebound_until = now + 20.0  # 20s thermal rebound grace period
                return self._apply(target, now)
            return None
        else:
            self._pending_downshift = None
            self._downshift_deadline = 0.0
            return None

    def _apply(self, target: str, now: float) -> str | None:
        prev = self.current
        self.current = target
        error = None
        if target != self._last_applied_profile:
            error = set_profile(target)
            if not error:
                self._last_applied_profile = target

        if prev == "max" and target != "max":
            err_fan = set_max_fan(False)
            if err_fan and not error:
                error = err_fan
        return error


# ------------------------------------------------------------- Hardware Worker

class HardwareWorker(QtCore.QThread):
    """Dedicated background telemetry worker running in an isolated QThread.
    
    Zero I/O on the main GUI thread.
    Adaptive Polling:
    - 1000ms polling when UI is visible
    - 5000ms when minimized to Tray
    - 15000ms when running on battery (BAT1/status != "Charging")
    """

    telemetry_updated = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interval_ms: int = 1000
        self._user_mode: str = "active"  # "active" (1000ms) or "tray" (5000ms)
        self._running: bool = True
        self._mutex = QtCore.QMutex()
        self._cond = QtCore.QWaitCondition()
        self._rapl_monitor = RaplMonitor()
        self._cpu_load = monitoring.CpuLoad()

    def set_poll_interval(self, interval_ms: int):
        with QtCore.QMutexLocker(self._mutex):
            self._user_mode = "tray" if interval_ms >= 5000 else "active"
            self._interval_ms = interval_ms
            self._cond.wakeOne()

    def set_ui_state(self, visible: bool):
        with QtCore.QMutexLocker(self._mutex):
            self._user_mode = "active" if visible else "tray"
            self._cond.wakeOne()

    def trigger_poll(self):
        with QtCore.QMutexLocker(self._mutex):
            self._cond.wakeOne()

    def stop(self):
        with QtCore.QMutexLocker(self._mutex):
            self._running = False
            self._cond.wakeOne()
        self.wait(2000)

    def _effective_interval(self, power_src: dict) -> int:
        # 15000ms when running on battery (BAT1/status != "Charging")
        status = (power_src.get("status") or "").strip()
        on_ac = power_src.get("on_ac")
        is_battery = (on_ac is False) or (status and status != "Charging" and on_ac != 1)

        if is_battery:
            return 15000
        if self._user_mode == "tray":
            return 5000
        return 1000

    def run(self):
        while True:
            with QtCore.QMutexLocker(self._mutex):
                if not self._running:
                    break

            try:
                # 1. Sysfs Sensors (dynamic hwmon: fans, cpu temp, chipset temp)
                sensors_data = sensors()

                # 2. NVIDIA GPU Telemetry (pynvml / ctypes or non-blocking async fallback)
                gpu_data = gpu.read(sync=True)

                # 3. RAPL CPU package wattage delta over time
                live_wattage = self._rapl_monitor.sample()
                limit_w = power_limit_w()

                # 4. CPU & RAM utilization
                cpu_load_pct = self._cpu_load.percent()
                ram_data = monitoring.memory()
                cpu_freq = cpu_frequency_mhz()

                # 5. Power supply & active platform profile
                power_src = power_source()
                prof = profile()
                max_f = max_fan()

                snapshot = {
                    "timestamp": time.time(),
                    "sensors": sensors_data,
                    "gpu": gpu_data,
                    "wattage": live_wattage,
                    "power_limit_w": limit_w,
                    "cpu_load": cpu_load_pct,
                    "cpu_freq": cpu_freq,
                    "ram": ram_data,
                    "power_source": power_src,
                    "profile": prof,
                    "max_fan": max_f,
                }

                self.telemetry_updated.emit(snapshot)
                sleep_interval = self._effective_interval(power_src)
            except Exception:
                sleep_interval = 2000

            with QtCore.QMutexLocker(self._mutex):
                if not self._running:
                    break
                self._cond.wait(self._mutex, sleep_interval)


class SleepMonitor(QtCore.QObject):
    """System Sleep/Resume Monitor listening for logind PrepareForSleep signal."""

    prepare_for_sleep = QtCore.Signal(bool)  # True = entering sleep, False = waking
    resumed = QtCore.Signal()  # Emitted when system resumes from sleep

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bus = None
        self._sub_id = None
        self._dbus_receiver = None
        self._connect_dbus()

    def _connect_dbus(self):
        # 1. Try gi.repository.Gio (preferred in modern desktop Linux)
        try:
            from gi.repository import Gio
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            if self._bus:
                self._sub_id = self._bus.signal_subscribe(
                    "org.freedesktop.login1",
                    "org.freedesktop.login1.Manager",
                    "PrepareForSleep",
                    "/org/freedesktop/login1",
                    None,
                    Gio.DBusSignalFlags.NONE,
                    self._on_gio_signal,
                    None
                )
                return
        except Exception:
            pass

        # 2. Try dbus-python fallback
        try:
            import dbus
            sys_bus = dbus.SystemBus()
            self._dbus_receiver = sys_bus.add_signal_receiver(
                self._on_dbus_signal,
                "PrepareForSleep",
                "org.freedesktop.login1.Manager",
                "org.freedesktop.login1",
                "/org/freedesktop/login1"
            )
        except Exception:
            pass

    def _on_gio_signal(self, connection, sender, path, iface, signal_name, params, user_data):
        try:
            sleeping = bool(params.unpack()[0])
            self._handle_sleep_state(sleeping)
        except Exception:
            pass

    def _on_dbus_signal(self, sleeping: bool):
        self._handle_sleep_state(bool(sleeping))

    def _handle_sleep_state(self, sleeping: bool):
        self.prepare_for_sleep.emit(sleeping)
        if not sleeping:
            self.resumed.emit()

    def simulate_sleep_event(self, sleeping: bool):
        """Programmatic simulation for test suites and headless verification."""
        self._handle_sleep_state(sleeping)

    def close(self):
        if self._bus and self._sub_id:
            try:
                self._bus.signal_unsubscribe(self._sub_id)
            except Exception:
                pass
            self._bus = None
            self._sub_id = None

