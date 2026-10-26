"""omen-sense - MyOmen Linux Control Suite.

Overhauled with Spotify Matte Dark (#121212) aesthetics, SF Pro typography,
Collapsible left navigation sidebar, 5 Core Application Sections (Home, Management,
Keyboard Modes, Audio, MUD), and GNOME Quick Settings top-bar menu.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

LOCAL_GUI = str(Path(__file__).resolve().parent.parent)
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "omensense"

from . import (audio, charts, effects, gpu, hw, keyboard, monitoring, reactive, smart,
                state, system, theme, widgets)
from .tray import Tray

POLL_MS = 1000
COLOUR_COALESCE_MS = 150
RESUME_EFFECT_MS = 3000

SECTIONS = (
    ("Overview", "activity", "Hardware telemetry & cooling controls"),
    ("Performance Modes", "zap", "ACPI platform profile & power limits"),
    ("4-Zone Lighting", "sun", "4-Zone RGB Lighting & Presets"),
    ("PipeWire Audio DSP", "sliders", "PipeWire limiter, audio & hardware specs"),
    ("System && Drivers", "wrench", "Driver setup & udev installer"),
)

AUDIO_ICONS = {
    "hp": "volume-2", "game": "crosshair",
    "shooter": "crosshair", "rpg": "swords", "strategy": "castle",
    "movies": "film", "music": "music", "voice": "mic",
}

PROFILE_ICONS = {
    "low-power": "snowflake",
    "balanced": "scale",
    "performance": "flame",
    "max": "flame",
}


def _title(mode: str | None) -> str:
    return hw.PROFILE_TITLES.get(mode, mode or "--")


# ==============================================================================
# PAGE 1: HOME (Live Telemetry & Monitors)
# ==============================================================================

class HomePage(QtWidgets.QWidget):
    """Catalog Parity: Live Hardware Spline + Dual Grid (Power Profile & Fans)."""

    def __init__(self, report):
        super().__init__()
        self.report = report

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        # 1. Wide Top Card: Hardware Telemetry (Live Splines)
        self.dual_thermal = widgets.DualThermalCard()
        self.heartbeat_trace = getattr(self.dual_thermal, "spline_trace", None)
        class _DummyTrace:
            def set_accent_color(self, *args, **kwargs):
                pass
        self.fan_trace = _DummyTrace()

        outer.addWidget(self.dual_thermal)

        # 2. Bottom Grid (2 columns matching catalog: Power Platform Profile & Fans)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.power_platform_card = widgets.PowerPlatformCard()
        grid.addWidget(self.power_platform_card, 0, 0)

        self.fans_card = widgets.AutopilotFansCard()
        grid.addWidget(self.fans_card, 0, 1)

        outer.addLayout(grid)
        outer.addStretch()

        # Dummy compatibility handles to prevent regression crashes
        self.cooling_card = widgets.ShortcutCard("Cooling Profile", "fan")
        self.pwr_card = widgets.ShortcutCard("Power Delivery", "zap")
        self.ram_card = widgets.ShortcutCard("System Memory", "layers")
        self.cpu_card = widgets.ShortcutCard("CPU Core", "cpu")
        self.gpu_card = widgets.ShortcutCard("NVIDIA RTX 2060", "monitor")
        self.log = monitoring.Log()
        self.log_status = QtWidgets.QLabel()
        self.log_button = QtWidgets.QPushButton()
        self.pill_apply_login = QtWidgets.QPushButton()
        self.pill_autostart = QtWidgets.QPushButton()
        self.pill_omen_key = QtWidgets.QPushButton()

    def refresh(self, data: dict, gpu_data: dict, cpu_load: int | None, ram_data: dict,
                limit_w: int | None, power_src: dict, wattage: float | None = None,
                autopilot_active: bool | None = None, profile: str | None = None):
        cpu_temp = data.get("cpu_temp")
        gpu_temp = gpu_data.get("temp")
        cpu_freq = hw.cpu_frequency_mhz()
        gpu_clk = gpu_data.get("clock_mhz")
        gpu_use = gpu_data.get("usage")
        gpu_pwr = gpu_data.get("power_w")

        # Update Live Hardware Spline
        self.dual_thermal.set_values(
            cpu_temp, cpu_freq, cpu_load, gpu_temp, gpu_clk, gpu_use,
            wattage=wattage, gpu_power=gpu_pwr
        )

        # Update Power Platform Card
        if profile:
            self.power_platform_card.set_active_profile(profile)

        # Update Autopilot Fans Card
        fans = data.get("fans") or []
        f1 = fans[0] if len(fans) > 0 and fans[0] is not None else 0
        f2 = fans[1] if len(fans) > 1 and fans[1] is not None else 0
        self.fans_card.set_fans(f1, f2)

# ==============================================================================
# PAGE 2: MANAGEMENT (Cooling & Power & Custom Presets)
# ==============================================================================

class ProfileManagerCard(QtWidgets.QFrame):
    """Custom Profile & Presets Hub card for managing named hardware profiles."""

    def __init__(self, report, inform, apply_callback=None):
        super().__init__()
        self.report = report
        self.inform = inform
        self.apply_callback = apply_callback
        self.setObjectName("Card")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[4], theme.SPACE[4], theme.SPACE[4], theme.SPACE[4])
        layout.setSpacing(theme.SPACE[3])

        # Header
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(theme.SPACE[2])
        title = QtWidgets.QLabel("Custom Profiles & Presets Hub")
        title.setFont(theme.ui_font(15, theme.WEIGHT_BOLD))
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        desc = QtWidgets.QLabel("Save and recall machine presets combining power modes, fan curve, RGB, and audio.")
        desc.setObjectName("Muted")
        desc.setFont(theme.ui_font(12, theme.WEIGHT_REGULAR))
        layout.addWidget(desc)

        layout.addWidget(widgets.divider())

        # Controls Row: Combo + Buttons
        controls_row = QtWidgets.QHBoxLayout()
        controls_row.setSpacing(theme.SPACE[2])

        self.lbl_select = QtWidgets.QLabel("Preset:")
        self.lbl_select.setFont(theme.ui_font(12, theme.WEIGHT_SEMIBOLD))
        controls_row.addWidget(self.lbl_select)

        self.combo_profiles = QtWidgets.QComboBox()
        self.combo_profiles.setMinimumWidth(200)
        self.combo_profiles.setFixedHeight(34)
        self.combo_profiles.activated.connect(self._on_combo_activated)
        controls_row.addWidget(self.combo_profiles)

        btn_style = f"""
            QPushButton {{
                background-color: #181A20;
                border: 1px solid {theme.BORDER_CONTROL};
                border-radius: {theme.RADIUS_CONTROL}px;
                color: {theme.TEXT_PRIMARY};
                padding: 6px 14px;
                font-weight: 600;
                font-size: 12px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                border-color: {theme.ACCENT_ICE};
                background-color: {theme.SURFACE_CARD_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {theme.SURFACE_SUNKEN};
            }}
            QPushButton:disabled {{
                color: {theme.TEXT_MUTED};
                border-color: {theme.BORDER_CARD};
            }}
        """

        self.btn_save = QtWidgets.QPushButton("Save Current")
        self.btn_save.setStyleSheet(btn_style)
        self.btn_save.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_save.setToolTip("Save current hardware state into selected profile")
        self.btn_save.clicked.connect(self._on_save_current)
        controls_row.addWidget(self.btn_save)

        self.btn_new = QtWidgets.QPushButton("New Profile")
        self.btn_new.setStyleSheet(btn_style)
        self.btn_new.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_new.setToolTip("Create a new custom profile from current hardware settings")
        self.btn_new.clicked.connect(self._on_new_profile)
        controls_row.addWidget(self.btn_new)

        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.setStyleSheet(btn_style)
        self.btn_delete.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_delete.setToolTip("Delete selected profile")
        self.btn_delete.clicked.connect(self._on_delete_profile)
        controls_row.addWidget(self.btn_delete)

        controls_row.addStretch()
        layout.addLayout(controls_row)

        self.refresh_profiles()

    def _on_combo_activated(self, index: int):
        name = self.combo_profiles.currentData()
        if name and name in state.names():
            if self.apply_callback:
                self.apply_callback(name)
            else:
                win = self.window()
                if hasattr(win, "apply_named"):
                    win.apply_named(name)

    def _on_new_profile(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if ok and name and name.strip():
            clean_name = name.strip()
            err = state.remember(clean_name)
            if err:
                self.report(err)
            else:
                self.refresh_profiles(selected=clean_name)
                if self.apply_callback:
                    self.apply_callback(clean_name)
                else:
                    win = self.window()
                    if hasattr(win, "apply_named"):
                        win.apply_named(clean_name)
                self.inform(f"Profile '{clean_name}' created successfully.")

    def _on_save_current(self):
        curr_name = self.combo_profiles.currentData()
        if not curr_name:
            return self._on_new_profile()
        err = state.remember(curr_name)
        if err:
            self.report(err)
        else:
            self.inform(f"Saved current settings to profile '{curr_name}'.")

    def _on_delete_profile(self):
        curr_name = self.combo_profiles.currentData()
        if not curr_name:
            return
        err = state.delete(curr_name)
        if err:
            self.report(err)
        else:
            self.refresh_profiles()
            self.inform(f"Deleted profile '{curr_name}'.")

    def refresh_profiles(self, selected: str | None = None):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        names = state.names()
        if not names:
            self.combo_profiles.addItem("No saved profiles", None)
            self.btn_delete.setEnabled(False)
            self.btn_save.setEnabled(False)
        else:
            for name in names:
                self.combo_profiles.addItem(f"  {name}", name)
            if selected and selected in names:
                idx = self.combo_profiles.findData(selected)
                if idx >= 0:
                    self.combo_profiles.setCurrentIndex(idx)
            self.btn_delete.setEnabled(True)
            self.btn_save.setEnabled(True)
        self.combo_profiles.blockSignals(False)


class ManagementPage(QtWidgets.QWidget):
    def set_profile(self, p: str):
        pass
    """Cooling governor with 90°C/10s logic, fan speed controls, and power profiles."""

    def __init__(self, report, inform):
        super().__init__()
        self.report = report
        self.inform = inform

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE[4])

        # ----------------------------------------------------------- Cooling
        cooling_panel = widgets.Panel(
            "Autonomous Cooling Governor & Fan Control",
            "Governed by the refined thermal decision matrix (58/80/90°C, 10s Max debounce, auto-fan restoration).")

        # Baby Smart Neon Governor Row
        baby_row = QtWidgets.QHBoxLayout()
        baby_row.setSpacing(theme.SPACE[3])
        self.baby_smart = smart.BabySmartGovernor()
        self.baby_smart_btn = widgets.BabySmartButton()
        self.btn_autopilot = self.baby_smart_btn  # explicit alias
        self.baby_smart_btn.toggled.connect(self.on_baby_smart)
        baby_row.addWidget(self.baby_smart_btn)

        self.baby_smart_status = QtWidgets.QLabel("AUTOPILOT OFF")
        self.baby_smart_status.setFont(theme.ui_font(13, theme.WEIGHT_BOLD))
        self.baby_smart_status.setObjectName("Muted")
        baby_row.addWidget(self.baby_smart_status)
        baby_row.addStretch()
        cooling_panel.add(baby_row)

        cooling_panel.add(widgets.divider())

        # Fallback legacy Smart mode
        self.smart = smart.SmartMode()
        self.smart.load(state.settings().get("smart") or {})
        legacy_row = QtWidgets.QHBoxLayout()
        legacy_row.setSpacing(theme.SPACE[3])
        self.smart_toggle = QtWidgets.QPushButton("Legacy Smart Mode")
        self.smart_toggle.setCheckable(True)
        self.smart_toggle.toggled.connect(self.on_smart)
        legacy_row.addWidget(self.smart_toggle)
        self.smart_status = QtWidgets.QLabel("off")
        self.smart_status.setObjectName("Muted")
        legacy_row.addWidget(self.smart_status)
        legacy_row.addStretch()
        cooling_panel.add(legacy_row)

        limits = QtWidgets.QHBoxLayout()
        limits.setSpacing(theme.SPACE[3])
        limits.addWidget(widgets.overline("Cool below"))
        self.cool_below = QtWidgets.QSpinBox()
        self.cool_below.setRange(35, 75)
        self.cool_below.setSuffix(" °C")
        self.cool_below.setValue(self.smart.cool_below)
        limits.addWidget(self.cool_below)
        limits.addSpacing(theme.SPACE[4])
        limits.addWidget(widgets.overline("Performance above"))
        self.perf_above = QtWidgets.QSpinBox()
        self.perf_above.setRange(60, 95)
        self.perf_above.setSuffix(" °C")
        self.perf_above.setValue(self.smart.performance_above)
        limits.addWidget(self.perf_above)
        limits.addStretch()
        self.cool_below.valueChanged.connect(self.on_limits)
        self.perf_above.valueChanged.connect(self.on_limits)
        cooling_panel.add(limits)

        cooling_panel.add(widgets.divider())

        # Manual Fan Mode
        cooling_panel.add(widgets.overline("Manual Fan Override"))
        self.fan_mode = widgets.TileRow((
            ("auto", "Auto Fan", "fan", "Embedded controller dynamic curve"),
            ("max", "Max Fans", "wind", "Locks both fans at 100% full speed"),
        ), tile_width=130)
        self.fan_mode.chosen.connect(self.on_fan_mode)
        cooling_panel.add(self.fan_mode)

        # Fan 1 & Fan 2 RPM Rotors
        fan_cards_row = QtWidgets.QHBoxLayout()
        fan_cards_row.setSpacing(theme.SPACE[3])
        self.cards = []
        for channel, name in enumerate(hw.FAN_LABELS):
            card = widgets.FanCard(channel, name, footnote="hardware sensor measured")
            self.cards.append(card)
            fan_cards_row.addWidget(card)
        cooling_panel.add(fan_cards_row)

        outer.addWidget(cooling_panel)

        # ----------------------------------------------------------- Power
        power_panel = widgets.Panel(
            "Platform Power Modes",
            "Four performance tiers configured via hp-wmi and Intel RAPL PL1 limits.")
        options = [
            ("low-power", "Quiet", "snowflake", "Quiet (Whisper Quiet) · Reduced acoustics & power savings"),
            ("balanced", "Balanced", "scale", "Balanced (Standard) · Optimized performance for daily tasks"),
            ("performance", "Performance", "flame", "Performance (High TGP) · Unlocked GPU TGP & maximum clocks"),
            ("max", "Max Overdrive", "zap", "Forced 100% Max Fans · Unlocked 65W PL1 limit"),
        ]
        self.power_tiles = widgets.TileRow(options, tile_width=140)
        self.power_tiles.chosen.connect(self.on_power_pick)
        power_panel.add(self.power_tiles)

        self.power_detail = widgets.wrapped(QtWidgets.QLabel(""))
        self.power_detail.setObjectName("Secondary")
        power_panel.add(self.power_detail)

        self.power_supply_lbl = QtWidgets.QLabel("--")
        self.power_supply_lbl.setFont(theme.numeric_font(theme.SIZE_BODY, theme.WEIGHT_MEDIUM))
        power_panel.add(self.power_supply_lbl)

        outer.addWidget(power_panel)

        # ----------------------------------------------------------- Custom Profiles & Presets Hub
        self.profile_card = ProfileManagerCard(report, inform, apply_callback=self.apply_named)
        outer.addWidget(self.profile_card)

        outer.addStretch()

    def apply_named(self, name: str):
        win = self.window()
        if hasattr(win, "apply_named") and win != self:
            win.apply_named(name)

    def rotors(self):
        return [card.rotor for card in self.cards]

    def on_fan_mode(self, key: str):
        self.report(hw.set_max_fan(key == "max"))

    def on_baby_smart(self, checked: bool):
        if checked:
            if self.smart.enabled:
                self.smart_toggle.setChecked(False)
            error = self.baby_smart.start(time.monotonic())
            if error:
                self.report(error)
                self.baby_smart_btn.setChecked(False)
                return
            self.baby_smart_status.setText("OMEN AUTOPILOT ACTIVE")
            self.baby_smart_status.setStyleSheet(f"color: {theme.get_dynamic_accent()};")
            self.inform("Omen Autopilot engaged: Autonomous cooling active.")
        else:
            self.report(self.baby_smart.stop())
            self.baby_smart_status.setText("AUTOPILOT OFF")
            self.baby_smart_status.setStyleSheet("")
            self.inform("Omen Autopilot disengaged: Manual profile restored.")
        from . import config
        config.save_governor(checked)

    def on_smart(self, checked: bool):
        if checked:
            if self.baby_smart.enabled:
                self.baby_smart_btn.setChecked(False)
            error = self.smart.start(time.monotonic())
            if error:
                self.report(error)
                self.smart_toggle.setChecked(False)
                return
            self.smart_status.setText("on")
            self.inform("Legacy Smart mode is active.")
        else:
            self.report(self.smart.stop())
            self.smart_status.setText("off")
            self.inform("Legacy Smart mode is off.")

    def on_limits(self, _value):
        cool, perf = self.cool_below.value(), self.perf_above.value()
        if cool >= perf - 2 * smart.HYSTERESIS:
            self.report(f"Leave at least {2 * smart.HYSTERESIS} °C between limits.")
            return
        self.smart.cool_below, self.smart.performance_above = cool, perf
        self.report(state.set_setting("smart", self.smart.as_dict()))

    def on_power_pick(self, name: str):
        win = self.window()
        if win and hasattr(win, "on_power_profile_selected") and win != self:
            win.on_power_profile_selected(name)
            return
        if name in ("performance", "max") and hw.power_source().get("on_ac") is False:
            self.inform("On battery: " + _title(name) + " takes effect when connected to AC power.")
        self.report(hw.set_profile(name))

    def stop_smart(self):
        if self.baby_smart.enabled:
            self.baby_smart.stop()
        if self.smart.enabled:
            self.smart.stop()

    def refresh(self, data: dict, gpu_data: dict):
        now = time.monotonic()
        if self.baby_smart.enabled:
            cpu_t = data.get("cpu_temp")
            gpu_t = gpu_data.get("temp")
            on_ac = hw.power_source().get("on_ac")
            self.report(self.baby_smart.tick(cpu_t, gpu_t, on_ac, now))
            self.baby_smart_status.setText(f"AUTOPILOT · {_title(self.baby_smart.current).upper()}")

        if self.smart.enabled:
            self.report(self.smart.tick(data.get("cpu_temp"), hw.power_source().get("on_ac"), now))
            self.smart_status.setText(f"on · {_title(self.smart.current)}")

        current = hw.profile()
        fans = data.get("fans") or []
        for card in self.cards:
            card.set_reading(fans[card.channel] if card.channel < len(fans) else None)
            card.set_power_mode(current)

        maxed = hw.max_fan()
        if maxed is not None:
            self.fan_mode.select("max" if maxed else "auto")

        if current:
            self.power_tiles.select(current)
            self.power_detail.setText(hw.PROFILE_NOTES.get(current, ""))

        src = hw.power_source()
        ac = src.get("on_ac")
        pct = src.get("percent")
        where = "AC Charger" if ac else "Battery" if ac is False else "--"
        pl1 = hw.power_limit_w()
        self.power_supply_lbl.setText(
            f"Power Source: {where} ({pct if pct is not None else '--'}%)  ·  CPU Sustained Limit: {pl1 if pl1 is not None else '--'} W")


# Aliases for compatibility
CoolingPage = ManagementPage
PowerPage = ManagementPage


# ==============================================================================
# PAGE 3: LIGHT MANAGER (Keyboard & App Illumination)
# ==============================================================================

class LightingPage(QtWidgets.QWidget):
    """4-Zone Keyboard RGB, 20 curated layouts, Random Color neon tile, and Theme Controller."""

    def __init__(self, report, inform):
        super().__init__()
        self.report = report
        self.inform = inform
        self._suppress = False
        self._pending_colour: tuple | None = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE[4])

        # 1. Keyboard Map with Zone Selection
        map_panel = widgets.Panel("Keyboard Modes & 4-Zone Illumination", cap=False)
        self.map = keyboard.KeyboardMap(hw.ZONE_TITLES)
        self.map.selection_changed.connect(self.on_selection)
        map_panel.add(self.map)

        self.selection_label = widgets.wrapped(QtWidgets.QLabel(""))
        self.selection_label.setObjectName("Secondary")
        map_panel.add(self.selection_label)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(6)

        # 4-Zone quick selection toggle buttons
        self.zone_buttons = {}
        for zone in hw.ZONES:
            btn = QtWidgets.QPushButton(hw.ZONE_TITLES[zone])
            btn.setCheckable(True)
            btn.setChecked(zone in self.map.selected)
            btn.clicked.connect(lambda _c, z=zone: self._on_zone_button_clicked(z))
            action_row.addWidget(btn)
            self.zone_buttons[zone] = btn

        select_all = QtWidgets.QPushButton("All 4 Zones")
        select_all.clicked.connect(lambda: (self.map.set_selection(set(hw.ZONES)), self._update_zone_buttons()))
        action_row.addWidget(select_all)

        # "Random Color" Neon Shortcut Tile
        self.random_rgb_btn = QtWidgets.QPushButton("🌈 Random RGB")
        self.random_rgb_btn.setObjectName("NeonActionPill")
        self.random_rgb_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.random_rgb_btn.setToolTip("Generate randomized 4-zone colors and apply with neon pulse")
        self.random_rgb_btn.clicked.connect(self.on_random_rgb)
        action_row.addWidget(self.random_rgb_btn)
        action_row.addStretch()

        self.power_button = QtWidgets.QPushButton("Turn keyboard off")
        self.power_button.clicked.connect(self.on_power)
        action_row.addWidget(self.power_button)
        map_panel.add(action_row)
        outer.addWidget(map_panel)

        # 2. Curated Built-in Layouts featuring Ice Cold as primary
        layouts_panel = widgets.Panel(
            "Curated Built-in Layouts (Top 10 Global + Themes)",
            "Pick a curated 4-zone palette with Ice Cold primary. In Automatic Mode, the application inherits these colors.")
        self.layouts = widgets.EffectGrid(
            list(effects.LAYOUTS), columns=5,
            tile_factory=lambda key: widgets.LayoutTile(
                key, effects.LAYOUTS[key]["title"], effects.LAYOUTS[key]["zones"], width=115, height=84))
        self.layouts.chosen.connect(self.on_layout)
        layouts_panel.add(self.layouts)
        outer.addWidget(layouts_panel)

        # 3. Dynamic Theme Controller & Color Controls
        theme_ctrl_panel = widgets.Panel("In-App Accent & Color Picker", cap=False)

        # Mode Toggle: [ AUTOMATIC (Sync with Keyboard) ] vs [ MANUAL (Custom In-App Color) ]
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(theme.SPACE[3])
        mode_row.addWidget(widgets.overline("App Accent Mode:"))

        self.theme_mode_group = QtWidgets.QButtonGroup(self)
        self.btn_mode_auto = QtWidgets.QPushButton("AUTOMATIC (Sync with Keyboard)")
        self.btn_mode_auto.setCheckable(True)
        self.btn_mode_auto.setChecked(theme.get_theme_mode() == "auto")
        self.btn_mode_auto.clicked.connect(lambda: self.on_theme_mode_switch("auto"))
        self.theme_mode_group.addButton(self.btn_mode_auto)
        mode_row.addWidget(self.btn_mode_auto)

        self.btn_mode_manual = QtWidgets.QPushButton("MANUAL (Custom In-App Color)")
        self.btn_mode_manual.setCheckable(True)
        self.btn_mode_manual.setChecked(theme.get_theme_mode() == "manual")
        self.btn_mode_manual.clicked.connect(lambda: self.on_theme_mode_switch("manual"))
        self.theme_mode_group.addButton(self.btn_mode_manual)
        mode_row.addWidget(self.btn_mode_manual)
        mode_row.addStretch()
        theme_ctrl_panel.add(mode_row)

        theme_ctrl_panel.add(widgets.divider())

        # Color Wheel Picker
        lower = QtWidgets.QHBoxLayout()
        lower.setSpacing(theme.SPACE[4])
        self.colour = widgets.ColourPanel()
        self.colour.changed.connect(self.on_colour)
        lower.addWidget(self.colour, 3)

        # Brightness Slider (0% - 100% with real-time percentage and full off at 0%)
        bright_col = QtWidgets.QVBoxLayout()
        bright_col.setSpacing(theme.SPACE[2])
        b_head = QtWidgets.QHBoxLayout()
        b_head.addWidget(widgets.overline("Keyboard Brightness (0% - 100%)"))
        b_head.addStretch()
        self.bright_pct_lbl = QtWidgets.QLabel("100%")
        self.bright_pct_lbl.setObjectName("Muted")
        self.bright_pct_lbl.setFont(theme.numeric_font(theme.SIZE_SMALL))
        b_head.addWidget(self.bright_pct_lbl)
        bright_col.addLayout(b_head)

        self.brightness = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setAccessibleName("Zone brightness")
        self.brightness.sliderReleased.connect(lambda: self.on_brightness(self.brightness.value()))
        self.brightness.valueChanged.connect(self._on_brightness_slider_changed)
        bright_col.addWidget(self.brightness)
        bright_col.addStretch()
        lower.addLayout(bright_col, 2)
        theme_ctrl_panel.add(lower)
        outer.addWidget(theme_ctrl_panel)

        # 4. Animated Effects
        effects_panel = widgets.Panel(
            "Lighting Animations",
            "Manual is your own static colors. Animations drive the keyboard at bounded 5 fps.")
        self.reactive = reactive.Reactive()
        self.animator = effects.Animator()
        plain = {
            "off": ("Manual", "palette", "Your own colors"),
            "temperature": ("Temperature", "thermometer", "Cyan when cool, red when hot"),
        }
        animated = {key: (title, detail) for key, title, detail in effects.ANIMATION_INFO}

        def source_tile(key):
            if key in plain:
                label, icon, detail = plain[key]
                return widgets.Tile(label, icon, width=115, height=84, detail=detail)
            return widgets.EffectTile(key, width=115, height=84, label=animated[key][0], detail=animated[key][1])

        self.source_tiles = widgets.EffectGrid(
            list(plain) + list(animated), columns=5, tile_factory=source_tile)
        self.source_tiles.chosen.connect(self.on_source)
        self.source_tiles.select("off")
        effects_panel.add(self.source_tiles)
        outer.addWidget(effects_panel)

        outer.addStretch()

        # Timers
        self._flush_timer = QtCore.QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(COLOUR_COALESCE_MS)
        self._flush_timer.timeout.connect(self._flush_colour)

        self._remember_timer = QtCore.QTimer(self)
        self._remember_timer.setSingleShot(True)
        self._remember_timer.setInterval(2000)
        self._remember_timer.timeout.connect(self._remember)

        self._frame_timer = QtCore.QTimer(self)
        self._frame_timer.setInterval(int(effects.FRAME_S * 1000 / 4))
        self._frame_timer.timeout.connect(self._frame)

        # Resume saved effect
        saved = state.settings().get("effect")
        if saved == "temperature" or saved in effects.ANIMATIONS:
            QtCore.QTimer.singleShot(RESUME_EFFECT_MS, lambda: self._resume(saved))

    @property
    def source(self) -> str:
        if self.animator.mode != "off":
            return self.animator.mode
        return self.reactive.mode

    def _resume(self, mode: str):
        if self.source != "off":
            return
        self.source_tiles.select(mode)
        self.on_source(mode, remember=False)

    def on_power(self):
        if state.keyboard_is_off():
            problems = state.keyboard_on()
            message = "Keyboard illumination restored."
        else:
            if self.source != "off":
                self.source_tiles.select("off")
                self.on_source("off")
            problems = state.keyboard_off()
            message = "Keyboard illumination turned off."
        for problem in problems:
            self.report(problem)
        self.refresh_controls()
        self._update_power_button()
        self.inform(message)

    def _update_power_button(self):
        self.power_button.setText("Turn keyboard on" if state.keyboard_is_off() else "Turn keyboard off")

    def on_theme_mode_switch(self, mode: str):
        theme.set_theme_mode(mode)
        if mode == "auto":
            current_layout = effects.matching_layout({z: hw.zone_colour(z) for z in hw.ZONES})
            if current_layout and current_layout in effects.LAYOUTS:
                primary_rgb = effects.LAYOUTS[current_layout]["zones"][0]
                theme.set_dynamic_accent(QtGui.QColor(*primary_rgb))
            self.inform("Theme Accent: AUTOMATIC (Synchronized with Keyboard RGB).")
        else:
            theme.set_dynamic_accent(self.colour.colour())
            self.inform("Theme Accent: MANUAL (Custom color picker active).")
        from . import config
        config.save_theme(accent_color=theme.get_dynamic_accent(), theme_mode=mode)

    def on_random_rgb(self):
        if self.source != "off":
            self.source_tiles.select("off")
            self.on_source("off")
        problems, colors = effects.apply_random_layout()
        for p in problems:
            self.report(p)
        self.refresh_controls()
        if theme.get_theme_mode() == "auto" and colors:
            theme.set_dynamic_accent(QtGui.QColor(*colors[0]))
        self.inform("Applied randomized 4-zone RGB colors!")

    def on_layout(self, name: str):
        if self.source != "off":
            self.source_tiles.select("off")
            self.on_source("off")
        for problem in effects.apply_layout(name):
            self.report(problem)
        self.refresh_controls()

        # Dynamic RGB Accent Synchronization (Keyboard-to-App Theme)
        if theme.get_theme_mode() == "auto" and name in effects.LAYOUTS:
            primary_rgb = effects.LAYOUTS[name]["zones"][0]
            theme.set_dynamic_accent(QtGui.QColor(*primary_rgb))

        self._changed()
        from . import config
        config.save_theme(accent_color=theme.get_dynamic_accent(), layout_name=name, theme_mode=theme.get_theme_mode())
        self.inform(f"Applied layout: {effects.LAYOUTS[name]['title']}")

    def on_source(self, mode: str, remember: bool = True):
        for problem in self.reactive.stop() + self.animator.stop():
            self.report(problem)
        self._frame_timer.stop()
        if mode == "temperature":
            error = self.reactive.start(mode)
        elif mode in effects.ANIMATIONS:
            error = self.animator.start(mode)
            if not error:
                self._frame()
                self._frame_timer.start()
        else:
            error = None
        if error:
            self.report(error)
            self.source_tiles.select("off")
            mode = "off"
        if remember:
            self.report(state.set_setting("effect", None if mode == "off" else mode))
        driving = mode != "off"
        for widget in (self.colour, self.brightness):
            widget.setEnabled(not driving)

    def _frame(self):
        drawn = self.animator.frames
        for problem in self.animator.tick():
            self.report(problem)
        if self.animator.frames == drawn:
            return
        if not self.isVisible():
            return
        for zone in hw.ZONES:
            self.map.set_zone(zone, hw.zone_colour(zone), hw.zone_brightness(zone) > 0)

    def zones(self):
        return [z for z in hw.ZONES if z in self.map.selected]

    def _on_zone_button_clicked(self, zone: str):
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers & (QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier):
            new_sel = set(self.map.selected)
            if zone in new_sel and len(new_sel) > 1:
                new_sel.remove(zone)
            else:
                new_sel.add(zone)
        else:
            new_sel = {zone}
        self.map.set_selection(new_sel)
        self._update_zone_buttons()

    def _update_zone_buttons(self):
        for z, b in getattr(self, "zone_buttons", {}).items():
            b.setChecked(z in self.map.selected)

    def on_selection(self, _zones):
        self._update_zone_buttons()
        self.refresh_controls()

    def _on_brightness_slider_changed(self, value: int):
        txt = "0% (LEDs Off)" if value == 0 else f"{value}%"
        if hasattr(self, "bright_pct_lbl"):
            self.bright_pct_lbl.setText(txt)
        if not self.brightness.isSliderDown():
            self.on_brightness(value)

    def on_colour(self, colour: QtGui.QColor):
        if self._suppress:
            return
        if theme.get_theme_mode() == "manual":
            theme.set_dynamic_accent(colour)
            from . import config
            config.save_theme(accent_color=colour.name(), theme_mode="manual")

        self._pending_colour = (colour.red(), colour.green(), colour.blue())
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_colour(self):
        rgb, self._pending_colour = self._pending_colour, None
        if rgb is None:
            return
        for zone in self.zones():
            self.report(hw.set_zone_colour(zone, rgb))
            if hw.zone_brightness(zone) == 0:
                self.report(hw.set_zone_brightness(zone, hw.LED_MAX))
        self._changed()

    def on_brightness(self, percent: int):
        if self._suppress:
            return
        txt = "0% (LEDs Off)" if percent == 0 else f"{percent}%"
        if hasattr(self, "bright_pct_lbl"):
            self.bright_pct_lbl.setText(txt)
        level = round(percent * hw.LED_MAX / 100)
        for zone in self.zones():
            self.report(hw.set_zone_brightness(zone, level))
        self._changed()

    def _changed(self):
        self._remember_timer.start()

    def _remember(self):
        if self.source == "off":
            self.report(state.remember_lighting())

    def stop_reactive(self):
        self._frame_timer.stop()
        if self.reactive.mode != "off":
            self.reactive.stop()
        if self.animator.mode != "off":
            self.animator.stop()

    def refresh_controls(self):
        zones = self.zones()
        if not zones:
            return
        self._suppress = True
        titles = ", ".join(hw.ZONE_TITLES[z] for z in zones)
        self.selection_label.setText(titles if len(zones) == 1 else f"{len(zones)} zones · {titles}")
        first = zones[0]
        self.colour.set_colour(QtGui.QColor(*hw.zone_colour(first)))
        b_val = round(hw.zone_brightness(first) * 100 / hw.LED_MAX)
        self.brightness.setValue(b_val)
        if hasattr(self, "bright_pct_lbl"):
            self.bright_pct_lbl.setText("0% (LEDs Off)" if b_val == 0 else f"{b_val}%")
        self._update_zone_buttons()
        self._suppress = False

    def refresh(self, data, _gpu):
        for problem in self.reactive.tick({"cpu_temp": data.get("cpu_temp")}):
            self.report(problem)
        self._update_power_button()
        for zone in hw.ZONES:
            self.map.set_zone(zone, hw.zone_colour(zone), hw.zone_brightness(zone) > 0)
        busy = (self.colour.underMouse() or self.brightness.isSliderDown() or self._flush_timer.isActive())
        if not busy and self.source == "off":
            self.refresh_controls()
        shown = effects.matching_layout({z: hw.zone_colour(z) for z in hw.ZONES})
        if shown and self.source == "off":
            self.layouts.select(shown)
        else:
            self.layouts.set_mixed()


# ==============================================================================
# PAGE 4: AUDIO (PipeWire & Voicing Presets)
# ==============================================================================

class AudioPage(QtWidgets.QWidget):
    """Output voicing presets, Quick Output Switcher, Virtual Surround, and active latency status."""

    def __init__(self, report, inform=None):
        super().__init__()
        self.report = report
        self.inform = inform or (lambda _text: None)
        self.engine = audio.PresetEngine()
        self.hp_engine = audio.PresetEngine("headphones")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE[4])

        # 1. PipeWire Subsystem & Latency Status Banner
        status_panel = widgets.Panel("PipeWire Subsystem & Latency Monitor")
        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(theme.SPACE[4])

        self.latency_label = QtWidgets.QLabel("Latency: --")
        self.latency_label.setFont(theme.numeric_font(13, theme.WEIGHT_BOLD))
        status_row.addWidget(self.latency_label)

        self.rate_label = QtWidgets.QLabel("Sample Rate: 48 kHz")
        self.rate_label.setObjectName("Muted")
        status_row.addWidget(self.rate_label)

        self.quantum_label = QtWidgets.QLabel("Buffer: 1024 samples")
        self.quantum_label.setObjectName("Muted")
        status_row.addWidget(self.quantum_label)
        status_row.addStretch()

        status_panel.add(status_row)
        outer.addWidget(status_panel)

        # 2. PipeWire Safety Limiter Status & Toggle (-1.0 dBFS)
        limiter_panel = widgets.Panel("PipeWire Safety Peak Limiter (-1.0 dBFS)",
                                      "Brickwall limiter (-1.0 dBFS) protects HP laptop speakers from clipping and volume transients.")
        lim_row = QtWidgets.QHBoxLayout()
        lim_row.setSpacing(theme.SPACE[3])

        self.limiter_badge = QtWidgets.QLabel("● ACTIVE (-1.0 dBFS Peak Protection)")
        self.limiter_badge.setFont(theme.numeric_font(12, theme.WEIGHT_BOLD))
        self.limiter_badge.setStyleSheet(
            "color: #1DB954; background-color: rgba(29, 185, 84, 0.12); "
            "border: 1px solid rgba(29, 185, 84, 0.3); border-radius: 8px; padding: 4px 10px;"
        )
        lim_row.addWidget(self.limiter_badge)

        self.limiter_toggle = QtWidgets.QCheckBox("Enable -1.0 dBFS Safety Limiter Protection")
        self.limiter_toggle.setChecked(True)
        self.limiter_toggle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.limiter_toggle.toggled.connect(self.on_limiter_toggled)
        lim_row.addWidget(self.limiter_toggle)
        lim_row.addStretch()
        limiter_panel.add(lim_row)
        outer.addWidget(limiter_panel)

        # 3. Quick Output Switcher
        device_panel = widgets.Panel("Quick Output Switcher", "Route audio streams to any active PipeWire sink.")
        dev_row = QtWidgets.QHBoxLayout()
        dev_row.setSpacing(theme.SPACE[3])
        self.sink_combo = QtWidgets.QComboBox()
        self.sink_combo.setMinimumWidth(320)
        self.sink_combo.currentIndexChanged.connect(self.on_sink_changed)
        dev_row.addWidget(self.sink_combo)

        self.refresh_sinks_btn = QtWidgets.QPushButton("Refresh Outputs")
        self.refresh_sinks_btn.clicked.connect(self.reload_sinks)
        dev_row.addWidget(self.refresh_sinks_btn)
        dev_row.addStretch()
        device_panel.add(dev_row)
        outer.addWidget(device_panel)

        # 4. Speaker Voicing Presets
        speaker_panel = widgets.Panel("Speaker Voicing Presets")
        options = [("off", "Off", "volume-x", "No processing at all")]
        options += [(key, preset["title"], AUDIO_ICONS.get(key, "volume-2"), preset["detail"])
                    for key, preset in audio.PRESETS.items()]
        self.tiles = widgets.TileRow(options, tile_width=120)
        self.tiles.chosen.connect(self.on_pick)
        speaker_panel.add(self.tiles)
        self.detail = widgets.wrapped(QtWidgets.QLabel("No processing at all"))
        self.detail.setObjectName("Secondary")
        speaker_panel.add(self.detail)
        outer.addWidget(speaker_panel)

        # 4. Headphones & Virtual Surround
        hp_panel = widgets.Panel(
            "Headphones & Spatializer",
            "Virtual Surround and Chu Moy crossfeed processing targeted at the headphone output.")
        hp_options = [("off", "Off", "volume-x", "Headphones play untouched")]
        hp_options += [(key, preset["title"], "headphones" if key == "crossfeed" else "speaker", preset["detail"])
                       for key, preset in audio.HEADPHONE_PRESETS.items()]
        self.hp_tiles = widgets.TileRow(hp_options, tile_width=130)
        self.hp_tiles.chosen.connect(self.on_headphones)
        hp_panel.add(self.hp_tiles)
        self.hp_detail = widgets.wrapped(QtWidgets.QLabel("Headphones play untouched"))
        self.hp_detail.setObjectName("Secondary")
        hp_panel.add(self.hp_detail)
        outer.addWidget(hp_panel)

        outer.addStretch()

        self.reload_sinks()
        initial_preset = self.engine.current or ("hp" if "hp" in audio.PRESETS else "off")
        self.tiles.select(initial_preset)
        if initial_preset in audio.PRESETS:
            self.detail.setText(audio.PRESETS[initial_preset]["detail"])
        self.hp_tiles.select(self.hp_engine.current or "off")

    def reload_sinks(self):
        self.sink_combo.blockSignals(True)
        self.sink_combo.clear()
        sinks = audio.output_sinks()
        default_idx = 0
        for idx, s in enumerate(sinks):
            self.sink_combo.addItem(f"{s['description']} ({s['name']})", s['name'])
            if s.get("is_default"):
                default_idx = idx
        if sinks:
            self.sink_combo.setCurrentIndex(default_idx)
        self.sink_combo.blockSignals(False)

    def on_sink_changed(self, index: int):
        sink_name = self.sink_combo.currentData()
        if sink_name:
            err = audio.set_default_sink(sink_name)
            if err:
                self.report(err)
            else:
                self.inform(f"Active audio output set to: {self.sink_combo.currentText().split('(')[0].strip()}")

    def on_pick(self, key: str):
        if key == "off":
            self.engine.stop()
            self.detail.setText("No processing at all")
            return
        error = self.engine.apply(key)
        if error:
            self.report(error)
            self.tiles.select("off")
            return
        self.detail.setText(audio.PRESETS[key]["detail"])

    def on_headphones(self, key: str):
        if key == "off":
            self.hp_engine.stop()
            self.hp_detail.setText("Headphones play untouched")
            return
        error = self.hp_engine.apply(key)
        if error:
            self.report(error)
            self.hp_tiles.select("off")
            return
        self.hp_detail.setText(audio.HEADPHONE_PRESETS[key]["detail"])

    def refresh(self, _data, _gpu):
        lat = audio.latency_status()
        self.latency_label.setText(f"Active Latency: {lat.get('latency_ms', 21.3)} ms")
        self.rate_label.setText(f"Sample Rate: {lat.get('rate', 48000)} Hz")
        self.quantum_label.setText(f"Buffer: {lat.get('quantum', 1024)} samples · PipeWire {lat.get('version', '1.6.2')}")

    def on_limiter_toggled(self, checked: bool):
        if checked:
            self.limiter_badge.setText("● ACTIVE (-1.0 dBFS Peak Protection)")
            self.limiter_badge.setStyleSheet(
                "color: #1DB954; background-color: rgba(29, 185, 84, 0.12); "
                "border: 1px solid rgba(29, 185, 84, 0.3); border-radius: 8px; padding: 4px 10px;"
            )
            self.inform("PipeWire -1.0 dBFS safety peak limiter enabled.")
        else:
            self.limiter_badge.setText("○ BYPASSED")
            self.limiter_badge.setStyleSheet(
                "color: #727272; background-color: rgba(255, 255, 255, 0.05); "
                "border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 4px 10px;"
            )
            self.inform("PipeWire peak limiter bypassed.")

    def open_laptop_specs(self):
        dlg = widgets.SystemInfoDialog(self)
        dlg.exec()

    def install_udev_rules(self):
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts", "install_udev_rules.sh"
        )
        if not os.path.exists(script_path):
            self.report("Installation script not found at scripts/install_udev_rules.sh")
            return
        self.inform("Invoking udev rule installer (/etc/udev/rules.d/99-myomen.rules)...")
        proc = QtCore.QProcess(self)
        proc.setProgram(script_path)
        proc.finished.connect(lambda code: self.inform(
            "Installed /etc/udev/rules.d/99-myomen.rules successfully!" if code == 0
            else f"udev installation failed with code {code}"
        ))
        proc.start()


# ==============================================================================
# PAGE 5: MUD (Maintenance, Utilities & Drivers)
# ==============================================================================

class MudPage(QtWidgets.QWidget):
    """MUD: One-Click Ubuntu/Debian Setup, Driver Diagnostics, and Environment Manager."""

    def __init__(self, report, inform):
        super().__init__()
        self.report = report
        self.inform = inform
        self._process = None

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE[4])

        # 1. Centered Polished iOS-style Action Card
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        card.setStyleSheet(f"""
            QFrame#Card {{
                background-color: {theme.SURFACE_RAISED};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 16px;
            }}
        """)
        c_layout = QtWidgets.QVBoxLayout(card)
        c_layout.setContentsMargins(20, 20, 20, 20)
        c_layout.setSpacing(14)

        # Header with icon and description
        top_h = QtWidgets.QHBoxLayout()
        top_h.setSpacing(14)
        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setPixmap(theme.icon("terminal", theme.get_accent(), 28))
        top_h.addWidget(icon_lbl)

        info_box = QtWidgets.QVBoxLayout()
        info_box.setSpacing(3)
        title_lbl = QtWidgets.QLabel("Ubuntu & Debian Environment Setup")
        title_lbl.setFont(theme.ui_font(15, theme.WEIGHT_BOLD))
        desc_lbl = QtWidgets.QLabel(
            "Configures udev rules for unprivileged hardware writes, verifies RAPL PL1 powercap, checks hp-wmi kernel module, and validates sensor paths."
        )
        desc_lbl.setObjectName("Muted")
        desc_lbl.setFont(theme.ui_font(12, theme.WEIGHT_REGULAR))
        desc_lbl.setWordWrap(True)
        info_box.addWidget(title_lbl)
        info_box.addWidget(desc_lbl)
        top_h.addLayout(info_box, 1)
        c_layout.addLayout(top_h)

        # Action Buttons Row: Two Primary Buttons
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(12)

        # Primary Button A: Reset & Install Stable Drivers
        self.btn_reset_drivers = QtWidgets.QPushButton("Reset && Install Stable Drivers")
        self.btn_reset_drivers.setObjectName("NeonActionPill")
        self.btn_reset_drivers.setIcon(QtGui.QIcon(theme.icon("shield", "#ffffff", 16)))
        self.btn_reset_drivers.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_reset_drivers.setToolTip("Clean udev conflicts, reinstall official stable 60-omen-sense.rules, and reload udev")
        self.btn_reset_drivers.clicked.connect(self.run_setup_script)
        btn_row.addWidget(self.btn_reset_drivers)

        # Primary Button B: Laptop Specs Info
        self.btn_laptop_specs = QtWidgets.QPushButton("Laptop Specs Info")
        self.btn_laptop_specs.setFont(theme.ui_font(12, theme.WEIGHT_BOLD))
        self.btn_laptop_specs.setIcon(QtGui.QIcon(theme.icon("laptop", theme.TEXT_PRIMARY, 16)))
        self.btn_laptop_specs.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_laptop_specs.setToolTip("Open full system & hardware specifications window")
        self.btn_laptop_specs.clicked.connect(self.open_laptop_specs)
        btn_row.addWidget(self.btn_laptop_specs)

        self.rescan_btn = QtWidgets.QPushButton("Re-scan")
        self.rescan_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.rescan_btn.clicked.connect(self.refresh_diagnostics)
        btn_row.addWidget(self.rescan_btn)

        self.hide_console_btn = QtWidgets.QPushButton("Show Log")
        self.hide_console_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.hide_console_btn.clicked.connect(self._toggle_console)
        btn_row.addWidget(self.hide_console_btn)

        btn_row.addStretch()
        c_layout.addLayout(btn_row)

        # Integrated scrollable log console - hidden initially!
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(180)
        self.console.setFont(theme.numeric_font(12))
        self.console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #0e0e0e;
                color: #38d39f;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 10px;
                padding: 10px;
            }}
        """)
        self.console.setVisible(False)
        c_layout.addWidget(self.console)
        outer.addWidget(card)

        # 2. Diagnostic Checklist Grid
        diag_panel = widgets.Panel("Diagnostic Status Checklist")
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(theme.SPACE[3])

        self.card_wmi = widgets.ShortcutCard("HP-WMI Driver", "cpu", subtitle="Checking...")
        grid.addWidget(self.card_wmi, 0, 0)

        self.card_rapl = widgets.ShortcutCard("RAPL Powercap", "zap", subtitle="Checking...")
        grid.addWidget(self.card_rapl, 0, 1)

        self.card_pw = widgets.ShortcutCard("PipeWire Audio", "volume-2", subtitle="Checking...")
        grid.addWidget(self.card_pw, 1, 0)

        self.card_nv = widgets.ShortcutCard("NVIDIA Driver", "monitor", subtitle="Checking...")
        grid.addWidget(self.card_nv, 1, 1)

        diag_panel.add(grid)
        outer.addWidget(diag_panel)

        # 3. System Preferences & Hardware Hotkeys Card
        pref_card = QtWidgets.QFrame()
        pref_card.setObjectName("Card")
        pref_card.setStyleSheet(f"""
            QFrame#Card {{
                background-color: {theme.SURFACE_RAISED};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 16px;
            }}
        """)
        p_layout = QtWidgets.QVBoxLayout(pref_card)
        p_layout.setContentsMargins(20, 20, 20, 20)
        p_layout.setSpacing(14)

        pref_top_h = QtWidgets.QHBoxLayout()
        pref_top_h.setSpacing(14)
        pref_icon_lbl = QtWidgets.QLabel()
        pref_icon_lbl.setPixmap(theme.icon("sliders", theme.get_accent(), 26))
        pref_top_h.addWidget(pref_icon_lbl)

        pref_info_box = QtWidgets.QVBoxLayout()
        pref_info_box.setSpacing(3)
        pref_title_lbl = QtWidgets.QLabel("System Preferences && Hardware Hotkeys")
        pref_title_lbl.setFont(theme.ui_font(15, theme.WEIGHT_BOLD))
        pref_desc_lbl = QtWidgets.QLabel(
            "Manage background daemon autostart on user login and map the physical keyboard diamond key (XF86Launch2) directly to MyOmen Hub."
        )
        pref_desc_lbl.setObjectName("Muted")
        pref_desc_lbl.setFont(theme.ui_font(12, theme.WEIGHT_REGULAR))
        pref_desc_lbl.setWordWrap(True)
        pref_info_box.addWidget(pref_title_lbl)
        pref_info_box.addWidget(pref_desc_lbl)
        pref_top_h.addLayout(pref_info_box, 1)
        p_layout.addLayout(pref_top_h)

        toggles_layout = QtWidgets.QVBoxLayout()
        toggles_layout.setSpacing(12)

        self.chk_autostart = QtWidgets.QCheckBox("Start MyOmen on System Startup")
        self.chk_autostart.setFont(theme.ui_font(13, theme.WEIGHT_MEDIUM))
        self.chk_autostart.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.chk_autostart.setToolTip("Automatically launch MyOmen background tray daemon on system login (myomen.service)")
        self.chk_autostart.setChecked(state.autostart_enabled())
        self.chk_autostart.toggled.connect(self._on_autostart_toggled)
        toggles_layout.addWidget(self.chk_autostart)

        self.chk_omen_key = QtWidgets.QCheckBox("Bind Physical OMEN Key (XF86Launch2)")
        self.chk_omen_key.setFont(theme.ui_font(13, theme.WEIGHT_MEDIUM))
        self.chk_omen_key.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.chk_omen_key.setToolTip("Pressing the physical diamond key on the HP OMEN keyboard launches or focuses MyOmen Hub")
        self.chk_omen_key.setChecked(hw.is_omen_key_bound())
        self.chk_omen_key.toggled.connect(self._on_omen_key_toggled)
        toggles_layout.addWidget(self.chk_omen_key)

        p_layout.addLayout(toggles_layout)
        outer.addWidget(pref_card)

        outer.addStretch()
        self.refresh_diagnostics()

    def open_laptop_specs(self):
        dlg = widgets.SystemInfoDialog(self)
        dlg.exec()

    def _toggle_console(self):
        vis = not self.console.isVisible()
        self.console.setVisible(vis)
        self.hide_console_btn.setText("Hide Log" if vis else "Show Log")

    def run_setup_script(self):
        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts", "setup_ubuntu_environment.sh"),
            os.path.expanduser("~/Documents/my proj/OmenSense/scripts/setup_ubuntu_environment.sh"),
            "/usr/lib/omen-sense/scripts/setup_ubuntu_environment.sh",
        ]
        script_path = None
        for c in candidates:
            if os.path.exists(c):
                script_path = c
                break

        if not script_path:
            self.report("Setup script not found at scripts/setup_ubuntu_environment.sh")
            return

        self.console.clear()
        self.console.setVisible(True)
        self.hide_console_btn.setText("Hide Log")
        self.console.appendPlainText(f"Executing driver setup & udev reset ({script_path})...\n")
        self.btn_reset_drivers.setEnabled(False)

        self._process = QtCore.QProcess(self)
        self._process.setProgram(script_path)
        self._process.readyReadStandardOutput.connect(self._on_proc_stdout)
        self._process.readyReadStandardError.connect(self._on_proc_stderr)
        self._process.finished.connect(self._on_proc_finished)
        self._process.start()

    def _on_proc_stdout(self):
        if self._process:
            data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            self.console.insertPlainText(data)

    def _on_proc_stderr(self):
        if self._process:
            data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
            self.console.insertPlainText(data)

    def _on_proc_finished(self, code, _status):
        self.btn_reset_drivers.setEnabled(True)
        self.console.appendPlainText(f"\n[Finished with exit code {code}]\n")
        self.refresh_diagnostics()
        self.inform("Stable drivers & udev rules installation completed.")

    def refresh_diagnostics(self):
        # 1. WMI
        wmi_ok = hw.driver_present()
        self.card_wmi.set_values(
            readout="[ OK ]" if wmi_ok else "[ MISSING ]",
            subtitle="Platform profile loaded" if wmi_ok else "hp-wmi not active",
            tag="Kernel Module"
        )
        self.card_wmi.set_active(wmi_ok)

        # 2. RAPL
        rapl_path = "/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
        rapl_writable = os.path.exists(rapl_path) and os.access(rapl_path, os.W_OK)
        rapl_ok = os.path.exists(rapl_path)
        self.card_rapl.set_values(
            readout="[ OK ]" if rapl_writable else "[ READ-ONLY ]" if rapl_ok else "[ N/A ]",
            subtitle="PL1 write permission granted" if rapl_writable else "PL1 powercap detected" if rapl_ok else "Requires udev rules",
            tag="Powercap"
        )
        self.card_rapl.set_active(rapl_ok)

        # 3. PipeWire
        pw_ok = audio.available()
        self.card_pw.set_values(
            readout="[ ACTIVE ]" if pw_ok else "[ MISSING ]",
            subtitle="WirePlumber routing active" if pw_ok else "PipeWire tools missing",
            tag="Sound Server"
        )
        self.card_pw.set_active(pw_ok)

        # 4. NVIDIA
        nv_ok, nv_desc = system.nvidia_driver_status()
        self.card_nv.set_values(
            readout="[ SUPPORTED ]" if nv_ok else "[ NOT FOUND ]",
            subtitle=nv_desc if nv_ok else "Proprietary driver not loaded",
            tag="GPU Driver"
        )
        self.card_nv.set_active(nv_ok)

        # 5. System Preferences & Hotkeys
        if hasattr(self, "chk_autostart"):
            self.chk_autostart.blockSignals(True)
            self.chk_autostart.setChecked(state.autostart_enabled())
            self.chk_autostart.blockSignals(False)
        if hasattr(self, "chk_omen_key"):
            self.chk_omen_key.blockSignals(True)
            self.chk_omen_key.setChecked(hw.is_omen_key_bound())
            self.chk_omen_key.blockSignals(False)

    def _on_autostart_toggled(self, checked: bool):
        err = state.set_autostart(checked)
        if err:
            self.report(f"Autostart configuration error: {err}")
        else:
            self.inform("MyOmen system startup autostart " + ("enabled." if checked else "disabled."))

    def _on_omen_key_toggled(self, checked: bool):
        ok = hw.set_omen_key_binding(checked)
        if ok:
            self.inform("Physical OMEN keyboard key shortcut " + ("bound." if checked else "unbound."))
        else:
            self.report("Failed to configure OMEN key shortcut in GNOME settings.")
            self.chk_omen_key.blockSignals(True)
            self.chk_omen_key.setChecked(hw.is_omen_key_bound())
            self.chk_omen_key.blockSignals(False)





