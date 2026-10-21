"""The clip library: a header, the card grid, and what to do with a card."""

from __future__ import annotations

import os

from PySide6.QtCore import QModelIndex, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QSlider,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt, platform
from vertex.config import CARD_WIDTH_DEFAULT, CARD_WIDTH_RANGE
from vertex.core import storage
from vertex.logs import CLIPS as log
from vertex.media import export, probe
from vertex.media import tracks as track_labels
from vertex.media.ffmpeg import Cancelled
from vertex.ui import icons, theme, workers
from vertex.ui.dialogs.export import copy_files_to_clipboard
from vertex.ui.dialogs.tags import RenameGameDialog, TagDialog
from vertex.ui.library.delegate import INFO_H, PAD, ClipDelegate
from vertex.ui.library.filters import FilterRow
from vertex.ui.library.model import ClipModel, ClipRole
from vertex.ui.library.selection import SelectionBar
from vertex.ui.library.state import Facet, LibraryState
from vertex.ui.widgets import ChoiceDialog, IconButton, Segmented, button, label

CARD_STEP = 20           # how much one notch of the size slider or Ctrl+scroll changes
PREVIEW_DELAY_MS = 450
PREVIEW_FRAME_MS = 330


class ClipGrid(QListView):
    """A virtualised grid: only the cards on screen are ever painted. Cards are
    at least `card_width` wide, and stretch to fill their row.

    The keyboard moves a focus ring between cards (shown only once a key is
    used): Enter opens, Delete deletes, F2 renames, F favorites, the menu key
    or Shift+F10 opens the card's menu. Ctrl+A and Esc ask to pick every card
    and none."""

    hovered_row = Signal(int)
    zoomed = Signal(int)             # Ctrl+scroll: notches, + for bigger cards
    open_key = Signal(object)        # clip
    delete_key = Signal(object)      # clip
    favorite_key = Signal(object)    # clip
    select_all_key = Signal()
    escape_key = Signal()

    MOVE_KEYS = frozenset({Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                           Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp,
                           Qt.Key.Key_PageDown})

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(28)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hovered = -1
        self.card_width = CARD_WIDTH_DEFAULT
        self.keyboard = False        # the focus ring shows: a key moved it last
        self._last_row = 0           # where the ring comes back after the cards reload

    def focus_row(self) -> int:
        """The card the focus ring is on, or -1 while it doesn't show."""
        index = self.currentIndex()
        return index.row() if self.keyboard and self.hasFocus() and index.isValid() else -1

    def _show_ring(self, shown: bool) -> None:
        if shown != self.keyboard:
            self.keyboard = shown
            self.viewport().update()

    def keyPressEvent(self, event):
        key = event.key()
        index = self.currentIndex()
        if self.state() == QAbstractItemView.State.EditingState:
            super().keyPressEvent(event)
            return
        if key in self.MOVE_KEYS:
            if not self.keyboard and index.isValid():
                # The first key shows where the ring is; the next ones move it.
                self._show_ring(True)
                self.scrollTo(index)
                return
            self._show_ring(True)
            rows = self.model().rowCount() if self.model() is not None else 0
            if not index.isValid() and rows:
                # After a delete or a reload: the card that took its place.
                self.setCurrentIndex(self.model().index(min(self._last_row, rows - 1), 0))
                self.scrollTo(self.currentIndex())
                return
            super().keyPressEvent(event)
            return
        clip = index.data(ClipRole) if index.isValid() else None
        plain = not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all_key.emit()
            return
        if plain and key == Qt.Key.Key_Escape:
            self.escape_key.emit()
            return
        if clip is not None and (key == Qt.Key.Key_Menu or (
                key == Qt.Key.Key_F10 and event.modifiers() == Qt.KeyboardModifier.ShiftModifier)):
            self._show_ring(True)
            self.customContextMenuRequested.emit(self.visualRect(index).center())
        elif clip is not None and plain and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_key.emit(clip)
        elif plain and key == Qt.Key.Key_Delete:
            self.delete_key.emit(clip)          # None without a ring: the picked cards
        elif clip is not None and plain and key == Qt.Key.Key_F2:
            self._show_ring(True)
            self.edit(index)
        elif clip is not None and plain and key == Qt.Key.Key_F:
            self._show_ring(True)
            self.favorite_key.emit(clip)
        else:
            super().keyPressEvent(event)

    def reset(self):
        super().reset()
        # The cards reloaded (a delete, a filter): the ring stays where it was.
        rows = self.model().rowCount() if self.model() is not None else 0
        if self.keyboard and rows:
            self.setCurrentIndex(self.model().index(min(self._last_row, rows - 1), 0))

    def currentChanged(self, current, previous):
        super().currentChanged(current, previous)
        if current.isValid():
            self._last_row = current.row()

    def keyboardSearch(self, search):
        # Typing a letter doesn't jump to a card: F is a key of its own, and
        # the cards' titles are mostly file names.
        pass

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.viewport().update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.viewport().update()

    def mousePressEvent(self, event):
        self._show_ring(False)
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        delegate = self.itemDelegate()
        if isinstance(delegate, ClipDelegate):
            self.fit_cells(delegate)

    def set_card_width(self, width: int) -> None:
        self.card_width = width
        delegate = self.itemDelegate()
        if isinstance(delegate, ClipDelegate):
            self.fit_cells(delegate)

    def layout_width(self) -> int:
        """The width QListView lays the cards out in. With the scroll bar shown
        as needed, it keeps room for one whether or not it shows: cells that
        fill the viewport when there is none would lose their last column."""
        width = self.maximumViewportSize().width()
        if self.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded:
            style = self.style()
            width -= style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None,
                                       self.verticalScrollBar())
            if style.styleHint(QStyle.StyleHint.SH_ScrollView_FrameOnlyAroundContents):
                width -= 2 * style.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth)
        return width - 1             # a row wraps once a cell reaches its last pixel

    def fit_cells(self, delegate: ClipDelegate) -> None:
        width = max(1, self.layout_width())
        columns = max(1, width // self.card_width)
        cell_w = width // columns
        thumb_h = (cell_w - 2 * PAD) * 9 // 16
        cell = QSize(cell_w, thumb_h + INFO_H + 2 * PAD)
        model = self.model()
        if isinstance(model, ClipModel):
            model.set_thumb_width(round((cell_w - 2 * PAD) * self.devicePixelRatioF()))
        if cell != delegate.cell:
            delegate.cell = cell
            self.setGridSize(cell)
            self.doItemsLayout()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            notches = event.angleDelta().y() // 120
            if notches:
                self.zoomed.emit(notches)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        row = self.indexAt(event.position().toPoint()).row()
        if row != self._hovered:
            self._hovered = row
            self.hovered_row.emit(row)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hovered = -1
        self.hovered_row.emit(-1)


class LibraryView(QWidget):
    open_clip = Signal(object)
    import_requested = Signal()
    # A toast: text, level, how long it shows (0 = until replaced), what a click does.
    notice = Signal(str, str, int, object)

    def __init__(self, context, state: LibraryState, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.CONTENT_MARGIN, 16, theme.CONTENT_MARGIN - 8, 10)
        layout.setSpacing(12)

        # The filters the rail had, in a row with the grid's own controls.
        self.sort = Segmented([("date", "Date"), ("game", "Game")], "date", directional=True)
        self.sort.changed.connect(state.set_sort)
        card_size = self._build_card_size()
        refresh = IconButton("refresh", "Refresh (F5)")
        refresh.clicked.connect(self.reload)
        self.filters = FilterRow(state, [self.sort, card_size, refresh], self.size_icons)
        self.filters.setContentsMargins(0, 0, 8, 0)
        self.filters.rename_game.connect(self.rename_game)
        # While clips are picked, what to do with them takes the filters' place.
        self.selection_bar = SelectionBar()
        self.selection_bar.acted.connect(self._act_on_picked)
        self.selection_bar.cleared.connect(self.clear_selection)
        self.top = QStackedWidget()
        self.top.addWidget(self.filters)
        self.top.addWidget(self.selection_bar)
        layout.addWidget(self.top)
        self._anchor = ""            # where a Shift-click picks from

        self.stack = QStackedWidget()
        self.grid = ClipGrid()
        self.model = ClipModel(state, context, self)
        self.delegate = ClipDelegate(self.grid, state, self.grid, selectable=True)
        self.grid.setModel(self.model)
        self.grid.setItemDelegate(self.delegate)
        self.stack.addWidget(self.grid)
        self.empty = self._build_empty()
        self.stack.addWidget(self.empty)
        layout.addWidget(self.stack, 1)

        self.delegate.open_requested.connect(self.open_clip)
        self.delegate.tags_requested.connect(self.edit_tags)
        self.delegate.favorite_toggled.connect(state.toggle_favorite)
        self.delegate.rename_requested.connect(self.grid.edit)
        self.delegate.select_clicked.connect(self._pick_clicked)
        self.connect_keys(self.grid)
        self.grid.select_all_key.connect(self.select_all)
        self.grid.escape_key.connect(self.clear_selection)
        state.counts_changed.connect(self._show_selection)
        self.grid.customContextMenuRequested.connect(lambda p: self.clip_menu(self.grid, p))
        self._exports: set[workers.Cancel] = set()      # quick exports running
        self.grid.hovered_row.connect(self._hover)
        self.grid.zoomed.connect(self.zoom)
        self.grid.set_card_width(self.card_size.value())
        for keys, notches in (("Ctrl++", 1), ("Ctrl+=", 1), ("Ctrl+-", -1)):
            QShortcut(QKeySequence(keys), self, lambda n=notches: self.zoom(n),
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+0"), self,
                  lambda: self.card_size.setValue(CARD_WIDTH_DEFAULT),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        state.reset.connect(self._after_reset)

        self._preview_delay = QTimer(self, singleShot=True, interval=PREVIEW_DELAY_MS)
        self._preview_delay.timeout.connect(self._begin_preview)
        self._preview_tick = QTimer(self, interval=PREVIEW_FRAME_MS)
        self._preview_tick.timeout.connect(self.model.advance_preview)
        self._preview_target = -1
        context.library_reset.connect(self._connect_previews)
        self._connect_previews()

    def _connect_previews(self) -> None:
        if self.context.thumbs is not None:
            self.context.thumbs.preview_ready.connect(self._preview_ready)

    def _build_card_size(self) -> QWidget:
        """Small cards to big ones: a slider between a small and a large grid."""
        box = QWidget()
        box.setToolTip("Card size (Ctrl+scroll)")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        small, large = QLabel(), QLabel()
        theme.themed(small, lambda: small.setPixmap(icons.pixmap("library", "TEXT_DIM", 12)),
                     "icon")
        theme.themed(large, lambda: large.setPixmap(icons.pixmap("library", "TEXT_DIM", 18)),
                     "icon")
        self.card_size = QSlider(Qt.Orientation.Horizontal)
        self.card_size.setRange(*CARD_WIDTH_RANGE)
        self.card_size.setSingleStep(CARD_STEP)
        self.card_size.setPageStep(2 * CARD_STEP)
        self.card_size.setFixedWidth(120)
        self.card_size.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_size.setValue(self.context.config.card_width)
        self.card_size.valueChanged.connect(self._card_size_changed)
        for widget in (small, self.card_size, large):
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.size_icons = [small, large]
        return box

    def zoom(self, notches: int) -> None:
        """Bigger (+) or smaller (-) cards, a slider step per notch."""
        self.card_size.setValue(self.card_size.value() + notches * CARD_STEP)

    def _card_size_changed(self, width: int) -> None:
        self.grid.set_card_width(width)
        self.context.config.card_width = width
        self.context.save_config_later()

    def _build_empty(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        self.empty_title = label("No clips yet", "Subheading")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text = label("", "Muted", wrap=True)
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_title)
        layout.addWidget(self.empty_text)
        row = QHBoxLayout()
        row.addStretch(1)
        self.empty_record = button("Start replay buffer", "primary", "record",
                                   self.context.recorder.start)
        row.addWidget(self.empty_record)
        row.addWidget(button("Import clips…", on_click=self.import_requested))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(2)
        return page

    # --- State ---------------------------------------------------------------

    def reload(self) -> None:
        self.state.reload()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self.grid.fit_cells(self.delegate))

    def _after_reset(self) -> None:
        # Picked clips a filter or a delete took away aren't picked any more.
        self.selection.intersection_update(clip.name for clip in self.state.visible)
        self._show_selection()
        total = len(self.state.all_clips)
        shown = len(self.state.visible)
        if shown:
            self.stack.setCurrentWidget(self.grid)
        else:
            self.stack.setCurrentWidget(self.empty)
            if self.state.error:
                self.empty_title.setText("Can't read the clips folder")
                self.empty_text.setText(self.state.error)
            elif total:
                self.empty_title.setText("Nothing matches")
                self.empty_text.setText("Try a different search or filter.")
            else:
                self.empty_title.setText("No clips yet")
                self.empty_text.setText("Start the replay buffer and save a clip, or import "
                                        "existing clips.")
            self.empty_record.setVisible(not total and not self.context.recorder.running)
        self.grid.fit_cells(self.delegate)

    # --- Hover previews -------------------------------------------------------

    def _hover(self, row: int) -> None:
        self._preview_delay.stop()
        self._preview_tick.stop()
        self.model.clear_preview()
        self._preview_target = row
        if row >= 0:
            self._preview_delay.start()

    def _begin_preview(self) -> None:
        row = self._preview_target
        if row < 0 or row >= len(self.state.visible) or self.context.thumbs is None:
            return
        clip = self.state.visible[row]
        self.context.thumbs.request_preview(clip.path, self.state.durations.get(clip.name))

    def _preview_ready(self, clip_path: str, frames: list) -> None:
        row = self._preview_target
        if row < 0 or row >= len(self.state.visible) or \
                self.state.visible[row].path != clip_path or not frames:
            return
        self.model.set_preview(row, frames)
        self._preview_tick.start()

    # --- Actions -------------------------------------------------------------

    def edit_tags(self, clip) -> None:
        library = self.context.library
        if library is None:
            return
        game, people = self.state.tags_of(clip)
        result = TagDialog.ask(self, self.state.title_of(clip), game, people,
                               library.known_games(), library.known_people())
        if result is not None:
            self.state.set_tags(clip, *result)

    def rename_game(self, game: str) -> None:
        """Retag a game's clips with another name, and remember it if asked."""
        games = dict(self.state.games())
        result = RenameGameDialog.ask(self, game, games.get(game, 0), games)
        if result is None:
            return
        name, remember = result
        self.context.rename_game(game, name, remember)
        if self.state.facet == Facet("game", game):
            self.state.facet = Facet("game", name)
        self.state.reload()

    def connect_keys(self, grid: ClipGrid) -> None:
        """What a grid's keys do: here and on Home alike. Delete here takes
        the picked clips while there are any."""
        grid.open_key.connect(self.open_clip)
        grid.delete_key.connect(self._delete_key if grid is self.grid else self.delete)
        grid.favorite_key.connect(self.state.toggle_favorite)

    # --- Picking several clips ----------------------------------------------------

    @property
    def selection(self) -> set[str]:
        """The names of the picked clips; the cards paint from the same set."""
        return self.delegate.selection

    def picked(self) -> list:
        """The picked clips, in the order the grid shows them."""
        return [clip for clip in self.state.visible if clip.name in self.selection]

    def _pick_clicked(self, row: int, modifiers) -> None:
        """A click picks a card or lets it go; Shift picks every card from the
        one clicked before."""
        clips = self.state.visible
        if not 0 <= row < len(clips):
            return
        names = [clip.name for clip in clips]
        name = names[row]
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor in names:
            start, end = sorted((names.index(self._anchor), row))
            self.selection.update(names[start:end + 1])
        elif name in self.selection:
            self.selection.discard(name)
        else:
            self.selection.add(name)
        self._anchor = name
        self._show_selection()

    def select_all(self) -> None:
        self.selection.update(clip.name for clip in self.state.visible)
        self._show_selection()

    def clear_selection(self) -> None:
        if self.selection:
            self.selection.clear()
            self._show_selection()

    def _show_selection(self) -> None:
        picked = self.picked()
        if picked:
            self.selection_bar.set_count(
                len(picked), all(clip.name in self.state.favorites for clip in picked))
        self.top.setCurrentWidget(self.selection_bar if picked else self.filters)
        self.grid.viewport().update()

    def _act_on_picked(self, action: str) -> None:
        clips = self.picked()
        if not clips:
            return
        if action == "favorite":
            favorite = not all(clip.name in self.state.favorites for clip in clips)
            for clip in clips:
                if (clip.name in self.state.favorites) != favorite:
                    self.state.toggle_favorite(clip)
        elif action == "game":
            self.set_game(clips)
        elif action == "people":
            self.add_people(clips)
        elif action == "export":
            self.quick_export(*clips)
        elif action == "folder":
            self._show_in_folder(clips[0])
        elif action == "delete":
            self.delete_clips(clips)

    def set_game(self, clips: list) -> None:
        """One game for every clip given; their people stay."""
        library = self.context.library
        if library is None:
            return
        games = {self.state.tags_of(clip)[0] for clip in clips}
        result = TagDialog.ask(self, fmt.plural(len(clips), "clip"),
                               games.pop() if len(games) == 1 else "", (),
                               library.known_games(), (), "Set game", "game")
        if result is not None:
            for clip in clips:
                self.state.set_tags(clip, result[0], self.state.tags_of(clip)[1])

    def add_people(self, clips: list) -> None:
        """People added to every clip given, next to the ones they have."""
        library = self.context.library
        if library is None:
            return
        result = TagDialog.ask(self, fmt.plural(len(clips), "clip"), "", (), (),
                               library.known_people(), "Add people", "people")
        if not result or not result[1]:
            return
        for clip in clips:
            game, people = self.state.tags_of(clip)
            known = {person.casefold() for person in people}
            self.state.set_tags(clip, game, people + [p for p in result[1]
                                                      if p.casefold() not in known])

    def delete_clips(self, clips: list) -> None:
        if len(clips) == 1:
            self.delete(clips[0])
            return
        trash = storage.trash_available()
        answer = ChoiceDialog.ask(
            self, "Delete clips", f"Delete {len(clips)} clips?",
            ("They're moved to the Trash." if trash else "This can't be undone."),
            [("Move to Trash" if trash else "Delete permanently", "delete", "danger")])
        if answer == "delete":
            for clip in clips:
                self.state.delete(clip)

    def _delete_key(self, clip) -> None:
        if self.selection:
            self.delete_clips(self.picked())
        elif clip is not None:
            self.delete(clip)

    def confirm_delete(self, clip) -> bool:
        trash = storage.trash_available()
        answer = ChoiceDialog.ask(
            self, "Delete clip", f"Delete “{self.state.title_of(clip)}”?",
            ("It's moved to the Trash." if trash else "This can't be undone."),
            [("Move to Trash" if trash else "Delete permanently", "delete", "danger")])
        return answer == "delete"

    def delete(self, clip) -> None:
        if clip is not None and self.confirm_delete(clip):
            self.state.delete(clip)

    def clip_menu(self, grid: QListView, point) -> None:
        """A clip's menu: right-click on a card here or on Home."""
        index: QModelIndex = grid.indexAt(point)
        clip = index.data(ClipRole) if index.isValid() else None
        if clip is None:
            return
        menu = QMenu(self)
        favorite = clip.name in self.state.favorites

        def add(text, handler, enabled=True):
            action = QAction(text, menu)
            action.triggered.connect(handler)
            action.setEnabled(enabled)
            menu.addAction(action)

        picked = self.picked() if grid is self.grid and clip.name in self.selection else []
        if len(picked) > 1:
            # On a picked card: the picked clips' menu, as on the bar.
            every = all(each.name in self.state.favorites for each in picked)
            add("Remove from favorites" if every else "Add to favorites",
                lambda: self._act_on_picked("favorite"))
            add("Set game…", lambda: self.set_game(picked))
            add("Add people…", lambda: self.add_people(picked))
            menu.addSeparator()
            size, _limit = self.quick_size()
            add(f"Quick export · {size}", lambda: self.quick_export(*picked))
            add("Show in folder", lambda: self._show_in_folder(picked[0]))
            menu.addSeparator()
            add(f"Delete {len(picked)} clips…", lambda: self.delete_clips(picked))
            menu.exec(grid.viewport().mapToGlobal(point))
            return
        add("Open", lambda: self.open_clip.emit(clip))
        add("Rename", lambda: grid.edit(index))
        add("Edit tags…", lambda: self.edit_tags(clip))
        add("Remove from favorites" if favorite else "Add to favorites",
            lambda: self.state.toggle_favorite(clip))
        menu.addSeparator()
        size, _limit = self.quick_size()
        add(f"Quick export · {size}", lambda: self.quick_export(clip))
        menu.addSeparator()
        add("Show in folder", lambda: self._show_in_folder(clip))
        add("Copy path", lambda: QGuiApplication.clipboard().setText(clip.path))
        menu.addSeparator()
        add("Delete…", lambda: self.delete(clip))
        menu.exec(grid.viewport().mapToGlobal(point))

    # --- Quick export ----------------------------------------------------------

    def quick_size(self) -> tuple[str, int | None]:
        """The size last exported at, or 10 MB before the first export."""
        return export.size_choice(self.context.config.export_size, export.QUICK_SIZE)

    def quick_export(self, *clips) -> None:
        """Export with each clip's saved trim and mix at `quick_size`, off the
        UI thread, and put the files on the clipboard once they are done,
        ready to paste into Discord or a browser."""
        library = self.context.library
        edits = [library.get_edit(clip.name) if library is not None else None
                 for clip in clips]
        size, limit = self.quick_size()
        folder = (self.context.config.resolved_export_dir()
                  or os.path.dirname(os.path.abspath(clips[0].path)))
        if len(clips) == 1:
            game, _people = self.state.tags_of(clips[0])
            what = f"the {game} clip" if game else f"“{self.state.title_of(clips[0])}”"
        else:
            what = f"{len(clips)} clips"
        cancel = workers.Cancel()
        self._exports.add(cancel)
        shown = [-1]

        def tell(text: str, level: str = "info", ms: int = 0, on_click=None) -> None:
            self.notice.emit(text, level, ms, on_click)

        def progress(fraction: float) -> None:
            percent = int(fraction * 100) // 5 * 5
            if percent != shown[0]:
                shown[0] = percent
                workers.post(lambda p: tell(f"Exporting {what}… {p}%"), percent)

        def job() -> list[export.ExportResult]:
            results = []
            for done_before, (clip, edit) in enumerate(zip(clips, edits, strict=True)):
                info = probe.probe(clip.path)
                tracks = track_labels.label_tracks(info.tracks)
                start, end = (export.apply_edit(edit, info.duration, tracks) if edit is not None
                              else (0.0, info.duration))
                results.append(export.export_clip(
                    clip.path, clip.name, folder, start, end, tracks, info, limit,
                    on_progress=lambda f, n=done_before: progress((n + f) / len(clips)),
                    cancel=cancel))
            return results

        def done(results: list[export.ExportResult]) -> None:
            self._exports.discard(cancel)
            for clip, result in zip(clips, results, strict=True):
                log.info("Quick export of %s: %s, %s%s", clip.path, result.path,
                         fmt.size(result.size),
                         " (over the size limit)" if result.over_limit else "")
            copy_files_to_clipboard([result.path for result in results])
            over_limit = sum(result.over_limit for result in results)
            over = ("" if not over_limit else f", over {size}" if len(results) == 1
                    else f", {over_limit} over {size}")
            folder_of = os.path.dirname(results[0].path)
            total = fmt.size(sum(result.size for result in results))
            tell(f"Copied {what} ({total}{over}), ready to paste. Click to open "
                 f"{'its' if len(results) == 1 else 'their'} folder.",
                 "warn" if over_limit else "ok", 12000,
                 lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder_of)))

        def failed(exc: BaseException) -> None:
            self._exports.discard(cancel)
            if isinstance(exc, Cancelled):
                log.info("Quick export of %s cancelled", what)
                return
            log.error("Couldn't export %s: %s", what, exc)
            tell(f"Couldn't export {what}: {exc}", "error", 10000)

        log.info("Quick export of %s to %s (%s)", ", ".join(clip.path for clip in clips),
                 folder, f"up to {size}" if limit else "original quality")
        tell(f"Exporting {what}…")
        workers.run(job, done, failed)

    def cancel_exports(self) -> None:
        """Stop the quick exports still running; they leave nothing behind."""
        for cancel in self._exports:
            cancel.set()

    @staticmethod
    def _show_in_folder(clip) -> None:
        # The file manager's own "select this file" call when it has one;
        # opening the folder is the universal fallback.
        if not platform.show_in_folder(clip.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(clip.path)))
