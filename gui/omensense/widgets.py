"""Composite widgets for MyOmen.

Spotify Matte Dark (#0F1012 Canvas, #16171A Cards), iOS Shortcuts neon geometry (12px radii),
Collapsible navigation sidebar, System Info hub, and GNOME-style Quick Settings.
"""

from __future__ import annotations

import math
import os
import pathlib

from PySide6 import QtCore, QtGui, QtWidgets

from . import charts, hw, state, system, theme


def get_brand_logo_path() -> str:
    path = theme.icon_path("myomen")
    if path and path.is_file():
        return str(path)
    return str(theme.ICONS / "myomen.svg")


class BabySmartButton(QtWidgets.QPushButton):
    """Cyberpunk Neon toggle button for Omen Autopilot cooling governor."""

    def __init__(self, text: str = "  Omen Autopilot", parent=None):
        super().__init__(text, parent)
        self.setObjectName("BabySmartButton")
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        # Set icon using official Royal Blue OMEN Diamond vector
        logo = theme.icon_path("myomen") or (theme.ICONS / "myomen.svg")
        if logo and os.path.exists(str(logo)):
            self.setIcon(QtGui.QIcon(str(logo)))
            self.setIconSize(QtCore.QSize(24, 24))


        # Drop shadow neon glow effect (glow radius 28px)
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self.setGraphicsEffect(self._shadow)

        self.toggled.connect(self._update_neon_style)
        self._update_neon_style(self.isChecked())

    def _update_neon_style(self, checked: bool):
        if checked:
            # Active Omen Autopilot: Spotify Green
            self._shadow.setBlurRadius(20)
            self._shadow.setColor(QtGui.QColor(29, 185, 84, 180))
            self.setStyleSheet(f"""
                QPushButton#BabySmartButton {{
                    background-color: rgba(29, 185, 84, 0.15);
                    border: 1.5px solid {theme.ACCENT_SPOTIFY};
                    color: #ffffff;
                    min-height: 42px;
                    border-radius: {theme.RADIUS_PILL}px;
                    padding: 8px 20px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton#BabySmartButton:hover {{
                    border-color: {theme.ACCENT_ICE};
                }}
            """)
        else:
            # Standby state
            self._shadow.setBlurRadius(0)
            self._shadow.setColor(QtGui.QColor(0, 0, 0, 0))
            self.setStyleSheet(f"""
                QPushButton#BabySmartButton {{
                    background-color: {theme.ACTIVE_NAV};
                    border: 1px solid {theme.BORDER_CARD};
                    color: {theme.TEXT_PRIMARY};
                    min-height: 42px;
                    border-radius: {theme.RADIUS_PILL}px;
                    padding: 8px 20px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton#BabySmartButton:hover {{
                    border-color: {theme.ACCENT_ICE};
                }}
            """)


class ShortcutCard(QtWidgets.QFrame):
    """iOS Shortcuts style widget card:
    - border-radius: 16px
    - icon top-left inside badge
    - title bold 15px
    - primary readout metric (20-24px)
    - subtitle / detail muted 12px
    - Vivid Magenta/Violet Neon (#e024c3) on active, Electric Blue or unlit on standby.
    """
    clicked = QtCore.Signal()

    def __init__(self, title: str, icon_name: str = "", subtitle: str = "",
                 is_interactive: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("ShortcutCard")
        self.is_interactive = is_interactive
        self._is_active = False

        self.setMinimumSize(180, 115)
        if is_interactive:
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # Top row: icon badge + top-right tag
        top_row = QtWidgets.QHBoxLayout()
        self.icon_label = QtWidgets.QLabel()
        self.icon_name = icon_name
        self._update_icon(theme.TEXT_SECONDARY)
        top_row.addWidget(self.icon_label)
        top_row.addStretch()

        self.tag_label = QtWidgets.QLabel("")
        self.tag_label.setObjectName("Muted")
        self.tag_label.setFont(theme.ui_font(11, theme.WEIGHT_MEDIUM))
        top_row.addWidget(self.tag_label)
        layout.addLayout(top_row)

        # Title: uppercase muted letter-spacing 0.8px (matching catalog .card-title)
        self.title_label = QtWidgets.QLabel(title.upper())
        self.title_label.setFont(theme.ui_font(12, theme.WEIGHT_BOLD, tracking=8.0))
        self.title_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.8px;")
        layout.addWidget(self.title_label)

        # Primary Readout Metric (18-20px font-mono)
        self.readout_label = QtWidgets.QLabel("--")
        self.readout_label.setFont(theme.numeric_font(18, theme.WEIGHT_BOLD))
        layout.addWidget(self.readout_label)

        # Subtitle muted 12px
        self.sub_label = QtWidgets.QLabel(subtitle)
        self.sub_label.setObjectName("Muted")
        self.sub_label.setFont(theme.ui_font(12, theme.WEIGHT_REGULAR))
        self.sub_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self.sub_label)

        # Subtle shadow
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self.setGraphicsEffect(self._shadow)
        self.set_active(False)

    def _update_icon(self, color_hex: str):
        if self.icon_name:
            self.icon_label.setPixmap(theme.icon(self.icon_name, color_hex, 22))

    def set_active(self, active: bool):
        self._is_active = active
        accent = theme.ACCENT_ICE
        if active:
            self._shadow.setBlurRadius(14)
            self._shadow.setColor(QtGui.QColor(0, 210, 255, 40))
            self.setStyleSheet(f"""
                QFrame#ShortcutCard {{
                    background-color: {theme.SURFACE_CARD_HOVER};
                    border: 1px solid {accent};
                    border-radius: {theme.RADIUS_CARD}px;
                }}
            """)
            self._update_icon(accent)
        else:
            self._shadow.setBlurRadius(0)
            self._shadow.setColor(QtGui.QColor(0, 0, 0, 0))
            self.setStyleSheet(f"""
                QFrame#ShortcutCard {{
                    background-color: {theme.BG_CARD};
                    border: 1px solid {theme.BORDER_CARD};
                    border-radius: {theme.RADIUS_CARD}px;
                }}
                QFrame#ShortcutCard:hover {{
                    border: 1px solid {theme.BORDER_CONTROL};
                    background-color: {theme.SURFACE_CARD_HOVER};
                }}
            """)
            self._update_icon(theme.TEXT_SECONDARY)

    def set_values(self, readout: str, subtitle: str = "", tag: str = "", color: str | None = None):
        self.readout_label.setText(readout)
        if color:
            self.readout_label.setStyleSheet(f"color: {color};")
        elif color is False:
            self.readout_label.setStyleSheet("")
        if subtitle:
            self.sub_label.setText(subtitle)
        if tag:
            self.tag_label.setText(tag)

    def mousePressEvent(self, event):
        if self.is_interactive:
            self.clicked.emit()
        super().mousePressEvent(event)


