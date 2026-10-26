#!/usr/bin/env bash
# ==============================================================================
# MyOmen - Automated FHS-Compliant Debian Package Build Pipeline
# Architecture: amd64 | Target: Ubuntu 24.04 LTS / Debian
# ==============================================================================
set -euo pipefail

PACKAGE_NAME="myomen"
VERSION="${1:-1.0.0}"
ARCH="${2:-amd64}"
PKG_IDENT="${PACKAGE_NAME}_${VERSION}_${ARCH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUILD_DIR="${REPO_ROOT}/build"
DIST_DIR="${REPO_ROOT}/dist"
STAGING_DIR="${BUILD_DIR}/deb/${PKG_IDENT}"
DEB_FILE="${DIST_DIR}/${PKG_IDENT}.deb"

echo "=========================================================="
echo "  📦 Building Debian Package: ${PKG_IDENT}"
echo "=========================================================="
echo ">>> Repo root:    ${REPO_ROOT}"
echo ">>> Staging dir:  ${STAGING_DIR}"
echo ">>> Output .deb:  ${DEB_FILE}"

# 1. Clean previous build artifacts
echo ">>> [1/5] Cleaning previous build and distribution artifacts..."
rm -rf "${BUILD_DIR}" "${DIST_DIR}"

# 2. Syntax & AST verification
echo ">>> [2/5] Validating Python AST and syntax..."
python3 -m py_compile "${REPO_ROOT}"/gui/omensense/*.py

# 3. Create FHS directory hierarchy
echo ">>> [3/5] Creating FHS directory hierarchy..."
mkdir -p "${STAGING_DIR}/DEBIAN"
mkdir -p "${STAGING_DIR}/usr/bin"
mkdir -p "${STAGING_DIR}/usr/lib/myomen"
mkdir -p "${STAGING_DIR}/usr/lib/systemd/user"
mkdir -p "${STAGING_DIR}/usr/lib/tmpfiles.d"
mkdir -p "${STAGING_DIR}/usr/share/applications"
mkdir -p "${STAGING_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${STAGING_DIR}/etc/udev/rules.d"
mkdir -p "${DIST_DIR}"

# 4. Populate files cleanly
echo ">>> [4/5] Populating application payload and system configurations..."

# Copy Python modules, assets and icons into /usr/lib/myomen/
rsync -a \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache' \
    "${REPO_ROOT}/gui/omensense" "${STAGING_DIR}/usr/lib/myomen/"

# /usr/bin/myomen executable wrapper
cat > "${STAGING_DIR}/usr/bin/myomen" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/lib/myomen${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 /usr/lib/myomen/omensense/app.py "$@"
EOF
chmod 755 "${STAGING_DIR}/usr/bin/myomen"

# /usr/share/applications/myomen.desktop
install -m 644 "${REPO_ROOT}/packaging/desktop/myomen.desktop" "${STAGING_DIR}/usr/share/applications/myomen.desktop"

# /usr/share/icons/hicolor/scalable/apps/myomen.svg & /usr/share/pixmaps/myomen.svg
install -m 644 "${REPO_ROOT}/gui/omensense/icons/myomen.svg" "${STAGING_DIR}/usr/share/icons/hicolor/scalable/apps/myomen.svg"
mkdir -p "${STAGING_DIR}/usr/share/pixmaps"
install -m 644 "${REPO_ROOT}/gui/omensense/icons/myomen.svg" "${STAGING_DIR}/usr/share/pixmaps/myomen.svg"

# Generate raster PNG derivatives for hicolor theme
python3 - <<EOF
from PySide6 import QtWidgets, QtGui, QtCore
import os

app = QtWidgets.QApplication([])
ico = QtGui.QIcon("${REPO_ROOT}/gui/omensense/icons/myomen.svg")
for s in [16, 32, 48, 64, 128, 256, 512]:
    dir_path = f"${STAGING_DIR}/usr/share/icons/hicolor/{s}x{s}/apps"
    os.makedirs(dir_path, exist_ok=True)
    pix = ico.pixmap(QtCore.QSize(s, s))
    img = pix.toImage().scaled(s, s, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
    img.save(os.path.join(dir_path, "myomen.png"), "PNG")
EOF

# /usr/lib/systemd/user/myomen.service
install -m 644 "${REPO_ROOT}/packaging/systemd/myomen.service" "${STAGING_DIR}/usr/lib/systemd/user/myomen.service"

# /usr/lib/tmpfiles.d/myomen.conf
install -m 644 "${REPO_ROOT}/packaging/tmpfiles.d/myomen.conf" "${STAGING_DIR}/usr/lib/tmpfiles.d/myomen.conf"

# /etc/udev/rules.d/99-myomen.rules
install -m 644 "${REPO_ROOT}/packaging/udev/99-myomen.rules" "${STAGING_DIR}/etc/udev/rules.d/99-myomen.rules"

# Populate DEBIAN control and maintainer scripts from packaging/debian/
cp "${REPO_ROOT}/packaging/debian/postinst" "${STAGING_DIR}/DEBIAN/postinst"
cp "${REPO_ROOT}/packaging/debian/prerm" "${STAGING_DIR}/DEBIAN/prerm"
cp "${REPO_ROOT}/packaging/debian/postrm" "${STAGING_DIR}/DEBIAN/postrm"

# Calculate Installed-Size dynamically (in KB) excluding DEBIAN directory
INSTALLED_SIZE=$(du -sk --exclude="${STAGING_DIR}/DEBIAN" "${STAGING_DIR}" | cut -f1)

cat > "${STAGING_DIR}/DEBIAN/control" <<EOF
Package: ${PACKAGE_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Haj Hamoud <hajhamoud@local>
Installed-Size: ${INSTALLED_SIZE}
Depends: python3 (>= 3.10), lm-sensors, pipewire, wireplumber, libnotify-bin
Description: Lightweight hardware telemetry and fan control hub for HP OMEN laptops.
 A modern, lightweight hardware telemetry monitor, dynamic fan controller,
 4-zone RGB keyboard lighting manager, and PipeWire DSP audio peak limiter
 designed specifically for HP OMEN laptops running Linux.
EOF

# Canonical Unix file permissions
find "${STAGING_DIR}" -type d -exec chmod 755 {} +
find "${STAGING_DIR}" -type f -exec chmod 644 {} +
chmod 755 "${STAGING_DIR}/usr/bin/myomen"
chmod 755 "${STAGING_DIR}/DEBIAN/postinst" "${STAGING_DIR}/DEBIAN/prerm" "${STAGING_DIR}/DEBIAN/postrm"

# 5. Build Debian package with root ownership
echo ">>> [5/5] Packaging binary .deb and generating SHA256 checksum..."
dpkg-deb --root-owner-group --build "${STAGING_DIR}" "${DEB_FILE}"

# Generate SHA256 checksums alongside package
(cd "${DIST_DIR}" && sha256sum "$(basename "${DEB_FILE}")" > SHA256SUMS)

echo "=========================================================="
echo "  ✅ Package built successfully!"
echo "  📦 Output:   ${DEB_FILE}"
echo "  🔑 SHA256:   $(cut -d' ' -f1 "${DIST_DIR}/SHA256SUMS")"
echo "  📊 Size:     $(du -h "${DEB_FILE}" | cut -f1)"
echo "=========================================================="
