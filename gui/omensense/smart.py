"""Smart mode: choose the power mode from temperature.

This laptop has no fan duty to set. HP's own software reports
IsSwFanControlSupport=False here, and the firmware's manual-fan handler is one
HP never uses on this board, so under the project rule it stays untouched. What
is left to steer the fans with is the three platform modes (and max fan, once
it has been observed from HP's software). So the closest thing to a fan curve
this machine can honestly offer is a governor over the modes.

It is deliberately slow. Every mode change is a firmware write that also
retunes the GPU power limit and raises a WMI event, and a mode-write loop is
exactly what went wrong once already on this board (docs/findings-8746.md,
event 0x1B). So a change needs the temperature to be past its threshold by the
hysteresis margin, and at least DWELL_S seconds after the previous change.
That caps it at one firmware write a minute, far below anything HP's own
software does.

It needs this process alive, so stopping it - cleanly or on a signal - puts
back the mode that was set before it started.
"""

from __future__ import annotations

from . import hw

#: Seconds a mode must hold before the governor may change it again.
DWELL_S = 60.0
#: Degrees past a threshold before it counts, each way.
HYSTERESIS = 4

DEFAULTS = {"cool_below": 55, "performance_above": 80}

#: Autopilot: seconds a hotter target must persist before stepping up. The
#: 10750H package sensor jumps 20+ degrees for a fraction of a second on any
#: burst of work; acting on that flaps the mode (an SMI + GPU notify per write).
UPSHIFT_CONFIRM_S = 4.0
#: Autopilot: above this the step-up is immediate - that is real heat.
UPSHIFT_IMMEDIATE_ABOVE = 88.0
#: Autopilot: degrees below a threshold before a step-down counts.
DOWNSHIFT_MARGIN = 4.0


class SmartMode:
    def __init__(self, cool_below: int = DEFAULTS["cool_below"],
                 performance_above: int = DEFAULTS["performance_above"]):
        self.cool_below = cool_below
        self.performance_above = performance_above
        self.enabled = False
        self._restore: str | None = None
        self._last_change = 0.0
        self.current: str | None = None

    # ------------------------------------------------------------- control

    def start(self, now: float) -> str | None:
        if self.enabled:
            return None
        if not hw.profile_path():
            return "No platform profile - is the patched hp-wmi loaded?"
        self._restore = hw.profile()
        self.current = self._restore
        # Allow the first decision immediately; the dwell starts from it.
        self._last_change = now - DWELL_S
        self.enabled = True
        return None

    def stop(self) -> str | None:
        """Put back the mode that was set before. Safe to call twice."""
        if not self.enabled:
            return None
        self.enabled = False
        restore, self._restore = self._restore, None
        if restore and restore != hw.profile():
            return hw.set_profile(restore)
        return None

    # ---------------------------------------------------------------- tick

    def wanted(self, temperature, on_ac) -> str:
        """The mode this temperature calls for, with hysteresis around `current`."""
        current = self.current or "balanced"
        if temperature is None:
            return current
        perf_ok = on_ac is not False           # unknown counts as allowed
        if current == "performance":
            if temperature < self.performance_above - HYSTERESIS or not perf_ok:
                return "balanced"
            return current
        if current == "low-power":
            if temperature > self.cool_below + HYSTERESIS:
                return "performance" if (perf_ok and temperature >= self.performance_above) else "balanced"
            return current
        # balanced, or anything else
        if perf_ok and temperature >= self.performance_above:
            return "performance"
        if temperature <= self.cool_below - HYSTERESIS:
            return "low-power"
        return "balanced"

    def tick(self, temperature, on_ac, now: float) -> str | None:
        """One step. Returns an error message, or None."""
        if not self.enabled:
            return None
        # Someone else changed the mode (the tray, Plasma's slider): follow it
        # rather than fighting, and let the dwell run from there.
        actual = hw.profile()
        if actual and actual != self.current:
            self.current = actual
            self._last_change = now
            return None
        target = self.wanted(temperature, on_ac)
        if target == self.current or now - self._last_change < DWELL_S:
            return None
        if target not in hw.profile_choices():
            return None
        error = hw.set_profile(target)
        if not error:
            self.current = target
            self._last_change = now
        return error

    # --------------------------------------------------------------- state

    def as_dict(self) -> dict:
        return {"cool_below": self.cool_below,
                "performance_above": self.performance_above}

    def load(self, data: dict):
        for key in DEFAULTS:
            if isinstance(data.get(key), int):
                setattr(self, key, data[key])


