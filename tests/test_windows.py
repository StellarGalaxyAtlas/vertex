"""What Vertex does differently on Windows, checked from any platform:
`platform.WINDOWS` chooses vertex.platform.windows and `ipc.USE_TCP` the
transport, so these tests switch them on."""

import json
import os
import pathlib
import re
import sys

import pytest

from vertex import config, desktop, ipc, paths, platform
from vertex.platform import windows as windows_platform


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    return tmp_path


def test_folders_live_in_appdata(windows):
    roaming, local = windows / "Roaming", windows / "Local"
    assert paths.config_path() == roaming / "Vertex" / "config.json"
    assert paths.default_data_dir() == local / "Vertex" / "Library"
    assert paths.default_state_dir() == local / "Vertex" / "State"
    assert paths.default_cache_dir() == local / "Vertex" / "Cache"
    assert paths.control_socket() == local / "Vertex" / "control.json"
    # No ~ shorthand to show paths with on Windows.
    home = os.path.expanduser("~")
    assert paths.tilde(os.path.join(home, "Videos")) == os.path.join(home, "Videos")


def test_videos_folder_falls_back_when_windows_cannot_say(windows, monkeypatch):
    monkeypatch.setattr(windows_platform, "known_folder", lambda role: "")
    assert paths.user_dir("VIDEOS", "~/Videos") == paths.normalize("~/Videos")
    monkeypatch.setattr(windows_platform, "known_folder", lambda role: "D:\\Videos")
    assert paths.user_dir("VIDEOS", "~/Videos").endswith("Videos")


def test_appdata_without_the_variables(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    home = os.path.expanduser("~")
    assert windows_platform.appdata() == os.path.join(home, "AppData", "Roaming")
    assert windows_platform.appdata(local=True) == os.path.join(home, "AppData", "Local")


def test_control_over_a_local_port_needs_the_token(windows, monkeypatch):
    monkeypatch.setattr(ipc, "USE_TCP", True)
    port_file = windows / "Local" / "Vertex" / "control.json"
    received = []

    def dispatch(command, args):
        received.append((command, args))
        return {"ok": True, "message": "done"}

    server = ipc.ControlServer(dispatch, port_file)
    assert server.start()
    try:
        found = json.loads(port_file.read_text())
        assert found["port"] > 0 and len(found["token"]) == 32
        assert ipc.is_running(port_file)
        assert ipc.send("replay", port_file, action="toggle")["ok"]
        assert received == [("replay", {"action": "toggle"})]
        # A second Vertex finds the first and stays out of its way.
        assert not ipc.ControlServer(dispatch, port_file).start()

        # Someone without the file's token gets nowhere.
        import socket
        with socket.create_connection(("127.0.0.1", found["port"]), timeout=5) as client:
            client.sendall(b'{"command": "replay", "args": {"action": "stop"}}\n')
            reply = json.loads(client.makefile("rb").readline())
        assert not reply["ok"] and len(received) == 1
    finally:
        server.stop()
    assert not port_file.exists()
    assert not ipc.is_running(port_file)


def test_a_stale_port_file_is_not_a_running_vertex(windows, monkeypatch):
    monkeypatch.setattr(ipc, "USE_TCP", True)
    port_file = windows / "control.json"
    port_file.write_text(json.dumps({"port": 9, "token": "x"}))      # nothing listens
    assert not ipc.is_running(port_file)
    port_file.write_text("half a fi")
    assert not ipc.is_running(port_file)


def test_shortcuts_start_vertex_without_a_console(windows, monkeypatch, tmp_path):
    python = tmp_path / "python.exe"
    monkeypatch.setattr(sys, "executable", str(python))
    assert desktop.launch_command() == [str(python), "-m", "vertex"]
    (tmp_path / "pythonw.exe").write_text("")
    assert desktop.launch_command() == [str(tmp_path / "pythonw.exe"), "-m", "vertex"]
    (tmp_path / "VertexApp.exe").write_text("")
    assert desktop.launch_command() == [str(tmp_path / "VertexApp.exe")]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert desktop.launch_command() == [str(python)]


def test_the_start_menu_shortcut_is_written_by_powershell(windows, monkeypatch):
    ran = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **_kw: ran.append(argv))
    monkeypatch.setattr(windows_platform, "draw_icon", lambda _v: [])
    written = desktop.install("light", argv=["C:\\Python\\pythonw.exe", "-m", "vertex"])
    shortcut = windows / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / \
        "Vertex.lnk"
    assert written == [shortcut]
    script = ran[0][-1]
    assert ran[0][0] == "powershell" and f"'{shortcut}'" in script
    assert "$link.TargetPath = 'C:\\Python\\pythonw.exe'" in script
    assert "$link.Arguments = '-m vertex'" in script
    assert desktop.icon_ink() == "light"


