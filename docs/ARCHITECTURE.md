# Architecture

Vertex is a Python application in one package, `vertex`, split by concern.
Everything except `vertex.ui` is free of Qt and can be imported, used and
tested on its own.

```
src/vertex/
├── __init__.py        version, APP_NAME, APP_ID
├── cli.py             the `vertex` command
├── ipc.py             control socket: single instance + `vertex save-clip` & co.
├── desktop.py         .desktop entry, icons, autostart
├── doctor.py          `vertex doctor`
├── config.py          config.json: paths, RecorderConfig, SonarConfig
├── paths.py           XDG directories and bundled assets
├── fmt.py, proc.py    formatting and subprocess helpers
├── core/              clips on disk
│   ├── clips.py       Clip, scanning, sorting, filtering, staging names
│   ├── naming.py      game/date from file names, tag normalisation
│   ├── importing.py   copy plans and tag-import plans
│   └── storage.py     disk usage, delete-to-Trash
├── library/
│   └── database.py    SQLite library with versioned migrations
├── media/             ffmpeg/ffprobe
│   ├── probe.py       MediaInfo, AudioTrack
│   ├── mp4meta.py     MP4 track titles read from the file's own boxes
│   ├── tracks.py      which track is Game/Chat/Media/Aux/Mic
│   ├── mixing.py      mpv and ffmpeg mix graphs
│   ├── waveform.py    peak levels per lane
│   ├── trim.py        lossless trims, keyframe search
│   ├── export.py      sizing maths, two-pass commands, staged export job
│   └── thumbnails.py  thumbnail/preview cache
├── audio/             Sonar
│   ├── channels.py    the channel definitions (pure data)
│   ├── pulse.py       typed pactl wrapper + event watcher
│   └── sonar.py       device lifecycle, routing rules, reconciliation
├── recorder/          GPU Screen Recorder
│   ├── gsr.py         detection, capability listing, argv builder, validation
│   ├── monitors.py    GSR's monitors placed where the desktop has them
│   └── replay.py      the replay-buffer child process
└── ui/                PySide6
    ├── app.py         QApplication, control commands, startup
    ├── services.py    Context + controllers (thumbnails, Sonar, recorder)
    ├── workers.py     run blocking work off the UI thread
    ├── main_window.py, rail.py, tray.py, first_run.py, sonar_view.py
    ├── library/       state (filter/sort/edits), model, delegate, view
    ├── editor/        mpv render widget, timeline, mixer rows, editor view
    ├── dialogs/       tags, export, import
    ├── settings/      the Settings page and its monitor map
    ├── theme.py, icons.py, widgets.py
```

## Threading

The UI thread only paints and reacts. Anything that blocks — ffmpeg, ffprobe,
pactl, scanning a slow disk — goes through `ui/workers.py`, which runs a
function on a worker thread and delivers its result to a callback on the UI
thread through a queued Qt signal. Every background job in the app uses that
one pattern.

- **Thumbnails, previews, durations**: a 3-thread pool in `ThumbnailService`,
  de-duplicated per clip.
- **Sonar**: a *single* worker thread (`SonarController`), so pactl commands
  run in the order they were issued. A dragged fader is coalesced into one
  pending value rather than hundreds of queued calls.
- **Waveforms**: one thread per open editor, decoding tracks one after another
  (the first lane appearing sooner matters more than all of them together).
- **The recorder** is a child process; its stdout/stderr are read by its own
  threads, which post state changes and saved-clip paths to the UI thread.
- **The control socket** is served on a background thread; each command is run
  on the UI thread through a blocking queued connection, and the reply goes
  back to the caller.

`vertex.library.Library` holds one SQLite connection, used only from the UI
thread.

## Sonar

Sonar is built from three stock modules, available in both PulseAudio and
PipeWire's pulse server:

| Module | Creates |
|---|---|
| `module-null-sink` | one virtual output per channel: `vertex_game`, `vertex_chat`, `vertex_media`, `vertex_aux` |
| `module-loopback` | plays each channel's `.monitor` into the real output device |
| `module-remap-source` | `vertex_mic`, a virtual input fed by the real microphone |

Applications play into a channel; the channel's own volume and mute apply; the
loopback carries it to the headset. A recorder captures `vertex_<id>.monitor`
(or `vertex_mic`) as one track per channel.

`Sonar.up()` **reconciles** rather than creates: it lists loaded modules,
recognises its own by their arguments (`sink_name=vertex_game`,
`source=vertex_game.monitor`, `source_name=vertex_mic`), keeps what matches,
replaces what points at the wrong device, and removes duplicates. That makes
it safe to run on every start, after a crash, or after the audio server
restarted (PipeWire happily creates a second node with the same name, so
blind creation would duplicate devices).

Points worth knowing:

- **Quoting.** Property lists are passed as
  `sink_properties='device.description="Vertex Game" …'`. Without the outer
  single quotes the module parser stops at the first space and the device is
  called "Vertex".