class DualThermalCard(QtWidgets.QFrame):
    """Wide top telemetry card combining CPU and GPU temperatures with an antialiased smooth spline heartbeat."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DualThermalCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setStyleSheet(f"""
            QFrame#DualThermalCard {{
                background-color: {theme.BG_CARD};
                border: 1px solid rgba(0, 210, 255, 0.3);
                border-radius: {theme.RADIUS_CARD}px;
            }}
            QFrame#DualThermalCard:hover {{
                border: 1px solid {theme.ACCENT_ICE};
                background-color: {theme.SURFACE_CARD_HOVER};
            }}
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header with card title, live RAPL badge, and status
        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("LIVE HARDWARE PULSE & TEMPERATURES")
        title.setFont(theme.ui_font(12, theme.WEIGHT_BOLD, tracking=8.0))
        title.setStyleSheet(f"color: {theme.TEXT_MUTED}; text-transform: uppercase; letter-spacing: 0.8px;")
        head.addWidget(title)
        head.addStretch()

        self.rapl_badge = QtWidgets.QLabel("RAPL: -- W")
        self.rapl_badge.setFont(theme.numeric_font(12, theme.WEIGHT_BOLD))
        self.rapl_badge.setStyleSheet(
            f"color: {theme.ACCENT_ICE}; background-color: rgba(0, 210, 255, 0.10); "
            f"border: 1px solid rgba(0, 210, 255, 0.25); border-radius: 20px; padding: 2px 10px;"
        )
        self.rapl_badge.setToolTip("Real-time Intel RAPL Package Power Draw (energy_uj)")
        head.addWidget(self.rapl_badge)

        self.overall_status = QtWidgets.QLabel("OPTIMAL")
        self.overall_status.setObjectName("Muted")
        self.overall_status.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.overall_status.setStyleSheet(f"color: {theme.ACCENT_SPOTIFY}; font-weight: 700;")
        head.addWidget(self.overall_status)
        layout.addLayout(head)

        # Dual Telemetry Readout Row (CPU & GPU side-by-side)
        readout_row = QtWidgets.QHBoxLayout()
        readout_row.setSpacing(16)

        # Left: CPU Box (Bound to Ice #00D2FF)
        cpu_box = QtWidgets.QHBoxLayout()
        cpu_box.setSpacing(12)
        cpu_icon = QtWidgets.QLabel()
        cpu_icon.setPixmap(theme.icon("cpu", theme.ACCENT_ICE, 28))
        cpu_box.addWidget(cpu_icon)

        cpu_details = QtWidgets.QVBoxLayout()
        cpu_details.setSpacing(1)
        self.cpu_tag = QtWidgets.QLabel("CPU Core · Intel i7-10750H")
        self.cpu_tag.setObjectName("Muted")
        self.cpu_tag.setFont(theme.ui_font(11, theme.WEIGHT_MEDIUM))
        self.cpu_readout = QtWidgets.QLabel("-- °C")
        self.cpu_readout.setObjectName("Readout")
        self.cpu_readout.setFont(theme.numeric_font(26, theme.WEIGHT_BOLD))
        self.cpu_readout.setStyleSheet(f"color: {theme.ACCENT_ICE};")
        self.cpu_sub = QtWidgets.QLabel("Freq: -- · Load: -- %")
        self.cpu_sub.setObjectName("Secondary")
        self.cpu_sub.setFont(theme.numeric_font(12, theme.WEIGHT_REGULAR))
        cpu_details.addWidget(self.cpu_tag)
        cpu_details.addWidget(self.cpu_readout)
        cpu_details.addWidget(self.cpu_sub)
        cpu_box.addLayout(cpu_details)
        readout_row.addLayout(cpu_box, 1)

        # Vertical separator
        v_div = QtWidgets.QFrame()
        v_div.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        v_div.setStyleSheet(f"background-color: {theme.BORDER_CARD}; max-width: 1px;")
        readout_row.addWidget(v_div)

        # Right: GPU Box (Bound to Spotify #1DB954)
        gpu_box = QtWidgets.QHBoxLayout()
        gpu_box.setSpacing(12)
        gpu_icon = QtWidgets.QLabel()
        gpu_icon.setPixmap(theme.icon("monitor", theme.ACCENT_SPOTIFY, 28))
        gpu_box.addWidget(gpu_icon)

        gpu_details = QtWidgets.QVBoxLayout()
        gpu_details.setSpacing(1)
        self.gpu_tag = QtWidgets.QLabel("NVIDIA RTX 2060 Mobile")
        self.gpu_tag.setObjectName("Muted")
        self.gpu_tag.setFont(theme.ui_font(11, theme.WEIGHT_MEDIUM))
        self.gpu_readout = QtWidgets.QLabel("-- °C")
        self.gpu_readout.setObjectName("Readout")
        self.gpu_readout.setFont(theme.numeric_font(26, theme.WEIGHT_BOLD))
        self.gpu_readout.setStyleSheet(f"color: {theme.ACCENT_SPOTIFY};")
        self.gpu_sub = QtWidgets.QLabel("Clock: -- · Load: -- % · Power: -- W")
        self.gpu_sub.setObjectName("Secondary")
        self.gpu_sub.setFont(theme.numeric_font(12, theme.WEIGHT_REGULAR))
        gpu_details.addWidget(self.gpu_tag)
        gpu_details.addWidget(self.gpu_readout)
        gpu_details.addWidget(self.gpu_sub)
        gpu_box.addLayout(gpu_details)
        readout_row.addLayout(gpu_box, 1)

        layout.addLayout(readout_row)
        layout.addWidget(divider())

        # Dual-Spline Live Graph (CPU Ice & GPU Spotify)
        from . import charts
        self.spline_trace = charts.DualSplineTrace("Thermal Pulse Heartbeat (Dual-Spline)", "°C", height=88)
        layout.addWidget(self.spline_trace)

    def set_values(self, cpu_temp, cpu_freq, cpu_load, gpu_temp, gpu_clk, gpu_load, wattage=None, gpu_power=None):
        c_temp_str = f"{cpu_temp} °C" if cpu_temp is not None else "-- °C"
        self.cpu_readout.setText(c_temp_str)
        freq_str = f"{cpu_freq / 1000:.1f} GHz" if cpu_freq else "--"
        load_str = f"{cpu_load} %" if cpu_load is not None else "--"
        self.cpu_sub.setText(f"Freq: {freq_str} · Load: {load_str}")

        if wattage is not None:
            self.rapl_badge.setText(f"⚡ RAPL: {wattage:.1f} W")
        else:
            self.rapl_badge.setText("⚡ RAPL: -- W")

        g_temp_str = f"{gpu_temp} °C" if gpu_temp is not None else "-- °C"
        self.gpu_readout.setText(g_temp_str)
        clk_str = f"{gpu_clk} MHz" if gpu_clk is not None else "--"
        g_load_str = f"{gpu_load} %" if gpu_load is not None else "--"
        pwr_str = f"{gpu_power:.1f} W" if gpu_power is not None else "-- W"
        self.gpu_sub.setText(f"Clock: {clk_str} · Load: {g_load_str} · Power: {pwr_str}")

        # Push dual CPU and GPU readings to Catmull-Rom cubic Bézier splines
        self.spline_trace.push(cpu_temp, gpu_temp)

        effective = max([t for t in (cpu_temp, gpu_temp) if t is not None], default=0)
        if effective >= 85:
            self.overall_status.setText("CRITICAL THERMAL LOAD")
            self.overall_status.setStyleSheet(f"color: {theme.ACCENT_FIRE}; font-weight: 800;")
        elif effective >= 75:
            self.overall_status.setText("ELEVATED (AUTOPILOT ENGAGED)")
            self.overall_status.setStyleSheet("color: #e4ac59; font-weight: 700;")
        else:
            self.overall_status.setText("OPTIMAL")
            self.overall_status.setStyleSheet(f"color: {theme.ACCENT_SPOTIFY}; font-weight: 700;")


def overline(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text.upper())
    label.setObjectName("Overline")
    label.setFont(theme.overline_font())
    return label


def wrapped(label: QtWidgets.QLabel) -> QtWidgets.QLabel:
    label.setWordWrap(True)
    policy = label.sizePolicy()
    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding)
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    return label


def note(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("Note")
    label.setMaximumWidth(theme.PROSE_MAX)
    return wrapped(label)


def divider() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class Panel(QtWidgets.QFrame):
    """A titled Spotify Matte Dark surface with 16px rounded borders."""

    def __init__(self, title: str = "", subtitle: str = "", cap: bool = False):
        super().__init__()
        self.setObjectName("Panel")
        if cap:
            self.setMaximumWidth(theme.CONTENT_MAX)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(*(theme.SPACE[4],) * 4)
        outer.setSpacing(theme.SPACE[3])

        if title:
            head = QtWidgets.QVBoxLayout()
            head.setSpacing(theme.SPACE[1])
            head.addWidget(overline(title))
            if subtitle:
                head.addWidget(note(subtitle))
            outer.addLayout(head)

        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(theme.SPACE[3])
        outer.addLayout(self.body)

    def add(self, item):
        if isinstance(item, QtWidgets.QLayout):
            self.body.addLayout(item)
        else:
            self.body.addWidget(item)
        return item


# ----------------------------------------------------------------- tiles

class Tile(QtWidgets.QAbstractButton):
    """An iOS Shortcuts style tile with 16px radius and neon glow."""

    def __init__(self, label: str, icon_name: str = "", width: int = 120,
                 height: int = 84, detail: str = ""):
        super().__init__()
        self.label = label
        self.icon_name = icon_name
        self.detail = detail
        self._hover = False
        self.setCheckable(True)
        self.setFixedSize(width, height)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(label)
        if detail:
            self.setAccessibleDescription(detail)
            self.setToolTip(detail)

    def enterEvent(self, _event):
        self._hover = True
        self.update()

    def leaveEvent(self, _event):
        self._hover = False
        self.update()

    def _colours(self):
        accent = theme.get_accent()
        wash = theme.ACCENT_WASH
        if self.isChecked():
            if self.label in ("Max", "Max Overdrive"):
                return theme.OVERDRIVE_WASH, theme.OVERDRIVE_ACCENT, "#ffffff"
            return wash, accent, "#ffffff"
        if self._hover:
            return theme.SURFACE_RAISED, theme.BORDER_CONTROL, theme.TEXT_PRIMARY
        return theme.SURFACE_BASE, theme.BORDER_QUIET, theme.TEXT_SECONDARY

    def paint_glyph(self, painter: QtGui.QPainter, box: QtCore.QRectF, colour: str):
        if not self.icon_name:
            return
        pixmap = theme.icon(self.icon_name, colour, int(box.height()))
        painter.drawPixmap(
            QtCore.QPointF(box.center().x() - box.height() / 2, box.top()),
            pixmap)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        background, border, foreground = self._colours()

        box = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(QtGui.QColor(background))
        painter.setPen(QtGui.QPen(QtGui.QColor(border), 1.5 if self.isChecked() else 1))
        painter.drawRoundedRect(box, theme.RADIUS_PANEL, theme.RADIUS_PANEL)

        glyph = QtCore.QRectF(0, box.top() + theme.SPACE[2], self.width(), 26)
        self.paint_glyph(painter, glyph, foreground)

        painter.setPen(QtGui.QColor(foreground))
        # Adaptive font sizing and horizontal bounds to guarantee zero clipping for long labels (e.g. "HP Windows Tuning")
        avail_w = self.width() - 4
        font_size = theme.SIZE_SMALL
        f = theme.ui_font(font_size, theme.WEIGHT_BOLD if self.isChecked() else theme.WEIGHT_MEDIUM)
        fm = QtGui.QFontMetrics(f)
        while fm.horizontalAdvance(self.label) > avail_w and font_size > 8.5:
            font_size -= 0.5
            f = theme.ui_font(font_size, theme.WEIGHT_BOLD if self.isChecked() else theme.WEIGHT_MEDIUM)
            fm = QtGui.QFontMetrics(f)
        painter.setFont(f)
        painter.drawText(
            QtCore.QRectF(2, self.height() - 26, self.width() - 4, 20),
            QtCore.Qt.AlignmentFlag.AlignCenter, self.label)

        if self.hasFocus():
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.get_accent()), 2))
            painter.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5),
                                    theme.RADIUS_PANEL + 1, theme.RADIUS_PANEL + 1)


