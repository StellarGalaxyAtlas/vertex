"""Home: the newest clips, a quick mixer, the games, the disk and the people,
on one screen (TODO item 32). Vertex opens on it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.audio import channels
from vertex.core import clips as clips_mod
from vertex.ui import icons, theme
from vertex.ui.library.delegate import ClipDelegate
from vertex.ui.library.filters import FilterChip
from vertex.ui.library.model import ClipModel
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.library.view import ClipGrid
from vertex.ui.widgets import ElidedLabel, IconButton, Meter, button, label

ROWS = 2                  # rows of newest clips
CARD_MIN = 220            # a newest-clip card is at least this wide: 4 to 6 to a row
SPACING = 12


def _alpha(colour: str, alpha: float) -> QColor:
    result = QColor(colour)
    result.setAlphaF(alpha)
    return result


class Tile(QFrame):
    """A panel on Home: an icon, a title and what goes with it, then its body.
    With `glow`, the scheme's accent and second colour light two corners."""

    def __init__(self, title: str, icon_name: str, glow: bool = False, parent=None):
        super().__init__(parent)
        self.glow = glow
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(17, 17)
        theme.themed(icon, lambda: icon.setPixmap(icons.pixmap(icon_name, "TEXT", 17)), "icon")
        self.header.addWidget(icon)
        self.title = label(title)
        self.title.setStyleSheet("font-size: 11.5pt; font-weight: 600;")
        self.header.addWidget(self.title)
        outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)

    def add_link(self, text: str, on_click) -> QPushButton:
        """A link at the right of the header: where to see more."""
        self.header.addStretch(1)
        link = QPushButton(text)
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setLayoutDirection(Qt.LayoutDirection.RightToLeft)       # the arrow after
        theme.themed(link, lambda: link.setIcon(icons.icon("chevron-right", "SELECT", 14)),
                     "icon")
        theme.style(link, lambda: f"QPushButton {{ background: transparent; border: none; "
                                  f"color: {theme.SELECT}; font-weight: 600; padding: 2px 4px; }}"
                                  f"QPushButton:hover {{ color: {theme.TEXT}; }}")
        link.clicked.connect(on_click)
        self.header.addWidget(link)
        return link

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 16, 16)
        ground = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        ground.setColorAt(0, QColor(theme.CARD_BG))
        ground.setColorAt(0.6, QColor(theme.SECTION_BG))
        p.fillPath(shape, QBrush(ground))
        if self.glow:
            reach = max(rect.width(), rect.height()) * 0.5
            for centre, colour in ((rect.topLeft(), theme.ACCENT),
                                   (rect.bottomRight(), theme.SECOND)):
                light = QRadialGradient(centre, reach)
                light.setColorAt(0, _alpha(colour, 0.11))
                light.setColorAt(1, _alpha(colour, 0))
                p.fillPath(shape, QBrush(light))
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)


