"""The library's filter row: All clips, Favorites and Untagged as chips,
Games and People as drop-downs with a search and their counts, then the
grid's own controls and the disk."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.ui import icons, theme
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.widgets import Meter, label

CHIP_H = 32
NAME_MAX = 220           # a chip naming a game or person elides past this


class FilterChip(QAbstractButton):
    """A filter as a pill: an optional icon, a name, a count, and a chevron
    when it opens a list. Filled with the accent's tint while it applies."""

    def __init__(self, text: str, count: int | None = None, icon_name: str = "",
                 dropdown: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.dropdown = dropdown
        self.count = "" if count is None else str(count)
        self.setText(text)
        self.setCheckable(not dropdown)
        self.applied = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedHeight(CHIP_H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_label(self, text: str, count: int | None) -> None:
        self.setText(text)
        self.setToolTip(text if QFontMetrics(self._font()).horizontalAdvance(text) > NAME_MAX
                        else "")
        self.count = "" if count is None else str(count)
        self.updateGeometry()
        self.update()

    def is_applied(self) -> bool:
        return self.isChecked() if self.isCheckable() else self.applied

    def set_applied(self, applied: bool) -> None:
        if self.isCheckable():
            self.setChecked(applied)
        else:
            self.applied = applied
        self.update()

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold if self.is_applied() else QFont.Weight.Medium)
        return font

    def _name_width(self) -> int:
        # A pixel spare: text measured to its exact width can still be elided.
        return min(NAME_MAX, QFontMetrics(self._font()).horizontalAdvance(self.text()) + 2)

    def sizeHint(self):
        metrics = QFontMetrics(self._font())
        width = 12 + (20 if self.icon_name else 0) + self._name_width()
        if self.count:
            width += 7 + metrics.horizontalAdvance(self.count)
        if self.dropdown:
            width += 6 + 12
        return QSize(width + 12, CHIP_H)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        applied, hover = self.is_applied(), self.underMouse()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if applied:
            edge = QColor(theme.ACCENT)
            edge.setAlphaF(0.6)
            ground = QColor(theme.ACCENT_SOFT)
        else:
            edge = QColor(theme.EDGE if hover or self.hasFocus() else theme.LINE)
            ground = QColor(theme.CARD_HOVER if hover else theme.CARD_BG)
        if self.hasFocus():
            edge = QColor(theme.SELECT)
        p.setPen(QPen(edge, 1))
        p.setBrush(ground)
        p.drawRoundedRect(rect, CHIP_H / 2, CHIP_H / 2)
        x = 12.0
        if self.icon_name:
            p.drawPixmap(int(x), (CHIP_H - 14) // 2, icons.pixmap(self.icon_name, "ACCENT", 14))
            x += 20
        font = self._font()
        metrics = QFontMetrics(font)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT))
        name = metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, self._name_width())
        p.drawText(QRectF(x, 0, self._name_width() + 2, CHIP_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        x += self._name_width()
        if self.count:
            x += 7
            p.setFont(self.font())
            p.setPen(QColor(theme.TEXT_MUTED if applied else theme.TEXT_DIM))
            p.drawText(QRectF(x, 0, self.width() - x, CHIP_H),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.count)
            x += QFontMetrics(self.font()).horizontalAdvance(self.count)
        if self.dropdown:
            p.drawPixmap(int(x) + 6, (CHIP_H - 12) // 2,
                         icons.pixmap("chevron-down", "TEXT_MUTED", 12))


class _RowDelegate(QStyledItemDelegate):
    """A row of the drop-down: a game's colour dot, its name, its count."""

    ROW = 32

    def sizeHint(self, _option, _index):
        return QSize(0, self.ROW)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(0, 1, 0, -1)
        facet = index.data(Qt.ItemDataRole.UserRole)
        current = index.data(Qt.ItemDataRole.UserRole + 1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT_SOFT))
            painter.drawRoundedRect(rect, 8, 8)
        elif selected or hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.CARD_HOVER))
            painter.drawRoundedRect(rect, 8, 8)
        x = rect.left() + 12
        if facet.kind == "game":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.game_colour(facet.value)))
            painter.drawEllipse(QRectF(x, rect.center().y() - 4, 8, 8))
            x += 16
        count = index.data(Qt.ItemDataRole.UserRole + 2)
        font = QFont(option.font)
        if current:
            font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        count_w = metrics.horizontalAdvance(count) + 12
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_MUTED if current else theme.TEXT_DIM))
        painter.drawText(QRectF(rect.left(), rect.top(), rect.width() - 12, rect.height()),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count)
        painter.setPen(QColor(theme.TEXT))
        name = metrics.elidedText(index.data(Qt.ItemDataRole.DisplayRole),
                                  Qt.TextElideMode.ElideRight, int(rect.right() - x - count_w))
        painter.drawText(QRectF(x, rect.top(), rect.right() - x, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        painter.restore()


class FacetMenu(QFrame):
    """The games or the people under their chip: a search, then every one with
    its count, the one the library is filtered by marked. `picked` carries
    the facet chosen."""

    picked = Signal(object)
    rename = Signal(str)          # a game, by right-click › Rename… or F2
    VISIBLE_ROWS = 10

    def __init__(self, placeholder: str, rows: list[tuple[str, Facet, int]], current: Facet,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("FacetMenu")
        theme.style(self, lambda: f"#FacetMenu {{ background: {theme.CARD_BG}; border: 1px solid "
                                  f"{theme.SEAM}; border-radius: 12px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.find = QLineEdit()
        self.find.setPlaceholderText(placeholder)
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter)
        self.find.installEventFilter(self)
        self.find.returnPressed.connect(self._pick_current)
        layout.addWidget(self.find)
        self.list = QListWidget()
        self.list.setItemDelegate(_RowDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(lambda item: self._pick(item))
        self.list.entered.connect(lambda _i: self.list.viewport().update())
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        for text, facet, count in rows:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, facet)
            item.setData(Qt.ItemDataRole.UserRole + 1, facet == current)
            item.setData(Qt.ItemDataRole.UserRole + 2, str(count))
            item.setToolTip(text)
            self.list.addItem(item)
        layout.addWidget(self.list)
        shown = min(len(rows), self.VISIBLE_ROWS)
        self.list.setFixedHeight(shown * _RowDelegate.ROW + 4)
        self.list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        first = None
        for row in range(self.list.count()):
            item = self.list.item(row)
            facet = item.data(Qt.ItemDataRole.UserRole)
            hidden = bool(needle) and (facet.kind == "all" or needle not in item.text().casefold())
            item.setHidden(hidden)
            if not hidden and first is None:
                first = row
        if first is not None:
            self.list.setCurrentRow(first)

    def _game_of(self, item: QListWidgetItem | None) -> str:
        facet = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return facet.value if facet is not None and facet.kind == "game" else ""

    def _menu(self, point) -> None:
        game = self._game_of(self.list.itemAt(point))
        if not game:
            return
        menu = QMenu(self)
        menu.addAction("Rename…", lambda: self._rename(game))
        menu.exec(self.list.viewport().mapToGlobal(point))

    def _rename(self, game: str) -> None:
        self.close()
        self.rename.emit(game)

    def keyPressEvent(self, event):
        game = self._game_of(self.list.currentItem())
        if event.key() == Qt.Key.Key_F2 and game:
            self._rename(game)
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.find and event.type() == QEvent.Type.KeyPress and \
                event.key() == Qt.Key.Key_F2:
            self.keyPressEvent(event)
            return True
        # Up and down move through the list while typing in the search.
        if watched is self.find and event.type() == QEvent.Type.KeyPress and \
                event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            row = self.list.currentRow() + step
            while 0 <= row < self.list.count() and self.list.item(row).isHidden():
                row += step
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return True
        return super().eventFilter(watched, event)

    def _pick_current(self) -> None:
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            self._pick(item)

    def _pick(self, item: QListWidgetItem) -> None:
        self.close()
        self.picked.emit(item.data(Qt.ItemDataRole.UserRole))

    def show_under(self, anchor: QWidget) -> None:
        self.setFixedWidth(max(anchor.width(), 300))
        self.adjustSize()
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 6)))
        self.show()
        self.find.setFocus()


