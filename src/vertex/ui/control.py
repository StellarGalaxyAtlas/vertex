"""The control API's commands, run on the UI thread, and the events pushed to
subscribers. What the commands are and answer is in `vertex.control`."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from vertex import APP_NAME, __version__, control, fmt, ipc, logs
from vertex.audio import channels
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
        # Many changes come in bursts (a fader dragged, Sonar coming up):
        # subscribers get the state once it settles, and only when it changed.
        self._last_state: dict | None = None
        self._state_timer = QTimer(self, singleShot=True, interval=120)
        self._state_timer.timeout.connect(self._publish_state)
        for signal in (context.config_changed, context.recorder.state_changed,
                       context.sonar.status_changed, context.sonar.devices_changed):
            signal.connect(self._state_may_have_changed)
        context.notified.connect(
            lambda notice: self.subscribers.publish(control.notice_event(notice)))

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

    # --- State --------------------------------------------------------------------

    def state(self) -> dict:
        return control.state(self.context.config, self.context.sonar.status,
                             self.context.recorder.phase)

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
            "replay": self._replay, "sonar": self._sonar, "volume": self._volume,
            "mute": self._mute, "device": self._device, "devices": self._devices,
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
            return control.ok(f"The replay buffer is {recorder.phase}.",
                              **self.state()["replay"])
        if action == "start" or (action == "toggle" and not recorder.running):
            recorder.start()
            return control.ok("Starting the replay buffer.", state="starting")
        recorder.stop()
        return control.ok("Stopping the replay buffer.", state="stopping")

    def _sonar(self, args) -> dict:
        sonar = self.context.sonar
        action = control.choice_arg(args, "action", ("up", "down", "status"))
        if action == "status":
            return control.ok(f"Sonar is {'up' if sonar.status.active else 'down'}.",
                              **self.state()["sonar"])
        sonar.set_enabled(action == "up")
        return control.ok(f"Sonar is going {'up' if action == 'up' else 'down'}.",
                          enabled=action == "up")

    def _need_sonar(self) -> dict | None:
        if not self.context.config.sonar.enabled:
            return control.error(control.SONAR_OFF, "Sonar is off. Turn it on with "
                                                    "`vertex sonar up`.")
        return None

    def _volume(self, args) -> dict:
        channel = control.channel_arg(args)
        action = control.choice_arg(args, "action", ("up", "down", "set"))
        value = control.number_arg(args, "value", 0, 100) if action == "set" else None
        step = control.number_arg(args, "step", 1, 100, control.VOLUME_STEP)
        refused = self._need_sonar()
        if refused:
            return refused
        current = self.state()["sonar"]["channels"][channel.id]["volume"]
        volume = control.volume_after(current, action, value, step)
        sonar = self.context.sonar
        sonar.set_volume(channel.id, volume / 100)
        sonar.refresh()           # the Sonar page and subscribers follow
        return control.ok(f"{channel.label} at {volume}%.", channel=channel.id, volume=volume)

    def _mute(self, args) -> dict:
        channel = control.channel_arg(args)
        action = control.choice_arg(args, "action", ("on", "off", "toggle"), "toggle")
        refused = self._need_sonar()
        if refused:
            return refused
        muted = self.state()["sonar"]["channels"][channel.id]["muted"]
        muted = not muted if action == "toggle" else action == "on"
        sonar = self.context.sonar
        self.context.config.sonar.channel(channel.id).muted = muted
        sonar.set_muted(channel.id, muted)
        sonar.refresh()
        return control.ok(f"{channel.label} {'muted' if muted else 'unmuted'}.",
                          channel=channel.id, muted=muted)

    def _device(self, args) -> dict:
        action = control.choice_arg(args, "action", ("next", "previous", "set"))
        channel = control.channel_arg(args, required=False)
        name = str(args.get("name") or "")
        if action == "set" and not name:
            raise control.BadArgument("name must be the device to switch to.")
        refused = self._need_sonar()
        if refused:
            return refused
        sonar = self.context.sonar
        if action == "set":
            moved = sonar.pick_device(name, channel.id if channel else "")
            if not moved:
                return control.error(control.NO_DEVICE, f"{name} isn't plugged in.")
        else:
            moved = sonar.cycle_device(1 if action == "next" else -1,
                                       channel.id if channel else "")
            if not moved:
                return control.error(control.NO_DEVICE,
                                     "There is no other device to switch to.")
        names = self.context.config.sonar.device_names
        described = {target: {"name": device, "description": names.get(device, device)}
                     for target, device in moved}
        devices = {d["description"] for d in described.values()}
        what = ("Vertex Mic records" if channel is channels.MIC else
                f"{channel.label} plays through" if channel and len(moved) == 1 and
                not self.context.config.sonar.linked else "Playing through")
        return control.ok(f"{what} {fmt.oxford(sorted(devices))}.", devices=described)

    def _devices(self, _args) -> dict:
        sonar, config = self.context.sonar, self.context.config.sonar
        names = {**config.device_names,
                 **{d.name: d.description for d in sonar.outputs + sonar.inputs}}
        return control.ok(
            "", outputs=control.device_list(config.output_priority, config.output_excluded,
                                            [d.name for d in sonar.outputs], names),
            mics=control.device_list(config.mic_priority, config.mic_excluded,
                                     [d.name for d in sonar.inputs], names))


# Asked for all the time (a Stream Deck keeps its keys up to date): not worth a line.
_QUIET_COMMANDS = {"ping", "state", "devices"}


def _log_command(command: str, args: dict, reply: dict) -> None:
    """A command that does something, from a shortcut, the Stream Deck or a
    script, with what came of it."""
    if command in _QUIET_COMMANDS or args.get("action") == "status":
        return
    if command == "volume" and reply.get("ok"):
        return      # a turned dial is a burst of these; Sonar logs where it settles
    given = " ".join(f"{key}={value}" for key, value in args.items() if value is not None)
    said = reply.get("message") or reply.get("error") or ""
    level = logging.INFO if reply.get("ok") else logging.WARNING
    logs.APP.log(level, "Command %s%s: %s", command, f" {given}" if given else "",
                 said or ("done" if reply.get("ok") else "failed"))
