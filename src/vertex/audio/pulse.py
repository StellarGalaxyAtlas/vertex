"""A thin, typed wrapper around `pactl`, the PulseAudio/PipeWire control tool.

pactl talks to PulseAudio and to PipeWire's pulse server alike, ships with
every desktop that has either, and its module interface (null sinks,
loopbacks, remapped sources) is exactly what Sonar is built from. Going
through the CLI rather than libpulse keeps Vertex free of native bindings and
makes every call here easy to test from recorded output.

JSON output (`pactl -f json`, pactl ≥ 16) is used for everything except the
module list, whose JSON form leaves out the module index on some versions.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from vertex.proc import die_with_parent, last_line


class AudioError(RuntimeError):
    """pactl failed or is missing; the message is fit to show a user."""


# --- Data -------------------------------------------------------------------

def _volume(raw) -> float:
    """Average channel volume as a fraction (1.0 = 100%)."""
    if not isinstance(raw, dict):
        return 1.0
    values = []
    for channel in raw.values():
        if isinstance(channel, dict):
            try:
                values.append(int(channel.get("value", 65536)) / 65536)
            except (TypeError, ValueError):
                continue
    return sum(values) / len(values) if values else 1.0


@dataclass
class Device:
    """A sink (output) or source (input)."""

    index: int
    name: str
    description: str
    kind: str                       # "sink" | "source"
    volume: float = 1.0
    muted: bool = False
    owner_module: int | None = None
    properties: dict = field(default_factory=dict)

    @property
    def is_monitor(self) -> bool:
        return self.kind == "source" and (
            self.name.endswith(".monitor") or self.properties.get("device.class") == "monitor")

    @property
    def is_vertex(self) -> bool:
        return self.name.startswith("vertex_")

    @property
    def label(self) -> str:
        return self.description or self.name

    @classmethod
    def from_json(cls, data: dict, kind: str) -> Device:
        return cls(
            index=int(data.get("index", -1)), name=str(data.get("name", "")),
            description=str(data.get("description") or ""), kind=kind,
            volume=_volume(data.get("volume")), muted=bool(data.get("mute", False)),
            owner_module=_int_or_none(data.get("owner_module")),
            properties=dict(data.get("properties") or {}),
        )


# Binaries that host other programs, so their name says nothing about which
# program is playing: the application name is the better key for these.
GENERIC_BINARIES = frozenset({
    "electron", "python", "python3", "java", "node", "bwrap", "flatpak",
    "wine", "wine64", "wine-preloader", "wine64-preloader", "pw-play", "paplay",
})


@dataclass
class Stream:
    """An application's playback stream (a sink input)."""

    index: int
    sink: int
    owner_module: int | None = None
    volume: float = 1.0
    muted: bool = False
    properties: dict = field(default_factory=dict)

    @property
    def app_name(self) -> str:
        props = self.properties
        return str(props.get("application.name") or props.get("media.name")
                   or props.get("node.name") or "Unknown")

    @property
    def binary(self) -> str:
        return str(self.properties.get("application.process.binary") or "")

    @property
    def icon(self) -> str:
        return str(self.properties.get("application.icon_name") or "")

    @property
    def key(self) -> str:
        """What a routing rule matches on: the program, case-insensitively."""
        binary = self.binary.strip()
        if binary and binary.casefold() not in GENERIC_BINARIES:
            return binary.casefold()
        return self.app_name.strip().casefold()

    @classmethod
    def from_json(cls, data: dict) -> Stream:
        return cls(
            index=int(data.get("index", -1)), sink=int(data.get("sink", -1)),
            owner_module=_int_or_none(data.get("owner_module")),
            volume=_volume(data.get("volume")), muted=bool(data.get("mute", False)),
            properties=dict(data.get("properties") or {}),
        )


@dataclass
class Module:
    index: int
    name: str
    argument: str

    @property
    def args(self) -> dict[str, str]:
        return parse_modargs(self.argument)


@dataclass
class Event:
    """One line of `pactl subscribe`: "Event 'new' on sink-input #42"."""

    kind: str        # new | change | remove
    facility: str    # sink | source | sink-input | source-output | module | client | server | card
    index: int


_EVENT_RE = re.compile(r"Event '(?P<kind>\w+)' on (?P<facility>[\w-]+) #(?P<index>\d+)")


def parse_event(line: str) -> Event | None:
    match = _EVENT_RE.search(line)
    if not match:
        return None
    return Event(match["kind"], match["facility"], int(match["index"]))


def _int_or_none(value) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


# --- Module arguments -------------------------------------------------------

def _clean(value: str) -> str:
    """Module arguments have no escaping, so quotes cannot appear inside values."""
    return str(value).replace('"', "").replace("'", "")


def proplist(props: dict[str, str]) -> str:
    """A property list as a module argument value: 'a="x y" b="z"'.

    The outer single quotes matter: without them the module parser ends the
    value at the first space and "Vertex Game" becomes "Vertex".
    """
    inner = " ".join(f'{_clean(key)}="{_clean(value)}"' for key, value in props.items())
    return f"'{inner}'"


