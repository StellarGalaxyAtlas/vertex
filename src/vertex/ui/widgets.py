"""Small widgets used across the app."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
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
        colour = "#ffffff" if kind == "primary" else (theme.DANGER if kind == "danger"
                                                      else theme.TEXT)
        widget.setIcon(icons.icon(icon, colour))
    if on_click is not None:
        widget.clicked.connect(on_click)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class IconButton(QToolButton):
    def __init__(self, icon_name: str, tooltip: str = "", size: int = 18,
                 colour: str = theme.TEXT, parent=None, kind: str = "ghost"):
        super().__init__(parent)
        self._size = size
        self.setProperty("kind", kind)
        self.set_icon(icon_name, colour)
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)

    def set_icon(self, icon_name: str, colour: str = theme.TEXT) -> None:
        self.setIcon(icons.icon(icon_name, colour, self._size))


def hline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.LINE};")
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
        track = QColor(theme.ACCENT) if self.isChecked() else QColor(theme.CONTROL_BG)
        if not self.isEnabled():
            track = QColor(theme.SECTION_BG)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 11, 11)
        knob = 16
        x = 3 + self._offset * (self.width() - knob - 6)
        p.setBrush(QColor("#ffffff" if self.isEnabled() else theme.TEXT_DIM))
        p.drawEllipse(QRectF(x, 3, knob, knob))

    def sizeHint(self):
        return QSize(40, 22)


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
        self.setStyleSheet(f"""
            #Segmented {{ background: {theme.FIELD_BG}; border-radius: {theme.RADIUS_CONTROL}px; }}
            #Segmented QPushButton {{ background: transparent; padding: 5px 12px;
                                      border-radius: 7px; color: {theme.TEXT_MUTED}; }}
            #Segmented QPushButton:hover {{ color: {theme.TEXT}; }}
            #Segmented QPushButton:checked {{ background: {theme.CARD_BG}; color: {theme.TEXT}; }}
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
    """The disk the clips are on: clips, everything else, free."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stats = None
        self.setMinimumHeight(54)

    def set_stats(self, stats) -> None:
        self.stats = stats
        if stats is not None:
            self.setToolTip(f"Clips {stats.clips_human} · other {stats.other_human} · "
                            f"free {stats.free_human} of {stats.total_human}")
        self.update()

    def paintEvent(self, _event):
        if self.stats is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        bar = QRectF(0, 22, width, 8)
        path = QPainterPath()
        path.addRoundedRect(bar, 4, 4)
        p.setClipPath(path)
        p.fillRect(bar, QColor(theme.GAUGE_FREE))
        x = 0.0
        for value, colour in ((self.stats.clips_bytes, theme.GAUGE_CLIPS),
                              (self.stats.other_used, theme.GAUGE_OTHER)):
            span = width * self.stats.fraction(value)
            p.fillRect(QRectF(x, bar.top(), span, bar.height()), QColor(colour))
            x += span
        p.setClipping(False)
        p.setPen(QColor(theme.TEXT_MUTED))
        p.setFont(theme.font(8.5))
        p.drawText(QRect(0, 0, width, 18), Qt.AlignmentFlag.AlignLeft,
                   f"Clips {self.stats.clips_human}")
        p.drawText(QRect(0, 0, width, 18), Qt.AlignmentFlag.AlignRight,
                   f"{self.stats.free_human} free")
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRect(0, 34, width, 18), Qt.AlignmentFlag.AlignLeft,
                   f"of {self.stats.total_human}")


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

    def __init__(self, title: str, blurb: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 20)
        outer.setSpacing(12)
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
        if isinstance(widget, (QComboBox, QAbstractSpinBox, QLineEdit)):
            widget.setMinimumWidth(max(widget.minimumWidth(), CONTROL_WIDTH))
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title))
        if hint:
            text.addWidget(label(hint, "Dim", wrap=True))
        layout.addLayout(text, 1)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(row)
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
        self.toggle.setIcon(icons.icon("chevron-down" if expanded else "chevron-right",
                                       theme.TEXT))
        self.body.setVisible(expanded)


class Meter(QWidget):
    """A thin bar filled to a fraction, in one colour."""

    def __init__(self, colour: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self.colour = colour
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
        p.fillRect(QRectF(0, 0, bar.width() * self.fraction, bar.height()),
                   QColor(self.colour))


class PathField(QWidget):
    """A folder path with a Browse button."""

    changed = Signal(str)

    def __init__(self, value: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(paths.tilde(value) if value else "")
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(lambda _t: self.changed.emit(self.value()))
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


class Banner(QLabel):
    """A transient one-line status message."""

    COLOURS: ClassVar[dict[str, str]] = {
        "info": theme.TEXT_MUTED, "ok": theme.OK, "warn": theme.WARN, "error": theme.DANGER}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.clear)

    def show_message(self, text: str, level: str = "info", ms: int = 6000) -> None:
        self.setStyleSheet(f"color: {self.COLOURS.get(level, theme.TEXT_MUTED)};")
        self.setText(text)
        if ms:
            self._timer.start(ms)


class ChoiceDialog(QDialog):
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