def test_appdata_folders_are_made_by_windows_and_handed_out_where_they_are(
        windows, monkeypatch):
    ran = []
    monkeypatch.setattr(windows_platform.subprocess, "run", lambda line, **kw: ran.append(line))
    cache = windows / "Local" / "Vertex" / "Cache"
    assert paths.make_dir(cache) == str(cache) and cache.is_dir()
    assert ran == [f'cmd /d /c mkdir "{cache}"']
    paths.make_dir(cache)                       # already there: Windows isn't asked again
    elsewhere = windows / "Clips"
    paths.make_dir(elsewhere)
    assert len(ran) == 1 and elsewhere.is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need rights there")
def test_a_folder_kept_elsewhere_is_named_by_where_it_is(windows):
    elsewhere = windows / "Clips"
    elsewhere.mkdir()
    private = windows / "Packages" / "Vertex"
    private.mkdir(parents=True)
    (windows / "Local").mkdir()
    moved = windows / "Local" / "Moved"
    moved.symlink_to(private)
    assert paths.real(str(moved)) == str(private)
    assert paths.real(str(elsewhere)) == str(elsewhere)


def test_vertex_starts_at_sign_in_from_a_shortcut_named_vertex(windows, monkeypatch):
    ran = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **_kw: ran.append(argv))
    startup = windows / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / \
        "Startup" / "Vertex.lnk"
    desktop.set_autostart(True, ["C:\\Python\\pythonw.exe", "-m", "vertex"])
    script = ran[0][-1]
    assert f"'{startup}'" in script and "$link.Arguments = '-m vertex --background'" in script
    startup.write_text("")                      # what PowerShell would have written
    assert desktop.autostart_enabled()
    desktop.set_autostart(False)
    assert not startup.exists() and not desktop.autostart_enabled()


def test_the_taskbar_theme_is_asked_of_windows_only_there(windows):
    light = windows_platform.light_desktop()
    assert light is None if sys.platform != "win32" else light in (True, False, None)


def test_hotkeys_are_written_in_windows_order_and_typing_keys_need_ctrl_alt_or_win():
    from vertex import hotkeys

    assert hotkeys.parse("Alt+Win+G").text == "Win+Alt+G"
    assert hotkeys.parse("Ctrl+Num +").parts == ("Ctrl", "Num +")
    assert hotkeys.parse("F13").text == "F13"            # what a macro key sends
    for refused in ("A", "Shift+A", "Shift+Space", "Ctrl+Ctrl+A", "Ctrl+Esc", "Ctrl+", ""):
        assert hotkeys.parse(refused) is None, refused
    assert "Add Ctrl, Alt or Win" in hotkeys.Hotkey.of(["Shift"], "5").problem()
    assert windows_platform.key_name(0x78) == "F9" and windows_platform.key_name(0xBA) == ""
    assert hotkeys.bindings({"save_clip": "Ctrl+Alt+F9", "show": "Ctrl+Alt+F9",
                             "nope": "F1", "replay": "A"}) == \
        {"save_clip": hotkeys.parse("Ctrl+Alt+F9")}


def test_hotkeys_in_the_settings_drop_what_cant_be_read(tmp_path):
    from vertex.config import Config

    config = Config.from_dict({"hotkeys": {"save_clip": "Alt+Ctrl+F9", "show": "Q",
                                           "replay": 5},
                               "hotkey_last_seconds": 45})
    assert config.hotkeys == {"save_clip": "Ctrl+Alt+F9"}
    assert config.hotkey_last_seconds == 30
    config.hotkey_last_seconds = 60
    config.save(tmp_path / "config.json")
    assert Config.load(tmp_path / "config.json").hotkey_last_seconds == 60


def test_track_volumes_stay_in_range():
    from vertex.config import Config

    rec = Config.from_dict({"recorder": {"chat_volume": 150, "mic_volume": -5,
                                         "media_volume": 40}}).recorder
    assert (rec.game_volume, rec.chat_volume, rec.mic_volume, rec.media_volume) == \
        (100, 100, 0, 40)


def test_a_hotkey_runs_once_and_its_key_is_kept_from_other_programs():
    from vertex import hotkeys

    matcher = hotkeys.Matcher({"save_clip": hotkeys.parse("F24"),
                               "show": hotkeys.parse("Ctrl+Alt+V")})
    # A macro key alone: runs once, held or repeating, and no one else sees it.
    assert matcher.down("F24", []) == ("save_clip", True)
    assert matcher.down("F24", []) == ("", True)
    assert matcher.up("F24")
    # Its modifiers exactly: more or fewer held is another key altogether.
    assert matcher.down("V", ["Alt", "Ctrl"]) == ("show", True)
    assert matcher.up("V")
    assert matcher.down("V", ["Ctrl"]) == ("", False)
    assert matcher.down("V", ["Ctrl", "Alt", "Shift"]) == ("", False)
    assert matcher.down("F24", ["Shift"]) == ("", False)
    assert not matcher.up("V") and not matcher.up("F24")
    # Typing goes on as before.
    assert matcher.down("A", []) == ("", False) and not matcher.up("A")
    # Its hotkeys changed while one is held: its key still comes up kept.
    matcher.down("F24", [])
    matcher.wanted = {}
    assert matcher.up("F24")
    assert matcher.down("F24", []) == ("", False)