class FilterRow(QWidget):
    """The filters, then the grid's controls (`tools`) and the disk. When the
    page is too narrow for all of it, the disk's text goes first, then the
    card-size icons, then the disk's bar."""

    rename_game = Signal(str)

    def __init__(self, state: LibraryState, tools: list[QWidget], size_icons: list[QWidget],
                 parent=None):
        super().__init__(parent)
        self.state = state
        self.size_icons = size_icons
        self.menu: FacetMenu | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.all = FilterChip("All clips")
        self.favorites = FilterChip("Favorites", icon_name="star")
        self.untagged = FilterChip("Untagged")
        for chip, facet in ((self.all, Facet("all")), (self.favorites, Facet("favorites")),
                            (self.untagged, Facet("untagged"))):
            chip.clicked.connect(lambda _c=False, f=facet: state.set_facet(f))
            layout.addWidget(chip)
        self.divider = QFrame()
        self.divider.setFixedSize(1, 20)
        theme.style(self.divider, lambda: f"background: {theme.SEAM};")
        layout.addSpacing(6)
        layout.addWidget(self.divider)
        layout.addSpacing(6)
        self.games = FilterChip("All games", dropdown=True)
        self.games.clicked.connect(lambda: self._open("game"))
        layout.addWidget(self.games)
        self.people = FilterChip("People", dropdown=True)
        self.people.clicked.connect(lambda: self._open("person"))
        layout.addWidget(self.people)
        self.found = label("", "Dim")
        layout.addSpacing(6)
        layout.addWidget(self.found)
        layout.addStretch(1)

        right = self._right = QHBoxLayout()
        right.setSpacing(14)
        for tool in tools:
            right.addWidget(tool, 0, Qt.AlignmentFlag.AlignVCenter)
        self.disk = QWidget()
        disk = QHBoxLayout(self.disk)
        disk.setContentsMargins(0, 0, 0, 0)
        disk.setSpacing(8)
        self.meter = Meter()
        self.meter.setFixedSize(56, 6)
        disk.addWidget(self.meter, 0, Qt.AlignmentFlag.AlignVCenter)
        self.disk_text = QLabel()
        self.disk_text.setObjectName("Muted")
        disk.addWidget(self.disk_text)
        right.addWidget(self.disk)
        layout.addLayout(right)

        state.counts_changed.connect(self.refresh)
        state.reset.connect(self.refresh)
        state.storage_changed.connect(self.set_storage)
        self.refresh()

    # --- What the chips say ----------------------------------------------------

    def refresh(self) -> None:
        state = self.state
        facet = state.facet
        self.all.set_label("All clips", len(state.all_clips))
        self.all.set_applied(facet.kind == "all")
        self.favorites.set_label("Favorites", state.favorite_count())
        self.favorites.set_applied(facet.kind == "favorites")
        untagged = state.untagged_count()
        self.untagged.set_label("Untagged", untagged)
        self.untagged.set_applied(facet.kind == "untagged")
        self.untagged.setVisible(bool(untagged) or facet.kind == "untagged")
        games, people = state.games(), state.people()
        if facet.kind == "game":
            self.games.set_label(facet.value, dict(games).get(facet.value, 0))
        else:
            self.games.set_label("All games", len(games))
        self.games.set_applied(facet.kind == "game")
        self.games.setVisible(bool(games) or facet.kind == "game")
        if facet.kind == "person":
            count = next((n for name, n in people if name.casefold() == facet.value.casefold()),
                         0)
            self.people.set_label(facet.value, count)
        else:
            self.people.set_label("People", len(people))
        self.people.set_applied(facet.kind == "person")
        self.people.setVisible(bool(people) or facet.kind == "person")
        self.divider.setVisible(self.games.isVisible() or self.people.isVisible())
        if state.query:
            total = fmt.plural(len(state.all_clips), "clip")
            self.found.setText(f"{len(state.visible)} of {total} match")
        self.found.setVisible(bool(state.query))
        self._fit()

    def set_storage(self, stats) -> None:
        if stats is None:
            return
        self.meter.set_fraction(1 - stats.fraction(stats.disk_free))
        self.disk_text.setText(f"{stats.clips_human} · {stats.free_human} free")
        self.disk.setToolTip(f"Clips {stats.clips_human} · everything else {stats.other_human} · "
                             f"free {stats.free_human} of {stats.total_human}")
        self._fit()

    # --- The drop-downs ------------------------------------------------------

    def _open(self, kind: str) -> None:
        state = self.state
        if kind == "game":
            entries, placeholder, chip = state.games(), "Find a game", self.games
            first = ("All games", Facet("all"), len(state.all_clips))
        else:
            entries, placeholder, chip = state.people(), "Find a person", self.people
            first = ("Everyone", Facet("all"), len(state.all_clips))
        rows = [first] + [(name, Facet(kind, name), count) for name, count in entries]
        self.menu = FacetMenu(placeholder, rows, state.facet, self)
        self.menu.picked.connect(state.set_facet)
        self.menu.rename.connect(self.rename_game)
        self.menu.show_under(chip)

    # --- Narrow pages -----------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _invalidate(self, groups) -> None:
        """Hidden widgets count at once only once every layout between them
        and this row forgets the size it worked out."""
        for widget in (widget for group in groups for widget in group):
            parent = widget.parentWidget()
            while parent is not None and parent is not self:
                if parent.layout() is not None:
                    parent.layout().invalidate()
                parent.updateGeometry()
                parent = parent.parentWidget()
        self._right.invalidate()
        self.layout().invalidate()

    def _fit(self) -> None:
        """Show as much of the disk and the card-size icons as fits."""
        groups = ([self.disk_text], self.size_icons, [self.disk])
        for level in range(len(groups) + 1):
            for index, group in enumerate(groups):
                for widget in group:
                    widget.setVisible(index >= level)
            self._invalidate(groups)
            if self.layout().sizeHint().width() <= self.width():
                break
