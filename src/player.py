"""Clip editor view: embedded mpv video, a per-track mixer, trim, and export.

mpv (libmpv) is used because, unlike most players, it can mix several audio
tracks at once via a lavfi-complex filter — GPU Screen Recorder clips carry a
separate audio stream per source. Each track passes through its own `volume`
node, and swapping the whole filter graph at runtime is instant and does not
disturb playback position, so that is how the mixer applies changes live.

`PlayerView` is a plain frame, not a window: the App swaps it in where the clip
grid was, so editing happens inside the main window.
"""

import os
import queue
import re
import threading
import time
import tkinter

import customtkinter as ctk
import mpv

import core
import export
import export_window
import widgets
import xguard
from theme import (
    ACCENT, ACCENT_HOVER, AUDIO_LANES, CONTENT_PAD_TOP, DANGER, GLOW_H,
    GLOW_PLATEAU, HEADER_H, LANE_BG, OK_GREEN, PAGE_GLOW, PANEL_BG,
    PLAYHEAD, PRIMARY_BUTTON, RADIUS_CONTROL, TEXT_MUTED, TRACK_LANES,
    TRIM_SHADE, VIDEO_BG, VIDEO_LANE, WAVE_MUTED, WAVE_SHADE, shade,
)

LANE_H = 34          # must match the mixer row height, or the lanes misalign
LANE_GAP = 4
RULER_H = 22
PANEL_W = 350        # mixer column; the timeline starts to the right of it
SLIDER_W = 150       # fixed, so every track's slider is the same length
PCT_W = 40
EDGE_PAD = 10
GRAB_PX = 7          # how close the pointer must be to grab a trim handle

SEEK_STEP = 5.0

WAVE_PAD = 3         # keeps the loudest peak off the lane's own edges
# Peaks are drawn on a curve rather than as raw amplitude. Speech recorded at a
# sane level peaks around a tenth of full scale, which is a pixel and a half in
# a lane this tall — indistinguishable from the silence the waveform is here to
# tell it apart from. The curve lifts the quiet end and leaves the loud end be.
WAVE_CURVE = 0.6


def mix_filter(tracks):
    """lavfi-complex summing every track at its current gain (None if no audio)."""
    if not tracks:
        return None
    nodes = "".join(
        f"[aid{t.index + 1}]volume={t.gain}[a{i}];" for i, t in enumerate(tracks)
    )
    if len(tracks) == 1:
        return f"[aid{tracks[0].index + 1}]volume={tracks[0].gain}[ao]"
    joined = "".join(f"[a{i}]" for i in range(len(tracks)))
    return f"{nodes}{joined}amix=inputs={len(tracks)}:normalize=0[ao]"


# The mixer shows these labels, in this order, regardless of how the streams
# happen to be ordered in the file. "Desktop Audio" sits where the game lane
# would, because that is what a mixed-down output track mostly carries.
TRACK_ORDER = ("Game Audio", "Desktop Audio", "Chat Audio", "Microphone")

# Which config setting names the device behind each lane.
DEVICE_SETTINGS = (
    ("Game Audio", "game_device"),
    ("Chat Audio", "chat_device"),
    ("Microphone", "mic_device"),
)

# Recorders name the field as well as the device — "device:Virtual_Game_Sink"
# (GPU Screen Recorder), "Devices: Monitor of Game Audio" (older builds).
DEVICE_PREFIX = re.compile(r"^devices?\s*:\s*", re.IGNORECASE)


def track_devices(name):
    """The capture devices a track's tag names, one entry per device.

    A recorder capturing two outputs into a single stream joins them with a
    pipe, so a track can legitimately name more than one device.
    """
    parts = (DEVICE_PREFIX.sub("", part).strip() for part in name.split("|"))
    return [part for part in parts if part]


def device_matches(configured, device):
    """Whether a configured device and a track's device are the same thing.

    Substring in either direction: the setting holds the node name as the
    system spells it today, while the clip holds whatever its recorder wrote at
    the time — a full node name, or a friendlier rendering of one.
    """
    configured, device = configured.casefold(), device.casefold()
    return configured in device or device in configured


def configured_source(device, config):
    """Which lane the user has configured `device` as, or None if they haven't."""
    for label, setting in DEVICE_SETTINGS:
        configured = (getattr(config, setting, "") or "").strip()
        if configured and device_matches(configured, device):
            return label
    return None


def guess_source(device):
    """Which lane a device name looks like it belongs to, or None.

    The fallback for clips recorded before the devices were configured, or on
    another machine: it can only go on how the device happens to be named.
    """
    lowered = device.lower()
    if "game" in lowered:
        return "Game Audio"
    if "chat" in lowered or "voice" in lowered:
        return "Chat Audio"
    if "mic" in lowered:
        return "Microphone"
    # A clip with no device tags falls back to "Audio 1" etc. in export.probe;
    # that says nothing about the source, so don't guess at it below.
    if re.fullmatch(r"audio \d+", lowered):
        return None
    # GPU Screen Recorder prefixes loopback sources with "Monitor of"; anything
    # else is a real capture device, i.e. the mic — whatever it is called.
    if "monitor of" not in lowered:
        return "Microphone"
    return None


def match_source(name, config=None):
    """Which mixer lane a track's device tag refers to, or None.

    The user's configured devices win over guessing at the name, since they
    name the hardware this machine actually records from.
    """
    devices = track_devices(name) or [name]
    if len(devices) > 1:
        # One stream fed by several devices, so no single source owns it.
        # Outputs mixed down are "Desktop Audio" — true whichever they are,
        # where "Game Audio" alone would be a lie. With the mic in the mix
        # there is no honest label, so the clip falls back to numbering.
        if any(_is_microphone(device, config) for device in devices):
            return None
        return "Desktop Audio"

    device = devices[0]
    if config is not None:
        matched = configured_source(device, config)
        if matched is not None:
            return matched
    return guess_source(device)


