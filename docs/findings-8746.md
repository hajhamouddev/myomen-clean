# Board 8746 checked against the deep research

*2026-09-27. Machine: OMEN 15-dh1xxx, board 8746, BIOS F.44, Windows 11.*

The two deep-research reports in `Deep Research/` had no 8746 firmware to work
from. Both said no public dump existed, so they reasoned from sibling boards
878A and 8786. This file checks their conclusions against two sources from
**this machine**:

1. **Its own ACPI tables.** They were dumped from the Windows registry copy and
   decompiled with `iasl` 20260408. They are in `research/acpi/`, with
   `SHA256SUMS`; the `.dsl` line numbers below refer to
   `DSDT_DSDT_HPQOEM_8746.dsl`.
2. **OMEN Gaming Hub's own logs.** These are HP-authored and were written by
   HP's software on this laptop, 2026-09-03 to 2026-09-27, in
   `%LOCALAPPDATA%\Packages\AD2F1837.OMENCommandCenter_v10z8vjag6ke6\LocalCache\Local\HPOMEN\`.

Mainline `hp-wmi.c` was read at `master` on 2026-09-27.

Nothing was sent to firmware for this analysis (2026-09-27): every step was
a read of a file or a table. The dated sections §00 onwards record later tests
on the installed driver, which did write, each with HP-observed payloads.

---

## Summary: what changes

| Claim in the reports | On 8746 | Evidence |
|---|---|---|
| Fan RPM "works upstream" through query 0x11 | **No. `fan1/2_input` will read 0.** `GM11` returns a hard-coded zero buffer | DSL `GM11`; `hp_wmi_get_fan_speed()` returns `buf[2]<<8 \| buf[3]` |
| Thermal profile is read from EC 0x95 (`HPCM`) | **There is no `HPCM`.** The profile lives in `OCCM`, bits 0–1 of byte 0x29 of the EC memory window. The window's 0x95 lies inside the battery model-name string | DSL `GM1A`, `PECM`/`ECMM` field maps |
| `gpu_mux_mode` writes fail with `-EOPNOTSUPP` (mask 0) | Confirmed. **Reads fail as well: command 0x52 does not exist on this board** | `HWMC` dispatch has no 0x52; `GM28` byte 7 unset; HP log agrees |
| Manual fan (`0x2E`) is "plausible" as a one-entry patch | **HP's own software says no:** `IsSwFanControlSupport=False`. The handler exists, but HP never uses it here. Enabling it would send payloads HP does not send on this board | HP log; `GM28` byte 4 = 0 |
| The fan interface goes through SMI (`WSMI`) | No. `GM2D`/`GM2E`/`GM27` use an EC command mailbox (`ERCD`). `GM1A` does call `WSMI` | DSL |
| Thermal policy V0 | Confirmed from **HP's log** (`GetThermalPolicyVersion = V0`), even though firmware byte 3 says 1. The kernel's force-V0 list is right | HP log; `GM28` |
| Keyboard is 4-zone | Confirmed from **HP's log**: `keyboardType = 1`, `IsLightingSupported = 1` | HP log; `GM2B` |
| S3 / `deep` sleep | `_S3_` present | DSL |

---

## 00. Patched driver on installed Ubuntu (2026-09-28)

Ubuntu dual-boot, kernel 7.0.0-34. *Corrected 2026-09-28:* Secure Boot was
in fact **off** in the BIOS for this install (the verify reports show
`module verification failed … tainting kernel`), and the DKMS signing key was
never enrolled; the installer's check only ran with Secure Boot on. The key
was enrolled the same day (MokManager, 18:11) and Secure Boot switched on:
lockdown `integrity`, the key loaded into the kernel keyring, and `hp-wmi`
loads with only the out-of-tree taint (4096), no signature failure. `hp-wmi` is
built from Ubuntu's `linux-source` plus `kbd-rgb-v11.patch` and
`patch-8746.py`, and installed through DKMS. Reports are in `research/verify/`.

| | result |
|---|---|
| Modes | `choices: low-power balanced performance`. The round trip reads back exactly what was set, with EC[0x29] = 2 / 1 / 0. This proves the OCCM location and the EC-space = window assumption |
| power-profiles-daemon | `PlatformDriver: platform_profile` for all three, so the KDE power slider drives the firmware |
| Fan RPM | 2900–4700 RPM, always equal to EC[0x11] × 100 (`FRPM`). The 0x2D reading is confirmed by an independent source |
| Keyboard RGB | 4 zones as `hp::kbd_zoned_backlight-{right,center,left,wasd}`. WASD red and back, confirmed by eye |
| Stability | "profile holds still" check passes on every run after the event-0x1B fix |

**Safety events, recorded so they are not repeated:**

1. **Event-0x1B mode loop.** This was a hazard introduced by enabling the
   profile. `GM1A` raises WMI event `0x1B` after every mode write; I found
   that in §2 and even saw it in HP's log as `eventId=27`. Stock `hp-wmi` maps
   `0x1B` to the Fn+P key and calls `platform_profile_cycle()`, which writes
   the mode again and raises `0x1B` again. With the first build, this ran at
   ~700 mode writes/s (ftrace) until the module was replaced; see the first
   report, where the read-backs trail the writes.
   - The payloads stayed the three HP-observed ones, but the rate was far
     outside anything HP does.
   - **Fixed:** `0x1B` is ignored on 8746.
   - **Lesson:** when enabling a write path, trace every event the handler
     raises back through the driver's own event handler.
2. **Hard freeze while test-loading a patched `hp-bioscfg`**
   (`patch-bioscfg-8746.py`, ~13:50). The cause is unknown. That script is
   marked UNTESTED/DO-NOT-USE and is not used by the installer.
   - Loading `hp-bioscfg` enumerates BIOS settings through `WQxx` data-block
     methods, several of which raise SMIs (`WSMI 0xEA7B`, e.g. `WQBE`
     DSL line 67143). The patch made it walk far more instances than stock
     does.
   - Until it is understood with a serial or netconsole log, **Adaptive
     Battery Extender and Fan Always On stay BIOS-setup-only (F10).**

**Open, lower priority:**

- ~~**Backlight off.**~~ **Done 2026-09-28.** v11 turned the backlight "off"
  by writing black. The driver now sends HP's real off payload (type `0x05`,
  `0x64`, seen from OMEN Gaming Hub on this machine) when every zone is at 0;
  `LM05` clears `KBLS` (EC 0xA1 bit 0), which was read back 1 -> 0 -> 1.
- ~~**Colours reset at boot.**~~ **Handled by the app.** The EC still starts
  from red/green/blue/white; `omen-sense-apply.service` puts the last colours
  back at login.
- **`hp_wmi: Unknown event_id - 0 - 0x0`** appears a few times per session.
  Harmless noise; the source is not identified.

## 00a. Keyboard colour read bug, and the backlight key (2026-09-28)

Found while testing software lighting effects, which made the right side of
the keyboard flash.

**The colour-table read returns the wrong blue for zone 1.** In `LM02` (WMI
0x20009, type 0x02, DSDT line ~63500), byte 0x1B is filled from `Z02B`, not
`Z01B`:

```
DerefOf (Local0 [0x02]) [0x1B] = ^^PCI0.LPCB.EC0.Z02B   // should be Z01B
```

The write handler `LM03` uses `Z01B` correctly. Zone 1 in the table is the
driver's zone 0, the **Right** zone (EC 0x08-0x0A). The v11 driver writes a
zone by reading the whole table, changing three bytes and writing it back, so
**every write to Left, WASD or Centre copies Centre's blue into Right's blue.**

Proved read-only through `ec_sys` (no `write_support`), with Rainbow set:

| after | EC 0x08-0x0D (Right R G B, Centre R G B) |
|---|---|
| Rainbow layout | `02 0a e7 17 ed 07` |
| writing Left, same colour as before | `02 0a 07 17 ed 07` (Right's blue is now Centre's) |
| writing Right | `02 0a e7 17 ed 07` |

Effects: during an animation, Right is wrong for ~35 ms of every frame, which
shows as flashing. With plain colours, changing any other zone leaves Right's
blue wrong until Right is written again. HP's own software is not affected:
OMEN Gaming Hub writes the whole table from its own copy
(`inputData=3,0,…,0,<12 colour bytes>,0,…` in its log) and never reads it first.

**The backlight key is invisible to the driver.** Over three minutes of
pressing it, `brightness_hw_changed` never got a value and the kernel logged
nothing: the firmware toggles the backlight itself. v11's
`hp_kbd_set_brightness()` turns the backlight on whenever it finds it off, so
any colour write undoes the key.

Driver trace of Fire frames (ftrace function_graph, 81 zone writes): a zone
write is 3 WMI calls taking ~11 ms together, frames arrived exactly 201 ms
apart, and 2 of the 81 writes overlapped on different CPUs. v11 has no lock
around its read-modify-write, so an overlap can lose a zone's update.

**Fixed in the driver** (`patch-8746.py` edit 6, installed 2026-09-28): the
table is written from the driver's own record of the four zones, the way HP
does, with no read first, under a mutex; the backlight is switched on only
when a zone goes from 0 to lit; and zone 0's blue is read from EC 0x0A at
probe. Verified:

- EC after writing Left alone: `02 0a e7 17 ed 07`, Right's blue unchanged.
- Trace of Fire frames: 1 WMI call per zone write (was 3), ~2 ms (was ~11 ms).
- By eye: Rainbow wave no longer flashes, and the backlight key keeps the
  keyboard off while an effect runs, until it is pressed again.

## 00b. Audio: HP's DTS:X Ultra speaker tuning, decoded (2026-09-28)

Windows runs **DTS:X Ultra** on this laptop (not Bang & Olufsen), from the
Realtek driver's `dtsapo4ultraextensionpkg` package. Its `.inf` maps the
ALC285's `SUBSYS_103C8746` (also 8600-8607, 8747) to the tuning folder
**`HP103C8600`**: `dts_apo4_oem_config_103C8600.xml` plus binary tables.

**The XML** holds 24 operating modes (Off, Music, Movie, Voice, Game 1-3,
Custom Audio, each for internal speakers, headphones and external speakers).
For the internal speakers:

| mode | runs | high-pass | GPEQ biquads |
|---|---|---|---|
| Off | EFX chain only | 160 Hz, order 2 | 5 (notches 368-992 Hz) |
| Music, Movie | MFX + DTS effects | 100 Hz, order 4 | 11 |
| Voice | MFX + DTS effects | 180 Hz, order 4 | 11 |
| Game 1-3, Custom | MFX + DTS effects | 100 Hz, order 4 | 0 |

"DTS effects" = TruBass HD-X, MBHL limiter, dialogue enhancement, I3DA; their
parameters are in the XML, their algorithms are not.

**The GPEQ tables** (`dts_gpeq_*_{44,48}k_*.bin`, 4720 bytes): int32 header =
2 x biquad count, then 511; then 24-byte records, each an int32 giving the
integer bits (2 = Q2.30, 1 = Q1.31) and b0 b1 b2 a1 a2 with the denominator
`1 - a1 z^-1 - a2 z^-2`. Decoded this way all 38 filters are stable (largest
pole radius 0.995) with a DC gain of exactly 1.000. After the biquads come a
gain word (`1, 0x7fffffff`) and a table identical in every mode; that part is
not decoded (read as a Q31 FIR it gives an implausible +-27 dB).

**Headphones: there is no headphone EQ to reproduce.** The headphone modes
use `dts_hpeq_*.bin` (11552 bytes), a settings bundle for several DTS modules
(its header carries the XML's VAEQ 85/75/5 and the hearing-test values). Its
filters, decoded the same way: one at word 517 is a 60 Hz 2nd-order
Butterworth high-pass (poles exactly the textbook 1.9889 / -0.989) with a
-7.7 dB pad, and the 13-record EQ bank at words 539 and 1129 is exactly flat
(0.00 dB everywhere; one record, +106 dB as read, is a marker, not a filter).
That fits the XML: `Headphone Name = uuid` (no headphone model chosen) and
`PEREQ MODE = EQ Bypass`. So HP's headphone processing here is that high-pass
plus DTS's effects. The high-pass only removes bass headphones can play (DTS
adds it to feed TruBass), so headphones are deliberately left untouched.

**Used on Linux:** `omen-sense audio import` copies the high-passes and
biquads into `~/.config/omen-sense/dts-tuning.json` (HP/DTS data stays out of
the repository), and the presets run them as PipeWire `bq_raw` sections,
targeted at the speaker sink with `filter.smart.target = { node.name = ... }`
(WirePlumber ignores a bare string).

## 0. Live-USB results (2026-09-26)

Kubuntu 26.04 live, kernel 7.0.0-30, Secure Boot on (lockdown `integrity`), on
AC. The raw output is in
`research/live-usb/omen-8746-check-20260926-213848.txt`.

| Prediction | Result |
|---|---|
| §1: fans read 0 RPM | **Confirmed.** `fan1: 0 RPM`, `fan2: 0 RPM`; `pwm1_enable = 2` (auto), no `pwm1` |
| §2: profile read-back reads the wrong byte | **Confirmed, and worse than predicted.** EC[0x95] = `0x43` (`'C'`), inside the battery string `333-2C-11PG06069` at 0x90. It matches no profile value, so `thermal_profile_setup()` returns `-EINVAL` and **no `platform_profile` device is registered. Linux has no performance modes on this laptop at all.** The failure is silent: `hp_wmi_bios_setup` ignores the error |
| §2: profile lives at window/EC offset 0x29 | **Consistent.** EC[0x29] = `0x00`, and Windows was last left in Default. The rest of the dump fits the ASL window map at the same offsets: IR temperature `IRST` at 0xB7 = `0x2B` (43 °C) and zone colours at 0x08–0x0D / 0x1B / 0x22–0x28 forming a clean red/green/blue/white boot pattern. **EC space and the `0xFC7E0800` window share offsets** |
| Probe writes | Only `0x27` (max fan off), which HP also sends. **No `0x1A` is sent**, because setup fails before the write. Firmware debug during reload: `0x04`, `0x0D` reads, `0x11` ×2, `0x27` |
| `WMAA` abort seen on the 5.15 probe | **Not reproduced on 7.0.** No `WMAA` abort in the boot log or during reload |
| `gpu_mux_mode` | Not present: 7.0 predates it (it arrived in 7.3). The ASL analysis stands |
| `hp-bioscfg` | **Mostly broken.** Firmware bug in `WQBE` (ordered-list query): `AE_AML_BUFFER_LIMIT, Index (0x32) is beyond end of object (length 0x32)`, then `hp_bioscfg: Returned error 0x3`. Only `Sure_Start` (empty) plus one nameless attribute appear, so **Adaptive Battery Extender and Fan Always On are not reachable through `hp-bioscfg` today** |
| OMEN key | **Works:** `MSC_SCAN 21a5` → `KEY_PROG2` |
| Backlight key | No event captured. Either it wasn't pressed, or upstream drops event 0x0D (v11 handles it) |
| Audio | SOF `sof-hda-dsp`, ALC285 subsystem `103c8746`, HDA analog playback, **DMIC present** (`DMIC`, `DMIC16kHz`) |
| Sleep | `s2idle [deep]`; S3 is the default |
| Graphics | NVIDIA only, on `nouveau` in the live session. No Intel GPU on the bus, so dGPU-only is confirmed |

Also seen in the EC dump: 0x11 (`FRPM`) = `0x19`, i.e. 25, likely CPU fan
RPM/100 = 2500 RPM. That's an independent sanity check for the `0x2D` reading
once patched. Upstream still reads fans through WMI; it does not use this byte.

**What upstream `hp-wmi` delivers on 8746 today:** the OMEN key, the max-fan
toggle, and two fan files that always read 0. No modes, no RPM, no keyboard
RGB, no BIOS settings.

## 1. Fan speed: upstream will report 0 RPM

On 8746, `hp-wmi` reads fans with query `0x11` (`hp_wmi_get_fan_speed`). The
handler on this board is:

```
Method (GM11) {                         // DSL line 62863
    Local0 = Package {0, 4, Buffer(4){}}
    ... [0] = 0; [1] = 0; [2] = 0       // byte 3 left at its zero default
    Return (Local0)                     // no EC access at all
}
```

The kernel computes `(buf[2] << 8) | buf[3]`, which is always 0. **`sensors`
will show two fans at 0 RPM.**

The live readings are behind `0x2D` instead:

- `GM2D` calls `ERCD {0x45, 0x52}` and `{0x45, 0x55}`, then returns them in
  bytes 0 and 1. That is presumably RPM/100, matching the Victus-S layout.
- Upstream reads `0x2D` only on `hp_wmi_feature_boards`, and 8746 is not
  listed.

**This is the most useful small upstream patch for this board: fan reading,
not fan control.** It needs the kernel to use the `0x2D` read path on 8746
without also enabling manual PWM, since `0x2D` is read-only on this firmware.

That split may not exist in the driver today. Check how
`hp_wmi_feature_boards` couples the RPM read with PWM.

Also: does OMEN Gaming Hub read `0x2D` itself? The ~14,000 unlabelled
`inputData=0,0,0,0` calls in the log (about one every 30 s) are probably its
polling. The log does not name their command, so that is unconfirmed.

## 2. Thermal profile: write path correct, read path reads the wrong byte

### The write path

`GM1A` (DSL line 62987), for payload `{0xFF, mode}`:

| mode | EC `OCCM` | EC `FNSW` | GPU `CTGP` |
|---|---|---|---|
| 0 default | 0 | 0 | 0 |
| 1 performance | 1 | – | 1 |
| 2 cool | 2 | – | 0 |

In every case it then calls `WSMI(0x20008, 0x1A, 2, 0, 1)`, sends
`Notify(PEGP, 0xC0)` to the NVIDIA GPU, and raises WMI event `0x1B` with data
5 or 6, depending on `IRIQ`.

- Any other mode value skips the `Switch` but **still triggers the SMI and the
  notify**.
- Performance mode also turns on the GPU's configurable TGP (`CTGP` = 1). The
  kernel's profile write therefore changes GPU power as a side effect.

**HP-authored confirmation**, from the log on this machine:

- `SetFanModeAsync(), mode = Cool` goes with payload `255,2,0,0` (47×).
- `mode = Default` goes with `255,0,0,0` (45×).
- The WMI event `eventId=27, eventData=6` (69×) is the `GWEV(0x1B, 6)` that
  `GM1A` raises.

**These are exactly the kernel's V0 payloads.** Performance was captured on
2026-09-27 (`SetFanModeAsync(), mode = Performance`, then `255,1,0,0`). **All
three mode payloads the kernel sends on 8746 have now been observed from HP's
software on this machine.** OGH sends 4 bytes where the kernel sends 2; `GM1A`
reads only bytes 0 and 1, so the difference is inert.

### The read path

`omen_thermal_profile_get()` does `ec_read(0x95)`. On 8746 the ASL declares
almost nothing in the ACPI EC address space: `ERAM` covers only 0x5F–0x61.
Every OMEN field sits in a 4 KB memory window at `0xFC7E0800` (`ECMM`, `PECM`
and `ECCD` all map it).

In that window:

- 0x29 bits 0–1 = `OCCM` (the profile);
- 0x90–0x98 = `BMNN`, the battery model name.

If EC I/O offsets equal window offsets, then **0x95 is a battery-name byte**.
That looks likely, because the two views agree around the SMBus block at 0x60,
where `ERAM.SMPR` = 0x60 and `ECMM.SMST` = 0x61.

Windows reports the battery as `PABAS0241231`. If the EC keeps that string at
0x90, then 0x95 is `'0'`, which is **0x30**. That is
`HP_OMEN_V1_THERMAL_PROFILE_DEFAULT`, so:

- at load, `platform_profile_omen_get_ec()` would say `balanced` whatever the
  real mode is;
- `thermal_profile_setup()` would then re-send V0 default, `{0xFF, 0x00}`.

That payload is one HP sends, so it is harmless, but it means **loading
`hp-wmi` silently resets the laptop to Default mode**. At runtime the driver
returns its cached value, so reads are only wrong at probe.

If the byte is not one of 0/1/2/0x30/0x31/0x50, setup returns `-EINVAL` and
no profile device is registered. `hp_wmi_bios_setup` ignores the return
value, so the rest of the driver still loads.

**Confidence:**

- *No `HPCM`; the profile is at `OCCM` 0x29*: high (ASL).
- *0x95 is inside the battery name*: medium. It depends on the EC space and
  the window sharing offsets.
- *The byte is 0x30*: low. It depends further on the EC storing that string.

**Settle it read-only on a live USB:**

```
sudo modprobe ec_sys                       # without write_support: read-only
sudo xxd -s 0x80 -l 0x30 /sys/kernel/debug/ec/ec0/io
sudo xxd -s 0x20 -l 0x10 /sys/kernel/debug/ec/ec0/io   # byte 0x29 = OCCM?
```

Do this after setting the mode in Windows, then compare with what
`platform_profile` reports after `hp-wmi` loads. Also run
`dmesg | grep -i profile`.

A patch could read the profile back with a WMI query instead of `ec_read`. The
firmware has no profile-get GM type, though, so a per-board EC offset (0x29,
mask 0x03) may be the only option.

## 3. GPU MUX: neither read nor write works through WMI on 8746

- `HWMC` dispatches command 1 (read) types 0x01…0x51 and command 2 (write)
  types up to 0x51. **There is no 0x52 handler**: the request returns code 4,
  "unknown command type".
- `gpu_mux_mode_show` turns that into `-EINVAL`.
- `gpu_mux_mode_store` first reads design data. `GM28` succeeds with byte 7 =
  0, so the store returns `-EOPNOTSUPP` without sending anything.
- It fails safe, but the attribute is present and never works. **That is worth
  an upstream report**: the attribute should not be created when 0x52 answers
  4.

`GM28` returns `C8 00 3D 01 00 00 00 00 …` (DSL line 63238). OMEN Gaming Hub
has the same bytes cached in the registry:
`SystemDesignData.Get(), from Registry C8-00-3D-01-00-…`.

**There is no graphics-mode BIOS setting either.** The full BIOS settings list
was read over WMI from an elevated shell (`tools/read-bios-settings.ps1` →
`research/bios-settings.txt`). It has no Graphics, Switchable, Hybrid or MUX
entry.

So there is no MUX control in the WMI mailbox, none in the BIOS setup, and
Windows enumerates no Intel iGPU. The most likely reading is that **this SKU is
wired dGPU-only, with no user-switchable MUX.** The single Intel + NVIDIA
report on linux-hardware.org would then be a different 15-dh1xxx SKU. The
Linux answer is the NVIDIA driver alone; `envycontrol`, `prime-select` and
supergfxctl don't apply.

## 3a. BIOS settings that matter for Linux

These come from the same dump, and `hp-bioscfg` exposes them under
`/sys/class/firmware-attributes/hp-bioscfg/attributes/`:

| setting | value | why it matters |
|---|---|---|
| **Adaptive Battery Extender** | Enable (status: Activated) | **HP's battery-care / charge limiting.** This is the battery-limit feature the reports found missing from `hp-wmi`: a BIOS setting, writable through `hp-bioscfg`. There is no percentage; it is on or off |
| Fan Always On | Enable | fans never stop on AC; a candidate for the GUI |
| Action Keys Mode | Disable | Fn-key behaviour |
| Secure Boot | Enable, HP keys | the DKMS module (keyboard patch) needs MOK signing, as on the Acer |
| Setup Password | not set | `hp-bioscfg` writes need no password |

The dump also contains the serial number, MAC address, UUID and Windows digital
marker. **Keep `research/bios-settings.txt` out of any public repository.**

## 4. Fan control

**What HP's software offers on this board**, from the logs:

```
GetThermalModeTypes(): IsDesktop=False, IsPavilionGaming=False,
  IsSwFanControlSupport=False, IsBiosPerformanceControlSupport=False,
  IsMaxFanSupported=True
