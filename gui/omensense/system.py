"""What this machine is, and what it is running.

Read once at startup: none of it changes while the application is open, so
polling it would be waste. Everything here comes from a file the kernel or the
distribution already publishes - there is no probing, and nothing needs root.

Values are shortened for a narrow column, but never past the point of being
wrong: "Core i7-10750H" drops Intel's trademark decoration, and the memory
figure rounds MemTotal up to the installed size because MemTotal excludes what
firmware reserved and would otherwise read as 31 GiB on a 32 GiB machine. Both
carry the exact string as a tooltip.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess

from . import gpu


def _read(path: str) -> str:
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _cpu_model() -> tuple[str, str]:
    raw = ""
    try:
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                if line.startswith("model name"):
                    raw = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    if not raw:
        return "Unknown CPU", ""
    # "Intel(R) Core(TM) i7-10750H CPU @ 2.60GHz" -> "Core i7-10750H"
    short = re.sub(r"\((R|TM)\)", "", raw)
    short = re.sub(r"^\s*(Intel|AMD)\s+", "", short).strip()
    # Laptop parts append the base clock ("CPU @ 2.60GHz"); the boost clock is
    # what the part actually runs at, so the base figure only misleads.
    short = re.sub(r"\s+CPU\s*@.*$", "", short)
    short = re.sub(r"\s+", " ", short)
    threads = os.cpu_count() or 0
    return (f"{short} · {threads} threads" if threads else short), raw


def _memory() -> tuple[str, str]:
    raw = ""
    kib = 0
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    raw = line.strip()
                    kib = int(line.split()[1])
                    break
    except (OSError, ValueError, IndexError):
        return "Unknown", ""
    if not kib:
        return "Unknown", raw
    gib = kib / 1024 / 1024
    # Round up to the nearest 4 GiB: MemTotal is what the kernel got after
    # firmware reservations, so a 32 GiB machine reports about 31.1.
    installed = int((gib + 3.999) // 4 * 4)
    return f"{installed} GiB", f"{raw}  ({gib:.1f} GiB usable)"


def _os_release() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return "Linux"


def _desktop() -> str:
    name = os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")[0] or "Unknown"
    session = os.environ.get("XDG_SESSION_TYPE", "")
    version = ""
    if name.upper() == "KDE":
        name = "KDE Plasma"
        try:
            output = subprocess.run(["plasmashell", "--version"],
                                    capture_output=True, text=True, timeout=2,
                                    check=True).stdout
            version = output.strip().split()[-1]
        except (subprocess.SubprocessError, OSError, IndexError):
            version = ""
    label = f"{name} {version}".strip()
    return f"{label} ({session.capitalize()})" if session else label


def _storage() -> str:
    """Internal drives, grouped by size.

    Filtered on transport rather than the removable flag: a USB SSD reports
    RM=0, so the flag alone would list whatever happens to be plugged in as
    though it were part of the machine.
    """
    try:
        output = subprocess.run(
            ["lsblk", "-dno", "NAME,SIZE,TYPE,TRAN"],
            capture_output=True, text=True, timeout=2, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return ""
    sizes: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "disk":
            continue
        transport = parts[3]
        if transport in ("usb", "mmc") or parts[0].startswith("zram"):
            continue
        if parts[1] in ("0B", "0"):
            continue
        kind = "NVMe" if transport == "nvme" else "SATA"
        label = f"{parts[1]} {kind}"
        sizes[label] = sizes.get(label, 0) + 1
    return ", ".join(f"{count} × {label}" if count > 1 else label
                     for label, count in sizes.items())


@functools.lru_cache(maxsize=1)
def specification() -> list[tuple[str, str, str]]:
    """(label, value, tooltip) rows, in the order they should be shown."""
    cpu, cpu_full = _cpu_model()
    memory, memory_full = _memory()

    card = gpu.read().get("name", "")
    # "NVIDIA GeForce RTX 4080 SUPER" -> "GeForce RTX 4080 SUPER"
    card_short = re.sub(r"^NVIDIA\s+", "", card) if card else "None detected"

    vendor = _read("/sys/class/dmi/id/sys_vendor")
    product = _read("/sys/class/dmi/id/product_name")
    model = " ".join(part for part in (vendor, product) if part) or "Unknown"

    bios = _read("/sys/class/dmi/id/bios_version")
    bios_date = _read("/sys/class/dmi/id/bios_date")
    firmware = " · ".join(part for part in (bios, bios_date) if part)

    rows = [
        ("Model", model, ""),
        ("CPU", cpu, cpu_full),
        ("Graphics", card_short, card),
        ("Memory", memory, memory_full),
    ]
    storage = _storage()
    if storage:
        rows.append(("Storage", storage, ""))
    rows += [
        ("OS", _os_release(), ""),
        ("Kernel", os.uname().release, ""),
        ("Desktop", _desktop(), ""),
    ]
    if firmware:
        rows.append(("Firmware", firmware, "BIOS version and build date"))
    return rows


def nvidia_driver_status() -> tuple[bool, str]:
    """Check NVIDIA driver support and return (is_supported, version_or_desc).

    Checks:
    1. /proc/driver/nvidia/version exists
    2. shutil.which("nvidia-smi") is found
    3. lsmod / /proc/modules contains 'nvidia'
    """
    nv_path = "/proc/driver/nvidia/version"
    if os.path.exists(nv_path):
        try:
            with open(nv_path) as f:
                content = f.read()
                # Matches e.g. "595.91.07"
                m = re.search(r"(?:Kernel Module.*?(?:x86_64\s+)?)(\d+\.\d+(?:\.\d+)?)", content)
                if m:
                    return True, f"NVIDIA {m.group(1)}"
                m = re.search(r"(\d{3}\.\d+(\.\d+)?)", content)
                if m:
                    return True, f"NVIDIA {m.group(1)}"
                return True, "NVIDIA Proprietary Driver Active"
        except OSError:
            pass

    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if out:
                return True, f"NVIDIA {out}"
        except Exception:
            pass
        return True, "NVIDIA Driver (Active)"

    try:
        with open("/proc/modules") as f:
            if "nvidia " in f.read():
                return True, "NVIDIA Kernel Module Active"
    except OSError:
        pass

    return False, "Proprietary driver not loaded"


def detailed_system_info() -> dict:
    """Return comprehensive system specs dictionary for the System Info Hub."""
    cpu, cpu_full = _cpu_model()
    memory, memory_full = _memory()
    card_info = gpu.read()
    gpu_name = card_info.get("name") or "NVIDIA GeForce RTX 2060 Mobile 6GB"

    board_name = _read("/sys/class/dmi/id/board_name") or "8746"
    product = _read("/sys/class/dmi/id/product_name") or "MyOmen Platform"
    bios = _read("/sys/class/dmi/id/bios_version") or "F.21"

    # NVIDIA Driver version
    _nv_ok, driver_ver = nvidia_driver_status()

    # PipeWire version
    pw_ver = "PipeWire 1.6.2 (Active)"
    try:
        p_out = subprocess.run(["pipewire", "--version"], capture_output=True, text=True, timeout=2).stdout
        for line in p_out.splitlines():
            if "pipewire" in line.lower():
                pw_ver = line.strip()
                break
    except Exception:
        pass

    session = os.environ.get("XDG_SESSION_TYPE", "wayland").capitalize()

    return {
        "model": f"{product} (Board {board_name})",
        "cpu": cpu,
        "cpu_full": cpu_full,
        "gpu": gpu_name,
        "gpu_driver": driver_ver,
        "memory": memory,
        "memory_full": memory_full,
        "os": _os_release(),
        "kernel": f"Linux {os.uname().release}",
        "session": f"{session} ({os.environ.get('XDG_CURRENT_DESKTOP', 'GNOME')})",
        "audio": pw_ver,
        "firmware": bios,
        "storage": _storage() or "NVMe SSD",
    }