class LatestGrid(ClipGrid):
    """The newest clips: two rows, four to six to a row as the width allows,
    and exactly as tall as those two rows."""

    columns_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = 5
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, event):
        width = self.layout_width()
        columns = max(4, min(6, width // CARD_MIN))
        if columns != self.columns:
            self.columns = columns
            self.columns_changed.emit()
        self.card_width = max(1, width // self.columns)
        super().resizeEvent(event)
        delegate = self.itemDelegate()
        if isinstance(delegate, ClipDelegate) and \
                self.height() != ROWS * delegate.cell.height():
            self.setFixedHeight(ROWS * delegate.cell.height())


class MixerRow(QWidget):
    """One channel in the quick mixer: its badge and name, what plays on it,
    its volume and mute, and a slider in its colour."""

    def __init__(self, controller, channel: channels.Channel, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.channel = channel
        self._quiet = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(8)
        badge = QLabel()
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.themed(badge, lambda: badge.setPixmap(
            icons.pixmap(icons.channel_icon_name(channel.id), "INK", 13)), "icon")
        theme.style(badge, lambda: f"background: {self.colour}; border-radius: 6px;")
        top.addWidget(badge)
        name = label(channel.label)
        name.setStyleSheet("font-weight: 600;")
        top.addWidget(name)
        self.apps = ElidedLabel("")
        self.apps.setObjectName("Dim")
        top.addWidget(self.apps, 1)
        self.value = label("100%")
        self.value.setStyleSheet("font-weight: 600;")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setMinimumWidth(QFontMetrics(self.value.font()).horizontalAdvance("100%") + 4)
        top.addWidget(self.value)
        self.mute = IconButton("volume", "Mute", 14, "TEXT_MUTED")
        self.mute.setCheckable(True)
        self.mute.setFixedSize(24, 24)
        self.mute.toggled.connect(self._on_mute)
        top.addWidget(self.mute)
        layout.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setAccessibleName(f"{channel.label} volume")
        theme.style(self.slider, lambda: f"QSlider::sub-page:horizontal {{ background: "
                                         f"{self.colour}; border-radius: 2px; }}")
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)
        settings = controller.context.config.sonar.channel(channel.id)
        self.show_status(settings.volume, settings.muted)

    @property
    def colour(self) -> str:
        return theme.channel_colour(self.channel.id)

    def show_status(self, volume: float, muted: bool) -> None:
        """Follow the channel: the Sonar page and the system mixer change it too."""
        if self.slider.isSliderDown():
            return
        self._quiet = True
        self.slider.setValue(round(volume * 100))
        self.mute.setChecked(muted)
        self._quiet = False
        self._paint_mute()

    def set_apps(self, text: str) -> None:
        self.apps.setText(text)

    def _on_slider(self, value: int) -> None:
        self.value.setText(f"{value}%")
        if not self._quiet:
            self.controller.set_volume(self.channel.id, value / 100)

    def _on_mute(self, muted: bool) -> None:
        self._paint_mute()
        if not self._quiet:
            self.controller.context.config.sonar.channel(self.channel.id).muted = muted
            self.controller.set_muted(self.channel.id, muted)

    def _paint_mute(self) -> None:
        muted = self.mute.isChecked()
        self.mute.set_icon("mute" if muted else "volume", "DANGER" if muted else "TEXT_MUTED")
        self.mute.setToolTip(f"Unmute {self.channel.label}" if muted else
                             f"Mute {self.channel.label}")


class RankList(QWidget):
    """Names with their counts as bars, the biggest first, as many as fit;
    a click picks one."""

    picked = Signal(str)
    ROW = 28

    def __init__(self, empty: str, parent=None):
        super().__init__(parent)
        self.empty = empty
        self.entries: list[tuple[str, int]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_entries(self, entries: list[tuple[str, int]]) -> None:
        self.entries = entries
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        return QSize(200, max(3, min(len(self.entries), 8)) * self.ROW)

    def minimumSizeHint(self):
        return QSize(120, 3 * self.ROW)

    def shown(self) -> list[tuple[str, int]]:
        return self.entries[:max(1, self.height() // self.ROW)]

    def _row_at(self, y: float) -> int:
        row = int(y // self.ROW)
        return row if 0 <= row < len(self.shown()) else -1

    def mouseMoveEvent(self, event):
        row = self._row_at(event.position().y())
        if row != self._hover:
            self._hover = row
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        row = self._row_at(event.position().y())
        if event.button() == Qt.MouseButton.LeftButton and row >= 0:
            self.picked.emit(self.shown()[row][0])

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.entries:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(self.rect()).adjusted(8, 0, -8, 0),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.empty)
            return
        top = max(count for _name, count in self.entries)
        metrics = QFontMetrics(self.font())
        width = float(self.width())
        for row, (name, count) in enumerate(self.shown()):
            y = row * self.ROW
            if row == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.CARD_HOVER))
                p.drawRoundedRect(QRectF(-6, y, width + 12, self.ROW), 6, 6)
            text = str(count)
            count_w = metrics.horizontalAdvance(text)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(0, y, width, self.ROW - 8),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, width - count_w - 12, self.ROW - 8),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       metrics.elidedText(name, Qt.TextElideMode.ElideRight,
                                          int(width - count_w - 12)))
            track = QRectF(0, y + self.ROW - 7, width, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SEAM))
            p.drawRoundedRect(track, 2, 2)
            fill = QLinearGradient(track.topLeft(), track.topRight())
            fill.setColorAt(0, QColor(theme.ACCENT))
            fill.setColorAt(1, QColor(theme.SECOND))
            p.setBrush(QBrush(fill))
            p.drawRoundedRect(QRectF(track.left(), track.top(),
                                     max(4.0, track.width() * count / top), 4), 2, 2)


class PeopleRow(QWidget):
    """The people tagged most, side by side: an initial, the name, how many
    clips. As many as fit; a click picks one."""

    picked = Signal(str)
    HEIGHT = 50
    MIN_WIDTH = 104

    def __init__(self, parent=None):
        super().__init__(parent)
        self.people: list[tuple[str, int]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self.HEIGHT)

    def set_people(self, people: list[tuple[str, int]]) -> None:
        self.people = people
        self.update()

    def _tiles(self) -> list[QRectF]:
        count = min(len(self.people), max(1, (self.width() + 8) // (self.MIN_WIDTH + 8)))
        if not count:
            return []
        width = (self.width() - 8 * (count - 1)) / count
        return [QRectF(i * (width + 8), 0, width, self.HEIGHT) for i in range(count)]

    def _at(self, point: QPointF) -> int:
        return next((i for i, tile in enumerate(self._tiles()) if tile.contains(point)), -1)

    def mouseMoveEvent(self, event):
        index = self._at(event.position())
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        index = self._at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and index >= 0:
            self.picked.emit(self.people[index][0])

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        for index, tile in enumerate(self._tiles()):
            name, count = self.people[index]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.CARD_HOVER if index == self._hover else theme.CONTROL_BG))
            p.drawRoundedRect(tile, 12, 12)
            avatar = QRectF(tile.left() + 10, tile.center().y() - 15, 30, 30)
            p.setBrush(QColor(theme.game_colour(name)))
            p.drawEllipse(avatar)
            p.setFont(bold)
            p.setPen(QColor(theme.INK))
            p.drawText(avatar, Qt.AlignmentFlag.AlignCenter, (name[:1] or "?").upper())
            x = avatar.right() + 9
            room = int(tile.right() - x - 8)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x, tile.top() + 7, room, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(bold).elidedText(name, Qt.TextElideMode.ElideRight, room))
            p.setFont(small)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(x, tile.top() + 25, room, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fmt.plural(count, "clip"))


