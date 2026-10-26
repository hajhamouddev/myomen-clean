#!/usr/bin/env bash
# live-usb-check.sh — one-shot evidence collection for HP OMEN 15-dh1xxx (board 8746)
# from a Linux live USB. Confirms or refutes docs/findings-8746.md §§1-3.
#
#   sudo bash live-usb-check.sh            # writes omen-8746-check-<date>.txt next to itself
#
# What reaches firmware, and why each is allowed (project rule: no invented values):
#   - reading sysfs (hwmon, platform_profile, gpu_mux_mode, hp-bioscfg): the same
#     queries hp-wmi / hp-bioscfg already make at boot on this board
#   - reading EC registers through ec_sys WITHOUT write_support: EC read commands only
#   - reloading hp-wmi once: repeats its boot-time probe (profile re-send, max-fan off)
#   - setting platform_profile cool -> performance -> balanced: payloads {FF,02},
#     {FF,01}, {FF,00}, all seen in HP's own OMEN Gaming Hub log on this machine
#     (performance only takes effect on AC; plug the charger in).
# Nothing else is written. No fan, no MUX, no keyboard, no BIOS setting.

set -u
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

out="$(dirname "$(readlink -f "$0")")/omen-8746-check-$(date +%Y%m%d-%H%M%S).txt"
exec > >(tee "$out") 2>&1

hr()  { printf '\n==================== %s\n' "$1"; }
run() { printf '\n$ %s\n' "$*"; "$@" 2>&1; }
cat_all() { for f in "$@"; do [ -e "$f" ] && printf '%s = %s\n' "$f" "$(cat "$f" 2>&1)"; done; }

HPDEV=/sys/devices/platform/hp-wmi
ECIO=/sys/kernel/debug/ec/ec0/io

ec_dump() {   # $1 = label
    if [ -r "$ECIO" ]; then
        echo "-- EC dump: $1"
        xxd -g1 "$ECIO" | sed -n '1,16p'
        printf 'EC[0x29] = 0x%s   EC[0x95] = 0x%s\n' \
            "$(xxd -s 0x29 -l 1 -p "$ECIO")" "$(xxd -s 0x95 -l 1 -p "$ECIO")"
    else
        echo "-- EC dump: $1: $ECIO not readable (ec_sys missing or lockdown)"
    fi
}

hr "1. Identity"
run uname -a
cat_all /sys/class/dmi/id/{sys_vendor,product_name,board_name,board_version,bios_version,bios_date}
run cat /proc/cmdline
run cat /sys/kernel/security/lockdown
run mokutil --sb-state

hr "2. Drivers and WMI devices"
run lsmod
run ls /sys/bus/wmi/devices
for d in /sys/bus/wmi/devices/*; do
    printf '%s  driver=%s\n' "$(basename "$d")" "$(basename "$(readlink "$d/driver" 2>/dev/null)" 2>/dev/null)"
done

hr "3. Boot log (hp, wmi, ACPI errors)"
dmesg | grep -iE 'hp[-_]wmi|hp-bioscfg|bioscfg|wmi|WMAA|WMID|EC0|platform.profile|ACPI (BIOS )?Error' | head -200

hr "4. platform_profile at boot (before we touch anything)"
cat_all /sys/firmware/acpi/platform_profile /sys/firmware/acpi/platform_profile_choices
for p in /sys/class/platform-profile/*; do cat_all "$p/name" "$p/profile" "$p/choices"; done

hr "5. hwmon (finding §1 predicts fan1/fan2 = 0 RPM)"
for h in /sys/class/hwmon/hwmon*; do
    printf '\n[%s] name=%s\n' "$h" "$(cat "$h/name" 2>/dev/null)"
    [ "$(cat "$h/name" 2>/dev/null)" = "hp" ] && { ls "$h"; cat_all "$h"/fan*_input "$h"/pwm*; }
done
command -v sensors >/dev/null && run sensors

hr "6. gpu_mux_mode (finding §3 predicts: read fails, EINVAL)"
if [ -e "$HPDEV/gpu_mux_mode" ]; then
    printf 'read: '; cat "$HPDEV/gpu_mux_mode" 2>&1
else
    echo "no gpu_mux_mode attribute (kernel older than 7.3?)"
fi
run lspci -nnk
run nvidia-smi -L

hr "7. EC registers, read-only (finding §2: profile at 0x29 bits 0-1; 0x95 inside battery name)"
modprobe ec_sys 2>&1 || true            # no write_support: reads only
ec_dump "boot state"
cat_all /sys/class/power_supply/BAT*/model_name /sys/class/power_supply/BAT*/manufacturer

