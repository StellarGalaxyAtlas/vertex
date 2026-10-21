import os
import stat
import sys

from vertex import paths
from vertex.platform import kwin

FAKE = """#!{python}
import sys
args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(" ".join(args[3:]) + "\\n")
method = args[4]
if method.endswith("loadScript") and not method.endswith("unloadScript"):
    print("method return time=1 sender=:1.2", "   int32 7", sep="\\n")
elif method.endswith("Script.run") and args[3] != {run_path!r}:
    sys.exit(1)
"""


def _fake_dbus(tmp_path, monkeypatch, run_path="/Scripting/Script7"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    fake = bin_dir / "dbus-send"
    fake.write_text(FAKE.format(python=sys.executable, log=str(log), run_path=run_path))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    return log


def test_script_id():
    assert kwin.script_id("method return time=1\n   int32 3\n") == "3"
    assert kwin.script_id("") == ""


def test_activate_loads_runs_and_unloads_a_script(tmp_path, monkeypatch):
    log = _fake_dbus(tmp_path, monkeypatch)
    assert kwin.activate(4242)
    calls = log.read_text().splitlines()
    script = paths.runtime_dir() / "vertex-activate.js"
    assert calls == [
        "/Scripting org.kde.kwin.Scripting.unloadScript string:vertex-activate",
        f"/Scripting org.kde.kwin.Scripting.loadScript string:{script} "
        "string:vertex-activate",
        "/Scripting/Script7 org.kde.kwin.Script.run",
        "/Scripting org.kde.kwin.Scripting.unloadScript string:vertex-activate",
    ]
    assert not script.exists()


def test_activate_on_plasma_5(tmp_path, monkeypatch):
    log = _fake_dbus(tmp_path, monkeypatch, run_path="/7")
    assert kwin.activate(4242)
    assert "/7 org.kde.kwin.Script.run" in log.read_text()


def test_script_names_the_process():
    assert "const pid = 4242;" in kwin.SCRIPT.format(pid=4242)


def test_no_kwin(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))         # no dbus-send at all
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    assert not kwin.activate(4242)
