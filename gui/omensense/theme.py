"""Design tokens and the Qt stylesheet for MyOmen.

Spotify Dark (#0F1012 Canvas, #16171A Cards, #282828 Borders, 12px radii).
Dynamic keyboard-to-app RGB theme synchronization.
"""

from __future__ import annotations

import pathlib
from pathlib import Path
from PySide6 import QtCore, QtGui

ICONS = Path(__file__).parent / "icons"
LUCIDE = ICONS / "lucide"

# ------------------------------------------------------------- Catalog Design Tokens
BG_CANVAS = "#0F1012"
BG_SIDEBAR = "#0B0C0E"
BG_CARD = "#16171A"
BORDER_CARD = "#282828"
ACTIVE_NAV = "#1C1D22"
ACCENT_ICE = "#00D2FF"
ACCENT_SPOTIFY = "#1DB954"
ACCENT_FIRE = "#FF6B00"
TEXT_PRIMARY = "#FFFFFF"
TEXT_MUTED = "#8E8E93"
FONT_MONO = "SF Mono, JetBrains Mono, monospace"

# ------------------------------------------------------------- Surfaces & Compatibility
SURFACE_CANVAS = BG_CANVAS
SURFACE_SUNKEN = BG_SIDEBAR
SURFACE_BASE = BG_SIDEBAR
SURFACE_RAISED = ACTIVE_NAV
SURFACE_CARD = BG_CARD
SURFACE_CARD_HOVER = "#1B1C20"

# Borders
BORDER_QUIET = BORDER_CARD
BORDER = BORDER_CARD
BORDER_CONTROL = "#383838"

# Text
CHALK_100 = TEXT_PRIMARY
CHALK_200 = "#eaedf1"
CHALK_300 = "#b3b3b3"
CHALK_500 = TEXT_MUTED

TEXT_SECONDARY = CHALK_300

# ------------------------------------------------------------- Core Brand Accents
ACCENT_EMERALD = ACCENT_SPOTIFY   # Stable Spotify Emerald
ACCENT_CYAN = ACCENT_ICE          # Ice Cyan
ACCENT_CRIMSON = ACCENT_FIRE      # High-Performance Fire

# ------------------------------------------------------------- Cyberpunk & Neon
NEON_CYAN = ACCENT_ICE
NEON_CYAN_BG = "rgba(0, 210, 255, 0.08)"
NEON_CYAN_TEXT = "#e0f7ff"
NEON_CYAN_GLOW = QtGui.QColor(0, 210, 255, 180)

NEON_MAGENTA = ACCENT_FIRE
NEON_MAGENTA_BG = "rgba(255, 107, 0, 0.15)"
NEON_MAGENTA_TEXT = "#fff0e6"
NEON_MAGENTA_GLOW = QtGui.QColor(255, 107, 0, 230)

OVERDRIVE_ACCENT = ACCENT_FIRE
OVERDRIVE_WASH = "rgba(255, 107, 0, 0.2)"

# Semantic
WARN = "#e4ac59"
ALERT = ACCENT_FIRE
OK = ACCENT_SPOTIFY       # Spotify green / success

# ------------------------------------------------------------- Dynamic Accent State
DYNAMIC_ACCENT = ACCENT_ICE
DYNAMIC_ACCENT_DIM = "#008fae"
DYNAMIC_ACCENT_WASH = "rgba(0, 210, 255, 0.15)"
THEME_MODE = "auto"  # "auto" (sync with keyboard) vs "manual" (custom in-app color)

ACCENT = DYNAMIC_ACCENT
ACCENT_DIM = DYNAMIC_ACCENT_DIM
ACCENT_WASH = DYNAMIC_ACCENT_WASH

_accent_subscribers = []

def register_accent_listener(callback):
    """Register callback(hex_color: str) when app accent is synchronized."""
    _accent_subscribers.append(callback)

def get_dynamic_accent() -> str:
    return DYNAMIC_ACCENT

def get_accent() -> str:
    return DYNAMIC_ACCENT

def get_theme_mode() -> str:
    return THEME_MODE

def set_theme_mode(mode: str):
    global THEME_MODE
    THEME_MODE = mode if mode in ("auto", "manual") else "auto"

