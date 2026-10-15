"""The editor's timeline: ruler, video lane, an audio lane per track with its
waveform, the trim selection and the playhead."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from vertex import fmt
from vertex.ui import theme

RULER_H = 22
LANE_H = 34          # the mixer rows use the same height, so they line up
LANE_GAP = 4
EDGE_PAD = 10
GRAB_PX = 7          # how close the pointer must be to grab a trim handle
WAVE_PAD = 3
# Peaks are drawn on a curve: speech at a sane level peaks around a tenth of
# full scale, a pixel and a half in a lane this tall, indistinguishable from
# silence. The curve lifts the quiet end and leaves the loud end be.
WAVE_CURVE = 0.6
MIN_SELECTION = 0.1


class Timeline(QWidget):
    seek_requested = Signal(float)
    scrub_started = Signal()         # the playhead is grabbed …
    scrub_finished = Signal()        # … and let go
    trim_changed = Signal(float, float)
    trim_committed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration = 0.0
        self.trim_start = 0.0
        self.trim_end = 0.0
        self.position = 0.0
        self.lanes: list[tuple[str, bool]] = []    # (colour, muted) per audio track
        self.waves: dict[int, list[float]] = {}     # lane position → levels
        self._wave_cache: dict[tuple[int, int, bool], QPolygonF] = {}
        self._drag = None
        self.scale = 1.0
        self.ruler_h, self.lane_h = RULER_H, LANE_H
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # --- Data -----------------------------------------------------------------

    def height_for(self, lanes: int) -> int:
        return self.ruler_h + (lanes + 1) * (self.lane_h + LANE_GAP)

    def set_lanes(self, lanes: list[tuple[str, bool]]) -> None:
        self.lanes = lanes
        self.setFixedHeight(self.height_for(len(lanes)))
        self._wave_cache.clear()
        self.update()

    def set_scale(self, scale: float) -> None:
        """Grow the ruler and the lanes with the window (the editor's scale)."""
        self.scale = scale
        self.ruler_h, self.lane_h = round(RULER_H * scale), round(LANE_H * scale)
        self.set_lanes(self.lanes)

    def set_wave(self, lane: int, levels: list[float]) -> None:
        self.waves[lane] = levels
        self._wave_cache = {k: v for k, v in self._wave_cache.items() if k[0] != lane}
        self.update()

    def set_duration(self, seconds: float) -> None:
        self.duration = seconds
        self._wave_cache.clear()
        self.update()

    def set_trim(self, start: float, end: float) -> None:
        self.trim_start, self.trim_end = start, end
        self.update()

    def set_position(self, seconds: float) -> None:
        if abs(seconds - self.position) * self._px_per_second() >= 0.5:
            self.position = seconds
            self.update()

    # --- Geometry -------------------------------------------------------------

    def _span(self) -> tuple[float, float]:
        return EDGE_PAD, max(EDGE_PAD + 1, self.width() - EDGE_PAD)

    def _px_per_second(self) -> float:
        left, right = self._span()
        return (right - left) / self.duration if self.duration else 0.0

    def x_for(self, seconds: float) -> float:
        left, right = self._span()
        if not self.duration:
            return left
        return left + (right - left) * max(0.0, min(1.0, seconds / self.duration))

    def time_for(self, x: float) -> float:
        left, right = self._span()
        if not self.duration:
            return 0.0
        return max(0.0, min(self.duration, (x - left) / (right - left) * self.duration))

    def _lane_top(self, lane: int) -> float:
        return self.ruler_h + LANE_GAP + lane * (self.lane_h + LANE_GAP)

    # --- Painting -------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right = self._span()
        self._paint_ruler(p, left, right)

        colours = [(theme.VIDEO_LANE, False), *self.lanes]
        for lane, (colour, muted) in enumerate(colours):
            top = self._lane_top(lane)
            rect = QRectF(left, top, right - left, self.lane_h)
            path = QPainterPath()
            path.addRoundedRect(rect, 5, 5)
            p.fillPath(path, QColor(theme.LANE_BG if muted else colour))
            if lane:
                self._paint_wave(p, lane - 1, colour, muted, top)

        bottom = self._lane_top(len(colours)) - LANE_GAP
        x_in, x_out = self.x_for(self.trim_start), self.x_for(self.trim_end)
        shade = QColor(theme.TRIM_SHADE)
        shade.setAlpha(175)
        for x0, x1 in ((left, x_in), (x_out, right)):
            if x1 > x0:
                p.fillRect(QRectF(x0, self.ruler_h, x1 - x0, bottom - self.ruler_h), shade)
        pen = QPen(QColor(theme.SELECT), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for x in (x_in, x_out):
            p.drawLine(QPointF(x, self.ruler_h - 4), QPointF(x, bottom))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SELECT))
        for x in (x_in, x_out):
            p.drawRoundedRect(QRectF(x - 5, self.ruler_h - 8, 10, 8), 2, 2)

        x = self.x_for(self.position)
        p.setPen(QPen(QColor(theme.PLAYHEAD), 1.2))
        p.drawLine(QPointF(x, 0), QPointF(x, bottom))
        p.setBrush(QColor(theme.PLAYHEAD))
        p.setPen(Qt.PenStyle.NoPen)
        head = QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 6)])
        p.drawPolygon(head)

    def _paint_ruler(self, p: QPainter, left: float, right: float) -> None:
        if not self.duration or right <= left:
            return
        target = max(1, int(self.duration / max(1, (right - left) / 90)))
        step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800) if s >= target),
                    3600)
        p.setFont(theme.font(7.5 * self.scale))
        metrics = QFontMetricsF(p.font())
        for seconds in range(0, int(self.duration) + 1, step):
            x = self.x_for(seconds)
            p.setPen(QColor(theme.SEAM))
            p.drawLine(QPointF(x, self.ruler_h - 6), QPointF(x, self.ruler_h))
            # Centred on its tick, but kept inside the widget at both ends.
            text = fmt.duration(seconds)
            half = metrics.horizontalAdvance(text) / 2 + 1
            middle = max(half, min(self.width() - half, x))
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(middle - 40, 0, 80, self.ruler_h - 7), Qt.AlignmentFlag.AlignCenter,
                       text)

    def _paint_wave(self, p: QPainter, lane: int, colour: str, muted: bool, top: float) -> None:
        levels = self.waves.get(lane)
        if not levels:
            return
        left, right = self._span()
        width = int(right - left)
        if width < 2:
            return
        key = (lane, width, muted)
        polygon = self._wave_cache.get(key)
        if polygon is None:
            middle = top + self.lane_h / 2
            limit = self.lane_h / 2 - WAVE_PAD
            upper, lower = [], []
            count = len(levels)
            for column in range(width + 1):
                low = column * count // (width + 1)
                high = max(low + 1, (column + 1) * count // (width + 1))
                # The loudest of everything the column covers, never the
                # average: one shout in a quiet minute is what is looked for.
                height = max(0.5, max(levels[low:high]) ** WAVE_CURVE * limit)
                upper.append(QPointF(left + column, middle - height))
                lower.append(QPointF(left + column, middle + height))
            polygon = QPolygonF(upper + lower[::-1])
            self._wave_cache[key] = polygon
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(theme.WAVE_MUTED if muted else theme.shade(colour,
                                                                          theme.WAVE_SHADE))))
        p.drawPolygon(polygon)

    # --- Mouse ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.duration:
            return
        x = event.position().x()
        if abs(x - self.x_for(self.trim_start)) <= GRAB_PX:
            self._drag = "in"
        elif abs(x - self.x_for(self.trim_end)) <= GRAB_PX:
            self._drag = "out"
        else:
            self._drag = "seek"
            self.scrub_started.emit()
            self.seek_requested.emit(self.time_for(x))

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._drag is None:
            near = self.duration and min(abs(x - self.x_for(self.trim_start)),
                                         abs(x - self.x_for(self.trim_end))) <= GRAB_PX
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.ArrowCursor)
            return
        moment = self.time_for(x)
        if self._drag == "in":
            self.trim_start = min(moment, self.trim_end - MIN_SELECTION)
            self.trim_changed.emit(self.trim_start, self.trim_end)
            self.update()
        elif self._drag == "out":
            self.trim_end = max(moment, self.trim_start + MIN_SELECTION)
            self.trim_changed.emit(self.trim_start, self.trim_end)
            self.update()
        else:
            self.seek_requested.emit(moment)

    def mouseReleaseEvent(self, _event):
        drag, self._drag = self._drag, None
        if drag in ("in", "out"):
            self.trim_committed.emit()
        elif drag == "seek":
            self.scrub_finished.emit()
