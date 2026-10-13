# Vertex design: Graphite colours, tightened layout

The look the maintainer chose on 2026-10-13 (TODO item 24), out of three
directions drawn on a design canvas: **B · Graphite's colours** with
**A · Anneal-sharpened's layout**. It has been applied: `src/vertex/ui/theme.py`
holds the palette and is the source of truth for every value below. This
folder is the reference for later work, so new UI follows the same rules.

- `library.html`, `sonar.html`: the two mockups of the chosen design. Open
  them in a browser. Thumbnails are grey boxes on purpose.
- This file: the rules, the palette with its measured contrast, and what is
  still open.

## The rules

1. **Colour only where it means something.** Vertex's own controls are black,
   grey and white. The colours on screen are the channels (Game, Chat,
   Media, Mic), the games' dots, recording (red), the meanings OK, warning and
   danger, and one blue for *selected or focused* (keyboard focus, trim
   handles, selected text, "Add tags" on hover).
2. **Red means recording, and only that.** Nothing is red while the replay
   buffer is off.
3. **The accent never colours an audio control.** In Graphite the accent is
   near-white, so a device slider is white and a channel's slider is the
   channel's colour. The two can't be confused.
4. **Text passes WCAG AA everywhere:** 4.5:1 for every text colour on every
   ground it sits on, 3:1 for a field's edge and a switch that is on.
5. **No dead space.** Nothing keeps room for something that isn't there:
   no empty boxes, no strip held for a status line, cards as tall as their
   content, one control instead of a card holding one control.

## Palette

| Token (`theme.py`) | Hex | Used for |
|---|---|---|
| `MAIN_BG` | `#0f1012` | the page |
| `SIDEBAR_BG` | `#141517` | the rail |
| `SECTION_BG` | `#191a1d` | panels, sections |
| `CARD_BG` | `#222327` | cards, and controls on a card |
| `CARD_HOVER` | `#303137` | hover |
| `CONTROL_BG` | `#2a2b30` | buttons, an off switch's track |
| `FIELD_BG` | `#0b0c0d` | text fields and drop-downs (recessed) |
| `EDGE` | `#6c6e76` | a field's edge, an off switch's outline |
| `LINE` / `SEAM` | `#2e2f34` / `#3a3b41` | dividers / menu and tooltip edges |
| `TEXT` | `#f4f4f5` | body text |
| `TEXT_MUTED` | `#b6b7bd` | secondary text |
| `TEXT_DIM` | `#909299` | hints, group labels, placeholders |
| `ACCENT` | `#f4f4f5` | primary button, switch on, plain sliders, gauges |
| `ON_ACCENT` | `#111214` | text and icons on `ACCENT` (and on app avatars) |
| `ACCENT_SOFT` | `#3b3c43` | the selected row, tab, segment or menu item |
| `SELECT` | `#8ab4ff` | keyboard focus, trim handles, links |
| `SELECTION` | `#2f4c7c` | selected text |
| `RECORDING` | `#ff5c6c` | the replay buffer while it records |
| `DANGER` / `WARN` / `OK` | `#ff6b70` / `#e6b422` / `#3fb950` | meanings |

The channel colours (`CHANNEL_COLOURS`) and the game dots (`game_colour`)
are unchanged.

### Measured contrast

| Check | Before (Anneal) | Graphite |
|---|---|---|
| Body text on a card | 13.2 | 14.3 |
| Secondary text on a card | 5.1 | 7.8 |
| Hint text on a card | 2.8 (fails) | 5.1 |
| Primary button label | 3.8 (fails) | 17.1 |
| Field edge on its panel | 1.2 (fails) | 3.4 |
| Switch "on" against a card | 4.2 | 14.3 |
| Danger text on a button | 3.8 (fails) | 5.1 |
| Text on a selected row | 9.5 | 10.0 |

## The layout (A's)

- **Rail** 216 px wide (was 252). The filters sit on the rail itself, with no
  box behind them. The replay buffer card shows its state on top and a
  "Save clip" button with start/stop below it.
- **Messages are toasts** in the bottom-right corner of the page
  (`widgets.Banner`). A click dismisses one. No strip is kept for them.
- **Sonar.** "New apps go to [channel]" sits in the page header, next to
  Enabled (the "Unrouted apps" card is gone). Channel cards are as tall as
  their apps. When four don't fit side by side they go two by two
  (`ChannelGrid`). At the minimum width, 980 px, four fit, and nothing scrolls
  sideways. The device manager follows straight after.
- **Library cards** have two lines under the thumbnail: the title, then
  game · people · age · size. An untagged clip says "Untagged", which turns
  into "Add tags" on hover. A click on that line edits the tags, and a click
  on the title renames the clip.

## Still open

Seen in the audit, not built yet. Each would be a TODO item of its own:
- Settings › Recording: the monitor map's frame is about twice as tall as
  the monitors drawn in it.
- First-run steps leave up to 300 px empty above Back and Continue.
- Drop-downs draw no arrow (the stylesheet hides the native one). With the
  3:1 edge they read as fields, but an arrow would say "pick from a list".
