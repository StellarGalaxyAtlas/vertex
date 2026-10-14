"""The order Sonar picks real devices in, and the ones it never picks itself.

Outputs and microphones each have one priority list and one excluded list of
device names, kept across plug-ins and restarts. Sonar uses the highest
connected device in the priority list. A device picked by hand (on a channel,
or with `vertex device next`) is used instead, for now: until a device is
plugged in or it is unplugged, and never across a restart. Picking leaves the
list as it is; reordering it is the lasting choice. Excluded devices are
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


def choose(priority: list[str], excluded: list[str], connected: list[str],
           picked: str = "") -> str:
    """The device to use: the one picked for now while it is connected, else
    the highest connected one in the list; "" when nothing is."""
    present = set(connected)
    if picked and picked in present:
        return picked
    for name in priority:
        if name in present and name not in excluded:
            return name
    return ""


def cycle(priority: list[str], excluded: list[str], connected: list[str], current: str,
          step: int) -> str:
    """The device `step` places on from `current` (1: next, -1: previous) among
    the connected devices that aren't excluded, in priority order and wrapping
    round; connected devices not in the list yet come last. "" when there is
    no other device to go to."""
    present = set(connected)
    order = [name for name in priority if name in present and name not in excluded]
    order += [name for name in connected if name not in order and name not in excluded]
    if not order:
        return ""
    if current not in order:
        return order[0] if step > 0 else order[-1]
    following = order[(order.index(current) + step) % len(order)]
    return "" if following == current else following


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