class EffectTile(Tile):
    """One lighting effect, with a glyph drawn from what the effect does."""

    def __init__(self, effect: str, width: int = 108, height: int = 80,
                 label: str | None = None, detail: str = ""):
        super().__init__(label or effect.replace("-", " ").title(), "", width,
                         height, detail=detail)
        self.effect = effect

    def paint_glyph(self, painter, box, colour):
        painter.save()
        painter.translate(box.center().x() - 12, box.top())
        pen = QtGui.QPen(QtGui.QColor(colour), 1.8)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        getattr(self, f"_glyph_{self.effect}", self._glyph_static)(painter, colour)
        painter.restore()

    def _glyph_static(self, painter, colour):
        painter.setBrush(QtGui.QColor(colour))
        painter.drawEllipse(QtCore.QPointF(12, 12), 6, 6)

    def _glyph_breathing(self, painter, colour):
        painter.setBrush(QtGui.QColor(colour))
        painter.drawEllipse(QtCore.QPointF(12, 12), 4, 4)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(12, 12), 9, 9)

    def _glyph_heartbeat(self, painter, _colour):
        path = QtGui.QPainterPath(QtCore.QPointF(1, 12))
        for x, y in ((7, 12), (9, 5), (12, 19), (15, 9), (17, 12), (23, 12)):
            path.lineTo(x, y)
        painter.drawPath(path)

    def _glyph_wave(self, painter, _colour):
        path = QtGui.QPainterPath(QtCore.QPointF(1, 12))
        for step in range(1, 25):
            path.lineTo(1 + step, 12 - math.sin(step / 24 * 4 * math.pi) * 6)
        painter.drawPath(path)

    def _glyph_cycle(self, painter, _colour):
        for index in range(12):
            pen = QtGui.QPen(QtGui.QColor.fromHsv(index * 30, 190, 225), 3.2)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(QtCore.QRectF(4, 4, 16, 16), index * 30 * 16, 30 * 16)

    def _glyph_chase(self, painter, colour):
        for index in range(4):
            box = QtCore.QRectF(1 + index * 6, 8, 4.4, 8)
            painter.setBrush(QtGui.QColor(colour) if index == 1 else QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box, 1.2, 1.2)

    def _glyph_fire(self, painter, colour):
        flame = QtGui.QPainterPath(QtCore.QPointF(12, 2))
        flame.cubicTo(QtCore.QPointF(16, 8), QtCore.QPointF(20, 11), QtCore.QPointF(19, 16))
        flame.cubicTo(QtCore.QPointF(18, 21), QtCore.QPointF(14, 22), QtCore.QPointF(12, 22))
        flame.cubicTo(QtCore.QPointF(8, 22), QtCore.QPointF(5, 19), QtCore.QPointF(5, 15))
        flame.cubicTo(QtCore.QPointF(5, 11), QtCore.QPointF(9, 9), QtCore.QPointF(12, 2))
        painter.drawPath(flame)
        painter.setBrush(QtGui.QColor(colour))
        painter.drawEllipse(QtCore.QPointF(12, 17), 2.6, 3.4)

    def _glyph_aurora(self, painter, colour):
        for row in range(3):
            path = QtGui.QPainterPath(QtCore.QPointF(1, 7 + row * 5))
            for step in range(1, 23):
                path.lineTo(1 + step, 7 + row * 5 - math.sin((step / 22 + row * 0.2) * 2 * math.pi) * 2.5)
            painter.drawPath(path)


class TileRow(QtWidgets.QWidget):
    chosen = QtCore.Signal(str)

    def __init__(self, options, tile_factory=None, spacing: int | None = None,
                 tile_width: int = 120):
        super().__init__()
        self.setObjectName("Row")
        self.tiles: dict[str, Tile] = {}
        self._suppress = False

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE[2] if spacing is None else spacing)

        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for key, label, icon_name, detail in options:
            tile = (tile_factory(key) if tile_factory
                    else Tile(label, icon_name, width=tile_width, detail=detail))
            self.setMinimumHeight(tile.height())
            group.addButton(tile)
            tile.clicked.connect(lambda _checked=False, k=key: self._pick(k))
            self.tiles[key] = tile
            row.addWidget(tile)
        row.addStretch()

    def _pick(self, key: str):
        if not self._suppress:
            self.chosen.emit(key)

    def select(self, key: str):
        tile = self.tiles.get(key)
        if tile and not tile.isChecked():
            self._suppress = True
            tile.setChecked(True)
            self._suppress = False


class LayoutTile(Tile):
    def __init__(self, key: str, title: str, colours, width: int = 108, height: int = 80):
        super().__init__(title, "", width, height)
        self.key = key
        self.colours = tuple(colours)

    def paint_glyph(self, painter, box, _colour):
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER_QUIET), 1))
        swatch, gap = 14.0, 3.0
        left = box.center().x() - (len(self.colours) * (swatch + gap) - gap) / 2
        for index, rgb in enumerate(self.colours):
            painter.setBrush(QtGui.QColor(*rgb))
            painter.drawRoundedRect(
                QtCore.QRectF(left + index * (swatch + gap), box.top() + 3, swatch, 18), 3, 3)
        painter.restore()


