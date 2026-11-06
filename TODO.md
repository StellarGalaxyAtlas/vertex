# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 87.

---

## Open

### To try on Windows

Built on Linux against stand-ins; only a Windows PC proves them.

**66.**
**Record with OBS**
That the replay buffer starts (also right after setup, and with "Start the
replay buffer with Vertex"), saves clips, cuts "save the last 30 seconds",
and records each track at its volume (77–79). Switching recording off closes
an OBS that Vertex started, and only that one.

**69, 72.**
**Folders and the taskbar on the Microsoft Store's Python**
That Cache, State and logs are where OBS and ffmpeg see them (`vertex doctor`
says where each one is), and that the Start menu shortcut and the taskbar
show Vertex's icon, not Python's.

**67, 81.**
**Hotkeys and the full-screen game tag**
That each hotkey works in a game and keys another program holds are named;
that a clip saved in a game, in exclusive and borderless full screen, is
tagged with it.

### To try on Linux

**86.**
**The game tag without Sonar**
With Sonar off, a clip saved in a Steam game is tagged with its store name;
one saved in another full-screen game (Lutris, Heroic, native) with its
window title; one saved on the desktop Desktop. Untried: that the desktop
clears XWayland's active window when a Wayland window is in front, and
that Steam names the game in its `reaper` process.

### Importing clips

**75.**
**Check the file-name presets against real clips**
Medal, Moments, ShadowPlay and GPU Screen Recorder are proven; OBS (its
default naming), Game Bar and AMD Adrenalin follow written descriptions of
their names. Game Bar's older names (`Minecraft 5_18_2024 8_32_45 PM.mp4`)
aren't read. Steam and Outplayed have no preset yet. Needs real file names
from those apps, and which app wrote `THE-FINALS2025-02-2816-49-17.mp4`.

## Decided

- One package for Linux and Windows. Sonar, the Stream Deck plugin and
  notifications over games are Linux only; hotkeys in Settings are
  Windows only. The game tag works without Sonar on both.
- Imported clips' audio tracks stay as Vertex reads them; no setting to say
  which track is which.
