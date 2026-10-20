"""The parts a clip's audio is recorded in: game, chat, media and mic.

A clip recorded by Vertex titles each of its tracks after the part it holds
("Vertex Game"), so the editor can name its lanes exactly whatever the
devices were called. This module is pure data, so the config, the recorder
and the track labeller can all share it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    id: str
    label: str

    @property
    def track_title(self) -> str:
        """The audio track title written into clips: 'Vertex Game'."""
        return f"Vertex {self.label}"


GAME = Role("game", "Game")
CHAT = Role("chat", "Chat")
MEDIA = Role("media", "Media")
MIC = Role("mic", "Mic")

ALL: tuple[Role, ...] = (GAME, CHAT, MEDIA, MIC)
BY_ID: dict[str, Role] = {role.id: role for role in ALL}


def get(role_id: str) -> Role | None:
    return BY_ID.get(role_id)
