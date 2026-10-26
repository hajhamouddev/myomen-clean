"""Keyboard layouts, and the animations this keyboard can carry.

A layout is four static colours, one per zone, written once - the same writes
the colour wheel makes, just four at a time. Nothing about them needs care.

The animations need some. The firmware stores one static colour per zone and
animates nothing itself (docs/findings-8746.md), so movement means software
rewriting the zones, frame after frame. What makes that acceptable here:

- HP does it on this machine. OMEN Light Studio's saved profile on the Windows
  side (Profiles/desktop/default.json, 2026-09-28) is a software "Wave" layer
  over the four-zone keyboard, with a rainbow gradient.
- The colour-set handler raises nothing. LM03 and LM02 in this board's DSDT
  copy colours into and out of EC memory: no WMI event, no SMI, no Notify, so
  a colour write cannot loop back into the driver the way event 0x1B did.
- The rate is bounded. A frame is at most four zone writes, and each zone
  write is three firmware calls in the v11 driver (backlight check, read the
  128-byte table, write it back): 5 frames a second is at most 60 calls a
  second, under half of what the community omen-rgb-keyboard driver sends to
  the same keyboards at its 20 frames a second, and zones whose colour has not
  changed are not written at all. 5 was chosen by the user on 2026-09-28, up
  from 2, so that breathing and fire read as motion rather than as steps.

No Qt here: the window drives tick() from a timer, and the logic tests drive it
with a fake clock.
"""

from __future__ import annotations

import colorsys
import math
import random
import time

from . import hw

# ------------------------------------------------------------------ layouts

#: Colours in hw.ZONES order: left, WASD, centre, right. Rainbow uses the stops
#: of HP's own Light Studio rainbow gradient, read from its profile on this
#: machine; Factory is the red / green / blue / white the firmware sets at boot.
LAYOUTS: dict[str, dict] = {
    "ice": {"title": "Ice Cold",
            "zones": ((160, 231, 229), (255, 255, 255), (160, 231, 229), (160, 231, 229))},
    "stealth": {"title": "Stealth Mode",
                "zones": ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0))},
    "crimson": {"title": "Omen Crimson",
                "zones": ((255, 26, 53), (255, 50, 70), (220, 0, 30), (180, 0, 20))},
    "neon": {"title": "Cyberpunk Neon",
             "zones": ((255, 0, 127), (0, 245, 212), (255, 0, 127), (0, 245, 212))},
    "cyberpunk": {"title": "Cyberpunk Magenta",
                  "zones": ((255, 0, 127), (121, 40, 202), (157, 78, 221), (0, 245, 212))},
    "deep-matrix": {"title": "Deep Matrix",
                    "zones": ((0, 255, 65), (30, 180, 60), (0, 140, 40), (0, 70, 25))},
    "golden-amber": {"title": "Golden Amber",
                     "zones": ((255, 183, 3), (255, 215, 0), (255, 183, 3), (255, 183, 3))},
    "ghost": {"title": "Ghost White",
              "zones": ((248, 249, 250), (255, 255, 255), (248, 249, 250), (248, 249, 250))},
    "solar-flare": {"title": "Solar Flare",
                    "zones": ((251, 133, 0), (255, 180, 50), (251, 133, 0), (251, 133, 0))},
    "ultraviolet": {"title": "Ultraviolet",
                    "zones": ((114, 9, 183), (180, 50, 255), (114, 9, 183), (114, 9, 183))},
    "rainbow": {"title": "Rainbow",
                "zones": ((238, 33, 46), (241, 224, 10), (23, 237, 7), (2, 10, 231))},
    "ocean": {"title": "Ocean",
              "zones": ((0, 60, 200), (0, 230, 255), (0, 150, 220), (0, 90, 255))},
    "sunset": {"title": "Sunset",
               "zones": ((255, 40, 0), (255, 150, 0), (255, 0, 90), (150, 0, 210))},
    "jungle": {"title": "Jungle",
               "zones": ((16, 150, 0), (255, 153, 0), (40, 255, 0), (16, 103, 0))},
    "focus": {"title": "WASD Pro",
              "zones": ((70, 0, 140), (0, 255, 255), (70, 0, 140), (70, 0, 140))},
    "red": {"title": "Crimson Red",
            "zones": ((255, 30, 0), (255, 75, 0), (210, 0, 50), (160, 0, 40))},
    "white": {"title": "Pure White",
              "zones": ((255, 255, 255),) * 4},
    "factory": {"title": "Factory Default",
                "zones": ((0, 0, 255), (255, 255, 255), (0, 255, 0), (255, 0, 0))},
    "synthwave": {"title": "Synthwave 84",
                  "zones": ((255, 113, 206), (1, 205, 254), (5, 255, 161), (185, 103, 255))},
    "tokyo-night": {"title": "Tokyo Night",
                    "zones": ((114, 135, 253), (125, 207, 255), (247, 118, 142), (187, 154, 247))},
    "nord-glacier": {"title": "Nord Glacier",
                     "zones": ((94, 129, 172), (136, 192, 208), (129, 161, 193), (143, 188, 187))},
    "dracula-violet": {"title": "Dracula Violet",
                       "zones": ((189, 147, 249), (255, 121, 198), (80, 250, 123), (139, 233, 253))},
    "matrix-green": {"title": "Matrix Green",
                     "zones": ((0, 255, 102), (16, 185, 129), (0, 230, 90), (5, 150, 105))},
    "vaporwave-sunset": {"title": "Vaporwave Sunset",
                         "zones": ((255, 154, 162), (107, 185, 240), (224, 187, 228), (255, 183, 178))},
    "fire-ice": {"title": "Fire & Ice",
                 "zones": ((255, 60, 0), (255, 160, 0), (0, 180, 255), (100, 220, 255))},
    "emerald-forest": {"title": "Emerald Forest",
                       "zones": ((46, 204, 113), (39, 174, 96), (241, 196, 15), (22, 160, 133))},
    "cotton-candy": {"title": "Cotton Candy",
                     "zones": ((255, 182, 193), (173, 216, 230), (255, 192, 203), (135, 206, 250))},
    "solarized-gold": {"title": "Solarized Gold",
                       "zones": ((181, 137, 0), (203, 75, 22), (42, 161, 152), (108, 113, 196))},
}


