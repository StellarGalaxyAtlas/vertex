# Development

## Setting up

You need the system packages from the [README](../README.md#install) and
Python 3.10+.

```bash
git clone https://github.com/StellarGalaxyAtlas/vertex.git && cd vertex
python -m venv .venv && source .venv/bin/activate
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
`pactl` (`tests/fake_pactl.py`), the recorder against a stand-in GPU Screen
Recorder script. The PipeWire tests create and remove `vertex_*` devices on
your running server; run them when nothing important is playing.

`tools/` takes screenshots against fakes: `docs_screenshots.py` retakes the
README's from a made-up demo library.

## Rules

- Only `vertex.ui` imports Qt. Logic goes in the other packages, tested
  there, and is called from a controller in `ui/services.py`.
- Never block the UI thread: blocking work (ffmpeg, pactl, disk) goes through
  `ui/workers.run`.
- Never modify a user's recordings. New files are written under a hidden
  staging name and moved into place when complete.
- Colors come from the tokens in `ui/theme.py`, never a new hex value.
- A config addition needs a default that keeps older config files loading.

## Layout

| Package | What's in it |
|---|---|
| `core` | clips on disk: scanning, file-name parsing, importing, Trash |
| `library` | the SQLite library (`library.db`, schema version 2) |
| `media` | ffmpeg/ffprobe: probing, track names, mixing, waveforms, trims, exports, thumbnails |
| `audio` | Sonar: channels, a `pactl` wrapper, device lists, level meters, the device manager |
| `recorder` | GPU Screen Recorder: detection, command building, monitors, presets, the replay buffer, `gsr-notify` |
| `ui` | the PySide6 app: pages, editor, dialogs, settings, tray, theme |
| `cli`, `ipc`, `control` | the `vertex` command, the control socket and its API |
| `notifications`, `logs`, `desktop`, `kwin`, `doctor` | notification kinds, log files, start menu entry, raising the window on KDE, checks |

**Sonar** is built from stock modules that PipeWire's pulse server and
PulseAudio both have: a `module-null-sink` per output channel, a
`module-loopback` from each channel to the real device, and a
`module-remap-source` for Vertex Mic. `Sonar.up()` reconciles rather than
creates: it keeps what matches, replaces what is wrong and removes
duplicates, so it is safe after a crash or an audio server restart.
Loopbacks use `sink_dont_move` so an unplugged device can't make a channel
feed itself.

**Recording** runs GPU Screen Recorder as a child process that never
outlives Vertex. It saves with `SIGUSR1` (or `SIGRTMIN+n` for the last N
seconds) and reads saved paths from stdout. Each recorded channel is its own
titled track, which `media/tracks.py` names in the editor.

## Control API

A running Vertex listens on `$XDG_RUNTIME_DIR/vertex/control.sock`. Send one
JSON object per line, get one back:

```
→ {"command": "volume", "args": {"channel": "chat", "action": "up"}}
← {"ok": true, "message": "Chat at 55%.", "data": {"channel": "chat", "volume": 55}}
```

| Command | Arguments |
|---|---|
| `ping`, `show`, `state`, `devices` | none |
| `save-clip` | `seconds`? (10, 30, 60, 300, 600, 1800) |
| `replay` | `action`: start, stop, toggle, status |
| `sonar` | `action`: up, down, status |
| `volume` | `channel`, `action`: up, down, set; `value`?, `step`? |
| `mute` | `channel`, `action`?: on, off, toggle |
| `device` | `action`: next, previous, set; `channel`?, `name`? |
| `subscribe` | none: sends the state, then a line per change or notification |

Channels are `game`, `chat`, `media` and `mic`. Failed replies have
`"ok": false` and an `error` code. The full details, including the shape of
`state`, are in the docstring of `src/vertex/control.py`. Its `api` number
only goes up for changes that could break a client.

## Pull requests

Small, focused commits with a message that explains the change. For UI
changes, a screenshot helps a lot.
