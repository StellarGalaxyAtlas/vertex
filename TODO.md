# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 25.

Finished items are kept short: what was built, and the decisions that still
matter. Their full write-ups, with the reasoning and the questions settled on
the way, are in this file as it was at commit 606d1a2
(`git show 606d1a2:TODO.md`).

---

## Open

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
- Removing 1.x (steps given 2026-10-13: delete `~/.local/lib/vertex` and the
  old `~/.local/bin/vertex`, link `~/vertex-test/venv/bin/vertex` there, run
  `vertex install-desktop`). Then update CLAUDE.md's test-install section,
  which still says "next to their 1.x install".
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
- 24: the new look on their desktop, in their font and display scale:
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
Graphite's colours with A's layout, and it is built. `temp/design/` holds the
rules, the palette with its measured contrast, two mockups and what is still
open; `theme.py` is the source of truth for the values. In short: neutral
greys with black-and-white controls, colour only for channels, games,
recording, meanings and a blue for focus; every text colour AA; a 216 px
rail with no empty box; messages as toasts; Sonar's "New apps go to" in its
header, channel cards as tall as their apps, two by two when four don't fit;
library cards of two lines. Not built, each its own item if wanted: the
monitor map's oversized frame, first run's empty space, drop-down arrows.

---

## Notes

**Documentation.** Don't touch the repo's documentation (README, `docs/`,
the screenshots in it) until the maintainer says so; it is written at the
end (item 21). Screenshots taken to check UI work are fine, and never
committed.

**Progress.** Done: 1–8 (8a, 8b), 10–20 and 22–24, including the bugs 14,
16 and 18.
Open: 9 (on hold) and 21 (documentation, at the end). Waiting on the
maintainer: the checks listed above, and removing 1.x.

**Reference screenshots.** Five of SteelSeries Sonar on Windows (the mixer;
a channel's gear with its shortcut fields; a channel's device list; the
device manager's output and mic tabs), described in the history; none of
Moments. They show behaviour: Vertex keeps its own look, and they are never
committed (CLAUDE.md). The mixer's Master column, EQ presets and ChatMix
were not asked for.
