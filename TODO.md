# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 79.

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

**68.** Bug
**Paths with / instead of \\**
Folders picked in Qt's dialogs come back as C:/Users/…, and parts of
Vertex compare or show them as they are. Normalise every path where it
enters Vertex (folder fields, the import dialogs, the config when loaded).

**69.** Bug
**No thumbnails in the library**
Find out why first: ffmpeg not on the PATH Vertex starts with, or a path
it can't read. Needs `vertex doctor`'s output and the logs from that PC.

**70.** Bug
**Cache, State and logs folders missing from AppData; capitalization**
Vertex creates them under %LOCALAPPDATA%\\Vertex on start. If they're not
there, the likeliest cause is the Microsoft Store Python, which redirects
AppData into its own package folder. To ask: which folders were seen
where, and which capitalization is expected.

**71.** Bug
**Startup apps lists Vertex as "pythonw.exe"**
The registry Run entry starts pythonw.exe, and Windows names it after
that. Use a "Vertex" shortcut in the Startup folder instead.

**72.** Bug
**No icon on the Start menu shortcut**

**73.** Bug
**The replay buffer doesn't start after first-run setup**
Even with "Start the replay buffer with Vertex" on.

### Importing clips

**74.** Bug
**Import skips subfolders**
Moments and Medal keep a folder per game: importing reads the folder and
everything under it.

**75.**
**Teach Vertex a clip app's file names**
Mockup: windows-port/mockups/1-file-names.png. When imported clips have
names Vertex doesn't know (Medal: MedalTV007FirstLight20260817235610725),
a step in first-run setup and in Settings › Import and setup lets the user
mark which part is the game, the date and the time, starting from known
apps (Medal, Moments, ShadowPlay, OBS, Game Bar), with a preview of what
Vertex reads from their own clips. Joined words in game names can be
split (FirstLight → First Light).

### Recording

**77.**
**A fourth track: Music**
Mockup: windows-port/mockups/3-recording-tracks.png. Optional, off until a
device is picked. The editor shows its lane only in clips that have it.

**78.**
**Recording volume per track**
Same mockup. A 0–100% slider per track in Settings › Recording, set as the
OBS source's volume, so clips play back right at 100%.

### Later

**67.**
**Hotkeys in Settings**
Vertex registers its own global hotkeys on Windows (save clip, save the last
30 seconds, start and stop the replay buffer, show Vertex), set with a key
picker in Settings › Shortcuts, in place of binding commands to keys.

## Decided

- No Sonar, and nothing about it in the UI. Stream Deck left out for now.
- This stays a separate repository from `vertex`.
- Imported clips' audio tracks stay as Vertex reads them now; no setting
  to say which track is which (dropped 76, 2026-10-20).
