"""Small widgets used across the app."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QBoxLayout,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vertex import paths
from vertex.ui import icons, theme

# The width of every drop-down, number and text field in a settings row, so
# they line up and look alike on every page.
CONTROL_WIDTH = 220


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    """A QLabel styled by `role`: '', 'Muted', 'Dim', 'Heading', 'Subheading', 'Group'."""
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, kind: str = "", icon: str = "", on_click=None,
           tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if kind:
        widget.setProperty("kind", kind)
    if icon:
        colour = {"primary": "ON_ACCENT", "danger": "DANGER"}.get(kind, "TEXT")
        theme.themed(widget, lambda: widget.setIcon(icons.icon(icon, colour)), "icon")
    if on_click is not None:
        widget.clicked.connect(on_click)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class IconButton(QToolButton):
    """A button that is only an icon. `colour` is a token of the scheme in use
    ("TEXT_MUTED") or a colour of its own."""

    def __init__(self, icon_name: str, tooltip: str = "", size: int = 18,
                 colour: str = "TEXT", parent=None, kind: str = "ghost"):
        super().__init__(parent)
        self._size = size
        self.setProperty("kind", kind)
        self.set_icon(icon_name, colour)
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)

    def set_icon(self, icon_name: str, colour: str = "TEXT") -> None:
        self._icon = (icon_name, colour)
        theme.themed(self, lambda: self.setIcon(icons.icon(icon_name, colour, self._size)),
                     "icon")

    def set_size(self, size: int) -> None:
        """Draw the icon at `size` px from now on."""
        if size != self._size:
            self._size = size
            self.setIconSize(QSize(size, size))
            self.set_icon(*self._icon)


def hline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    theme.style(line, lambda: f"background: {theme.LINE};")
    return line


class ElidedLabel(QLabel):
    """A label that elides instead of growing past its width."""

    def __init__(self, text: str = "", parent=None, mode=Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self._elide()
        self.setToolTip(text if self.text() != text else "")

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        self._elide()
        super().resizeEvent(event)

    def _elide(self):
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, self._mode, max(10, self.width())))

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())


class EditableLabel(QWidget):
    """Text that becomes a line edit when clicked. Emits `committed(text)`."""

    committed = Signal(str)

    def __init__(self, text: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self.display = ElidedLabel(text)
        self.display.setCursor(Qt.CursorShape.IBeamCursor)
        self.display.setToolTip("Click to rename")
        self.edit = QLineEdit(text)
        self.edit.setPlaceholderText(placeholder)
        self._stack.addWidget(self.display)
        self._stack.addWidget(self.edit)
        self.edit.editingFinished.connect(self._finish)
        self.edit.installEventFilter(self)
        self.display.mousePressEvent = lambda _e: self.begin_edit()
        self._cancelled = False

    def text(self) -> str:
        return self.display.full_text()

    def set_text(self, text: str) -> None:
        self.display.setText(text)
        self.edit.setText(text)

    def begin_edit(self) -> None:
        self._cancelled = False
        self.edit.setText(self.display.full_text())
        self._stack.setCurrentWidget(self.edit)
        self.edit.setFocus()
        self.edit.selectAll()

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == event.Type.KeyPress \
                and event.key() == Qt.Key.Key_Escape:
            self._cancelled = True
            self._stack.setCurrentWidget(self.display)
            return True
        return super().eventFilter(obj, event)

    def _finish(self) -> None:
        if self._stack.currentWidget() is not self.edit:
            return
        self._stack.setCurrentWidget(self.display)
        if self._cancelled:
            return
        text = self.edit.text().strip()
        if text != self.display.full_text():
            self.committed.emit(text)


class Toggle(QAbstractButton):
    """An on/off switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked() and self.isEnabled()
        # Off, the track is outlined so the switch reads as one on any card;
        # disabled, the knob dims and the track stays.
        p.setPen(Qt.PenStyle.NoPen if on else QPen(QColor(theme.EDGE), 1))
        p.setBrush(QColor(theme.ACCENT if on else theme.CONTROL_BG))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 10.5, 10.5)
        knob = 16
        x = 3 + self._offset * (self.width() - knob - 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ON_ACCENT if on else
                          theme.TEXT_MUTED if self.isEnabled() else theme.TEXT_DIM))
        p.drawEllipse(QRectF(x, 3, knob, knob))

    def sizeHint(self):
        return QSize(40, 22)


