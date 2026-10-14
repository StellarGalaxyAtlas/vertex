# Vertex design

The look the maintainer chose. It started on 2026-10-13 as "Anneal,
sharpened" (TODO items 24 and 25): Vertex's navy and periwinkle made
readable, with a tightened layout. On 2026-10-14 the maintainer picked from
a second and third round on the design canvas (items 27 to 34): the plum
colours and gradients of the round-2 direction "Shelves" as the default,
a choice of eight colour schemes (item 30), a top bar with a Home page, the
library's filters in a row above the grid, and Shelves' Sonar page.
`src/vertex/ui/theme.py` holds every scheme and is the source of truth for
every value. This folder is the reference for later work, so new UI follows
the same rules.

- `library.html`, `sonar.html`: mockups of the 2026-10-13 design (navy, the
  rail). Open them in a browser. Thumbnails are grey boxes on purpose. The
  round-3 mockups (top bar, Home, the scheme picker) are on the design
  canvas; items 31 to 34 build them.
- This file: the rules, the schemes, what was tried and rejected, and what
  is still open.

## The rules

1. **Keep Vertex's colour.** A deep navy page, surfaces lifted a step off
   it, a periwinkle accent. A neutral grey look was tried and rejected as
   "sad" (see below).
2. **Text passes WCAG AA everywhere:** 4.5:1 for every text colour on every
   ground it sits on, 3:1 for a field's edge and a switch that is on.
3. **The accent never colours an audio control.** A channel's slider takes
   the channel's colour; a device's slider is neutral grey
   (`sonar_view.neutral_slider`). The accent marks what is selected, what
   can be pressed and plain settings, so Chat's blue never looks like it.
4. **Red means recording, and only that.** Nothing is red while the replay
   buffer is off.
5. **No dead space.** Nothing keeps room for something that isn't there:
   no empty boxes, no strip held for a status line, cards as tall as their
   content, one control instead of a card holding one control.

## Colour schemes

Picked in Settings › General › Appearance. A scheme shows across the whole
app the moment it is picked; Save keeps it, Revert or leaving without saving
goes back. Each sets every token in `theme.py`; `tests/test_theme.py` measures
the rules below for every one of them.

| Scheme | Ground / panel | Accent → second | Game · Chat · Media · Mic |
|---|---|---|---|
| **Plum** (default) | `#150a1f` / `#1d0d2b` | `#ff3ea5` → `#7d8bff`; buttons `#d42481`, white text | `#2fd39b` · `#4cb0ff` · `#b4e04a` · `#ffad33` |
| Spooky | `#09070b` / `#140f17` | `#ff7a1a` → `#a259ff`; selected items a purple tint | `#8be04e` · `#6f8dff` · `#ffd23f` · `#e3d5c1` |
| Abyss | `#02050c` / `#071226` | `#1fe5ff` → `#ff4fd8` | `#3dff8f` · `#4d8dff` · `#b98cff` · `#ffc94a` |
| Aurora | `#0f0b24` / `#1a1538` | `#52e0f0` → `#a68bff` | `#3cc78a` · `#5b97ff` · `#ee72c0` · `#eba23e` |
| Midnight blue | `#0a1020` / `#1c2640` | `#f6b03e` → `#3dd6f0` | `#4fcb72` · `#4a8ff7` · `#e0709a` · `#a88bfa` |
| Coral | `#0d1117` / `#1a2230` | `#ff8a66` → `#8c9eff` | `#2ec4a6` · `#4ea8f5` · `#c084fc` · `#e9b949` |
| Polar (light) | `#eceef7` / `#fbfbfe` | `#7c3aed` → `#0d9488`, white text | `#047857` · `#2563eb` · `#c0267a` · `#b45309` |
| Glacier (light) | `#e9f0f5` / `#fafcfd` | `#0a6cb4` → `#14a3b8`, white text | `#0f8a5f` · `#4f46e5` · `#c0267a` · `#b45309` |
| Navy (before) | `#0b0e14` / `#161b26` | `#4a62ec` → `#9aabff` | `#2fb39b` · `#3b82f6` · `#c25d7b` · `#d98d2b` |

What the tokens are for:

