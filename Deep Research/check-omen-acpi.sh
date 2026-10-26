#!/usr/bin/env bash
# check-omen-acpi.sh — static, read-only check of HP OMEN ACPI tables.
# Nothing here calls firmware: it only decompiles table dumps and greps them.
#
# Get the input on a Linux live USB (acpidump only reads tables, runs no AML):
#   sudo acpidump > acpi.txt
#   ./check-omen-acpi.sh acpi.txt
# Or pass a directory that already holds dsdt.dat / facp.dat / nhlt.dat / ssdt*.dat.
# Needs: acpica-tools (iasl, acpixtract).
set -u
in="${1:?usage: $0 <acpidump.txt | dir-with-.dat-files>}"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
if [ -d "$in" ]; then cp "$in"/*.dat "$work"/; else cp "$in" "$work/dump.txt"; (cd "$work" && acpixtract -a dump.txt >/dev/null); fi
cd "$work" || exit 1
for t in dsdt facp nhlt; do [ -f $t.dat ] && iasl -d $t.dat >/dev/null 2>&1; done
D=dsdt.dsl; [ -s $D ] || { echo "no DSDT decompiled"; exit 1; }

body() { awk -v m="Method ($1," 'index($0,m){f=1} f&&/Method \(/&&!index($0,m){exit} f' "$D"; }
hr() { printf '\n== %s\n' "$1"; }

hr "Board (DSDT OEM Table ID)  [878A / 8786 = siblings analysed]"
grep -m1 'OEM Table ID' $D

hr "Implemented HP WMI commands (firmware debug strings)"
grep -o 'HP WMI Command[^"]*' $D | sort -u | sed 's/^/  /'

hr "Fan interface GM2D / GM2E / GM2F   [878A: all present; GM2E writes SRP1/SRP2 after an SMI]"
for m in GM2D GM2E GM2F; do
  b=$(body $m)
  if [ -z "$b" ]; then echo "$m: ABSENT"; continue; fi
  printf '%s: present; SMI=%s; EC fields touched: %s\n' $m \
    "$(grep -q WSMI <<<"$b" && echo yes || echo no)" \
    "$(grep -o 'EC0\.[A-Z0-9]\{3,4\}' <<<"$b" | sort -u | tr '\n' ' ')"
  grep -q 'EC0\.' <<<"$b" || echo "   ($m is SMM-only: its behaviour is not visible in ASL)"
done

hr "EC offsets   [878A: SRP1=0x34  HPCM=0x95  RPM1=0xB0]"
awk '/OperationRegion \(ERAM/{f=1} f&&/Offset \(/{o=$0} f&&/(SRP1|SRP2|HPCM|RPM1|RPM3|KBT0),/{gsub(/[ \t]/,"",o);gsub(/[ \t]/,"");print $0"  (in block starting "o")"}' $D | head

hr "GM28 system design data   [878A & 8786: byte 7 never set -> 7.3 gpu_mux_mode writes fail with EOPNOTSUPP]"
b=$(body GM28)
echo "bytes assigned: $(grep -o 'Local0 \[0x02\]) \[[^]]*\]' <<<"$b" | sed 's/.*\[//;s/\]//' | sort -u | tr '\n' ' ')"
if grep -q '\[0x07\]' <<<"$b"; then echo "byte 7 IS set -> read its value before any MUX write"; else echo "byte 7 NOT set -> MUX mask reads 0 (same as siblings)"; fi
grep -q '\[0x03\]' <<<"$b" && echo "byte 3 (policy version) set: $(grep '\[0x03\]' <<<"$b" | head -1 | sed 's/.*= //')" || echo "byte 3 not set (policy V0; kernel forces V0 on 8746 anyway)"

hr "0x52 graphics-mode handlers   [siblings: read+write present, via SMI]"
grep -o 'HP WMI Command 0x52 ([^)]*)' $D | sort -u

hr "GM2B keyboard type mapping   [878A: KBT0 1->3 per-key, 2->1/2 four-zone]"
body GM2B | grep -E 'KBT0 ==|\[Zero\] =' | sed 's/^ *//'

hr "Sleep   [878A & 8786: S3 present, LPS0 = 0 -> mem_sleep 'deep']"
grep -o 'Name (_S[0-5]_\?' $D | sort -u | tr '\n' ' '; echo
[ -f facp.dsl ] && grep -i 'Low Power S0' facp.dsl || echo "facp not available"

hr "NHLT microphones   [878A: PDM array, 2 mics]"
[ -f nhlt.dsl ] && grep -iE 'Type PDM|Microphone Count' nhlt.dsl || echo "nhlt not available"
