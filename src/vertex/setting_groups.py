"""Every setting, grouped as Settings shows them: what a restore lets the user
pick from. Each item names the config fields it carries over, and between
them the items cover every field (a test keeps it so). No Qt."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable
from dataclasses import dataclass

from vertex import fmt, paths, platform
from vertex.config import Config

LIBRARY = "library"           # the item that stands for the library, not a setting


@dataclass(frozen=True)
class Item:
    key: str
    title: str
    fields: tuple[str, ...]          # dotted: "recorder.fps"
    shown: Callable[[Config], str]   # its value, in a few words
    folders: bool = False            # names folders, which may not be on this computer
    recorder: bool = False           # belongs to the recorder (or Sonar) it was set for


@dataclass(frozen=True)
class Group:
    title: str
    items: tuple[Item, ...]


def _on(value: bool) -> str:
    return "On" if value else "Off"


def _folder(path: str) -> str:
    return paths.tilde(paths.normalize(path)) or "Vertex's own"


def _count(items, noun: str, none: str = "None") -> str:
    return fmt.plural(len(items), noun) if items else none


def _capture(c: Config) -> str:
    rec = c.recorder
    where = rec.capture if rec.capture not in ("screen", "focused", "portal", "region") \
        else {"screen": "Whole screen", "focused": "Window in front", "portal": "Ask each time",
              "region": "A region"}[rec.capture]
    return ", ".join(part for part in (where, rec.resolution, f"{rec.fps} fps") if part)


def _tracks(c: Config) -> str:
    rec = c.recorder
    used = [name for name, device in (("Game", rec.game_audio), ("Chat", rec.chat_audio),
                                      ("Media", rec.media_audio), ("Mic", rec.mic_audio))
            if device]
    return ", ".join(used) or "None"


GROUPS: tuple[Group, ...] = (
    Group("General", (
        Item("colour_scheme", "Colour scheme", ("colour_scheme",),
             lambda c: c.colour_scheme.replace("_", " ").title()),
        Item("clip_path", "Clips folder", ("clip_path",), lambda c: _folder(c.clip_path),
             folders=True),
        Item("export_path", "Exports folder", ("export_path",),
             lambda c: _folder(c.export_path), folders=True),
        Item("other_folders", "Library, cache and log folders",
             ("data_path", "state_path", "cache_path", "log_path"),
             lambda c: _folder(c.data_path), folders=True),
        Item("close_to_tray", "Close to tray", ("close_to_tray",),
             lambda c: _on(c.close_to_tray)),
        Item("keep_logs", "Keep logs", ("keep_logs",), lambda c: _on(c.keep_logs)),
        Item("daily_backup", "Back up every day", ("daily_backup",),
             lambda c: _on(c.daily_backup)),
        Item("viewing", "Card size, playback volume, export size",
             ("card_width", "playback_volume", "export_size"),
             lambda c: f"{c.card_width} px, {c.playback_volume}%"),
    )),
    Group("Recording", (
        Item("recording", "Record clips with Vertex", ("recorder.enabled",),
             lambda c: _on(c.recorder.enabled)),
        Item("capture", "What's recorded", (
            "recorder.capture", "recorder.region", "recorder.resolution", "recorder.fps",
            "recorder.cursor", "recorder.restore_portal_session"), _capture, recorder=True),
        Item("quality", "Quality and format", (
            "recorder.container", "recorder.video_codec", "recorder.quality",
            "recorder.bitrate_kbps", "recorder.bitrate_mode", "recorder.framerate_mode",
            "recorder.color_range", "recorder.encoder", "recorder.keyframe_interval",
            "recorder.audio_codec", "recorder.audio_bitrate", "recorder.extra_args"),
             lambda c: f"{c.recorder.quality.replace('_', ' ').capitalize()}, "
                       f"{c.recorder.container.upper()}", recorder=True),
        Item("replay", "Replay length and storage", (
            "recorder.replay_seconds", "recorder.replay_storage", "recorder.output_dir"),
             lambda c: fmt.duration(c.recorder.replay_seconds), recorder=True),
        Item("tracks", "Audio tracks and volumes", (
            "recorder.game_audio", "recorder.chat_audio", "recorder.media_audio",
            "recorder.mic_audio", "recorder.game_volume", "recorder.chat_volume",
            "recorder.media_volume", "recorder.mic_volume"), _tracks, recorder=True),
        Item("autostart", "Start the replay buffer with Vertex", ("recorder.autostart",),
             lambda c: _on(c.recorder.autostart)),
        Item("tagging", "Tag clips with the game", ("recorder.tag_with_game",),
             lambda c: _on(c.recorder.tag_with_game)),
        Item("recorder_program", "Recorder program", ("recorder.command",),
             lambda c: os.path.basename(c.recorder.command) or "Found by itself",
             recorder=True),
    )),
    Group("Notifications", (
        Item("notifications", "Which notifications", ("notifications",),
             lambda c: f"{len(c.notifications)} changed" if c.notifications else "Default"),
        Item("notify_over_games", "Over games", ("notify_over_games",),
             lambda c: _on(c.notify_over_games)),
        Item("sounds", "Sounds", ("sounds", "sound_files", "sound_volume"),
             lambda c: f"{c.sound_volume}%" + (", your own files" if c.sound_files else "")),
    )),
    Group("Shortcuts", (
        Item("hotkeys", "Hotkeys", ("hotkeys",),
             lambda c: _count([k for k in c.hotkeys.values() if k], "hotkey")),
        Item("hotkey_last_seconds", "Save the last…", ("hotkey_last_seconds",),
             lambda c: fmt.plural(c.hotkey_last_seconds, "second")),
    )),
    Group("Import and setup", (
        Item("name_patterns", "Clip file names", ("name_patterns",),
             lambda c: ", ".join(p.app for p in c.patterns()) or "None"),
        Item("game_names", "Game names", ("game_names",),
             lambda c: _count(c.game_names, "game")),
        Item("kept_tags", "Tags kept over file names", ("kept_tags",),
             lambda c: _count(c.kept_tags, "tag")),
    )),
    Group("Sonar", (
        Item("sonar_devices", "Devices and outputs", (
            "sonar.enabled", "sonar.output_device", "sonar.linked", "sonar.second_output",
            "sonar.mic_device", "sonar.default_channel", "sonar.set_default_mic",
            "sonar.latency_ms", "sonar.device_names"),
             lambda c: _on(c.sonar.enabled), recorder=True),
        Item("sonar_channels", "Channel volumes", ("sonar.channels",),
             lambda c: ", ".join(f"{key.title()} {round(ch.volume * 100)}%"
                                 for key, ch in c.sonar.channels.items()), recorder=True),
        Item("sonar_apps", "Apps on each channel", ("sonar.app_rules",),
             lambda c: _count(c.sonar.app_rules, "app"), recorder=True),
        Item("sonar_order", "Device order", (
            "sonar.output_priority", "sonar.output_excluded", "sonar.mic_priority",
            "sonar.mic_excluded", "sonar.show_disconnected"),
             lambda c: _count(c.sonar.output_priority + c.sonar.mic_priority, "device"),
             recorder=True),
    )),
)


def groups() -> tuple[Group, ...]:
    """The groups shown here: Sonar's only where there is Sonar."""
    return tuple(group for group in GROUPS if group.title != "Sonar" or platform.SONAR)


def left_here(settings: Config) -> list[str]:
    """The groups `settings` set apart from their defaults that this system
    doesn't have (Sonar, without Sonar): they stay in the backup."""
    defaults = Config()
    shown = groups()
    return [group.title for group in GROUPS if group not in shown and
            any(differs(item, settings, defaults) for item in group.items)]


def items() -> dict[str, Item]:
    return {item.key: item for group in GROUPS for item in group.items}


def get(config: Config, dotted: str):
    target = config
    for part in dotted.split("."):
        target = getattr(target, part)
    return target


def put(config: Config, dotted: str, value) -> None:
    *path, last = dotted.split(".")
    target = config
    for part in path:
        target = getattr(target, part)
    setattr(target, last, value)


def differs(item: Item, one: Config, other: Config) -> bool:
    return any(_plain(get(one, name)) != _plain(get(other, name)) for name in item.fields)


def _plain(value):
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else \
        {k: _plain(v) for k, v in value.items()} if isinstance(value, dict) else value
