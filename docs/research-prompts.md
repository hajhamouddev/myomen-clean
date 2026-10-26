# Deep research prompts — Linux support for HP OMEN 15-dh1xxx (board 8746)

Two prompts. They are independent and can run in parallel:

1. **Landscape** — what already works on Linux for this exact machine, and which
   projects exist. This decides whether there is anything to build at all.
2. **Interface** — how HP's OMEN firmware interface works and how it differs
   from the Acer Predator Orion project this is modelled on. This decides what
   building would look like, and what is dangerous.

Lesson carried from the Acer project: its research prompt listed two "already
established" facts that were wrong, and every run built on them. So the
machine facts below are split into **measured** (read from this laptop, with
the method stated) and **believed** (to be verified, not built on).

---

## Shared context — paste at the top of both prompts

### Measured on the machine (Windows 11, 2026-09-26, read-only queries)

| | value | how measured |
|---|---|---|
| Model | OMEN by HP Laptop 15-dh1xxx | `Win32_ComputerSystem` |
| SKU | `132Z1EA#AB8` | `SystemSKUNumber` |
| System family | `103C_5335KV HP OMEN` | `SystemFamily` |
| Board ID | **`8746`**, version 04.35 | `Win32_BaseBoard.Product`; also the ACPI table OEM table ID |
| BIOS | AMI **F.44**, 2024-08-12 | `Win32_BIOS` |
| CPU | Intel Core i7-10750H (Comet Lake-H, 6C/12T) | `Win32_Processor` |
| dGPU | NVIDIA GeForce RTX 2060 Mobile, PCI `10DE:1F15`, subsystem `103C:8746` | PnP |
| iGPU | **not enumerated at all** — Windows lists only the NVIDIA adapter. The CPU has UHD 630, so it is either disabled by a MUX / BIOS graphics setting, or this SKU wires the panel to the dGPU only | `Get-PnpDevice -Class Display` |
| Panel | 1920×1080 @ 144 Hz | `Win32_VideoController` |
| RAM | 2 × 8 GB Samsung DDR4-3200 SO-DIMM | `Win32_PhysicalMemory` |
| Storage | Samsung PM981a 512 GB NVMe (`MZVLB512HBJQ-000H1`) | `Get-PhysicalDisk` |
| Audio codec | Realtek **ALC285** (`10EC:0285`, subsystem `103C:8746`) via Intel Smart Sound (SST) | PnP |
| Keyboard | PS/2, ACPI `HPQ8001`. No separate USB/HID lighting controller seen | PnP |
| Touchpad | ELAN `ELAN0711` over I2C-HID | PnP |
| HP ACPI devices | `HPIC0004` "HP Omen Driver", `HPIC0003` "HP Application Driver", `HPQ6001` wireless button | PnP |
| HP Windows software | OMEN Command Center 1101.2609.3.0, OMEN Light Studio 1.0.69.0, OMEN Audio Control 1.12.219.0, HP System Event Utility 3.2.24.0; services `HPOmenCap`, `HPAppHelperCap`, `HPSysInfoCap` | Appx list, services |
| WMI classes (`root\wmi`) | `hpqBIntM`, `hpqBDataIn`, `hpqBDataOut0/4/128/1024/4096`, `hpqBEvnt`, `HPBIOS_BIOSEvent`, `HP_BIOSEvent` | `Get-CimClass` |

ACPI-WMI GUIDs parsed from the `_WDG` buffers of this machine's DSDT and SSDTs
(dumped from the Windows registry copy):

