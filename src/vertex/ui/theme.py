"""The palette, the channel colours and the application stylesheet.

The palette is the one Vertex 1.x called "Anneal", sharpened: a deep navy
page with the rail, the cards and the controls each lifted a step off it,
and a periwinkle accent. Every text colour reads at 4.5:1 or better on every
ground it sits on, and a field's edge at 3:1. The accent never colours an
audio control: a channel's slider takes the channel's colour, a device's
slider is neutral. The design and its rules are in temp/design/.
Every colour the UI uses is defined here, once.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

# --- Accent -----------------------------------------------------------------
ACCENT = "#4a62ec"
ACCENT_HOVER = "#3d55dd"
ACCENT_EDGE = "#9aabff"     # the accent as a line or an icon on a dark ground
ACCENT_SOFT = "#27336a"     # the selected row, tab or menu item
ON_ACCENT = "#ffffff"       # text and icons on ACCENT
INK = "#0b0e14"             # text on a bright colour: an app's badge, a red button

# Selected and focused: the keyboard focus, the trim handles, links.
SELECT = "#9aabff"
SELECTION = ACCENT          # selected text

# --- Grounds, darkest first -------------------------------------------------
MAIN_BG = "#0b0e14"         # the page behind everything
SECTION_BG = "#161b26"      # panels: above the page, under the cards
SIDEBAR_BG = "#10141c"      # the rail
CARD_BG = "#1f2533"         # cards, and the controls that sit on one
CARD_HOVER = "#29303f"
FIELD_BG = "#0d1017"        # text fields, recessed
CONTROL_BG = "#262d3c"      # buttons and empty thumbnails
LINE = "#2a3141"            # dividers
SEAM = "#343c4e"            # the edge of a menu or tooltip
EDGE = "#66718a"            # the edge of a field: 3:1 on a panel or card
PAGE_GLOW = "#151a26"       # the lit band across the top of a page

CARD_TOP = "#212734"
CARD_BOTTOM = "#191d27"
CARD_HOVER_TOP = "#2a3040"
CARD_HOVER_BOTTOM = "#1f2431"

BADGE_BG = "#06070a"

# --- Text -------------------------------------------------------------------
TEXT = "#eef0f3"
TEXT_MUTED = "#aab2bf"
TEXT_DIM = "#8c95a5"

# --- Meaning ----------------------------------------------------------------
DANGER = "#ff6b70"
DANGER_HOVER = "#e85a5f"
OK = "#3fb950"
WARN = "#e6b422"
RECORDING = "#ff5c6c"

# --- Editor -----------------------------------------------------------------
VIDEO_BG = "#000000"
TRIM_SHADE = "#06080c"
PLAYHEAD = "#ffffff"
VIDEO_LANE = "#1f6f66"
LANE_BG = CARD_BG
WAVE_MUTED = "#3d4454"
WAVE_SHADE = 0.40

# A lane the mixer could name keeps its channel's colour however many tracks
# the clip has, so the mic is the same colour on a two-track clip as on a
# five-track one. Unnamed tracks take these in order instead.
CHANNEL_COLOURS = {
    "game": "#2fb39b",
    "desktop": "#9b6bd6",
    "chat": "#3b82f6",
    "media": "#c25d7b",
    "mic": "#d98d2b",
}
AUDIO_LANES = ("#2fb39b", "#3b82f6", "#d98d2b", "#9b6bd6", "#c25d7b", "#8a93a6")

# --- Geometry ---------------------------------------------------------------
RADIUS_CARD = 14
RADIUS_CONTROL = 10
RADIUS_SMALL = 8
RAIL_WIDTH = 216            # the rail grows from here to fit its filters
RAIL_MAX_WIDTH = 320
CONTENT_MARGIN = 24


def channel_colour(channel: str, position: int = 0) -> str:
    return CHANNEL_COLOURS.get(channel) or AUDIO_LANES[position % len(AUDIO_LANES)]


def shade(colour: str, factor: float) -> str:
    """`colour` mixed towards black (factor < 1) or white (factor > 1)."""
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    if factor <= 1:
        channels = [round(c * factor) for c in channels]
    else:
        channels = [round(c + (255 - c) * (factor - 1)) for c in channels]
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in channels)


def game_colour(name: str) -> str:
    """A stable colour per game, so each one keeps its dot in the rail."""
    palette = ("#5878ff", "#2fb39b", "#d98d2b", "#c25d7b", "#9b6bd6", "#3b82f6",
               "#e6b422", "#4fb3d9", "#e5734d", "#8ac24a")
    total = 0
    for char in name.casefold():
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    return palette[total % len(palette)]


def palette() -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: MAIN_BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: FIELD_BG,
        QPalette.ColorRole.AlternateBase: SECTION_BG,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_DIM,
        QPalette.ColorRole.Button: CONTROL_BG,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: SELECTION,
        QPalette.ColorRole.HighlightedText: ON_ACCENT,
        QPalette.ColorRole.ToolTipBase: CARD_BG,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Link: SELECT,
        QPalette.ColorRole.Mid: LINE,
        QPalette.ColorRole.Dark: MAIN_BG,
    }
    for role, colour in roles.items():
        pal.setColor(role, QColor(colour))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_DIM))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_DIM))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_DIM))
    return pal


def font(size: float = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    result = QFont()
    result.setPointSizeF(size)
    result.setWeight(weight)
    return result


STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}
QMainWindow, #Page {{ background: {MAIN_BG}; }}
QToolTip {{
    background: {CARD_BG}; color: {TEXT}; border: 1px solid {SEAM};
    border-radius: 6px; padding: 5px 8px;
}}

/* --- Buttons ------------------------------------------------------------ */
QPushButton, QToolButton {{
    background: {CONTROL_BG}; color: {TEXT}; border: 1px solid transparent;
    border-radius: {RADIUS_CONTROL}px; padding: 7px 14px;
}}
QPushButton:hover, QToolButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {SECTION_BG}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {TEXT_DIM}; background: {SECTION_BG}; }}
QPushButton[kind="primary"] {{
    background: {ACCENT}; border: 1px solid {ACCENT_EDGE}; color: {ON_ACCENT}; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:disabled {{
    background: {CONTROL_BG}; border-color: {CONTROL_BG}; color: {TEXT_DIM};
}}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton[kind="danger"]:hover {{ background: {DANGER}; color: {INK}; }}
QPushButton[kind="danger"]:disabled {{ color: {TEXT_DIM}; background: {SECTION_BG}; }}
QPushButton[kind="ghost"], QToolButton[kind="ghost"] {{ background: transparent; }}
QPushButton[kind="ghost"]:hover, QToolButton[kind="ghost"]:hover {{ background: {CARD_HOVER}; }}
QToolButton {{ padding: 6px; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; }}

/* --- Fields -------------------------------------------------------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {FIELD_BG}; border: 1px solid {EDGE}; border-radius: {RADIUS_CONTROL}px;
    padding: 7px 10px; selection-background-color: {SELECTION}; selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {SELECT};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox {{
    background: {FIELD_BG}; border: 1px solid {EDGE}; border-radius: {RADIUS_CONTROL}px;
    padding: 6px 10px; min-height: 20px;
}}
QComboBox:focus {{ border-color: {SELECT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD_BG}; border: 1px solid {SEAM}; selection-background-color: {ACCENT_SOFT};
    outline: none; padding: 4px;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {EDGE};
    background: {FIELD_BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT_EDGE}; }}

/* --- Sliders ------------------------------------------------------------- */
QSlider::groove:horizontal {{ height: 4px; background: {CONTROL_BG}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: white; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}}
QSlider::groove:vertical {{ width: 4px; background: {CONTROL_BG}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:vertical {{
    background: white; width: 14px; height: 14px; margin: 0 -5px; border-radius: 7px;
}}

/* --- Lists, scroll bars, menus -------------------------------------------- */
QListView, QTreeView, QScrollArea {{ background: transparent; border: none; outline: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {EDGE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::handle:horizontal:hover {{ background: {TEXT_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {EDGE}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QMenu {{
    background: {CARD_BG}; border: 1px solid {SEAM}; border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::item:disabled {{ color: {TEXT_DIM}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}
QProgressBar {{
    background: {CONTROL_BG}; border: none; border-radius: 4px; height: 8px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QDialog {{ background: {SECTION_BG}; }}

/* --- Named surfaces -------------------------------------------------------- */
#Rail {{ background: {SIDEBAR_BG}; border-right: 1px solid {SEAM}; }}
#Card, #Section {{ background: {SECTION_BG}; border-radius: {RADIUS_CARD}px; }}
#Muted {{ color: {TEXT_MUTED}; }}
#Dim {{ color: {TEXT_DIM}; }}
#Heading {{ font-size: 18pt; font-weight: 600; }}
#Subheading {{ font-size: 12pt; font-weight: 600; }}
#Group {{ color: {TEXT_DIM}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#Chip {{
    background: {CARD_BG}; border-radius: {RADIUS_SMALL}px; padding: 4px 10px;
    color: {TEXT_MUTED};
}}
#Chip:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
"""
