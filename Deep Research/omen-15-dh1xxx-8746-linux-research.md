# Linux support for HP OMEN 15-dh1xxx (board 8746): what exists, what's missing

*Research date: 2026-09-26 · Kernel reference: mainline v7.3-rc4 · Target: Ubuntu/Kubuntu, kernel 6.x–7.x*

This consolidates four research passes into one document. Everything here comes from primary sources where possible:

- kernel source fetched at each tag from v5.15 to v7.3-rc4;
- lore / platform-driver-x86 threads;
- project repositories that were cloned and read;
- OmenMon source;
- linux-hardware.org probes;
- decompiled ACPI tables of two sibling boards.

**Method note.** The research skill's formal claim-verification and critic stages were not run, because no subagent tools were available. Every finding below was checked against source code or the original thread, not against summaries. Where evidence covers only the 15-dh1xxx family or sibling boards rather than board 8746 itself, that is stated.

---

## 1. Verdict

| Feature | Status on board 8746 | Confidence | Basis |
|---|---|---|---|
| Thermal modes (`platform_profile`) | **Works upstream** since 5.16: `cool` / `balanced` / `performance`, forced V0 policy | High (code); medium (no 8746 test report exists) | `hp-wmi.c` board lists |
| Fan RPM (hwmon `fan1/2_input`) | **Works upstream** (query 0x11) | Medium–high | `hp-wmi.c` |
| Fan control | **Partial**: `pwm1_enable` 0 = max, 2 = auto; 1 (manual) → `-EOPNOTSUPP` | High | `hp-wmi.c` |
| Fan curves / manual speed | **Missing**. Sibling firmware has the interface (`GM2D`/`GM2E`/`GM2F`), so a one-entry kernel patch is plausible | Medium (sibling evidence) | 878A/8786 DSDT, 8A13 precedent |
| Keyboard RGB | **Pending upstream**: v11 patch reviewed, not yet applied. Per-key SKUs unsupported | High on status | lore |
| GPU MUX | Hardware MUX exists. 7.3 `gpu_mux_mode` reads work, but **writes likely fail** (firmware reports a zero mode mask) | Medium–high | probes, 878A/8786 DSDT, kernel code |
| Speakers / headphones | Audio device appears through SOF (`sof-hda-dsp`); speaker output not confirmed | Medium | linux-hardware probes |
| Internal mic | Siblings declare a 2-mic PDM array; SOF should handle it | Medium | 878A NHLT, forum history |
| Mute / mic-mute LEDs | **No quirk for `103C:8746`**; sibling boards have one | High (code) | `alc269.c` |
| OMEN key | Upstream code path exists; not tested on dh1 | Low–medium | `hp-wmi.c` |
| Airplane key (`HPQ6001`) | **Works upstream** (`wireless-hotkey`) | High | kernel source |
| Battery charge limit | **Missing upstream**; may exist as a BIOS setting via `hp-bioscfg` | Medium | kernel source |
| BIOS settings | `hp-bioscfg` should bind (all its GUIDs are present) | Medium | `hp-bioscfg` source + your `_WDG` dump |
| Suspend | Siblings: S3 present, no S0ix → `deep` by default | Medium (sibling) | 878A/8786 FADT |
| OMEN Audio Control (B&O / DTS) | **Not portable**; proprietary Windows audio processing | High | HP forums |

**Recommendation: adopt, don't build a kernel driver.** Unlike the Acer desktop in orion-sense, upstream already covers this exact board ID.

