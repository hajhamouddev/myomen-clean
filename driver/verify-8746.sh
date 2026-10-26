#!/usr/bin/env bash
# verify-8746.sh — check the patched hp-wmi on board 8746.
#
#   sudo bash verify-8746.sh      # writes verify-8746-<date>.txt next to itself
#
# Writes to firmware: platform_profile low-power -> performance -> balanced, i.e. the
# V0 payloads {FF,02} {FF,01} {FF,00}, all observed from OMEN Gaming Hub on this
# machine; and one keyboard colour round trip on the WASD zone. Everything else
# is a read. EC access is read-only (ec_sys without
# write_support).

set -u
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
out="$(dirname "$(readlink -f "$0")")/verify-8746-$(date +%Y%m%d-%H%M%S).txt"
exec > >(tee "$out") 2>&1

PP=/sys/firmware/acpi/platform_profile
ECIO=/sys/kernel/debug/ec/ec0/io
modprobe ec_sys 2>/dev/null || true
ec() { [ -r "$ECIO" ] && printf '0x%s' "$(xxd -s "$1" -l 1 -p "$ECIO")" || echo "n/a"; }
hw() { for h in /sys/class/hwmon/hwmon*; do [ "$(cat "$h/name")" = hp ] && echo "$h"; done; }

echo "== module"
uname -r
echo "file:   $(modinfo -n hp_wmi)"
echo "signer: $(modinfo -F signer "$(modinfo -n hp_wmi)" 2>/dev/null)"
lsmod | grep -E '^hp_wmi' || echo "hp_wmi NOT loaded"
dmesg | grep -iE '8746 quirk|hp_wmi|hp-wmi|platform_profile' | tail -10

echo; echo "== platform_profile"
echo "choices: $(cat $PP"_choices" 2>&1)"
echo "current: $(cat $PP 2>&1)   EC[0x29]=$(ec 0x29)"
echo "on AC:   $(cat /sys/class/power_supply/A*/online 2>/dev/null)"

echo; echo "== fans (EC[0x11] is an independent RPM/100 cross-check)"
H="$(hw)"
for i in 1 2 3; do
    [ -n "$H" ] && echo "fan1=$(cat "$H/fan1_input") fan2=$(cat "$H/fan2_input")  EC[0x11]=$(ec 0x11)"
    sleep 2
done

echo; echo "== profile holds still (event 0x1B loop check)"
seen="$(for i in $(seq 20); do cat $PP; sleep 0.1; done | sort -u | tr '\n' ' ')"
echo "20 reads over 2s: $seen"
[ "$(echo $seen | wc -w)" -eq 1 ] && echo "OK: stable" || echo "FAIL: profile is changing by itself - run: sudo bash install-8746.sh --remove"

echo; echo "== profile round trip"
if [ -w "$PP" ]; then
    orig="$(cat $PP)"
    for p in low-power performance balanced; do
        echo $p > $PP; sleep 3
        printf '%-12s -> reads %-12s EC[0x29]=%s  fan1=%s fan2=%s\n' "$p" "$(cat $PP)" "$(ec 0x29)" \
            "$(cat "$H/fan1_input" 2>/dev/null)" "$(cat "$H/fan2_input" 2>/dev/null)"
    done
    echo "expect EC[0x29] low bits: low-power(cool)=2 performance=1 balanced=0"
    [ "$orig" != balanced ] && echo "$orig" > $PP
else
    echo "platform_profile not writable/present"
fi

echo; echo "== keyboard RGB (kbd-rgb-v11.patch)"
dmesg | grep -iE 'keyboard RGB|multicolor' | tail -3
zones="$(ls -d /sys/class/leds/hp::kbd* 2>/dev/null)"
if [ -z "$zones" ]; then
    echo "no hp::kbd LEDs registered"
else
    for z in $zones; do
        printf '%-40s brightness=%-3s intensity=%s\n' "${z##*/}" "$(cat $z/brightness)" "$(cat $z/multi_intensity)"
    done
    # colour round trip on WASD: one LM03 table write each way, the layout OGH sends
    W=/sys/class/leds/hp::kbd_zoned_backlight-wasd
    # only with the backlight on: from off, a write turns the whole backlight
    # on, and nothing in the v11 interface can turn it off again
    if [ -d "$W" ] && [ "$(cat $W/brightness)" -eq 0 ]; then
        echo "backlight off - colour round trip skipped (turn it on with the backlight key to test)"
    elif [ -d "$W" ]; then
        oi="$(cat $W/multi_intensity)"; ob="$(cat $W/brightness)"
        echo "255 0 0" > $W/multi_intensity; echo 255 > $W/brightness; sleep 2
        echo "wasd set red -> reads intensity=$(cat $W/multi_intensity) brightness=$(cat $W/brightness)"
        echo "$oi" > $W/multi_intensity; echo "$ob" > $W/brightness
        echo "wasd restored -> intensity=$(cat $W/multi_intensity) brightness=$(cat $W/brightness)"
        echo "check by eye: WASD went red for 2s, then back"
    fi
fi

echo; echo "== power-profiles-daemon"
command -v powerprofilesctl >/dev/null && powerprofilesctl 2>&1 | head -20 || echo "ppd not installed"

echo; echo "Saved to: $out"
