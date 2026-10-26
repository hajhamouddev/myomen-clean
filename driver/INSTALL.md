# Installing the patched hp-wmi on board 8746

A patched `hp-wmi` driver for the **HP OMEN 15-dh1xxx, board 8746**, running
Ubuntu. Background and evidence: `../docs/findings-8746.md`.

## What it fixes

| | stock `hp-wmi` on 8746 | patched |
|---|---|---|
| Performance modes | missing: no `platform_profile`, KDE power slider does nothing | Cool (as `low-power`) / Balanced / Performance |
| Fan speed | always 0 RPM | real RPM |
| Keyboard RGB | none | 4 zones as `/sys/class/leds/hp::kbd_zoned_backlight-{right,center,left,wasd}` |

**How:**

- **Modes:** the driver reads the current mode from EC byte `0x29` instead of
  `0x95`. On this board, `0x95` is part of the battery's part-number text.
- **Fan speed:** read through query `0x2D` instead of `0x11`, which returns
  zeros on this board.
- **No mode-switch loop:** after every mode change the firmware raises WMI
  event `0x1B`. Stock `hp-wmi` takes that as the Fn+P key and switches mode
  again, which raises `0x1B` again, forever (about 700 mode writes a second).
  On 8746 the driver ignores that event.
- **Cool shows as `low-power`:** `power-profiles-daemon` doesn't know `cool`,
  so the desktop's Power Saver did nothing. Same firmware mode, new name.
- **Keyboard RGB:** the upstream v11 patch (reviewed by Hans de Goede, not
  merged yet), plus fixes for this board:
  - v11 turned the other zones white when you lit one zone with the
    backlight off.
  - **HP firmware bug:** the colour read returns the Right zone's blue from
    the Centre zone. v11 reads the table before every write, so each change
    to another zone copied Centre's blue into Right, and Right flashed during
    effects. The driver now writes the whole table from its own record, the
    way HP's software does, with no read. That's 1 firmware call per zone
    instead of 3, under a lock so writes can't interleave.
  - **Backlight key:** the firmware handles the key by itself and tells the
    driver nothing. v11 switched the backlight back on for every colour
    write, so the key couldn't keep the keyboard off. Now it only switches
    on when a zone goes from dark to lit.
  - **A real off:** v11's brightness 0 only wrote black. With every zone at
    0, the driver now sends HP's own backlight-off command, and lighting a
    zone again sends "on".

**Safety:** nothing new is written to the firmware.

- Mode changes use the same three payloads HP's own software sends on this
  laptop: `{FF,00}`, `{FF,01}` and `{FF,02}`.
- The fan reading only reads.
- All changes apply only when the board is 8746.

## Files

| File | Purpose |
|---|---|
| `kbd-rgb-v11.patch` | Upstream keyboard RGB patch v11 (patchwork 14812352), `hp-wmi.c` part. The installer checks its SHA-256 before applying it |
| `patch-8746.py` | Makes six edits to Ubuntu's own `hp-wmi.c`. Aborts without writing anything if the source isn't exactly as expected |
| `install-8746.sh` | Gets Ubuntu's kernel source, patches it, does a trial build, then installs through DKMS with Secure Boot signing |
| `verify-8746.sh` | Checks modes, fan speed and a Low-power → Performance → Balanced round trip. Writes a report file |
| `Makefile`, `dkms.conf` | Build files. DKMS rebuilds the driver automatically after kernel updates |

## Steps

1. **Copy this `driver` folder to Ubuntu.**
   - A USB stick is easiest.
   - You can also open the Windows drive from Ubuntu's file manager. If it
     refuses, Windows Fast Startup is locking it; use the USB instead.

2. **Install.** Open a terminal inside the folder and run:

   ```
   sudo bash install-8746.sh
   ```

3. **If it asks you to set a password:** Secure Boot needs your signing key
   enrolled once.
   1. Choose a short password.
   2. Reboot. A blue **MokManager** screen appears.
   3. Choose **Enroll MOK → Continue → Yes**, type the password, then
      **Reboot**.

4. **Verify.** Back in Ubuntu, with **the charger plugged in** (Performance
   only works on AC), run:

   ```
   sudo bash verify-8746.sh
   ```

   Bring back the `verify-8746-*.txt` file it writes.

## What a good result looks like

- `choices: low-power balanced performance`
- A fan reading well above 0 RPM, close to `EC[0x11] × 100`.
- Round trip: `EC[0x29]` reads 2 for low-power (Cool), 1 for performance and 0 for
  balanced, and each profile reads back as the one that was set.
- `dmesg` shows `board 8746 quirk: fan RPM via query 0x2D, profile at EC 0x29`.
- Four `hp::kbd_zoned_backlight-*` zones. With the backlight on, WASD turns
  red for 2 s and comes back. With it off, that test is skipped.

## If something goes wrong

- **The install stops before step 6 (DKMS install):** nothing was installed,
  and the system is unchanged.
- **Back to the stock driver at any time:**

  ```
  sudo bash install-8746.sh --remove
  ```

- **After a kernel update the driver fails to build:** DKMS leaves the stock
  module in place. The laptop keeps working, just without modes and fan RPM.
  Re-run `install-8746.sh`.

## Not included yet

- **Battery care and Fan Always On.** These need the `hp-bioscfg` firmware bug
  worked around first. Both are on, and can be changed in BIOS setup (F10).
