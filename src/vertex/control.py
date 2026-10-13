"""The control API: what outside software can ask the running Vertex.

A Stream Deck plugin, a desktop shortcut or a script talks to Vertex through
the control socket, `$XDG_RUNTIME_DIR/vertex/control.sock` (see `ipc`). Each
request is one JSON object on one line, and so is each reply:

    → {"command": "volume", "args": {"channel": "chat", "action": "up"}}
    ← {"ok": true, "message": "Chat at 55%.", "data": {"channel": "chat", "volume": 55}}

Every reply has `ok` and `message` (a sentence for people). Replies with
something to report carry it in `data`; failed ones carry an `error` code:

    unknown_command   no such command
    bad_argument      a missing or invalid argument (the message says which)
    replay_off        the replay buffer isn't running (saving a clip)
    sonar_off         Sonar is off (volumes, mutes, devices)
    no_device         no other device to switch to
    failed            anything else; the message says what

Commands, with their arguments:

    ping                                      data: api, version
    show                                      bring the window to the front
    state                                     data: the state (below)
    save-clip    seconds?                     10, 30, 60, 300, 600 or 1800
    replay       action: start|stop|toggle|status
    sonar        action: up|down|status
    volume       channel, action: up|down|set, value? (set: 0-100), step? (5)
    mute         channel, action?: on|off|toggle (toggle)
    device       action: next|previous, channel?
    subscribe    keeps the connection open; see below

Channels are game, chat, media and mic. Volumes are percentages, 0-100, as
the Sonar page shows them. `mute mic` mutes Vertex Mic: everything recording
it hears silence. `device` picks the next connected device in the device
manager's priority list (skipping excluded ones) and puts that list in
Manual mode. With no channel it moves every output channel; with the output
channels unlinked, a channel moves that one alone; `mic` cycles microphones.

`state` describes everything a button face may show:

    {"api": 1,
     "replay": {"state": "running", "running": true, "seconds": 60},
     "sonar": {"enabled": true, "active": true, "linked": true,
               "output": {"name": "alsa_output…", "description": "Headset"},
               "output_mode": "auto", "mic": {…}, "mic_mode": "auto",
               "channels": {"game": {"name": "Game", "volume": 100,
                                     "muted": false, "device": {…}}, …}}}

`replay.state` is stopped, starting, running, restarting or failed. A device
is null when there is none (Sonar off, nothing plugged in).

`subscribe` answers like `state`, then keeps the connection open and sends
one line per event until the client hangs up:

    {"event": "state", "data": {…the state…}}       whenever it changes
    {"event": "notice", "data": {"kind": "clip_saved", "category": "clips",
                                  "title": "Clip saved", "body": "…"}}

Notices are the notifications Vertex shows (see `notifications`), whether or
not their desktop pop-up is switched on.

`api` goes up when a change could break a client: a field removed or
renamed, a meaning changed. New commands, fields and events don't change it.
"""

from __future__ import annotations

from vertex import notifications
from vertex.audio import channels

API_VERSION = 1

UNKNOWN_COMMAND = "unknown_command"
BAD_ARGUMENT = "bad_argument"
REPLAY_OFF = "replay_off"
SONAR_OFF = "sonar_off"
NO_DEVICE = "no_device"
FAILED = "failed"

VOLUME_STEP = 5
SAVE_LENGTHS = (10, 30, 60, 300, 600, 1800)


def ok(message: str = "", **data) -> dict:
    reply = {"ok": True, "message": message}
    if data:
        reply["data"] = data
    return reply


def error(code: str, message: str) -> dict:
    return {"ok": False, "error": code, "message": message}


class BadArgument(ValueError):
    """A request's argument is missing or invalid; the message says which."""


def channel_arg(args: dict, required: bool = True) -> channels.Channel | None:
    value = args.get("channel")
    if value in (None, "") and not required:
        return None
    channel = channels.get(str(value)) if value is not None else None
    if channel is None:
        names = ", ".join(channel.id for channel in channels.ALL)
        raise BadArgument(f"channel must be one of {names}" +
                          ("" if value is None else f", not {value!r}") + ".")
    return channel


def choice_arg(args: dict, name: str, choices: tuple[str, ...], default: str = "") -> str:
    value = args.get(name, default) or default
    if value not in choices:
        raise BadArgument(f"{name} must be one of {', '.join(choices)}.")
    return value


def number_arg(args: dict, name: str, low: int, high: int, default: int | None = None) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or \
            not low <= value <= high:
        raise BadArgument(f"{name} must be a number from {low} to {high}.")
    return round(value)


def volume_after(current: int, action: str, value: int | None = None,
                 step: int = VOLUME_STEP) -> int:
    """A channel's volume, in percent, after `action` (up, down or set)."""
    if action == "set":
        target = value if value is not None else current
    else:
        target = current + (step if action == "up" else -step)
    return max(0, min(100, target))


def _device(name: str, names: dict[str, str]) -> dict | None:
    return {"name": name, "description": names.get(name, name)} if name else None


def state(config, status, replay_phase: str) -> dict:
    """Everything a button face may show, from the settings, Sonar's status
    (`audio.sonar.SonarStatus`) and the replay buffer's phase."""
    sonar = config.sonar
    names = sonar.device_names
    active = bool(status.active)
    channel_states = {}
    for channel in channels.ALL:
        entry = status.channels.get(channel.id)
        settings = sonar.channel(channel.id)
        present = entry is not None and entry.present
        volume = entry.volume if present else settings.volume
        muted = entry.muted if present else settings.muted
        if not active:
            device = ""
        elif channel.is_output:
            device = (entry.output if entry is not None else "") or status.output
        else:
            device = status.mic
        channel_states[channel.id] = {"name": channel.label, "volume": round(volume * 100),
                                      "muted": bool(muted), "device": _device(device, names)}
    return {
        "api": API_VERSION,
        "replay": {"state": replay_phase, "running": replay_phase == "running",
                   "seconds": config.recorder.replay_seconds},
        "sonar": {
            "enabled": sonar.enabled, "active": active, "linked": sonar.linked,
            "output": _device(status.output if active else "", names),
            "output_mode": "auto" if sonar.output_auto else "manual",
            "mic": _device(status.mic if active else "", names),
            "mic_mode": "auto" if sonar.mic_auto else "manual",
            "channels": channel_states,
        },
    }


def notice_event(notice: notifications.Notice) -> dict:
    kind = notifications.BY_ID[notice.kind]
    return {"event": "notice", "data": {"kind": notice.kind, "category": kind.category,
                                        "title": notice.title, "body": notice.body}}


def state_event(snapshot: dict) -> dict:
    return {"event": "state", "data": snapshot}
