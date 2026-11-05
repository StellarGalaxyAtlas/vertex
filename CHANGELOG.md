# Changelog

## 2.0.0 — unreleased

A rewrite of the application around a GUI-free core, with recording and Sonar
added, for Linux and Windows.

### Added
- **Windows 10 and 11**, from the same package: recording with OBS Studio 30+
  (Vertex starts it in the tray and keeps a profile and scene of its own),
  hotkeys set in Settings › Shortcuts, new clips tagged with the full-screen
  game, Windows folders, Start menu shortcut and autostart. Sonar stays on
  Linux.
- **Backups**: Settings › Backup exports the settings and library to one
  file, keeps a daily one (the last five) and restores what you pick, down to
  single settings; `vertex backup export|import` from a terminal.
- Recording can be switched off, in setup and Settings, to use Vertex only for
  the clips you have.
- Selecting several clips in the library to favorite, tag, export or delete
  them together.
- A recording volume per track.
- **Sonar**: virtual Game, Chat, Media and Aux outputs and a Vertex Mic input on
  PipeWire/PulseAudio, with per-channel volume and mute, output and microphone
  selection, and remembered per-app routing.
- **Recording** through GPU Screen Recorder's replay buffer, with every recorder
  option in Settings, a live command preview, `vertex save-clip` for desktop
  hotkeys, and a tray menu.
- Every Sonar channel recorded as its own consistently named track, so every new
  clip has the same audio layout.
- New clips can be tagged with the game playing on the Game channel, and are
  then named after it the way Moments names clips
  (`Heroes-of-the-Storm__2026-10-20__21-00-00.mp4`); with no game there,
  they are tagged Desktop.
- `vertex` command with `save-clip`, `replay`, `sonar`, `doctor`,
  `install-desktop` and `uninstall-desktop`; single-instance control socket.
- Tray icon, start at login, and keep running when the window is closed.
- Export sheet: 10 MB tier and copying the exported file to the clipboard.
- Editor: frame stepping, Shift-seek, I/O and Home/End keys, full screen.
- Track names read from MP4 boxes when the installed ffprobe can't see them.
- Packaging with `pyproject.toml` (installable with pipx), tests and CI.
- Teaching Vertex a clip app's file names, in setup and in Settings › Import
  and setup: presets for Medal, SteelSeries Moments, NVIDIA ShadowPlay, Xbox
  Game Bar, OBS, AMD Adrenalin and GPU Screen Recorder, or a name marked up
  by hand, with a preview of what Vertex reads from your clips. Several
  apps can be listed, tried in turn; a game ending in a number keeps it
  (Medal's "Helldivers2" + date is Helldivers 2).
- Under the apps, what reading the clips' names again would change, one
  ticked line per game (old → new, opening to its clips), applied at once.
- Importing clips reads the folders inside the chosen one too (Moments and
  Medal keep a folder per game), with a list to leave folders out.
- A Media track, recording Sonar's Media channel. Setup picks each track's
  device too.
- A playback volume in the editor, 0–300%, kept between clips; the clip, its
  mix and exports stay as they are.
- Renaming a game from the library's games menu (right-click, or F2): its
  clips are retagged, merging into a game you already have, and new clips
  get the new name too, also when tagged from the Game channel. Settings ›
  Import and setup lists the renames.
- `vertex doctor` names the Python Vertex runs on, and a failed thumbnail
  logs ffmpeg's error.

### Changed
- UI rebuilt on Qt 6 (PySide6). Runs natively on Wayland; video renders through
  mpv's render API instead of an embedded X11 window.
- The library grid is a virtualised list view; thumbnails load on demand.
- `.mkv` clips are listed alongside `.mp4`.
- Clips named `Replay_…` are no longer tagged *Desktop* automatically.
- Enter in a confirmation takes what it asks for (Delete, Apply), not Cancel.
- The clip-saved notification says the clip is in your library instead of
  naming its file.
- Settings' folder fields show the real default clips and exports folders.
- Library schema is versioned (`PRAGMA user_version`); 1.x libraries upgrade in
  place.

### Removed
- The custom `install.py`, replaced by pipx and `vertex install-desktop`.
- Adoption of configs and libraries from the app's pre-1.0 names.
- CustomTkinter, Pillow and the X11 error-handler workaround.
