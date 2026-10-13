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
  (maintainer's call): Sonar removes a Vertex Aux left by an older version,
  and older clips' Aux tracks keep their name. With four columns the page
  fits the minimum window width.
- Left for 8b: the device list's priority order, its "Excluded devices"
  part and the "Device Manager" button.

**14.** (bug, next after 8a)
**Replay buffer › Saving more than one clip**
Only the first save of a running buffer produces a clip. Later saves show
"Saving the replay buffer…" at the bottom of the window for a few seconds,
then nothing is saved, until the buffer is restarted. Reported 2026-10-13.

**8b.**
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

**9.**
**Sonar › Hotkeys**
Hotkeys per channel for volume up, volume down, and switching to the next device.
Sonar's reference also has previous device and mute. On hold: the maintainer
said to leave keybinds out for now.

**10.**
**Sonar › Output**
Play the sound Sonar manages through two audio devices at the same time.

**11.**
**Sonar › UI**
Overhaul the Sonar page's UI and UX, bringing items 5 and 7–10 together.
Keep Vertex Sonar's look rather than copying SteelSeries'.

**12.**
**Rail (left-hand menu) › Games / People**
Make the Games and People groups collapsible.

**13.**
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

---

## Notes

Decisions already made, and questions to settle when their item comes up.

**Documentation.** Don't touch the repo's documentation (README, `docs/`, the
screenshots in it) until the maintainer says so (2026-10-13). Screenshots
taken to check UI work are fine; they are never committed. Some of it is
already behind: README still says to set *Capture* to *Portal* if recording a
monitor fails, shows the old Recording page, and has people run `vertex
install-desktop` (still works, but no longer needed); `docs/ARCHITECTURE.md`
doesn't describe the monitor map, the primary-monitor fallback, the
"Restarting…" state, `recorder/presets.py`, the start-menu marker or the
recorded tracks no longer depending on Sonar (it still says channels are
ticked "In clips").

**Progress.** Done: 1–7 and 8a. Next: the bug 14, unless the maintainer says
otherwise.
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
gets a message. The questions below were answered by that:
- What each drop-down offers. Proposal: "None" (no track), the Vertex
  channels (Vertex Game, Chat, Media, Aux; Vertex Mic for the microphone) and
  the real devices. Defaults with Sonar on: Vertex Game, Vertex Chat, Vertex
  Mic.
- Whether the three drop-downs also replace the "Tracks without Sonar" text box,
  so the same three settings apply with Sonar on or off.
- Clips then have at most three tracks: Media and Aux only reach a clip when
  picked in one of the drop-downs. Confirm that's wanted.
- In 1.x, the config keys `game_device`, `chat_device` and `mic_device` were
  the devices recorded. 2.0 uses them for "Capture devices of older clips",
  which names the tracks of old clips. Decide whether the new drop-downs get
  their own keys under `recorder` (keeping that page as it is) or take those
  keys back.
- Ask for a Moments screenshot of its recording audio settings if there is one.

**Items 8a and 8b.** Earlier decision: one device manager for the outputs,
shared by every output channel, and one for the input. The chain link (8a)
changes that: linked, the outputs share one list as decided; unlinked, each
output channel has its own device. Each channel already has its own loopback,
so the audio side allows it. To settle:
- 8a (settled): the Output and Microphone drop-downs went; linking again
  takes the device of the channel whose link was clicked.
- 8b: unlinked, does each output channel get its own priority and excluded
  lists (a tab per channel), or only its own current device?
- 8b: SteelSeries also has "Backup device switch" (Manual/Auto: when the
  current device goes away, move to the next one in the priority list), with
  an option to apply it at boot. Include it? Vertex already moves to another
  output when the device disappears; the priority list would decide which.
  Its "auto-switch when the Nova Wireless headset is powered off" option is
  specific to one headset and stays out.

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

**Item 11.** The sideways scrolling at the minimum window width (980 px) is
gone since 8a: Aux went and the columns may be a little narrower.

**Item 7 (done).** A drop is remembered as a routing rule; right-click → "Use
the default channel" removes it. Apps playing straight to a device appear
under "Not routed". The Mic list is read-only and flags apps recording a
microphone directly.
