"""The `vertex` command.

    vertex                      open Vertex (or bring the running one forward)
    vertex --background         start in the tray, e.g. at login
    vertex save-clip [--last N] save the replay buffer (bind this to a hotkey)
    vertex replay start|stop|toggle|status
    vertex sonar up|down|status
    vertex volume CHANNEL up|down|0-100 [--step N]
    vertex mute CHANNEL [on|off|toggle]
    vertex device next|previous [CHANNEL]
    vertex state [--json]       what is running, volumes, devices
    vertex watch                follow changes and notifications, as JSON lines
    vertex doctor               check dependencies
    vertex install-desktop      add Vertex to the start menu (and autostart)
    vertex uninstall-desktop
"""

from __future__ import annotations

import argparse
import json
import sys

from vertex import APP_NAME, __version__, control, ipc
from vertex.audio import channels


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vertex", description=f"{APP_NAME} — game clips and Sonar audio for Linux.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--background", action="store_true",
                        help="start hidden in the system tray")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    commands.add_parser("show", help="bring the running Vertex to the front")
    save = commands.add_parser("save-clip", help="save the replay buffer to a clip")
    save.add_argument("--last", type=int, metavar="SECONDS",
                      choices=(10, 30, 60, 300, 600, 1800),
                      help="save only the last 10/30/60/300/600/1800 seconds")

    replay = commands.add_parser("replay", help="control the replay buffer")
    replay.add_argument("action", choices=("start", "stop", "toggle", "status"))

    sonar = commands.add_parser("sonar", help="control the virtual audio devices")
    sonar.add_argument("action", choices=("up", "down", "status"))

    names = [channel.id for channel in channels.ALL]
    volume = commands.add_parser("volume", help="turn a Sonar channel up or down")
    volume.add_argument("channel", choices=names)
    volume.add_argument("level", metavar="up|down|0-100",
                        help="a step up or down, or a volume in percent")
    volume.add_argument("--step", type=int, default=control.VOLUME_STEP, metavar="PERCENT",
                        help=f"how far up or down (default {control.VOLUME_STEP})")
    mute = commands.add_parser("mute", help="mute or unmute a Sonar channel (mic: Vertex Mic)")
    mute.add_argument("channel", choices=names)
    mute.add_argument("action", nargs="?", default="toggle", choices=("on", "off", "toggle"))
    device = commands.add_parser("device", help="switch to the next or previous device")
    device.add_argument("action", choices=("next", "previous"))
    device.add_argument("channel", nargs="?", choices=names,
                        help="mic for microphones; an output channel while unlinked")

    state = commands.add_parser("state", help="what is running, the volumes and devices")
    state.add_argument("--json", action="store_true", help="the state as JSON")
    commands.add_parser("watch", help="print changes and notifications as JSON lines")

    commands.add_parser("doctor", help="check that everything Vertex needs is installed")

    install = commands.add_parser("install-desktop", help="add Vertex to the start menu")
    install.add_argument("--icon", choices=("light", "dark"), default=None,
                         help="logo ink for the icon (light suits dark panels)")
    install.add_argument("--autostart", action=argparse.BooleanOptionalAction, default=None,
                         help="start Vertex in the tray when you log in")
    commands.add_parser("uninstall-desktop", help="remove the start menu entry and autostart")
    return parser


def _forward(command: str, **args) -> int:
    try:
        reply = ipc.send(command, **args)
    except ipc.NotRunning:
        print(f"{APP_NAME} is not running. Start it first (`vertex` or `vertex --background`).",
              file=sys.stderr)
        return 1
    message = reply.get("message", "")
    if message:
        print(message, file=sys.stdout if reply.get("ok") else sys.stderr)
    return 0 if reply.get("ok") else 1


def _volume(args) -> int:
    if args.level in ("up", "down"):
        return _forward("volume", channel=args.channel, action=args.level, step=args.step)
    try:
        value = int(args.level)
    except ValueError:
        value = -1
    if not 0 <= value <= 100:
        print("The level is up, down or a volume from 0 to 100.", file=sys.stderr)
        return 2
    return _forward("volume", channel=args.channel, action="set", value=value)


