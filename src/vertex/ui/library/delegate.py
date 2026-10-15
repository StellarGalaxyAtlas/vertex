"""Paints one clip card, and maps clicks on it to the part that was hit."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QLineEdit, QStyle, QStyledItemDelegate

from vertex import fmt
from vertex.ui import icons, theme
from vertex.ui.library.model import ClipRole

PAD = 9            # room around the card for its shadow
INFO_H = 58        # the two text lines under the thumbnail
RADIUS = theme.RADIUS_CARD
STAR = 30          # the favourite button's square


def thumb_rect(cell: QRect) -> QRectF:
    card = QRectF(cell).adjusted(PAD, PAD, -PAD, -PAD)
    return QRectF(card.left(), card.top(), card.width(), card.width() * 9 / 16)


def card_rect(cell: QRect) -> QRectF:
    return QRectF(cell).adjusted(PAD, PAD, -PAD, -PAD)


def star_rect(cell: QRect) -> QRectF:
    thumb = thumb_rect(cell)
    return QRectF(thumb.right() - STAR - 8, thumb.top() + 8, STAR, STAR)


def title_rect(cell: QRect) -> QRectF:
    thumb = thumb_rect(cell)
    return QRectF(thumb.left() + 14, thumb.bottom() + 8, thumb.width() - 28, 22)


def tags_rect(cell: QRect) -> QRectF:
    """The line under the title: tags, age and size. A click on it edits the tags."""
    thumb = thumb_rect(cell)
    return QRectF(thumb.left() + 14, thumb.bottom() + 30, thumb.width() - 28, 18)


class ClipDelegate(QStyledItemDelegate):
    open_requested = Signal(object)          # clip
    tags_requested = Signal(object)          # clip
    rename_requested = Signal(object)        # QModelIndex
    favorite_toggled = Signal(object)        # clip

    def __init__(self, view, state, parent=None):
        super().__init__(parent)
        self.view = view
        self.state = state
        self.cell = QSize(320, 260)

    def sizeHint(self, option, index):
        return self.cell

    # --- Painting -------------------------------------------------------------

    def paint(self, painter: QPainter, option, index):
        clip = index.data(ClipRole)
        if clip is None:
            return
        model = index.model()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cell = option.rect
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = card_rect(cell)
        thumb = thumb_rect(cell)

        self._shadow(painter, card, hovered)
        body = QPainterPath()
        body.addRoundedRect(card, RADIUS, RADIUS)
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        gradient.setColorAt(0, QColor(theme.CARD_HOVER_TOP if hovered else theme.CARD_TOP))
        gradient.setColorAt(1, QColor(theme.CARD_HOVER_BOTTOM if hovered else theme.CARD_BOTTOM))
        painter.fillPath(body, QBrush(gradient))

        # Thumbnail, clipped to the card's rounded top.
        painter.save()
        top = QPainterPath()
        top.addRoundedRect(QRectF(thumb.left(), thumb.top(), thumb.width(),
                                  thumb.height() + RADIUS), RADIUS, RADIUS)
        clip_area = QPainterPath()
        clip_area.addRect(thumb)
        painter.setClipPath(top.intersected(clip_area))
        pixmap = model.preview_pixmap(index.row()) or model.thumbnail(clip)
        if pixmap is not None and not pixmap.isNull():
            self._draw_cover(painter, pixmap, thumb)
        else:
            painter.fillRect(thumb, QColor(theme.CONTROL_BG))
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(thumb, Qt.AlignmentFlag.AlignCenter, "…")
        scrim = QLinearGradient(thumb.topLeft(), thumb.bottomLeft())
        scrim.setColorAt(0.0, QColor(0, 0, 0, 70))
        scrim.setColorAt(0.35, QColor(0, 0, 0, 0))
        scrim.setColorAt(0.7, QColor(0, 0, 0, 0))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 130))
        painter.fillRect(thumb, QBrush(scrim))
        painter.restore()

        # Duration badge.
        seconds = model.duration(clip)
        if seconds:
            text = fmt.duration(seconds)
            painter.setFont(theme.font(8.5, QFont.Weight.DemiBold))
            width = QFontMetrics(painter.font()).horizontalAdvance(text) + 14
            badge = QRectF(thumb.right() - width - 8, thumb.bottom() - 28, width, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(6, 7, 10, 200))
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(theme.ON_VIDEO))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

        # Favourite star: always shown when set, on hover otherwise.
        favorite = clip.name in self.state.favorites
        if favorite or hovered:
            star = star_rect(cell)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(6, 7, 10, 150))
            painter.drawRoundedRect(star, 8, 8)
            glyph = icons.pixmap("star" if favorite else "star-outline",
                                 theme.STAR if favorite else theme.ON_VIDEO, 18)
            painter.drawPixmap(QPointF(star.center().x() - 9, star.center().y() - 9), glyph)

        # Title.
        title = title_rect(cell)
        painter.setFont(theme.font(10.5, QFont.Weight.DemiBold))
        painter.setPen(QColor(theme.TEXT))
        metrics = QFontMetrics(painter.font())
        painter.drawText(title, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(self.state.title_of(clip),
                                            Qt.TextElideMode.ElideRight, int(title.width())))

        # One line under it: game (with its colour) · people · age · size. An
        # untagged clip says so, and offers to tag it while hovered.
        game, people = self.state.tags_of(clip)
        line = tags_rect(cell)
        painter.setFont(theme.font(8.5))
        metrics = QFontMetrics(painter.font())
        x = line.left()
        if game:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.game_colour(game)))
            painter.drawEllipse(QPointF(x + 4, line.center().y()), 4, 4)
            x += 13
        parts = [part for part in (game, ", ".join(people)) if part]
        text = "  ·  ".join([*parts, clip.age_human, clip.size_human])
        if not parts:
            lead = "Add tags" if hovered else "Untagged"
            painter.setPen(QColor(theme.SELECT if hovered else theme.TEXT_DIM))
            painter.drawText(QRectF(x, line.top(), line.right() - x, line.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lead)
            x += metrics.horizontalAdvance(lead)
            text = "  ·  " + text
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.drawText(QRectF(x, line.top(), line.right() - x, line.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                            int(line.right() - x)))
        self._outline(painter, card, hovered)
        painter.restore()

    @staticmethod
    def _outline(painter: QPainter, card: QRectF, hovered: bool) -> None:
        """A faint edge in the scheme's own colours, the accent into the second
        one, so a card stands off the page; brighter while hovered."""
        alpha = 0.6 if hovered else 0.25
        edge = QLinearGradient(card.topLeft(), card.bottomRight())
        for at, token in ((0, theme.ACCENT), (1, theme.SECOND)):
            colour = QColor(token)
            colour.setAlphaF(alpha)
            edge.setColorAt(at, colour)
        painter.setPen(QPen(QBrush(edge), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)

    @staticmethod
    def _shadow(painter: QPainter, card: QRectF, hovered: bool) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        steps = 6
        for i in range(steps, 0, -1):
            alpha = int((26 if hovered else 18) * (steps - i + 1) / steps)
            spread = i * 1.3
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(card.adjusted(-spread, -spread + 3, spread, spread + 3),
                                    RADIUS + spread, RADIUS + spread)

    @staticmethod
    def _draw_cover(painter: QPainter, pixmap, target: QRectF) -> None:
        """Fill `target` with the pixmap, cropping rather than letterboxing."""
        source = QRectF(pixmap.rect())
        scale = max(target.width() / source.width(), target.height() / source.height())
        width, height = target.width() / scale, target.height() / scale
        crop = QRectF(source.center().x() - width / 2, source.center().y() - height / 2,
                      width, height)
        painter.drawPixmap(target, pixmap, crop)

    # --- Clicks ---------------------------------------------------------------

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.Type.MouseButtonRelease or \
                event.button() != Qt.MouseButton.LeftButton:
            return False
        clip = index.data(ClipRole)
        if clip is None:
            return False
        point = event.position()
        cell = option.rect
        if star_rect(cell).contains(point):
            self.favorite_toggled.emit(clip)
        elif tags_rect(cell).contains(point):
            self.tags_requested.emit(clip)
        elif title_rect(cell).contains(point):
            self.rename_requested.emit(index)
        elif card_rect(cell).contains(point):
            self.open_requested.emit(clip)
        else:
            return False
        return True

    # --- Inline rename ----------------------------------------------------------

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFont(theme.font(10.5, QFont.Weight.DemiBold))
        editor.setStyleSheet(f"padding: 1px 6px; border-radius: 6px; "
                             f"border: 1px solid {theme.SELECT}; background: {theme.FIELD_BG};")
        return editor

    def setEditorData(self, editor, index):
        # The view calls this again on every change to the row: each frame of
        # the hover preview, a thumbnail arriving. Filling the field only once
        # keeps what is being typed.
        if editor.property("filled"):
            return
        editor.setProperty("filled", True)
        editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text().strip(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(title_rect(option.rect).adjusted(-7, -2, 7, 2).toRect())

