"""Named profiles, and putting the machine's settings back after a boot.

A profile is everything this application can set - power mode, max fan, every
keyboard zone's colour and brightness, and the audio preset - under one name.

Separately from profiles, the last keyboard colours are always remembered.
The firmware resets the four zones to a fixed red / green / blue / white at
every boot (seen in the EC dump on 2026-09-26, and again after installing the
driver), and the driver starts from whatever the EC holds. So `omen-sense
apply`, run by a systemd user unit at login, re-applies the startup profile if
one is set, and otherwise just the last colours. That is why this module has no
Qt import: it runs with no display attached.

Storage is one JSON file under XDG_CONFIG_HOME, written atomically. A partial
write here would lose every profile at once, and the failure would only show up
at the next login.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

from . import audio, hw

#: Bump when the on-disk shape changes in a way older files cannot satisfy.
SCHEMA = 1


def config_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = pathlib.Path(base) / "omen-sense"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> pathlib.Path:
    return config_dir() / "profiles.json"


# ----------------------------------------------------------------- storage

def load() -> dict:
    """Everything on disk, or an empty document if there is nothing usable."""
    empty = {"version": SCHEMA, "startup": None, "profiles": {}}
    try:
        with open(config_file()) as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(document, dict) or "profiles" not in document:
        return empty
    document.setdefault("version", SCHEMA)
    document.setdefault("startup", None)
    if not isinstance(document.get("profiles"), dict):
        document["profiles"] = {}
    return document


def save(document: dict) -> str | None:
    """Write atomically. Returns None, or a message worth showing."""
    document["version"] = SCHEMA
    target = config_file()
    try:
        handle, temporary = tempfile.mkstemp(dir=str(target.parent),
                                             prefix=".profiles-", suffix=".tmp")
        with os.fdopen(handle, "w") as out:
            json.dump(document, out, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, target)
    except OSError as error:
        return f"Could not save profiles: {error}"
    return None


# ------------------------------------------------------------- the machine

def capture_lighting() -> dict:
    return {zone: {"rgb": list(hw.zone_colour(zone)),
                   "brightness": hw.zone_brightness(zone)}
            for zone in hw.ZONES}


def capture() -> dict:
    """The machine's current settings, as a profile."""
    return {
        "power": hw.profile(),
        "max_fan": bool(hw.max_fan()),
        "zones": capture_lighting(),
        "audio": audio.PresetEngine().current,
    }


def apply_lighting(zones: dict) -> list[str]:
    """Colour before brightness, so a dark zone does not flash its old colour."""
    problems = []
    for zone, wanted in (zones or {}).items():
        if zone not in hw.ZONE_TITLES:
            continue
        rgb = wanted.get("rgb")
        if rgb and len(rgb) == 3:
            error = hw.set_zone_colour(zone, tuple(int(v) for v in rgb))
            if error:
                problems.append(error)
        brightness = wanted.get("brightness")
        if brightness is not None:
            error = hw.set_zone_brightness(zone, int(brightness))
            if error:
                problems.append(error)
    return problems


def apply(profile: dict) -> list[str]:
    """Put a profile onto the machine. Returns whatever refused."""
    problems: list[str] = []

    def note(error):
        if error:
            problems.append(error)

    power = profile.get("power")
    if power and power in hw.profile_choices():
        note(hw.set_profile(power))

    if "max_fan" in profile:
        wanted = bool(profile["max_fan"])
        # Only ever turn it off unless the payload has been observed; a profile
        # saved with max fan on must not smuggle an unobserved write in.
        if wanted and hw.MAX_FAN_OBSERVED:
            note(hw.set_max_fan(True))
        elif hw.max_fan():
            note(hw.set_max_fan(False))

    problems += apply_lighting(profile.get("zones") or {})

    wanted_audio = profile.get("audio")
    engine = audio.PresetEngine()
    if wanted_audio:
        note(engine.apply(wanted_audio))
    elif engine.current:
        engine.stop()

    return problems


# ------------------------------------------------------ last-used lighting

def remember_lighting(zones: dict | None = None) -> str | None:
    """Keep the current keyboard colours, to restore after the next boot."""
    document = load()
    document["lighting"] = zones if zones is not None else capture_lighting()
    return save(document)


def last_lighting() -> dict | None:
    zones = load().get("lighting")
    return zones if isinstance(zones, dict) and zones else None


# ------------------------------------------------------ keyboard on / off

def keyboard_off() -> list[str]:
    """Switch the keyboard backlight off, keeping the colours to come back to.

    Brightness 0 on every zone is what the patched driver turns into HP's real
    backlight-off command (patch-8746.py edit 6). The colours stay in the
    driver's record, and the levels before are kept here for keyboard_on().
    The off state is remembered like any colour, so it survives a login.
    """
    before = capture_lighting()
    problems = []
    if any(zone["brightness"] for zone in before.values()):
        document = load()
        document["lighting_before_off"] = before
        error = save(document)
        if error:
            problems.append(error)
    for zone in hw.ZONES:
        error = hw.set_zone_brightness(zone, 0)
        if error:
            problems.append(error)
    error = remember_lighting()
    if error:
        problems.append(error)
    return problems


def keyboard_on() -> list[str]:
    """Light the keyboard again with what keyboard_off() kept, or full white."""
    before = load().get("lighting_before_off")
    if isinstance(before, dict) and any(
            isinstance(z, dict) and z.get("brightness") for z in before.values()):
        problems = apply_lighting(before)
    else:
        problems = [error for zone in hw.ZONES
                    if (error := hw.set_zone_brightness(zone, hw.LED_MAX))]
    error = remember_lighting()
    if error:
        problems.append(error)
    return problems


