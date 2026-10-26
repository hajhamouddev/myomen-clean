"""Centralized reboot persistence manager for MyOmen.

Persists active governor autopilot (Omen Autopilot), theme accents,
active profile names, user profile in config.json, and startup toggles into ~/.config/myomen/state.json.
Synchronously loaded on app launch to restore the complete operating state across reboots.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import tempfile

DEFAULT_STATE = {
    "version": 1,
    "governor": {
        "baby_smart": False,
        "smart": False,
    },
    "theme": {
        "accent_color": "#00d2ff",
        "theme_mode": "manual",
        "layout_name": "nord-glacier",
    },
    "active_profile": "myBaby",
    "startup_toggles": {
        "apply_at_login": False,
        "start_with_computer": False,
        "omen_key": False,
    },
}


def config_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = pathlib.Path(base) / "myomen"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> pathlib.Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    target = config_file()
    if not target.exists():
        legacy = pathlib.Path(target.parent.parent) / "omensense" / "config.json"
        if legacy.exists():
            target = legacy
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(data: dict) -> bool:
    target = config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle, temp_path = tempfile.mkstemp(
            dir=str(target.parent), prefix=".cfg-", suffix=".tmp"
        )
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, target)
        return True
    except OSError:
        return False


def load_user_profile() -> dict:
    cfg = load_config()
    return {
        "user_name": cfg.get("user_name", ""),
        "user_title": cfg.get("user_title", ""),
        "full_name_and_title": cfg.get("full_name_and_title", ""),
    }


def save_user_profile(full_name_and_title: str) -> bool:
    cfg = load_config()
    raw = full_name_and_title.strip()
    if " - " in raw:
        name, role = raw.split(" - ", 1)
    elif " | " in raw:
        name, role = raw.split(" | ", 1)
    elif "\n" in raw:
        name, role = raw.split("\n", 1)
    elif " — " in raw:
        name, role = raw.split(" — ", 1)
    elif "," in raw:
        name, role = raw.split(",", 1)
    else:
        name, role = raw, ""
    cfg["full_name_and_title"] = raw
    cfg["user_name"] = name.strip()
    cfg["user_title"] = role.strip()
    return save_config(cfg)


def state_file() -> pathlib.Path:
    return config_dir() / "state.json"


def load_state() -> dict:
    """Synchronously load persisted state from state.json with fail-safe defaults."""
    target = state_file()
    if not target.exists():
        legacy1 = pathlib.Path(target.parent.parent) / "omensense" / "state.json"
        legacy2 = pathlib.Path(target.parent.parent) / "omen-sense" / "state.json"
        if legacy1.exists():
            target = legacy1
        elif legacy2.exists():
            target = legacy2

    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                merged = copy.deepcopy(DEFAULT_STATE)
                for k, v in data.items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                return merged
    except (OSError, json.JSONDecodeError):
        pass

    return copy.deepcopy(DEFAULT_STATE)


def save_state(document: dict) -> bool:
    """Atomically write full state dictionary to ~/.config/omensense/state.json."""
    target = state_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle, temp_path = tempfile.mkstemp(
            dir=str(target.parent), prefix=".state-", suffix=".tmp"
        )
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(document, out, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, target)
        return True
    except OSError:
        return False


def save_governor(baby_smart: bool, smart: bool = False) -> bool:
    """Persist active governor modes."""
    state = load_state()
    state.setdefault("governor", {})
    state["governor"]["baby_smart"] = bool(baby_smart)
    state["governor"]["smart"] = bool(smart)
    return save_state(state)


def save_theme(accent_color: str, layout_name: str | None = None, theme_mode: str = "manual") -> bool:
    """Persist active accent color and keyboard layout name."""
    state = load_state()
    state.setdefault("theme", {})
    state["theme"]["accent_color"] = accent_color
    state["theme"]["theme_mode"] = theme_mode
    if layout_name:
        state["theme"]["layout_name"] = layout_name
    return save_state(state)


def save_active_profile(name: str | None) -> bool:
    """Persist active profile selection."""
    state = load_state()
    state["active_profile"] = name
    return save_state(state)


def active_profile() -> str:
    """Return currently persisted active profile name or fallback to 'balanced'."""
    state = load_state()
    return state.get("active_profile") or "balanced"


def save_startup_toggles(apply_at_login: bool, start_with_computer: bool, omen_key: bool) -> bool:
    """Persist states of the 3 startup toggle pills."""
    state = load_state()
    state["startup_toggles"] = {
        "apply_at_login": bool(apply_at_login),
        "start_with_computer": bool(start_with_computer),
        "omen_key": bool(omen_key),
    }
    return save_state(state)


def update_startup_toggle(key: str, value: bool) -> bool:
    state = load_state()
    state.setdefault("startup_toggles", {})
    state["startup_toggles"][key] = bool(value)
    return save_state(state)