def set_dynamic_accent(color: QtGui.QColor | str):
    global DYNAMIC_ACCENT, DYNAMIC_ACCENT_DIM, DYNAMIC_ACCENT_WASH, ACCENT, ACCENT_DIM, ACCENT_WASH
    if isinstance(color, QtGui.QColor):
        hex_col = color.name()
        r, g, b = color.red(), color.green(), color.blue()
    else:
        hex_col = color
        qc = QtGui.QColor(color)
        if not qc.isValid():
            return
        r, g, b = qc.red(), qc.green(), qc.blue()

    DYNAMIC_ACCENT = hex_col
    DYNAMIC_ACCENT_WASH = f"rgba({r}, {g}, {b}, 0.18)"
    DYNAMIC_ACCENT_DIM = f"rgba({r}, {g}, {b}, 0.50)"
    ACCENT = DYNAMIC_ACCENT
    ACCENT_WASH = DYNAMIC_ACCENT_WASH
    ACCENT_DIM = DYNAMIC_ACCENT_DIM

    for cb in _accent_subscribers:
        try:
            cb(hex_col)
        except Exception:
            pass

# ---------------------------------------------------------------- Scale & Typography
SPACE = {0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 24, 6: 32, 7: 48}

RADIUS_CONTROL = 20
RADIUS_PANEL = 12
RADIUS_CARD = 12
RADIUS_WINDOW = 16
RADIUS_PILL = 20

FONT_UI = "-apple-system, BlinkMacSystemFont, SF Pro Display, SF Pro Text, Inter, sans-serif"
FONT_NUM = "SF Mono"

SIZE_OVERLINE = 10
SIZE_SMALL = 12
SIZE_BODY = 14
SIZE_HEADING = 16
SIZE_TITLE = 20
SIZE_READOUT = 28

WEIGHT_REGULAR = QtGui.QFont.Weight.Normal
WEIGHT_MEDIUM = QtGui.QFont.Weight.Medium
WEIGHT_SEMIBOLD = QtGui.QFont.Weight.DemiBold
WEIGHT_BOLD = QtGui.QFont.Weight.Bold

# Collapsible Sidebar Geometry
SIDEBAR_COLLAPSED_WIDTH = 72
SIDEBAR_EXPANDED_WIDTH = 230
CONTENT_MAX = 1000
PROSE_MAX = 700


def numeric_font(size: int = 14, weight=WEIGHT_MEDIUM) -> QtGui.QFont:
    font = QtGui.QFont()
    font.setFamilies(["SF Mono", "JetBrains Mono", "monospace"])
    font.setPixelSize(size)
    font.setWeight(weight)
    font.setFeature(QtGui.QFont.Tag("tnum"), 1)
    return font


def ui_font(size: int = SIZE_BODY, weight=WEIGHT_REGULAR, tracking: float = 0.0) -> QtGui.QFont:
    font = QtGui.QFont()
    font.setFamilies(["-apple-system", "BlinkMacSystemFont", "SF Pro Display", "SF Pro Text", "Inter", "sans-serif"])
    font.setPixelSize(size)
    font.setWeight(weight)
    if tracking:
        font.setLetterSpacing(QtGui.QFont.SpacingType.PercentageSpacing, 100 + tracking)
    return font


def overline_font() -> QtGui.QFont:
    return ui_font(SIZE_OVERLINE, WEIGHT_SEMIBOLD, tracking=8.0)


INLINE_ICONS = {
    "wrench": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    "sun": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>',
    "x": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    "sliders": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/><line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/><line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/></svg>',
    "sparkles": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>',
    "power": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>',
    "monitor": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>',
    "keyboard": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="M6 8h.01"/><path d="M10 8h.01"/><path d="M14 8h.01"/><path d="M18 8h.01"/><path d="M6 12h.01"/><path d="M18 12h.01"/><path d="M10 12h4"/></svg>',
    "cpu": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9"/><path d="M9 1v3"/><path d="M15 1v3"/><path d="M9 20v3"/><path d="M15 20v3"/><path d="M20 9h3"/><path d="M20 14h3"/><path d="M1 9h3"/><path d="M1 14h3"/></svg>',
    "layers": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 12.5-9.17 4.16a2 2 0 0 1-1.66 0L2 12.5"/><path d="m22 17.5-9.17 4.16a2 2 0 0 1-1.66 0L2 17.5"/></svg>',
    "shield": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>',
    "terminal": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>',
    "hard-drive": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" x2="2" y1="12" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" x2="6.01" y1="16" y2="16"/><line x1="10" x2="10.01" y1="16" y2="16"/></svg>',
    "layout": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>',
    "laptop": '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16"/></svg>',
}


