# Control API

A running Vertex can be controlled by other programs: a Stream Deck plugin, a
desktop shortcut, a script. The `vertex` command uses the same API, so
anything below can also be done from a terminal (see `vertex --help`).

## The socket

Vertex listens on a Unix socket at `$XDG_RUNTIME_DIR/vertex/control.sock`.
Each request is one JSON object on one line, and so is each reply:

```
→ {"command": "volume", "args": {"channel": "chat", "action": "up"}}
← {"ok": true, "message": "Chat at 55%.", "data": {"channel": "chat", "volume": 55}}
```

Every reply has `ok` and `message` (a sentence for people). Replies with
something to report carry it in `data`; failed ones carry an `error` code:

| Error | Meaning |
|---|---|
| `unknown_command` | no such command |
| `bad_argument` | a missing or invalid argument (the message says which) |
| `replay_off` | the replay buffer isn't running (saving a clip) |
| `sonar_off` | Sonar is off (volumes, mutes, devices) |
| `no_device` | no other device to switch to |
| `failed` | anything else; the message says what |

A quick try from a shell:

```bash
echo '{"command": "state"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/vertex/control.sock
```

## Commands

| Command | Arguments | Does |
|---|---|---|
| `ping` | | replies with `api` and `version` |
| `show` | | brings the window to the front |
| `state` | | replies with the state (below) |
| `save-clip` | `seconds`? (10, 30, 60, 300, 600 or 1800) | saves the replay buffer, or only its end |
| `replay` | `action`: start, stop, toggle, status | the replay buffer |
| `sonar` | `action`: up, down, status | turns Sonar on or off |
| `volume` | `channel`, `action`: up, down, set; `value`? (0-100, for set); `step`? (default 5) | a channel's volume |
| `mute` | `channel`, `action`?: on, off, toggle (default) | a channel's mute |
| `device` | `action`: next, previous, set; `channel`?; `name`? (for set) | switches the output device or microphone |
| `devices` | | lists outputs and microphones (below) |
| `subscribe` | | keeps the connection open and sends events (below) |

**Channels** are `game`, `chat`, `media` and `mic`. Volumes are percentages,
as the Sonar page shows them. `mute mic` mutes Vertex Mic: everything
recording it hears silence.

**Devices.** `device next` picks the next connected device in the device
list's order, skipping excluded ones, for now: until a device is plugged in or
out. The list's order is left alone. With no channel it moves every output
channel; with the output channels unlinked, naming a channel moves that one
alone; `mic` cycles microphones. `device set` switches to the device `name`
the same way, as picking it on the Sonar page does.

`devices` lists outputs and microphones in the device list's order, the ones
not on the list yet last:

```json
{"outputs": [{"name": "alsa_output…", "description": "Headset",
              "connected": true, "excluded": false}],
 "mics": []}
```

## State

`state` describes everything a button face may show:

```json
{"api": 1,
 "replay": {"state": "running", "running": true, "seconds": 60},
 "sonar": {"enabled": true, "active": true, "linked": true,
           "output": {"name": "alsa_output…", "description": "Headset"},
           "output_picked": false, "mic": {"name": "…", "description": "…"},
           "mic_picked": false,
           "channels": {"game": {"name": "Game", "volume": 100,
                                 "muted": false, "device": {"name": "…", "description": "…"}}}}}
```

`replay.state` is `stopped`, `starting`, `running`, `restarting` or `failed`.
A device is `null` when there is none (Sonar off, nothing plugged in).
`output_picked` and `mic_picked` say a device was picked by hand rather than
by the list.

## Events

`subscribe` answers like `state`, then keeps the connection open and sends
one line per event until the client hangs up:

```
{"event": "state", "data": {…the state…}}        whenever it changes
{"event": "notice", "data": {"kind": "clip_saved", "category": "clips",
                             "title": "Clip saved", "body": "…"}}
```

Notices are the notifications Vertex shows (kinds are listed in
`src/vertex/notifications.py`), whether or not their pop-up is switched on.
`vertex watch` prints the same stream.

## Versions

`api` goes up when a change could break a client: a field removed or renamed,
or a meaning changed. New commands, fields and events don't change it.
