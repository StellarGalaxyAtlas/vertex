"""Home: the newest clips, the games, the disk and the people, on one screen.
Vertex opens on it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.core import clips as clips_mod
from vertex.ui import icons, theme
from vertex.ui.library.delegate import INFO_H, PAD, ClipDelegate
from vertex.ui.library.filters import FilterChip
from vertex.ui.library.model import ClipModel
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.library.view import ClipGrid
from vertex.ui.widgets import button, label

ROWS = 2                  # rows of newest clips (one, while one row holds them all)
COLUMNS = (4, 6)          # how many to a row, at the least and the most
CARD_MIN = 220            # a newest-clip card is at least this wide
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
    """The newest clips, in the rows and columns Home gives them (`set_shape`),
    and exactly as tall as those rows."""

    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns, self.rows = 5, ROWS
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def row_height(self, columns: int) -> int:
        """How tall a row of cards is at `columns` to a row."""
        cell = max(1, self.layout_width()) // columns
        return (cell - 2 * PAD) * 9 // 16 + INFO_H + 2 * PAD

    def set_shape(self, columns: int, rows: int) -> bool:
        """Lay the cards out `columns` by `rows`; whether that changed anything."""
        if (columns, rows) == (self.columns, self.rows):
            return False
        self.columns, self.rows = columns, rows
        self._fit()
        return True

    def _fit(self) -> None:
        self.card_width = max(1, self.layout_width() // self.columns)
        delegate = self.itemDelegate()
        if isinstance(delegate, ClipDelegate):
            self.fit_cells(delegate)
            height = self.rows * delegate.cell.height()
            if self.height() != height:
                self.setFixedHeight(height)

    def resizeEvent(self, event):
        self.card_width = max(1, self.layout_width() // self.columns)
        super().resizeEvent(event)
        self._fit()
        self.resized.emit()


class RankList(QWidget):
    """Names with their counts as bars, the biggest first, as many as fit;
    a click picks one."""

    picked = Signal(str)
    ROW = 28
    ROW_MOST = 56         # with room to spare and few names, rows open up to this

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

    def pitch(self) -> float:
        """How tall a row is: as many as fit at ROW; when they all fit with room
        over, they share it, up to ROW_MOST."""
        shown = len(self.shown())
        if not shown or shown < len(self.entries):
            return float(self.ROW)
        return max(float(self.ROW), min(float(self.ROW_MOST), self.height() / shown))

    def _row_at(self, y: float) -> int:
        row = int(y // self.pitch())
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
        pitch = self.pitch()
        bar = 4.0 + (pitch - self.ROW) / 7           # 4 px, thickening to 8 as rows open up
        for row, (name, count) in enumerate(self.shown()):
            y = row * pitch
            if row == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.CARD_HOVER))
                p.drawRoundedRect(QRectF(-6, y, width + 12, pitch), 6, 6)
            text = str(count)
            count_w = metrics.horizontalAdvance(text)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(0, y, width, pitch - 4 - bar),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, width - count_w - 12, pitch - 4 - bar),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       metrics.elidedText(name, Qt.TextElideMode.ElideRight,
                                          int(width - count_w - 12)))
            track = QRectF(0, y + pitch - 3 - bar, width, bar)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SEAM))
            p.drawRoundedRect(track, bar / 2, bar / 2)
            fill = QLinearGradient(track.topLeft(), track.topRight())
            fill.setColorAt(0, QColor(theme.ACCENT))
            fill.setColorAt(1, QColor(theme.SECOND))
            p.setBrush(QBrush(fill))
            p.drawRoundedRect(QRectF(track.left(), track.top(),
                                     max(bar, track.width() * count / top), bar),
                              bar / 2, bar / 2)


class PeopleRow(QWidget):
    """The people tagged most: an initial, the name, how many clips. As many
    as fit, in as many rows as the tile has room for; tall tiles stand the
    name under a bigger initial. A click picks one."""

    picked = Signal(str)
    HEIGHT = 50           # a tile at its smallest
    TALLEST = 260
    MIN_WIDTH = 104
    GAP = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.people: list[tuple[str, int]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self):
        return QSize(3 * self.MIN_WIDTH, self.HEIGHT)

    def set_people(self, people: list[tuple[str, int]]) -> None:
        self.people = people
        self.update()

    def _tiles(self) -> list[QRectF]:
        count = len(self.people)
        if not count:
            return []
        gap, width, height = self.GAP, self.width(), self.height()
        columns = min(count, max(1, (width + gap) // (self.MIN_WIDTH + gap)))
        rows = min(-(-count // columns), max(1, (height + gap) // (self.HEIGHT + gap)))
        tile_w = (width - gap * (columns - 1)) / columns
        tile_h = min(float(self.TALLEST), (height - gap * (rows - 1)) / rows)
        top = (height - (rows * tile_h + gap * (rows - 1))) / 2
        return [QRectF(c * (tile_w + gap), top + r * (tile_h + gap), tile_w, tile_h)
                for r in range(rows) for c in range(columns)][:count]

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
            tall = tile.height() >= 92
            side = max(44.0, min(88.0, tile.height() * 0.38)) if tall else 30.0
            if tall:
                avatar = QRectF(tile.center().x() - side / 2, tile.top() + (tile.height() - side
                                                                           - 42) / 2, side, side)
            else:
                avatar = QRectF(tile.left() + 10, tile.center().y() - side / 2, side, side)
            p.setBrush(QColor(theme.game_colour(name)))
            p.drawEllipse(avatar)
            initial = QFont(bold)
            initial.setPointSizeF(bold.pointSizeF() * (1.4 if tall else 1.0))
            p.setFont(initial)
            p.setPen(QColor(theme.INK))
            p.drawText(avatar, Qt.AlignmentFlag.AlignCenter, (name[:1] or "?").upper())
            if tall:
                text = QRectF(tile.left() + 8, avatar.bottom() + 6, tile.width() - 16, 18)
                align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            else:
                x = avatar.right() + 9
                text = QRectF(x, tile.center().y() - 18, tile.right() - x - 8, 18)
                align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            p.setFont(bold)
            p.setPen(QColor(theme.TEXT))
            p.drawText(text, align, QFontMetrics(bold).elidedText(
                name, Qt.TextElideMode.ElideRight, int(text.width())))
            p.setFont(small)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(text.translated(0, 18), align, fmt.plural(count, "clip"))


class DiskBar(QWidget):
    """The disk as one bar: the clips, everything else on it, and what is free."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parts = (0.0, 0.0)
        self.setFixedHeight(8)

    def set_stats(self, stats) -> None:
        self.parts = (stats.fraction(stats.clips_bytes), stats.fraction(stats.other_used))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        shape = QPainterPath()
        shape.addRoundedRect(rect, 4, 4)
        p.setClipPath(shape)
        p.fillRect(rect, QColor(theme.SEAM))
        x = 0.0
        for fraction, colour in zip(self.parts, ("ACCENT", "SECOND"), strict=True):
            width = rect.width() * fraction
            p.fillRect(QRectF(x, 0, width, rect.height()), QColor(theme.colour(colour)))
            x += width