def random_layout() -> tuple[tuple[int, int, int], ...]:
    """Generate 4 randomized vibrant RGB colors."""
    zones = []
    for _ in range(4):
        hue = random.random()
        sat = random.uniform(0.75, 1.0)
        val = random.uniform(0.85, 1.0)
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        zones.append((int(r * 255), int(g * 255), int(b * 255)))
    return tuple(zones)


def apply_random_layout() -> tuple[list[str], tuple[tuple[int, int, int], ...]]:
    """Generate and apply random 4-zone colors."""
    colors = random_layout()
    problems = []
    for zone, rgb in zip(hw.ZONES, colors):
        for error in (hw.set_zone_colour(zone, rgb),
                      None if hw.zone_brightness(zone) else
                      hw.set_zone_brightness(zone, hw.LED_MAX)):
            if error:
                problems.append(error)
    return problems, colors



def layout_colours(name: str) -> dict[str, tuple]:
    return dict(zip(hw.ZONES, LAYOUTS[name]["zones"]))


def matching_layout(colours: dict[str, tuple]) -> str | None:
    """The layout the keyboard is showing now, if it is showing one."""
    for name in LAYOUTS:
        if all(tuple(colours.get(z) or ()) == rgb
               for z, rgb in layout_colours(name).items()):
            return name
    return None


def apply_layout(name: str) -> list[str]:
    """Write a layout. A zone at brightness 0 is lit, or it would show nothing."""
    if name not in LAYOUTS:
        return [f"Unknown layout {name!r}; try: {' '.join(LAYOUTS)}"]
    problems = []
    for zone, rgb in layout_colours(name).items():
        for error in (hw.set_zone_colour(zone, rgb),
                      None if hw.zone_brightness(zone) else
                      hw.set_zone_brightness(zone, hw.LED_MAX)):
            if error:
                problems.append(error)
    return problems


# --------------------------------------------------------------- animations

#: Key, title, and what it does - in the order the window shows them.
ANIMATION_INFO = (
    ("cycle", "Colour cycle", "Every zone drifts round the colour wheel together"),
    ("wave", "Rainbow wave", "A rainbow travelling left to right, like HP's Wave"),
    ("breathing", "Breathing", "Your colours fade out and back in"),
    ("heartbeat", "Heartbeat", "Your colours beat twice, then rest"),
    ("chase", "Chase", "One zone at a time lights up, left to right"),
    ("fire", "Fire", "Reds and oranges flickering like a flame"),
    ("aurora", "Aurora", "Greens, teals and violets drifting slowly"),
)
ANIMATIONS = tuple(key for key, _title, _detail in ANIMATION_INFO)
TITLES = {key: title for key, title, _detail in ANIMATION_INFO}

