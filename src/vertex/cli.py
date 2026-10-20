"""The `vertex` command.

    vertex                      open Vertex (or bring the running one forward)
    vertex --background         start in the tray, e.g. at login
    vertex save-clip [--last N] save the replay buffer (bind this to a hotkey)
    vertex replay start|stop|toggle|status
    vertex state [--json]       what is running
    vertex watch                follow changes and notifications, as JSON lines
    vertex doctor               check dependencies
    vertex install-desktop      add Vertex to the start menu (and autostart)
    vertex uninstall-desktop
"""

from __future__ import annotations

import argparse
import json
import sys

from vertex import APP_NAME, __version__, ipc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vertex", description=f"{APP_NAME} — game clips: record, trim, mix and share.")
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

    state = commands.add_parser("state", help="what is running")
    state.add_argument("--json", action="store_true", help="the state as JSON")
    commands.add_parser("watch", help="print changes and notifications as JSON lines")

    commands.add_parser("doctor", help="check that everything Vertex needs is installed")

    install = commands.add_parser("install-desktop", help="add Vertex to the start menu")
    install.add_argument("--icon", choices=("light", "dark"), default=None,
                         help="logo ink for the icon (default: what suits your desktop)")
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

    replay = state.get("replay", {})
    keeping = f" (last {replay.get('seconds')} s)" if replay.get("running") else ""
    print(f"Replay buffer  {replay.get('state', '?')}{keeping}")
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
    if args.command == "state":
        return _state(args.json)
    if args.command == "watch":
        return _watch()
    if args.command == "doctor":
        from vertex import doctor

        return doctor.report(doctor.run_checks())
    if args.command == "install-desktop":
        from vertex import desktop, paths

        variant = args.icon or desktop.desktop_ink()
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
