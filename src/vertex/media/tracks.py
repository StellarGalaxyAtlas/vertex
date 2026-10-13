"""Naming a clip's audio tracks: which one is the game, the chat, the mic…

Clips recorded through Vertex's Sonar devices are recognised exactly: their
tracks are titled after the channel they came from ("Vertex Game", or GPU
Screen Recorder's own "Devices: Monitor of Vertex Game"), whatever the
hardware is called.

Other clips go by how their devices happen to be named. All or nothing: a
half-recognised mixer reads like a bug, so unless every track maps to a
distinct source they all get numbered.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from vertex.audio import channels
from vertex.media.probe import AudioTrack

DESKTOP = "desktop"   # a recorder's mixed-down output: game and chat in one track

LABELS = {
    channels.GAME.id: "Game",
    DESKTOP: "Desktop",
    channels.CHAT.id: "Chat",
    channels.MEDIA.id: "Media",
    channels.AUX.id: "Aux",
    channels.MIC.id: "Microphone",
}
# The order lanes appear in, whatever order the streams have in the file.
ORDER = (channels.GAME.id, DESKTOP, channels.CHAT.id, channels.MEDIA.id,
         channels.AUX.id, channels.MIC.id)

# Recorders name the field as well as the device — "device:Virtual_Game_Sink",
# "Devices: Monitor of Game Audio".
DEVICE_PREFIX = re.compile(r"^devices?\s*:\s*", re.IGNORECASE)
MONITOR_PREFIX = re.compile(r"^monitor of\s+", re.IGNORECASE)
VERTEX_DEVICE = re.compile(
    rf"^vertex[ _-]?(?P<channel>"
    rf"{'|'.join(c.id for c in (*channels.ALL, *channels.RETIRED))})(?:\.monitor)?$",
    re.IGNORECASE,
)

def track_devices(name: str) -> list[str]:
    """The capture devices a track's title names, one entry per device.

    A recorder capturing several devices into one stream joins them: older
    GPU Screen Recorder builds with '|', current ones as 'Devices: a, b'.
    """
    parts = name.split("|")
    if len(parts) == 1 and DEVICE_PREFIX.match(name):
        parts = DEVICE_PREFIX.sub("", name).split(", ")
    devices = (DEVICE_PREFIX.sub("", part).strip() for part in parts)
    return [device for device in devices if device]


def vertex_channel(device: str) -> str | None:
    """The Sonar channel a device is, if it is one of Vertex's own."""
    match = VERTEX_DEVICE.match(MONITOR_PREFIX.sub("", device.strip()))
    return match.group("channel").lower() if match else None


def guess_source(device: str) -> str | None:
    """Which lane a device's name looks like it belongs to, or None."""
    lowered = device.lower()
    if "game" in lowered:
        return channels.GAME.id
    if "chat" in lowered or "voice" in lowered:
        return channels.CHAT.id
    if "media" in lowered or "music" in lowered:
        return channels.MEDIA.id
    if re.search(r"\baux\b", lowered):
        return channels.AUX.id
    if "mic" in lowered:
        return channels.MIC.id
    # "Audio 1" is a placeholder for a track with no name at all.
    if re.fullmatch(r"audio \d+", lowered):
        return None
    # Loopbacks are "Monitor of …"; anything else is a real capture device —
    # the microphone, whatever it is called.
    if "monitor of" not in lowered and not lowered.endswith(".monitor"):
        return channels.MIC.id
    return None


def _is_microphone(device: str) -> bool:
    return vertex_channel(device) == channels.MIC.id or "mic" in device.lower()


def match_source(name: str) -> str | None:
    """Which lane a track's title refers to, or None if it can't be told."""
    devices = track_devices(name) or [name]
    if len(devices) > 1:
        # Several outputs mixed down are "Desktop" — true whichever they are.
        # With the mic in the mix there is no honest single label.
        if any(_is_microphone(device) for device in devices):
            return None
        return DESKTOP
    device = devices[0]
    own = vertex_channel(device)
    if own is not None:
        return own
    return guess_source(device)


def label_tracks(tracks: Sequence[AudioTrack]) -> list[AudioTrack]:
    """Label every track and return them in the order the mixer shows them."""
    by_file = sorted(tracks, key=lambda track: track.index)
    matches = [match_source(track.name) if track.has_name else None
               for track in by_file]
    if None in matches or len(set(matches)) != len(matches):
        for position, track in enumerate(by_file, start=1):
            track.label, track.channel = f"Audio {position}", ""
        return by_file
    for track, channel_id in zip(by_file, matches, strict=True):
        track.channel = channel_id
        track.label = LABELS[channel_id]
    return sorted(by_file, key=lambda track: ORDER.index(track.channel))
