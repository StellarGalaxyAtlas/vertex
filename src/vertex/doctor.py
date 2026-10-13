"""`vertex doctor`: check everything Vertex depends on, and say how to fix it."""

from __future__ import annotations

import ctypes.util
import importlib.util
import shutil
import subprocess
from dataclasses import dataclass

from vertex import config as config_mod
from vertex import paths
from vertex.audio.pulse import AudioError, Pactl
from vertex.recorder import gsr


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    required: bool = True


def _distro() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            text = handle.read().lower()
    except OSError:
        return ""
    for family, markers in (("arch", ("arch", "manjaro", "endeavouros", "cachyos")),
                            ("fedora", ("fedora", "nobara", "bazzite")),
                            ("debian", ("debian", "ubuntu", "mint", "pop"))):
        if any(f"id={m}" in text or f"id_like={m}" in text or f"id_like=\"{m}" in text
               for m in markers):
            return family
    return ""


PACKAGES = {
    "ffmpeg": {"arch": "ffmpeg", "fedora": "ffmpeg", "debian": "ffmpeg"},
    "libmpv": {"arch": "mpv", "fedora": "mpv-libs", "debian": "libmpv2"},
    "pactl": {"arch": "libpulse", "fedora": "pulseaudio-utils", "debian": "pulseaudio-utils"},
    "gsr": {"arch": "gpu-screen-recorder (AUR)", "fedora": "gpu-screen-recorder (COPR)",
            "debian": "gpu-screen-recorder (Flatpak: com.dec05eba.gpu_screen_recorder)"},
}


def _hint(what: str) -> str:
    family = _distro()
    package = PACKAGES[what].get(family)
    if package is None:
        return "install " + " / ".join(sorted(set(PACKAGES[what].values())))
    return f"install {package}"


def run_checks(config: config_mod.Config | None = None) -> list[Check]:
    config = config or config_mod.Config.load_or_default()
    checks: list[Check] = []

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        checks.append(Check(tool, bool(found), found or "not found", _hint("ffmpeg")))

    lib = ctypes.util.find_library("mpv")
    checks.append(Check("libmpv", bool(lib), lib or "not found", _hint("libmpv")))

    for module, label in (("PySide6", "PySide6"), ("mpv", "python-mpv"),
                          ("send2trash", "Send2Trash")):
        found = importlib.util.find_spec(module) is not None
        checks.append(Check(label, found, "installed" if found else "missing",
                            f"pip install {label}", required=module != "send2trash"))

    pactl = Pactl()
    try:
        info = pactl.info()
        server = str(info.get("server_name", "audio server"))
        checks.append(Check("audio server", True, server))
        checks.append(Check("PipeWire", "pipewire" in server.lower(),
                            server, "Sonar works best on PipeWire (pipewire-pulse)",
                            required=False))
    except AudioError as exc:
        checks.append(Check("audio server", False, str(exc), _hint("pactl")))

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
        problems = gsr.validate(config.recorder)
        checks.append(Check("recorder settings", not problems, "; ".join(problems) or "valid",
                            "fix them in Settings → Recording", required=False))

    checks.append(Check("config", not config_mod.needs_setup(),
                        paths.tilde(str(paths.config_path())),
                        "run Vertex once to go through setup", required=False))
    try:
        subprocess.run(["xdg-open", "--version"], capture_output=True, timeout=5)
        checks.append(Check("xdg-open", True, "found", required=False))
    except (OSError, subprocess.SubprocessError):
        checks.append(Check("xdg-open", False, "not found", "install xdg-utils",
                            required=False))
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
