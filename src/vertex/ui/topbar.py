"""The bar across the top of the window: the pages, search, the replay buffer."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
)

from vertex import fmt, paths
from vertex.recorder.replay import RecorderError
from vertex.ui import icons, theme
from vertex.ui.widgets import IconButton, button, label

HEIGHT = 60
SEARCH_MIN = 180
SEARCH_MAX = 400          # the search at most, at 1280 px; it grows on bigger screens
SEARCH_WIDEST = 760
PAD = 12                  # room either side of a tab's name; more on bigger screens
PAD_WIDEST = 22


class PageTab(QAbstractButton):
    """A page in the top bar: an icon and its name, underlined in the accent
    while it is the page showing. Compact, it drops the icon."""

    ICON = 16

    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.compact = False
        self.pad = PAD
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
        return font

    def width_for(self, compact: bool, pad: int = PAD) -> int:
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        text = QFontMetrics(bold).horizontalAdvance(self.text())
        return 2 * pad + (0 if compact else self.ICON + 7) + text

    def set_pad(self, pad: int) -> None:
        if pad != self.pad:
            self.pad = pad
            self.updateGeometry()
            self.update()

    def set_compact(self, compact: bool) -> None:
        if compact != self.compact:
            self.compact = compact
            self.updateGeometry()
            self.update()

    def sizeHint(self):
        return QSize(self.width_for(self.compact, self.pad), HEIGHT)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        hover = self.underMouse()
        colour = QColor(theme.TEXT if checked or hover else theme.TEXT_MUTED)
        x = float(self.pad)
        if not self.compact:
            icon = icons.pixmap(self.icon_name, "ACCENT_EDGE" if checked else
                                ("TEXT" if hover else "TEXT_MUTED"), self.ICON)
            p.drawPixmap(int(x), (self.height() - self.ICON) // 2, icon)
            x += self.ICON + 7
        p.setFont(self._font())
        p.setPen(colour)
        p.drawText(QRectF(x, 0, self.width() - x, self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        if checked:
            # The underline, with a glow of its own colour around it.
            inset = self.pad - 3
            line = QRectF(inset, self.height() - 3, self.width() - 2 * inset, 3)
            glow = QColor(theme.ACCENT)
            for grow, alpha in ((6, 0.10), (3, 0.18)):
                glow.setAlphaF(alpha)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(line.adjusted(-grow, -grow, grow, grow), 4 + grow, 4 + grow)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(line.adjusted(0, 0, 0, 3), 3, 3)
        if self.hasFocus():
            p.setPen(QColor(theme.SELECT))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(3, 12, -3, -12), 6, 6)


class ReplayPill(QFrame):
    """The replay buffer: whether it is on and how much it keeps, Save clip,
    and start/stop. Red is its light while it records, and only that: while
    the buffer is off nothing here is red. Compact, it drops the second line."""

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setObjectName("ReplayPill")
        theme.style(self, lambda: f"#ReplayPill {{ background: {theme.SECTION_BG}; "
                                  f"border: 1px solid {theme.SEAM}; border-radius: 20px; }}")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 3, 4, 3)
        layout.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        layout.addWidget(self.dot)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = label("Replay off")
        self.title.setStyleSheet("font-weight: 600; font-size: 9pt;")
        self.detail = label("", "Muted")
        theme.style(self.detail, lambda: f"color: {theme.TEXT_MUTED}; font-size: 8.5pt;")
        text.addWidget(self.title)
        text.addWidget(self.detail)
        layout.addLayout(text)
        self.save = button("Save clip", "primary", "save-clip", self._save,
                           "Save clip")
        self.save.setStyleSheet("QPushButton { padding: 6px 14px; border-radius: 16px; }")
        layout.addWidget(self.save)
        self.toggle = IconButton("record", "Start the replay buffer", 14, "TEXT_MUTED", kind="")
        self.toggle.setFixedSize(32, 32)
        theme.style(self.toggle, lambda: f"QToolButton {{ background: {theme.CONTROL_BG}; "
                                         f"border-radius: 16px; padding: 0; }}"
                                         f"QToolButton:hover {{ background: {theme.CARD_HOVER}; }}")
        self.toggle.clicked.connect(context.recorder.toggle)
        layout.addWidget(self.toggle)
        context.recorder.state_changed.connect(self.update_state)
        context.config_changed.connect(lambda: self.update_state(context.recorder.phase, ""))
        self.update_state("stopped", "")

    def _save(self) -> None:
        try:
            self.context.message.emit(self.context.recorder.save(), "info")
        except RecorderError:
            pass         # the recorder has told the user

    def set_compact(self, compact: bool) -> None:
        self.detail.setVisible(not compact)

    def width_for(self, compact: bool) -> int:
        """Its width with or without the second line, whichever is showing now."""
        margins, spacing = self.layout().contentsMargins(), self.layout().spacing()
        text = self.title.sizeHint().width()
        if not compact:
            text = max(text, self.detail.sizeHint().width())
        return (margins.left() + margins.right() + self.dot.width() + text +
                self.save.sizeHint().width() + self.toggle.width() + 3 * spacing)

    def update_state(self, state: str, error: str) -> None:
        seconds = self.context.config.recorder.replay_seconds
        running = state == "running"
        colour = {"running": "RECORDING", "starting": "WARN", "restarting": "WARN",
                  "failed": "DANGER"}.get(state, "TEXT_DIM")
        theme.style(self.dot, lambda: f"background: {theme.colour(colour)}; border-radius: 4px;")
        self.title.setText({"running": "Replay on", "starting": "Starting…",
                            "restarting": "Restarting…", "failed": "Replay stopped"}
                           .get(state, "Replay off"))
        self.detail.setText(f"keeps the last {fmt.duration(seconds)}" if running or
                            state == "restarting" else "start it to save clips")
        self.setToolTip(error or ("Restarting"
                                  if state == "restarting" else ""))
        self.save.setEnabled(running)
        busy = running or state in ("starting", "restarting")
        self.toggle.set_icon("stop" if busy else "record", "TEXT" if busy else "TEXT_MUTED")
        self.toggle.setToolTip("Stop the replay buffer" if running else
                               "Start the replay buffer")


class TopBar(QFrame):
    """The logo, the pages, search and the replay buffer, in one row."""

    navigate = Signal(str)        # "home" | "library" | "sonar" | "settings"

    LOGO_HEIGHT = 30
    PAGES = (("home", "Home", "home"), ("library", "Library", "library"),
             ("sonar", "Sonar", "sonar"), ("settings", "Settings", "settings"))

    def __init__(self, context, state, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.page = ""
        self.setObjectName("TopBar")
        self.setFixedHeight(HEIGHT)
        theme.style(self, lambda: f"#TopBar {{ background: {theme.SIDEBAR_BG}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 12, 0)
        layout.setSpacing(0)

        self.logo = QLabel()
        self.logo.setFixedSize(self.LOGO_HEIGHT, self.LOGO_HEIGHT)
        theme.themed(self.logo, self._show_logo, "icon")
        layout.addWidget(self.logo)
        layout.addSpacing(8)
        self.name = QLabel("Vertex")
        self.name.setStyleSheet("font-size: 14pt; font-weight: 700;")
        layout.addWidget(self.name)
        layout.addSpacing(22)

        self.tabs: dict[str, PageTab] = {}
        group = QButtonGroup(self)
        for key, text, icon_name in self.PAGES:
            tab = PageTab(text, icon_name)
            tab.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            group.addButton(tab)
            self.tabs[key] = tab
            layout.addWidget(tab)

        layout.addSpacing(16)
        layout.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("TopSearch")
        self.search.setPlaceholderText("Search clips, games, people")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(SEARCH_MIN)
        self.search.setMaximumWidth(SEARCH_MAX)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        find = self.search.addAction(icons.icon("search", "TEXT_MUTED", 16),
                                     QLineEdit.ActionPosition.LeadingPosition)
        theme.themed(self.search, lambda: find.setIcon(icons.icon("search", "TEXT_MUTED", 16)),
                     "icon")
        theme.style(self.search, lambda: f"QLineEdit {{ background: {theme.FIELD_BG}; "
                                         f"border: 1px solid {theme.EDGE}; border-radius: 18px; "
                                         f"padding: 7px 12px 7px 6px; }}"
                                         f"QLineEdit:focus {{ border-color: {theme.SELECT}; }}")
        self._search_timer = QTimer(self, singleShot=True, interval=150)
        self._search_timer.timeout.connect(lambda: state.set_query(self.search.text()))
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        # What is found shows in the library, so typing elsewhere goes there.
        self.search.textEdited.connect(self._searching)
        layout.addWidget(self.search, 4)
        layout.addStretch(1)
        layout.addSpacing(16)

        self.recorder = ReplayPill(context)
        layout.addWidget(self.recorder)
        self._compact = None

    def _show_logo(self) -> None:
        # The mark in the ink that shows on the bar: light, or dark on a light scheme.
        pixmap = QPixmap(str(paths.mark_path(theme.logo_ink())))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaledToHeight(int(self.LOGO_HEIGHT * ratio),
                                           Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self.logo.setPixmap(scaled)

    def set_page(self, key: str) -> None:
        self.page = key
        tab = self.tabs.get(key)
        if tab is not None:
            tab.setChecked(True)

    def _searching(self, _text: str) -> None:
        if self.page != "library":
            self.navigate.emit("library")
            self.search.setFocus()

    def natural_width(self, compact: bool) -> int:
        """The width the bar needs with the search at its narrowest."""
        margins = self.layout().contentsMargins()
        pill = self.recorder.width_for(compact)
        return (margins.left() + margins.right() + self.logo.width() + 8 +
                self.name.sizeHint().width() + 22 +
                sum(tab.width_for(compact) for tab in self.tabs.values()) + 16 +
                SEARCH_MIN + 16 + pill)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Too narrow for everything, the tabs drop their icons and the replay
        buffer its second line, before the search would get too short. On a
        bigger screen the search grows with the window and the tabs get more
        room, so the bar doesn't turn into gaps."""
        width = self.width()
        self.search.setMaximumWidth(max(SEARCH_MAX, min(SEARCH_WIDEST, int(width * 0.34))))
        pad = max(PAD, min(PAD_WIDEST, PAD + (width - 1500) // 50))
        for tab in self.tabs.values():
            tab.set_pad(pad)
        compact = width < self.natural_width(False)
        if compact == self._compact:
            return
        self._compact = compact
        for tab in self.tabs.values():
            tab.set_compact(compact)
        self.recorder.set_compact(compact)

    def paintEvent(self, event):
        super().paintEvent(event)
        # A line under the bar: the accent fading into the scheme's second colour.
        p = QPainter(self)
        width = float(self.width())
        line = QLinearGradient(0, 0, width, 0)
        start, accent, second, end = (QColor(theme.ACCENT), QColor(theme.ACCENT),
                                      QColor(theme.SECOND), QColor(theme.SECOND))
        start.setAlphaF(0.0)
        accent.setAlphaF(0.9)
        second.setAlphaF(0.9)
        end.setAlphaF(0.0)
        line.setColorAt(0, start)
        line.setColorAt(0.28, accent)
        line.setColorAt(0.72, second)
        line.setColorAt(1, end)
        p.fillRect(QRectF(0, self.height() - 1, width, 1), QBrush(line))
