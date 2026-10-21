"""Human-readable formatting shared by the CLI and the UI."""

from __future__ import annotations

import math
import time

# How long a clip is described by its age before it is described by its date.
# "412 days ago" is a number to decode, not a date, so past a month the date
# itself says more.
AGE_DAYS = 30


def size(size_bytes: float, decimals: int = 2) -> str:
    """A byte count as e.g. '1.50 GB'."""
    if size_bytes <= 0:
        return "0 Bytes"
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB"]
    i = min(len(units) - 1, math.floor(math.log(size_bytes, 1024)))
    if i == 0:
        return f"{int(size_bytes)} Bytes"
    return f"{size_bytes / (1024 ** i):.{decimals}f} {units[i]}"


def duration(seconds: float) -> str:
    """Seconds as 'M:SS', or 'H:MM:SS' for long clips. 60 → '1:00'."""
    seconds = max(0, round(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def date(timestamp: float) -> str:
    """A date written out as '20 Aug 2023'.

    Day before month and the month spelled out, so it cannot be read the wrong
    way round on a desktop whose own date format is the other one.
    """
    return time.strftime("%d %b %Y", time.localtime(timestamp))


def relative_time(timestamp: float, now: float | None = None) -> str:
    """'6 days ago', or the date once it is AGE_DAYS old."""
    now = time.time() if now is None else now
    seconds = max(0.0, now - timestamp)
    if seconds >= AGE_DAYS * 86400:
        return date(timestamp)
    for unit, length in (("day", 86400), ("hour", 3600), ("minute", 60)):
        count = int(seconds // length)
        if count >= 1:
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def plural(count: int, noun: str, plural_form: str | None = None) -> str:
    """'1 clip', '3 clips'."""
    word = noun if count == 1 else (plural_form or noun + "s")
    return f"{count:,} {word}"


def oxford(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    items = [item for item in items if item]
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"
