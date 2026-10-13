# Notes for Claude

Vertex re-implements SteelSeries Moments (clips library, editor, export) and
SteelSeries Sonar (virtual Game/Chat/Media outputs and a Vertex Mic) for
Linux. Read `docs/ARCHITECTURE.md` and `CONTRIBUTING.md` before changing code.

## The work list

`TODO.md` is the to-do list, and it is the copy that lasts between sessions.
At the start of a session, put its open items into the task panel with the
same numbering ("1 · Settings › Recording › Capture: …"), and keep both in step:
when an item changes or is finished, update `TODO.md` as well and push it.

The "Notes" section at the end of `TODO.md` records decisions already made and
open questions. Read it before starting an item; its "Progress" paragraph says
where the work stands. New requests and bugs get the next free number in
`TODO.md`, even when they are done straight away.

## How the maintainer likes to work

- One TODO item at a time, top to bottom unless they say otherwise. Say which
  item is next, and ask about anything unclear before building it.
- No hardcoded special cases or exclusions to work around something specific
  to one system. Raise it with the maintainer instead.
- Keep the human-written intro and the "Thanks" paragraph in `README.md` word
  for word.
- Don't open pull requests unless asked.
- Don't touch the repo's documentation (README, `docs/`, the screenshots in
  it) until the maintainer says so (since 2026-10-13). `TODO.md` and this file
  are kept up to date; the Notes in `TODO.md` list what the docs have fallen
  behind on.
- No code for upgrades nobody went through: 2.0 isn't released and nobody
  upgraded from 1.x, so settings, data and devices from 1.x or earlier 2.0
  builds aren't carried over. Their library database (version 2) must keep
  opening, though.
- Their shell is fish: commands for them must work there (no heredocs or
  other bash-only syntax).
- Keep token use down: no multi-agent work (workflows, parallel reviewers,
  subagents) unless it is strictly necessary, even if a session setting
  suggests it. Tests, screenshots and your own review are the default.

## Rules of the code

- Everything outside `vertex.ui` stays free of Qt.
- Blocking work (pactl, ffmpeg, disk) goes through `ui/workers.run`, never on
  the UI thread.
- Never modify a user's recordings; write under a staging name and move into
  place.
- Before every push: `ruff check src tests tools` and
  `xvfb-run -a python -m pytest` must both pass. Set up with
  `pip install -e ".[dev]"`.

## Working in the cloud container

- No audio server runs there. Tests use the fake pactl in `tests/fake_pactl.py`;
  the PipeWire tests skip themselves.
- Run the tests through `python -m pytest`: the bare `pytest` on the PATH can
  be a separate tool that can't import Vertex. If `import vertex` fails in a
  new container, run `pip install -e ".[dev]"` again.
- For UI changes, look at the result before pushing:
  `xvfb-run -a python tools/sonar_screenshot.py /tmp/shot` screenshots the
  Sonar page against the fake server at the default and minimum window sizes.
  Read the PNGs, and send the maintainer the final one.
  `xvfb-run -a python tools/settings_screenshot.py /tmp/shot` does the same for
  Settings › Recording, with a fake recorder and three fake monitors (one
  standing up). `xvfb-run -a python tools/first_run_screenshot.py /tmp/shot`
  shoots every step of first-run setup, with and without a recorder.
- Workflow agents with `isolation: "worktree"` get a worktree made from the
  repository's default branch (`main`, an early 2.0 merged long before the
  work on this branch), not the working branch. Have them `git reset --hard`
  to the working branch's commit first.

## The design

`temp/design/` holds the look the maintainer chose (TODO items 24 and 25):
Vertex's navy and periwinkle at AA contrast, with a tightened layout. Read
its README before UI work. New UI follows its rules: every text colour at AA
contrast, the accent never on an audio control, red only for recording, no
dead space. A grey palette was tried and rejected. The colours live in
`ui/theme.py`; use the tokens there, never a new hex value in a widget.

## Reference screenshots

The maintainer takes screenshots of SteelSeries GG (Moments and Sonar) on
Windows as references for TODO items. Use them to understand the intended
layout and behaviour, but never commit them: they show SteelSeries' own UI,
and this repository is public. Vertex should be inspired by them, not copy
them.

## The maintainer's installation

They run one installation, installed with pipx from the working branch as
the README describes (`~/vertex-test` and 1.x are gone). After each push,
give them the update command with the branch you pushed to. It works in
fish:

```bash
pipx install --force "git+https://github.com/StellarGalaxyAtlas/vertex.git@claude/loving-curie-0t4h2o"
```

A running Vertex keeps the old code until it is quit from the tray and opened
again: say so. Once the work is merged into `main`, the `@…` part goes.
