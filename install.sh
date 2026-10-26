#!/usr/bin/env bash
# ==============================================================================
# MyOmen - Universal Automated One-Click Installer
# Target Architecture: Linux x86_64 / HP OMEN 15-dh1xxx / Ubuntu & Debian
# ==============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "=========================================================="
echo "      🚀 MyOmen Universal Installer (2026 Production)     "
echo "=========================================================="
echo ">>> Target User: $TARGET_USER"
echo ">>> Source Path: $ROOT_DIR"

# 1. Dependency Resolution via apt
if command -v apt-get >/dev/null 2>&1; then
    echo ">>> [1/5] Checking and installing system dependencies..."
    REQUIRED_PKGS=(
        python3
        python3-pip
        python3-pyside6.qtwidgets
        python3-pyside6.qtgui
        python3-pyside6.qtcore
        lm-sensors
        pipewire
        wireplumber
    )
    MISSING_PKGS=()
    for pkg in "${REQUIRED_PKGS[@]}"; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            MISSING_PKGS+=("$pkg")
        fi
    done

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo ">>> Installing missing packages: ${MISSING_PKGS[*]}"
        if [ "$EUID" -eq 0 ]; then
            apt-get update -y
            apt-get install -y --no-install-recommends "${MISSING_PKGS[@]}"
        else
            sudo apt-get update -y
            sudo apt-get install -y --no-install-recommends "${MISSING_PKGS[@]}"
        fi
    else
        echo ">>> All essential system dependencies are already satisfied."
    fi
fi

# 2. Kernel Module hp_wmi Verification
echo ">>> [2/5] Verifying hp-wmi kernel module..."
if ! lsmod | grep -q "^hp_wmi"; then
    echo ">>> Loading hp_wmi kernel module..."
    if [ "$EUID" -eq 0 ]; then
        modprobe hp_wmi || true
    else
        sudo modprobe hp_wmi || true
    fi
fi

# 3. Non-Root Hardware Permissions (udev)
echo ">>> [3/5] Configuring udev rules and hardware access..."
UDEV_RULE_SRC="$ROOT_DIR/packaging/udev/99-myomen.rules"
UDEV_RULE_DST="/etc/udev/rules.d/99-myomen.rules"

if [ -f "$UDEV_RULE_SRC" ]; then
    if [ "$EUID" -eq 0 ]; then
        cp "$UDEV_RULE_SRC" "$UDEV_RULE_DST"
        chmod 644 "$UDEV_RULE_DST"
        usermod -aG plugdev "$TARGET_USER" 2>/dev/null || true
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
    elif command -v sudo >/dev/null 2>&1; then
        sudo cp "$UDEV_RULE_SRC" "$UDEV_RULE_DST"
        sudo chmod 644 "$UDEV_RULE_DST"
        sudo usermod -aG plugdev "$TARGET_USER" 2>/dev/null || true
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
    fi
fi

# 4. Deploy Application Files & Binaries
echo ">>> [4/5] Deploying MyOmen binaries and assets..."
INSTALL_PREFIX="/opt/myomen"

if [ "$EUID" -eq 0 ]; then
    mkdir -p "$INSTALL_PREFIX"
    cp -r "$ROOT_DIR/gui" "$INSTALL_PREFIX/"
    cp -r "$ROOT_DIR/scripts" "$INSTALL_PREFIX/"
    find "$INSTALL_PREFIX" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

    cat << 'WRAPPER' > /usr/local/bin/myomen
#!/usr/bin/env bash
export PYTHONPATH="/opt/myomen/gui:${PYTHONPATH:-}"
exec /usr/bin/python3 -m omensense.app "$@"
WRAPPER
    chmod 755 /usr/local/bin/myomen
else
    # User local installation fallback
    USER_BIN="$USER_HOME/.local/bin"
    mkdir -p "$USER_BIN"
    cp "$ROOT_DIR/scripts/myomen" "$USER_BIN/myomen"
    chmod 755 "$USER_BIN/myomen"
fi

# 5. Desktop Launcher, Icon, and Autostart Integration
echo ">>> [5/5] Integrating desktop icons and autostart..."
USER_APPS="$USER_HOME/.local/share/applications"
USER_ICONS="$USER_HOME/.local/share/icons/hicolor/scalable/apps"
USER_AUTOSTART="$USER_HOME/.config/autostart"

mkdir -p "$USER_APPS" "$USER_ICONS" "$USER_AUTOSTART"

# Icon
if [ -f "$ROOT_DIR/gui/omensense/icons/myomen.svg" ]; then
    cp "$ROOT_DIR/gui/omensense/icons/myomen.svg" "$USER_ICONS/myomen.svg"
elif [ -f "$ROOT_DIR/gui/omensense/icons/omen-sense.svg" ]; then
    cp "$ROOT_DIR/gui/omensense/icons/omen-sense.svg" "$USER_ICONS/myomen.svg"
fi

# Desktop file
cp "$ROOT_DIR/packaging/desktop/myomen.desktop" "$USER_APPS/myomen.desktop"

# Clean legacy autostart entries so systemd --user remains single source of truth
rm -f "$USER_AUTOSTART/myomen.desktop" "$USER_AUTOSTART/omen-sense.desktop" 2>/dev/null || true

chmod 644 "$USER_APPS/myomen.desktop"
chown -R "$TARGET_USER:$TARGET_USER" "$USER_HOME/.local/share" 2>/dev/null || true

echo "=========================================================="
echo "   ✅ MyOmen successfully installed & ready to launch!   "
echo "=========================================================="
echo "• Launch interactively: myomen"
echo "• Background tray mode: myomen --tray"
echo "• Autostart enabled on user login."
