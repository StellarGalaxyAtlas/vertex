"""Settings › General › Appearance: the colour schemes, each shown as a small
picture of Vertex in its own colours."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QSizePolicy, QWidget

from vertex.ui import icons, theme


def _alpha(colour: str, alpha: float) -> QColor:
    result = QColor(colour)
    result.setAlphaF(alpha)
    return result


class SchemeCard(QAbstractButton):
    """One scheme: a picture of the app in its colours, its name and a line on
    what it looks like. The frame and text are in the scheme in use; the
    picture is always in its own."""

    PREVIEW_H = 92
    PAD = 8

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.title, self.blurb, self.colours = theme.SCHEMES[key]
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setToolTip(f"{self.title}: {self.blurb}")
        self.setAccessibleName(f"{self.title} colour scheme")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _text_height(self) -> int:
        return QFontMetrics(self._title_font()).height() + QFontMetrics(self.font()).height() + 6

    def sizeHint(self):
        return QSize(220, self.PAD * 2 + self.PREVIEW_H + 10 + self._text_height())

    def minimumSizeHint(self):
        return QSize(150, self.sizeHint().height())

    def _title_font(self) -> QFont:
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        checked = self.isChecked()
        if checked:
            edge, width = QColor(theme.ACCENT), 2.0
        elif self.hasFocus():
            edge, width = QColor(theme.SELECT), 1.5
        elif self.underMouse():
            edge, width = QColor(theme.EDGE), 1.0
        else:
            edge, width = QColor(theme.LINE), 1.0
        p.setPen(QPen(edge, width))
        p.setBrush(QColor(theme.MAIN_BG))
        p.drawRoundedRect(outer, 12, 12)

        preview = QRectF(self.PAD, self.PAD, self.width() - 2 * self.PAD, self.PREVIEW_H)
        self._paint_preview(p, preview)

        # Its name, "Default" beside Plum's, the line under it, a tick if chosen.
        x = self.PAD + 4
        top = preview.bottom() + 10
        title_font = self._title_font()
        title_h = QFontMetrics(title_font).height()
        p.setFont(title_font)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(x, top, self.width(), title_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        right = self.width() - self.PAD - 4
        if checked:
            tick = QRectF(right - 20, top, 20, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT_FILL))
            p.drawEllipse(tick)
            p.drawPixmap(tick.adjusted(4, 4, -4, -4).toRect(),
                         icons.pixmap("check", "ON_ACCENT", 12))
            right -= 26
        if self.key == theme.DEFAULT_SCHEME:
            small = QFont(self.font())
            small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
            small.setWeight(QFont.Weight.DemiBold)
            p.setFont(small)
            tag_x = x + QFontMetrics(title_font).horizontalAdvance(self.title) + 8
            tag_w = QFontMetrics(small).horizontalAdvance("Default") + 14
            tag = QRectF(tag_x, top + (title_h - 18) / 2, tag_w, 18)
            p.setPen(QPen(QColor(theme.ACCENT_EDGE), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tag, 9, 9)
            p.drawText(tag, Qt.AlignmentFlag.AlignCenter, "Default")
        p.setFont(self.font())
        p.setPen(QColor(theme.TEXT_DIM))
        metrics = QFontMetrics(self.font())
        p.drawText(QRectF(x, top + title_h + 2, right - x, metrics.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   metrics.elidedText(self.blurb, Qt.TextElideMode.ElideRight, int(right - x)))

    def _paint_preview(self, p: QPainter, rect: QRectF) -> None:
        c = self.colours
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        clip_r = 8
        p.setBrush(QColor(c["MAIN_BG"]))
        p.drawRoundedRect(rect, clip_r, clip_r)
        # The scheme's two glows: its accent from the bottom left, its second
        # colour from the top right.
        for centre, colour, alpha in ((rect.bottomLeft(), c["ACCENT"], 0.24),
                                      (rect.topRight(), c["SECOND"], 0.22)):
            glow = QRadialGradient(centre, rect.width() * 0.6)
            glow.setColorAt(0, _alpha(colour, alpha))
            glow.setColorAt(1, _alpha(colour, 0))
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(rect, clip_r, clip_r)

        # The top bar: a dot, three tabs, the Save clip pill, a gradient under it.
        bar = QRectF(rect.left(), rect.top(), rect.width(), 16)
        p.setBrush(QColor(c["SIDEBAR_BG"]))
        p.drawRoundedRect(bar, clip_r, clip_r)
        p.drawRect(bar.adjusted(0, clip_r, 0, 0))
        y = bar.center().y()
        p.setBrush(QColor(c["ACCENT"]))
        p.drawEllipse(QPointF(bar.left() + 11, y), 3, 3)
        for offset, length, token in ((18, 18, "TEXT"), (40, 14, "TEXT_MUTED"),
                                      (58, 14, "TEXT_MUTED")):
            p.setBrush(QColor(c[token]))
            p.drawRoundedRect(QRectF(bar.left() + offset, y - 1.5, length, 3), 1.5, 1.5)
        p.setBrush(QColor(c["ACCENT"]))
        p.drawRoundedRect(QRectF(bar.right() - 36, y - 4, 28, 8), 4, 4)
        underline = QLinearGradient(bar.bottomLeft(), bar.bottomRight())
        underline.setColorAt(0, _alpha(c["ACCENT"], 0))
        underline.setColorAt(0.3, QColor(c["ACCENT"]))
        underline.setColorAt(0.7, QColor(c["SECOND"]))
        underline.setColorAt(1, _alpha(c["SECOND"], 0))
        p.fillRect(QRectF(bar.left(), bar.bottom() - 1, bar.width(), 1), QBrush(underline))

        # Two panels: a clip's text and a gradient button; the four channels.
        body = QRectF(rect.left() + 8, bar.bottom() + 8, rect.width() - 16,
                      rect.bottom() - bar.bottom() - 16)
        gap = 6
        left = QRectF(body.left(), body.top(), (body.width() - gap) * 0.56, body.height())
        right = QRectF(left.right() + gap, body.top(), body.right() - left.right() - gap,
                       body.height())
        p.setBrush(QColor(c["SECTION_BG"]))
        p.drawRoundedRect(left, 6, 6)
        p.drawRoundedRect(right, 6, 6)
        p.setBrush(QColor(c["TEXT"]))
        p.drawRoundedRect(QRectF(left.left() + 8, left.top() + 8, left.width() * 0.66, 5), 2.5, 2.5)
        p.setBrush(QColor(c["TEXT_MUTED"]))
        p.drawRoundedRect(QRectF(left.left() + 8, left.top() + 18, left.width() * 0.44, 4), 2, 2)
        pill = QRectF(left.left() + 8, left.bottom() - 18, min(46.0, left.width() - 16), 12)
        button = QLinearGradient(pill.topLeft(), pill.topRight())
        button.setColorAt(0, QColor(c["ACCENT"]))
        button.setColorAt(1, QColor(c["SECOND"]))
        p.setBrush(QBrush(button))
        p.drawRoundedRect(pill, 6, 6)
        channels = ("GAME", "CHAT", "MEDIA", "MIC")
        step = (right.height() - 16) / (len(channels) - 1) if right.height() > 16 else 0
        for index, token in enumerate(channels):
            p.setBrush(QColor(c[token]))
            p.drawRoundedRect(QRectF(right.left() + 8, right.top() + 6 + index * step,
                                     right.width() - 16, 4), 2, 2)
        p.restore()


class SchemePicker(QWidget):
    """The schemes in a grid, four to a row, or two when the page is narrow.
    Picking one emits `picked` with its key."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards = {key: SchemeCard(key) for key in theme.SCHEMES}
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self._per_row = 0
        for card in self.cards.values():
            card.clicked.connect(lambda _c=False, k=card.key: self._pick(k))
        self._arrange(4)
        self._value = theme.DEFAULT_SCHEME
        self.set_value(theme.scheme)

    def value(self) -> str:
        return self._value

    def set_value(self, key: str) -> None:
        if key not in self.cards:
            key = theme.DEFAULT_SCHEME
        self._value = key
        for card_key, card in self.cards.items():
            card.setChecked(card_key == key)

    def _pick(self, key: str) -> None:
        self.set_value(key)
        self.picked.emit(key)

    def _arrange(self, per_row: int) -> None:
        if per_row == self._per_row:
            return
        self._per_row = per_row
        for card in self.cards.values():
            self.grid.removeWidget(card)
        for index, card in enumerate(self.cards.values()):
            self.grid.addWidget(card, index // per_row, index % per_row)
        for column in range(4):
            self.grid.setColumnStretch(column, 1 if column < per_row else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card = next(iter(self.cards.values()))
        need = 4 * card.minimumSizeHint().width() + 3 * self.grid.spacing()
        self._arrange(4 if self.width() >= need else 2)
