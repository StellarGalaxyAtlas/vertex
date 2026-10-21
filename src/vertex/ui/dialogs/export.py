"""The share and export sheet: pick a size, render, then hand the file on.

Modelled on Moments' share sheet. "Original" copies the video untouched and
only mixes the audio down; the capped sizes re-encode to fit the limits chat
platforms enforce. Sharing renders into Vertex's cache, emptied each time
Vertex starts, and puts the file on the clipboard; exporting saves it in the Exports folder.
Either way the file can then be copied, or dragged from the preview straight
into a chat window.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDrag, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

from vertex import fmt, paths
from vertex.logs import CLIPS as log
from vertex.media import export
from vertex.media.ffmpeg import Cancelled, MediaError
from vertex.media.mixing import ffmpeg_graph
from vertex.ui import theme, workers
from vertex.ui.widgets import Segmented, button, label

PREVIEW_W = 460
DAY = 24 * 60 * 60


def copy_file_to_clipboard(path: str) -> None:
    """Put the file itself on the clipboard, the way file managers do, so
    pasting into Discord or a browser upload field attaches it."""
    url = QUrl.fromLocalFile(path)
    data = QMimeData()
    data.setUrls([url])
    data.setData("x-special/gnome-copied-files", f"copy\n{url.toString()}".encode())
    data.setData("application/x-kde-cutselection", b"0")
    QGuiApplication.clipboard().setMimeData(data)


class FilePreview(QLabel):
    """The preview picture. Once the file is written it can be dragged out,
    into Discord, a browser or the file manager."""

    def __init__(self):
        super().__init__("…")
        self.path = ""
        self._press: QPoint | None = None

    def set_path(self, path: str) -> None:
        self.path = path
        self.setCursor(Qt.CursorShape.OpenHandCursor if path else Qt.CursorShape.ArrowCursor)
        self.setToolTip("Drag into a chat" if path else "")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.path:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton and \
                (event.position().toPoint() - self._press).manhattanLength() >= \
                QApplication.startDragDistance():
            self._press = None
            self.drag()
            return
        super().mouseMoveEvent(event)

    def drag(self) -> None:
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(self.path)])
        drag = QDrag(self)
        drag.setMimeData(data)
        picture = self.pixmap()
        if picture is not None and not picture.isNull():
            ratio = picture.devicePixelRatio() or 1.0
            small = picture.scaledToWidth(round(200 * ratio),
                                          Qt.TransformationMode.SmoothTransformation)
            small.setDevicePixelRatio(ratio)
            drag.setPixmap(small)
            drag.setHotSpot(QPoint(100, round(small.height() / ratio) // 2))
        drag.exec(Qt.DropAction.CopyAction)


class ExportDialog(QDialog):
    """`share` renders into the cache and copies the file to the clipboard;
    otherwise the file is exported into the Exports folder."""

    def __init__(self, parent, context, clip, start: float, end: float, tracks, info,
                 share: bool = False):
        super().__init__(parent)
        self.context = context
        self.clip = clip
        self.start, self.end = start, end
        self.tracks = tracks
        self.info = info
        self.share = share
        self.limit: int | None = None
        cache = context.config.resolved_cache_dir()
        self.folder = export.share_dir(cache) if share else (
            context.config.resolved_export_dir() or os.path.dirname(os.path.abspath(clip.path)))
        self.out_path = ""
        self._cancel = workers.Cancel()
        self._running = False
        self._workdir = tempfile.mkdtemp(prefix="vertex-preview-")
        title = "Share clip" if share else "Export clip"
        self.setWindowTitle(title)
        self.setMinimumWidth(PREVIEW_W + 48)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(title, "Subheading"))
        self.preview = FilePreview()
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_W * 9 // 16)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.style(self.preview, lambda: f"background: {theme.VIDEO_BG}; border-radius: 10px;")
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(label(f"{fmt.duration(end - start)} selected", "Muted"))

        layout.addWidget(label("SIZE", "Group"))
        # It opens on the size last exported at.
        size, self.limit = export.size_choice(context.config.export_size)
        self.sizes = Segmented([(name, name) for name, _ in export.SIZE_CHOICES], size)
        self.sizes.changed.connect(self._on_size)
        layout.addWidget(self.sizes)
        self.detail = label("", "Muted", wrap=True)
        layout.addWidget(self.detail)

        destination = QHBoxLayout()
        self.where = label("", "Dim")
        destination.addWidget(self.where, 1)
        if not share:
            destination.addWidget(button("Change…", "ghost", on_click=self._choose_folder))
        layout.addLayout(destination)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.status = label("", "Muted", wrap=True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.copy_button = button("Copy file", icon="save-clip", on_click=self._copy,
                                  tooltip="Copy to clipboard")
        self.folder_button = button("Open folder", icon="folder", on_click=self._open_folder)
        self.copy_button.hide()
        self.folder_button.hide()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch(1)
        self.close_button = button("Close", on_click=self._close_or_cancel)
        self.export_button = button("Share" if share else "Export", "primary",
                                    "export" if share else "folder", self._export)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        self._describe()
        self._show_where()
        source, preview = clip.path, os.path.join(self._workdir, "preview.jpg")
        workers.run(lambda: export.grab_frame(source, start, preview, PREVIEW_W * 2),
                    self._show_preview, lambda _exc: self.preview.setText("No preview"))

    # --- Choices ----------------------------------------------------------------

    def _on_size(self, name: str, _descending: bool) -> None:
        self.limit = dict(export.SIZE_CHOICES)[name]
        self._describe()

    def _describe(self) -> None:
        selection = self.end - self.start
        original = export.copy_estimate(self.info, selection)
        possible = True
        if self.limit is None:
            text = self.info.summary or "Source quality"
            if original:
                text += f" · ≈{fmt.size(original, 0)}"
            text += " — the video is copied untouched, cut on a keyframe."
        else:
            try:
                plan = export.plan(selection, self.info.width, self.info.height, self.info.fps,
                                   ffmpeg_graph(self.tracks) is not None, self.limit)
                text = f"{plan.summary} · ≈{fmt.size(plan.estimate(selection), 0)}"
                if original and original <= self.limit:
                    text += " — Original already fits, without re-encoding."
            except MediaError as exc:
                text, possible = str(exc), False
        self.detail.setText(text)
        theme.style(self.detail, lambda: f"color: {theme.TEXT_MUTED if possible else theme.WARN};")
        if not self._running:
            self.export_button.setEnabled(possible)

    def _show_where(self) -> None:
        self.where.setText("Copies the file, ready to paste. Vertex deletes it when it "
                           "next starts." if self.share
                           else f"Saves to {paths.tilde(self.folder)}")

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Export to", self.folder)
        if chosen:
            self.folder = paths.normalize(chosen)
            self._show_where()

    def _show_preview(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview.setText("No preview")
            return
        ratio = self.devicePixelRatioF() or 1.0
        scaled = pixmap.scaled(int(self.preview.width() * ratio),
                               int(self.preview.height() * ratio),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self.preview.setPixmap(scaled)

    # --- Exporting ----------------------------------------------------------------

    def _export(self) -> None:
        if self._running:
            return
        self._running = True
        self._cancel.clear()
        self.progress.setValue(0)
        self.sizes.setEnabled(False)
        self.export_button.setEnabled(False)
        self.copy_button.hide()
        self.folder_button.hide()
        self.preview.set_path("")
        self.close_button.setText("Cancel")
        if self.share:
            # For anyone who never quits Vertex: a day is long enough to paste.
            cache = self.context.config.resolved_cache_dir()
            workers.run(lambda: export.clear_shares(cache, older_than=DAY))
        size = export.size_label(self.limit)
        if size != self.context.config.export_size:
            self.context.config.export_size = size
            self.context.save_config_later()
        verb = "Copying" if self.limit is None else "Converting"
        self.status.setText(f"{verb}…")
        theme.style(self.status, lambda: f"color: {theme.TEXT_MUTED};")
        args = (self.clip.path, self.clip.name, self.folder, self.start, self.end,
                self.tracks, self.info, self.limit)
        log.info("Exporting %s to %s (%s)", self.clip.path, self.folder,
                 f"up to {fmt.size(self.limit)}" if self.limit else "original quality")

        def progress(fraction: float) -> None:
            workers.post(self._progress, fraction)

        workers.run(lambda: export.export_clip(*args, on_progress=progress, cancel=self._cancel),
                    self._done, self._failed)

    def _progress(self, fraction: float) -> None:
        if self._running:
            self.progress.setValue(int(fraction * 1000))
            verb = "Copying" if self.limit is None else "Converting"
            self.status.setText(f"{verb}… {fraction * 100:.0f}%")

    def _done(self, result: export.ExportResult) -> None:
        self._running = False
        self.out_path = result.path
        log.info("Exported %s, %s%s", result.path, fmt.size(result.size),
                 " (over the size limit)" if result.over_limit else "")
        self.progress.setValue(1000)
        self._release()
        over = "  —  over the size limit" if result.over_limit else ""
        done = "Copied" if self.share else "Saved"
        if self.share:
            copy_file_to_clipboard(result.path)
        self.status.setText(f"{done} {os.path.basename(result.path)} · "
                            f"{fmt.size(result.size)}{over}. Paste it into a chat, "
                            "or drag the picture there.")
        theme.style(self.status, lambda: f"color: {theme.WARN if over else theme.OK};")
        self.preview.set_path(result.path)
        self.copy_button.show()
        self.folder_button.setVisible(not self.share)

    def _failed(self, exc: BaseException) -> None:
        self._running = False
        self.progress.setValue(0)
        self._release()
        if isinstance(exc, Cancelled):
            log.info("Export of %s cancelled", self.clip.path)
            self.status.setText("Sharing cancelled." if self.share else "Export cancelled.")
            theme.style(self.status, lambda: f"color: {theme.TEXT_MUTED};")
        else:
            log.error("Couldn't export %s: %s", self.clip.path, exc)
            self.status.setText(str(exc))
            theme.style(self.status, lambda: f"color: {theme.DANGER};")

    def _release(self) -> None:
        self.sizes.setEnabled(True)
        self.close_button.setText("Close")
        self._describe()

    # --- After ----------------------------------------------------------------------

    def _copy(self) -> None:
        if self.out_path:
            copy_file_to_clipboard(self.out_path)
            self.status.setText("Copied to clipboard")
            theme.style(self.status, lambda: f"color: {theme.OK};")

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.out_path)
                                                    or self.folder))

    def _close_or_cancel(self) -> None:
        if self._running:
            self._cancel.set()
        else:
            self.accept()

    def done(self, result: int) -> None:
        self._cancel.set()
        shutil.rmtree(self._workdir, ignore_errors=True)
        super().done(result)
