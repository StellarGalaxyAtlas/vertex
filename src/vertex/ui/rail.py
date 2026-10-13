"""The rail down the left of the window: navigation, search, recorder, filters."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt, paths
from vertex.ui import icons, theme
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.widgets import IconButton, StorageGauge, label

ROW_STYLE = f"""
QPushButton {{
    background: transparent; border: none; border-radius: 8px; padding: 6px 10px;
    text-align: left; color: {theme.TEXT_MUTED};
}}
QPushButton:hover {{ background: {theme.CARD_BG}; color: {theme.TEXT}; }}
QPushButton:checked {{ background: {theme.ACCENT_SOFT}; color: #dfe4ff; }}
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

    def sizeHint(self):
        return QSize(200, self.HEIGHT)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if self.isChecked():
            background, colour = theme.ACCENT_SOFT, "#dfe4ff"
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


class RecorderCard(QFrame):
    """Replay buffer state, with start/stop and save."""

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setObjectName("Card")
        self.setStyleSheet(f"#Card {{ background: {theme.CARD_BG}; border-radius: 12px; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 6, 8)
        layout.setSpacing(6)
        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        layout.addWidget(self.dot)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.title = label("Replay buffer")
        self.title.setStyleSheet("font-weight: 600;")
        self.detail = label("", "Dim")
        text.addWidget(self.title)
        text.addWidget(self.detail)
        layout.addLayout(text, 1)
        self.save = IconButton("save-clip", "Save clip", 18)
        self.save.clicked.connect(self._save)
        self.toggle = IconButton("record", "Start the replay buffer", 18, theme.RECORDING)
        self.toggle.clicked.connect(context.recorder.toggle)
        layout.addWidget(self.save)
        layout.addWidget(self.toggle)
        context.recorder.state_changed.connect(self.update_state)
        context.config_changed.connect(lambda: self.update_state(
            context.recorder.phase, ""))
        self.update_state("stopped", "")

    def _save(self) -> None:
        try:
            self.context.message.emit(self.context.recorder.save(), "info")
        except Exception as exc:     # shown to the user
            self.context.message.emit(str(exc), "error")

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
        self.toggle.set_icon("stop" if running or state in ("starting", "restarting") else "record",
                             theme.TEXT if running else theme.RECORDING)
        self.toggle.setToolTip("Stop the replay buffer" if running else
                               "Start the replay buffer")


class Rail(QFrame):
    navigate = Signal(str)        # "library" | "sonar" | "settings"

    def __init__(self, context, state: LibraryState, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.setObjectName("Rail")
        self.setFixedWidth(theme.RAIL_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)

        self.logo = QLabel()
        self.logo.setFixedHeight(46)
        self.set_logo(context.config.logo_variant)
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
        scroll = QScrollArea()
        scroll.setWidget(self.facets_host)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)
        self.facet_group = QButtonGroup(self)

        self.gauge = StorageGauge()
        layout.addWidget(self.gauge)

        state.counts_changed.connect(self.rebuild_facets)
        state.reset.connect(self._sync_facet)
        state.storage_changed.connect(self.gauge.set_stats)
        self.rebuild_facets()

    def set_logo(self, variant: str) -> None:
        pixmap = QPixmap(str(paths.wordmark_path(variant)))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF() or 1.0
            scaled = pixmap.scaledToHeight(int(46 * ratio),
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

    def _add_facet(self, text: str, facet: Facet, count: int | None, dot: str = "") -> None:
        row = FacetRow(text, count, dot)
        row.facet = facet
        row.clicked.connect(lambda _c=False, f=facet: self._pick(f))
        self.facet_group.addButton(row)
        self.facets.addWidget(row)

    def rebuild_facets(self) -> None:
        self._clear_facets()
        state = self.state
        self._add_facet("All clips", Facet("all"), len(state.all_clips))
        self._add_facet("Favorites", Facet("favorites"), state.favorite_count())
        untagged = state.untagged_count()
        if untagged:
            self._add_facet("Untagged", Facet("untagged"), untagged)
        games = state.games()
        if games:
            self.facets.addSpacing(8)
            self.facets.addWidget(label("  GAMES", "Group"))
            for game, count in games:
                self._add_facet(game, Facet("game", game), count, theme.game_colour(game))
        people = state.people()
        if people:
            self.facets.addSpacing(8)
            self.facets.addWidget(label("  PEOPLE", "Group"))
            for person, count in people:
                self._add_facet(person, Facet("person", person), count)
        self.facets.addStretch(1)
        self._sync_facet()

    def _pick(self, facet: Facet) -> None:
        self.state.set_facet(facet)
        self.navigate.emit("library")

    def _sync_facet(self) -> None:
        current = self.state.facet
        for button in self.facet_group.buttons():
            if button.facet == current:
                button.setChecked(True)
                return