```
DSDT block (14 entries):
  5FB7F034-2C63-45E9-BE91-3D44E2C707E4  obj AA  method
  95F24279-4D7B-4334-9387-ACCDC67EF61C  event notify 0x80
  2B814318-4BE8-4707-9D84-A190A859B5D0  event notify 0xA0
  1F4C91EB-DC5C-460B-951D-C7CB9B4B8D5E  obj BA  method
  2D114B49-2DFB-4130-B8FE-4A3C09E75133  obj BC  data, 77 instances
  988D08E3-68F4-4C35-AF3E-6A1B8106F83C  obj BD  data, 24 instances
  14EA9746-CE1F-4098-A0E0-7045CB4DA745  obj BE  data, 2 instances
  322F2028-0F84-4901-988E-015176049E2D  obj BF  data
  8232DE3D-663D-4327-A8F4-E293ADB9BF05  obj BG  data
  8F1F6436-9F42-42C8-BADC-0E9424F20C9A  obj BH  data, 0 instances
  8F1F6435-9F42-42C8-BADC-0E9424F20C9A  obj BI  data, 0 instances
  7391A661-223A-47DB-A77A-7BE84C60822D  obj AC  method, 0 instances
  DF4E63B6-3BBC-4858-9737-C74F82F821F3  obj BJ  data, 0 instances
  05901221-D566-11D1-B2F0-00A0C9062910  obj AB  (binary MOF)
DSDT, other blocks:
  86CCFD48-205E-4A77-9C48-2021CBEDE341  obj TF  method
  2BC49DEF-7B15-4F05-8BB7-EE37B9547C0B  obj DE  method  (+ event A6FEA33E-… notify 0xD0)
  1F13AB7F-6220-4210-8F8E-8BB5E71EE969  obj DE  method
SSDT (NVIDIA / Optimus-MXM related):
  CA4982BF-C230-458E-B12F-6F16475F351B  obj OP  method
  F6CB5C3C-9CAE-4EBD-B577-931EA32A2CC0  obj MX  method  (+ 7 events)
```

### Believed, not verified — check these, do not build on them

- `5FB7F034-…` is the HP BIOS WMI interface that mainline `drivers/platform/x86/hp/hp-wmi.c`
  calls `HPWMI_BIOS_GUID`, and `95F24279-…` is its event GUID.
- Mainline `hp-wmi` already supports OMEN thermal profiles through
  `platform_profile`, plus some fan reporting and control, and board `8746` may
  be on its OMEN board list.
- `2D114B49-…` / `988D08E3-…` etc. are the HP BIOS-settings interface used by
  `hp-bioscfg`.
- The keyboard backlight is either 4-zone RGB or single-colour. Owning OMEN
  Light Studio suggests RGB, but that is not confirmed.

### The reference project

This follows a finished project, **orion-sense**: a Linux kernel module
(hwmon fans/temps/pwm, `platform_profile`, `leds-class-multicolor` zones), a Qt
GUI + CLI, and packaging (DKMS, MOK signing under Secure Boot, udev,
systemd), replacing Acer PredatorSense on an Acer Predator Orion desktop. There,
**nothing upstream worked**: `acer-wmi` used the laptop method map on a
desktop ABI, so a new driver was required. The question now is how much of that
is necessary here, where the vendor interface is much better known upstream.

### Governing safety rule (carried over)

**No invented value is ever sent to firmware.** Every byte written must trace
to vendor code, a vendor-authored constant, an upstream driver that sends it
on this board, or a captured payload from HP's own software. Unknown method
IDs are usually refused safely; unknown *payloads* can reach SMM or the EC with
no protection. A related Acer project crashed a machine probing an unobserved
selector on a "Get" call — being a read does not make a call safe. Flag anything
in the research that would break this rule, and prefer observing or reading
over probing by writing.

### Standard for sources

Prioritise **primary sources**: kernel source at a named tag, `Documentation/`,
lore.kernel.org threads, project source code, HP's own documentation. Treat
blogs, Reddit and forum posts as **leads to verify**, not evidence. A confirmed
"nobody has published this" is a useful result — say so explicitly rather than
guessing. Where something is board-specific, say whether the evidence is about
board `8746`, the 15-dh1xxx family, or OMEN laptops in general.

