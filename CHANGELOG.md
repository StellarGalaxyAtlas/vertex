# Changelog

## Windows port — unreleased

Vertex on Windows 10 and 11, without Sonar.

### Removed
- **Sonar** and everything that referred to it: the Sonar page, the Home
  tile and quick mixer, the tray's device menus, its setup step, its
  notifications and log, and the `sonar`, `volume`, `mute`, `device` and
  `devices` commands (control API version 2).
- Tagging new clips with the game on the Game channel.
- The Stream Deck link on the Shortcuts page, for now.

### Changed
- On Windows, `vertex` typed in a terminal starts Vertex apart from it and
  returns, so closing the terminal doesn't quit Vertex.
- Enter in a confirmation takes what it asks for (Delete, Apply), not
  Cancel.
- A clip's tracks default to the default output (Game) and the default
  microphone (Mic); a Chat track is picked in Settings › Recording.

### Added
- Recording on Windows with OBS Studio 30+: Vertex starts OBS in the tray,
  switches on its WebSocket server, and keeps its own "Vertex" profile and
  scene. Each track records the device picked in Settings › Recording; the
  video quality is High or Ultra (OBS's own two levels). `vertex doctor`
  checks OBS and its WebSocket server.
- Windows folders: settings in `%APPDATA%\Vertex`, the library, logs and
  thumbnails in `%LOCALAPPDATA%\Vertex`, clips in the Videos folder. They are
  made where OBS and ffmpeg see them, also on the Microsoft Store's Python;
  `vertex doctor` says where each one is.
- The control channel over a token-guarded local port on Windows.
- Start menu shortcut and start at login (a "Vertex" shortcut in the Startup
  folder, starting `VertexApp.exe`, the name Windows lists it by) on Windows,
  removed by `vertex uninstall-desktop`.
- ffmpeg runs without console windows; Show in folder opens Explorer.
- The logo's ink follows the taskbar's theme, which Windows sets apart from
  the apps' one. The window is on the taskbar as Vertex, not as Python,
  also on the Microsoft Store's Python.
- Teaching Vertex a clip app's file names, in setup and in Settings › Import
  and setup: presets for Medal, SteelSeries Moments, NVIDIA ShadowPlay, Xbox
  Game Bar, OBS, AMD Adrenalin and GPU Screen Recorder, or a name marked up
  by hand, with a preview of what Vertex reads from your clips. Several
  apps can be listed, tried in turn, each with how many clips it reads; the
  next one is taught from the clips none reads yet. A game ending in a
  number keeps it when the date follows straight on (Medal's
  "Helldivers2" + "20260817…" is Helldivers 2, not Helldivers).
- Importing clips reads the folders inside the chosen one too (Moments and
  Medal keep a folder per game), with a list to leave folders out.
- Hotkeys on Windows, set in Settings › Shortcuts by pressing them: save a
  clip, save the last part of the buffer, start or stop the replay buffer,
  show Vertex. Keys another program holds are named on their row.
- A Media track (music, videos), off until a device is picked, and a
  recording volume per track (on Windows, set on the track's OBS source). Setup picks each
  track's device and volume too.
- A playback volume in the editor, 0–300%, kept between clips; the clip, its
  mix and exports stay as they are.
- On Windows, a saved clip is tagged with the game filling the screen (its
  window's title), or Desktop when none does; a switch in Settings ›
  Recording.
- Renaming a game from the library's games menu (right-click, or F2):
  its clips are retagged, merging into a game you already have, and new
  clips get the new name too. Settings › Import and setup lists the renames.
- A Windows job in CI.

## 2.0.0 — unreleased

A rewrite of the application around a GUI-free core, with recording and Sonar
added.

### Added
- **Sonar**: virtual Game, Chat, Media and Aux outputs and a Vertex Mic input on
  PipeWire/PulseAudio, with per-channel volume and mute, output and microphone
  selection, and remembered per-app routing.
- **Recording** through GPU Screen Recorder's replay buffer, with every recorder
  option in Settings, a live command preview, `vertex save-clip` for desktop
  hotkeys, and a tray menu.
- Every Sonar channel recorded as its own consistently named track, so every new
  clip has the same audio layout.
- New clips can be tagged with the game playing on the Game channel.
- `vertex` command with `save-clip`, `replay`, `sonar`, `doctor`,
  `install-desktop` and `uninstall-desktop`; single-instance control socket.
- Tray icon, start at login, and keep running when the window is closed.
- Export sheet: 10 MB tier and copying the exported file to the clipboard.
- Editor: frame stepping, Shift-seek, I/O and Home/End keys, full screen.
- Track names read from MP4 boxes when the installed ffprobe can't see them.
- Packaging with `pyproject.toml` (installable with pipx), tests and CI.

### Changed
- UI rebuilt on Qt 6 (PySide6). Runs natively on Wayland; video renders through
  mpv's render API instead of an embedded X11 window.
- The library grid is a virtualised list view; thumbnails load on demand.
- `.mkv` clips are listed alongside `.mp4`.
- Clips named `Replay_…` are no longer tagged *Desktop* automatically.
- Library schema is versioned (`PRAGMA user_version`); 1.x libraries upgrade in
  place.

### Removed
- The custom `install.py`, replaced by pipx and `vertex install-desktop`.
- Adoption of configs and libraries from the app's pre-1.0 names.
- CustomTkinter, Pillow and the X11 error-handler workaround.
