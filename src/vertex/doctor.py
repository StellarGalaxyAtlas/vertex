"""`vertex doctor`: check everything Vertex depends on, and say how to fix it."""

from __future__ import annotations

import ctypes.util
import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from vertex import config as config_mod
from vertex import paths, platform
from vertex.recorder import backend, gsr, notifier, obs, presets


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    required: bool = True


def _hint(what: str) -> str:
    return platform.install_hint(what)


def _find_libmpv() -> str | None:
    """Where libmpv is, by the names python-mpv itself looks for."""
    for name in platform.LIBMPV_NAMES:
        found = ctypes.util.find_library(name)
        if found:
            return found
    return None


def _obs_checks(config: config_mod.Config) -> list[Check]:
    found = obs.detect(config.recorder.command)
    detail = found.version_text or ("found" if found.available else "not installed")
    fix = found.error if found.available else _hint("obs") + " — or set where it is in Settings"
    checks = [Check(obs.NAME, found.available and not found.too_old, detail, fix,
                    required=False)]
    if found.available:
        websocket = obs.websocket_settings()
        checks.append(Check(
            "OBS WebSocket server", websocket.enabled or not obs.running(),
            f"port {websocket.port}" if websocket.enabled else "off",
            "close OBS and Vertex switches it on when it starts the replay buffer",
            required=False))
        problems = obs.validate(presets.resolve(config.recorder, []))
        checks.append(Check("recorder settings", not problems, "; ".join(problems) or "valid",
                            "fix them in Settings → Recording", required=False))
    return checks


def _gsr_checks(config: config_mod.Config) -> list[Check]:
    checks: list[Check] = []
    found = gsr.detect(config.recorder.command)
    if not found.available:
        detail, fix = "not installed", _hint("gsr") + " — or set its command in Settings"
    else:
        detail, fix = found.version_text, found.error
        if not found.supports_track_names:
            detail += " (tracks are titled by device; 5.15+ titles them by channel)"
    checks.append(Check("GPU Screen Recorder", found.available and not found.too_old,
                        detail, fix, required=False))

    if found.available:
        # As the recorder passes them: a bitrate left to the quality level is
        # worked out first (the monitor's size only changes how high).
        problems = gsr.validate(presets.resolve(config.recorder, []))
        checks.append(Check("recorder settings", not problems, "; ".join(problems) or "valid",
                            "fix them in Settings → Recording", required=False))

    found_notifier = notifier.find()
    checks.append(Check("GPU Screen Recorder notifier", bool(found_notifier),
                        found_notifier or "not found",
                        _hint("gsr-notify") + " — to show notifications over games",
                        required=False))
    return checks


def _folder_check(name: str, folder: str) -> Check:
    """Where a folder Vertex keeps things in is, and whether it is really
    there: Windows can keep an app's AppData folders somewhere else, where
    the programs Vertex starts (ffmpeg, OBS) don't look."""
    if not os.path.isdir(folder):
        return Check(name, False, f"{paths.tilde(folder)} (not there yet)",
                     "run Vertex once to create it", required=False)
    real = os.path.realpath(folder)
    if os.path.normcase(real) != os.path.normcase(os.path.abspath(folder)):
        return Check(name, False, f"{paths.tilde(folder)}, kept in {paths.tilde(real)}",
                     "ffmpeg and OBS may not find it there", required=False)
    return Check(name, True, paths.tilde(folder), required=False)


def run_checks(config: config_mod.Config | None = None) -> list[Check]:
    config = config or config_mod.Config.load_or_default()
    checks: list[Check] = []

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        checks.append(Check(tool, bool(found), found or "not found", _hint("ffmpeg")))

    lib = _find_libmpv()
    checks.append(Check("libmpv", bool(lib), lib or "not found", _hint("libmpv")))

    for module, label in (("PySide6", "PySide6"), ("mpv", "python-mpv"),
                          ("send2trash", "Send2Trash")):
        found = importlib.util.find_spec(module) is not None
        checks.append(Check(label, found, "installed" if found else "missing",
                            f"pip install {label}", required=module != "send2trash"))

    checks += _obs_checks(config) if backend.is_obs() else _gsr_checks(config)

    checks.append(Check("config", not config_mod.needs_setup(),
                        paths.tilde(str(paths.config_path())),
                        "run Vertex once to go through setup", required=False))
    # A virtual environment's (pipx's) own python.exe says little: name the
    # Python it was made from too.
    python = sys.executable if sys.prefix == sys.base_prefix else \
        f"{sys.executable}, made from {sys.base_prefix}"
    checks.append(Check("python", True, python, required=False))
    for name, folder in (("library", config.resolved_data_dir()),
                         ("state", config.resolved_state_dir()),
                         ("cache", config.resolved_cache_dir())):
        checks.append(_folder_check(name, folder))
    if platform.FILE_OPENER is None:
        return checks
    opener, fix = platform.FILE_OPENER
    try:
        subprocess.run([opener, "--version"], capture_output=True, timeout=5)
        checks.append(Check(opener, True, "found", required=False))
    except (OSError, subprocess.SubprocessError):
        checks.append(Check(opener, False, "not found", fix, required=False))
    return checks


def report(checks: list[Check]) -> int:
    width = max(len(check.name) for check in checks)
    failed = 0
    for check in checks:
        mark = "✓" if check.ok else ("✗" if check.required else "!")
        print(f"  {mark} {check.name.ljust(width)}  {check.detail}")
        if not check.ok and check.fix:
            print(f"    {' ' * width}  → {check.fix}")
        if not check.ok and check.required:
            failed += 1
    print()
    print("Everything Vertex needs is here." if not failed else
          f"{failed} required item{'s' if failed != 1 else ''} missing.")
    return 1 if failed else 0