| Token | Used for |
|---|---|
| `MAIN_BG`, `SIDEBAR_BG`, `SECTION_BG` | the page, the top bar, panels and sections |
| `CARD_BG`, `CARD_HOVER`, `CONTROL_BG` | cards, hover, buttons and an off switch's track |
| `FIELD_BG`, `EDGE` | text fields and drop-downs (recessed); their 3:1 edge |
| `LINE` / `SEAM` | dividers / menu and tooltip edges |
| `TEXT`, `TEXT_MUTED`, `TEXT_DIM` | body text, secondary text, hints |
| `ACCENT` | lines, glows, underlines, a switch that is on, gauges |
| `ACCENT_FILL`, `ON_ACCENT` | what text sits on (a primary button, selected text) and that text; the accent itself unless the scheme deepens it so the text can be white (Plum) |
| `SECOND` | the accent's partner in gradients: gauges, the page's glow |
| `ACCENT_EDGE` / `SELECT` | the accent as a line or icon / focus, trim handles, links |
| `ACCENT_SOFT` | the selected row, tab, segment, menu or drop-down item (Plum: a periwinkle tint, from its second colour) |
| `INK` | text on a bright colour: an app's or a person's badge |
| `ON_CHANNEL`, `ON_DANGER` | the icon on a channel's badge, the text on a red button on hover: `INK`, white on a light scheme |
| `RECORDING` | the replay buffer while it records |
| `DANGER` / `WARN` / `OK` | meanings, the same in every dark scheme, deeper in a light one |
| `ON_VIDEO`, `STAR` | text and the favourite star over a thumbnail's dark scrim, in every scheme |
| `HANDLE`, `PLAYHEAD` | a slider's handle (outlined on a light scheme), the editor's playhead (white, or the text colour on a light scheme) |
| `GAME`, `CHAT`, `MEDIA`, `MIC`, `DESKTOP` | the channels (each scheme tunes them away from its accent) |

**Light schemes** (item 41). A page colour that is light makes a light
scheme, and `theme.LIGHT` says so. The steps worked out from the key colours
turn round: the top bar goes paler than the page instead of darker, fields
sit a step into the page, edges go darker than what they outline. The
channels, red, green and yellow are deep enough to read on white, so what
sits on them is white; the logo takes its dark ink (`theme.logo_ink()`);
slider handles get an outline (`theme.handle()`). What sits on video stays
light on its dark scrim.

**Gradients.** Each scheme's accent and second colour glow faintly from the
corners of the page (`widgets.GlowArea`), and gauges run from one to the
other.

**In code.** The UI reads `theme.ACCENT` and so on when it paints. Anything
taken from the scheme once, when a widget is built (a stylesheet, an icon, a
pixmap), goes through `theme.style(widget, lambda: ...)` or
`theme.themed(widget, apply)`, so it changes with the scheme. Icons take a
token name (`IconButton("volume", "Mute", 16, "TEXT_MUTED")`), not a value.

## The layout

- **Top bar** (item 31), 60 px: the mark and "Vertex", the page tabs (the
  page showing is underlined in the accent, with a glow), the search in the
  middle, the replay pill on the right. A line under it fades from the
  accent into the second colour. Too narrow, the tabs drop their icons and
  the pill its second line; wider, the search grows (to 760 px) and the tabs
  get more room. The rail of 24 to 26 is gone.
- **Library filters** (item 33) in one row over the grid: chips for All
  clips, Favorites and Untagged; Games ▾ and People ▾ open a searchable list
  with counts, so long names never squeeze anything; then sort, card size,
  rescan and the disk. Narrow, the disk's text goes first.
- **Home** (item 32), the start page: tiles with rounded corners and a
  faint gradient. Latest clips across the full width (lit from two corners
  by the accent and second colour), then Sonar's quick mixer, Games as bars,
  Storage and People. It fits a 1280 × 820 window without scrolling. The
  clips stay two rows; on a bigger window the tiles below fill their height
  instead of leaving gaps: faders for the mixer, roomier game rows, the
  disk's breakdown, bigger people tiles (item 35). Each fader is a card lit
  by its channel's colour as on the Sonar page, glowing along its fill and
  widening with the card (item 37). With no clips yet, the
  welcome takes the room and the other tiles stay compact.
- **Messages are toasts** in the bottom-right corner of the page
  (`widgets.Banner`). A click dismisses one. No strip is kept for them.
- **Sonar** (item 34, as on Shelves' board): a one-line header with a status
  light. Each channel is a card lit by its colour, with a coloured top edge,
  a badge, the mute by its name, the volume as a big number in its colour
  (large text, so 3:1 is enough) over a slider in it, the device, and its
  apps as pills. Four in a row, two by two when they don't fit. The devices
  sit in a panel per kind (item 36), each a row of four (Manual/Auto and
  the second device, in use, priority, excluded), two by two below
  1000 px. At the
  minimum width, 980 px, nothing scrolls sideways.
- **Library cards** have two lines under the thumbnail: the title, then
  game · people · age · size. An untagged clip says "Untagged", which turns
  into "Add tags" on hover. A click on that line edits the tags, and a click
  on the title renames the clip.

## Tried and rejected

- **Graphite** (item 24, undone in 25): neutral greys with black-and-white
  controls, colour only for channels, games and recording. It passed every
  contrast check, but looked "sad". Don't suggest a grey or colourless
  palette again.
- Not chosen on the canvas: an icon rail with Sonar as a vertical mixer
  (B's layout), and a top bar with chip filters on a true-black ground with a
  lime accent (C).

## Still open

Seen in the audit, not built yet. Each would be a TODO item of its own:
- Settings › Recording: the monitor map's frame is about twice as tall as
  the monitors drawn in it.
- First-run steps leave up to 300 px empty above Back and Continue.
- Drop-downs draw no arrow (the stylesheet hides the native one). With the
  3:1 edge they read as fields, but an arrow would say "pick from a list".
