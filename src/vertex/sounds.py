"""The sounds Vertex plays when something happens: a clip saved or not, the
replay buffer starting, stopping or crashing.

Each sound belongs to a kind of notification (vertex.notifications) and plays
when a notice of that kind does, whether or not it pops up. Each has its own
switch and can play a file of the user's instead of Vertex's own; only what
differs from the defaults is stored. Played by libmpv, so any audio file mpv
reads will do. No Qt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from importlib import resources

log = logging.getLogger(__name__)

VOLUME_RANGE = (0, 100)
DEFAULT_VOLUME = 70

# What the file picker offers; mpv plays more, picked as "All files".
EXTENSIONS = ("wav", "mp3", "ogg", "oga", "opus", "flac", "m4a", "aac")


@dataclass(frozen=True)
class Sound:
    kind: str            # the notification kind it plays for
    name: str            # as Settings calls it
    file: str            # Vertex's own, in assets/sounds
    default: bool = True  # plays unless switched off


SOUNDS = (
    Sound("clip_saved", "Clip saved", "clip-saved.wav"),
    Sound("clip_not_saved", "Clip not saved", "clip-not-saved.wav"),
    Sound("replay_started", "Replay buffer started", "replay-started.wav", default=False),
    Sound("replay_stopped", "Replay buffer stopped", "replay-stopped.wav", default=False),
    Sound("replay_failed", "Replay buffer crashed", "replay-stopped.wav"),
)

BY_KIND = {sound.kind: sound for sound in SOUNDS}


def own_file(kind: str) -> str:
    """The path of Vertex's own sound for `kind`."""
    return str(resources.files("vertex") / "assets" / "sounds" / BY_KIND[kind].file)


def enabled(choices: dict[str, bool], kind: str) -> bool:
    """Whether `kind` plays a sound, given the switches stored (those changed
    from their default). Kinds without a sound never do."""
    sound = BY_KIND.get(kind)
    return sound is not None and choices.get(kind, sound.default)


def changed_choices(switches: dict[str, bool]) -> dict[str, bool]:
    """The switches that differ from their sound's default: what is stored."""
    return {kind: on for kind, on in switches.items()
            if kind in BY_KIND and isinstance(on, bool) and on != BY_KIND[kind].default}


def own_files(files: dict[str, str]) -> dict[str, str]:
    """The user's files by kind, as stored: known kinds, non-empty paths."""
    return {kind: path for kind, path in files.items()
            if kind in BY_KIND and isinstance(path, str) and path.strip()}


def file_for(files: dict[str, str], kind: str) -> str:
    """What `kind` plays: the user's file while it is there, else Vertex's own."""
    chosen = files.get(kind, "")
    if chosen and os.path.isfile(chosen):
        return chosen
    if chosen:
        log.warning("Sound file %s isn't there; playing Vertex's own", chosen)
    return own_file(kind)


def _new_player():
    import mpv  # libmpv: loaded only once a sound plays

    return mpv.MPV(video=False, ytdl=False, terminal=False, input_default_bindings=False,
                   input_vo_keyboard=False, osc=False, idle=True,
                   audio_client_name="Vertex")


class Player:
    """Plays one sound at a time; a new one cuts the last short. Blocking the
    first time (libmpv starts its audio output), so call it from a worker."""

    def __init__(self):
        self._player = None

    def play(self, path: str, volume: int, sink: str = "") -> None:
        """Play `path` at `volume` percent, on the audio server's device named
        `sink` when there is one by that name, else on the default output."""
        if self._player is None:
            self._player = _new_player()
        player = self._player
        player.audio_device = device_for(player, sink)
        player.volume = min(max(volume, VOLUME_RANGE[0]), VOLUME_RANGE[1])
        player.play(path)

    def close(self) -> None:
        player, self._player = self._player, None
        if player is not None:
            player.terminate()


def device_for(player, sink: str) -> str:
    """mpv's name for the output device `sink` ("pulse/<sink>", "pipewire/<sink>"),
    or "auto" (the default output) when there is no sink or mpv doesn't list it."""
    if not sink:
        return "auto"
    try:
        listed = player.audio_device_list or []
    except Exception:  # an mpv that can't list them: play on the default
        return "auto"
    for device in listed:
        name = device.get("name", "")
        if name.partition("/")[2] == sink:
            return name
    return "auto"
