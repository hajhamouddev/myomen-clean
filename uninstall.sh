#!/usr/bin/env bash
# ==============================================================================
# MyOmen - Clean System Uninstaller
# ==============================================================================
set -euo pipefail

TARGET_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo ">>> [MyOmen] Stopping running instances..."
pkill -9 -f "myomen|omensense" 2>/dev/null || true

echo ">>> [MyOmen] Removing application files and binaries..."
if [ -d "/opt/myomen" ]; then
    if [ "$EUID" -eq 0 ]; then
        rm -rf /opt/myomen /usr/local/bin/myomen
    else
        sudo rm -rf /opt/myomen /usr/local/bin/myomen
    fi
fi
rm -f "$USER_HOME/.local/bin/myomen"

echo ">>> [MyOmen] Removing desktop shortcuts, icons, and autostart..."
rm -f "$USER_HOME/.local/share/applications/myomen.desktop"
rm -f "$USER_HOME/.local/share/icons/hicolor/scalable/apps/myomen.svg"
rm -f "$USER_HOME/.config/autostart/myomen.desktop" "$USER_HOME/.config/autostart/omen-sense.desktop"

echo ">>> [MyOmen] Cleaning up udev rules..."
if [ -f "/etc/udev/rules.d/99-myomen.rules" ]; then
    if [ "$EUID" -eq 0 ]; then
        rm -f /etc/udev/rules.d/99-myomen.rules
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
    elif command -v sudo >/dev/null 2>&1; then
        sudo rm -f /etc/udev/rules.d/99-myomen.rules
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
    fi
fi

echo ">>> [MyOmen] Cleaning temporary sockets and cache..."
rm -rf /tmp/*myomen* /tmp/*omen* "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/*myomen* "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/*omen* 2>/dev/null || true

echo ">>> [MyOmen] Uninstallation completed cleanly without touching system packages."