def _state(as_json: bool) -> int:
    try:
        reply = ipc.send("state")
    except ipc.NotRunning:
        print(f"{APP_NAME} is not running.", file=sys.stderr)
        return 1
    state = reply.get("data") or {}
    if as_json:
        print(json.dumps(state, indent=2))
        return 0 if reply.get("ok") else 1

    def device(entry):
        return entry["description"] if entry else "nothing"
    replay, sonar = state.get("replay", {}), state.get("sonar", {})
    keeping = f" (last {replay.get('seconds')} s)" if replay.get("running") else ""
    print(f"Replay buffer  {replay.get('state', '?')}{keeping}")
    if not sonar.get("enabled"):
        print("Sonar          off")
        return 0
    print(f"Sonar          {'on' if sonar.get('active') else 'starting'}, playing through "
          f"{device(sonar.get('output'))} ({sonar.get('output_mode')})")
    for channel_id, entry in sonar.get("channels", {}).items():
        where = f"  {device(entry['device'])}" if channel_id == "mic" or \
            not sonar.get("linked") else ""
        print(f"  {entry['name']:<7} {entry['volume']:>3}%{'  muted' if entry['muted'] else ''}"
              f"{where}")
    return 0


def _watch() -> int:
    try:
        for event in ipc.follow():
            print(json.dumps(event), flush=True)
    except ipc.NotRunning:
        print(f"{APP_NAME} is not running.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def _sonar(action: str) -> int:
    """Through the running app if there is one; directly otherwise."""
    if ipc.is_running():
        return _forward("sonar", action=action)

    from vertex import paths
    from vertex.audio.pulse import AudioError
    from vertex.audio.sonar import Sonar
    from vertex.config import Config

    config = Config.load_or_default()
    sonar = Sonar(config.sonar, f"{config.resolved_state_dir()}/sonar.json")
    try:
        if action == "up":
            config.sonar.enabled = True
            for warning in sonar.up():
                print(f"warning: {warning}", file=sys.stderr)
            if paths.config_path().exists():
                config.save()
            print("Sonar is up. Note: without Vertex running, apps are not routed "
                  "automatically.")
        elif action == "down":
            sonar.down()
            config.sonar.enabled = False
            if paths.config_path().exists():
                config.save()
            print("Sonar is down; your previous default devices are restored.")
        else:
            status = sonar.status()
            if not status.available:
                print(status.error, file=sys.stderr)
                return 1
            print(f"Sonar is {'up' if status.active else 'down'}.")
            for entry in status.channels.values():
                state = ("missing" if not entry.present else
                         f"{round(entry.volume * 100)}%{' muted' if entry.muted else ''}")
                print(f"  {entry.channel.description:<14} {state}")
            if status.output:
                print(f"  output → {status.output}")
    except AudioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command is None or args.command == "show":
        if ipc.is_running():
            return _forward("show")
        if args.command == "show":
            print(f"{APP_NAME} is not running.", file=sys.stderr)
            return 1
        from vertex.ui.app import run

        return run(background=args.background)

    if args.command == "save-clip":
        return _forward("save-clip", seconds=args.last)
    if args.command == "replay":
        return _forward("replay", action=args.action)
    if args.command == "sonar":
        return _sonar(args.action)
    if args.command == "volume":
        return _volume(args)
    if args.command == "mute":
        return _forward("mute", channel=args.channel, action=args.action)
    if args.command == "device":
        return _forward("device", action=args.action, channel=args.channel or "")
    if args.command == "state":
        return _state(args.json)
    if args.command == "watch":
        return _watch()
    if args.command == "doctor":
        from vertex import doctor

        return doctor.report(doctor.run_checks())
    if args.command == "install-desktop":
        from vertex import desktop, paths

        variant = args.icon or paths.DEFAULT_LOGO_VARIANT
        for path in desktop.install(variant, args.autostart):
            print(f"  wrote {paths.tilde(str(path))}")
        return 0
    if args.command == "uninstall-desktop":
        from vertex import desktop, paths

        for path in desktop.uninstall():
            print(f"  removed {paths.tilde(str(path))}")
        print("Your clips, library and settings were not touched.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
