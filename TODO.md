# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 65 (70 to 79 are taken by the ideas
list of 2026-10-15).

Finished items are kept short: what was built, and the decisions that still
matter. Their full write-ups, with the reasoning and the questions settled on
the way, are in this file as it was at commit 606d1a2
(`git show 606d1a2:TODO.md`).

---

## Open

**43.** Next
**Editor › "Video" and "This clip has no audio." overlap**
Under the timeline of a clip without audio, the Video lane's name and the
note that there is no audio are drawn on top of each other (seen at
1600 × 1000, in every scheme). Found while checking item 41.

**Ideas the maintainer picked (2026-10-15).** Items 70 to 79 come from the
ideas list (see Notes, "Ideas list"); each keeps its id from that list. They
are in the order to build them: small ones first, then Settings, then
Sonar. A change to how something looks starts with a mockup to pick from.

**70.** Ideas list U4
**Settings › Recording › Clearer "recorder not installed" message**
Settings › Recording says "set its command in Settings" when you are already
in Settings. It could show the "How to install it" button that first-run
setup has, plus a button that opens Advanced at the command field.
- The text comes from `recorder/gsr.py` (`detect`) and is shown as is;
  `vertex doctor` uses the same "or set its command in Settings" in
  `doctor.py`, where it reads fine. Give the Recording page its own wording
  rather than changing what the CLI prints.

**71.** Ideas list X3
**Library › Keyboard**
Arrow keys to move between cards, Enter to open, Delete to delete, F2 to
rename, F to favorite.
- The grid (`ClipGrid` in `ui/library/view.py`) has no selection today
  (`NoSelection`): keys need a current card that is drawn as focused.
- Home's latest clips use the same grid; decide with the maintainer
  whether the keys work there too.

**72.** Ideas list X4
**Library › Drag a clip out of Vertex**
Drag a card straight into Discord, a browser upload field or the file
manager. Today that takes Export › Copy file, or Show in folder.
- A drag carries the clip's file as a `file://` URL (as Copy file in the
  export dialog does), from the Library and from Home.
- The card's own drag must not get in the way of a click, the favorite
  star or a rename.

**73.** Ideas list X7
**Library › Quick export from the clip menu**
An "Export for Discord (10 MB)" entry in a card's right-click menu, using
the size you picked last, without opening the editor.
- The export dialog doesn't remember the size today (it always starts on
  Original); remembering it is part of this item.
- Uses the clip's saved trim and mix, as the editor's export does; shows
  progress and the result as a toast, with Copy file and Open folder.

**74.** Ideas list X8
**Tray › More in the tray menu**
The tray has Save clip, Save the last 30 seconds, Sonar and Quit. It could
also switch the output device and microphone, and open the Library or
Sonar directly.
- Device switching goes through the same calls as the Sonar page and
  `vertex device` (`pick_device` in `ui/services.py`): a pick is for now,
  the priority list stays the lasting order (item 53). Excluded devices
  are left out of the menu.

**75.** Ideas list L3
**Editor › Controls grow with the window**
At 2560 px the play button, Trim, Export and the track mixer stay the size
they have at 1280 px. They could scale up to 1.5× like the top bar does,
and the track names could get a wider column.
- The top bar's scaling (item 58, `SCALE_MAX` in `ui/topbar.py`) is the
  model. Check at 980, 1280 and 2560 px; mockup first.
- Item 43 (the overlapping "Video" and "This clip has no audio.") is in
  the same place: fix it first.

**76.** Ideas list X6
**Settings › Apply right away**
Every change in Settings waits for Save, and leaving asks whether to save.
Switches and lists could apply as soon as they change, the way the colour
scheme already does. Only recording changes that restart the replay buffer
would get an Apply button.
- Today: Save and Revert in the header, `is_dirty` in
  `ui/settings/view.py`, and the "leave without saving?" question in
  `ui/main_window.py` (`_may_leave_settings`). All of that goes, except
  for the recording settings.
