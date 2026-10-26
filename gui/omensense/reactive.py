"""Keyboard lighting that follows the CPU temperature.

Hue runs from cyan when the CPU is cool to red when it is hot, so the keyboard
says what the gauges say without anyone looking at the window.

It changes slowly on purpose: the colour is quantised into STEPS hues and a
zone is only written when its step changes - in practice a handful of writes
a minute. A temperature signal needs no more than that, and it keeps this
well clear of the animations' frame budget (effects.py).
"""

from __future__ import annotations

import colorsys
import time

from . import hw

MODES = ("off", "temperature")

#: Below this the keyboard is "cool"; above the top it is "hot". A comfort
#: signal matched to the gauges, not a warning.
TEMP_COOL, TEMP_HOT = 45, 90

#: Distinct colours between cool and hot, about 4 degrees apart.
STEPS = 12

#: A temperature sitting on the edge between two steps must not flip the
#: keyboard back and forth, so a new step has to be this far past the middle
#: of the current one (in steps: 0.5 is the edge, 0.85 is ~3.5 degrees in).
STEP_HYSTERESIS = 0.85

#: And never rewrite the keyboard more often than this, whatever the CPU does.
MIN_INTERVAL_S = 5.0


class Reactive:
    """Drives the zones from temperature while a mode is selected."""

    def __init__(self):
        self.mode = "off"
        self._saved: dict | None = None
        self._last_step: int | None = None
        self._last_write = float("-inf")

    # ------------------------------------------------------------- control

    def start(self, mode: str) -> str | None:
        if mode not in MODES:
            return f"Unknown lighting source {mode!r}."
        if mode == self.mode:
            return None
        self.stop()
        if mode == "off":
            return None
        # Remember the user's colours, so stopping puts them back rather than
        # leaving whatever frame it happened to stop on.
        self._saved = {zone: (hw.zone_colour(zone), hw.zone_brightness(zone))
                       for zone in hw.ZONES}
        self.mode = mode
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
        self._last_step = None
        self._last_write = float("-inf")
        self.mode = "off"
        return problems

    # ---------------------------------------------------------------- tick

    @staticmethod
    def position_for(temperature) -> float | None:
        """Where a temperature falls on the 0..STEPS-1 scale, unrounded."""
        if temperature is None:
            return None
        span = (temperature - TEMP_COOL) / max(1, TEMP_HOT - TEMP_COOL)
        return max(0.0, min(1.0, span)) * (STEPS - 1)

    def next_step(self, temperature) -> int | None:
        """The step to show, or None to leave the keyboard alone."""
        position = self.position_for(temperature)
        if position is None:
            return None
        if self._last_step is None:
            return int(round(position))
        if abs(position - self._last_step) < STEP_HYSTERESIS:
            return None
        return int(round(position))

    @staticmethod
    def colour_for_step(step: int) -> tuple:
        # Hue 0.5 (cyan) down to 0.0 (red).
        hue = 0.5 * (1.0 - step / (STEPS - 1))
        red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        return (int(red * 255), int(green * 255), int(blue * 255))

    def tick(self, readings: dict, now: float | None = None) -> list[str]:
        if self.mode != "temperature":
            return []
        now = time.monotonic() if now is None else now
        if now - self._last_write < MIN_INTERVAL_S:
            return []
        # A colour write would switch the backlight back on: leave the key be.
        if hw.backlight_off_by_key():
            self._last_step = None
            return []
        step = self.next_step(readings.get("cpu_temp"))
        if step is None or step == self._last_step:
            return []
        self._last_step = step
        self._last_write = now
        colour = self.colour_for_step(step)
        problems = []
        for zone in hw.ZONES:
            for error in (hw.set_zone_colour(zone, colour),
                          None if hw.zone_brightness(zone) else
                          hw.set_zone_brightness(zone, hw.LED_MAX)):
                if error:
                    problems.append(error)
        return problems
