"""The `vertex` command.

    vertex                      open Vertex (or bring the running one forward)
    vertex --background         start in the tray, e.g. at login
    vertex save-clip [--last N] save the replay buffer (bind this to a hotkey)
    vertex replay start|stop|toggle|status
    vertex sonar up|down|status                       (Linux: Sonar)
    vertex volume CHANNEL up|down|0-100 [--step N]
    vertex mute CHANNEL [on|off|toggle]
    vertex device next|previous [CHANNEL]
    vertex state [--json]       what is running, and Sonar's volumes and devices
    vertex watch                follow changes and notifications, as JSON lines
    vertex doctor               check dependencies
    vertex backup export [FILE] save your settings and library to one file
    vertex backup import FILE [--only settings|library]
                                put a backup back (quit Vertex first)
    vertex install-desktop      add Vertex to the start menu (and autostart)
    vertex uninstall-desktop
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from vertex import APP_NAME, __version__, control, ipc, platform
from vertex.audio import channels


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

    if platform.SONAR:
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

    state = commands.add_parser("state", help="what is running"
                                + (", the volumes and devices" if platform.SONAR else ""))
    state.add_argument("--json", action="store_true", help="the state as JSON")
    commands.add_parser("watch", help="print changes and notifications as JSON lines")

    commands.add_parser("doctor", help="check that everything Vertex needs is installed")

    install = commands.add_parser("install-desktop", help="add Vertex to the start menu")
    install.add_argument("--icon", choices=("light", "dark"), default=None,
                         help="logo ink for the icon (default: what suits your desktop)")
    install.add_argument("--autostart", action=argparse.BooleanOptionalAction, default=None,
                         help="start Vertex in the tray when you log in")
    commands.add_parser("uninstall-desktop", help="remove the start menu entry and autostart")
    backup = commands.add_parser("backup", help="back up or restore your settings and library")
    actions = backup.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export", help="save your settings and library to one file")
    export.add_argument("file", nargs="?",
                        help="where to save it (default: \"Vertex backup DATE.zip\" here)")
    restore = actions.add_parser("import", help="put a backup back (quit Vertex first)")
    restore.add_argument("file")
    restore.add_argument("--only", choices=("settings", "library"),
                         help="put back only the settings or only the library")
    restore.add_argument("-y", "--yes", action="store_true", help="don't ask first")
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
    replay, sonar = state.get("replay", {}), state.get("sonar")
    keeping = f" (last {replay.get('seconds')} s)" if replay.get("running") else ""
    print(f"Replay buffer  {replay.get('state', '?')}{keeping}")
    if sonar is None:
        return 0
    if not sonar.get("enabled"):
        print("Sonar          off")
        return 0
    for_now = " (picked for now)" if sonar.get("output_picked") else ""
    print(f"Sonar          {'on' if sonar.get('active') else 'starting'}, playing through "
          f"{device(sonar.get('output'))}{for_now}")
    for channel_id, entry in sonar.get("channels", {}).items():
        where = f"  {device(entry['device'])}" if channel_id == "mic" or \
            not sonar.get("linked") else ""
        if channel_id == "mic" and sonar.get("mic_picked"):
            where += " (picked for now)"
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


def _backup(args) -> int:
    from vertex import backup, fmt, paths
    from vertex.config import Config
    from vertex.setting_groups import LIBRARY

    if args.action == "export":
        target = args.file or backup.default_name()
        if os.path.isdir(target):
            target = os.path.join(target, backup.default_name())
        try:
            contents = backup.export(target, Config.load_or_default())
        except (OSError, backup.BackupError) as exc:
            print(f"Couldn't save the backup: {exc}", file=sys.stderr)
            return 1
        held = "settings and library" if "library" in contents.parts else "settings"
        clips = f" ({fmt.plural(contents.clips, 'clip')})" if "library" in contents.parts else ""
        print(f"Saved your {held}{clips} to {paths.tilde(os.path.abspath(target))}.")
        return 0

    if ipc.is_running():
        print(f"{APP_NAME} is running. Quit it from the tray first, or restore the backup in "
              f"Settings › Backup.", file=sys.stderr)
        return 1
    try:
        contents = backup.read(args.file)
    except backup.BackupError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not args.yes:
        if not sys.stdin.isatty():
            print("Add --yes to restore without being asked.", file=sys.stderr)
            return 2
        what = args.only or " and ".join(contents.parts)
        answer = input(f"Replace your {what} with the backup from "
                       f"{fmt.date(contents.created)}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    current = Config.load_or_default()
    try:
        picks = None
        if args.only:
            offered = backup.choices(contents, backup.load_settings(args.file), current)
            picks = [key for key, choice in offered.items() if choice.default and
                     (key == LIBRARY) == (args.only == "library")]
        restored = backup.restore(args.file, current, picks)
    except (OSError, backup.BackupError) as exc:
        print(f"Couldn't restore the backup: {exc}", file=sys.stderr)
        return 1
    print(_restored(restored))
    return 0


def _restored(restored) -> str:
    """What a restore did, in a few lines."""
    from vertex import backup, fmt, paths, setting_groups
    from vertex.setting_groups import LIBRARY

    what = [part for part, there in (("settings", restored.settings),
                                     ("library", LIBRARY in restored.picks)) if there]
    lines = [f"Restored your {' and '.join(what)}"
             + (f" ({fmt.plural(restored.clips, 'clip')})." if LIBRARY in restored.picks
                else ".")]
    if restored.left_out:
        items = setting_groups.items()
        names = [items[key].title.lower() for key in restored.left_out]
        lines.append(f"Kept as they were: {fmt.oxford(names)} (not on this computer, or made "
                     f"for another recorder).")
    missing, known = backup.missing_clips(restored.config)
    if missing * 2 > known:
        lines.append(f"{missing} of the library's {fmt.plural(known, 'clip')} aren't in "
                     f"{paths.tilde(restored.config.resolved_clip_dir())}. Set the clips folder "
                     f"in Settings › General.")
    if restored.moved_to:
        lines.append(f"What was replaced is in {restored.moved_to}.")
    return "\n".join(lines)


def _start_apart(background: bool) -> int:
    """`vertex` typed in a terminal on Windows: Vertex starts on its own and
    the terminal is handed back, so closing it doesn't quit Vertex."""
    from vertex import desktop

    try:
        platform.start_detached([*desktop.launch_command(),
                               *(["--background"] if background else [])])
    except OSError as exc:
        print(f"Couldn't start {APP_NAME}: {exc}", file=sys.stderr)
        return 1
    print(f"{APP_NAME} is starting. This window can be closed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command is None or args.command == "show":
        if ipc.is_running():
            return _forward("show")
        if args.command == "show":
            print(f"{APP_NAME} is not running.", file=sys.stderr)
            return 1
        if platform.in_console():
            return _start_apart(args.background)
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

        variant = args.icon or desktop.desktop_ink()
        for path in desktop.install(variant, args.autostart):
            print(f"  wrote {paths.tilde(str(path))}")
        return 0
    if args.command == "backup":
        return _backup(args)
    if args.command == "uninstall-desktop":
        from vertex import desktop, paths

        for path in desktop.uninstall():
            print(f"  removed {paths.tilde(str(path))}")
        print("Your clips, library and settings were not touched.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
