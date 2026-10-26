#!/usr/bin/env python3
"""Bidirectional Profile Synchronization & Hardware Readout Test Suite.

Verifies:
1. hw.set_platform_profile(mode) & hw.set_profile(mode) error handling & normalization.
2. PowerPlatformCard click triggers canonical mode emission and reflects state.
3. TrayMenu power actions synchronize bidirectionally with hardware state.
4. Window.on_power_profile_selected updates UI state and sysfs read-back.
"""

import os
import sys
import unittest
from pathlib import Path

# Set headless platform before Qt import
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_RUNTIME_DIR"] = "/tmp/runtime-myomen-test"
os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)

LOCAL_GUI = str(Path(__file__).resolve().parent.parent / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

from PySide6 import QtCore, QtWidgets
from omensense import hw, widgets
from omensense.app import Window
from omensense.tray import Tray


class TestProfileSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.initial_profile = hw.profile()

    def tearDown(self):
        # Restore initial profile
        if self.initial_profile:
            hw.set_profile(self.initial_profile)

    def test_01_hw_profile_api_and_normalization(self):
        """Test hw.set_platform_profile and hw.set_profile normalization & error handling."""
        self.assertTrue(hasattr(hw, "set_platform_profile"), "hw must expose set_platform_profile alias")
        self.assertTrue(hasattr(hw, "set_profile"), "hw must expose set_profile")

        # Test invalid mode handling
        err = hw.set_profile("non_existent_turbo_mode")
        self.assertIsNotNone(err)
        self.assertIn("Unknown mode", err)

        # Test normalization of 'quiet' to 'low-power'
        err_quiet = hw.set_platform_profile("quiet")
        if hw.profile_path():
            self.assertIsNone(err_quiet, f"set_platform_profile('quiet') failed: {err_quiet}")
            current = hw.profile()
            self.assertEqual(current, "low-power", "Profile 'quiet' must normalize to 'low-power'")

        # Test 'balanced'
        err_bal = hw.set_platform_profile("balanced")
        if hw.profile_path():
            self.assertIsNone(err_bal, f"set_platform_profile('balanced') failed: {err_bal}")
            self.assertEqual(hw.profile(), "balanced")

    def test_02_power_platform_card_sync(self):
        """Test PowerPlatformCard button clicks and state reflection."""
        card = widgets.PowerPlatformCard()
        emitted_modes = []
        card.profile_changed.connect(lambda m: emitted_modes.append(m))

        # Click Quiet button -> emits canonical 'low-power'
        card.buttons["low-power"].click()
        self.assertEqual(emitted_modes[-1], "low-power")

        # Click Performance button -> emits canonical 'performance'
        card.buttons["performance"].click()
        self.assertEqual(emitted_modes[-1], "performance")

        # Click Balanced button -> emits canonical 'balanced'
        card.buttons["balanced"].click()
        self.assertEqual(emitted_modes[-1], "balanced")

        # Test set_active_profile reflections
        card.set_active_profile("low-power")
        self.assertTrue(card.buttons["low-power"].isChecked())

        card.set_active_profile("quiet")
        self.assertTrue(card.buttons["low-power"].isChecked())

        card.set_active_profile("performance")
        self.assertTrue(card.buttons["performance"].isChecked())

        card.set_active_profile("balanced")
        self.assertTrue(card.buttons["balanced"].isChecked())

    def test_03_window_bidirectional_sync(self):
        """Test Window.on_power_profile_selected synchronizes PowerPlatformCard and Tray."""
        win = Window(tray_mode=True)
        if win.tray is None:
            win.tray = Tray(win)
        self.assertIsNotNone(win.tray)

        # 1. Switch to Quiet / low-power via Window API
        win.on_power_profile_selected("quiet")
        self.assertTrue(win.home.power_platform_card.buttons["low-power"].isChecked())
        if "low-power" in win.tray.power_actions:
            self.assertTrue(win.tray.power_actions["low-power"].isChecked())

        # 2. Switch to Performance
        win.on_power_profile_selected("performance")
        self.assertTrue(win.home.power_platform_card.buttons["performance"].isChecked())
        if "performance" in win.tray.power_actions:
            self.assertTrue(win.tray.power_actions["performance"].isChecked())

        # 3. Switch to Balanced via Tray action trigger
        if "balanced" in win.tray.power_actions:
            win.tray.power_actions["balanced"].trigger()
            self.assertTrue(win.home.power_platform_card.buttons["balanced"].isChecked())
            self.assertTrue(win.tray.power_actions["balanced"].isChecked())

        # Clean shutdown of worker thread
        if win.worker:
            win.worker.stop()


if __name__ == "__main__":
    unittest.main()