class SideNav(QWidget):
    """A column of pages to pick from, each with an icon: a page's tabs, on
    the left of it. Takes (key, text, icon) options."""

    changed = Signal(str, bool)       # key, and always True: as Segmented's

    def __init__(self, options: list[tuple[str, str, str]], current: str = "", parent=None):
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._icons = {key: name for key, _text, name in options}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setObjectName("SideNav")
        theme.style(self, lambda: f"""
            #SideNav QPushButton {{ background: transparent; text-align: left;
                                    padding: 10px 14px; border-radius: {theme.RADIUS_CONTROL}px;
                                    color: {theme.TEXT_MUTED}; font-size: 11pt; }}
            #SideNav QPushButton:hover {{ color: {theme.TEXT}; background: {theme.CARD_BG}; }}
            #SideNav QPushButton:checked {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT};
                                            font-weight: 600; }}
        """)
        for key, text, _name in options:
            option = QPushButton(text)
            option.setCheckable(True)
            option.setIconSize(QSize(20, 20))
            option.setCursor(Qt.CursorShape.PointingHandCursor)
            option.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            option.clicked.connect(lambda _c=False, k=key: self._pick(k))
            layout.addWidget(option)
            self._buttons[key] = option
        layout.addStretch(1)
        self._current = current or options[0][0]
        self._paint()

    @property
    def current(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        self._current = key
        self._paint()

    def _pick(self, key: str) -> None:
        self._current = key
        self._paint()
        self.changed.emit(key, True)

    def _paint(self) -> None:
        for key, option in self._buttons.items():
            active = key == self._current
            option.setChecked(active)
            colour = "TEXT" if active else "TEXT_MUTED"
            theme.themed(option, lambda o=option, k=key, c=colour: o.setIcon(
                icons.icon(self._icons[k], c, 20)), "icon")


class Columns(QWidget):
    """Sections side by side once there is room for them, one above the other
    before that. Each keeps its own height."""

    WIDE = 1300          # px this row needs before its sections go side by side

    def __init__(self, *sections: QWidget, parent=None):
        super().__init__(parent)
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(16)
        for section in sections:
            self._layout.addWidget(section, 1, Qt.AlignmentFlag.AlignTop)

    @property
    def side_by_side(self) -> bool:
        return self._layout.direction() == QBoxLayout.Direction.LeftToRight

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = event.size().width() >= self.WIDE
        if wide != self.side_by_side:
            self._layout.setDirection(QBoxLayout.Direction.LeftToRight if wide
                                      else QBoxLayout.Direction.TopToBottom)


class Segmented(QWidget):
    """A row of mutually exclusive options. With `directional`, clicking the
    active option again flips its direction, and only it carries an arrow."""

    changed = Signal(str, bool)       # key, descending

    def __init__(self, options: list[tuple[str, str]], current: str = "",
                 directional: bool = False, parent=None):
        super().__init__(parent)
        self._directional = directional
        self._descending = True
        self._buttons: dict[str, QPushButton] = {}
        self._labels = dict(options)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.setObjectName("Segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)     # its recessed track
        theme.style(self, lambda: f"""
            #Segmented {{ background: {theme.FIELD_BG}; border-radius: {theme.RADIUS_CONTROL}px; }}
            #Segmented QPushButton {{ background: transparent; padding: 5px 12px;
                                      border-radius: 7px; color: {theme.TEXT_MUTED}; }}
            #Segmented QPushButton:hover {{ color: {theme.TEXT}; }}
            #Segmented QPushButton:checked {{ background: {theme.ACCENT_SOFT}; color: {theme.TEXT};
                                              font-weight: 600; }}
        """)
        for key, text in options:
            option = QPushButton(text)
            option.setCheckable(True)
            option.setCursor(Qt.CursorShape.PointingHandCursor)
            option.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            option.clicked.connect(lambda _c=False, k=key: self._pick(k))
            layout.addWidget(option)
            self._buttons[key] = option
        self._current = current or options[0][0]
        self._paint()

    @property
    def current(self) -> str:
        return self._current

    @property
    def descending(self) -> bool:
        return self._descending

    def set_current(self, key: str, descending: bool = True) -> None:
        self._current, self._descending = key, descending
        self._paint()

    def _pick(self, key: str) -> None:
        if key == self._current and self._directional:
            self._descending = not self._descending
        else:
            self._current = key
            self._descending = True
        self._paint()
        self.changed.emit(self._current, self._descending)

    def _paint(self) -> None:
        for key, option in self._buttons.items():
            active = key == self._current
            option.setChecked(active)
            arrow = (" ↓" if self._descending else " ↑") if active and self._directional else ""
            option.setText(self._labels[key] + arrow)


class StorageGauge(QWidget):
    """The disk the clips are on: one slim bar of how full it is, and a line
    under it with the clips' share and what is free (of how much, unless
    `short`)."""

    def __init__(self, short: bool = False, parent=None):
        super().__init__(parent)
        self._short = short
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.meter = Meter()
        layout.addWidget(self.meter)
        self.text = label("", "Dim", wrap=True)
        layout.addWidget(self.text)
        self.stats = None

    def set_stats(self, stats) -> None:
        self.stats = stats
        if stats is None:
            return
        # Full is what isn't free to use, matching the text: the disk's own
        # count of used space leaves out what it keeps back for the system.
        self.meter.set_fraction(1 - stats.fraction(stats.disk_free))
        text = f"Clips {stats.clips_human} · {stats.free_human} free"
        self.text.setText(text if self._short else f"{text} of {stats.total_human}")
        self.setToolTip(f"Clips {stats.clips_human} · everything else {stats.other_human} · "
                        f"free {stats.free_human} of {stats.total_human}")


class FlowLayout(QLayout):
    """Lays children out left to right, wrapping onto new lines."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, dry):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x = rect.x()
                y += line + self._spacing
                line = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


class Section(QFrame):
    """A settings card: a title, a sentence about it, then its controls."""

    def __init__(self, title: str = "", blurb: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)
        outer.setSpacing(12)
        if title:
            outer.addWidget(label(title, "Subheading"))
        if blurb:
            outer.addWidget(label(blurb, "Muted", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_row(self, title: str, widget: QWidget, hint: str = "") -> QWidget:
        row = setting_row(title, widget, hint)
        self.body.addWidget(row)
        return row


def setting_row(title: str, widget: QWidget, hint: str = "") -> QWidget:
    """One setting: its name, a hint under it, and its control on the right."""
    if isinstance(widget, (QComboBox, QAbstractSpinBox, QLineEdit)):
        widget.setMinimumWidth(max(widget.minimumWidth(), CONTROL_WIDTH))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    row.hint = label(hint, "Dim", wrap=True)
    row.hint.setVisible(bool(hint))
    text.addWidget(row.hint)
    layout.addLayout(text, 1)
    layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class FieldGrid(QWidget):
    """Fields side by side, each with its title above: all in one row when
    they fit, two to a row when they don't, one when even that is too wide."""

    def __init__(self, field_width: int = 150, parent=None):
        super().__init__(parent)
        self._field_width = field_width
        self._fields: list[QWidget] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

    def add(self, title: str, widget: QWidget) -> QWidget:
        if isinstance(widget, QComboBox):
            # Sized by the grid, not by the longest entry, so the row can
            # narrow and reflow.
            widget.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(6)
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(label(title))
        layout.addWidget(widget)
        self._fields.append(field)
        self._columns = 0
        self._reflow()
        return field

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        count = len(self._fields)
        if not count:
            return
        spacing = self._grid.horizontalSpacing()
        fits = max(1, (self.width() + spacing) // (self._field_width + spacing))
        columns = count if fits >= count else (2 if fits >= 2 else 1)
        if columns == self._columns:
            return
        self._columns = columns
        for field in self._fields:
            self._grid.removeWidget(field)
        for index, field in enumerate(self._fields):
            self._grid.addWidget(field, index // columns, index % columns)
        for column in range(count):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)


class Disclosure(QWidget):
    """A header that shows or hides what is under it, hidden to begin with."""

    def __init__(self, title: str, blurb: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(10)
        self.toggle = button(title, "ghost", icon="chevron-right")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self.set_expanded)
        header.addWidget(self.toggle)
        if blurb:
            header.addWidget(label(blurb, "Dim"), 1)
        else:
            header.addStretch(1)
        layout.addLayout(header)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(16)
        self.body.hide()
        layout.addWidget(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body_layout.addWidget(widget)
        return widget

    @property
    def expanded(self) -> bool:
        return self.body.isVisibleTo(self)

    def set_expanded(self, expanded: bool) -> None:
        if self.toggle.isChecked() != expanded:
            self.toggle.setChecked(expanded)     # comes back here
            return
        name = "chevron-down" if expanded else "chevron-right"
        theme.themed(self.toggle, lambda: self.toggle.setIcon(icons.icon(name)), "icon")
        self.body.setVisible(expanded)


class GlowArea(QWidget):
    """Where the pages sit: the scheme's second colour glows faintly from the
    top right and its accent from the bottom left, over the page's ground."""

    def paintEvent(self, _event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        reach = max(rect.width(), rect.height()) * 0.7
        for centre, colour, alpha in ((rect.topRight(), theme.SECOND, 0.08),
                                      (rect.bottomLeft(), theme.ACCENT, 0.06)):
            glow = QRadialGradient(centre, reach)
            inner = QColor(colour)
            inner.setAlphaF(alpha)
            outer = QColor(colour)
            outer.setAlphaF(0)
            glow.setColorAt(0, inner)
            glow.setColorAt(1, outer)
            p.fillRect(rect, QBrush(glow))


class Meter(QWidget):
    """A thin bar filled to a fraction: from `colour` to `second`, tokens of the
    scheme in use ("ACCENT") or colours of their own."""

    def __init__(self, colour: str = "ACCENT", second: str = "SECOND", parent=None):
        super().__init__(parent)
        self.colour = colour
        self.second = second
        self.fraction = 0.0
        self.setFixedHeight(8)

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(bar, 4, 4)
        p.setClipPath(path)
        p.fillRect(bar, QColor(theme.CONTROL_BG))
        fill = QLinearGradient(0, 0, bar.width(), 0)
        fill.setColorAt(0, QColor(theme.colour(self.colour)))
        fill.setColorAt(1, QColor(theme.colour(self.second)))
        p.fillRect(QRectF(0, 0, bar.width() * self.fraction, bar.height()), QBrush(fill))


class ChoiceCard(QFrame):
    """One of a few answers to a question, as a card: a title and a sentence.

    Cards joined with `join` behave like radio buttons.
    """

    chosen = Signal()

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.group: list[ChoiceCard] = [self]
        self._checked = False
        self.setObjectName("ChoiceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(4)
        self.title = label(title)
        self.title.setStyleSheet("font-weight: 600; background: transparent;")
        layout.addWidget(self.title)
        self.text = label(text, "Muted", wrap=True)
        self.text.setStyleSheet("background: transparent;")
        layout.addWidget(self.text)
        layout.addStretch(1)      # cards side by side keep their titles level
        self._paint()

    @staticmethod
    def join(*cards: ChoiceCard) -> None:
        for card in cards:
            card.group = list(cards)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        for card in self.group:
            card._checked = checked if card is self else (card._checked and not checked)
            card._paint()

    def _paint(self) -> None:
        theme.style(self, self._sheet)

    def _sheet(self) -> str:
        edge = theme.ACCENT if self._checked else theme.LINE
        ground = theme.ACCENT_SOFT if self._checked else theme.CARD_BG
        return (f"#ChoiceCard {{ background: {ground}; border: 1px solid {edge};"
                f" border-radius: {theme.RADIUS_CONTROL}px; }}"
                f"#ChoiceCard:focus {{ border-color: {theme.SELECT}; }}")

    def choose(self) -> None:
        if not self._checked:
            self.setChecked(True)
            self.chosen.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.choose()
            return
        super().keyPressEvent(event)


class PathField(QWidget):
    """A folder path with a Browse button. `changed` follows the typing;
    `committed` comes once the field is left or a folder is picked."""

    changed = Signal(str)
    committed = Signal(str)

    def __init__(self, value: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(paths.tilde(value) if value else "")
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda _t: self.changed.emit(self.value()))
        self.edit.editingFinished.connect(lambda: self.committed.emit(self.value()))
        browse = button("Browse…", on_click=self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def value(self) -> str:
        return paths.normalize(self.edit.text())

    def set_value(self, value: str) -> None:
        self.edit.setText(paths.tilde(value) if value else "")

    def _browse(self) -> None:
        start = self.value() or paths.normalize("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            self.set_value(chosen)
            self.committed.emit(self.value())


class Banner(QFrame):
    """A transient message, shown as a toast in the bottom-right corner of the
    widget it floats over. It takes no room in any layout, so nothing is kept
    free for it while there is nothing to say. A click dismisses it, after
    doing what the message offered, if it offered something."""

    COLOURS: ClassVar[dict[str, str]] = {
        "info": "TEXT_MUTED", "ok": "OK", "warn": "WARN", "error": "DANGER"}
    MARGIN = 20
    MAX_WIDTH = 440

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("Toast")
        theme.style(self, lambda: f"#Toast {{ background: {theme.CARD_BG}; border: 1px solid "
                                  f"{theme.SEAM}; border-radius: {theme.RADIUS_CONTROL}px; }}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.clear)
        self._on_click = None
        host.installEventFilter(self)
        self.hide()

    def text(self) -> str:
        return self.label.text()

    def show_message(self, text: str, level: str = "info", ms: int = 6000,
                     on_click=None) -> None:
        """Show `text`; `on_click`, if given, runs when the toast is clicked."""
        if not text:
            self.clear()
            return
        self._on_click = on_click
        colour = self.COLOURS.get(level, "TEXT_MUTED")
        theme.style(self.dot, lambda: f"background: {theme.colour(colour)}; border-radius: 4px;")
        self.label.setText(text)
        self._place()
        self.show()
        self.raise_()
        if ms:
            self._timer.start(ms)
        else:
            self._timer.stop()

    def clear(self) -> None:
        self._timer.stop()
        self._on_click = None
        self.label.clear()
        self.hide()

    def mousePressEvent(self, event):
        action = self._on_click
        self.clear()
        if action is not None:
            action()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize \
                and self.isVisible():
            self._place()
        return False

    def _place(self) -> None:
        host = self.parentWidget()
        margins = self.layout().contentsMargins()
        chrome = margins.left() + margins.right() + self.dot.width() + self.layout().spacing()
        natural = self.label.fontMetrics().horizontalAdvance(self.label.text()) + chrome + 2
        width = max(160, min(natural, self.MAX_WIDTH, host.width() - 2 * self.MARGIN))
        height = self.layout().totalHeightForWidth(width)
        self.setFixedSize(width, height)
        self.move(host.width() - width - self.MARGIN, host.height() - height - self.MARGIN)


class TextDialog(QDialog):
    """A dialog of text and buttons, always as tall as its wrapped text needs
    at the width it has.

    Qt sizes a window once, from its layout, then leaves its height alone:
    text that wraps onto more lines than were counted (shown at another
    width, in another font, on another screen) is cut off at the bottom."""

    def event(self, event):
        handled = super().event(event)
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            layout = self.layout()
            if layout is not None and layout.hasHeightForWidth():
                need = layout.totalHeightForWidth(self.width())
                if self.minimumHeight() != need:
                    self.setMinimumHeight(need)      # grows the window if it is shorter
        return handled


class ChoiceDialog(TextDialog):
    """A message with a set of choices; `ask` returns the chosen value or None."""

    def __init__(self, parent, title: str, message: str, detail: str = "",
                 choices: list[tuple[str, str, str]] = (), cancel: str = "Cancel"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.result_value = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(message, "Subheading", wrap=True))
        if detail:
            text = label(detail, "Muted", wrap=True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(text)
        layout.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        if cancel:
            row.addWidget(button(cancel, on_click=self.reject))
        for text, value, kind in choices:
            choice = button(text, kind)
            choice.clicked.connect(lambda _c=False, v=value: self._choose(v))
            row.addWidget(choice)
            if kind == "primary":
                choice.setDefault(True)
        layout.addLayout(row)

    def _choose(self, value: str) -> None:
        self.result_value = value
        self.accept()

    @classmethod
    def ask(cls, parent, title, message, detail="", choices=(), cancel="Cancel"):
        dialog = cls(parent, title, message, detail, list(choices), cancel)
        dialog.exec()
        return dialog.result_value