hr "8. Reload hp-wmi with AML debug output (identifies the WMAA abort)"
echo "Before: platform_profile=$(cat /sys/firmware/acpi/platform_profile 2>&1)"
echo 1 > /sys/module/acpi/parameters/aml_debug_output 2>/dev/null \
    && echo "aml_debug_output enabled" || echo "could not enable aml_debug_output"
dmesg -C 2>/dev/null
modprobe -r hp_wmi 2>&1; sleep 1; modprobe hp_wmi 2>&1; sleep 2
echo "-- dmesg during hp-wmi probe:"
dmesg | grep -vE 'audit|apparmor' | head -150
echo 0 > /sys/module/acpi/parameters/aml_debug_output 2>/dev/null
echo "After reload: platform_profile=$(cat /sys/firmware/acpi/platform_profile 2>&1)"
ec_dump "after hp-wmi reload"

hr "9. Profile round trip: cool -> performance -> balanced (HP-observed payloads only)"
cat_all /sys/class/power_supply/A*/online
if [ -w /sys/firmware/acpi/platform_profile ] && grep -qw cool /sys/firmware/acpi/platform_profile_choices 2>/dev/null; then
    for p in cool performance balanced; do
        echo $p > /sys/firmware/acpi/platform_profile; sleep 2
        echo "set $p -> reads $(cat /sys/firmware/acpi/platform_profile)"; ec_dump "after $p"
    done
    echo "Expectation if §2 is right: EC[0x29] low 2 bits go 2 -> 1 -> 0; EC[0x95] never changes."
else
    echo "platform_profile not writable or no 'cool' choice - skipped"
fi

hr "10. BIOS settings via hp-bioscfg (read-only)"
B=/sys/class/firmware-attributes/hp-bioscfg/attributes
if [ -d "$B" ]; then
    for a in "$B"/*/; do
        n=$(basename "$a")
        printf '%-45s = %s\n' "$n" "$(cat "$a/current_value" 2>/dev/null)"
    done | grep -viE 'serial|uuid|mac address|digital marker|ct number'
else
    echo "hp-bioscfg attributes not present"; run modprobe hp-bioscfg; ls "$B" 2>&1 | head
fi

hr "11. Audio"
run aplay -l
run arecord -l
grep -H -iE '^Codec|Subsystem Id' /proc/asound/card*/codec#* 2>/dev/null
dmesg | grep -iE 'sof|snd_hda|alc285|dmic' | head -40

hr "12. Sleep and battery"
cat_all /sys/power/mem_sleep /sys/power/state
ls /sys/class/power_supply/BAT*/ 2>/dev/null

hr "13. Keys (optional, 20 s): press the OMEN key, then the keyboard-backlight key"
dev=$(grep -l 'HP WMI hotkeys' /sys/class/input/event*/device/name 2>/dev/null | head -1)
if [ -n "$dev" ] && command -v evtest >/dev/null; then
    node=/dev/input/$(basename "$(dirname "$(dirname "$dev")")")
    echo "listening on $node (HP WMI hotkeys) ..."
    timeout 20 evtest "$node" 2>&1 | tail -40
    dmesg | grep -i 'unknown key' | tail -10
else
    echo "skipped (evtest not installed or no HP WMI hotkeys device)"
fi

hr "done"
echo "Saved to: $out"