class EffectGrid(QtWidgets.QWidget):
    chosen = QtCore.Signal(str)

    def __init__(self, effects, columns: int = 5, tile_factory=None):
        super().__init__()
        self.setObjectName("Row")
        self.tiles: dict[str, Tile] = {}
        self._suppress = False

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(theme.SPACE[2])

        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        self._group = group
        for index, effect in enumerate(effects):
            tile = tile_factory(effect) if tile_factory else EffectTile(effect)
            group.addButton(tile)
            tile.clicked.connect(lambda _checked=False, e=effect: self._pick(e))
            self.tiles[effect] = tile
            grid.addWidget(tile, index // columns, index % columns)
        grid.setColumnStretch(columns, 1)

    def _pick(self, effect: str):
        if not self._suppress:
            self.chosen.emit(effect)

    def select(self, effect: str):
        tile = self.tiles.get(effect)
        if tile and not tile.isChecked():
            self._suppress = True
            tile.setChecked(True)
            self._suppress = False

    def set_mixed(self):
        self._suppress = True
        self._group.setExclusive(False)
        for tile in self.tiles.values():
            tile.setChecked(False)
        self._group.setExclusive(True)
        self._suppress = False


# ---------------------------------------------------------------- colour

class ColourWheel(QtWidgets.QWidget):
    picked = QtCore.Signal(QtGui.QColor)

    def __init__(self, diameter: int = 150):
        super().__init__()
        self.setFixedSize(diameter, diameter)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._hue = 186
        self._saturation = 255
        self._value = 255
        self._wheel: QtGui.QPixmap | None = None
        self.setAccessibleName("HSV Colour ring")

    def set_colour(self, colour: QtGui.QColor):
        hue, saturation, value, _ = colour.getHsv()
        self._hue = max(0, hue)
        self._saturation = saturation
        self._value = value
        self.update()

    def colour(self) -> QtGui.QColor:
        return QtGui.QColor.fromHsv(self._hue, self._saturation, self._value)

    def _build_wheel(self):
        side = min(self.width(), self.height())
        image = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        box = QtCore.QRectF(0, 0, side, side)
        outer_r = side / 2.0 - 2
        inner_r = outer_r * 0.65

        hue_ring = QtGui.QConicalGradient(box.center(), 90)
        for step in range(0, 361, 15):
            hue_ring.setColorAt(step / 360.0,
                                QtGui.QColor.fromHsv((360 - step) % 360, 255, 255))

        path = QtGui.QPainterPath()
        path.addEllipse(box.center(), outer_r, outer_r)
        inner = QtGui.QPainterPath()
        inner.addEllipse(box.center(), inner_r, inner_r)
        ring = path.subtracted(inner)

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(hue_ring)
        painter.drawPath(ring)

        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 80), 1))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(box.center(), outer_r, outer_r)
        painter.drawEllipse(box.center(), inner_r, inner_r)

        painter.end()
        self._wheel = QtGui.QPixmap.fromImage(image)

    @staticmethod
    def _angle_for_hue(hue: float) -> float:
        return math.radians(90.0 - hue)

    @staticmethod
    def _hue_for_angle(dx: float, dy: float) -> int:
        return int((90.0 - math.degrees(math.atan2(-dy, dx))) % 360)

    def _from_point(self, point: QtCore.QPointF):
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2)
        delta = point - centre
        self._hue = self._hue_for_angle(delta.x(), delta.y())
        self.update()
        self.picked.emit(self.colour())

    def mousePressEvent(self, event):
        self._from_point(QtCore.QPointF(event.position()))

    def mouseMoveEvent(self, event):
        if event.buttons():
            self._from_point(QtCore.QPointF(event.position()))

    def paintEvent(self, _event):
        if self._wheel is None:
            self._build_wheel()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._wheel)

        side = min(self.width(), self.height())
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2)
        outer_r = side / 2.0 - 2
        inner_r = outer_r * 0.65

        # Inner circular preview disc
        preview_r = inner_r - 4
        current_col = self.colour()
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1.5))
        painter.setBrush(current_col)
        painter.drawEllipse(centre, preview_r, preview_r)

        # Ring selector handle indicator
        mid_r = (outer_r + inner_r) / 2.0
        angle = self._angle_for_hue(self._hue)
        marker = QtCore.QPointF(
            centre.x() + math.cos(angle) * mid_r,
            centre.y() - math.sin(angle) * mid_r
        )
        painter.setPen(QtGui.QPen(QtGui.QColor("#000000"), 3))
        painter.setBrush(current_col)
        painter.drawEllipse(marker, 6, 6)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
        painter.drawEllipse(marker, 6, 6)


class ColourPanel(QtWidgets.QWidget):
    changed = QtCore.Signal(QtGui.QColor)

    PRESETS = ("#e024c3", "#00d2ff", "#40b7c4", "#38d39f", "#e4ac59", "#df6862", "#ffffff")

    def __init__(self):
        super().__init__()
        self.setObjectName("Row")
        self._suppress = False

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE[3])

        self.wheel = ColourWheel()
        self.wheel.picked.connect(self._from_wheel)
        outer.addWidget(self.wheel, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(theme.SPACE[3])

        self.value = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.value.setRange(0, 255)
        self.value.setValue(255)
        self.value.setMinimumWidth(150)
        self.value.setAccessibleName("Colour brightness")
        self.value.valueChanged.connect(self._from_value)

        self.value_label = QtWidgets.QLabel("100%")
        self.value_label.setObjectName("Muted")
        self.value_label.setFont(theme.numeric_font(theme.SIZE_SMALL))

        value_row = QtWidgets.QVBoxLayout()
        value_row.setSpacing(theme.SPACE[1])
        v_head = QtWidgets.QHBoxLayout()
        v_head.addWidget(overline("Brightness (0% - 100%)"))
        v_head.addStretch()
        v_head.addWidget(self.value_label)
        value_row.addLayout(v_head)
        value_row.addWidget(self.value)
        right.addLayout(value_row)

        self.fields = {}
        rgb_row = QtWidgets.QHBoxLayout()
        rgb_row.setSpacing(theme.SPACE[2])
        for channel in ("R", "G", "B"):
            column = QtWidgets.QVBoxLayout()
            column.setSpacing(theme.SPACE[1])
            box = QtWidgets.QSpinBox()
            box.setRange(0, 255)
            box.setFixedWidth(56)
            box.setFont(theme.numeric_font(theme.SIZE_BODY))
            box.valueChanged.connect(self._from_fields)
            self.fields[channel] = box
            column.addWidget(overline(channel))
            column.addWidget(box)
            rgb_row.addLayout(column)
        rgb_row.addStretch()
        right.addLayout(rgb_row)

        presets_column = QtWidgets.QVBoxLayout()
        presets_column.setSpacing(theme.SPACE[1])
        presets_column.addWidget(overline("Quick Swatches"))
        presets = QtWidgets.QHBoxLayout()
        presets.setSpacing(theme.SPACE[2])
        for value in self.PRESETS:
            button = QtWidgets.QPushButton()
            button.setObjectName("Swatch")
            button.setFixedSize(24, 24)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"background: {value}; border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.RADIUS_CONTROL}px;")
            button.setToolTip(value.upper())
            button.clicked.connect(
                lambda _checked=False, v=value: self.set_colour(QtGui.QColor(v), announce=True))
            presets.addWidget(button)
        presets.addStretch()
        presets_column.addLayout(presets)
        right.addLayout(presets_column)

        outer.addLayout(right)
        self.set_colour(QtGui.QColor(theme.get_accent()))

    def colour(self) -> QtGui.QColor:
        return QtGui.QColor(self.fields["R"].value(), self.fields["G"].value(),
                            self.fields["B"].value())

    def set_colour(self, colour: QtGui.QColor, announce: bool = False):
        if not colour.isValid():
            return
        self._suppress = True
        self.wheel.set_colour(colour)
        self.value.setValue(colour.value())
        pct = int(round(colour.value() / 255.0 * 100.0))
        if hasattr(self, "value_label"):
            self.value_label.setText(f"{pct}%")
        for channel, component in zip("RGB", (colour.red(), colour.green(), colour.blue())):
            self.fields[channel].setValue(component)
        self._suppress = False
        if announce:
            self.changed.emit(colour)

    def _emit(self, colour: QtGui.QColor):
        if not self._suppress:
            self.set_colour(colour)
            self.changed.emit(colour)

    def _from_wheel(self, colour: QtGui.QColor):
        self._emit(QtGui.QColor.fromHsv(colour.hue(), colour.saturation(), self.value.value()))

    def _from_value(self, value: int):
        pct = int(round(value / 255.0 * 100.0))
        if hasattr(self, "value_label"):
            self.value_label.setText(f"{pct}%")
        current = self.wheel.colour()
        self._emit(QtGui.QColor.fromHsv(current.hue(), current.saturation(), value))

    def _from_fields(self):
        self._emit(self.colour())


# ------------------------------------------------------------------ fans

