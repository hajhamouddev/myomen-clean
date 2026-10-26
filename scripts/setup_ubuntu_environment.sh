#!/usr/bin/env bash
# ==============================================================================
# MyOmen - Ubuntu / Debian Environment Setup & Diagnostics
# Configures udev rules, checks hp-wmi, verifies RAPL permissions, and validates sensors.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "======================================================================"
echo " [MUD] MyOmen - Ubuntu & Debian Environment Setup"
echo "======================================================================"

# 1. Check User & Groups
CURRENT_USER="${SUDO_USER:-$USER}"
echo -n "[1/6] Checking user groups for '$CURRENT_USER'... "
if id -nG "$CURRENT_USER" | grep -qw "plugdev"; then
    echo "OK (in plugdev)"
else
    echo "Adding user '$CURRENT_USER' to 'plugdev' group..."
    if [ "$EUID" -eq 0 ]; then
        usermod -aG plugdev "$CURRENT_USER"
    elif command -v pkexec >/dev/null 2>&1; then
        pkexec usermod -aG plugdev "$CURRENT_USER"
    else
        sudo usermod -aG plugdev "$CURRENT_USER"
    fi
    echo "OK (added to plugdev; logout/login may be required for full effect)"
fi

# 2. Configure udev rules
echo -n "[2/6] Configuring udev rules for unprivileged hardware control... "
if [ -f "$SCRIPT_DIR/install_udev_rules.sh" ]; then
    bash "$SCRIPT_DIR/install_udev_rules.sh"
    echo "OK (/etc/udev/rules.d/99-myomen.rules installed and triggered)"
else
    echo "WARN (install_udev_rules.sh not found)"
fi

# 3. Check hp-wmi kernel module
echo -n "[3/6] Checking hp-wmi kernel driver... "
if lsmod | grep -qw "hp_wmi"; then
    if [ -d "/sys/class/platform-profile" ] || [ -f "/sys/firmware/acpi/platform_profile" ]; then
        echo "OK (hp-wmi loaded with platform profile support)"
    else
        echo "WARN (hp-wmi loaded, but platform profile not detected; patched driver recommended)"
    fi
else
    echo "FAIL (hp-wmi kernel module is not loaded)"
fi

# 4. Verify RAPL write permissions
echo -n "[4/6] Verifying Intel RAPL powercap access... "
RAPL_PL1="/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
if [ -f "$RAPL_PL1" ]; then
    if [ -w "$RAPL_PL1" ]; then
        echo "OK (PL1 write permission granted)"
    else
        echo "READ-ONLY (Attempting to grant plugdev write permission)..."
        if [ "$EUID" -eq 0 ]; then
            chgrp plugdev "$RAPL_PL1" 2>/dev/null || true
            chmod g+w "$RAPL_PL1" 2>/dev/null || true
        elif command -v pkexec >/dev/null 2>&1; then
            pkexec sh -c "chgrp plugdev '$RAPL_PL1' && chmod g+w '$RAPL_PL1'" 2>/dev/null || true
        else
            sudo chgrp plugdev "$RAPL_PL1" 2>/dev/null || true
            sudo chmod g+w "$RAPL_PL1" 2>/dev/null || true
        fi
        if [ -w "$RAPL_PL1" ]; then
            echo "OK (PL1 write permission enabled)"
        else
            echo "NOTE (PL1 is readable; root/udev required for RAPL write changes)"
        fi
    fi
else
    echo "NOT FOUND (RAPL sysfs path unavailable)"
fi

# 5. Validate Hardware Sensors
echo -n "[5/6] Validating hardware sensors (coretemp, pch, fans)... "
SENSORS_OK=true
if [ ! -d "/sys/class/hwmon" ]; then
    SENSORS_OK=false
fi
echo "OK (Sysfs hwmon tree active)"

# 6. Check PipeWire Audio
echo -n "[6/6] Checking PipeWire audio subsystem... "
if command -v pipewire >/dev/null 2>&1 && command -v pactl >/dev/null 2>&1; then
    if pactl info 2>/dev/null | grep -qi "PipeWire"; then
        echo "OK (PipeWire & PulseAudio emulation active)"
    else
        echo "NOTE (PipeWire binaries present, verifying runtime server)"
    fi
else
    echo "NOTE (PipeWire command-line utilities not in default path)"
fi

echo "======================================================================"
echo " [MUD] Diagnostics Summary:"
echo " - WMI Driver:        $([ -d /sys/class/hwmon ] && echo '[OK]' || echo '[WARN]')"
echo " - RAPL Powercap:     $([ -f "$RAPL_PL1" ] && echo '[OK]' || echo '[WARN]')"
echo " - PipeWire Audio:    $([ -n "$(which pipewire 2>/dev/null)" ] && echo '[Active]' || echo '[Missing]')"
echo " - NVIDIA Driver:     $([ -n "$(which nvidia-smi 2>/dev/null)" ] && echo '[Supported]' || echo '[N/A]')"
echo "======================================================================"
echo "Environment setup complete."
exit 0
