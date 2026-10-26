# Omen Sense: the app

A Linux replacement for OMEN Gaming Hub on the **HP OMEN 15-dh1xxx, board
8746**. It is one window plus a command line, both on top of the patched
`hp-wmi` driver (`driver/INSTALL.md`). Install the driver first; without it
the app has nothing to control.

It is adapted from orion-sense, the Acer Predator Orion app, and keeps the same
layout and safety rules.

## What it does

| Section | What you get |
|---|---|
| **Monitor** | CPU, GPU and chipset temperature gauges, two minutes of history, GPU details, CSV logging |
| **Cooling** | Both fan speeds (measured), Auto / Max fan, and **Smart mode**, which picks the mode from temperature |
| **Power** | Cool / Balanced / Performance, charger and battery state, CPU power limit |
| **Lighting** | A drawn keyboard. Click a key to pick its zone (Left, WASD, Centre, Right + numpad), then set colour and brightness. Ten one-click **layouts** (Rainbow, Ocean, Sunset, Jungle, Neon, Ice, WASD focus, All red, All white, Factory). Or let it run by itself with an **effect**: Temperature (follows the CPU), Colour cycle, Rainbow wave, Breathing, Heartbeat, Chase, Fire or Aurora. Breathing, Heartbeat and Chase animate your own colours. **Turn keyboard off** switches the backlight off for real and keeps your colours |
| **Audio** | **HP's own speaker tuning**, rebuilt in PipeWire: HP tuning, Music, Movie, Voice and Game, read from the DTS:X Ultra files on the Windows side (`omen-sense audio import`). The EQ is exact. DTS's bass enhancement is stood in for by Bankstown (Asahi Linux's virtual bass) set from HP's bass levels, with a −1 dB safety limiter; dialogue enhancement and 3D aren't reproduced. Speakers only. **Headphones** get their own options: **Crossfeed** (bs2b) or **Virtual speakers** (PipeWire's spatializer with the MIT KEMAR head, speakers at ±30°); HP's own headphone tuning turned out to have no EQ to copy |

The panel on the right is always visible. It shows CPU and GPU temperature,
CPU load, RAM in use, both fans and the power limit. It lets you save named
profiles (mode + fan + keyboard + audio), set one to apply at login, start
the app with the computer, and make the **OMEN key** open the window (a GNOME
shortcut; pressing it while the app runs in the panel just brings it forward,
because only one copy ever runs).

**Keyboard colours come back after a reboot.** The firmware resets the
keyboard to red / green / blue / white at every boot. The app remembers your
last colours, and `omen-sense-apply.service` puts them back when you log in.
A running effect is remembered too: it starts again a few seconds after the
window opens, so with **Start with the computer** on it comes back at every
login.

## How it stays safe

- **Only HP-observed writes.** Every firmware write is one that HP's own
  software was seen sending on this laptop. Max fan was the last to meet
  that bar (see below).
- **Rate limits.** Colour-wheel drags are merged into one write every 150 ms.
  Smart mode changes the mode at most once a minute, with a 4 °C margin.
  Temperature lighting rewrites the keyboard at most every 5 s, and only when
  the colour step really changes. The animated effects draw at most
  5 frames a second and skip zones whose colour hasn't changed.
  `tests/test_logic.py` checks all of this.
- **Why animation is allowed at all.** The keyboard can't animate by itself,
  so the window rewrites the zones. HP does the same on this laptop: OMEN
  Light Studio's saved profile is a software Wave over the four zones. The
  colour-write handler (`LM03`) raises no event, so it can't loop the way the
  mode switch once did. 5 frames a second is at most 60 firmware calls a
  second, under half of what the community `omen-rgb-keyboard` driver sends
  to the same keyboards. On this laptop the driver kept up with every frame:
  25 of 25 read back correctly, with no errors.
- **The backlight key always wins.** It turns the keyboard off even while
  an effect runs; the effect carries on in the dark and shows again when you
  press the key. (This needed a driver fix; see `driver/INSTALL.md`.)
- **Clean exit.** Stopping Smart mode or any lighting source, including on
  quit or logout, puts back the mode and colours you had before. The
  animations only run while the app does.

## Run it from the folder (try this first)

On Ubuntu, copy the whole `OmenSense` folder over (a USB stick is easiest),
then:

```
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtgui python3-pyside6.qtcore libqt6svg6 fonts-ibm-plex
python3 tests/test_logic.py                   # should end with ALL PASS

sudo cp packaging/60-omen-sense.rules /etc/udev/rules.d/
sudo usermod -aG plugdev $USER                # then log out and back in
sudo udevadm control --reload-rules
sudo modprobe -r hp_wmi && sudo modprobe hp_wmi   # re-create the files with the new permissions

PYTHONPATH=gui python3 -m omensense status    # command line
PYTHONPATH=gui python3 -m omensense           # the window
```

Without the udev rule and the `plugdev` group, reading works but every change
fails with "No permission …". That's expected, not a bug.

## Install it as a package

```
./packaging/build-deb.sh
sudo apt install ./packaging/deb/omen-sense_0.5.0_all.deb
systemctl --user enable --now omen-sense-apply.service
```

After that it's in the app menu as **Omen Sense**, and `omen-sense` works in
any terminal.

## Command line

```
omen-sense status                          # everything at once
omen-sense power cool|balanced|performance
omen-sense fan auto                        # or: fan max
omen-sense light all --colour 00AEC7
omen-sense light wasd --colour FF0000 --brightness 100
omen-sense light --layout rainbow          # or ocean, sunset, jungle, neon, ...
omen-sense light off                       # backlight off, colours kept
omen-sense light on
omen-sense headphones crossfeed           # or: speakers, off
omen-sense profile save Gaming
omen-sense profile startup Gaming
omen-sense log --interval 5
```

## Max fan

**On since 2026-09-28.** `0x27 {1}` was the last write waiting for evidence.
HP's software was seen sending it on this laptop, in that day's
`HPOMENBG_*.log`: `SetMaxFan(), mode = On` followed by `inputData=1`, three
times. The firmware's handler (`GM27`) turns it into the controller's max-fan
command and raises no event. Tested: the fans went from 2200/2400 to about
4500/4700 rpm within 3 s, and back down on Auto.

Max pins both fans at full speed whatever the temperature, so it's loud. It
stays on until you pick Auto; loading the driver (every boot) sets it back to
Auto.

## Please check while trying it

- **Keyboard drawing:** confirmed. All four zones change colour where the
  drawing says they do (checked 2026-09-28).
- **Fans:** settled as far as it can be. Under a GPU-only benchmark (GPU 95 %,
  CPU 5 %) both fans rose together, 1800/2000 → 3100/3300 rpm. Fan 2 stays
  about 200 rpm above Fan 1 at every speed. They only rose once the CPU passed
  about 80 °C: the heat pipes are shared, so the GPU heats the CPU as well. The
  embedded controller drives them as a pair, so their speeds can't tell you
  which is which, and they keep neutral names.
- **Smart mode:** does it feel right? The thresholds are 55 °C for Cool and
  80 °C for Performance by default, and can be changed on the Cooling page.
