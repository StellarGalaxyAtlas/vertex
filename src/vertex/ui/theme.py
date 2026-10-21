"""The colour schemes, the channel colours and the application stylesheet.

Vertex has nine colour schemes, picked in Settings › General, in the order
they are listed here. Navy, the default, is Vertex's original look; Plum is
the "Shelves" design of round 2: a deep plum page, a hot magenta accent and
a periwinkle second colour for gradients. Polar and Glacier are light ones.
Each scheme gives every token below a value; the UI reads them as `theme.ACCENT` and so on when it
paints, and anything set once when a widget is built (a stylesheet, an icon)
goes through `themed`, so the whole app changes the moment a scheme is picked
(`use`).

Every scheme keeps the design's rules: every text colour reads at
4.5:1 or better on every ground it sits on, a field's edge at 3:1; the accent
never colours an audio control (a channel's slider takes the channel's
colour, a device's slider is neutral); red only means recording. The tests
measure all of it, for every scheme. Every colour the UI uses is defined
here, once.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from vertex import paths


def _mix(a: str, b: str, amount: float) -> str:
    """`a` moved `amount` of the way towards `b`."""
    one = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    two = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}"
                         for x, y in zip(one, two, strict=True))


def _luminance(colour: str) -> float:
    """How bright `colour` looks (WCAG's relative luminance, 0 to 1)."""
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def is_light(ground: str) -> bool:
    """Whether a scheme with this page colour is a light one."""
    return _luminance(ground) > 0.4


def _scheme(ground: str, panel: str, text: str, muted: str, dim: str, accent: str,
            on_accent: str, edge: str, second: str, select: str, recording: str,
            channels: tuple[str, str, str, str, str], fill: str = "",
            soft: str = "") -> dict[str, str]:
    """A scheme from its key colours; the steps between them are worked out.

    `ground` is the page, `panel` the sections on it; cards and controls are
    lifted off the panel towards the text colour. `channels` are Game, Chat,
    Media, Mic and the desktop's own track. `fill` is what text sits on where
    it isn't the accent itself (a deeper shade, so `on_accent` can be white),
    and `soft`, "second", makes the selected row, tab or menu item a tint of
    the second colour rather than of the accent.

    A light `ground` makes a light scheme: the top bar goes paler than the
    page instead of darker, fields sit half way between the page and the
    panels, lines are a step stronger, and edges go darker than what they
    outline rather than lighter. Its page is a clear step darker than its
    near-white panels, so they stand off it."""
    fill = fill or accent
    dark_label = sum(int(on_accent[i:i + 2], 16) for i in (1, 3, 5)) < 300
    game, chat, media, mic, desktop = channels
    card = _mix(panel, text, 0.04)
    light = is_light(ground)
    away = "#000000" if light else "#ffffff"      # an edge stands out from the ground
    return {
        "MAIN_BG": ground, "SECTION_BG": panel,
        "SIDEBAR_BG": _mix(ground, "#ffffff", 0.6) if light else _mix(ground, "#000000", 0.25),
        "CARD_BG": card, "CARD_HOVER": _mix(panel, text, 0.09),
        "CONTROL_BG": _mix(panel, text, 0.07),
        "FIELD_BG": _mix(ground, panel, 0.55) if light else _mix(ground, "#000000", 0.2),
        "LINE": _mix(panel, text, 0.12 if light else 0.08), "SEAM": _mix(panel, text, 0.14),
        "EDGE": edge,
        "TEXT": text, "TEXT_MUTED": muted, "TEXT_DIM": dim,
        "ACCENT": accent, "ACCENT_FILL": fill,
        "ACCENT_HOVER": (_mix(fill, "#ffffff", 0.18) if dark_label
                         else _mix(fill, "#000000", 0.1)),
        "ACCENT_EDGE": _mix(accent, away, 0.2 if light else 0.3),
        "ACCENT_FILL_EDGE": _mix(fill, away, 0.15 if light else 0.3),
        "ACCENT_SOFT": (_mix(card, second, 0.3) if soft == "second"
                        else _mix(ground, accent, 0.25)),
        "ON_ACCENT": on_accent, "INK": _mix(text if light else ground, "#000000", 0.3),
        "SELECT": select, "SECOND": second, "RECORDING": recording,
        "GAME": game, "CHAT": chat, "MEDIA": media, "MIC": mic, "DESKTOP": desktop,
    }


# name: (label in Settings, what it looks like, its colours)
SCHEMES: dict[str, tuple[str, str, dict[str, str]]] = {
    # Vertex's colours until round 3, as they were (the hint text one step
    # lighter, to pass on a hovered card).
    "navy": ("Navy", "Vertex's original look", {
        "MAIN_BG": "#0b0e14", "SIDEBAR_BG": "#10141c", "SECTION_BG": "#161b26",
        "CARD_BG": "#1f2533", "CARD_HOVER": "#29303f", "CONTROL_BG": "#262d3c",
        "FIELD_BG": "#0d1017", "LINE": "#2a3141", "SEAM": "#343c4e", "EDGE": "#66718a",
        "TEXT": "#eef0f3", "TEXT_MUTED": "#aab2bf", "TEXT_DIM": "#9099a9",
        "ACCENT": "#4a62ec", "ACCENT_FILL": "#4a62ec", "ACCENT_HOVER": "#3d55dd",
        "ACCENT_EDGE": "#9aabff", "ACCENT_FILL_EDGE": "#9aabff",
        "ACCENT_SOFT": "#27336a", "ON_ACCENT": "#ffffff", "INK": "#0b0e14",
        "SELECT": "#9aabff", "SECOND": "#9aabff", "RECORDING": "#ff5c6c",
        "GAME": "#2fb39b", "CHAT": "#3b82f6", "MEDIA": "#c25d7b", "MIC": "#d98d2b",
        "DESKTOP": "#9b6bd6"}),
    # White text on a deeper pink than the accent, and the selected item in
    # periwinkle: dark text on hot pink was hard to read, and a pink tint on
    # plum came out wine.
    "plum": ("Plum", "Magenta and periwinkle", _scheme(
        "#150a1f", "#1d0d2b", "#f8f0ff", "#d2bfe6", "#b39dcc", "#ff3ea5", "#ffffff", "#8d6fae",
        "#7d8bff", "#a9b4ff", "#ff4d6a", ("#2fd39b", "#4cb0ff", "#b4e04a", "#ffad33", "#c08cff"),
        fill="#d42481", soft="second")),
    # Halloween night: near black with a hint of purple, a pumpkin's orange
    # into witchy purple (the selected item a purple tint, not a muddy
    # orange one), the channels slime green, dusk blue, candy-corn yellow,
    # bone and ghost lilac.
    "spooky": ("Spooky", "Pumpkin and purple on the dark", _scheme(
        "#09070b", "#140f17", "#f6eee6", "#c9bccb", "#a898aa", "#ff7a1a", "#1a0a00", "#76667a",
        "#a259ff", "#ffa95e", "#ff4757", ("#8be04e", "#6f8dff", "#ffd23f", "#e3d5c1", "#c3a6ff"),
        soft="second")),
    # The deep sea, blue going on black, lit as its animals light themselves:
    # a cyan glow into fluorescent magenta, the channels in neon green,
    # electric blue, violet, a lure's gold and a fluorescent orange.
    "abyss": ("Abyss", "Deep-sea glow on black-blue", _scheme(
        "#02050c", "#071226", "#e4f3ff", "#a5bfdb", "#8ba6c4", "#1fe5ff", "#00161c", "#4f6c90",
        "#ff4fd8", "#7cefff", "#ff4766", ("#3dff8f", "#4d8dff", "#b98cff", "#ffc94a", "#ff9a57"))),
    "aurora": ("Aurora", "Cyan and violet", _scheme(
        "#0f0b24", "#1a1538", "#f3f0ff", "#c2bae6", "#a39bcf", "#52e0f0", "#0f0b24", "#6e64a6",
        "#a68bff", "#b9a6ff", "#ff5470", ("#3cc78a", "#5b97ff", "#ee72c0", "#eba23e", "#d4e157"))),
    "midnight": ("Midnight blue", "Amber and cyan", _scheme(
        "#0a1020", "#1c2640", "#ecf1f9", "#aab6cb", "#99a5bc", "#f6b03e", "#0a1020", "#6c7b9a",
        "#3dd6f0", "#3dd6f0", "#ff5d62", ("#4fcb72", "#4a8ff7", "#e0709a", "#a88bfa", "#b8d860"))),
    "coral": ("Coral", "Coral and periwinkle on ink", _scheme(
        "#0d1117", "#1a2230", "#eef2f7", "#aeb8c8", "#97a2b5", "#ff8a66", "#1a0f0b", "#6a7690",
        "#8c9eff", "#8c9eff", "#f04a5a", ("#2ec4a6", "#4ea8f5", "#c084fc", "#e9b949", "#f07fb0"))),
    # The first light scheme: an aurora over snow, a violet accent into teal
    # on white and snow-grey grounds, the channels deep enough to read on them.
    "polar": ("Polar", "Aurora violet on snow", _scheme(
        "#d5d9e8", "#fdfdff", "#1a1730", "#47435f", "#5a5677", "#7c3aed", "#ffffff", "#7d7a97",
        "#0d9488", "#6d28d9", "#d92d3f", ("#047857", "#2563eb", "#c0267a", "#b45309", "#0e7490"))),
    # The second light scheme: ice. Snow-white and ice-grey grounds, a deep
    # glacier blue (white text on it) into icy teal; the channels kept off the
    # blue, Chat in indigo.
    "glacier": ("Glacier", "Glacier blue on ice", _scheme(
        "#d1dce7", "#fdfeff", "#0f1e2b", "#3d5163", "#485c6e", "#0a6cb4", "#ffffff", "#76889a",
        "#14a3b8", "#0a5a96", "#d92d3f", ("#0f8a5f", "#4f46e5", "#c0267a", "#b45309", "#7c3aed"))),
}
DEFAULT_SCHEME = "navy"

# --- The tokens, set from the scheme in use by `select` ------------------------
# Accent
ACCENT = ""                 # lines, glows, underlines, a switch that is on
ACCENT_FILL = ""            # what text sits on: a primary button, selected text
ACCENT_HOVER = ""           # ACCENT_FILL, hovered
ACCENT_EDGE = ""            # the accent as a line or an icon on a dark ground
ACCENT_FILL_EDGE = ""       # the rim of a primary button
ACCENT_SOFT = ""            # the selected row, tab or menu item
ON_ACCENT = ""              # text and icons on ACCENT_FILL, a switch's knob
SECOND = ""                 # the accent's partner in a gradient
INK = ""                    # text on a bright colour: an app's badge, a person's
ON_CHANNEL = ""             # the icon on a channel's badge: INK, white on a light scheme
SELECT = ""                 # the keyboard focus, the trim handles, links
SELECTION = ""              # selected text

# Grounds, darkest first
MAIN_BG = ""                # the page behind everything
SIDEBAR_BG = ""             # the top bar
SECTION_BG = ""             # panels: above the page, under the cards
CARD_BG = ""                # cards, and the controls that sit on one
CARD_HOVER = ""
FIELD_BG = ""               # text fields, recessed
CONTROL_BG = ""             # buttons and empty thumbnails
LINE = ""                   # dividers
SEAM = ""                   # the edge of a menu or tooltip
EDGE = ""                   # the edge of a field: 3:1 on a panel or card
CARD_TOP = ""               # a clip card's gradient, and while hovered
CARD_BOTTOM = ""
CARD_HOVER_TOP = ""
CARD_HOVER_BOTTOM = ""
BADGE_BG = ""

# Text
TEXT = ""
TEXT_MUTED = ""
TEXT_DIM = ""

# Meaning: the same in every dark scheme, deeper in a light one so they read
# on it; the recording light is each scheme's own
MEANING = {
    False: {"DANGER": "#ff6b70", "DANGER_HOVER": "#e85a5f", "OK": "#3fb950", "WARN": "#e6b422"},
    True: {"DANGER": "#c42b2b", "DANGER_HOVER": "#a82323", "OK": "#1a7f37", "WARN": "#8f5d00"},
}
DANGER = ""
DANGER_HOVER = ""
ON_DANGER = ""              # text on DANGER: a red button, hovered
OK = ""
WARN = ""
RECORDING = ""
LIGHT = False               # whether the scheme in use is a light one

# Over video, whatever the scheme: a clip's duration and star sit on its
# picture, under a dark scrim
VIDEO_BG = "#000000"
ON_VIDEO = "#ffffff"
STAR = "#e6b422"            # a favourite's star on its thumbnail

# Editor
PLAYHEAD = ""               # white on a dark scheme, the text colour on a light one
VIDEO_LANE = "#1f6f66"
HANDLE = "#ffffff"          # a slider's handle; outlined in EDGE on a light scheme
WAVE_SHADE = 0.40
TRIM_SHADE = ""
LANE_BG = ""
WAVE_MUTED = ""

# The channels: Game, Chat, Media, Mic and the desktop's own track
GAME = ""
CHAT = ""
MEDIA = ""
MIC = ""
DESKTOP = ""

# A lane the mixer could name keeps its channel's colour however many tracks
# the clip has, so the mic is the same colour on a two-track clip as on a
# five-track one. Unnamed tracks take AUDIO_LANES in order instead.
CHANNEL_COLOURS: dict[str, str] = {}
AUDIO_LANES: tuple[str, ...] = ()

STYLESHEET = ""
scheme = DEFAULT_SCHEME     # the one in use

# --- Geometry ---------------------------------------------------------------
RADIUS_CARD = 14
RADIUS_CONTROL = 10
RADIUS_SMALL = 8
CONTENT_MARGIN = 24

TOKENS = frozenset(SCHEMES["navy"][2]) | {
    "SELECTION", "CARD_TOP", "CARD_BOTTOM", "CARD_HOVER_TOP", "CARD_HOVER_BOTTOM",
    "BADGE_BG", "TRIM_SHADE", "LANE_BG", "WAVE_MUTED", "DANGER", "DANGER_HOVER", "ON_DANGER",
    "OK", "WARN", "VIDEO_BG", "ON_VIDEO", "STAR", "PLAYHEAD", "VIDEO_LANE", "HANDLE",
    "ON_CHANNEL"}


def colour(value: str) -> str:
    """A colour named by its token ("TEXT_MUTED") in the scheme in use, or a
    colour given as itself ("#2fb39b")."""
    return globals()[value] if value in TOKENS else value


def select(name: str) -> str:
    """Make `name` the scheme every token reads from (an unknown name gets the
    default), and return the name used. Restyling a running app is `use`."""
    global scheme
    if name not in SCHEMES:
        name = DEFAULT_SCHEME
    scheme = name
    values = SCHEMES[name][2]
    tokens = dict(values)
    ground, card, text = values["MAIN_BG"], values["CARD_BG"], values["TEXT"]
    light = is_light(ground)
    tokens.update(MEANING[light])
    tokens.update(
        # A light scheme's channels and red are deep, so what sits on them is white.
        LIGHT=light, ON_DANGER="#ffffff" if light else values["INK"],
        ON_CHANNEL="#ffffff" if light else values["INK"],
        PLAYHEAD=text if light else "#ffffff",
        SELECTION=values["ACCENT_FILL"],
        CARD_TOP=_mix(card, text, 0.012), CARD_BOTTOM=_mix(card, ground, 0.35),
        CARD_HOVER_TOP=_mix(card, text, 0.06), CARD_HOVER_BOTTOM=card,
        BADGE_BG=_mix(ground, "#000000", 0.5),
        # Outside the trim, the lanes fade into the page.
        TRIM_SHADE=_mix(ground, "#ffffff", 0.3) if light else _mix(ground, "#000000", 0.45),
        LANE_BG=card, WAVE_MUTED=_mix(card, text, 0.13),
        CHANNEL_COLOURS={"game": values["GAME"], "desktop": values["DESKTOP"],
                         "chat": values["CHAT"], "media": values["MEDIA"], "mic": values["MIC"]},
        AUDIO_LANES=(values["GAME"], values["CHAT"], values["MIC"], values["DESKTOP"],
                     values["MEDIA"], values["TEXT_DIM"]),
    )
    globals().update(tokens)
    globals()["STYLESHEET"] = _stylesheet()
    return name


def logo_ink() -> str:
    """Which ink of the logo shows on the app's own grounds: the light artwork
    on a dark scheme, the dark one on a light scheme."""
    return "dark" if LIGHT else "light"


def handle() -> str:
    """A slider handle's fill, and on a light scheme its outline, so it shows
    on a pale track."""
    return f"background: {HANDLE};" + (f" border: 1px solid {EDGE};" if LIGHT else "")


def use(name: str) -> None:
    """Switch the running app to scheme `name`: the stylesheet, the palette,
    everything set up through `themed`, and a repaint of every widget."""
    select(name)
    app = QApplication.instance()
    if app is None:
        return
    app.setPalette(palette())
    app.setStyleSheet(STYLESHEET)
    for widget in app.allWidgets():
        for apply in list(getattr(widget, "_theme_hooks", {}).values()):
            apply()
        widget.update()


def themed(widget: QWidget, apply: Callable[[], object], key: str = "style") -> None:
    """Run `apply` now, and again whenever the scheme changes.

    For what a widget takes from the scheme once, when it is set up, rather
    than when it paints: its stylesheet, its icon, a pixmap. `apply` reads the
    tokens each time it runs. A later `apply` for the same key replaces the
    earlier one, so a label whose colour follows its state keeps one."""
    hooks = getattr(widget, "_theme_hooks", None)
    if hooks is None:
        hooks = {}
        widget._theme_hooks = hooks
    hooks[key] = apply
    apply()


def style(widget: QWidget, build: Callable[[], str]) -> None:
    """Give `widget` the stylesheet `build` returns, now and in every scheme."""
    themed(widget, lambda: widget.setStyleSheet(build()))


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
    """A stable colour per game, so each one keeps its dot wherever it is listed."""
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


TICK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<path d="M5.5 12.5 10 17l8.5-10" fill="none" stroke="{colour}" '
            'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _tick() -> str:
    """The tick in a checked box. A style sheet takes an image only from a
    file, so it is written once for each colour it comes in: ON_ACCENT. No
    file, no tick: the box is still filled."""
    path = paths.runtime_dir() / f"tick-{ON_ACCENT.lstrip('#')}.svg"
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TICK_SVG.format(colour=ON_ACCENT), encoding="utf-8")
    except OSError:
        return ""
    return f"image: url({path.as_posix()});"


