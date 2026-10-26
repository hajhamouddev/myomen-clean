"""Watching the machine: temperature alerts, and a sensor log.

Both exist because a live number on screen only helps while someone is looking
at it. An alert says something when nobody is, and a log answers the question
the gauges cannot - what was it doing an hour ago, when the game stuttered.

No Qt here either: `omen-sense log` has to run headless from a terminal or a
unit, the same as every other command.
"""

from __future__ import annotations

import csv
import datetime
import os
import pathlib
import shutil
import subprocess

from . import gpu, hw
from .smart import BabySmartGovernor

#: Advisory, not authoritative. The firmware never told us a throttle point, so
#: these are "worth looking at", not "the limit".
DEFAULT_THRESHOLDS = {"cpu_temp": 92, "gpu_temp": 85}

#: How long to stay quiet after firing, so a value hovering on the threshold
#: does not produce a notification a second.
REARM_SECONDS = 300

#: And how far it has to fall before the alert re-arms early.
HYSTERESIS = 5


def data_dir() -> pathlib.Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = pathlib.Path(base) / "omen-sense"
    path.mkdir(parents=True, exist_ok=True)
    return path


# -------------------------------------------------------------------- load

class CpuLoad:
    """CPU use across all cores, as a percentage of the time since last asked.

    From /proc/stat's first line: the share of jiffies that were not idle or
    waiting on I/O. The first call has nothing to compare with and returns
    None, as does a call that comes too soon for any time to have passed.
    """

    def __init__(self, path: str = "/proc/stat"):
        self.path = path
        self._last: tuple[int, int] | None = None

    def _read(self) -> tuple[int, int] | None:
        try:
            with open(self.path) as handle:
                fields = [int(v) for v in handle.readline().split()[1:]]
        except (OSError, ValueError):
            return None
        if len(fields) < 5:
            return None
        return sum(fields), fields[3] + fields[4]      # total, idle + iowait

    def percent(self) -> int | None:
        now = self._read()
        last, self._last = self._last, now
        if now is None or last is None or now[0] <= last[0]:
            return None
        total, idle = now[0] - last[0], now[1] - last[1]
        return round(100 * (total - idle) / total)


def memory(path: str = "/proc/meminfo") -> dict:
    """RAM in use: total minus what the kernel says is available, in GB."""
    values = {}
    try:
        with open(path) as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0])     # kB
    except (OSError, ValueError, IndexError):
        return {}
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    if not total or available is None:
        return {}
    used = total - available
    return {"percent": round(100 * used / total),
            "used_gb": used / 1024 ** 2, "total_gb": total / 1024 ** 2}


# ------------------------------------------------------------------ alerts

def notify(title: str, body: str, urgent: bool = False) -> None:
    """Desktop notification, if this session has one. Never fatal."""
    if not shutil.which("notify-send"):
        return
    try:
        subprocess.run(
            ["notify-send", "--app-name=Omen Sense",
             f"--urgency={'critical' if urgent else 'normal'}",
             "--icon=omen-sense", title, body],
            capture_output=True, timeout=3, check=False)
    except (subprocess.SubprocessError, OSError):
        pass


EMERGENCY_THRESHOLD = 98
EMERGENCY_TICKS = 3
EMERGENCY_HOLD_S = 6.0


class Alerts:
    """Silent autopilot: mutes routine notifications; emergency alert only at >= 98°C sustained."""

    def __init__(self, thresholds: dict | None = None):
        self.enabled = True
        self._emergency_fired = False
        self._sustained_ticks = 0
        self._sustained_start = 0.0

    def check(self, readings: dict, now: float) -> list[str]:
        fired = []
        if not self.enabled:
            return fired

        cpu = readings.get("cpu_temp")
        gpu_t = readings.get("gpu_temp")
        temps = [t for t in (cpu, gpu_t) if t is not None]
        if not temps:
            return fired

        effective_temp = max(temps)

        if effective_temp >= EMERGENCY_THRESHOLD:
            if self._sustained_ticks == 0:
                self._sustained_start = now
            self._sustained_ticks += 1
            duration = now - self._sustained_start

            # Must be continuously for at least 6 seconds and at least 3 consecutive evaluation ticks
            if self._sustained_ticks >= EMERGENCY_TICKS and duration >= (EMERGENCY_HOLD_S - 0.1):
                if not self._emergency_fired:
                    self._emergency_fired = True
                    hw.set_max_fan(True)
                    notify(
                        "Baby Smart — Thermal Emergency",
                        f"Sustained temperature reached {effective_temp}°C. Cooling fans locked to 100%.",
                        urgent=True,
                    )
                    fired.append(f"Thermal emergency: {effective_temp} °C")
        else:
            # Below 98°C: reset emergency tracking if cooled down sufficiently
            if effective_temp < EMERGENCY_THRESHOLD - HYSTERESIS:
                self._emergency_fired = False
            self._sustained_ticks = 0
            self._sustained_start = 0.0

        return fired


# --------------------------------------------------------------------- log

FIELDS = ("time", "cpu_temp", "chipset_temp", "gpu_temp", "limit_w",
          "fan1_rpm", "fan2_rpm", "gpu_fan_pct", "power_mode", "on_ac",
          "battery_pct")


def sample() -> dict:
    """One row. Everything unavailable comes back as None, not zero."""
    data = hw.sensors()
    card = gpu.read()
    source = hw.power_source()
    fans = data.get("fans") or []

    def fan(index):
        return fans[index] if index < len(fans) else None

    return {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "cpu_temp": data.get("cpu_temp"),
        "chipset_temp": data.get("sys_temp"),
        "gpu_temp": card.get("temp"),
        "limit_w": hw.power_limit_w(),
        "fan1_rpm": fan(0),
        "fan2_rpm": fan(1),
        "gpu_fan_pct": card.get("fan_percent"),
        "power_mode": hw.profile(),
        "on_ac": source.get("on_ac"),
        "battery_pct": source.get("percent"),
    }


class Log:
    """Appends samples to a CSV, one file per day."""

    def __init__(self, path: pathlib.Path | None = None):
        self.path = pathlib.Path(path) if path else self.default_path()
        self._handle = None
        self._writer = None

    @staticmethod
    def default_path() -> pathlib.Path:
        stamp = datetime.date.today().isoformat()
        return data_dir() / f"sensors-{stamp}.csv"

    def open(self) -> str | None:
        if self._handle:
            return None
        try:
            fresh = not self.path.exists() or self.path.stat().st_size == 0
            self._handle = open(self.path, "a", newline="")
            self._writer = csv.DictWriter(self._handle, fieldnames=FIELDS)
            if fresh:
                self._writer.writeheader()
        except OSError as error:
            self._handle = None
            return f"Could not open the log: {error}"
        return None

    def write(self, row: dict | None = None) -> None:
        if not self._writer:
            return
        self._writer.writerow(row or sample())
        # Flushed every row: a log that loses its tail in a crash is no use
        # for explaining the crash.
        self._handle.flush()

    def close(self) -> None:
        if self._handle:
            self._handle.close()
        self._handle = None
        self._writer = None

    @property
    def active(self) -> bool:
        return self._handle is not None
