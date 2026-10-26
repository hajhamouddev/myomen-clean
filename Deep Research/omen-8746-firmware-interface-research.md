# HP OMEN firmware control interface: protocol, HP's software path, and design differences from the Acer Orion

*Research date: 2026-09-26 · Target: HP OMEN 15-dh1xxx, board 8746, BIOS F.44 · Companion to `omen-15-dh1xxx-8746-linux-research.md`*

**Method.**

- The research skill's Workflow/Agent tools were not available, so the stages were run directly.
- Primary evidence:
  - the firmware's own **binary MOF**, extracted from the AML and decoded with `bmfdec`;
  - the decompiled ASL of sibling boards **878A** (OMEN 15-ek0, Intel, 2020) and **8786** (OMEN 15-en0, AMD, 2020) from `linuxhw/ACPI`;
  - mainline `hp-wmi.c` at v7.3-rc4;
  - OmenMon and OmenHubLight source code;
  - **Ohman's research notes**, which record byte-exact payloads read from OMEN Gaming Hub's own log on board 8C58.
- **Nothing here was observed on board 8746.** Every row says whether its evidence is HP software, a community tool, firmware ASL, or a guess.
- Formal claim-verification and critic stages were not run.

---

## Summary

1. **The interface is self-describing, unlike Acer's.** Three things make this so:
   - The firmware carries a binary MOF that names every class, method and field. `hpqBIntM` has five methods whose numbers are output sizes, and `hpqBDataIn` is `{Sign[4], Command, CommandType, Size, hpqBData[]}`.
   - The AML dispatcher (`HWMC`) is readable: it checks the `SECU` signature, sets return codes, and routes each command type to a named handler.
   - Every handler starts with a debug string naming its command.

   Payload layouts that Acer hid entirely in SMM are, on the siblings, largely **visible in ASL**.
2. **Calls end in two places.**
   - **EC fields**, written directly by AML: thermal profile, max fan, GPU power, keyboard type, fan-control arming.
   - **SMM**, through an SMI via `WSMI`, which writes `0xE4` to port `0xB2`: fan read/set/table, graphics mode.
   - Keyboard colours go to an **EC shared-memory window** (`0xFE400000`) with a commit flag.
3. **HP's software path**: the OMEN Gaming Hub UWP → its background process / HP HSA service → WMI (`WmiProv`) → `wmiacpi.sys` → ACPI `WMAA` → `HWMC`. OGH's background log **records the input bytes of every BIOS call** (`[ExecuteBiosWmiCommandThruDriver] inputData=…`). That is a passive, HP-authored capture source, and it is safer than any hook. Collect it before OCC is uninstalled.
4. **Two findings matter most for safety.**
   - The 0x20008 handlers do **no range checking** (878A); whatever bytes arrive are stored in the EC.
   - A **"get" command has side effects**: type `0x10` (fan count) sets EC bit `OMCC`, which hands fan control to the host until a firmware timeout. This matches the kernel comment and Ohman's measurement.
5. **Design consequence.** There is no need for a new kernel driver. Upstream `hp-wmi` already implements the call path, and its extension points are feature-board entries and the pending LED patch. Driver work is:
   - small patches to mainline `hp-wmi`, each gated on bytes seen in OGH's log for 8746;
   - otherwise userspace on top of `hp-wmi` sysfs.

   A second kernel module sharing the GUID is possible but unsafe for multi-step sequences.

---

## A. The HP BIOS WMI protocol

### A1. Call format

**Answer.** The MOF embedded in the firmware (878A, decoded) defines the following.

- **Namespace:** `root\wmi`.
- **Method class** `hpqBIntM`, GUID `5FB7F034-2C63-45E9-BE91-3D44E2C707E4`. There are five methods; the method ID selects the output size class:

| Method ID | Name | Output class | Output data size |
|---|---|---|---|
| 1 | `hpqBIOSInt0` | `hpqBDataOut0` | 0 |
| 2 | `hpqBIOSInt4` | `hpqBDataOut4` | 4 |
| 3 | `hpqBIOSInt128` | `hpqBDataOut128` | 128 |
| 4 | `hpqBIOSInt1024` | `hpqBDataOut1024` | 1024 |
| 5 | `hpqBIOSInt4096` | `hpqBDataOut4096` | 4096 |

- **Input** `hpqBDataIn`: `Sign uint8[4]`, `Command uint32`, `CommandType uint32`, `Size uint32`, `hpqBData uint8[Size]`.
- **Output:** `Sign uint8[4]`, `rwReturnCode uint32`, plus `Data` in the sized classes.
- **`Command`** selects the command family:
  - `1` = legacy BIOS read, `2` = legacy BIOS write;
  - `0x20008` = gaming ("GM") commands;
  - `0x20009` = lighting;
  - `0x2000B` and `0x20000` = small sets of other commands.
- **`CommandType`** is the opcode within the family.

**Firmware side.** On 878A the dispatcher is `HWMC`, called from `WMID.WMAA`.

- It reads the signature, command, command type and size from the input buffer.
- It copies the payload into a global buffer `WBUF` (or `GMBF` for payloads over 128 bytes, apart from two exceptions).
- It sets the output signature to `FAIL` (`0x4C494146`), and to `PASS` (`0x53534150`) on success.

**Return codes** (878A `HWMC`):

| Code | Meaning |
|---|---|
| 0 | OK |
| 2 | wrong signature (the default) |
| 3 | unknown `Command` |
| 4 | unknown `CommandType` |
| 5 | invalid parameters: missing input, or the handler's output is larger than the chosen size class, i.e. the wrong method ID |
| 6 | value outside a validated range; only a few legacy commands validate at all |

Ohman saw 1, 4, 6 and 46 on 8C58, with 6 meaning "accepted, pending restart" for the graphics write. Code semantics are firmware-specific.

**Linux side** (`hp-wmi.c`, v7.3-rc4):