class StorageArea(QWidget):
    """The disk: the clips' size and what is free, over a bar of it; with
    room to spare, what the bar is made of. It asks only for the first
    part's room, so the breakdown never makes the tile taller."""

    PARTS = (("Clips", "ACCENT"), ("Everything else", "SECOND"), ("Free", "SEAM"),
             ("Disk", ""))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary = QWidget(self)
        column = QVBoxLayout(self.summary)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.clips_size = label("")
        self.clips_size.setStyleSheet("font-size: 17pt; font-weight: 700;")
        row.addWidget(self.clips_size, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(label("of clips", "Muted"), 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        self.free = label("", "Muted")
        row.addWidget(self.free, 0, Qt.AlignmentFlag.AlignBaseline)
        column.addLayout(row)
        self.bar = DiskBar()
        column.addWidget(self.bar)
        self.legend = QWidget(self)
        grid = QGridLayout(self.legend)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.values: dict[str, QLabel] = {}
        for index, (name, colour) in enumerate(self.PARTS):
            dot = QLabel()
            dot.setFixedSize(10, 10)
            if colour:
                theme.style(dot, lambda c=colour: f"background: {theme.colour(c)}; "
                                                  f"border-radius: 3px;")
            grid.addWidget(dot, index, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(label(name, "Muted"), index, 1)
            value = label("")
            value.setStyleSheet("font-weight: 600;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(value, index, 2)
            self.values[name] = value
        grid.setColumnStretch(1, 1)
        self.legend.hide()

    def sizeHint(self):
        return self.summary.sizeHint()

    def minimumSizeHint(self):
        return self.summary.minimumSizeHint()

    def set_stats(self, stats) -> None:
        self.clips_size.setText(stats.clips_human)
        self.free.setText(f"{stats.free_human} free")
        self.bar.set_stats(stats)
        for name, text in (("Clips", stats.clips_human), ("Everything else", stats.other_human),
                           ("Free", stats.free_human), ("Disk", stats.total_human)):
            self.values[name].setText(text)
        self._place()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        """The summary, and the breakdown under it if it fits, as one block in
        the middle of the room. Room over first opens the breakdown's rows up
        (to a row's height again), then is shared above and below."""
        width, height = self.width(), self.height()
        summary = self.summary.sizeHint().height()
        grid = self.legend.layout()
        grid.setVerticalSpacing(6)
        legend = self.legend.sizeHint().height()
        gap = 16
        shown = height >= summary + gap + legend
        if shown:
            rows = len(self.PARTS)
            grow = min((height - summary - gap - legend) // rows, legend // rows)
            grid.setVerticalSpacing(6 + grow)
            gap += grow
            legend += grow * (rows - 1)
        block = summary + (gap + legend if shown else 0)
        top = max(0, (height - block) // 2)
        self.summary.setGeometry(0, top, width, summary)
        self.legend.setVisible(shown)
        if shown:
            self.legend.setGeometry(0, top + summary + gap, width, legend)


class HomeView(QWidget):
    """The tiles: the newest clips across the top, then the games, and the
    disk with the people. `navigate` asks for a page; the library's
    filters are set first when a tile leads there."""

    navigate = Signal(str)
    open_clip = Signal(object)

    def __init__(self, context, state: LibraryState, library_view, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.library_view = library_view
        self.latest: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._fit_timer = QTimer(self, singleShot=True, interval=0)
        self._fit_timer.timeout.connect(self._fit)
        self.scroll = scroll = QScrollArea()
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
        self.games_tile = self._build_games()
        bottom.addWidget(self.games_tile, 1)
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
        self.library_view.connect_keys(self.grid)
        self.grid.customContextMenuRequested.connect(
            lambda point: self.library_view.clip_menu(self.grid, point))
        self.grid.resized.connect(self._fit_timer.start)
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
        self.latest = newest[:self.grid.columns * self.grid.rows]

    def _fit(self) -> None:
        """Two rows of newest clips, four to six to a row as the width allows;
        one row while that holds them all. The tiles under them take the rest
        of the height and make use of it."""
        width = self.grid.layout_width()
        if width <= 0:
            return
        columns = max(COLUMNS[0], min(COLUMNS[1], width // CARD_MIN))
        rows = ROWS if len(self.state.all_clips) > columns else 1
        if self.grid.set_shape(columns, rows):
            self._find_latest()
            self.model.relist()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_timer.start()

    # --- Games, the disk, people ---------------------------------------------------

    def _build_games(self) -> Tile:
        tile = Tile("Games", "game")
        self.games_count = label("", "Muted")
        tile.header.addWidget(self.games_count)
        tile.add_link("All games", self._all_games)
        self.games = RankList("Tag clips with a game to see them here")
        self.games.picked.connect(lambda game: self.show_in_library(Facet("game", game)))
        tile.body.addWidget(self.games, 1)
        return tile

    def _build_storage(self) -> Tile:
        tile = Tile("Storage", "storage")
        self.storage = StorageArea()
        tile.body.addWidget(self.storage, 1)
        self.storage_tile = tile
        return tile

    def _build_people(self) -> Tile:
        tile = Tile("People", "people")
        self.people_count = label("", "Muted")
        tile.header.addWidget(self.people_count)
        tile.add_link("All people", self._all_people)
        self.people = PeopleRow()
        self.people.picked.connect(lambda name: self.show_in_library(Facet("person", name)))
        tile.body.addWidget(self.people, 1)
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
            self.empty_text.setText("Start the replay buffer and save a clip, or import "
                                    "existing clips.")
            self.empty_record.setVisible(not self.context.recorder.running)
        games = state.games()
        self.games_count.setText(str(len(games)) if games else "")
        self.games.set_entries(games)
        people = state.people()
        self.people_count.setText(str(len(people)))
        self.people.set_people(people)
        # No one tagged: no tile kept for them; the disk takes the column.
        self.people_tile.setVisible(bool(people))
        self.column.setStretchFactor(self.storage_tile, 1)
        self._fit_timer.start()

    def _show_storage(self, stats) -> None:
        if stats is None:
            return
        self.storage.set_stats(stats)
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
