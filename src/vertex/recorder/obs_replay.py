"""Running OBS Studio's replay buffer for Vertex, over obs-websocket.

The same shape as replay.ReplayRecorder, which runs GPU Screen Recorder:
start, stop and save, with the state and each saved clip reported through
callbacks on its own threads. Starting brings OBS up in the tray if it isn't
running, switches it to Vertex's profile and scene collection, sets them up
from the plan (obs.plan) and starts the buffer. OBS is left running when the
buffer stops, as an app of its own, until `close_app`: that quits an OBS
this recorder started, and leaves one the user started alone.

OBS saves the whole buffer into a folder of Vertex's. Each save is then
finished into the clips folder: cut to the last N seconds when that was asked
for, its tracks titled after what they hold, written under a staging name and
moved into place. No Qt here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from vertex import paths
from vertex.core.clips import staging_path
from vertex.logs import RECORDER as log
from vertex.media import probe, trim
from vertex.media.ffmpeg import MediaError, run_quiet
from vertex.media.roles import ALL as ROLES
from vertex.recorder import obs
from vertex.recorder.obsws import Client, ObsError
from vertex.recorder.replay import RecorderError, State

HOST = "127.0.0.1"
# How long OBS gets to come up and open its WebSocket server after starting.
LAUNCH_SECONDS = 60.0
# How long the buffer gets to report itself started or stopped.
OUTPUT_SECONDS = 10.0

# The sources Vertex puts in its scene, so ones no longer wanted can go.
OWN_INPUTS = {obs.DISPLAY_INPUT, *(role.track_title for role in ROLES)}


def finish(raw: str, clip_dir: str, seconds: int | None, titles: dict[int, str],
           when: float | None = None) -> str:
    """Turn an OBS save into a clip in `clip_dir`: its last `seconds` (all of
    it for None), tracks titled, named Replay_<date>_<time> as GSR names them.
    The save is removed once the clip is in place; if it can't be finished
    it is moved there as it is, so nothing recorded is lost."""
    ext = os.path.splitext(raw)[1] or ".mp4"
    stamp = time.strftime("Replay_%Y-%m-%d_%H-%M-%S", time.localtime(when))
    os.makedirs(clip_dir, exist_ok=True)
    target, count = os.path.join(clip_dir, stamp + ext), 2
    while os.path.exists(target):
        target = os.path.join(clip_dir, f"{stamp} ({count}){ext}")
        count += 1
    staging = staging_path(target, "saving")
    length = probe.duration(raw) or 0.0
    start = max(0.0, length - seconds) if seconds and length > seconds else 0.0
    end = length if length else 10_000_000.0
    try:
        run_quiet(trim.trim_command(raw, staging, start, end, titles), 600,
                  "Could not finish the clip")
        os.replace(staging, target)
    except (MediaError, OSError) as exc:
        log.error("%s; keeping OBS's save as it is", exc)
        try:
            os.remove(staging)
        except OSError:
            pass
        shutil.move(raw, target)
        return target
    try:
        os.remove(raw)
    except OSError as exc:
        log.warning("Couldn't remove OBS's save %s: %s", raw, exc)
    return target


class ObsRecorder:
    def __init__(self,
                 on_state: Callable[[State, str], None] | None = None,
                 on_saved: Callable[[str], None] | None = None):
        self.on_state = on_state
        self.on_saved = on_saved
        self.state = State.STOPPED
        self.error = ""
        self.plan: obs.Plan | None = None
        self.clip_dir = ""
        self._client: Client | None = None
        self._lock = threading.Lock()
        self._stopping = False
        self._saves: deque[int | None] = deque()
        # The OBS this recorder started, if it did.
        self._launched: subprocess.Popen | None = None

    # --- Lifecycle ----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self.state in (State.STARTING, State.RUNNING)

    @property
    def pid(self) -> int | None:
        return None

    def start(self, setup: obs.Plan, clip_dir: str) -> None:
        with self._lock:
            if self.running:
                raise RecorderError("The replay buffer is already running.")
            try:
                os.makedirs(clip_dir, exist_ok=True)
                paths.make_dir(setup.save_dir)
            except OSError as exc:
                raise RecorderError(f"Could not create {exc.filename}: {exc}") from exc
            self.plan, self.clip_dir = setup, clip_dir
            self._stopping = False
            self._saves.clear()
            self.error = ""
            self.state = State.STARTING
        self._set(State.STARTING)
        threading.Thread(target=self._start, args=(setup,), daemon=True,
                         name="obs-start").start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the buffer without saving it. OBS keeps running."""
        with self._lock:
            client, self._stopping = self._client, True
        if client is not None and client.connected:
            try:
                client.request("StopReplayBuffer", timeout=timeout)
                self._wait_output(client, False, timeout)
            except ObsError as exc:
                log.info("Stopping OBS's replay buffer: %s", exc)
            client.close()
        self._client = None
        self._set(State.STOPPED)

    def close_app(self) -> None:
        """Stop the buffer, and quit OBS if this recorder started it."""
        self.stop()
        launched, self._launched = self._launched, None
        if launched is not None and obs.close(launched):
            log.info("Closed OBS, which Vertex started")

    def save(self, seconds: int | None = None) -> None:
        client = self._client
        if client is None or self.state != State.RUNNING:
            raise RecorderError("The replay buffer is not running.")
        self._saves.append(seconds)
        try:
            client.request("SaveReplayBuffer")
        except ObsError as exc:
            self._saves.pop()
            raise RecorderError(str(exc)) from exc

    # --- Starting -------------------------------------------------------------

    def _start(self, setup: obs.Plan) -> None:
        try:
            client = self._connect(setup)
            with self._lock:
                if self._stopping:
                    client.close()
                    return
                self._client = client
            log.info("Connected to OBS; setting up the profile and scene")
            self._setup(client, setup)
            if client.request("GetReplayBufferStatus").get("outputActive"):
                # Started by OBS itself, or by an earlier Vertex: restart it,
                # so the settings just made apply.
                client.request("StopReplayBuffer")
                self._wait_output(client, False, OUTPUT_SECONDS)
            client.request("StartReplayBuffer")
            if not self._wait_output(client, True, OUTPUT_SECONDS):
                raise ObsError("OBS didn't start the replay buffer. Its log (Help › Log "
                               "Files in OBS) says why.")
        except (ObsError, OSError) as exc:
            self._fail(str(exc))
            return
        if not self._stopping:
            self._set(State.RUNNING)

    def _connect(self, setup: obs.Plan) -> Client:
        exe = obs.find(setup.command)
        settings = obs.websocket_settings()
        launched = False
        if not obs.running():
            if not exe:
                raise ObsError(f"{obs.NAME} is not installed.")
            if not settings.enabled or (settings.auth and not settings.password):
                log.info("Switching on OBS's WebSocket server")
                settings = obs.enable_websocket()
            log.info("Starting OBS: %s", exe)
            self._launched = obs.launch(exe)
            launched = True
        elif not settings.enabled:
            raise ObsError("OBS's WebSocket server is off. Close OBS and Vertex switches it "
                           "on, or turn it on in OBS under Tools › WebSocket Server Settings.")
        deadline = time.monotonic() + (LAUNCH_SECONDS if launched else 5.0)
        while True:
            client = Client(on_event=self._on_event, on_close=self._on_close)
            try:
                client.connect(HOST, settings.port, settings.password if settings.auth else "")
                return client
            except ObsError as exc:
                if exc.code or time.monotonic() > deadline or self._stopping:
                    raise
            time.sleep(1.0)

    def _setup(self, client: Client, setup: obs.Plan) -> None:
        # The profile: OBS reads its output settings when the profile loads,
        # so after changing them it is loaded again, by way of another one.
        profiles = client.request("GetProfileList")
        if obs.PROFILE not in profiles.get("profiles", []):
            client.request("CreateProfile", {"profileName": obs.PROFILE})
        elif profiles.get("currentProfileName") != obs.PROFILE:
            client.request("SetCurrentProfile", {"profileName": obs.PROFILE})
        changed = False
        for section, key, value in setup.profile:
            now = client.request("GetProfileParameter", {"parameterCategory": section,
                                                         "parameterName": key})
            if now.get("parameterValue") != value:
                client.request("SetProfileParameter", {"parameterCategory": section,
                                                       "parameterName": key,
                                                       "parameterValue": value})
                changed = True
        if changed:
            others = [name for name in client.request("GetProfileList").get("profiles", [])
                      if name != obs.PROFILE]
            if others:
                client.request("SetCurrentProfile", {"profileName": others[0]})
            else:
                client.request("CreateProfile", {"profileName": obs.SPARE_PROFILE})
            client.request("SetCurrentProfile", {"profileName": obs.PROFILE})
        client.request("SetVideoSettings", {
            "fpsNumerator": setup.fps, "fpsDenominator": 1,
            "baseWidth": setup.size[0], "baseHeight": setup.size[1],
            "outputWidth": setup.output[0], "outputHeight": setup.output[1]})

        collections = client.request("GetSceneCollectionList")
        if obs.COLLECTION not in collections.get("sceneCollections", []):
            client.request("CreateSceneCollection", {"sceneCollectionName": obs.COLLECTION})
        elif collections.get("currentSceneCollectionName") != obs.COLLECTION:
            client.request("SetCurrentSceneCollection",
                           {"sceneCollectionName": obs.COLLECTION})
        scene = client.request("GetCurrentProgramScene")
        scene_name = scene.get("currentProgramSceneName") or scene.get("sceneName")
        existing = {item["inputName"]: item.get("inputKind", "")
                    for item in client.request("GetInputList").get("inputs", [])}

        def ensure(name: str, kind: str, settings: dict) -> None:
            if existing.get(name) == kind:
                client.request("SetInputSettings", {"inputName": name,
                                                    "inputSettings": settings})
                return
            if name in existing:
                client.request("RemoveInput", {"inputName": name})
            client.request("CreateInput", {"sceneName": scene_name, "inputName": name,
                                           "inputKind": kind, "inputSettings": settings,
                                           "sceneItemEnabled": True})

        ensure(obs.DISPLAY_INPUT, "monitor_capture", {"capture_cursor": setup.cursor})
        items = client.request("GetInputPropertiesListPropertyItems", {
            "inputName": obs.DISPLAY_INPUT, "propertyName": "monitor_id"})
        wanted = next((m for m in obs.monitor_rects() if m.name == setup.monitor), None)
        monitor_id = obs.pick_monitor(items.get("propertyItems", []), wanted, setup.size)
        log.info("Recording monitor %s (%s)", setup.monitor, monitor_id or "OBS's pick")
        if monitor_id:
            client.request("SetInputSettings", {"inputName": obs.DISPLAY_INPUT,
                                                "inputSettings": {"monitor_id": monitor_id}})
        # Fill the canvas with the monitor, whatever size it was last time.
        item = client.request("GetSceneItemId", {"sceneName": scene_name,
                                                 "sourceName": obs.DISPLAY_INPUT})
        client.request("SetSceneItemTransform", {
            "sceneName": scene_name, "sceneItemId": item.get("sceneItemId"),
            "sceneItemTransform": {"positionX": 0, "positionY": 0, "rotation": 0,
                                   "alignment": 5, "boundsType": "OBS_BOUNDS_SCALE_INNER",
                                   "boundsAlignment": 0, "boundsWidth": setup.size[0],
                                   "boundsHeight": setup.size[1]}})

        for audio in setup.inputs:
            ensure(audio.name, audio.kind, {"device_id": audio.device})
            client.request("SetInputAudioTracks", {
                "inputName": audio.name,
                "inputAudioTracks": {str(n): n == audio.track
                                     for n in range(1, obs.MAX_TRACKS + 1)}})
            client.request("SetInputMute", {"inputName": audio.name, "inputMuted": False})
            client.request("SetInputVolume", {"inputName": audio.name,
                                              "inputVolumeMul": audio.volume / 100})
        wanted_names = {obs.DISPLAY_INPUT, *(audio.name for audio in setup.inputs)}
        for name in sorted(OWN_INPUTS & set(existing) - wanted_names):
            client.request("RemoveInput", {"inputName": name})
        # OBS's own Desktop Audio and Mic/Aux would mix into every track.
        silent = {str(n): False for n in range(1, obs.MAX_TRACKS + 1)}
        for name in client.request("GetSpecialInputs").values():
            if name and name not in wanted_names:
                client.request("SetInputAudioTracks", {"inputName": name,
                                                       "inputAudioTracks": silent})

    @staticmethod
    def _wait_output(client: Client, active: bool, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if bool(client.request("GetReplayBufferStatus").get("outputActive")) == active:
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)

    # --- What OBS tells us ------------------------------------------------------

    def _on_event(self, kind: str, data: dict) -> None:
        if kind == "ReplayBufferSaved":
            raw = paths.normalize(data.get("savedReplayPath", ""))
            seconds = self._saves.popleft() if self._saves else None
            if raw:
                threading.Thread(target=self._finish, args=(raw, seconds), daemon=True,
                                 name="obs-finish").start()
        elif kind == "ReplayBufferStateChanged":
            if not data.get("outputActive") and data.get("outputState") == \
                    "OBS_WEBSOCKET_OUTPUT_STOPPED" and self.state == State.RUNNING \
                    and not self._stopping:
                self._fail("OBS stopped the replay buffer.")
        elif kind == "ExitStarted" and not self._stopping:
            self._fail("OBS was closed.")

    def _on_close(self, reason: str) -> None:
        if not self._stopping and self.running:
            self._fail(f"Lost the connection to OBS: {reason}")

    def _finish(self, raw: str, seconds: int | None) -> None:
        setup = self.plan
        titles = setup.titles if setup is not None else {}
        try:
            path = finish(raw, self.clip_dir, seconds, titles)
        except OSError as exc:
            log.error("Couldn't move OBS's save %s into the clips folder: %s", raw, exc)
            return
        if self.on_saved is not None:
            self.on_saved(path)

    def _fail(self, error: str) -> None:
        with self._lock:
            client, self._client = self._client, None
            if self.state == State.FAILED:
                return
        if client is not None:
            client.close()
        log.error("OBS: %s", error)
        self._set(State.FAILED, error)

    def _set(self, state: State, error: str = "") -> None:
        self.state = state
        if error:
            self.error = error
        if self.on_state is not None:
            self.on_state(state, error)
