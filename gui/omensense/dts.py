"""HP's own speaker tuning, read from the Windows side, for the Linux EQ.

On this laptop Windows runs DTS:X Ultra (Realtek driver package, "APO4"),
tuned by HP per audio subsystem. The tuning ships in the driver store as a
readable XML file plus binary EQ tables. `omen-sense audio import` finds the
Windows partition, picks this machine's folder the way the driver does (its
.inf maps SUBSYS_103C8746 to HP103C8600), and keeps what can be reproduced
exactly in PipeWire:

- the high-pass filters (EFX/MFX "HPF Freq/Order/Enable"), and
- the GPEQ tables: biquad cascades in fixed point, 24 bytes each - an int32
  giving the integer bits (2 for Q2.30, 1 for Q1.31), then b0 b1 b2 a1 a2 with
  the denominator 1 - a1 z^-1 - a2 z^-2. Decoded this way every filter in
  every table is stable with a DC gain of exactly 1, as an EQ section must be.
  The header's first word is twice the number of biquads. What follows the
  biquads - a gain word and a 511-entry table that is the same in every mode -
  is not decoded, and not used.

Headphones get nothing, on purpose: their table (dts_hpeq_*.bin) decodes to a
60 Hz high-pass and an exactly flat EQ - no headphone model is selected in
HP's tuning - so the faithful version of HP's headphone EQ is none.

What is not reproduced: DTS's own processing (TruBass HD-X bass, the MBHL
limiter, dialogue enhancement, the I3DA virtualiser). Those are proprietary
algorithms with parameters but no published design.

The data is HP's and DTS's. It is copied into the user's own settings folder,
never into this repository or its packages.
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import struct
import subprocess
import xml.etree.ElementTree as ET

DRIVER_STORE = "Windows/System32/DriverStore/FileRepository"
PACKAGE_GLOB = "dtsapo4*extensionpkg.inf_amd64_*"
SPEAKERS = "APO4-Internal Stereo"

#: Which DTS modes become presets. The three game modes share one preset:
#: on these speakers they differ only in DTS's own effects, which are not
#: reproduced, so three tiles would be three copies.
MODES = {
    "hp": "APO4-Off",
    "music": "APO4-Music",
    "movies": "APO4-Movie",
    "voice": "APO4-Voice",
    "game": "APO4-Game1",
}


def tuning_file() -> str:
    # Check ~/.config/myomen first, then legacy ~/.config/omen-sense, then local repo fallback
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    myomen_path = os.path.join(base, "myomen", "dts-tuning.json")
    if os.path.exists(myomen_path):
        return myomen_path
    legacy_path = os.path.join(base, "omen-sense", "dts-tuning.json")
    if os.path.exists(legacy_path):
        return legacy_path
    repo_local = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "local", "config", "dts-tuning.json")
    if os.path.exists(repo_local):
        return repo_local
    os.makedirs(os.path.join(base, "myomen"), exist_ok=True)
    return myomen_path


def load() -> dict | None:
    try:
        with open(tuning_file()) as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data.get("modes"), dict) else None


# ------------------------------------------------------------ this machine

def subsystem_id() -> str | None:
    """The Realtek codec's subsystem ID, as the driver .inf writes it."""
    for path in glob.glob("/proc/asound/card*/codec#*"):
        try:
            text = open(path).read()
        except OSError:
            continue
        if "Realtek" in text:
            match = re.search(r"Subsystem Id:\s*0x([0-9a-fA-F]{8})", text)
            if match:
                return match.group(1).upper()
    return None


# ----------------------------------------------------------- Windows side

