"""Automated headless smoke test verifying end-to-end page navigation across all 5 sections."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure offscreen Qt execution
os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_GUI = str(REPO_ROOT / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

from PySide6 import QtCore, QtWidgets
from omensense import app, theme


def run_navigation_audit() -> bool:
    print("================================================================================")
    print(" MYOMEN END-TO-END NAVIGATION AUDIT & PAGE SWITCHING TEST")
    print("================================================================================")

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["--platform", "offscreen"])

    # Instantiate GUI Window
    win = app.Window(tray_mode=False)
    win.show()

    # Verify 5 pages are present
    assert win.pages.count() == 5, f"Expected 5 stacked pages, found {win.pages.count()}"
    print(f"[✓] StackedWidget initialized with exactly {win.pages.count()} pages.")

    # Expected titles and subheadings
    pages_spec = [
        (0, "System Overview", "Omen Autopilot Active • Non-root udev rules"),
        (1, "Performance Modes", "ACPI platform profile & power limits"),
        (2, "4-Zone Lighting", "4-Zone RGB Lighting & Presets"),
        (3, "PipeWire Audio DSP", "PipeWire limiter, audio & hardware specs"),
        (4, "System & Drivers", "Driver setup & udev installer"),
    ]

    mock_telemetry = {
        "sensors": {"cpu_temp": 52, "fans": [2400, 2600], "sys_temp": 46},
        "gpu": {"temp": 48, "usage": 15, "clock_mhz": 1200, "power_w": 28.5},
        "cpu_load": 12,
        "ram": {"percent": 45, "used_gb": 7.2, "total_gb": 16.0},
        "power_limit_w": 45,
        "power_source": {"ac_online": True, "battery_percent": 100, "status": "Full"},
        "wattage": 35.0,
        "profile": "balanced",
        "max_fan": False,
    }

    print("\n--- Testing Navigation via Direct Button Click ---")
    for idx, expected_title, expected_sub in pages_spec:
        btn = win.sidebar.btn_group.button(idx)
        assert btn is not None, f"Sidebar button at index {idx} not found!"
        btn.click()
        qt_app.processEvents()

        # Assert active page index
        current_idx = win.pages.currentIndex()
        assert current_idx == idx, f"Expected page index {idx}, got {current_idx}"

        # Assert heading and subheading
        title = win.page_heading.text()
        sub = win.page_subheading.text()
        assert title == expected_title, f"Expected title '{expected_title}', got '{title}'"
        assert sub == expected_sub, f"Expected subtitle '{expected_sub}', got '{sub}'"

        # Assert sidebar button check state
        assert btn.isChecked(), f"Sidebar button at index {idx} was not checked"

        # Dispatch telemetry refresh to verify active page stability
        win.on_telemetry_updated(mock_telemetry)
        qt_app.processEvents()

        print(f"  [✓] Page {idx}: '{title}' -> Switched, Heading Validated, Telemetry Dispatched.")

    print("\n--- Testing Navigation via section_changed Signal ---")
    for idx, expected_title, _ in reversed(pages_spec):
        win.sidebar.section_changed.emit(idx)
        qt_app.processEvents()
        assert win.pages.currentIndex() == idx
        assert win.page_heading.text() == expected_title
        assert win.sidebar.btn_group.button(idx).isChecked()
        print(f"  [✓] Signal section_changed({idx}) -> Switched to '{expected_title}' with sidebar sync.")

    print("\n--- Testing Programmatic select(index) Synchronization ---")
    for idx, expected_title, _ in pages_spec:
        win.select(idx)
        qt_app.processEvents()
        assert win.pages.currentIndex() == idx
        assert win.page_heading.text() == expected_title
        assert win.sidebar.btn_group.button(idx).isChecked()
        print(f"  [✓] win.select({idx}) -> Synchronized sidebar button and stacked page.")

    print("\n--- Testing Sidebar Collapse & Expand on Each Page ---")
    for idx, _, _ in pages_spec:
        win.select(idx)
        # Collapse
        win.sidebar.toggle_sidebar()
        qt_app.processEvents()
        assert win.sidebar.is_expanded is False
        assert win.sidebar.width() == theme.SIDEBAR_COLLAPSED_WIDTH
        assert win.sidebar.brand_widget.isHidden()

        # Expand
        win.sidebar.toggle_sidebar()
        qt_app.processEvents()
        assert win.sidebar.is_expanded is True
        assert win.sidebar.width() == theme.SIDEBAR_EXPANDED_WIDTH
        assert not win.sidebar.brand_widget.isHidden()
        print(f"  [✓] Page {idx}: Sidebar collapsed to 72px and expanded to 230px with 0 errors.")

    print("\n================================================================================")
    print(" ALL 5 PAGES SWITCHED & VERIFIED WITH ZERO ERRORS (PASS)")
    print("================================================================================")
    win.close()
    return True


if __name__ == "__main__":
    success = run_navigation_audit()
    sys.exit(0 if success else 1)
