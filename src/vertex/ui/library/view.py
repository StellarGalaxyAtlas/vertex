"""The clip library: a header, the card grid, and what to do with a card."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QModelIndex, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
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

from vertex import fmt, paths
from vertex.config import CARD_WIDTH_DEFAULT, CARD_WIDTH_RANGE
from vertex.core import storage
from vertex.ui import icons, theme
from vertex.ui.dialogs.tags import TagDialog
from vertex.ui.library.delegate import INFO_H, PAD, ClipDelegate
from vertex.ui.library.model import ClipModel, ClipRole
from vertex.ui.library.state import LibraryState
from vertex.ui.widgets import ChoiceDialog, IconButton, Segmented, button, label

CARD_STEP = 20           # how much one notch of the size slider or Ctrl+scroll changes
PREVIEW_DELAY_MS = 450
PREVIEW_FRAME_MS = 330


class ClipGrid(QListView):
    """A virtualised grid: only the cards on screen are ever painted. Cards are
    at least `card_width` wide, and stretch to fill their row."""

    hovered_row = Signal(int)
    zoomed = Signal(int)             # Ctrl+scroll: notches, + for bigger cards

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

    def __init__(self, context, state: LibraryState, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.CONTENT_MARGIN, 18, theme.CONTENT_MARGIN - 8, 10)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title = label("All clips", "Heading")
        self.count = label("", "Muted")
        header.addWidget(self.title)
        header.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        header.addStretch(1)
        header.addWidget(self._build_card_size())
        header.addSpacing(12)
        self.sort = Segmented([("date", "Date"), ("game", "Game")], "date", directional=True)
        self.sort.changed.connect(state.set_sort)
        header.addWidget(self.sort)
        refresh = IconButton("refresh", "Rescan the clips folder (F5)")
        refresh.clicked.connect(self.reload)
        header.addWidget(refresh)
        header.setContentsMargins(0, 0, 8, 0)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.grid = ClipGrid()
        self.model = ClipModel(state, context, self)
        self.delegate = ClipDelegate(self.grid, state, self.grid)
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
        self.grid.customContextMenuRequested.connect(self._menu)
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
        box.setToolTip("Card size (Ctrl+scroll, Ctrl+plus/minus; Ctrl+0 resets)")
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
        total = len(self.state.all_clips)
        shown = len(self.state.visible)
        self.title.setText(self.state.facet.title())
        if self.state.query or self.state.facet.kind != "all":
            self.count.setText(f"{shown} of {fmt.plural(total, 'clip')}")
        else:
            self.count.setText(fmt.plural(total, "clip"))
        if shown:
            self.stack.setCurrentWidget(self.grid)
        else:
            self.stack.setCurrentWidget(self.empty)
            folder = paths.tilde(self.context.config.resolved_clip_dir())
            if self.state.error:
                self.empty_title.setText("Can't read the clips folder")
                self.empty_text.setText(self.state.error)
            elif total:
                self.empty_title.setText("Nothing matches")
                self.empty_text.setText("Try a different search or filter.")
            else:
                self.empty_title.setText("No clips yet")
                self.empty_text.setText(
                    f"Clips saved into {folder} show up here. Start the replay buffer and "
                    f"press your save-clip hotkey, or bring an existing library in.")
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

    def confirm_delete(self, clip) -> bool:
        trash = storage.trash_available()
        answer = ChoiceDialog.ask(
            self, "Delete clip", f"Delete “{self.state.title_of(clip)}”?",
            ("The file goes to your Trash, along with its tags and edits."
             if trash else "This deletes the file permanently — Send2Trash is not installed."),
            [("Move to Trash" if trash else "Delete permanently", "delete", "danger")])
        return answer == "delete"

    def delete(self, clip) -> None:
        if self.confirm_delete(clip):
            self.state.delete(clip)

    def _menu(self, point) -> None:
        index: QModelIndex = self.grid.indexAt(point)
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

        add("Open", lambda: self.open_clip.emit(clip))
        add("Rename", lambda: self.grid.edit(index))
        add("Edit tags…", lambda: self.edit_tags(clip))
        add("Remove from favorites" if favorite else "Add to favorites",
            lambda: self.state.toggle_favorite(clip))
        menu.addSeparator()
        add("Show in folder", lambda: self._show_in_folder(clip))
        add("Copy path", lambda: QGuiApplication.clipboard().setText(clip.path))
        menu.addSeparator()
        add("Delete…", lambda: self.delete(clip))
        menu.exec(self.grid.viewport().mapToGlobal(point))

    @staticmethod
    def _show_in_folder(clip) -> None:
        # The file manager's own "select this file" call when it has one;
        # opening the folder is the universal fallback.
        try:
            subprocess.Popen(
                ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                 "--type=method_call", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 f"array:string:{QUrl.fromLocalFile(clip.path).toString()}", "string:"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(clip.path)))