---

## Prompt 1 — Landscape: what already works, and what exists

> *(paste the shared context above first)*

### Role and goal

You are deciding whether a Linux replacement for **OMEN Command Center / OMEN
Light Studio / OMEN Audio Control** needs to be built for an **HP OMEN 15-dh1xxx,
board 8746**, or whether existing kernel drivers and open-source projects
already cover it. The target is feature parity for: fan monitoring and control,
performance/thermal modes, keyboard lighting, GPU mode/MUX, monitoring, and
audio. Assume a current Ubuntu/Kubuntu with a recent kernel (6.x–7.x).

### Research questions

**A. Upstream kernel coverage, board by board**

1. In mainline `hp-wmi.c` (cite the latest tag and relevant commits), what does
   the driver do for OMEN machines: `platform_profile` (which profiles, and how
   it picks the thermal-policy variant per board), fan RPM via hwmon,
   `pwm1_enable` / max-fan, keyboard backlight, the OMEN key, GPU mode? **Is
   board `8746` in any of its board-ID tables** (`omen_thermal_profile_boards`,
   the V1 / "force V0" / Victus lists, or similar)? If yes, which list and what
   does membership imply? If no, what happens on an unlisted OMEN board?
2. Which commits added OMEN support, and which boards were tested? Find the
   lore threads and any reports specifically for 15-dh1xxx / 8746 / 8747 / 8748
   / 8749 / 874A (the neighbouring 2020 OMEN 15 boards).
3. **Fan control upstream:** can fans be set to a manual speed, or only "max"
   vs "auto"? Is there any fan-curve support, and has anyone proposed patches
   (merged, rejected or pending) to add more? Summarise what maintainers said.
4. Does `hp-bioscfg` bind on this model, and what does it expose?
5. **Keyboard lighting upstream:** is there any mainline support for OMEN 4-zone
   keyboard RGB (e.g. through `leds-class-multicolor`)? If there are pending or
   rejected patches, link them and summarise the review.

**B. Out-of-tree and userspace projects**

6. List every open-source project that controls OMEN laptops on Linux:
   out-of-tree kernel modules (e.g. patched `hp-wmi` forks with keyboard RGB or
   fan control), CLIs, GUIs, daemons. For each: repo link, last commit date,
   licence, features, **which boards/models it claims or was tested on**,
   whether 15-dh1xxx is mentioned, open issues relevant to this model, and how
   it reaches the hardware (WMI via kernel module, `ec_sys`/EC register writes,
   `acpi_call`, etc.). Flag any that write raw EC registers or invented values,
   since that breaks the safety rule.
7. List **open-source Windows tools** for OMEN laptops (for example OmenMon, and
   any others). These matter because their source documents the BIOS WMI
   commands HP's own software sends. For each: which commands/queries it uses,
   and whether it was tested on 15-dh1xxx.
8. Do general tools already handle this machine: **CoolerControl**, `fancontrol`
   / lm-sensors, **NBFC-Linux** (is there a config for OMEN 15-dh1xxx, and does it
   write the EC directly?), `power-profiles-daemon`, `tuned-ppd`, OpenRGB (does
   it support OMEN laptop keyboards, and which models?).

**C. Everything else on this machine under Linux**

9. **Graphics:** does the 15-dh1xxx have a hardware MUX, Advanced Optimus, or
   neither? How is dGPU-only vs hybrid mode switched (BIOS setting, OMEN Command
   Center, WMI call)? What does Linux do with it — `supergfxctl`,
   `envycontrol`, `prime-select`, any HP-specific support? Note that Windows
   currently enumerates **no Intel iGPU at all** on this machine.
10. **Audio:** ALC285 on HP boards needs `snd-hda-intel` quirks for the speakers,
    mute LED and mic-mute LED. Is there a quirk for subsystem `103C:8746` in
    `sound/pci/hda/patch_realtek.c`? What do owners report (speakers, internal
    mic via SST/SOF, headphone jack)? What is OMEN Audio Control built on (DTS,
    Bang & Olufsen, something else) and is any of it portable?
