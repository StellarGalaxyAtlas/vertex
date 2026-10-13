# Notes for Claude

Vertex re-implements SteelSeries Moments (clips library, editor, export) and
SteelSeries Sonar (virtual Game/Chat/Media/Aux outputs and a Vertex Mic) for
Linux. Read `docs/ARCHITECTURE.md` and `CONTRIBUTING.md` before changing code.

## The work list

`TODO.md` is the to-do list, and it is the copy that lasts between sessions.
At the start of a session, put its open items into the task panel with the
same numbering ("1 · Settings › Recording › Capture: …"), and keep both in step:
when an item changes or is finished, update `TODO.md` as well and push it.

The "Notes" section at the end of `TODO.md` records decisions already made and
open questions. Read it before starting an item.

## How the maintainer likes to work

- One TODO item at a time, top to bottom unless they say otherwise. Say which
  item is next, and ask about anything unclear before building it.
- No hardcoded special cases or exclusions to work around something specific
  to one system. Raise it with the maintainer instead.
- Keep the human-written intro and the "Thanks" paragraph in `README.md` word
  for word.
- Don't open pull requests unless asked.

## Rules of the code

- Everything outside `vertex.ui` stays free of Qt.
- Blocking work (pactl, ffmpeg, disk) goes through `ui/workers.run`, never on
  the UI thread.
- Never modify a user's recordings; write under a staging name and move into
  place.
- Before every push: `ruff check src tests` and `xvfb-run -a pytest` must both
  pass. Set up with `pip install -e ".[dev]"`.

## The maintainer's test install

They test from a separate copy in `~/vertex-test`, next to their 1.x install.
After each push, give them the update command:

```bash
cd ~/vertex-test/src && git pull && ~/vertex-test/venv/bin/pip install --no-cache-dir .
```
