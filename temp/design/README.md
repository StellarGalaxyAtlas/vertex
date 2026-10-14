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
| **Plum** (default) | `#150a1f` / `#1d0d2b` | `#ff3ea5` → `#7d8bff` | `#2fd39b` · `#4cb0ff` · `#b4e04a` · `#ffad33` |
| Ember | `#16110e` / `#221a15` | `#ff9a3e` → `#ffcf5c` | `#33c4a3` · `#4f97ff` · `#ec7598` · `#ad8cff` |
| Midnight blue | `#0a1020` / `#1c2640` | `#f6b03e` → `#3dd6f0` | `#4fcb72` · `#4a8ff7` · `#e0709a` · `#a88bfa` |
| Deep sea | `#061a1d` / `#0f2c2f` | `#5eead4` → `#60c5fa` | `#c08cff` · `#5ea8ff` · `#f2799f` · `#f5a742` |
| Coral | `#0d1117` / `#1a2230` | `#ff8a66` → `#8c9eff` | `#2ec4a6` · `#4ea8f5` · `#c084fc` · `#e9b949` |
| Aurora | `#0f0b24` / `#1a1538` | `#52e0f0` → `#a68bff` | `#3cc78a` · `#5b97ff` · `#ee72c0` · `#eba23e` |
| Forest | `#0b1410` / `#1a2c22` | `#e9b440` → `#9fd36a` | `#3fc7c1` · `#6b9cf7` · `#e5729f` · `#b393f5` |
| Navy (before) | `#0b0e14` / `#161b26` | `#4a62ec` → `#9aabff` | `#2fb39b` · `#3b82f6` · `#c25d7b` · `#d98d2b` |

What the tokens are for:

| Token | Used for |
|---|---|
| `MAIN_BG`, `SIDEBAR_BG`, `SECTION_BG` | the page, the rail, panels and sections |
| `CARD_BG`, `CARD_HOVER`, `CONTROL_BG` | cards, hover, buttons and an off switch's track |
| `FIELD_BG`, `EDGE` | text fields and drop-downs (recessed); their 3:1 edge |
| `LINE` / `SEAM` | dividers / menu and tooltip edges |
| `TEXT`, `TEXT_MUTED`, `TEXT_DIM` | body text, secondary text, hints |
| `ACCENT`, `ON_ACCENT` | primary button, switch on, gauges, selected text; what sits on it |
| `SECOND` | the accent's partner in gradients: gauges, the page's glow |
| `ACCENT_EDGE` / `SELECT` | the accent as a line or icon / focus, trim handles, links |
| `ACCENT_SOFT` | the selected row, tab, segment or menu item |
| `INK` | text on a bright colour: an app's badge, a red button on hover |
| `RECORDING` | the replay buffer while it records |
| `DANGER` / `WARN` / `OK` | meanings, the same in every scheme |
| `GAME`, `CHAT`, `MEDIA`, `MIC`, `DESKTOP` | the channels (each scheme tunes them away from its accent) |

**Gradients.** Each scheme's accent and second colour glow faintly from the
corners of the page (`widgets.GlowArea`), and gauges run from one to the
other.

**In code.** The UI reads `theme.ACCENT` and so on when it paints. Anything
taken from the scheme once, when a widget is built (a stylesheet, an icon, a
pixmap), goes through `theme.style(widget, lambda: ...)` or
`theme.themed(widget, apply)`, so it changes with the scheme. Icons take a
token name (`IconButton("volume", "Mute", 16, "TEXT_MUTED")`), not a value.

## The layout

- **Rail** as wide as its longest filter (name and count) needs, from 216 to
  320 px (item 26); past that, names are cut short. The filters sit on the
  rail itself, with no box behind them. The replay buffer card shows its state on top and a
  "Save clip" button with start/stop below it.
- **Messages are toasts** in the bottom-right corner of the page
  (`widgets.Banner`). A click dismisses one. No strip is kept for them.
- **Sonar.** "New apps go to [channel]" sits in the page header, next to
  Enabled (the "Unrouted apps" card is gone). Channel cards are as tall as
  their apps. When four don't fit side by side they go two by two
  (`ColumnGrid`), and the device manager's two panels stack the same way.
  At the minimum width, 980 px, nothing scrolls sideways.
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
