"""Core logic for Vertex: config loading and clip scanning.

This module has no GUI dependencies so it can be used and tested on its own.
"""

import datetime
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

try:
    from send2trash import send2trash
except ImportError:  # optional — without it, deletes are permanent
    send2trash = None


APP_NAME = "Vertex"
APP_ID = "vertex"      # desktop entry and icon name
APP_SLUG = "vertex"    # XDG directory name

CONFIG_DIR = os.path.expanduser(f"~/.config/{APP_SLUG}")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# Fallbacks used when a path is left blank in config.json (XDG-aligned).
DEFAULT_DATA_DIR = os.path.expanduser(f"~/.local/share/{APP_SLUG}")
DEFAULT_STATE_DIR = os.path.expanduser(f"~/.local/state/{APP_SLUG}")
DEFAULT_CACHE_DIR = os.path.expanduser(f"~/.cache/{APP_SLUG}")

# Subfolder of the user's videos dir that clips are scanned from by default.
CLIP_SUBDIR = "Game Recordings"

# Settings first-run setup has to produce before the app can start.
REQUIRED_FIELDS = ("clip_path", "export_path", "data_path", "state_path",
                   "cache_path")

# Bundled artwork, resolved from this file — Assets/ sits beside src/, not in
# it — so it works whatever the cwd is.
# The logo ships in two inks: "light" artwork for dark backgrounds — what the
# app's own chrome wants — and "dark" artwork for light ones. Which is used is
# the user's to pick (Config.logo_variant), because the desktop it sits on is
# not something the app can see.
#
# The PNGs are rendered from the .svg beside them: Pillow, which the installer
# scales the icon with, cannot read SVG, and the SVGs are the only place the
# artwork is authoritative.
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Assets")
LOGO_DIR = os.path.join(ASSETS_DIR, "logo")

LOGO_VARIANTS = ("light", "dark")
DEFAULT_LOGO_VARIANT = "light"      # the app's chrome is dark


def logo_variant(name):
    """`name` if it is a variant we ship, else the default. Never raises."""
    return name if name in LOGO_VARIANTS else DEFAULT_LOGO_VARIANT


def mark_path(variant=DEFAULT_LOGO_VARIANT):
    """The square mark: desktop icon, titlebar, the first-run screen."""
    variant = logo_variant(variant)
    return os.path.join(LOGO_DIR, variant, f"vertex-mark-{variant}.png")


def wordmark_path(variant=DEFAULT_LOGO_VARIANT):
    """The horizontal lockup the rail heads with."""
    variant = logo_variant(variant)
    return os.path.join(LOGO_DIR, variant, f"vertex-horizontal-{variant}.png")


def format_size(size_bytes, decimals=2):
    """Turn a byte count into a human-readable string, e.g. '1.50 GB'."""
    if size_bytes == 0:
        return "0 Bytes"

    power = 1024
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB"]
    i = math.floor(math.log(size_bytes, power))
    return f"{size_bytes / (power ** i):.{decimals}f} {units[i]}"


