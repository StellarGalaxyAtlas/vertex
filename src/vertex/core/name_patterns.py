"""File-name patterns: how a clip app writes the game and the time into a
clip's name, so Vertex can read them back.

A pattern is a template, kept in the settings as text:

    MedalTV{game}{datetime:YYYYMMDDHHmmss}{skip}

Plain text must be in the name as it is; `{game}` is the game, `{skip}` any
text that changes from clip to clip (a counter, milliseconds), `{skip:7}`
exactly that many characters (what tells it apart from a game right beside
it), and
`{date:…}`, `{time:…}`, `{datetime:…}` read when the clip was recorded, in a
format made of YYYY, MM, DD, HH, mm and ss with the separators between them.
A brace in plain text is written twice ({{ or }}).

Presets cover the clip apps whose names Vertex knows; a pattern can also be
made by marking up one of the user's own names (`from_marks`).
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from functools import cached_property

KINDS = ("game", "date", "time", "datetime", "skip")
WHEN_KINDS = ("date", "time", "datetime")

_CODES = {"YYYY": r"(?P<Y>\d{4})", "MM": r"(?P<M>\d{2})", "DD": r"(?P<D>\d{2})",
          "HH": r"(?P<h>\d{2})", "mm": r"(?P<m>\d{2})", "ss": r"(?P<s>\d{2})"}
_CODE = re.compile("|".join(_CODES))
_FIELD = re.compile(r"\{\{|\}\}|\{(\w+)(?::([^{}]*))?\}")

# A trim keeps the name and adds a suffix: "_trim" from Moments, " (trimmed)"
# from Vertex.
_SUFFIX = r"(?:_trim\w*|[ ]\(trimmed(?:[ ]\d+)?\))?"


class PatternError(ValueError):
    """A template that can't be read; the message is fit to show."""


@dataclass(frozen=True)
class Part:
    kind: str           # "text" or one of KINDS
    text: str = ""      # the text, for "text"; the format, for a date or time


@dataclass(frozen=True)
class Reading:
    game: str = ""
    when: float = 0.0   # a timestamp; 0.0 if the name doesn't say


@dataclass(frozen=True)
class NamePattern:
    app: str                        # whose names these are: "Medal", "My names"
    template: str
    split_words: bool = False       # "FirstLight" → "First Light"
    spaces: str = ""                # what stands for a space in the game: "-", "_"

    @cached_property
    def parts(self) -> tuple[Part, ...]:
        return parse(self.template)

    @cached_property
    def regex(self) -> re.Pattern:
        return self._regex(1)

    def _regex(self, shortest_game: int) -> re.Pattern:
        pieces = []
        for part in self.parts:
            if part.kind == "text":
                pieces.append(re.escape(part.text))
            elif part.kind == "game":
                pieces.append(f"(?P<game>.{{{shortest_game},}}?)")
            elif part.kind == "skip":
                pieces.append(f".{{{part.text}}}" if part.text else r".*?")
            else:
                pieces.append(_format_regex(part.text))
        return re.compile("^" + "".join(pieces) + _SUFFIX + "$")

    def read(self, name: str) -> Reading | None:
        """What `name` (a file name, with or without its extension) says, or
        None if it isn't written this way."""
        stem = os.path.splitext(name)[0] if name.lower().endswith(_EXTENSIONS) else name
        match = self.regex.match(stem)
        if not match:
            return None
        found = match.groupdict()
        # A game ending in a number runs into a date written straight after
        # it ("Helldivers2" + "20260817…"): the shortest game leaves no real
        # date, so the game takes more until one is left.
        while found.get("game") and found.get("Y") and not _timestamp(found):
            match = self._regex(len(found["game"]) + 1).match(stem)
            if not match:
                found = self.regex.match(stem).groupdict()
                break
            found = match.groupdict()
        game = found.get("game") or ""
        if game:
            game = self.tidy_game(game)
        return Reading(game, _timestamp(found))

    def tidy_game(self, text: str) -> str:
        for char in self.spaces:
            text = text.replace(char, " ")
        if self.split_words:
            text = re.sub(r"(?<=[a-z])(?=[A-Z\d])|(?<=\d)(?=[A-Z][a-z])", " ", text)
        return " ".join(text.split())

    def to_dict(self) -> dict:
        return {"app": self.app, "template": self.template,
                "split_words": self.split_words, "spaces": self.spaces}

    @classmethod
    def from_dict(cls, data) -> NamePattern | None:
        """A pattern from the settings, or None if it can't be read."""
        if not isinstance(data, dict):
            return None
        app, template = data.get("app"), data.get("template")
        split, spaces = data.get("split_words", False), data.get("spaces", "")
        if not (isinstance(app, str) and isinstance(template, str) and
                isinstance(split, bool) and isinstance(spaces, str)):
            return None
        pattern = cls(app, template, split, spaces)
        try:
            pattern.regex      # noqa: B018 - reading it is the check
        except (PatternError, re.error):
            return None
        return pattern


