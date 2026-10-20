"""What Vertex does differently on Windows, checked from any platform: the
Windows branches are chosen by `system.WINDOWS` and the transport by
`ipc.USE_TCP`, so these tests switch them on."""

import json
import os
import sys

import pytest

from vertex import desktop, ipc, paths, system


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "WINDOWS", True)
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
    monkeypatch.setattr(system, "known_folder", lambda role: "")
    assert paths.xdg_user_dir("VIDEOS", "~/Videos") == paths.normalize("~/Videos")
    monkeypatch.setattr(system, "known_folder", lambda role: "D:\\Videos")
    assert paths.xdg_user_dir("VIDEOS", "~/Videos").endswith("Videos")


def test_appdata_without_the_variables(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    home = os.path.expanduser("~")
    assert system.appdata() == os.path.join(home, "AppData", "Roaming")
    assert system.appdata(local=True) == os.path.join(home, "AppData", "Local")


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
    monkeypatch.setattr(desktop, "_windows_icon", lambda _v: [])
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
    monkeypatch.setattr(paths.subprocess, "run", lambda line, **kw: ran.append(line))
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
    light = system.light_desktop()
    assert light is None if sys.platform != "win32" else light in (True, False, None)


def test_hotkeys_are_written_in_windows_order_and_typing_keys_need_ctrl_alt_or_win():
    from vertex import hotkeys

    assert hotkeys.parse("Alt+Win+G").text == "Win+Alt+G"
    assert hotkeys.parse("Ctrl+Num +").parts == ("Ctrl", "Num +")
    assert hotkeys.parse("F13").text == "F13"            # what a macro key sends
    for refused in ("A", "Shift+A", "Shift+Space", "Ctrl+Ctrl+A", "Ctrl+Esc", "Ctrl+", ""):
        assert hotkeys.parse(refused) is None, refused
    assert "Add Ctrl, Alt or Win" in hotkeys.Hotkey.of(["Shift"], "5").problem()
    assert hotkeys.key_name(0x78) == "F9" and hotkeys.key_name(0xBA) == ""
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


def test_windows_holds_the_hotkeys_and_lets_them_go():
    import threading

    from vertex import hotkeys

    results = []
    done = threading.Event()
    listener = hotkeys.Listener(lambda _action: None,
                                lambda failed: (results.append(failed), done.set()))
    listener.set({"save_clip": hotkeys.parse("Ctrl+Alt+Shift+F24")})
    if sys.platform != "win32":
        assert listener._thread is None and not results     # nothing to hold elsewhere
        return
    try:
        assert done.wait(5)
        assert results[-1] <= {"save_clip"}         # held, or another program has it
        done.clear()
        listener.set({})
        assert done.wait(5) and results[-1] == set()
    finally:
        listener.close()


def test_a_window_goes_on_the_taskbar_as_vertex():
    from vertex import desktop

    if sys.platform != "win32":
        assert not desktop.put_on_taskbar(0)
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
        assert desktop.put_on_taskbar(hwnd)
    finally:
        user32.DestroyWindow(hwnd)


def test_vertex_typed_in_a_terminal_starts_apart_from_it(monkeypatch, capsys):
    from vertex import cli, ipc, system

    started = []
    monkeypatch.setattr(ipc, "is_running", lambda: False)
    monkeypatch.setattr(system, "in_console", lambda: True)
    monkeypatch.setattr(system, "start_detached", started.append)
    assert cli.main(["--background"]) == 0
    assert started[0][-1] == "--background"
    assert "can be closed" in capsys.readouterr().out
    if sys.platform != "win32":
        monkeypatch.undo()
        assert not system.in_console()          # elsewhere Vertex runs in place
