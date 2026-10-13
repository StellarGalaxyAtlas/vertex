"""Filter graphs that sum a clip's audio tracks at the user's gains.

The same mix is expressed twice: for mpv, where it plays live and is swapped
in whole whenever a slider moves, and for ffmpeg, where it is baked into an
export. Both sum without normalising, so a track at 100% sounds the same in
the editor as in the exported file.
"""

from __future__ import annotations

from collections.abc import Sequence

from vertex.media.probe import AudioTrack


def mpv_graph(tracks: Sequence[AudioTrack]) -> str | None:
    """lavfi-complex for mpv summing every track at its gain (None: no audio).

    Muted tracks stay in the graph at gain 0 rather than being dropped, so
    muting does not change the graph's shape and playback never stutters.
    """
    if not tracks:
        return None
    if len(tracks) == 1:
        return f"[aid{tracks[0].index + 1}]volume={tracks[0].gain}[ao]"
    nodes = "".join(f"[aid{t.index + 1}]volume={t.gain}[a{i}];" for i, t in enumerate(tracks))
    joined = "".join(f"[a{i}]" for i in range(len(tracks)))
    return f"{nodes}{joined}amix=inputs={len(tracks)}:normalize=0[ao]"


def ffmpeg_graph(tracks: Sequence[AudioTrack], label: str = "ao") -> str | None:
    """filter_complex fragment mixing the audible tracks (None: nothing audible)."""
    live = [t for t in tracks if t.audible]
    if not live:
        return None
    if len(live) == 1:
        return f"[0:a:{live[0].index}]volume={live[0].gain}[{label}]"
    nodes = "".join(f"[0:a:{t.index}]volume={t.gain}[m{i}];" for i, t in enumerate(live))
    joined = "".join(f"[m{i}]" for i in range(len(live)))
    return f"{nodes}{joined}amix=inputs={len(live)}:normalize=0[{label}]"
