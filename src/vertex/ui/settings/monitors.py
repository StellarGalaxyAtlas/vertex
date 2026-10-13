"""The monitor map on Settings › Recording: click a monitor to record it."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from vertex.recorder import monitors
from vertex.recorder.monitors import Monitor
from vertex.ui import theme

# Room around the arrangement, and between monitors that touch on the desktop.
MARGIN = 14
GAP = 3


def desktop_screens() -> list[monitors.Screen]:
    """The monitors as the desktop arranges them, as Qt reports them."""
    screens = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        screens.append(monitors.Screen(
            screen.name(), geometry.x(), geometry.y(), geometry.width(), geometry.height(),
            screen.model().strip() or screen.manufacturer().strip(),
            (round(geometry.width() * ratio), round(geometry.height() * ratio))))
    return screens


def resolution(monitor: Monitor) -> str:
    width, height = monitor.pixels
    return f"{width} × {height}" if width and height else ""


class MonitorMap(QWidget):
    """Every monitor drawn where it sits on the desktop. Clicking one, or
    stepping with the arrow keys, emits `picked` with its name."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitors: list[Monitor] = []
        self.current = ""
        self._rects: list[QRectF] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(240)
        self.setFixedHeight(180)
        self.setAccessibleName("Monitors")

    def set_monitors(self, monitor_list: list[Monitor]) -> None:
        self.monitors = list(monitor_list)
        self._hover = -1
        self._layout()
        self._describe()
        self.update()

    def set_current(self, name: str) -> None:
        self.current = name
        self._describe()
        self.update()

    def rect_of(self, name: str) -> QRectF:
        """Where a monitor is drawn (empty if it isn't)."""
        for monitor, rect in zip(self.monitors, self._rects, strict=False):
            if monitor.name == name:
                return QRectF(rect)
        return QRectF()

    # --- Geometry ----------------------------------------------------------------

    def _layout(self) -> None:
        boxes = monitors.fit(self.monitors, self.width(), self.height(), MARGIN)
        self._rects = [QRectF(x, y, w, h).adjusted(GAP, GAP, -GAP, -GAP)
                       for x, y, w, h in boxes]

    def _at(self, point: QPointF) -> int:
        # Last drawn is on top, so search from the end.
        for index in range(len(self._rects) - 1, -1, -1):
            if self._rects[index].contains(point):
                return index
        return -1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    # --- Input -------------------------------------------------------------------

    def mouseMoveEvent(self, event):
        index = self._at(event.position())
        if index != self._hover:
            self._hover = index
            self.setCursor(Qt.CursorShape.PointingHandCursor if index >= 0
                           else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        index = self._at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and index >= 0:
            self._pick(self.monitors[index].name)
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -1,
                Qt.Key.Key_Right: 1, Qt.Key.Key_Down: 1}.get(event.key())
        order = [m.name for m in monitors.reading_order(self.monitors)]
        if step is None or not order:
            super().keyPressEvent(event)
            return
        if self.current in order:
            index = max(0, min(len(order) - 1, order.index(self.current) + step))
        else:
            index = 0 if step > 0 else len(order) - 1
        self._pick(order[index])

    def event(self, event):
        if event.type() == event.Type.ToolTip:
            index = self._at(QPointF(event.pos()))
            if index >= 0:
                QToolTip.showText(event.globalPos(), self._tooltip(self.monitors[index]), self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def _pick(self, name: str) -> None:
        if name != self.current:
            self.set_current(name)
        self.picked.emit(name)

    def _tooltip(self, monitor: Monitor) -> str:
        lines = [" — ".join(part for part in (monitor.name, monitor.model) if part)]
        if resolution(monitor):
            lines.append(resolution(monitor))
        if not monitor.placed:
            lines.append("The desktop didn't say where this monitor is, so it is drawn "
                         "to the side.")
        lines.append("Recording this monitor." if monitor.name == self.current
                     else "Click to record this monitor.")
        return "\n".join(lines)

    def _describe(self) -> None:
        chosen = next((m for m in self.monitors if m.name == self.current), None)
        self.setAccessibleDescription(
            f"Recording {chosen.name}" if chosen else "No monitor chosen")

    # --- Painting ----------------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.ACCENT if self.hasFocus() else theme.SEAM), 1))
        p.setBrush(QColor(theme.FIELD_BG))
        p.drawRoundedRect(frame, theme.RADIUS_CONTROL, theme.RADIUS_CONTROL)
        if not self.monitors:
            p.setPen(QColor(theme.TEXT_DIM))
            p.setFont(theme.font(9.5))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No monitors found")
            return
        for index, (monitor, rect) in enumerate(zip(self.monitors, self._rects, strict=False)):
            self._paint_monitor(p, monitor, rect, monitor.name == self.current,
                                index == self._hover)

    def _paint_monitor(self, p: QPainter, monitor: Monitor, rect: QRectF, chosen: bool,
                       hover: bool) -> None:
        if chosen:
            fill, edge, width = theme.ACCENT_SOFT, theme.ACCENT, 2.0
        elif hover:
            fill, edge, width = theme.CARD_HOVER, theme.ACCENT_EDGE, 1.0
        else:
            fill, edge, width = theme.CARD_BG, theme.SEAM, 1.0
        p.setPen(QPen(QColor(edge), width))
        p.setBrush(QColor(fill))
        inset = width / 2
        p.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset),
                          theme.RADIUS_SMALL, theme.RADIUS_SMALL)

        # Name, resolution and model, as many as fit, centred in the monitor.
        lines = [(monitor.name, theme.font(9.5, QFont.Weight.DemiBold),
                  "#ffffff" if chosen else theme.TEXT)]
        # The chosen monitor's fill is brighter, so its small print steps up too.
        if resolution(monitor):
            lines.append((resolution(monitor), theme.font(8.5),
                          theme.TEXT if chosen else theme.TEXT_MUTED))
        if monitor.model:
            lines.append((monitor.model, theme.font(8.5),
                          theme.TEXT_MUTED if chosen else theme.TEXT_DIM))
        room = rect.adjusted(6, 4, -6, -4)
        heights = [QFontMetrics(font).height() for _t, font, _c in lines]
        while len(lines) > 1 and sum(heights) > room.height():
            lines.pop()
            heights.pop()
        y = room.top() + max(0.0, (room.height() - sum(heights)) / 2)
        for (text, font, colour), height in zip(lines, heights, strict=True):
            metrics = QFontMetrics(font)
            p.setFont(font)
            p.setPen(QColor(colour))
            shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(room.width()))
            p.drawText(QRectF(room.left(), y, room.width(), height),
                       Qt.AlignmentFlag.AlignCenter, shown)
            y += height
