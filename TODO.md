# To-Do

One item at a time, top to bottom unless we decide otherwise.

---

**1.** ✅ Done
**Settings › Recording › Video › Capture**
Add a preview for choosing the monitor. If that turns out to be too difficult, at
least offer a drop-down with every capture option GPU Screen Recorder reports
(each monitor by name, focused monitor/window, portal, region, …).
- Done as a map of the monitors, laid out the way the desktop arranges them (a
  vertical monitor stands up), under a drop-down with every capture option GPU
  Screen Recorder reports. Click a monitor, or use the arrow keys, to record it.
- Decided: a diagram rather than pictures of each screen. Moments shows
  pictures, but they get vertical monitors wrong.
- Follow-up, done: only monitors can be picked, on the map; the drop-down
  went, as the map does its job. No Automatic, portal, region, focused window
  or cameras. Until a monitor is picked (and for old settings naming one of
  those), and while the picked one isn't connected, Vertex records the
  desktop's primary monitor. A line above the map names the monitor recorded.

**2.** ✅ Done
**Settings › Recording**
Like the "Clip settings" of Moments (reference in the Notes), in Vertex's look:
- One row of drop-downs with their labels above, wrapping at narrow widths:
  - Duration: 30, 60, 90, 120 seconds.
  - Video quality: Low, Medium, High, Ultra, each showing the bitrate it gives
    ("High · 20 Mbps"). The bitrate follows resolution and frame rate.
  - Resolution: 720p, 1080p, 1440p, 2160p, only up to the recorded monitor's
    own size, plus "Native". Turned for a vertical monitor (1080p = 1080×1920).
  - FPS: 30, 60, 120.
- Record cursor is a basic setting, a toggle like the rest of Settings.
- Estimates: the size of one clip, the memory the buffer uses while running,
  and how many clips fit on the disk the clips folder is on, with bars.
- Everything else goes into a collapsible "Advanced" section, including
  constant bitrate (on by default) and a custom bitrate.
