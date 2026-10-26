"""Hardware access for omen-sense.

Everything here is plain sysfs against the patched hp-wmi driver
(driver/INSTALL.md). No daemon, no D-Bus, no root:
60-omen-sense.rules grants the plugdev group write access to the handful of
attributes that need it.

Every write this module can make, and why it is allowed under the project rule
that nothing invented reaches firmware (docs/findings-8746.md):

- platform_profile low-power / balanced / performance
    -> 0x1A payloads {FF,02} {FF,00} {FF,01}, all logged from OMEN Gaming Hub
       on this machine.
- keyboard zone colour / brightness
    -> 0x20009 type 0x03 colour table (byte 0 = 3, RGB from byte 25) and type
       0x05 backlight-on 0xE4, both logged from OMEN Gaming Hub.
- max fan (pwm1_enable = 0 on, 2 off)
    -> 0x27 {1} and {0}, both logged from OMEN Gaming Hub on this machine:
       see MAX_FAN_OBSERVED. The driver sends the int as 4 bytes, HP one;
       GM27 reads only byte 0, so they are the same to the firmware.

Readings are genuine measurements: fan RPM from query 0x2D (cross-checked
against EC 0x11 on this machine), CPU temperature from coretemp, chipset
temperature from the PCH sensor. The keyboard is the exception - the driver
cannot read colours back from the EC's point of view, so what is shown is the
driver's record, and the firmware resets it at every boot.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
import time
from typing import Optional

BOARD = "8746"

FAN_LABELS = ("Fan 1", "Fan 2")

#: Which physical fan is which cannot be told from their speeds. Under a
#: GPU-only load (2026-09-28: GPU 95 %, CPU 5 %) the embedded controller moved
#: both together, Fan 2 always 200 rpm above Fan 1 (1800/2000 -> 3100/3300), and
#: only once the CPU passed ~80 °C: the heat pipes are shared, so the GPU heats
#: the CPU too. So they keep neutral names.
FAN_NOTE = ("The embedded controller runs both fans together, Fan 2 about "
            "200 rpm faster, so which is CPU-side and which GPU-side does not "
            "show in their speeds.")

#: 0x27 {1} was captured from HP's own software on this laptop on 2026-09-28:
#: HPOMENBG_20260928.log, "SetMaxFan(), mode = On" then "inputData=1," at
#: 15:22:55, 15:23:09 and 15:23:48, and "mode = Off" then "inputData=0,"
#: throughout. GM27 (DSDT line 63206) turns byte 0 == 1 into the EC's max-fan
#: command 0x45 0x49 and anything else into 0x45 0x4A, and raises no event.
#: Kept as a switch so a board without that evidence could turn it off again.
MAX_FAN_OBSERVED = True

# ----------------------------------------------------------------- keyboard

#: Physical order, left to right. The sysfs names are upstream's
#: (kbd-rgb-v11.patch): zone index 0 right, 1 center, 2 left, 3 wasd. All four
#: zones were confirmed by eye on this machine (2026-09-28).
ZONES = ("left", "wasd", "center", "right")
ZONE_TITLES = {
    "left": "Left",
    "wasd": "WASD",
    "center": "Centre",
    "right": "Right + numpad",
}
LED_PREFIX = "/sys/class/leds/hp::kbd_zoned_backlight-"
LED_MAX = 255

# ------------------------------------------------------------------ profiles

PROFILE_ORDER = ("low-power", "balanced", "performance", "max")
PROFILE_TITLES = {
    "low-power": "Quiet",
    "balanced": "Balanced",
    "performance": "Performance",
    "max": "Max",
}
#: What the firmware does for each, from its own handler (GM1A, DSL line
#: 62987) - not HP's marketing text.
PROFILE_NOTES = {
    "low-power": "OMEN Cool · GPU configurable TGP off",
    "balanced": "OMEN Default · GPU configurable TGP off",
    "performance": "OMEN Performance · GPU configurable TGP on · needs the charger",
    "max": "OMEN Max / Overdrive · Max Fans · Unlocked CPU/GPU Power · needs the charger",
}


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
                "60-omen-sense.rules installed, and are you in plugdev?")
    except OSError as err:
        return f"{os.path.basename(path)}: {err.strerror or err}"


def _num(path: str):
    raw = _read(path)
    return int(raw) if raw and raw.lstrip("-").isdigit() else None


def find_hwmon_by_name(target_name: str) -> Optional[Path]:
    """Scan /sys/class/hwmon/hwmon*/name dynamically for target_name."""
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
    """Find a hwmon by name; the hwmonN number changes with probe order."""
    p = find_hwmon_by_name(name)
    return str(p) if p is not None else None


def board() -> str | None:
    return _read("/sys/class/dmi/id/board_name")


def hwmon_path() -> str | None:
    return _hwmon("hp")


def driver_present() -> bool:
    return hwmon_path() is not None


def driver_problems() -> list[str]:
    """What is missing, in words - so a stock hp-wmi is recognised as such.

    Stock hp-wmi on this board loads fine and looks alive, but registers no
    platform profile and reports both fans at 0 RPM. Without saying so, the
    window would show a dead Power page and two stopped fans.
    """
    problems = []
    if board() != BOARD:
        problems.append(f"This is board {board() or 'unknown'}, not {BOARD}; "
                        "omen-sense is built and verified for the 8746 only.")
    if not driver_present():
        problems.append("hp-wmi is not loaded.")
        return problems
    if not profile_path():
        problems.append("No platform profile: this looks like the stock hp-wmi. "
                        "Install the patched one (driver/INSTALL.md).")
    if not zones_present():
        problems.append("No keyboard zones: kbd-rgb-v11.patch is not in the "
                        "loaded hp-wmi.")
    return problems


def zones_present() -> bool:
    return any(os.path.isdir(LED_PREFIX + zone) for zone in ZONES)


# ------------------------------------------------------------- monitoring

def sensors() -> dict:
    """Live readings. Missing values are None, never zero.
    
    Dynamically scans hwmon for hp and coretemp without hardcoded paths:
    - fan1_input and fan2_input from discovered hp hwmon path.
    - temp1_input from discovered coretemp hwmon path for CPU Package Temperature.
    - temp1_input from pch_cometlake for chipset temperature.
    """
    hp_node = find_hwmon_by_name("hp")
    fans = [None, None]
    if hp_node:
        fans = [_num(str(hp_node / f"fan{i}_input")) for i in (1, 2)]

    cpu = None
    core_node = find_hwmon_by_name("coretemp")
    if core_node:
        # temp1_input is "Package id 0" on coretemp
        milli = _num(str(core_node / "temp1_input"))
        cpu = milli // 1000 if milli is not None else None

    chipset = None
    pch_node = find_hwmon_by_name("pch_cometlake")
    if pch_node:
        milli = _num(str(pch_node / "temp1_input"))
        chipset = milli // 1000 if milli is not None else None

    return {"cpu_temp": cpu, "sys_temp": chipset, "fans": fans}


def rapl_energy_uj() -> int | None:
    """Read raw energy counter from intel-rapl:0/energy_uj if accessible."""
    return _num("/sys/class/powercap/intel-rapl:0/energy_uj")


def rapl_max_range_uj() -> int | None:
    """Read max counter wrap-around limit from intel-rapl:0/max_energy_range_uj."""
    return _num("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")


class RaplMonitor:
    """Computes real-time package wattage from successive intel-rapl:0/energy_uj differential readings."""

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
            # Counter rollover
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
    """The CPU long-term power limit."""
    raw = _read("/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw")
    return int(raw) // 1000000 if raw and raw.isdigit() else None


def set_power_limit_w(watts: int) -> str | None:
    """Set the CPU PL1 power limit via RAPL constraint 0."""
    path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
    if not os.path.exists(path):
        return "RAPL interface not found"
    return _write(path, str(int(watts) * 1000000))


def cpu_frequency_mhz() -> int | None:
    """Current average CPU frequency across active cores in MHz."""
    freqs = []
    for path in glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"):
        val = _num(path)
        if val:
            freqs.append(val // 1000)
    if freqs:
        return sum(freqs) // len(freqs)
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("cpu MHz"):
                    freqs.append(int(float(line.split(":")[1].strip())))
        if freqs:
            return sum(freqs) // len(freqs)
    except Exception:
        pass
    return None


def power_source() -> dict:
    """Charger and battery, which decide whether Performance takes effect."""
    online = None
    for supply in glob.glob("/sys/class/power_supply/*"):
        if _read(os.path.join(supply, "type")) == "Mains":
            online = _read(os.path.join(supply, "online")) == "1"
            break
    battery = {}
    for supply in glob.glob("/sys/class/power_supply/BAT*"):
        capacity = _num(os.path.join(supply, "capacity"))
        status = _read(os.path.join(supply, "status"))
        power_uw = _num(os.path.join(supply, "power_now"))
        current_ua = _num(os.path.join(supply, "current_now"))
        voltage_uv = _num(os.path.join(supply, "voltage_now"))
        rate_w = None
        if power_uw is not None:
            rate_w = round(power_uw / 1000000, 1)
        elif current_ua is not None and voltage_uv is not None:
            rate_w = round((current_ua * voltage_uv) / 1000000000000, 1)
        battery = {
            "percent": capacity,
            "status": status,
            "rate_w": rate_w,
        }
        break
    return {"on_ac": online, **battery}


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
    g = gpu_read() if "gpu_read" in globals() else {}

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


def gpu_read(sync: bool = False) -> dict:
    """Read GPU telemetry using non-blocking, cached, D3cold-safe sysfs & worker."""
    from . import gpu
    return gpu.read(sync=sync)


def __getattr__(name: str):
    if name == "BabySmartGovernor":
        from .smart import BabySmartGovernor
        return BabySmartGovernor
    if name == "OmenAutopilot":
        from .hardware import OmenAutopilot
        return OmenAutopilot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")



# ------------------------------------------------------------------ fans

def max_fan() -> bool | None:
    """True if max fan is on. pwm1_enable: 0 = max, 2 = firmware auto."""
    base = hwmon_path()
    raw = _read(os.path.join(base, "pwm1_enable")) if base else None
    return None if raw is None else raw == "0"


def set_max_fan(enabled: bool) -> str | None:
    base = hwmon_path()
    if not base:
        return "hp-wmi is not loaded"
    if enabled and not MAX_FAN_OBSERVED:
        return ("Max fan is not enabled yet: HP's software has not been seen "
                "sending it on this machine (see hw.MAX_FAN_OBSERVED).")
    return _write(os.path.join(base, "pwm1_enable"), "0" if enabled else "2")


# --------------------------------------------------------------- profile

def profile_path() -> str | None:
    """The class device of hp-wmi, falling back to the legacy global file."""
    for candidate in glob.glob("/sys/class/platform-profile/platform-profile-*"):
        if _read(os.path.join(candidate, "name")) == "hp-wmi":
            return os.path.join(candidate, "profile")
    legacy = "/sys/firmware/acpi/platform_profile"
    return legacy if os.path.exists(legacy) else None


def profile() -> str | None:
    path = profile_path()
    raw = _read(path) if path else None
    if raw == "performance" and max_fan() is True:
        return "max"
    return raw


def profile_choices() -> list:
    path = profile_path()
    if not path:
        return []
    choices = os.path.join(os.path.dirname(path), "choices")
    if not os.path.exists(choices):
        choices = path + "_choices"
    raw = _read(choices)
    offered = raw.split() if raw else []
    choices_list = [p for p in ("low-power", "balanced", "performance") if p in offered] + \
                   [p for p in offered if p not in PROFILE_ORDER]
    if "performance" in choices_list and MAX_FAN_OBSERVED:
        choices_list.append("max")
    return choices_list


def set_profile(name: str) -> str | None:
    path = profile_path()
    if not path:
        return "No platform profile - is the patched hp-wmi loaded?"
    if name == "quiet":
        name = "low-power"
    if name not in profile_choices() and name != "max":
        return f"Unknown mode {name!r}."

    if name == "max":
        err = _write(path, "performance")
        if err:
            return err
        err_fan = set_max_fan(True)
        if err_fan:
            return err_fan
        set_power_limit_w(65)
        return None

    # Leaving max mode: restore auto fans and default PL1
    if max_fan():
        set_max_fan(False)
    curr_limit = power_limit_w()
    if curr_limit and curr_limit > 45:
        set_power_limit_w(45)

    return _write(path, name)


set_platform_profile = set_profile


# -------------------------------------------------------------- keyboard

def _led(zone: str) -> str:
    return LED_PREFIX + zone


def zone_colour(zone: str) -> tuple:
    raw = _read(f"{_led(zone)}/multi_intensity")
    parts = raw.split() if raw else []
    return tuple(int(p) for p in parts[:3]) if len(parts) >= 3 else (0, 0, 0)


def backlight_off_by_key() -> bool:
    """Whether the keyboard's backlight key has turned the backlight off.

    Where the firmware reports the key, v11 records it in
    brightness_hw_changed: 0 after the key turned the backlight off. On board
    8746 it never does - the firmware toggles the backlight by itself, and
    nothing reached the driver in three minutes of pressing (2026-09-28) - so
    this is always False here. What keeps the key working on 8746 is the
    driver: patch-8746.py edit 6 no longer switches the backlight on for a
    colour write, only when a zone goes from dark to lit. This check stays for
    boards whose firmware does report the key.
    """
    return any(_num(f"{_led(zone)}/brightness_hw_changed") == 0
               for zone in ZONES)


def zone_brightness(zone: str) -> int:
    """0-255. 0 means the zone is written black; see set_zone_brightness."""
    value = _num(f"{_led(zone)}/brightness")
    return value if value is not None else 0


def set_zone_colour(zone: str, rgb: tuple) -> str | None:
    if zone not in ZONE_TITLES:
        return f"Unknown zone {zone!r}."
    rgb = tuple(max(0, min(255, int(v))) for v in rgb)
    return _write(f"{_led(zone)}/multi_intensity", "%d %d %d" % rgb)


def set_zone_brightness(zone: str, level: int) -> str | None:
    """Brightness scales the colour; 0 writes black, it does not switch off.

    The v11 driver has no real off: HP's off payload (type 0x05, 0x64) is
    observed on this machine but not wired up yet, so the backlight key stays
    the way to turn the whole keyboard dark.
    """
    if zone not in ZONE_TITLES:
        return f"Unknown zone {zone!r}."
    return _write(f"{_led(zone)}/brightness", str(max(0, min(LED_MAX, int(level)))))


# -------------------------------------------------------------- OMEN key shortcut

def is_omen_key_bound() -> bool:
    """Check whether the hardware OMEN keyboard diamond key is bound in GNOME."""
    from . import state
    return state.omen_key_enabled()


def set_omen_key_binding(enabled: bool) -> bool:
    """Bind or unbind the physical OMEN keyboard key to MyOmen Hub."""
    from . import state
    return state.set_omen_key(enabled) is None

