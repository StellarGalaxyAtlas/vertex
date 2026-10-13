# Contributing

Thanks for wanting to help. Bug reports, distro packaging notes and pull
requests are all welcome.

## Setting up

You need the system packages listed in the README (ffmpeg, libmpv, pactl), plus
Python 3.10+.

```bash
git clone https://github.com/StellarGalaxyAtlas/vertex.git && cd vertex
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
vertex doctor
vertex
```

## Tests and lint

```bash
ruff check src tests tools
pytest                                   # UI tests run offscreen
xvfb-run -a pytest                       # also runs the editor's OpenGL test
VERTEX_TEST_PIPEWIRE=1 pytest -m pipewire  # against your running audio server
```

The PipeWire tests create and remove `vertex_*` devices on the server you are
logged into and briefly change your default devices; they restore them, but
run them when nothing important is playing.

Tests never touch your real config or library: every test gets its own `HOME`
and `XDG_*` directories.

## Where things go

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). In short:

- Keep Qt out of everything but `vertex.ui`. If the UI needs new behaviour,
  put the logic in `core`, `media`, `audio` or `recorder`, test it there, and
  call it from a controller in `ui/services.py`.
- Never block the UI thread: use `ui/workers.run`.
- Never modify a user's recordings. New files are written under a hidden
  staging name (`core.clips.staging_path`) and moved into place when complete.
- Library schema changes are a new function appended to `MIGRATIONS` in
  `library/database.py`, with a test that opens an older database.
- Config additions need a default that keeps older config files loading.

## Style

- `ruff` is the formatter of record for imports and the linter for the rest.
- Comments explain *why*; the code says what.
- User-facing text is plain and specific: say what happened and what to do.

## Commits and pull requests

Small, focused commits with a message that explains the change. For UI changes,
a screenshot in the pull request helps reviewers a lot.