class HomeView(QWidget):
    """The tiles: the newest clips across the top, then Sonar, the games, and
    the disk with the people. `navigate` asks for a page; the library's
    filters are set first when a tile leads there."""

    navigate = Signal(str)
    open_clip = Signal(object)

    def __init__(self, context, state: LibraryState, library_view, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.library_view = library_view
        self.controller = context.sonar
        self.latest: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.CONTENT_MARGIN, 14, theme.CONTENT_MARGIN, 14)
        layout.setSpacing(SPACING)

        # Before the model: it lists `self.latest`, so that must be current
        # by the time the model hears of a change.
        state.reset.connect(self._find_latest)
        self.page_layout = layout
        self.latest_tile = self._build_latest()
        layout.addWidget(self.latest_tile)
        self.bottom = bottom = QHBoxLayout()
        bottom.setSpacing(SPACING)
        bottom.addWidget(self._build_sonar(), 1)
        bottom.addWidget(self._build_games(), 1)
        self.column = QVBoxLayout()
        self.column.setSpacing(SPACING)
        self.column.addWidget(self._build_storage())
        self.column.addWidget(self._build_people(), 1)
        bottom.addLayout(self.column, 1)
        layout.addLayout(bottom, 1)

        state.counts_changed.connect(self._show_counts)
        state.reset.connect(self._show_counts)
        state.storage_changed.connect(self._show_storage)
        self._show_counts()

    # --- The newest clips ------------------------------------------------------

    def _build_latest(self) -> Tile:
        tile = Tile("Latest clips", "library", glow=True)
        self.favorites = FilterChip("Favorites", icon_name="star")
        self.untagged = FilterChip("Untagged")
        for chip, facet in ((self.favorites, Facet("favorites")),
                            (self.untagged, Facet("untagged"))):
            chip.setCheckable(False)
            chip.clicked.connect(lambda _c=False, f=facet: self.show_in_library(f))
            tile.header.addWidget(chip)
        self.all_link = tile.add_link("All clips", lambda: self.show_in_library(Facet("all")))

        self.grid = LatestGrid()
        self._find_latest()
        self.model = ClipModel(self.state, self.context, self, source=lambda: self.latest)
        delegate = ClipDelegate(self.grid, self.state, self.grid)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(delegate)
        delegate.open_requested.connect(self.open_clip)
        delegate.tags_requested.connect(self.library_view.edit_tags)
        delegate.favorite_toggled.connect(self.state.toggle_favorite)
        delegate.rename_requested.connect(self.grid.edit)
        self.grid.customContextMenuRequested.connect(
            lambda point: self.library_view.clip_menu(self.grid, point))
        self.grid.columns_changed.connect(self._columns_changed)
        tile.body.addWidget(self.grid)

        # No clips yet: what to do about it, in place of the cards.
        self.empty = QWidget()
        empty = QVBoxLayout(self.empty)
        empty.setContentsMargins(0, 12, 0, 12)
        self.empty.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        empty.addStretch(1)
        title = label("No clips yet", "Subheading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(title)
        self.empty_text = label("", "Muted", wrap=True)
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.empty_text)
        row = QHBoxLayout()
        row.addStretch(1)
        self.empty_record = button("Start replay buffer", "primary", "record",
                                   self.context.recorder.start)
        row.addWidget(self.empty_record)
        row.addWidget(button("Import clips…", on_click=self.library_view.import_requested))
        row.addStretch(1)
        empty.addLayout(row)
        empty.addStretch(1)
        tile.body.addWidget(self.empty)
        return tile

    def _find_latest(self) -> None:
        newest = clips_mod.sort_clips(self.state.all_clips, "date", True)
        self.latest = newest[:self.grid.columns * ROWS]

    def _columns_changed(self) -> None:
        self._find_latest()
        self.model.relist()

    # --- Sonar ------------------------------------------------------------------

    def _build_sonar(self) -> Tile:
        tile = Tile("Sonar", "sonar")
        self.sonar_dot = QLabel()
        self.sonar_dot.setFixedSize(8, 8)
        tile.header.addWidget(self.sonar_dot)
        self.sonar_state = label("", "Muted")
        tile.header.addWidget(self.sonar_state)
        self.sonar_on = button("Turn on", on_click=lambda: self.controller.set_enabled(True))
        self.sonar_on.setStyleSheet("QPushButton { padding: 3px 10px; }")
        tile.header.addWidget(self.sonar_on)
        tile.add_link("Open", lambda: self.navigate.emit("sonar"))
        self.mixer = QWidget()
        rows = QVBoxLayout(self.mixer)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        self.channels: dict[str, MixerRow] = {}
        for index, channel in enumerate(channels.ALL):
            if index:
                rows.addStretch(1)       # a taller tile spreads the channels out
            self.channels[channel.id] = MixerRow(self.controller, channel)
            rows.addWidget(self.channels[channel.id])
        tile.body.addWidget(self.mixer, 1)
        self.controller.status_changed.connect(self._show_sonar)
        self.controller.streams_changed.connect(self._show_streams)
        self.controller.recorders_changed.connect(self._show_recorders)
        self._show_sonar(self.controller.status)
        self._show_streams([])
        self._show_recorders([])
        return tile

    def _show_sonar(self, status) -> None:
        enabled = self.context.config.sonar.enabled
        running = enabled and status.active
        if not status.available and status.error:
            text, colour = "No audio server", "WARN"
        elif running:
            text, colour = "Running", "SECOND"
        elif enabled:
            text, colour = "Starting…", "WARN"
        else:
            text, colour = "Off", "TEXT_DIM"
        self.sonar_state.setText(text)
        theme.style(self.sonar_dot, lambda: f"background: {theme.colour(colour)}; "
                                            f"border-radius: 4px;")
        self.sonar_on.setVisible(not enabled)
        self.mixer.setEnabled(running)
        for channel_id, entry in status.channels.items():
            if entry.present and channel_id in self.channels:
                self.channels[channel_id].show_status(entry.volume, entry.muted)

    def _show_streams(self, streams) -> None:
        names: dict[str, list[str]] = {channel.id: [] for channel in channels.OUTPUTS}
        for stream in streams:
            if stream.channel in names and stream.name not in names[stream.channel]:
                names[stream.channel].append(stream.name)
        for channel_id, apps in names.items():
            self.channels[channel_id].set_apps(", ".join(apps) or "Nothing playing")

    def _show_recorders(self, recorders) -> None:
        apps = list(dict.fromkeys(capture.name for capture in recorders))
        self.channels[channels.MIC.id].set_apps(
            f"Recording from it: {', '.join(apps)}" if apps else "Nothing recording it")

    # --- Games, the disk, people ---------------------------------------------------

    def _build_games(self) -> Tile:
        tile = Tile("Games", "game")
        self.games_count = label("", "Muted")
        tile.header.addWidget(self.games_count)
        tile.add_link("All games", self._all_games)
        self.games = RankList("Tag clips with their game, and the games show here with how "
                              "many clips each has.")
        self.games.picked.connect(lambda game: self.show_in_library(Facet("game", game)))
        tile.body.addWidget(self.games, 1)
        return tile

    def _build_storage(self) -> Tile:
        tile = Tile("Storage", "storage")
        tile.body.addStretch(1)          # alone in its column, it sits in the middle
        row = QHBoxLayout()
        row.setSpacing(8)
        self.clips_size = label("")
        self.clips_size.setStyleSheet("font-size: 17pt; font-weight: 700;")
        row.addWidget(self.clips_size, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(label("of clips", "Muted"), 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        self.free = label("", "Muted")
        row.addWidget(self.free, 0, Qt.AlignmentFlag.AlignBaseline)
        tile.body.addLayout(row)
        self.disk = Meter()
        tile.body.addWidget(self.disk)
        tile.body.addStretch(1)
        self.storage_tile = tile
        return tile

    def _build_people(self) -> Tile:
        tile = Tile("People", "people")
        self.people_count = label("", "Muted")
        tile.header.addWidget(self.people_count)
        tile.add_link("All people", self._all_people)
        self.people = PeopleRow()
        self.people.picked.connect(lambda name: self.show_in_library(Facet("person", name)))
        tile.body.addWidget(self.people)
        tile.body.addStretch(1)
        self.people_tile = tile
        return tile

    def _show_counts(self) -> None:
        state = self.state
        total = len(state.all_clips)
        favorites, untagged = state.favorite_count(), state.untagged_count()
        self.favorites.set_label("Favorites", favorites)
        self.favorites.setVisible(bool(favorites))
        self.untagged.set_label("Untagged", untagged)
        self.untagged.setVisible(bool(untagged))
        self.all_link.setText(f"All {fmt.plural(total, 'clip')}")
        self.all_link.setVisible(bool(total))
        self.grid.setVisible(bool(total))
        self.empty.setVisible(not total)
        # No clips yet: the room goes to what to do about it, not to empty tiles.
        self.page_layout.setStretchFactor(self.latest_tile, 0 if total else 1)
        self.page_layout.setStretchFactor(self.bottom, 1 if total else 0)
        if not total:
            folder = self.context.config.resolved_clip_dir()
            self.empty_text.setText(f"Clips saved into {folder} show up here. Start the replay "
                                    f"buffer and press your save-clip hotkey, or bring an "
                                    f"existing library in.")
            self.empty_record.setVisible(not self.context.recorder.running)
        games = state.games()
        self.games_count.setText(str(len(games)) if games else "")
        self.games.set_entries(games)
        people = state.people()
        self.people_count.setText(str(len(people)))
        self.people.set_people(people)
        # No one tagged: no tile kept for them; the disk takes the column.
        self.people_tile.setVisible(bool(people))
        self.column.setStretchFactor(self.storage_tile, 0 if people else 1)

    def _show_storage(self, stats) -> None:
        if stats is None:
            return
        self.clips_size.setText(stats.clips_human)
        self.free.setText(f"{stats.free_human} free")
        self.disk.set_fraction(1 - stats.fraction(stats.disk_free))
        self.storage_tile.setToolTip(f"Clips {stats.clips_human} · everything else "
                                     f"{stats.other_human} · free {stats.free_human} of "
                                     f"{stats.total_human}")

    # --- Leading to the library ------------------------------------------------------

    def show_in_library(self, facet: Facet) -> None:
        self.state.set_facet(facet)
        self.navigate.emit("library")

    def _all_games(self) -> None:
        self.show_in_library(Facet("all"))
        self.library_view.filters.games.click()

    def _all_people(self) -> None:
        self.show_in_library(Facet("all"))
        self.library_view.filters.people.click()

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.refresh()
        self.controller.refresh_streams()