_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".ts", ".m4v")


def parse(template: str) -> tuple[Part, ...]:
    """A template's parts. Raises PatternError if it can't be read."""
    parts: list[Part] = []
    text, at, seen = "", 0, set()
    for match in _FIELD.finditer(template):
        text += template[at:match.start()]
        at = match.end()
        if match.group(0) in ("{{", "}}"):
            text += match.group(0)[0]
            continue
        kind, fmt = match.group(1), match.group(2) or ""
        if kind not in KINDS:
            raise PatternError(f"Vertex doesn't know {{{kind}}}.")
        if kind in WHEN_KINDS and not _CODE.search(fmt):
            raise PatternError(f"{{{kind}}} needs a format, such as YYYY-MM-DD.")
        if kind == "skip" and fmt and not (fmt.isdigit() and int(fmt) > 0):
            raise PatternError("{skip:…} takes a number of characters, such as {skip:7}.")
        if kind == "game" and fmt:
            raise PatternError("{game} takes no format.")
        reads = {"game": {"game"}, "date": {"date"}, "time": {"time"},
                 "datetime": {"date", "time"}, "skip": set()}[kind]
        if reads & seen:
            raise PatternError("Each of the game, the date and the time can be marked once.")
        seen |= reads
        if text:
            parts.append(Part("text", text))
            text = ""
        parts.append(Part(kind, fmt))
    text += template[at:]
    if "{" in text or "}" in text:
        raise PatternError("A brace without its pair.")
    if text:
        parts.append(Part("text", text))
    return tuple(parts)


def template_of(parts) -> str:
    """The template for `parts` (the opposite of `parse`)."""
    out = []
    for part in parts:
        if part.kind == "text":
            out.append(part.text.replace("{", "{{").replace("}", "}}"))
        else:
            out.append(f"{{{part.kind}:{part.text}}}" if part.text else f"{{{part.kind}}}")
    return "".join(out)


def _format_regex(fmt: str) -> str:
    out, at = [], 0
    for match in _CODE.finditer(fmt):
        out.append(re.escape(fmt[at:match.start()]))
        out.append(_CODES[match.group(0)])
        at = match.end()
    out.append(re.escape(fmt[at:]))
    return "".join(out)


def _timestamp(found: dict) -> float:
    if not found.get("Y"):
        return 0.0      # a time alone doesn't say when
    if not 1990 <= int(found["Y"]) <= datetime.date.today().year + 1:
        return 0.0      # no clip was recorded then: digits of something else
    try:
        moment = datetime.datetime(int(found["Y"]), int(found["M"]), int(found["D"]),
                                   int(found.get("h") or 0), int(found.get("m") or 0),
                                   int(found.get("s") or 0))
    except (TypeError, ValueError):
        return 0.0      # the right shape, but no real moment
    return moment.timestamp()


# --- Formats a marked part can be read in ---------------------------------------

_DATE_ORDERS = (("YYYY", "MM", "DD"), ("DD", "MM", "YYYY"), ("MM", "DD", "YYYY"))
_DATE_SEPARATORS = ("-", ".", "_", "", " ", "/")
_TIME_SEPARATORS = ("-", ".", "_", "", ":")
_JOINERS = ("", "_", "__", " ", " - ", "-", "T", ".")


def _dates() -> list[str]:
    return [sep.join(order) for order in _DATE_ORDERS for sep in _DATE_SEPARATORS]


def _times() -> list[str]:
    return [sep.join(codes) for codes in (("HH", "mm", "ss"), ("HH", "mm"))
            for sep in _TIME_SEPARATORS]


