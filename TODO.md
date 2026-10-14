# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 43.

Finished items are kept short: what was built, and the decisions that still
matter. Their full write-ups, with the reasoning and the questions settled on
the way, are in this file as it was at commit 606d1a2
(`git show 606d1a2:TODO.md`).

---

## Open

**41.** Next
**Colour schemes › Polar, a light scheme, replaces Deep sea**
The first light scheme, coloured as an aurora over snow: white and
snow-grey grounds, a violet accent into teal (the maintainer's pick).
Everything so far assumes a dark ground (the derived steps, `INK`, white
slider handles, glows), so the light ground needs its own path; every
contrast rule still holds.

**42.**
**Colour schemes › Glacier, a second light scheme**
Snow-white and ice-grey grounds, a deep glacier-blue accent into icy teal.
Asked for alongside 41, as a scheme of its own; built on 41's light path.

**9.** On hold
**Sonar › Hotkeys**
Keys for each channel's volume up and down, next and previous device, and
mute (SteelSeries Sonar has all five). On hold until the maintainer says:
keybinds were left out for now.
- Already possible without it: every one of these is a `vertex` command
  (item 13) that a desktop shortcut can run, and Settings › Shortcuts lists
  them ready to copy. What 9 would add is setting the keys inside Vertex. On
  Wayland, global keys go through the desktop (or its GlobalShortcuts
  portal), so ask what the maintainer wants before building anything.
- Decided with 13: linked, "next device" moves every output channel;
  unlinked, every one or the one named. Volume and mute are per channel, in
  5% steps. Cycling devices in Auto switches the list to Manual.

**21.**
**Documentation**
Written at the end, when the maintainer says so (see Notes). What has fallen
behind:
- README: still says to set *Capture* to *Portal* if recording a monitor
  fails; shows the old Recording page; has people run `vertex
  install-desktop` (works, but no longer needed); points to *Settings → Older
  clips*; lists Aux; has an "Upgrading from Vertex 1.x" section; mentions
  picking the logo ink; its list of `vertex` commands lacks volume, mute,
  device, state and watch. Keep the human-written intro and "Thanks" word for
  word (CLAUDE.md).
- `docs/ARCHITECTURE.md`: doesn't describe the monitor map and the
  primary-monitor fallback, the "Restarting…" state, `recorder/presets.py`,
  tracks no longer depending on Sonar (it says channels are ticked "In
  clips"), the start-menu marker, notifications, the control API or
  subscriptions; still describes 1.x configs and their keys (`logo_variant`
  among them), the 1.x library upgrade, *Settings → Older clips* and an Aux
  lane.
- `docs/CONTROL.md`: new, written from `vertex/control.py`'s docstring.
- README's "Settings and first run": first-run setup now has the Vertex
  Sonar and Vertex Moments steps and brings an existing library along
  (item 22); the import tools are no longer where setup points.
- The screenshots in `docs/` (first-run.png shows the old step 1). Since
  item 24 every one of them shows the old colours and layout.

## Waiting on the maintainer

Built and tested in the container; only their system can confirm:
- Switching to one installation (steps given 2026-10-13): quit Vertex, back
  up the library, remove 1.x (`~/.local/lib/vertex`, the old
  `~/.local/bin/vertex`) and `~/vertex-test`, `pipx install` from the
  working branch, then `vertex install-desktop --autostart` so the start
  menu and autostart entries point at it. CLAUDE.md gives the update command.
- 1: Qt and GPU Screen Recorder name the monitors alike; if not, a monitor
  is drawn to the side of the map instead of in place.
- 13: the commands against real audio (`vertex state`, `volume`, `mute`,
  `device next`, `watch`).
- 17: desktop pop-ups through the tray; resets landing in the Trash.
- 18: "Clear the cache?" shows all its text. If not: Wayland or X11, and
  the display scale.
- 19: thumbnails are made again, at 960 px, as the library is scrolled.
- 20: the tray icon's ink on their panel (a dark panel on an otherwise light
  desktop would get the dark ink).
- 22: "How to install it" opens GPU Screen Recorder's page in their browser;
  the wording of every step reads right to them.
- 35: Home and the top bar on their big screen: two rows of clips, the
  tiles under them filled (faders, games, storage, people), a wider search.
- 34: the Sonar page with their devices and apps: the big numbers and the
  device lists in their font; nothing cut short at their window size.
- 32: Home with their library (632 clips, 23 games) at their window size:
  the newest clips fill two rows and everything fits without scrolling.
- 31, 33: the top bar and the filter row in their font and display scale;
  the drop-downs open under their chip and take the keyboard.
- 30: the schemes on their desktop: each one picked in Settings shows at
  once everywhere (rail, Library, Sonar, Settings, the editor), and the saved
  one is there after a restart.
- 24, 25: the new look on their desktop, in their font and display scale:
  toasts appear bottom-right and go after a few seconds; at 980 px wide the
  Sonar page doesn't scroll sideways.

---

## Done

**1. Settings › Recording › Capture.** The monitor to record is picked on a
map laid out as the desktop arranges the monitors (a vertical one stands
up); positions come from Qt, matched to GSR's monitors by name. Only
monitors can be picked (no portal, region, focused window or cameras). Until
one is picked, or while it is unplugged, Vertex records the primary monitor.
A diagram rather than pictures: Moments' pictures get vertical monitors
wrong.

**2. Settings › Recording.** Moments-style Recording Settings: duration (30,
60, 90, 120 s), video quality (Low, Medium, High, Ultra: 8, 12, 20, 35 Mbps
at 1080p60 H.264, scaled for size and frame rate; constant bitrate by
default; one set by hand shows as Custom), resolution (up to the monitor's
own, turned for a vertical one; Native by default), frame rate, record the
cursor, and estimates of a clip's size and the clips that fit on the disk.
The rest is under a collapsed Advanced. Changes apply on Save, with one
buffer restart, shown as "Restarting…". The choices live in
`recorder/presets.py`.

**3. Start menu entry.** Added by itself on the first run, once: a marker in
`~/.local/state/vertex/` remembers, so `vertex uninstall-desktop` sticks.
Named just "Vertex".

**4. Settings › Recording › Audio.** Three drop-downs choose a clip's tracks
(Game, Chat, Microphone; Vertex Game, Chat and Mic by default), whether
Sonar is on or not. A missing device is stood in for (the default output or
microphone) until it is back. Tracks are titled by role ("Vertex Game") with
GSR 5.15+.

**5. Sonar › Channels.** The "In clips" checkbox went; item 4 chooses tracks.

**6. Sonar › Devices.** Each explanation sits with its control.

**7. Sonar › Apps.** Each channel lists the apps playing through it, live.
Dragging an app to another channel is remembered as a routing rule
(right-click → "Use the default channel" removes it). Apps playing straight
to a device show under "Not routed"; the Mic list is read-only.

**8a, 8b. Sonar › Devices and the device manager.** Each channel shows its
device; a chain link means one device for every output channel (unlinked,
each has its own). The device manager is on the Sonar page: Output devices
and Microphones, each with Manual | Auto, the device in use with its volume
and format, a priority list to drag and an Excluded list. Auto uses the
highest connected device in the list, at start too; picking one in Auto
puts it on top; excluded devices are never picked by themselves; new devices
join the bottom. One priority list for the outputs, linked or not. Aux went.

**10. Sonar › Second output.** "Also play through" one more device, with its
own volume; each output channel has an "Also on" switch. Every Vertex volume
slider follows an audio taper (loudness as the square of the slider);
settings hold slider levels, converted when sent.

**11. Sonar › UI.** Closed without changes (maintainer's call); the points
raised on the way are in the history.

**12. Rail › Games and People.** The groups fold, and stay folded between
runs. A folded group still shows the row the library is filtered by.

**13. Control API.** `vertex/control.py` describes it (its docstring is the
source for `docs/CONTROL.md`) and holds the Qt-free parts; the commands run
in `ui/control.py`. API version 1. Replies keep `ok` and `message` and add
`data`, or an `error` code. Commands: ping, show, state, save-clip, replay,
sonar, volume, mute, device, subscribe; a subscription gets the state, then
a `state` event whenever it changes and a `notice` event for every
notification. `vertex` gained volume, mute, device, state [--json] and
watch. Mic mute is the Mic channel's mute. The StreamController plugin is a
separate project; Python, so it talks to the socket directly.

**14. Bug: only the first clip saved.** Save signals go to GSR alone, not
its process group, where they killed gsr-kms-server.

**15. Settings › Older clips.** The page and 1.x's device keys went, with
all code that only served upgrades from 1.x or earlier 2.0 builds.
Libraries at version 2 keep opening.

**16. Bug: tagging a clip.** The suggestions are kept alive, and Enter
saves (in People it adds the person).

**17. Settings restructured.** Tabs: General · Recording · Notifications ·
Shortcuts · Import and setup · Reset and delete.
- Notifications: `vertex/notifications.py` lists the categories (Clips,
  Sonar, Vertex) and every kind; a new kind is one entry there and one
  `Context.notify(kind, title, body)` where it happens, and its switch
  appears by itself. Pop-ups only for kinds switched on, while the window
  isn't in front; the message bar shows everything. config.json keeps only
  switches changed from their default.
- Library, State and Cache folders under Advanced in General. The storage
  gauge is one slim accent bar, on Recording and in the rail.
- Shortcuts: the `vertex` commands worth binding to a key (`COMMANDS` in
  `ui/settings/shortcuts.py`, checked against the CLI by a test).
- Run first-run setup again: with the current settings, a Cancel on every
  step, and applied to the running Vertex.
- Reset settings or the library: to the Trash (or a dated .bak beside it),
  after typing RESET or DELETE; resetting settings opens first-run setup.
  Clearing the cache removes only its own folders.

**18. Bug: dialog text cut off.** `widgets.TextDialog` keeps a dialog as
tall as its wrapped text needs; the confirmation dialogs use it. Export, Copy
clips and Tag import don't (they hold lists and are resized by hand).

**19. Library › Card size.** The grid fills its rows (with no scroll bar it
planned a column more than Qt laid out). A card-size slider in the header,
plus Ctrl+scroll, Ctrl+plus/minus and Ctrl+0 (`card_width`, 200–640 px,
290 by default). Thumbnails and previews are 960 px, loaded at the cards'
size within the old memory budget.

**20. Logo ink.** Appearance and `logo_variant` went. The window, tray and
start-menu icons follow the desktop's light or dark look; the rail and
first-run logos are always light.

**22. First run.** Reworded and rebuilt (the maintainer found it technical
and off). Steps: Welcome ("Your clips folder"; exports follow the clips
folder until given their own) · Vertex Sonar (the virtual devices first,
recording each as a track only as a side note; Output device and Input
device, each with a sentence) · Vertex Moments (the monitor map and
Duration, Video quality, Resolution and Frame rate exactly as in Settings ›
Recording, plus start the buffer with Vertex; when GSR is missing or too
old, "How to install it" opens GSR's own page, `gsr.INSTALL_URL`, and
"Check again") · Clips you already have (start fresh, or a folder whose
clips are used where they are or copied into the clips folder, with
progress and Stop) · Tag your clips (only when clips were brought along:
the games read from file names, editable, and one game for the clips that
name none; written before the library's first scan). Decided with the
maintainer: the user picks in place or copy; Moments shows monitor,
quality, resolution, frame rate, duration and start with Vertex, but not
the save-clip shortcut; the GSR guide is a link, not per-distro commands.
The monitor map and the four drop-downs are one `ClipChoices`
(`ui/settings/clip_choices.py`) used by both, so they stay alike. The
same steps run again from Settings, with Cancel.

**23. First run › Vertex Moments: clip size.** The step shows how big a clip
comes out, as Settings › Recording does: `ClipSize` in
`ui/settings/clip_choices.py`, used by both. Only the clip size; the disk
space half ("Room for about N more clips") stays in Settings (maintainer's
call).

**24. Design: colour, contrast and dead space.** Three directions were drawn
(A · Anneal sharpened, B · Graphite, C · Showcase); the maintainer chose
Graphite's colours with A's layout, and it was built. The layout stays: a
216 px rail with no empty box, messages as toasts, Sonar's "New apps go to"
in its header, channel cards as tall as their apps (two by two when four
don't fit), library cards of two lines. The colours went in 25.

**25. Graphite undone.** It looked "sad" to the maintainer. The colours are
Vertex's navy and periwinkle again, at AA contrast (A's palette), with the
layout of 24 kept; a device's slider is neutral grey so the accent never
marks an audio control. `temp/design/` holds the rules, the palette with
its measured contrast, two mockups, what was rejected (don't suggest a grey
palette again) and what is still open (the monitor map's oversized frame,
first run's empty space, drop-down arrows); `theme.py` is the source of
truth for the values.

**26. Rail width.** At 216 px the rail cut names and counts (632 showed as
63) and its scroll bar covered the counts: each filter row was a fixed 200 px
in a narrower list. Rows now ask for the width of their name and count and
elide instead of overflowing, and the rail sizes itself to the widest one,
with room for the scroll bar, from 216 to 320 px. With a wider rail at the
980 px minimum, Sonar's device panels stack like its channels do
(`ColumnGrid`).

**27. Design round 2.** Eight directions on the design canvas's Round 2
page (Dock, Split view, Shelves, Studio, Home dashboard, Daylight, Side
mixer, Command bar), each a Library and a Sonar board with its pick-able
ideas, and a board of their palettes; one designer agent per direction, no
automated review (the maintainer reviewed them). The picks became 29 to 34.

**28. Device manager: no volume for the device in use.** The channels'
sliders already set what is heard, so the Output devices and Microphones
panels show the device in use by name and format only. The second output
("Also play through") keeps its own volume.

**29. Design round 3: the picks put together.** The maintainer's picks from
round 2 (Shelves' plum colours, gradients and top bar; Home as on the Home
dashboard board without its replay buffer card; the Library's grid under
Shelves' filter row; Sonar as on Shelves' board; a choice of colour schemes)
drawn together on the canvas's Round 3 page, approved, and built as 30 to 34.

**30. Colour schemes.** Settings › General › Appearance offers eight, each
drawn as a small picture of the app in its colours: Plum (the default,
Shelves' palette), Spooky, Abyss, Aurora, Midnight blue, Deep sea, Coral and
Navy (the colours before; its hint text one step lighter to pass on a
hovered card). A pick shows across the whole app at once; Save keeps it
(`colour_scheme` in the config), Revert or leaving without saving goes
back, a settings reset returns to Plum. Each scheme brings its own channel
colours, kept clear of its accent, and a second colour for gradients (the
page's corner glows, gauges). `theme.py` builds a scheme from its key
colours; whatever a widget takes from the scheme when it is built goes
through `theme.style`/`theme.themed`, icons by token name.
`tests/test_theme.py` measures the contrast rules for every scheme.

**31. Top bar instead of the rail** (built with 33). The mark and "Vertex",
tabs Library · Sonar · Settings (Home joins with 32), a search in the middle
and the replay pill: its light (red only while recording), "Replay on ·
keeps the last 1:00", Save clip, start/stop. Typing a search on another page
goes to the Library. Too narrow for all of it, the tabs drop their icons and
the pill its second line. The rail and its settings (`rail_collapsed`) are
gone; the editor and first-run setup still take the whole window.

**32. Home page.** Vertex opens on it, and its tab comes first in the top
bar. As on the Home dashboard board without the replay buffer card:
- Latest clips across the full width: the newest, two rows of four to six
  as the width allows, as the Library's own cards (open, favourite, tags,
  rename, right-click), with Favorites and Untagged chips and "All N clips".
  No clips yet: what to do about it (start the buffer, import) takes the
  room instead.
- Sonar's quick mixer: each channel with what plays on it, its volume and
  mute; greyed out while Sonar is off, with "Turn on" and "Open".
- Games with their counts as bars, as many as fit; Storage; People (hidden
  while nobody is tagged, the disk then takes the column).
Every name, chip and "All …" link opens the Library filtered by it. The
editor goes back to the page it was opened from.

**33. Library: the filter row** (built with 31). All clips, Favorites and
Untagged as chips with counts, Games ▾ and People ▾ as drop-downs with a
search (Enter picks, arrows move) and counts, naming the game or person they
filter by; one filter at a time, as before. Then Date/Game, card size,
rescan and the disk. While searching, "N of M clips match". The page heading
went. Too narrow for the row, the disk's text goes first, then the
card-size icons, then the disk's bar.

**34. Sonar as on Shelves' board.** The header is one line: "Sonar", a
status light (the scheme's second colour while running) and what Sonar is
doing, then "New apps go to" and Enabled. Each channel is a card lit by its
colour: a coloured top edge, a badge, the mute beside the name, the volume
as a big number in the channel's colour over a slider in it, the device
with its link, and the apps as pills. Devices sit under one heading
(with "Show disconnected devices"), a panel per kind (item 36): Manual or Auto
(and for outputs the second device, with its volume once one is set), the
device in use, the priority list (numbered, "In use" or "Connected" on each
row) and the excluded list (a dashed drop zone while empty); two by two
below 1000 px. Manual's explanation shows only in Manual.

**35. Home and the top bar on bigger screens.** On a big window Home's
tiles stretched into gaps (the mixer's channels far apart) and the top bar
into empty stretches. The newest clips stay two rows (four to six to a row,
one row while one holds them all); the tiles under them use the height
they get: Sonar's mixer turns into tall faders (the volume big in the
channel's colour, mute at the foot) once it has 300 px, Games' rows open
up (to 56 px, their bars thicker), Storage adds what the disk is made of
(clips, everything else, free, the disk) and spreads it, and People's
tiles grow, standing the name under a bigger initial. The first try (two
to five rows of clips) was not what the maintainer meant. The top bar's
search grows with the window (to 760 px) and the tabs get more room
either side.

**36. Sonar › Devices: outputs and microphones apart.** They shared one
panel with a line between them and ran together; now each kind has a
panel of its own under the Devices heading.

**37. Home › Sonar's faders lit as on the Sonar page.** Each fader is a
small card lit by its channel's colour (a coloured top edge and a wash
from the top, as the Sonar page's channels), with a soft glow along the
fill; muted or with Sonar off, the light dims. The fader widens with its
card, 8 to 22 px (a tenth of the card), its handle a pill 12 px wider.

**38. Colour schemes: Ember reworked, Forest out, Abyss in.** Ember's
ground was brown and muddied its orange and gold; it is charcoal now, near
black and barely warm (`#0f0f0f`, panels `#1a1918`), orange into gold, the
channels teal, blue, lime, lilac and sand. Forest is gone (not to the
maintainer's taste; a config naming it gets Plum). Abyss is new, third in
the picker: blue going on black (`#02050c`, panels `#071226`), lit as the
deep sea's animals light themselves, a cyan glow into fluorescent magenta,
the channels neon green, electric blue, violet, a lure's gold and a
fluorescent orange. Both keep every contrast rule.

**39. Plum: text on the pink, and the selected highlight.** Dark text on
the hot pink was hard to read (6:1, but the pink sits where neither black
nor white reads well), and the selected tab, segment and menu item were a
wine (the pink faded into plum) that barely stood out and clashed. Mocked
up side by side; the maintainer picked white text on a deeper pink
(`#d42481`, 4.8:1) for what text sits on, while lines, glows, the tab
underline and switches keep the hot pink; and a periwinkle tint (Plum's
second colour) for the selected item. A scheme now has `ACCENT_FILL` for
the first and may tint `ACCENT_SOFT` from its second colour; the other
schemes look as before. In every scheme, drop-downs open as a list, so
their hovered and current rows take the highlight (as a menu, Qt drew them
darker than the list).

**40. Colour schemes: Spooky replaces Ember; Plum, Spooky, Abyss first.**
Spooky is Halloween night: near black with a hint of purple (`#09070b`,
panels `#140f17`), a pumpkin orange (`#ff7a1a`, dark text on it reads at
8:1) into witchy purple (`#a259ff`), the selected item a purple tint (as
Plum's, from the second colour, so it doesn't go muddy), the channels slime
green, dusk blue, candy-corn yellow, bone and ghost lilac. The picker reads
Plum, Spooky, Abyss, Aurora, Midnight blue, then the rest (the maintainer
first wrote Aurora third, and meant Abyss). A config naming Ember gets Plum.

---

## Notes

**Documentation.** Don't touch the repo's documentation (README, `docs/`,
the screenshots in it) until the maintainer says so; it is written at the
end (item 21). Screenshots taken to check UI work are fine, and never
committed.

**Progress.** Done: 1–8 (8a, 8b), 10–20 and 22–40, including the bugs 14,
16, 18 and 26: the new look of round 3 is built, and scales on big screens.
Open: 41 and 42 (the light schemes Polar and Glacier), 9 (on hold) and 21
(documentation, at the end). Waiting on the
maintainer: the checks listed above, and switching to one installation.

**Reference screenshots.** Five of SteelSeries Sonar on Windows (the mixer;
a channel's gear with its shortcut fields; a channel's device list; the
device manager's output and mic tabs), described in the history; none of
Moments. They show behaviour: Vertex keeps its own look, and they are never
committed (CLAUDE.md). The mixer's Master column, EQ presets and ChatMix
were not asked for.
