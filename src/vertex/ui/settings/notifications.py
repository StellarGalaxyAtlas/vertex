"""Settings › Notifications: a switch for each kind of notification, grouped by
category. Built from vertex.notifications, so a new kind shows up by itself."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget

from vertex import notifications
from vertex.recorder import notifier
from vertex.ui.widgets import Section, Toggle, button


class NotificationsPage:
    def __init__(self, send_test=None):
        self.switches: dict[str, Toggle] = {}
        pop_ups = Section(
            "Desktop notifications", "Shown when Vertex isn't in front")
        self.over_games = Toggle()
        found = notifier.find() is not None
        self.over_games.setEnabled(found)
        # A sample over whatever is on screen, to see how it looks in a game.
        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.test_button = button("Send a test", on_click=send_test)
        self.test_button.setEnabled(found and self.over_games.isChecked())
        self.over_games.toggled.connect(lambda on: self.test_button.setEnabled(
            on and self.over_games.isEnabled()))
        row.addWidget(self.test_button)
        row.addWidget(self.over_games)
        pop_ups.add_row(
            "Show them over games", controls,
            "Uses GPU Screen Recorder's overlay" if found else
            "Requires gpu-screen-recorder-notification")
        self.sections = [pop_ups]
        for category in notifications.CATEGORIES:
            section = Section(category.name, category.description)
            for kind in notifications.in_category(category.id):
                switch = Toggle()
                section.add_row(kind.name, switch, kind.description)
                self.switches[kind.id] = switch
            self.sections.append(section)

    def load(self, choices: dict[str, bool], over_games: bool) -> None:
        self.over_games.setChecked(over_games)
        for kind, switch in self.switches.items():
            switch.setChecked(notifications.enabled(choices, kind))

    def choices(self) -> dict[str, bool]:
        """What to store: the switches set away from their default."""
        return notifications.changed_choices(
            {kind: switch.isChecked() for kind, switch in self.switches.items()})