def test_windows_hooks_the_keyboard_only_while_there_are_hotkeys():
    import time

    from vertex import hotkeys

    listener = hotkeys.listener(lambda _action: None)
    listener.set({"save_clip": hotkeys.parse("Ctrl+Alt+Shift+F24")})
    if sys.platform != "win32":
        assert listener._thread is None and not listener.hooked   # nothing to hook elsewhere
        return

    def settles(hooked: bool) -> bool:
        deadline = time.monotonic() + 5
        while listener.hooked != hooked and time.monotonic() < deadline:
            time.sleep(0.02)
        return listener.hooked == hooked

    try:
        assert settles(True)
        listener.set({})
        assert settles(False)
    finally:
        listener.close()


def test_a_window_goes_on_the_taskbar_as_vertex(monkeypatch):
    given = []
    monkeypatch.setattr(windows_platform, "set_window_app_id", lambda *args: given.append(args))
    windows_platform.put_on_taskbar(1)
    # The pin's icon is a resource: the file, then its index.
    assert given[0][3] == f"{windows_platform._shortcut_icon()},0"
    monkeypatch.undo()
    if sys.platform != "win32":
        assert not platform.put_on_taskbar(0)
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, wintypes.LPVOID)
    hwnd = user32.CreateWindowExW(0, "STATIC", "Vertex", 0, 0, 0, 10, 10,
                                  None, None, None, None)
    assert hwnd
    try:
        assert platform.put_on_taskbar(hwnd)
    finally:
        user32.DestroyWindow(hwnd)


def test_vertex_typed_in_a_terminal_starts_apart_from_it(monkeypatch, capsys):
    from vertex import cli

    started = []
    monkeypatch.setattr(ipc, "is_running", lambda: False)
    monkeypatch.setattr(platform.here(), "in_console", lambda: True)
    monkeypatch.setattr(platform.here(), "start_detached", started.append)
    assert cli.main(["--background"]) == 0
    assert started[0][-1] == "--background"
    assert "can be closed" in capsys.readouterr().out
    if sys.platform != "win32":
        monkeypatch.undo()
        assert not platform.in_console()          # elsewhere Vertex runs in place


def test_windows_is_asked_what_fills_the_screen():
    window = windows_platform.fullscreen_app()
    if sys.platform != "win32":
        assert window is None
        return
    assert window is None or all(isinstance(part, str) for part in window)


def test_monitors_are_shown_as_display_and_their_number(windows):
    assert platform.monitor_label("\\\\.\\DISPLAY2") == "Display 2"
    assert platform.monitor_label("Odd name") == "Odd name"


def test_linux_and_windows_hand_out_the_same_names():
    from vertex.platform import linux

    for module in (linux, windows_platform):
        missing = [name for name in platform.NAMES if not hasattr(module, name)]
        assert not missing, f"{module.__name__} lacks {missing}"
    # What only one system has isn't handed out: shared code can't lean on it.
    with pytest.raises(AttributeError):
        platform.desktop_file      # noqa: B018


def test_windows_is_chosen_by_platform_windows(windows):
    assert platform.here() is windows_platform
    assert platform.RECORDER == "obs" and platform.CONTROL_FILE == "control.json"
    # No Sonar there: no Sonar settings in the track choices, no Sonar commands.
    assert not platform.SONAR and not platform.STREAM_DECK_PLUGIN
    assert config.RecorderConfig().chat_audio == ""


# What tells one system from another, or calls into Windows itself.
SYSTEM_CHECK = re.compile(r"sys\.platform|\bos\.name\b|platform\.WINDOWS|platform\.here\("
                          r"|\bwindll\b|\bWinDLL\b|\bwinreg\b")
# Reaching into one system's module past vertex.platform. The OBS recorder
# runs only on Windows and asks Windows itself what it records.
SYSTEM_MODULE = re.compile(r"vertex\.platform import (linux|windows|kwin)"
                           r"|vertex\.platform\.(linux|windows|kwin)")
RECORDERS_OF_ONE_SYSTEM = {"recorder/obs.py"}


def test_only_vertex_platform_knows_which_system_it_is():
    root = pathlib.Path(paths.__file__).parent
    found = []
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix()
        if name.startswith("platform/"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SYSTEM_CHECK.search(line) or (SYSTEM_MODULE.search(line)
                                             and name not in RECORDERS_OF_ONE_SYSTEM):
                found.append(f"{name}:{number}: {line.strip()}")
    assert not found, "ask vertex.platform instead:\n" + "\n".join(found)