- `hp_wmi_perform_query(query, command, buffer, insize, outsize)` builds `struct bios_args {signature=0x55434553 "SECU", command, commandtype, datasize, data[]}`. It allocates at least 128 data bytes.
- `encode_outsize_for_pvsz()` maps the output size to method ID 1–5 (0 → 1, ≤4 → 2, ≤128 → 3, ≤1024 → 4, ≤4096 → 5).
- It calls `wmi_evaluate_method(HPWMI_BIOS_GUID, 0, mid, …)` and returns the firmware's code. It stays quiet on 3/4 and warns on the others.
- `zero_insize_support` is detected at init: if a probe with a non-zero size returns 5, later "read" queries are sent with size 0.

**Confidence.** High. The MOF and dispatcher are firmware-authored, and the kernel code was read directly. Board 8746's own MOF should be identical; your `_WDG` layout matches 878A entry for entry. Confirm by decoding your dump's `WQAB` blob with `bmfdec`.

**Action.** Treat the MOF as the authoritative schema. Payload meanings still come only from handlers, HP's software, or its logs.

### A2. Command table

**How to read the status column:**

- **HP-log** — bytes read from OMEN Gaming Hub's own background log (Ohman, 8C58).
- **HP-code** — taken from decompiled HP assemblies or HP's embedded data (Ohman, OmenMon comments, OmenHubLight's reconstructed HP classes, the kernel's OCC-JSON board lists).
- **ASL** — the handler exists and its behaviour is readable in 878A/8786 firmware.
- **community** — sent by a community tool or the kernel, without a published HP-software capture.
- **guessed** — inferred.

Sizes are payload in → data out. Unless stated, nothing in this table has been observed on board 8746.

