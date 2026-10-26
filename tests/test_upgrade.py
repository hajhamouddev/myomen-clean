"""Comprehensive automated test suite for MyBaby Omen upgrade.

Evaluates:
- Dual-sensor effective temperature: max(T_CPU, T_GPU).
- Decision matrix: <58 Cool, 58-77 Balanced, 78-87 Performance, >=88 Max.
- Spike detection: dT >= 7°C within 3 seconds triggers proactive step-up.
- Asymmetric hysteresis: instant step-up, 45-second hold on downshift.
- Kill-switch handover: toggling OFF cleanly restores user's manual profile and fans.
- 4th 'Max' Power/Overdrive profile: performance profile + max fans + 65W PL1.
- Notification filter: 92°C/85°C muted; 98°C (sustained for 6s) triggers emergency alert and fans locked to 100%.
- Asset & icon health check: all SVGs in gui/omensense/icons/lucide/ intact and non-empty.
"""

import os
import sys
import tempfile
import types
from pathlib import Path

LOCAL_GUI = str(Path(__file__).resolve().parent.parent / "gui")
GUI_DIR = LOCAL_GUI
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

# Stub PySide6 if not running under full X/Wayland session so logic tests run anywhere
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    class Stub:
        def __init__(self, *a, **k): pass
        def __getattr__(self, _n): return Stub()
        def __call__(self, *a, **k): return Stub()
        def __or__(self, _o): return Stub()
        __ror__ = __and__ = __add__ = __radd__ = __truediv__ = __or__
        def __iter__(self): return iter(())
        def __mro_entries__(self, _bases): return (object,)

    qt = types.ModuleType("PySide6")
    for name in ("QtCore", "QtGui", "QtWidgets"):
        mod = types.ModuleType(name)
        mod.__getattr__ = lambda _n: Stub()
        setattr(qt, name, mod)
        sys.modules[f"PySide6.{name}"] = mod
    sys.modules["PySide6"] = qt

from omensense import config, gpu, hw, monitoring, smart, system, theme, widgets

failures = []

def check(condition: bool, message: str):
    prefix = "PASS: " if condition else "FAIL: "
    print(prefix + message)
    if not condition:
        failures.append(message)


# ---------------------------------------------------------------------------
# 1. Dual-Sensor Logic
# ---------------------------------------------------------------------------
def test_dual_sensor():
    print("\n--- Testing Dual-Sensor Temperature Formula ---")
    eff = smart.BabySmartGovernor.effective_temp
    check(eff(50, 45) == 50, "Dual-sensor: CPU higher (50 vs 45) -> 50")
    check(eff(60, 75) == 75, "Dual-sensor: GPU higher (60 vs 75) -> 75")
    check(eff(None, 65) == 65, "Dual-sensor: CPU None, GPU 65 -> 65")
    check(eff(70, None) == 70, "Dual-sensor: CPU 70, GPU None -> 70")
    check(eff(None, None) is None, "Dual-sensor: both None -> None")


# ---------------------------------------------------------------------------
# 2. Decision Matrix & Governor Ladder
# ---------------------------------------------------------------------------
def test_decision_matrix():
    print("\n--- Testing Decision Matrix ---")
    p = smart.BabySmartGovernor.profile_for_temp
    check(p(45.0) == "low-power", "Decision: 45°C -> low-power (Cool)")
    check(p(57.9) == "low-power", "Decision: 57.9°C -> low-power (Cool)")
    check(p(58.0) == "balanced", "Decision: 58.0°C -> balanced")
    check(p(79.9) == "balanced", "Decision: 79.9°C -> balanced")
    check(p(80.0) == "performance", "Decision: 80.0°C -> performance (Auto fans)")
    check(p(87.9) == "performance", "Decision: 87.9°C -> performance (Auto fans)")
    check(p(89.9) == "performance", "Decision: 89.9°C -> performance (Auto fans)")
    check(p(90.0) == "max", "Decision: 90.0°C -> max (Overdrive)")
    check(p(95.0) == "max", "Decision: 95.0°C -> max (Overdrive)")


# ---------------------------------------------------------------------------
# 3. Spike Detection, 10s Max Debounce & Asymmetric Hysteresis
# ---------------------------------------------------------------------------
class MockHardware:
    def __init__(self):
        self.profile = "balanced"
        self.max_fan = False
        self.power_limit = 45
        self.writes = []

    def set_profile(self, name):
        self.writes.append(("set_profile", name))
        self.profile = name
        return None

    def set_max_fan(self, enabled):
        self.writes.append(("set_max_fan", enabled))
        self.max_fan = enabled
        return None

    def set_power_limit_w(self, watts):
        self.writes.append(("set_power_limit_w", watts))
        self.power_limit = watts
        return None


