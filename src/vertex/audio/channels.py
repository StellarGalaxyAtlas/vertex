"""The Sonar channels: the fixed set of virtual devices Vertex manages.

Every channel becomes one PipeWire node with a stable name, so a clip recorded
through Vertex always carries the same tracks, named the same way, however the
machine's real hardware is called:

    vertex_game   "Vertex Game"    virtual output (sink)  → recorded from its monitor
    vertex_chat   "Vertex Chat"    virtual output (sink)
    vertex_media  "Vertex Media"   virtual output (sink)
    vertex_aux    "Vertex Aux"     virtual output (sink)
    vertex_mic    "Vertex Mic"     virtual input (source) → recorded directly

This module is pure data, so the config, the recorder, the track labeller and
the UI can all share it without importing anything that talks to PipeWire.
"""

from __future__ import annotations

from dataclasses import dataclass

NODE_PREFIX = "vertex_"


@dataclass(frozen=True)
class Channel:
    id: str
    label: str
    kind: str          # "output" (a virtual sink) or "input" (a virtual source)
    icon: str          # freedesktop icon name, for the system mixer and our UI
    blurb: str

    @property
    def node(self) -> str:
        """PipeWire node name, e.g. 'vertex_game'."""
        return f"{NODE_PREFIX}{self.id}"

    @property
    def description(self) -> str:
        """What sound settings and other apps show, e.g. 'Vertex Game'."""
        return f"Vertex {self.label}"

    @property
    def is_output(self) -> bool:
        return self.kind == "output"

    @property
    def record_source(self) -> str:
        """The capture device a recorder reads this channel from."""
        return f"{self.node}.monitor" if self.is_output else self.node

    @property
    def track_title(self) -> str:
        """The audio track title written into clips: 'Vertex Game'."""
        return self.description


GAME = Channel("game", "Game", "output", "input-gaming",
               "Games. The default for anything not routed elsewhere.")
CHAT = Channel("chat", "Chat", "output", "internet-group-chat",
               "Voice chat — Discord, TeamSpeak, Mumble.")
MEDIA = Channel("media", "Media", "output", "audio-x-generic",
                "Music and video — Spotify, the browser.")
AUX = Channel("aux", "Aux", "output", "audio-card",
              "Anything you want kept apart from the rest.")
MIC = Channel("mic", "Mic", "input", "audio-input-microphone",
              "Your microphone, as one device every chat app can pick.")

OUTPUTS: tuple[Channel, ...] = (GAME, CHAT, MEDIA, AUX)
ALL: tuple[Channel, ...] = (*OUTPUTS, MIC)
BY_ID: dict[str, Channel] = {channel.id: channel for channel in ALL}
BY_NODE: dict[str, Channel] = {channel.node: channel for channel in ALL}


def get(channel_id: str) -> Channel | None:
    return BY_ID.get(channel_id)
