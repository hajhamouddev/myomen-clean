"""Automated test validating Typography escaping, RAPL sysfs non-root permissions, and Tray icon."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_GUI = str(REPO_ROOT / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

from PySide6 import QtCore, QtWidgets
from omensense import app, hw, tray


def test_typography_and_rapl():
    print("================================================================================")
    print(" TYPOGRAPHY POLISH & RAPL NON-ROOT WRITE ACCESS VALIDATION")
    print("================================================================================")

    # 1. Typography & Ampersand Escaping
    print("\n[Track 1] Typography & Ampersand Mnemonic Escaping:")
    assert app.SECTIONS[4][0] == "System && Drivers", f"Expected 'System && Drivers', got '{app.SECTIONS[4][0]}'"
    print(f"  [✓] app.SECTIONS[4][0] is correctly escaped: '{app.SECTIONS[4][0]}'")

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["--platform", "offscreen"])
    win = app.Window(tray_mode=False)

    # Verify Sidebar navigation item button
    btn_sys = win.sidebar.btn_group.button(4)
    assert btn_sys is not None, "Sidebar button 4 not found"
    assert "System && Drivers" in btn_sys.text(), f"Unexpected button text: {btn_sys.text()}"
    assert btn_sys.toolTip().startswith("System & Drivers:"), f"Unexpected tooltip: {btn_sys.toolTip()}"
    print(f"  [✓] Sidebar button 4 text: '{btn_sys.text()}' | tooltip: '{btn_sys.toolTip()}'")

    # Verify Page 5 Reset & Install Stable Drivers button
    mud_page = win.mud
    assert mud_page.btn_reset_drivers.text() == "Reset && Install Stable Drivers", (
        f"Unexpected reset button text: {mud_page.btn_reset_drivers.text()}"
    )
    print(f"  [✓] btn_reset_drivers text: '{mud_page.btn_reset_drivers.text()}'")

    # 2. RAPL Non-Root Permissions & Diagnostic Card
    print("\n[Track 2] RAPL Non-Root Read/Write Permissions:")
    rapl_node = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
    assert os.path.exists(rapl_node), f"RAPL node not found at {rapl_node}"
    is_writable = os.access(rapl_node, os.W_OK)
    print(f"  [✓] Sysfs node {rapl_node} exists. Non-root W_OK: {is_writable}")

    # Check diagnostic card on System & Drivers page
    mud_page.refresh_diagnostics()
    card_readout = mud_page.card_rapl.readout_label.text()
    card_subtitle = mud_page.card_rapl.sub_label.text()
    print(f"  [✓] card_rapl readout: '{card_readout}', subtitle: '{card_subtitle}'")
    assert card_readout in ["[ OK ]", "[ READ / WRITE ]"], f"Unexpected card readout: {card_readout}"
    if is_writable:
        assert card_readout == "[ OK ]"
        assert card_subtitle == "PL1 write permission granted"

    # Test hw module read/write without root
    current_limit = hw.power_limit_w()
    print(f"  [✓] hw.power_limit_w() readout: {current_limit} W")
    assert current_limit is not None and current_limit > 0, "Failed to read valid power limit"

    if is_writable:
        res = hw.set_power_limit_w(current_limit)
        assert res is None, f"Failed to write power limit: {res}"
        print(f"  [✓] hw.set_power_limit_w({current_limit}) succeeded non-root (return: {res})")

    # 3. Dynamic Tray Icon Contrast
    print("\n[Track 3] Dynamic Tray Icon Generation:")
    icon = tray.make_dynamic_tray_icon(45, 50)
    assert not icon.isNull(), "Generated tray icon is null"
    sizes = icon.availableSizes()
    print(f"  [✓] make_dynamic_tray_icon returned valid QIcon with sizes: {sizes}")

    print("\n================================================================================")
    print(" ALL TYPOGRAPHY, RAPL & TRAY TESTS PASSED (100%)")
    print("================================================================================")


if __name__ == "__main__":
    test_typography_and_rapl()