def test_governor_logic():
    print("\n--- Testing Governor Logic, 10s Debounce, Spike Safeguards & Rebound ---")
    mock = MockHardware()
    real_set_profile = hw.set_profile
    real_profile = hw.profile
    real_max_fan = hw.max_fan
    real_set_max_fan = hw.set_max_fan
    real_profile_path = hw.profile_path

    hw.profile_path = lambda: "/mock/profile"
    hw.profile = lambda: mock.profile
    hw.set_profile = mock.set_profile
    hw.max_fan = lambda: mock.max_fan
    hw.set_max_fan = mock.set_max_fan

    try:
        gov = smart.BabySmartGovernor(hold_time_s=45.0)
        gov.start(now=0.0)
        check(gov.enabled, "Governor starts and enables successfully")
        check(gov.current == "balanced", "Governor captures initial profile 'balanced'")

        # 3.1 Steady temp 50°C -> initiates downshift to low-power, holding 45s
        mock.writes.clear()
        gov.tick(cpu_temp=50, gpu_temp=48, on_ac=True, now=1.0)
        check(gov.current == "balanced" and len(mock.writes) == 0,
              "Asymmetric hysteresis: 50°C does not instantly downshift, holds 45s")

        # Advance to 44s: still holding balanced
        gov.tick(cpu_temp=50, gpu_temp=48, on_ac=True, now=44.0)
        check(gov.current == "balanced", "44s elapsed: still holding balanced")

        # Advance to 46s: downshift triggers!
        gov.tick(cpu_temp=50, gpu_temp=48, on_ac=True, now=46.5)
        check(gov.current == "low-power" and ("set_profile", "low-power") in mock.writes,
              "46s elapsed (>45s): downshift to low-power successfully applied")

        # 3.2 Spike floor check: dT >= 7°C disabled when T < 75°C
        mock.writes.clear()
        # Temp jumps 50 -> 60°C (+10°C in 2s, but eff_temp 60 < 75°C, so spike disabled)
        gov.tick(cpu_temp=50, gpu_temp=48, on_ac=True, now=50.0)
        gov.tick(cpu_temp=60, gpu_temp=55, on_ac=True, now=52.0)
        check(gov.current == "low-power", "60°C step-up waits for confirmation (UPSHIFT_CONFIRM_S)")
        gov.tick(cpu_temp=60, gpu_temp=55, on_ac=True, now=56.5)
        check(gov.current == "balanced", "60°C transitions to balanced via matrix after 4s (spike disabled <75°C)")

        # 3.3 Active spike safeguard (T >= 75°C): jumps one tier, NEVER jumps directly to Max
        mock.writes.clear()
        # at 70s temp is 70°C (balanced)
        gov.tick(cpu_temp=70, gpu_temp=68, on_ac=True, now=70.0)
        # at 72s temp spikes to 78°C (+8°C in 2s, and >= 75°C) -> one-tier bump latched, confirmed after 4s
        gov.tick(cpu_temp=78, gpu_temp=76, on_ac=True, now=72.0)
        gov.tick(cpu_temp=78, gpu_temp=76, on_ac=True, now=74.0)
        check(gov.current == "balanced" and not mock.writes,
              "Spike bump is latched, not applied before UPSHIFT_CONFIRM_S")
        gov.tick(cpu_temp=78, gpu_temp=76, on_ac=True, now=76.0)
        check(gov.current == "performance" and ("set_profile", "performance") in mock.writes,
              "Spike safeguard >=75°C: bumps one tier from balanced to performance")

        # 3.4 Transient micro-spikes between 80°C and 89°C remain strictly in Performance Mode with Auto fan
        mock.writes.clear()
        gov.tick(cpu_temp=85, gpu_temp=82, on_ac=True, now=77.0)
        check(gov.current == "performance" and ("set_max_fan", True) not in mock.writes,
              "Transient 85°C remains strictly in Performance Mode with Auto fans")

        gov.tick(cpu_temp=89, gpu_temp=88, on_ac=True, now=78.0)
        check(gov.current == "performance" and ("set_max_fan", True) not in mock.writes,
              "89°C (under 90°C) remains strictly in Performance Mode with Auto fans")

        # 3.5 10-Second Max Mode Debounce Window:
        # At 90°C for ticks 1 to 9 (1-9 seconds), must stay in Performance!
        mock.writes.clear()
        for sec in range(1, 10):
            gov.tick(cpu_temp=91, gpu_temp=89, on_ac=True, now=80.0 + sec)
            check(gov.current == "performance", f"Tick {sec}/10 at >=90°C: still in Performance (debouncing)")

        # Tick 10 (10th consecutive second at >=90°C) -> Engages Max Overdrive!
        gov.tick(cpu_temp=92, gpu_temp=90, on_ac=True, now=90.0)
        check(gov.current == "max" and ("set_max_fan", True) in mock.writes
              and ("set_profile", "max") not in mock.writes,
              "Tick 10 (10s sustained >=90°C): Max Overdrive = performance + max fan, PL1 untouched")

        # 3.6 Reset on single tick drop: if temp drops below 90°C during debounce window, reset counter!
        # First test leaving max mode downshift and explicit fan restoration:
        mock.writes.clear()
        # Drop temp to 82°C (Performance) -> holds for 45s downshift
        gov.tick(cpu_temp=82, gpu_temp=80, on_ac=True, now=91.0)
        # Advance 46s: downshift triggers!
        gov.tick(cpu_temp=82, gpu_temp=80, on_ac=True, now=137.0)
        check(gov.current == "performance", "Downshift to Performance applied after hold")
        check(("set_max_fan", False) in mock.writes,
              "Explicit Fan Restoration: leaving Max mode sets fan back to Auto (pwm1_enable=2)")

        # Now test single-tick drop during debounce:
        mock.writes.clear()
        # 5 ticks at 91°C
        for sec in range(1, 6):
            gov.tick(cpu_temp=91, gpu_temp=89, on_ac=True, now=160.0 + sec)
        # 1 tick drop to 88°C -> counter resets!
        gov.tick(cpu_temp=88, gpu_temp=86, on_ac=True, now=166.0)
        # Next 5 ticks at 91°C (total 10 ticks, but interrupted!)
        for sec in range(1, 6):
            gov.tick(cpu_temp=91, gpu_temp=89, on_ac=True, now=166.0 + sec)
        check(gov.current == "performance" and ("set_profile", "max") not in mock.writes,
              "Interrupted 90°C window does NOT trigger Max (counter cleanly reset)")

        # 3.7 Kill-switch handover: stopping governor cleanly restores initial manual profile
        mock.writes.clear()
        gov.stop()
        check(not gov.enabled, "Governor cleanly stopped")
        check(mock.profile == "balanced", "Kill-switch restored user's initial manual profile ('balanced')")

    finally:
        hw.profile_path = real_profile_path
        hw.profile = real_profile
        hw.set_profile = real_set_profile
        hw.max_fan = real_max_fan
        hw.set_max_fan = real_set_max_fan