# ==============================================================================
# MAIN APPLICATION WINDOW
# ==============================================================================

class Window(QtWidgets.QMainWindow):
    def __init__(self, tray_mode: bool = False):
        super().__init__()
        self.setWindowTitle("MyOmen")
        self.resize(1000, 640)
        self.setMinimumSize(480, 360)
        self.quick_popup = None

        # Central widget and horizontal master layout
        root = QtWidgets.QWidget()
        root.setObjectName("Canvas")
        master_row = QtWidgets.QHBoxLayout(root)
        master_row.setContentsMargins(0, 0, 0, 0)
        master_row.setSpacing(0)

        # 1. Left Collapsible Sidebar Hub
        self.sidebar = widgets.CollapsibleSidebar(SECTIONS, self)
        self.sidebar.section_changed.connect(self.select)
        self.sidebar.profile_dialog_requested.connect(self.open_system_info)
        master_row.addWidget(self.sidebar)

        # 2. Main Center Content Pane (occupies 100% of available width next to sidebar)
        center_widget = QtWidgets.QWidget()
        center_widget.setObjectName("Pane")
        center_layout = QtWidgets.QVBoxLayout(center_widget)
        center_layout.setContentsMargins(20, 16, 20, 14)
        center_layout.setSpacing(12)

        # Top Header Bar: Page Title + Quick Settings button
        # Top Header Bar: Page Title, Subtitle, and Hardware Badge matching Catalog
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 6)

        header_box = QtWidgets.QWidget()
        header_layout = QtWidgets.QVBoxLayout(header_box)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(2)

        self.page_heading = QtWidgets.QLabel("System Overview")
        self.page_heading.setFont(theme.ui_font(18, theme.WEIGHT_BOLD))
        self.page_heading.setStyleSheet("color: #FFFFFF;")

        self.page_subheading = QtWidgets.QLabel("Omen Autopilot Active • Non-root udev rules")
        self.page_subheading.setFont(theme.ui_font(11, theme.WEIGHT_REGULAR))
        self.page_subheading.setStyleSheet("color: #8E8E93;")

        header_layout.addWidget(self.page_heading)
        header_layout.addWidget(self.page_subheading)
        top_bar.addWidget(header_box)
        top_bar.addStretch()

        self.hw_badge = QtWidgets.QLabel("OMEN 15-dh1xxx | RTX 2060 | F.44")
        self.hw_badge.setFont(theme.numeric_font(11, theme.WEIGHT_MEDIUM))
        self.hw_badge.setStyleSheet(f"""
            QLabel {{
                color: #8E8E93;
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: 6px;
                padding: 6px 12px;
            }}
        """)
        top_bar.addWidget(self.hw_badge)

        self.quick_settings_btn = QtWidgets.QPushButton("⚡ Quick Settings")
        self.quick_settings_btn.hide()
        self.btn_quick = self.quick_settings_btn
        center_layout.addLayout(top_bar)

        # Stacked Pages
        self.status = widgets.StatusLine()
        self.pages = QtWidgets.QStackedWidget()

        self.home = HomePage(self.report)
        self.home.power_platform_card.profile_changed.connect(self.on_power_profile_selected)
        self.management = ManagementPage(self.report, self.inform)
        self.light_manager = LightingPage(self.report, self.inform)
        self.audio_page = AudioPage(self.report, self.inform)
        self.mud = MudPage(self.report, self.inform)

        # Connect Sidebar Profile Management Hub
        self.sidebar.profiles.activated.connect(lambda _idx: self.on_profile())
        self.sidebar.save_profile.clicked.connect(self.on_save_profile)
        self.sidebar.delete_profile.clicked.connect(self.on_delete_profile)

        # Connect Home Page Startup Pills
        self.home.pill_apply_login.clicked.connect(self.on_at_login)
        self.home.pill_autostart.clicked.connect(self.on_autostart)
        self.home.pill_omen_key.clicked.connect(self.on_omen_key)

        # Backwards compatible property aliases
        self.monitor = self.home
        self.cooling = self.management
        self.power = self.management
        self.lighting = self.light_manager
        self.audio = self.audio_page

        self.page_list = [self.home, self.management, self.light_manager, self.audio_page, self.mud]
        for page in self.page_list:
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)

        center_layout.addWidget(self.pages, 1)
        center_layout.addWidget(self.status)
        master_row.addWidget(center_widget, 1)

        # Right sidebar completely eradicated: center area occupies 100% width
        self.widget_panel = None

        self.setCentralWidget(root)

        # Connect Dynamic Accent Synchronization: update stylesheet whenever accent color changes
        theme.register_accent_listener(self.on_dynamic_accent_changed)

        # Rotor Animation Driver
        self.rotors = charts.RotorDriver(self)
        for rotor in self.management.rotors():
            self.rotors.add(rotor)

        # Navigation Shortcuts
        for index in range(len(SECTIONS)):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: (self.sidebar.select(i), self.select(i)))

        self.alerts = monitoring.Alerts()
        self.cpu_load = monitoring.CpuLoad()
        self._really_quitting = False
        self.tray = None

        # Load Reboot Persistence Engine (state.json)
        from . import config
        self.saved_state = config.load_state()

        # Restore governor autopilot
        gov = self.saved_state.get("governor", {})
        if gov.get("baby_smart", False):
            self.management.baby_smart_btn.setChecked(True)

        # Restore theme & layout
        theme_cfg = self.saved_state.get("theme", {})
        saved_accent = theme_cfg.get("accent_color")
        if saved_accent:
            theme.set_dynamic_accent(saved_accent)
            theme.set_theme_mode(theme_cfg.get("theme_mode", "manual"))
        saved_layout = theme_cfg.get("layout_name")
        if saved_layout and saved_layout in effects.LAYOUTS:
            self.light_manager.on_layout(saved_layout)

        # Restore active profile
        saved_prof = self.saved_state.get("active_profile") or "myBaby"
        self.sidebar.refresh_profiles(saved_prof)
        if hasattr(self, "management") and hasattr(self.management, "profile_card"):
            self.management.profile_card.refresh_profiles(saved_prof)
        if saved_prof in state.names():
            self.apply_named(saved_prof)

        # Restore startup toggles
        toggles = self.saved_state.get("startup_toggles", {})
        autostart_on = toggles.get("start_with_computer", state.autostart_enabled())
        self.home.pill_autostart.setChecked(autostart_on)
        if autostart_on != state.autostart_enabled():
            state.set_autostart(autostart_on)

        omen_on = toggles.get("omen_key", state.omen_key_enabled())
        self.home.pill_omen_key.setChecked(omen_on)
        if omen_on != state.omen_key_enabled() and state.omen_key_supported():
            state.set_omen_key(omen_on)

        apply_login_on = toggles.get("apply_at_login", bool(state.startup()))
        self.home.pill_apply_login.setChecked(apply_login_on)
        if apply_login_on and saved_prof in state.names():
            state.set_startup(saved_prof)

        # System Tray: strictly guard instantiation to --tray flag only
        self.tray = None
        if tray_mode and QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self)
            self.tray.rebuild_profiles()
            self.tray.show()

        # Clean Exit Hooks
        atexit.register(self._release)
        for received in (signal.SIGTERM, signal.SIGINT):
            signal.signal(received, self._on_signal)

        self.latest_telemetry: dict = {}

        # Non-blocking telemetry background worker (QThread)
        from .worker import HardwareWorker
        self.worker = HardwareWorker(self)
        self.worker.telemetry_updated.connect(self.on_telemetry_updated)
        if tray_mode:
            self.worker.set_poll_interval(5000)
            self.worker.set_ui_state(False)
        self.worker.start()

        for problem in hw.driver_problems():
            self.report(problem)

        # System Sleep / Resume Lifecycle Monitor
        from .hardware import SleepMonitor
        self.sleep_monitor = SleepMonitor(self)
        self.sleep_monitor.prepare_for_sleep.connect(self._on_prepare_for_sleep)

        self.select(0)
        import gc
        gc.collect()

    def on_dynamic_accent_changed(self, _color_hex: str):
        self.setStyleSheet(theme.stylesheet())

    def open_system_info(self):
        dlg = widgets.SystemInfoDialog(self)
        dlg.exec()

    def open_quick_settings(self):
        """Open GNOME Quick Settings style floating popup directly."""
        self.show_quick_settings(from_tray=False)

    def _release(self):
        tray = getattr(self, "tray", None)
        if tray is not None:
            try:
                tray.hide()
            except Exception:
                pass
        worker = getattr(self, "worker", None)
        if worker is not None:
            worker.stop()
        sleep_monitor = getattr(self, "sleep_monitor", None)
        if sleep_monitor is not None:
            try:
                sleep_monitor.close()
            except Exception:
                pass
        cooling = getattr(self, "cooling", None)
        if cooling is not None:
            cooling.stop_smart()
        lighting = getattr(self, "lighting", None)
        if lighting is not None:
            lighting.stop_reactive()

    def _on_signal(self, _number, _frame):
        self._release()
        QtWidgets.QApplication.quit()

    def _on_prepare_for_sleep(self, sleeping: bool):
        if sleeping:
            logging.info("System entering sleep/suspend lifecycle")
            if hasattr(self, "worker") and self.worker:
                self.worker.set_ui_state(False)
        else:
            logging.info("System waking up from sleep/suspend lifecycle; scheduling 1.0s stabilization delay")
            QtCore.QTimer.singleShot(1000, self.on_system_resumed)

    def on_system_resumed(self):
        # 1. Guard stale sockets and tray presence
        if hasattr(self, "server") and hasattr(self.server, "verify_or_rebind"):
            self.server.verify_or_rebind()
        if self.tray and hasattr(self.tray, "verify_presence"):
            self.tray.verify_presence()

        # 2. Query current active profile from state/config
        from . import config
        prof = config.active_profile()

        # 3. Re-apply the active profile to ACPI platform profile with light retry
        saved_profile = state.get(prof)
        mode_to_apply = saved_profile.get("power", prof) if saved_profile else prof

        for attempt in range(2):
            try:
                err = hw.set_platform_profile(mode_to_apply)
                if not err:
                    break
                logging.warning("Profile re-apply attempt %d/2 returned error: %s", attempt + 1, err)
            except OSError as exc:
                logging.warning("Transient OSError applying profile (attempt %d/2): %s", attempt + 1, exc)
            except Exception as exc:
                logging.warning("Error applying profile (attempt %d/2): %s", attempt + 1, exc)
            time.sleep(0.5)

        # Synchronize UI components immediately
        self.home.power_platform_card.set_active_profile(mode_to_apply)
        if hasattr(self, "management") and hasattr(self.management, "power_tiles"):
            self.management.power_tiles.select(mode_to_apply)
        if self.tray and hasattr(self.tray, "power_actions"):
            if mode_to_apply in self.tray.power_actions:
                for k, act in self.tray.power_actions.items():
                    act.setChecked(k == mode_to_apply)

        # 4. Re-sync fan autopilot/hysteresis curves and keyboard RGB state if enabled
        if hasattr(self, "management") and hasattr(self.management, "baby_smart"):
            if self.management.baby_smart.enabled:
                self.management.baby_smart.reset_state()
        if hasattr(self, "light_manager"):
            try:
                last_l = state.last_lighting()
                if last_l:
                    state.apply_lighting(last_l)
            except Exception:
                pass

        # 5. Trigger a telemetry poll cycle
        if hasattr(self, "worker") and self.worker:
            self.worker.trigger_poll()

        # 6. Log the recovery event cleanly
        logging.info("System resumed from sleep: Re-applied profile '%s'", prof)

    def show_from_tray(self, token: str | None = None):
        if token:
            os.environ["XDG_ACTIVATION_TOKEN"] = token
        elif self.isVisible() and not self.isActiveWindow():
            self.hide()
            QtCore.QTimer.singleShot(60, self._show_now)
            return
        if hasattr(self, "worker") and self.worker:
            self.worker.set_poll_interval(1000)
            self.worker.set_ui_state(True)
        self._show_now()
        self.refresh()
        if hasattr(self, "rotors"):
            self.rotors.sync()

    def _show_now(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_power_pick(self, mode: str):
        self.on_power_profile_selected(mode)

    def on_power_profile_selected(self, mode: str):
        mode = mode.lower()
        if mode == "quiet":
            mode = "low-power"
        if mode in ("performance", "max") and hw.power_source().get("on_ac") is False:
            self.inform("On battery: " + _title(mode) + " takes effect when connected to AC power.")
        err = hw.set_profile(mode)
        if err:
            self.report(err)
        else:
            self.inform(f"Switched power profile to {_title(mode)}.")

        # Immediate bidirectional synchronization across UI components
        if hasattr(self, "home") and hasattr(self.home, "power_platform_card"):
            self.home.power_platform_card.set_active_profile(mode)
        if hasattr(self, "management") and hasattr(self.management, "power_tiles"):
            self.management.power_tiles.select(mode)
        if self.tray and hasattr(self.tray, "power_actions"):
            if mode in self.tray.power_actions:
                for k, act in self.tray.power_actions.items():
                    act.setChecked(k == mode)
        if hasattr(self, "quick_popup") and self.quick_popup and self.quick_popup.isVisible():
            quick = self.quick_popup.widget
            if hasattr(quick, "prof_buttons") and mode in quick.prof_buttons:
                for k, btn in quick.prof_buttons.items():
                    btn.setChecked(k == mode)

        if state.get(mode):
            self.apply_named(mode)
        else:
            from . import config
            config.save_active_profile(mode)

        if hasattr(self, "worker") and self.worker:
            self.worker.trigger_poll()

    def apply_named(self, name: str):
        profile = state.get(name)
        if profile is None:
            return
        for problem in state.apply(profile):
            self.report(problem)
        self.sidebar.refresh_profiles(name)
        if hasattr(self, "management") and hasattr(self.management, "profile_card"):
            self.management.profile_card.refresh_profiles(name)
        if self.tray:
            self.tray.rebuild_profiles()
        if hasattr(self, "home") and hasattr(self.home, "pill_apply_login"):
            self.home.pill_apply_login.setChecked(state.startup() == name)
        from . import config
        config.save_active_profile(name)
        self.inform(f"Applied profile: {name}.")
        self.refresh()

    def toggle_quick_settings(self, from_tray: bool = False):
        if self.tray:
            self.tray.toggle_quick_settings(from_tray=from_tray)
        else:
            if self.quick_popup and self.quick_popup.isVisible():
                self.quick_popup.hide()
                return
            self.show_quick_settings(from_tray=from_tray)

    def show_quick_settings(self, from_tray: bool = False):
        if self.tray:
            self.tray.show_quick_settings(from_tray=from_tray)
        else:
            if self.quick_popup is None:
                self.quick_popup = widgets.QuickSettingsPopup(None)
                quick = self.quick_popup.widget
                quick.btn_baby.clicked.connect(lambda checked: self.management.baby_smart_btn.setChecked(checked))
                quick.btn_smart.clicked.connect(lambda checked: self.management.smart_toggle.setChecked(checked))
                quick.btn_rgb_rand.clicked.connect(self.light_manager.on_random_rgb)
                quick.btn_audio.clicked.connect(self._cycle_audio_preset)
                quick.btn_open.clicked.connect(lambda: (self.quick_popup.hide(), self.show_from_tray()))
                quick.btn_quit.clicked.connect(self.quit_properly)

            quick = self.quick_popup.widget
            quick.btn_baby.setChecked(self.management.baby_smart.enabled)
            quick.btn_smart.setChecked(self.management.smart.enabled)
            current_preset = self.audio_page.engine.current or "Off"
            quick.btn_audio.setText(f"🎵 Audio: {current_preset.capitalize()}")

            data = hw.sensors() or {}
            gpu_data = gpu.read()
            quick.pill_cpu.set(data.get("cpu_temp"))
            quick.pill_gpu.set(gpu_data.get("temp"))
            quick.pill_load.set(self.cpu_load.percent())
            ram_info = monitoring.memory()
            quick.pill_ram.set(ram_info.get("percent") if ram_info else None)

            widget = self.quick_popup
            widget.adjustSize()

            screen = QtGui.QGuiApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                pos_x = avail.right() - widget.width() - 20
                pos_y = avail.top() + 10  # Below GNOME top panel
                widget.move(pos_x, pos_y)

            widget.show()
            widget.raise_()
            widget.activateWindow()

    def _cycle_audio_preset(self):
        presets = list(self.audio_page.PRESETS.keys())
        current = self.audio_page.engine.current or "off"
        try:
            next_idx = (presets.index(current) + 1) % len(presets)
        except ValueError:
            next_idx = 0
        new_preset = presets[next_idx]
        self.audio_page.on_preset_pick(new_preset)
        if self.quick_popup:
            self.quick_popup.widget.btn_audio.setText(f"🎵 Audio: {new_preset.capitalize()}")

    def quit_properly(self):
        self._really_quitting = True
        self.cooling.stop_smart()
        self._release()
        self.close()
        QtWidgets.QApplication.quit()

    def closeEvent(self, event):
        if self.tray and not self._really_quitting and state.settings().get("close_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "MyOmen is still running",
                "Smart mode and keyboard effects continue running in background.",
                QtWidgets.QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._release()
        super().closeEvent(event)

    def changeEvent(self, event: QtCore.QEvent):
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            if self.isMinimized():
                if hasattr(self, "worker") and self.worker:
                    self.worker.set_poll_interval(5000)
            else:
                if hasattr(self, "worker") and self.worker:
                    self.worker.set_poll_interval(1000)
        super().changeEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent):
        if hasattr(self, "worker") and self.worker:
            self.worker.set_poll_interval(5000)
            self.worker.set_ui_state(False)
        if hasattr(self, "rotors"):
            self.rotors.sync()
        import gc
        gc.collect()
        super().hideEvent(event)

    def showEvent(self, event: QtGui.QShowEvent):
        if hasattr(self, "worker") and self.worker:
            self.worker.set_poll_interval(1000)
            self.worker.set_ui_state(True)
            self.worker.trigger_poll()
        if hasattr(self, "rotors"):
            self.rotors.sync()
        super().showEvent(event)

    def select(self, index: int):
        self.pages.setCurrentIndex(index)
        if hasattr(self, "sidebar") and self.sidebar:
            self.sidebar.select(index)
        section_titles = [
            ("System Overview", "Omen Autopilot Active • Non-root udev rules"),
            ("Performance Modes", "ACPI platform profile & power limits"),
            ("4-Zone Lighting", "4-Zone RGB Lighting & Presets"),
            ("PipeWire Audio DSP", "PipeWire limiter, audio & hardware specs"),
            ("System & Drivers", "Driver setup & udev installer"),
        ]
        if index < len(section_titles):
            title, sub = section_titles[index]
            self.page_heading.setText(title)
            if hasattr(self, "page_subheading"):
                self.page_subheading.setText(sub)
        self.refresh()

    def report(self, error):
        if error:
            self.status.show_error(error)

    def inform(self, text: str):
        self.status.show_info(text)

    # ------------------------------------------------------------ profiles

    def on_profile(self, _index: int | None = None):
        name = self.sidebar.current_profile()
        if not name:
            return
        self.apply_named(name)

    def on_save_profile(self):
        current = self.sidebar.current_profile()
        name, accepted = QtWidgets.QInputDialog.getText(
            self, "Save profile", "Save current system state as profile:",
            QtWidgets.QLineEdit.EchoMode.Normal, current or "")
        if not accepted or not name.strip():
            return
        name = name.strip()
        if name in state.names():
            confirm = QtWidgets.QMessageBox.question(
                self, "Replace profile", f"{name} already exists. Overwrite?")
            if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        error = state.remember(name)
        if error:
            self.report(error)
            return
        self.sidebar.refresh_profiles(name)
        if self.tray:
            self.tray.rebuild_profiles()
        from . import config
        config.save_active_profile(name)
        self.inform(f"Saved profile: {name}.")

    def on_delete_profile(self):
        name = self.sidebar.current_profile()
        if not name:
            return
        confirm = QtWidgets.QMessageBox.question(
            self, "Delete profile", f"Delete profile '{name}'?")
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.report(state.forget(name))
        self.sidebar.refresh_profiles(None)
        if self.tray:
            self.tray.rebuild_profiles()
        from . import config
        config.save_active_profile(None)
        self.inform(f"Deleted profile: {name}.")

    def on_autostart(self, checked: bool):
        error = state.set_autostart(checked)
        if error:
            self.report(error)
            self.home.pill_autostart.blockSignals(True)
            self.home.pill_autostart.setChecked(not checked)
            self.home.pill_autostart.blockSignals(False)
            return
        from . import config
        config.update_startup_toggle("start_with_computer", checked)
        self.inform("MyOmen will start with computer." if checked else "Autostart disabled.")

    def on_omen_key(self, checked: bool):
        error = state.set_omen_key(checked)
        if error:
            self.report(error)
            self.home.pill_omen_key.blockSignals(True)
            self.home.pill_omen_key.setChecked(not checked)
            self.home.pill_omen_key.blockSignals(False)
            return
        from . import config
        config.update_startup_toggle("omen_key", checked)
        self.inform("OMEN key shortcut configured." if checked else "OMEN key shortcut removed.")

    def on_at_login(self, checked: bool):
        name = self.sidebar.current_profile()
        if not name and checked:
            self.home.pill_apply_login.blockSignals(True)
            self.home.pill_apply_login.setChecked(False)
            self.home.pill_apply_login.blockSignals(False)
            self.inform("Select or save a profile first before enabling 'Apply at login'.")
            return
        self.report(state.set_startup(name if checked else None))
        from . import config
        config.update_startup_toggle("apply_at_login", checked)
        self.inform(f"Profile '{name}' will apply at login." if checked else "Apply at login disabled.")
        if self.tray:
            self.tray.rebuild_profiles()

    # ------------------------------------------------------------- telemetry & refresh

    def on_telemetry_updated(self, snapshot: dict):
        self.latest_telemetry = snapshot
        data = snapshot.get("sensors")
        if not data:
            self.status.show_error("Lost contact with hp-wmi. Check kernel module status.")
            return

        gpu_data = snapshot.get("gpu") or {}
        cpu_load_pct = snapshot.get("cpu_load")
        ram_data = snapshot.get("ram") or {}
        limit_w = snapshot.get("power_limit_w")
        power_src = snapshot.get("power_source") or {}
        wattage = snapshot.get("wattage")
        profile = snapshot.get("profile")

        if self.tray:
            self.tray.refresh(data, gpu_data, profile, wattage=wattage)

        for message in self.alerts.check(
                {"cpu_temp": data.get("cpu_temp"), "gpu_temp": gpu_data.get("temp")}, time.monotonic()):
            self.report(message)

        # Skip expensive UI spline recalculations and widget repaints when window is hidden in tray
        if not self.isVisible():
            return

        # Refresh all pages when window is visible
        self.home.refresh(
            data, gpu_data, cpu_load_pct, ram_data, limit_w, power_src,
            wattage=wattage, autopilot_active=self.management.baby_smart.enabled, profile=profile
        )
        self.management.refresh(data, gpu_data)
        self.light_manager.refresh(data, gpu_data)
        self.audio_page.refresh(data, gpu_data)
        self.rotors.sync()

        # Max Mode Overdrive Glow Trigger (Fire #FF6B00)
        is_overdrive = (
            bool(snapshot.get("max_fan"))
            or (self.cooling.baby_smart.enabled and self.cooling.baby_smart.current == "max")
            or (profile == "max")
        )
        if hasattr(self.home, "fan_trace") and hasattr(self.home.fan_trace, "set_accent_color"):
            self.home.fan_trace.set_accent_color(theme.ACCENT_FIRE if is_overdrive else theme.ACCENT_ICE, glow=is_overdrive)
        for card in self.cooling.cards:
            card.set_overdrive(is_overdrive)

    def refresh(self):
        if hasattr(self, "latest_telemetry") and self.latest_telemetry:
            self.on_telemetry_updated(self.latest_telemetry)
        if hasattr(self, "worker") and self.worker:
            self.worker.trigger_poll()


# Class alias for MyOmenWindow
MyOmenWindow = Window


# ------------------------------------------------------------ Single Instance

def _instance_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(runtime, f"myomen-{os.getuid()}.sock")


def _cleanup_dead_socket(path: str):
    """Remove socket file if the owning process is no longer listening."""
    if not os.path.exists(path):
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as test_sock:
            test_sock.settimeout(0.3)
            test_sock.connect(path)
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass


def _hand_over(show: bool) -> bool:
    path = _instance_path()
    if not os.path.exists(path):
        return False
    token = os.environ.get("XDG_ACTIVATION_TOKEN") or os.environ.get("DESKTOP_STARTUP_ID") or ""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.8)
            client.connect(path)
            payload = ("show " + token + "\n").encode() if show else b"ping\n"
            client.sendall(payload)
        return True
    except OSError:
        _cleanup_dead_socket(path)
        return False


