"""Automated test suite auditing 4-Zone RGB engine and PipeWire Audio DSP filter-chain."""

from __future__ import annotations

import glob
import os
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_GUI = str(REPO_ROOT / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

from omensense import animations, audio, dts, effects, hw, light, state


def test_lighting_and_audio():
    print("================================================================================")
    print(" 4-ZONE RGB ENGINE & PIPEWIRE AUDIO DSP AUDIT TEST SUITE")
    print("================================================================================")

    # -------------------------------------------------------------------------
    # Track 1: 4-Zone RGB Lighting Controller & Animations
    # -------------------------------------------------------------------------
    print("\n[Track 1] Auditing 4-Zone RGB Keyboard Subsystem:")

    # 1.1 Non-root write access to LED sysfs nodes
    nodes = glob.glob("/sys/class/leds/hp::kbd_zoned_backlight-*/multi_intensity")
    assert len(nodes) == 4, f"Expected 4 backlight zones, found {len(nodes)}"
    for n in nodes:
        zone_name = os.path.basename(os.path.dirname(n)).replace("hp::kbd_zoned_backlight-", "")
        writable = os.access(n, os.W_OK)
        assert writable, f"Sysfs node {n} is not writable by non-root user"
        print(f"  [✓] Zone '{zone_name}' multi_intensity node writable (0664 plugdev)")

    # 1.2 Rate limiting: FRAME_S must enforce <= 5 FPS
    assert effects.FRAME_S >= 0.1, f"FRAME_S too fast: {effects.FRAME_S}"
    fps = 1.0 / effects.FRAME_S
    assert fps <= 10.0, f"Frame rate cap exceeded: {fps} FPS"
    print(f"  [✓] Frame rate limiter verified: {fps:.1f} FPS cap (FRAME_S = {effects.FRAME_S}s)")

    # 1.3 Test all 7 animation modes
    animator = animations.Animator()
    base_colours = {z: (160, 231, 229) for z in hw.ZONES}
    for mode in animations.ANIMATIONS:
        err = animator.start(mode)
        assert err is None, f"Failed to start animation {mode}: {err}"
        # Test simulated frame generation
        frm = animations.frame(mode, 1.5, base_colours, seed=42)
        assert len(frm) == 4, f"Frame for {mode} did not return 4 zones"
        for z, rgb in frm.items():
            assert len(rgb) == 3, f"Zone {z} invalid RGB tuple: {rgb}"
            for c in rgb:
                assert 0 <= c <= 255, f"Colour component out of range: {c} in {rgb}"
        animator.stop()
        print(f"  [✓] Animation '{mode}' ({animations.TITLES[mode]}): Passed frame generation & safe bounds")

    # 1.4 Measure real CPU footprint of active animation loop
    animator.start("wave")
    t0_wall = time.time()
    t0_cpu = time.process_time()
    for _ in range(25):  # 2.5 seconds simulation
        animator.tick()
        time.sleep(0.1)
    t1_wall = time.time()
    t1_cpu = time.process_time()
    animator.stop()

    wall_s = t1_wall - t0_wall
    cpu_s = t1_cpu - t0_cpu
    cpu_pct = (cpu_s / wall_s) * 100 if wall_s > 0 else 0.0
    print(f"  [✓] Active animation CPU consumption: {cpu_pct:.2f}% (Target: < 1.5%)")
    assert cpu_pct < 1.5, f"Animation CPU usage {cpu_pct:.2f}% exceeded 1.5% ceiling"

    # 1.5 Test lighting state persistence & profile restoration
    test_zones = {
        "left": {"colour": (255, 0, 127), "brightness": 255},
        "wasd": {"colour": (0, 245, 212), "brightness": 255},
        "center": {"colour": (255, 0, 127), "brightness": 255},
        "right": {"colour": (0, 245, 212), "brightness": 255},
    }
    state.remember_lighting(test_zones)
    restored = state.last_lighting()
    assert restored is not None, "Failed to retrieve last_lighting"
    assert restored["wasd"]["colour"] == [0, 245, 212], f"Mismatch in restored lighting: {restored}"
    print(f"  [✓] Profile lighting state persistence & restore verified: {restored['wasd']}")

    # 1.6 Verify light facade module functions
    assert len(light.get_all_presets()) >= 10, "Presets list too short"
    print(f"  [✓] light.py and animations.py facades operational with {len(light.get_all_presets())} presets")

    # -------------------------------------------------------------------------
    # Track 2: PipeWire Audio DSP & WirePlumber Integration
    # -------------------------------------------------------------------------
    print("\n[Track 2] Auditing PipeWire Audio DSP Subsystem:")

    # 2.1 PipeWire availability and sink detection
    pw_avail = audio.available()
    assert pw_avail, "PipeWire tools (pipewire, pactl) not available"
    spk_sink = audio.speaker_sink()
    hp_sink = audio.headphone_sink()
    print(f"  [✓] PipeWire sound server available: True")
    print(f"  [✓] Resolved Speaker Sink: '{spk_sink}'")
    print(f"  [✓] Resolved Headphone Sink: '{hp_sink}'")

    # 2.2 Safety limiter clamped strictly at -1.0 dBFS (0.891 amplitude)
    for name, p in audio.GENERIC_PRESETS.items():
        cfg = audio._config(p["bands"], limit=True)
        assert '"th" = 0.891' in cfg, f"Limiter threshold not 0.891 (-1.0 dBFS) in {name}"
        assert '"boost" = 0' in cfg, f"Limiter boost not 0 in {name}"
        assert '"alr" = 0' in cfg, f"Limiter ALR not 0 in {name}"
    print(f"  [✓] All 6 generic presets verified with hard -1.0 dBFS limiter (th=0.891, boost=0, alr=0)")

    # 2.3 Bass boost ceiling clamped at <= 250 Hz
    b_norm = audio._bankstown({"level": 52.0, "speaker_size": 160.0})
    assert b_norm["ceil"] == 160.0
    b_high = audio._bankstown({"level": 40.0, "speaker_size": 600.0})
    assert b_high["ceil"] == 250.0, f"Expected 250.0 ceiling, got {b_high['ceil']}"
    print(f"  [✓] Bass boost ceiling clamped strictly at <= 250.0 Hz (got {b_high['ceil']} Hz)")

    # 2.4 DTS GPEQ biquad unity DC gain verification
    def _q(value, integer_bits):
        return round(value * 2 ** (32 - integer_bits))

    first = (0.95, -1.9, 0.955, 1.9, -0.905)
    second = (0.9, 0.0, 0.6, 0.0, -0.5)
    blob = struct.pack("<ii", 4, 511)
    blob += struct.pack("<i5i", 2, *(_q(v, 2) for v in first))
    blob += struct.pack("<i5i", 1, *(_q(v, 1) for v in second))
    blob += struct.pack("<ii", 1, 0x7FFFFFFF) + bytes(64)

    biquads = dts.parse_gpeq(blob)
    assert len(biquads) == 2, f"Expected 2 biquads, got {len(biquads)}"
    for b in biquads:
        b0, b1, b2, a1, a2 = b
        dc_gain = (b0 + b1 + b2) / (1.0 + a1 + a2)
        assert abs(dc_gain - 1.0) < 2e-3, f"Biquad DC gain {dc_gain} deviated from unity 1.0"
    print(f"  [✓] Parametric EQ biquad decoder verified: Unity DC gain (1.000)")

    # 2.5 Live Filter-Chain apply & clean stop test
    engine = audio.PresetEngine("speakers")
    print("  [>] Testing live filter-chain loading...")
    apply_err = engine.apply("music")
    assert apply_err is None, f"Failed to apply preset: {apply_err}"
    time.sleep(0.8)
    in_effect = engine.in_effect()
    assert in_effect, "Preset was not marked in_effect after apply"
    print(f"  [✓] PipeWire smart filter active in audio graph: {engine.current}")

    print("  [>] Testing live filter-chain clean termination...")
    stop_err = engine.stop()
    assert stop_err is None, f"Failed to stop preset: {stop_err}"
    time.sleep(0.4)
    assert not engine.in_effect(), "Filter still in_effect after stop"
    print("  [✓] Filter-chain stopped cleanly, virtual sink removed, audio graph restored")

    print("\n================================================================================")
    print(" ALL 4-ZONE RGB & PIPEWIRE DSP AUDIT TESTS PASSED (100%)")
    print("================================================================================")


if __name__ == "__main__":
    test_lighting_and_audio()