- To ask the maintainer: whether folder changes (clips, exports) apply
  right away too, or wait for Apply like recording.
- Before 77, because 77 lays out the header and pages again.

**77.** Ideas list L2
**Settings › Use the width**
On a wide screen each setting's name sits at the far left and its switch
about 2,000 px away at the far right, and the text stays small. The page
tabs could become a list with icons in a left column, and on wide windows
the sections could sit in two columns (Notifications: Clips next to Sonar;
General: Folders next to Behavior).
- From the mockup: a "Send a test" button next to "Show them over games",
  which shows a sample notification over a game.
- Keep the Import and setup style the maintainer likes (bold title, a
  line of text, a full-width button). Check at 980, 1280 and 2560 px with
  no dead space; mockup first.

**78.** Ideas list F4
**Sonar › Level meters on the channels**
A live meter next to each fader, on the Sonar page and Home, so you can see
that the game's sound is coming through and that your mic picks you up,
without asking someone on Discord.
- To work out: how to read the levels. `pactl` has no peak readings; a
  small reader per channel on its monitor (as pavucontrol does) is the
  likely way. It must stay off the UI thread, cost little CPU, and only
  run while a page with meters is shown.
- Colours: meters are audio controls, so no accent (design rules);
  red stays for recording, so the top of a meter needs another warning
  colour. Check in a dark and a light scheme.

**79.** Ideas list L1
**Sonar › The page fills big windows**
At 2560 × 1380 about 45% of the Sonar page is empty below the device lists.
The channel cards could grow into tall mixer columns with a vertical fader
and a level meter (item 78), and the two device panels could move into a
column on the right. At 1280 px it would fall back to today's layout.
- After 78, whose meters these columns hold.
- Items 34 and 36 built today's page; keep what they settled (a panel per
  kind of device, priority and excluded lists, "also play through").
  Check at 980, 1280 and 2560 px; mockup first.

**49.**
**Other programs' notifications over games**
Asked for with 46 (Discord and the like), after 47. Vertex can't replace
GNOME's or KDE's notification server, but it can listen on the session bus
(`busctl --user monitor`, as `pactl subscribe` is watched) for
`org.freedesktop.Notifications.Notify`, and on GNOME also
`org.gtk.Notifications` and the portal (Flatpak apps), and show each through
GSR's notifier. Needs: a switch, the apps seen so far to pick from, an "app
name only" choice (toasts are recorded in clips when the whole screen is),
and Vertex's own desktop notifications left out so they don't loop.

**48.** Bug
**A test: the start-menu marker races the desktop file**
`test_first_run_adds_the_start_menu_entry` checks the marker as soon as
the desktop file appears, before the job has written the marker. It fails
now and then, also without any change (seen while building 47).

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
  5% steps. Cycling devices picks for now and keeps the list's order (53).

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
- `docs/CONTROL.md`: new, written from `vertex/control.py`'s docstring
  (since item 59 it also has `devices` and `device set`).
- README's "Settings and first run": first-run setup now has the Vertex
  Sonar and Vertex Moments steps and brings an existing library along
  (item 22); the import tools are no longer where setup points.
- The screenshots in `docs/` (first-run.png shows the old step 1). Since
  item 24 every one of them shows the old colours and layout.
- Round 3 and after (items 29 to 45), in README and `docs/ARCHITECTURE.md`:
  the rail is gone for a top bar (Home, Library, Sonar, Settings, search,
  the replay pill; 31); Vertex opens on Home (32, 35, 37); the Library's
  filter row (33); the Sonar page as on Shelves' board, with a panel per
  kind of device (34, 36); nine colour schemes picked in Settings › General,
  two of them light (30, 38 to 42, 44), and how `ui/theme.py` works them
  out (`_scheme`, the light path, `ACCENT_FILL`, `ON_CHANNEL`, `ON_VIDEO`).

## Waiting on the maintainer