```

So on 8746 the only fan controls are the **three modes plus max fan**. That is
exactly what upstream exposes (`platform_profile` + `pwm1_enable` 0/2).

**Max fan on, observed 2026-09-28** (`HPOMENBG_20260928.log`): OGH logs
`SetMaxFan(), mode = On` then `inputData=1,` (15:22:55, 15:23:09, 15:23:48),
and `mode = Off` then `inputData=0,` throughout. `GM27` (DSL line 63206) sends
EC command `0x45 0x49` for byte 0 == 1 and `0x45 0x4A` otherwise, and raises no
event; the `eventId 27` after each "on" in HP's log is from the mode write OGH
makes just before it. Upstream sends the int as 4 bytes (`1,0,0,0`), which
GM27 reads identically. Enabled in the app; on the machine the fans went from
2200/2400 to ~4500/4700 rpm within 3 s, and back on Auto.

**What the firmware has anyway:**

| Handler | Behaviour | Notes |
|---|---|---|
| `GM2E` | writes payload bytes 0/1 through `ERCD {0x45, 0x50/0x51, byte}`, then sets `FNSW` = 1 (manual mode) | no range check |
| `GM1A` default | clears `FNSW` | – |
| `GM10` | returns count 2 and sets `OCCN` = 1, the "arm" side effect | – |
| `GM2F` | returns a static table: count byte 0x30, but only 11 rows filled (18–45 ×100 RPM) | would mislead the kernel's table parser |

**Conclusion:** manual fan control on 8746 would mean sending `0x10`/`0x2E`
payloads that HP's software never sends on this board. Under the project rule
this is **out**, unless a later OGH version turns on `IsSwFanControlSupport`
here.

A userspace fan curve is still possible *within* the rule, by switching
between the three profiles and max fan by temperature.

## 5. Keyboard

- HP's log: `GetKeyboardTypeAsync(): keyboardType = 1` and
  `BiosWmiCmd_IsLightingSupported(): isSupported = 1`. The v11 LED patch treats
  type 1 as 4-zone.
- `GM2B` returns 1 when EC `KB4Z` is set, and 0 otherwise.
- Zone colours are stored in OGH's profile as
  `FourZoneLighting Z0..Z3` = `16428047, 1017082, 16428047, 8714767`. These are
  0xRRGGBB integers.
- Backlight writes observed: `0x20009` type `0x05` payload `100,0,0,0` (0x64,
  backlight off) 7×, plus type `0x04` reads.
- **Colour-table write captured** (2026-09-27, OGH four-zone page). It is a
  128-byte payload with byte 0 = `3` and bytes 25–36 holding RGB for zones
  0–3: `FA 0F E7 | 0F D3 FA | F9 35 0F | FA AC 0F`. Every other byte is 0. It
  was followed by `228,0,0,0` (`0xE4`, backlight on). This is exactly the
  layout `LM03` accepts and the v11 patch writes, so **keyboard RGB now has HP
  evidence on 8746.**
- EC window 0x08–0x0D and 0x21–0x28 hold `Z01R/G/B` … `Z04R/G/B`. Colours are
  therefore **direct EC-window fields** on this board, not the `H2RA`
  shared-memory table the reports found on 878A.
- `LM03` writes them from payload bytes 0x19–0x24, but **only when payload
  byte 0 is 3**. `LM02` (the table read) always returns 3 there, while a
  table built from scratch with byte 0 = 0 would be silently ignored.
  *Correction, 2026-09-28:* v11's read-modify-write does **not** work cleanly,
  because `LM02` returns zone 0's blue from the wrong field (§00a). The
  driver now builds the table itself with byte 0 = 3, as OGH does.
- `LM05` sets `KBLS` from bit 7 of the payload, and `LM04` reports it back as
  `0xE4` or `0x64`.

## 6. Other corrections to the reports

- **`0x20008` type `0x35`** is called by OGH on this board (47×). 8746 has **no
  handler** for it (GM handlers end at `0x30`), so it gets return code 4. It is
  harmless, but it shows OGH sends queries the board doesn't implement.
- **`check-omen-acpi.sh`** would mislead on 8746:
  - its EC-offset section looks for 878A names (`HPCM`, `SRP1`, `RPM1`) that
    don't exist here;
  - it reports `GM2D`/`GM2E` as "SMI=no" correctly, but its sibling hints say
    the opposite.

  This file replaces what it was meant to produce.
- **OGH ships a kernel driver**, `HpReadHWData.sys`, inside the OMEN Command
  Center package. Neither report mentions it. It may be how OGH reads sensors;
  static inspection only.

## 7. Revised plan

*Superseded 2026-09-28:* this was the plan before the patched driver was
built. What was actually done, and verified, is in §00 and §00a; the open work
is in `APP.md` and `driver/INSTALL.md`. Kept as the record of the reasoning.

**Adopt; don't build a kernel driver.** That recommendation stands, but the
patch list changes.

1. **Live-USB check (read-only)**, on kernel 7.x: `sensors` (expect 0 RPM),
   `platform_profile` right after boot, `gpu_mux_mode` read (expect an error),
   `ec_sys` read of 0x20–0x30 and 0x80–0xB0, and `hp-bioscfg` attributes (look
   for graphics mode and battery care). This confirms or refutes §§1–3.
2. **Upstream patches**, each backed by the ASL above plus the live-USB
   evidence:
   - read fan RPM from `0x2D` on 8746, without enabling PWM;
   - read the profile from the correct EC offset (or stop trusting 0x95) on
     8746–874A;
   - don't create `gpu_mux_mode` when `0x52` returns 4.
3. **Keyboard**: test the v11 LED patch as DKMS, after one more OGH capture of
   a colour change (type `0x03` payload).
4. **Application**: reuse the orion-sense Qt shell. On this board it covers:
   - the three profiles plus max fan;
   - a profile-switching "curve";
   - 4-zone colours;
   - temperatures from `coretemp` and `nvidia-smi`;
   - fan RPM once patch 1 lands;
   - PipeWire EQ presets in place of B&O/DTS.

**New from the online re-check (2026-09-27):** the only public Linux boot log
for board 8746 (linux-hardware.org probe `c1c82e2ff7`, kernel 5.15, BIOS F.36)
shows:

```
ACPI Error: Aborting method \_SB.WMID.WMAA due to previous error (AE_AML_OPERAND_VALUE)
```

That means one of `hp-wmi`'s boot-time calls aborts inside the firmware
dispatcher. Which call it is can't be told from the tables. The firmware's own
`Debug = "HP WMI Command …"` strings will name it when `aml_debug_output` is
on. `tools/live-usb-check.sh` step 8 does that while reloading `hp-wmi`.

**Still open:**

- the command behind the ~30 s `0,0,0,0` polling;
- ~~the performance-mode payload~~: **closed**, `255,1,0,0` observed;
- ~~how graphics mode is switched~~: **closed**. There is no MUX control in
  WMI or in the BIOS; the SKU looks dGPU-only (§3);
- ~~whether EC space and the `0xFC7E0800` window share offsets~~: **closed**,
  they do. The profile round trip reads OCCM back at EC 0x29, and the zone
  colours sit at the window's Z01R-Z02B offsets (0x08-0x0D) in EC space (§00,
  §00a);
- what `HpReadHWData.sys` does.
