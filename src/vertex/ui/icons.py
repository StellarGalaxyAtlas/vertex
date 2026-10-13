"""The UI's icons, drawn with QPainter.

Drawn rather than loaded from the icon theme, so they look the same on every
desktop and in any colour — a theme can be missing half of them, and emoji
glyphs render differently on every font stack.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from vertex import paths
from vertex.ui import theme

_DRAW = {}


def _register(name):
    def wrap(fn):
        _DRAW[name] = fn
        return fn
    return wrap


def _pen(p: QPainter, colour: QColor, width: float = 1.8):
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill(p: QPainter, colour: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)


# Every drawer paints into a 24×24 box.

@_register("play")
def _play(p, c):
    _fill(p, c)
    path = QPainterPath(QPointF(8, 5.5))
    path.lineTo(18.5, 12)
    path.lineTo(8, 18.5)
    path.closeSubpath()
    p.drawPath(path)


@_register("pause")
def _pause(p, c):
    _fill(p, c)
    p.drawRoundedRect(QRectF(7, 5.5, 3.6, 13), 1, 1)
    p.drawRoundedRect(QRectF(13.4, 5.5, 3.6, 13), 1, 1)


@_register("mark-in")
def _mark_in(p, c):
    _pen(p, c)
    p.drawLine(QPointF(6, 5), QPointF(6, 19))
    p.drawLine(QPointF(6, 5), QPointF(10, 5))
    p.drawLine(QPointF(6, 19), QPointF(10, 19))
    _fill(p, c)
    path = QPainterPath(QPointF(11, 8))
    path.lineTo(18, 12)
    path.lineTo(11, 16)
    path.closeSubpath()
    p.drawPath(path)


@_register("mark-out")
def _mark_out(p, c):
    _pen(p, c)
    p.drawLine(QPointF(18, 5), QPointF(18, 19))
    p.drawLine(QPointF(18, 5), QPointF(14, 5))
    p.drawLine(QPointF(18, 19), QPointF(14, 19))
    _fill(p, c)
    path = QPainterPath(QPointF(13, 8))
    path.lineTo(6, 12)
    path.lineTo(13, 16)
    path.closeSubpath()
    p.drawPath(path)


@_register("reset")
def _reset(p, c):
    _pen(p, c)
    p.drawArc(QRectF(5, 5, 14, 14), 60 * 16, 270 * 16)
    _fill(p, c)
    path = QPainterPath(QPointF(15.5, 3.5))
    path.lineTo(19.5, 7.5)
    path.lineTo(14, 9)
    path.closeSubpath()
    p.drawPath(path)


@_register("volume")
def _volume(p, c):
    _fill(p, c)
    path = QPainterPath(QPointF(4, 9.5))
    for x, y in ((8, 9.5), (12.5, 5.5), (12.5, 18.5), (8, 14.5), (4, 14.5)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)
    _pen(p, c)
    p.drawArc(QRectF(11, 8, 6, 8), -60 * 16, 120 * 16)
    p.drawArc(QRectF(11, 5, 10, 14), -60 * 16, 120 * 16)


@_register("mute")
def _mute(p, c):
    _fill(p, c)
    path = QPainterPath(QPointF(4, 9.5))
    for x, y in ((8, 9.5), (12.5, 5.5), (12.5, 18.5), (8, 14.5), (4, 14.5)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)
    _pen(p, c)
    p.drawLine(QPointF(15.5, 9.5), QPointF(20.5, 14.5))
    p.drawLine(QPointF(20.5, 9.5), QPointF(15.5, 14.5))


def _star_path(cx=12.0, cy=12.4, outer=8.6, inner=3.9) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + i * 36)
        point = QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


@_register("star")
def _star(p, c):
    _fill(p, c)
    p.drawPath(_star_path())


@_register("star-outline")
def _star_outline(p, c):
    _pen(p, c, 1.6)
    p.drawPath(_star_path())


@_register("search")
def _search(p, c):
    _pen(p, c, 2)
    p.drawEllipse(QRectF(5, 5, 10.5, 10.5))
    p.drawLine(QPointF(14, 14), QPointF(19, 19))


@_register("library")
def _library(p, c):
    _pen(p, c)
    for x, y in ((4.5, 4.5), (13, 4.5), (4.5, 13), (13, 13)):
        p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.6, 1.6)


@_register("sonar")
def _sonar(p, c):
    _pen(p, c, 2)
    for x, top in ((6, 8), (10, 4.5), (14, 10), (18, 6.5)):
        p.drawLine(QPointF(x, top), QPointF(x, 19.5))


@_register("settings")
def _settings(p, c):
    _pen(p, c)
    for y, knob in ((7, 9), (12, 15), (17, 7)):
        p.drawLine(QPointF(4.5, y), QPointF(19.5, y))
        _fill(p, c)
        p.drawEllipse(QPointF(knob, y), 2.4, 2.4)
        _pen(p, c)


@_register("record")
def _record(p, c):
    _fill(p, c)
    p.drawEllipse(QPointF(12, 12), 6, 6)


@_register("stop")
def _stop(p, c):
    _fill(p, c)
    p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2, 2)


@_register("save-clip")
def _save_clip(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(4, 6, 16, 12), 2.5, 2.5)
    _fill(p, c)
    path = QPainterPath(QPointF(10, 9))
    path.lineTo(15, 12)
    path.lineTo(10, 15)
    path.closeSubpath()
    p.drawPath(path)


@_register("link")
def _link(p, c):
    # Two chain links, joined.
    _pen(p, c, 2)
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-9.5, -3.5, 11, 7), 3.5, 3.5)
    p.drawRoundedRect(QRectF(-1.5, -3.5, 11, 7), 3.5, 3.5)
    p.restore()


@_register("unlink")
def _unlink(p, c):
    # The same links, pulled apart.
    _pen(p, c, 2)
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-10.5, -3.5, 8.5, 7), 3.5, 3.5)
    p.drawRoundedRect(QRectF(2, -3.5, 8.5, 7), 3.5, 3.5)
    p.restore()


@_register("grip")
def _grip(p, c):
    # Six dots: a handle to drag by.
    _fill(p, c)
    for x in (9, 15):
        for y in (7, 12, 17):
            p.drawEllipse(QPointF(x, y), 1.5, 1.5)


@_register("check")
def _check(p, c):
    _pen(p, c, 2.2)
    path = QPainterPath(QPointF(6, 12.5))
    path.lineTo(10.5, 17)
    path.lineTo(18, 7.5)
    p.drawPath(path)


@_register("chevron-right")
def _chevron_right(p, c):
    _pen(p, c, 2)
    p.drawLine(QPointF(10, 7), QPointF(15, 12))
    p.drawLine(QPointF(15, 12), QPointF(10, 17))


@_register("chevron-down")
def _chevron_down(p, c):
    _pen(p, c, 2)
    p.drawLine(QPointF(7, 10), QPointF(12, 15))
    p.drawLine(QPointF(12, 15), QPointF(17, 10))


@_register("back")
def _back(p, c):
    _pen(p, c, 2)
    p.drawLine(QPointF(19, 12), QPointF(6, 12))
    p.drawLine(QPointF(11, 7), QPointF(6, 12))
    p.drawLine(QPointF(11, 17), QPointF(6, 12))


@_register("trash")
def _trash(p, c):
    _pen(p, c)
    p.drawLine(QPointF(5, 7), QPointF(19, 7))
    p.drawLine(QPointF(10, 4.5), QPointF(14, 4.5))
    path = QPainterPath(QPointF(7, 7))
    path.lineTo(8, 19.5)
    path.lineTo(16, 19.5)
    path.lineTo(17, 7)
    p.drawPath(path)


@_register("folder")
def _folder(p, c):
    _pen(p, c)
    path = QPainterPath(QPointF(4, 7))
    for x, y in ((9.5, 7), (11, 9), (20, 9), (20, 18), (4, 18)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)


@_register("refresh")
def _refresh(p, c):
    _pen(p, c)
    p.drawArc(QRectF(5, 5, 14, 14), 30 * 16, 300 * 16)
    _fill(p, c)
    path = QPainterPath(QPointF(19.5, 4.5))
    path.lineTo(19.8, 10)
    path.lineTo(14.5, 8.5)
    path.closeSubpath()
    p.drawPath(path)


@_register("tag")
def _tag(p, c):
    _pen(p, c)
    path = QPainterPath(QPointF(4.5, 4.5))
    for x, y in ((12, 4.5), (19.5, 12), (12, 19.5), (4.5, 12)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)
    _fill(p, c)
    p.drawEllipse(QPointF(8.6, 8.6), 1.5, 1.5)


@_register("scissors")
def _scissors(p, c):
    _pen(p, c)
    p.drawEllipse(QRectF(4, 13, 5.5, 5.5))
    p.drawEllipse(QRectF(14.5, 13, 5.5, 5.5))
    p.drawLine(QPointF(8.5, 14), QPointF(17, 4.5))
    p.drawLine(QPointF(15.5, 14), QPointF(7, 4.5))


@_register("export")
def _export(p, c):
    _pen(p, c)
    p.drawLine(QPointF(12, 4), QPointF(12, 14))
    p.drawLine(QPointF(8, 8), QPointF(12, 4))
    p.drawLine(QPointF(16, 8), QPointF(12, 4))
    path = QPainterPath(QPointF(5, 12))
    path.lineTo(5, 19.5)
    path.lineTo(19, 19.5)
    path.lineTo(19, 12)
    p.drawPath(path)


@_register("game")
def _game(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(3.5, 7.5, 17, 10), 5, 5)
    p.drawLine(QPointF(7, 12.5), QPointF(10, 12.5))
    p.drawLine(QPointF(8.5, 11), QPointF(8.5, 14))
    _fill(p, c)
    p.drawEllipse(QPointF(15.5, 11.5), 1.1, 1.1)
    p.drawEllipse(QPointF(17.5, 13.5), 1.1, 1.1)


@_register("chat")
def _chat(p, c):
    _pen(p, c)
    path = QPainterPath(QPointF(5, 5.5))
    for x, y in ((19, 5.5), (19, 15.5), (11, 15.5), (7, 19), (7, 15.5), (5, 15.5)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.drawPath(path)


@_register("media")
def _media(p, c):
    _pen(p, c)
    p.drawLine(QPointF(10, 16.5), QPointF(10, 5.5))
    p.drawLine(QPointF(10, 5.5), QPointF(18, 4))
    p.drawLine(QPointF(18, 4), QPointF(18, 15))
    _fill(p, c)
    p.drawEllipse(QPointF(7.8, 16.8), 2.6, 2.2)
    p.drawEllipse(QPointF(15.8, 15.3), 2.6, 2.2)


@_register("mic")
def _mic(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(9, 3.5, 6, 11), 3, 3)
    p.drawArc(QRectF(6, 7, 12, 10), 200 * 16, 140 * 16)
    p.drawLine(QPointF(12, 17), QPointF(12, 20))
    p.drawLine(QPointF(9, 20), QPointF(15, 20))


@_register("headphones")
def _headphones(p, c):
    _pen(p, c)
    p.drawArc(QRectF(4.5, 5, 15, 15), 0, 180 * 16)
    _fill(p, c)
    p.drawRoundedRect(QRectF(4, 12.5, 4, 7), 1.5, 1.5)
    p.drawRoundedRect(QRectF(16, 12.5, 4, 7), 1.5, 1.5)


@_register("plus")
def _plus(p, c):
    _pen(p, c, 2)
    p.drawLine(QPointF(12, 6), QPointF(12, 18))
    p.drawLine(QPointF(6, 12), QPointF(18, 12))


@_register("close")
def _close(p, c):
    _pen(p, c, 2)
    p.drawLine(QPointF(7, 7), QPointF(17, 17))
    p.drawLine(QPointF(17, 7), QPointF(7, 17))


@_register("menu")
def _menu(p, c):
    _fill(p, c)
    for y in (6.5, 12, 17.5):
        p.drawEllipse(QPointF(12, y), 1.7, 1.7)


def pixmap(name: str, colour: str = theme.TEXT, size: int = 18, ratio: float = 2.0) -> QPixmap:
    side = int(size * ratio)
    image = QPixmap(side, side)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(side / 24, side / 24)
    _DRAW[name](painter, QColor(colour))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


@lru_cache(maxsize=256)
def icon(name: str, colour: str = theme.TEXT, size: int = 18,
         disabled: str = theme.TEXT_DIM) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, colour, size), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, colour, size), QIcon.Mode.Active)
    result.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled)
    return result


def channel_icon_name(channel_id: str) -> str:
    return {"game": "game", "chat": "chat", "media": "media",
            "mic": "mic", "desktop": "headphones"}.get(channel_id, "volume")


@lru_cache(maxsize=4)
def app_icon(variant: str = paths.DEFAULT_LOGO_VARIANT) -> QIcon:
    return QIcon(str(paths.mark_path(variant)))


def names() -> list[str]:
    return sorted(_DRAW)
