"""The recorder this system has: GPU Screen Recorder on Linux, OBS Studio on
Windows. The rest of Vertex asks this module, so Settings, setup, doctor and
the replay buffer read the same on both. No Qt here.
"""

from __future__ import annotations

import os
import shlex

from vertex import paths, platform
from vertex.config import Config
from vertex.recorder import gsr, obs, presets
from vertex.recorder.gsr import CaptureOption, GsrInfo, Track
from vertex.recorder.monitors import Monitor

# What "save the last N seconds" offers, on either recorder.
SAVE_PRESETS = gsr.SAVE_PRESETS


def is_obs() -> bool:
    return platform.RECORDER == "obs"


def name() -> str:
    return obs.NAME if is_obs() else "GPU Screen Recorder"


def install_url() -> str:
    return obs.INSTALL_URL if is_obs() else gsr.INSTALL_URL


def min_version() -> tuple[int, ...]:
    return obs.MIN_VERSION if is_obs() else gsr.MIN_VERSION


def default_command() -> str:
    """The command used when none is set: OBS is found where it is installed."""
    return platform.RECORDER_COMMAND


def has_notifier() -> bool:
    """Whether GSR's in-game notifier can exist here."""
    return not is_obs()


def volume_after_save() -> bool:
    """Whether Vertex sets each track's volume in a clip once it is saved
    (media.track_volume): GSR records devices as they are, while OBS records
    each track at its volume itself."""
    return not is_obs()


def quality_levels() -> tuple[str, ...]:
    """The video quality levels Settings offers: OBS has two of its own."""
    return obs.QUALITY_LEVELS if is_obs() else presets.LEVELS


def detect(command: str) -> GsrInfo:
    return obs.detect(command) if is_obs() else gsr.detect(command)


def list_capture_options(command: str) -> list[CaptureOption]:
    return obs.list_capture_options(command) if is_obs() else gsr.list_capture_options(command)


def list_audio_devices(command: str) -> list[tuple[str, str]]:
    return obs.list_audio_devices(command) if is_obs() else gsr.list_audio_devices(command)


def is_output(device: str) -> bool:
    """Whether a device from list_audio_devices plays sound (a track records
    what goes to it) rather than records it."""
    return obs.is_output(device) if is_obs() else device.endswith(".monitor")


def validate(rec) -> list[str]:
    return obs.validate(rec) if is_obs() else gsr.validate(rec)


def recorder(on_state=None, on_saved=None):
    if is_obs():
        from vertex.recorder.obs_replay import ObsRecorder

        return ObsRecorder(on_state, on_saved)
    from vertex.recorder.replay import ReplayRecorder

    return ReplayRecorder(on_state, on_saved)


def launch_plan(config: Config, monitor_list: list[Monitor], tracks: list[Track],
                info: GsrInfo | None = None):
    """What the recorder is started with: GSR's command line, or OBS's plan."""
    resolved = presets.resolve(config.recorder, monitor_list)
    if not is_obs():
        return gsr.build_argv(resolved, tracks, config.resolved_recording_dir(), info)
    monitor = presets.recorded_monitor(config.recorder, monitor_list)
    pixels = monitor.pixels if monitor is not None and all(monitor.pixels) \
        else presets.ASSUMED_PIXELS
    output = presets.output_size(config.recorder.resolution, pixels)
    save_dir = paths.real(os.path.join(config.resolved_cache_dir(), "obs"))
    return obs.plan(resolved, tracks, save_dir, pixels, output, obs.gpu_vendor(),
                    presets.clip_bytes(resolved, len(tracks)))


def describe(plan) -> str:
    return obs.describe(plan) if isinstance(plan, obs.Plan) else shlex.join(plan)