class FanCard(QtWidgets.QFrame):
    """Fan telemetry card with turning rotor chart and measured RPM."""

    def __init__(self, channel: int, name: str, footnote: str = ""):
        super().__init__()
        self.setObjectName("Card")
        self.channel = channel

        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(theme.SPACE[4], theme.SPACE[3],
                                theme.SPACE[4], theme.SPACE[3])
        grid.setHorizontalSpacing(theme.SPACE[4])
        grid.setVerticalSpacing(theme.SPACE[2])

        self.rotor = charts.FanRotor(diameter=64)
        grid.addWidget(self.rotor, 0, 0, 2, 1, QtCore.Qt.AlignmentFlag.AlignVCenter)

        title = QtWidgets.QLabel(name)
        title.setFont(theme.ui_font(theme.SIZE_BODY, theme.WEIGHT_BOLD))
        grid.addWidget(title, 0, 1)
        hint = QtWidgets.QLabel(footnote)
        hint.setObjectName("Muted")
        grid.addWidget(hint, 1, 1)

        reading = QtWidgets.QHBoxLayout()
        reading.setSpacing(theme.SPACE[1])
        reading.addStretch()
        self.value = QtWidgets.QLabel("--")
        self.value.setFont(theme.numeric_font(theme.SIZE_READOUT, theme.WEIGHT_REGULAR))
        unit_label = QtWidgets.QLabel("rpm")
        unit_label.setObjectName("Muted")
        reading.addWidget(self.value)
        reading.addWidget(unit_label, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        grid.addLayout(reading, 0, 2)

        measured = QtWidgets.QLabel("measured")
        measured.setObjectName("Muted")
        measured.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(measured, 1, 2, QtCore.Qt.AlignmentFlag.AlignTop
                       | QtCore.Qt.AlignmentFlag.AlignRight)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 5500)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.SURFACE_SUNKEN};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.get_dynamic_accent()};
                border-radius: 2px;
            }}
        """)
        grid.addWidget(self.progress, 2, 0, 1, 3)

    def set_reading(self, rpm):
        self.rotor.set_rpm(rpm)
        self.value.setText("--" if rpm is None else f"{rpm}")
        self.progress.setValue(int(rpm) if rpm else 0)

    def set_overdrive(self, enabled: bool):
        """Toggle Fire (#FF6B00) overdrive illumination with active glow."""
        if enabled:
            self.progress.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {theme.BG_CANVAS};
                    border: none;
                    border-radius: 2px;
                }}
                QProgressBar::chunk {{
                    background-color: {theme.ACCENT_FIRE};
                    border-radius: 2px;
                }}
            """)
            self.value.setStyleSheet(f"color: {theme.ACCENT_FIRE}; font-weight: 800;")
            shadow = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(16)
            shadow.setColor(QtGui.QColor(255, 107, 0, 200))
            shadow.setOffset(0, 0)
            self.setGraphicsEffect(shadow)
        else:
            col = theme.get_dynamic_accent()
            self.progress.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {theme.BG_CANVAS};
                    border: none;
                    border-radius: 2px;
                }}
                QProgressBar::chunk {{
                    background-color: {col};
                    border-radius: 2px;
                }}
            """)
            self.value.setStyleSheet("")
            self.setGraphicsEffect(None)

    def set_power_mode(self, mode: str | None):
        """Update fan card border with colored gradient/accent according to active power mode."""
        if mode in ("low-power", "cool"):
            border_col = theme.ACCENT_ICE
            accent_col = theme.ACCENT_ICE
            glow_col = QtGui.QColor(0, 210, 255, 60)
        elif mode == "balanced":
            border_col = theme.ACCENT_SPOTIFY
            accent_col = theme.ACCENT_SPOTIFY
            glow_col = QtGui.QColor(29, 185, 84, 60)
        elif mode in ("performance", "max"):
            border_col = theme.ACCENT_FIRE
            accent_col = theme.ACCENT_FIRE
            glow_col = QtGui.QColor(255, 107, 0, 80)
        else:
            border_col = theme.BORDER_CARD
            accent_col = theme.get_dynamic_accent()
            glow_col = None

        self.setStyleSheet(f"""
            QFrame#Card {{
                background-color: {theme.SURFACE_CARD};
                border: 1px solid {border_col};
                border-radius: {theme.RADIUS_CARD}px;
            }}
        """)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.SURFACE_SUNKEN};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_col};
                border-radius: 2px;
            }}
        """)
        if glow_col:
            shadow = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(14)
            shadow.setColor(glow_col)
            shadow.setOffset(0, 0)
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)


# ------------------------------------------------------- Left Collapsible Sidebar

class CollapsibleSidebar(QtWidgets.QFrame):
    """Modern Left Sidebar navigation hub.
    - Collapsible: 72px (collapsed, square icons) / 230px (expanded, icons + titles).
    - Centered custom H-logo vector header.
    - User Profile Card & System Info Hub.
    """

    section_changed = QtCore.Signal(int)
    profile_dialog_requested = QtCore.Signal()

    LOGO_PATH = str(theme.icon_path("myomen") or (theme.ICONS / "myomen.svg"))

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.is_expanded = True
        self.setFixedWidth(theme.SIDEBAR_EXPANDED_WIDTH)

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)

        # Header: Royal Blue OMEN Diamond Logo + Title Brand Widget
        self.header_layout = QtWidgets.QHBoxLayout()
        self.header_layout.setContentsMargins(4, 4, 4, 2)
        self.header_layout.setSpacing(10)

        self.brand_icon = QtWidgets.QLabel()
        self.logo_label = self.brand_icon  # backwards compatibility alias
        icon_file = theme.icon_path("myomen") or (theme.ICONS / "myomen.svg")
        if icon_file and os.path.exists(str(icon_file)):
            ico = QtGui.QIcon(str(icon_file))
            self.brand_icon.setPixmap(ico.pixmap(QtCore.QSize(30, 30)))
        self.header_layout.addWidget(self.brand_icon, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.brand_widget = QtWidgets.QWidget()
        self.brand_text_layout = QtWidgets.QVBoxLayout(self.brand_widget)
        self.brand_text_layout.setContentsMargins(0, 0, 0, 0)
        self.brand_text_layout.setSpacing(0)
        self.brand_name = QtWidgets.QLabel("◆ MyOmen Hub")
        self.brand_name.setFont(theme.ui_font(15, theme.WEIGHT_BOLD))
        self.brand_name.setMinimumWidth(130)
        self.brand_name.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.brand_text_layout.addWidget(self.brand_name)
        self.header_layout.addWidget(self.brand_widget)
        self.header_layout.addStretch()
        self._layout.addLayout(self.header_layout)

        # Visible Stylish Neon Toggle Arrow Button Below Logo
        self.toggle_btn = QtWidgets.QPushButton("❮")
        self.toggle_btn.setObjectName("SidebarToggleArrow")
        self.toggle_btn.setFixedHeight(24)
        self.toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.update_toggle_style()
        theme.register_accent_listener(self.update_toggle_style)
        self.toggle_btn.setToolTip("Collapse sidebar")
        self.toggle_btn.clicked.connect(self.toggle_sidebar)
        self._layout.addWidget(self.toggle_btn)

        self._layout.addWidget(divider())

        # Navigation Buttons Group
        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.btn_group.idClicked.connect(self.section_changed.emit)
        self.items: list[tuple[QtWidgets.QPushButton, str, str]] = []

        for index, (title, icon_name, desc) in enumerate(sections):
            clean_title = title.replace("&&", "&")
            btn = QtWidgets.QPushButton(f"  {title}")
            btn.setObjectName("SidebarItem")
            btn.setCheckable(True)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.setIcon(QtGui.QIcon(theme.icon(icon_name, theme.TEXT_SECONDARY, 20)))
            btn.setIconSize(QtCore.QSize(20, 20))
            btn.setToolTip(f"{clean_title}: {desc}")
            self.btn_group.addButton(btn, index)
            self._layout.addWidget(btn)
            self.items.append((btn, title, icon_name))

        self._layout.addStretch()

        # Compatibility dummy properties for MainWindow & persistence engine
        self.profiles = QtWidgets.QComboBox()
        self.save_profile = QtWidgets.QPushButton()
        self.delete_profile = QtWidgets.QPushButton()
        self.user_input = QtWidgets.QLineEdit()
        self.btn_save_name = QtWidgets.QPushButton()
        self.btn_edit_profile = QtWidgets.QPushButton()
        self.user_card = QtWidgets.QWidget()
        self.user_input_container = QtWidgets.QWidget()
        self.user_profile_box = QtWidgets.QWidget()

    def refresh_profiles(self, *args, **kwargs):
        pass

    def update_toggle_style(self, accent: str | None = None):
        col = accent or (theme.get_dynamic_accent() if hasattr(theme, "get_dynamic_accent") else theme.ACCENT_ICE)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton#SidebarToggleArrow {{
                background-color: {theme.ACTIVE_NAV};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: 6px;
                color: {col};
                font-size: 13px;
                font-weight: 800;
                padding: 2px 0px;
            }}
            QPushButton#SidebarToggleArrow:hover {{
                border-color: {theme.ACCENT_ICE};
                color: #ffffff;
            }}
        """)

    def current_profile(self) -> str | None:
        return None

    def select_profile(self, name: str | None):
        pass

    def select(self, index: int):
        btn = self.btn_group.button(index)
        if btn:
            btn.setChecked(True)

    def toggle_sidebar(self):
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.setFixedWidth(theme.SIDEBAR_EXPANDED_WIDTH)
            self.brand_widget.setVisible(True)
            self.brand_name.setVisible(True)
            self.toggle_btn.setText("❮")
            self.toggle_btn.setToolTip("Collapse sidebar")
            for btn, title, _icon in self.items:
                btn.setText(f"  {title}")
                btn.setStyleSheet("")
        else:
            self.setFixedWidth(theme.SIDEBAR_COLLAPSED_WIDTH)
            self.brand_widget.setVisible(False)
            self.brand_name.setVisible(False)
            self.toggle_btn.setText("❯")
            self.toggle_btn.setToolTip("Expand sidebar")
            for btn, _title, _icon in self.items:
                btn.setText("")
                btn.setStyleSheet("text-align: center; padding: 10px 0;")


# ------------------------------------------------------- System Info Dialog

