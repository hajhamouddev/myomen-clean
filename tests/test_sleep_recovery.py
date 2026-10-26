#!/usr/bin/env python3
"""Suspend/Resume Lifecycle & ACPI Hardware State Recovery Test Suite.

Simulates:
1. Emitting PrepareForSleep(True) (entering sleep).
2. Simulating firmware/EC state drift during sleep (e.g. platform profile reset).
3. Emitting PrepareForSleep(False) (resuming from sleep).
4. Asserting that hw.set_platform_profile() is invoked with the expected active profile
   and GUI/Tray state remains synchronized.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure headless offscreen platform and clean XDG directory
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_RUNTIME_DIR"] = "/tmp/runtime-myomen-sleep-test"
os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)

# Strict sys.path isolation
LOCAL_GUI = str(Path(__file__).resolve().parent.parent / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

from PySide6 import QtCore, QtWidgets
from omensense import config, hw, state
from omensense.app import Window
from omensense.hardware import SleepMonitor
from omensense.tray import Tray


class TestSleepRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.initial_profile = hw.profile()
        config.save_active_profile("performance")

    def tearDown(self):
        if self.initial_profile:
            hw.set_profile(self.initial_profile)
        config.save_active_profile(self.initial_profile or "balanced")

    def test_01_sleep_monitor_signals(self):
        """Test SleepMonitor signal emission on sleep and resume."""
        monitor = SleepMonitor()
        sleep_states = []
        resumed_called = []

        monitor.prepare_for_sleep.connect(lambda s: sleep_states.append(s))
        monitor.resumed.connect(lambda: resumed_called.append(True))

        # 1. Simulate entering sleep
        monitor.simulate_sleep_event(True)
        self.assertEqual(sleep_states, [True])
        self.assertEqual(len(resumed_called), 0)

        # 2. Simulate resuming from sleep
        monitor.simulate_sleep_event(False)
        self.assertEqual(sleep_states, [True, False])
        self.assertEqual(len(resumed_called), 1)

        monitor.close()

    def test_02_window_sleep_and_recovery(self):
        """Test Window recovers active profile and resyncs GUI/Tray upon wake."""
        win = Window(tray_mode=True)
        if win.tray is None:
            win.tray = Tray(win)

        # Set active profile to 'performance' in config
        config.save_active_profile("performance")
        self.assertEqual(config.active_profile(), "performance")

        applied_profiles = []
        original_set_profile = hw.set_platform_profile

        def mock_set_platform_profile(mode):
            applied_profiles.append(mode)
            return original_set_profile(mode)

        hw.set_platform_profile = mock_set_platform_profile

        try:
            # 1. Simulate entering sleep
            win.sleep_monitor.simulate_sleep_event(True)
            self.assertEqual(win.worker._user_mode, "tray")

            # 2. Simulate firmware reset during sleep: force sysfs to 'low-power'
            original_set_profile("low-power")
            self.assertEqual(hw.profile(), "low-power")

            # 3. Simulate waking up from sleep
            win.sleep_monitor.simulate_sleep_event(False)

            # Trigger immediate recovery handler (bypassing 1.0s timer for instant assert)
            win.on_system_resumed()

            # Verify that hw.set_platform_profile was re-invoked with 'performance'
            self.assertIn("performance", applied_profiles)
            self.assertEqual(hw.profile(), "performance")

            # Verify that PowerPlatformCard and Tray buttons reflect 'performance'
            self.assertTrue(win.home.power_platform_card.buttons["performance"].isChecked())
            if "performance" in win.tray.power_actions:
                self.assertTrue(win.tray.power_actions["performance"].isChecked())

        finally:
            hw.set_platform_profile = original_set_profile
            if win.worker:
                win.worker.stop()
            win.sleep_monitor.close()

    def test_03_transient_error_retry(self):
        """Test recovery retries on transient OSError during resume."""
        win = Window(tray_mode=True)
        if win.tray is None:
            win.tray = Tray(win)

        config.save_active_profile("balanced")
        attempts = []

        def failing_once_set_profile(mode):
            attempts.append(mode)
            if len(attempts) == 1:
                raise OSError("Device or resource busy (transient)")
            return None

        with patch.object(hw, "set_platform_profile", side_effect=failing_once_set_profile):
            win.on_system_resumed()
            # Assert retry happened
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts, ["balanced", "balanced"])

        if win.worker:
            win.worker.stop()
        win.sleep_monitor.close()


if __name__ == "__main__":
    unittest.main()
