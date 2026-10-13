"""The order Sonar picks real devices in, and the ones it never picks itself.

Outputs and microphones each have one priority list and one excluded list of
device names, kept across plug-ins and restarts. In Auto mode Sonar uses the
highest connected device in the priority list; in Manual mode the one picked,
or the highest connected one while that is unplugged. Excluded devices are
never picked automatically, though they can still be picked by hand.

Pure functions over names, so the config, Sonar and the UI share them.
"""

from __future__ import annotations

import re


def learn(priority: list[str], excluded: list[str], names: list[str],
          first: str = "") -> list[str]:
    """The priority list with devices seen for the first time added at the
    end. The very first time, `first` (the device in use) goes on top."""
    known = set(priority) | set(excluded)
    new = [name for name in names if name not in known]
    if not priority and first in new:
        new.remove(first)
        new.insert(0, first)
    return [*priority, *new]


def choose(priority: list[str], excluded: list[str], connected: list[str], picked: str,
           auto: bool) -> str:
    """The device to use, or "" when the lists have nothing connected."""
    present = set(connected)
    if not auto and picked in present:
        return picked
    for name in priority:
        if name in present and name not in excluded:
            return name
    return ""


def promote(priority: list[str], excluded: list[str], name: str) -> tuple[list[str], list[str]]:
    """`name` moved to the top of the priority list (out of excluded)."""
    return [name, *(n for n in priority if n != name)], [n for n in excluded if n != name]


def reorder(full: list[str], shown: set[str], new_shown: list[str]) -> list[str]:
    """A list after its shown entries were rearranged to `new_shown`: hidden
    ones (disconnected, while those aren't shown) keep their places; entries
    moved in from the other list go after the rest."""
    result, queue = [], [name for name in new_shown]
    for name in full:
        if name in shown:
            if queue:
                result.append(queue.pop(0))
        else:
            result.append(name)
    return result + queue


def describe_format(spec: str) -> str:
    """A device's sample format for people: "s24le 2ch 48000Hz" → "24-bit ·
    48 kHz · stereo". "" when it can't be read."""
    match = re.match(r"\s*(?P<format>\S+)\s+(?P<channels>\d+)ch\s+(?P<rate>\d+)Hz", spec or "")
    if not match:
        return ""
    sample = match["format"].lower()
    bits = re.search(r"(\d+)", sample)
    depth = "32-bit float" if sample.startswith("float") else \
        f"{bits[1]}-bit" if bits else sample
    rate = f"{int(match['rate']) / 1000:g} kHz"
    count = int(match["channels"])
    layout = {1: "mono", 2: "stereo"}.get(count, f"{count} channels")
    return " · ".join((depth, rate, layout))