def icon(name: str, colour: str = TEXT_SECONDARY, size: int = 20) -> QtGui.QPixmap:
    markup = None
    path = LUCIDE / f"{name}.svg"
    if path.exists():
        try:
            markup = path.read_text()
        except OSError:
            markup = None
    if markup is None:
        path = ICONS / f"{name}.svg"
        if path.exists():
            try:
                markup = path.read_text()
            except OSError:
                markup = None
    if markup is None:
        markup = INLINE_ICONS.get(name)

    if not markup:
        return QtGui.QPixmap()

    screen = QtGui.QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    edge = max(1, int(round(size * ratio)))

    try:
        content = (markup
                   .replace("currentColor", colour)
                   .replace('width="24"', f'width="{edge}"', 1)
                   .replace('height="24"', f'height="{edge}"', 1))
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(QtCore.QByteArray(content.encode()), "SVG")
        pixmap.setDevicePixelRatio(ratio)
        return pixmap
    except Exception:
        return QtGui.QPixmap()


def icon_path(name: str) -> Path | None:
    """Resolve an icon to its filesystem Path if available."""
    for candidate in [
        ICONS / f"{name}.svg",
        LUCIDE / f"{name}.svg",
        Path("/usr/share/icons/hicolor/scalable/apps") / f"{name}.svg",
        Path.home() / ".local/share/icons/hicolor/scalable/apps" / f"{name}.svg",
        Path("/usr/share/pixmaps") / f"{name}.svg",
    ]:
        if candidate.is_file():
            return candidate
    return None


