# Notes for Claude

Vertex re-implements SteelSeries Moments (clips library, editor, export) for
Linux and Windows, and SteelSeries Sonar (virtual Game/Chat/Media outputs and
a Vertex Mic) on Linux only. One package serves both: GPU Screen Recorder
records on Linux, OBS Studio on Windows. Read `docs/DEVELOPMENT.md` before
changing code.

## The work list

`TODO.md` is the to-do list, and it is the copy that lasts between sessions.
At the start of a session, put its open items into the task panel, and keep
both in step: when an item changes or is finished, update `TODO.md` as well
and push it. Code, tests and docs don't mention TODO items.

## How the maintainer likes to work

- One item at a time, top to bottom unless they say otherwise. Say which
  item is next, and ask about anything unclear before building it.
- No hardcoded special cases or exclusions to work around something specific
  to one system. Raise it with the maintainer instead.
- Keep the human-written intro and the "Thanks" paragraph in `README.md` word
  for word.
- Don't open pull requests unless asked.
- The documentation is the README (for users) and `docs/DEVELOPMENT.md`,
  nothing else. The maintainer wants it brief: cover everything
  Vertex offers without much detail. Keep it in step when a change alters
  what a user sees. The install steps keep the "written by AI, not
  verified" warning. Retake the screenshots with
  `xvfb-run -a python tools/docs_screenshots.py docs/screenshots`.
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
- What differs between Linux and Windows lives in `vertex/platform/`
  (`linux.py`, `windows.py`, the same names in each, listed in `NAMES`);
  nothing else checks which system it runs on, and a test fails if it does.
  Sonar exists where `platform.SONAR` says; in the UI, `context.sonar` is
  None without it. Hotkeys are Windows-only.
- Blocking work (pactl, ffmpeg, the recorder, disk) goes through `ui/workers.run`, never on
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
- No Windows there: `tests/test_windows.py` switches the Windows branches on
  (`platform.WINDOWS`, `ipc.USE_TCP`), and CI's Windows job runs it for real.
  A test of the app without Sonar asks for the `no_sonar` fixture.
- No OBS there either: `tests/fake_obs.py` stands in for obs-websocket.
  What Vertex sets up in OBS is only proven on Windows, so ask the maintainer
  to have recording changes tried there.
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

## The design

The look the maintainer chose: nine colour schemes, Navy the default, two of them light (Polar,
Glacier), all at AA contrast. New UI follows these rules: every text colour at AA
contrast, the accent never on an audio control, red only for recording, no
dead space, nothing that only works on a dark ground (white handles, white
text outside the video). A grey palette was tried and rejected. The colours
live in `ui/theme.py`; use the tokens there, never a new hex value in a
widget. A colour set when a widget is built goes through `theme.style` or
`theme.themed` (icons take a token name), or it stays in the old scheme when
the maintainer picks another. Text on the accent sits on `ACCENT_FILL` in
`ON_ACCENT`; what is drawn over video uses `ON_VIDEO`; a slider handle takes
`theme.handle()`, the logo `theme.logo_ink()`. `theme.LIGHT` says whether
the scheme in use is a light one.

## Reference screenshots

The maintainer takes screenshots of SteelSeries GG (Moments and Sonar) on
Windows as references. Use them to understand the intended
layout and behaviour, but never commit them: they show SteelSeries' own UI,
and this repository is public. Vertex should be inspired by them, not copy
them.

## The maintainer's installation

They run one installation, installed with pipx from `main` as the README
describes (`~/vertex-test` and 1.x are gone). `main` is the only branch:
a session works on its own branch, and the maintainer tries it
with the command below, adding `@<branch>` at the end of the URL. When they
say it's good, it goes onto `main` and the session's branch is deleted.
It works in fish:

```bash
pipx install --force "git+https://github.com/StellarGalaxyAtlas/vertex.git"
```

A running Vertex keeps the old code until it is quit from the tray and opened
again: say so.
