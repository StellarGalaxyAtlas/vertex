"""Every kind of notification Vertex can show, in one list.

Whatever notifies the user names one of these kinds (`Context.notify` in the
UI). The kind decides how it looks and whether it may pop up on the desktop;
the Notifications settings are built from this list. A new kind is one entry
in KINDS and one call where it happens. Hotkeys and the control API will
bring many more, and outside listeners can follow the same stream of notices.
"""

from __future__ import annotations

from dataclasses import dataclass

LEVELS = ("info", "ok", "warn", "error")


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class Kind:
    id: str
    category: str        # a Category id
    name: str            # as the setting is called
    description: str     # when it happens
    default: bool = True  # pops up unless switched off
    level: str = "info"   # one of LEVELS: how it looks
    icon: str = ""        # GSR's notifier icon over games (notifier.ICONS), if any
    in_window: bool = True  # also shown at the bottom of Vertex's window


@dataclass(frozen=True)
class Notice:
    """One notification: its kind, a heading, and the detail under it."""

    kind: str
    title: str
    body: str = ""
    icon: str = ""        # one of Vertex's own icons, drawn for it over games

    @property
    def line(self) -> str:
        """Heading and detail on one line, for the message bar."""
        return f"{self.title}: {self.body}" if self.title and self.body else \
            self.title or self.body


CATEGORIES = (
    Category("clips", "Clips", "Saving clips and the replay buffer."),
    Category("sonar", "Sonar", "Sonar's channels and the devices they use."),
    Category("vertex", "Vertex", "The app itself, and problems it runs into."),
)

KINDS = (
    Kind("clip_saved", "clips", "Clip saved", "Each new clip, with its name.", level="ok",
         icon="replay"),
    Kind("clip_not_saved", "clips", "A clip couldn't be saved",
         "Saving was asked for while the replay buffer wasn't running, or GPU Screen "
         "Recorder couldn't be reached.", level="error", icon="replay"),
    Kind("replay_started", "clips", "Replay buffer started",
         "Also when it starts with Vertex.", default=False, icon="replay"),
    Kind("replay_stopped", "clips", "Replay buffer stopped",
         "When it is stopped from the window, the tray or a command.", default=False,
         icon="replay"),
    Kind("replay_failed", "clips", "Replay buffer stopped unexpectedly",
         "With GPU Screen Recorder's reason.", level="error", icon="replay"),
    Kind("replay_restarted", "clips", "Replay buffer restarted",
         "To use changed settings or tracks. It starts empty again.", default=False,
         level="ok", icon="replay"),
    Kind("track_missing", "clips", "A track's device is missing",
         "Clips record a stand-in, or go without that track, until it is back.",
         level="warn"),
    Kind("sonar_switched", "sonar", "Sonar turned on or off", "From anywhere.",
         default=False),
    Kind("output_changed", "sonar", "Output device changed",
         "Sonar plays through another device: one was picked, plugged in or "
         "unplugged."),
    Kind("mic_changed", "sonar", "Microphone changed",
         "Vertex Mic records another microphone: one was picked, plugged in or "
         "unplugged."),
    Kind("volume_changed", "sonar", "Volume changed",
         "A channel turned up, down, muted or unmuted by a shortcut or your desktop's "
         "volume keys. Pop-up only: Vertex's window shows it on the faders.",
         default=False, in_window=False),
    Kind("sonar_problem", "sonar", "Sonar ran into a problem",
         "No output device or microphone was found, or a change didn't work.",
         level="warn"),
    Kind("in_tray", "vertex", "Still running in the tray",
         "Once per run, when the window is closed and Vertex keeps running."),
    Kind("vertex_problem", "vertex", "Settings, library or folder problems",
         "Settings couldn't be saved, the library couldn't be opened, or a folder "
         "couldn't be created.", level="error"),
)

BY_ID = {kind.id: kind for kind in KINDS}


def volume_notice(label: str, volume: int, muted: bool, mute_changed: bool) -> Notice:
    """A channel's new volume ("Game volume: 55%"), or that it was muted or
    unmuted ("Chat muted")."""
    icon = "mute" if muted else "volume"
    if muted:
        return Notice("volume_changed", f"{label} muted", "", icon)
    if mute_changed:
        return Notice("volume_changed", f"{label} unmuted", f"{volume}%", icon)
    return Notice("volume_changed", f"{label} volume", f"{volume}%", icon)


def in_category(category: str) -> list[Kind]:
    return [kind for kind in KINDS if kind.category == category]


def enabled(choices: dict[str, bool], kind: str) -> bool:
    """Whether `kind` may pop up, given the switches set in Settings (only the
    ones changed from their default are stored)."""
    return choices.get(kind, BY_ID[kind].default)


def changed_choices(switches: dict[str, bool]) -> dict[str, bool]:
    """The switches that differ from their kind's default: what is stored, so a
    kind added later, or a default changed, applies to everyone who left it be."""
    return {kind: on for kind, on in switches.items()
            if kind in BY_ID and on != BY_ID[kind].default}
