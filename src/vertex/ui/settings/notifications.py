"""Settings › Notifications: a switch for each kind of notification, grouped by
category. Built from vertex.notifications, so a new kind shows up by itself."""

from __future__ import annotations

from vertex import notifications
from vertex.ui.widgets import Section, Toggle


class NotificationsPage:
    def __init__(self):
        self.switches: dict[str, Toggle] = {}
        self.sections = [Section(
            "Desktop notifications",
            "Which of these pop up on your desktop while Vertex's window isn't in front. "
            "With the window in front, every one of them shows at the bottom of it "
            "instead.")]
        for category in notifications.CATEGORIES:
            section = Section(category.name, category.description)
            for kind in notifications.in_category(category.id):
                switch = Toggle()
                section.add_row(kind.name, switch, kind.description)
                self.switches[kind.id] = switch
            self.sections.append(section)

    def load(self, choices: dict[str, bool]) -> None:
        for kind, switch in self.switches.items():
            switch.setChecked(notifications.enabled(choices, kind))

    def choices(self) -> dict[str, bool]:
        """What to store: the switches set away from their default."""
        return notifications.changed_choices(
            {kind: switch.isChecked() for kind, switch in self.switches.items()})
