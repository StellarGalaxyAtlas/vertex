# To-Do

One item at a time, top to bottom unless we decide otherwise.

---

**1.**
**Settings › Recording › Video › Capture**
Add a preview for choosing the monitor. If that turns out to be too difficult, at
least offer a drop-down with every capture option GPU Screen Recorder reports
(each monitor by name, focused monitor/window, portal, region, …).

**2.**
**Settings › Recording**
- Show only the basic settings; move everything else into a collapsible
  "Advanced" section.
- Rename "Replay buffer" to "Recording Settings".
- "Keep the last" becomes "Duration", a drop-down with 15, 30, 45, 60, 90 and
  120 seconds.
- Bitrate is a basic setting.
- Show an estimate of how much space one clip takes with the current settings,
  and roughly how many clips fit on the current disk.
- "Save clips to" shows the clips folder configured under General.
- "Record cursor" moves into Recording Settings.
- Controls look and behave the same across all settings pages.

**3.**
**Settings › General › Start menu entry**
The start-menu entry should be created by default instead of being a setting,
and the entry is named just "Vertex".

**4.**
**Settings › Recording › Audio**
Three drop-downs choose what goes into clips, one track each:
- Game audio device
- Chat audio device
- Microphone input

This replaces choosing tracks on the Sonar page (see 5). Media is no longer
recorded by default because it is not one of the three; that was this item's
old aim ("Media not in clips by default"). Questions in the Notes.

**5.**
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

**8a.**
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

**Progress.** Done: 6 and 7. Next: 1, unless the maintainer says otherwise.
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

**Order.** Do item 13 before or together with item 9. Any action exposed as a
`vertex …` command can be bound to a desktop keyboard shortcut, which is the
simplest reliable way to get global hotkeys on Wayland.

**Item 4.** To settle before building:
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
- 8a: once each channel shows its device, do the Output and Microphone
  drop-downs in the Devices section (item 6) go? "Unrouted apps" would stay.
- 8a: when the channels are linked again after being set separately, which
  device do they all take? Proposal: the one on the channel whose link was
  clicked.
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

**Item 11.** At the minimum window width (980 px) the five channel columns
don't fit and the Sonar page scrolls sideways. Fix as part of the overhaul.

**Item 7 (done).** A drop is remembered as a routing rule; right-click → "Use
the default channel" removes it. Apps playing straight to a device appear
under "Not routed". The Mic list is read-only and flags apps recording a
microphone directly.