| Command | Type | Size | Dir | Meaning | Payload layout | Sources | Boards confirmed | Status |
|---|---|---|---|---|---|---|---|---|
| `1` | `0x0C` | 4 → 4 | R | Hotkey code (after event 0x04/0x1D) | out `[0..3]` key code, e.g. `0x21A5` | `hp-wmi` `hp_wmi_read_int(HPWMI_HOTKEY_QUERY)` | many HP laptops | community + ASL (878A `WMID` has 0x0C) |
| `1`/`2` | `0x4C` | 4 → 4 | R/W | Generic thermal profile (non-OMEN path) | byte 0 profile | `hp-wmi` `thermal_profile_get/set`; 878A `GBSC`/`STPS` | non-OMEN HP | community + ASL |
| `1` | `0x52` | 0/4 → 4 | R | Graphics mode | out `[0] & 0x7F`: 0 Hybrid, 1 Discrete, 2 Optimus, 3 iGPU only | OmenMon `GetGpuMode` (`Cmd.Legacy`, 0x52); Ohman; `hp-wmi` `hp_wmi_get_mux_mode`; 878A `GDSS` → SMI | 8C58 (Ohman), 8A14 (OmenMon) | HP-code + ASL |
| `2` | `0x52` | 4 → 4 | W | Set graphics mode, applied at next boot | `{mode,0,0,0}`; OGH sets bit 7 ("no reboot") only on platform cycle 26C1 and later | OmenMon `SetGpuMode` (enum from HP `GraphicsSwitcher`); Ohman; `hp-wmi` `gpu_mux_mode`; 878A `SDSS` → SMI | 8C58 | HP-code; **write untested on 8746** |
| `1` | `0x0F` | 4 → 4 | R | Smart adapter status | out `[0]`: 1 meets, 2 below requirement, 3 battery, … | OmenMon `GetAdapter` | 8A14 | community |
| `0x20008` | `0x10` | 0/4 → 4 | R* | Fan count. **Side effect: arms host fan control** | out `[0]` = count (878A returns 2). 878A also sets EC `OMCC` = 1. State expires about 120 s after the last call | 878A `GM10` (ASL); `hp-wmi` comment on `hp_wmi_get_fan_count_userdefine_trigger`; Ohman measured; OGH sends it about every 15 s | 878A (ASL), 8C58 (HP-log) | **HP-log + ASL**; read-named but writes |
| `0x20008` | `0x11` | 1 → 4 | R | Fan speed (legacy) | in `{fan}`; out `[2]<<8 \| [3]` RPM | `hp-wmi` `hp_wmi_get_fan_speed` (used on 8746); 878A `GM11` | 15-en0023dx (AMD) in the 2021 patch | community + ASL |
| `0x20008` | `0x1A` | 2–4 → 0 | W | Performance / thermal mode | `{0xFF, mode, byBios, 0}`. V0 modes (8746): 0 default, 1 performance, 2 cool. V1: `0x30`/`0x31`/`0x50`. `byBios` = 1 on battery (OGH). The kernel sends only `{0xFF, mode}`. 878A `GM1A` writes byte 1 to EC `HPCM` (0x95) and ignores byte 2 | Ohman (HP-log `255,49,0,0` / `255,48,1,0`; HP-code `PerformanceControlHelper.SetFanMode`); OmenHubLight reconstructed HP code (force-V0 list with 8746); `hp-wmi`; OmenMon | 8C58 (HP-log); kernel force-V0 list for 8746 from OCC JSON | **HP-log / HP-code**; V0 values for 8746 from HP-code |
| `0x20008` | `0x21` | 4 → 4 | R | GPU power state | out `{cTGP, PPAB, dState, peakTemp}` | OmenMon `GetGpuPower`; Ohman; 878A `GM21` (EC `ECDO`) | 8C58 | HP-log + ASL |
| `0x20008` | `0x22` | 4 → 0 | W | Set GPU power (cTGP / PPAB) | `{cTGP, PPAB, dState, peakTemp}`; OGH Eco `{0,0,1,75}`, Balanced `{0,1,1,87}`, Performance `{1,1,1,87}` | Ohman (HP-log); `hp-wmi` `victus_s_gpu_thermal_profile_set` (feature boards only); 878A `GM22` (EC `NVDO`) | 8C58 | **HP-log**; not observed for 8746 |
| `0x20008` | `0x23` | 4 → 4 | R | Chassis / IR sensor temperature | in `{1,0,0,0}`; out `[0]` °C | OmenMon `GetTemperature`; Ohman; 878A `GM23` (EC `TNT3`) | 8C58 | HP-log + ASL |
| `0x20008` | `0x26` | 4 → 4 | R | Max fan state | out `[0]` | `hp-wmi` enum; OmenMon; 878A `GM26` (EC `FFFS`) | 8C58 | HP-log + ASL |
| `0x20008` | `0x27` | 4 → 0 | W | Max fan on/off | `{on,0,0,0}`; 878A sets EC bit `FFFS` | `hp-wmi` `hp_wmi_fan_speed_max_set` (sent on 8746 by upstream); OmenMon; Ohman HP-log `SetMaxFan` | 8C58 (HP-log); all `hp-wmi` OMEN boards | **HP-log + ASL** |
| `0x20008` | `0x28` | 0/4 → 128 | R | System design data | `[3]` thermal policy version; `[4]` bit 0 software fan control; `[5]` default PL4; `[7]` graphics-mode mask (1 iGPU, 2 Hybrid, 4 Discrete, 8 Advanced Optimus); `[8]` concurrent TDP. **878A and 8786 never set byte 7** | OmenHubLight reconstructed HP code (`BiosWmiCmd_Get(0x20008, 40, 4 bytes, 128)`); Ohman; OmenMon; `hp-wmi`; 878A/8786 `GM28` | 8C58 (measured) | HP-code + ASL |
| `0x20008` | `0x29` | 4 → 0 | W | CPU power limits / "Smart Performance Gain" | `{PL1, PL2, PL4, concurrent}`, `0xFF` = unchanged | Ohman HP-log `255,255,255,45`; OmenMon; 878A `GM29` (EC `TPL4`) | 8C58 | HP-log; **out of scope** (power limits) |
| `0x20008` | `0x2B` | 0/4 → 4 | R | Keyboard type | out `[0]`: 0 none, 1 4-zone + numpad, 2 4-zone, 3 per-key, 4/5 single zone. 878A derives it from EC `KBT0` plus a GPIO | Ohman (HP-code); OmenMon; v11 LED patch; 878A/8786 `GM2B` | 8C58 = 2 | HP-code + ASL |
| `0x20008` | `0x2C` | 4 → 128 | R | Fan types | `[0]` nibbles, `0x21` = fan 1 CPU, fan 2 GPU | OmenMon `GetFanType`; Ohman; 878A `GM2C` returns 0x21 | 8C58 | community + ASL |
| `0x20008` | `0x2D` | 4 → 128 | R | Fan levels (RPM/100) | out `[0]`, `[1]` | OmenHubLight reconstructed HP code (`GetFanLevel` → 0x2D); `hp-wmi` (feature boards); Ohman; 878A `GM2D`: SMI, then EC `RPM1`–`RPM4` | 8C58; 8C78 and other feature boards | HP-code + ASL (**SMI**) |
| `0x20008` | `0x2E` | 2–128 → 0 | W | Set fan levels (RPM/100). **0 = fan off**, not "auto" | `{cpu, gpu, …}`; 878A `GM2E`: SMI, then EC `SRP1`/`SRP2` (0x34/0x35) with **no range check** | Ohman HP-log; `hp-wmi` `hp_wmi_fan_speed_set` (feature boards only); OmenMon `SetFanLevel` | 8C58 (HP-log), 8C78 (kernel) | **HP-log**; not on 8746; **dangerous** (A4) |
| `0x20008` | `0x2F` | 4 → 128 | R | Fan table | `[0]` fans, `[1]` rows, then `{cpu, gpu, noise-dB}` rows. 878A returns a static table (12/14 rows); 8786 is SMM-only | `hp-wmi` `victus_s_fan_table`; Ohman; OmenMon | 8C58; 878A (ASL) | community + ASL |
| `0x20008` | `0x32` | 128 → 0 | W | Set fan table | layout as `0x2F` | OmenMon `SetFanTable` only | – | community; **absent on 878A** (no `GM32`; handlers end at `GM30`) |
| `0x20008` | `0x18`, `0x19`, `0x31`, `0x35` | – | R/W | Memory-overclock capability, XMP, idle mode, overclock capability | – | OmenMon | 8A14 | community; **out of scope**; `0x31`/`0x35` absent on 878A |
| `0x20009` | `0x01` | 0/4 → 4/128 | R | Lighting supported / keyboard info | 878A `LM01`: bit layout from `KBT0`, byte 1 = EC `RTMP`. Weak signal on 8D87 (Ohman) | Rishit 2023 patch; OmenMon; Ohman | 15-en0037AX, 8D87 | community + ASL |
| `0x20009` | `0x02` | 0/4 → 128 | R | Colour table | zone *i* = bytes `25+3i .. 27+3i` (R, G, B); bytes 0–24 kept as read | OmenHubLight `FourZoneHelper` (reconstructed HP `HP.Omen.FourZoneModule`); Ohman (HP-code `HP.Omen.Background.FourZone`); pelrun; v11 LED patch | 15-dc0 (OmenHubLight), 8C58 | HP-code |
| `0x20009` | `0x03` | 128 → 4 | W | Write colour table (read-modify-write) | 878A: copies bytes 0x19–0x24 into `LRGB`/`BRGB` in the EC shared-memory window `H2RA` (`0xFE400000`, +0xEE3/+0xEF0), sets commit flag `LCMC` | as above; 878A handler | 8C58 (read back byte-exact) | HP-code + ASL |
| `0x20009` | `0x04` | 0/4 → 128 | R | Backlight byte | bit 7 = on; OGH uses `0xE4`/`0x64`; needs a 128-byte output buffer (else rc 5, Ohman) | OmenMon; Ohman; OmenHubLight | 8C58 | HP-code |
| `0x20009` | `0x05` | 4 → 4 | W | Set backlight byte | `{0xE4 \| 0x64, 0, 0, 0}`; 878A writes `LBRT`, sets `LCMC` | as above | 8C58 | HP-code + ASL |
| `0x20009` | `0x06`/`0x07` | 128 | R/W | LED animation table | format unknown; OmenMon says writes have no effect | OmenMon; OmenHubLight constants | – | community; **absent on 878A** (handlers only 0x01–0x05) |
| event (GUID `95F24279`, notify 0x80) | ID `0x1D` | – | in | OMEN key | data `0x21A5` (8613); another key 8615 | `hp-wmi` keymap; Ohman measured 29/8613 on 8C58; 15-dh0 sends ID 0x04 with empty data (OmenLinux) | 8C58, 8600 | community + measured |
| event | ID `0x0D` | – | in | Fn backlight key | data 0 = off, 2 = on | Ohman; v11 LED patch | 8C58 | measured |
| event | ID `0x05` / `0x03` | – | in | Wireless / smart adapter | – | `hp-wmi` | many | community |
| – | – | – | – | **Battery charge limit** | **none known in the mailbox.** A scan of commands 0x2000C–0x20020 returned rc 3 on 16-am0 (MasonDye/OmenXHub via Ohman §11); myHP uses a separate WinRT path | Ohman §11 | 16-am0 | negative result |