def _is_microphone(device, config):
    """Whether `device` is the mic, judged only on evidence worth trusting.

    guess_source treats any non-loopback device as the mic, which is a fair
    guess for a track of its own but not for one device among several — so a
    mixed track only counts the mic in when it was configured or named as one.
    """
    if config is not None and configured_source(device, config) == "Microphone":
        return True
    return "mic" in device.lower()


def lane_colour(track, position):
    """The colour of `track`'s lane — by name, or by position when it has none.

    A clip whose tracks could not be told apart is labelled "Audio 1", "Audio
    2"…, and position is then the only thing there is to go on.
    """
    return TRACK_LANES.get(track.label, AUDIO_LANES[position % len(AUDIO_LANES)])


def label_tracks(tracks, config=None):
    """Label every track and return them in the order the mixer shows.

    All or nothing: a half-recognised mixer ("Game Audio / Monitor of Desk… /
    Microphone") reads like a bug, so unless every track maps to a distinct
    known source they all get generic numbering in file order.
    """
    by_file = sorted(tracks, key=lambda track: track.index)
    matches = [match_source(track.name, config) for track in by_file]
    if None in matches or len(set(matches)) != len(matches):
        for position, track in enumerate(by_file, start=1):
            track.label = f"Audio {position}"
        return by_file
    for track, label in zip(by_file, matches):
        track.label = label
    return sorted(by_file, key=lambda track: TRACK_ORDER.index(track.label))


def lane_grid(frame):
    """Shared column layout so every mixer row lines its slider up identically."""
    frame.grid_propagate(False)
    frame.grid_columnconfigure(2, weight=1)   # the name column absorbs the slack
    frame.grid_rowconfigure(0, weight=1)


class TrackRow(ctk.CTkFrame):
    """One mixer row: name, mute toggle, volume slider, gain readout."""

    def __init__(self, master, track, colour, on_change):
        super().__init__(master, fg_color="transparent", height=LANE_H, width=PANEL_W)
        lane_grid(self)
        self.track = track
        self.on_change = on_change

        tkinter.Frame(self, bg=colour, width=3, highlightthickness=0).grid(
            row=0, column=0, sticky="ns", pady=3
        )
        self.mute_btn = ctk.CTkButton(
            self, text="🔊", width=28, height=24, fg_color="transparent",
            hover_color=LANE_BG, command=self.toggle_mute,
        )
        self.mute_btn.grid(row=0, column=1, padx=(6, 2))
        ctk.CTkLabel(
            self, text=track.label, anchor="w",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).grid(row=0, column=2, sticky="ew", padx=(2, 6))
        self.slider = ctk.CTkSlider(
            self, from_=0, to=1.5, width=SLIDER_W, height=14,
            command=self._on_volume, progress_color=colour, button_color=colour,
        )
        self.slider.set(track.volume)
        self.slider.grid(row=0, column=3)
        self.pct = ctk.CTkLabel(
            self, text="100%", width=PCT_W, anchor="e",
            font=ctk.CTkFont(size=10), text_color=TEXT_MUTED,
        )
        self.pct.grid(row=0, column=4, padx=(4, 0))
        self._refresh()

    def _refresh(self):
        muted = self.track.muted
        self.mute_btn.configure(text="🔇" if muted else "🔊")
        self.pct.configure(
            text="muted" if muted else f"{round(self.track.volume * 100)}%",
            text_color="#5a6070" if muted else TEXT_MUTED,
        )

    def toggle_mute(self):
        self.track.muted = not self.track.muted
        self._refresh()
        self.on_change()

    def _on_volume(self, value):
        self.track.volume = float(value)
        self.track.muted = False      # touching the slider un-mutes, as expected
        self._refresh()
        self.on_change()