def _ntfs_partitions() -> list[tuple[str, list[str]]]:
    try:
        out = subprocess.run(["lsblk", "-J", "-p", "-o", "NAME,FSTYPE,MOUNTPOINTS"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []

    def walk(devices):
        for device in devices or []:
            if device.get("fstype") == "ntfs":
                found.append((device["name"],
                              [m for m in device.get("mountpoints") or [] if m]))
            walk(device.get("children"))
    walk(json.loads(out).get("blockdevices"))
    return found


def _mount_read_only(device: str) -> str | None:
    try:
        out = subprocess.run(["udisksctl", "mount", "-b", device, "-o", "ro"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r" at (.+?)\.?$", out.strip())
    return match.group(1) if match else None


def _unmount(device: str) -> None:
    subprocess.run(["udisksctl", "unmount", "-b", device],
                   capture_output=True, text=True)


def _find_folder(root: str, ssid: str) -> str | None:
    """The tuning folder the driver would use for this subsystem."""
    for package in glob.glob(os.path.join(root, DRIVER_STORE, PACKAGE_GLOB)):
        for inf in glob.glob(os.path.join(package, "*.inf")):
            try:
                text = open(inf, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            match = re.search(rf"=\s*(\w+)\s*,\s*[^\n]*SUBSYS_{ssid}\b", text, re.I)
            if match and os.path.isdir(os.path.join(package, match.group(1))):
                return os.path.join(package, match.group(1))
    return None


# ------------------------------------------------------------------ parsing

def parse_gpeq(data: bytes) -> list[list[float]]:
    """Biquads from a GPEQ table, in PipeWire's convention (a0 = 1, y -= a1 y1)."""
    count = struct.unpack_from("<i", data, 0)[0] // 2
    biquads = []
    for index in range(count):
        offset = 8 + 24 * index
        if offset + 24 > len(data):
            break
        integer_bits, *raw = struct.unpack_from("<i5i", data, offset)
        if not 1 <= integer_bits <= 4:
            break
        b0, b1, b2, a1, a2 = (value / 2 ** (32 - integer_bits) for value in raw)
        biquads.append([b0, b1, b2, -a1, -a2])
    return biquads


def parse_modes(xml_text: str) -> dict[str, dict[str, str]]:
    """Every internal-speaker operating mode's controls, by mode name."""
    modes = {}
    for mode in ET.fromstring(xml_text).findall("operating_mode"):
        controls = {c.get("name"): (c.text or "").strip() for c in mode.iter("control")}
        if controls.get("APO4-Speaker Type") == SPEAKERS:
            modes[controls.get("APO4-Operating Mode")] = controls
    return modes


def _stage(controls: dict, chain: str, folder: str) -> dict:
    """One chain's (EFX or MFX) high-pass and GPEQ, if it switches them on."""
    stage = {"hpf": [], "biquads": {}}
    if controls.get(f"{chain}:Eagle-HPF Enable") == "1":
        stage["hpf"].append({"freq": float(controls[f"{chain}:Eagle-HPF Freq"]),
                             "order": int(controls[f"{chain}:Eagle-HPF Order"])})
    for rate, key in ((44100, "44k"), (48000, "48k")):
        blob = controls.get(f"{chain}:Eagle-GPEQ Blob {key}")
        if blob:
            with open(os.path.join(folder, blob), "rb") as handle:
                stage["biquads"][str(rate)] = parse_gpeq(handle.read())
    return stage


def build(folder: str) -> dict:
    xml_path = glob.glob(os.path.join(folder, "dts_apo4_oem_config_*.xml"))[0]
    with open(xml_path, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    modes = parse_modes(text)
    result = {}
    for key, name in MODES.items():
        controls = modes[name]
        # "Off" runs the EFX chain alone; every other mode runs MFX.
        chain = "EFX" if name == "APO4-Off" else "MFX"
        stage = _stage(controls, chain, folder)
        # TruBass HD-X: kept as settings only, to drive a stand-in (audio.py).
        if controls.get("MFX:Eagle-TBHDX Enable") == "1":
            stage["bass"] = {
                "level": float(controls.get("MFX:Eagle-TBHDX Bass Level", 0)),
                "speaker_size": float(controls.get("MFX:Eagle-TBHDX Speaker Custom Size", 0)),
            }
        result[key] = stage
    return {"modes": result,
            "source": os.path.basename(folder),
            "xml_sha256": hashlib.sha256(text.encode()).hexdigest()}


# ------------------------------------------------------------------- import

def import_tuning() -> tuple[dict | None, str]:
    """Find this machine's tuning on a Windows partition and keep it.

    Returns (tuning, message). Mounts an unmounted Windows partition
    read-only for the duration, and puts it back as it was.
    """
    ssid = subsystem_id()
    if not ssid:
        return None, "No Realtek codec found, so there is no tuning to look for."
    for device, mounts in _ntfs_partitions():
        mounted_here = False
        if not mounts:
            point = _mount_read_only(device)
            if not point:
                continue
            mounts, mounted_here = [point], True
        try:
            for mount in mounts:
                folder = _find_folder(mount, ssid)
                if folder:
                    tuning = build(folder)
                    tuning.update({"subsystem": ssid,
                                   "imported": datetime.date.today().isoformat()})
                    with open(tuning_file(), "w") as handle:
                        json.dump(tuning, handle, indent=1)
                    return tuning, (f"Imported HP's tuning for subsystem {ssid} "
                                    f"({tuning['source']}) from {device}.")
        finally:
            if mounted_here:
                _unmount(device)
    return None, (f"No DTS tuning for subsystem {ssid} was found on a Windows "
                  "partition. It lives in the Realtek driver package's DTS APO4 "
                  "extension; is Windows on this machine?")