def stylesheet() -> str:
    """Compose the Spotify Matte Dark & Catalog Luxe stylesheet."""
    return f"""
    QMainWindow, QWidget#Canvas, QWidget#Root {{
        background-color: {BG_CANVAS};
        color: {TEXT_PRIMARY};
        font-family: {FONT_UI};
        font-size: {SIZE_BODY}px;
    }}

    QLabel, QCheckBox, QRadioButton, QSlider {{
        background: transparent;
    }}
    QWidget#Row, QWidget#Pane > QWidget, QScrollArea, QScrollArea > QWidget {{
        background: transparent;
    }}

    /* ---- Navigation Sidebar ------------------------------------------- */
    QWidget#Sidebar {{
        background-color: {BG_SIDEBAR};
        border-right: 1px solid {BORDER_CARD};
    }}

    QPushButton#SidebarItem {{
        background: transparent;
        border: none;
        border-radius: 8px;
        color: {TEXT_MUTED};
        text-align: left;
        padding: 10px 12px;
        min-height: 38px;
        font-size: 13px;
        font-weight: 500;
        margin-bottom: 4px;
    }}
    QPushButton#SidebarItem:hover {{
        background: {ACTIVE_NAV};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#SidebarItem:checked {{
        background: {ACTIVE_NAV};
        border-left: 3px solid {ACCENT_ICE};
        color: #ffffff;
    }}

    /* ---- Panels & Cards -------------------------------- */
    QWidget#Pane {{
        background-color: {BG_CANVAS};
    }}

    QFrame#Panel, QWidget#Panel {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER_CARD};
        border-radius: {RADIUS_CARD}px;
    }}

    QFrame#Card, QFrame#ShortcutCard, QFrame#TelemetryCard, QFrame#ElevatedTelemetryCard, QFrame#ProfileHubCard, QFrame#DualThermalCard {{
        background-color: {BG_CARD};
        border: 1px solid {BORDER_CARD};
        border-radius: {RADIUS_CARD}px;
    }}
    QFrame#Card:hover, QFrame#ShortcutCard:hover, QFrame#TelemetryCard:hover, QFrame#ElevatedTelemetryCard:hover, QFrame#ProfileHubCard:hover, QFrame#DualThermalCard:hover {{
        border: 1px solid {BORDER_CONTROL};
        background-color: {SURFACE_CARD_HOVER};
    }}

    QFrame#Divider {{
        background: {BORDER_CARD};
        border: none;
        max-height: 1px;
    }}

    /* ---- Type roles --------------------------------------------------- */
    QLabel#Overline {{
        color: {TEXT_MUTED};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.8px;
    }}
    QLabel#Muted {{
        color: {TEXT_MUTED};
        font-size: {SIZE_SMALL}px;
    }}
    QLabel#Secondary {{
        color: {TEXT_SECONDARY};
        font-size: {SIZE_BODY}px;
    }}
    QLabel#Note {{
        color: {TEXT_MUTED};
        font-size: {SIZE_SMALL}px;
    }}
    QLabel#Wordmark {{
        color: {TEXT_PRIMARY};
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#Readout {{
        color: {TEXT_PRIMARY};
        font-family: "{FONT_NUM}", "JetBrains Mono", monospace;
        font-size: {SIZE_READOUT}px;
        font-weight: 700;
    }}

    /* ---- Buttons & Controls ------------------------------------------- */
    QPushButton {{
        background-color: {ACTIVE_NAV};
        border: 1px solid {BORDER_CARD};
        border-radius: {RADIUS_PILL}px;
        color: {TEXT_PRIMARY};
        padding: 6px 14px;
        min-height: 28px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        border-color: {ACCENT_ICE};
        background-color: {SURFACE_CARD_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {SURFACE_SUNKEN};
    }}
    QPushButton:disabled {{
        color: {TEXT_MUTED};
        border-color: {BORDER_CARD};
    }}

    QPushButton#Pill {{
        background-color: {ACTIVE_NAV};
        border: 1px solid {BORDER_CARD};
        border-radius: {RADIUS_PILL}px;
        color: {TEXT_MUTED};
        padding: 6px 14px;
        min-height: 24px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#Pill:hover {{
        border-color: {ACCENT_ICE};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#Pill:checked {{
        background-color: {ACTIVE_NAV};
        border: 1px solid {ACCENT_ICE};
        color: #ffffff;
    }}

    /* Quick Action Pill Button */
    QPushButton#NeonActionPill {{
        background-color: {ACTIVE_NAV};
        border: 1px solid {BORDER_CARD};
        border-radius: {RADIUS_PILL}px;
        color: #ffffff;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#NeonActionPill:hover {{
        background-color: {SURFACE_CARD_HOVER};
        border-color: {ACCENT_ICE};
        color: #ffffff;
    }}

    /* Cyberpunk Governor Button */
    QPushButton#BabySmartButton {{
        background-color: {ACTIVE_NAV};
        border: 1px solid {ACCENT_SPOTIFY};
        border-radius: {RADIUS_PILL}px;
        color: {ACCENT_SPOTIFY};
        min-height: 38px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton#BabySmartButton:checked {{
        background-color: rgba(29, 185, 84, 0.15);
        border: 1px solid {ACCENT_SPOTIFY};
        color: #ffffff;
    }}
    QPushButton#BabySmartButton:hover {{
        border-color: {ACCENT_ICE};
    }}
    QPushButton#BabySmartButton:checked:hover {{
        border-color: {ACCENT_SPOTIFY};
    }}

    /* ---- Combobox, Spinboxes, Sliders ---------------------------------- */
    QComboBox {{
        background-color: {SURFACE_RAISED};
        border: 1px solid {BORDER_CONTROL};
        border-radius: {RADIUS_CONTROL}px;
        padding: 6px 12px;
        min-height: 28px;
        color: {TEXT_PRIMARY};
    }}
    QComboBox:hover {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{
        border: none; width: 22px; subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        image: url({ICONS}/chevron.svg); width: 11px; height: 11px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {SURFACE_BASE};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_WASH};
        selection-color: {ACCENT};
        outline: none;
    }}

    QSpinBox {{
        background-color: {SURFACE_RAISED};
        border: 1px solid {BORDER_CONTROL};
        border-radius: {RADIUS_CONTROL}px;
        color: {TEXT_PRIMARY};
        padding: 4px 8px;
        min-height: 26px;
    }}
    QSpinBox:focus {{ border-color: {ACCENT}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

    QSlider::groove:horizontal {{
        background: {SURFACE_SUNKEN};
        border: 1px solid {BORDER_QUIET};
        border-radius: 4px;
        height: 6px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 4px;
        height: 6px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        border: none;
        width: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {ACCENT};
    }}

    QCheckBox, QRadioButton {{
        color: {TEXT_PRIMARY};
        spacing: 8px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER_CONTROL};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 9px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{ image: url({ICONS}/check.svg); }}

    QScrollArea {{ border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_CONTROL}; border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """
