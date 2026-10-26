"""The keyboard, drawn, with every key in its zone's current colour.

A list of four zone names says nothing about where "centre" stops and "right"
starts; a picture of the keys does. Each key is filled with the colour of the
zone it belongs to, so the window shows the same picture the keyboard does, and
clicking any key selects its zone.

The firmware exposes four colour slots and no key map, and HP's four-zone split
is only documented as "left, WASD, middle, right". The boundaries here are drawn
from the usual OMEN 15 layout, and all four were checked by eye against the real
keyboard on this machine on 2026-09-28.

Interface: selection_changed, set_zone, set_selection, selected.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from . import theme

#: Rows of (label, width in key units). Main block is 15 units wide; the
#: numpad sits after a half-unit gap. Row 0 is the short function row.
MAIN_ROWS = [
    [("Esc", 1)] + [(f"F{i}", 1) for i in range(1, 13)] + [("PrtSc", 1), ("Del", 1)],
    [("`", 1)] + [(c, 1) for c in "1234567890"] + [("-", 1), ("=", 1), ("⌫", 2)],
    [("Tab", 1.5)] + [(c, 1) for c in "QWERTYUIOP"] + [("[", 1), ("]", 1), ("\\", 1.5)],
    [("Caps", 1.75)] + [(c, 1) for c in "ASDFGHJKL"] + [(";", 1), ("'", 1), ("Enter", 2.25)],
    [("Shift", 2.25)] + [(c, 1) for c in "ZXCVBNM"] + [(",", 1), (".", 1), ("/", 1), ("Shift", 2.75)],
    [("Ctrl", 1.25), ("Fn", 1), ("Win", 1.25), ("Alt", 1.25), ("", 5.25),
     ("Alt", 1), ("Ctrl", 1), ("◀", 1), ("▲▼", 1), ("▶", 1)],
]
NUMPAD_ROWS = [
    [("Home", 1), ("PgUp", 1), ("PgDn", 1), ("End", 1)],
    [("Num", 1), ("/", 1), ("*", 1), ("-", 1)],
    [("7", 1), ("8", 1), ("9", 1), ("+", 1)],
    [("4", 1), ("5", 1), ("6", 1), ("", 1)],
    [("1", 1), ("2", 1), ("3", 1), ("⏎", 1)],
    [("0", 2), (".", 1), ("", 1)],
]
NUMPAD_X = 15.5
TOTAL_UNITS = NUMPAD_X + 4
FUNCTION_ROW_HEIGHT = 0.7

WASD_KEYS = {(2, "W"), (3, "A"), (3, "S"), (3, "D")}

#: Where the main block changes zone, in key units from the left edge.
LEFT_END = 5.25
CENTRE_END = 10.25


def _zone_for(row: int, label: str, centre_x: float) -> str:
    if (row, label) in WASD_KEYS:
        return "wasd"
    if centre_x >= CENTRE_END:
        return "right"
    if centre_x >= LEFT_END:
        return "center"
    return "left"


def _layout():
    """[(zone, label, x, y, w, h)] in key units."""
    keys = []
    y = 0.0
    for row, spec in enumerate(MAIN_ROWS):
        height = FUNCTION_ROW_HEIGHT if row == 0 else 1.0
        x = 0.0
        for label, width in spec:
            keys.append((_zone_for(row, label, x + width / 2), label,
                         x, y, width, height))
            x += width
        y += height
    y = 0.0
    for row, spec in enumerate(NUMPAD_ROWS):
        height = FUNCTION_ROW_HEIGHT if row == 0 else 1.0
        x = NUMPAD_X
        for label, width in spec:
            keys.append(("right", label, x, y, width, height))
            x += width
        y += height
    return keys


KEYS = _layout()
TOTAL_ROWS = FUNCTION_ROW_HEIGHT + len(MAIN_ROWS) - 1


class KeyboardMap(QtWidgets.QWidget):
    """Interactive plan of the four zones. Emits the selection when it changes."""

    selection_changed = QtCore.Signal(set)

    def __init__(self, zone_titles: dict):
        super().__init__()
        self.zone_titles = zone_titles
        self.order = [z for z in zone_titles]
        self.colours: dict[str, tuple] = {z: (0, 0, 0) for z in self.order}
        self.lit: dict[str, bool] = {z: False for z in self.order}
        self.selected: set[str] = {self.order[0]} if self.order else set()
        self._focus_index = 0
        self._hover: str | None = None

        self.setMinimumSize(420, 170)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Preferred)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Keyboard lighting map")
        self._describe()

    def sizeHint(self):
        return QtCore.QSize(640, 240)

    def heightForWidth(self, width: int) -> int:
        return int(width * TOTAL_ROWS / TOTAL_UNITS) + 24

    def hasHeightForWidth(self) -> bool:
        return True

    # ---------------------------------------------------------------- state

    def set_zone(self, zone: str, rgb: tuple, lit: bool):
        if self.colours.get(zone) != rgb or self.lit.get(zone) != lit:
            self.colours[zone] = rgb
            self.lit[zone] = lit
            self.update()

    def set_selection(self, zones: set):
        zones = {z for z in zones if z in self.colours}
        if zones and zones != self.selected:
            self.selected = zones
            self._describe()
            self.update()
            self.selection_changed.emit(set(self.selected))

    def _describe(self):
        names = ", ".join(self.zone_titles[z] for z in self.order
                          if z in self.selected)
        self.setAccessibleDescription(
            f"{len(self.order)} zones. Selected: {names or 'none'}. "
            "Arrow keys move, space adds to the selection.")

    # ------------------------------------------------------------- geometry

    def _unit(self) -> tuple[float, QtCore.QPointF]:
        margin = 10
        unit = min((self.width() - margin * 2) / TOTAL_UNITS,
                   (self.height() - margin * 2) / TOTAL_ROWS)
        origin = QtCore.QPointF((self.width() - unit * TOTAL_UNITS) / 2,
                                (self.height() - unit * TOTAL_ROWS) / 2)
        return unit, origin

    def _key_rect(self, key, unit, origin) -> QtCore.QRectF:
        _zone, _label, x, y, w, h = key
        gap = max(1.5, unit * 0.08)
        return QtCore.QRectF(origin.x() + x * unit + gap / 2,
                             origin.y() + y * unit + gap / 2,
                             w * unit - gap, h * unit - gap)

    def _zone_at(self, point: QtCore.QPointF) -> str | None:
        unit, origin = self._unit()
        for key in KEYS:
            if self._key_rect(key, unit, origin).contains(point):
                return key[0]
        return None

    # ---------------------------------------------------------------- input

    def mousePressEvent(self, event):
        zone = self._zone_at(QtCore.QPointF(event.position()))
        if zone is None:
            return
        self._focus_index = self.order.index(zone)
        if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            selection = set(self.selected)
            selection.symmetric_difference_update({zone})
            self.set_selection(selection or {zone})
        else:
            self.set_selection({zone})

    def mouseMoveEvent(self, event):
        zone = self._zone_at(QtCore.QPointF(event.position()))
        if zone != self._hover:
            self._hover = zone
            self.setToolTip(self.zone_titles.get(zone, "") if zone else "")
            self.update()

    def leaveEvent(self, _event):
        self._hover = None
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        step = {QtCore.Qt.Key.Key_Right: 1, QtCore.Qt.Key.Key_Down: 1,
                QtCore.Qt.Key.Key_Left: -1, QtCore.Qt.Key.Key_Up: -1}.get(key)
        if step:
            self._focus_index = (self._focus_index + step) % len(self.order)
            self.set_selection({self.order[self._focus_index]})
            self.update()
        elif key in (QtCore.Qt.Key.Key_Space, QtCore.Qt.Key.Key_Return):
            zone = self.order[self._focus_index]
            selection = set(self.selected)
            selection.symmetric_difference_update({zone})
            self.set_selection(selection or {zone})
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------------------- drawing

    def _fill(self, zone: str) -> QtGui.QColor:
        if not self.lit.get(zone):
            return QtGui.QColor(theme.SURFACE_SUNKEN)
        return QtGui.QColor(*self.colours.get(zone, (0, 0, 0)))

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        unit, origin = self._unit()

        deck = QtCore.QRectF(origin.x() - 6, origin.y() - 6,
                             unit * TOTAL_UNITS + 12, unit * TOTAL_ROWS + 12)
        painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1.2))
        painter.setBrush(QtGui.QColor(theme.SURFACE_BASE))
        painter.drawRoundedRect(deck, 8, 8)

        focus_zone = self.order[self._focus_index] if self.hasFocus() else None
        label_font = theme.ui_font(max(7, int(unit * 0.26)))
        painter.setFont(label_font)

        for key in KEYS:
            zone, label = key[0], key[1]
            rect = self._key_rect(key, unit, origin)
            fill = self._fill(zone)

            if zone in self.selected:
                pen = QtGui.QPen(QtGui.QColor(theme.TEXT_PRIMARY), 1.8)
            elif zone == self._hover:
                pen = QtGui.QPen(QtGui.QColor(theme.TEXT_SECONDARY), 1.3)
            else:
                pen = QtGui.QPen(QtGui.QColor(theme.BORDER_CONTROL), 1.0)
            if zone == focus_zone:
                pen = QtGui.QPen(QtGui.QColor(theme.ACCENT), 1.8,
                                 QtCore.Qt.PenStyle.DashLine)

            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 3, 3)

            if label and unit >= 22:
                # Legible on any key colour: dark text on light keys.
                # Perceived brightness, not HSL lightness: pure green and
                # yellow are as "dark" as navy by lightness, and bright to the eye.
                luma = (0.2126 * fill.redF() + 0.7152 * fill.greenF()
                        + 0.0722 * fill.blueF())
                light = luma > 0.5 and self.lit.get(zone)
                painter.setPen(QtGui.QColor("#1b1b1f" if light else theme.TEXT_SECONDARY))
                painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)