- **No feedback loops.** Loopbacks are loaded with `sink_dont_move=true`. When
  the output device disappears, the server unloads the loopback instead of
  moving it to the default sink — which is a Vertex channel, and would feed it
  back into itself. The `pactl subscribe` watcher sees the device go and
  `reconcile()` re-routes to another output.
- **Defaults.** `up()` remembers the system's default sink/source in
  `~/.local/state/vertex/sonar.json` before making the default channel and
  Vertex Mic the defaults; `down()` restores them. Automatic repairs
  (`reconcile`) don't retake defaults unless devices had to be recreated, so a
  default the user picked by hand is respected.
- **Routing rules** map an app key (the process binary, or the application
  name for generic hosts such as Electron) to a channel. They are applied to
  existing streams when set and to new streams as `sink-input` events arrive.
  Vertex's own loopback streams carry a `vertex.loopback` property and are
  never routed.
- **Event handling** ignores `change` events for repairs (setting a volume or
  a default emits them; reacting would chase its own tail) and debounces
  device add/remove events.

## Recording

`recorder/gsr.py` turns `RecorderConfig` into a GPU Screen Recorder command
line as a pure function, validated beforehand (`gsr.validate`). With Sonar on,
`audio_tracks()` yields one `-a` per recorded channel. GSR 5.15+ accepts
`name:<title>|device:<node>`, which titles the track "Vertex Game"; older
versions title it "Devices: Monitor of Vertex Game". `media/tracks.py`
recognises both, so labelling never depends on the recorder version.

What can be recorded comes from `gpu-screen-recorder --list-capture-options`
(`gsr.parse_capture_options`): each monitor by name with its size, plus the
portal, region, cameras and so on. GSR doesn't say where a monitor sits, so
`recorder/monitors.py` places GSR's monitors where the desktop has them, matched
by name; the UI passes the desktop's arrangement in as plain `Screen`s read from
Qt. Settings draws the result as a map to click, a vertical monitor standing
up. GSR decides what is listed; the desktop only says where.

`recorder/replay.py` runs GSR in its own session (signals reach a wrapper's
children too) with `PR_SET_PDEATHSIG`, so it never outlives Vertex. It saves
with `SIGUSR1` (whole buffer) or `SIGRTMIN+n` (last 10 s … 30 min), stops with
`SIGINT`, reads saved paths from stdout and reports the last stderr lines when
GSR exits unexpectedly. "Running" means the process stayed up past a short
settle period — GSR exits within a fraction of a second on bad settings.

## Track names in clips

`media/probe.py` names each audio stream from its tags (`name`, then `title`,
then a non-generic MP4 handler). FFmpeg before 7.0 doesn't report track-level
titles stored in an MP4 track's `udta/name` box, which is where GSR (and
ffmpeg's own muxer) puts them, so `media/mp4meta.py` reads those boxes directly
when ffprobe comes back empty. The library keys each track's saved volume by
this name, so its precedence must not change.

`media/tracks.py` labels tracks all-or-nothing: Vertex devices are matched
exactly; older clips by the capture devices named in Settings, then by device
name heuristics (inherited from 1.x); a mixed-down "game + chat" track is
*Desktop*. If any track can't be named, or two would share a name, they are
all numbered instead.

## Data formats

**config.json** — `Config.to_dict()`. The 1.x keys (`clip_path`, `data_path`,
`state_path`, `export_path`, `cache_path`, `game_device`, `chat_device`,
`mic_device`, `logo_variant`) are unchanged; `recorder` and `sonar` are
nested objects. Unknown or mistyped values fall back to defaults instead of
failing. Written atomically.

**library.db** — table `clips`, keyed by file name:

| Column | |
|---|---|
| `filename` | primary key, relative to the clips folder |
| `title`, `description` | display metadata (`''` = show the file name) |
| `game`, `people` | tag, and a JSON list of names |
| `favorite` | 0/1 |
| `trim_start`, `trim_end` | seconds, NULL = clip start/end |
| `volumes` | JSON `{track name: {"volume": 0..1.5, "muted": bool}}` |
| `duration`, `recorded` | cached probe result; recording date |
| `tag`, `updated` | legacy column; last write time |

`PRAGMA user_version` tracks the schema. Version 1 makes sure every column 1.x
added ad hoc exists; version 2 adds indexes. New migrations go at the end of
`MIGRATIONS` in `library/database.py`.

## Testing

`pytest` covers the Qt-free packages directly, with real ffmpeg runs against a
generated clip; Sonar against an in-memory fake of pactl (`tests/fake_pactl.py`)
and, when `VERTEX_TEST_PIPEWIRE=1`, against the running audio server; the
recorder against a stand-in GSR script that speaks the same flags, signals and
stdout. UI smoke tests run with Qt's offscreen platform; the editor test needs
OpenGL and runs under `xvfb-run` (as CI does).
