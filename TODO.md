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
**Sonar › Media**
Media is not recorded into clips by default ("In clips" off).

**5.**
**Sonar › Channels**
Rename the checkbox under each channel ("In clips") to something more intuitive.

**6.**
**Sonar › Devices**
Move the explanations for "Output", "Microphone" and "Unrouted apps" from the
right-hand side to directly above or below their drop-downs, possibly
colour-coded.

**7.** ✅ Done
**Sonar › Channels**
- Under each channel, list the apps currently playing through it, updating live
  as apps start and stop.
- Under the microphone, list the apps currently recording from it.
- Drag and drop an app from one channel to another, taking effect immediately.
- Decided: a drop is remembered (right-click → "Use the default channel" undoes it);
  apps that play straight to a device appear in a "Not routed" section; the Mic
  list is read-only and flags apps recording a mic directly.

**8.**
**Sonar › Device manager**
A device manager like SteelSeries Sonar's. Two buttons on the Sonar page, one
for the output devices (shared by all output channels) and one for the input,
each open a panel over the page:
- An ordered list of devices, reordered by dragging. The current device is
  marked and has its own volume; the ones before and after it are "previous"
  and "next", the order device hotkeys cycle through.
- An "Excluded devices" column for devices kept out of the cycle.
- The format (e.g. 24 bit / 96 kHz), shown for information.
- Shortcuts: previous/next device, volume up/down, mute (see 9).

**9.**
**Sonar › Hotkeys**
Hotkeys per channel for volume up, volume down, and switching to the next device.
Sonar's reference also has previous device and mute (see 8).

**10.**
**Sonar › Output**
Play the sound Sonar manages through two audio devices at the same time.

**11.**
**Sonar › UI**
Overhaul the Sonar page's UI and UX, bringing items 4–10 together.

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

**Order.** Do item 13 before or together with item 9. Any action exposed as a
`vertex …` command can be bound to a desktop keyboard shortcut, which is the
simplest reliable way to get global hotkeys on Wayland.

**Item 8.** Not one device manager per channel: one for the outputs (shared by
every output channel, as now) and one for the input.

**Item 9.** Since the output device list is shared, "next device" switches all
channels at once, while volume up/down and mute are per channel. Confirm this
with the maintainer before building it.

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

**Item 7 (done).** A drop is remembered as a routing rule; right-click → "Use
the default channel" removes it. Apps playing straight to a device appear
under "Not routed". The Mic list is read-only and flags apps recording a
microphone directly.