Built and tested in the container; only their system can confirm:
- 60: Settings › General lists the schemes as Navy, Plum, Spooky, Abyss,
  Aurora, Midnight blue, Coral, Polar, Glacier; a fresh config opens in Navy.
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
- 40 to 42, 44: Spooky, Polar and Glacier on their desktop. On the light
  ones: the dark logo in the top bar, the panels standing off the page, the
  slider handles and the editor's playhead visible, nothing white on white
  (first-run setup and the export dialog were not looked at in a light
  scheme).
- 39, 45: Plum's white text on the deeper pink and its periwinkle
  highlight; drop-downs opening as a list under their field, the hovered row
  highlighted; the clip cards' outline subtle enough.
- 36, 37: the Sonar page's two device panels; Home's faders lit and as wide
  as their card allows, on their big screen.
- 35: Home and the top bar on their big screen: two rows of clips, the
  tiles under them filled (faders, games, storage, people), a wider search.
- 34: the Sonar page with their devices and apps: the big numbers and the
  device lists in their font; nothing cut short at their window size.
- 32: Home with their library (632 clips, 23 games) at their window size:
  the newest clips fill two rows and everything fits without scrolling.
- 31, 33: the top bar and the filter row in their font and display scale;
  the drop-downs open under their chip and take the keyboard.
- 30: the schemes on their desktop: each one picked in Settings shows at
  once everywhere (top bar, Home, Library, Sonar, Settings, the editor), and
  the saved one is there after a restart.
- 61: the logs on their system: lines from a real GSR, Sonar with their
  devices, the Stream Deck's commands; switching Keep logs off and on.
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
join the bottom. One priority list for the outputs, linked or not. Aux went. Since 53 there is no
Manual or Auto: the list decides, and a pick is for now.

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

**30. Colour schemes.** Settings › General › Appearance offers nine, each
drawn as a small picture of the app in its colours: Plum (the default,
Shelves' palette), Spooky, Abyss, Aurora, Midnight blue, Coral, Polar,
Glacier and Navy (the colours before; its hint text one step lighter to
pass on a hovered card). A pick shows across the whole app at once; Save
keeps it (`colour_scheme` in the config), Revert or leaving without saving
goes back, a settings reset returns to Plum. Each scheme brings its own channel
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
below 1000 px. Manual's explanation shows only in Manual. (53: the toggle went, three
across.)

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

**41. Colour schemes: Polar, the first light scheme, replaces Deep sea.**
An aurora over snow: snow-grey page `#eceef7`, panels `#fbfbfe`, text
`#1a1730`, a violet accent `#7c3aed` with white text into teal `#0d9488`,
the channels emerald, blue, raspberry, amber and cyan, each deep enough
for 3:1 on white. A light page colour turns round the steps worked out
from the key colours (a paler top bar, fields a step into the page, darker
edges) and what assumed a dark ground: red, green and yellow go deeper
(`theme.MEANING`), white goes on the channel badges and a red button
(`ON_CHANNEL`, `ON_DANGER`), the logo takes its dark ink, slider handles
an outline, the playhead the text colour, and the duration and star over
a thumbnail stay light on their scrim (`ON_VIDEO`, `STAR`). The dark
schemes look as before. Deep sea is gone; a config naming it gets Plum.

**42. Colour schemes: Glacier, a second light scheme.** Asked for with 41
as a scheme of its own: ice-grey page `#e9f0f5`, panels `#fafcfd`, text
`#0f1e2b`, a deep glacier blue `#0a6cb4` with white text into icy teal
`#14a3b8`, the channels green, indigo (kept off the blue), raspberry,
amber and violet. With nine schemes the picker would leave one alone on a
row, so it now takes as many to a row as fit (two to four) but fewer when
that fills every row: three by three.

**44. Light schemes: the panels melted into the page.** Polar's and
Glacier's panels were 1.12:1 against their page, their outline 1.05:1, so
the bubbles hardly showed. The pages are a clear step darker now (Polar
`#d5d9e8`, Glacier `#d1dce7`) under near-white panels, 1.4:1; lines are a
step stronger on a light scheme, and fields sit half way between page and
panel instead of taking the page's colour. Glacier's hint text went one
step darker to keep 4.5:1 on the darker page.

