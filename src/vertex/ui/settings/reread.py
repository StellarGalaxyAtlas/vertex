"""Clips whose names say another game (or date) than Vertex has: one line
under the apps Vertex reads names with, and a window that asks about each
game in turn."""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from vertex import fmt
from vertex.core.importing import RereadGroup
from vertex.ui import theme
from vertex.ui.widgets import TextDialog, button, label

FILES_SHOWN = 10         # clips listed under a question, then "…N more"
SCROLL_HEIGHT = 460      # the questions' height before they scroll


def _when(timestamp: float) -> str:
    return f"{fmt.date(timestamp)}, {time.strftime('%H:%M', time.localtime(timestamp))}"


def summary(groups: list[RereadGroup]) -> str:
    """The line Settings shows: how many clips' names disagree with Vertex."""
    games = sum(len(group.changes) for group in groups if group.game)
    dates = sum(len(group.changes) for group in groups if not group.game)
    if games:
        text = f"{games} clips' names say another game than their tag" if games > 1 else \
            "1 clip's name says another game than its tag"
        return text + (f", {fmt.plural(dates, 'clip')} another date" if dates else "")
    if dates:
        return f"{dates} clips' names give another recording date" if dates > 1 else \
            "1 clip's name gives another recording date"
    return ""


class RereadLine(QFrame):
    """How many clips disagree with their names, and Review…; hidden when
    none do."""

    review = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RereadLine")
        theme.style(self, lambda: (f"#RereadLine {{ background: {theme.CARD_BG}; "
                                   f"border-radius: {theme.RADIUS_SMALL}px; }}"))
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 8, 8)
        row.setSpacing(12)
        self.text = label("", wrap=True)
        row.addWidget(self.text, 1)
        self.button = button("Review…", on_click=self.review.emit)
        row.addWidget(self.button)
        self.groups: list[RereadGroup] = []
        self.set_groups([])

    def set_groups(self, groups: list[RereadGroup]) -> None:
        self.groups = groups
        self.text.setText(summary(groups))
        self.setVisible(bool(groups))


def _question(group: RereadGroup) -> tuple[str, str, str]:
    """What a card asks about `group`, and its two buttons."""
    many = len(group.changes) > 1
    count = f"<b>{fmt.plural(len(group.changes), 'clip')}</b>"
    names = "their names say" if many else "its name says"
    game, was = html.escape(group.game), html.escape(group.game_was)
    them = "them" if many else "it"
    if not group.game:
        text = (f"{count} {'have names that give' if many else 'has a name that gives'} "
                f"another recording date than Vertex has.")
        return text, "Use the dates", "Keep the dates"
    if group.game_was:
        text = f"{count} {'are' if many else 'is'} tagged <b>{was}</b>, and {names} <b>{game}</b>."
        return text, f"Tag {them} {group.game}", f"Keep {group.game_was}"
    text = f"{count} {'have' if many else 'has'} no game, and {names} <b>{game}</b>."
    return text, f"Tag {them} {group.game}", f"Leave {them}"


class _Card(QFrame):
    """One question: a group of clips, what to do with them, and the clips."""

    def __init__(self, group: RereadGroup, on_use, on_keep, parent=None):
        super().__init__(parent)
        self.group = group
        self.setObjectName("RereadCard")
        theme.style(self, lambda: (f"#RereadCard {{ background: {theme.CARD_BG}; "
                                   f"border-radius: {theme.RADIUS_SMALL}px; }}"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        text, use, keep = _question(group)
        self.text = label(text, wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.text)
        if group.game and group.dates:
            layout.addWidget(label("Their recording dates come from the names too."
                                   if len(group.changes) > 1 else
                                   "Its recording date comes from the name too.", "Dim"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.use = button(use, "primary", on_click=lambda: on_use(self))
        self.keep = button(keep, on_click=lambda: on_keep(self))
        row.addWidget(self.use)
        row.addWidget(self.keep)
        row.addStretch(1)
        self.opener = button("Show clips", "ghost", on_click=self._open)
        row.addWidget(self.opener)
        layout.addLayout(row)
        shown = [f"{c.filename} · {_when(c.when)}" if c.when else c.filename
                 for c in group.changes[:FILES_SHOWN]]
        if len(group.changes) > FILES_SHOWN:
            shown.append(f"…{len(group.changes) - FILES_SHOWN} more")
        self.files = label("\n".join(shown), "Muted", wrap=True)
        self.files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.files.hide()
        layout.addWidget(self.files)
        self.files_toggled = lambda: None

    def _open(self) -> None:
        opened = self.files.isHidden()
        self.files.setVisible(opened)
        self.opener.setText("Hide clips" if opened else "Show clips")
        self.files_toggled()


class RereadDialog(TextDialog):
    """A question per group; each answer is acted on at once. `use` carries
    the games and the dates to write, by file name; `keep` the group whose
    tag the user keeps."""

    use = Signal(dict, dict)
    keep = Signal(object)

    def __init__(self, parent, groups: list[RereadGroup]):
        super().__init__(parent)
        self.setWindowTitle("Tags from file names")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(label("Tags from file names", "Subheading"))
        self.hint = label("Pick what each group of clips is tagged. Keeping a tag "
                          "is remembered.", "Muted", wrap=True)
        layout.addWidget(self.hint)
        host = QWidget()
        self.rows = QVBoxLayout(host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.cards = [_Card(group, self._use, self._keep) for group in groups]
        for card in self.cards:
            self.rows.addWidget(card)
            card.files_toggled = lambda: QTimer.singleShot(0, self._fit)
        self.scroll = QScrollArea()
        self.scroll.setWidget(host)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget "
                                  "{ background: transparent; }")
        layout.addWidget(self.scroll, 1)
        self._fit()
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.done_button = button("Done", on_click=self.accept)
        footer.addWidget(self.done_button)
        layout.addLayout(footer)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()          # the questions wrap differently at another width

    def _fit(self) -> None:
        """As tall as the questions, up to SCROLL_HEIGHT; past that, they scroll."""
        rows = self.scroll.widget().layout()
        rows.activate()
        width = max(self.scroll.viewport().width(), self.minimumWidth() - 48)
        need = rows.totalHeightForWidth(width) if rows.hasHeightForWidth() else \
            rows.sizeHint().height()
        self.scroll.setFixedHeight(min(need, SCROLL_HEIGHT))

    def _answered(self, card: _Card) -> None:
        self.cards.remove(card)
        card.hide()
        self._fit()
        if not self.cards:
            self.hint.setText("Every clip's tag now matches its name, or you kept it.")

    def _use(self, card: _Card) -> None:
        games, dates = {}, {}
        for change in card.group.changes:
            if change.game:
                games[change.filename] = change.game
            if change.when:
                dates[change.filename] = change.when
        self.use.emit(games, dates)
        self._answered(card)

    def _keep(self, card: _Card) -> None:
        self.keep.emit(card.group)
        self._answered(card)
