"""The monitors a recording can capture, arranged the way the desktop has them.

GPU Screen Recorder lists each monitor's name and size but not where it sits,
so the desktop's own arrangement — read by the UI toolkit, and passed in here
as plain `Screen`s — is joined to GSR's list by name. Settings draws the result
as a map to pick from, with a vertical monitor standing up as it does on the
desk.
"""

from __future__ import annotations

from dataclasses import dataclass

from vertex.recorder.gsr import CaptureOption


@dataclass(frozen=True)
class Screen:
    """A monitor as the desktop arranges it, in the desktop's coordinates."""

    name: str
    x: int
    y: int
    width: int
    height: int
    model: str = ""
    pixels: tuple[int, int] = (0, 0)   # its resolution, which scaling can make differ


@dataclass(frozen=True)
class Monitor:
    """A monitor to draw: where it sits, and what GSR knows about it."""

    name: str              # what GSR's -w takes
    x: float
    y: float
    width: float
    height: float
    pixels: tuple[int, int] = (0, 0)   # resolution as GSR reports it; (0, 0) = not known
    model: str = ""
    placed: bool = True    # False: the desktop didn't say where it is, so it was put aside


def arrange(options: list[CaptureOption], screens: list[Screen]) -> list[Monitor]:
    """GSR's monitors, in GSR's order, placed where the desktop has them.

    GSR is the authority on what can be recorded; the desktop only says where.
    A monitor the desktop doesn't know by that name goes in a row to the right
    of the others. Without a list from GSR (not installed, or not asked yet),
    the desktop's own monitors stand in.
    """
    reported = [option for option in options if option.kind == "monitor"]
    if not reported:
        return [Monitor(s.name, s.x, s.y, s.width, s.height, s.pixels, s.model)
                for s in screens]
    by_name = {screen.name: screen for screen in screens}
    placed = [by_name[o.value] for o in reported if o.value in by_name]
    right = max((s.x + s.width for s in placed), default=0)
    top = min((s.y for s in placed), default=0)
    monitors = []
    for option in reported:
        screen = by_name.get(option.value)
        pixels = (option.width, option.height)
        if screen is not None:
            pixels = pixels if option.width and option.height else screen.pixels
            monitors.append(Monitor(option.value, screen.x, screen.y, screen.width,
                                    screen.height, pixels, screen.model))
            continue
        width, height = (option.width, option.height) if option.width and option.height \
            else (1920, 1080)
        monitors.append(Monitor(option.value, right, top, width, height, pixels, placed=False))
        right += width
    return monitors


def fit(monitors: list[Monitor], width: float, height: float,
        margin: float = 0) -> list[tuple[float, float, float, float]]:
    """Each monitor's (x, y, width, height) scaled into a width × height box,
    centred, keeping the arrangement's proportions."""
    if not monitors:
        return []
    left = min(m.x for m in monitors)
    top = min(m.y for m in monitors)
    span_x = max(m.x + m.width for m in monitors) - left
    span_y = max(m.y + m.height for m in monitors) - top
    if span_x <= 0 or span_y <= 0:
        return [(0.0, 0.0, 0.0, 0.0) for _m in monitors]
    scale = max(0.0, min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y))
    offset_x = (width - span_x * scale) / 2
    offset_y = (height - span_y * scale) / 2
    return [(offset_x + (m.x - left) * scale, offset_y + (m.y - top) * scale,
             m.width * scale, m.height * scale) for m in monitors]


def reading_order(monitors: list[Monitor]) -> list[Monitor]:
    """Left to right, then top to bottom: the order arrow keys step through."""
    return sorted(monitors, key=lambda m: (m.x, m.y))
