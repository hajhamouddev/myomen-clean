"""4-Zone RGB Lighting Studio for MyOmen (HP OMEN Laptop 15-dh1xxx).

Provides:
- 4-Zone control: Zone 1 (Left), Zone 2 (Center), Zone 3 (Right), Zone 4 (WASD)
- Brightness scalar from 0% to 100% (at 0%, sends power-down command to the LED IC)
- 10 Built-in Presets:
  1. Ice Cold (#A0E7E5)
  2. Cyberpunk Neon (#FF007F / #00F5D4)
  3. Omen Crimson (#FF1A35)
  4. Deep Matrix (#00FF41)
  5. Golden Amber (#FFB703)
  6. Ghost White (#F8F9FA)
  7. Solar Flare (#FB8500)
  8. Ultraviolet (#7209B7)
  9. Breathing Wave (Dynamic thermal-linked pulse)
  10. Stealth Mode (0% brightness, all LEDs off)
- Direct sysfs interface with /sys/devices/platform/hp-wmi/leds or /sys/class/leds
"""

from __future__ import annotations

import glob
import math
import os
from pathlib import Path
import time
from typing import Optional

from . import hw

ZONES = ("left", "center", "right", "wasd")
ZONE_TITLES = {
    "left": "Zone 1 (Left)",
    "center": "Zone 2 (Center)",
    "right": "Zone 3 (Right)",
    "wasd": "Zone 4 (WASD)",
}

LED_BASE = "/sys/class/leds"
LED_PREFIX = "hp::kbd_zoned_backlight-"


def _led_dir(zone: str) -> Path | None:
    standard = Path(LED_BASE) / f"{LED_PREFIX}{zone}"
    if standard.is_dir():
        return standard
    # Check platform device directly
    platform_dir = Path("/sys/devices/platform/hp-wmi/leds") / f"{LED_PREFIX}{zone}"
    if platform_dir.is_dir():
        return platform_dir
    return None


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    h = hex_code.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (255, 255, 255)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


# 10 Built-in Presets
PRESETS: dict[str, dict] = {
    "ice_cold": {
        "title": "Ice Cold",
        "hex": "#A0E7E5",
        "description": "Crisp Arctic glacial frost with diamond white WASD",
        "zones": {
            "left": (160, 231, 229),
            "center": (160, 231, 229),
            "right": (160, 231, 229),
            "wasd": (255, 255, 255),
        },
    },
    "cyberpunk_neon": {
        "title": "Cyberpunk Neon",
        "hex": "#FF007F",
        "description": "High-contrast synthwave split between Neon Pink and Aqua Cyan",
        "zones": {
            "left": (255, 0, 127),
            "center": (255, 0, 127),
            "right": (0, 245, 212),
            "wasd": (0, 245, 212),
        },
    },
    "omen_crimson": {
        "title": "Omen Crimson",
        "hex": "#FF1A35",
        "description": "Signature HP OMEN battle-ready crimson red",
        "zones": {
            "left": (255, 26, 53),
            "center": (220, 0, 30),
            "right": (180, 0, 20),
            "wasd": (255, 50, 70),
        },
    },
    "deep_matrix": {
        "title": "Deep Matrix",
        "hex": "#00FF41",
        "description": "Phosphor hacker green glowing across all keys",
        "zones": {
            "left": (0, 255, 65),
            "center": (0, 255, 65),
            "right": (0, 255, 65),
            "wasd": (50, 255, 120),
        },
    },
    "golden_amber": {
        "title": "Golden Amber",
        "hex": "#FFB703",
        "description": "Warm tungsten amber glow for late night coding",
        "zones": {
            "left": (255, 183, 3),
            "center": (255, 183, 3),
            "right": (255, 183, 3),
            "wasd": (255, 215, 0),
        },
    },
    "ghost_white": {
        "title": "Ghost White",
        "hex": "#F8F9FA",
        "description": "Pure clean daylight white illumination",
        "zones": {
            "left": (248, 249, 250),
            "center": (248, 249, 250),
            "right": (248, 249, 250),
            "wasd": (255, 255, 255),
        },
    },
    "solar_flare": {
        "title": "Solar Flare",
        "hex": "#FB8500",
        "description": "Radiant molten solar orange and hyper-gold",
        "zones": {
            "left": (251, 133, 0),
            "center": (251, 133, 0),
            "right": (251, 133, 0),
            "wasd": (255, 180, 50),
        },
    },
    "ultraviolet": {
        "title": "Ultraviolet",
        "hex": "#7209B7",
        "description": "Deep electric ultraviolet neon aura",
        "zones": {
            "left": (114, 9, 183),
            "center": (114, 9, 183),
            "right": (114, 9, 183),
            "wasd": (180, 50, 255),
        },
    },
    "breathing_wave": {
        "title": "Breathing Wave",
        "hex": "#00B4D8",
        "description": "Dynamic thermal-linked breathing wave pulsing with system load",
        "zones": {
            "left": (0, 180, 216),
            "center": (0, 180, 216),
            "right": (0, 180, 216),
            "wasd": (255, 26, 53),
        },
        "dynamic": True,
    },
    "stealth_mode": {
        "title": "Stealth Mode",
        "hex": "#000000",
        "description": "Total stealth: 0% brightness, all LEDs and controller powered down",
        "zones": {
            "left": (0, 0, 0),
            "center": (0, 0, 0),
            "right": (0, 0, 0),
            "wasd": (0, 0, 0),
        },
        "stealth": True,
    },
}


