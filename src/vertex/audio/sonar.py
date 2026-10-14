"""Sonar: Vertex's virtual audio devices, and the routing between them.

Built from three stock modules, all of which PulseAudio and PipeWire's pulse
server both provide:

    module-null-sink     one virtual output per channel (vertex_game, …)
    module-loopback      plays each channel's monitor into the real output device
    module-remap-source  "Vertex Mic", a virtual input fed by the real microphone

Applications play into a channel; the channel's volume and mute apply on the
way to the headset; and a recorder captures each channel's monitor as its own
track. Which application lands on which channel is a rule keyed by the
program, applied whenever a new stream appears.

Everything is reconciled rather than blindly created: `up()` looks at what is
loaded, keeps what already matches, replaces what doesn't and removes
duplicates, so it is safe to run repeatedly, after a crash, or after the audio
server restarted underneath it. The loopbacks are created with
`sink_dont_move`, so unplugging the output device unloads them instead of
letting the server move them onto a channel — which would feed the channel
back into itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from vertex.audio import channels, devices
from vertex.audio.channels import Channel
from vertex.audio.pulse import (
    AudioError,
    Device,
    Event,
    Module,
    Pactl,
    Stream,
    from_server,
    proplist,
    to_server,
)
from vertex.config import SonarConfig

NULL_SINK = "module-null-sink"
LOOPBACK = "module-loopback"
REMAP_SOURCE = "module-remap-source"


@dataclass
class ChannelStatus:
    channel: Channel
    present: bool = False
    routed: bool = False         # an output channel is looped to a real device
    output: str = ""             # the real device an output channel plays through
    also: bool = False           # and it plays through the second device too
    volume: float = 1.0
    muted: bool = False


@dataclass
class AppStream:
    index: int
    key: str
    name: str
    icon: str
    channel: str | None          # the channel it is playing on, if one of ours
    rule: str | None             # the channel a rule sends it to, if any
    device: str = ""             # what it is playing on, as the system names it

    @property
    def stuck(self) -> bool:
        """It has a channel to go to, but is playing somewhere else — the
        server refused to move it (yet). `apply_rules` keeps retrying."""
        return self.rule is not None and self.channel != self.rule


@dataclass
class AppCapture:
    """An application recording from an input."""

    index: int
    key: str
    name: str
    icon: str
    device: str                  # the input it records from
    via_vertex: bool             # recording Vertex Mic, rather than a mic directly


@dataclass
class SonarStatus:
    available: bool = False
    error: str = ""
    active: bool = False
    output: str = ""             # real sink the channels play through
    mic: str = ""                # real source behind Vertex Mic
    channels: dict[str, ChannelStatus] = field(default_factory=dict)
    # Picked by hand for now, rather than the device manager's choice.
    output_picked: bool = False
    mic_picked: bool = False


@dataclass
class _State:
    """What Sonar changed and must put back: the defaults it replaced."""

    previous_sink: str = ""
    previous_source: str = ""
    output: str = ""
    mic: str = ""


class Sonar:
    def __init__(self, config: SonarConfig, state_file: str | None = None,
                 pactl: Pactl | None = None):
        self.config = config
        self.pactl = pactl or Pactl()
        self.state_file = state_file
        self.state = self._load_state()
        # Devices picked by hand for now, by kind ("output", "mic"): used
        # instead of the device manager's choice until a device of that kind
        # is plugged in or the one picked is unplugged. Never saved.
        self.picked = {"output": "", "mic": ""}
        self._connected: dict[str, set[str] | None] = {"output": None, "mic": None}

    # --- State file ---------------------------------------------------------

    def _load_state(self) -> _State:
        if not self.state_file:
            return _State()
        try:
            with open(self.state_file, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return _State()
        return _State(**{key: str(data.get(key, "")) for key in _State.__dataclass_fields__})

    def _save_state(self) -> None:
        if not self.state_file:
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as handle:
                json.dump(self.state.__dict__, handle, indent=2)
        except OSError:
            pass   # losing this only means defaults are not restored on `down`

    # --- Inspection ---------------------------------------------------------

    def outputs(self) -> list[Device]:
        """Real output devices a channel can play through."""
        return [sink for sink in self.pactl.sinks() if not sink.is_vertex]

    def inputs(self) -> list[Device]:
        """Real capture devices Vertex Mic can be fed from."""
        return [source for source in self.pactl.sources()
                if not source.is_monitor and not source.is_vertex]

    def _ours(self, modules: list[Module]) -> dict[str, list[Module]]:
        """Our modules by role: 'null:<id>', 'loop:<id>', 'mic'."""
        found: dict[str, list[Module]] = {}
        for module in modules:
            args = module.args
            if module.name == NULL_SINK:
                channel = channels.BY_NODE.get(args.get("sink_name", ""))
                if channel is not None and channel.is_output:
                    found.setdefault(f"null:{channel.id}", []).append(module)
            elif module.name == LOOPBACK:
                source = args.get("source", "").removesuffix(".monitor")
                channel = channels.BY_NODE.get(source)
                if channel is not None and channel.is_output:
                    found.setdefault(f"loop:{channel.id}", []).append(module)
            elif module.name == REMAP_SOURCE and args.get("source_name") == channels.MIC.node:
                found.setdefault("mic", []).append(module)
        return found

    def _resolve(self, wanted: str, devices: list[Device], fallbacks: list[str]) -> str:
        """The configured device if present, else the first fallback present."""
        names = {device.name for device in devices}
        for candidate in (wanted, *fallbacks):
            if candidate and candidate in names and not candidate.startswith("vertex_"):
                return candidate
        return devices[0].name if devices else ""

    def _picked_for_now(self, kind: str, connected: list[str]) -> str:
        """The device picked by hand for `kind`, unless a device of that kind
        was plugged in since the last look, or it was unplugged."""
        before, now = self._connected[kind], set(connected)
        self._connected[kind] = now
        if self.picked[kind] and (self.picked[kind] not in now or
                                  (before is not None and now - before)):
            self.picked[kind] = ""
        return self.picked[kind]

    def resolve_output(self, outputs: list[Device] | None = None) -> str:
        """The device the channels share: the one picked for now, else by the
        device manager's lists, else the one chosen in setup, the last one
        used, or the system's default."""
        outputs = self.outputs() if outputs is None else outputs
        cfg = self.config
        names = [device.name for device in outputs]
        chosen = devices.choose(cfg.output_priority, cfg.output_excluded, names,
                                self._picked_for_now("output", names))
        return chosen or self._resolve(
            cfg.output_device, outputs,
            [self.state.output, self.state.previous_sink, self._default_sink()])

    def second_output(self, channel: Channel, outputs: list[Device]) -> str:
        """The second device a channel also plays through, if one is set, the
        channel asks for it, and it is plugged in."""
        second = self.config.second_output
        if not second or not self.config.channel(channel.id).also_second:
            return ""
        return second if second in {device.name for device in outputs} else ""

    def channel_output(self, channel: Channel, outputs: list[Device], shared: str) -> str:
        """The device an output channel plays through: the shared one while
        linked, else its own, unless that is unplugged (then the shared one)."""
        if self.config.linked:
            return shared
        own = self.config.channel(channel.id).output_device
        if own and not own.startswith(channels.NODE_PREFIX) and \
                own in {device.name for device in outputs}:
            return own
        return shared

    def resolve_mic(self, inputs: list[Device] | None = None) -> str:
        inputs = self.inputs() if inputs is None else inputs
        cfg = self.config
        names = [device.name for device in inputs]
        chosen = devices.choose(cfg.mic_priority, cfg.mic_excluded, names,
                                self._picked_for_now("mic", names))
        return chosen or self._resolve(
            cfg.mic_device, inputs,
            [self.state.mic, self.state.previous_source, self._default_source()])

    def _default_sink(self) -> str:
        try:
            return self.pactl.default_sink()
        except AudioError:
            return ""

    def _default_source(self) -> str:
        try:
            return self.pactl.default_source()
        except AudioError:
            return ""

    def status(self) -> SonarStatus:
        status = SonarStatus()
        try:
            sinks = {sink.name: sink for sink in self.pactl.sinks()}
            sources = {source.name: source for source in self.pactl.sources()}
            ours = self._ours(self.pactl.modules())
        except AudioError as exc:
            status.error = str(exc)
            return status
        status.available = True
        status.output = self.state.output
        status.mic = self.state.mic
        status.output_picked = bool(self.picked["output"]) and \
            self.picked["output"] == status.output
        status.mic_picked = bool(self.picked["mic"]) and self.picked["mic"] == status.mic
        for channel in channels.ALL:
            device = (sinks if channel.is_output else sources).get(channel.node)
            entry = ChannelStatus(channel, present=device is not None)
            if device is not None:
                entry.volume, entry.muted = from_server(device.volume), device.muted
            loops = ours.get(f"loop:{channel.id}", [])
            entry.routed = bool(loops) if channel.is_output else bool(ours.get("mic"))
            targets = [module.args.get("sink", "") for module in loops]
            second = self.config.second_output
            entry.output = next((sink for sink in targets if sink != second),
                                targets[0] if targets else "")
            entry.also = bool(second) and second in targets and entry.output != second
            status.channels[channel.id] = entry
        status.active = all(entry.present for entry in status.channels.values())
        return status

    def is_active(self) -> bool:
        return self.status().active

    # --- Bringing it up -----------------------------------------------------

    def up(self, take_defaults: bool = True) -> list[str]:
        """Create or repair every device and route. Returns warnings to show.

        `take_defaults` makes the default channel and Vertex Mic the system
        defaults. Automatic repairs pass False, so a default the user picked
        by hand is left alone — unless the devices had to be recreated (the
        audio server restarted), in which case they are taken again.
        """
        warnings: list[str] = []
        outputs, inputs = self.outputs(), self.inputs()
        output = self.resolve_output(outputs)
        mic = self.resolve_mic(inputs)
        self._remember_defaults()

        ours = self._ours(self.pactl.modules())
        created = False
        for channel in channels.OUTPUTS:
            created |= self._ensure_sink(channel, ours.get(f"null:{channel.id}", []))
            targets = [target] if (target := self.channel_output(channel, outputs, output)) \
                else []
            second = self.second_output(channel, outputs)
            if second and second not in targets:
                targets.append(second)
            self._ensure_loopbacks(channel, targets, ours.get(f"loop:{channel.id}", []))
        if not output:
            warnings.append("No output device was found, so the channels are not "
                            "connected to anything you can hear.")
        if mic:
            # A mic that went missing and came back under the same name leaves
            # a remap pointing at a node that no longer exists; rebuild it.
            stale = self.state.mic != mic
            created |= self._ensure_mic(mic, ours.get("mic", []), rebuild=stale)
        else:
            warnings.append("No microphone was found, so Vertex Mic was not created.")

        self.state.output, self.state.mic = output, mic
        self._save_state()
        if take_defaults or created:
            self._take_defaults(mic_present=bool(mic))
        if created or take_defaults:
            self.apply_mix()
        self.apply_rules()
        return warnings

    def reconcile(self) -> list[str]:
        """Repair devices after a hardware change, if Sonar is meant to be up."""
        if not self.config.enabled:
            return []
        return self.up(take_defaults=False)

    def _ensure_sink(self, channel: Channel, existing: list[Module]) -> bool:
        """Exactly one virtual sink for `channel`. True if it had to be created."""
        for extra in existing[1:]:
            self._unload(extra)
        if existing:
            return False
        self.pactl.load_module(NULL_SINK, {
            "sink_name": channel.node,
            "sink_properties": proplist({
                "device.description": channel.description,
                "media.icon_name": channel.icon,
                "device.icon_name": channel.icon,
                "vertex.channel": channel.id,
            }),
        })
        return True

    def _ensure_loopbacks(self, channel: Channel, targets: list[str],
                          existing: list[Module]) -> None:
        """One loopback from `channel` to each of `targets`, and no others."""
        latency = str(max(1, int(self.config.latency_ms)))
        kept: set[str] = set()
        for module in existing:
            sink = module.args.get("sink", "")
            if sink in targets and sink not in kept and \
                    module.args.get("latency_msec") == latency:
                kept.add(sink)
            else:
                self._unload(module)
        for target in targets:
            if target not in kept:
                self._load_loopback(channel, target, latency)

    def _load_loopback(self, channel: Channel, output: str, latency: str) -> None:
        self.pactl.load_module(LOOPBACK, {
            "source": channel.record_source,
            "sink": output,
            "latency_msec": latency,
            "source_dont_move": "true",
            "sink_dont_move": "true",
            "sink_input_properties": proplist({
                "media.name": f"{channel.description} → output",
                "vertex.loopback": channel.id,
            }),
            "source_output_properties": proplist({"vertex.loopback": channel.id}),
        })

    def _ensure_mic(self, mic: str, existing: list[Module], rebuild: bool = False) -> bool:
        """Vertex Mic fed from `mic`. True if it had to be (re)created.

        With no mic at all the existing remap is left in place: a silent
        Vertex Mic keeps chat apps pointed at it until a mic returns.
        """
        keep = None
        for module in existing:
            if keep is None and not rebuild and module.args.get("master") == mic:
                keep = module
            else:
                self._unload(module)
        if keep is not None:
            return False
        self.pactl.load_module(REMAP_SOURCE, {
            "master": mic,
            "source_name": channels.MIC.node,
            "source_properties": proplist({
                "device.description": channels.MIC.description,
                "media.icon_name": channels.MIC.icon,
                "device.icon_name": channels.MIC.icon,
                "vertex.channel": channels.MIC.id,
            }),
        })
        return True

    def _remember_defaults(self) -> None:
        """Note the system defaults we are about to replace — unless they are
        already ours, which means we replaced them earlier and still know."""
        sink, source = self._default_sink(), self._default_source()
        if sink and not sink.startswith("vertex_"):
            self.state.previous_sink = sink
        if source and not source.startswith("vertex_"):
            self.state.previous_source = source
        self._save_state()

    def _take_defaults(self, mic_present: bool) -> None:
        target = channels.get(self.config.default_channel) or channels.GAME
        try:
            self.pactl.set_default_sink(target.node)
            if self.config.set_default_mic and mic_present:
                self.pactl.set_default_source(channels.MIC.node)
        except AudioError:
            pass   # the devices exist; defaults are a convenience

    def _unload(self, module: Module) -> None:
        try:
            self.pactl.unload_module(module.index)
        except AudioError:
            pass   # already gone

    # --- Taking it down -----------------------------------------------------

    def down(self) -> None:
        """Remove every Vertex device and give the system its defaults back."""
        self.picked = {"output": "", "mic": ""}      # picks last while Sonar runs
        self._connected = {"output": None, "mic": None}
        outputs = self.outputs()
        names = {device.name for device in outputs}
        restore_sink = next((name for name in (self.state.previous_sink, self.state.output)
                             if name in names), outputs[0].name if outputs else "")
        source_names = {device.name for device in self.inputs()}
        restore_source = next((name for name in (self.state.previous_source, self.state.mic)
                               if name in source_names), "")
        try:
            if restore_sink:
                self.pactl.set_default_sink(restore_sink)
            if restore_source:
                self.pactl.set_default_source(restore_source)
        except AudioError:
            pass

        # Move streams off the channels first, so they land on the restored
        # default rather than wherever the server would pick.
        if restore_sink:
            ours = {sink.index for sink in self.pactl.sinks() if sink.is_vertex}
            for stream in self.pactl.sink_inputs():
                if stream.sink in ours and not self._is_loopback(stream):
                    try:
                        self.pactl.move_sink_input(stream.index, restore_sink)
                    except AudioError:
                        pass

        modules = self._ours(self.pactl.modules())
        order = [key for key in modules if key.startswith("loop:")] + \
            [key for key in modules if key == "mic"] + \
            [key for key in modules if key.startswith("null:")]
        for key in order:
            for module in modules[key]:
                self._unload(module)
        self.state = _State()
        self._save_state()

    # --- Mixing -------------------------------------------------------------

    def apply_mix(self) -> None:
        """Push the configured volumes and mutes onto the devices."""
        for channel in channels.ALL:
            settings = self.config.channel(channel.id)
            self._set_volume(channel, settings.volume)
            self._set_muted(channel, settings.muted)

    def set_volume(self, channel_id: str, volume: float) -> None:
        channel = channels.BY_ID[channel_id]
        self.config.channel(channel_id).volume = max(0.0, min(1.0, volume))
        self._set_volume(channel, self.config.channel(channel_id).volume)

    def set_muted(self, channel_id: str, muted: bool) -> None:
        channel = channels.BY_ID[channel_id]
        self.config.channel(channel_id).muted = muted
        self._set_muted(channel, muted)

    def _set_volume(self, channel: Channel, volume: float) -> None:
        try:
            if channel.is_output:
                self.pactl.set_sink_volume(channel.node, to_server(volume))
            else:
                self.pactl.set_source_volume(channel.node, to_server(volume))
        except AudioError:
            pass   # the device is not up; the setting applies when it is

    def _set_muted(self, channel: Channel, muted: bool) -> None:
        try:
            if channel.is_output:
                self.pactl.set_sink_mute(channel.node, muted)
            else:
                self.pactl.set_source_mute(channel.node, muted)
        except AudioError:
            pass

    def _pick(self, kind: str, device: str, lasting: bool) -> None:
        """Use `device` for now, or (`lasting`, as setup does) put it on top
        of the device manager's list."""
        if not lasting:
            self.picked[kind] = device
            self._connected[kind] = None     # what is plugged in now doesn't undo it
            return
        self.picked[kind] = ""
        if device:
            cfg = self.config
            priority, excluded = devices.promote(getattr(cfg, f"{kind}_priority"),
                                                 getattr(cfg, f"{kind}_excluded"), device)
            setattr(cfg, f"{kind}_priority", priority)
            setattr(cfg, f"{kind}_excluded", excluded)
            setattr(cfg, f"{kind}_device", device)

    def set_channel_output(self, channel_id: str, device: str,
                           lasting: bool = False) -> list[str]:
        """Play a channel through `device`: every output channel while linked,
        for now (see _pick); unlinked, the channel keeps it as its own."""
        if self.config.linked:
            self._pick("output", device, lasting)
        else:
            self.config.channel(channel_id).output_device = device
        return self.up() if self.config.enabled else []

    def set_linked(self, linked: bool, channel_id: str) -> list[str]:
        """Linking plays every output channel through `channel_id`'s device.
        Unlinking keeps each where it is, ready to be set apart."""
        if linked:
            if not self.config.linked:
                own = self.config.channel(channel_id).output_device
                if own:
                    self._pick("output", own, lasting=False)
        else:
            shared = self.state.output or self.config.output_device
            for channel in channels.OUTPUTS:
                self.config.channel(channel.id).output_device = shared
        self.config.linked = linked
        return self.up() if self.config.enabled else []

    def set_mic(self, device: str, lasting: bool = False) -> list[str]:
        """Feed Vertex Mic from `device`, for now (see _pick)."""
        self._pick("mic", device, lasting)
        return self.up() if self.config.enabled else []

    def set_second_output(self, device: str) -> list[str]:
        """A device the output channels also play through ("" for none)."""
        self.config.second_output = device
        return self.up() if self.config.enabled else []

    def set_also_second(self, channel_id: str, also: bool) -> list[str]:
        """Whether a channel also plays through the second device."""
        self.config.channel(channel_id).also_second = also
        return self.up() if self.config.enabled else []

    def learn_devices(self, outputs: list[Device], inputs: list[Device]) -> bool:
        """Add devices seen for the first time to the device manager's lists
        and remember every device's name. True if anything changed."""
        cfg = self.config
        before = (list(cfg.output_priority), list(cfg.mic_priority), dict(cfg.device_names))
        cfg.output_priority = devices.learn(cfg.output_priority, cfg.output_excluded,
                                            [d.name for d in outputs],
                                            self.state.output or cfg.output_device)
        cfg.mic_priority = devices.learn(cfg.mic_priority, cfg.mic_excluded,
                                         [d.name for d in inputs],
                                         self.state.mic or cfg.mic_device)
        for device in (*outputs, *inputs):
            if device.description:
                cfg.device_names[device.name] = device.description
        return before != (cfg.output_priority, cfg.mic_priority, cfg.device_names)

    def set_device_volume(self, kind: str, name: str, volume: float) -> None:
        """The volume of a real device (kind: "sink" or "source"), as a slider
        level."""
        try:
            if kind == "sink":
                self.pactl.set_sink_volume(name, to_server(volume))
            else:
                self.pactl.set_source_volume(name, to_server(volume))
        except AudioError:
            pass   # unplugged meanwhile

    # --- Routing ------------------------------------------------------------

    @staticmethod
    def _is_loopback(stream: Stream) -> bool:
        return "vertex.loopback" in stream.properties

    def streams(self) -> list[AppStream]:
        """Every application currently playing, and which channel it is on.

        Streams created by modules (Vertex's own loopbacks, echo cancellers…)
        and volume meters are not applications and are left out.
        """
        sinks = {sink.index: sink for sink in self.pactl.sinks()}
        result = []
        for stream in self.pactl.sink_inputs():
            if self._is_loopback(stream) or stream.owner_module is not None or stream.is_meter:
                continue
            sink = sinks.get(stream.sink)
            channel = channels.BY_NODE.get(sink.name) if sink else None
            result.append(AppStream(
                index=stream.index, key=stream.key, name=stream.app_name, icon=stream.icon,
                channel=channel.id if channel else None,
                rule=self.config.app_rules.get(stream.key),
                device=sink.label if sink else "",
            ))
        return result

    def recorders(self) -> list[AppCapture]:
        """Every application recording from a microphone — through Vertex Mic
        or straight from a device. Monitors (recordings of an output, which is
        how a screen recorder takes desktop audio) and meters are left out."""
        sources = {source.index: source for source in self.pactl.sources()}
        result = []
        for capture in self.pactl.source_outputs():
            if capture.owner_module is not None or capture.is_meter or \
                    "vertex.loopback" in capture.properties:
                continue
            source = sources.get(capture.source)
            if source is None or source.is_monitor:
                continue
            result.append(AppCapture(
                index=capture.index, key=capture.key, name=capture.app_name,
                icon=capture.icon, device=source.label,
                via_vertex=source.name == channels.MIC.node))
        return result

    def route(self, app_key: str, channel_id: str | None) -> int:
        """Send an application to a channel from now on. None clears the rule
        and moves it back to the default channel. Returns streams moved."""
        if channel_id is None:
            self.config.app_rules.pop(app_key, None)
            target = self.config.default_channel
        else:
            if channels.get(channel_id) is None or not channels.BY_ID[channel_id].is_output:
                raise ValueError(f"{channel_id!r} is not an output channel")
            self.config.app_rules[app_key] = channel_id
            target = channel_id
        return self._move_matching(lambda stream: stream.key == app_key, target)

    def apply_rules(self, index: int | None = None) -> int:
        """Move streams their rules say belong elsewhere. Returns streams moved."""
        if not self.config.app_rules:
            return 0
        moved = 0
        sinks = {sink.index: sink.name for sink in self.pactl.sinks()}
        present = set(sinks.values())
        for stream in self.pactl.sink_inputs():
            if index is not None and stream.index != index:
                continue
            if self._is_loopback(stream):
                continue
            target = channels.get(self.config.app_rules.get(stream.key, ""))
            if target is None or target.node not in present:
                continue
            if sinks.get(stream.sink) != target.node:
                try:
                    self.pactl.move_sink_input(stream.index, target.node)
                    moved += 1
                except AudioError:
                    # Ended in the meantime, or the server won't move it right
                    # now (a stream starting up or shutting down). It shows as
                    # stuck, and the next call tries again.
                    pass
        return moved

    def _move_matching(self, predicate, channel_id: str) -> int:
        target = channels.BY_ID[channel_id].node
        moved = 0
        for stream in self.pactl.sink_inputs():
            if not self._is_loopback(stream) and predicate(stream):
                try:
                    self.pactl.move_sink_input(stream.index, target)
                    moved += 1
                except AudioError:
                    pass
        return moved

    def game_apps(self) -> list[str]:
        """Names of the applications playing on the Game channel right now."""
        try:
            return [stream.name for stream in self.streams()
                    if stream.channel == channels.GAME.id]
        except AudioError:
            return []

    # --- Events -------------------------------------------------------------

    def handle(self, event: Event) -> str | None:
        """React to one server event. Returns 'reconcile' when devices changed
        in a way that needs `reconcile()` (callers debounce that)."""
        if event.facility == "sink-input" and event.kind == "new":
            try:
                self.apply_rules(event.index)
            except AudioError:
                pass
            return None
        # Devices coming and going: a headset unplugged, a USB mic plugged in,
        # or the audio server restarting under us. "change" events are left
        # alone — setting a volume or a default emits them, and reacting would
        # chase our own tail.
        if event.facility in ("sink", "source") and event.kind in ("new", "remove"):
            return "reconcile"
        return None