### A3. The other GUIDs

**Answer.** On 878A, every GUID in your list except the NVIDIA ones is **named by the firmware's own MOF**. The `_WDG` layout matches your 8746 dump entry for entry; the only difference is `BD` with 25 instances against your 24.

| GUID | Object | Class (from MOF) | What it is | Linux driver |
|---|---|---|---|---|
| `5FB7F034-…` | AA (method) | `hpqBIntM` | BIOS mailbox (A1) | `hp-wmi` |
| `95F24279-…` | event 0x80 | `hpqBEvnt` | hotkey / BIOS events | `hp-wmi` |
| `2B814318-…` | event 0xA0 | `HPBIOS_BIOSEvent` (namespace `root\HP\InstrumentedBIOS`) | BIOS-setting change events | `hp-bioscfg` (listed) |
| `1F4C91EB-…` | BA (method) | `HPBIOS_BIOSSettingInterface` | `SetBIOSSetting(Name, Value, Password)`, `SetSystemDefaults` | `hp-bioscfg` |
| `2D114B49-…` | BC, 77 inst | `HPBIOS_BIOSEnumeration` | enumeration settings | `hp-bioscfg` |
| `988D08E3-…` | BD, 24–25 inst | `HPBIOS_BIOSString` | string settings | `hp-bioscfg` |
| `14EA9746-…` | BE, 2 inst | `HPBIOS_BIOSOrderedList` | ordered lists (boot order) | `hp-bioscfg` |
| `322F2028-…` | BF | `HPBIOS_BIOSPassword` | password objects | `hp-bioscfg` |
| `8232DE3D-…` | BG | `HPBIOS_BIOSInteger` | integer settings | `hp-bioscfg` |
| `8F1F6436-…` | BH, **0 inst** | `HPBIOS_BIOSStateSensor` | state sensors (unused) | none; Linux logs "zero instances" |
| `8F1F6435-…` | BI, **0 inst** | `HPBIOS_BIOSNumericSensor` | numeric sensors (unused) | none |
| `7391A661-…` | AC (method), **0 inst** | `HPBIOS_BIOSUserInterface` | `ManageBIOSUsers` (BIOS user/role management, business-class feature) | none |
| `DF4E63B6-…` | BJ, **0 inst** | `HP_BIOSUser` | BIOS user objects | none |
| `05901221-…` | AB / CC | binary MOF | the schema itself | `wmi-bmof` |
| `86CCFD48-…` | TF (device `WMTF`) | – | Intel Thunderbolt force-power WMI | `intel-wmi-thunderbolt` (`INTEL_WMI_THUNDERBOLT_GUID`) |
| `2BC49DEF-…` + event `A6FEA33E-…` 0xD0 | DE (device `WFDE`, `_UID "SampleDev"`) | `POWER_DATA` (GetVersion / IsEnabled / GetData) + `POWER_CHANGE_EVENT` | Intel reference-code sample: returns `PDAT` built from `SDAA`/`SDAB`, read-only | none |
| `1F13AB7F-…` | DE (device `WFTE`) | `FIRE_TEST_EVENT` ("Debug: Fire event") | reference-code debug event trigger | none; **do not call** |
| `CA4982BF-…` | OP (`WMI2`) | – | NVIDIA Optimus WMI method (SSDT) | none in Linux; paired data block `A486D8F8-…` "SM" is NVIDIA's Optimus `_DSM` MUID (`nouveau_acpi.c` `nouveau_op_dsm_muid`) |
| `F6CB5C3C-…` | MX (`WMI1`) | – | NVIDIA MXM WMI | `mxm-wmi` (`MXM_WMMX_GUID`) |

There are **no Sure Start or security GUIDs** among them. The password and user classes belong to the BIOS-settings family. The zero-instance blocks (`BH`, `BI`, `AC`, `BJ`) are the ones the Linux WMI core reports as having zero instances on OMEN boards, as seen in an 8C75 omen-space issue log.

**Confidence.** High for 878A (firmware MOF, decoded). High that 8746 is the same, given the identical `_WDG`. Decoding your own `WQAB` settles it.

**Action.** Nothing to build. `hp-bioscfg` covers the settings classes. Never call `AC`/`BA` writes or `FIRE_TEST_EVENT` from tooling.

### A4. Where calls end up, and known dangers

**Answer.** On 878A, three sinks, varying by command type:

- **Direct EC fields**, AML writing EC registers through the `ERAM` region:

  | Type | EC field | Offset |
  |---|---|---|
  | `0x1A` | `HPCM` | 0x95 |
  | `0x27` / `0x26` | `FFFS` bit | around 0xE9 |
  | `0x22` | `NVDO` | – |
  | `0x10` | `OMCC` bit | around 0x61–0x62 |
  | `0x2B` | reads `KBT0` | – |

  None of these handlers range-checks the payload.
- **SMM**, through `WSMI`: it loads `AEAX`–`AEDX`, copies `WBUF`, writes `0xE4` to I/O port `0xB2`, and retries up to three times. Used by `0x2D`, `0x2E`, `0x2F`, `0x30` and graphics mode `0x52`. `0x2E` then also writes `SRP1`/`SRP2` in AML. On 8786 (AMD) the fan handlers are **pure SMM**, so their behaviour is invisible. This is the same pattern as Acer's SMI 0x91, but with the SMI number `0xE4`, and with most of the logic still in AML.
- **EC shared memory**: keyboard colour and brightness go to `H2RA`, a 4 KB `SystemMemory` window at `0xFE400000` (fields `LRGB`, `BRGB`, `LBRT`, commit bit `LCMC`).