- Rename "Replay buffer" to "Recording Settings".
- "Save clips to" (Advanced) shows the clips folder configured under General.
- Controls look and behave the same across all settings pages.
- Changes restart the replay buffer when they need to (question in the Notes).
- Done as: GPU Screen Recorder (status, start with Vertex), Saving a clip, and
  Recording Settings (monitor map, the four drop-downs, cursor, then "Clip
  size" and "Disk space" side by side). "Advanced" below, collapsed, holds
  Video, Replay buffer, Audio and Recorder. Every drop-down, number and text
  field in a settings row is the same width on every page. First-run setup
  offers the same durations.

**3.** ✅ Done
**Settings › General › Start menu entry**
The start-menu entry should be created by default instead of being a setting,
and the entry is named just "Vertex".
- Done: Vertex adds the entry the first time it runs (overwriting one with the
  same name, such as the 1.x install's), once only: a marker in
  `~/.local/state/vertex/` remembers, so `vertex uninstall-desktop` sticks.
  The "Add to start menu" button is gone. The entry has no generic name
  ("Game Clip Recorder"), so menus show just "Vertex". Changing the logo ink
  redraws the start-menu icon on Save.

**4.** ✅ Done
**Settings › Recording › Audio**
Three drop-downs choose what goes into clips, one track each:
- Game audio device
- Chat audio device
- Microphone input

This replaces choosing tracks on the Sonar page (see 5). Media is no longer
recorded by default because it is not one of the three; that was this item's
old aim ("Media not in clips by default"). Questions in the Notes.
- Done: the three drop-downs sit under "Record the cursor". Recording no
  longer depends on Sonar: each track is the device picked, Sonar's channels
  among them. Defaults: Vertex Game, Vertex Chat, Vertex Mic. While a device
  picked is missing (Sonar off or crashed, a headset unplugged), Game and
  Chat record the default output and the microphone the default input; the
  pick is kept and used again once the device is back. The buffer restarts
  by itself when Sonar's devices come or go. "Saving a clip" moved below
  Recording Settings.

**5.** ✅ Done
**Sonar › Channels**
Remove the "In clips" checkbox under each channel, and the "In your clips"
text that refers to it. Do this after 4: until then the checkbox is the only
way to choose tracks. Replaces the old aim of renaming the checkbox.

**6.** ✅ Done
**Sonar › Devices**
Move the explanations for "Output", "Microphone" and "Unrouted apps" from the
right-hand side to directly above or below their drop-downs, possibly
colour-coded.
- Done as three columns, each a badge and title, its explanation, then the
  drop-down. Microphone uses the Mic channel's colour; Unrouted apps takes the
  colour and icon of the channel it is set to.

**7.** ✅ Done
**Sonar › Channels**
- Under each channel, list the apps currently playing through it, updating live
  as apps start and stop.
- Under the microphone, list the apps currently recording from it.
- Drag and drop an app from one channel to another, taking effect immediately.
- Decided: a drop is remembered (right-click → "Use the default channel" undoes it);
  apps that play straight to a device appear in a "Not routed" section; the Mic
  list is read-only and flags apps recording a mic directly.

**8a.** ✅ Done
**Sonar › Channels › Device**
Show under each channel the device it plays through (the Mic channel: the
microphone behind Vertex Mic).
- A chain-link icon next to the output channels' devices means "the same
  device on all output channels". Linked, picking a device for one channel
  picks it for all. Unlinked, each output channel can have its own device.
  The Mic channel has no link.
- Clicking the device opens a small list under it: the devices in priority
  order with the current one marked, then the excluded devices, and a large
  "Device Manager" button at the bottom that opens 8b.
- Keep Vertex Sonar's own look; the reference shows the behaviour, not the
  styling.
- Done: each column shows its device under its name, with the link on the
  output channels; clicking the device lists the others, the current one
  ticked. Unlinked, a channel whose own device is unplugged plays through the
  shared one meanwhile. The Devices section's Output and Microphone
  drop-downs went; "Unrouted apps" stays, as its own section. Aux went too
  (maintainer's call), with no clean-up of an old Vertex Aux (item 15). With
  four columns the page
  fits the minimum window width.
- Left for 8b: the device list's priority order, its "Excluded devices"
  part and the "Device Manager" button.

**14.** ✅ Done (bug)
**Replay buffer › Saving more than one clip**
Only the first save of a running buffer produces a clip. Later saves show
"Saving the replay buffer…" at the bottom of the window for a few seconds,
then nothing is saved, until the buffer is restarted. Reported 2026-10-13.
- Cause: Vertex sent the save signal to GSR's whole process group, which
  includes gsr-kms-server, GSR's screen-capture helper. It has no handler for
  that signal, so the first save killed it: GSR saved that clip from memory,
  then got no more frames and finished no other save.
- Fixed: save signals go to GSR alone, found in the process tree Vertex
  started (through a Flatpak wrapper too). Stopping still signals the group.
  A test runs GSR's stand-in with a helper like gsr-kms-server, through a
  wrapper, and saves three times.

**8b.** ✅ Done
**Sonar › Device manager**
A panel over the Sonar page, opened from 8a's button, with a tab for the
outputs and one for the microphone:
- An ordered priority list of devices, reordered by dragging. The current
  device is marked and has its own volume.
- An "Excluded devices" list for devices kept out of it; drag between the two.
- Show only connected devices, or all devices including remembered ones.
- "Use the same device on all output channels", the same setting as 8a's
  chain link.
- The format of each channel (e.g. 24 bit / 96 kHz), shown for information.
- Not the shortcuts: the maintainer said to leave keybinds out for now.

Questions in the Notes.
- Done, on the Sonar page itself (the maintainer's call: plenty of room)
  under "Unrouted apps": "Output devices" and "Microphones" side by side,
  each with Manual | Auto, the device in use with its volume and format, a
  priority list to drag and an Excluded list to drag into. One toggle shows
  disconnected devices; off by default. The device list under each channel
  orders by priority, shows excluded devices apart, and has a "Device
  manager" button that scrolls down to it.
- Auto (the default) uses the highest connected device in the list, at start
  too, and switches when one higher up is plugged in. Manual uses the device
  picked, and the highest connected one while it is unplugged. Picking a
  device in Auto puts it on top. Excluded devices are never picked by
  themselves. New devices join the bottom of the list. One priority list for
  the outputs, even with the channels unlinked.

**9.**
**Sonar › Hotkeys**
Hotkeys per channel for volume up, volume down, and switching to the next device.
Sonar's reference also has previous device and mute. On hold: the maintainer
said to leave keybinds out for now.

**10.** ✅ Done
**Sonar › Output**
Play the sound Sonar manages through two audio devices at the same time.
- Done as the maintainer chose: one second device, picked once under "Also
  play through" in the device manager's Output devices panel, with its own
  volume. Each output channel has an "Also on <device>" switch, on by
  default, shown once a second device is set; switch Chat off to keep it in
  the headset. Unplugged, the channels carry on through the first device
  alone; back, it joins in again. Two devices can be a little out of step
  (Bluetooth especially); that is the devices', not fixable here.
- Follow-ups from testing (2026-10-13): "Also play through" offers the
  device manager's priority list (connected, not excluded, not the device in
  use). Every Vertex volume slider follows an audio taper (loudness as the
  square of the slider: 50% ≈ -12 dB, 25% ≈ -24 dB) instead of the server's
  cubic scale, where 25% (≈ -36 dB) was all but silent; settings hold slider
  levels, converted only when sent (`audio.pulse.to_server`).

**15.** ✅ Done
**Settings › Older clips**
Remove the page, without breaking how old clips' tracks are named.
Asked 2026-10-13.
- Done: the tab went, and so did the three config keys it set
  (`game_device`, `chat_device`, `mic_device`, kept from 1.x). Maintainer's
  call: nobody went from 1.x to 2.0, so the published software shouldn't
  carry that migration. Clips recorded through Sonar, or titled by role (GSR
  5.15+), never needed them; other clips are named from their device names,
  and numbered if that fails. A config that still has the keys loads; they
  go on the next save.
- Follow-up, done: the rest of the code that only served upgrades went too.
  The library database no longer upgrades a 1.x library (no `tag` column
  folded into Game, no bare-number track volumes); new libraries get the
  whole layout at once, at version 2, where libraries in use already are.
  The cache no longer clears 1.x's loose thumbnails. Sonar no longer removes
  a Vertex Aux left by an earlier build (a reboot does), and an Aux track in
  a clip gets the clip's lanes numbered rather than one called Aux (or,
  guessed from its name, Microphone).

**18.** ✅ Done (bug)
**Dialogs › Text cut off**
"Clear the cache?" showed its explanation's second line cut off at the
bottom. Reported 2026-10-13, with a screenshot.
- Cause: Qt sizes a window once, from its layout, and then leaves its height
  alone. When the text wraps onto more lines than were counted (the dialog
  shown at another width, in another font, on another screen), the last line
  is cut. It didn't happen in the container, so the exact trigger on the
  maintainer's desktop is a guess; changing the font after the dialog opens
  reproduces it.
- Fixed: `widgets.TextDialog` keeps a dialog's minimum height at what its
  wrapped text needs at its current width, checked whenever it is shown,
  resized or its contents change. The confirmation dialogs (`ChoiceDialog`,
  used by Clear the cache, deleting a clip and unsaved settings) and Reset's
  type-to-confirm dialog use it. Export, Copy clips and Tag import don't:
  they hold lists and are meant to be resized, so their minimum height
  shouldn't grow to their full height. Move them over if they show the same.

**16.** ✅ Done (bug)
**Library › Tagging a clip**
The tag dialog suggests nothing, and doesn't apply the changes. Reported
2026-10-13.
- Cause: the list of games and people behind each field's suggestions was a
  model nothing kept hold of, so Python collected it as soon as the dialog
  was built, leaving nothing to suggest (since the PySide6 rebuild). And
  Cancel was the dialog's default button, so Enter in the Game field closed
  it without saving; only clicking Save saved.
- Fixed: the suggestions stay with the dialog. Enter saves (in the People
  field it adds the person, as before). Picking a suggested person adds them
  straight away. A test tags a clip through the library's dialog: the
  suggestions, a person added with Enter, and Enter saving.

**11.** ✅ Done
**Sonar › UI**
Overhaul the Sonar page's UI and UX, bringing items 5 and 7–10 together.
Keep Vertex Sonar's look rather than copying SteelSeries'.
- Done without changes (maintainer's call, 2026-10-13): items 5 and 7–10
  already brought the page together. Points raised and left as they are:
  the page is one long scroll (Unrouted apps is a card of its own and the
  device manager is always open), device names are cut short at the minimum
  width, the Mic column's rows sit a few pixels off the others, mute is
  only the speaker icon, Manual | Auto barely shows which is on, "Also play
  through" shows a slider while set to "Nothing else", and the header
  repeats the device each column shows.

**12.** ✅ Done
**Rail (left-hand menu) › Games / People**
Make the Games and People groups collapsible.
- Done: each group's heading shows its name, how many entries it has and a
  chevron (down when open, right when folded, as in Settings' Advanced);
  clicking it folds the group. Settled with the maintainer (2026-10-13): the
  folds are remembered (`rail_collapsed` in config.json); a folded group
  still shows the row the library is filtered by, so the filter in use is
  always in view; no reference screenshot.

**13.** ✅ Done
**Control API (for a StreamController / Stream Deck plugin)**
Let outside software control Vertex. The plugin itself is a separate project;
this is the part that lives in this repo. The control socket and the `vertex`
command already handle `save-clip`, `replay start/stop/toggle/status` and
`sonar up/down/status`, but replies are plain sentences meant for people.
- A documented, versioned API on the existing control socket
  (`docs/CONTROL.md`), with structured replies (fields, not sentences) and
  error codes.
- More commands: per-channel volume up/down/set and mute, next/previous
  device, mic mute, and saving clips of a set length.
- State queries for button faces: volume, muted, current device, replay
  buffer running.
- A subscription that pushes changes, so buttons update live without polling.
- Every command also available as `vertex …`, so it can be bound to a desktop
  shortcut. Item 9's hotkeys can be built on the same commands.
- Done: `vertex/control.py` describes the API in its docstring (the source
  for `docs/CONTROL.md` when the docs are written) and holds the Qt-free
  parts: API version 1, error codes (unknown_command, bad_argument,
  replay_off, sonar_off, no_device, failed), argument checks, volume steps
  and the state snapshot. Replies keep `ok` and `message` and add `data` or
  `error`. New commands: `state`, `volume`, `mute`, `device`, `subscribe`;
  `ping` reports the API version. `subscribe` answers with the state, then
  streams `state` events (once a burst of changes settles, only when
  something changed) and `notice` events; each subscriber has its own
  queue, capped so a client that stops reading can't grow it. The commands
  run in `ui/control.py`. The `vertex` command gained `volume`, `mute`,
  `device`, `state [--json]` and `watch`, and the Shortcuts tab lists the
  new ones worth binding.

**17.** ✅ Done
**Settings › Restructure the whole page**
Asked 2026-10-13.
- General: Folders stay as they are, with Library, State and Cache marked as
  advanced. Behaviour (tray, start at login) stays.
- Recording: "Saving a clip" goes, to another tab (advanced settings or
  whatever fits) that can also show how to control Vertex from the command
  line. The storage gauge goes or is reworked: it is an eyesore.
- Notifications, a new tab: switches for which notifications are shown, such
  as "Vertex is running in the tray" and "Clip captured", grouped into
  recording, Sonar, and system/logging/errors (names to be suggested).
  Built to grow: hotkeys (9) and the control API (13) will bring many more
  notifications, so adding one must be easy.
- Import becomes "Import and setup", with a way to run first-run setup again
  (with warnings).
- Reset and delete, a new tab: reset the config, the database and the cache,
  with very clear warnings and confirmations.

Questions in the Notes.

Progress:
- Notifications, done: `vertex/notifications.py` lists the categories (Clips,
  Sonar, Vertex) and every kind, with its default and level; config.json's
  `notifications` keeps the switches changed from their default. Everything
  goes through `Context.notify(kind, title, body)`, whose `notified` signal
  is what item 13 can pass on. The window shows each notice in its message
  bar, and pops it up through the tray when its kind is on and the window
  isn't in front. New kinds: replay buffer started, stopped and restarted,
  Sonar on or off, output device and microphone changed (all but the last
  two off by default); the ones that only showed in the window (a track's
  device missing, Sonar's and the library's problems) can now pop up too.
- General, done: Library, State and Cache sit under a collapsed "Advanced"
  in Folders (opened by itself when Save finds one of them blank).
- Recording, done: "Saving a clip" went (its commands go to the Shortcuts
  tab); its "Tag new clips with the game" switch is in Recording Settings,
  under "Record the cursor". The storage gauge, on the Recording page and in
  the rail, is one slim accent bar, as full as the disk is (what isn't free
  to use, so it matches the text), with "Clips X · Y free of Z" under it
  (without "of Z" in the rail).
- Shortcuts, done: a tab with the `vertex` commands worth binding to a key
  (save a clip, the last 30 seconds, replay on/off, Sonar on/off, show
  Vertex), each with a Copy button, and what the terminal adds (status,
  doctor, --help). The list is `COMMANDS` in `ui/settings/shortcuts.py`; a
  test checks each one parses with the `vertex` command's own parser.
- Import and setup, done: the tab is renamed, and "First-run setup" has "Run
  setup again…". A warning says what setup can change and that nothing is
  deleted; setup then opens with the current settings (Sonar on or off, its
  devices, the buffer's duration and autostart), with a Cancel on every
  step, and "Save and close" at the end. Finishing applies the changes to
  the running Vertex the way Settings and the Sonar page do (library
  reopened if folders moved, Sonar switched or its devices picked, buffer
  restarted if its settings changed) instead of starting anything twice.
- Reset and delete, done: "Reset settings…" and "Reset the library…" open a
  red dialog listing what goes and what stays, with the action enabled only
  once RESET or DELETE is typed; "Clear the cache…" asks plainly. Settings:
  the buffer stops, Sonar goes down (the system's default devices come
  back), config.json goes to the Trash (or a dated .bak beside it without
  one), the settings return to defaults in place, and first-run setup opens.
  Library: the database and its journal go the same way and a fresh one
  opens; games come back from Moments-style names. Cache: only its
  thumbnails and previews folders are removed. Danger buttons now look like
  buttons (red label on the usual background) rather than links.
- Tabs: General · Recording · Notifications · Shortcuts · Import and setup ·
  Reset and delete; they fit the minimum window width.

**19.** ✅ Done
**Library › Card size**
"There is so much wasted space. I'd rather have bigger clips and fewer than
more and small ones": a way to set how big the cards are. Asked 2026-10-13,
with a screenshot of 22 Overwatch clips.
- Found first: the empty strip on the right is a bug. Cards are meant to
  stretch to fill each row, but while the clips fit without scrolling, the
  grid plans one column more than Qt lays out (Qt keeps room for a scrollbar
  that isn't there), so a whole column's width stays empty.
- Decided (2026-10-13): a card-size slider in the library's header, next to
  Date/Game, plus Ctrl+scroll and Ctrl+plus/minus over the grid, remembered
  between runs. It sets the card size; cards always stretch to fill the row,
  so how many fit per row follows the window. Not in Settings.
- Done: the grid now works out its width the way Qt lays it out (room for
  the scroll bar kept either way), so rows fill whatever the filter. The
  slider runs from 200 to 640 px (the narrowest a card may be before a row
  holds one fewer; `card_width` in config.json, 290 by default), in 20 px
  steps; Ctrl+scroll and Ctrl+plus/minus over the library step it, Ctrl+0
  resets it. Thumbnails and hover previews are made 960 px wide (were 480)
  so big cards stay sharp; the size is part of their cache key, so they are
  made again as they are shown and the old ones pruned. In memory they load
  at the cards' size, within the same budget as before (about 120 MB).

**20.** ✅ Done
**Settings › General › Appearance**
"The appearance radio button does nothing." It switches the logo ink of the
window, tray and start-menu icon, and of the rail's logo, where dark ink is
dark on dark. Asked 2026-10-13.
- Decided (2026-10-13): the choice goes. The window, tray and start-menu
  icon follow the desktop's light/dark setting by themselves; the rail's
  logo is always the light ink, as the app is always dark.
- Done: the Appearance section and the `logo_variant` setting are gone (a
  config that still has it loads; it goes on the next save). The window and
  tray icon take the ink from Qt's colour scheme (dark ink on a light
  desktop, light otherwise) and change with it while Vertex runs. The
  start-menu icon is redrawn when the desktop's look no longer matches the
  ink it was drawn in, which the start-menu marker now records; `vertex
  install-desktop --icon` still picks one by hand. The rail and first-run
  logos are always light.

---

## Notes

Decisions already made, and questions to settle when their item comes up.

**Documentation.** Don't touch the repo's documentation (README, `docs/`, the
screenshots in it) until the maintainer says so (2026-10-13). Confirmed again
later that day: the docs are written at the end, item 13's `docs/CONTROL.md`
included; until then the control protocol is described in its module's
docstring. Screenshots
taken to check UI work are fine; they are never committed. Some of it is
already behind: README still says to set *Capture* to *Portal* if recording a
monitor fails, shows the old Recording page, and has people run `vertex
install-desktop` (still works, but no longer needed); `docs/ARCHITECTURE.md`
doesn't describe the monitor map, the primary-monitor fallback, the
"Restarting…" state, `recorder/presets.py`, the start-menu marker or the
recorded tracks no longer depending on Sonar (it still says channels are
ticked "In clips"). README and `docs/ARCHITECTURE.md` still point to
*Settings → Older clips*, which is gone; README still lists Aux and has an
"Upgrading from Vertex 1.x" section, and ARCHITECTURE still describes 1.x
configs, the 1.x library upgrade and an Aux lane (item 15). README still
mentions picking the logo ink for your panel, and ARCHITECTURE lists
`logo_variant` among the config keys (item 20). Item 13 needs
`docs/CONTROL.md` (from `vertex/control.py`'s docstring), README's list of
`vertex` commands lacks volume, mute, device, state and watch, and
ARCHITECTURE's control-socket paragraph predates subscriptions.

**Progress.** Done: 1–8 (8a, 8b), 10–13, 15, 17, 19, 20 and the bugs 14, 16 and 18.
Open: 9 (hotkeys), on hold until the maintainer says; it can be built on
item 13's commands. The documentation is written at the end (see
Documentation).
The maintainer is collecting reference screenshots of SteelSeries GG on
Windows for the remaining items; ask for the relevant ones when starting an
item, and don't commit them (see CLAUDE.md).

**Reference screenshots received** (described here; the images are not in
the repo). All five are of Sonar; none of Moments yet, so items 1–3 and 12
have no reference.
- *Sonar mixer, overview.* One column each for Master, Game, Chat, Media,
  Aux and Mic. Each column: icon, name and a gear button; an EQ preset
  ("Custom", "Music: Metal"); the device it plays through, with a chain-link
  icon on the output channels and the volume (100%); a vertical fader; a
  mute button; an "Apps" box. Under Master: "Apps to be routed". A ChatMix
  slider sits under Game and Chat. No record checkbox anywhere. Helps with
  5, 8a and 11 (and showed 7, now done). The maintainer wants to keep
  Vertex's look, so this is for function only; the Master column, EQ presets
  and ChatMix were not asked for.
- *Mixer with the Game column's gear open.* Shortcut fields for previous and
  next device, volume down and up, and mute. Keybinds: left out for now (9).
- *Mixer with the Game channel's device clicked.* A list drops down under
  the device: "All output devices" with the current headset marked, "All
  excluded devices" with drag handles, and a wide "Device Manager" button at
  the bottom. Helps with 8a.
- *Device manager, "All" (outputs) tab.* Left: "Output device priority list"
  with the current device marked, its volume (100%) and a headset badge;
  right: "Excluded devices". "Show: only active devices / all devices". A
  "Use the same device on all output channels" switch. A side panel with each
  channel's format (Hi-Res 24 bit / 96 or 48 kHz) and a Shortcuts panel.
  Below: "Backup device switch" Manual/Auto, "Automatic backup device switch
  at boot/reboot", "Auto-switch when Nova Wireless headset is powered off".
  Helps with 8b (shortcuts left out).
- *Device manager, "Mic" tab.* The same layout for inputs: "Input device
  priority list", "Excluded devices", the mic's format (24 bit / 48 kHz),
  shortcuts and the backup switch. Helps with 8b.

**Decided on 2026-10-13.** Keep Vertex Sonar's look; the references show
behaviour. The "In clips" checkbox goes (5) and three drop-downs in Settings ›
Recording choose the clip tracks instead (4). Each channel shows its device,
with a chain link for "same device everywhere" (8a), opening the device manager
(8b). Keybinds are left out for now.

**Item 1 (done).** GPU Screen Recorder lists each monitor's name and size but
not where it sits, so positions come from the desktop (Qt's screens) and are
matched to GSR's monitors by name. The maintainer wants one monitor picked and
nothing else: GSR's `screen` (the first monitor it finds), portal, region,
focused window and cameras are not offered. Still to check on the
maintainer's system: that Qt and GSR name the monitors alike (commands sent
on 2026-10-13); if not, a monitor is drawn to the side instead of in place.

**Item 2.** Decided on 2026-10-13:
- Video quality at 1080p60 (H.264): Low 8, Medium 12, High 20, Ultra 35 Mbps,
  scaled for other resolutions and frame rates. A bitrate set by hand in
  Advanced shows as "Custom (40 Mbps)". With constant bitrate off, the four
  levels map to GSR's own medium, high, very high and ultra, and the size
  estimate is marked as approximate.
- GSR's `-s WxH` fits the picture inside the box keeping its shape, and
  scales up as well as down. So a vertical monitor needs the box turned, and
  sizes above the monitor's own aren't offered.
- A value that isn't in a list (e.g. a 45 s duration from an older config)
  stays selected and is shown as it is.
- No migration for the new defaults: 2.0 isn't released, and the maintainer
  resets the recording settings of their test install with the next update.
- Changes apply on Save, as now: one restart of the replay buffer per Save.
- Built (2026-10-13): the choices live in `recorder/presets.py`. Resolution
  is saved as "1080p" (or "" for native) and turned into GSR's `-s` box for
  the monitor recorded when the buffer starts; the bitrate likewise. Native is
  the default. The estimate counts video plus every audio track (GSR's own
  160 kbps for AAC, 128 for Opus, unless set) and the clips that fit in the
  free space of the disk clips are saved to. Its bar compares the clip with
  the largest one the choices allow.
- Done already (2026-10-13): a restart shows as "Restarting…" in the rail and
  tray until the buffer runs again, Save says it is restarting, and a message
  says when it has.

Reference (Moments › Settings › Clips): a "Clip settings" row of four
drop-downs with labels above (Duration "1 Minute", Video quality "High",
Resolution "1080p", FPS "30"), a line saying lower settings mean smaller
files, then two halves: "Clip size estimate: up to 180 MB each, based on clip
settings" and "Hard drive space: 0 B of clips, 139.81 GB free on C:\", each
with a bar.

**Item 17.** What there is today (2026-10-13):
- Settings tabs: General (Folders, Behaviour, Appearance), Recording (GPU
  Screen Recorder, Recording Settings, Saving a clip, Advanced), Import (Copy
  clips in, Tag from file names). "Saving a clip" also holds the switch
  "Tag new clips with the game on the Game channel".
- The storage gauge is `widgets.StorageGauge`, the yellow and green bar
  under "Disk space" on the Recording page; the same widget sits at the
  bottom of the rail.
- Desktop notifications (the tray's pop-ups): "Still running in the tray"
  (once per run, on closing the window), "Clip saved" (only while the window
  isn't in front), "Replay buffer stopped" with GSR's error, and a failed
  save from the tray menu. Nothing can switch them off.
- In-app messages (the bar at the bottom of the window): clip saved, replay
  buffer restarted, a clip track's device missing, Sonar's warnings (no
  output device, no microphone, a failed change), clips tagged from file
  names, deleted or trimmed clips and their errors, Settings saved or not
  valid, the library or settings not saved or opened, a folder not created.
- Plan for growth (maintainer, 2026-10-13): one list of notification types,
  outside the UI (Qt-free), each with an id, its category, a name, a
  description and whether it is on by default. Everything that notifies
  goes through one place, which checks the setting and shows it. The
  Notifications tab is built from that list, so a new type is one entry
  there and one call where it happens. Item 13's subscription can carry
  the same events.
- Decided (2026-10-13): 17 before 13. Categories "Clips", "Sonar" and
  "Vertex". The switches decide which desktop pop-ups appear; the in-app
  message bar keeps showing everything while the window is open. "Saving a
  clip" moves to a "Shortcuts" tab with copyable `vertex` commands (where
  item 9's hotkeys can go later). The storage gauge is reworked in both
  places (Recording and the rail): one slim bar in the accent colour, with
  "Room for about N more clips · X free of Y". Library, State and Cache fold
  away under "Advanced" in Folders. "Run first-run setup again" opens setup
  with the current settings, after a warning; Cancel changes nothing and
  nothing is deleted. Resetting the config or the database moves the file to
  the Trash after a red dialog where you type a word to confirm; clearing the
  cache asks plainly. Resetting the config opens first-run setup.

**Order.** Do item 13 before or together with item 9. Any action exposed as a
`vertex …` command can be bound to a desktop keyboard shortcut, which is the
simplest reliable way to get global hotkeys on Wayland.

**Item 4 (done).** Settled on 2026-10-13: the maintainer wants recording
decoupled from Sonar, with the device settings on the Recording page. The
stand-ins (default output for Game and Chat, default input for the mic) are
the maintainer's. Each track is titled by its role ("Vertex Game"), so the
editor names its lane Game whatever device it came from (GSR 5.15+; older
versions title tracks after the device). A missing Sonar channel is stood in
for silently, as it is the plan while Sonar is off; any other missing device
gets a message. Each drop-down offers "None" (no track), the Vertex channels
(Vertex Mic for the microphone) and the real devices; the same three settings
apply with Sonar on or off, so clips have at most three tracks.

**Items 8a and 8b.** Earlier decision: one device manager for the outputs,
shared by every output channel, and one for the input. The chain link (8a)
changes that: linked, the outputs share one list as decided; unlinked, each
output channel has its own device. Each channel already has its own loopback,
so the audio side allows it. To settle:
- 8a (settled): the Output and Microphone drop-downs went; linking again
  takes the device of the channel whose link was clicked.
- 8b (settled): one priority list; the Auto/Manual switch is in, applied at
  start too; the Nova Wireless option stays out; only connected devices are
  shown unless a toggle says otherwise; the manager lives on the Sonar page.

**Item 9.** On hold (keybinds left out for now). When it comes up: linked,
"next device" switches all output channels at once; unlinked, it is per
channel. Volume up/down and mute are per channel. Confirm with the maintainer
before building it.

**Item 13 and the StreamController plugin.**
- The plugin for [StreamController](https://github.com/StreamController/StreamController)
  is a separate project in its own repository. Only the control API belongs in
  this repo.
- Today's protocol: one JSON object per line over the Unix socket
  `$XDG_RUNTIME_DIR/vertex/control.sock`. A request is
  `{"command": "save-clip", "args": {"seconds": 60}}`; a reply is
  `{"ok": true, "message": "…"}` (see `src/vertex/ipc.py`). Commands are
  dispatched on the UI thread in `Commands._run` (`src/vertex/ui/app.py`), and
  the `vertex` command in `src/vertex/cli.py` wraps them.
- To build: structured reply fields and error codes next to `message`
  (existing callers must keep working), an API version reported by `ping`, the
  commands and state queries listed under item 13, a subscription that keeps
  the connection open and pushes changes, and `docs/CONTROL.md` describing it
  all.
- Plugins are written in Python, so the plugin can talk to the socket
  directly; no extra dependency is needed on either side.
- Decided (2026-10-13): mic mute is the Mic channel's mute. Next/previous
  device picks the next connected, non-excluded device in the priority list;
  in Auto it switches the mode to Manual (picking in Auto would put the
  device on top, so cycling would bounce between two). Linked, it moves
  every output channel; unlinked, every one too unless a channel is named
  (`vertex device next chat`); the Mic channel cycles the microphones.
  Volume steps are 5% (`--step` changes it). A subscription pushes the full
  state whenever it changes, and every notification as it happens.

**Item 11 (done).** The sideways scrolling at the minimum window width (980 px) is
gone since 8a: Aux went and the columns may be a little narrower. The page now
has, top to bottom: the header (subtitle, Enabled switch), the channel
columns (each with its device, link button and "Also on" switch), "Not
routed" (only while apps play straight to a device), "Unrouted apps" (the
channel they go to), and the device manager (show
disconnected devices; Output and Microphone panels with Manual/Auto, the
device in use, its volume and format, "Also play through" for outputs, and
the priority and excluded lists). The only reference is the mixer overview
screenshot described above.

**Item 7 (done).** A drop is remembered as a routing rule; right-click → "Use
the default channel" removes it. Apps playing straight to a device appear
under "Not routed". The Mic list is read-only and flags apps recording a
microphone directly.