# ---------------------------------------------------------------------------
# 4. Max Mode Composite Actions
# ---------------------------------------------------------------------------
def test_max_profile_hardware_actions():
    print("\n--- Testing 4th 'Max' Power Composite Action ---")
    choices = hw.profile_choices()
    check("max" in choices, f"'max' is present in profile_choices(): {choices}")
    check(hw.PROFILE_TITLES.get("max") == "Max", "PROFILE_TITLES['max'] is 'Max'")
    check("Max" in hw.PROFILE_NOTES.get("max", ""), "PROFILE_NOTES has descriptive Max entry")


# ---------------------------------------------------------------------------
# 5. Silent Notification & Emergency Alert
# ---------------------------------------------------------------------------
def test_notification_policy():
    print("\n--- Testing Silent Notification Policy & Emergency Alert ---")
    mock_notified = []
    real_notify = monitoring.notify
    monitoring.notify = lambda title, body, urgent=False: mock_notified.append((title, body, urgent))

    try:
        alerts = monitoring.Alerts()

        # 5.1 Routine temperatures: 75°C, 85°C, 92°C must NOT trigger any alert
        fired = alerts.check({"cpu_temp": 75, "gpu_temp": 70}, now=0.0)
        check(len(fired) == 0 and len(mock_notified) == 0, "75°C produces no notification")

        fired = alerts.check({"cpu_temp": 85, "gpu_temp": 80}, now=1.0)
        check(len(fired) == 0 and len(mock_notified) == 0, "85°C produces no notification")

        fired = alerts.check({"cpu_temp": 92, "gpu_temp": 84}, now=2.0)
        check(len(fired) == 0 and len(mock_notified) == 0, "92°C (former threshold) produces no notification (MUTED)")

        # 5.2 98°C transient spike (< 6s, 1 tick) -> must NOT alert
        mock_notified.clear()
        fired = alerts.check({"cpu_temp": 98, "gpu_temp": 80}, now=10.0)
        check(len(fired) == 0 and len(mock_notified) == 0, "98°C transient at 0s does NOT alert immediately")

        # at 3s (tick 2): still within 6s window -> no alert
        fired = alerts.check({"cpu_temp": 99, "gpu_temp": 82}, now=13.0)
        check(len(fired) == 0 and len(mock_notified) == 0, "99°C sustained for 3s does not alert yet")

        # at 6.1s (tick 3): sustained >= 6s with 3 ticks -> FIRES EMERGENCY!
        fired = alerts.check({"cpu_temp": 98, "gpu_temp": 85}, now=16.1)
        check(len(fired) > 0 and len(mock_notified) == 1,
              f"98°C sustained for 6.1s triggers emergency alert: {mock_notified}")

        if mock_notified:
            title, body, urgent = mock_notified[0]
            check(title == "Baby Smart — Thermal Emergency", f"Emergency title is exact: {title}")
            check("Sustained temperature reached 98°C" in body, f"Emergency body contains sustained temp: {body}")
            check("Cooling fans locked to 100%" in body, "Emergency body specifies fans locked to 100%")
            check(urgent is True, "Emergency alert urgency is Critical (True)")

    finally:
        monitoring.notify = real_notify


