"""The one place the app's colours and corner radii live.

Every module that draws imports from here. Before this file, gui.py, widgets.py
and player.py each carried their own copy of ACCENT, CARD_BG and friends, so a
re-skin meant editing the same value in three places and finding out later that
one of them had drifted.

The palette is "Anneal": the same layout as before, lit. The page drops a step
deeper and the card rises one, so a card reads as sitting above the page rather
than beside it, and the accent is lifted to stay bright against the deeper
ground.

Two kinds of value live here. Most are flat colours a widget can simply be
given. The rest — the gradient stops, the shadow — are the inputs to the images
paint.py renders, because CustomTkinter has no gradient fill and no shadow of
its own. Which a value is decides where it can be used: a flat colour goes on
any widget, a gradient stop only ever reaches the screen through paint.py.
"""

# --- Accent ----------------------------------------------------------------
ACCENT = "#5878ff"          # primary / active highlight
ACCENT_HOVER = "#4560e8"
ACCENT_EDGE = "#8098ff"     # 1px lit edge; what is left of Anneal's convex button

# --- Grounds ---------------------------------------------------------------
# Four steps, darkest first: page, rail, card, and the small controls on a
# card. The page is the darkest thing in the app and everything else is lifted
# off it, so depth reads as "how far above the page is this" and nothing has to
# be outlined to be told apart.
#
# The rail used to sit *below* the page, the way Anneal drew it. Once the whole
# ramp was taken darker there was nowhere below the page left to go — the two
# arrived within a few levels of each other and read as one flat surface — so
# the rail was turned over into a panel lifted off the page instead. It is the
# same separation, in the direction that still has room in it.
SIDEBAR_BG = "#171b26"      # the rail: a panel lifted off the page
MAIN_BG = "#0d1016"         # the page behind everything
SECTION_BG = "#141822"      # settings panels: above the page, under the cards
CARD_BG = "#1d2230"         # clip card — and the controls that sit on one
CARD_HOVER = "#262c3b"      # and the same card under the pointer

SEAM = "#2b3242"            # 1px highlight where the rail meets the page
THUMB_BG = "#222735"        # empty thumbnail, entry fields, small buttons

# --- Rail ------------------------------------------------------------------
# The rail is lighter than the page, so its own fields have to be cut *into*
# it: a field at THUMB_BG would float above the rail rather than sink into it,
# which is the wrong way round for something you type into.
RAIL_FIELD_BG = "#10131b"   # the search box, recessed
RAIL_LINE = "#232838"       # dividers, and the search box's border
RAIL_ACTIVE = "#2a3765"     # the row you are looking at
RAIL_ACTIVE_TEXT = "#dfe4ff"

# The sort control on the workspace header: a recessed track with the chosen
# option raised out of it, so the pair reads as one control and not two buttons.
SEG_TRACK_BG = "#151924"
SEG_TRACK_HOVER = "#1f2431"

# --- Rendered surfaces -----------------------------------------------------
# Inputs to paint.py, not colours to hand a widget. These are the gradient stops
# and the shadow the published design specified; the images built from them are
# what finally gave the app the depth the flat palette above cannot carry.
CHROME_TOP = "#1e2331"      # top stop of the rail's ramp; SIDEBAR_BG is the foot
CARD_TOP = "#212734"        # card face, top stop
CARD_BOTTOM = "#191d27"     # card face, foot — and the colour the info strip takes
CARD_HOVER_TOP = "#2a3040"
CARD_HOVER_BOTTOM = "#1f2431"

# The light on the top edge of the page: a band held at PAGE_GLOW across the
# header row, then let down into MAIN_BG in the gap above the first card. The
# fade has to finish exactly there — everything below it is a widget painting
# MAIN_BG flat, and CustomTkinter has no transparency for it to fade through
# (see paint.py). That is the whole reason the lit band is the height it is.
PAGE_GLOW = "#171d2b"

# The lift itself. CARD_PAD is the margin the card widget keeps around its own
# face for the shadow to fall into, so the widget is this much bigger on every
# side than the card you see. Changing it changes the grid's row height.
CARD_PAD = 9
CARD_SHADOW = 0.60          # how dark the shadow goes, 0-1
CARD_BLUR = 7
CARD_DROP = 4               # how far the shadow falls below the card

# For the duration badge and the favourite star, which sit on the thumbnail.
# They cannot be transparent — see the note at the top — so they take the colour
# paint.scrim darkens the frame's own edges towards, and disappear into it.
BADGE_BG = "#06070a"
BADGE_HOVER = "#141822"