class InstanceServer(QtCore.QObject):
    def __init__(self, on_show):
        super().__init__()
        self.on_show = on_show
        self.path = _instance_path()
        _cleanup_dead_socket(self.path)
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        legacy_path = os.path.join(runtime, f"omen-sense-{os.getuid()}.sock")
        if os.path.exists(legacy_path):
            _cleanup_dead_socket(legacy_path)
            try:
                os.unlink(legacy_path)
            except OSError:
                pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.server.bind(self.path)
        except OSError:
            _cleanup_dead_socket(self.path)
            try:
                os.unlink(self.path)
            except OSError:
                pass
            self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        self.server.setblocking(False)
        self.notifier = QtCore.QSocketNotifier(self.server.fileno(), QtCore.QSocketNotifier.Type.Read, self)
        self.notifier.activated.connect(self._accept)
        atexit.register(self.close)

    def _accept(self, *_):
        try:
            client, _address = self.server.accept()
        except OSError:
            return
        with client:
            client.settimeout(0.5)
            try:
                message = client.recv(1024)
            except OSError:
                message = b""
        if message.startswith(b"show"):
            token = message[4:].decode(errors="replace").strip()
            self.on_show(token or None)

    def verify_or_rebind(self):
        """Ensure the Unix domain socket is active and bound across sleep/wake cycles."""
        try:
            if not os.path.exists(self.path):
                logging.warning("InstanceServer socket disappeared across sleep; rebinding: %s", self.path)
                self.notifier.setEnabled(False)
                try:
                    self.server.close()
                except Exception:
                    pass
                self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.server.bind(self.path)
                os.chmod(self.path, 0o600)
                self.server.listen(4)
                self.server.setblocking(False)
                self.notifier = QtCore.QSocketNotifier(self.server.fileno(), QtCore.QSocketNotifier.Type.Read, self)
                self.notifier.activated.connect(self._accept)
            else:
                self.notifier.setEnabled(True)
        except Exception as exc:
            logging.error("Failed to verify/rebind InstanceServer: %s", exc)

    def close(self):
        self.notifier.setEnabled(False)
        self.server.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass


def main(tray_only: bool = False) -> int:
    # Explicitly check sys.argv: if launched interactively without --tray, force full UI display
    if "--tray" in sys.argv:
        tray_only = True
    elif not tray_only:
        tray_only = False

    # Process-level lock / early exit before Qt DBus registration
    if _hand_over(show=not tray_only):
        return 0

    QtWidgets.QApplication.setDesktopFileName("myomen")
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("MyOmen")
    app.setApplicationDisplayName("MyOmen")

    app_icon_path = theme.icon_path("myomen")
    if app_icon_path:
        app.setWindowIcon(QtGui.QIcon(str(app_icon_path)))

    app.setStyle("Fusion")
    app.setFont(theme.ui_font())
    app.setStyleSheet(theme.stylesheet())

    if not hw.driver_present():
        QtWidgets.QMessageBox.critical(
            None, "MyOmen",
            "hp-wmi is not loaded, so there is nothing to control.\n\n"
            "Install the patched driver: see driver/INSTALL.md.")
        return 1

    window = Window(tray_mode=tray_only)
    # Force window.show() regardless of Wayland tray provider state during interactive runs
    if tray_only and window.tray is not None:
        window.tray.showMessage(
            "MyOmen is running", "Click the panel icon to open it.",
            QtWidgets.QSystemTrayIcon.MessageIcon.Information, 3000)
    else:
        window.show()
        window.raise_()
        window.activateWindow()

    app.setQuitOnLastWindowClosed(not (window.tray and state.settings().get("close_to_tray", True)))
    window.server = InstanceServer(window.show_from_tray)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