**45. Clip cards: a faint outline in the scheme's colours.** Asked for so
a clip stands off the background: every clip card (Library and Home) has
a 1 px outline running from the accent at its top left into the second
colour at its bottom right, at 25 % (60 % while hovered), over its shadow.

**46. Notifications over games.** Desktop notifications don't show over a
fullscreen game, while GPU Screen Recorder's own overlay does. Pop-ups now
go through GSR's notifier, `gsr-notify` (package
gpu-screen-recorder-notification), when it is installed and Settings ›
Notifications › "Show them over games" is on (the default); otherwise, or
if it fails to start, they are desktop notifications as before. Its
background is the scheme's accent (warning and error colours for those
levels), replay kinds get its replay icon, and each toast replaces the one
before (`recorder/notifier.py`). `vertex doctor` reports whether it is
found. Open: it is looked up on the PATH only, so a Flatpak-only GSR has
none (the Flatpak ships its own copy). Saving a clip tried by the
maintainer: works.

**47. Volume changes over games.** Built (a "Volume changed" toast for
shortcuts and the desktop's volume keys), then taken out again with its
setting: the maintainer found it annoying. Not to be brought back.

**50. First run › Vertex Moments: GSR's notifier.** The step looks for
`gsr-notify` along with GPU Screen Recorder: in green when found
(notifications show over games), else a muted line naming the
gpu-screen-recorder-notification package, with Check again.

**51. A shortcut for the next microphone.** `vertex device next mic`
already went down the device manager's list of microphones, top to bottom
and round again, skipping excluded ones; Settings › Shortcuts now lists it
on its own row. Checked: in Manual it follows the list as it is; in Auto
the first switch puts the microphones in Manual, as decided with 13 (a pick
in Auto goes to the top of the list, so cycling would bounce between two).
Superseded by 53.

**58. The top bar fills its room.** On a wide window the logo, the name and
the tabs grow (up to 1.5 times, icons and text alike) and spread out until
they nearly reach the search, and the bar gets a little taller to fit them
(60 to 72 px). The search keeps its width and place; at 980 and 1280 px
the bar barely changes (`topbar.TopBar._fit`).

**57. Editor: the mixer no longer stalls playback.** Every slider step
swapped mpv's whole lavfi-complex, and mpv seeks each time it changes: the
picture and sound stopped while a slider moved. The graph now only lines the
tracks up as stereo pairs (set once); the gains are `volume` filters in the
`af` chain, changed while playing with `af-command` (`mixing.mpv_mix_filter`).

**56. Editor: dragging the playhead holds playback.** Grabbing the playhead
of a playing clip pauses it until it is let go, then it plays on from there;
a paused clip stays paused where it was dropped.

**55. Editor: the window vanished opening the first clip.** The first
OpenGL widget (the video) in a shown window makes Qt rebuild the window. The
main window now carries a hidden OpenGL widget from the start.

**54. Reset and delete, regrouped.** Reset settings and Clear cache share
one card, each laid out like an Import and setup card (title, line, full-width
button). Reset library has its own card under them, with an
amber warning on top: only do this if something's wrong and clearing the
cache didn't fix it. "Reset the library" and "Clear the cache" are now
"Reset library" and "Clear cache" on the buttons and dialog titles.

**53. Devices: the priority list decides, picks are for now.** Auto and
Manual are gone, for outputs and microphones alike. Sonar uses the highest
connected device in the list: A unplugged, B; A back, A. A device picked by
hand (`vertex device next`, a channel's device on the Sonar page, linking
from a channel) is used for now, without touching the list: until a device
of that kind is plugged in or the picked one is unplugged, and never across
a restart of Vertex or Sonar (`Sonar.picked`, not saved). Setup's choice is
the exception: it goes on top of the list. Unlinked channels keep their own
device as before; excluded devices are never picked automatically but can
be by hand. The device manager's panels are three across (the name over the
device in use, with "Also play through" for outputs; priority; excluded);
below 1000 px the first two side by side over the excluded list. A pick
shows "Picked for now" under the device in use; `vertex state` says
"picked for now" too (`output_picked`, `mic_picked` in the control API).

