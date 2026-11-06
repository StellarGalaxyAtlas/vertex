"""Telling the game on Linux without Sonar: the game Steam runs, and the
full-screen X window in front."""

from __future__ import annotations

import ctypes
import os

import pytest

from vertex.platform import linux, steam, x11


def _process(proc, pid, *args):
    folder = proc / str(pid)
    folder.mkdir(parents=True)
    (folder / "cmdline").write_bytes(b"\0".join(arg.encode() for arg in args) + b"\0")


def _library(folder, app_id, name):
    apps = folder / "steamapps"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / f"appmanifest_{app_id}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{app_id}"\n\t"name"\t\t"{name}"\n}}\n')


def test_the_game_steam_runs_is_named_from_its_library(tmp_path):
    proc, home = tmp_path / "proc", tmp_path / "home"
    steam_home = home / ".local/share/Steam"
    other = tmp_path / "games"
    _library(steam_home, 1091500, "Cyberpunk 2077")
    _library(other, 1245620, "ELDEN RING™")
    (steam_home / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{steam_home}"\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{other}"\n\t}}\n}}\n')
    _process(proc, 1, "/usr/lib/systemd/systemd")
    _process(proc, 2, "/home/me/.local/share/Steam/ubuntu12_32/steam")
    assert steam.running_games(str(proc), home) == set()

    # The game's AppId is reaper's own; one in the game's arguments isn't.
    _process(proc, 3, f"{steam_home}/ubuntu12_32/reaper", "SteamLaunch", "AppId=1245620",
             "--", "/x/steam-launch-wrapper", "--", "game.exe", "AppId=1091500")
    assert steam.running_app_ids(str(proc)) == {"1245620"}
    assert steam.running_games(str(proc), home) == {"ELDEN RING™"}

    # A shortcut to a game from elsewhere has no manifest, and no name.
    _process(proc, 4, "reaper", "SteamLaunch", "AppId=3141592653", "--", "lutris")
    assert steam.running_games(str(proc), home) == {"ELDEN RING™"}


def test_without_steam_no_game_is_running(tmp_path, monkeypatch):
    assert steam.running_games(str(tmp_path / "no proc"), tmp_path) == set()
    _process(tmp_path / "proc", 7, "reaper", "SteamLaunch", "AppId=730", "--", "cs2")
    assert steam.running_games(str(tmp_path / "proc"), tmp_path) == set()    # no library

    # Two games at once: which one is unclear.
    monkeypatch.setattr(steam, "running_games", lambda: {"A", "B"})
    assert linux.running_game() == ""
    monkeypatch.setattr(steam, "running_games", lambda: {"Dota 2"})
    assert linux.running_game() == "Dota 2"


# --- The X server ---------------------------------------------------------------

def _x_window(**properties):
    """A window on the X server under test with these properties set, as
    a window manager and the window's program would. Returns its id and a
    function that destroys it."""
    lib = x11._xcb()
    connection = x11._Connection(lib, None)
    if not connection.root:
        pytest.skip("no X server")
    lib.xcb_generate_id.restype = ctypes.c_uint32
    lib.xcb_generate_id.argtypes = [ctypes.c_void_p]
    lib.xcb_create_window.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint32,
                                      ctypes.c_uint32, ctypes.c_int16, ctypes.c_int16,
                                      ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16,
                                      ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p]
    lib.xcb_change_property.argtypes = [ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint32,
                                        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint8,
                                        ctypes.c_uint32, ctypes.c_void_p]
    lib.xcb_delete_property.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    lib.xcb_destroy_window.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.xcb_flush.argtypes = [ctypes.c_void_p]
    c = connection.c
    window = lib.xcb_generate_id(c)
    lib.xcb_create_window(c, 0, window, connection.root, 0, 0, 640, 480, 0, 1, 0, 0, None)

    def put(target, name, kind, values):
        if isinstance(values, bytes):
            data, fmt, count = ctypes.create_string_buffer(values, len(values)), 8, len(values)
        else:
            data, fmt, count = (ctypes.c_uint32 * len(values))(*values), 32, len(values)
        lib.xcb_change_property(c, 0, target, connection.atom(name), kind, fmt, count, data)

    utf8 = connection.atom("UTF8_STRING")
    for name, value in properties.items():
        if name == "_NET_WM_STATE":
            put(window, name, x11.ATOM, [connection.atom(state) for state in value])
        elif name == "_NET_WM_PID":
            put(window, name, x11.CARDINAL, [value])
        elif name == "WM_CLASS":
            put(window, name, x11.STRING, b"\0".join(value) + b"\0")
        else:
            put(window, name, utf8, value.encode())
    put(connection.root, "_NET_ACTIVE_WINDOW", x11.WINDOW, [window])
    lib.xcb_flush(c)

    def destroy():
        lib.xcb_delete_property(c, connection.root, connection.atom("_NET_ACTIVE_WINDOW"))
        lib.xcb_destroy_window(c, window)
        lib.xcb_flush(c)
        connection.close()

    return window, destroy


@pytest.fixture
def x_server():
    if not os.environ.get("DISPLAY") or x11._xcb() is None:
        pytest.skip("no X server")


def test_the_full_screen_x_window_in_front_is_told(x_server):
    assert x11.fullscreen_window() == ("", "", 0)       # no window manager: none active

    _window, destroy = _x_window(_NET_WM_NAME="ELDEN RING™", WM_CLASS=(b"eldenring.exe",) * 2,
                                 _NET_WM_STATE=["_NET_WM_STATE_FULLSCREEN"], _NET_WM_PID=4242)
    try:
        assert x11.fullscreen_window() == ("ELDEN RING™", "eldenring.exe", 4242)
        assert linux.fullscreen_app() == ("ELDEN RING™", "eldenring.exe")
    finally:
        destroy()

    # Not full screen: no game in front.
    _window, destroy = _x_window(_NET_WM_NAME="Files", WM_CLASS=(b"nautilus", b"Nautilus"),
                                 _NET_WM_STATE=["_NET_WM_STATE_MAXIMIZED_VERT"])
    try:
        assert linux.fullscreen_app() == ("", "")
    finally:
        destroy()

    # Vertex's own window can't say what was played behind it.
    _window, destroy = _x_window(_NET_WM_NAME="Vertex", WM_CLASS=(b"vertex", b"Vertex"),
                                 _NET_WM_STATE=["_NET_WM_STATE_FULLSCREEN"],
                                 _NET_WM_PID=os.getpid())
    try:
        assert linux.fullscreen_app() is None
    finally:
        destroy()


def test_no_x_server_tells_nothing(monkeypatch):
    if x11._xcb() is not None:
        assert x11.fullscreen_window(":4093") is None      # no server there
    monkeypatch.setattr(x11, "_lib", False)
    assert x11.fullscreen_window() is None
    assert linux.fullscreen_app() is None