# ------------------------------------------------------------- Baby Smart

class BabySmartGovernor:
    """Zero-overhead autonomous cooling governor ('Omen Autopilot') for MyOmen.

    Synchronously evaluated on periodic telemetry ticks without extra threads or loops.
    Dual-sensor effective temperature: T_target = max(T_CPU, T_GPU).
    Profile ladder: low-power < balanced < performance < max.

    Thresholds & Logic:
    - T_target < 58°C: Cool Mode ('low-power')
    - 58°C <= T_target < 80°C: Balanced Mode ('balanced')
    - 80°C <= T_target < 90°C: Performance Mode ('performance', fans on Auto)
    - T_target >= 90°C (SUSTAINED for >= 10s): Max Overdrive ('max', fans 100%, PL1 65W)

    Debounce & Safeguards:
    - 10-Second Max Mode Debounce: T_target >= 90°C for 10 consecutive ticks (10s).
      A drop below 90°C resets counter and stays in Performance or lower.
    - Spike Detection: dT >= 7°C in <= 3s is completely DISABLED when T_target < 75°C.
      When active (>= 75°C), bumps at most ONE tier (Cool->Balanced, or Balanced->Performance).
      Spike detection NEVER jumps or bypasses directly to Max Mode.
    - Thermal Rebound Grace Period: Following any downshift, 20-second grace period
      where rate-of-rise (spike) detection is ignored to accommodate natural thermal bounce.
    - Asymmetric Hysteresis: Step-up confirmed over 4s (immediate >= 88°C; a
      spike bump stays latched while >= 75°C); step-down needs 4°C below the
      threshold and holds for >= 60s.
    - Max Overdrive from the autopilot = performance + max fan, PL1 untouched.
    - Explicit Fan Restoration: Whenever leaving Max mode (transitioning down to
      Performance, Balanced, or Cool), explicitly set Fan Mode back to Auto (pwm1_enable = 2).
    """

    LADDER = ("low-power", "balanced", "performance", "max")

    def __init__(self, hold_time_s: float = 60.0):
        self.enabled = False
        self.current: str | None = None
        self._restore_profile: str | None = None
        self._restore_max_fan: bool | None = None

        # State caching to minimize hardware/WMI writes
        self._last_applied_profile: str | None = None

        # Rate of rise tracking using scalar variables only
        self._t0: float = 0.0
        self._temp0: float | None = None
        self._t1: float = 0.0
        self._temp1: float | None = None
        self._t2: float = 0.0
        self._temp2: float | None = None

        # 10-Second Max Mode Debounce Counter
        self._sustained_90_ticks: int = 0

        # Thermal rebound grace period (timestamp until which spike detection is ignored)
        self._rebound_until: float = 0.0

        # Asymmetric hysteresis: downshift hold (minimum 60-second dwell buffer before spin-down)
        self._pending_downshift: str | None = None
        self._downshift_deadline: float = 0.0
        self._hold_time_s: float = float(hold_time_s)

        # Upshift confirmation: lowest hotter target seen since _upshift_since
        self._pending_upshift: str | None = None
        self._upshift_since: float = 0.0

    @staticmethod
    def effective_temp(cpu_temp: float | None, gpu_temp: float | None) -> float | None:
        """Effective temperature: max(T_CPU, T_GPU)."""
        candidates = [t for t in (cpu_temp, gpu_temp) if t is not None]
        return max(candidates) if candidates else None

    @staticmethod
    def profile_for_temp(temp: float) -> str:
        """Profile Decision Matrix:
        T < 58°C             --> Cool Mode (low-power)
        58°C <= T < 80°C     --> Balanced Mode (balanced)
        80°C <= T < 90°C     --> Performance Mode (performance)
        T >= 90°C            --> Max Overdrive (max)
        """
        if temp < 58.0:
            return "low-power"
        if temp < 80.0:
            return "balanced"
        if temp < 90.0:
            return "performance"
        return "max"

    def start(self, now: float) -> str | None:
        """Engage governor and save previous manual profile."""
        if self.enabled:
            return None
        if not hw.profile_path():
            return "No platform profile - is the patched hp-wmi loaded?"
        self._restore_profile = hw.profile()
        self._restore_max_fan = hw.max_fan()
        self.current = self._restore_profile or "balanced"
        self._last_applied_profile = self.current

        # Reset rate-of-rise tracking scalars
        self._t0, self._temp0 = 0.0, None
        self._t1, self._temp1 = 0.0, None
        self._t2, self._temp2 = 0.0, None

        self._sustained_90_ticks = 0
        self._rebound_until = 0.0
        self._pending_downshift = None
        self._downshift_deadline = 0.0
        self.enabled = True
        return None

    def stop(self) -> str | None:
        """Instantly stop automation, detach governor logic, and restore user's manual profile."""
        if not self.enabled:
            return None
        self.enabled = False
        prev = self.current
        restore_profile = self._restore_profile
        restore_max_fan = self._restore_max_fan
        self._restore_profile = None
        self._restore_max_fan = None
        self.current = None
        self._pending_downshift = None
        self._sustained_90_ticks = 0
        self._rebound_until = 0.0

        errors = []
        # Explicit Fan Restoration if stopped from Max mode
        if prev == "max":
            err_fan = hw.set_max_fan(False)
            if err_fan:
                errors.append(err_fan)
        elif restore_max_fan is not None and restore_max_fan != hw.max_fan():
            err_fan = hw.set_max_fan(restore_max_fan)
            if err_fan:
                errors.append(err_fan)

        if restore_profile and restore_profile != hw.profile():
            err_prof = hw.set_profile(restore_profile)
            if err_prof:
                errors.append(err_prof)
        return "; ".join(errors) if errors else None

    def reset_state(self):
        """Reset thermal hysteresis tracking scalars and rate-of-rise buffers on wake."""
        self._t0, self._temp0 = 0.0, None
        self._t1, self._temp1 = 0.0, None
        self._t2, self._temp2 = 0.0, None
        self._sustained_90_ticks = 0
        self._rebound_until = 0.0
        self._pending_downshift = None
        self._downshift_deadline = 0.0
        self._pending_upshift = None
        self._last_applied_profile = None

    def _detect_spike(self, temp: float, now: float) -> bool:
        """Detect if dT >= 7°C within a 3-second window using scalar variables.
        Safeguards:
        - Completely DISABLED when T_target < 75°C.
        - DISABLED during 20-second thermal rebound grace period following a downshift.
        """
        # Shift scalar window
        self._t0, self._temp0 = self._t1, self._temp1
        self._t1, self._temp1 = self._t2, self._temp2
        self._t2, self._temp2 = now, temp

        # Safeguard 1: Disabled if T_target < 75°C
        if temp < 75.0:
            return False

        # Safeguard 2: Disabled during 20-second thermal rebound grace period
        if now < self._rebound_until:
            return False

        # Check against oldest entry within 3.5s window
        if self._t0 > 0.0 and (now - self._t0) <= 3.5:
            if self._temp0 is not None and (temp - self._temp0) >= 7.0:
                return True
        if self._t1 > 0.0 and (now - self._t1) <= 3.5:
            if self._temp1 is not None and (temp - self._temp1) >= 7.0:
                return True
        return False

    def tick(self, cpu_temp: float | None, gpu_temp: float | None, on_ac: bool | None, now: float) -> str | None:
        """Zero-overhead periodic evaluation hook."""
        if not self.enabled:
            return None

        eff_temp = self.effective_temp(cpu_temp, gpu_temp)
        if eff_temp is None:
            return None

        # 10-Second Max Mode Debounce Window:
        # Max Mode must ONLY engage if T_target >= 90°C continuously for at least 10 consecutive ticks (10s).
        # If temperature drops below 90°C for even 1 tick during this window, reset counter.
        if eff_temp >= 90.0:
            self._sustained_90_ticks += 1
        else:
            self._sustained_90_ticks = 0

        # Check rate-of-rise spike
        spike = self._detect_spike(eff_temp, now)

        # Base target from decision matrix
        if eff_temp < 58.0:
            base_target = "low-power"
        elif eff_temp < 80.0:
            base_target = "balanced"
        elif eff_temp < 90.0:
            base_target = "performance"
        else:
            # T >= 90°C: Only engage Max if sustained for >= 10 consecutive ticks
            if self._sustained_90_ticks >= 10:
                base_target = "max"
            else:
                base_target = "performance"

        # Performance / Max modes require AC power if known
        perf_allowed = (on_ac is not False)
        if not perf_allowed and base_target in ("performance", "max"):
            base_target = "balanced"

        target = base_target
        curr = self.current or "balanced"
        if curr not in self.LADDER:
            curr = "balanced"
        curr_idx = self.LADDER.index(curr)

        # Battery guard: If on battery power and currently in performance/max,
        # back off immediately to balanced without waiting for cooldown dwell.
        if not perf_allowed and curr in ("performance", "max"):
            self._pending_downshift = None
            self._downshift_deadline = 0.0
            return self._apply_profile("balanced")

        # Safeguard: When active (T_target >= 75°C), a spike can only bump up ONE tier:
        # (Cool -> Balanced, or Balanced -> Performance).
        # Spike detection must NEVER jump or bypass directly to Max Mode.
        if spike:
            if curr == "low-power":
                bump_target = "balanced"
            elif curr == "balanced":
                bump_target = "performance" if perf_allowed else "balanced"
            else:
                bump_target = curr  # Never bump to max from spike

            if self.LADDER.index(bump_target) > self.LADDER.index(target):
                target = bump_target
            # Extra guarantee: spike can NEVER directly enter Max Mode
            if target == "max" and self._sustained_90_ticks < 10:
                target = "performance"

        # Extra guarantee: battery guard NEVER allows performance or max
        if not perf_allowed and target in ("performance", "max"):
            target = "balanced"

        # Downshift deadband: the temperature must sit DOWNSHIFT_MARGIN below the
        # threshold, so a reading hovering on a boundary never counts as cooler.
        if self.LADDER.index(target) < curr_idx:
            margin_idx = min(self.LADDER.index(self.profile_for_temp(eff_temp + DOWNSHIFT_MARGIN)), curr_idx)
            target = self.LADDER[max(self.LADDER.index(target), margin_idx)]

        target_idx = self.LADDER.index(target)

        # Asymmetric Hysteresis
        if target_idx > curr_idx:
            self._pending_downshift = None
            self._downshift_deadline = 0.0
            # Step-up: confirmed over UPSHIFT_CONFIRM_S unless it is already really hot
            if eff_temp < UPSHIFT_IMMEDIATE_ABOVE:
                if self._pending_upshift is None:
                    self._pending_upshift = target
                    self._upshift_since = now
                    return None
                if target_idx < self.LADDER.index(self._pending_upshift):
                    self._pending_upshift = target
                if now - self._upshift_since < UPSHIFT_CONFIRM_S:
                    return None
                target = self._pending_upshift
            self._pending_upshift = None
            return self._apply_profile(target)

        if self._pending_upshift is not None and target_idx == curr_idx and eff_temp >= 75.0:
            # A spike bump stays latched while it is still hot (spike floor 75 °C)
            if now - self._upshift_since >= UPSHIFT_CONFIRM_S:
                target, self._pending_upshift = self._pending_upshift, None
                return self._apply_profile(target)
            return None
        self._pending_upshift = None
        if target_idx < curr_idx:
            # Step-down: Enforce minimum sustained hold at lower temperature
            if self._pending_downshift is None or target_idx < self.LADDER.index(self._pending_downshift):
                self._pending_downshift = target
                self._downshift_deadline = now + self._hold_time_s
            elif now >= self._downshift_deadline:
                downshift_target = self._pending_downshift
                self._pending_downshift = None
                # Thermal rebound grace period: 20s post-downshift where spike detection is ignored
                self._rebound_until = now + 20.0
                return self._apply_profile(downshift_target)
            return None

        else:
            # Target matches current profile - clear any pending downshift
            self._pending_downshift = None
            return None

    def _apply_profile(self, target: str) -> str | None:
        """Apply target profile to hardware with explicit fan restoration when leaving Max."""
        prev = self.current
        self.current = target
        errors = []

        # Explicit Fan Restoration: Whenever leaving Max mode, set Fan Mode back to Auto (pwm1_enable = 2)
        if prev == "max" and target != "max":
            err_fan = hw.set_max_fan(False)
            if err_fan:
                errors.append(err_fan)

        if target != self._last_applied_profile:
            if target == "max":
                # Max fans, not more watts: hw.set_profile("max") also lifts PL1
                # to 65 W, which only adds heat once it is already >= 90 °C.
                error = hw.set_profile("performance") or hw.set_max_fan(True)
            else:
                error = hw.set_profile(target)
            if error:
                errors.append(error)
            else:
                self._last_applied_profile = target

        return "; ".join(errors) if errors else None