def format_duration(seconds):
    """Seconds → 'M:SS' (or 'H:MM:SS' for long clips). e.g. 60 → '1:00'."""
    seconds = int(round(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def clean_tag(text):
    """Tidy a typed tag: collapse runs of whitespace, trim the ends.

    Casing is left alone — the user's own spelling of a name or a game title is
    what gets stored and suggested back to them later.
    """
    return " ".join(str(text).split())


def clean_tags(tags):
    """Clean a list of tags, dropping blanks and case-insensitive duplicates.

    The first spelling of a tag wins, so 'Anna' typed before 'anna' keeps the
    capital in both places.
    """
    seen = set()
    cleaned = []
    for tag in tags:
        tag = clean_tag(tag)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            cleaned.append(tag)
    return cleaned


# SteelSeries Moments names a recording "<Game>__<date>__<time>.mp4", writing
# the spaces in a game's name as dashes. The date and time are matched strictly
# so that another recorder's naming can never be read as a game: GPU Screen
# Recorder's "Replay_2026-03-28_05-28-25.mp4" has to fall through untagged.
# A trim keeps the name and adds a suffix — "_trim" from SteelSeries Moments
# itself, " (trimmed)" from this app — and is still a clip of the same game.
MOMENTS_FILENAME = re.compile(
    r"^(?P<game>.+?)__\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}"
    r"(?:_\w+|[ ]\(trimmed(?:[ ]\d+)?\))?$"
)

# What a capture that isn't a game gets tagged as.
DESKTOP_TAG = "Desktop"

# Recorder names for a capture that is not a game.
CAPTURE_NAMES = {"desktopcapture": DESKTOP_TAG}

# GPU Screen Recorder names every recording "Replay_<date>_<time>.mp4" no matter
# what was on screen, so the name itself carries no game. On this setup it is
# the desktop recorder, SteelSeries Moments handling the games, so that is what
# its clips are tagged as. Change this if it starts recording games too — the
# tag it writes is the one that stops a clip being offered for tagging again.
GSR_FILENAME = re.compile(r"^replay[_-]", re.IGNORECASE)

# Recorders take the game's registered title, symbols and all ("Overwatch®"),
# which nobody types when tagging by hand.
TRADEMARKS = str.maketrans("", "", "®™©")


def game_from_filename(name):
    """The game a clip's file name says it holds, or "" if the name doesn't say.

    Both recorders in use here are read: SteelSeries Moments puts the game in
    the name ("THE-FINALS__2024-06-16__19-45-23.mp4" → "THE FINALS"), and GPU
    Screen Recorder's fixed "Replay_…" naming means a desktop capture.

    Anything else returns "" rather than a guess — a name that matches neither
    recorder says nothing dependable, and a wrong tag is worse than no tag.
    """
    stem = os.path.splitext(name)[0]
    if GSR_FILENAME.match(stem):
        return DESKTOP_TAG
    match = MOMENTS_FILENAME.match(stem)
    if not match:
        return ""
    game = match.group("game")
    special = CAPTURE_NAMES.get(game.casefold())
    if special:
        return special
    return clean_tag(game.replace("-", " ").translate(TRADEMARKS))


# Both recorders stamp the name with when they started recording, differing
# only in how many underscores separate the date from the time:
# "Replay_2026-03-28_05-28-25" and "THE-FINALS__2024-06-16__19-45-23".
CLIP_TIMESTAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})_{1,2}(\d{2})-(\d{2})-(\d{2})"
)


def recorded_at(name):
    """When a clip's file name says it was recorded, or 0.0 if it doesn't say.

    Read as local time, which is the clock the recorder wrote it by. The parts
    are handed to `datetime` rather than only shape-checked, so an impossible
    date can't come back as a real timestamp.
    """
    match = CLIP_TIMESTAMP.search(os.path.splitext(name)[0])
    if not match:
        return 0.0
    try:
        return datetime.datetime(*(int(part) for part in match.groups())).timestamp()
    except ValueError:
        return 0.0   # matched the shape but names no real moment, e.g. month 13


def game_key(game):
    """Key on which two spellings of one game's name count as the same tag.

    Case and punctuation are dropped, so a recorder's "R.E.P.O." lands on a
    hand-typed "R.E.P.O" and "THE FINALS" on "The Finals", rather than each
    starting a near-duplicate tag next to the other. Words still have to match:
    "Overwatch 2" stays distinct from "Overwatch".
    """
    return re.sub(r"[^a-z0-9]+", "", game.casefold())


def normalize_path(path):
    """Expand '~', collapse '..'/'.', and drop any trailing slash. '' stays ''."""
    path = path.strip()
    if not path:
        return ""
    return os.path.normpath(os.path.expanduser(path))


# How long a clip is described by its age before it is described by its date.
# An age places a recent clip without anyone having to work out what the date
# was — but "412 days ago" is a number to decode, not a date, so past a month
# the date itself says more.
AGE_DAYS = 30


def format_date(timestamp):
    """A clip's date, written out: '20 Aug 2023'.

    Day before month, and the month spelled out, so it cannot be read the wrong
    way round on a desktop whose own date format is the other one.
    """
    return time.strftime("%d %b %Y", time.localtime(timestamp))