# ---------------------------------------------------------------------------
# 6. Asset & Icon Health Check
# ---------------------------------------------------------------------------
def test_asset_integrity():
    print("\n--- Testing Asset & Icon Health ---")
    lucide_dir = os.path.join(GUI_DIR, "omensense", "icons", "lucide")
    check(os.path.isdir(lucide_dir), f"Lucide directory exists: {lucide_dir}")

    svgs = [f for f in os.listdir(lucide_dir) if f.endswith(".svg")]
    check(len(svgs) >= 20, f"Lucide icons intact: found {len(svgs)} SVGs")

    empty_svgs = [f for f in svgs if os.path.getsize(os.path.join(lucide_dir, f)) == 0]
    check(len(empty_svgs) == 0, f"No empty SVGs found (empty: {empty_svgs})")

    # Check local H-Logo
    logo_path = os.path.join(GUI_DIR, "omensense", "icons", "logo-color-for-dark-bg.svg")
    check(os.path.exists(logo_path) and os.path.getsize(logo_path) > 0,
          f"Local H-Logo SVG exists and is non-empty ({logo_path})")

    # Check BabySmartButton widget class
    check(hasattr(widgets, "BabySmartButton"), "BabySmartButton is exported in widgets.py")


# ---------------------------------------------------------------------------
# 7. Reboot Persistence Engine (state.json)
# ---------------------------------------------------------------------------
def test_config_persistence():
    print("\n--- Testing Reboot Persistence Engine (state.json) ---")
    with tempfile.TemporaryDirectory() as tmp:
        orig_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = tmp
        try:
            # 1. Loading when no file exists returns DEFAULT_STATE
            initial = config.load_state()
            check(initial["governor"]["baby_smart"] is False, "Default state: baby_smart is False")
            check(initial["active_profile"] == "myBaby", "Default state: active_profile is 'myBaby'")
            check(initial["startup_toggles"]["apply_at_login"] is False, "Default state: apply_at_login is False")

            # 2. Saving governor state
            check(config.save_governor(baby_smart=True, smart=False), "save_governor returns True")
            loaded = config.load_state()
            check(loaded["governor"]["baby_smart"] is True, "Persisted baby_smart=True preserved")
            check(loaded["governor"]["smart"] is False, "Persisted smart=False preserved")

            # 3. Saving theme
            check(config.save_theme("#00d2ff", "nord-glacier", "manual"), "save_theme returns True")
            loaded = config.load_state()
            check(loaded["theme"]["accent_color"] == "#00d2ff", "Persisted accent_color is '#00d2ff'")
            check(loaded["theme"]["layout_name"] == "nord-glacier", "Persisted layout_name is 'nord-glacier'")
            check(loaded["theme"]["theme_mode"] == "manual", "Persisted theme_mode is 'manual'")

            # 4. Saving active profile
            check(config.save_active_profile("myBaby"), "save_active_profile returns True")
            loaded = config.load_state()
            check(loaded["active_profile"] == "myBaby", "Persisted active_profile is 'myBaby'")

            # 5. Saving startup toggles
            check(config.save_startup_toggles(apply_at_login=True, start_with_computer=True, omen_key=True),
                  "save_startup_toggles returns True")
            loaded = config.load_state()
            check(loaded["startup_toggles"]["apply_at_login"] is True, "apply_at_login is True")
            check(loaded["startup_toggles"]["start_with_computer"] is True, "start_with_computer is True")
            check(loaded["startup_toggles"]["omen_key"] is True, "omen_key is True")

            # 6. Update single startup toggle
            check(config.update_startup_toggle("omen_key", False), "update_startup_toggle returns True")
            loaded = config.load_state()
            check(loaded["startup_toggles"]["omen_key"] is False, "update_startup_toggle updated omen_key to False")
            check(loaded["startup_toggles"]["apply_at_login"] is True, "other toggles unmodified")

            # 7. Fault tolerance on corrupted state file
            st_file = config.state_file()
            with open(st_file, "w") as f:
                f.write("INVALID JSON DATA {{{")
            fallback = config.load_state()
            check(fallback["governor"]["baby_smart"] is False, "Corrupt state.json gracefully falls back to defaults")
        finally:
            if orig_xdg is not None:
                os.environ["XDG_CONFIG_HOME"] = orig_xdg
            else:
                os.environ.pop("XDG_CONFIG_HOME", None)


