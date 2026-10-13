"""Read audio track titles straight out of an MP4's boxes.

GPU Screen Recorder (and ffmpeg's mp4 muxer generally) stores a stream's
title as a `name` atom in the track's `udta` box. ffprobe only reports that
from FFmpeg 7 on, so on distros still shipping 6.x every track would come back
nameless and the mixer could not tell the game from the mic. Reading the box
ourselves makes track names independent of the installed ffmpeg.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from typing import BinaryIO

_CONTAINERS = {b"moov", b"trak", b"mdia", b"udta"}
_MAX_META = 64 * 1024 * 1024     # a moov bigger than this is not worth reading


def _boxes(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """(type, payload start, payload end) for each box in [start, end)."""
    pos = start
    while pos + 8 <= end:
        handle.seek(pos)
        header = handle.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        payload = pos + 8
        if size == 1:
            large = handle.read(8)
            if len(large) < 8:
                return
            size = struct.unpack(">Q", large)[0]
            payload = pos + 16
        elif size == 0:
            size = end - pos
        if size < payload - pos:
            return                      # corrupt; stop rather than loop
        yield kind, payload, min(pos + size, end)
        pos += size


def _find(handle: BinaryIO, start: int, end: int, kind: bytes) -> tuple[int, int] | None:
    for found, payload, box_end in _boxes(handle, start, end):
        if found == kind:
            return payload, box_end
    return None


def _track_info(handle: BinaryIO, start: int, end: int) -> tuple[bytes, str | None]:
    handler = b""
    name = None
    mdia = _find(handle, start, end, b"mdia")
    if mdia:
        hdlr = _find(handle, *mdia, b"hdlr")
        if hdlr and hdlr[1] - hdlr[0] >= 12:
            handle.seek(hdlr[0] + 8)    # version/flags, pre_defined
            handler = handle.read(4)
    udta = _find(handle, start, end, b"udta")
    if udta:
        box = _find(handle, *udta, b"name")
        if box and 0 < box[1] - box[0] <= 4096:
            handle.seek(box[0])
            text = handle.read(box[1] - box[0]).split(b"\0", 1)[0]
            name = text.decode("utf-8", errors="replace").strip() or None
    return handler, name


def audio_track_names(path: str) -> list[str | None]:
    """Title of each audio track, in stream order; None where a track has none.

    Returns [] for anything that is not a readable MP4.
    """
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            moov = _find(handle, 0, size, b"moov")
            if moov is None or moov[1] - moov[0] > _MAX_META:
                return []
            names = []
            for kind, payload, box_end in _boxes(handle, *moov):
                if kind == b"trak":
                    handler, name = _track_info(handle, payload, box_end)
                    if handler == b"soun":
                        names.append(name)
            return names
    except (OSError, struct.error):
        return []
