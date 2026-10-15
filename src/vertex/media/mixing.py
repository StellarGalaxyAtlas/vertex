"""Filter graphs that sum a clip's audio tracks at the user's gains.

The same mix is expressed twice: for mpv, where it plays live, and for
ffmpeg, where it is baked into an export. Both sum without normalising, so a
track at 100% sounds the same in the editor as in the exported file.

mpv gets its mix in two halves. Its lavfi-complex only lines the tracks up
side by side as one many-channel stream: changing that graph makes mpv seek,
which stalls playback, so it is set once and never touched again. The gains
live in an ordinary audio filter after it, whose volumes take commands while
playing — a slider can move without the picture or sound skipping a beat.
"""

from __future__ import annotations

from collections.abc import Sequence

from vertex.media.probe import AudioTrack

MPV_MIX_LABEL = "mix"
_RATE = 48000


def mpv_graph(tracks: Sequence[AudioTrack]) -> str | None:
    """lavfi-complex for mpv putting every track side by side as stereo pairs
    (None: no audio). It holds no gains, so it never has to change."""
    if not tracks:
        return None
    fmt = f"aformat=sample_rates={_RATE}:channel_layouts=stereo"
    if len(tracks) == 1:
        return f"[aid{tracks[0].index + 1}]{fmt}[ao]"
    nodes = "".join(f"[aid{t.index + 1}]{fmt}[s{i}];" for i, t in enumerate(tracks))
    joined = "".join(f"[s{i}]" for i in range(len(tracks)))
    return f"{nodes}{joined}amerge=inputs={len(tracks)}[ao]"


def mpv_mix_filter(tracks: Sequence[AudioTrack]) -> str | None:
    """mpv audio filter summing the pairs mpv_graph lines up, each at its gain.

    Muted tracks stay in at gain 0, so muting is just another gain change.
    """
    if not tracks:
        return None
    count = len(tracks)
    split = f"asplit={count}" + "".join(f"[i{i}]" for i in range(count))
    gains = "".join(
        f"[i{i}]pan=stereo|c0=c{2 * i}|c1=c{2 * i + 1},{mpv_volume_target(i)}"
        f"={t.gain}[t{i}];" for i, t in enumerate(tracks))
    joined = "".join(f"[t{i}]" for i in range(count))
    return f"@{MPV_MIX_LABEL}:lavfi=[{split};{gains}{joined}amix=inputs={count}:normalize=0]"


def mpv_volume_target(position: int) -> str:
    """Name of a track's volume filter within mpv_mix_filter, for af-command."""
    return f"volume@v{position}"


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