def parse_modargs(argument: str) -> dict[str, str]:
    """Parse 'a=1 b="x y" c=\'p="q"\'' into {'a': '1', 'b': 'x y', 'c': 'p="q"'}."""
    result: dict[str, str] = {}
    pos, text = 0, argument or ""
    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        eq = text.find("=", pos)
        if eq < 0:
            break
        key = text[pos:eq].strip()
        pos = eq + 1
        if pos < len(text) and text[pos] in "'\"":
            quote = text[pos]
            end = text.find(quote, pos + 1)
            end = len(text) if end < 0 else end
            value = text[pos + 1:end]
            pos = end + 1
        else:
            end = pos
            while end < len(text) and not text[end].isspace():
                end += 1
            value = text[pos:end]
            pos = end
        if key:
            result[key] = value
    return result


# --- The client -------------------------------------------------------------

class Pactl:
    """Run pactl commands. Every method raises AudioError on failure."""

    def __init__(self, binary: str = "pactl", timeout: float = 5.0):
        self.binary = binary
        self.timeout = timeout

    def run(self, *args: str) -> str:
        try:
            result = subprocess.run([self.binary, *args], capture_output=True, text=True,
                                    timeout=self.timeout)
        except FileNotFoundError as exc:
            raise AudioError("pactl is not installed (it ships in pulseaudio-utils / "
                             "libpulse).") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise AudioError(f"pactl {' '.join(args[:2])} failed: {exc}") from exc
        if result.returncode != 0:
            raise AudioError(last_line(result.stderr, f"pactl {args[0]} failed"))
        return result.stdout

    def json(self, *args: str):
        out = self.run("-f", "json", *args)
        try:
            return json.loads(out or "null")
        except ValueError as exc:
            raise AudioError("pactl returned unreadable output — Vertex needs pactl 16 or "
                             "newer.") from exc

    # --- Server -------------------------------------------------------------

    def info(self) -> dict:
        data = self.json("info")
        return data if isinstance(data, dict) else {}

    def available(self) -> bool:
        try:
            self.info()
        except AudioError:
            return False
        return True

    def is_pipewire(self) -> bool:
        return "pipewire" in str(self.info().get("server_name", "")).casefold()

    def default_sink(self) -> str:
        return self.run("get-default-sink").strip()

    def default_source(self) -> str:
        return self.run("get-default-source").strip()

    def set_default_sink(self, name: str) -> None:
        self.run("set-default-sink", name)

    def set_default_source(self, name: str) -> None:
        self.run("set-default-source", name)

    # --- Objects ------------------------------------------------------------

    def sinks(self) -> list[Device]:
        return [Device.from_json(item, "sink") for item in self.json("list", "sinks") or []]

    def sources(self) -> list[Device]:
        return [Device.from_json(item, "source") for item in self.json("list", "sources") or []]

    def sink_inputs(self) -> list[Stream]:
        return [Stream.from_json(item) for item in self.json("list", "sink-inputs") or []]

    def modules(self) -> list[Module]:
        modules = []
        for line in self.run("list", "short", "modules").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit():
                modules.append(Module(int(parts[0]), parts[1],
                                      parts[2] if len(parts) > 2 else ""))
        return modules

    # --- Changes ------------------------------------------------------------

    def load_module(self, name: str, args: dict[str, str]) -> int:
        tokens = [f"{key}={value}" for key, value in args.items()]
        out = self.run("load-module", name, *tokens).strip()
        try:
            return int(out.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise AudioError(f"Loading {name} returned no module index") from exc

    def unload_module(self, index: int) -> None:
        self.run("unload-module", str(index))

    def move_sink_input(self, index: int, sink: str) -> None:
        self.run("move-sink-input", str(index), sink)

    def set_sink_volume(self, name: str, volume: float) -> None:
        self.run("set-sink-volume", name, f"{max(0, round(volume * 100))}%")

    def set_sink_mute(self, name: str, muted: bool) -> None:
        self.run("set-sink-mute", name, "1" if muted else "0")

    def set_source_volume(self, name: str, volume: float) -> None:
        self.run("set-source-volume", name, f"{max(0, round(volume * 100))}%")

    def set_source_mute(self, name: str, muted: bool) -> None:
        self.run("set-source-mute", name, "1" if muted else "0")

    # --- Events -------------------------------------------------------------

    def watch(self, on_event: Callable[[Event], None],
              on_exit: Callable[[str], None] | None = None) -> EventWatcher:
        watcher = EventWatcher([self.binary, "subscribe"], on_event, on_exit)
        watcher.start()
        return watcher


class EventWatcher:
    """Runs `pactl subscribe` on a thread and reports each event.

    Callbacks run on the watcher's own thread; the UI marshals them across.
    """

    def __init__(self, argv: list[str], on_event: Callable[[Event], None],
                 on_exit: Callable[[str], None] | None = None):
        self.argv = argv
        self.on_event = on_event
        self.on_exit = on_exit
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self.argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                bufsize=1, preexec_fn=die_with_parent)
        except OSError as exc:
            raise AudioError(f"Could not watch audio events: {exc}") from exc
        self._thread = threading.Thread(target=self._read, name="pactl-subscribe", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            event = parse_event(line)
            if event is not None:
                try:
                    self.on_event(event)
                except Exception:       # a bad handler must not end the watch
                    pass
        proc.wait()
        if not self._stopping and self.on_exit is not None:
            self.on_exit(last_line(proc.stderr.read() if proc.stderr else "",
                                   "the audio server went away"))

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        self._stopping = True
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def describe(argv: Iterable[str]) -> str:
    """A shell-pasteable rendering of a command, for logs and error messages."""
    return shlex.join(list(argv))
