"""What differs between Linux and Windows, in one place: the rest of Vertex
asks this package, and never checks which system it runs on itself.

`linux` and `windows` each hand out the same names, and this package hands
out those of the system Vertex runs on: `platform.config_dir()` is
`windows.config_dir()` on Windows and `linux.config_dir()` everywhere else.
To change what Vertex does on one system, change that system's module.

What each has is listed in NAMES, and a test keeps the two in step. What
else either has is its own, for its own use.

Neither module imports anything of its system's at the top, so both load
anywhere, and tests choose Windows on Linux by setting `WINDOWS`. A test
that replaces one of these names replaces it in `linux` or `windows`, not
here. No Qt in this package.
"""

from __future__ import annotations

import sys

from vertex.platform import linux, windows

WINDOWS = sys.platform == "win32"


NAMES = (
    # The recorder: "gsr" or "obs", and the command it runs (recorder.backend).
    "RECORDER", "RECORDER_COMMAND",
    # Whether Sonar, Vertex's own Game/Chat/Media/Mic devices, can run here
    # (vertex.audio needs PipeWire).
    "SONAR",
    # How `vertex <command>` reaches the running Vertex (ipc).
    "UNIX_SOCKETS", "CONTROL_FILE",
    # Global hotkeys, and the name of a key event's native key (hotkeys).
    "HOTKEYS", "HotkeyListener", "key_name",
    # Where to get the Vertex plugin for this system's Stream Deck software;
    # "" for none.
    "STREAM_DECK_PLUGIN",
    # Whether the game in front can be told when a clip is saved, and it.
    "FULLSCREEN_GAME", "fullscreen_app",
    # Folders (paths): whether to show home as ~, and where things go.
    "SHORT_HOME", "config_dir", "data_dir", "state_dir", "cache_dir", "runtime_dir",
    "user_dir", "real", "prepare_dir",
    # What `vertex doctor` looks for, and how it says to get what's missing.
    "LIBMPV_NAMES", "FILE_OPENER", "install_hint",
    # Keyword arguments for every helper program Vertex starts.
    "NO_WINDOW",
    # The menu entry and starting at sign-in (desktop).
    "launch_command", "install_entry", "has_entry", "draw_icon", "set_autostart",
    "autostart_enabled", "remove_entry", "refresh_menus",
    # A monitor's name as Settings shows it.
    "monitor_label",
    # The window, the taskbar, the file manager and the terminal.
    "set_app_id", "put_on_taskbar", "activate_windows", "allow_foreground",
    "light_desktop", "show_in_folder", "in_console", "start_detached",
)


def here():
    """The module of the system Vertex runs on."""
    return windows if WINDOWS else linux


def __getattr__(name: str):
    if name not in NAMES:
        raise AttributeError(f"vertex.platform has no {name!r}")
    return getattr(here(), name)
