"""Settings › Notifications: pop-ups over games, the sounds, and a switch for
each kind of notification, grouped by category. Built from vertex.notifications
and vertex.sounds, so a new kind or sound shows up by itself."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSlider, QWidget

from vertex import notifications, platform, sounds
from vertex.recorder import backend, notifier
from vertex.ui import theme
from vertex.ui.widgets import IconButton, Section, Toggle, button, label


class NotificationsPage:
    def __init__(self, send_test=None, play=None, changed=None):
        """`send_test()` shows a sample over games, `play(path, volume)` plays a
        sound, `changed()` is told when a sound file or the volume changes."""
        self._play = play or (lambda _path, _volume: None)
        self._changed = changed or (lambda: None)
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
        self.sounds_section = self._build_sounds()
        self.sections = [pop_ups, self.sounds_section]
        for category in notifications.CATEGORIES:
            section = Section(category.name, category.description)
            for kind in notifications.in_category(category.id):
                switch = Toggle()
                section.add_row(kind.name, switch, kind.description)
                self.switches[kind.id] = switch
            self.sections.append(section)

    # --- Sounds -------------------------------------------------------------------

    def _build_sounds(self) -> Section:
        section = Section("Sounds", "Played even while you're in a game")
        self.sound_files: dict[str, str] = {}
        self.sound_switches: dict[str, Toggle] = {}
        self.sound_rows: dict[str, QWidget] = {}
        self.sound_resets: dict[str, IconButton] = {}

        volume = QWidget()
        line = QHBoxLayout(volume)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(10)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(*sounds.VOLUME_RANGE)
        self.volume.setFixedWidth(160)
        # Not the accent: that never sits on an audio control.
        theme.style(self.volume, lambda: f"QSlider::sub-page:horizontal {{ background: "
                                         f"{theme.TEXT_MUTED}; border-radius: 2px; }}")
        self.volume_readout = label("", "Muted")
        self.volume_readout.setFixedWidth(40)
        self.volume_readout.setAlignment(Qt.AlignmentFlag.AlignRight |
                                         Qt.AlignmentFlag.AlignVCenter)
        self.volume.valueChanged.connect(
            lambda value: self.volume_readout.setText(f"{value}%"))
        # Let go: a sample at the new volume, and it is kept.
        self.volume.sliderReleased.connect(self._volume_set)
        line.addWidget(self.volume)
        line.addWidget(self.volume_readout)
        section.add_row("Volume", volume)

        for sound in sounds.SOUNDS:
            controls = QWidget()
            line = QHBoxLayout(controls)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(6)
            reset = IconButton("reset", "Back to Vertex's sound", 16, "TEXT_MUTED")
            reset.clicked.connect(lambda _c=False, k=sound.kind: self._set_file(k, ""))
            line.addWidget(reset)
            play = IconButton("play", "Play it", 16, "TEXT_MUTED")
            play.clicked.connect(lambda _c=False, k=sound.kind: self.play(k))
            line.addWidget(play)
            line.addWidget(button("Choose…", on_click=lambda _c=False, k=sound.kind:
                                  self._choose(k)))
            switch = Toggle()
            line.addSpacing(6)
            line.addWidget(switch)
            self.sound_resets[sound.kind] = reset
            self.sound_switches[sound.kind] = switch
            self.sound_rows[sound.kind] = section.add_row(sound.name, controls, " ")
            self._show_file(sound.kind)
        return section

    def play(self, kind: str) -> None:
        """Play `kind`'s sound as chosen here, saved or not."""
        self._play(sounds.file_for(self.sound_files, kind), self.volume.value())

    def _volume_set(self) -> None:
        self._changed()
        self.play("clip_saved")

    def _choose(self, kind: str) -> None:
        current = self.sound_files.get(kind, "")
        patterns = " ".join(f"*.{extension}" for extension in sounds.EXTENSIONS)
        path, _filter = QFileDialog.getOpenFileName(
            self.sounds_section, f"Sound for “{sounds.BY_KIND[kind].name}”",
            os.path.dirname(current) if current else os.path.expanduser("~"),
            f"Sounds ({patterns});;All files (*)")
        if path:
            self._set_file(kind, path)
            self.play(kind)

    def _set_file(self, kind: str, path: str) -> None:
        if path:
            self.sound_files[kind] = path
        else:
            self.sound_files.pop(kind, None)
        self._show_file(kind)
        self._changed()

    def _show_file(self, kind: str) -> None:
        """Under the sound's name: whose sound plays."""
        path = self.sound_files.get(kind, "")
        hint = self.sound_rows[kind].hint
        self.sound_resets[kind].setVisible(bool(path))
        hint.setToolTip(path)
        if not path:
            hint.setText("Vertex's sound")
            theme.style(hint, lambda: "")
        elif os.path.isfile(path):
            hint.setText(os.path.basename(path))
            theme.style(hint, lambda: "")
        else:
            hint.setText(f"{os.path.basename(path)} is gone: plays Vertex's")
            theme.style(hint, lambda: f"color: {theme.WARN};")

    def load_sounds(self, choices: dict[str, bool], files: dict[str, str], volume: int) -> None:
        self.sound_files = dict(files)
        self.volume.setValue(volume)
        self.volume_readout.setText(f"{volume}%")
        for kind, switch in self.sound_switches.items():
            switch.setChecked(sounds.enabled(choices, kind))
            self._show_file(kind)

    def sound_choices(self) -> dict[str, bool]:
        """What to store: the switches set away from their default."""
        return sounds.changed_choices(
            {kind: switch.isChecked() for kind, switch in self.sound_switches.items()})

    # --- Pop-ups ------------------------------------------------------------------

    def _show_notifier(self) -> bool:
        """Grey the switch out while GSR's notifier isn't installed. Looked for
        each time Settings opens, so installing it needs no restart. Vertex's
        own toast, where there is one, is always there."""
        shown = platform.GAME_TOAST or backend.has_notifier()
        self.over_games_row.setVisible(shown)
        self.test_row.setVisible(shown)
        found = platform.GAME_TOAST or (backend.has_notifier() and notifier.find() is not None)
        self.over_games.setEnabled(found)
        self.over_games.setChecked(found and self._over_games_on)
        self.test_button.setEnabled(found and self._over_games_on)
        hint = self.over_games_row.hint
        if platform.GAME_TOAST:
            hint.setText("Over windowed and most full-screen games")
            theme.style(hint, lambda: "")
        elif found:
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
