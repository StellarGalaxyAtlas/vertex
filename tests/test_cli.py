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


def test_ping_reports_the_api(server):
    from vertex import control

    reply = ipc.send("ping")
    assert reply["ok"] and reply["data"]["api"] == control.API_VERSION


def test_subscribers_get_the_state_then_events(tmp_path):
    sock = tmp_path / "control.sock"
    subscribers = ipc.Subscribers()
    state = {"api": 1, "replay": {"state": "stopped"}}
    control = ipc.ControlServer(lambda command, args: {"ok": True, "data": state}, sock,
                                subscribers=subscribers)
    assert control.start()
    try:
        stream = ipc.follow(sock)
        assert next(stream)["data"] == state
        for _ in range(100):             # the server registers the subscriber
            if len(subscribers):
                break
            threading.Event().wait(0.02)
        subscribers.publish({"event": "notice", "data": {"kind": "clip_saved"}})
        assert next(stream) == {"event": "notice", "data": {"kind": "clip_saved"}}
        stream.close()                   # hanging up ends the subscription
        for _ in range(100):
            if not len(subscribers):
                break
            threading.Event().wait(0.05)
        assert not len(subscribers)
    finally:
        control.stop()


def test_cli_sonar_commands(server, capsys):
    _control, received = server
    assert cli.main(["volume", "chat", "up"]) == 0
    assert cli.main(["volume", "game", "down", "--step", "10"]) == 0
    assert cli.main(["volume", "media", "40"]) == 0
    assert cli.main(["mute", "mic"]) == 0
    assert cli.main(["device", "next"]) == 0
    assert cli.main(["device", "previous", "chat"]) == 0
    assert received == [
        ("volume", {"channel": "chat", "action": "up", "step": 5}),
        ("volume", {"channel": "game", "action": "down", "step": 10}),
        ("volume", {"channel": "media", "action": "set", "value": 40}),
        ("mute", {"channel": "mic", "action": "toggle"}),
        ("device", {"action": "next", "channel": ""}),
        ("device", {"action": "previous", "channel": "chat"}),
    ]
    assert cli.main(["volume", "chat", "loud"]) == 2
    assert "0 to 100" in capsys.readouterr().err


def test_cli_state(tmp_path, monkeypatch, capsys):
    import json

    from vertex import control
    from vertex.audio import channels
    from vertex.audio.sonar import ChannelStatus, SonarStatus
    from vertex.config import Config

    config = Config()
    config.sonar.enabled = True
    config.sonar.device_names = {"hw": "Headset"}
    status = SonarStatus(active=True, output="hw", channels={
        "chat": ChannelStatus(channels.CHAT, present=True, volume=0.55, muted=True)})
    state = control.state(config, status, "running")
    sock = tmp_path / "control.sock"
    monkeypatch.setattr(paths, "control_socket", lambda: sock)
    server = ipc.ControlServer(lambda command, args: control.ok("", **state), sock)
    assert server.start()
    try:
        assert cli.main(["state"]) == 0
        out = capsys.readouterr().out
        assert "Replay buffer  running (last 60 s)" in out
        assert "playing through Headset" in out
        assert "Chat     55%  muted" in out
        assert cli.main(["state", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == state
    finally:
        server.stop()


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


def test_install_desktop_draws_the_icon_for_the_desktop(isolated_home, monkeypatch):
    # The ink comes from a child process asking Qt; one that dies gives the default.
    answers = iter(["dark\n", ""])
    monkeypatch.setattr(desktop.subprocess, "run", lambda *_a, **_k: type(
        "Done", (), {"stdout": next(answers)})())
    monkeypatch.setattr(desktop, "refresh_caches", lambda: None)
    assert cli.main(["install-desktop"]) == 0
    assert desktop.icon_ink() == "dark"
    assert desktop.desktop_ink() == paths.DEFAULT_LOGO_VARIANT
