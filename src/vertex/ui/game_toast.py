"""Vertex's own toast over games, where the platform has it (platform.GAME_TOAST):
a card in the top right corner of the screen the pointer is on, with a
coloured strip, an icon, a heading and the detail under it.

It is a frameless window that stays on top, takes no focus and lets every
click through, so it shows above windowed, borderless and most full-screen
games without taking the game out of the front. One at a time: a new notice
replaces the one showing.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from vertex.recorder.notifier import TIMEOUTS
from vertex.ui import icons, theme

WIDTH = 340
HEIGHT = 70
MARGIN = 28          # from the screen's edges
STRIP = 5
RADIUS = 12

# Each level's strip and icon: tokens in ui/theme.
LOOKS = {"ok": ("ACCENT", "check", "OK"), "info": ("ACCENT", "bell", "ACCENT_EDGE"),
         "warn": ("WARN", "bell", "WARN"), "error": ("DANGER", "close", "DANGER")}


class GameToast(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.WindowTransparentForInput |
                         Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(WIDTH, HEIGHT)
        self.title = ""
        self.body = ""
        self.level = "info"
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._fade)
        self._fading = QPropertyAnimation(self, b"windowOpacity", self)
        self._fading.setDuration(250)
        self._fading.setStartValue(1.0)
        self._fading.setEndValue(0.0)
        self._fading.finished.connect(self.hide)

    def show_notice(self, title: str, body: str, level: str) -> bool:
        self.title, self.body = title, body
        self.level = level if level in LOOKS else "info"
        self._fading.stop()
        self.setWindowOpacity(1.0)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.geometry()
            self.move(area.right() + 1 - MARGIN - WIDTH, area.top() + MARGIN)
        self.update()
        self.show()
        self.raise_()
        self._timer.start(round(TIMEOUTS.get(self.level, 3.0) * 1000))
        return True

    def _fade(self) -> None:
        self._fading.start()

    def paintEvent(self, _event):
        strip, icon, icon_colour = LOOKS[self.level]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(card, RADIUS, RADIUS)
        p.fillPath(shape, QColor(theme.SECTION_BG))
        p.save()
        p.setClipPath(shape)
        p.fillRect(QRectF(card.left(), card.top(), STRIP, card.height()),
                   QColor(theme.colour(strip)))
        p.restore()
        p.setPen(QColor(theme.SEAM))
        p.drawPath(shape)
        p.drawPixmap(20, (HEIGHT - 28) // 2,
                     icons.pixmap(icon, icon_colour, 28, self.devicePixelRatioF()))
        text_left, text_width = 62, WIDTH - 62 - 16
        p.setFont(theme.font(12, QFont.Weight.DemiBold))
        p.setPen(QColor(theme.TEXT))
        heading = QRectF(text_left, 13 if self.body else 0, text_width,
                         24 if self.body else HEIGHT)
        p.drawText(heading, Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, text_width))
        if self.body:
            p.setFont(theme.font(10))
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(QRectF(text_left, 37, text_width, 20), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(self.body, Qt.TextElideMode.ElideRight,
                                                  text_width))
        p.end()
