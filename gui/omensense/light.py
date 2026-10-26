"""OMEN 4-Zone RGB Lighting Controller and Manager (Compatibility Facade for rgb.py and effects.py)."""

from __future__ import annotations

from . import effects, hw, rgb, state
from .rgb import (
    PRESETS,
    ZONES,
    ZONE_TITLES,
    BreathingWaveGenerator,
    apply_preset,
    get_brightness,
    get_zone_color,
    hex_to_rgb,
    rgb_to_hex,
    set_brightness,
    set_zone_brightness,
    set_zone_color,
)

__all__ = [
    "PRESETS",
    "ZONES",
    "ZONE_TITLES",
    "BreathingWaveGenerator",
    "apply_preset",
    "get_all_presets",
    "get_brightness",
    "get_preset_by_id",
    "get_zone_color",
    "hex_to_rgb",
    "restore_lighting",
    "rgb_to_hex",
    "set_brightness",
    "set_zone_brightness",
    "set_zone_color",
    "toggle_backlight",
]


def get_all_presets() -> dict[str, dict]:
    """Get all available built-in 4-zone lighting presets."""
    return rgb.PRESETS


def get_preset_by_id(preset_id: str) -> dict | None:
    """Get preset definition by key."""
    return rgb.PRESETS.get(preset_id)


def toggle_backlight() -> bool:
    """Toggle keyboard backlight between on and off."""
    if state.keyboard_is_off():
        state.keyboard_on()
        return True
    state.keyboard_off()
    return False


def restore_lighting() -> list[str]:
    """Restore saved lighting state from disk."""
    return state.last_lighting()
