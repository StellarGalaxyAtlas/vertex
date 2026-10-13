import os
import threading

import pytest

from vertex import cli, desktop, ipc, paths


@pytest.fixture
def server(tmp_path, monkeypatch):
    sock = tmp_path / "run" / "control.sock"
    monkeypatch.setattr(paths, "control_socket", lambda: sock)
    received = []

    def dispatch(command, args):
        received.append((command, args))
        return {"ok": command != "fail", "message": f"did {command}"}

    control = ipc.ControlServer(dispatch, sock)
    assert control.start()
    yield control, received
    control.stop()


def test_round_trip(server):
    _control, received = server
    assert ipc.is_running()
    reply = ipc.send("save-clip", seconds=30)
    assert reply == {"ok": True, "message": "did save-clip"}
    assert received == [("save-clip", {"seconds": 30})]


def test_second_instance_is_refused(server, tmp_path):
    control, _ = server
    other = ipc.ControlServer(lambda c, a: {}, control.path)
    assert not other.start()


def test_stale_socket_is_replaced(tmp_path):
    sock = tmp_path / "control.sock"
    sock.touch()
    control = ipc.ControlServer(lambda c, a: {"ok": True}, sock)
    assert control.start()
    assert ipc.send("x", sock)["ok"]
    control.stop()
    assert not sock.exists()


def test_concurrent_clients(server):
    results = []
    threads = [threading.Thread(target=lambda: results.append(ipc.send("go")["ok"]))
               for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True] * 8


def test_not_running(tmp_path):
    with pytest.raises(ipc.NotRunning):
        ipc.send("x", tmp_path / "missing.sock")


def test_cli_forwards(server, capsys):
    _control, received = server
    assert cli.main(["save-clip", "--last", "60"]) == 0
    assert cli.main(["replay", "toggle"]) == 0
    assert received == [("save-clip", {"seconds": 60}), ("replay", {"action": "toggle"})]
    assert "did replay" in capsys.readouterr().out


def test_cli_without_app(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "control_socket", lambda: tmp_path / "none.sock")
    assert cli.main(["save-clip"]) == 1
    assert "not running" in capsys.readouterr().err


def test_desktop_install_and_uninstall(isolated_home):
    written = desktop.install("light", autostart=True, argv=["/opt/my apps/vertex"])
    entry = desktop.desktop_file().read_text()
    assert 'Exec="/opt/my apps/vertex"' in entry
    assert "StartupWMClass=vertex" in entry
    assert 'Exec="/opt/my apps/vertex" save-clip' in entry
    assert "--background" in desktop.autostart_file().read_text()
    assert any(p.suffix == ".svg" for p in written)
    assert desktop.autostart_enabled()
    removed = desktop.uninstall()
    assert set(removed) >= {desktop.desktop_file(), desktop.autostart_file()}
    assert not desktop.desktop_file().exists()
    assert not os.listdir(desktop.applications_dir())


def test_entry_is_added_once_and_stays_removed(isolated_home):
    assert desktop.update_icons("dark") == []        # no entry, nothing to redraw
    written = desktop.ensure("light")
    assert desktop.desktop_file() in written and desktop.added_marker().exists()
    entry = desktop.desktop_file().read_text()
    # Just "Vertex" in every menu: no generic name for menus to show instead.
    assert "\nName=Vertex\n" in entry and "GenericName" not in entry
    assert desktop.ensure("light") == []
    # The desktop turned light: the icon is redrawn in the dark ink, once.
    assert desktop.icon_ink() == "light"
    assert any(p.suffix == ".svg" for p in desktop.ensure("dark"))
    assert desktop.icon_ink() == "dark"
    assert desktop.ensure("dark") == []
    desktop.uninstall()
    assert desktop.ensure("light") == []
    assert not desktop.desktop_file().exists()