def _stylesheet() -> str:
    return f"""
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
QPushButton:disabled, QToolButton:disabled {{
    color: {TEXT_DIM}; background: {SECTION_BG}; border-color: {SEAM};
}}
QPushButton[kind="primary"] {{
    background: {ACCENT_FILL}; border: 1px solid {ACCENT_FILL_EDGE}; color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:disabled {{
    background: {CONTROL_BG}; border-color: {CONTROL_BG}; color: {TEXT_DIM};
}}
QPushButton[kind="danger"] {{ color: {DANGER}; }}
QPushButton[kind="danger"]:hover {{ background: {DANGER}; color: {ON_DANGER}; }}
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
    combobox-popup: 0;      /* a list, so the rows below take their colours */
}}
QComboBox:focus {{ border-color: {SELECT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD_BG}; border: 1px solid {SEAM}; selection-background-color: {ACCENT_SOFT};
    outline: none; padding: 4px;
}}
QComboBox QAbstractItemView::item {{ padding: 5px 8px; border-radius: 6px; }}
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{
    background: {ACCENT_SOFT}; color: {TEXT};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {EDGE};
    background: {FIELD_BG};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_FILL}; border-color: {ACCENT_FILL_EDGE}; {_tick()}
}}

/* --- Sliders ------------------------------------------------------------- */
QSlider::groove:horizontal {{ height: 4px; background: {CONTROL_BG}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    {handle()} width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}}
QSlider::groove:vertical {{ width: 4px; background: {CONTROL_BG}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:vertical {{
    {handle()} width: 14px; height: 14px; margin: 0 -5px; border-radius: 7px;
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
QProgressBar::chunk {{
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 {ACCENT}, stop: 1 {SECOND});
    border-radius: 4px;
}}
QDialog {{ background: {SECTION_BG}; }}

/* --- Named surfaces -------------------------------------------------------- */
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


select(DEFAULT_SCHEME)