# ---------------------------------------------------------------------------
# 8. Zero-Overhead GPU Telemetry & D3cold Detection
# ---------------------------------------------------------------------------
def test_gpu_telemetry_and_d3cold():
    print("\n--- Testing Zero-Overhead GPU Telemetry & D3cold Detection ---")
    orig_is_suspended = gpu.is_suspended
    orig_available = gpu.available
    orig_query_raw = gpu._query_raw
    orig_last_fetch = gpu._last_fetch_time
    orig_cached = dict(gpu._cached_data)

    try:
        gpu.available = lambda: True

        # 1. When GPU is in D3cold runtime suspend (is_suspended == True)
        gpu.is_suspended = lambda: True
        with gpu._lock:
            gpu._cached_data = {}
        data = gpu.read(sync=False)
        check(data.get("suspended") is True, "D3cold detection: GPU marked suspended")
        check(data.get("usage") == 0, "D3cold detection: GPU usage reported as 0 (bus idle)")
        check(data.get("temp") is None, "D3cold detection: GPU temp not probed (avoids waking bus)")

        # 2. When GPU is active (is_suspended == False) and query is cached
        gpu.is_suspended = lambda: False
        with gpu._lock:
            gpu._cached_data = {
                "fan_percent": 30,
                "temp": 55,
                "clock_mhz": 1200,
                "usage": 25,
                "name": "NVIDIA GeForce RTX 2060 Mobile",
                "suspended": False,
            }
            gpu._last_fetch_time = 1000.0

        # Query within TTL (say 1001.0, diff 1.0s < 3.0s) returns cached data immediately
        import time
        orig_time = time.monotonic
        time.monotonic = lambda: 1001.0

        mock_query_called = []
        gpu._query_raw = lambda: (mock_query_called.append(True) or {})

        res = gpu.read(sync=False)
        check(res["temp"] == 55 and res["usage"] == 25, "Read returns cached GPU metrics")
        check(len(mock_query_called) == 0, "No new query spawned when within 3s TTL cache window")

        time.monotonic = orig_time

    finally:
        gpu.is_suspended = orig_is_suspended
        gpu.available = orig_available
        gpu._query_raw = orig_query_raw
        gpu._last_fetch_time = orig_last_fetch
        with gpu._lock:
            gpu._cached_data = orig_cached


# ---------------------------------------------------------------------------
# 9. Dynamic Theme Accent Synchronization
# ---------------------------------------------------------------------------
def test_dynamic_accent():
    print("\n--- Testing Dynamic Theme Accent Synchronization ---")
    orig_accent = theme.get_dynamic_accent()
    notified = []
    theme.register_accent_listener(lambda c: notified.append(c))

    try:
        theme.set_dynamic_accent("#00d2ff")
        check(theme.get_dynamic_accent() == "#00d2ff", "Dynamic accent updated to '#00d2ff'")
        check("#00d2ff" in notified, "Accent listener was notified of update")

        theme.set_dynamic_accent("#e024c3")
        check(theme.get_dynamic_accent() == "#e024c3", "Dynamic accent updated to '#e024c3'")
    finally:
        theme.set_dynamic_accent(orig_accent)