def keyboard_is_off() -> bool:
    return all(hw.zone_brightness(zone) == 0 for zone in hw.ZONES)


# ------------------------------------------------------------- preferences

#: Small app-level choices, kept in the same document as the profiles so there
#: is one file to back up and one file to lose.
DEFAULT_SETTINGS = {
    "autostart": False,
    "close_to_tray": True,
    "smart": None,
    #: The lighting effect running when the window last changed it - an
    #: animation or "temperature" - so it starts again with the window.
    "effect": None,
}


def settings() -> dict:
    stored = load().get("settings")
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    return merged


def set_setting(key: str, value) -> str | None:
    if key not in DEFAULT_SETTINGS:
        return f"Unknown setting {key!r}."
    document = load()
    document.setdefault("settings", {})[key] = value
    return save(document)


# ------------------------------------------------------------- autostart

AUTOSTART_ENTRY = """[Desktop Entry]
Type=Application
Name=MyOmen
Comment=Power mode, fan and keyboard lighting control for MyOmen
Exec={command}
Icon=myomen
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def autostart_file() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = pathlib.Path(base) / "autostart"
    return path / "myomen.desktop"


def autostart_command() -> str:
    return "myomen --tray"


def autostart_enabled() -> bool:
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-enabled", "myomen.service"],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and "enabled" in res.stdout:
            return True
    except Exception:
        pass
    return bool(settings().get("autostart", False))


def set_autostart(enabled: bool) -> str | None:
    # Purge any legacy autostart desktop entries so systemd --user remains single source of truth
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    autostart_dir = pathlib.Path(base) / "autostart"
    for name in ("omen-sense.desktop", "myomen.desktop"):
        p = autostart_dir / name
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    cmd = ["systemctl", "--user", "enable" if enabled else "disable", "myomen.service"]
    try:
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except Exception:
        pass
    return set_setting("autostart", enabled)


# -------------------------------------------------------------- OMEN key

#: The OMEN key reaches the desktop as KEY_PROG2 (hp-wmi keymap 0x21a5, seen
#: on this machine at the live-USB check), which xkb names XF86Launch2. A GNOME
#: custom shortcut binds it to launching MyOmen Hub - and a launch while the
#: app is already running only brings its window forward (app.InstanceServer).
OMEN_KEY_BINDING = "XF86Launch2"
_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
_KEY_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/myomen/"
_LEGACY_KEY_PATHS = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/omen-sense/",
)


def _gsettings(*args: str) -> str | None:
    import subprocess
    try:
        done = subprocess.run(["gsettings", *args], capture_output=True,
                              text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def _shortcut_paths() -> list[str] | None:
    raw = _gsettings("get", _KEYS_SCHEMA, "custom-keybindings")
    if raw is None:
        return None
    raw = raw.removeprefix("@as").strip()
    return [item.strip().strip("'") for item in raw.strip("[]").split(",")
            if item.strip()]


def omen_key_supported() -> bool:
    return shutil.which("gsettings") is not None and _shortcut_paths() is not None


def omen_key_enabled() -> bool:
    paths = _shortcut_paths() or []
    if _KEY_PATH in paths:
        return True
    if any(p in paths for p in _LEGACY_KEY_PATHS):
        # Auto-migrate legacy omen-sense binding to official myomen binding
        set_omen_key(True)
        return True
    return False


def set_omen_key(enabled: bool) -> str | None:
    """Bind or unbind the OMEN key. GNOME only; other desktops say so."""
    paths = _shortcut_paths()
    if paths is None:
        return ("Couldn't reach GNOME's keyboard shortcuts. On another desktop, "
                f"bind {OMEN_KEY_BINDING} to `/usr/bin/myomen` in its own settings.")
    paths = [path for path in paths if path != _KEY_PATH and path not in _LEGACY_KEY_PATHS]
    if enabled:
        schema = f"{_KEYS_SCHEMA}.custom-keybinding:{_KEY_PATH}"
        command = "/usr/bin/myomen"
        for key, value in (("name", "MyOmen Hub"), ("command", command),
                           ("binding", OMEN_KEY_BINDING)):
            if _gsettings("set", schema, key, value) is None:
                return "Couldn't save the OMEN key shortcut."
        paths.append(_KEY_PATH)
    listed = "[" + ", ".join(f"'{path}'" for path in paths) + "]"
    if _gsettings("set", _KEYS_SCHEMA, "custom-keybindings", listed) is None:
        return "Couldn't save the OMEN key shortcut."
    return None


# -------------------------------------------------------------- profile API

def names() -> list[str]:
    return sorted(load().get("profiles", {}))


def get(name: str) -> dict | None:
    return load().get("profiles", {}).get(name)


def remember(name: str, profile: dict | None = None) -> str | None:
    """Save the machine's current settings, or a supplied profile, as `name`."""
    if not name.strip():
        return "A profile needs a name."
    document = load()
    document["profiles"][name.strip()] = profile or capture()
    return save(document)


def forget(name: str) -> str | None:
    document = load()
    if name not in document["profiles"]:
        return f"No profile called {name!r}."
    del document["profiles"][name]
    if document.get("startup") == name:
        document["startup"] = None
    return save(document)


def startup() -> str | None:
    """The profile to re-apply at login, if any."""
    document = load()
    name = document.get("startup")
    return name if name and name in document.get("profiles", {}) else None


def set_startup(name: str | None) -> str | None:
    document = load()
    if name is not None and name not in document["profiles"]:
        return f"No profile called {name!r}."
    document["startup"] = name
    return save(document)


delete = forget
save_named = remember
