"""System tray presence and GNOME-style Quick Settings popup management."""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import gpu, hw, monitoring, state, theme, widgets


def _title(name: str | None) -> str:
    return hw.PROFILE_TITLES.get(name, name.capitalize() if name else "--")


def make_dynamic_tray_icon(cpu_temp: int | None = None, gpu_temp: int | None = None, profile: str | None = None) -> QtGui.QIcon:
    """Generate dynamic square 24x24 and 48x48 in-memory icon with OMEN diamond logo and status dot."""
    icon = QtGui.QIcon()

    # Generate both 1x (24x24) and 2x HiDPI (48x48) square pixmaps
    for dpr in (1.0, 2.0):
        s = int(24 * dpr)
        pixmap = QtGui.QPixmap(s, s)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(dpr)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # 1. OMEN Diamond Brand Logo (centered at 12, 12, 18x18 bounding box)
        diamond = QtGui.QPolygonF([
            QtCore.QPointF(12, 3),
            QtCore.QPointF(21, 12),
            QtCore.QPointF(12, 21),
            QtCore.QPointF(3, 12),
        ])

        if profile == "performance" or profile == "max":
            start_col = QtGui.QColor("#FF1A35")
            end_col = QtGui.QColor("#FB8500")
        elif profile == "low-power":
            start_col = QtGui.QColor("#1DB954")
            end_col = QtGui.QColor("#00B4D8")
        else:
            start_col = QtGui.QColor("#00D2FF")
            end_col = QtGui.QColor("#0077B6")

        diamond_grad = QtGui.QLinearGradient(3, 3, 21, 21)
        diamond_grad.setColorAt(0.0, start_col)
        diamond_grad.setColorAt(1.0, end_col)

        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 200), 1.2, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QtGui.QBrush(diamond_grad))
        painter.drawPolygon(diamond)

        # 2. Subtle telemetry health status dot at bottom-right corner
        max_t = max(t for t in (cpu_temp, gpu_temp) if t is not None) if (cpu_temp or gpu_temp) else None
        if max_t is None:
            dot_color = QtGui.QColor("#727272")
        elif max_t >= 85:
            dot_color = QtGui.QColor("#FF1A35")
        elif max_t >= 75:
            dot_color = QtGui.QColor("#FB8500")
        elif max_t >= 65:
            dot_color = QtGui.QColor("#00B4D8")
        else:
            dot_color = QtGui.QColor("#1DB954")

        # Dark halo ring around dot for crisp contrast
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(11, 12, 14, 230)))
        painter.drawEllipse(QtCore.QRectF(14.5, 14.5, 7.0, 7.0))

        painter.setBrush(QtGui.QBrush(dot_color))
        painter.drawEllipse(QtCore.QRectF(15.5, 15.5, 5.0, 5.0))

        painter.end()
        icon.addPixmap(pixmap)

    return icon