11. **Hotkeys and extras:** OMEN key, Fn keys, keyboard-backlight key, airplane
    mode (`HPQ6001`), touchpad (`ELAN0711`), suspend/s2idle vs S3, battery charge
    limit. Which work out of the box, which need quirks?
12. **Owner reports:** collect first-hand Linux reports for this model (Arch wiki,
    Ubuntu/Fedora forums, Reddit, GitHub issues, linux-hardware.org probes). A
    `linux-hardware.org` probe for board 8746 would be especially useful.

### Output format

Start with a one-screen **verdict table**: each feature (fan RPM, fan control,
thermal modes, keyboard RGB, GPU mode, audio, hotkeys, battery limit) → *works
upstream / works with project X / partial / missing* → confidence → source.

Then one section per lettered group. For each numbered question:

- **Answer** — direct, with the specific finding
- **Evidence** — links, file paths, function names, commit hashes, threads
- **Confidence** — high / medium / low, and what would raise it
- **Action** — what this means concretely: use as-is, contribute upstream,
  adopt a project, or build

End with:

1. **Build or adopt?** — a direct recommendation, with reasons
2. **Gaps** — features with no existing solution for this board
3. **What to measure on the machine** — cheap checks from a Linux live USB that
   would settle the open questions (e.g. `ls /sys/bus/wmi/devices`,
   `cat /sys/firmware/acpi/platform_profile_choices`, `sensors`, `dmesg | grep hp`)

---

## Prompt 2 — Interface: how HP's OMEN firmware interface works, and how it differs from Acer's

> *(paste the shared context above first)*

### Role and goal

You are documenting the **HP OMEN laptop firmware control interface** well enough
to (a) judge how it differs from the Acer Predator Orion interface described
below, and (b) plan any driver work for board 8746 **without sending invented
values to firmware**. Research only; nothing will be sent to hardware based on
this report until it is confirmed by observation.

### How the Acer interface worked, for comparison

- One WMI GUID with 12 methods on class `AcerGamingFunction`; u64/u32 and
  byte-array arguments packed with sub-selectors in the low byte.
- Call path: Electron app → plaintext JSON on TCP 127.0.0.1:46933 → Acer
  service → WMI → ACPI `WMBH` → SMI 0x91 → SMM. The AML was only a mailbox shim,
  so the packing appeared in no firmware table and had to be captured from the
  vendor service with a frida hook.
- Lighting was forwarded to a bundled OpenRGB; audio was a DTS Windows APO.
- GPU fan was not on the vendor interface (NVML owned it).

### Research questions

**A. The HP BIOS WMI protocol**

1. Describe the call format of the HP BIOS WMI method (`5FB7F034-…`, method
   `hpqBIntM` / `hpqBDataIn` → `hpqBDataOut*`): signature, `command` vs
   `commandtype`, the size classes (0/4/128/1024/4096), return codes, and how
   `hp-wmi.c` implements it (`hp_wmi_perform_query` or its current name).
2. Build a table of **every known command / command-type pair relevant to OMEN
   machines**: thermal policy get/set, fan speed get, fan count, max-fan get/set,
   fan level/table, GPU power (Dynamic Boost/TGP/PPAB), GPU mode / MUX,
   keyboard type, keyboard colour table (the 4-zone colour command and its
   byte layout), keyboard brightness, backlight on/off, animation/effects,
   system design data, battery charge control, OMEN key. For each, give **the
   source that shows it being sent** (hp-wmi line, OmenMon source, another
   project) and which boards it was confirmed on. Distinguish **observed being
   sent by HP software** from **used by a community tool** from **guessed**.
