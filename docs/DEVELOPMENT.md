# Development

## Setting up

You need the system packages from the [README](../README.md#install) and
Python 3.10+.

```bash
git clone https://github.com/StellarGalaxyAtlas/vertex.git && cd vertex
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
vertex
```

## Checks

```bash
ruff check src tests tools
xvfb-run -a python -m pytest                      # UI tests included
VERTEX_TEST_PIPEWIRE=1 python -m pytest -m pipewire  # against your audio server
```

Tests never touch your real config or library. Sonar is tested against a fake
`pactl` (`tests/fake_pactl.py`), GPU Screen Recorder against a stand-in
script, and OBS against a stand-in obs-websocket server (`tests/fake_obs.py`).
The PipeWire tests create and remove `vertex_*` devices on your running
server; run them when nothing important is playing.

Everything runs on Linux. `tests/test_windows.py` and `tests/test_obs.py`
switch the Windows branches on (`platform.WINDOWS`), and a test without Sonar
asks for the `no_sonar` fixture. CI runs the Windows tests and the
platform-neutral ones on Windows too.

`tools/` takes screenshots against fakes: `docs_screenshots.py` retakes the
README's from a made-up demo library.

## Rules

- Only `vertex.ui` imports Qt. Logic goes in the other packages, tested
  there, and is called from a controller in `ui/services.py`.
- What differs between Linux and Windows lives in `vertex/platform/`
  (`linux.py` and `windows.py`, the same names in each, listed in `NAMES`);
  nothing else checks which system it runs on, and a test fails if it does.
  Sonar exists where `platform.SONAR` says; in the UI, `context.sonar` is
  None without it.
- Never block the UI thread: blocking work (ffmpeg, pactl, the recorder,
  disk) goes through `ui/workers.run`.
- Never modify a user's recordings. New files are written under a hidden
  staging name and moved into place when complete.
- Colors come from the tokens in `ui/theme.py`, never a new hex value.
- A config addition needs a default that keeps older config files loading,
  and a place in `setting_groups.py` (what a backup restore offers); a test
  checks that every setting has one.
- A folder another program writes to or reads from (ffmpeg, OBS, Explorer)
  is made with `paths.make_dir` and handed over as `paths.real(...)`: a
  Python packaged as a Windows app keeps what it makes in AppData in a
  private copy the others don't see.

## Layout

| Package | What's in it |
|---|---|
| `core` | clips on disk: scanning, file-name parsing (`name_patterns`: presets and taught patterns), importing, Trash |
| `library` | the SQLite library (`library.db`, schema version 2) |
| `media` | ffmpeg/ffprobe: probing, track roles and names, mixing, waveforms, trims, exports, thumbnails |
| `audio` | Sonar (Linux): channels, a `pactl` wrapper, device lists, level meters, the device manager |
| `recorder` | the replay buffer: `backend` picks GPU Screen Recorder (`gsr`, `replay`, `notifier`) or OBS (`obs`, `obsws`, `obs_replay`); monitors and presets for both |
| `platform` | what differs between Linux and Windows: folders, the menu entry and autostart, hotkeys, the game being played (Steam, the full-screen window), which recorder |
| `backup`, `setting_groups` | backups: export, daily backups, restore by setting |
| `hotkeys` | global hotkeys (Windows): their text form, and holding them with `RegisterHotKey` |
| `ui` | the PySide6 app: pages, editor, dialogs, settings, tray, theme |
| `cli`, `ipc`, `control` | the `vertex` command, the control socket and its API |
| `notifications`, `logs`, `desktop`, `kwin`, `doctor`, `paths` | notification kinds, log files, start menu entry, raising the window on KDE, checks, where things go |

**Sonar** is built from stock modules that PipeWire's pulse server and
PulseAudio both have: a `module-null-sink` per output channel, a
`module-loopback` from each channel to the real device, and a
`module-remap-source` for Vertex Mic. `Sonar.up()` reconciles rather than
creates: it keeps what matches, replaces what is wrong and removes
duplicates, so it is safe after a crash or an audio server restart.
Loopbacks use `sink_dont_move` so an unplugged device can't make a channel
feed itself.

**Recording on Linux** runs GPU Screen Recorder as a child process that
never outlives Vertex. It saves with `SIGUSR1` (or `SIGRTMIN+n` for the last
N seconds) and reads saved paths from stdout. Each recorded channel is its
own titled track, which `media/tracks.py` names in the editor.

**Recording on Windows** drives OBS Studio over obs-websocket 5 (a small
stdlib client in `obsws.py`). Starting switches OBS's WebSocket server on in
its settings file while OBS is closed, starts OBS in the tray, and sets up
the "Vertex" profile (simple output mode, the replay buffer, one track per
part) and scene collection (the monitor, one WASAPI source per track).
Changed output settings take effect by loading the profile again, by way of
another one. OBS saves into the cache folder; each save is cut to the last N
seconds when asked, its tracks titled, and moved into the clips folder.

With recording switched off (`recorder.enabled`), Vertex never looks for or
starts either recorder.

## Control API

A running Vertex listens on `$XDG_RUNTIME_DIR/vertex/control.sock`. On
Windows it listens on a local port instead, written with a token to
`%LOCALAPPDATA%\Vertex\control.json`; requests carry the token as `"token"`.
Send one JSON object per line, get one back:

```
→ {"command": "volume", "args": {"channel": "chat", "action": "up"}}
← {"ok": true, "message": "Chat at 55%.", "data": {"channel": "chat", "volume": 55}}
```

| Command | Arguments |
|---|---|
| `ping`, `show`, `state`, `devices` | none |
| `save-clip` | `seconds`? (10, 30, 60, 300, 600, 1800) |
| `replay` | `action`: start, stop, toggle, status |
| `sonar` (Linux) | `action`: up, down, status |
| `volume` | `channel`, `action`: up, down, set; `value`?, `step`? |
| `mute` | `channel`, `action`?: on, off, toggle |
| `device` | `action`: next, previous, set; `channel`?, `name`? |
| `subscribe` | none: sends the state, then a line per change or notification |

`devices`, `volume`, `mute` and `device` are Sonar's, so Linux only.
Channels are `game`, `chat`, `media` and `mic`. Failed replies have
`"ok": false` and an `error` code. The full details, including the shape of
`state`, are in the docstring of `src/vertex/control.py`. Its `api` number
only goes up for changes that could break a client.

## Pull requests

Small, focused commits with a message that explains the change. For UI
changes, a screenshot helps a lot.