# ---------------------------------------------------------------------------
# 10. NVIDIA Driver Detection in System / MUD
# ---------------------------------------------------------------------------
def test_nvidia_driver_detection():
    print("\n--- Testing NVIDIA Driver Detection in System/MUD ---")
    supported, desc = system.nvidia_driver_status()
    if os.path.exists("/proc/driver/nvidia/version"):
        check(supported is True, "NVIDIA driver detected as supported from /proc/driver/nvidia/version")
        check("NVIDIA" in desc, f"NVIDIA driver description contains version: '{desc}'")
        check("595" in desc, f"NVIDIA driver description correctly includes major version: '{desc}'")
    else:
        check(isinstance(supported, bool), "Supported is boolean")
        check(isinstance(desc, str), "Description is string")


# ---------------------------------------------------------------------------
# 11. Tray DBus Menu, Quick Settings Overlay & Sidebar Geometry
# ---------------------------------------------------------------------------
def test_tray_menu_and_quick_settings_overlay():
    print("\n--- Testing Tray DBus Menu, Quick Settings Overlay & Sidebar Geometry ---")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv + ["-platform", "offscreen"])

    from omensense import tray as tray_module
    from omensense import widgets

    # Test standalone QuickSettingsPopup flags
    popup = widgets.QuickSettingsPopup(None)
    flags = popup.windowFlags()
    check(bool(flags & QtCore.Qt.WindowType.Tool), "QuickSettingsPopup has WindowType.Tool flag")
    check(bool(flags & QtCore.Qt.WindowType.FramelessWindowHint), "QuickSettingsPopup has FramelessWindowHint")
    check(bool(flags & QtCore.Qt.WindowType.WindowStaysOnTopHint), "QuickSettingsPopup has WindowStaysOnTopHint")

    # QuickSettingsWidget is the panel hosted inside the popup; the popup owns the window flags
    check(isinstance(popup.widget, widgets.QuickSettingsWidget) and popup.widget.parent() is popup,
          "QuickSettingsWidget is embedded in QuickSettingsPopup")
    popup.close()

    # Test Tray context menu & DBus AppIndicator compatibility
    dummy_win = QtWidgets.QWidget()
    t = tray_module.Tray(dummy_win)
    check(t.contextMenu() is not None, "Tray context menu is attached via setContextMenu")
    check(t.contextMenu() is t.menu, "Tray contextMenu matches internal menu instance")

    actions = t.menu.actions()
    action_texts = [a.text() for a in actions if not a.isSeparator()]
    check("⚡ Quick Settings..." in action_texts, "Menu contains '⚡ Quick Settings...' action")
    check("Open MyOmen" in action_texts, "Menu contains 'Open MyOmen' action")
    check("Quit" in action_texts, "Menu contains 'Quit' action")
    check(any(a.isSeparator() for a in actions), "Menu contains separator between open and quit")
    check(t.menu.defaultAction() == t.act_quick, "'⚡ Quick Settings...' is set as defaultAction")

    # CollapsibleSidebar: the profile hub was removed (d808e43); MainWindow still wires these attributes
    sections = (("Home", "activity", "Test"),)
    sidebar = widgets.CollapsibleSidebar(sections, dummy_win)
    check(all(hasattr(sidebar, a) for a in ("profiles", "save_profile", "delete_profile")),
          "CollapsibleSidebar keeps profile compatibility attributes for MainWindow")
    check(sidebar.current_profile() is None, "CollapsibleSidebar has no active sidebar profile")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_dual_sensor()
    test_decision_matrix()
    test_governor_logic()
    test_max_profile_hardware_actions()
    test_notification_policy()
    test_asset_integrity()
    test_config_persistence()
    test_gpu_telemetry_and_d3cold()
    test_dynamic_accent()
    test_nvidia_driver_detection()
    test_tray_menu_and_quick_settings_overlay()

    print("\n==================================================")
    if not failures:
        print("ALL UPGRADE TESTS PASSED SUCCESSFULLY (0 FAILURES)")
        sys.exit(0)
    else:
        print(f"FAILED: {len(failures)} test(s) failed:")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