**52. Shorter UI strings.** Most labels and hints read like explanations,
not settings. Every string was listed with a shorter wording and the
maintainer approved them all: switches are a few words ("Close to tray"),
hints one short line or none, notification kinds mostly without a hint,
errors start "Couldn't", spelling is American. Left out on purpose: the
Auto/Manual and device-priority text (replaced by the mic-switching work),
the colour schemes' descriptions (dropping them leaves room in the scheme
cards, a look to show first), and the shortcut hint for `--last`, which
keeps naming 10, 60, 300, 600 or 1800 since only those work.

---

**59. A StreamController plugin for Vertex.** Tested and approved by the maintainer
(2026-10-15). In `streamcontroller/` (plugin id `com_stellargalaxyatlas_Vertex`, install
and Flatseal steps in its README), a client of the control socket. Keys, named
by the maintainer (2026-10-15): Sonar Information (a channel's volume, in the bottom label),
Sonar Volume (up or down by a step set on the key; on a dial, turning goes
either way), Sonar Toggle Channel Mute, Sonar Next Microphone, Sonar
Next Output Device, Sonar Toggle Microphone, Sonar Toggle Output Device,
Replay Buffer Toggle, Replay Save Clip (flashes green when a clip lands)
and Show Vertex. Action ids stay as first published (Volume is now Sonar
Information, Mute is Sonar Toggle Channel Mute), so set-up keys keep working. One
subscription follows the state for every key. Decided (maintainer,
2026-10-14): the toggles' two devices are picked in the key's settings from
the list Sonar gives (`devices`); a press switches for now (`device set`),
as the Sonar page does; on any other device the key shows a neutral "No
mic" face. Inside the Flatpak the plugin uses the socket when given
`xdg-run/vertex` (Flatseal), else a relay run with `flatpak-spawn --host
python3`. Show Vertex on Wayland also asks KWin, through its scripting
interface on the session bus, to activate Vertex's windows (`vertex.kwin`),
since Wayland won't let Vertex take the focus itself; works on the
maintainer's Plasma. The state keys (both toggles,
Sonar Toggle Channel Mute, Replay Buffer Toggle) take a picture per state in
their settings (asked 2026-10-15, as the maintainer's Discord plugin
does); a face without one falls back to `assets/<name>.png` when present
(mic-1, mic-2, mic-none, output-1/2/none, muted, unmuted, replay-on,
replay-off). Drawing those default icons is the next stage.

---

**60. Navy is the default scheme again, and first in the list** (asked
2026-10-15). The schemes now run Navy, Plum, Spooky, Abyss, Aurora, Midnight
blue, Coral, Polar, Glacier in Settings › General. Only the default changed:
a saved pick (Plum included) is kept. Navy's blurb now reads "Vertex's
original look" instead of "until now".

**61. Log files.** Asked 2026-10-15: what Vertex does, written down for
troubleshooting, "just enough to troubleshoot", not so much it wears an SSD.
`vertex.logs`: one plain-text file per part in the log folder (`vertex.log`
the app, settings and commands; `recorder.log`; `sonar.log`; `clips.log`),
each line the time, the level and what happened. A file starts over at 2 MB,
keeping two older ones (`.1`, `.2`). Only actions and errors are logged: a
dragged fader or a turned Stream Deck dial is one line once it settles;
`state`, `devices` and `status` commands aren't logged; GPU Screen
Recorder's own output only when it exits on an error. Notices go in the log
of their part too. Settings › General › Advanced: Keep logs (on by default,
asked as a switch) and the Logs folder (default `logs` in the state folder,
`~/.local/state/vertex/logs`). Uncaught errors land in `vertex.log`. Only
the running app writes logs, not `vertex save-clip` and co.