3. What are the **other GUIDs** on this machine for — `1F4C91EB-…` (BA),
   `7391A661-…` (AC), `86CCFD48-…` (TF), `2BC49DEF-…` / `1F13AB7F-…` (DE), and
   the data blocks `2D114B49-…`, `988D08E3-…`, `14EA9746-…`, `322F2028-…`,
   `8232DE3D-…`, `8F1F6435/6-…`, `DF4E63B6-…`? Cite drivers or docs that
   reference them. Which belong to `hp-bioscfg`, which to Sure Start / security,
   which to NVIDIA (`OP`, `MX`)?
4. Where does the call end up: an EC mailbox (ACPI `EC0` fields), SMI/SMM, or
   both? Are there known cases of these WMI commands **bricking, hanging or
   damaging** OMEN machines, or of community tools writing raw EC registers and
   causing trouble? Which commands are known-dangerous?

**B. How HP's own software talks to firmware**

5. How does **OMEN Command Center** (UWP, `AD2F1837.OMENCommandCenter`) reach the
   hardware — through the `HPOmenCap` HSA service, a driver behind the
   `HPIC0004` "HP Omen Driver" device, direct WMI, or a local socket/named pipe?
   Has anyone documented this path (the equivalent of Acer's TCP 46933 `[PA]`
   protocol)?
6. What is the **safest way to observe it** on Windows 11: ETW providers for
   WMI-Activity, hooking `IWbemServices::ExecMethod` in the service with frida,
   IRP monitoring of the HP driver, or tracing the UWP↔service channel? Which
   process should be hooked? Note: on the Acer machine, a frida hook on the
   vendor service's WMI calls captured every payload; the HSA/UWP split may
   change that.
7. Same questions for **OMEN Light Studio** (does it use the same BIOS WMI
   keyboard commands, or a separate path?) and **OMEN Audio Control** (what audio
   stack it drives).

**C. Differences that change the design**

8. Given the answers above, lay out **Acer Orion vs HP OMEN 15-dh1xxx** side by
   side: interface discovery (MOF/documented vs captured), upstream driver state,
   fan model (per-fan duty vs max/auto vs level table), thermal profiles,
   lighting (EC-hosted effects vs host-side colour table), GPU control
   (absent vs MUX/TGP present), event/hotkey handling, and packaging (DKMS
   module vs upstream patch vs userspace only).
9. If an addition is needed (e.g. keyboard RGB or manual fan control), is the
   right vehicle **a patch to mainline `hp-wmi`** (and what have maintainers
   accepted or rejected for OMEN features — cite threads), a separate
   out-of-tree module that coexists with `hp-wmi`, or userspace? How do two
   drivers share `5FB7F034-…` safely?
10. **Laptop-specific concerns absent on the desktop:** battery/AC-dependent
    thermal limits, what happens to fan control when the lid closes, suspend
    (s2idle vs S3) and whether settings survive resume, and whether BIOS F.44
    (2024) changed any of this relative to older BIOS versions.

### Output format

A structured report, one section per lettered group. For each numbered
question:

- **Answer** — direct, with the specific finding
- **Evidence** — links, file paths, function names, commit hashes, threads
- **Confidence** — high / medium / low, and what would raise it
- **Action** — what it implies concretely

Include a **command table** (question 2) as a single table: command, type, size,
direction, meaning, payload layout, source, boards confirmed, and an
*observed / community / guessed* column.

End with:

1. **Blockers** — anything that makes part of this infeasible or unsafe
2. **Ordered next actions** — noting which must happen on Windows (captures of
   OMEN Command Center / Light Studio) while it is still installed, and which
   can be done from a Linux live USB
3. **Open gaps** — questions still unanswered after the research

### Constraints

- CPU/GPU overclocking and undervolting are out of scope.
- Do not propose probing unknown commands or payloads on the machine. If a
  value is only known from a community tool and never seen from HP's software,
  say so, and propose how to observe HP's software sending it instead.
