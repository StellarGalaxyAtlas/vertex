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


@dataclass(frozen=True)
class Notice:
    """One notification: its kind, a heading, and the detail under it."""

    kind: str
    title: str
    body: str = ""

    @property
    def line(self) -> str:
        """Heading and detail on one line, for the message bar."""
        return f"{self.title}: {self.body}" if self.title and self.body else \
            self.title or self.body


CATEGORIES = (
    Category("clips", "Clips", ""),
    Category("sonar", "Sonar", ""),
    Category("vertex", "Vertex", ""),
)

KINDS = (
    Kind("clip_saved", "clips", "Clip saved", "", level="ok",
         icon="replay"),
    Kind("clip_not_saved", "clips", "Clip not saved", "", level="error", icon="replay"),
    Kind("replay_started", "clips", "Replay buffer started",
         "", default=False, icon="replay"),
    Kind("replay_stopped", "clips", "Replay buffer stopped",
         "", default=False,
         icon="replay"),
    Kind("replay_failed", "clips", "Replay buffer crashed", "", level="error", icon="replay"),
    Kind("replay_restarted", "clips", "Replay buffer restarted",
         "After a settings change", default=False,
         level="ok", icon="replay"),
    Kind("track_missing", "clips", "Audio device missing", "", level="warn"),
    Kind("sonar_switched", "sonar", "Sonar turned on or off", "",
         default=False),
    Kind("output_changed", "sonar", "Output device changed", ""),
    Kind("mic_changed", "sonar", "Microphone changed", ""),
    Kind("sonar_problem", "sonar", "Sonar errors", "", level="warn"),
    Kind("in_tray", "vertex", "Still running in the tray",
         "Once per session"),
    Kind("vertex_problem", "vertex", "App errors", "", level="error"),
)

BY_ID = {kind.id: kind for kind in KINDS}


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
