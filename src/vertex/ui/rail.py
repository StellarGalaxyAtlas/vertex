"""The rail down the left of the window: navigation, search, recorder, filters."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt, paths
from vertex.recorder.replay import RecorderError
from vertex.ui import icons, theme
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.widgets import IconButton, StorageGauge, label

ROW_STYLE = f"""
QPushButton {{
    background: transparent; border: none; border-radius: 8px; padding: 6px 10px;
    text-align: left; color: {theme.TEXT_MUTED};
}}
QPushButton:hover {{ background: {theme.CARD_BG}; color: {theme.TEXT}; }}
QPushButton:checked {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT}; }}
"""


class FacetRow(QAbstractButton):
    """One filter in the rail: an optional colour dot, a name, a count."""

    HEIGHT = 32

    def __init__(self, text: str, count: int | None = None, dot: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setText(text)
        self.setToolTip(text)
        self.count = "" if count is None else str(count)
        self.dot = dot
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        # Narrower than its text, a row elides its name; it never pushes the
        # rail's list wider than the rail (which would cut the counts off).
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(self.needed_width(), self.HEIGHT)

    def needed_width(self) -> int:
        """The width that shows the whole name and the count."""
        self.ensurePolished()
        metrics = QFontMetrics(self.font())
        count_w = metrics.horizontalAdvance(self.count) + 10 if self.count else 0
        return 10 + (16 if self.dot else 0) + metrics.horizontalAdvance(self.text()) + \
            12 + count_w + 10

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if self.isChecked():
            background, colour = theme.ACCENT_SOFT, theme.TEXT
        elif self.underMouse():
            background, colour = theme.CARD_BG, theme.TEXT
        else:
            background, colour = None, theme.TEXT_MUTED
        if background:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(background))
            p.drawRoundedRect(rect, 8, 8)
        x = 10.0
        if self.dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.dot))
            p.drawEllipse(QRectF(x, rect.center().y() - 4, 8, 8))
            x += 16
        metrics = QFontMetrics(self.font())
        count_w = metrics.horizontalAdvance(self.count) + 10 if self.count else 0
        p.setPen(QColor(theme.TEXT_DIM if not self.isChecked() else colour))
        p.drawText(QRectF(0, 0, rect.width() - 10, rect.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.count)
        p.setPen(QColor(colour))
        name = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                  int(rect.width() - x - count_w - 10))
        p.drawText(QRectF(x, 0, rect.width() - x, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)


class GroupHeader(QAbstractButton):
    """A group's heading in the rail: its name, how many entries it has, and a
    chevron. Clicking it folds the group away or brings it back."""

    HEIGHT = 26

    def __init__(self, text: str, count: int, parent=None):
        super().__init__(parent)
        self.setObjectName("Group")          # the group heading's font
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setText(text.upper())
        self.count = str(count)
        self.expanded = True
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._noun = text.lower()

    def sizeHint(self):
        return QSize(self.needed_width(), self.HEIGHT)

    def needed_width(self) -> int:
        self.ensurePolished()
        metrics = QFontMetrics(self.font())
        return 10 + metrics.horizontalAdvance(self.text()) + 8 + \
            metrics.horizontalAdvance(self.count) + 12 + 14 + 8

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.setToolTip(f"Hide the {self._noun}" if expanded else f"Show the {self._noun}")
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        hover = self.underMouse()
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.CARD_BG))
            p.drawRoundedRect(rect, 8, 8)
        colour = QColor(theme.TEXT_MUTED if hover else theme.TEXT_DIM)
        chevron = 14
        p.drawPixmap(int(rect.width()) - chevron - 8, (self.height() - chevron) // 2,
                     icons.pixmap("chevron-down" if self.expanded else "chevron-right",
                                  colour.name(), chevron))
        x = 10.0
        p.setPen(colour)
        p.drawText(QRectF(x, 0, rect.width() - x, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        x += QFontMetrics(self.font()).horizontalAdvance(self.text()) + 8
        count_font = self.font()
        count_font.setWeight(QFont.Weight.Normal)
        p.setFont(count_font)
        p.drawText(QRectF(x, 0, rect.width() - x, rect.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.count)


class RecorderCard(QFrame):
    """Replay buffer state, with save and start/stop. Red means recording,
    and only that: while the buffer is off nothing here is red."""

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setObjectName("Card")
        self.setStyleSheet(f"#Card {{ background: {theme.CARD_BG}; border-radius: 12px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        top.addWidget(self.dot)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = label("Replay buffer")
        self.title.setStyleSheet("font-weight: 600;")
        self.detail = label("", "Muted")
        text.addWidget(self.title)
        text.addWidget(self.detail)
        top.addLayout(text, 1)
        layout.addLayout(top)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.save = QPushButton(" Save clip")
        self.save.setIcon(icons.icon("save-clip", theme.TEXT, 16))
        self.save.setToolTip("Save the replay buffer as a clip")
        self.save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save.setStyleSheet("QPushButton { padding: 6px 10px; font-weight: 600; }")
        self.save.clicked.connect(self._save)
        self.toggle = IconButton("record", "Start the replay buffer", 16, theme.TEXT_MUTED,
                                 kind="")
        self.toggle.setStyleSheet("QToolButton { padding: 7px; }")
        self.toggle.clicked.connect(context.recorder.toggle)
        actions.addWidget(self.save, 1)
        actions.addWidget(self.toggle)
        layout.addLayout(actions)
        context.recorder.state_changed.connect(self.update_state)
        context.config_changed.connect(lambda: self.update_state(
            context.recorder.phase, ""))
        self.update_state("stopped", "")

    def _save(self) -> None:
        try:
            self.context.message.emit(self.context.recorder.save(), "info")
        except RecorderError:
            pass         # the recorder has told the user

    def update_state(self, state: str, error: str) -> None:
        seconds = self.context.config.recorder.replay_seconds
        running = state == "running"
        colour = {"running": theme.RECORDING, "starting": theme.WARN, "restarting": theme.WARN,
                  "failed": theme.DANGER}.get(state, theme.TEXT_DIM)
        self.dot.setStyleSheet(f"background: {colour}; border-radius: 4px;")
        self.detail.setText({
            "running": f"On · last {fmt.duration(seconds)}",
            "starting": "Starting…",
            "restarting": "Restarting…",
            "failed": "Stopped",
        }.get(state, "Off"))
        self.detail.setToolTip(error or ("Restarting to use the new settings. It starts "
                                         "empty." if state == "restarting" else ""))
        self.save.setEnabled(running)
        busy = running or state in ("starting", "restarting")
        self.toggle.set_icon("stop" if busy else "record", theme.TEXT if busy else theme.TEXT_MUTED)
        self.toggle.setToolTip("Stop the replay buffer" if running else
                               "Start the replay buffer")


class Rail(QFrame):
    navigate = Signal(str)        # "library" | "sonar" | "settings"

    LOGO_HEIGHT = 42

    def __init__(self, context, state: LibraryState, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.setObjectName("Rail")
        self.setFixedWidth(theme.RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        self.logo = QLabel()
        self.logo.setFixedHeight(self.LOGO_HEIGHT)
        self._show_logo()
        layout.addWidget(self.logo)
        layout.addSpacing(4)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search clips")
        self.search.addAction(icons.icon("search", theme.TEXT_DIM, 16),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(f"background: {theme.FIELD_BG}; border-radius: 10px;")
        self._search_timer = QTimer(self, singleShot=True, interval=150)
        self._search_timer.timeout.connect(lambda: state.set_query(self.search.text()))
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        layout.addWidget(self.search)

        self.nav = QButtonGroup(self)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, icon_name in (("library", "Library", "library"),
                                     ("sonar", "Sonar", "sonar"),
                                     ("settings", "Settings", "settings")):
            row = QPushButton(f"  {text}")
            row.setIcon(icons.icon(icon_name, theme.TEXT_MUTED))
            row.setIconSize(QSize(18, 18))
            row.setCheckable(True)
            row.setStyleSheet(ROW_STYLE + "QPushButton { padding: 8px 10px; }")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.clicked.connect(lambda _c=False, k=key: self.navigate.emit(k))
            self.nav.addButton(row)
            self.nav_buttons[key] = row
            layout.addWidget(row)

        self.recorder_card = RecorderCard(context)
        layout.addWidget(self.recorder_card)

        self.facets_host = QWidget()
        self.facets = QVBoxLayout(self.facets_host)
        self.facets.setContentsMargins(0, 0, 0, 0)
        self.facets.setSpacing(2)
        self.scroll = scroll = QScrollArea()
        scroll.setWidget(self.facets_host)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # The filters sit on the rail itself: a ground of their own drew an
        # empty box down the rail whenever there were few of them.
        scroll.viewport().setAutoFillBackground(False)
        self.facets_host.setAutoFillBackground(False)
        self.facets_host.setStyleSheet("background: transparent;")
        layout.addWidget(scroll, 1)
        self.facet_group = QButtonGroup(self)
        self.group_headers: dict[str, GroupHeader] = {}

        self.gauge = StorageGauge(short=True)
        layout.addWidget(self.gauge)

        state.counts_changed.connect(self.rebuild_facets)
        state.reset.connect(self._sync_facet)
        state.storage_changed.connect(self.gauge.set_stats)
        self.rebuild_facets()

    def _show_logo(self) -> None:
        # The light ink: the rail is dark whatever the desktop looks like.
        pixmap = QPixmap(str(paths.wordmark_path("light")))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaledToHeight(int(self.LOGO_HEIGHT * ratio),
                                           Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(ratio)
            self.logo.setPixmap(scaled)

    def set_page(self, key: str) -> None:
        button = self.nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def _clear_facets(self) -> None:
        for button in self.facet_group.buttons():
            self.facet_group.removeButton(button)
        while self.facets.count():
            item = self.facets.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _add_facet(self, text: str, facet: Facet, count: int | None, dot: str = "",
                   group: str = "") -> None:
        row = FacetRow(text, count, dot)
        row.facet = facet
        row.group = group
        row.clicked.connect(lambda _c=False, f=facet: self._pick(f))
        self.facet_group.addButton(row)
        self.facets.addWidget(row)

    def _add_group(self, key: str, title: str, entries: int) -> None:
        self.facets.addSpacing(8)
        header = GroupHeader(title, entries)
        header.clicked.connect(lambda _c=False, k=key: self.toggle_group(k))
        self.group_headers[key] = header
        self.facets.addWidget(header)

    def rebuild_facets(self) -> None:
        self._clear_facets()
        self.group_headers = {}
        state = self.state
        self._add_facet("All clips", Facet("all"), len(state.all_clips))
        self._add_facet("Favorites", Facet("favorites"), state.favorite_count())
        untagged = state.untagged_count()
        if untagged:
            self._add_facet("Untagged", Facet("untagged"), untagged)
        games = state.games()
        if games:
            self._add_group("games", "Games", len(games))
            for game, count in games:
                self._add_facet(game, Facet("game", game), count, theme.game_colour(game),
                                "games")
        people = state.people()
        if people:
            self._add_group("people", "People", len(people))
            for person, count in people:
                self._add_facet(person, Facet("person", person), count, group="people")
        self.facets.addStretch(1)
        self._sync_facet()
        self._fit_width()

    def _fit_width(self) -> None:
        """As wide as the widest filter needs, name and count, with room for
        the list's scroll bar: from RAIL_WIDTH up to RAIL_MAX_WIDTH, past
        which names are cut short."""
        rows = [*self.facet_group.buttons(), *self.group_headers.values()]
        needed = max((row.needed_width() for row in rows), default=0)
        margins = self.layout().contentsMargins()
        scroll_bar = self.scroll.verticalScrollBar().sizeHint().width()
        width = needed + margins.left() + margins.right() + scroll_bar
        self.setFixedWidth(max(theme.RAIL_WIDTH, min(theme.RAIL_MAX_WIDTH, width)))

    def toggle_group(self, key: str) -> None:
        folded = self.context.config.rail_collapsed
        if key in folded:
            folded.remove(key)
        else:
            folded.append(key)
        self.context.save_config_later()
        self._apply_folds()

    def _apply_folds(self) -> None:
        """Hide the rows of folded groups, all but the one the library is
        filtered by: what the list shows should always be visible in the rail."""
        folded = self.context.config.rail_collapsed
        for key, header in self.group_headers.items():
            header.set_expanded(key not in folded)
        for row in self.facet_group.buttons():
            row.setHidden(bool(row.group) and row.group in folded and not row.isChecked())

    def _pick(self, facet: Facet) -> None:
        self.state.set_facet(facet)
        self.navigate.emit("library")

    def _sync_facet(self) -> None:
        current = self.state.facet
        for button in self.facet_group.buttons():
            if button.facet == current:
                button.setChecked(True)
                break
        self._apply_folds()
