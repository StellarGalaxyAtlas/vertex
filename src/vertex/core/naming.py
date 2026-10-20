"""What a clip's file name says: the game it holds and when it was recorded.

Recorders write both into the name, and reading them back is what lets a
library of hundreds of clips sort and group itself without anybody tagging it.
Anything that does not match a known convention comes back empty rather than
guessed at — a wrong tag is worse than no tag.
"""

from __future__ import annotations

import datetime
import os
import re

from vertex.core.name_patterns import NamePattern, Reading

# SteelSeries Moments names a recording "<Game>__<date>__<time>.mp4", writing
# the spaces in a game's name as dashes. The date and time are matched strictly
# so another recorder's naming can never be read as a game. A trim keeps the
# name and adds a suffix — "_trim" from Moments, " (trimmed)" from Vertex.
MOMENTS_FILENAME = re.compile(
    r"^(?P<game>.+?)__\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}"
    r"(?:_\w+|[ ]\(trimmed(?:[ ]\d+)?\))?$"
)

# What a capture that isn't a game gets tagged as.
DESKTOP_TAG = "Desktop"

# Recorder names for a capture that is not a game.
CAPTURE_NAMES = {"desktopcapture": DESKTOP_TAG}

# Recorders take the game's registered title, symbols and all ("Overwatch®"),
# which nobody types when tagging by hand.
TRADEMARKS = str.maketrans("", "", "®™©")

# Both recorders stamp the name with when they started recording, differing
# only in how many underscores separate the date from the time:
# GPU Screen Recorder's "Replay_2026-03-28_05-28-25" and Moments'
# "THE-FINALS__2024-06-16__19-45-23".
CLIP_TIMESTAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})_{1,2}(\d{2})-(\d{2})-(\d{2})")


def clean_tag(text: object) -> str:
    """Collapse runs of whitespace and trim the ends. Casing is the user's."""
    return " ".join(str(text).split())


def clean_tags(tags) -> list[str]:
    """Clean a list of tags, dropping blanks and case-insensitive duplicates.

    The first spelling wins, so 'Anna' typed before 'anna' keeps the capital.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags:
        tag = clean_tag(tag)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            cleaned.append(tag)
    return cleaned


def game_key(game: str) -> str:
    """Key on which two spellings of one game count as the same tag.

    Case and punctuation are dropped, so a recorder's "R.E.P.O." lands on a
    hand-typed "R.E.P.O" and "THE FINALS" on "The Finals". Words still have to
    match: "Overwatch 2" stays distinct from "Overwatch".
    """
    return re.sub(r"[^a-z0-9]+", "", game.casefold())


# The patterns the user taught Vertex (Settings › Import and setup), tried
# before the conventions above. Set from the settings by the app.
_taught: list[NamePattern] = []


def use_patterns(patterns) -> None:
    _taught[:] = list(patterns)


def taught_patterns() -> list[NamePattern]:
    return list(_taught)


def _read(name: str, patterns) -> Reading | None:
    for pattern in _taught if patterns is None else patterns:
        reading = pattern.read(name)
        if reading is not None:
            return reading
    return None


# reader_of: a name only the conventions above read (Moments' names, the
# date stamp GPU Screen Recorder and Moments write).
BUILT_IN = -1


def reader_of(name: str, patterns) -> int | None:
    """Which of `patterns` reads `name` first (its index), BUILT_IN when only
    a convention Vertex always knows does, or None when nothing does."""
    for index, pattern in enumerate(patterns):
        if pattern.read(name) is not None:
            return index
    stem = os.path.splitext(name)[0]
    if MOMENTS_FILENAME.match(stem) or CLIP_TIMESTAMP.search(stem):
        return BUILT_IN
    return None


def _tag(game: str) -> str:
    return CAPTURE_NAMES.get(game.casefold()) or clean_tag(game.translate(TRADEMARKS))


def game_from_filename(name: str, patterns=None) -> str:
    """The game a clip's file name says it holds, or "" if the name doesn't say.

    "THE-FINALS__2024-06-16__19-45-23.mp4" → "THE FINALS". GPU Screen
    Recorder's fixed "Replay_…" naming carries no game at all, so those clips
    are left for the library (or the Sonar game channel) to tag instead.
    `patterns` are tried first (by default the ones taught).
    """
    reading = _read(name, patterns)
    if reading is not None and reading.game:
        return _tag(reading.game)
    stem = os.path.splitext(name)[0]
    match = MOMENTS_FILENAME.match(stem)
    if not match:
        return ""
    return _tag(match.group("game").replace("-", " "))


def recorded_at(name: str, patterns=None) -> float:
    """When a clip's file name says it was recorded, or 0.0 if it doesn't say.

    Read as local time, the clock the recorder wrote it by. The parts go
    through `datetime`, so an impossible date can't come back as a timestamp.
    """
    reading = _read(name, patterns)
    if reading is not None and reading.when:
        return reading.when
    match = CLIP_TIMESTAMP.search(os.path.splitext(name)[0])
    if not match:
        return 0.0
    try:
        return datetime.datetime(*(int(part) for part in match.groups())).timestamp()
    except ValueError:
        return 0.0   # the right shape, but no real moment — e.g. month 13


# Wine and Proton report a game's process as its .exe; native games and SDL
# sometimes report a binary name with separators instead of spaces.
_APP_SUFFIXES = re.compile(r"\.(exe|x86_64|x86|bin|sh|appimage)$", re.IGNORECASE)

# Processes that play audio on behalf of a game rather than being one.
_NOT_GAMES = frozenset({
    "steam", "steamwebhelper", "wine", "wine64", "wine-preloader", "wine64-preloader",
    "wineserver", "pressure-vessel-wrap", "reaper", "proton", "gamescope",
    "firefox", "chromium", "chrome", "discord", "spotify", "vesktop", "obs",
    "pipewire", "wireplumber", "pulseaudio", "paplay", "pw-play", "mpv",
})


def game_from_app(name: str) -> str:
    """A tag-worthy game name from an audio stream's application name.

    "Overwatch.exe" → "Overwatch", "Deep_Rock_Galactic" → "Deep Rock Galactic".
    Launchers, runtimes and media apps come back "" — they are what is playing
    the sound, not what was played.
    """
    text = clean_tag(_APP_SUFFIXES.sub("", name.strip()))
    if not text or text.casefold() in _NOT_GAMES:
        return ""
    if " " not in text and ("_" in text or "-" in text):
        text = clean_tag(text.replace("_", " ").replace("-", " "))
    return text.translate(TRADEMARKS).strip()