def is_available() -> bool:
    return any(_led_dir(z) is not None for z in ZONES)


def set_zone_color(zone: str, r: int, g: int, b: int) -> str | None:
    p = _led_dir(zone)
    if not p:
        return f"LED zone node for {zone} not found."
    target = p / "multi_intensity"
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    try:
        target.write_text(f"{r} {g} {b}")
        return None
    except PermissionError:
        return f"Permission denied writing {target}. Verify 99-myomen.rules."
    except OSError as err:
        return f"I/O error writing {target}: {err}"


def get_zone_color(zone: str) -> tuple[int, int, int]:
    p = _led_dir(zone)
    if not p:
        return (0, 0, 0)
    target = p / "multi_intensity"
    try:
        raw = target.read_text().strip().split()
        if len(raw) >= 3:
            return (int(raw[0]), int(raw[1]), int(raw[2]))
    except (OSError, ValueError):
        pass
    return (0, 0, 0)


def set_zone_brightness(zone: str, percent: int) -> str | None:
    p = _led_dir(zone)
    if not p:
        return f"LED zone node for {zone} not found."
    target = p / "brightness"
    percent = max(0, min(100, int(percent)))
    level = int(round(percent * 255.0 / 100.0))
    try:
        target.write_text(str(level))
        return None
    except PermissionError:
        return f"Permission denied writing {target}. Verify 99-myomen.rules."
    except OSError as err:
        return f"I/O error writing {target}: {err}"


def set_brightness(percent: int) -> str | None:
    """Set brightness scalar 0-100%. At 0%, sends power-down command to the LED IC."""
    percent = max(0, min(100, int(percent)))
    errors = []
    for zone in ZONES:
        err = set_zone_brightness(zone, percent)
        if err:
            errors.append(err)

    if percent == 0:
        # At 0%, send power-down command to the LED IC to conserve energy
        for zone in ZONES:
            err_c = set_zone_color(zone, 0, 0, 0)
            if err_c:
                errors.append(err_c)
    return "; ".join(errors) if errors else None


def get_brightness() -> int:
    values = []
    for zone in ZONES:
        p = _led_dir(zone)
        if p:
            target = p / "brightness"
            try:
                val = int(target.read_text().strip())
                values.append(int(round(val * 100.0 / 255.0)))
            except (OSError, ValueError):
                pass
    return max(values) if values else 100


def apply_preset(preset_key: str, brightness: int = 100) -> str | None:
    preset = PRESETS.get(preset_key)
    if not preset:
        return f"Unknown preset: {preset_key}"

    if preset.get("stealth"):
        return set_brightness(0)

    errors = []
    zones = preset.get("zones", {})
    for zone, rgb in zones.items():
        err = set_zone_color(zone, *rgb)
        if err:
            errors.append(err)

    err_b = set_brightness(brightness)
    if err_b:
        errors.append(err_b)

    return "; ".join(errors) if errors else None


class BreathingWaveGenerator:
    """Thermal-linked dynamic breathing wave animation generator."""

    def __init__(self):
        self._start_time = time.monotonic()

    def frame(self, cpu_temp: float | None = None, gpu_temp: float | None = None) -> dict[str, tuple[int, int, int]]:
        t = time.monotonic() - self._start_time
        max_temp = max(t for t in (cpu_temp, gpu_temp) if t is not None) if (cpu_temp or gpu_temp) else 50.0

        # Frequency scales with temperature: 0.5 Hz idle to 2.0 Hz hot
        speed_factor = 0.5 + min(1.5, max(0.0, (max_temp - 50.0) / 40.0))
        phase = t * speed_factor * 2 * math.pi

        # Base hue shifts from Cyan (#00B4D8) at cool to Crimson (#FF1A35) at high load
        temp_ratio = min(1.0, max(0.0, (max_temp - 45.0) / 45.0))
        r_base = int(0 + temp_ratio * 255)
        g_base = int(180 * (1.0 - temp_ratio * 0.8))
        b_base = int(216 * (1.0 - temp_ratio * 0.7))

        frames = {}
        for idx, z in enumerate(ZONES):
            z_phase = phase + (idx * math.pi / 2.0)
            intensity = 0.35 + 0.65 * ((math.sin(z_phase) + 1.0) / 2.0)
            frames[z] = (
                int(round(r_base * intensity)),
                int(round(g_base * intensity)),
                int(round(b_base * intensity)),
            )
        return frames