def formats_for(kind: str, text: str) -> list[str]:
    """The formats that read `text` as a real date, time or both, most likely
    first. Empty if none does."""
    candidates = {"date": _dates(), "time": _times(),
                  "datetime": [d + j + t for d in _dates() for j in _JOINERS
                               for t in _times()]}[kind]
    found = []
    for fmt in candidates:
        match = re.fullmatch(_format_regex(fmt), text)
        if not match:
            continue
        values = match.groupdict()
        if kind != "time" and not 1970 <= int(values["Y"]) <= 2100:
            continue
        if kind != "time" and not _timestamp(values):
            continue
        if values.get("h") is not None and not (int(values["h"]) < 24 and
                                                int(values["m"]) < 60 and
                                                int(values.get("s") or 0) < 60):
            continue
        found.append(fmt)
    return found


# --- Marking up a name -------------------------------------------------------------

@dataclass(frozen=True)
class Mark:
    start: int
    end: int
    kind: str           # one of KINDS
    format: str = ""    # for a date or time


def from_marks(name: str, marks, app: str = "My clips", split_words: bool = False,
               spaces: str = "") -> NamePattern:
    """A pattern from one name and the parts marked in it; what isn't marked
    is plain text. Raises PatternError if the marks can't make one.

    A part to ignore right beside the game, with nothing between them, says
    nothing about where one ends and the other starts, so it keeps the length
    it has in this name."""
    stem = os.path.splitext(name)[0] if name.lower().endswith(_EXTENSIONS) else name
    marks = sorted(marks, key=lambda m: m.start)
    parts, at = [], 0
    for index, mark in enumerate(marks):
        if mark.start < at:
            raise PatternError("Two marked parts overlap.")
        if mark.start > at:
            parts.append(Part("text", stem[at:mark.start]))
        fmt = mark.format if mark.kind in WHEN_KINDS else ""
        if mark.kind == "skip" and _touches_game(marks, index):
            fmt = str(mark.end - mark.start)
        parts.append(Part(mark.kind, fmt))
        at = mark.end
    if at < len(stem):
        parts.append(Part("text", stem[at:]))
    pattern = NamePattern(app, template_of(parts), split_words, spaces)
    if pattern.read(stem) is None:
        raise PatternError("Those marks don't read the name back.")
    return pattern


def _touches_game(marks, index: int) -> bool:
    mark = marks[index]
    return any(0 <= other < len(marks) and marks[other].kind == "game" and
               (marks[other].end == mark.start or marks[other].start == mark.end)
               for other in (index - 1, index + 1))


# --- Presets ---------------------------------------------------------------------

@dataclass(frozen=True)
class Preset:
    pattern: NamePattern
    sample: str             # a name as the app writes it
    checked: bool = False   # proven against a real file from the app

    @property
    def app(self) -> str:
        return self.pattern.app


PRESETS: tuple[Preset, ...] = (
    Preset(NamePattern("Medal", "MedalTV{game}{datetime:YYYYMMDDHHmmss}{skip}",
                       split_words=True),
           "MedalTV007FirstLight20260817235610725.mp4", checked=True),
    Preset(NamePattern("SteelSeries Moments",
                       "{game}__{date:YYYY-MM-DD}__{time:HH-mm-ss}", spaces="-"),
           "THE-FINALS__2024-06-16__19-45-23.mp4", checked=True),
    Preset(NamePattern("NVIDIA ShadowPlay / NVIDIA App",
                       "{game} {date:YYYY.MM.DD} - {time:HH.mm.ss}{skip}"),
           "Call of Duty Black Ops II 2023.01.27 - 19.38.28.03.DVR.mp4", checked=True),
    Preset(NamePattern("Xbox Game Bar", "{game} {date:YYYY-MM-DD} {time:HH-mm-ss}"),
           "Minecraft 2024-05-18 20-32-45.mp4"),
    Preset(NamePattern("OBS Studio", "{skip}{date:YYYY-MM-DD} {time:HH-mm-ss}"),
           "Replay 2024-06-16 19-45-23.mkv"),
    # "_replay_" before the date in an instant replay, and seconds or a
    # counter after the time in some driver versions.
    Preset(NamePattern("AMD Adrenalin", "{game}_{skip}{date:YYYY.MM.DD}-{time:HH.mm}{skip}"),
           "Cyberpunk 2077_replay_2024.05.18-20.32.mp4"),
    Preset(NamePattern("GPU Screen Recorder", "Replay_{date:YYYY-MM-DD}_{time:HH-mm-ss}"),
           "Replay_2024-06-16_19-45-23.mp4", checked=True),
)