**62. Renaming a clip card kept losing the typing** (bug, found 2026-10-15
testing the whole app). The card's name field was filled in again from the
library each time its row changed, and the hover preview changes it every
frame: with the pointer resting on the card, typed letters vanished. The
field is now filled once, when renaming starts (Library and Home).

**63. `vertex doctor` warned about the default recording settings** (bug,
found with 62). It checked the settings as saved, where "constant bitrate"
has no number yet because the video quality works it out, and so reported
"Constant bitrate needs a bitrate" for everyone. It now checks them as GPU
Screen Recorder gets them. Also: `vertex replay status` said "The replay
buffer is failed."; it now says "stopped after an error".

**64. The replay buffer starts again after a crash** (asked 2026-10-15,
picked "restart once"). Until now GPU Screen Recorder dying while it recorded
left the buffer off, with a notice, until it was started by hand. Now Vertex
starts it again by itself, once: if that start fails, or it dies again within
a minute of being restarted, it stays off and the "Replay buffer stopped"
notice shows as before. A start that fails (bad settings, no recorder) is
never retried. The restart shows as "Restarting…" in the top bar, goes in
`recorder.log`, and pops up "Replay buffer restarted" only with that
notification switched on (off by default; its line in Settings ›
Notifications now reads "After a settings change or a crash").

## Notes

**Documentation.** Don't touch the repo's documentation (README, `docs/`,
the screenshots in it) until the maintainer says so; it is written at the
end (item 21). Screenshots taken to check UI work are fine, and never
committed.

**Progress.** Done: 1–8 (8a, 8b), 10–20, 22–42, 44 to 47, 50, 51, 53 to 64, including the
bugs 14, 16, 18 and 26. The new look of round 3 is built and scales on big
screens; there are nine colour schemes, two of them light. Next: 43 (an
editor bug), then the picked ideas 70 to 79 in order. Then 9 (on hold) and
21 (documentation, when the maintainer says). Waiting on the maintainer: the checks listed above. The session that
ended 2026-10-14 finished with 45; nothing was left half done.

**Colour schemes.** Decided along the way (items 30, 38 to 45): the picker
reads Plum, Spooky, Abyss, Aurora, Midnight blue, Coral, Polar, Glacier,
Navy, the first three the maintainer's favourites. Ember, Forest and Deep
sea were dropped, a grey palette rejected (item 25). A new or changed
scheme is mocked up or screenshotted for the maintainer, and passes
`tests/test_theme.py`. Where a mid-bright accent leaves dark text hard to
read, text sits on a deeper `fill` and goes white (Plum). A selected item
tinted from the accent can turn muddy (wine, brown); tint it from the second
colour instead (`soft="second"`, Plum and Spooky). A light scheme needs its
page a clear step darker than its panels (1.4:1), deeper channels and
meaning colours, and nothing white that isn't over video.

**Reference screenshots.** Five of SteelSeries Sonar on Windows (the mixer;
a channel's gear with its shortcut fields; a channel's device list; the
device manager's output and mic tabs), described in the history; none of
Moments. They show behaviour: Vertex keeps its own look, and they are never
committed (CLAUDE.md). The mixer's Master column, EQ presets and ChatMix
were not asked for.

**Ideas list.** On 2026-10-15 Claude looked through the whole app and
proposed 26 changes, each with an id (L layout, U UI, X UX, F features),
with mockups: https://claude.ai/artifact/4xYZDY9hvGL1f5d6bCY8PL (private to
the maintainer). The maintainer picked L1, L2, L3, U4, X3, X4, X6, X7, X8
and F4 for now (items 70 to 79). The rest stay ideas, built only when
the maintainer asks: L4
smaller scheme previews, L5 storage tile, U1 readable clip names, U2
replay switch, U3 date headers, X1 undo after delete, X2 several clips at
once, X5 editor previous and next, F1 clean-up of old clips, F2 whole
sessions, F3 screenshots, F5 ChatMix, F6 mic noise suppression, F7 volume
per app, F8 audio profiles, F9 highlight reel.