**Known dangers**, with evidence:

1. **Read-named commands with side effects.** `0x10` sets `OMCC` and puts fans under host control. If the host then writes nothing, or crashes, the firmware keeps the **last written level** until the state expires. Ohman measured that level 0 means fans off and triggered a Windows critical thermal shutdown (Kernel-Power 88) with fans held at 0 under load. `hp-wmi` sends `0x10` only on feature boards, never on 8746.
2. **`0x2E` level 0 = off.** Any curve code that sends 0 as "auto" stops the fans. Ohman refuses levels 1–17 as unholdable.
3. **Direct EC writes:**
   - omen-space blocks EC writes on some 2024–25 models to prevent an EC "Caps Lock panic". Caps Lock blinking is HP's EC fault signal.
   - Ohman measured on 8C58 that of two EC register pairs, only one drives the fans. The other accepts writes silently, so a register can look writable and do nothing.
   - NBFC's "OMEN Notebook PC 15" config writes 0x94, next to `HPCM`.
4. **Firmware changes between BIOS versions**: an 8BCA (F.31) regression report shows the WMI path breaking after a BIOS update (`GTPS` `AE_NOT_FOUND`), after which the user fell back to raw EC writes.
5. **No confirmed bricking** from these WMI commands was found. The only OMEN "bricks" found were failed BIOS flashes: 15-dc0 on Win-Raid, 15-dh0 on Tom's Guide.

**Confidence.** High for the 878A sinks (ASL). Medium for the danger list, which is field reports plus Ohman's controlled measurements on 8C58.

**Action.**

- Never send `0x10` or `0x2E` on 8746 until OGH's log shows it doing so, and then only with the kernel's keep-alive plus a thermal fallback to max fan.
- Treat every `0x20008` write as unvalidated storage into EC/SMM.
- Prefer `0x27` (max fan) as the only fan override until then.

---

## B. How HP's own software reaches the firmware

### B5. The OMEN Command Center / Gaming Hub path

**Answer.** Four layers, from the hardware up:

- **Device and driver layer.** BIOS exposes dummy ACPI devices `HPIC0003` (consumer), `HPIC000C` (business) and `HPIC0004` (OMEN/Victus).
  - Each installs a system driver (`hpcustomcapdriver.sys` / `hpomencustomcapdriver.sys`) and a software component (`SWC\HPIC0004`, `hpomencustomcapcomp.inf`).
  - The software component installs the **HSA services**, including `HPOmenCap` ("HP Omen HSA Service", `OmenCap.exe`).
  - OmenHwCtl reports that the base INFs are enough to make `hpqBIntM` usable, and the component INF is not needed.
- **App layer.** The UWP `AD2F1837.OMENCommandCenter` plus its background process `OmenCommandCenterBackground`, started at logon by HP's `OmenInstallMonitor` scheduled tasks.
- **UWP ↔ service channel.** HP's HSA services expose an **LPC/RPC** endpoint whose client is `NativeRpcClient.dll`, shipped with OGH and HP System Event Utility.
  - The services check their callers. OmenHubLight's `OmenDriverPatcher` patches exactly those check functions in `OmenCap.exe`, `SysInfoCap.exe` and `AppHelperCap.exe` so third-party code can connect.
  - This is HP's equivalent of Acer's TCP 46933, but it is **local RPC with caller validation**, not plaintext JSON.
  - No published byte-level protocol for it was found.
- **Firmware calls.** OGH's background log names the helper `ExecuteBiosWmiCommandThruDriver` for every call. HP code reconstructed in OmenHubLight (`Hp.Omen.OmenCommonLib.OMENHsaClient`) calls `hpqBIntM` through `System.Management`.
  - The MOF says the class is served by `Provider("WmiProv")`, the standard kernel-WMI provider in `WmiPrvSE.exe`, which talks to `wmiacpi.sys`. That in turn evaluates `WMAA` with `(instance, method ID, buffer)`, as Microsoft's ACPI-WMI mapper documentation describes.
  - **Unresolved:** whether the `ExecMethod` originates in the background process or inside `HPOmenCap` after an RPC hop. "ThruDriver" suggests the latter.

**Evidence.** OmenMon issue #15 (HPIC devices and drivers); OmenHwCtl README; OmenHubLight README and `patches.txt`; Ohman `docs/research.md` §5 and §9; the 878A MOF.

**Confidence.** Medium–high on the layers. Low on exactly which process calls WMI.

**Action.** You don't need to reverse the RPC channel. Capture at the log or WMI layer instead (B6).

### B6. The safest way to observe it on Windows 11

Options from least to most invasive:

1. **OGH's own log (best; entirely passive, HP-authored).**
   - Path: `%LOCALAPPDATA%\Packages\AD2F1837.OMENCommandCenter_v10z8vjag6ke6\LocalCache\Local\HPOMEN\HPOMENBG_<date>.log`.
   - It records `[ExecuteBiosWmiCommandThruDriver] inputData=…` for every BIOS call, with the helper names around it.
   - Ohman derived every OGH payload on 8C58 this way.
   - Procedure: click every mode, fan option, graphics option, lighting option and brightness step in OGH and Light Studio, on AC and on battery, then copy the logs.