def relative_time(timestamp, now=None):
    """A timestamp as '6 days ago', or as its date once it is AGE_DAYS old."""
    now = time.time() if now is None else now
    seconds = max(0, now - timestamp)
    if seconds >= AGE_DAYS * 86400:
        return format_date(timestamp)

    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        count = int(seconds // size)
        if count >= 1:
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


# --- Machine-local defaults ------------------------------------------------
# Nothing here may be baked into the repo: the shipped config.json is a blank
# template, and every path the app starts with is derived from the account it
# is actually running under. The user's media folders also carry translated
# names on a non-English desktop ("Vidéos", "Videos", "Видео"), so they are
# asked for by role via xdg-user-dir rather than assumed to be named in English.

def xdg_user_dir(name, fallback):
    """Absolute path of an XDG user folder, e.g. xdg_user_dir('VIDEOS', '~/Videos').

    Tries the xdg-user-dir helper, then the user-dirs.dirs file it reads, then
    the English fallback. `name` is the role (VIDEOS, PICTURES, ...), which is
    what makes this locale-independent.
    """
    try:
        out = subprocess.run(
            ["xdg-user-dir", name], capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if out and out != os.path.expanduser("~"):
            return normalize_path(out)
    except (OSError, subprocess.SubprocessError):
        pass  # helper not installed (it ships with xdg-user-dirs); read the file

    dirs_file = os.path.expanduser("~/.config/user-dirs.dirs")
    try:
        with open(dirs_file) as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key == f"XDG_{name}_DIR":
                    value = value.strip().strip('"')
                    # Entries are written as "$HOME/Videos".
                    value = value.replace("$HOME", os.path.expanduser("~"))
                    if value:
                        return normalize_path(value)
    except OSError:
        pass

    return normalize_path(fallback)


def default_config():
    """A Config with every path filled in for the account running right now."""
    videos = xdg_user_dir("VIDEOS", "~/Videos")
    clips = os.path.join(videos, CLIP_SUBDIR)
    return Config(
        clip_path=clips,
        data_path=DEFAULT_DATA_DIR,
        state_path=DEFAULT_STATE_DIR,
        export_path=os.path.join(clips, APP_NAME, "Exports"),
        cache_path=DEFAULT_CACHE_DIR,
    )


def audio_devices():
    """Names of the audio sources a recorder can capture from, or [] if unknown.

    PipeWire and PulseAudio both list real inputs (microphones) and the
    ".monitor" of every output under `pactl list short sources` — exactly the
    set a recorder can be pointed at, spelled the way it writes them into a
    clip's stream tags, which is what makes matching the two possible at all.
    """
    try:
        listing = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []   # no PulseAudio/PipeWire here; the user types a name instead

    names = []
    for line in listing.splitlines():
        columns = line.split("\t")
        if len(columns) > 1 and columns[1] and columns[1] not in names:
            names.append(columns[1])
    return sorted(names)


# XDG folder names this app has used before, newest first — it was Vertex
# Moments before the name was shortened, GrapheneSeries Moments before the
# rebrand, and spelled with a separate "graphene" and "series" before that. An
# install from any of those has its config, tags, favourites and trim points
# sitting under the name of its day.
LEGACY_SLUGS = ("vertex_moments", "grapheneseries_moments",
                "graphene_series_moments")


def adopt_legacy_config(path=CONFIG_PATH):
    """Carry a config written under an earlier app name over to `path`.

    Copied verbatim, pointing at the same folders it always did: the rename is
    a change of name, not a request to move anybody's library or exports. So an
    upgrade lands on the screen the user left off at rather than on first-run
    setup, and Settings still shows the paths they chose. Never overwrites a
    config already at `path`. Returns the path it adopted from, or "".
    """
    if os.path.exists(path):
        return ""
    for slug in LEGACY_SLUGS:
        source = os.path.expanduser(f"~/.config/{slug}/config.json")
        if source != path and os.path.exists(source):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copy2(source, path)
            except OSError:
                return ""
            return source
    return ""


def adopt_legacy_library(data_dir, db_name="library.db"):
    """Bring a library left under an earlier data-dir name into `data_dir`.

    Copies rather than moves, so the original stays put as a backup, and never
    overwrites a library that is already there. Returns the path it adopted
    from, or "" if there was nothing to adopt.
    """
    target = os.path.join(data_dir, db_name)
    if os.path.exists(target):
        return ""
    for slug in LEGACY_SLUGS:
        source = os.path.expanduser(f"~/.local/share/{slug}/{db_name}")
        if source != target and os.path.exists(source):
            try:
                os.makedirs(data_dir, exist_ok=True)
                shutil.copy2(source, target)
            except OSError:
                return ""
            return source
    return ""


# The folders a run cannot quietly do without. Everything else a config names
# is either output (exports) or derived state (thumbnails, window position),
# remade on demand — losing one of those costs a rebuild, not data.
CHECKED_DIRS = ("clip_path", "data_path")


def missing_dirs(config):
    """Folders the config names that are not on disk, as (key, path) pairs.

    Renamed, moved, or on a drive that is not mounted — from here they look the
    same, and none of them is the app's to guess at. Worth reporting rather than
    recreating, because an empty folder in place of either of these is
    indistinguishable from a fresh install: the clips simply are not listed, and
    a remade data folder means every tag, favourite and trim point looks lost
    while the real library sits safely under the old name.
    """
    found = {"clip_path": normalize_path(config.clip_path),
             "data_path": config.resolved_data_dir()}
    return [(key, found[key]) for key in CHECKED_DIRS
            if found[key] and not os.path.isdir(found[key])]


def needs_setup(path=CONFIG_PATH):
    """True when first-run setup has to run before the app is usable.

    That means no config file, an unreadable one, or one that predates a
    setting — a config written on another machine and synced here counts too,
    since its clip folder will not exist locally.
    """
    try:
        config = Config.load(path)
    except (OSError, ValueError):
        return True
    return not config.is_complete()


@dataclass
class Config:
    """Paths loaded from the user's config.json."""

    clip_path: str = ""
    data_path: str = ""
    state_path: str = ""
    export_path: str = ""
    cache_path: str = ""

    # Capture devices, so the editor can tell a clip's audio tracks apart by
    # what recorded them instead of guessing from their names. Optional: blank
    # means "fall back to guessing", which is what every older config does.
    game_device: str = ""
    chat_device: str = ""
    mic_device: str = ""

    # Which ink the logo is drawn in — see LOGO_VARIANTS. Blank means "never
    # chosen", which every config written before the setting existed says, and
    # which resolves to the default.
    logo_variant: str = DEFAULT_LOGO_VARIANT

    @classmethod
    def load(cls, path=CONFIG_PATH):
        """Read config.json and return a Config. Missing keys default to ''."""
        with open(path) as user_file:
            data = json.loads(user_file.read())
        return cls(
            clip_path=data.get("clip_path", ""),
            data_path=data.get("data_path", ""),
            state_path=data.get("state_path", ""),
            export_path=data.get("export_path", ""),
            cache_path=data.get("cache_path", ""),
            game_device=data.get("game_device", ""),
            chat_device=data.get("chat_device", ""),
            mic_device=data.get("mic_device", ""),
            logo_variant=logo_variant(data.get("logo_variant", "")),
        )

    def to_dict(self):
        return {
            "clip_path": self.clip_path,
            "data_path": self.data_path,
            "state_path": self.state_path,
            "export_path": self.export_path,
            "cache_path": self.cache_path,
            "game_device": self.game_device,
            "chat_device": self.chat_device,
            "mic_device": self.mic_device,
            "logo_variant": self.logo_variant,
        }

    def resolved_data_dir(self):
        """Absolute data dir (SQLite library), falling back to the XDG default."""
        return normalize_path(self.data_path) or DEFAULT_DATA_DIR

    def resolved_state_dir(self):
        """Absolute state dir (window/session info), falling back to the default."""
        return normalize_path(self.state_path) or DEFAULT_STATE_DIR

    def resolved_cache_dir(self):
        """Absolute cache dir (thumbnails), falling back to the XDG default."""
        return normalize_path(self.cache_path) or DEFAULT_CACHE_DIR

    def is_complete(self):
        """Every path set, and the clips folder reachable from this account.

        A blank field means a setting was added to the app after this config was
        written. A clips folder that neither exists nor sits under this account's
        home is a config carried over from another machine, so it is re-derived
        rather than leaving the app pointed at someone else's home directory.
        """
        if not all(normalize_path(getattr(self, key)) for key in REQUIRED_FIELDS):
            return False
        clips = normalize_path(self.clip_path)
        home = os.path.expanduser("~")
        return os.path.isdir(clips) or clips.startswith(home + os.sep)

    def ensure_dirs(self):
        """Create the folders this config names. Returns paths that could not be.

        The clips folder is included: it is normally the recorder's output dir,
        and creating it up front means the recorder can write straight into a
        folder the app is already watching.
        """
        failed = []
        for path in (normalize_path(self.clip_path), self.resolved_data_dir(),
                     self.resolved_state_dir(), self.resolved_cache_dir(),
                     normalize_path(self.export_path)):
            if not path:
                continue
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                failed.append(path)
        return failed

    def save(self, path=CONFIG_PATH):
        """Write the current paths back to config.json (pretty-printed)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as user_file:
            json.dump(self.to_dict(), user_file, indent=4)


@dataclass
class Clip:
    """A single clip file with its size in bytes and its dates on disk."""

    name: str
    size_bytes: int
    mtime: float = 0.0
    path: str = ""  # absolute path to the file; "" for demo/placeholder clips
    created: float = 0.0   # birth time where the filesystem has one, else mtime
    # When it was recorded: seeded from the name, then replaced by the library's
    # stored date once the clip has been indexed. 0.0 until either is known.
    recorded: float = 0.0

    def __post_init__(self):
        # Demo clips and older callers only set an mtime, so the creation date
        # falls back to it rather than sorting them as if they were from 1970.
        if not self.created:
            self.created = self.mtime

    @property
    def date(self):
        """The clip's date: when it was recorded, or failing that, its file's.

        The recording date is the better answer whenever there is one — copying
        a clip between folders, or trimming it in place, rewrites every date the
        filesystem keeps, but not the one written into its name and not the one
        the library stored the first time it saw the clip. The file's own date
        only stands in for a clip nothing has indexed yet.
        """
        return self.recorded or self.created

    @property
    def size_human(self):
        return format_size(self.size_bytes)

    @property
    def age_human(self):
        return relative_time(self.date)


@dataclass
class CopyPlan:
    """Which recordings an import would copy in, and what that would cost."""

    source: str = ""
    target: str = ""
    files: list = field(default_factory=list)     # (name, size_bytes)
    present: list = field(default_factory=list)   # already in the target
    total_bytes: int = 0
    free_bytes: int = 0

    @property
    def fits(self):
        """Whether the target volume has room, with a little left over."""
        return self.free_bytes >= self.total_bytes * 1.02

    @property
    def total_human(self):
        return format_size(self.total_bytes)

    @property
    def free_human(self):
        return format_size(self.free_bytes)


def plan_copy(source, target):
    """Work out which .mp4s would be copied from `source` into `target`.

    Only the folder itself is read, never its subfolders: a SteelSeries Moments
    library keeps thumbnails, shared clips and exports in folders of their own
    beside the recordings, and none of those are recordings.

    A name already present in the target is left alone rather than overwritten —
    re-running an import must not clobber a clip that has since been edited.
    """
    source, target = normalize_path(source), normalize_path(target)
    existing = {name for name in os.listdir(target)} if os.path.isdir(target) else set()

    plan = CopyPlan(source=source, target=target)
    for name in sorted(os.listdir(source)):
        if not name.lower().endswith(".mp4"):
            continue
        if name in existing:
            plan.present.append(name)
            continue
        try:
            size = os.path.getsize(os.path.join(source, name))
        except OSError:
            continue   # vanished between listing and sizing; nothing to copy
        plan.files.append((name, size))
        plan.total_bytes += size

    if os.path.isdir(target):
        plan.free_bytes = shutil.disk_usage(target).free
    return plan


COPY_CHUNK = 4 * 1024 * 1024      # read/write size for a single clip
COPY_REPORT_EVERY = 8 * 1024 * 1024   # how much must land before we report again


def _copy_file(source, target, on_bytes=None):
    """Copy one file in chunks, reporting bytes written as it goes.

    shutil.copy2 would do the same in one call, but silently: a single 500 MB
    clip is a long time for a progress bar to sit still, so the copy is run by
    hand and the caller hears about it while it happens. Metadata is copied
    afterwards, which is the other half of what copy2 does.
    """
    written = since_report = 0
    with open(source, "rb") as src, open(target, "wb") as dst:
        while True:
            chunk = src.read(COPY_CHUNK)
            if not chunk:
                break
            dst.write(chunk)
            written += len(chunk)
            since_report += len(chunk)
            if on_bytes is not None and since_report >= COPY_REPORT_EVERY:
                since_report = 0
                on_bytes(written)
    shutil.copystat(source, target)
    return written


def copy_clips(plan, on_progress=None, cancelled=None):
    """Carry out a CopyPlan. Returns (copied names, [(name, error)]).

    Each clip is written under a temporary name and only moved into place once
    it is whole, so an interrupted import can never leave a half-written file
    sitting in the library looking like a real recording. Timestamps are
    preserved, and the source is only ever read.

    `on_progress(index, name, done_bytes)` is called repeatedly while a clip is
    being written and once more as it lands, where `index` is the 1-based
    position of that clip in the plan and `done_bytes` counts everything
    written so far. `cancelled()` is checked before each file — both callbacks
    run on the calling thread.
    """
    copied, failed, done_bytes = [], [], 0
    for index, (name, size) in enumerate(plan.files, start=1):
        if cancelled is not None and cancelled():
            break
        source = os.path.join(plan.source, name)
        target = os.path.join(plan.target, name)
        partial = target + ".part"   # not a .mp4, so a scan mid-copy ignores it
        settled = done_bytes         # bytes from the clips already finished
        try:
            _copy_file(source, partial, on_bytes=(
                None if on_progress is None
                else lambda written: on_progress(index, name, settled + written)))
            os.replace(partial, target)
            copied.append(name)
            done_bytes = settled + size
        except OSError as err:
            failed.append((name, str(err)))
            done_bytes = settled      # a half-written clip is not progress
            try:
                os.remove(partial)
            except OSError:
                pass   # never existed, or is already gone
        if on_progress is not None:
            on_progress(index, name, done_bytes)
    return copied, failed


@dataclass
class ImportPlan:
    """What importing a folder would tag, worked out before anything is written.

    Held apart from the writing so the user can be shown the whole thing and
    change their mind: cancelling an import leaves nothing behind.
    """

    folder: str = ""
    games: dict = field(default_factory=dict)    # derived game -> [filenames]
    stored_as: dict = field(default_factory=dict)  # derived game -> tag to write
    strays: list = field(default_factory=list)   # names carrying no game
    already: list = field(default_factory=list)  # clips the library has tagged
    dates: dict = field(default_factory=dict)    # filename -> recorded timestamp

    @property
    def clip_count(self):
        return sum(len(names) for names in self.games.values()) + \
            len(self.strays) + len(self.already)

    @property
    def taggable(self):
        return sum(len(names) for names in self.games.values())


def plan_import(folder, known_games=(), tagged=()):
    """Work out what importing `folder` would do, touching nothing.

    `known_games` are the tags the library already uses, so a game landing on
    one keeps the spelling in use rather than starting a near-duplicate beside
    it; `tagged` are the clips that already carry a game and are left alone.
    """
    known = {game_key(game): game for game in known_games}
    tagged = set(tagged)

    plan = ImportPlan(folder=folder)
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".mp4"):
            continue
        when = recorded_at(name)
        if when:
            plan.dates[name] = when
        if name in tagged:
            plan.already.append(name)
            continue
        game = game_from_filename(name)
        if not game:
            plan.strays.append(name)
            continue
        plan.games.setdefault(game, []).append(name)

    plan.stored_as = {
        game: known.get(game_key(game), game) for game in plan.games
    }
    return plan


@dataclass
class ClipScan:
    """Result of scanning the clip directory."""

    clips: list = field(default_factory=list)
    clips_total_bytes: int = 0
    disk_total_bytes: int = 0

    @property
    def clips_total_human(self):
        return format_size(self.clips_total_bytes)

    @property
    def disk_total_human(self):
        return format_size(self.disk_total_bytes)


@dataclass
class StorageStats:
    """Disk usage for the filesystem holding the clips, plus the clips' share."""

    clips_bytes: int = 0
    disk_total: int = 0
    disk_used: int = 0
    disk_free: int = 0

    @property
    def other_used(self):
        """Bytes used by everything on the disk that isn't our clips."""
        return max(0, self.disk_used - self.clips_bytes)

    def fraction(self, value):
        return value / self.disk_total if self.disk_total else 0.0

    @property
    def clips_human(self):
        return format_size(self.clips_bytes)

    @property
    def disk_total_human(self):
        return format_size(self.disk_total)

    @property
    def disk_free_human(self):
        return format_size(self.disk_free)

    @property
    def other_used_human(self):
        return format_size(self.other_used)


def storage_stats(clip_path):
    """Total size of .mp4 clips in clip_path and disk usage of its filesystem.

    Falls back to the root filesystem when clip_path is unset or missing.
    """
    clips_bytes = 0
    disk_target = "/"
    if clip_path and os.path.isdir(clip_path):
        disk_target = clip_path
        for name in os.listdir(clip_path):
            if name.endswith(".mp4"):
                try:
                    clips_bytes += os.path.getsize(os.path.join(clip_path, name))
                except OSError:
                    pass

    usage = shutil.disk_usage(disk_target)
    return StorageStats(
        clips_bytes=clips_bytes,
        disk_total=usage.total,
        disk_used=usage.used,
        disk_free=usage.free,
    )


def delete_clip(path):
    """Delete a clip file, preferring the desktop Trash so it stays recoverable.

    Returns True if it went to the Trash, or False if it had to be removed
    permanently — send2trash isn't installed, or the file lives on a volume with
    no usable trash dir (some removable and network mounts). Raises OSError if
    the file could not be removed at all.
    """
    if send2trash is not None:
        try:
            send2trash(path)
            return True
        except OSError:
            pass  # no trash available here; fall through to a real delete
    os.remove(path)
    return False


def creation_time(stat_result):
    """Best creation date a file can offer, falling back to its mtime.

    st_birthtime only exists on the platforms Python exposes it for (macOS and
    the BSDs — os.stat does not report it on Linux even where the filesystem
    keeps one), so the last-modified time stands in everywhere else. For a
    recording that is written once and never edited in place the two are the
    same date, which is why the sort is labelled by the date, not the source.
    """
    birth = getattr(stat_result, "st_birthtime", 0) or 0
    return birth or stat_result.st_mtime


def sort_clips(clips, key="date", descending=True, games=None):
    """Return `clips` ordered by recording date ("date") or game ("game").

    Descending means newest first by date, and Z→A by game. File name is the
    tie-break throughout, so a burst of recordings saved in the same second —
    or the whole of one game's clips — keeps a steady order in the grid instead
    of shuffling on every rescan.

    `games` is {filename: game} from the library, since a Clip carries no tags
    of its own. Untagged clips sort together at the end either way: they are the
    ones you still have to label, not the ones to bury in the middle.
    """
    ordered = sorted(clips, key=lambda clip: clip.name.casefold())
    if key == "date":
        ordered.sort(key=lambda clip: clip.date, reverse=descending)
    elif key == "game":
        lookup = games or {}
        # Two passes, because the untagged flag must not invert with the game
        # name: flipping the arrow reverses the games you have without dragging
        # the unlabelled pile to the top. Python's sort is stable, so file-name
        # order survives underneath both.
        ordered.sort(key=lambda clip: (lookup.get(clip.name) or "").casefold(),
                     reverse=descending)
        ordered.sort(key=lambda clip: not lookup.get(clip.name))
    elif descending:
        ordered.reverse()
    return ordered


def filter_clips(clips, query, tags=None, titles=None):
    """Return the clips matching `query` across game, people, title and name.

    Blank query means everything. Matching is case-insensitive and by substring,
    with every whitespace-separated word having to match somewhere — "finals
    anna" finds the Finals clips Anna is tagged in, in either typing order.

    File names are searched too, so a clip nobody has tagged yet is still
    findable by whatever the recorder called it.
    """
    words = query.casefold().split()
    if not words:
        return list(clips)

    tags = tags or {}
    titles = titles or {}
    matched = []
    for clip in clips:
        game, people = tags.get(clip.name, ("", []))
        haystack = " ".join(
            [clip.name, titles.get(clip.name, ""), game, *people]).casefold()
        if all(word in haystack for word in words):
            matched.append(clip)
    return matched


def scan_clips(clip_path, disk_root=None):
    """Scan clip_path for .mp4 files and report their sizes plus disk capacity.

    Capacity is measured on the filesystem holding the clips, not on the root
    one: a clips folder on a second drive or an external disk would otherwise
    be reported against a disk it has nothing to do with. `disk_root` overrides
    that for callers that mean a specific filesystem.
    """
    clips = []
    total = 0
    for name in os.listdir(clip_path):
        if name.endswith(".mp4"):
            full = os.path.join(clip_path, name)
            info = os.stat(full)
            clips.append(Clip(name=name, size_bytes=info.st_size,
                              mtime=info.st_mtime, path=full,
                              created=creation_time(info),
                              recorded=recorded_at(name)))
            total += info.st_size

    # Newest first, matching the default sort in the UI.
    clips = sort_clips(clips)

    return ClipScan(
        clips=clips,
        clips_total_bytes=total,
        disk_total_bytes=shutil.disk_usage(disk_root or clip_path).total,
    )