# --- Text ------------------------------------------------------------------
TEXT_BRIGHT = "#e8eaed"
TEXT_MUTED = "#8b93a1"
TEXT_DIM = "#5f6878"        # group headings and counts: present, not competing

# --- Meaning ---------------------------------------------------------------
DANGER = "#e5484d"          # destructive actions (delete)
DANGER_HOVER = "#c93c40"
OK_GREEN = "#3fb950"

# Storage gauge segments, in the order they sit on the bar.
GAUGE_CLIPS = "#e5484d"     # clips — red
GAUGE_OTHER = "#e6b422"     # everything else on the disk — yellow
GAUGE_FREE = "#3fb950"      # free space — green (also the bar's track)

# The accent for anything that reads as "your clips" in text.
METER_CLIPS = "#e6b422"

# --- Editor ----------------------------------------------------------------
VIDEO_BG = "#000000"
TRIM_SHADE = "#06080c"      # over the timeline, outside the selection
PLAYHEAD = "#ffffff"

# Lane colours, mirroring the reference editor: video first, then audio.
VIDEO_LANE = "#1f6f66"
AUDIO_LANES = ("#2fb39b", "#3b82f6", "#d98d2b", "#9b6bd6", "#c25d7b")

# The waveform inside an audio lane is a darker cast of that lane's own colour,
# so a track stays recognisable by colour while its level reads as shape. A
# muted lane is drawn on LANE_BG instead, where a darkened colour would vanish,
# so its waveform takes a grey that clears the flat lane.
WAVE_SHADE = 0.40
WAVE_MUTED = "#3d4454"

# A track the mixer could name keeps its own colour however many tracks the clip
# turned out to carry, so the microphone lane is the same yellow on a two-track
# clip as on a four-track one. Colouring by position instead made the mic
# whatever colour was left over, which is a poor thing to have to count lanes
# for on the one track you most often want to find.
TRACK_LANES = {
    "Game Audio": "#2fb39b",
    "Desktop Audio": "#9b6bd6",
    "Chat Audio": "#3b82f6",
    "Microphone": "#d98d2b",
}

# --- Aliases ---------------------------------------------------------------
# The three modules had grown different names for the same colour. Keeping the
# aliases means none of their call sites had to be renamed to move the palette
# here; they are the same value, not a second one to keep in step.
FIELD_BG = THUMB_BG         # widgets.py
HOVER_BG = CARD_HOVER       # widgets.py
PANEL_BG = MAIN_BG          # player.py
LANE_BG = CARD_BG           # player.py

# --- Geometry --------------------------------------------------------------
# Anneal opens the corners up a step. Cards and panels share a radius, and so do
# every control on top of them, so the two sizes are all there is to match.
RADIUS_CARD = 14
RADIUS_PANEL = 14
RADIUS_CONTROL = 10
RADIUS_SMALL = 8            # badges, chips, and anything under ~28px tall

# Where the light on the top edge of the page starts and stops, measured from
# the top of the window. The window paints this band and so does every view
# inside it, which is why the numbers live here rather than in any one of them:
# a view whose header sat outside the plateau would step out of the light, and
# the seam would run right across the top of the app.
#
# GLOW_PLATEAU is the foot of the header row (CONTENT_PAD_TOP above it, then a
# 34px row) and GLOW_H is the top of what comes below, so the fall happens in
# the gap between the two and nothing is ever half-lit.
CONTENT_PAD_TOP = 18
HEADER_H = 34
GLOW_PLATEAU = CONTENT_PAD_TOP + HEADER_H
GLOW_H = GLOW_PLATEAU + 14

# Passed straight to CTkButton for anything that is the primary action on its
# screen. The border is the whole trick: 1px of a lighter accent around a solid
# accent fill reads as a lit edge, which is as close to Anneal's convex button
# as a toolkit without gradients gets.
PRIMARY_BUTTON = {
    "fg_color": ACCENT,
    "hover_color": ACCENT_HOVER,
    "border_width": 1,
    "border_color": ACCENT_EDGE,
}


# --- Derived colours -------------------------------------------------------
def shade(colour, factor):
    """`colour` mixed towards black (factor < 1) or white (> 1), as '#rrggbb'.

    The only value here that cannot simply be written down: a lane's colour is
    picked at runtime from the track it belongs to, so anything derived from it
    — the waveform drawn inside it — has to be computed rather than listed.
    """
    value = colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    if factor <= 1:
        channels = [round(c * factor) for c in channels]
    else:
        channels = [round(c + (255 - c) * (factor - 1)) for c in channels]
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in channels)
