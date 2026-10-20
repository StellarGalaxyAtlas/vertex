# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 80.

---

## Open

**66.**
**Record on Windows with OBS**
OBS Studio is the recorder on Windows, driven over obs-websocket (v5).
Vertex sets up the replay buffer from Settings › Recording (monitor, fps,
quality, buffer length, clip folder), starts and stops it, saves clips and
picks them up into the library like GSR's. Each track (Game, Chat, Mic)
records a device the user picks: they bring their own virtual devices,
whatever made them; Vertex makes none. OBS is not bundled: Vertex finds it
and says where to get it.
Decided: Vertex starts OBS in the tray when the buffer starts; keeps its own
"Vertex" profile and scene collection; switches OBS's WebSocket server on in
OBS's settings file while OBS is closed; "save the last 30 seconds" cuts the
save and keeps only the cut.
Built; first tried on a friend's Windows PC (2026-10-20), whose findings
are 68–78 below (76 dropped).

### Windows: fixes from the first install

**69.** Bug
**No thumbnails; Cache, State and logs missing from AppData**
Cause: a Python packaged as a Windows app (the Microsoft Store's) keeps the
folders it makes in AppData in a private copy, which OBS ("invalid path")
and ffmpeg don't see. Built (2026-10-20): Vertex has Windows make its
AppData folders, and hands other programs the real place of each;
`vertex doctor` shows which Python runs Vertex and where each folder really
is. To try on the friend's PC, and to ask which capitalization they saw.

**72.** Bug
**No icon on the Start menu shortcut or in the taskbar**
The Start menu entry is added when `vertex` first runs (pipx can't add
it). The icon was drawn for the apps' light theme, so a dark mark sat on
Windows' dark taskbar; it now follows the taskbar's theme
(2026-10-20). The shortcut's icon file may also have sat in the private
AppData copy (69). The taskbar still showed Python's logo: a packaged
Python files its windows under its own package, so the window now carries
Vertex's taskbar id itself (2026-10-20). To check on the friend's PC.

**73.** Bug
**The replay buffer doesn't start after first-run setup**
Even with "Start the replay buffer with Vertex" on.
Likely the same cause as 69: OBS called the save folder in Cache an
invalid path, so the buffer failed to start. To check after 69 is tried,
with the logs if it still doesn't start.

### Importing clips

**75.**
**Check the file-name presets against real clips**
Built (2026-10-20): presets plus marking up a name, in setup and Settings.
Medal, Moments, ShadowPlay and GPU Screen Recorder are proven; OBS (its
default naming), Game Bar and AMD Adrenalin follow written descriptions
of their names and say they're not checked. Game Bar's older names
(`Minecraft 5_18_2024 8_32_45 PM.mp4`) aren't read: no format code reads
an unpadded number or AM/PM.
Steam and Outplayed have no preset yet. Needs real file names from those
apps, and which app wrote `THE-FINALS2025-02-2816-49-17.mp4` (marking it up
reads it already).

### Recording and the editor

**77–79.**
**Media track, recording volume per track, playback volume in the editor**
Built (2026-10-20) as in mockups 2 and 3: an optional Media track (its own
lane, off until a device is picked; first called Music), a 0–100% recording volume per track
set on the OBS source, and a 0–300% playback volume in the editor. To try
on the friend's PC: that OBS records each track at its volume.

### Game tags

**80.**
**Game names: map a name Vertex reads to the tag it should be**
Built (2026-10-20) as option B of windows-port/mockups/7-game-names.png:
Rename… in the library's games menu retags the clips and, ticked, adds a
game name every automatic tag follows; Settings › Import and setup lists
them. Linux Vertex gets it with the port list.

**81.**
**Tag new clips with the fullscreen game on Windows**
Built (2026-10-20): the foreground window that fills its monitor, by its
title (else the program's name); a browser, Discord or video player, or
nothing fullscreen, is Desktop. To try on the friend's PC: games in
exclusive and borderless fullscreen.

**82.**
**"Tag games from file names" in Settings does nothing after setup**
Becomes "Read tags again" (picked 2026-10-20): read every clip's name again
with the apps list and game names, show what would change, ticked, and
apply. Mockup windows-port/mockups/8-read-tags-again.png (A: a dialog
per clip, B: under the apps list, grouped by game); waiting for the pick.

### Later

**67.**
**Hotkeys in Settings**
Built (2026-10-20) as in windows-port/mockups/5-hotkeys.png: Settings ›
Shortcuts records keys as they're pressed, held with Windows'
RegisterHotKey. To try on the friend's PC: that each hotkey works in a
game, and that keys another program holds are named.

## Decided

- No Sonar, and nothing about it in the UI. Stream Deck left out for now.
- This stays a separate repository from `vertex`.
- Imported clips' audio tracks stay as Vertex reads them now; no setting
  to say which track is which (dropped 76, 2026-10-20).
