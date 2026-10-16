"""Video playback: libmpv rendering into a QOpenGLWidget.

mpv draws through its render API into the widget's own framebuffer, so the
video is an ordinary part of the Qt scene. That works the same on Wayland and
X11 — no foreign window embedded by ID, no X error handlers to guard — and the
widget gets its own mouse events like any other.

mpv is used because, unlike most players, it can mix several audio tracks at
once through a lavfi-complex graph, and swapping that graph mid-playback is
instant: it is how the editor's mixer applies changes live.
"""

from __future__ import annotations

import locale

import mpv
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget


def _get_proc_address(_ctx, name: bytes) -> int:
    context = QOpenGLContext.currentContext()
    if context is None:
        return 0
    address = context.getProcAddress(name)
    return int(address) if address else 0


_PROC_ADDRESS = mpv.MpvGlGetProcAddressFn(_get_proc_address)


class MpvWidget(QOpenGLWidget):
    clicked = Signal()
    double_clicked = Signal()
    _frame_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # libmpv refuses to start unless numbers are formatted the C way, and
        # Qt adopted the desktop's locale when the application started.
        locale.setlocale(locale.LC_NUMERIC, "C")
        options = dict(
            vo="libmpv", keep_open="yes", idle="yes", osc=False,
            input_default_bindings=False, input_vo_keyboard=False,
            audio_client_name="Vertex", title="Vertex", hr_seek="yes",
            # Plain bilinear scaling: the preview is shrunk to fit the editor,
            # where mpv's sharper default scalers look the same but cost an
            # older integrated GPU its frame rate. Exports are not affected.
            profile="fast",
        )
        # Decoded frames stay on the GPU and are drawn from there; copying
        # them back to the CPU costs a weak laptop most of its frame rate.
        # Where that can't work, mpv falls back to a copy-back decoder itself.
        try:
            self.player = mpv.MPV(hwdec="auto-safe", **options)
        except (TypeError, AttributeError, ValueError):
            self.player = mpv.MPV(**options)     # an mpv without that hwdec mode
        self._render = None
        self._frame_ready.connect(self.update, Qt.ConnectionType.QueuedConnection)
        self.setMinimumHeight(160)

    def initializeGL(self):
        self._render = mpv.MpvRenderContext(
            self.player, "opengl", opengl_init_params={"get_proc_address": _PROC_ADDRESS})
        # Runs on mpv's thread whenever a new frame is due; repaint on ours.
        self._render.update_cb = self._frame_ready.emit

    def paintGL(self):
        if self._render is None:
            return
        ratio = self.devicePixelRatioF()
        self._render.render(flip_y=True, opengl_fbo={
            "w": int(self.width() * ratio), "h": int(self.height() * ratio),
            "fbo": self.defaultFramebufferObject()})

    def decoder(self) -> tuple[str, str] | None:
        """The playing video ("h264 2560x1440") and the hardware decoder mpv
        uses for it ("" = decoded on the CPU); None until a frame is decoded."""
        try:
            codec, width, height = self.player.video_format, self.player.width, self.player.height
            hwdec = self.player.hwdec_current
        except Exception:
            return None
        if not codec:
            return None
        return f"{codec} {width}x{height}", "" if hwdec in (None, "no") else hwdec

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def shutdown(self) -> None:
        """Free the render context (with GL current) and stop mpv. Idempotent."""
        if self._render is not None:
            self.makeCurrent()
            self._render.update_cb = None
            self._render.free()
            self._render = None
            self.doneCurrent()
        if self.player is not None:
            try:
                self.player.terminate()
            except Exception:       # already gone
                pass
            self.player = None
