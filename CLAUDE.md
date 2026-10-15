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
- The documentation (README, `docs/GUIDE.md`, `docs/CONTROL.md`,
  `docs/ARCHITECTURE.md`) was rewritten in item 21. Keep it short and in step
  when a change alters what a user sees; the install steps carry the
  maintainer's "written by AI, not verified" warning. Retake the screenshots
  with `xvfb-run -a python tools/docs_screenshots.py docs/screenshots`
  (a made-up demo library; then copy first-run.png from
  `tools/first_run_screenshot.py`'s moments step).
- No code for upgrades nobody went through: 2.0 isn't released and nobody
  upgraded from 1.x, so settings, data and devices from 1.x or earlier 2.0
  builds aren't carried over. Their library database (version 2) must keep
  opening, though.
- Their shell is fish: commands for them must work there (no heredocs or
  other bash-only syntax).
- Keep token use down: no multi-agent work (workflows, parallel reviewers,
  subagents) unless it is strictly necessary, even if a session setting
  suggests it. Tests, screenshots and your own review are the default.
- For a look (colours, a layout), show them choices side by side, as a
  mockup image or screenshots, and let them pick; then build the pick.
- They use a big screen (about 2560 px wide): check UI at the default size,
  the minimum (980 px) and big sizes, and leave no dead space at any of them.

## Rules of the code

- Everything outside `vertex.ui` stays free of Qt.
- Blocking work (pactl, ffmpeg, disk) goes through `ui/workers.run`, never on
  the UI thread.
- Never modify a user's recordings; write under a staging name and move into
  place.
- Before every push: `ruff check src tests tools` and
  `xvfb-run -a python -m pytest` must both pass. Set up with
  `pip install -e ".[dev]"`. Check pytest's exit status itself (write its
  output to a file, then look at `$?`): piped into `tail`, a failure looks
  like a pass, and one push went out red that way.

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
  The tools shoot Navy, the default. A colour change is checked in a dark
  and a light scheme: for another one, add `"colour_scheme": "polar"` to
  the config a tool writes (and don't commit that).
- Workflow agents with `isolation: "worktree"` get a worktree made from the
  repository's default branch (`main`, an early 2.0 merged long before the
  work on this branch), not the working branch. Have them `git reset --hard`
  to the working branch's commit first.

## The design

`temp/design/` holds the look the maintainer chose (TODO items 24, 25 and
27 to 34, 38 to 42): colour schemes, Plum the default, two of them light
(Polar, Glacier), all at AA contrast. Read its
README before UI work. New UI follows its rules: every text colour at AA
contrast, the accent never on an audio control, red only for recording, no
dead space, nothing that only works on a dark ground (white handles, white
text outside the video). A grey palette was tried and rejected. The colours
live in `ui/theme.py`; use the tokens there, never a new hex value in a
widget. A colour set when a widget is built goes through `theme.style` or
`theme.themed` (icons take a token name), or it stays in the old scheme when
the maintainer picks another. Text on the accent sits on `ACCENT_FILL` in
`ON_ACCENT`; what is drawn over video uses `ON_VIDEO`; a slider handle takes
`theme.handle()`, the logo `theme.logo_ink()`. `theme.LIGHT` says whether
the scheme in use is a light one. The decisions behind the schemes are in
the Notes of `TODO.md`.

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
