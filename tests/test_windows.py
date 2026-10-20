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