#: Never more than this many frames a second, whatever calls tick(). In the
#: window, frames land 204-242 ms apart (a 50 ms timer, rounded up to this).
FRAME_S = 0.2

#: The longest gap between two real frames. Anything an effect must show - a
#: heartbeat's beat - has to last at least this long, or it can fall between
#: two frames and never reach the keyboard.
FRAME_GAP_MAX_S = 0.25

#: One trip round the colour wheel for Colour cycle.
PERIOD_S = 30.0

#: Where each zone sits across the keyboard, 0 at the left edge and 1 at the
#: right: the key-width-weighted centre of its keys in keyboard.py (which a
#: test checks). WASD is an island inside Left, not a step after it, and Right
#: with the numpad covers half the width - so an effect that moves across the
#: keyboard has to use these, not the zones' order.
ZONE_X = {"left": 0.12, "wasd": 0.16, "center": 0.39, "right": 0.76}

#: Rainbow wave: how much of the colour wheel spans the keyboard at once, and
#: how long one colour takes to pass a point. 0.75 of the wheel keeps the
#: rainbow order (red, yellow, green, cyan, blue) readable over four zones.
WAVE_SPREAD = 0.75
WAVE_PERIOD_S = 16.0   # crosses the keyboard in 12 s, ~5 degrees of hue a frame

BREATH_S = 4.0       # one breath, out and in
HEARTBEAT_S = 2.0    # lub, gap, dub, rest - each step longer than a frame gap
CHASE_STEP_S = 0.6   # time on each zone

#: Aurora: green most of the time, with teal and violet-pink surges, never
#: dark. Stops are (position 0..1, colour); a zone's position drifts smoothly
#: and is skewed towards 0 (AURORA_SKEW), which over ten simulated minutes
#: gives about 59 % green, 22 % teal, 7 % blue and 13 % violet or pink - green
#: dominating the way it does in a real aurora, violet at the top of it.
AURORA_STOPS = ((0.0, (0, 150, 40)), (0.4, (20, 255, 100)), (0.6, (0, 210, 170)),
                (0.78, (130, 40, 255)), (1.0, (210, 40, 200)))
AURORA_SKEW = 1.3
AURORA_DRIFT_S = 4.0   # time between the drift's random targets
AURORA_MIN_LEVEL = 0.45

#: Fire: the flicker's random targets are this far apart, and the colour moves
#: smoothly between them, so it reads as a flame rather than a strobe.
FIRE_FLICKER_S = 0.4


def _hsv(hue: float, value: float = 1.0) -> tuple:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, 1.0, value)
    return (int(red * 255), int(green * 255), int(blue * 255))


def _scaled(rgb: tuple, level: float) -> tuple:
    return tuple(int(v * level) for v in rgb)


def _random(*key) -> float:
    """A repeatable random number in [0, 1) for a tuple of ints."""
    return ((hash(key) * 2654435761) % 4294967296) / 4294967296


def _noise(seed: int, channel: int, t: float) -> float:
    """Smooth random motion in [0, 1]: random targets at whole t, eased between.

    Pure, so frames can be computed for any time; the seed keeps each zone and
    each channel on its own path.
    """
    knot = math.floor(t)
    ease = 0.5 - 0.5 * math.cos(math.pi * (t - knot))
    a, b = _random(seed, channel, knot), _random(seed, channel, knot + 1)
    return a + (b - a) * ease


def _gradient(stops, position: float) -> tuple:
    position = max(0.0, min(1.0, position))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if position <= p1:
            mix = (position - p0) / (p1 - p0)
            return tuple(int(a + (b - a) * mix) for a, b in zip(c0, c1))
    return stops[-1][1]


def _heart_level(phase: float) -> float:
    step = phase * HEARTBEAT_S
    if step < 0.26:
        return 1.0      # lub
    if step < 0.52:
        return 0.3
    if step < 0.78:
        return 0.8      # dub
    return 0.1          # rest


