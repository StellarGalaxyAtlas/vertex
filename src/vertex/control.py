"""The control API: what outside software can ask the running Vertex.

A desktop shortcut or a script talks to Vertex through the control channel
(see `ipc`). Each request is one JSON object on one line, and so is each
reply:

    → {"command": "replay", "args": {"action": "status"}}
    ← {"ok": true, "message": "The replay buffer is running.",
       "data": {"state": "running", "running": true, "seconds": 60}}

Every reply has `ok` and `message` (a sentence for people). Replies with
something to report carry it in `data`; failed ones carry an `error` code:

    unknown_command   no such command
    bad_argument      a missing or invalid argument (the message says which)
    replay_off        the replay buffer isn't running (saving a clip)
    failed            anything else; the message says what

Commands, with their arguments:

    ping                                      data: api, version
    show                                      bring the window to the front
    state                                     data: the state (below)
    save-clip    seconds?                     10, 30, 60, 300, 600 or 1800
    replay       action: start|stop|toggle|status
    subscribe    keeps the connection open; see below

`state` describes everything a button face may show:

    {"api": 2,
     "replay": {"state": "running", "running": true, "seconds": 60}}

`replay.state` is stopped, starting, running, restarting or failed.

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

API_VERSION = 2

UNKNOWN_COMMAND = "unknown_command"
BAD_ARGUMENT = "bad_argument"
REPLAY_OFF = "replay_off"
FAILED = "failed"

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


def choice_arg(args: dict, name: str, choices: tuple[str, ...], default: str = "") -> str:
    value = args.get(name, default) or default
    if value not in choices:
        raise BadArgument(f"{name} must be one of {', '.join(choices)}.")
    return value


def state(config, replay_phase: str) -> dict:
    """Everything a button face may show, from the settings and the replay
    buffer's phase."""
    return {
        "api": API_VERSION,
        "replay": {"state": replay_phase, "running": replay_phase == "running",
                   "seconds": config.recorder.replay_seconds},
    }


def notice_event(notice: notifications.Notice) -> dict:
    kind = notifications.BY_ID[notice.kind]
    return {"event": "notice", "data": {"kind": notice.kind, "category": kind.category,
                                        "title": notice.title, "body": notice.body}}


def state_event(snapshot: dict) -> dict:
    return {"event": "state", "data": snapshot}
