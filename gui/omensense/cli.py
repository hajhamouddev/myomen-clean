"""Command line for omen-sense.

Deliberately free of any Qt import. This is what a systemd user unit runs at
login and what a keyboard shortcut binds to, so it has to start immediately and
work with no display attached.

Everything the window can do is here, which is also what makes the window
testable: the same calls, without a mouse.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import audio, effects, gpu, hw, monitoring, state


def _fail(message: str) -> int:
    print(f"omen-sense: {message}", file=sys.stderr)
    return 1


def _report(problems) -> int:
    if isinstance(problems, str):
        problems = [problems]
    problems = [p for p in problems or [] if p]
    for problem in problems:
        print(f"omen-sense: {problem}", file=sys.stderr)
    return 1 if problems else 0


def _parse_colour(text: str):
    text = text.lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


# ------------------------------------------------------------------ reads

def cmd_status(_args) -> int:
    for problem in hw.driver_problems():
        print(f"warning   {problem}")
    data = hw.sensors()
    card = gpu.read()
    source = hw.power_source()

    mode = hw.profile()
    print(f"Mode      {hw.PROFILE_TITLES.get(mode, mode or '--')}"
          f"   ({hw.power_limit_w() or '--'} W limit)")
    ac = source.get("on_ac")
    print(f"Power     {'charger' if ac else 'battery' if ac is False else '--'}"
          f"   battery {source.get('percent', '--')}% "
          f"{(source.get('status') or '').lower()}")

    fans = data.get("fans") or []
    for index, name in enumerate(hw.FAN_LABELS):
        rpm = fans[index] if index < len(fans) else None
        print(f"{name:<10}{'--' if rpm is None else rpm:>6} rpm")
    maxed = hw.max_fan()
    print(f"Max fan   {'on' if maxed else 'off' if maxed is False else '--'}")

    print(f"Temps     CPU {data.get('cpu_temp', '--')} °C"
          f"   Chipset {data.get('sys_temp', '--')} °C")

    # CPU load needs two readings; a quarter of a second apart is enough.
    meter = monitoring.CpuLoad()
    meter.percent()
    time.sleep(0.25)
    cpu = meter.percent()
    ram = monitoring.memory()
    print(f"Load      CPU {'--' if cpu is None else cpu} %"
          + (f"   RAM {ram['percent']} % ({ram['used_gb']:.1f} of "
             f"{ram['total_gb']:.1f} GB)" if ram else "   RAM --"))
    if card:
        # nvidia-smi reports no fan on this laptop: the two EC fans cool both.
        fan = card.get("fan_percent")
        print(f"GPU       {card.get('temp', '--')} °C"
              + (f"   {fan}% fan" if fan is not None else "")
              + f"   {card.get('clock_mhz', '--')} MHz")

    preset = audio.PresetEngine().current
    print(f"Audio     {audio.PRESETS[preset]['title'] if preset else 'off'}")

    for zone in hw.ZONES:
        red, green, blue = hw.zone_colour(zone)
        print(f"Key {hw.ZONE_TITLES[zone]:<15}#{red:02X}{green:02X}{blue:02X}"
              f"  brightness {round(hw.zone_brightness(zone) * 100 / hw.LED_MAX)}%")
    return 0


def cmd_sensors(args) -> int:
    """One line of readings, for logging or scripting."""
    row = monitoring.sample()
    if args.header:
        print(",".join(monitoring.FIELDS))
    elif args.csv:
        print(",".join("" if row[k] is None else str(row[k])
                       for k in monitoring.FIELDS))
    else:
        for key in monitoring.FIELDS:
            value = row[key]
            print(f"{key:<14}{'--' if value is None else value}")
    return 0


# ----------------------------------------------------------------- writes

#: Friendly names on the command line, the kernel's names underneath.
MODE_ALIASES = {"cool": "low-power", "quiet": "low-power",
                "default": "balanced", "turbo": "performance"}


def cmd_power(args) -> int:
    if not args.mode:
        mode = hw.profile()
        print(hw.PROFILE_TITLES.get(mode, mode or "--"))
        return 0
    mode = MODE_ALIASES.get(args.mode, args.mode)
    choices = hw.profile_choices()
    if mode not in choices:
        return _fail(f"unknown mode {args.mode!r}; try: cool balanced performance")
    if mode == "performance" and hw.power_source().get("on_ac") is False:
        print("omen-sense: on battery - the firmware applies Performance "
              "only on the charger", file=sys.stderr)
    return _report(hw.set_profile(mode))


def cmd_fan(args) -> int:
    if args.setting is None:
        maxed = hw.max_fan()
        print("max" if maxed else "auto" if maxed is False else "--")
        return 0
    if args.setting == "auto":
        return _report(hw.set_max_fan(False))
    if args.setting == "max":
        return _report(hw.set_max_fan(True))
    return _fail("fan takes 'auto' or 'max' - this board has no duty control")


def cmd_light(args) -> int:
    if args.zone in ("off", "on"):
        if args.colour or args.brightness is not None or args.layout:
            return _fail(f"'light {args.zone}' takes no other options")
        return _report(state.keyboard_off() if args.zone == "off"
                       else state.keyboard_on())
    if args.layout:
        if args.zone not in (None, "all") or args.colour:
            return _fail("--layout sets every zone; it takes no zone or --colour")
        code = _report(effects.apply_layout(args.layout))
        if code == 0:
            state.remember_lighting()
        return code
    zones = list(hw.ZONES) if args.zone in (None, "all") else [args.zone]
    for zone in zones:
        if zone not in hw.ZONE_TITLES:
            return _fail(f"unknown zone {zone!r}; try: {' '.join(hw.ZONES)} all")
    rgb = None
    if args.colour:
        rgb = _parse_colour(args.colour)
        if rgb is None:
            return _fail("colour must be RRGGBB in hex")
    problems = []
    for zone in zones:
        if rgb:
            problems.append(hw.set_zone_colour(zone, rgb))
            if args.brightness is None and hw.zone_brightness(zone) == 0:
                problems.append(hw.set_zone_brightness(zone, hw.LED_MAX))
        if args.brightness is not None:
            level = round(max(0, min(100, args.brightness)) * hw.LED_MAX / 100)
            problems.append(hw.set_zone_brightness(zone, level))
    code = _report(problems)
    if code == 0:
        state.remember_lighting()
    return code


def cmd_audio(args) -> int:
    if args.preset == "import":
        from . import dts
        tuning, message = dts.import_tuning()
        print(message)
        if tuning:
            print("Presets now: " + ", ".join(audio.hp_presets(tuning))
                  + ". Restart Omen Sense to see them.")
        return 0 if tuning else 1
    engine = audio.PresetEngine()
    if not args.preset:
        print(engine.current or "off")
        return 0
    if args.preset == "off":
        engine.stop()
        return 0
    if audio.ALIASES.get(args.preset, args.preset) not in audio.PRESETS:
        return _fail(f"unknown preset; try: off {' '.join(audio.PRESETS)}")
    return _report(engine.apply(args.preset))


def cmd_headphones(args) -> int:
    engine = audio.PresetEngine("headphones")
    if not args.preset:
        print(engine.current or "off")
        return 0
    if args.preset == "off":
        engine.stop()
        return 0
    if args.preset not in audio.HEADPHONE_PRESETS:
        return _fail(f"unknown option; try: off {' '.join(audio.HEADPHONE_PRESETS)}")
    return _report(engine.apply(args.preset))


def cmd_log(args) -> int:
    """Append a sample every interval until interrupted."""
    log = monitoring.Log(args.output)
    error = log.open()
    if error:
        return _fail(error)
    print(f"logging to {log.path} every {args.interval}s; Ctrl-C to stop",
          file=sys.stderr)
    rows = 0
    try:
        while True:
            log.write()
            rows += 1
            if args.count and rows >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        log.close()
    print(f"{rows} rows written to {log.path}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- profiles

def cmd_profile(args) -> int:
    if args.action == "list":
        startup = state.startup()
        for name in state.names():
            print(f"{'*' if name == startup else ' '} {name}")
        if not state.names():
            print("(no profiles saved)")
        return 0
    if args.action in ("save", "delete", "apply") and not args.name:
        return _fail(f"profile {args.action} needs a name")
    if args.action == "save":
        return _report(state.remember(args.name))
    if args.action == "delete":
        return _report(state.forget(args.name))
    if args.action == "startup":
        if args.name in (None, "none", ""):
            return _report(state.set_startup(None))
        return _report(state.set_startup(args.name))
    if args.action == "apply":
        profile = state.get(args.name)
        if profile is None:
            return _fail(f"no profile called {args.name!r}")
        return _report(state.apply(profile))
    return _fail("unknown profile action")


def cmd_apply(_args) -> int:
    """What the login unit runs: the startup profile, else the last colours."""
    if not hw.driver_present():
        # Warn, but succeed: a missing driver is a fact about the machine, not a
        # failure of the job, and a red unit at every boot would be noise.
        print("omen-sense: hp-wmi is not loaded; nothing applied.",
              file=sys.stderr)
        return 0
    name = state.startup()
    if name:
        problems = state.apply(state.get(name))
        if not problems:
            print(f"applied {name!r}")
        return _report(problems)
    zones = state.last_lighting()
    if zones and hw.zones_present():
        problems = state.apply_lighting(zones)
        if not problems:
            print("restored the last keyboard colours")
        return _report(problems)
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omen-sense",
        description="Control MyOmen hardware. "
                    "With no arguments, opens the window.")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("status", help="everything the machine is currently doing")

    sensors = subs.add_parser("sensors", help="one reading, for logging")
    sensors.add_argument("--csv", action="store_true",
                         help="comma-separated values only")
    sensors.add_argument("--header", action="store_true",
                         help="print the CSV header and exit")

    power = subs.add_parser("power", help="show or set the mode")
    power.add_argument("mode", nargs="?",
                       help="cool, balanced or performance")

    fan = subs.add_parser("fan", help="show or set max fan")
    fan.add_argument("setting", nargs="?", help="auto or max")

    light = subs.add_parser("light", help="set keyboard lighting on a zone, or all")
    light.add_argument("zone", nargs="?", default="all",
                       help=f"{', '.join(hw.ZONES)} or all; "
                            "or off / on for the whole backlight")
    light.add_argument("--colour", "--color", dest="colour", help="RRGGBB")
    light.add_argument("--brightness", type=int, help="0-100 percent")
    light.add_argument("--layout", choices=list(effects.LAYOUTS),
                       help="four colours at once, one per zone")

    phones = subs.add_parser("headphones", help="show or set headphone processing")
    phones.add_argument("preset", nargs="?", help="off, crossfeed or speakers")
    sound = subs.add_parser("audio", help="show or set the audio preset")
    sound.add_argument("preset", nargs="?",
                       help="a preset name, 'off', or 'import' to read HP's own "
                            "speaker tuning from the Windows partition")

    profile = subs.add_parser("profile", help="named saved settings")
    profile.add_argument("action",
                         choices=("list", "save", "apply", "delete", "startup"))
    profile.add_argument("name", nargs="?")

    log = subs.add_parser("log", help="append sensor samples to a CSV")
    log.add_argument("--interval", type=float, default=5.0,
                     help="seconds between samples (default 5)")
    log.add_argument("--count", type=int, default=0,
                     help="stop after this many rows (default: run until Ctrl-C)")
    log.add_argument("--output", help="file to append to")

    subs.add_parser("apply", help="re-apply the startup profile, or the last colours")
    gui = subs.add_parser("gui", help="open the window")
    gui.add_argument("--tray", action="store_true",
                     help="start hidden in the panel (what autostart uses)")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        # Imported here, not at the top: every other command must not pay for
        # Qt, and must work with no display.
        from . import app
        return app.main(tray_only=getattr(args, "tray", False))

    handlers = {
        "status": cmd_status, "sensors": cmd_sensors, "power": cmd_power,
        "fan": cmd_fan, "light": cmd_light, "audio": cmd_audio,
        "headphones": cmd_headphones,
        "profile": cmd_profile, "apply": cmd_apply, "log": cmd_log,
    }
    if args.command not in ("apply", "status") and not hw.driver_present():
        return _fail("hp-wmi is not loaded.")
    return handlers[args.command](args)