class Tray(QtWidgets.QSystemTrayIcon):
    """System tray presence with GNOME-styled Quick Settings menu and live telemetry."""

    def __init__(self, window):
        # Initialize with the Royal Blue OMEN Diamond icon
        icon_file = theme.icon_path("myomen")
        if icon_file and icon_file.is_file():
            initial_icon = QtGui.QIcon(str(icon_file))
        else:
            initial_icon = make_dynamic_tray_icon(0, 0, "balanced")
        if initial_icon.isNull():
            initial_icon = make_dynamic_tray_icon(0, 0, "balanced")

        super().__init__(initial_icon, window)
        self.window = window
        self.setIcon(initial_icon)
        self.setIconName("myomen")
        self.setToolTip("MyOmen")
        self.quick_popup = None

        # Clean DBus / StatusNotifierItem unregistration upon application shutdown
        app_inst = QtCore.QCoreApplication.instance()
        if app_inst is not None:
            app_inst.aboutToQuit.connect(self.hide)

        # Build clean QMenu for GNOME AppIndicator / DBus StatusNotifierItem compatibility
        self.menu = QtWidgets.QMenu()
        self.menu.setObjectName("TrayMenu")
        self.menu.setStyleSheet(f"""
            QMenu#TrayMenu {{
                background-color: {theme.SURFACE_BASE};
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 12px;
                padding: 6px;
                color: #ffffff;
            }}
            QMenu#TrayMenu::item {{
                padding: 8px 18px;
                border-radius: 8px;
                font-weight: 600;
            }}
            QMenu#TrayMenu::item:selected {{
                background-color: rgba(255, 255, 255, 0.12);
                color: {theme.get_dynamic_accent()};
            }}
            QMenu#TrayMenu::separator {{
                height: 1px;
                background-color: rgba(255, 255, 255, 0.12);
                margin: 4px 8px;
            }}
        """)

        # 1. Live Telemetry Headers (real-time temperature & fan speeds)
        self.act_temp = QtGui.QAction("🔥 CPU: -- °C  ·  GPU: -- °C", self)
        self.act_temp.setEnabled(False)
        self.menu.addAction(self.act_temp)

        self.act_fans = QtGui.QAction("🌀 Fan 1: -- rpm  ·  Fan 2: -- rpm", self)
        self.act_fans.setEnabled(False)
        self.menu.addAction(self.act_fans)

        self.menu.addSeparator()

        # 2. Instant Power Modes Submenu
        self.power_menu = self.menu.addMenu("⚡ Power Modes")
        self.power_menu.setObjectName("TraySubMenu")
        self.power_group = QtGui.QActionGroup(self)
        self.power_group.setExclusive(True)
        self.power_actions = {}

        for mode, title in [("low-power", "Quiet (Whisper Quiet)"),
                            ("balanced", "Balanced (Standard)"),
                            ("performance", "Performance (High TGP)"),
                            ("max", "Max Overdrive (100% Fans)")]:
            act = QtGui.QAction(title, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c=False, m=mode: self.set_power_profile(m))
            self.power_group.addAction(act)
            self.power_menu.addAction(act)
            self.power_actions[mode] = act

        self.power_menu.addSeparator()
        self.act_max_fans = QtGui.QAction("Forced Max Fans (100% Speed)", self)
        self.act_max_fans.setCheckable(True)
        self.act_max_fans.triggered.connect(self.toggle_max_fans)
        self.power_menu.addAction(self.act_max_fans)

        # 3. Instant Keyboard Lighting Controls
        self.rgb_menu = self.menu.addMenu("💡 Keyboard Lighting")
        self.rgb_menu.setObjectName("TraySubMenu")

        self.act_kb_toggle = QtGui.QAction("Toggle Backlight (On / Off)", self)
        self.act_kb_toggle.triggered.connect(self.toggle_keyboard_power)
        self.rgb_menu.addAction(self.act_kb_toggle)

        self.act_rand_rgb = QtGui.QAction("🎲 Random RGB Cycle", self)
        self.act_rand_rgb.triggered.connect(lambda: self.window.light_manager.on_random_rgb())
        self.rgb_menu.addAction(self.act_rand_rgb)

        self.rgb_menu.addSeparator()
        top_presets = [
            ("ice", "❄️ Ice Cold (Primary)"),
            ("stealth", "🕶️ Stealth Off"),
            ("crimson", "🔴 Omen Crimson"),
            ("cyberpunk", "🌌 Cyberpunk"),
            ("ghost", "⚪ Ghost White"),
        ]
        for key, label in top_presets:
            p_act = QtGui.QAction(label, self)
            p_act.triggered.connect(lambda _c=False, k=key: self.apply_layout(k))
            self.rgb_menu.addAction(p_act)

        self.menu.addSeparator()

        # 4. Standard Quick Settings & Window Navigation
        self.act_quick = QtGui.QAction("⚡ Quick Settings...", self)
        self.act_quick.setIcon(QtGui.QIcon(theme.icon("activity", theme.TEXT_PRIMARY, 16)))
        self.act_quick.triggered.connect(self.open_quick_settings_window)
        self.menu.addAction(self.act_quick)

        self.act_open = QtGui.QAction("Open MyOmen", self)
        self.act_open.setIcon(QtGui.QIcon(theme.icon("monitor", theme.TEXT_PRIMARY, 16)))
        self.act_open.triggered.connect(self.show_main_window)
        self.menu.addAction(self.act_open)

        self.menu.addSeparator()

        self.act_quit = QtGui.QAction("Quit", self)
        self.act_quit.setIcon(QtGui.QIcon(theme.icon("power", theme.ALERT, 16)))
        self.act_quit.triggered.connect(self.quit_app)
        self.menu.addAction(self.act_quit)

        # Set default action so double-clicking or standard activation triggers it directly
        self.menu.setDefaultAction(self.act_quick)
        self.setContextMenu(self.menu)

        # Activation handler for clicks
        self.activated.connect(self._on_activated)

    def setIconName(self, name: str):
        self._icon_name = name
        self.setProperty("iconName", name)

    def _on_activated(self, reason=QtWidgets.QSystemTrayIcon.ActivationReason.Trigger):
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_quick_settings(from_tray=True)

    def open_quick_settings_window(self):
        self.show_quick_settings(from_tray=True)

    def show_main_window(self):
        if self.quick_popup and self.quick_popup.isVisible():
            self.quick_popup.hide()
        self.window.show_from_tray()

    def verify_presence(self):
        """Ensure tray icon is visible and re-asserted on DBus SNI after sleep/wake."""
        if not self.isVisible():
            self.show()

    def quit_app(self):
        self.hide()
        if self.quick_popup and self.quick_popup.isVisible():
            self.quick_popup.hide()
        self.window.quit_properly()

    def toggle_quick_settings(self, from_tray: bool = True):
        if self.quick_popup and self.quick_popup.isVisible():
            self.quick_popup.hide()
            return
        self.show_quick_settings(from_tray=from_tray)

    def show_quick_settings(self, from_tray: bool = True):
        if self.quick_popup is None:
            self.quick_popup = widgets.QuickSettingsPopup(None)
            self.window.quick_popup = self.quick_popup
            w = self.window
            quick = self.quick_popup.widget
            quick.btn_max_fans.clicked.connect(self.toggle_max_fans)
            for p_key, btn in quick.prof_buttons.items():
                btn.clicked.connect(lambda _c=False, m=p_key: self.set_power_profile(m))
            for chip_id, chip_btn in quick.rgb_chips.items():
                chip_btn.clicked.connect(lambda _c=False, k=chip_id: self.apply_layout(k))
            quick.btn_open.clicked.connect(lambda: (self.quick_popup.hide(), w.show_from_tray()))
            quick.btn_quit.clicked.connect(w.quit_properly)

        # Refresh stats and states
        quick = self.quick_popup.widget
        data = hw.sensors() or {}
        gpu_data = gpu.read(sync=False) or {}
        cpu_t = data.get("cpu_temp")
        gpu_t = gpu_data.get("temp")
        cpu_pct = self.window.cpu_load.percent() or 0
        gpu_pct = gpu_data.get("usage") or 0
        fans = data.get("fans") or []
        f1 = f"{fans[0]} rpm" if len(fans) > 0 and fans[0] else "-- rpm"
        f2 = f"{fans[1]} rpm" if len(fans) > 1 and fans[1] else "-- rpm"

        quick.bar_cpu.setValue(int(cpu_pct))
        quick.lbl_cpu_stat.setText(f"{cpu_t or '--'} °C")
        quick.bar_gpu.setValue(int(gpu_pct))
        quick.lbl_gpu_stat.setText(f"{gpu_t or '--'} °C")
        quick.lbl_fan_speed.setText(f"{f1} · {f2}")

        maxed = hw.max_fan()
        if maxed is not None:
            quick.btn_max_fans.setChecked(maxed)

        curr_prof = hw.profile()
        if curr_prof and curr_prof in quick.prof_buttons:
            for k, btn in quick.prof_buttons.items():
                btn.setChecked(k == curr_prof)

        widget = self.quick_popup
        widget.adjustSize()

        # Position elegantly at top-right of active screen below GNOME top panel
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
        page = self.window.audio_page
        presets = list(page.engine.presets.keys())
        if not presets:
            return
        current = page.engine.current
        try:
            new_preset = presets[(presets.index(current) + 1) % len(presets)]
        except ValueError:
            new_preset = presets[0]
        if hasattr(page, "on_preset_pick"):
            page.on_preset_pick(new_preset)
        else:
            page.engine.apply(new_preset)

    def set_power_profile(self, mode: str):
        if hasattr(self.window, "on_power_pick"):
            self.window.on_power_pick(mode)
        elif hasattr(self.window, "management"):
            self.window.management.on_power_pick(mode)

    def toggle_max_fans(self, checked: bool):
        hw.set_max_fan(checked)
        if hasattr(self.window, "management"):
            self.window.management.fan_mode.select("max" if checked else "auto")

    def toggle_keyboard_power(self):
        if hasattr(self.window, "light_manager"):
            self.window.light_manager.on_power()

    def apply_layout(self, layout_key: str):
        if hasattr(self.window, "light_manager"):
            self.window.light_manager.on_layout(layout_key)

    def rebuild_profiles(self):
        pass

    def refresh(self, data: dict, gpu_data: dict, profile: str | None, wattage: float | None = None):
        fans = data.get("fans") or []
        cpu_t = data.get("cpu_temp")
        gpu_t = gpu_data.get("temp")
        gpu_pwr = gpu_data.get("power_w")
        f1 = f"{fans[0]} rpm" if len(fans) > 0 and fans[0] else "-- rpm"
        f2 = f"{fans[1]} rpm" if len(fans) > 1 and fans[1] else "-- rpm"

        # Update strictly square 24x24 in-memory dynamic tray icon with OMEN diamond logo
        self.setIcon(make_dynamic_tray_icon(cpu_t, gpu_t, profile))

        # Update Live Telemetry Items in Tray Menu (iStat-style)
        w_str = f" ({wattage:.1f}W)" if wattage is not None else ""
        gpu_w_str = f" ({gpu_pwr:.1f}W)" if gpu_pwr is not None else ""
        self.act_temp.setText(f"🔥 CPU: {cpu_t or '--'} °C{w_str}  ·  GPU: {gpu_t or '--'} °C{gpu_w_str}")
        self.act_fans.setText(f"🌀 Fan 1: {f1}  ·  Fan 2: {f2}")

        # Update checked state for power profile actions
        if profile and profile in self.power_actions:
            for k, act in self.power_actions.items():
                act.setChecked(k == profile)

        maxed = hw.max_fan()
        if maxed is not None:
            self.act_max_fans.setChecked(maxed)

        wattage_tip = f" · {wattage:.1f} W" if wattage is not None else ""
        gpu_tip = f" · {gpu_pwr:.1f} W" if gpu_pwr is not None else ""
        self.setToolTip(
            f"MyOmen — {_title(profile)}\n"
            f"CPU: {cpu_t or '--'} °C{wattage_tip}\n"
            f"GPU: {gpu_t or '--'} °C{gpu_tip}\n"
            f"Fans: {f1} / {f2}")

        if self.quick_popup and self.quick_popup.isVisible():
            quick = self.quick_popup.widget
            cpu_pct = self.window.cpu_load.percent() or 0
            gpu_pct = gpu_data.get("usage") or 0
            w_val = f" · {wattage:.1f} W" if wattage is not None else ""
            gw_val = f" · {gpu_pwr:.1f} W" if gpu_pwr is not None else ""

            quick.bar_cpu.setValue(int(cpu_pct))
            quick.lbl_cpu_stat.setText(f"{cpu_t or '--'} °C{w_val}")
            quick.bar_gpu.setValue(int(gpu_pct))
            quick.lbl_gpu_stat.setText(f"{gpu_t or '--'} °C{gw_val}")
            quick.lbl_fan_speed.setText(f"{f1} · {f2}")

            if maxed is not None:
                quick.btn_max_fans.setChecked(maxed)
            if profile and profile in quick.prof_buttons:
                for k, btn in quick.prof_buttons.items():
                    btn.setChecked(k == profile)
