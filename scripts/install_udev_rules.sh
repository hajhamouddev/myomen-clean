#!/usr/bin/env bash
# ==============================================================================
# MyOmen - Install udev Rules for Unprivileged Non-Root Hardware Control
# Target: HP OMEN Laptop 15-dh1xxx / Board 8746
# ==============================================================================
set -euo pipefail

RULES_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/packaging/udev/99-myomen.rules"
RULES_TARGET="/etc/udev/rules.d/99-myomen.rules"
CURRENT_USER="${SUDO_USER:-$USER}"

echo ">>> [MyOmen] Installing udev rules to $RULES_TARGET for user '$CURRENT_USER'..."

if [ "$EUID" -eq 0 ]; then
    cp "$RULES_SOURCE" "$RULES_TARGET"
    chmod 644 "$RULES_TARGET"
    usermod -aG plugdev "$CURRENT_USER" 2>/dev/null || true
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
    # Immediate runtime sysfs permissions
    chmod a+r /sys/class/powercap/intel-rapl:0/energy_uj /sys/class/powercap/intel-rapl:0/max_energy_range_uj 2>/dev/null || true
    for f in /sys/class/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/constraint_*_power_limit_uw; do
        [ -e "$f" ] && chgrp plugdev "$f" 2>/dev/null && chmod 0664 "$f" 2>/dev/null || true
    done
    for f in /sys/class/hwmon/hwmon*/pwm1_enable; do
        [ -f "$f" ] && chgrp plugdev "$f" 2>/dev/null && chmod g+w "$f" 2>/dev/null || true
    done
    for p in /sys/class/platform-profile/platform-profile-*/profile; do
        [ -f "$p" ] && chgrp plugdev "$p" 2>/dev/null && chmod g+w "$p" 2>/dev/null || true
    done
elif command -v pkexec >/dev/null 2>&1; then
    pkexec /bin/sh -c "
        cp '$RULES_SOURCE' '$RULES_TARGET' && \
        chmod 644 '$RULES_TARGET' && \
        usermod -aG plugdev '$CURRENT_USER' 2>/dev/null || true
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        chmod a+r /sys/class/powercap/intel-rapl:0/energy_uj /sys/class/powercap/intel-rapl:0/max_energy_range_uj 2>/dev/null || true
        for f in /sys/class/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/constraint_*_power_limit_uw; do
            [ -e \"\$f\" ] && chgrp plugdev \"\$f\" 2>/dev/null && chmod 0664 \"\$f\" 2>/dev/null || true
        done
        for f in /sys/class/hwmon/hwmon*/pwm1_enable; do
            [ -f \"\$f\" ] && chgrp plugdev \"\$f\" 2>/dev/null && chmod g+w \"\$f\" 2>/dev/null || true
        done
        for p in /sys/class/platform-profile/platform-profile-*/profile; do
            [ -f \"\$p\" ] && chgrp plugdev \"\$p\" 2>/dev/null && chmod g+w \"\$p\" 2>/dev/null || true
        done
    "
else
    sudo cp "$RULES_SOURCE" "$RULES_TARGET"
    sudo chmod 644 "$RULES_TARGET"
    sudo usermod -aG plugdev "$CURRENT_USER" 2>/dev/null || true
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    sudo chmod a+r /sys/class/powercap/intel-rapl:0/energy_uj /sys/class/powercap/intel-rapl:0/max_energy_range_uj 2>/dev/null || true
    for f in /sys/class/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/*/constraint_*_power_limit_uw /sys/class/powercap/intel-rapl*/constraint_*_power_limit_uw /sys/devices/virtual/powercap/intel-rapl*/constraint_*_power_limit_uw; do
        [ -e "$f" ] && sudo chgrp plugdev "$f" 2>/dev/null && sudo chmod 0664 "$f" 2>/dev/null || true
    done
fi

echo ">>> [MyOmen] Successfully installed $RULES_TARGET."
