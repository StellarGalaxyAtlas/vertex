# Vertex design: Anneal, sharpened

The look the maintainer chose on 2026-10-13 (TODO items 24 and 25):
Vertex's own navy and periwinkle, made readable, with a tightened layout. It
was "Direction A · Anneal, sharpened" of three drawn on a design canvas.
It has been applied: `src/vertex/ui/theme.py` holds the palette and is the
source of truth for every value below. This folder is the reference for
later work, so new UI follows the same rules.

- `library.html`, `sonar.html`: mockups of the design. Open them in a
  browser. Thumbnails are grey boxes on purpose.
- This file: the rules, the palette with its measured contrast, what was
  tried and rejected, and what is still open.

## The rules

1. **Keep Vertex's colour.** A deep navy page, surfaces lifted a step off
   it, a periwinkle accent. A neutral grey look was tried and rejected as
   "sad" (see below).
2. **Text passes WCAG AA everywhere:** 4.5:1 for every text colour on every
   ground it sits on, 3:1 for a field's edge and a switch that is on.
3. **The accent never colours an audio control.** A channel's slider takes
   the channel's colour; a device's slider is neutral grey
   (`sonar_view.NEUTRAL_SLIDER`). The accent marks what is selected, what
   can be pressed and plain settings, so Chat's blue never looks like it.
4. **Red means recording, and only that.** Nothing is red while the replay
   buffer is off.
5. **No dead space.** Nothing keeps room for something that isn't there:
   no empty boxes, no strip held for a status line, cards as tall as their
   content, one control instead of a card holding one control.

## Palette

| Token (`theme.py`) | Hex | Used for |
|---|---|---|
| `MAIN_BG` | `#0b0e14` | the page |
| `SIDEBAR_BG` | `#10141c` | the rail |
| `SECTION_BG` | `#161b26` | panels, sections |
| `CARD_BG` | `#1f2533` | cards, and controls on a card |
| `CARD_HOVER` | `#29303f` | hover |
| `CONTROL_BG` | `#262d3c` | buttons, an off switch's track |
| `FIELD_BG` | `#0d1017` | text fields and drop-downs (recessed) |
| `EDGE` | `#66718a` | a field's edge, an off switch's outline |
| `LINE` / `SEAM` | `#2a3141` / `#343c4e` | dividers / menu and tooltip edges |
| `TEXT` | `#eef0f3` | body text |
| `TEXT_MUTED` | `#aab2bf` | secondary text, a device's slider |
| `TEXT_DIM` | `#8c95a5` | hints, group labels, placeholders |
| `ACCENT` | `#4a62ec` | primary button, switch on, plain sliders, gauges, selected text |
| `ON_ACCENT` | `#ffffff` | text and icons on `ACCENT` |
| `ACCENT_EDGE` / `SELECT` | `#9aabff` | the accent as a line or icon; focus, trim handles, links |
| `ACCENT_SOFT` | `#27336a` | the selected row, tab, segment or menu item |
| `INK` | `#0b0e14` | text on a bright colour: an app's badge, a red button on hover |
| `RECORDING` | `#ff5c6c` | the replay buffer while it records |
| `DANGER` / `WARN` / `OK` | `#ff6b70` / `#e6b422` / `#3fb950` | meanings |

The channel colours (`CHANNEL_COLOURS`) and the game dots (`game_colour`)
are unchanged.

### Measured contrast

| Check | Before | Now |
|---|---|---|
| Body text on a card | 13.2 | 13.4 |
| Secondary text on a card | 5.1 | 7.2 |
| Hint text on a card | 2.8 (fails) | 5.1 |
| Primary button label | 3.8 (fails) | 4.9 |
| Field edge on its panel / card | 1.2 (fails) | 3.5 / 3.1 |
| Switch "on" against a card | 4.2 | 3.1 |
| Danger text on a button | 3.8 (fails) | 5.0 |

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
