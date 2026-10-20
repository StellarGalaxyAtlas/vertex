"""The control API's commands, run on the UI thread, and the events pushed to
subscribers. What the commands are and answer is in `vertex.control`."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from vertex import APP_NAME, __version__, control, ipc, logs
from vertex.recorder.replay import RecorderError


class Commands(QObject):
    """Runs control-socket commands on the UI thread and returns their reply.

    The socket server calls `dispatch` from its own threads; the blocking
    queued connection runs the handler on the UI thread and waits for it.
    State changes and notifications go to `subscribers` as events.
    """

    # `object`, not dict/list: Qt copies those across threads, and the reply
    # has to land in the very list the socket thread is waiting on.
    request = Signal(str, object, object)

    def __init__(self, window, context):
        super().__init__()
        self.window = window
        self.context = context
        self.subscribers = ipc.Subscribers()
        self.request.connect(self._handle, Qt.ConnectionType.BlockingQueuedConnection)
        # Many changes come in bursts (a restart, settings saved):
        # subscribers get the state once it settles, and only when it changed.
        self._last_state: dict | None = None
        self._state_timer = QTimer(self, singleShot=True, interval=120)
        self._state_timer.timeout.connect(self._publish_state)
        for signal in (context.config_changed, context.recorder.state_changed):
            signal.connect(self._state_may_have_changed)
        context.notified.connect(
            lambda notice: self.subscribers.publish(control.notice_event(notice)))
        context.hotkeys.pressed.connect(self._hotkey)

    def dispatch(self, command: str, args: dict) -> dict:
        box: list = []
        self.request.emit(command, args, box)
        return box[0] if box else control.error(control.FAILED, "No reply.")

    def _handle(self, command: str, args: dict, box: list) -> None:
        try:
            box.append(self._run(command, args))
        except control.BadArgument as exc:
            box.append(control.error(control.BAD_ARGUMENT, str(exc)))
        except Exception as exc:     # reported to the caller
            logs.APP.exception("Command %s failed", command)
            box.append(control.error(control.FAILED, str(exc)))
        _log_command(command, args, box[-1])

    def _hotkey(self, action: str) -> None:
        """A hotkey runs its action as the command a shortcut would send."""
        command, args = {
            "save_clip": ("save-clip", {}),
            "save_last": ("save-clip", {"seconds": self.context.config.hotkey_last_seconds}),
            "replay": ("replay", {"action": "toggle"}),
            "show": ("show", {}),
        }[action]
        logs.APP.info("Hotkey %s", self.context.config.hotkeys.get(action, action))
        self._handle(command, args, [])

    # --- State --------------------------------------------------------------------

    def state(self) -> dict:
        return control.state(self.context.config, self.context.recorder.phase)

    def _state_may_have_changed(self, *_args) -> None:
        if len(self.subscribers):
            self._state_timer.start()

    def _publish_state(self) -> None:
        snapshot = self.state()
        if snapshot != self._last_state:
            self._last_state = snapshot
            self.subscribers.publish(control.state_event(snapshot))

    # --- Commands -----------------------------------------------------------------

    def _run(self, command: str, args: dict) -> dict:
        handler = {
            "ping": lambda: control.ok("pong", api=control.API_VERSION, version=__version__),
            "show": self._show, "state": self._state, "save-clip": self._save_clip,
            "replay": self._replay,
        }.get(command)
        if handler is None:
            return control.error(control.UNKNOWN_COMMAND, f"Unknown command: {command}")
        return handler(args) if command != "ping" else handler()

    def _show(self, _args) -> dict:
        self.window.bring_to_front()
        return control.ok()

    def _state(self, _args) -> dict:
        return control.ok(f"{APP_NAME} is running.", **self.state())

    def _save_clip(self, args) -> dict:
        seconds = args.get("seconds")
        if seconds is not None and (isinstance(seconds, bool) or
                                    seconds not in control.SAVE_LENGTHS):
            raise control.BadArgument("seconds must be one of " +
                                      ", ".join(map(str, control.SAVE_LENGTHS)) + ".")
        try:
            return control.ok(self.context.recorder.save(seconds), seconds=seconds)
        except RecorderError as exc:
            return control.error(control.REPLAY_OFF, str(exc))

    def _replay(self, args) -> dict:
        recorder = self.context.recorder
        action = control.choice_arg(args, "action", ("start", "stop", "toggle", "status"))
        if action == "status":
            phase = "stopped after an error" if recorder.phase == "failed" else recorder.phase
            return control.ok(f"The replay buffer is {phase}.",
                              **self.state()["replay"])
        if action == "start" or (action == "toggle" and not recorder.running):
            recorder.start()
            return control.ok("Starting the replay buffer.", state="starting")
        recorder.stop()
        return control.ok("Stopping the replay buffer.", state="stopping")


# Asked for all the time (a client keeps its display up to date): not worth a line.
_QUIET_COMMANDS = {"ping", "state"}


def _log_command(command: str, args: dict, reply: dict) -> None:
    """A command that does something, from a shortcut or a script, with what
    came of it."""
    if command in _QUIET_COMMANDS or args.get("action") == "status":
        return
    given = " ".join(f"{key}={value}" for key, value in args.items() if value is not None)
    said = reply.get("message") or reply.get("error") or ""
    level = logging.INFO if reply.get("ok") else logging.WARNING
    logs.APP.log(level, "Command %s%s: %s", command, f" {given}" if given else "",
                 said or ("done" if reply.get("ok") else "failed"))