def frame(mode: str, elapsed: float, base: dict | None = None,
          seed: int = 0) -> dict[str, tuple]:
    """The colours for every zone, `elapsed` seconds into an animation.

    `base` is the user's own colour per zone, for the effects that animate it
    (breathing, heartbeat, chase); `seed` gives fire and aurora their own paths.
    """
    base = base or {zone: (255, 255, 255) for zone in hw.ZONES}
    count = len(hw.ZONES)
    colours = {}
    for index, zone in enumerate(hw.ZONES):
        if mode == "cycle":
            rgb = _hsv(elapsed / PERIOD_S)
        elif mode == "wave":
            # Hue rises left to right (red at the left, blue at the right),
            # and the whole pattern slides right as time passes.
            rgb = _hsv(WAVE_SPREAD * ZONE_X[zone] - elapsed / WAVE_PERIOD_S)
        elif mode == "breathing":
            # Squared, because the eye is far more sensitive to changes near
            # dark: a linear fade looks like a long bright hold and a blink.
            swing = 0.5 - 0.5 * math.cos(2 * math.pi * elapsed / BREATH_S)
            rgb = _scaled(base[zone], 0.04 + 0.96 * swing ** 2)
        elif mode == "heartbeat":
            rgb = _scaled(base[zone], _heart_level((elapsed / HEARTBEAT_S) % 1.0))
        elif mode == "chase":
            lit = int(elapsed / CHASE_STEP_S) % count
            rgb = _scaled(base[zone], 1.0 if index == lit else 0.06)
        elif mode == "fire":
            t = elapsed / FIRE_FLICKER_S
            level = 0.5 + 0.5 * _noise(seed + index, 0, t)
            rgb = _scaled((255, int(25 + 115 * _noise(seed + index, 1, t)), 0),
                          level)
        elif mode == "aurora":
            t = elapsed / AURORA_DRIFT_S
            position = _noise(seed + index, 0, t) ** AURORA_SKEW
            level = AURORA_MIN_LEVEL + (1 - AURORA_MIN_LEVEL) * _noise(
                seed + index, 1, t * 0.7)
            rgb = _scaled(_gradient(AURORA_STOPS, position), level)
        else:
            raise ValueError(f"unknown animation {mode!r}")
        colours[zone] = rgb
    return colours


class Animator:
    """Runs one animation at a time, and puts the user's colours back after."""

    def __init__(self, seed: int | None = None):
        self.mode = "off"
        self._saved: dict | None = None
        self._start = 0.0
        self._last_frame = float("-inf")
        self._shown: dict[str, tuple] = {}
        self._seed = random.Random(seed).randrange(1 << 20)
        #: Frames actually sent, so the window redraws only when one was.
        self.frames = 0
        #: True while the backlight key has the keyboard off.
        self.paused = False

    def start(self, mode: str, now: float | None = None) -> str | None:
        if mode not in ANIMATIONS:
            return f"Unknown animation {mode!r}."
        if mode == self.mode:
            return None
        self.stop()
        self._saved = {zone: (hw.zone_colour(zone), hw.zone_brightness(zone))
                       for zone in hw.ZONES}
        self.mode = mode
        self._start = time.monotonic() if now is None else now
        return None

    def stop(self) -> list[str]:
        problems = []
        if self._saved:
            for zone, (rgb, brightness) in self._saved.items():
                for error in (hw.set_zone_colour(zone, rgb),
                              hw.set_zone_brightness(zone, brightness)):
                    if error:
                        problems.append(error)
        self._saved = None
        self._last_frame = float("-inf")
        self._shown = {}
        self.mode = "off"
        return problems

    def tick(self, now: float | None = None) -> list[str]:
        if self.mode == "off":
            return []
        now = time.monotonic() if now is None else now
        if now - self._last_frame < FRAME_S:
            return []
        self._last_frame = now
        # Any colour write switches the backlight back on, so while the
        # backlight key has it off, hold still. The animation's clock keeps
        # running, so it picks up where it would have been.
        self.paused = hw.backlight_off_by_key()
        if self.paused:
            self._shown = {}
            return []
        # A zone that was black before would breathe black; animate white.
        base = {zone: (rgb if any(rgb) else (255, 255, 255))
                for zone, (rgb, _b) in (self._saved or {}).items()}
        problems = []
        self.frames += 1
        for zone, rgb in frame(self.mode, now - self._start, base,
                               self._seed).items():
            if self._shown.get(zone) == rgb:
                continue
            for error in (hw.set_zone_colour(zone, rgb),
                          None if hw.zone_brightness(zone) else
                          hw.set_zone_brightness(zone, hw.LED_MAX)):
                if error:
                    problems.append(error)
            self._shown[zone] = rgb
        return problems