class SystemInfoDialog(QtWidgets.QDialog):
    """Detailed System Info Hub modal displaying full hardware specs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Information — MyOmen")
        self.resize(600, 560)
        self.setMinimumSize(480, 360)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {theme.SURFACE_CANVAS};
                color: #ffffff;
            }}
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        # Header
        head = QtWidgets.QHBoxLayout()
        logo_file = theme.icon_path("myomen") or (theme.ICONS / "myomen.svg")
        if logo_file and os.path.exists(str(logo_file)):
            mark = QtWidgets.QLabel()
            ico = QtGui.QIcon(str(logo_file))
            mark.setPixmap(ico.pixmap(QtCore.QSize(36, 36)))
            head.addWidget(mark)
        t_box = QtWidgets.QVBoxLayout()
        t_box.setSpacing(2)
        title = QtWidgets.QLabel("Hardware & System Specifications")
        title.setFont(theme.ui_font(18, theme.WEIGHT_BOLD))
        sub = QtWidgets.QLabel("MyOmen · Hardware & System Hub")
        sub.setObjectName("Muted")
        t_box.addWidget(title)
        t_box.addWidget(sub)
        head.addLayout(t_box)
        head.addStretch()
        layout.addLayout(head)
        layout.addWidget(divider())

        # Grid of specs
        info = system.detailed_system_info()
        spec_items = [
            ("Platform Model", info.get("model", "--"), "laptop"),
            ("Processor (CPU)", f"{info.get('cpu', '--')}\n{info.get('cpu_full', '')}", "cpu"),
            ("Dedicated GPU", f"{info.get('gpu', '--')}\n{info.get('gpu_driver', '')}", "monitor"),
            ("System Memory", f"{info.get('memory', '--')} ({info.get('memory_full', '')})", "layers"),
            ("Linux OS", info.get("os", "--"), "terminal"),
            ("Kernel Release", info.get("kernel", "--"), "shield"),
            ("Desktop Session", info.get("session", "--"), "layout"),
            ("Audio Subsystem", info.get("audio", "--"), "volume-2"),
            ("Storage Disks", info.get("storage", "--"), "hard-drive"),
            ("BIOS Firmware", f"Version {info.get('firmware', '--')}", "cpu"),
        ]

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        c_layout = QtWidgets.QVBoxLayout(container)
        c_layout.setSpacing(10)

        for label, val, icon_name in spec_items:
            card = QtWidgets.QFrame()
            card.setObjectName("Card")
            card.setStyleSheet(f"""
                QFrame#Card {{
                    background-color: {theme.SURFACE_RAISED};
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                    padding: 8px 12px;
                }}
            """)
            r = QtWidgets.QHBoxLayout(card)
            r.setContentsMargins(10, 8, 10, 8)
            r.setSpacing(12)

            ic = QtWidgets.QLabel()
            ic.setPixmap(theme.icon(icon_name, theme.get_accent(), 22))
            r.addWidget(ic)

            tb = QtWidgets.QVBoxLayout()
            tb.setSpacing(2)
            lbl = QtWidgets.QLabel(label.upper())
            lbl.setObjectName("Overline")
            lbl.setFont(theme.overline_font())
            v = QtWidgets.QLabel(val)
            v.setFont(theme.ui_font(13, theme.WEIGHT_MEDIUM))
            v.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            tb.addWidget(lbl)
            tb.addWidget(v)
            r.addLayout(tb, 1)
            c_layout.addWidget(card)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Close button
        btn_box = QtWidgets.QHBoxLayout()
        btn_box.addStretch()
        close_btn = QtWidgets.QPushButton("Done")
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.get_accent()};
                color: #ffffff;
                font-weight: 700;
                border-radius: 10px;
                padding: 8px;
            }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)


# ------------------------------------------------------- GNOME-Style Quick Settings Popup

class QuickSettingsWidget(QtWidgets.QFrame):
    """Frameless compact popup HUD (320px width) with real-time telemetry strips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setFixedWidth(320)
        self.setStyleSheet(f"""
            QFrame#Panel {{
                background-color: {theme.SURFACE_CARD};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_CARD}px;
            }}
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header / Title
        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("MyOmen HUD")
        title.setFont(theme.ui_font(13, theme.WEIGHT_BOLD))
        head.addWidget(title)
        head.addSpacing(6)

        self.dot = QtWidgets.QLabel("●")
        self.dot.setStyleSheet("color: #1DB954; font-size: 10px;")
        head.addWidget(self.dot)
        head.addStretch()

        self.btn_close = QtWidgets.QPushButton("✕")
        self.btn_close.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Close HUD")
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid {theme.BORDER};
                border-radius: 11px;
                color: #ffffff;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.22);
            }}
        """)
        self.btn_close.clicked.connect(self.hide_popup)
        head.addWidget(self.btn_close)
        layout.addLayout(head)

        # 1. Real-time CPU/GPU Load Strips and Wattage
        strips_box = QtWidgets.QVBoxLayout()
        strips_box.setSpacing(6)

        # CPU strip row
        cpu_head = QtWidgets.QHBoxLayout()
        cpu_lbl = QtWidgets.QLabel("CPU")
        cpu_lbl.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.lbl_cpu_stat = QtWidgets.QLabel("-- °C · -- W")
        self.lbl_cpu_stat.setFont(theme.numeric_font(11))
        self.lbl_cpu_stat.setStyleSheet("color: #00B4D8;")
        cpu_head.addWidget(cpu_lbl)
        cpu_head.addStretch()
        cpu_head.addWidget(self.lbl_cpu_stat)
        strips_box.addLayout(cpu_head)

        self.bar_cpu = QtWidgets.QProgressBar()
        self.bar_cpu.setRange(0, 100)
        self.bar_cpu.setValue(0)
        self.bar_cpu.setTextVisible(False)
        self.bar_cpu.setFixedHeight(6)
        self.bar_cpu.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #007799, stop:1 #00B4D8);
                border-radius: 3px;
            }
        """)
        strips_box.addWidget(self.bar_cpu)

        # GPU strip row
        gpu_head = QtWidgets.QHBoxLayout()
        gpu_lbl = QtWidgets.QLabel("GPU (RTX 2060)")
        gpu_lbl.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.lbl_gpu_stat = QtWidgets.QLabel("-- °C · -- W")
        self.lbl_gpu_stat.setFont(theme.numeric_font(11))
        self.lbl_gpu_stat.setStyleSheet("color: #FF1A35;")
        gpu_head.addWidget(gpu_lbl)
        gpu_head.addStretch()
        gpu_head.addWidget(self.lbl_gpu_stat)
        strips_box.addLayout(gpu_head)

        self.bar_gpu = QtWidgets.QProgressBar()
        self.bar_gpu.setRange(0, 100)
        self.bar_gpu.setValue(0)
        self.bar_gpu.setTextVisible(False)
        self.bar_gpu.setFixedHeight(6)
        self.bar_gpu.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #990018, stop:1 #FF1A35);
                border-radius: 3px;
            }
        """)
        strips_box.addWidget(self.bar_gpu)
        layout.addLayout(strips_box)

        # Compatibility pills for legacy calls
        self.pill_cpu = MiniStat("CPU", "°C")
        self.pill_gpu = MiniStat("GPU", "°C")
        self.pill_load = MiniStat("Load", "%")
        self.pill_ram = MiniStat("RAM", "%")

        layout.addWidget(divider())

        # 2. Fan Speeds and Max Fans Instant Toggle
        fan_box = QtWidgets.QVBoxLayout()
        fan_box.setSpacing(6)
        fan_head = QtWidgets.QHBoxLayout()
        fan_title = QtWidgets.QLabel("Fans")
        fan_title.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.lbl_fan_speed = QtWidgets.QLabel("-- / -- rpm")
        self.lbl_fan_speed.setFont(theme.numeric_font(11))
        self.lbl_fan_speed.setStyleSheet("color: #b3b3b3;")
        fan_head.addWidget(fan_title)
        fan_head.addStretch()
        fan_head.addWidget(self.lbl_fan_speed)
        fan_box.addLayout(fan_head)

        self.btn_max_fans = QtWidgets.QPushButton("  Forced Max Fans (100%)")
        self.btn_max_fans.setIcon(QtGui.QIcon(theme.icon("zap", "#FF1A35", 14)))
        self.btn_max_fans.setCheckable(True)
        self.btn_max_fans.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.btn_max_fans.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_max_fans.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 26, 53, 0.10);
                border: 1px solid rgba(255, 26, 53, 0.35);
                border-radius: 8px;
                padding: 6px;
                color: #ffe6ea;
            }}
            QPushButton:checked {{
                background: rgba(255, 26, 53, 0.35);
                border: 1px solid #FF1A35;
                color: #ffffff;
            }}
        """)
        fan_box.addWidget(self.btn_max_fans)
        layout.addLayout(fan_box)

        layout.addWidget(divider())

        # 3. Power Profile Switcher (Quiet, Balanced, Performance)
        prof_title = QtWidgets.QLabel("Power Profile")
        prof_title.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        layout.addWidget(prof_title)

        prof_row = QtWidgets.QHBoxLayout()
        prof_row.setSpacing(6)
        self.prof_group = QtWidgets.QButtonGroup(self)
        self.prof_group.setExclusive(True)

        self.btn_prof_quiet = QtWidgets.QPushButton("Quiet")
        self.btn_prof_balanced = QtWidgets.QPushButton("Balanced")
        self.btn_prof_perf = QtWidgets.QPushButton("Performance")

        self.prof_buttons = {
            "low-power": self.btn_prof_quiet,
            "balanced": self.btn_prof_balanced,
            "performance": self.btn_prof_perf,
        }

        for p_key, btn in self.prof_buttons.items():
            btn.setCheckable(True)
            btn.setFont(theme.ui_font(11, theme.WEIGHT_SEMIBOLD))
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            self.prof_group.addButton(btn)
            prof_row.addWidget(btn)

        self.btn_prof_quiet.setStyleSheet(f"""
            QPushButton {{ background: rgba(255,255,255,0.06); border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 6px; color: #ccc; }}
            QPushButton:checked {{ background: rgba(29, 185, 84, 0.25); border: 1px solid #1DB954; color: #1DB954; font-weight: bold; }}
        """)
        self.btn_prof_balanced.setStyleSheet(f"""
            QPushButton {{ background: rgba(255,255,255,0.06); border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 6px; color: #ccc; }}
            QPushButton:checked {{ background: rgba(0, 180, 216, 0.25); border: 1px solid #00B4D8; color: #00B4D8; font-weight: bold; }}
        """)
        self.btn_prof_perf.setStyleSheet(f"""
            QPushButton {{ background: rgba(255,255,255,0.06); border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 6px; color: #ccc; }}
            QPushButton:checked {{ background: rgba(255, 26, 53, 0.25); border: 1px solid #FF1A35; color: #FF1A35; font-weight: bold; }}
        """)
        layout.addLayout(prof_row)

        # 4. Quick RGB Preset Chips
        rgb_title = QtWidgets.QLabel("Keyboard RGB Presets")
        rgb_title.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        layout.addWidget(rgb_title)

        chips_row = QtWidgets.QHBoxLayout()
        chips_row.setSpacing(4)
        self.rgb_chips = {}
        for chip_id, chip_label in [
            ("ice", "❄️ Ice"),
            ("neon", "🌌 Cyber"),
            ("crimson", "🔴 Omen"),
            ("deep-matrix", "🟢 Matrix"),
            ("stealth", "🕶️ Off"),
        ]:
            c_btn = QtWidgets.QPushButton(chip_label)
            c_btn.setFont(theme.ui_font(10, theme.WEIGHT_MEDIUM))
            c_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            c_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid {theme.BORDER};
                    border-radius: 6px;
                    padding: 4px 6px;
                    color: #ffffff;
                }}
                QPushButton:hover {{
                    background: rgba(255, 255, 255, 0.16);
                }}
            """)
            chips_row.addWidget(c_btn)
            self.rgb_chips[chip_id] = c_btn
        layout.addLayout(chips_row)

        layout.addWidget(divider())

        # 5. Action Buttons (Open MyOmen & Quit)
        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setSpacing(8)

        self.btn_open = QtWidgets.QPushButton("  Open MyOmen")
        self.btn_open.setIcon(QtGui.QIcon(theme.icon("monitor", "#ffffff", 14)))
        self.btn_open.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.btn_open.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_open.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                padding: 6px 10px;
                color: #ffffff;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.18);
                border-color: {theme.get_dynamic_accent()};
            }}
        """)

        self.btn_quit = QtWidgets.QPushButton("  Quit")
        self.btn_quit.setIcon(QtGui.QIcon(theme.icon("power", "#ff9999", 14)))
        self.btn_quit.setFont(theme.ui_font(11, theme.WEIGHT_BOLD))
        self.btn_quit.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_quit.setStyleSheet("""
            QPushButton {
                background: rgba(223, 104, 98, 0.12);
                border: 1px solid rgba(223, 104, 98, 0.35);
                border-radius: 8px;
                padding: 6px 10px;
                color: #ff9999;
            }
            QPushButton:hover {
                background: rgba(223, 104, 98, 0.28);
                border-color: #ff5555;
                color: #ffffff;
            }
        """)

        actions_row.addWidget(self.btn_open, 2)
        actions_row.addWidget(self.btn_quit, 1)
        layout.addLayout(actions_row)

        # Compatibility handles for any remaining references
        self.btn_baby = QtWidgets.QPushButton("Autopilot")
        self.btn_smart = QtWidgets.QPushButton("Smart")
        self.btn_audio = QtWidgets.QPushButton("Audio")
        self.btn_rgb_rand = QtWidgets.QPushButton("Random")

    def hide_popup(self):
        p = self.window()
        if p:
            p.hide()

    def mousePressEvent(self, event):
        top = self.window()
        if top and event.button() == QtCore.Qt.MouseButton.LeftButton:
            top._drag_pos = event.globalPosition().toPoint() - top.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        top = self.window()
        if top and hasattr(top, "_drag_pos") and top._drag_pos is not None and (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            top.move(event.globalPosition().toPoint() - top._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        top = self.window()
        if top and hasattr(top, "_drag_pos"):
            top._drag_pos = None
        super().mouseReleaseEvent(event)


class QuickSettingsPopup(QtWidgets.QWidget):
    """Floating neon Quick Settings capsule displayed beneath the desktop system tray."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetFixedSize)

        self.widget = QuickSettingsWidget(self)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QtGui.QColor(0, 0, 0, 200))
        shadow.setOffset(0, 4)
        self.widget.setGraphicsEffect(shadow)
        layout.addWidget(self.widget)
        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, "_drag_pos") and self._drag_pos is not None and (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


QuickPopup = QuickSettingsPopup  # alias


# ------------------------------------------------------- Legacy / Compatibility Widgets

class Rail(QtWidgets.QFrame):
    """Compatibility section navigation."""
    changed = QtCore.Signal(int)

    def __init__(self, sections):
        super().__init__()
        self.setObjectName("Rail")
        self.setFixedWidth(theme.SIDEBAR_EXPANDED_WIDTH)

        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(theme.SPACE[3], theme.SPACE[4],
                                  theme.SPACE[3], theme.SPACE[4])
        column.setSpacing(theme.SPACE[1])

        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        for index, (title, icon_name, description) in enumerate(sections):
            button = QtWidgets.QPushButton(f"  {title}")
            button.setObjectName("RailItem")
            button.setCheckable(True)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.setToolTip(description)
            self.group.addButton(button, index)
            column.addWidget(button)
        self.group.idClicked.connect(self.changed)
        if self.group.button(0):
            self.group.button(0).setChecked(True)
        column.addStretch()

    def update_toggle_style(self, accent: str | None = None):
        col = accent or (theme.get_dynamic_accent() if hasattr(theme, "get_dynamic_accent") else theme.ACCENT_ICE)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton#SidebarToggleArrow {{
                background-color: {theme.ACTIVE_NAV};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: 6px;
                color: {col};
                font-size: 13px;
                font-weight: 800;
                padding: 2px 0px;
            }}
            QPushButton#SidebarToggleArrow:hover {{
                border-color: {theme.ACCENT_ICE};
                color: #ffffff;
            }}
        """)

    def current_profile(self) -> str | None:
        return None

    def select_profile(self, name: str | None):
        pass

    def refresh_profiles(self, *args, **kwargs):
        pass

    def select(self, index: int):
        button = self.group.button(index)
        if button:
            button.setChecked(True)


class MiniStat(QtWidgets.QFrame):
    def __init__(self, caption: str, unit: str):
        super().__init__()
        self.setObjectName("Card")
        self.unit = unit
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)

        self.caption = QtWidgets.QLabel(caption)
        self.caption.setObjectName("Muted")
        self.caption.setFont(theme.ui_font(11, theme.WEIGHT_MEDIUM))
        line = QtWidgets.QHBoxLayout()
        line.setSpacing(theme.SPACE[1])
        self.value = QtWidgets.QLabel("--")
        self.value.setFont(theme.numeric_font(16, theme.WEIGHT_BOLD))
        unit_label = QtWidgets.QLabel(unit)
        unit_label.setObjectName("Muted")
        unit_label.setFont(theme.ui_font(11, theme.WEIGHT_REGULAR))
        line.addWidget(self.value)
        line.addWidget(unit_label, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        line.addStretch()

        layout.addWidget(self.caption)
        layout.addLayout(line)

    def set(self, value, tone: str | None = None):
        self.value.setText("--" if value is None else f"{value}")
        self.value.setStyleSheet(
            f"color: {charts.tone_colour(tone).name() if tone else theme.TEXT_PRIMARY};")


class SpecRow(QtWidgets.QWidget):
    def __init__(self, label: str, value: str, tooltip: str = ""):
        super().__init__()
        self.setObjectName("Row")
        column = QtWidgets.QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        caption = QtWidgets.QLabel(label)
        caption.setObjectName("Muted")
        body = wrapped(QtWidgets.QLabel(value))
        body.setFont(theme.ui_font(theme.SIZE_SMALL, theme.WEIGHT_MEDIUM))
        body.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        column.addWidget(caption)
        column.addWidget(body)
        if tooltip:
            body.setToolTip(tooltip)


class WidgetPanel(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Widget")
        self.setFixedWidth(240)

        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        shell.addWidget(scroll)

        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)

        column = QtWidgets.QVBoxLayout(inner)
        column.setContentsMargins(12, 16, 12, 16)
        column.setSpacing(12)

        column.addWidget(overline("Profile"))
        self.profiles = QtWidgets.QComboBox()
        column.addWidget(self.profiles)

        buttons = QtWidgets.QHBoxLayout()
        self.save_profile = QtWidgets.QPushButton("Save…")
        self.delete_profile = QtWidgets.QPushButton("Delete")
        buttons.addWidget(self.save_profile)
        buttons.addWidget(self.delete_profile)
        column.addLayout(buttons)

        self.at_login = QtWidgets.QCheckBox("Apply at login")
        column.addWidget(self.at_login)
        self.autostart = QtWidgets.QCheckBox("Start with computer")
        column.addWidget(self.autostart)
        self.omen_key = QtWidgets.QCheckBox("OMEN key opens window")
        column.addWidget(self.omen_key)

        column.addWidget(divider())
        column.addWidget(overline("Summary"))
        self.summary = {}
        for key, label in (("profile", "Mode"), ("fans", "Fans"),
                           ("keyboard", "Keyboard"), ("audio", "Audio")):
            row = QtWidgets.QHBoxLayout()
            name = QtWidgets.QLabel(label)
            name.setObjectName("Secondary")
            value = QtWidgets.QLabel("--")
            value.setFont(theme.ui_font(theme.SIZE_BODY, theme.WEIGHT_MEDIUM))
            row.addWidget(name)
            row.addStretch()
            row.addWidget(value)
            self.summary[key] = value
            column.addLayout(row)

        column.addStretch()

    def refresh_profiles(self, selected: str | None = None):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        names = state.names()
        self.profiles.addItem("—", None)
        for name in names:
            self.profiles.addItem(name, name)
        wanted = selected if selected in names else None
        index = self.profiles.findData(wanted)
        self.profiles.setCurrentIndex(max(0, index))
        self.profiles.blockSignals(False)

        self.delete_profile.setEnabled(bool(wanted))
        self.at_login.blockSignals(True)
        self.at_login.setEnabled(bool(wanted))
        self.at_login.setChecked(bool(wanted) and state.startup() == wanted)
        self.at_login.blockSignals(False)

    def refresh(self, data: dict, gpu: dict, limit_w, summary: dict, load: dict | None = None):
        for key, value in summary.items():
            if key in self.summary:
                self.summary[key].setText(value)


class StatusLine(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        self.label = wrapped(QtWidgets.QLabel(""))
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)

    def show_error(self, text: str):
        self.label.setText(text)
        self.label.setStyleSheet(f"color: {theme.ALERT};")
        self._timer.start(9000)

    def show_info(self, text: str):
        self.label.setText(text)
        self.label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._timer.start(5000)

    def clear(self):
        self.label.setText("")


# ------------------------------------------------------- Catalog Parity Cards

class PowerPlatformCard(QtWidgets.QFrame):
    """Segmented ACPI power platform profile selector matching catalog."""
    profile_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PowerPlatformCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.setStyleSheet(f"""
            QFrame#PowerPlatformCard {{
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: {theme.RADIUS_CARD}px;
            }}
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("POWER PLATFORM PROFILE")
        title.setFont(theme.ui_font(12, theme.WEIGHT_BOLD, tracking=1.0))
        title.setStyleSheet(f"color: {theme.TEXT_MUTED}; text-transform: uppercase;")
        layout.addWidget(title)

        # Segmented controls: Quiet | Balanced | Performance
        btn_box = QtWidgets.QFrame()
        btn_box.setStyleSheet(f"""
            QFrame {{
                background-color: {theme.BG_CANVAS};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: 8px;
            }}
        """)
        btn_layout = QtWidgets.QHBoxLayout(btn_box)
        btn_layout.setContentsMargins(4, 4, 4, 4)
        btn_layout.setSpacing(4)

        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)

        mode_specs = [
            ("Quiet", "low-power"),
            ("Balanced", "balanced"),
            ("Performance", "performance"),
        ]
        self.buttons = {}
        for label, mode_id in mode_specs:
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setFont(theme.ui_font(12, theme.WEIGHT_MEDIUM))
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {theme.TEXT_MUTED};
                    border: none;
                    border-radius: 6px;
                    padding: 8px 14px;
                }}
                QPushButton:checked {{
                    color: {theme.ACCENT_ICE};
                    background-color: rgba(0, 180, 216, 0.08);
                    border: 1px solid {theme.ACCENT_ICE};
                    font-weight: bold;
                }}
            """)
            self.btn_group.addButton(btn)
            btn_layout.addWidget(btn)
            self.buttons[mode_id] = btn
            self.buttons[label.lower()] = btn
            btn.clicked.connect(lambda _, m=mode_id: self.profile_changed.emit(m))

        self.buttons["balanced"].setChecked(True)
        layout.addWidget(btn_box)

        sysfs_lbl = QtWidgets.QLabel("ACPI sysfs: /sys/firmware/acpi/platform_profile")
        sysfs_lbl.setFont(theme.numeric_font(10, theme.WEIGHT_REGULAR))
        sysfs_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; margin-top: 6px;")
        layout.addWidget(sysfs_lbl)

    def set_active_profile(self, profile: str):
        p = (profile or "balanced").lower()
        if p == "quiet":
            p = "low-power"
        elif p == "max":
            p = "performance"
        if p in self.buttons:
            self.buttons[p].setChecked(True)


class AutopilotFansCard(QtWidgets.QFrame):
    """Dynamic hysteresis fans telemetry card with progress bars."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AutopilotFansCard")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.setStyleSheet(f"""
            QFrame#AutopilotFansCard {{
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER_CARD};
                border-radius: {theme.RADIUS_CARD}px;
            }}
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("OMEN AUTOPILOT FANS")
        title.setFont(theme.ui_font(12, theme.WEIGHT_BOLD, tracking=1.0))
        title.setStyleSheet(f"color: {theme.TEXT_MUTED}; text-transform: uppercase;")
        layout.addWidget(title)

        # CPU Fan Row
        cpu_row = QtWidgets.QHBoxLayout()
        cpu_lbl = QtWidgets.QLabel("CPU Fan (hp_wmi fan1)")
        cpu_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        self.cpu_rpm = QtWidgets.QLabel("2450 RPM")
        self.cpu_rpm.setFont(theme.numeric_font(12, theme.WEIGHT_BOLD))
        self.cpu_rpm.setStyleSheet("color: #FFFFFF;")
        cpu_row.addWidget(cpu_lbl)
        cpu_row.addStretch()
        cpu_row.addWidget(self.cpu_rpm)
        layout.addLayout(cpu_row)

        self.cpu_bar = QtWidgets.QProgressBar()
        self.cpu_bar.setRange(0, 5000)
        self.cpu_bar.setValue(2450)
        self.cpu_bar.setTextVisible(False)
        self.cpu_bar.setFixedHeight(4)
        self.cpu_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: #222222; border-radius: 2px; border: none; }}
            QProgressBar::chunk {{ background-color: {theme.ACCENT_ICE}; border-radius: 2px; }}
        """)
        layout.addWidget(self.cpu_bar)

        # GPU Fan Row
        gpu_row = QtWidgets.QHBoxLayout()
        gpu_lbl = QtWidgets.QLabel("GPU Fan (hp_wmi fan2)")
        gpu_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        self.gpu_rpm = QtWidgets.QLabel("2100 RPM")
        self.gpu_rpm.setFont(theme.numeric_font(12, theme.WEIGHT_BOLD))
        self.gpu_rpm.setStyleSheet("color: #FFFFFF;")
        gpu_row.addWidget(gpu_lbl)
        gpu_row.addStretch()
        gpu_row.addWidget(self.gpu_rpm)
        layout.addLayout(gpu_row)

        self.gpu_bar = QtWidgets.QProgressBar()
        self.gpu_bar.setRange(0, 5000)
        self.gpu_bar.setValue(2100)
        self.gpu_bar.setTextVisible(False)
        self.gpu_bar.setFixedHeight(4)
        self.gpu_bar.setStyleSheet(f"""
            QProgressBar {{ background-color: #222222; border-radius: 2px; border: none; }}
            QProgressBar::chunk {{ background-color: {theme.ACCENT_ICE}; border-radius: 2px; }}
        """)
        layout.addWidget(self.gpu_bar)

    def set_fans(self, f1: int, f2: int):
        self.cpu_rpm.setText(f"{f1} RPM")
        self.cpu_bar.setValue(min(5000, max(0, f1)))
        self.gpu_rpm.setText(f"{f2} RPM")
        self.gpu_bar.setValue(min(5000, max(0, f2)))