2. **OGH's cached and embedded data**, read-only:
   - `HKCU\Software\HP\OMEN Ally\Settings\SystemDesignData` (OGH's cache of `0x28`);
   - the per-model JSON embedded in the OGH assemblies (`HP.Omen.Core.Common.PowerControl.JSON.*`, `profiles.json`), extractable by reflection from the readable `WindowsApps` folder (Ohman §9);
   - OGH's capability JSON, which is where the kernel's board lists came from.

   This yields the 8746 entry: features, thermal policy, and any fan curve.
3. **Kernel/WMI telemetry.** The `Microsoft-Windows-WMI-Activity` ETW provider and Security event 4662 ("Local Execute (ExecMethod)") record class::method and caller, **not the input buffer**. They are useful only to identify the calling process.
4. **Frida hook (passive) at the WMI choke point.** Hook `DeviceIoControl` in the `WmiPrvSE.exe` instance hosting `WmiProv`, or `IWbemServices::ExecMethod` in the caller that item 3 identified.
   - Every `hpqBIntM` call passes through `WmiProv`, whichever HP process makes it. The raw input buffer there is exactly the `SECU|Command|Type|Size|Data` block that reaches `WMAA`.
   - The IOCTL choke point is standard Windows architecture but was not verified for this report; confirm it with API Monitor before relying on it.
5. **IRP monitoring of `hpomencustomcapdriver.sys`.** Only needed if items 1–4 show calls bypassing WMI. Nothing found suggests they do.

**Which process to hook.** Use `WmiPrvSE.exe` with `WmiProv` loaded. Unlike Acer, the HSA/UWP split does not hide the payload, because everything converges on the WMI provider.

**Confidence.** High for item 1 (Ohman used it); medium for item 4.

**Action.** Do items 1 and 2 **before uninstalling OCC**. They need no code injection and give HP-authored bytes.

### B7. OMEN Light Studio and OMEN Audio Control

**Light Studio.**

- A 2021 reverse-engineering series on an OMEN 15-en0037AX found Light Studio's work done by a background service (`LightStudioHelper`) and `OmenFourZoneLighting.dll`, calling WMI (`wmiacpi`).
- Animations such as "wave" are **host-side**: after a reboot into Linux only the last static colour remains.
- Current OGH folds this into `HP.Omen.Background.FourZone`, and animates by writing frames at about 15 fps (Ohman).
- It uses the same `0x20009` types 0x02–0x05. On 878A the firmware implements only 0x01–0x05 and stores 12 colour bytes plus a commit flag in EC shared memory. There is no firmware effects engine, unlike Acer's EC-hosted effects.
- **Newer boards differ:**
  - `OMENLighting.sys` (a KMDF lower filter) publishes four-zone keyboards as a Windows Dynamic Lighting LampArray over the same WMI mailbox.
  - Per-key boards use USB HID controllers: Primax `0461:4E9A`/`4E9B` on 2021–24 boards, Darfon `0D62:54BF` on 2025.
  - On those boards the `0x20009` table is inert.
- Your PS/2 keyboard with no USB lighting controller fits the WMI four-zone case.

**OMEN Audio Control** is HP's front end for Bang & Olufsen speaker presets and EQ, and DTS (Headphone:X / X Ultra) for the headphone jack. These are Windows audio processing objects delivered with the Realtek driver package; the DTS/B&O attribution comes from HP community threads.

- It does **not** use the BIOS mailbox.
- Nothing is portable. On Linux the replacement is a PipeWire filter chain or EasyEffects with your own EQ.
- This is the same situation as Acer's DTS APO.

**Confidence.** Medium for Light Studio: 2021 blog plus current OGH notes, on other boards. Medium–low for the OAC internals: forum-level evidence.

**Action.** Capture Light Studio sessions in the OGH/HSA logs as in B6 item 1. No audio work beyond EQ presets.

---

## C. Differences that change the design

### C8. Acer Predator Orion vs HP OMEN 15-dh1xxx

| Aspect | Acer Predator Orion (orion-sense) | HP OMEN 15-dh1xxx (8746) |
|---|---|---|
| Interface discovery | 12-method `AcerGamingFunction` GUID; packing hidden in SMM behind a `WMBH` shim; **captured with frida** from the vendor service | Self-describing: firmware MOF names classes and fields; the dispatcher and most handlers are readable ASL (siblings); OGH **logs its own payloads** |
| Call path | Electron app → JSON over TCP 127.0.0.1:46933 → service → WMI → `WMBH` → SMI 0x91 → SMM | UWP → local RPC (caller-validated) → HSA service / background → WMI (`WmiProv`) → `wmiacpi` → `WMAA` → `HWMC` → EC fields, or SMI 0xE4 → SMM, or EC shared memory |
| Upstream driver | none usable (`acer-wmi` used the laptop map on a desktop ABI) | `hp-wmi` lists 8746: profiles, fan RPM, max/auto fan, OMEN key; `hp-bioscfg`; MUX attribute (write likely refused) |
| Fan model | per-fan duty via vendor methods | V0 profile + max/auto upstream. Firmware interface is a **level table** (RPM/100 per fan) armed by `0x10`, expiring after ~120 s, with level 0 = off; not enabled for 8746 |
| Thermal profiles | vendor profile method | `platform_profile` cool/balanced/performance (V0 values from HP code); EC refuses performance on battery; OGH adds a `byBios` flag on battery |
| Lighting | EC-hosted effects; OpenRGB bundled | host-side static 4-zone table in EC shared memory; effects done by software; v11 LED patch pending; per-key SKUs use USB HID and are unsupported |
| GPU control | absent (NVML owned the GPU fan) | graphics mode (MUX) via 0x52 → SMM, next-boot; cTGP/PPAB via `0x22` (HP-log on other boards; not for 8746 upstream) |
| Events / hotkeys | – | `hpqBEvnt`: OMEN key 0x1D/0x21A5, backlight key 0x0D, wireless, adapter; handled by `hp-wmi` |
| Audio | DTS APO (not portable) | B&O + DTS APOs (not portable) |
| Packaging | new DKMS module + MOK signing | **upstream patches** to `hp-wmi` (board entries, LED patch, MUX fix) + userspace GUI; DKMS only as an interim patched `hp-wmi`, which replaces the in-tree one rather than coexisting |

### C9. Right vehicle for additions, and sharing `5FB7F034`

**Answer.** Patch mainline `hp-wmi`. Review history shows what is accepted:

- **Accepted:**
  - board-ID additions with a real test report;
  - per-board feature entries (`hp_wmi_feature_boards`);
  - manual fan with keep-alive (Chomal, tested on 8C78);
  - GPU MUX (Abaylı).
- **Pushed back:**
  - forcing cTGP/PPAB calls on boards not known to support them (September 2026 review of the 8C58 patch);
  - pseudonymous sign-offs (8A13);
  - new LED naming outside the documented scheme. Rishit Bansal's 2023 keyboard series stalled on this; the 2026 series is on v11, reviewed but not applied.

**Sharing the GUID.** `hp-wmi` uses the legacy GUID-based `wmi_evaluate_method()` rather than binding a WMI bus device, so a second module *can* call the same GUID. There is no shared lock.

- AML serializes the SMI path (`WSMI` acquires mutex `MUTS`), so single calls won't corrupt each other.
- **Multi-call sequences can interleave:**
  - `0x10` arm → `0x2E` write → keep-alive;
  - colour-table read-modify-write;
  - `hp-wmi`'s own probe-time writes.

  hippomasters/omen-rgb-linux documents the same limitation.
- **Consequence:** one kernel owner per feature. Put additions in `hp-wmi`, or do them in userspace over `hp-wmi` sysfs. Don't load a second mailbox driver alongside it.

**Confidence.** High on maintainer patterns; high on the locking analysis (kernel + ASL).

**Action.** Plan three small `hp-wmi` patches, each gated on HP-log evidence for 8746:

1. an 8746 feature-board entry (only if 8746 exposes `GM2D`/`GM2E`/`GM2F` and OGH drives them);
2. the `gpu_mux_mode` zero-mask fallback;
3. testing and acking the v11 LED patch.

### C10. Laptop-specific concerns

- **AC vs battery.**
  - `hp-wmi` stores the chosen profile and re-applies it when AC returns (`omen_powersource_event`), because the EC refuses performance mode off AC (driver comment).
  - OGH additionally sends `byBios = 1` in `0x1A` on battery (8C58). The 878A `GM1A` ignores byte 2, so its effect on 8746 is unknown.
  - Smart-adapter events and legacy `0x0F` report whether the 200 W adapter meets its requirement; below it, the EC throttles.
- **Lid closed:** **no evidence found** on any OMEN board. Measure it.
- **Suspend.** The siblings offer S3 and no S0ix (FADT LPS0 = 0).
  - `hp-wmi`'s resume handler refreshes only rfkill/dock/tablet state. It does **not** re-apply the thermal profile or max fan, and it would not re-arm manual fan state. Firmware-held fan state expires in about 120 s anyway.
  - EC-held settings (profile at 0x95, colours in shared memory) plausibly survive S3 because the EC stays powered; unverified.
  - S4/hibernation can reset firmware state: OmenHwCtl reports TGP reverting to lowest after hibernation on a 16-b1xxx with BIOS F.15.
  - The v11 LED patch sets `LED_CORE_SUSPENDRESUME`, so the LED core restores brightness.
- **BIOS F.44 (2024-08-12).** No release notes were found. A later **F.45** exists for 15-dh1xxx (HP forum, October 2025). Probes show F.10, F.28 and F.36 in the field.
  - Nothing public describes interface changes between these versions.
  - The only way to know is to compare DSDT dumps across BIOS versions with `check-omen-acpi.sh`, and to note that `hp-wmi` behaviour has been reported to change after BIOS updates on other boards (8BCA).

**Confidence.** Medium on AC behaviour; low on lid, suspend and BIOS deltas.

**Action.** Add AC, lid and suspend cases to the capture plan (below). Record the BIOS version with every capture.

---

## Blockers

1. **No HP-software capture exists for board 8746.** Every write beyond what `hp-wmi` already sends (`0x1A` V0, `0x27`) is unobserved on this board. The capture must be made on Windows **while OCC is still installed**.
2. **Firmware accepts unvalidated payloads** (878A `GM` handlers), so any invented byte reaches the EC or SMM.
3. **Read-named commands change state** (`0x10` → `OMCC`). "Probe with reads" is not safe on this interface.
4. **Manual fan control is a watchdog protocol.** It needs a heartbeat, and "0 = off" semantics. A crashed controller can leave fans at a low level. Only the kernel keep-alive path with a max-fan fallback is acceptable.
5. **Per-key keyboards** (type 3) are unreachable through the mailbox; per-key needs a USB-HID capture.
6. **Battery charge limit** appears to be absent from the mailbox.
7. **The kernel MUX write is likely refused** (byte 7 = 0 on the siblings) until patched.

## Ordered next actions

**On Windows, while OCC, Light Studio and Audio Control are installed:**

1. Clear or rotate the OGH logs. Then, on AC:
   - cycle every performance mode;
   - toggle max fan;
   - try every fan option OCC offers on this model (note whether manual/curve controls exist at all);
   - open the graphics switcher, but don't switch unless you intend to reboot;
   - set each keyboard zone colour, brightness and backlight on/off in Light Studio;
   - press the OMEN key and the backlight key.
   Repeat the mode and fan steps **on battery**, and with the lid closed on an external display if possible. Copy `…\LocalCache\Local\HPOMEN\HPOMENBG_*.log`.
2. Export `HKCU\Software\HP\OMEN Ally\Settings\SystemDesignData`, and extract the 8746 entries from OGH's embedded JSON (`HP.Omen.Core.Common.PowerControl.JSON.*`, `profiles.json`) by read-only reflection.
3. Record the OCC, Light Studio and HSA service versions (you have OCC 1101.2609.3.0) and the BIOS version.
4. Only if the logs lack bytes for a feature: attach a passive Frida hook to `DeviceIoControl` in the `WmiPrvSE.exe` that hosts `WmiProv`, after confirming the IOCTL path with API Monitor. Repeat the relevant clicks.
5. Dump ACPI tables. Registry-based dumps may lack FACP/NHLT, so a live-USB `acpidump` is better.

**From a Linux live USB (read-only):**

6. Run `sudo acpidump > acpi.txt`, then `check-omen-acpi.sh acpi.txt`. Decode `WQAB` with `bmfdec` to confirm the MOF. Compare `GM10`/`GM1A`/`GM27`/`GM2B`/`GM2D`/`GM2E`/`GM2F`/`GM28` and `WSMI` with 878A.
7. Run the sysfs checks from the companion report (`platform_profile`, hwmon, `gpu_mux_mode` read, `firmware-attributes`, `dmesg`, `evtest`). Check suspend/resume retention of profile and colours, and profile behaviour on AC unplug/replug.

**Afterwards, on Linux, only with HP-log evidence:**

8. Map each logged 8746 payload onto the existing `hp-wmi` code paths, then propose the gated patches from C9.

## Open gaps

- Which HP process issues the `ExecMethod` (background process or `HPOmenCap` after RPC), and the RPC protocol itself. Not needed if the log is complete.
- Whether 8746's ASL matches 878A: in particular `GM10` side effects, `GM2E` target registers, `GM28` byte 7, and any `WSMI`-only handlers.
- What `byBios` in `0x1A` does on 8746.
- Lid-closed fan/thermal behaviour on any OMEN.
- S3 retention of EC-held state, and S4 effects, on 8746.
- BIOS F.44 vs earlier/later versions: no release notes found.
- Whether OCC on 8746 offers manual fan or fan curves at all; if not, the firmware fan-level path may be unused by HP on this model.
- The exact Windows audio components behind OAC. Not needed, as nothing is portable.

---

## Sources

**Firmware (decoded here)**
- linuxhw/ACPI: `Notebook/Hewlett-Packard/OMEN/OMEN Laptop 15-ek0xxx/99FDA76A13EA` (board 878A) and `…/OMEN Laptop 15-en0xxx/53ADDB862BBA` (board 8786) — https://github.com/linuxhw/ACPI
- bmfdec (binary MOF decoder) — https://github.com/pali/bmfdec
- Your `_WDG` dump for 8746 (supplied in the brief)

**Kernel (torvalds/linux, v7.3-rc4 unless noted)**
- `drivers/platform/x86/hp/hp-wmi.c` (`hp_wmi_perform_query`, `encode_outsize_for_pvsz`, OMEN board lists, fan/keep-alive, `gpu_mux_mode`, `omen_powersource_event`, resume handler)
- `drivers/platform/x86/hp/hp-bioscfg/bioscfg.h` (settings GUIDs)
- `drivers/platform/x86/intel/wmi/thunderbolt.c`, `drivers/platform/x86/mxm-wmi.c`, `drivers/gpu/drm/nouveau/nouveau_acpi.c`, `drivers/platform/x86/wmi-bmof.c`
- Kernel ACPI-WMI interface doc — https://www.kernel.org/doc/Documentation/wmi/acpi-interface.rst
- Microsoft, "Windows Instrumentation: WMI and ACPI" (ACPI-WMI mapper, `WMxx` arguments) — https://learn.microsoft.com/en-us/previous-versions/windows/hardware/design/dn614028(v=vs.85)

**Mailing lists**
- Manual fan for Victus S (Chomal, v2) — https://lkml.iu.edu/2512.3/04738.html
- 8A13 support + per-fan PWM (GM2D/GM2E, EC offsets) — https://ratatoskr.run/platform-driver-x86/2026/05/9004910/t
- cTGP/PPAB review for 8C58 — https://ratatoskr.run/lkml/2026/09/17507832/t
- Rishit Bansal, "Support omen backlight control wmi-acpi methods" (2023) — https://lkml.iu.edu/2301.1/09123.html ; V3: https://lkml2.uits.iu.edu/hypermail/linux/kernel/2301.3/09869.html
- Hans de Goede on zoned-keyboard LED API (2023) — https://lkml.iu.edu/hypermail/linux/kernel/2302.0/05643.html
- Keyboard multicolor LED v6–v10 and v11 — https://ratatoskr.run/platform-driver-x86/2026/04/3535841/t , https://ratatoskr.run/platform-driver-x86/2026/09/17571031
- GPU MUX v5 (applied) — https://ratatoskr.run/lkml/2026/07/17311174/t
- Bug reports: 16-s1034nf fan reading — https://lkml.iu.edu/hypermail/linux/kernel/2412.1/06996.html ; 8BCA BIOS F.31 regression — https://lkml.iu.edu/2602.3/05799.html

**Projects (cloned and read)**
- Ohman, `docs/research.md` (OGH log-derived payloads, fan semantics, OGH internals, battery negative result, per-key HID) — https://github.com/P4R1H/Ohman ; https://ohmanapp.github.io/
- OmenMon (`Hardware/BiosCtl.cs`, `BiosData.cs`) — https://github.com/OmenMon/OmenMon ; issue #15 (HPIC devices/drivers) — https://github.com/OmenMon/OmenMon/issues/15
- OmenHubLight (reconstructed HP classes, `OmenDriverPatcher/patches.txt`) — https://github.com/determ1ne/OmenHubLight
- OmenHwCtl (OGH WMI calls in PowerShell; driver notes; hibernation TGP issue) — https://github.com/GeographicCone/OmenHwCtl
- yunusemreyl/omen-space (EC-write block list, WMAA-abort boards) — https://github.com/yunusemreyl/omen-space ; issue #175 (zero-instance GUIDs in dmesg) — https://github.com/yunusemreyl/omen-space/issues/175
- hippomasters/omen-rgb-linux (coexistence note) — https://github.com/hippomasters/omen-rgb-linux
- omencore issue #151 (Darfon per-key HID) — https://github.com/theantipopau/omencore/issues/151

**Reverse-engineering write-ups and forums**
- Rishit Bansal, "Reverse Engineering Keyboard Driver" parts 1–2 — https://dev.to/rishit/reversing-keyboard-driver-part-1-introduction-2hdg , https://dev.to/rishit/reverse-engineering-keyboard-driver-part-2-decompiling-net-applications-44l2
- HP community: HSA software component — https://h30434.www3.hp.com/t5/Desktop-Software-and-How-To-Questions/HP-Inc-SoftwareComponent-1-0-804-0/td-p/8528894
- HP community: OMEN Audio Control / B&O / DTS — https://h30434.www3.hp.com/t5/Gaming-Notebooks/HP-Omen-15-dc1060nr-laptop-Bang-and-Olufsen-Enhanced-Output/td-p/7842093
- HP community: 15-dh1xxx BIOS F.45 — https://h30434.www3.hp.com/t5/Gaming-Notebooks/Current-BIOS-version/td-p/9519219
- WMI activity auditing (event 4662) — https://www.darkoperator.com/blog/2022/3/27/tracking-wmi-activity-with-psgumshoe
- Win-Raid, OMEN 15-dc0 BIOS brick — https://winraid.level1techs.com/t/hp-omen-15-dc0850nd-bios-bricked/39814
