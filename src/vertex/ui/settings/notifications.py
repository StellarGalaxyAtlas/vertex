"""Settings › Notifications: a switch for each kind of notification, grouped by
category. Built from vertex.notifications, so a new kind shows up by itself."""

from __future__ import annotations

from vertex import notifications
from vertex.recorder import backend, notifier
from vertex.ui import theme
from vertex.ui.widgets import Section, Toggle, button


class NotificationsPage:
    def __init__(self, send_test=None):
        self.switches: dict[str, Toggle] = {}
        pop_ups = Section(
            "Desktop notifications", "Pop-ups while you're in a game or another app")
        self.over_games = Toggle()
        self._over_games_on = False      # the saved choice, kept while it can't be used
        self.over_games_row = pop_ups.add_row("Show them over games", self.over_games, " ")
        # A sample over whatever is on screen, to see how it looks in a game.
        self.test_button = button("Send a test", on_click=send_test)
        self.over_games.toggled.connect(lambda on: self.test_button.setEnabled(
            on and self.over_games.isEnabled()))
        self.test_row = pop_ups.add_row("Test notification", self.test_button,
                                        "Shows one over whatever is on screen")
        self._show_notifier()
        self.sections = [pop_ups]
        for category in notifications.CATEGORIES:
            section = Section(category.name, category.description)
            for kind in notifications.in_category(category.id):
                switch = Toggle()
                section.add_row(kind.name, switch, kind.description)
                self.switches[kind.id] = switch
            self.sections.append(section)

    def _show_notifier(self) -> bool:
        """Grey the switch out while GSR's notifier isn't installed. Looked for
        each time Settings opens, so installing it needs no restart."""
        # GSR's notifier is Linux's; Windows has no such overlay to use.
        self.over_games_row.setVisible(backend.has_notifier())
        self.test_row.setVisible(backend.has_notifier())
        found = backend.has_notifier() and notifier.find() is not None
        self.over_games.setEnabled(found)
        self.over_games.setChecked(found and self._over_games_on)
        self.test_button.setEnabled(found and self._over_games_on)
        hint = self.over_games_row.hint
        if found:
            hint.setText("Uses GPU Screen Recorder's overlay")
            theme.style(hint, lambda: "")
        else:
            hint.setText("Needs gpu-screen-recorder-notification, which isn't installed")
            theme.style(hint, lambda: f"color: {theme.WARN};")
        return found

    def over_games_choice(self) -> bool:
        """What to store: the switch, or the saved choice while it is greyed out."""
        if self.over_games.isEnabled():
            self._over_games_on = self.over_games.isChecked()
        return self._over_games_on

    def load(self, choices: dict[str, bool], over_games: bool) -> None:
        self._over_games_on = over_games
        self._show_notifier()
        for kind, switch in self.switches.items():
            switch.setChecked(notifications.enabled(choices, kind))

    def choices(self) -> dict[str, bool]:
        """What to store: the switches set away from their default."""
        return notifications.changed_choices(
            {kind: switch.isChecked() for kind, switch in self.switches.items()})
