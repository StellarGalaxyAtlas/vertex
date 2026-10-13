"""The clip grid's model: rows are the visible clips; images load on demand."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QSize, Qt
from PySide6.QtGui import QImage, QPixmap

from vertex.ui.library.state import LibraryState, is_settling

ClipRole = Qt.ItemDataRole.UserRole + 1

# Thumbnails are kept at the size cards draw them, and only so many of them:
# a full-resolution pixmap per clip is half a megabyte, times a library.
THUMB_CACHE = 240
THUMB_SIZE = QSize(480, 270)


class ClipModel(QAbstractListModel):
    def __init__(self, state: LibraryState, context, parent=None):
        super().__init__(parent)
        self.state = state
        self.context = context
        self._thumbs: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._missing: set[tuple] = set()    # generation failed for this version of a file
        self._asked: set[str] = set()
        self._durations_asked: set[tuple] = set()
        self._rows: dict[str, int] = {}
        self.preview_row = -1
        self.preview_frames: list[QPixmap] = []
        self.preview_index = 0
        state.reset.connect(self._reset)
        state.clip_changed.connect(self._clip_changed)
        context.library_reset.connect(self.connect_thumbs)
        self.connect_thumbs()

    def connect_thumbs(self) -> None:
        thumbs = self.context.thumbs
        if thumbs is None:
            return
        thumbs.thumbnail_ready.connect(self._thumbnail_ready)
        thumbs.duration_ready.connect(self._duration_ready)
        self._thumbs.clear()
        self._missing.clear()
        self._asked.clear()

    # --- Qt model -------------------------------------------------------------

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.state.visible)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.state.visible):
            return None
        clip = self.state.visible[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.state.title_of(clip)
        if role == ClipRole:
            return clip
        if role == Qt.ItemDataRole.ToolTipRole:
            return clip.name
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        self.state.set_title(self.state.visible[index.row()], str(value))
        return True

    def flags(self, index):
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable)

    def _reset(self) -> None:
        self.beginResetModel()
        self._rows = {clip.name: row for row, clip in enumerate(self.state.visible)}
        self.preview_row = -1
        self.preview_frames = []
        self.endResetModel()

    def _clip_changed(self, name: str) -> None:
        row = self._rows.get(name)
        if row is not None and row < len(self.state.visible):
            index = self.index(row)
            self.dataChanged.emit(index, index)

    def row_of_path(self, clip_path: str) -> int | None:
        for row, clip in enumerate(self.state.visible):
            if clip.path == clip_path:
                return row
        return None

    # --- Images ----------------------------------------------------------------

    @staticmethod
    def _key(clip) -> tuple:
        """Images belong to a version of a file: a clip re-recorded or still
        being written under the same name gets new ones."""
        return (clip.path, clip.size_bytes, clip.mtime)

    def thumbnail(self, clip) -> QPixmap | None:
        """The clip's thumbnail if it is loaded; asks for it otherwise."""
        if not clip.path:
            return None
        key = self._key(clip)
        cached = self._thumbs.get(key)
        if cached is not None:
            self._thumbs.move_to_end(key)
            return cached
        thumbs = self.context.thumbs
        if thumbs is None or key in self._missing or is_settling(clip):
            return None
        on_disk = thumbs.cached_thumbnail(clip.path)
        if on_disk:
            return self._load(key, on_disk)
        if clip.path not in self._asked:
            self._asked.add(clip.path)
            thumbs.request_thumbnail(clip.path)
        return None

    def _load(self, key: tuple, image_path: str) -> QPixmap | None:
        image = QImage(image_path)
        if image.isNull():
            self._missing.add(key)
            return None
        pixmap = QPixmap.fromImage(image.scaled(
            THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation))
        self._thumbs[key] = pixmap
        while len(self._thumbs) > THUMB_CACHE:
            self._thumbs.popitem(last=False)
        return pixmap

    def _thumbnail_ready(self, clip_path: str, image_path: str) -> None:
        self._asked.discard(clip_path)
        row = self.row_of_path(clip_path)
        if row is None:
            return
        key = self._key(self.state.visible[row])
        if not image_path:
            self._missing.add(key)
            return
        self._load(key, image_path)
        self.dataChanged.emit(self.index(row), self.index(row))

    def duration(self, clip) -> float | None:
        seconds = self.state.durations.get(clip.name)
        if seconds:
            return seconds
        thumbs = self.context.thumbs
        if clip.path and thumbs is not None and not is_settling(clip) and \
                self._key(clip) not in self._durations_asked:
            self._durations_asked.add(self._key(clip))
            thumbs.request_duration(clip.path)
        return None

    def _duration_ready(self, clip_path: str, seconds: float) -> None:
        if seconds > 0:
            self.state.set_duration(clip_path, seconds)

    # --- Hover preview --------------------------------------------------------

    def set_preview(self, row: int, frame_paths: list[str]) -> None:
        self.preview_row = row
        self.preview_frames = [QPixmap.fromImage(QImage(path)) for path in frame_paths]
        self.preview_frames = [frame for frame in self.preview_frames if not frame.isNull()]
        self.preview_index = 0
        self._touch(row)

    def advance_preview(self) -> None:
        if self.preview_row < 0 or not self.preview_frames:
            return
        self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
        self._touch(self.preview_row)

    def clear_preview(self) -> None:
        row, self.preview_row = self.preview_row, -1
        self.preview_frames = []
        if row >= 0:
            self._touch(row)

    def preview_pixmap(self, row: int) -> QPixmap | None:
        if row == self.preview_row and self.preview_frames:
            return self.preview_frames[self.preview_index]
        return None

    def _touch(self, row: int) -> None:
        if 0 <= row < self.rowCount():
            self.dataChanged.emit(self.index(row), self.index(row))
