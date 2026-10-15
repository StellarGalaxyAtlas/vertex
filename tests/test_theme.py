"""The colour schemes keep the design's rules (temp/design/README.md)."""

import pytest

pytest.importorskip("PySide6")

from vertex.ui import theme


def _luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(one: str, two: str) -> float:
    high, low = sorted((_luminance(one), _luminance(two)), reverse=True)
    return (high + 0.05) / (low + 0.05)


GROUNDS = ("MAIN_BG", "SIDEBAR_BG", "SECTION_BG", "CARD_BG", "CARD_HOVER", "CONTROL_BG",
           "FIELD_BG")
CHANNELS = ("GAME", "CHAT", "MEDIA", "MIC", "DESKTOP")


@pytest.fixture
def each_scheme():
    yield
    theme.select(theme.DEFAULT_SCHEME)


@pytest.mark.parametrize("name", list(theme.SCHEMES))
def test_every_scheme_meets_the_contrast_rules(name, each_scheme):
    assert theme.select(name) == name
    failures = []

    def need(fg, bg, minimum):
        ratio = _contrast(theme.colour(fg), theme.colour(bg))
        if ratio < minimum:
            failures.append(f"{fg} on {bg}: {ratio:.2f} < {minimum}")

    # Every text colour on every ground it sits on: 4.5:1.
    for text in ("TEXT", "TEXT_MUTED", "TEXT_DIM"):
        for ground in GROUNDS:
            need(text, ground, 4.5)
    need("TEXT", "ACCENT_SOFT", 4.5)                  # a selected row
    need("ON_ACCENT", "ACCENT_FILL", 4.5)             # a primary button
    need("ON_ACCENT", "ACCENT_HOVER", 4.5)
    need("ON_ACCENT", "ACCENT", 3)                    # a switch's knob on its track
    need("ON_DANGER", "DANGER", 4.5)                  # a red button, hovered
    for ground in ("SECTION_BG", "CARD_BG"):
        need("SELECT", ground, 4.5)                   # links
        for meaning in ("OK", "WARN", "DANGER"):
            need(meaning, ground, 4.5)
        # Edges, a switch that is on, the accent as an icon, the channels: 3:1.
        need("EDGE", ground, 3)
        need("ACCENT", ground, 3)
        need("ACCENT_FILL", ground, 3)                # a primary button's shape
        need("ACCENT_EDGE", ground, 3)
        for channel in CHANNELS:
            need(channel, ground, 3)
    for channel in CHANNELS:
        need("ON_CHANNEL", channel, 3)                # the icon on a channel's badge
    need("EDGE", "FIELD_BG", 3)
    need("SELECT", "FIELD_BG", 3)                     # the focus ring
    for ground in ("SIDEBAR_BG", "CARD_BG"):
        need("RECORDING", ground, 3)
    assert not failures, failures


@pytest.mark.parametrize("name", list(theme.SCHEMES))
def test_the_accent_never_looks_like_a_channel(name, each_scheme):
    """The accent never marks an audio control, so it must not be mistaken
    for one: it stays clear of every channel's colour."""
    theme.select(name)
    for channel in CHANNELS:
        assert theme.colour(channel).lower() != theme.ACCENT.lower()
    assert len({theme.colour(channel).lower() for channel in CHANNELS}) == len(CHANNELS)


def test_navy_is_the_default_and_leads_the_list():
    assert theme.DEFAULT_SCHEME == "navy"
    assert list(theme.SCHEMES) == [
        "navy", "plum", "spooky", "abyss", "aurora", "midnight", "coral", "polar", "glacier"]


def test_an_unknown_scheme_gets_the_default(each_scheme):
    assert theme.select("no-such-scheme") == theme.DEFAULT_SCHEME
    assert theme.scheme == theme.DEFAULT_SCHEME
    default = theme.SCHEMES[theme.DEFAULT_SCHEME][2]
    assert default["ACCENT"] == theme.ACCENT


def test_tokens_resolve_by_name_and_colours_pass_through(each_scheme):
    theme.select("navy")
    assert theme.colour("TEXT_MUTED") == theme.TEXT_MUTED
    assert theme.colour("MIC") == theme.channel_colour("mic")
    assert theme.colour("#123456") == "#123456"


def test_a_light_scheme_turns_what_assumed_a_dark_ground(each_scheme):
    """On a light scheme the logo takes its dark ink, the playhead the text
    colour, slider handles an outline, and red, green and yellow go deeper;
    the dark schemes keep theirs."""
    theme.select("polar")
    assert theme.LIGHT and theme.logo_ink() == "dark"
    assert theme.PLAYHEAD == theme.TEXT
    assert theme.EDGE in theme.handle()
    assert theme.MEANING[True]["DANGER"] == theme.DANGER
    theme.select("plum")
    assert not theme.LIGHT and theme.logo_ink() == "light"
    assert theme.PLAYHEAD == "#ffffff"
    assert theme.handle() == f"background: {theme.HANDLE};"
    assert theme.MEANING[False]["DANGER"] == theme.DANGER
