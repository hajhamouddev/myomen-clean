#!/usr/bin/env bash
# install-8746.sh — build and install hp-wmi with the board-8746 quirk via DKMS.
#
#   sudo bash install-8746.sh            # from the OmenSense/driver folder
#   sudo bash install-8746.sh --remove   # uninstall, back to the stock module
#
# Takes hp-wmi.c from Ubuntu's own kernel source package, so the base is exactly
# what the running kernel was built from, applies patch-8746.py, builds it,
# and only then installs. Any failure before install leaves the system as-is.

set -euo pipefail
PKG=hp-wmi-omen8746
VER=1.0
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC=/usr/src/$PKG-$VER
KVER="$(uname -r)"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

if [ "${1:-}" = "--remove" ]; then
    dkms remove -m $PKG -v $VER --all 2>/dev/null || true
    rm -rf "$SRC"
    modprobe -r hp_wmi 2>/dev/null || true; modprobe hp_wmi || true
    echo "removed; stock hp-wmi: $(modinfo -n hp_wmi)"
    exit 0
fi

board="$(cat /sys/class/dmi/id/board_name)"
[ "$board" = "8746" ] || { echo "board is '$board', not 8746 - refusing"; exit 1; }

echo "== 1. build tools"
apt-get update -qq
apt-get install -y -qq patch dkms build-essential "linux-headers-$KVER" python3 mokutil linux-source

echo "== 2. hp-wmi.c from Ubuntu's kernel source"
tarball="$(ls /usr/src/linux-source-*/linux-source-*.tar.* 2>/dev/null | sort -V | tail -1)"
[ -n "$tarball" ] || { echo "linux-source tarball not found under /usr/src"; exit 1; }
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
# tar gets SIGPIPE when head exits early; don't let pipefail treat that as failure
top="$({ tar -tf "$tarball" 2>/dev/null || true; } | head -1 | cut -d/ -f1)"
[ -n "$top" ] || { echo "could not read $tarball"; exit 1; }
tar -xf "$tarball" -C "$work" "$top/drivers/platform/x86/hp/hp-wmi.c"
echo "source: $tarball"
echo "running kernel: $KVER ($(cat /proc/version_signature 2>/dev/null || true))"

echo "== 3. patch"
# Keyboard RGB: upstream "[PATCH v11] platform/x86: hp-wmi: Add multicolor LED
# support for HP keyboard backlight" (patchwork 14812352, Reviewed-by Hans de
# Goede), hp-wmi.c part only. Written against linux-next; one hunk of #defines
# needs fuzz 3 on 7.0. Pinned so a changed file is never applied.
echo "987c54295b4ae453791221e7e949ba0d0c4c7028a664c73740a2a68cacac454c  $HERE/kbd-rgb-v11.patch" | sha256sum -c --quiet \
    || { echo "kbd-rgb-v11.patch checksum mismatch"; exit 1; }
patch -s -p1 -F3 --no-backup-if-mismatch -d "$work/$top" < "$HERE/kbd-rgb-v11.patch"
echo "kbd-rgb-v11.patch applied"
python3 "$HERE/patch-8746.py" "$work/$top/drivers/platform/x86/hp/hp-wmi.c" "$work/hp-wmi.c"

echo "== 4. trial build (nothing installed yet)"
mkdir -p "$work/build"
cp "$work/hp-wmi.c" "$HERE/Makefile" "$work/build/"
make -s -C "/lib/modules/$KVER/build" M="$work/build" modules

echo "== 5. signing key (must exist before DKMS builds, or the module is unsigned)"
key=/var/lib/shim-signed/mok/MOK.der
[ -f "$key" ] || update-secureboot-policy --new-key
mkdir -p /etc/dkms/framework.conf.d
cat > /etc/dkms/framework.conf.d/omen-sense.conf <<EOF
mok_signing_key=/var/lib/shim-signed/mok/MOK.priv
mok_certificate=$key
EOF

echo "== 6. DKMS install"
dkms remove -m $PKG -v $VER --all 2>/dev/null || true
rm -rf "$SRC"; mkdir -p "$SRC"
cp "$work/hp-wmi.c" "$HERE/Makefile" "$HERE/dkms.conf" "$SRC/"
dkms add -m $PKG -v $VER
dkms build -m $PKG -v $VER
dkms install -m $PKG -v $VER --force
echo "module now resolves to: $(modinfo -n hp_wmi)"
echo "signer: $(modinfo -F signer "$(modinfo -n hp_wmi)" 2>/dev/null)"

echo "== 7. is the key enrolled?"
# Checked against the firmware's own list, not the kernel keyring: with Secure
# Boot off the keyring holds no MOK keys, so --test-key cannot tell, and an
# unenrolled key only shows up later - when Secure Boot is switched on and the
# kernel refuses the module.
fingerprint="$(openssl x509 -inform der -in "$key" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d : | tr A-F a-f)"
enrolled() { mokutil --list-enrolled 2>/dev/null | tr -d ': ' | tr A-F a-f | grep -q "$fingerprint"; }
pending() { mokutil --list-new 2>/dev/null | tr -d ': ' | tr A-F a-f | grep -q "$fingerprint"; }
secure_boot_on=0
mokutil --sb-state 2>/dev/null | grep -q enabled && secure_boot_on=1
if enrolled; then
    echo "signing key enrolled"
elif pending; then
    echo "signing key enrolment is already queued: reboot and finish it on the blue MokManager screen"
else
    echo
    echo ">>> The module is signed with $key, which is NOT enrolled."
    [ $secure_boot_on = 0 ] && echo ">>> Secure Boot is off, so it loads anyway - but it would be refused once Secure Boot is on."
    echo ">>> Choose a one-time password now; after reboot, the blue MokManager"
    echo ">>> screen asks for it: Enroll MOK -> Continue -> Yes -> password -> Reboot."
    mokutil --import "$key"
    if [ $secure_boot_on = 1 ]; then
        echo ">>> Reboot, enroll, then run: sudo bash verify-8746.sh"
        exit 0
    fi
fi

echo "== 8. load"
modprobe -r hp_wmi 2>/dev/null || true
modprobe hp_wmi
dmesg | grep -iE 'hp_wmi|hp-wmi|8746 quirk' | tail -5
echo "done. Next: sudo bash verify-8746.sh"
