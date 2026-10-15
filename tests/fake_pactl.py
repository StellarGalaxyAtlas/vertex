"""An in-memory stand-in for pactl, simulating the modules Sonar uses."""

from __future__ import annotations

from vertex.audio.pulse import AudioError, Capture, Device, Module, Stream, parse_modargs


class FakePactl:
    def __init__(self, sinks=("hw_headset",), sources=("hw_mic",)):
        self._next = 100
        self.modules_: list[Module] = []
        self.sinks_: list[Device] = []
        self.sources_: list[Device] = []
        self.inputs_: list[Stream] = []
        self.outputs_: list[Capture] = []
        # Stream index → how many more move attempts to refuse (-1: always),
        # like a stream the server won't move while it starts or shuts down.
        self.refuse_moves: dict[int, int] = {}
        self.owner: dict[int, list] = {}
        self.calls: list[tuple] = []
        for name in sinks:
            self.add_sink(name)
        for name in sources:
            self.add_source(name)
        self.default_sink_ = sinks[0] if sinks else ""
        self.default_source_ = sources[0] if sources else ""

    def _id(self) -> int:
        self._next += 1
        return self._next

    def add_sink(self, name, module=None, props=None):
        sink = Device(self._id(), name, props.get("device.description", name) if props else name,
                      "sink", owner_module=module, properties=props or {})
        monitor = Device(self._id(), f"{name}.monitor", f"Monitor of {name}", "source",
                         owner_module=module, properties={"device.class": "monitor"})
        self.sinks_.append(sink)
        self.sources_.append(monitor)
        return sink

    def add_source(self, name, module=None, props=None):
        source = Device(self._id(), name, name, "source", owner_module=module,
                        properties=props or {})
        self.sources_.append(source)
        return source

    def remove_device(self, name):
        self.sinks_ = [d for d in self.sinks_ if d.name != name]
        self.sources_ = [d for d in self.sources_ if d.name not in (name, f"{name}.monitor")]
        # Loopbacks with sink_dont_move go with their sink, like the real thing.
        for module in list(self.modules_):
            if module.name == "module-loopback" and module.args.get("sink") == name:
                self.unload_module(module.index)

    def play(self, app, binary=None, sink=None):
        target = self._sink(sink or self.default_sink_)
        stream = Stream(self._id(), target.index, properties={
            "application.name": app, "application.process.binary": binary or app.lower()})
        self.inputs_.append(stream)
        return stream

    def record(self, app, source, binary=None, props=None):
        """An app recording from `source` (a device name)."""
        device = self._device(source)
        capture = Capture(self._id(), device.index, properties={
            "application.name": app, "application.process.binary": binary or app.lower(),
            **(props or {})})
        self.outputs_.append(capture)
        return capture

    def _sink(self, name) -> Device:
        for sink in self.sinks_:
            if sink.name == name:
                return sink
        raise AudioError(f"No such sink: {name}")

    # --- pactl surface ------------------------------------------------------

    def available(self):
        return True

    def watch(self, on_event, on_exit=None):
        """No server to watch; returns a watcher that is never running."""
        class _Watcher:
            running = False

            def stop(self):
                pass
        return _Watcher()

    def default_sink(self):
        return self.default_sink_

    def default_source(self):
        return self.default_source_

    def set_default_sink(self, name):
        self._sink(name)
        self.default_sink_ = name

    def set_default_source(self, name):
        if name not in {s.name for s in self.sources_}:
            raise AudioError(f"No such source: {name}")
        self.default_source_ = name

    def sinks(self):
        return list(self.sinks_)

    def sources(self):
        return list(self.sources_)

    def sink_inputs(self):
        return list(self.inputs_)

    def source_outputs(self):
        return list(self.outputs_)

    def modules(self):
        return list(self.modules_)

    def load_module(self, name, args):
        argument = " ".join(f"{key}={value}" for key, value in args.items())
        module = Module(self._id(), name, argument)
        parsed = parse_modargs(argument)
        self.calls.append(("load", name, parsed))
        props = parse_modargs(parsed.get("sink_properties") or
                              parsed.get("source_properties") or "")
        if name == "module-null-sink":
            self.add_sink(parsed["sink_name"], module.index, props)
        elif name == "module-loopback":
            self._sink(parsed["sink"])
            loop_props = parse_modargs(parsed.get("sink_input_properties", ""))
            self.inputs_.append(Stream(self._id(), self._sink(parsed["sink"]).index,
                                       owner_module=module.index, properties=loop_props))
        elif name == "module-remap-source":
            self.add_source(parsed["source_name"], module.index, props)
        self.modules_.append(module)
        return module.index

    def unload_module(self, index):
        self.calls.append(("unload", index))
        self.modules_ = [m for m in self.modules_ if m.index != index]
        gone = {d.name for d in self.sinks_ if d.owner_module == index}
        self.sinks_ = [d for d in self.sinks_ if d.owner_module != index]
        self.sources_ = [d for d in self.sources_ if d.owner_module != index]
        self.inputs_ = [s for s in self.inputs_ if s.owner_module != index]
        if gone and self.default_sink_ in gone:
            self.default_sink_ = self.sinks_[0].name if self.sinks_ else ""

    def move_sink_input(self, index, sink):
        target = self._sink(sink)
        refusals = self.refuse_moves.get(index, 0)
        if refusals:
            self.refuse_moves[index] = refusals - 1 if refusals > 0 else -1
            raise AudioError(f"Failed to move stream {index}")
        for stream in self.inputs_:
            if stream.index == index:
                stream.sink = target.index
                return
        raise AudioError("No such stream")

    def _device(self, name):
        for device in self.sinks_ + self.sources_:
            if device.name == name:
                return device
        raise AudioError(f"No such device: {name}")

    def set_sink_volume(self, name, volume):
        self._device(name).volume = volume

    def set_sink_mute(self, name, muted):
        self._device(name).muted = muted

    set_source_volume = set_sink_volume
    set_source_mute = set_sink_mute