Build a thin GUI/CLI (reuse orion-sense's Qt frontend) on top of these standard interfaces:

- `platform_profile`
- hwmon
- `leds-class-multicolor`
- `gpu_mux_mode`
- `firmware-attributes`

Up to three small upstream patches may follow, each gated on evidence from your own machine (§8).

---

## 2. Upstream kernel coverage (`drivers/platform/x86/hp/hp-wmi.c`)

### 2.1 Board 8746 membership and behaviour

In v7.3-rc4, 8746 appears in:

- **`omen_thermal_profile_boards`**, which enables the OMEN profile path;
- **`omen_thermal_profile_force_v0_boards`**, together with 8607 and 8747–874A.

It does **not** appear in:

- `omen_timed_thermal_profile_boards` (8A15, 8A42, 8BAD);
- the Victus lists;
- `hp_wmi_feature_boards`, which gates manual fan control and the Victus-S / OMEN-v1 extras.

History, from comparing tags: 8746 has been listed since **v5.16**, and the force-V0 list arrived in **v5.18**. Manual PWM (`HWMON_PWM_INPUT`) arrived in **v7.0**, but only for feature boards. `gpu_mux_mode` is new in **v7.3**.

What the driver does on 8746:

- **Profile choices:** cool, balanced, performance.
- **Setting a profile:** GM command `0x20008`, type `0x1A`, payload `{0xFF, mode}`, where mode is 0x00 default, 0x01 performance or 0x02 cool.
- **Reading the profile:** EC read at **0x95**. The EC flag/timer writes at 0x62/0x63 happen only on timed boards, so **not on 8746**.
- **At probe:** re-sends the current profile, and sends `0x27 {0}` (max fan off) during hwmon init. Loading `hp-wmi` is therefore not write-free, but these are the payloads upstream sends to every listed board.
- **On AC plug-in:** re-applies the chosen profile.
- **hwmon:** `fan1_input`/`fan2_input` via query 0x11, and `pwm1_enable` only. There is no `pwm1`.

### 2.2 Origin and testing

- OMEN support came from Enver Balalic, "hp-wmi: add support for omen laptops" (5.16). It added hwmon fans, the three profiles and the max-fan toggle. It was tested on a 2020 OMEN 15 **AMD 15-en0023dx**, not on 8746.
- The V0/V1 split is commit `286e937efbc7` (v5.18). Board IDs come from OCC's capability JSON, and the force-V0 list mirrors what OCC does, for reasons nobody documented.
- **No lore report tested on 8746–874A was found.**

### 2.3 Fan control upstream

- Manual PWM ("Victus S" path) came from Krishna Chomal's series, tested on 8C78. It uses:
  - type **0x2E** with RPM/100 values, clamped to the **0x2F** fan table;
  - a 90 s keep-alive, because the firmware reverts after 120 s.
- There is no fan-curve ABI upstream.
- Maintainers want per-board opt-in through `hp_wmi_feature_boards`, because forcing calls on unsupported boards has broken profile switching before.
- **Precedent:** the 8A13 patch (OMEN 16-b1xxx, May 2026) added a *legacy-EC* OMEN (profile at 0x95) to the manual-fan path, because its firmware implements `GM2D`/`GM2E` with setpoints at EC 0x34/0x35. Krishna noted the Victus-S list entry alone is enough. Ilpo turned the patch away because it was signed with a pseudonym; a real-name sign-off is required.

### 2.4 `hp-bioscfg`

It requires the BIOS GUID `5FB7F034` plus the set-setting GUID `1F4C91EB`. Your `_WDG` dump has both, as well as the string, integer, enumeration, ordered-list and password GUIDs (`988D08E3`, `8232DE3D`, `2D114B49`, `14EA9746`, `322F2028`).

It should therefore bind and expose `/sys/class/firmware-attributes/hp-bioscfg/`. Binding has not been observed yet. `8F1F6435/6`, `7391A661` and `DF4E63B6` remain unidentified.

### 2.5 Keyboard RGB

**The series:** "Add multicolor LED support for HP keyboard backlight", originally by Edip Hazuri, now carried by Konenko A.V. It went through v1–v11.

- **Review history:**
  - Hans de Goede acked the naming on v8 (8 June).
  - Ilpo flagged corrupted long lines (10 June).
  - v11 was rebased on linux-next and got Hans's Reviewed-by (14 September 2026).
- **Status:** **no "applied" reply exists, and it is not in 7.3-rc4.** One mirror's "queued as `79ac28f175e0`" label is a false match. That commit is the LED naming *documentation*, which is already in mainline.
- **Possible blocker:** the documentation names the zones `right`, **`middle`**, `left` and `wasd`, while v11 uses **`center`**. Hans had asked for `-middle` in his v6 review.
- **What it does:**
  - reads the keyboard type with `0x20008`/`0x2B`;
  - reads and writes a 128-byte colour table with `0x20009` types 0x02/0x03 (RGB at offset 25, 3 bytes per zone);
  - handles brightness with types 0x04/0x05 (0xE4 = on, 0x64 = off);
  - filters event 0x0D so the backlight key updates the LED state.
  These payloads match OmenMon and pelrun independently.
- **Keyboard types handled:** 1/2 (4-zone) and 4/5 (single zone). **Type 3 (per-key) gets nothing.**
- **Plan:** use v11 as a DKMS module; treat inclusion in 7.4 as a bonus.

### 2.6 GPU MUX (`gpu_mux_mode`, v7.3)

- Author: Kürşat Abaylı. Applied by Ilpo as commit `59f586eb9394`. No tested hardware is stated.
- The attribute is always created.
- **Reading** issues a READ of 0x52.
- **Writing** sends the index (0 Hybrid, 1 Discrete, 2 Optimus, 3 UMA) to 0x52. That encoding matches OmenMon's GpuMode enum from OCC.
- **The supported-mode mask** comes from byte 7 of system-design query 0x28. The driver falls back to a legacy Hybrid + Discrete mask only if the 0x28 query itself *fails*.
- **Problem on this family:** both sibling firmwares answer 0x28 successfully without ever setting byte 7 (§5). The mask is therefore 0 and **every write returns `-EOPNOTSUPP`**. This fails safe but doesn't work.

---

## 3. Out-of-tree and userspace projects

None of these projects list 15-dh1xxx or 8746 as tested.

| Project | Last commit | Licence | Method | Tested on | Safety-rule status |
|---|---|---|---|---|---|
| pelrun/hp-omen-linux-module | 2021-05 | GPL-2.0 | patched hp-wmi, 4-zone WMI | not stated | method OK; stale |
| OmenLinux/omen-rgb-keyboard | 2026-09-08 | GPL-3.0 | own WMI module; HDA codec mute LED | 15-dh0025nl (board 8600), 15-en1004ns, several 16s | asks you to blacklist hp_wmi; audit before use |
| hippomasters/omen-rgb-linux | 2026-09-26 | GPL-2.0 | WMI with exact DMI/BIOS lock | 8BAB / F.26 only | **best safety model**; refuses 8746 |
| TitanHZZ/omen-keyboard-rgb-linux | 2024-04 | MIT | WMI | not stated | method OK |
| alou-S/omen-fan | 2026-01 | GPL-3.0 | **`ec_sys write_support=1`**, writes EC 0x34 | 16-c0140AX | **breaks rule** |
| yunusemreyl/omen-space | 2026-09-26 | GPL-3.0 | patched hp-wmi + **EC writes via ec_sys**, MSR undervolt | 8746 not listed | **breaks rule** unless the EC path is disabled |
| arfelious/omen-fan-control | 2026-09-24 | GPL-3.0 | backported hp-wmi; "cleaner" uses **raw `acpi_call`** types 0x2C/0x2E | 88C8, 8BCA, 8D41 and others | cleaner **breaks rule** |
| openomen/openomen | 2026-08-22 | GPL-3.0 | upstream hp-wmi sysfs | "OMEN 15" (unspecified) | OK |
| emomaxd/hpfand | 2026-07-20 | GPL-2.0 | upstream `pwm1` only | Victus/Omen | OK, but needs `pwm1`, which 8746 lacks |
| Batuhan4/victus-control | 2026-09-24 | GPL-3.0 | hp-wmi sysfs + scripts | Victus | not audited |
| **NBFC-Linux** | 2026-09-26 | GPL-3.0 | **direct EC writes** | no 15-dh1xxx config | **breaks rule** (see below) |

**NBFC warning.** Its "HP OMEN Notebook PC 15" config writes EC **0x94** and reads **0x95**. On this family, 0x95 is the thermal-profile byte (`HPCM`). The other OMEN configs (15-en0, 15-dc) also write the EC directly.

**OmenMon** (Windows, GPL-3.0, last commit 2024-05) documents the BIOS calls:

| Command | Types |
|---|---|
| `0x20008` | 0x10 fan count, 0x1A mode, 0x21/0x22 GPU power, 0x23 temperature, 0x26/0x27 max fan, 0x28 system data, 0x29 CPU power, 0x2B keyboard type, 0x2D/0x2E fan level, 0x2F/0x32 fan table |
| `0x20009` | keyboard |
| cmd 2, type `0x52` | GPU mode |

**Flag:** OmenMon's fan array defaults to EC registers taken from the **8A14** DSDT, with write access. Do not use its fan control on 8746. It was not tested on 15-dh1xxx.

**General tools:**

- **CoolerControl / fancontrol:** need a writable `pwmN`, which 8746 doesn't expose.
- **OpenRGB:** only an open device request for the 2020 OMEN 15; no support.
- **power-profiles-daemon and tuned:** see §4.

---

## 4. Power-profile daemons vs the OMEN "cool" mode

- **power-profiles-daemon 0.30** (Ubuntu archive source, `ppd-driver-platform-profile.c`):
  - It only counts a platform as having a power-saver mode if the choices include `low-power` or `quiet`. On 8746 the choices are `cool balanced performance`.
  - Power-saver therefore **writes `balanced`**; the actual saving comes from PPD's CPU driver.
  - Reading back, it treats `cool` as balanced.
- **tuned** (September 2026 source, `plugin_acpi.py`):
  - The `powersave` profile asks for `low-power|quiet`. tuned tries each name, and when none exist it logs warnings and an error and **writes nothing**. The rest of the profile still applies.
  - tuned-ppd's watcher maps only `low-power`, `quiet`, `balanced` and `performance`, so it ignores `cool`.
- **Consequence:** "cool" is reachable only by writing it directly. Both daemons will overwrite it with `balanced` or `performance` on profile switches and at boot. Your GUI should either own `platform_profile` itself or mask the daemon.
- **Possible upstream contribution:** a PPD patch so power-saver falls back to `cool`.

---

## 5. Firmware analysis of sibling boards 878A and 8786

No 8746 ACPI dump is public. The linuxhw/ACPI repository has dumps for **878A** (OMEN 15-ek0, Intel, 2020) and **8786** (OMEN 15-en0, AMD, 2020). Both are on the same upstream OMEN board list. They were decompiled with `iasl`.

### 5.1 The command handlers label themselves

Every handler starts with a debug string such as `"HP WMI Command type 0x2E for WMI 20008h command"`. Searching for `Debug = "HP WMI` therefore lists every command the firmware implements, offline.

### 5.2 Findings

| Item | 878A (Intel) | 8786 (AMD) |
|---|---|---|
| `GM01`–`GM30` present | yes | 48 GM methods |
| `GM1A` (profile) | writes EC `HPCM` at **0x95** | – |
| `GM27` (max fan) | sets EC bit `FFFS` | – |
| `GM2D` (fan speed read) | SMI, then reads `RPM1`–`RPM4` (EC **0xB0–0xB3**), returns RPM/100 | SMM only (`WSMI` + return) |
| `GM2E` (fan speed set) | SMI, then writes payload bytes 0/1 to `SRP1`/`SRP2` (EC **0x34/0x35**) | SMM only |
| `GM2F` (fan table) | static table: 2 fans, 12 or 14 rows by SKU (≈2,300–5,800 RPM); parses cleanly with the kernel's `victus_s_fan_table` | SMM only |
| EC layout | `SRP1` 0x34, `HPCM` 0x95, `RPM1` 0xB0 | `SRP1` 0x34, `HPCM` 0x95, `RPM1` 0xAF |
| `GM28` system data | sets bytes 0, 2–5 (byte 3 = 1, i.e. policy V1); **byte 7 never set** | sets byte 0 only; **byte 7 never set** |
| 0x52 MUX read/write | present, via SMI | present |
| `GM2B` keyboard type | EC `KBT0`: 0 → none, 1 → **3 (per-key)**, 2 → 1/2 (4-zone, numpad chosen by GPIO) | 0 → none, 2 → 2 |
| Sleep | `_S3` present, FADT Low Power S0 Idle = 0 | same |
| NHLT | PDM digital array, 2 microphones | – |

The fan table's third column is called noise (dB) by the kernel and temperature by OmenMon. It doesn't affect the kernel's min/max calculation.

### 5.3 What this means

- **Manual fan control:** the 2020 generation very likely has the Victus-S-style interface. Enabling it on 8746 would be a one-entry `hp_wmi_feature_boards` patch, following the 8A13 precedent. It is only justified if 8746's own DSDT matches and OCC's traffic confirms the payload.
- **MUX:** both siblings leave byte 7 unset, so 7.3 `gpu_mux_mode` writes almost certainly fail on this family. That is worth a bug report or patch; the obvious fix is to fall back to the legacy mask when the reported mask is 0. Meanwhile, switch GPU mode in BIOS setup or OCC.
- **Safety:** `GM2D`, `GM2E`, `GM2F` and the 0x52 handlers all call `WSMI`, which raises an SMI. Their payloads reach SMM code. This includes the read-only `GM2D`, which backs your rule that a "Get" is not automatically safe. NBFC and alou-S/omen-fan write the same EC bytes directly, bypassing the firmware handler entirely.

---

## 6. Everything else on the machine

### 6.1 Graphics

- The 2020 OMEN 15 line has a Hybrid/Discrete Graphics Switcher; this is family-level evidence.
- linux-hardware.org lists **17** 15-dh1xxx machines. All but one report Nvidia-only graphics; one reports Intel + Nvidia. That split confirms a working MUX, and that Discrete mode is common. It matches your Windows view with no iGPU.
- In Discrete mode Linux sees only the NVIDIA GPU, so `prime-select` and `envycontrol` don't apply.

### 6.2 Audio

**Kernel quirk table.** In `sound/hda/codecs/realtek/alc269.c` (v7.3-rc4) there is **no entry for `0x103c, 0x8746`**, nor for 8747–874A.

- Siblings 8786/8787/8788 ("HP OMEN 15") and 8603 (OMEN 17-cb0) use `ALC285_FIXUP_HP_MUTE_LED`.
- That fixup drives the mute LED through codec coefficient 0x0B bit 3 and the mic-mute LED through coefficient 0x19 bit 13.
- OmenLinux independently toggles coefficient 0x0B for the mute LED.

**What works.** Probes of 8746 show the `sof-hda-dsp` card with HDA Analog next to NVIDIA HDMI. One matches your hardware: Mint 21.3, kernel 5.15, RTX 2060 `10de:1f15:103c:8746`, BIOS F.36. Speakers and headphones should work through the generic ALC285 path. The LEDs probably don't, if the chassis has them.

**Internal mic.**

- 2020-era OMEN mic failures came from forcing the legacy HDA driver (`dsp_driver=1`) or disabling the DMIC (`dmic_detect=0`), and from old SOF firmware.
- Keep SOF with current `sof-firmware` / `firmware-sof-signed`, and don't use those two options.
- Verify with `arecord -l`, where a DMIC device should appear.

**OMEN Audio Control** is B&O speaker presets and EQ, plus DTS:X Ultra / Headphone:X for headphones. It is proprietary Windows audio processing and nothing is portable. The Linux equivalent is a PipeWire filter chain or EasyEffects with your own tuning.

### 6.3 Hotkeys and extras

- **OMEN key:** upstream handles event 0x1D (payload or 0x0C hotkey query) and event 0x04 (reads 0x0C), with 0x21a5 mapped to `KEY_PROG2`. On the 15-dh0 (8600) the key sends event 0x4 with an empty payload. Untested on dh1.
- **Backlight key:** upstream ignores the 0x21aa codes and event 0x0D; v11 handles 0x0D.
- **Airplane key:** `drivers/platform/x86/wireless-hotkey.c` binds `HPQ6001` and reports `KEY_RFKILL`.
- **Touchpad:** ELAN0711 is detected in the probes.
- **Battery limit:** there is no `charge_control_end_threshold` in `hp-wmi`. Check `hp-bioscfg` attributes for a battery-care option.
- **Suspend:** the siblings indicate S3 / `deep`. With the proprietary NVIDIA driver this relies on the nvidia-suspend services.

### 6.4 Keyboard variants

The 2020 OMEN 15 line shipped with standard backlighting, 4-zone RGB, or optional per-key RGB. 15-dh1 retail listings advertise 4-zone. Your PS/2 keyboard with no USB lighting controller suggests WMI-controlled 4-zone, but that is not verified. The sibling firmware confirms the per-key type exists in this family.

---

## 7. Safety-rule summary

| Action | Payload traceable? | Verdict |
|---|---|---|
| Loading upstream `hp-wmi` (0x1A re-send, 0x27 {0}, reads 0x11/0x0C/0x28) | yes: upstream sends these on every listed board | acceptable |
| `platform_profile` changes | yes: upstream V0 values, which mirror OCC | acceptable |
| `pwm1_enable` 0/2 | yes: upstream | acceptable |
| `gpu_mux_mode` read | yes: upstream | acceptable |
| `gpu_mux_mode` write | encoding matches OmenMon/OCC, but untested on 8746 and likely to be refused | don't rely on it; compare with an OCC capture first |
| v11 keyboard RGB | matches OmenMon and pelrun | acceptable after a read-only check of the 0x2B result |
| Manual fan (0x2E) on 8746 | not yet: needs a DSDT check plus an OCC capture | **blocked** until both exist |
| NBFC, omen-fan, omen-space EC path, arfelious cleaner, OmenMon fan control | invented or foreign-board values | **do not use** |

---

## 8. Gaps and planned contributions

**Gaps with no existing solution for 8746:**

1. Manual fan speed and curves.
2. Keyboard RGB until v11 merges; per-key SKUs indefinitely.
3. Working MUX writes from Linux.
4. Mute and mic-mute LEDs.
5. A Linux replacement for the B&O/DTS audio tuning.

**Candidate contributions, each gated on evidence:**

1. **Audio quirk:** add `SND_PCI_QUIRK(0x103c, 0x8746, …, ALC285_FIXUP_HP_MUTE_LED)`, if the LEDs exist and a test passes.
2. **Manual fan:** an `hp_wmi_feature_boards` entry for 8746, if the DSDT shows the `GM2D`/`GM2E`/`GM2F` interface and an OCC capture confirms the payloads.
3. **MUX fix:** a `gpu_mux_mode` report or patch for the zero-mask case.
4. **PPD:** a fallback from power-saver to `cool`.
5. **Keyboard:** a v11 test report on 8746, noting the `center`/`middle` naming.

---

## 9. What to measure

### 9.1 Offline, with no firmware calls

Run the accompanying `check-omen-acpi.sh` on a table dump. `acpidump` only reads tables and runs no AML.

```
sudo acpidump > acpi.txt          # from a Linux live USB
bash check-omen-acpi.sh acpi.txt  # needs acpica-tools
```

It reports, each next to the 878A/8786 result:

- the board ID;
- every implemented WMI command;
- whether `GM2D`/`GM2E`/`GM2F` exist and which EC fields they touch;
- the EC offsets;
- which `GM28` bytes are set (especially byte 7);
- the 0x52 handlers;
- the `GM2B` keyboard-type mapping;
- sleep states and the FADT LPS0 flag;
- the NHLT microphones.

Your Windows registry dump may lack `FACP`/`NHLT`; a live-USB `acpidump` is complete.

### 9.2 On Windows

- Check whether OCC offers manual fan or fan curves on this model at all.
- If it does, capture the payloads OCC sends.
- Check whether the chassis has mute and mic-mute LEDs.

### 9.3 On a Linux live USB (7.3 kernel preferred)

```
uname -r; cat /sys/class/dmi/id/board_name
ls /sys/bus/wmi/devices; lsmod | grep -E 'hp_wmi|bioscfg'
dmesg | grep -i -E 'hp|wmi'
cat /sys/firmware/acpi/platform_profile{,_choices}         # expect: cool balanced performance
sensors; ls /sys/devices/platform/hp-wmi/hwmon/hwmon*/      # expect fan1/2_input, pwm1_enable, no pwm1
cat /sys/devices/platform/hp-wmi/gpu_mux_mode               # read only
ls /sys/class/firmware-attributes/*/attributes | grep -i -E 'batt|graph|switch'
lspci -nnk | grep -A3 -E 'VGA|3D'
grep -i -E 'codec|subsystem' /proc/asound/card*/codec#*
arecord -l                                                  # DMIC should appear
cat /sys/power/mem_sleep
ls /sys/class/power_supply/BAT*/
evtest                        # press the OMEN key and the backlight key
dmesg | grep -i "unknown key"
powerprofilesctl set power-saver; cat /sys/firmware/acpi/platform_profile
```

---

## 10. Still open

| Item | Why it is open | How it closes |
|---|---|---|
| 878A/8786 findings on 8746 itself | no public 8746 ACPI dump | run `check-omen-acpi.sh` on your dump |
| OCC payloads for fan and MUX | only observable on Windows | capture on your machine |
| Runtime behaviour (OMEN key, LEDs, mic, jack, suspend) | needs the hardware | live-USB checks (§9.3) |
| RGB patch in 7.4 | maintainer hasn't applied it; naming mismatch | recheck the platform-drivers-x86 `review-ilpo-next` branch in 2–3 weeks |
| tuned's side effects when no profile matches | minor; not traced beyond the ACPI plugin | read tuned's profile-apply path if it matters |

---

## 11. Sources

**Kernel source (torvalds/linux on GitHub, read at the named tags)**
- `drivers/platform/x86/hp/hp-wmi.c`, v5.15–v7.3-rc4 (v5.16/v5.17 at `drivers/platform/x86/hp-wmi.c`)
- `drivers/platform/x86/hp/hp-bioscfg/bioscfg.{c,h}` (master)
- `drivers/platform/x86/wireless-hotkey.c` (master)
- `sound/hda/codecs/realtek/alc269.c` (master)
- `Documentation/leds/leds-class.rst` (v7.2, master)
- commit `79ac28f175e0`: leds documentation, keyboard backlight naming

**Mailing lists (lore mirrors: lkml.iu.edu, spinics, ratatoskr.run, patchew)**
- Balalic, "hp-wmi: add support for omen laptops" v5, and Hans de Goede's reply (Sep 2021): https://lkml.iu.edu/hypermail/linux/kernel/2109.1/05476.html
- "support omen thermal profile policy v1" (Mar 2022): https://patchew.org/linux/20220313190532.vpeuytz2ergnfsyt@omen/
- Phoronix, Linux 5.18 OMEN thermal policy: https://www.phoronix.com/news/Linux-5.18-HP-Omen-Thermal
- Keyboard multicolor LED series v6–v10: https://ratatoskr.run/platform-driver-x86/2026/04/3535841/t
- Keyboard multicolor LED v11 + Hans's review: https://ratatoskr.run/platform-driver-x86/2026/09/17571031
- GPU MUX switch v5, applied: https://ratatoskr.run/lkml/2026/07/17311174/t
- Victus S manual fan series (Chomal): https://lkml.iu.edu/2512.3/04738.html
- OMEN 16-b1xxx (8A13) support + per-fan PWM: https://ratatoskr.run/platform-driver-x86/2026/05/9004910/t
- cTGP/PPAB for 8C58, with the review on feature boards: https://ratatoskr.run/lkml/2026/09/17507832/t
- OMEN 16-am2xxx (8F1C): https://ratatoskr.run/platform-driver-x86/2026/08/17477872

**Projects (cloned and read)**
- OmenMon: https://github.com/OmenMon/OmenMon
- pelrun/hp-omen-linux-module, OmenLinux/omen-rgb-keyboard, hippomasters/omen-rgb-linux, TitanHZZ/omen-keyboard-rgb-linux, alou-S/omen-fan, yunusemreyl/omen-space, arfelious/omen-fan-control, openomen/openomen, emomaxd/hpfand, Batuhan4/victus-control, evident0/victus-hub, saikiranworks/hp-omen-dkms, nbfc-linux/nbfc-linux (all on GitHub)
- power-profiles-daemon 0.30 source: http://archive.ubuntu.com/ubuntu/pool/main/p/power-profiles-daemon/
- tuned: https://github.com/redhat-performance/tuned
- linuxhw/ACPI (878A and 8786 dumps): https://github.com/linuxhw/ACPI

**Hardware data and owner reports**
- linux-hardware.org, 15-dh1xxx computers: https://linux-hardware.org/?view=computers&type=notebook&vendor=Hewlett-Packard&model=OMEN+by+Laptop+15-dh1xxx
- Probe 277cc8fa8b (Fedora 33, BIOS F.10): https://linux-hardware.org/?probe=277cc8fa8b
- Probe c1c82e2ff7 (Mint 21.3, RTX 2060, BIOS F.36): https://linux-hardware.org/?probe=c1c82e2ff7
- PCWorld, 2020 OMEN 15 Graphics Switcher: https://www.pcworld.com/article/399234/the-hp-omen-gaming-laptop-offers-amd-and-intel-flavors-for-1000-and-up.html
- OpenRGB issue #790: https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/790
- SOF issue #2097 (ALC285 OMEN 15 mic): https://github.com/thesofproject/linux/issues/2097
- Launchpad #1892714 (OMEN 17 mic): https://bugs.launchpad.net/bugs/1892714
- Linux Mint forum, 2019 OMEN 15t DMIC: https://forums.linuxmint.com/viewtopic.php?t=340466
- HP community, OMEN Audio Control / B&O / DTS: https://h30434.www3.hp.com/t5/Gaming-Notebooks/HP-Omen-15-dc1060nr-laptop-Bang-and-Olufsen-Enhanced-Output/td-p/7842093
- ArchWiki, HP Omen 16-c0140AX: https://wiki.archlinux.org/title/HP_Omen_16-c0140AX
