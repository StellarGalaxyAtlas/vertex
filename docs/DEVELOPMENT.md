# Development

## Setting up

You need the system packages from the [README](../README.md#install) and
Python 3.10+.

```bash
git clone https://github.com/StellarGalaxyAtlas/vertex-windows.git && cd vertex-windows
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
vertex
```

## Checks

```bash
ruff check src tests tools
xvfb-run -a python -m pytest                      # UI tests included
```

Tests never touch your real config or library. The recorder is tested
against a stand-in GPU Screen Recorder script, and OBS against a stand-in
obs-websocket server (`tests/fake_obs.py`). `tests/test_windows.py` and
`tests/test_obs.py` run the Windows branches from any platform; on Windows
itself CI runs those and the platform-neutral tests (the UI, media and GSR
tests still assume Linux).

`tools/` takes screenshots against fakes: `docs_screenshots.py` retakes the
README's from a made-up demo library.

## Rules

- Only `vertex.ui` imports Qt. Logic goes in the other packages, tested
  there, and is called from a controller in `ui/services.py`.
- Never block the UI thread: blocking work (ffmpeg, the recorder, disk) goes through
  `ui/workers.run`.
- Never modify a user's recordings. New files are written under a hidden
  staging name and moved into place when complete.
- Colors come from the tokens in `ui/theme.py`, never a new hex value.
- A config addition needs a default that keeps older config files loading.
- Platform differences go through `vertex.system` (`system.WINDOWS`, the
  Windows API calls), not checks of their own.
- A folder another program writes to or reads from (ffmpeg, OBS, Explorer)
  is made with `paths.make_dir` and handed over as `paths.real(...)`: a
  Python packaged as a Windows app keeps what it makes in AppData in a
  private copy the others don't see.

## Layout

| Package | What's in it |
|---|---|
| `core` | clips on disk: scanning, file-name parsing, importing, Trash |
| `library` | the SQLite library (`library.db`, schema version 2) |
| `media` | ffmpeg/ffprobe: probing, track roles and names, mixing, waveforms, trims, exports, thumbnails |
| `recorder` | the replay buffer: `backend` picks GPU Screen Recorder (`gsr`, `replay`, `gsr-notify`) or OBS (`obs`, `obsws`, `obs_replay`); monitors and presets for both |
| `ui` | the PySide6 app: pages, editor, dialogs, settings, tray, theme |
| `cli`, `ipc`, `control` | the `vertex` command, the control socket and its API |
| `notifications`, `logs`, `desktop`, `kwin`, `doctor` | notification kinds, log files, start menu entry and autostart, raising the window on KDE, checks |
| `system`, `paths` | what differs on Windows; where settings, data and logs go |

**Recording** (Linux) runs GPU Screen Recorder as a child process that never
outlives Vertex. It saves with `SIGUSR1` (or `SIGRTMIN+n` for the last N
seconds) and reads saved paths from stdout. Each recorded part (game, chat,
mic) is its own titled track, which `media/tracks.py` names in the editor.

**Recording** (Windows) drives OBS Studio over obs-websocket 5 (a small
stdlib client in `obsws.py`). Starting switches OBS's WebSocket server on in
its settings file while OBS is closed, starts OBS in the tray, and sets up
the "Vertex" profile (simple output mode, the replay buffer, one track per
part) and scene collection (the monitor, one WASAPI source per track).
Changed output settings take effect by loading the profile again, by way of
another one. OBS saves into the cache folder; each save is cut to the last N
seconds when asked, its tracks titled, and moved into the clips folder.

## Control API

A running Vertex listens on `$XDG_RUNTIME_DIR/vertex/control.sock`. On
Windows it listens on a local port instead, written with a token to
`%LOCALAPPDATA%\Vertex\control.json`; requests carry the token as `"token"`.
Send one JSON object per line, get one back:

```
→ {"command": "replay", "args": {"action": "toggle"}}
← {"ok": true, "message": "Starting the replay buffer.", "data": {"state": "starting"}}
```

| Command | Arguments |
|---|---|
| `ping`, `show`, `state` | none |
| `save-clip` | `seconds`? (10, 30, 60, 300, 600, 1800) |
| `replay` | `action`: start, stop, toggle, status |
| `subscribe` | none: sends the state, then a line per change or notification |

Failed replies have `"ok": false` and an `error` code. The full details, including the shape of
`state`, are in the docstring of `src/vertex/control.py`. Its `api` number
only goes up for changes that could break a client.

## Pull requests

Small, focused commits with a message that explains the change. For UI
changes, a screenshot helps a lot.