class PlayerView(ctk.CTkFrame):
    """Full-window clip editor. `on_back` returns to whatever opened it."""

    def __init__(self, master, clip_path, title="Clip", on_back=None,
                 export_dir="", library=None, clip_name="", on_delete=None,
                 on_trimmed=None, config=None, recorded=0.0):
        super().__init__(master, fg_color=PANEL_BG)
        self.clip_path = clip_path
        self.clip_title = title
        # When it was recorded, as the library settled it. Passed in rather than
        # read off the file: the dates on disk are rewritten by copying a clip
        # between folders or trimming it in place, and this one is not.
        self.recorded = recorded
        self.on_back = on_back
        self.on_delete = on_delete
        self.on_trimmed = on_trimmed
        self.export_dir = export_dir
        self.library = library
        self.config_data = config   # names the capture devices, for the mixer
        self.clip_name = clip_name or os.path.basename(clip_path)

        self._player = None
        self._poll_job = None
        self._closing = False
        self._suppress_until = 0.0   # ignore poll updates right after a user seek
        self._position = 0.0
        self._drag = None            # 'in' | 'out' | 'seek' while dragging

        # Audio levels behind each lane, filled in by a background decode.
        self._waves = {}            # stream index -> peak levels, 0-1
        self._wave_points = {}      # stream index -> polygon, at _wave_width
        self._wave_width = 0
        self._wave_events = queue.Queue()
        self._wave_cancel = threading.Event()
        self._wave_thread = None
        self._wave_poll_job = None

        self._export_win = None     # the export window, while one is open
        # Clicks arrive on mpv's event thread; the poller replays them on Tk's.
        self._input_events = queue.Queue()
        # Trim runs on a worker thread and reports back the same way.
        self._trim_events = queue.Queue()
        self._trim_thread = None
        self._trim_poll_job = None
        self._trim_mode = None    # "copy" | "replace" while one is running
        self._trim_out = None     # the file it is writing, until handed over

        try:
            self.info = export.probe(clip_path)
        except export.ExportError:
            self.info = export.MediaInfo()
        # Display order only — each track keeps its own stream index, so the
        # mpv and ffmpeg mixes still address the right stream.
        self.tracks = label_tracks(self.info.tracks, self.config_data)
        self.duration = self.info.duration or 0.0
        self.trim_start = 0.0
        self.trim_end = self.duration
        self.game = ""        # "" means: the default game
        self.people = []
        # Restore before the widgets are built so sliders and the timeline come
        # up already showing the saved state.
        self._dirty = False
        self._save_job = None
        self._restore_edit()

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_video()
        self._build_transport()
        self._build_editor()

        self._bind_keys()

        # Create the player once the surface exists so winfo_id() is valid.
        self.after(60, self._start_player)
        self.after(80, self._update_estimate)
        # After the player: decoding the levels is work the clip does not need
        # anyone to wait for, and playback starting is what the user is waiting
        # for. The lanes fill in underneath it a moment later.
        self.after(120, self._start_waves)

    # --- Keyboard ----------------------------------------------------------

    def _bind_keys(self):
        """Space toggles playback, the arrows seek, Escape goes back.

        Bound on the toplevel so the shortcuts work wherever focus sits inside
        the editor, and released in `stop()` so the keys go dead again once the
        clip grid is back.
        """
        top = self.winfo_toplevel()
        self._key_bindings = [
            (seq, top.bind(seq, handler, add="+"))
            for seq, handler in (
                ("<space>", self._on_space),
                ("<Escape>", self._on_escape),
                ("<Left>", lambda e: self._on_arrow(-SEEK_STEP)),
                ("<Right>", lambda e: self._on_arrow(SEEK_STEP)),
            )
        ]

    def _unbind_keys(self):
        top = self.winfo_toplevel()
        for sequence, funcid in getattr(self, "_key_bindings", []):
            try:
                top.unbind(sequence, funcid)
            except tkinter.TclError:
                pass
        self._key_bindings = []

    def _typing(self):
        """True when focus is in a text field, where space means a space."""
        return isinstance(self.focus_get(), (tkinter.Entry, tkinter.Text))

    def _on_space(self, _event=None):
        if self._closing or not self.winfo_exists() or self._typing():
            return None
        self.toggle_play()
        return "break"      # don't let a focused widget also act on it

    def _on_arrow(self, delta):
        """Left/Right seek by SEEK_STEP, as they do in every other player."""
        if self._closing or not self.winfo_exists() or self._typing():
            return None
        self.nudge(delta)
        return "break"

    def _on_escape(self, _event=None):
        if self._closing or not self.winfo_exists():
            return None
        self.go_back()
        return "break"

    # --- Saved edit state --------------------------------------------------

    def _restore_edit(self):
        """Load this clip's title, tags, trim and mixer settings."""
        if self.library is None:
            return
        try:
            edit = self.library.get_edit(self.clip_name)
        except Exception:
            return

        if edit.title:
            self.clip_title = edit.title
        self.game = edit.game
        self.people = list(edit.people)

        if self.duration:
            if edit.trim_start is not None:
                self.trim_start = max(0.0, min(edit.trim_start, self.duration))
            if edit.trim_end is not None:
                self.trim_end = max(
                    self.trim_start + 0.1, min(edit.trim_end, self.duration)
                )
        for track in self.tracks:
            saved = (edit.volumes or {}).get(track.name)
            if saved is None:
                continue
            if isinstance(saved, dict):
                track.volume = float(saved.get("volume", 1.0))
                track.muted = bool(saved.get("muted", False))
            else:
                track.volume = float(saved)   # older rows stored a bare number

    def _save_edit(self):
        """Write trim and mixer settings back, leaving other columns intact."""
        if self.library is None or not self.duration:
            return
        try:
            edit = self.library.get_edit(self.clip_name)
            edit.trim_start = self.trim_start
            edit.trim_end = self.trim_end
            edit.volumes = {
                track.name: {
                    "volume": round(track.volume, 3),
                    "muted": bool(track.muted),
                }
                for track in self.tracks
            }
            self.library.save_edit(edit)
        except Exception:
            pass   # a read-only or missing DB must not break playback

    def _rename(self, text):
        """Commit a title typed into the header. The clip file is untouched, and
        exports keep deriving their filename from it."""
        # Typing the filename back means "no custom title".
        self.clip_title = text or self.clip_name
        if self.library is not None:
            try:
                self.library.set_title(
                    self.clip_name,
                    "" if self.clip_title == self.clip_name else self.clip_title,
                )
            except Exception:
                pass   # a read-only DB must not swallow the clip's editor
        return self.clip_title

    # --- Tags --------------------------------------------------------------

    def _tag_text(self):
        """The header's tag chip: '🏷 Game · Anna, Ben', or an invitation."""
        parts = [part for part in (self.game, ", ".join(self.people)) if part]
        return "🏷  " + ("  ·  ".join(parts) or "Add tags")

    def _edit_tags(self, _event=None):
        """Retag the open clip. Playback carries on behind the dialog."""
        try:
            games = self.library.known_games()
            people = self.library.known_people()
        except Exception:
            return   # an unreadable DB has nothing to suggest and nowhere to save
        tags = widgets.TagDialog.ask(
            self, clip=self.clip_title, game=self.game, people=self.people,
            games=games, people_pool=people,
        )
        if tags is None:
            return   # cancelled
        try:
            self.game, self.people = self.library.set_tags(self.clip_name, *tags)
        except Exception:
            return   # read-only DB; leave the header showing what is stored
        if self.tags_label.winfo_exists():
            self.tags_label.configure(text=self._tag_text())

    def _mark_dirty(self):
        """Note a user edit and schedule a save shortly after they stop moving."""
        self._dirty = True
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except (tkinter.TclError, ValueError):
                pass
        self._save_job = self.after(800, self._flush)

    def _flush(self):
        self._save_job = None
        if self._dirty:
            self._dirty = False
            self._save_edit()

    # --- Layout ------------------------------------------------------------

    def _build_header(self):
        # The editor takes the whole window, so it carries the page's lit band
        # like every other view — and its header row is what sits on the band's
        # plateau. Full width and PAGE_GLOW rather than inset and transparent:
        # an inset row would leave a strip of unlit page down either side of
        # the light, and a transparent one would paint MAIN_BG over it.
        widgets.attach_glow(self, top=PAGE_GLOW, bottom=PANEL_BG,
                            plateau=GLOW_PLATEAU, height=GLOW_H,
                            offset=CONTENT_PAD_TOP)
        header = ctk.CTkFrame(self, fg_color=PAGE_GLOW, corner_radius=0,
                              height=HEADER_H)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        ctk.CTkButton(
            header, text="←  Back", width=90, fg_color="transparent",
            hover_color=ACCENT, command=self.go_back,
        ).pack(side="left", padx=(12, 0))
        # Click the title to rename the clip. This is library metadata only —
        # the file on disk keeps its name, and exports still use the filename.
        self.title_field = widgets.EditableLabel(
            header, self.clip_title, self._rename, height=28, autofit=True,
            font=ctk.CTkFont(size=13), text_color=TEXT_MUTED,
        )
        self.title_field.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            header, text=meta_of(self.info, self.recorded), text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(0, 12))
        # Tags live next to the title: same kind of metadata, same place to
        # click. Without a library there is nowhere to store them.
        if self.library is not None:
            self.tags_label = ctk.CTkLabel(
                header, text=self._tag_text(), text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=12), cursor="hand2", corner_radius=6,
                fg_color=LANE_BG, padx=10, height=26,
            )
            self.tags_label.pack(side="left")
            self.tags_label.bind("<Button-1>", self._edit_tags)
        # The owner confirms and performs the delete, then sends us back — the
        # editor has no business knowing about the library or the clip grid.
        if self.on_delete is not None:
            ctk.CTkButton(
                header, text="Delete", width=90, fg_color="transparent",
                text_color=DANGER, hover_color=DANGER, command=self._delete,
            ).pack(side="right", padx=(0, 12))

    def _build_video(self):
        # Video surface: a bare Tk frame whose window id mpv renders into.
        self.video = tkinter.Frame(self, bg=VIDEO_BG, highlightthickness=0)
        self.video.grid(row=1, column=0, sticky="nsew", padx=12, pady=10)

    def _icon_button(self, bar, glyph, command, tip, padx=0):
        """One transport icon: a glyph, and a tooltip saying what it does."""
        button = ctk.CTkButton(
            bar, text=glyph, width=34, fg_color="transparent",
            corner_radius=RADIUS_CONTROL, hover_color=LANE_BG, command=command,
            font=ctk.CTkFont(size=15),
        )
        button.pack(side="left", padx=padx)
        widgets.Tooltip(button, tip)
        return button

    def _build_transport(self):
        """Play/pause with the trim markers either side of it.

        The markers sit here rather than over the mixer because setting one is a
        transport action: you play up to the moment you want and mark it, so the
        button belongs next to the one that got you there — and either side of
        play, they read the way they sit on the timeline. Seeking is the
        timeline's and the arrow keys' job, so no button does it.
        """
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=12)

        self._icon_button(bar, "⇤", self.set_in,
                          "Set In — start the selection here")
        self.play_btn = ctk.CTkButton(
            bar, text="⏸", width=44, corner_radius=RADIUS_CONTROL,
            command=self.toggle_play, **PRIMARY_BUTTON,
        )
        self.play_btn.pack(side="left", padx=4)
        self._icon_button(bar, "⇥", self.set_out,
                          "Set Out — end the selection here")
        self._icon_button(bar, "↺", self.reset_trim,
                          "Reset — select the whole clip", padx=(10, 0))

        self.time_label = ctk.CTkLabel(bar, text="0:00 / 0:00", width=110)
        self.time_label.pack(side="left", padx=12)

        self.export_btn = ctk.CTkButton(
            bar, text="Export", width=110, corner_radius=RADIUS_CONTROL,
            command=self.start_export, **PRIMARY_BUTTON,
        )
        self.export_btn.pack(side="right")
        self.trim_btn = ctk.CTkButton(
            bar, text="Trim", width=90, corner_radius=RADIUS_CONTROL,
            fg_color=LANE_BG, hover_color=ACCENT_HOVER, command=self.confirm_trim,
        )
        self.trim_btn.pack(side="right", padx=8)
        self.status_label = ctk.CTkLabel(
            bar, text="", text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
        )
        self.status_label.pack(side="right", padx=10)

    def _build_editor(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 12))
        wrap.grid_columnconfigure(1, weight=1)

        panel = ctk.CTkFrame(wrap, fg_color="transparent", width=PANEL_W)
        panel.grid(row=0, column=0, sticky="nw")
        panel.grid_propagate(False)

        # The trim buttons used to live here; they are in the transport now.
        # The row stays as a spacer, because it is what stands the mixer off by
        # the height of the timeline's ruler and so keeps every lane aligned
        # with the track beside it.
        ctk.CTkFrame(panel, fg_color="transparent", height=RULER_H).pack(fill="x")

        # Video row has no controls; it just keeps the lanes aligned.
        video_row = ctk.CTkFrame(panel, fg_color="transparent",
                                 height=LANE_H, width=PANEL_W)
        video_row.pack(fill="x", pady=(LANE_GAP, 0))
        lane_grid(video_row)
        tkinter.Frame(video_row, bg=VIDEO_LANE, width=3,
                      highlightthickness=0).grid(row=0, column=0, sticky="ns", pady=3)
        ctk.CTkLabel(
            video_row, text="Source clip", anchor="w",
            font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
        ).grid(row=0, column=2, sticky="ew", padx=(2, 6))

        self.rows = []
        for i, track in enumerate(self.tracks):
            row = TrackRow(panel, track, lane_colour(track, i),
                           self._on_mix_changed)
            row.pack(fill="x", pady=(LANE_GAP, 0))
            self.rows.append(row)

        lanes = 1 + len(self.tracks)
        height = RULER_H + lanes * (LANE_H + LANE_GAP)
        panel.configure(height=height)
        self.timeline = tkinter.Canvas(
            wrap, height=height, bg=PANEL_BG, highlightthickness=0, bd=0,
        )
        self.timeline.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.timeline.bind("<Configure>", lambda _e: self._draw_timeline())
        self.timeline.bind("<Button-1>", self._on_press)
        self.timeline.bind("<B1-Motion>", self._on_drag)
        self.timeline.bind("<ButtonRelease-1>", self._on_release)

    # --- Playback ----------------------------------------------------------

    def _start_player(self):
        if self._closing or not self.winfo_exists():
            return
        # mpv's X11 backend queries the window tree; if the surface isn't mapped
        # yet that's a fatal BadWindow. Wait until it's actually on-screen.
        if not self.video.winfo_viewable():
            self.after(50, self._start_player)
            return
        self.update_idletasks()
        try:
            self._player = mpv.MPV(
                wid=str(self.video.winfo_id()),
                # Tk is an X11 window (XWayland — Tk has no Wayland backend at
                # all). Force mpv onto the X11 GLX backend so it embeds into
                # `wid` instead of opening its own Wayland window. (x11egl
                # throws a fatal BadWindow when embedding; x11/GLX embeds
                # cleanly.)
                vo="gpu", gpu_context="x11",
                osc=False, input_default_bindings=False, input_vo_keyboard=False,
                keep_open="yes",  # hold the last frame instead of closing at EOF
            )
        except Exception:
            self.time_label.configure(text="No player")
            return

        # mpv owns the video surface, so Tk never sees clicks on it — ask mpv
        # for them instead. (Its builtin MBTN_LEFT is 'ignore'; MBTN_RIGHT is
        # already 'cycle pause'.)
        try:
            self._player.register_key_binding("MBTN_LEFT", self._on_video_click)
        except Exception:
            pass

        self._apply_mix()
        # A clip with a saved trim opens at its IN marker: the trimmed-off head
        # is not what the user wants to watch. mpv's `start` applies to the load
        # itself, so playback begins there rather than seeking after the fact.
        if self.trim_start > 0:
            try:
                self._player["start"] = self.trim_start
            except Exception:
                pass    # unsupported build; playback just starts at 0
            self._position = self.trim_start
            self._update_time_label()
            self._draw_playhead()
        self._player.play(self.clip_path)
        self._poll()

    def _on_video_click(self, state, *_args):
        """Runs on mpv's event thread: hand the click to the Tk thread."""
        if state.startswith("d"):     # press only; the release repeats the event
            self._input_events.put("toggle")

    def _on_mix_changed(self):
        """A mixer widget moved: apply it live and remember it."""
        self._apply_mix()
        self._draw_timeline()   # a muted track greys its lane out
        self._mark_dirty()

    def _apply_mix(self):
        """Push the current mixer settings into mpv's filter graph."""
        if self._player is None:
            return
        graph = mix_filter(self.tracks)
        if graph is None:
            return
        try:
            self._player["lavfi-complex"] = graph
        except Exception:
            pass

    def _poll(self):
        """Drive the timeline from the player's clock (avoids mpv-thread callbacks)."""
        player = self._player
        if player is None:
            return

        while True:                   # clicks queued from mpv's event thread
            try:
                self._input_events.get_nowait()
            except queue.Empty:
                break
            self.toggle_play()

        try:
            duration = player.duration
            position = player.time_pos
            paused = player.pause
        except Exception:
            duration = position = paused = None

        # Pause can also change behind our back — mpv binds right-click to
        # 'cycle pause' — so the button follows the player, not the other way.
        if paused is not None:
            icon = "▶" if paused else "⏸"
            if self.play_btn.cget("text") != icon:
                self.play_btn.configure(text=icon)

        if duration and not self.duration:
            self.duration = duration
            if self.trim_end <= 0:      # no saved trim to preserve
                self.trim_end = duration
            # ffprobe could not say how long the clip was; now that mpv can,
            # there is a timeline to lay the levels out along.
            self._start_waves()
        if position is not None and time.time() > self._suppress_until:
            self._position = position
            self._update_time_label()
            self._draw_playhead()
        self._poll_job = self.after(100, self._poll)

    def _update_time_label(self):
        self.time_label.configure(
            text=f"{core.format_duration(self._position)} / "
            f"{core.format_duration(self.duration)}"
        )

    def toggle_play(self):
        if self._player is None:
            return
        # Starting from outside the selection is almost never what's wanted.
        if self._player.pause and not (
            self.trim_start <= self._position <= self.trim_end
        ):
            self.seek_to(self.trim_start)
        self._player.pause = not self._player.pause
        self.play_btn.configure(text="▶" if self._player.pause else "⏸")

    def nudge(self, delta):
        self.seek_to(self._position + delta)

    def seek_to(self, seconds):
        if self._player is None or not self.duration:
            return
        seconds = max(0.0, min(self.duration, seconds))
        self._position = seconds
        self._suppress_until = time.time() + 0.3
        self._update_time_label()
        self._draw_playhead()
        try:
            self._player.command("seek", seconds, "absolute", "exact")
        except Exception:
            pass

    # --- Trim --------------------------------------------------------------

    def set_in(self):
        self.trim_start = min(self._position, self.trim_end - 0.1)
        self._draw_timeline()
        self._update_estimate()
        self._mark_dirty()

    def set_out(self):
        self.trim_end = max(self._position, self.trim_start + 0.1)
        self._draw_timeline()
        self._update_estimate()
        self._mark_dirty()

    def reset_trim(self):
        self.trim_start, self.trim_end = 0.0, self.duration
        self._draw_timeline()
        self._update_estimate()
        self._mark_dirty()

    @property
    def selection(self):
        return max(0.0, self.trim_end - self.trim_start)

    # --- Waveforms ---------------------------------------------------------

    def _start_waves(self):
        """Decode every track's levels off the Tk thread. Idempotent.

        A clip with a silent track looks exactly like one where the recorder
        missed a source, and the mixer cannot tell them apart — which is the
        whole reason the lanes carry a waveform.
        """
        if self._closing or self._wave_thread is not None:
            return
        if not self.tracks or not self.duration:
            return          # nothing to draw, or nothing to lay it out along
        self._wave_thread = threading.Thread(target=self._wave_worker, daemon=True)
        self._wave_thread.start()
        self._wave_poll_job = self.after(200, self._poll_waves)

    def _wave_worker(self):
        """Runs off the Tk thread, one track at a time; results go in the queue.

        Sequentially rather than a thread per track: they all read the same file
        off the same disk, and the first lane appearing sooner is worth more
        than all four appearing together.
        """
        for track in self.tracks:
            if self._wave_cancel.is_set():
                return
            try:
                levels = export.peaks(
                    self.clip_path, track.index, self.duration,
                    cancel=self._wave_cancel,
                )
            except Exception:                             # noqa: BLE001
                levels = []      # a lane with no waveform, not a broken editor
            self._wave_events.put((track.index, levels))

    def _poll_waves(self):
        """Take finished waveforms on the Tk thread and redraw as they land."""
        self._wave_poll_job = None
        if self._closing or not self.winfo_exists():
            return
        landed = False
        while True:
            try:
                index, levels = self._wave_events.get_nowait()
            except queue.Empty:
                break
            self._waves[index] = levels
            landed = True
        if landed:
            self._wave_points.clear()
            self._draw_timeline()
        if len(self._waves) < len(self.tracks):
            self._wave_poll_job = self.after(200, self._poll_waves)

    def _wave_shape(self, index, top):
        """Polygon points for one lane's waveform, or None while it has none.

        One polygon per lane rather than a line per column: every resize
        redraws the whole timeline, and a canvas item per pixel per track makes
        that visibly slow where a single item does not. The points are cached
        until the width changes, so muting a track redraws for free.
        """
        levels = self._waves.get(index)
        if not levels:
            return None
        left, right = self._span()
        width = int(right - left)
        if width < 2:
            return None
        if width != self._wave_width:
            self._wave_points.clear()
            self._wave_width = width
        cached = self._wave_points.get(index)
        if cached is not None:
            return cached

        middle = top + LANE_H / 2
        limit = LANE_H / 2 - WAVE_PAD
        upper, lower = [], []
        for column in range(width + 1):
            low = column * len(levels) // (width + 1)
            high = max(low + 1, (column + 1) * len(levels) // (width + 1))
            # The loudest of everything the column covers, never the average: a
            # single shout in a quiet minute is exactly what is being looked for.
            height = max(0.5, max(levels[low:high]) ** WAVE_CURVE * limit)
            x = left + column
            upper.append((x, middle - height))
            lower.append((x, middle + height))
        points = [value for point in upper + lower[::-1] for value in point]
        self._wave_points[index] = points
        return points

    def _draw_wave(self, track, colour, muted, top):
        """Draw `track`'s levels mirrored about the middle of its lane."""
        points = self._wave_shape(track.index, top)
        if points is None:
            return
        self.timeline.create_polygon(
            points, outline="",
            fill=WAVE_MUTED if muted else shade(colour, WAVE_SHADE),
        )

    # --- Timeline drawing --------------------------------------------------

    def _span(self):
        width = max(1, self.timeline.winfo_width())
        return EDGE_PAD, width - EDGE_PAD

    def _x_for(self, seconds):
        left, right = self._span()
        if not self.duration:
            return left
        return left + (right - left) * (seconds / self.duration)

    def _time_for(self, x):
        left, right = self._span()
        if right <= left or not self.duration:
            return 0.0
        return max(0.0, min(self.duration, (x - left) / (right - left) * self.duration))

    def _draw_timeline(self):
        canvas = self.timeline
        if not canvas.winfo_exists():
            return
        canvas.delete("all")
        left, right = self._span()
        if right <= left:
            return

        for seconds, label in self._ticks():
            x = self._x_for(seconds)
            canvas.create_line(x, RULER_H - 6, x, RULER_H, fill="#3a4050")
            canvas.create_text(x, RULER_H - 12, text=label, fill=TEXT_MUTED,
                               font=("TkDefaultFont", 8))

        lanes = [VIDEO_LANE] + [
            lane_colour(track, i) for i, track in enumerate(self.tracks)
        ]
        muted = [False] + [t.muted for t in self.tracks]
        for i, colour in enumerate(lanes):
            top = RULER_H + LANE_GAP + i * (LANE_H + LANE_GAP)
            canvas.create_rectangle(
                left, top, right, top + LANE_H,
                fill=LANE_BG if muted[i] else colour, outline="",
            )
            if i:      # lane 0 is the video, which has no levels to show
                self._draw_wave(self.tracks[i - 1], colour, muted[i], top)

        # Shade everything outside the selection, then bracket it.
        bottom = RULER_H + len(lanes) * (LANE_H + LANE_GAP)
        x_in, x_out = self._x_for(self.trim_start), self._x_for(self.trim_end)
        for x0, x1 in ((left, x_in), (x_out, right)):
            if x1 > x0:
                canvas.create_rectangle(x0, RULER_H, x1, bottom,
                                        fill=TRIM_SHADE, outline="", stipple="gray50")
        for x in (x_in, x_out):
            canvas.create_line(x, RULER_H - 4, x, bottom, fill=ACCENT, width=3)

        self._draw_playhead()

    def _ticks(self):
        """Roughly one label per 90px, snapped to a friendly interval."""
        left, right = self._span()
        if not self.duration or right <= left:
            return []
        target = max(1, int(self.duration / max(1, (right - left) / 90)))
        for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
            if step >= target:
                target = step
                break
        return [(t, core.format_duration(t))
                for t in range(0, int(self.duration) + 1, target)]

    def _draw_playhead(self):
        canvas = self.timeline
        if not canvas.winfo_exists():
            return
        canvas.delete("playhead")
        bottom = RULER_H + (1 + len(self.tracks)) * (LANE_H + LANE_GAP)
        x = self._x_for(self._position)
        canvas.create_line(x, 0, x, bottom, fill=PLAYHEAD, width=1, tags="playhead")

    # --- Timeline interaction ---------------------------------------------

    def _on_press(self, event):
        x_in, x_out = self._x_for(self.trim_start), self._x_for(self.trim_end)
        if abs(event.x - x_in) <= GRAB_PX:
            self._drag = "in"
        elif abs(event.x - x_out) <= GRAB_PX:
            self._drag = "out"
        else:
            self._drag = "seek"
            self.seek_to(self._time_for(event.x))

    def _on_drag(self, event):
        moment = self._time_for(event.x)
        if self._drag == "in":
            self.trim_start = min(moment, self.trim_end - 0.1)
            self._draw_timeline()
        elif self._drag == "out":
            self.trim_end = max(moment, self.trim_start + 0.1)
            self._draw_timeline()
        elif self._drag == "seek":
            self.seek_to(moment)

    def _on_release(self, _event):
        if self._drag in ("in", "out"):
            self._update_estimate()
            self._mark_dirty()
        self._drag = None

    # --- Export ------------------------------------------------------------

    def _update_estimate(self):
        """Describe what a trim of the current selection would come to.

        Trimming copies the streams, so this is the source's own quality at the
        length of the selection — it follows the markers rather than any fixed
        budget. Sizing down to a cap is the export window's business, and the
        cap is chosen there.
        """
        if self.selection < 0.05:
            self.status_label.configure(text="Selection is empty.",
                                        text_color=TEXT_MUTED)
            return
        parts = [core.format_duration(self.selection)]
        if self.info.summary:
            parts.append(self.info.summary)
        estimate = export.copy_estimate(self.info, self.selection)
        if estimate:
            parts.append(f"≈{core.format_size(estimate, 0)}")
        self.status_label.configure(text=" · ".join(parts),
                                    text_color=TEXT_MUTED)

    def start_export(self):
        """Open the export window; it owns the size choice and the encode."""
        if self.selection < 0.05:
            self.status_label.configure(text="Selection is empty.")
            return
        if self._export_win is not None and self._export_win.winfo_exists():
            self._export_win.focus()          # one at a time
            return
        self._export_win = export_window.ExportWindow(
            self, self.clip_path, self.trim_start, self.trim_end,
            self.tracks, self.info,
            clip_name=self.clip_name, export_dir=self.export_dir,
        )

    # --- Trim to disk ------------------------------------------------------

    def _has_trim(self):
        """True when the markers actually select less than the whole clip."""
        if not self.duration or self.selection < 0.05:
            return False
        return self.trim_start > 0.05 or self.trim_end < self.duration - 0.05

    def confirm_trim(self):
        """Ask what to do with the selection, then write it out."""
        if self._trim_thread is not None:
            return
        if not self._has_trim():
            self.status_label.configure(
                text="Set the In/Out markers first.", text_color=TEXT_MUTED)
            return

        span = (f"{core.format_duration(self.trim_start)} – "
                f"{core.format_duration(self.trim_end)} "
                f"({core.format_duration(self.selection)})")
        choice = widgets.ChoiceDialog.ask(
            self,
            title="Trim clip",
            message="Trim this clip to the selection?",
            detail=f"{span}\n\n"
                   "The trimmed file keeps the original quality and every audio "
                   "track, so it can be edited again. It starts at the nearest "
                   "keyframe before the In marker.\n\n"
                   "Deleting keeps the clip's name and moves the original to "
                   "your Trash.",
            choices=[
                ("Save Trim and Delete Clip", "replace", True),
                ("Save Trim as Copy", "copy", False),
            ],
            min_width=460,
        )
        if choice is not None:
            self._start_trim(choice)

    def _trim_target(self, mode):
        """Where the trimmed file is written for `mode`."""
        folder = os.path.dirname(os.path.abspath(self.clip_path))
        stem = os.path.splitext(os.path.basename(self.clip_path))[0]
        if mode == "copy":
            candidate = os.path.join(folder, f"{stem} (trimmed).mp4")
            count = 2
            while os.path.exists(candidate):
                candidate = os.path.join(folder, f"{stem} (trimmed {count}).mp4")
                count += 1
            return candidate
        # Replacing: stage next to the original, so the swap is a rename on the
        # same filesystem. Hidden, so a folder scan mid-trim ignores it.
        return os.path.join(folder, f".{stem}.gsm-trim.mp4")

    def _start_trim(self, mode):
        out_path = self._trim_target(mode)
        # Held until the result is handed over, so an editor closed mid-trim
        # knows there is a staged file to clean up.
        self._trim_mode, self._trim_out = mode, out_path
        self.trim_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.status_label.configure(text="Trimming…", text_color=TEXT_MUTED)
        self._trim_thread = threading.Thread(
            target=self._trim_worker, args=(mode, out_path), daemon=True
        )
        self._trim_thread.start()
        self._trim_poll_job = self.after(120, self._poll_trim)

    def _trim_worker(self, mode, out_path):
        """Runs off the Tk thread; results come back through the queue."""
        try:
            size = export.trim(
                self.clip_path, out_path, self.trim_start, self.trim_end
            )
            self._trim_events.put(("done", (mode, out_path, size)))
        except export.ExportError as exc:
            self._trim_events.put(("failed", str(exc)))
        except Exception as exc:                          # noqa: BLE001
            self._trim_events.put(("failed", f"Trim failed: {exc}"))

    def _poll_trim(self):
        """Drain trim results on the Tk thread (mpv's poller may not be running)."""
        self._trim_poll_job = None
        if self._closing or not self.winfo_exists():
            return
        try:
            kind, payload = self._trim_events.get_nowait()
        except queue.Empty:
            self._trim_poll_job = self.after(120, self._poll_trim)
            return
        self._trim_thread = None
        if kind == "done":
            self._trim_done(*payload)
        else:
            self._trim_failed(payload)

    def _trim_done(self, mode, out_path, size):
        self._trim_out = None      # handed over; no longer ours to clean up
        self.trim_btn.configure(state="normal")
        self.export_btn.configure(state="normal")
        if mode == "copy":
            self._title_the_copy(out_path)
            self.status_label.configure(
                text=f"Saved {os.path.basename(out_path)} · "
                     f"{core.format_size(size)}",
                text_color=OK_GREEN,
            )
        else:
            self.status_label.configure(text="Trimmed.", text_color=OK_GREEN)
        if self.on_trimmed is not None:
            # For "replace" this leaves the editor and swaps the file in — the
            # original cannot be touched while mpv still has it open.
            self.on_trimmed(mode, out_path)

    def _trim_failed(self, message):
        # ffmpeg may have left a half-written file; it must not end up in the
        # clip folder looking like a real clip.
        self._discard_staged()
        self.trim_btn.configure(state="normal")
        self.export_btn.configure(state="normal")
        self.status_label.configure(text=message, text_color=DANGER)

    def _discard_staged(self):
        staged, self._trim_out = self._trim_out, None
        if not staged:
            return
        try:
            os.remove(staged)
        except OSError:
            pass   # never existed, or already gone

    def _title_the_copy(self, out_path):
        """Carry a renamed clip's title over to its trimmed copy."""
        if self.library is None or self.clip_title == self.clip_name:
            return
        try:
            self.library.set_title(
                os.path.basename(out_path), f"{self.clip_title} (trimmed)"
            )
        except Exception:
            pass   # a title is a nicety; never fail the trim over one

    # --- Teardown ----------------------------------------------------------

    def go_back(self):
        if self.on_back is not None:
            self.on_back()

    def _delete(self):
        if self.on_delete is not None and not self._closing:
            self.on_delete()

    def stop(self):
        """Shut mpv down. Must run before this frame's X window is destroyed."""
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except (tkinter.TclError, ValueError):
                pass
            self._save_job = None
        if self._dirty:
            self._dirty = False
            self._save_edit()
        self._unbind_keys()

        self._closing = True
        if self._export_win is not None and self._export_win.winfo_exists():
            self._export_win.close()
        self._export_win = None
        # The waveform decode is pure decoration and nothing waits on it, so it
        # is told to stop and left to notice: killing its ffmpeg is the point,
        # and blocking the close on a thread that only fills a queue is not.
        self._wave_cancel.set()
        self._wave_thread = None
        for attr in ("_poll_job", "_trim_poll_job", "_wave_poll_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except (tkinter.TclError, ValueError):
                    pass
                setattr(self, attr, None)
        # Wait out a trim in flight — it only writes its own new file — then
        # drop a staged replacement, whose swap into the clip folder is never
        # going to happen now. A finished copy is left alone: the user asked
        # for that file by name, and it shows up on the next folder scan.
        thread, self._trim_thread = self._trim_thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        if self._trim_mode == "replace":
            self._discard_staged()
        self._trim_mode = None
        player, self._player = self._player, None
        if player is None:
            return
        try:
            player.terminate()
        except Exception:
            pass
        # Tearing the video output down resets the X error handler to Xlib's
        # fatal default, discarding Tk's. Without re-arming, the very next
        # request Tk makes against this dying frame exits the process.
        xguard.rearm()

    def destroy(self):
        self.stop()
        super().destroy()


def meta_of(info, recorded=0.0):
    """Resolution, frame rate and recording date, shown next to the title.

    Whatever of the three is known: a clip whose streams would not probe still
    gets its date, and one the library has no date for still gets its size and
    rate. The date is written out in full rather than as an age — the grid says
    how old a clip is, and the editor is where you look to find out when.
    """
    parts = []
    if info.width and info.height:
        parts.append(f"{info.width}×{info.height} @ {round(info.fps)} fps")
    if recorded:
        parts.append(core.format_date(recorded))
    return "".join(f"   ·   {part}" for part in parts)
