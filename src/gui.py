"""CustomTkinter GUI for Vertex.

Implements the Clips Overview screen (top strip + clip grid) and the clip editor
it swaps to, both modelled on the SteelSeries Moments layout. Tkinter has no
native video widget, so the editor embeds mpv — see player.py.
"""

import os
import queue
import sqlite3
import subprocess
import threading
import time
import tkinter
from tkinter import filedialog
from typing import ClassVar

import customtkinter as ctk
from PIL import Image, ImageTk

import core
import database
import paint
import player
import thumbnails
import widgets
import xguard
from theme import (
    ACCENT, ACCENT_HOVER, BADGE_BG, BADGE_HOVER, CARD_BG,
    CARD_BLUR, CARD_BOTTOM, CARD_DROP, CARD_HOVER, CARD_HOVER_BOTTOM,
    CARD_HOVER_TOP, CARD_SHADOW, CARD_TOP, DANGER, GAUGE_CLIPS,
    CHROME_TOP, CONTENT_PAD_TOP, GAUGE_FREE, GAUGE_OTHER, GLOW_H, GLOW_PLATEAU,
    HEADER_H, MAIN_BG, METER_CLIPS, PAGE_GLOW,
    PRIMARY_BUTTON, RADIUS_CARD,
    RADIUS_CONTROL, RADIUS_PANEL, RADIUS_SMALL, RAIL_ACTIVE, RAIL_ACTIVE_TEXT,
    RAIL_FIELD_BG, RAIL_LINE, SEAM, SECTION_BG, SEG_TRACK_BG, SEG_TRACK_HOVER,
    SIDEBAR_BG, TEXT_BRIGHT, TEXT_DIM, TEXT_MUTED, THUMB_BG,
)
from theme import CARD_PAD as SHADOW_PAD

ctk.set_appearance_mode("dark")

# Pixels the view moves per mouse-wheel tick. CustomTkinter's default 1-unit
# step feels sluggish; the App-level wheel handler moves this many pixels
# instead — via yview_moveto, which (unlike yscrollincrement) keeps embedded
# card windows' hit regions aligned with what's drawn after a partial scroll.
SCROLL_STEP = 55


def plural(count, noun):
    """'1 clip' / '2 clips' — status lines say this often enough to share it."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def tilde(path):
    """'/home/you/.config/x' -> '~/.config/x', for paths shown in the chrome."""
    home = os.path.expanduser("~")
    return f"~{path[len(home):]}" if path.startswith(home + os.sep) else path


def oxford(items):
    """['a'] -> 'a'; ['a','b'] -> 'a and b'; ['a','b','c'] -> 'a, b and c'."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def find_scroll_canvas(widget):
    """Walk up from `widget` to the enclosing scrollable canvas, or None.

    Not every canvas on the way up is one: every CTkFrame/CTkLabel draws its
    rounded corners on an inner canvas placed edge to edge behind its children,
    so the pointer sitting on a card's own background — the info row under the
    thumbnail, the padding around it — reports that decorative canvas as the
    event target. Scrolling it does nothing to the view, so a wheel handler
    that stopped at the first canvas simply stopped scrolling there.

    Only the canvas a CTkScrollableFrame scrolls has a scrollregion, which is
    what tells the two apart. Decorative canvases never get one.
    """
    while widget is not None:
        if isinstance(widget, tkinter.Canvas):
            try:
                if widget.cget("scrollregion"):
                    return widget
            except tkinter.TclError:
                pass
        widget = getattr(widget, "master", None)
    return None


def bind_recursive(widget, sequence, func):
    """Bind `sequence` on `widget` and every descendant, once each.

    CustomTkinter widgets are composites, so a binding on the outer frame never
    sees clicks that land on an inner label, canvas or button — hence the walk.

    It goes through `tkinter.Misc.bind` rather than the widget's own `bind`
    because a CTk composite forwards `bind` to the very children this then
    recurses into, which left every one of them holding the handler twice. A
    handler that toggles something therefore ran twice and did nothing at all,
    which is why a fold-away heading only answered clicks on its bare frame and
    never on its chevron or its title.
    """
    tkinter.Misc.bind(widget, sequence, func, add="+")
    for child in widget.winfo_children():
        bind_recursive(child, sequence, func)


def _guard_ctk_scroll():
    """Stop CustomTkinter's global wheel handler raising on a stale target.

    CTkScrollableFrame binds the wheel with bind_all, so its handler sees every
    scroll anywhere in the app and walks the target's .master chain to work out
    whether the event belongs to it. Tk passes a plain string instead of a
    widget whenever it cannot resolve the target — a window torn down between
    the event being queued and dispatched, which a modal closing under the
    pointer does routinely — and a string has no .master, so it raises.

    The binding outlives the frame that made it, so one closed dialog is enough
    to keep raising for the rest of the session. Patched centrally because
    every scrollable frame in the app inherits the same handler.
    """
    original = ctk.CTkScrollableFrame._check_if_valid_scroll

    def guarded(self, widget):
        if isinstance(widget, str):
            return False    # not a live widget, so certainly not ours
        try:
            return original(self, widget)
        except (AttributeError, tkinter.TclError):
            return False    # the .master chain died partway up
    ctk.CTkScrollableFrame._check_if_valid_scroll = guarded


_guard_ctk_scroll()


def make_scroll_pixel_precise(scrollable):
    """Override CustomTkinter's 30px scroll increment (Linux) with 1px.

    The large increment desyncs embedded card windows' hit regions from what's
    drawn after a partial scroll (hover lands on the wrong clip). At 1px the
    view is pixel-exact and stays aligned; the App-level wheel handler supplies
    the actual scroll speed via yview_moveto.
    """
    try:
        scrollable._parent_canvas.configure(yscrollincrement=1)
    except (AttributeError, tkinter.TclError):
        pass


# A CTkLabel doesn't wrap without being told a width, so an explanatory
# paragraph would otherwise render as one very wide line and be clipped by the
# scroll frame around it. Every blurb in Settings and first-run setup wraps here.
BLURB_WRAP = 620

# Space between the panels in Settings — wide enough that the sections read as
# separate blocks rather than as one long column of fields.
SECTION_GAP = 20

# Between two fields on a Settings page. Settings shows one page at a time now,
# so a field can have the room to be read rather than being packed tight to fit
# every subject on one screen.
FIELD_GAP = 26

# A Settings panel's own margins: PANEL_SHADOW is the ring of page colour the
# drop shadow falls into (so the widget is bigger than the panel you see, as a
# clip card is), PANEL_PAD the breathing room inside the panel itself.
PANEL_SHADOW = 8
PANEL_PAD = 26

# How often Settings re-reads its fields to say what is still unsaved. Slow
# enough to cost nothing, quick enough that it lands while you are still looking
# at the field you changed.
DIRTY_POLL_MS = 400


# --- Branding --------------------------------------------------------------
LOGO_SIZE = 36        # general-purpose mark, px square
# The rail heads with the horizontal lockup rather than a mark beside a text
# label, so the name is set the way the brand sets it. Sized by height, since
# the artwork carries its own width: below about 34px the "MOMENTS" line under
# the wordmark stops resolving into letters.
RAIL_WORDMARK_H = 40

# --- The lit top edge ------------------------------------------------------
# The page is lit from above: a band held at PAGE_GLOW behind the header row,
# let down into MAIN_BG in the gap between that row and the first card. The
# window paints its half — what shows in the margin — and each view paints the
# rest, on the shared numbers in theme.py so the two line up across the margin.
#
# Why a band and not a gradient over the whole page: everything below the
# header is a widget, CustomTkinter widgets cannot be transparent, and a widget
# over a gradient paints a flat rectangle of its parent's colour (see paint.py)
# — so the light has to finish where the widgets start.
#
# The rail is lit the same way, with its own stops and its own foot: the brand
# row sits on the plateau, the search field's own fill covers the fall, and the
# lists below start where it has arrived at SIDEBAR_BG.
RAIL_GLOW_PLATEAU = 60
RAIL_GLOW_H = 114
SETUP_LOGO_SIZE = 56  # larger mark on the first-run screen

# Rebuilding the grid on every keystroke would rebuild it four times for
# "apex"; the search box waits for the typing to stop first.
SEARCH_DEBOUNCE_MS = 180

# A stable colour per game for the rail's dots, so a game keeps the same one
# between sessions and between machines. Derived from the name rather than from
# its position in the list, which would reshuffle every time a game was added.
# How many people the rail lists before it stops. The count in the group's
# header still reports them all, so a long tail is visible even when it is not
# listed — searching by name finds anyone this leaves out.
PEOPLE_SHOWN = 6

GAME_DOTS = ("#c04a3c", "#d1762c", "#e0b230", "#6b48a8", "#1f7fd4",
             "#2fb39b", "#d9932b", "#3b82f6", "#c25d7b", "#9b6bd6")


def game_colour(name):
    """The rail's dot colour for `name`, stable for as long as the name is."""
    return GAME_DOTS[hash_name(name) % len(GAME_DOTS)]


def hash_name(name):
    """A small stable hash. Python's own is salted per process, so not that."""
    total = 0
    for char in name.casefold():
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    return total


def load_logo(size, variant=core.DEFAULT_LOGO_VARIANT):
    """The mark as a CTkImage of `size` px square, in the chosen ink.

    Used as drawn, never tinted: recolouring it from its alpha channel would
    flatten the accent dot at its centre into the same grey as the rest, and
    each variant is already drawn for the background it belongs on. Returns None
    if the file is missing, so the app still runs from a checkout without it.
    """
    try:
        with Image.open(core.mark_path(variant)) as source:
            mark = source.convert("RGBA")
    except (OSError, ValueError):
        return None
    return ctk.CTkImage(light_image=mark, dark_image=mark, size=(size, size))


def load_wordmark(height, variant=core.DEFAULT_LOGO_VARIANT):
    """The horizontal lockup `height` px tall, width to match, in that ink.

    The lockup is exported on a wide canvas with the name set well left of its
    right edge, so it is cropped to its own artwork first — otherwise the empty
    canvas would be scaled along with it and the logo would sit as a small mark
    in a large invisible box. Returns None if the file is missing.
    """
    try:
        with Image.open(core.wordmark_path(variant)) as source:
            art = source.convert("RGBA")
            ink = art.getchannel("A").getbbox()
            if ink:
                art = art.crop(ink)
    except (OSError, ValueError):
        return None
    width = max(1, round(art.width * height / art.height))
    return ctk.CTkImage(light_image=art, dark_image=art, size=(width, height))


def apply_window_icon(window, variant=core.DEFAULT_LOGO_VARIANT):
    """Set the taskbar/titlebar icon from the mark, in the chosen ink."""
    try:
        with Image.open(core.mark_path(variant)) as source:
            icon = ImageTk.PhotoImage(source.convert("RGBA"))
    except (OSError, ValueError):
        return
    # Tk drops the image if nothing keeps a reference to it.
    window._icon_image = icon
    try:
        window.iconphoto(True, icon)
    except tkinter.TclError:
        pass


# --- Tooltip ---------------------------------------------------------------
# It lives in widgets.py now that the editor's icon-only transport needs one
# too; gui.py imports player.py, so a shared widget cannot live here.
Tooltip = widgets.Tooltip


# --- Confirm dialog --------------------------------------------------------
def confirm_delete_clip(master, clip):
    """Ask before deleting `clip`. Shared by the clip grid and the editor."""
    return widgets.ChoiceDialog.ask(
        master,
        title="Delete clip",
        message="Delete this clip?",
        detail=f"{clip.name}\n{clip.size_human}  ·  {clip.age_human}\n\n"
               "It is moved to your Trash, so you can still recover it.",
        choices=[("Delete", True, True)],
    ) is True


# --- Top bar ---------------------------------------------------------------
class Rail(ctk.CTkFrame):
    """The app's one piece of chrome, down the left.

    It replaced a top strip that had a brand, a storage gauge and a cog on it
    and nothing else. Everything from that strip is still here — the brand at
    the top, the gauge at the foot, the cog as the last row — and the space in
    between, which a horizontal strip did not have, goes to the two things the
    library already knows and could never show: which games are in it, and who
    is in them.

    The lists are one component in two states. On the grid they are the library;
    in Settings they are its sections. The shell never changes, so moving
    between the two does not move anything else on screen.
    """

    WIDTH = 250
    # (label, kind, value) for the fixed rows above the tag-derived ones.
    LIBRARY_ROWS: ClassVar[list] = [
        ("All clips", None, None),
        ("★ Favorites", "favorite", None),
    ]
    # The Settings pages, in the order the rail lists them. Each is a page of
    # its own in SettingsView, so this list is also that view's running order.
    SETTINGS_ROWS: ClassVar[list] = [
        ("Folders", "folders"), ("Audio devices", "devices"),
        ("Appearance", "appearance"), ("Import", "import"),
    ]

    def __init__(self, master, on_search, on_facet, on_settings, on_section,
                 logo_variant=core.DEFAULT_LOGO_VARIANT):
        super().__init__(master, width=self.WIDTH, corner_radius=0,
                         fg_color=SIDEBAR_BG)
        self.grid_propagate(False)
        self.on_search = on_search
        self.on_facet = on_facet
        self.on_settings = on_settings
        self.on_section = on_section
        self.mode = "library"
        self.facet = (None, None)     # (kind, value); (None, None) is everything
        self.section = "folders"
        self._rows = {}               # (kind, value) -> the row's frame
        self._collapsed = {}          # group key -> folded? Games and People
        self._search_job = None

        # The rail's own lit top, on its own stops: it is a panel above the
        # page, so it is lit from CHROME_TOP down to its own SIDEBAR_BG rather
        # than to the page's. Built before the rail's children, which stack on
        # top of it.
        widgets.attach_glow(self, top=CHROME_TOP, bottom=SIDEBAR_BG,
                            plateau=RAIL_GLOW_PLATEAU, height=RAIL_GLOW_H)

        # A 1px lit edge where the rail meets the workspace, doing the same job
        # the seam did under the old strip.
        tkinter.Frame(self, bg=SEAM, width=1, bd=0, highlightthickness=0).place(
            relx=1.0, y=0, relheight=1, anchor="ne")

        # CHROME_TOP, not transparent: this row sits on the plateau at the top
        # of the rail's band, and a transparent frame would paint SIDEBAR_BG
        # over it (see widgets.attach_glow).
        head = ctk.CTkFrame(self, fg_color=CHROME_TOP)
        head.pack(fill="x", padx=14, pady=(16, 0))
        # Kept as an attribute: set_logo swaps the artwork in place when the
        # variant is changed in Settings, and Tk drops an image the moment
        # nothing holds a reference to it.
        self.logo_image = None
        self.brand = ctk.CTkLabel(head, text="", compound="left")
        self.brand.pack(side="left")
        self.set_logo(logo_variant)

        # Free-text search. The rail's lists narrow by one tag; this still
        # searches game, people, title and file name all at once.
        self.search_entry = ctk.CTkEntry(
            self, height=32, fg_color=RAIL_FIELD_BG, border_width=1,
            border_color=RAIL_LINE, corner_radius=RADIUS_SMALL,
            placeholder_text="Search clips")
        self.search_entry.pack(fill="x", padx=14, pady=(14, 0))
        for sequence in ("<KeyRelease>", "<<Paste>>", "<<Cut>>", "<<Clear>>"):
            self.search_entry.bind(sequence, self._search_changed, add="+")

        # Everything between the search box and the storage panel, rebuilt
        # whenever the library's tags change. Scrollable, because the games
        # list is as long as the library is varied — twenty of them would
        # otherwise push the gauge and the cog off the bottom of the rail,
        # which is exactly the thing moving them here was meant to fix.
        self.lists = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                            width=self.WIDTH - 30)
        self.lists.pack(fill="both", expand=True, padx=8, pady=(14, 0))
        make_scroll_pixel_precise(self.lists)

        self.storage = ctk.CTkFrame(self, fg_color="transparent")
        self.storage.pack(fill="x", padx=14, pady=(0, 0))
        ctk.CTkFrame(self.storage, height=1, fg_color=RAIL_LINE,
                     corner_radius=0).pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            self.storage, text="CLIPS DRIVE", anchor="w", text_color=TEXT_DIM,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", pady=(0, 8))
        holder = ctk.CTkFrame(self.storage, fg_color="transparent", height=8)
        holder.pack(fill="x")
        holder.pack_propagate(False)
        self.track = ctk.CTkFrame(holder, height=8, corner_radius=4,
                                  fg_color=GAUGE_FREE)
        self.track.pack(fill="x")
        self.track.pack_propagate(False)
        self.clips_segment = self.other_segment = None
        # The legend is the point of moving the gauge here: on the old strip the
        # bar had no room to say which colour was which, or how big any of them
        # were.
        self.legend = {}
        for key, colour, label in (("clips", GAUGE_CLIPS, "Clips"),
                                   ("other", GAUGE_OTHER, "Everything else"),
                                   ("free", GAUGE_FREE, "Free")):
            self.legend[key] = self._legend_row(colour, label)

        self.cog_row = self._row(self, "⚙  Settings", ("settings", None),
                                 command=self._toggle_settings)
        self.cog_row.pack(fill="x", padx=8, pady=(12, 12))

        self.set_library({}, set(), 0)

    # --- rows --------------------------------------------------------------

    def _legend_row(self, colour, label):
        row = ctk.CTkFrame(self.storage, fg_color="transparent", height=18)
        row.pack(fill="x", pady=(6, 0))
        row.pack_propagate(False)
        ctk.CTkFrame(row, width=8, height=8, corner_radius=2,
                     fg_color=colour).pack(side="left", pady=4)
        ctk.CTkLabel(row, text=label, anchor="w", text_color=TEXT_MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(8, 0))
        value = ctk.CTkLabel(row, text="", anchor="e", text_color=TEXT_BRIGHT,
                             font=ctk.CTkFont(size=11))
        value.pack(side="right")
        return value

    def _heading(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), anchor="w", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     ).pack(anchor="w", fill="x", padx=9, pady=(14, 5))

    def _group(self, parent, title, key, count):
        """A heading that folds its rows away. Returns the frame to pack into.

        Same idea as Disclosure in Settings, at the size the rail's headings
        are: a chevron, the title, and how many rows are inside — the count is
        what keeps a folded group worth having, since it still says what is in
        there. Which groups are folded lives on the rail rather than on the
        widgets, so it survives set_library rebuilding the lists.
        """
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.pack(fill="x")

        header = ctk.CTkFrame(holder, fg_color="transparent", height=22)
        header.pack(fill="x", padx=9, pady=(14, 5))
        header.pack_propagate(False)
        chevron = ctk.CTkLabel(
            header, text="", width=10, anchor="w", text_color=TEXT_DIM,
            font=ctk.CTkFont(size=9))
        chevron.pack(side="left")
        ctk.CTkLabel(header, text=title.upper(), anchor="w",
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=10, weight="bold"),
                     ).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(header, text=str(count), anchor="e", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=10)).pack(side="right")

        body = ctk.CTkFrame(holder, fg_color="transparent")

        def paint():
            folded = self._collapsed.get(key, False)
            chevron.configure(text="▸" if folded else "▾")
            if folded:
                body.pack_forget()
            else:
                body.pack(fill="x")

        def toggle(_event=None):
            self._collapsed[key] = not self._collapsed.get(key, False)
            paint()

        bind_recursive(header, "<Button-1>", toggle)
        for widget in (header, chevron, *header.winfo_children()):
            widget.configure(cursor="hand2")
        paint()
        return body

    def _row(self, parent, label, key, count=None, dot=None, command=None):
        """One clickable row: optional colour dot, label, optional count."""
        row = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=8,
                           height=29)
        row.pack_propagate(False)
        if dot:
            ctk.CTkFrame(row, width=7, height=7, corner_radius=2,
                         fg_color=dot).pack(side="left", padx=(9, 0))
        name = ctk.CTkLabel(row, text=label, anchor="w", text_color=TEXT_MUTED,
                            font=ctk.CTkFont(size=12))
        name.pack(side="left", padx=(9 if not dot else 8, 0), fill="x",
                  expand=True)
        tally = None
        if count is not None:
            tally = ctk.CTkLabel(row, text=str(count), anchor="e",
                                 text_color=TEXT_DIM,
                                 font=ctk.CTkFont(size=11))
            tally.pack(side="right", padx=(0, 9))
        row._parts = (name, tally)
        handler = command or (lambda _e=None, k=key: self._pick(k))
        bind_recursive(row, "<Button-1>", lambda _e, h=handler: h())
        for widget in (row, name) + ((tally,) if tally else ()):
            widget.configure(cursor="hand2")
        self._rows[key] = row
        return row

    def _paint_rows(self):
        """Mark whichever row is current, in whichever mode we are in."""
        active = ("settings", None) if self.mode == "settings" else self.facet
        if self.mode == "settings":
            active = ("section", self.section)
        for key, row in self._rows.items():
            if not row.winfo_exists():
                continue
            on = key == active or (self.mode == "settings"
                                   and key == ("settings", None))
            row.configure(fg_color=RAIL_ACTIVE if on else "transparent")
            name, tally = row._parts
            name.configure(text_color=RAIL_ACTIVE_TEXT if on else TEXT_MUTED)
            if tally is not None:
                tally.configure(text_color=RAIL_ACTIVE_TEXT if on else TEXT_DIM)

    # --- contents ----------------------------------------------------------

    def set_library(self, tags, favorites, total):
        """Rebuild the library lists from the tags the grid just loaded."""
        self._clear_lists()
        games, people = {}, {}
        for game, names in tags.values():
            if game:
                games[game] = games.get(game, 0) + 1
            for person in names:
                people[person] = people.get(person, 0) + 1
        untagged = total - sum(1 for game, _p in tags.values() if game)

        self._heading(self.lists, "Library")
        for label, kind, value in self.LIBRARY_ROWS:
            count = len(favorites) if kind == "favorite" else total
            self._row(self.lists, label, (kind, value), count).pack(fill="x")

        ranked = sorted(games.items(), key=lambda kv: (-kv[1], kv[0]))
        if ranked or untagged > 0:
            body = self._group(self.lists, "Games", "games",
                               len(ranked) + (1 if untagged else 0))
            for name, count in ranked:
                self._row(body, name, ("game", name), count,
                          dot=game_colour(name)).pack(fill="x")
            if untagged > 0:
                self._row(body, "Untagged", ("game", ""), untagged,
                          dot=TEXT_DIM).pack(fill="x")
        if people:
            named = sorted(people.items(), key=lambda kv: (-kv[1], kv[0]))
            body = self._group(self.lists, "People", "people", len(named))
            for name, count in named[:PEOPLE_SHOWN]:
                self._row(body, name, ("person", name), count).pack(fill="x")
        self._paint_rows()

    def set_logo(self, variant):
        """Draw the brand row in `variant`'s ink, live.

        Falls back to the name set in type when the artwork will not load, which
        beats an empty corner and is what a checkout without the PNGs gets.
        """
        self.logo_image = load_wordmark(RAIL_WORDMARK_H, variant)
        if self.logo_image is not None:
            self.brand.configure(image=self.logo_image, text="")
        else:
            self.brand.configure(image=None, text=core.APP_NAME,
                                 font=ctk.CTkFont(size=14, weight="bold"))

    def set_mode(self, mode):
        """Swap the lists between the library and the Settings sections."""
        if mode == self.mode:
            self._paint_rows()
            return
        self.mode = mode
        if mode == "settings":
            self._clear_lists()
            self._heading(self.lists, "Settings")
            for label, key in self.SETTINGS_ROWS:
                self._row(self.lists, label, ("section", key),
                          command=lambda k=key: self._pick_section(k)).pack(fill="x")
        self._paint_rows()

    def _clear_lists(self):
        for child in self.lists.winfo_children():
            child.destroy()
        self._rows = {k: v for k, v in self._rows.items() if k == ("settings", None)}

    def refresh_storage(self, stats):
        """Redraw the gauge and its legend from a core.storage_stats() reading."""
        for segment in (self.clips_segment, self.other_segment):
            if segment is not None:
                segment.destroy()
        self.clips_segment = self.other_segment = None
        if stats is None:
            for value in self.legend.values():
                value.configure(text="—")
            return
        clips = stats.fraction(stats.clips_bytes)
        other = stats.fraction(stats.other_used)
        if clips > 0:
            self.clips_segment = ctk.CTkFrame(self.track, corner_radius=4,
                                              fg_color=GAUGE_CLIPS)
            self.clips_segment.place(relx=0, rely=0, relheight=1, relwidth=clips)
        if other > 0:
            self.other_segment = ctk.CTkFrame(self.track, corner_radius=0,
                                              fg_color=GAUGE_OTHER)
            self.other_segment.place(relx=clips, rely=0, relheight=1,
                                     relwidth=other)
        self.legend["clips"].configure(text=stats.clips_human)
        self.legend["other"].configure(text=stats.other_used_human)
        self.legend["free"].configure(text=stats.disk_free_human)

    # --- events ------------------------------------------------------------

    def query(self):
        return self.search_entry.get()

    def _search_changed(self, *_args):
        """Re-filter shortly after the last keystroke, not on every one."""
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(SEARCH_DEBOUNCE_MS, self.on_search)

    def _pick(self, key):
        self.facet = key
        self._paint_rows()
        self.on_facet(key)

    def _pick_section(self, section):
        self.section = section
        self._paint_rows()
        self.on_section(section)

    def _toggle_settings(self):
        self.on_settings(self.mode != "settings")


# --- Clip card -------------------------------------------------------------
CARD_PAD = 3          # inset between the card edge and the thumbnail
THUMB_ASPECT = 9 / 16  # thumbnail height as a fraction of its width
PREVIEW_HOVER_DELAY = 800  # ms to hover before generating/playing a preview
PREVIEW_FRAME_MS = 300     # ms each preview frame is shown (~3 fps)
HOVER_WATCH_MS = 150       # how often the watchdog re-checks the pointer


class ClipCard(ctk.CTkFrame):
    # Longest tag line a card shows before it gets an ellipsis; past this the
    # text runs into the action buttons on a narrow window.
    TAG_CHARS = 42

    def __init__(self, master, clip, thumbs, library, on_delete=None):
        # The card's face — rounded corners, gradient, and the drop shadow that
        # does the actual lifting — is one pre-rendered image (paint.card_surface).
        # The widget itself is therefore only the page it sits on: page-coloured,
        # square, unbordered, and SHADOW_PAD bigger on every side than the card
        # you see, so the shadow has somewhere to fall.
        super().__init__(master, fg_color=MAIN_BG, corner_radius=0,
                         border_width=0)
        self._surface = None       # PhotoImage; the cache in paint.py owns it
        self._surface_key = None   # (width, height, hovered) last painted
        self.backdrop = tkinter.Label(self, bd=0, highlightthickness=0,
                                      bg=MAIN_BG)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._on_card_resize, add="+")
        self.clip = clip
        self.library = library
        self.thumbs = thumbs
        self.on_delete = on_delete
        self._menu = None         # posted context menu; kept alive by this ref
        self._thumb_image = None  # keep a reference so Tk doesn't GC it
        self._pil_image = None    # source frame, rescaled to fill on resize
        self._resize_job = None   # pending debounced resize (after id)
        self._last_width = 0      # last width we actually rendered at

        # Hover-preview state.
        self._hover_active = False
        self._hover_job = None       # pending "start preview" timer (after id)
        self._preview_job = None     # frame-cycling timer (after id)
        self._watch_job = None       # watchdog that self-heals a missed <Leave>
        self._preview_frames = None  # list of PIL images once loaded
        self._preview_ctk = None     # CTkImage reused across preview frames
        self._preview_index = 0

        # Thumbnail: starts as a play glyph, swapped for the real frame async.
        # It tracks the card's width and stays 16:9, so there is no dead space.
        self.thumb = ctk.CTkFrame(self, fg_color=THUMB_BG, corner_radius=0,
                                  height=160)
        self.thumb.pack(fill="x", padx=SHADOW_PAD + CARD_PAD,
                        pady=(SHADOW_PAD + CARD_PAD, 0))
        self.thumb.pack_propagate(False)
        self.thumb.bind("<Configure>", self._on_thumb_resize)
        thumb = self.thumb
        self.thumb_label = ctk.CTkLabel(
            thumb, text="▶", font=ctk.CTkFont(size=32), text_color=TEXT_MUTED,
        )
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")
        # A single click on the thumbnail opens the clip and starts playback.
        for w in (thumb, self.thumb_label):
            w.bind("<Button-1>", self._open_editor)
        Tooltip(self.thumb_label, "Click to play")

        # Duration badge (top-right) and favorite star (bottom-right).
        duration = library.get_duration(clip.name)
        # Both the badge and the star need a fill, because a "transparent" CTk
        # widget paints its parent's colour — here the mid-grey THUMB_BG, as an
        # obvious box on top of the picture. Near-black instead, matching what
        # paint.scrim darkens the frame's edges to, so they sit in the image
        # rather than on it.
        self.duration_label = ctk.CTkLabel(
            thumb, text=self._duration_text(duration), fg_color=BADGE_BG,
            corner_radius=RADIUS_SMALL, font=ctk.CTkFont(size=11), padx=6,
        )
        self.duration_label.place(relx=0.97, rely=0.08, anchor="ne")
        # The badge sits on top of the thumbnail, so it needs the click too.
        self.duration_label.bind("<Button-1>", self._open_editor)
        if duration is None and clip.path:
            thumbs.request_duration(clip.path, self._apply_duration)
        edit = library.get_edit(clip.name)
        self.custom_title = edit.title    # "" means: show the filename
        self.game = edit.game             # "" means: the default game
        self.people = list(edit.people)
        self.favorite = edit.favorite
        self.star = ctk.CTkButton(
            thumb, text="★" if self.favorite else "☆", width=28, height=28,
            fg_color=BADGE_BG, hover_color=BADGE_HOVER,
            text_color=METER_CLIPS if self.favorite else TEXT_BRIGHT,
            corner_radius=RADIUS_SMALL, font=ctk.CTkFont(size=16),
            command=self._toggle_favorite,
        )
        self.star.place(relx=0.96, rely=0.92, anchor="se")
        Tooltip(self.star, "Favorite")

        # Kick off async thumbnail generation (no-op for demo clips w/o a path).
        if clip.path:
            thumbs.request(clip.path, self._apply_thumbnail)
            # Misc.bind, not self.bind: a CTk frame forwards bind to its own
            # canvas, and this card's canvas is covered by the backdrop label
            # and every widget on it — so the pointer never touches the thing
            # the binding was on, and the hover never fired. Bound on the frame
            # itself, X's virtual crossing events deliver Enter when the
            # pointer arrives anywhere inside the card.
            tkinter.Misc.bind(self, "<Enter>", self._on_enter, add="+")
            tkinter.Misc.bind(self, "<Leave>", self._on_leave, add="+")

        # Info row. Both frames are square-cornered purely for speed: a rounded
        # CustomTkinter frame draws its corners as anti-aliased canvas shapes,
        # which costs more than everything else on this row put together — and
        # a transparent frame has no visible corners to round in the first place.
        # Explicitly CARD_BOTTOM, not transparent: a transparent CTk frame
        # paints its parent's colour, and this one's parent is the page. The
        # card surface is drawn flat at exactly this value under the info strip
        # (see paint._ramp's flat tail) so the two meet invisibly.
        info = self._info_frame = ctk.CTkFrame(self, fg_color=CARD_BOTTOM,
                                               corner_radius=0)
        info.pack(fill="x", padx=SHADOW_PAD + 12, pady=(0, SHADOW_PAD + 12))

        text_col = self._text_col = ctk.CTkFrame(info, fg_color=CARD_BOTTOM,
                                                 corner_radius=0)
        # Tag line: the game, plus whoever was in the clip. Click it to retag.
        self.tag_label = ctk.CTkLabel(
            text_col, text=self._tag_text(), text_color=TEXT_MUTED, anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"), cursor="hand2",
        )
        self.tag_label.pack(anchor="w")
        self.tag_label.bind("<Button-1>", self._edit_tags)
        Tooltip(self.tag_label, "Click to edit tags")
        # Click the title to rename it. The name is library metadata — the file
        # on disk keeps its own name.
        self._title_font = ctk.CTkFont(size=13, weight="bold")
        self.title_label = widgets.EditableLabel(
            text_col, self.display_name(), self._rename,
            font=self._title_font,
            display=lambda text, pixels: self._elide(
                text, self._title_font, pixels),
        )
        self.title_label.pack(fill="x", anchor="w")
        Tooltip(self.title_label.label, "Click to rename")
        self.meta_label = ctk.CTkLabel(
            text_col, text=self._meta_text(), text_color=TEXT_MUTED, anchor="w",
            font=ctk.CTkFont(size=11),
        )
        self.meta_label.pack(anchor="w")

        # Action buttons (glyph, tooltip, command); rightmost is packed first.
        # Both go on before the text column, so pack reserves their width first
        # — a long file name would otherwise claim the row and push them off
        # the card entirely, which is what happened once the rail narrowed it.
        self.more_button = self._action_button(info, "⋮", "More", self._popup_menu)
        self._action_button(info, "↗", "Share", None)
        text_col.pack(side="left", fill="x", expand=True)

        # Right-click anywhere on the card opens the same menu. Bound last, so
        # every child built above is covered.
        bind_recursive(self, "<Button-3>", self._popup_menu)

    # --- Card surface ------------------------------------------------------

    def _on_card_resize(self, event):
        self._paint_surface(event.width, event.height)

    def _paint_surface(self, width=None, height=None):
        """Put the right rendered face behind this card.

        Cheap to call: paint.card_surface caches by size and state, so a grid
        of identical cards renders one image between them and every card after
        the first is a dictionary hit.
        """
        if width is None:
            width, height = self.winfo_width(), self.winfo_height()
        if width <= 2 * SHADOW_PAD or height <= 2 * SHADOW_PAD:
            return      # not laid out yet
        key = (width, height, self._hover_active)
        if key == self._surface_key:
            return
        self._surface_key = key
        hovered = self._hover_active
        self._surface = paint.card_surface(
            width, height,
            fill_top=CARD_HOVER_TOP if hovered else CARD_TOP,
            fill_bottom=CARD_HOVER_BOTTOM if hovered else CARD_BOTTOM,
            base=MAIN_BG, radius=RADIUS_CARD, pad=SHADOW_PAD,
            shadow=CARD_SHADOW, blur=CARD_BLUR, drop=CARD_DROP,
            border=ACCENT if hovered else None,
            glow=ACCENT if hovered else None,
        )
        try:
            self.backdrop.configure(image=self._surface)
        except tkinter.TclError:
            pass    # torn down mid-paint
        # The info strip has to follow the face it sits on.
        colour = CARD_HOVER_BOTTOM if hovered else CARD_BOTTOM
        for widget in (self._info_frame, self._text_col):
            if widget.winfo_exists():
                widget.configure(fg_color=colour)

    def _meta_text(self):
        return f"◷ {self.clip.age_human}  ·  {self.clip.size_human}"

    def adopt(self, clip):
        """Re-point this card at the same clip as seen by a later scan.

        Cards outlive the scan that made them (see ClipsView's pool), so the
        Clip object behind one goes stale: a rescan builds fresh ones, and
        indexing settles their recording date. Only the file's own facts are
        redrawn here — the caller checks that it is still the same file, so the
        thumbnail and duration on the card still describe it.
        """
        self.clip = clip
        if self.meta_label.winfo_exists():
            self.meta_label.configure(text=self._meta_text())

    def _action_button(self, parent, glyph, tip, command):
        btn = ctk.CTkButton(
            parent, text=glyph, width=32, height=32,
            corner_radius=RADIUS_CONTROL, fg_color=THUMB_BG,
            hover_color=CARD_HOVER, font=ctk.CTkFont(size=15), command=command,
            bg_color=CARD_BOTTOM,
        )
        btn.pack(side="right", padx=3)
        Tooltip(btn, tip)
        return btn

    # --- Context menu ------------------------------------------------------

    def _popup_menu(self, _event=None):
        """Post the card's context menu, anchored under the ⋮ button.

        Right-click and the ⋮ button both come here, so the menu always appears
        in the same spot on the card rather than wherever the pointer was.
        """
        self._stop_preview()  # a posted menu swallows the pointer events
        if self._menu is not None:
            self._menu.destroy()
        menu = self._menu = tkinter.Menu(
            self, tearoff=0, bg=CARD_BG, fg=TEXT_BRIGHT,
            activebackground=ACCENT, activeforeground="#ffffff",
            activeborderwidth=0, borderwidth=0, relief="flat",
            disabledforeground=TEXT_MUTED,
        )
        # Demo clips have no file behind them, so anything touching disk is out.
        file_state = "normal" if self.clip.path else "disabled"

        menu.add_command(label="Open", command=self._open_editor, state=file_state)
        menu.add_command(
            label="Remove from favorites" if self.favorite else "Add to favorites",
            command=self._toggle_favorite,
        )
        menu.add_command(label="Edit tags…", command=self._edit_tags)
        menu.add_separator()
        menu.add_command(label="Show in file manager", command=self._show_in_files,
                         state=file_state)
        menu.add_command(label="Copy path", command=self._copy_path, state=file_state)
        menu.add_separator()
        menu.add_command(
            label="Delete clip…", command=self._request_delete, state=file_state,
            foreground=DANGER, activebackground=DANGER, activeforeground="#ffffff",
        )

        # Hang the menu down from the button's right edge, so it stays on the
        # card instead of running off the screen on the rightmost column.
        menu.update_idletasks()
        btn = self.more_button
        x = btn.winfo_rootx() + btn.winfo_width() - menu.winfo_reqwidth()
        y = btn.winfo_rooty() + btn.winfo_height() + 4
        # No grab_release() afterwards: tk_popup returns as soon as the menu is
        # posted on X11, and the grab it takes is what dismisses the menu when
        # the user clicks elsewhere. Releasing it here leaves the menu stuck.
        menu.tk_popup(max(0, x), y)

    def _show_in_files(self):
        try:
            subprocess.Popen(["xdg-open", os.path.dirname(self.clip.path)])
        except OSError:
            pass  # no xdg-open on this system; nothing useful to fall back to

    def _copy_path(self):
        self.clipboard_clear()
        self.clipboard_append(self.clip.path)

    def _request_delete(self):
        if self.on_delete is not None and self.clip.path:
            self.on_delete(self)

    def _apply_thumbnail(self, path):
        """Main-thread callback from the thumbnail service."""
        if not path or not self.thumb_label.winfo_exists():
            return
        try:
            with Image.open(path) as frame:
                frame.load()
                self._pil_image = self._dress(frame)
        except OSError:
            return
        self.thumb_label.configure(text="")
        self._render_thumb(self.thumb.winfo_width())

    @staticmethod
    def _dress(frame):
        """Scrim a thumbnail's edges and round its top corners into the card.

        Tk labels are rectangular, so a picture inside a rounded card overhangs
        the curve at the top unless the corners are cut in the image itself.
        The bottom two stay square: the info strip sits under them.
        """
        return paint.round_corners(paint.scrim(frame), radius=26,
                                   base=CARD_TOP, corners=("tl", "tr"))

    def _on_thumb_resize(self, event):
        """Debounce resizes: a maximize fires a burst of <Configure> events, so
        coalesce them into a single update once the size settles."""
        if event.width == self._last_width:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, lambda w=event.width: self._apply_resize(w))

    def _apply_resize(self, width):
        self._resize_job = None
        if width <= 1 or not self.thumb.winfo_exists():
            return
        self._last_width = width
        self.thumb.configure(height=max(1, int(width * THUMB_ASPECT)))
        self._render_thumb(width)

    def _render_thumb(self, width):
        if self._pil_image is None or width <= 1 or not self.thumb_label.winfo_exists():
            return
        size = (width, max(1, int(width * THUMB_ASPECT)))
        try:
            if self._thumb_image is None:
                self._thumb_image = ctk.CTkImage(
                    light_image=self._pil_image, dark_image=self._pil_image, size=size
                )
                self.thumb_label.configure(image=self._thumb_image)
            else:
                self._thumb_image.configure(size=size)
        except tkinter.TclError:
            # Widget torn down mid-resize; safe to ignore.
            pass

    def _toggle_favorite(self):
        self.favorite = not self.favorite
        self.star.configure(
            text="★" if self.favorite else "☆",
            text_color=METER_CLIPS if self.favorite else TEXT_BRIGHT,
        )
        self.library.set_favorite(self.clip.name, self.favorite)

    # --- Tags --------------------------------------------------------------

    def _tag_text(self):
        """The card's tag line: 'GAME · WITH ANNA, BEN'.

        An untagged clip says so rather than showing an empty row: the line is
        what you click to tag it, so it has to stay visible.
        """
        parts = []
        if self.game:
            parts.append(self.game.upper())
        if self.people:
            parts.append("WITH " + ", ".join(self.people).upper())
        text = "  ·  ".join(parts) or "UNTAGGED"
        if len(text) > self.TAG_CHARS:
            text = text[:self.TAG_CHARS - 1].rstrip(" ,·") + "…"
        return text

    def _edit_tags(self, _event=None):
        """Open the tag dialog for this clip and store whatever comes back."""
        self._stop_preview()   # a modal over a playing preview looks broken
        tags = widgets.TagDialog.ask(
            self, clip=self.display_name(), game=self.game, people=self.people,
            games=self.library.known_games(),
            people_pool=self.library.known_people(),
        )
        if tags is None:
            return   # cancelled
        game, people = self.library.set_tags(self.clip.name, *tags)
        self.refresh_tags(game, people)

    def refresh_tags(self, game, people):
        """Adopt tags set here or elsewhere (e.g. inside the editor)."""
        if game == self.game and people == self.people:
            return
        self.game = game
        self.people = list(people)
        if self.tag_label.winfo_exists():
            self.tag_label.configure(text=self._tag_text())

    # --- Title -------------------------------------------------------------

    @staticmethod
    def _elide(text, font, pixels):
        """`text` cut to fit `pixels`, ending in an ellipsis if anything went.

        Measured against the font rather than counted in characters: the cards
        are three to a row whatever the window is, so the room for a name
        changes every time the window or the rail does, and any fixed number of
        characters is right at exactly one width. It was 26, which cut names
        that would have fitted a maximised window and still overflowed a narrow
        one — a Tk label clips silently, so an overflow shows as a name ending
        mid-timestamp with nothing to say it was cut.

        `pixels` of 0 means nothing has been laid out yet, and the full text is
        the right answer until the first <Configure> says otherwise.
        """
        if pixels <= 0 or font.measure(text) <= pixels:
            return text
        cut = len(text) - 1
        while cut > 0 and font.measure(text[:cut] + "…") > pixels:
            cut -= 1
        return text[:cut].rstrip() + "…"

    def display_name(self):
        """The custom title if the clip has one, otherwise its filename."""
        return self.custom_title or self.clip.name

    def _rename(self, text):
        """Commit a title typed into the card. The file is not renamed."""
        # Typing the filename back is the same as having no custom title.
        self.custom_title = "" if text == self.clip.name else text
        self.library.set_title(self.clip.name, self.custom_title)
        return self.display_name()

    def refresh_title(self, title):
        """Adopt a title set elsewhere (e.g. renamed inside the editor)."""
        if title == self.custom_title:
            return
        self.custom_title = title
        self.title_label.set(self.display_name())

    def _open_editor(self, _=None):
        if not self.clip.path:
            return
        self._stop_preview()  # hand the clip over to the player
        self.winfo_toplevel().open_clip(self.clip)

    @staticmethod
    def _duration_text(seconds):
        return f"◷ {core.format_duration(seconds)}" if seconds else "◷ --:--"

    def _apply_duration(self, seconds):
        """Background probe finished; cache it and update the badge."""
        if not seconds or not self.duration_label.winfo_exists():
            return
        self.library.set_duration(self.clip.name, seconds)
        self.duration_label.configure(text=self._duration_text(seconds))

    # --- Hover preview -----------------------------------------------------

    def _on_enter(self, _=None):
        if self._hover_active:
            return
        self._hover_active = True
        # Instant highlight: the hovered face carries an accent border, a
        # lighter gradient and an accent halo bled into the shadow. One cached
        # image swap, undone in _stop_preview.
        self._paint_surface()
        # Wait a beat before doing any work, so skimming over cards is free.
        self._hover_job = self.after(PREVIEW_HOVER_DELAY, self._begin_preview)
        # A watchdog re-checks the pointer, self-healing any missed <Leave>.
        self._watch_job = self.after(HOVER_WATCH_MS, self._watch_pointer)

    def _on_leave(self, _=None):
        # Tk fires <Leave> when the pointer moves onto a child widget too, so
        # defer and check whether the pointer really left the whole card.
        self.after(1, self._check_really_left)

    def _pointer_inside(self):
        """True if the pointer is within this card's screen rectangle. Geometry-
        based, so it doesn't depend on child widgets or reliable <Leave> events."""
        if not self.winfo_exists():
            return False
        px, py = self.winfo_pointerxy()
        x, y = self.winfo_rootx(), self.winfo_rooty()
        return x <= px < x + self.winfo_width() and y <= py < y + self.winfo_height()

    def _check_really_left(self):
        if self.winfo_exists() and not self._pointer_inside():
            self._stop_preview()

    def _watch_pointer(self):
        if not self._hover_active:
            self._watch_job = None
            return
        if not self._pointer_inside():
            self._stop_preview()
            return
        self._watch_job = self.after(HOVER_WATCH_MS, self._watch_pointer)

    def _begin_preview(self):
        self._hover_job = None
        if not self._hover_active or not self.winfo_exists() or not self.clip.path:
            return
        if self._preview_frames is not None:
            self._start_cycling()  # already loaded this session
        else:
            self.thumbs.request_preview(self.clip.path, self._on_preview_ready)

    def _on_preview_ready(self, paths):
        if not self._hover_active or not paths or not self.thumb_label.winfo_exists():
            return
        try:
            frames = []
            for p in paths:
                with Image.open(p) as img:
                    img.load()  # fully read now so file handles don't linger
                    # Same treatment as the still, or the picture would change
                    # shape the moment the preview started.
                    frames.append(self._dress(img))
            self._preview_frames = frames
        except OSError:
            return
        self._start_cycling()

    def _start_cycling(self):
        if not self._hover_active or not self._preview_frames:
            return
        self._preview_index = 0
        self._advance_preview()

    def _advance_preview(self):
        if not self._hover_active or not self.thumb_label.winfo_exists():
            return
        frame = self._preview_frames[self._preview_index]
        width = max(1, self.thumb.winfo_width())
        size = (width, max(1, int(width * THUMB_ASPECT)))
        try:
            if self._preview_ctk is None:
                self._preview_ctk = ctk.CTkImage(
                    light_image=frame, dark_image=frame, size=size
                )
                self.thumb_label.configure(image=self._preview_ctk, text="")
            else:
                self._preview_ctk.configure(light_image=frame, dark_image=frame, size=size)
        except tkinter.TclError:
            return
        self._preview_index = (self._preview_index + 1) % len(self._preview_frames)
        self._preview_job = self.after(PREVIEW_FRAME_MS, self._advance_preview)

    def _stop_preview(self):
        self._hover_active = False
        if self.winfo_exists():
            self._paint_surface()   # back to the resting face
        for attr in ("_hover_job", "_preview_job", "_watch_job"):
            job = getattr(self, attr)
            if job is not None:
                self.after_cancel(job)
                setattr(self, attr, None)
        # Restore the static thumbnail (or the play glyph if none yet).
        if self.thumb_label.winfo_exists():
            if self._thumb_image is not None:
                self.thumb_label.configure(image=self._thumb_image, text="")
            else:
                self.thumb_label.configure(image="", text="▶")
        # Release decoded frames so hovering many cards doesn't accrue memory;
        # the disk cache makes a re-hover fast to reload.
        self._preview_frames = None
        self._preview_ctk = None
        self._preview_index = 0


# --- Sort control ----------------------------------------------------------
class SortBar(ctk.CTkFrame):
    """Sort-by buttons for the overview: pick a field, click again to flip it.

    Only the active button carries an arrow, so the one arrow on screen always
    describes the order the grid is actually in: ↓ is descending (newest first,
    or Z→A) and ↑ is ascending.
    """

    # key -> (label, direction it starts in when first selected). "Date" is the
    # recording date the library holds for a clip, not any date on disk; "Game"
    # is its tag, and untagged clips stay at the end whichever way it points.
    OPTIONS: ClassVar[dict[str, tuple[str, bool]]] = {
        "date": ("Date", True),   # newest first
        "game": ("Game", False),  # A→Z
    }

    def __init__(self, master, on_change, key="date"):
        # A recessed track with the active option raised out of it, rather than
        # two loose buttons: the pair is one control — a single choice with a
        # direction — and reads better as one shape.
        super().__init__(master, fg_color=SEG_TRACK_BG,
                         corner_radius=RADIUS_CONTROL)
        self.on_change = on_change
        self.key = key
        self.descending = self.OPTIONS[key][1]

        self.buttons = {}
        for option, (label, _) in self.OPTIONS.items():
            button = ctk.CTkButton(
                self, text=label, width=96, height=28, anchor="center",
                corner_radius=RADIUS_SMALL, border_width=1,
                font=ctk.CTkFont(size=12),
                command=lambda o=option: self._select(o),
            )
            button.pack(side="left", padx=3, pady=3)
            self.buttons[option] = button
        self._paint()

    def _select(self, option):
        """Switch to `option`, or flip the direction if it is already active."""
        if option == self.key:
            self.descending = not self.descending
        else:
            self.key = option
            self.descending = self.OPTIONS[option][1]
        self._paint()
        self.on_change(self.key, self.descending)

    def _paint(self):
        arrow = "↓" if self.descending else "↑"
        for option, button in self.buttons.items():
            label = self.OPTIONS[option][0]
            active = option == self.key
            # The active button is the primary control on this row, so it takes
            # the lit edge; the others keep a border of their own fill, which
            # holds the row's height steady as the selection moves.
            button.configure(
                text=f"{label} {arrow}" if active else label,
                fg_color=ACCENT if active else "transparent",
                hover_color=ACCENT_HOVER if active else SEG_TRACK_HOVER,
                border_color=(PRIMARY_BUTTON["border_color"] if active
                              else SEG_TRACK_BG),
                text_color=TEXT_BRIGHT if active else TEXT_MUTED,
            )


# --- Clips overview view ---------------------------------------------------
class ClipsView(ctk.CTkFrame):
    COLUMNS = 3
    # Rebuilding the grid on every keystroke would rebuild it four times for
    # "apex"; this waits for the typing to stop first.
    SEARCH_DEBOUNCE_MS = 180

    def __init__(self, master, config, thumbs, library, on_storage_changed=None):
        super().__init__(master, fg_color="transparent")
        self.config_data = config
        self.thumbs = thumbs
        self.library = library
        # Called when the clips folder gained or lost bytes, so the gauge in
        # the top strip can follow a delete or a trim without a full rescan.
        self.on_storage_changed = on_storage_changed
        # Grid order, held for the session and applied on every reload.
        self._sort_key = "date"
        self._sort_desc = True

        # No page heading: the rail already says which app this is, and a
        # second "Vertex" under it would cost a row of grid for nothing.

        # Search + sort row. Typing filters the clips already scanned, so it
        # never touches the disk.
        #
        # Deliberately no textvariable: CTkEntry only shows its placeholder when
        # one isn't bound, and the placeholder is what says which fields are
        # searched. Keystrokes are read off the widget instead.
        # The header says which slice of the library is on screen and how big
        # it is, then gives the rest of the row to sorting and rescanning. The
        # search box is not here any more — it belongs to the rail, along with
        # everything else that decides *which* clips these are.
        # This view's half of the window's lit band, and the header row that
        # sits on its plateau — PAGE_GLOW rather than transparent, or the row
        # would paint the page's colour over the light (see widgets.attach_glow).
        widgets.attach_glow(self, top=PAGE_GLOW, bottom=MAIN_BG,
                            plateau=GLOW_PLATEAU, height=GLOW_H,
                            offset=CONTENT_PAD_TOP)
        subhead = self.subhead = ctk.CTkFrame(self, fg_color=PAGE_GLOW,
                                              corner_radius=0, height=HEADER_H)
        subhead.pack(fill="x", pady=(0, 14))
        subhead.pack_propagate(False)
        self.heading = ctk.CTkLabel(
            subhead, text="All clips", anchor="w",
            font=ctk.CTkFont(size=21, weight="bold"),
        )
        self.heading.pack(side="left")
        self.count_label = ctk.CTkLabel(
            subhead, text="", anchor="w", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        )
        self.count_label.pack(side="left", padx=(12, 0), pady=(4, 0))
        self.refresh_button = ctk.CTkButton(
            subhead, text="Refresh", width=90, height=34,
            corner_radius=RADIUS_CONTROL, command=self.reload, **PRIMARY_BUTTON,
        )
        self.refresh_button.pack(side="right")
        self.sort_bar = SortBar(subhead, self._set_sort, key=self._sort_key)
        self.sort_bar.pack(side="right", padx=(0, 12))

        # Refresh indicator: shown only while a reload is running, and kept up
        # until the thumbnails it set off are made too — a grid full of empty
        # cards is not a finished refresh. Packed on demand, above the grid.
        self.progress_row = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_row, height=6, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x")
        self.progress_label = ctk.CTkLabel(
            self.progress_row, text="", anchor="w", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11))
        self.progress_label.pack(anchor="w", pady=(3, 0))

        self.grid_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.grid_area.pack(fill="both", expand=True)
        make_scroll_pixel_precise(self.grid_area)
        for c in range(self.COLUMNS):
            self.grid_area.grid_columnconfigure(c, weight=1, uniform="clips")

        self.status = ctk.CTkLabel(self, text="", text_color=TEXT_MUTED, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        # Grid state — see the "Grid building" section below for what carries
        # what. The token lets a new rebuild cancel a fill still running from
        # the previous one.
        self._build_token = 0
        self._order = []          # every clip the grid shows, in grid order
        self._placed = {}         # slot index -> the card sitting in that slot
        self._pool = {}           # {filename: ClipCard} — built, on grid or not
        self._row_height = 0      # measured card height, including its padding
        self._rows_reserved = 0   # rows currently held open in the grid
        self._page_first = 0      # library row the frame's first row holds
        self._page_rows = 0       # rows the frame holds at once
        self._spacer = None       # canvas item that gives the grid its full height
        self._fill_job = None     # pending continuation of a fill (after id)
        self._scroll_job = None   # viewport poller (after id)
        self._announce = False    # this fill finishes a reload, so report it
        self._warm_pending = False  # a scan happened; warm the caches after it
        self._fallback_status = ""
        self._status_job = None
        self._scroll_px = 0.0
        self._stale = False       # set when the clip folder changed behind us
        self._storage_job = None  # pending gauge refresh (after id)
        # Everything the last scan found, before the search box narrowed it, so
        # typing and clearing the box never costs a rescan.
        self._all_clips = []
        self._tags = {}           # {filename: (game, [people])} from the library
        self._titles = {}         # {filename: title} likewise
        self._search_text = ""    # the query the grid on screen was filtered by
        # Which slice of the library the rail has asked for: (kind, value),
        # where kind is None for everything, "favorite", "game" or "person".
        # It narrows the same list the search box narrows, one after the other.
        self._facet = (None, None)
        self._favorites = set()
        # Refresh indicator state.
        self._progress_job = None    # pending "processing" poll or hide (after id)
        self._process_peak = 0       # most thumbnail jobs seen outstanding
        # The indicator follows scans, not layouts, so it has a token of its own:
        # re-filtering or re-sorting mid-refresh must not strand it half-shown
        # with the Refresh button still disabled behind it.
        self._refresh_token = 0
        self.reload()
        self._watch_viewport()

    def reload(self):
        # Up before the scan, not after: scanning and indexing run on the Tk
        # thread, so this is the last chance to paint anything until they are
        # done — and on a big folder that is exactly the wait worth covering.
        self._begin_refresh()
        clips = self._load_clips()
        # Before sorting: indexing is what settles each clip's date, and the
        # date is what "Date Created" orders the grid by.
        self._index(clips)
        self._all_clips = clips
        self._load_tags()
        # Only the visible cards get built, so nothing else asks ffmpeg for the
        # rest of the library's frames any more — this scan does (see _warm_caches).
        self._warm_pending = True
        self._rebuild(announce=True)

    def _load_tags(self):
        """Cache the library's tags and titles — what search and Game sort read."""
        try:
            self._tags = self.library.tags()
            self._titles = self.library.titles()
            self._favorites = self.library.favorites()
        except sqlite3.Error:
            # A locked or missing DB only costs tags: the grid still lists the
            # files, search still matches names, and Game sort sees everything
            # as untagged rather than failing the reload. The rail's lists come
            # from the same place, so they empty out with it.
            self._tags, self._titles, self._favorites = {}, {}, set()

    def _rebuild(self, announce=False):
        """Re-filter, re-sort and re-lay the grid from the last scan.

        `announce` marks this as the end of a reload, so the refresh indicator
        is carried through to "up to date" once the grid is on screen. A
        re-filter or a re-sort passes it up: nothing was rescanned, so there is
        no refresh to report.
        """
        clips = self._apply_facet(self._all_clips)
        clips = core.filter_clips(clips, self.search_query(),
                                  self._tags, self._titles)
        games = {name: game for name, (game, _people) in self._tags.items()}
        self._order = core.sort_clips(clips, self._sort_key, self._sort_desc,
                                      games=games)

        # Supersede any fill still running from the previous rebuild.
        self._build_token += 1
        self._cancel_fill_job()
        # Carried, not overwritten: typing in the search box mid-reload
        # supersedes the fill that would have reported it, and the indicator has
        # to come down on whichever fill ends up finishing.
        self._announce = announce or self._announce

        # Take every card off the grid — the ones this layout still wants go
        # straight back on below, in their new slots.
        for card in self._placed.values():
            card.grid_forget()
        self._placed = {}
        # A card whose clip has left the folder has nothing to come back for.
        # Everything else stays pooled, however the search box narrowed it.
        live = {clip.name for clip in self._all_clips}
        for name in [name for name in self._pool if name not in live]:
            self._pool.pop(name).destroy()

        self._reserve_rows()
        self._update_count()
        try:
            # Settle the new scroll region before reading it: which slots are on
            # screen is worked out from it, and a grid that just changed length
            # still reports the old one until Tk has laid it out.
            self.grid_area.update_idletasks()
        except tkinter.TclError:
            pass   # the view is going away mid-rebuild
        self._fill_viewport(self._build_token)

    def _apply_facet(self, clips):
        """Narrow `clips` to the rail's current selection.

        Deliberately before the text search rather than folded into it: the two
        are different questions — the rail asks which shelf, the box asks what
        is on it — and doing them in this order means clearing the box leaves
        you on the shelf you picked.
        """
        kind, value = self._facet
        if kind is None:
            return clips
        if kind == "favorite":
            return [c for c in clips if c.name in self._favorites]
        if kind == "game":
            return [c for c in clips
                    if self._tags.get(c.name, ("", []))[0] == value]
        if kind == "person":
            folded = value.casefold()
            return [c for c in clips
                    if any(p.casefold() == folded
                           for p in self._tags.get(c.name, ("", []))[1])]
        return clips

    def _storage_changed(self):
        """Ask for the top strip's gauge to be re-read, once the work settles.

        Deferred rather than immediate: a delete re-reads the folder's size, so
        doing it inline would put a directory walk in the middle of the click.
        """
        if self.on_storage_changed is None:
            return
        if self._storage_job is not None:
            self.after_cancel(self._storage_job)
        self._storage_job = self.after(120, self._run_storage_changed)

    def _run_storage_changed(self):
        self._storage_job = None
        if self.on_storage_changed is not None:
            self.on_storage_changed()

    def search_query(self):
        """The query the grid is filtered by. Owned by the rail, held here."""
        return self._search_text

    def set_query(self, text):
        """Filter to `text`. Called by the rail when its search box settles."""
        if text == self._search_text:
            return
        self._search_text = text
        self._run_search()

    def set_facet(self, facet):
        """Narrow to one game, one person, favourites, or everything."""
        if facet == self._facet:
            return
        self._facet = facet
        self.scroll_to_top()
        self._rebuild()

    def facet_title(self):
        """What the workspace heading calls the current slice."""
        kind, value = self._facet
        if kind == "favorite":
            return "Favorites"
        if kind == "person":
            return value
        if kind == "game":
            return value or "Untagged"
        return "All clips"

    def tags(self):
        return self._tags

    def favorites(self):
        return self._favorites

    def clip_count(self):
        return len(self._all_clips)

    def _run_search(self):
        # Back to the top first, for the same reason a re-sort goes back: the
        # results are a new list, and the old offset points into a grid that no
        # longer exists. Also keeps the rebuild building the cards that will be
        # on screen rather than the ones under the previous scroll position.
        self.scroll_to_top()
        self._rebuild()

    # --- Refresh indicator -------------------------------------------------
    #
    # One bar covers the whole refresh, so it only ever moves forward: the scan
    # opens it, building the cards fills it to BUILD_SHARE, and the thumbnails
    # those cards asked for carry it the rest of the way.

    SCAN_SHARE = 0.05
    BUILD_SHARE = 0.70

    def _begin_refresh(self):
        """Put the indicator up and force it on screen before the work starts."""
        self._cancel_progress_job()
        self._refresh_token += 1
        self._process_peak = 0
        self.refresh_button.configure(state="disabled", text="Refreshing…")
        if not self.progress_row.winfo_manager():
            # Anchored after the sort row rather than before the grid: a
            # CTkScrollableFrame packs an inner widget, so it can't be a
            # `before=` reference.
            self.progress_row.pack(fill="x", pady=(0, 8), after=self.subhead)
        self._show_progress(0.0, "Scanning the clips folder…")
        try:
            self.update_idletasks()   # paint now; the scan blocks the loop next
        except tkinter.TclError:
            pass   # the view is going away mid-refresh

    def _show_progress(self, fraction, text, color=TEXT_MUTED):
        if not self.progress_row.winfo_exists():
            return
        self.progress_bar.set(max(0.0, min(1.0, fraction)))
        self.progress_label.configure(text=text, text_color=color)

    def _build_progress(self, built, total):
        share = built / total if total else 1.0
        self._show_progress(
            self.SCAN_SHARE + (self.BUILD_SHARE - self.SCAN_SHARE) * share,
            f"Building the grid — {built} of {total}")

    def _cards_built(self, token):
        """The grid is on screen — now wait on the frames it set ffmpeg making."""
        if token != self._refresh_token:
            return
        self._build_progress(1, 1)
        self._await_processing(token)

    def _await_processing(self, token):
        """Hold the indicator until the thumbnail pool has caught up.

        Cards go up before their thumbnails exist, so the grid looking complete
        is not the same as the refresh being over — this is the part of the
        wait a user actually watches, and it ends when ffmpeg runs dry.
        """
        self._progress_job = None
        if token != self._refresh_token or not self.progress_row.winfo_exists():
            return
        outstanding = getattr(self.thumbs, "pending", 0)
        if not outstanding:
            self._finish_refresh(token)
            return
        self._process_peak = max(self._process_peak, outstanding)
        done = self._process_peak - outstanding
        self._show_progress(
            self.BUILD_SHARE + (1 - self.BUILD_SHARE) * (done / self._process_peak),
            f"Processing thumbnails — {done} of {self._process_peak}")
        self._progress_job = self.after(200, self._await_processing, token)

    def _finish_refresh(self, token):
        """Say it plainly, then take the indicator away."""
        count = len(self._order)
        self._show_progress(1.0, f"Up to date — {plural(count, 'clip')} ready", ACCENT)
        self.refresh_button.configure(state="normal", text="Refresh")
        self._progress_job = self.after(1400, self._hide_progress, token)

    def _hide_progress(self, token):
        self._progress_job = None
        if token == self._refresh_token and self.progress_row.winfo_exists():
            self.progress_row.pack_forget()

    def _cancel_progress_job(self):
        if self._progress_job is not None:
            try:
                self.after_cancel(self._progress_job)
            except tkinter.TclError:
                pass   # the view (or the app) is already going away
            self._progress_job = None

    def _index(self, clips):
        """Settle each clip's game and date in the library, before the cards read it.

        Both are worked out once, from the clip's file name, and kept — from
        then on the library is what the app goes by, and the name is only ever
        consulted for a clip it has not seen before.

        A clip whose name carries no timestamp is dated from its file instead,
        and that date is stored too, so the library ends up holding a date for
        every clip. That is the point of storing it: dates on disk are rewritten
        by copying a clip between folders or trimming it in place, and a grid
        sorted by date should not reshuffle when a file is touched.

        Demo clips are skipped: they have no file behind them, so nothing they
        are called should reach the library.
        """
        real = [clip for clip in clips if clip.path]
        if not real:
            return
        try:
            tagged = self.library.autotag_games([clip.name for clip in real])
            self.library.store_recorded(
                {clip.name: clip.recorded or clip.created for clip in real})
            dates = self.library.recorded_dates()
        except sqlite3.Error:
            return   # a locked or missing DB just means indexing waits a scan
        for clip in real:
            clip.recorded = dates.get(clip.name) or clip.recorded
        if tagged:
            self._flash_status(f"Tagged {plural(len(tagged), 'clip')} from their file names")

    def _set_sort(self, key, descending):
        """Re-order the grid after the sort bar was clicked.

        Re-lays the clips already scanned rather than rescanning the folder:
        the order changed, not what is in it.
        """
        self._sort_key = key
        self._sort_desc = descending
        # Back to the top first, so the rebuild builds the cards that will be on
        # screen rather than the ones at the old scroll position.
        self.scroll_to_top()
        self._rebuild()

    # --- Grid building -----------------------------------------------------
    #
    # A clip card is expensive: CustomTkinter draws each widget's rounded edges
    # as anti-aliased shapes on its own canvas, which puts one card at ~15 ms of
    # Tcl round-trips however fast the disk and the database are. Building a
    # card per clip therefore costs seconds on a library of a few hundred, all
    # of it spent on cards below the fold. Two things keep that off the clock:
    #
    #   * Only the slots around the viewport are ever built. The rest of the
    #     grid is held open by reserved row heights, so the scrollbar still
    #     measures the whole library and scrolling lands where it should; the
    #     cards for those rows are made as they come into view.
    #   * Cards are pooled by file name and kept across rebuilds. Narrowing the
    #     search, widening it again, or re-sorting re-lays the cards that exist
    #     rather than destroying and remaking them — which is what made leaving
    #     the search box cost as much as a cold start.
    #
    # The frame those rows live in is not the whole grid, either. X11 cannot
    # represent a window taller than 32767 px and simply stops drawing past it,
    # so a library of a few hundred clips — 600 of them want some 69000 px —
    # would freeze the last visible row on screen while the scrollbar carried on
    # down over nothing. The frame therefore holds only a page of rows, at most
    # MAX_FRAME_PX tall, and slides along a scroll region that spans the whole
    # library: `_page_first` says which library row its first row is showing.
    # A library small enough to fit keeps one page at row 0 and never slides.

    # Rows of cards built beyond the visible ones, so an ordinary scroll lands
    # on finished cards instead of on the space reserved for them.
    BUFFER_ROWS = 3
    # Wall-clock one fill may spend before yielding to the event loop, so a big
    # jump down the grid paints what it has rather than freezing on the rest.
    BUILD_BUDGET_MS = 25
    # Stand-in row height until a real card has been measured.
    EST_ROW_HEIGHT = 300
    # Tallest the card frame may get. X11 windows top out at 32767 px; this
    # leaves room for the cards to grow with the window before the next poll.
    MAX_FRAME_PX = 20000
    # Space _place_card puts around a card, which its row has to hold too.
    CARD_PADY = 1
    # How often the viewport is re-read. Scrolling arrives from the app's wheel
    # handler, CustomTkinter's own binding and the scrollbar alike, so the
    # position is polled rather than bound — one check costs a fraction of a
    # card, and it picks up window resizes in the same pass.
    VIEWPORT_POLL_MS = 120

    @property
    def cards(self):
        """The cards on the grid right now, in grid order.

        Only the built slots, so this is a screenful and its buffer rather than
        the whole library — anything that has to reach every card the view has
        ever made wants `self._pool` instead.
        """
        return [self._placed[slot] for slot in sorted(self._placed)]

    def _rows_needed(self):
        return -(-len(self._order) // self.COLUMNS)   # ceil division

    def _page_capacity(self):
        """Rows the frame may hold at once, bounded by what X11 can draw.

        Kept well under the 32767 px ceiling: the cards grow with the window, so
        there has to be room for a resize to land between two viewport polls
        without the frame crossing the limit in the meantime.
        """
        height = self._row_height or self.EST_ROW_HEIGHT
        return max(1, self.MAX_FRAME_PX // height)

    def _reserve_rows(self):
        """Hold the page's rows open, and tell the canvas how tall the grid is.

        Two different heights, and they are not the same once a library is big:
        the frame is a page of rows, while the scroll region spans every row
        there is so the scrollbar keeps measuring the library rather than the
        part of it currently built.
        """
        rows = self._rows_needed()
        height = self._row_height or self.EST_ROW_HEIGHT
        self._page_rows = min(rows, self._page_capacity())
        for row in range(self._page_rows):
            self.grid_area.grid_rowconfigure(row, minsize=height)
        # Let go of the rows a shorter page no longer needs, or the frame would
        # keep the height of the tallest one ever shown.
        for row in range(self._page_rows, self._rows_reserved):
            self.grid_area.grid_rowconfigure(row, minsize=0)
        self._rows_reserved = self._page_rows
        self._resize_spacer(rows * height)
        self._move_page(self._page_first)   # clamp it into the new grid

    def _resize_spacer(self, total_px):
        """Stretch the canvas's invisible spacer to the whole grid's height.

        The scroll region follows the canvas's bounding box, which the frame no
        longer fills on its own — this item is what keeps the scrollbar, the
        wheel handler and the saved scroll offset all measuring the library.
        Drawn as a rectangle with neither fill nor outline: nothing appears, but
        the canvas still counts it.
        """
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        if self._spacer is None:
            self._spacer = canvas.create_rectangle(0, 0, 0, 0, outline="", fill="")
        canvas.coords(self._spacer, 0, 0, 0, max(total_px, 1))
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _page_holds(self, slot):
        row = slot // self.COLUMNS
        return self._page_first <= row < self._page_first + self._page_rows

    def _move_page(self, first_row):
        """Slide the frame so its first row shows library row `first_row`.

        The frame moves up the canvas by exactly as much as the cards inside it
        move down their own rows, so nothing shifts on screen; both happen
        before the next redraw, so the slide is invisible.
        """
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        window = getattr(self.grid_area, "_create_window_id", None)
        if canvas is None or window is None or not canvas.winfo_exists():
            return
        rows = self._rows_needed()
        first_row = max(0, min(first_row, rows - self._page_rows))
        height = self._row_height or self.EST_ROW_HEIGHT
        moved = first_row != self._page_first
        self._page_first = first_row
        canvas.coords(window, 0, first_row * height)
        if not moved:
            return
        for slot, card in list(self._placed.items()):
            if self._page_holds(slot):
                self._place_card(card, slot)   # same clip, new row in the page
            else:
                card.grid_forget()             # off the page; it stays pooled
                del self._placed[slot]

    def _ensure_page(self, first_slot, last_slot):
        """Slide the page if the slots about to be built fall outside it."""
        if not self._page_rows:
            return
        if self._page_holds(first_slot) and self._page_holds(last_slot):
            return
        # Centred on what is being built, so scrolling on in either direction
        # has most of a page to cross before it has to slide again.
        middle = (first_slot // self.COLUMNS + last_slot // self.COLUMNS) // 2
        self._move_page(middle - self._page_rows // 2)

    def _sync_row_height(self):
        """Match the reserved rows to what a real card actually measures.

        The height follows the window's width — a card's thumbnail is 16:9 of
        it — so this is re-checked with the viewport rather than worked out once.
        """
        card = next(iter(self._placed.values()), None)
        if card is None or not card.winfo_exists():
            return
        height = card.winfo_height()
        if height <= 1:
            return   # not laid out yet; EST_ROW_HEIGHT stands until it is
        height += 2 * self.CARD_PADY
        if height == self._row_height:
            return
        self._row_height = height
        self._reserve_rows()

    def _visible_slots(self):
        """The slots worth having built: what is on screen, plus BUFFER_ROWS
        either side of it."""
        total = len(self._order)
        if not total:
            return range(0)
        rows = self._rows_needed()
        height = self._row_height or self.EST_ROW_HEIGHT
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        first_row, last_row = 0, 0
        if canvas is not None and canvas.winfo_exists():
            bbox = canvas.bbox("all")
            span = (bbox[3] - bbox[1]) if bbox else 0
            top = canvas.yview()[0] * span
            # Before the view is mapped the canvas reports a height of 1, which
            # would leave the first screen a single row short; the poller comes
            # back with the real height a moment later either way.
            view = max(canvas.winfo_height(), 1)
            first_row = int(top // height)
            last_row = int((top + view) // height)
        first_row = max(0, first_row - self.BUFFER_ROWS)
        last_row = min(rows - 1, last_row + self.BUFFER_ROWS)
        return range(first_row * self.COLUMNS,
                     min(total, (last_row + 1) * self.COLUMNS))

    def _fill_viewport(self, token):
        """Build and place whatever the viewport wants and does not have yet."""
        self._fill_job = None
        if token != self._build_token or not self.grid_area.winfo_exists():
            return  # superseded by a newer rebuild, or the view was closed
        # First, in case the window was resized: the rows have to be the height
        # they will hold before working out which of them are on screen.
        self._sync_row_height()
        deadline = time.perf_counter() + self.BUILD_BUDGET_MS / 1000
        wanted = self._visible_slots()
        if wanted:
            # Bring the page under the rows about to be built, or they would
            # have nowhere on the frame to go.
            self._ensure_page(wanted[0], wanted[-1])
        for done, slot in enumerate(wanted):
            if slot in self._placed or not self._page_holds(slot):
                continue
            self._build_slot(slot)
            if time.perf_counter() >= deadline:
                # More than fits in one tick — let the loop paint what is there
                # before carrying on with the rest.
                if self._announce:
                    # Only a reload's own fill drives the indicator; scrolling
                    # into fresh rows is not a refresh and must not narrate as one.
                    self._build_progress(done + 1, len(wanted))
                self._fill_job = self.after(1, self._fill_viewport, token)
                return
        self._fill_done()

    def _fill_done(self):
        """The viewport is covered — report the reload this fill finished, if any."""
        if not self._announce:
            return
        self._announce = False
        if self._warm_pending:
            self._warm_pending = False
            self._warm_caches()
        self._cards_built(self._refresh_token)

    def _build_slot(self, slot):
        """Put a card in `slot`, reusing the pooled one for its clip if there is
        one to reuse."""
        clip = self._order[slot]
        card = self._pool.get(clip.name)
        if card is not None and not self._same_file(card.clip, clip):
            # The file behind it changed — a trim written over it, say — so its
            # thumbnail and duration describe a recording that is gone.
            card.destroy()
            card = None
        if card is None:
            card = ClipCard(self.grid_area, clip, self.thumbs, self.library,
                            on_delete=self.delete_clip)
            self._pool[clip.name] = card
        else:
            # A pooled card was built against an older scan and may have sat out
            # an edit made in the player, so it catches up before going back up.
            card.adopt(clip)
            card.refresh_title(self._titles.get(clip.name, ""))
            card.refresh_tags(*self._tags.get(clip.name, ("", [])))
        self._place_card(card, slot)
        self._placed[slot] = card

    @staticmethod
    def _same_file(before, after):
        """True if two scans' Clips are the same file, unchanged."""
        return (before.path == after.path
                and before.mtime == after.mtime
                and before.size_bytes == after.size_bytes)

    def _place_card(self, card, slot):
        # Rows are relative to the page, not to the library, so a card's row
        # changes whenever the page slides under it.
        card.grid(
            row=slot // self.COLUMNS - self._page_first,
            column=slot % self.COLUMNS,
            padx=1, pady=self.CARD_PADY, sticky="nsew",
        )

    def _watch_viewport(self):
        """Keep the built slots in step with what is on screen."""
        self._scroll_job = None
        if not self.winfo_exists():
            return
        # Skipped while hidden behind the player or Settings: nothing is being
        # scrolled, and the canvas would report the size it had on the way out.
        if self._fill_job is None and self.winfo_ismapped():
            self._fill_viewport(self._build_token)
        self._scroll_job = self.after(self.VIEWPORT_POLL_MS, self._watch_viewport)

    def _cancel_fill_job(self):
        if self._fill_job is not None:
            try:
                self.after_cancel(self._fill_job)
            except tkinter.TclError:
                pass   # the view (or the app) is already going away
            self._fill_job = None

    def _warm_caches(self):
        """Make the frames and durations the unbuilt cards will want.

        Every card used to ask for its own thumbnail as it was built, so a scan
        warmed the whole library's worth of them. Only a screenful of cards is
        built now, so the rest is asked for here instead — same background pool,
        same cache, so scrolling down finds the frames already made rather than
        waiting on ffmpeg a row at a time. Clips that already have a card are
        skipped: it asked for its own.
        """
        try:
            probed = self.library.probed()
        except sqlite3.Error:
            probed = set()   # a locked DB just means some durations wait a scan

        def store(name):
            def keep(seconds):
                if seconds:
                    try:
                        self.library.set_duration(name, seconds)
                    except sqlite3.Error:
                        pass   # the badge fills in on a later scan instead
            return keep

        for clip in self._all_clips:
            if not clip.path or clip.name in self._pool:
                continue
            self.thumbs.request(clip.path, lambda _path: None)
            if clip.name not in probed:
                self.thumbs.request_duration(clip.path, store(clip.name))

    def _update_count(self):
        """Name the slice on screen, and say how much of the library it is."""
        total = len(self._order)
        self.heading.configure(text=self.facet_title())
        size = core.format_size(sum(clip.size_bytes for clip in self._order))
        if total == len(self._all_clips):
            self.count_label.configure(text=f"{plural(total, 'clip')}  ·  {size}")
        else:
            # Say what was filtered out, so an empty-looking grid reads as a
            # narrow search rather than as a folder that lost its clips.
            self.count_label.configure(
                text=f"{total} of {len(self._all_clips)} clips  ·  {size}")

    def refresh(self):
        """Catch up with whatever changed while the grid was hidden."""
        if self._stale:
            self._stale = False
            self.reload()      # rebuilds the cards, labels included
        else:
            self.refresh_labels()

    def mark_stale(self):
        """Note that the clip folder itself changed, so the grid must rescan."""
        self._stale = True

    def refresh_labels(self):
        """Pick up titles and tags changed while the grid was behind the editor."""
        try:
            titles = self.library.titles()
            tags = self.library.tags()
        except sqlite3.Error:
            return   # a locked or missing DB just means stale labels
        # Held for search and the Game sort as well as the cards, so a tag typed
        # in the editor is searchable the moment the grid comes back.
        self._titles, self._tags = titles, tags
        # The whole pool, not just the cards on the grid: a card the search box
        # is currently hiding has to be right for when it comes back.
        for name, card in self._pool.items():
            card.refresh_title(titles.get(name, ""))
            card.refresh_tags(*tags.get(name, ("", [])))

    # --- Deletion ----------------------------------------------------------

    def delete_clip(self, card):
        """Confirm, then delete the card's clip from disk and drop its card."""
        if card.clip.path and confirm_delete_clip(self, card.clip):
            self.remove_clip(card.clip)

    def remove_clip(self, clip):
        """Delete `clip` from disk and the library, and drop it from the grid.

        Confirming is the caller's job (see confirm_delete_clip), so the editor
        can ask while it is still open and delete once it has closed.
        """
        # Cached thumbnails are keyed on the file's mtime and size, so they have
        # to go before the file does or the entries become unreachable.
        self.thumbs.discard(clip.path)
        try:
            trashed = core.delete_clip(clip.path)
        except OSError as err:
            self._flash_status(f"Could not delete {clip.name} — {err}", error=True)
            return False

        self.library.delete_clip(clip.name)
        # Out of the scan cache too, or clearing the search box would bring the
        # deleted clip back on the next re-filter.
        self._all_clips = [c for c in self._all_clips if c.name != clip.name]
        # Re-lay rather than close the gap by hand: every card after the deleted
        # one moves up a slot, and re-laying reuses the ones that already exist.
        # A clip whose card was never built simply has no slot to give up.
        self._rebuild()
        self._storage_changed()
        verb = "Moved to Trash" if trashed else "Deleted"
        self._flash_status(f"{verb}: {clip.name}")
        return True

    # --- Trim --------------------------------------------------------------

    def replace_clip(self, clip, trimmed_path):
        """Swap `clip`'s file for the trimmed version staged at `trimmed_path`.

        The trimmed file takes the original's name, so the clip keeps its title,
        favorite and mixer settings; only the trim markers and cached duration
        are dropped, since they describe the file that just went to the Trash.

        The caller must have left the editor first — mpv holds the file open.
        """
        self.thumbs.discard(clip.path)   # cached on the old file's mtime/size
        try:
            trashed = core.delete_clip(clip.path)
        except OSError as err:
            self._flash_status(f"Could not replace {clip.name} — {err}", error=True)
            return False
        try:
            os.replace(trimmed_path, clip.path)
        except OSError as err:
            # The original is already in the Trash, so keep the trimmed file
            # under a name of its own rather than losing the recording.
            salvaged = self._salvage(trimmed_path, clip)
            self.reload()
            self._flash_status(
                f"Trimmed clip saved as {salvaged} — could not take over the "
                f"original name: {err}", error=True)
            return False

        self.library.clear_trim(clip.name)
        self._stale = False
        # Rescan first: reloading resets the status line, so the message has to
        # be flashed after it or it is wiped straight away.
        self.reload()
        where = "moved to Trash" if trashed else "deleted"
        self._flash_status(f"Trimmed {clip.name} · original {where}")
        return True

    def _salvage(self, trimmed_path, clip):
        """Give a staged trim a visible name after a failed swap."""
        stem = os.path.splitext(clip.name)[0]
        target = os.path.join(os.path.dirname(clip.path), f"{stem} (trimmed).mp4")
        try:
            os.replace(trimmed_path, target)
        except OSError:
            return os.path.basename(trimmed_path)
        return os.path.basename(target)

    # --- Scroll position ---------------------------------------------------
    # The view is hidden rather than destroyed while the editor is open, so the
    # canvas keeps its own yview. These save/restore around that anyway: the
    # scroll region changes when a clip is deleted, which would otherwise shift
    # the view, and an unmapped canvas can report a stale height.

    def save_scroll(self):
        """Remember the scroll offset in pixels, not as a fraction."""
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        bbox = canvas.bbox("all") if canvas is not None else None
        if bbox:
            self._scroll_px = canvas.yview()[0] * (bbox[3] - bbox[1])

    def restore_scroll(self):
        # Wait for the re-map to settle, or the scroll region is still stale.
        self.after_idle(self._apply_scroll)

    def scroll_to_top(self):
        """Jump back to the first card — used when the order changes under us."""
        self._scroll_px = 0.0
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        if canvas is not None and canvas.winfo_exists():
            canvas.yview_moveto(0.0)

    def _apply_scroll(self):
        canvas = getattr(self.grid_area, "_parent_canvas", None)
        if canvas is None or not self._scroll_px or not canvas.winfo_exists():
            return
        bbox = canvas.bbox("all")
        height = (bbox[3] - bbox[1]) if bbox else 0
        if height > 0:
            canvas.yview_moveto(min(1.0, self._scroll_px / height))

    # --- Status line -------------------------------------------------------
    #
    # Storage used to live here as well, but the top strip now carries it, and
    # two readings of the same disk in one window only invite comparing them.
    # What is left is transient messages, over a note about demo clips when
    # that is the reason the grid is showing what it is.

    def _restore_status(self):
        self._cancel_status_job()
        if self.status.winfo_exists():
            self.status.configure(text=self._fallback_status,
                                  text_color=TEXT_MUTED)

    def _cancel_status_job(self):
        if self._status_job is not None:
            try:
                self.after_cancel(self._status_job)
            except tkinter.TclError:
                pass  # the view (or the app) is already going away
            self._status_job = None

    def _flash_status(self, text, error=False, ms=6000):
        """Show a transient message, then fall back to the storage line."""
        self._cancel_status_job()
        self.status.configure(text=text, text_color=DANGER if error else ACCENT)
        self._status_job = self.after(ms, self._restore_status)

    def _load_clips(self):
        """Load real clips from config; fall back to demo data so the UI renders."""
        self._fallback_status = ""
        clip_path = self.config_data.clip_path
        if clip_path:
            try:
                scan = core.scan_clips(clip_path)
                if scan.clips:
                    self._restore_status()
                    self._storage_changed()
                    return scan.clips
                self._fallback_status = "No .mp4 clips found — showing demo clips."
            except OSError as err:
                self._fallback_status = f"Showing demo clips — {err}"

        self._restore_status()
        # Demo fallback.
        now = time.time()
        return [
            core.Clip(f"Auto-clip Headshot kill {i + 1}.mp4",
                      size_bytes=(180 + i * 12) * 1024 * 1024,
                      mtime=now - (i + 1) * 86400)
            for i in range(6)
        ]


# --- Settings view ---------------------------------------------------------
class PathField(ctk.CTkFrame):
    """A labelled path input: type a path, or Browse to pick a folder."""

    def __init__(self, master, label, description, value):
        super().__init__(master, fg_color="transparent")

        ctk.CTkLabel(
            self, text=label, anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self, text=description, anchor="w", justify="left",
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
            wraplength=BLURB_WRAP,
        ).pack(anchor="w", pady=(0, 6))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")
        self.entry = ctk.CTkEntry(row, height=36, fg_color=CARD_BG, border_width=0)
        self.entry.insert(0, value)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="Browse", width=90, height=36, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._browse,
        ).pack(side="left")

    def _browse(self):
        start = os.path.expanduser(self.entry.get() or "~")
        chosen = filedialog.askdirectory(initialdir=start)
        if chosen:
            self.entry.delete(0, "end")
            self.entry.insert(0, chosen)

    def get(self):
        return self.entry.get().strip()

    def set(self, value):
        self.entry.delete(0, "end")
        self.entry.insert(0, value)


class Disclosure(ctk.CTkFrame):
    """A section that stays folded away until the user clicks its header.

    Pack children into `.body`. The body is only packed while open, so a closed
    section costs one row of height and the fields inside it can't be filled in
    by accident.
    """

    def __init__(self, master, title, description=""):
        super().__init__(master, fg_color="transparent")
        self.title = title
        self.open = False

        self.header = ctk.CTkButton(
            self, text=self._header_text(), anchor="w", height=34,
            fg_color=CARD_BG, hover_color=CARD_HOVER, text_color=TEXT_BRIGHT,
            font=ctk.CTkFont(size=13, weight="bold"), command=self.toggle,
        )
        self.header.pack(fill="x")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        if description:
            ctk.CTkLabel(
                self.body, text=description, anchor="w", justify="left",
                text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
                wraplength=BLURB_WRAP,
            ).pack(anchor="w", fill="x", pady=(0, 14))

    def _header_text(self):
        return f"{'▾' if self.open else '▸'}  {self.title}"

    def toggle(self):
        self.open = not self.open
        self.header.configure(text=self._header_text())
        if self.open:
            self.body.pack(fill="x", pady=(14, 0))
        else:
            self.body.pack_forget()


class CopyClipsDialog(widgets.Modal):
    """Copy an existing recording library into the app's own clips folder.

    `ask` returns the number of clips copied in, or None if the user backed out
    without copying any. Originals are only ever read: a cancelled or failed
    import costs disk space and nothing else.

    The copy runs on a worker thread — 100 GB of clips would otherwise freeze
    the window for minutes — and reports back through a queue the Tk thread
    drains, the same way the editor runs a trim.
    """

    MIN_WIDTH = 720
    POLL_MS = 120
    DONE_HOLD_MS = 900   # how long the finished bar stays up before closing

    def __init__(self, master, target, source=""):
        super().__init__(master, "Import existing clips")
        self.target = target
        self.plan = None
        self.copied = []
        self.failed = []
        self._events = queue.Queue()
        self._thread = None
        self._poll_job = None
        self._done_job = None
        self._stop = threading.Event()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        ctk.CTkLabel(
            body, text="Import existing clips", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            body, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11), wraplength=self.MIN_WIDTH - 60,
            text=f"Copies the .mp4 files from a folder you already have into "
                 f"your clips folder:\n{target}\n\nThe originals are left where "
                 f"they are, and a clip whose name is already in your clips "
                 f"folder is skipped rather than overwritten. Subfolders are "
                 f"not read, so a library's thumbnails, shared and exported "
                 f"clips stay behind.",
        ).pack(anchor="w", pady=(2, 10))

        ctk.CTkLabel(
            body, anchor="w", justify="left", text_color=METER_CLIPS,
            font=ctk.CTkFont(size=11, weight="bold"),
            wraplength=self.MIN_WIDTH - 60,
            text="Built for SteelSeries Moments libraries. Games and recording "
                 "dates can only be read from file names written the way that "
                 "recorder writes them — anything else copies in fine, but "
                 "comes in untagged for you to label by hand.",
        ).pack(anchor="w", pady=(0, 14))

        picker = ctk.CTkFrame(body, fg_color="transparent")
        picker.pack(fill="x")
        self.source_entry = ctk.CTkEntry(
            picker, height=34, fg_color=CARD_BG, border_width=0,
            placeholder_text="Folder holding your SteelSeries Moments clips")
        if source:
            self.source_entry.insert(0, source)
        self.source_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.browse_button = ctk.CTkButton(
            picker, text="Browse", width=84, height=34, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._browse)
        self.browse_button.pack(side="left", padx=(0, 8))
        self.scan_button = ctk.CTkButton(
            picker, text="Scan", width=84, height=34, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._scan)
        self.scan_button.pack(side="left")

        self.summary = ctk.CTkLabel(
            body, text="Choose the folder your clips are in.", anchor="w",
            justify="left", text_color=TEXT_MUTED, font=ctk.CTkFont(size=12),
            wraplength=self.MIN_WIDTH - 60)
        self.summary.pack(anchor="w", fill="x", pady=(14, 8))

        self.progress = ctk.CTkProgressBar(body, height=10,
                                           progress_color=ACCENT)
        self.progress.set(0)

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(16, 0))
        self.copy_button = ctk.CTkButton(
            actions, text="Copy clips", width=130, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self._start, state="disabled")
        self.copy_button.pack(side="right")
        self.cancel_button = ctk.CTkButton(
            actions, text="Not now", width=130, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._cancel)
        self.cancel_button.pack(side="right", padx=(0, 8))

        if source:
            self._scan()
        self._present(master)

    # --- Planning ----------------------------------------------------------

    def _browse(self):
        chosen = filedialog.askdirectory(
            initialdir=os.path.expanduser(self.source_entry.get() or "~"),
            parent=self)
        if chosen:
            self.source_entry.delete(0, "end")
            self.source_entry.insert(0, chosen)
            self._scan()

    def _scan(self):
        folder = core.normalize_path(self.source_entry.get())
        if not folder:
            return
        if os.path.normpath(folder) == os.path.normpath(self.target):
            self._say("That is already your clips folder — nothing to copy in.",
                      TEXT_MUTED)
            self.copy_button.configure(state="disabled")
            return
        try:
            self.plan = core.plan_copy(folder, self.target)
        except OSError as err:
            self.plan = None
            self._say(f"Cannot read that folder — {err}", DANGER)
            self.copy_button.configure(state="disabled")
            return

        plan = self.plan
        if not plan.files:
            note = (f"All {len(plan.present)} clips are already in your clips "
                    f"folder." if plan.present else "No .mp4 clips in that folder.")
            self._say(note, TEXT_MUTED)
            self.copy_button.configure(state="disabled")
            return

        parts = [f"{len(plan.files)} clips to copy", plan.total_human]
        if plan.present:
            parts.append(f"{len(plan.present)} already there, skipped")
        if not plan.fits:
            self._say(f"{'  ·  '.join(parts)} — not enough room, "
                      f"{plan.free_human} free.", DANGER)
            self.copy_button.configure(state="disabled")
            return
        parts.append(f"{plan.free_human} free")
        self._say("  ·  ".join(parts), TEXT_BRIGHT)
        self.copy_button.configure(state="normal")

    def _say(self, text, colour):
        self.summary.configure(text=text, text_color=colour)

    # --- Copying -----------------------------------------------------------

    def _start(self):
        if self.plan is None or self._thread is not None:
            return
        self.progress.pack(fill="x", pady=(0, 4), before=self.summary)
        self.progress.set(0)
        for widget in (self.copy_button, self.browse_button, self.scan_button):
            widget.configure(state="disabled")
        self.source_entry.configure(state="disabled")
        self.cancel_button.configure(text="Stop")
        # Closing mid-copy would leave the worker writing into a dead window.
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.unbind("<Escape>")

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def _worker(self):
        """Runs off the Tk thread; progress and the result come back by queue."""
        try:
            copied, failed = core.copy_clips(
                self.plan,
                on_progress=lambda index, name, done_bytes: self._events.put(
                    ("progress", (index, name, done_bytes))),
                cancelled=self._stop.is_set,
            )
            self._events.put(("done", (copied, failed)))
        except Exception as exc:                            # noqa: BLE001
            self._events.put(("failed", str(exc)))

    def _poll(self):
        self._poll_job = None
        if not self.winfo_exists():
            return
        # Progress arrives far faster than the eye can read it, so only the
        # newest report in this batch is drawn; the rest are already history.
        latest = None
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                latest = payload
            elif kind == "done":
                self._on_done(*payload)   # its own message replaces progress
                return
            elif kind == "failed":
                self._say(f"Import failed — {payload}", DANGER)
                self._finish()
                return
        if latest is not None:
            self._on_progress(*latest)
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def _on_progress(self, index, name, done_bytes):
        # The bar tracks bytes, not files: clips differ enough in size that a
        # file count jumps in a way that doesn't match the wait.
        total_files = len(self.plan.files)
        total_bytes = self.plan.total_bytes
        self.progress.set(min(1.0, done_bytes / total_bytes) if total_bytes else 1.0)
        stopping = "  (stopping…)" if self._stop.is_set() else ""
        self._say(f"Copying {index} of {total_files}  ·  "
                  f"{core.format_size(done_bytes)} of {self.plan.total_human}"
                  f"{stopping}\n{name}", TEXT_BRIGHT)

    def _on_done(self, copied, failed):
        self.copied, self.failed = copied, failed
        self.progress.set(1.0)
        if failed:
            self._say(f"Copied {len(copied)} clips, {len(failed)} could not be "
                      f"copied — first was {failed[0][0]}: {failed[0][1]}", DANGER)
            self._finish(keep_open=True)
            return
        # Hold the finished bar on screen for a moment: closing the instant the
        # last byte lands reads as the dialog vanishing, not as a copy that
        # finished. The tagging step opens straight after.
        self._say(f"Copied {plural(len(copied), 'clip')}  ·  {self.plan.total_human} — done.",
                  ACCENT)
        self.cancel_button.configure(state="disabled")
        self._done_job = self.after(self.DONE_HOLD_MS, self._close_finished)

    def _close_finished(self):
        self._done_job = None
        if self.winfo_exists():
            self.close(len(self.copied))

    def _finish(self, keep_open=False):
        """Put the dialog back in a usable state after a copy ended badly."""
        self._thread = None
        self._stop.clear()
        self.cancel_button.configure(text="Close")
        self.source_entry.configure(state="normal")
        for widget in (self.browse_button, self.scan_button):
            widget.configure(state="normal")
        if not keep_open:
            self.copy_button.configure(state="normal")

    def _cancel(self):
        """Back out, or ask a copy in flight to stop at the next whole file."""
        if self._thread is not None and self._thread.is_alive():
            self._stop.set()
            self.cancel_button.configure(state="disabled")
            return
        self.close(len(self.copied) or None)

    def close(self, result=None):
        self._stop.set()
        for attr in ("_poll_job", "_done_job"):
            job = getattr(self, attr)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tkinter.TclError:
                    pass
                setattr(self, attr, None)
        super().close(result)


class TagImportDialog(widgets.Modal):
    """Review a folder of recordings before their tags go into the library.

    `ask` returns ({filename: game}, {filename: recorded}) to write, or None if
    the user backed out. Nothing is written from here — the caller applies the
    result — so cancelling really does leave no trace.

    Every game is shown as an editable field rather than being applied silently:
    matching by name gets "THE FINALS" onto an existing "The Finals", but it
    can't know that "Heroes of the Storm" is the "HOTS" already in use. Only
    the person who typed the first one knows that, so they get the last word.
    """

    MIN_WIDTH = 780
    BODY_HEIGHT = 400

    def __init__(self, master, folder, known_games=(), tagged=()):
        super().__init__(master, "Import a library")
        self.known_games = list(known_games)
        self.tagged = set(tagged)
        self.plan = None
        self.game_fields = {}    # derived game -> field holding the tag to write
        self.stray_fields = {}   # filename -> field, blank meaning "skip"

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        ctk.CTkLabel(
            body, text="Import a SteelSeries Moments library", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            body, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11), wraplength=self.MIN_WIDTH - 60,
            text="Reads the game and the recording date out of each file name "
                 "and stores them against the clip. Files are never renamed, "
                 "moved or altered, and clips already carrying a game are left "
                 "as they are.",
        ).pack(anchor="w", pady=(2, 8))
        ctk.CTkLabel(
            body, anchor="w", justify="left", text_color=METER_CLIPS,
            font=ctk.CTkFont(size=11, weight="bold"),
            wraplength=self.MIN_WIDTH - 60,
            text="Only SteelSeries Moments names carry a game, so only those "
                 "can be tagged this way. GPU Screen Recorder's “Replay_…” "
                 "names say nothing about what was played and are tagged "
                 "Desktop; anything else is listed below for you to label.",
        ).pack(anchor="w", pady=(0, 14))

        picker = ctk.CTkFrame(body, fg_color="transparent")
        picker.pack(fill="x")
        self.folder_entry = ctk.CTkEntry(
            picker, height=34, fg_color=CARD_BG, border_width=0)
        self.folder_entry.insert(0, folder)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            picker, text="Browse", width=84, height=34, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._browse,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            picker, text="Scan", width=84, height=34, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=self._scan,
        ).pack(side="left")

        self.summary = ctk.CTkLabel(
            body, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=12), wraplength=self.MIN_WIDTH - 60,
        )
        self.summary.pack(anchor="w", fill="x", pady=(12, 8))

        self.rows = ctk.CTkScrollableFrame(
            body, fg_color=SIDEBAR_BG, height=self.BODY_HEIGHT, corner_radius=8)
        self.rows.pack(fill="both", expand=True)
        make_scroll_pixel_precise(self.rows)

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(16, 0))
        # Starts disabled; the scan below is what decides whether there is
        # anything here to import.
        self.import_button = ctk.CTkButton(
            actions, text="Import", width=120, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self._confirm, state="disabled",
        )
        self.import_button.pack(side="right")
        ctk.CTkButton(
            actions, text="Cancel", width=120, fg_color=CARD_BG,
            hover_color=CARD_HOVER, command=lambda: self.close(None),
        ).pack(side="right", padx=(0, 8))

        self._scan()
        self._present(master)

    # --- Scanning ----------------------------------------------------------

    def _browse(self):
        chosen = filedialog.askdirectory(
            initialdir=os.path.expanduser(self.folder_entry.get() or "~"),
            parent=self,
        )
        if chosen:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)
            self._scan()

    def _scan(self):
        for child in self.rows.winfo_children():
            child.destroy()
        self.game_fields = {}
        self.stray_fields = {}

        folder = core.normalize_path(self.folder_entry.get())
        try:
            self.plan = core.plan_import(folder, self.known_games, self.tagged)
        except OSError as err:
            self.plan = None
            self.summary.configure(text=f"Cannot read that folder — {err}",
                                   text_color=DANGER)
            self.import_button.configure(state="disabled")
            return

        self._describe()
        self._build_rows()
        self.import_button.configure(
            state="normal" if self.plan.taggable or self.plan.strays else "disabled")

    def _describe(self):
        plan = self.plan
        if not plan.clip_count:
            self.summary.configure(text="No .mp4 clips in that folder.",
                                   text_color=TEXT_MUTED)
            return
        parts = [f"{plan.clip_count} clips", f"{plan.taggable} to tag"]
        if plan.already:
            parts.append(f"{len(plan.already)} already tagged, left alone")
        if plan.strays:
            parts.append(f"{len(plan.strays)} with no game in the name")
        self.summary.configure(text="  ·  ".join(parts), text_color=TEXT_BRIGHT)

    # --- Rows --------------------------------------------------------------

    def _build_rows(self):
        plan = self.plan
        if plan.games:
            self._heading("GAMES FOUND — EDIT ANY TAG BEFORE IMPORTING")
        for game in sorted(plan.games, key=lambda g: (-len(plan.games[g]), g)):
            self.game_fields[game] = self._row(
                label=game, count=len(plan.games[game]),
                value=plan.stored_as[game],
                note="reuses your tag" if plan.stored_as[game] != game else "",
            )
        if plan.strays:
            self._heading("NO GAME IN THE NAME — TAG THESE, OR LEAVE BLANK TO SKIP")
        for name in plan.strays:
            self.stray_fields[name] = self._row(label=name, count=0, value="")

    def _heading(self, text):
        ctk.CTkLabel(
            self.rows, text=text, anchor="w", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", fill="x", padx=12, pady=(12, 4))

    def _row(self, label, count, value, note=""):
        row = ctk.CTkFrame(self.rows, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)

        left = ctk.CTkLabel(
            row, text=label, anchor="w", font=ctk.CTkFont(size=12),
            width=300, wraplength=300, justify="left",
        )
        left.pack(side="left")
        ctk.CTkLabel(
            row, text=f"{count} clips" if count else "", anchor="e",
            width=70, text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(4, 8))

        field = ctk.CTkComboBox(
            row, width=240, height=30, values=self.known_games or [""],
            fg_color=CARD_BG, border_width=0, button_color=CARD_HOVER,
            button_hover_color=THUMB_BG, font=ctk.CTkFont(size=12),
        )
        field.set(value)   # never leave CTkComboBox on its own first value
        field.pack(side="left")
        ctk.CTkLabel(
            row, text=note, anchor="w", width=110, text_color=ACCENT,
            font=ctk.CTkFont(size=10),
        ).pack(side="left", padx=(8, 0))
        return field

    # --- Result ------------------------------------------------------------

    def _confirm(self):
        assignments = {}
        for game, field in self.game_fields.items():
            tag = field.get().strip()
            for name in self.plan.games[game]:
                assignments[name] = tag
        for name, field in self.stray_fields.items():
            assignments[name] = field.get().strip()
        self.close((assignments, self.plan.dates))


class DeviceField(ctk.CTkFrame):
    """A labelled capture-device input: pick a live device, or type a name.

    Typing matters as much as picking: a clip recorded on hardware that is no
    longer plugged in, or by a recorder that wrote a friendlier spelling of the
    device, still has to be matchable — so anything the user types is kept.
    """

    def __init__(self, master, label, description, value, devices):
        super().__init__(master, fg_color="transparent")

        ctk.CTkLabel(
            self, text=label, anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self, text=description, anchor="w", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11), justify="left", wraplength=BLURB_WRAP,
        ).pack(anchor="w", pady=(0, 6))

        self.combo = ctk.CTkComboBox(
            self, height=36, values=devices or [], fg_color=CARD_BG,
            border_width=0, button_color=CARD_HOVER, button_hover_color=THUMB_BG,
        )
        # CTkComboBox seeds itself with the first value, which would silently
        # configure a device the user never chose.
        self.combo.set(value)
        self.combo.pack(fill="x")

    def get(self):
        return self.combo.get().strip()

    def set(self, value):
        self.combo.set(value)


# (config key, label, description) — shared by Settings and first-run setup so
# a new setting shows up in both places at once.
PATH_FIELDS: list[tuple[str, str, str]] = [
    ("clip_path", "Clips folder (scan)",
     "Scanned for recordings. Only ever read — never moved or rewritten."),
    ("export_path", "Export folder (save)",
     "Exported clips are written here. Originals stay untouched."),
]

# The same, for folders the app manages itself. Their defaults are right for
# almost everyone, so both screens keep them folded away behind a disclosure
# the user has to open — see build_path_fields().
ADVANCED_PATH_FIELDS: list[tuple[str, str, str]] = [
    ("data_path", "Data folder",
     "Tags, favorites, trim points, clip index. Back this one up."),
    ("state_path", "State folder",
     "Window size, last view, scroll position. Safe to lose."),
    ("cache_path", "Cache folder",
     "Thumbnails and previews. Safe to delete; rebuilt as you browse."),
]

ALL_PATH_FIELDS = PATH_FIELDS + ADVANCED_PATH_FIELDS
ADVANCED_PATH_KEYS = {key for key, _label, _desc in ADVANCED_PATH_FIELDS}

# How a folder is named in prose, where the field labels above are too terse to
# stand on their own ("Clips folder (scan)" reads as a field, not a sentence).
FOLDER_NAMES = {
    "clip_path": "Clips folder",
    "data_path": "Data folder",
}

ADVANCED_PATHS_BLURB = (
    "The app's own storage, at the standard locations for your user. Change "
    "these only if you keep app data elsewhere."
)


def build_path_fields(parent, config_data, pady=(0, 18)):
    """Pack a PathField per path setting into `parent`; advanced ones folded.

    Returns ({config key: PathField}, disclosure). The mapping covers every
    setting, folded away or not, so callers collect and save them all the same
    way; the disclosure is handed back so a complaint about a field inside it
    can unfold it first.
    """
    fields = {}
    for key, label, desc in PATH_FIELDS:
        field = PathField(parent, label, desc, getattr(config_data, key))
        field.pack(fill="x", pady=pady)
        fields[key] = field

    advanced = Disclosure(parent, "Advanced folders", ADVANCED_PATHS_BLURB)
    advanced.pack(fill="x", pady=pady)
    for key, label, desc in ADVANCED_PATH_FIELDS:
        field = PathField(advanced.body, label, desc, getattr(config_data, key))
        field.pack(fill="x", pady=pady)
        fields[key] = field
    return fields, advanced

# (config key, label, description) for the capture devices the mixer matches
# tracks against — asked for by first-run setup's second step and editable in
# Settings after that. Every one of them is optional: they describe how you
# record, not where files live, and the app is usable with all three blank.
DEVICE_FIELDS: list[tuple[str, str, str]] = [
    ("game_device", "Game audio output",
     "Where games play — headset or speakers. Tracks land as “Game Audio”."),
    ("chat_device", "Chat audio output",
     ("Where voice chat plays — Discord, TeamSpeak, in-game. Tracks land as "
      "“Chat Audio”.")),
    ("mic_device", "Microphone",
     "What you speak into. Tracks land as “Microphone”."),
]

# Shown above the device fields on both screens; setup adds its own tail about
# skipping the step, so the shared part stops before that.
DEVICES_BLURB = (
    "Recordings name their audio tracks after the devices they came from. Name "
    "yours and the mixer labels them instead of guessing. All optional."
)

# The one thing on this screen a single-track recorder has to know, so it gets
# its own card instead of a clause in the paragraph above.
SPLIT_AUDIO_HINT = (
    "Not recording split audio? Just set your default output as the game audio "
    "output."
)


def build_hint(parent, text, pady=(0, 16)):
    """A caveat worth stopping on, as a bordered yellow card.

    Reserved for the two things a user can only find out the hard way — that
    split audio has to be set up in the recorder, and what the import has
    actually been tried against. A third would make the first two ordinary.
    """
    card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8,
                        border_width=1, border_color=METER_CLIPS)
    card.pack(anchor="w", fill="x", pady=pady)
    ctk.CTkLabel(
        card, text=text, anchor="w", justify="left",
        text_color=METER_CLIPS, font=ctk.CTkFont(size=12, weight="bold"),
        wraplength=BLURB_WRAP,
    ).pack(anchor="w", fill="x", padx=14, pady=10)
    return card


def build_device_hint(parent, pady=(0, 16)):
    """The split-audio note, on both screens that ask about devices."""
    return build_hint(parent, SPLIT_AUDIO_HINT, pady)

# The import, described where it lives in Settings (devices are above it there)
# and where first-run setup offers it as the last, optional step.
IMPORT_BLURB = (
    "Copies a SteelSeries Moments library into your clips folder, reading the "
    "game and recording date from each file name. You review every tag before "
    "it is saved; anything unrecognized comes in untagged. Nothing at the "
    "source is moved or changed."
)

# What the import has been tried against, said as what was tested rather than
# as a rule — nobody has established that a share or an NTFS mount fails, only
# that neither has been run.
IMPORT_DRIVES_HINT = (
    "It has only been tested on local drives — no network shares, no mounts "
    "and no NTFS drives have been tested."
)

SETUP_IMPORT_BLURB = (
    "This import is built for SteelSeries Moments libraries first: the game "
    "name and recording date are read straight out of the file names, and "
    "clips it can't recognize are left untagged for you to label by hand.\n\n"
    "Nothing at the source is moved or changed. If you'd rather not, just "
    "finish setup — the same import lives under Settings."
)

# Shown instead of the device list when pactl doesn't answer.
NO_DEVICES_BLURB = (
    "Couldn't read this system's audio devices — PipeWire or PulseAudio didn't "
    "answer. You can still type names by hand, exactly as your recorder writes "
    "them."
)

APPEARANCE_BLURB = (
    f"How {core.APP_NAME} presents itself. Applied the moment you save — "
    f"nothing here needs a restart."
)


class LogoField(ctk.CTkFrame):
    """Pick which ink the logo is drawn in, by looking at both of them.

    A named pair of radio buttons would make the user guess what "light" means;
    the artwork is the only honest label for artwork, so each choice is the
    logo itself on the background it is drawn for. Selection is the accent
    border, which is the same thing a hovered clip card wears.
    """

    PREVIEW_H = 40      # wordmark height inside a swatch
    SWATCH_W = 232
    SWATCH_H = 92
    # What each variant is drawn to sit on, so the swatch shows it in its
    # element rather than both on the same plate.
    GROUNDS = {"light": SIDEBAR_BG, "dark": "#f2f1ed"}

    def __init__(self, master, variant):
        super().__init__(master, fg_color="transparent")
        self.variant = core.logo_variant(variant)
        self._images = {}       # variant -> CTkImage; Tk needs the reference
        self.swatches = {}

        ctk.CTkLabel(
            self, text="Logo", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            self, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11), wraplength=BLURB_WRAP,
            text="Used for the logo in the rail and for the window icon. This "
                 "app's own chrome is dark whichever you pick, so light is the "
                 "one that reads in the rail — choose dark when what matters is "
                 "the icon sitting on a light taskbar, and expect the rail's "
                 "logo to go quiet with it.",
        ).pack(anchor="w", pady=(0, 14))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(anchor="w")
        for index, name in enumerate(core.LOGO_VARIANTS):
            swatch = self._swatch(row, name)
            swatch.pack(side="left", padx=(0 if index == 0 else 14, 0))
            self.swatches[name] = swatch
        self._paint()

    def _swatch(self, parent, name):
        """One clickable plate showing `name`'s artwork on its own ground."""
        ground = self.GROUNDS[name]
        frame = ctk.CTkFrame(parent, fg_color=ground, corner_radius=RADIUS_CARD,
                             width=self.SWATCH_W, height=self.SWATCH_H,
                             border_width=2, border_color=ground)
        frame.pack_propagate(False)
        self._images[name] = load_wordmark(self.PREVIEW_H, name)
        if self._images[name] is not None:
            label = ctk.CTkLabel(frame, text="", image=self._images[name])
        else:   # no artwork in this checkout — the word still picks a side
            label = ctk.CTkLabel(
                frame, text=name.title(), font=ctk.CTkFont(size=14),
                text_color=TEXT_BRIGHT if name == "light" else "#16161a")
        label.place(relx=0.5, rely=0.5, anchor="center")
        # The label covers most of the plate, so it has to take the click too.
        for widget in (frame, label):
            widget.bind("<Button-1>", lambda _e, n=name: self.set(n))
            widget.configure(cursor="hand2")
        return frame

    def _paint(self):
        """Ring the chosen swatch and leave the other flush with its ground."""
        for name, swatch in self.swatches.items():
            swatch.configure(border_color=ACCENT if name == self.variant
                             else self.GROUNDS[name])

    def get(self):
        return self.variant

    def set(self, variant):
        self.variant = core.logo_variant(variant)
        self._paint()


class SettingsSection(ctk.CTkFrame):
    """One Settings page, drawn as a panel with the library's lift.

    The face — rounded corners and the drop shadow under them — is a rendered
    image behind the whole panel, the same paint.card_surface a clip card sits
    on, so a page here reads as the same kind of object as a card over there
    rather than as a flat box. Two consequences of that, both from paint.py's
    one rule (a CustomTkinter widget over an image paints a flat rectangle of
    its own colour):

      * the face is flat SECTION_BG rather than a gradient, because widgets sit
        all the way down a settings page and each one has to be handed the exact
        colour of the image beneath it;
      * everything packed here is SECTION_BG or transparent-over-SECTION_BG, and
        the panel itself is page-coloured with PANEL_SHADOW of margin on every
        side for the shadow to fall into.

    Pack content into `.body`.
    """

    def __init__(self, master, title, blurb=""):
        # SECTION_BG, though the *visible* ground is the rendered face and the
        # page-coloured margin around it, both of which come from the backdrop
        # image below. This colour shows in exactly two places, and wants to be
        # the face's colour in both: through the 1px row a CustomTkinter frame
        # leaves unpainted at its own bottom edge, and under any child packed
        # here with fg_color="transparent" — which paints its parent's colour.
        super().__init__(master, fg_color=SECTION_BG, corner_radius=0,
                         border_width=0)
        self._surface = None        # PhotoImage; paint.py's cache owns it
        self._surface_size = None
        self.backdrop = tkinter.Label(self, bd=0, highlightthickness=0,
                                      bg=MAIN_BG)
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._on_resize, add="+")

        # The heading's opaque ground is this frame, not the labels on it. A
        # CTkLabel sizes its own background when it is created, before pack has
        # given it a width to wrap against — so a blurb that turns out to need a
        # third line draws that line outside its own background and over
        # whatever is under it. A frame follows the geometry it is given.
        # corner_radius=0 throughout, because these sit *on* the rendered face:
        # a rounded widget cuts its corners back to this frame's own colour —
        # the page colour — leaving dark notches in the middle of a panel.
        pad = PANEL_SHADOW
        header = ctk.CTkFrame(self, fg_color=SECTION_BG, corner_radius=0)
        header.pack(fill="x", padx=pad + PANEL_PAD, pady=(pad + PANEL_PAD, 0))
        ctk.CTkLabel(
            header, text=title, anchor="w", fg_color="transparent",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(anchor="w", fill="x", pady=(0, 4))
        if blurb:
            ctk.CTkLabel(
                header, text=blurb, anchor="w", justify="left",
                text_color=TEXT_MUTED, font=ctk.CTkFont(size=12),
                wraplength=BLURB_WRAP, fg_color="transparent",
            ).pack(anchor="w", fill="x", pady=(0, 2))

        # A hairline under the heading, the way the action bar has one: it sets
        # the title off from the fields without costing another band of space.
        # A plain Tk frame, not a CTkFrame: CustomTkinter draws a frame's fill
        # from (0,0) to (w-1,h-1), so at height=1 there is nothing left to fill
        # and the "line" comes out as bare parent colour instead of SEAM.
        tkinter.Frame(self, bg=SEAM, height=1, bd=0, highlightthickness=0).pack(
            fill="x", padx=pad + PANEL_PAD, pady=(14, 0))

        self.body = ctk.CTkFrame(self, fg_color=SECTION_BG, corner_radius=0)
        self.body.pack(fill="x", padx=pad + PANEL_PAD,
                       pady=(PANEL_PAD, pad + PANEL_PAD))

    def _on_resize(self, event):
        if (event.width, event.height) != self._surface_size:
            self._surface_size = (event.width, event.height)
            self._paint()

    def _paint(self):
        """Put the rendered panel face behind everything packed on it."""
        width, height = self._surface_size
        if width <= 2 * PANEL_SHADOW or height <= 2 * PANEL_SHADOW:
            return      # not laid out yet
        self._surface = paint.card_surface(
            width, height, fill_top=SECTION_BG, fill_bottom=SECTION_BG,
            base=MAIN_BG, radius=RADIUS_PANEL, pad=PANEL_SHADOW,
            shadow=CARD_SHADOW, blur=CARD_BLUR, drop=CARD_DROP,
        )
        self.backdrop.configure(image=self._surface)


class SettingsView(ctk.CTkFrame):
    """Settings in the same shell the grid uses: header, pane, action bar.

    The rail's list picks a page and this view shows that one alone, so a screen
    holds one subject rather than the whole file at once. Every page is built up
    front and only the shown one is packed — never destroyed — because one Save
    still writes the lot, and a field that stopped existing when its page was
    hidden would drop out of what that button covers. The page titles carry a
    dot while their page holds unsaved edits, so nothing hides behind a page you
    are not looking at.
    """

    def __init__(self, master, on_saved=None, library=None, on_imported=None):
        super().__init__(master, fg_color="transparent")
        self.on_saved = on_saved
        self.on_imported = on_imported
        self.library = library
        self.pages = {}           # key -> the page frame, packed one at a time
        self.current_page = None

        # Same lit band as the grid, on the same numbers: the two views swap in
        # and out of the same slot, so a header that sat differently would make
        # the light jump as you moved between them.
        widgets.attach_glow(self, top=PAGE_GLOW, bottom=MAIN_BG,
                            plateau=GLOW_PLATEAU, height=GLOW_H,
                            offset=CONTENT_PAD_TOP)
        head = ctk.CTkFrame(self, fg_color=PAGE_GLOW, corner_radius=0,
                            height=HEADER_H)
        head.pack(fill="x", pady=(0, 14))
        head.pack_propagate(False)
        ctk.CTkLabel(
            head, text="Settings", anchor="w",
            font=ctk.CTkFont(size=21, weight="bold"),
        ).pack(side="left")
        # Which page you are on, in the header rather than only in the rail:
        # this is now one page of several and the header is where the grid says
        # what it is showing too.
        self.crumb = ctk.CTkLabel(
            head, text="", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=15, weight="bold"))
        self.crumb.pack(side="left", padx=(10, 0), pady=(3, 0))
        # Packed last and to the right, so a long path is the thing that gets
        # squeezed on a narrow window rather than the page name beside it. `~`
        # rather than the expanded home dir for the same reason.
        ctk.CTkLabel(
            head, text=f"Stored in {tilde(core.CONFIG_PATH)}",
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=12), anchor="e",
        ).pack(side="right", padx=(24, 0), pady=(4, 0))

        self.pane = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.pane.pack(fill="both", expand=True)
        make_scroll_pixel_precise(self.pane)

        self.config_data = self._load_config()

        self._build_folders_page()
        self._build_devices_page()
        self._build_appearance_page()
        self._build_import_page()
        self._dirty_job = None      # the poll below; cancelled on teardown

        # Pinned under the pane rather than floating between the panels: Save
        # writes every page, not the one on screen, so it cannot sit on a page.
        # The import's own button does sit on its page — that one really is
        # about the page it is on (see _build_import_page).
        ctk.CTkFrame(self, height=1, fg_color=SEAM, corner_radius=0).pack(
            fill="x", pady=(12, 0))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        save_button = ctk.CTkButton(
            actions, text="Save settings", width=140, height=36,
            corner_radius=RADIUS_CONTROL,
            font=ctk.CTkFont(size=13, weight="bold"), command=self.save,
            **PRIMARY_BUTTON,
        )
        save_button.pack(side="left")
        self.status = ctk.CTkLabel(actions, text="", text_color=TEXT_MUTED)
        self.status.pack(side="left", padx=16)

        # The baseline is_dirty compares against: what the fields held once
        # every one of them existed. Taken last, so it covers the whole screen.
        self._saved_values = self._current_values()
        self.show_section("folders")
        self._watch_dirty()

    # --- Pages ---------------------------------------------------------------
    def _page(self, key, title, blurb=""):
        """A page's panel, built but not shown. Pack content into `.body`."""
        page = SettingsSection(self.pane, title, blurb)
        self.pages[key] = page
        return page

    def show_section(self, key):
        """Show one page and hide the rest, when the rail asks for one."""
        page = self.pages.get(key)
        if page is None or not page.winfo_exists():
            return
        if self.current_page is not None and self.current_page is not page:
            self.current_page.pack_forget()
        self.current_page = page
        page.pack(fill="x", pady=(0, SECTION_GAP))
        titles = {row_key: title for title, row_key in Rail.SETTINGS_ROWS}
        self.crumb.configure(text=titles.get(key, ""))
        # A page shorter than the one before it would otherwise stay scrolled
        # to where the taller one was left.
        try:
            self.pane.update_idletasks()
            self.pane._parent_canvas.yview_moveto(0.0)
        except (tkinter.TclError, AttributeError):
            pass

    def _build_folders_page(self):
        page = self._page("folders", "Folders",
                          "Read from, and written to. Applied on save.")
        self.fields, self.advanced_paths = build_path_fields(
            page.body, self.config_data, pady=(0, FIELD_GAP))

    def _build_devices_page(self):
        page = self._page("devices", "Audio devices", DEVICES_BLURB)
        build_device_hint(page.body, pady=(0, 18))

        devices = core.audio_devices()
        if not devices:
            ctk.CTkLabel(
                page.body, anchor="w", justify="left", text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=11), wraplength=BLURB_WRAP,
                text=NO_DEVICES_BLURB,
            ).pack(anchor="w", fill="x", pady=(0, 12))

        self.device_fields = {}
        for key, label, desc in DEVICE_FIELDS:
            field = DeviceField(page.body, label, desc,
                                getattr(self.config_data, key), devices)
            field.pack(fill="x", pady=(0, FIELD_GAP))
            self.device_fields[key] = field

    def _build_appearance_page(self):
        page = self._page("appearance", "Appearance", APPEARANCE_BLURB)
        self.logo_field = LogoField(page.body, self.config_data.logo_variant)
        self.logo_field.pack(fill="x")

    def _build_import_page(self):
        """The one-time bulk import, for a library that arrived all at once."""
        page = self._page("import", "Import", IMPORT_BLURB)
        build_hint(page.body, IMPORT_DRIVES_HINT, pady=(0, 20))

        # On the panel rather than in the action bar below it: Save covers the
        # settings, this covers nothing — it copies and tags as it runs and is
        # committed the moment it returns. Sitting it next to the caveat it has
        # to be read with says that better than any placement in a shared row.
        self.import_button = ctk.CTkButton(
            page.body, text="Import a SteelSeries Moments library…", height=38,
            corner_radius=RADIUS_CONTROL, fg_color=CARD_BG,
            hover_color=CARD_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
            command=self._import,
        )
        if self.library is None:
            self.import_button.configure(state="disabled")
        self.import_button.pack(anchor="w")

        self.import_status = ctk.CTkLabel(
            page.body, text="", text_color=TEXT_MUTED, anchor="w",
            font=ctk.CTkFont(size=11), justify="left", wraplength=BLURB_WRAP,
        )
        if self.library is None:
            self.import_status.configure(
                text="Unavailable — your library couldn't be opened. Check the "
                     "data folder on the Folders page.")
        self.import_status.pack(anchor="w", fill="x", pady=(14, 0))

    def _import(self):
        # Copy first, then tag. Backing out of the copy ends the whole import:
        # "Not now" has to mean not now, not "on to the next dialog".
        copied = CopyClipsDialog.ask(self, target=self.config_data.clip_path)
        if copied is None:
            return
        self.import_status.configure(
            text=f"Copied {plural(copied, 'clip')} — tagging them now…",
            text_color=TEXT_MUTED)
        self.update_idletasks()
        # New files in the clips folder: whatever the grid is showing was
        # scanned before they arrived, so it has to rescan on the way back.
        self._mark_grid_stale()

        try:
            known = self.library.known_games()
            tagged = set(self.library.tags())
        except sqlite3.Error as err:
            self.import_status.configure(text=f"Couldn't read your library — {err}",
                                         text_color=DANGER)
            return

        answer = TagImportDialog.ask(
            self, folder=self.config_data.clip_path,
            known_games=known, tagged=tagged,
        )
        if answer is None:
            return   # cancelled, and nothing was written

        assignments, dates = answer
        try:
            written = self.library.apply_import(assignments, dates)
        except sqlite3.Error as err:
            self.import_status.configure(text=f"Couldn't import — {err}",
                                         text_color=DANGER)
            return
        skipped = len(assignments) - written
        note = f", {skipped} left untagged" if skipped else ""
        self.import_status.configure(
            text=f"Tagged {plural(written, 'clip')}{note}. Open your library to "
                 f"see them.",
            text_color=ACCENT)
        # Tags changed under the grid too, even when nothing was copied.
        self._mark_grid_stale()

    def _mark_grid_stale(self):
        if self.on_imported is not None:
            self.on_imported()

    def _load_config(self):
        try:
            return core.Config.load()
        except (OSError, ValueError):
            # No config yet — start from blanks so the user can fill them in.
            return core.Config()

    def _current_values(self):
        """What Save would write, read straight off the fields.

        Every page's fields, not just the one on screen: pages are hidden by
        unpacking them, never destroyed, so they all still answer. Paths go
        through normalize_path first — the same call _save makes — so that
        typing a trailing slash and taking it off again doesn't count as an edit
        and doesn't prompt on the way out.
        """
        values = {key: core.normalize_path(field.get())
                  for key, field in self.fields.items()}
        # Device names are stored verbatim — they are node names, not paths.
        values.update({key: field.get()
                       for key, field in self.device_fields.items()})
        values["logo_variant"] = self.logo_field.get()
        return values

    def _page_of(self, key):
        """Which page a config key is edited on, for naming it in the status."""
        if key in self.device_fields:
            return "devices"
        if key == "logo_variant":
            return "appearance"
        return "folders"

    def dirty_pages(self):
        """Titles of the pages holding unsaved edits, in the rail's order."""
        try:
            values = self._current_values()
        except tkinter.TclError:
            return []
        changed = {self._page_of(key) for key, value in values.items()
                   if self._saved_values.get(key) != value}
        return [title for title, key in Rail.SETTINGS_ROWS if key in changed]

    def _watch_dirty(self):
        """Keep the status line naming whatever Save has left to write.

        Polled rather than wired into every field: the pages carry entries,
        combo boxes and a pair of clickable swatches between them, and one
        cheap read of what they hold beats a change binding per widget that a
        later field could quietly forget to add.
        """
        self._dirty_job = None
        try:
            if not self.winfo_exists():
                return
            pending = self.dirty_pages()
            showing = self.status.cget("text_color")
            if showing == DANGER:
                pass          # a write that failed; leave it until they retry
            elif pending:
                # Replaces a "Saved ✓" too: that message went stale the moment
                # there was something new to save.
                self.status.configure(text=f"Unsaved on {oxford(pending)}",
                                      text_color=TEXT_MUTED)
            elif showing != ACCENT:
                self.status.configure(text="")
            self._dirty_job = self.after(DIRTY_POLL_MS, self._watch_dirty)
        except tkinter.TclError:
            pass              # torn down between the check and the write

    def is_dirty(self):
        """Whether the fields hold anything Save hasn't written yet.

        Only the settings on this screen. The import writes as it runs and is
        already committed by the time it returns, so it is never pending here.
        """
        try:
            return self._current_values() != self._saved_values
        except tkinter.TclError:
            return False    # torn down mid-check; nothing left to lose

    def save(self):
        """Write the config. True if it landed, False if the disk said no."""
        values = self._current_values()
        for key, field in self.fields.items():
            field.set(values[key])   # show the user what actually gets stored
        for key, value in values.items():
            setattr(self.config_data, key, value)
        try:
            self.config_data.save()
        except OSError as err:
            self.status.configure(text=f"Couldn't write the config file — {err}",
                                  text_color=DANGER)
            return False
        # Only once it is on disk: this is what is_dirty measures against, and
        # a failed write has to leave the screen still holding unsaved changes.
        self._saved_values = values
        self.status.configure(text="Saved ✓", text_color=ACCENT)
        if self.on_saved is not None:
            self.on_saved()
        return True


# --- First-run setup -------------------------------------------------------
class FirstRunView(ctk.CTkScrollableFrame):
    """Setup shown once, before the app is usable, as three steps.

    Nothing about where files live is assumed from the machine the app was
    built on: every field starts from core.default_config(), which derives the
    paths from the account running right now.

    Each step is saved as it is left rather than everything at the end. That is
    what lets the import step copy into a clips folder that already exists, and
    it means closing the window part-way still leaves a usable install behind.
    """

    # (heading shown in the step counter, what the step is for)
    STEPS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Folders", "First, where your clips live."),
        ("Audio devices", "Next, what you record from."),
        ("Import", "Last, bring an existing library with you."),
    )

    def __init__(self, master, on_done, config=None, missing=()):
        super().__init__(master, fg_color="transparent")
        self.on_done = on_done
        make_scroll_pixel_precise(self)

        # Given a config, this is a re-run over a working install come back to
        # fix a folder that moved — so it opens on what the user already has,
        # not on the detected defaults, which would quietly undo their choices
        # on every other setting. "Reset to detected" still offers those.
        self.config_data = config or core.default_config()
        self.missing = list(missing)   # (config key, path) pairs that went AWOL
        self.step = 0
        self.fields = {}          # rebuilt by the folders step
        self.advanced_paths = None  # its disclosure, likewise
        self.device_fields = {}   # rebuilt by the devices step
        self.import_status = None
        self._devices = None      # audio devices, listed once when first needed

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(8, 6))
        self.logo_image = load_logo(SETUP_LOGO_SIZE,
                                    self.config_data.logo_variant)
        if self.logo_image is not None:
            ctk.CTkLabel(header, text="", image=self.logo_image).pack(
                side="left", padx=(0, 14))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", anchor="w")
        ctk.CTkLabel(
            titles, anchor="w", font=ctk.CTkFont(size=24, weight="bold"),
            text=("Let's find your folders again" if self.missing
                  else f"Welcome to {core.APP_NAME}"),
        ).pack(anchor="w")
        self.subtitle = ctk.CTkLabel(
            titles, text="", anchor="w",
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=13),
        )
        self.subtitle.pack(anchor="w")

        # Only this frame is torn down and rebuilt between steps, so the header
        # and the buttons below it stay put instead of flickering.
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(14, 0))

        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.pack(fill="x", pady=(4, 12))
        self.next_button = ctk.CTkButton(
            self.actions, text="Next", width=140, height=38, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, font=ctk.CTkFont(size=14, weight="bold"),
            command=self._next,
        )
        self.back_button = ctk.CTkButton(
            self.actions, text="Back", width=100, height=38,
            fg_color=CARD_BG, hover_color=CARD_HOVER, command=self._back,
        )
        # One button whose job changes with the step: it is always the optional
        # action next to Next, never something the user has to press.
        self.extra_button = ctk.CTkButton(
            self.actions, text="", width=170, height=38,
            fg_color=CARD_BG, hover_color=CARD_HOVER,
        )
        self.status = ctk.CTkLabel(
            self.actions, text="", text_color=TEXT_MUTED, anchor="w",
            justify="left")

        self._show_step(0)

    # --- Step plumbing -----------------------------------------------------
    def _show_step(self, index):
        """Swap the body over to `index` and re-label the buttons for it."""
        self.step = index
        for child in self.body.winfo_children():
            child.destroy()
        self.status.configure(text="")
        self.import_status = None

        heading, blurb = self.STEPS[index]
        self.subtitle.configure(
            text=f"Step {index + 1} of {len(self.STEPS)} · {heading} — {blurb}")
        (self._build_paths, self._build_devices, self._build_import)[index]()
        self._paint_actions()
        self.scroll_to_top()

    def _paint_actions(self):
        """Re-pack the button row for the current step, in a fixed order.

        The last step reverses the usual order: finishing sits on the right
        where import used to be, with import next to it as the alternative to
        finishing straight away. Import is outlined rather than filled — loud
        enough to be seen, but still visibly the optional one next to the
        accented Finish setup.
        """
        last = self.step == len(self.STEPS) - 1
        for widget in (self.next_button, self.back_button, self.extra_button,
                       self.status):
            widget.pack_forget()

        self.next_button.configure(text="Finish setup" if last else "Next")
        if self.step == 0:
            self.extra_button.configure(
                text="Reset to detected", command=self._reset, width=170,
                border_width=0, text_color=TEXT_BRIGHT,
                font=ctk.CTkFont(size=13),
            )
        elif last:
            self.extra_button.configure(
                text="Import clips…", command=self._run_import, width=190,
                border_width=2, border_color=ACCENT, text_color=TEXT_BRIGHT,
                font=ctk.CTkFont(size=14, weight="bold"),
            )

        if last:
            self.back_button.pack(side="left")
            self.extra_button.pack(side="left", padx=(10, 0))
            self.next_button.pack(side="left", padx=(10, 0))
        else:
            self.next_button.pack(side="left")
            if self.step:
                self.back_button.pack(side="left", padx=(10, 0))
            if self.step == 0:
                self.extra_button.pack(side="left", padx=(10, 0))
        self.status.pack(side="left", padx=10)

    def scroll_to_top(self):
        canvas = getattr(self, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(0.0)

    def _next(self):
        """Save what this step collected, then move on (or finish)."""
        if self.step == 0 and not self._save_paths():
            return
        if self.step == 1 and not self._save_devices():
            return
        if self.step == len(self.STEPS) - 1:
            self.on_done()
            return
        self._show_step(self.step + 1)

    def _back(self):
        """Go back a step, keeping whatever the current one holds."""
        if self.step == 1:
            self._collect_devices()   # unsaved, but not lost either
        self._show_step(self.step - 1)

    # --- Step 1: folders ---------------------------------------------------
    def _build_paths(self):
        if self.missing:
            names = [FOLDER_NAMES[key].lower() for key, _path in self.missing]
            gone = (f"the {names[0]} is not where it used to be" if len(names) == 1
                    else f"the {' and '.join(names)} are not where they used to be")
            blurb = (f"These are your folders as they were last saved, and "
                     f"{gone}. Point each one at where it lives now, or name a "
                     f"new folder and it is created when you continue. "
                     f"Everything else is as you left it.")
        else:
            blurb = (f"These are the default folders {core.APP_NAME} picked out "
                     "for you. Change anything you like — they're created when "
                     "you continue, and Settings can change them again later.")
        ctk.CTkLabel(
            self.body, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12), wraplength=BLURB_WRAP, text=blurb,
        ).pack(anchor="w", fill="x", pady=(0, 18))

        self.fields, self.advanced_paths = build_path_fields(
            self.body, self.config_data)
        # Pointing at a folded-away field is a dead end, so the data folder
        # being the missing one unfolds the section holding it.
        if any(key in ADVANCED_PATH_KEYS for key, _path in self.missing):
            self._open_advanced()

    def _reset(self):
        """Put the detected defaults back into every folder field."""
        detected = core.default_config()
        for key, field in self.fields.items():
            field.set(getattr(detected, key))
        self.status.configure(text="")

    def _collect_paths(self):
        """Normalize what was typed into self.config_data. Returns blank labels."""
        missing = []
        for key, label, _ in ALL_PATH_FIELDS:
            normalized = core.normalize_path(self.fields[key].get())
            self.fields[key].set(normalized)  # show what actually gets stored
            setattr(self.config_data, key, normalized)
            if not normalized:
                missing.append(label)
                # Complaining about a field nobody can see is a dead end, so
                # unfold the advanced section if the blank one lives in it.
                if key in ADVANCED_PATH_KEYS:
                    self._open_advanced()
        return missing

    def _open_advanced(self):
        if self.advanced_paths is not None and not self.advanced_paths.open:
            self.advanced_paths.toggle()

    def _save_paths(self):
        """Create the folders and write the config. False if it can't be done."""
        missing = self._collect_paths()
        if missing:
            self.status.configure(
                text=f"Still empty: {', '.join(missing)}", text_color=DANGER)
            return False

        failed = self.config_data.ensure_dirs()
        if failed:
            self.status.configure(
                text=f"Could not create: {failed[0]}", text_color=DANGER)
            return False
        # An earlier install may have kept its library under a different data
        # dir name; take it along rather than starting from an empty one.
        core.adopt_legacy_library(self.config_data.resolved_data_dir())
        return self._save_config()

    # --- Step 2: audio devices ---------------------------------------------
    def _build_devices(self):
        ctk.CTkLabel(
            self.body, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12), wraplength=BLURB_WRAP,
            text=f"{DEVICES_BLURB}\n\nSkip this entirely if you like — none of "
                 "it is needed to start, and Settings has the same fields.",
        ).pack(anchor="w", fill="x", pady=(0, 12))
        build_device_hint(self.body, pady=(0, 20))

        # Listing the devices shells out to pactl, so it waits until the step
        # is actually opened, and the answer is kept for a second visit.
        if self._devices is None:
            self._devices = core.audio_devices()
        if not self._devices:
            ctk.CTkLabel(
                self.body, anchor="w", justify="left", text_color=TEXT_MUTED,
                font=ctk.CTkFont(size=11), wraplength=BLURB_WRAP,
                text=NO_DEVICES_BLURB,
            ).pack(anchor="w", fill="x", pady=(0, 12))

        self.device_fields = {}
        for key, label, desc in DEVICE_FIELDS:
            field = DeviceField(self.body, label, desc,
                                getattr(self.config_data, key), self._devices)
            field.pack(fill="x", pady=(0, 18))
            self.device_fields[key] = field

    def _collect_devices(self):
        """Read the device fields into the config, verbatim — they aren't paths."""
        for key, field in self.device_fields.items():
            setattr(self.config_data, key, field.get())

    def _save_devices(self):
        self._collect_devices()
        return self._save_config()

    def _save_config(self):
        try:
            self.config_data.save()
        except OSError as err:
            self.status.configure(text=f"Couldn't write the config file — {err}", text_color=DANGER)
            return False
        return True

    # --- Step 3: import ----------------------------------------------------
    def _build_import(self):
        ctk.CTkLabel(
            self.body, anchor="w", justify="left", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12), wraplength=BLURB_WRAP,
            text=SETUP_IMPORT_BLURB,
        ).pack(anchor="w", fill="x", pady=(0, 16))
        # The same caveat Settings carries, in the same yellow: this screen is
        # where most people meet the import, so it cannot be the quieter one.
        build_hint(self.body, IMPORT_DRIVES_HINT, pady=(0, 20))
        self.import_status = ctk.CTkLabel(
            self.body, text="", text_color=TEXT_MUTED, anchor="w",
            justify="left", font=ctk.CTkFont(size=11),
        )
        self.import_status.pack(anchor="w", fill="x")

    def _say_import(self, text, color=TEXT_MUTED):
        if self.import_status is not None:
            self.import_status.configure(text=text, text_color=color)

    def _run_import(self):
        """Copy an existing library in, then tag what was copied.

        Backing out of the copy dialog ends the import there: "Not now" has to
        drop the user back on this step, not open the tagging dialog behind it.
        """
        copied = CopyClipsDialog.ask(self, target=self.config_data.clip_path)
        if copied is None:
            return   # backed out of the copy — don't march them into tagging
        self._say_import(f"Copied {plural(copied, 'clip')} — tagging them now…")
        self.update_idletasks()
        self._tag_imported()

    def _tag_imported(self):
        """Review and store the games for everything now in the clips folder."""
        try:
            library = database.Library(self.config_data.resolved_data_dir())
        except sqlite3.Error as err:
            self._say_import(f"Couldn't open your library to tag them — {err}",
                             DANGER)
            return
        try:
            answer = TagImportDialog.ask(
                self, folder=self.config_data.clip_path,
                known_games=library.known_games(), tagged=set(library.tags()),
            )
            if answer is None:
                return   # cancelled, and nothing was written
            assignments, dates = answer
            written = library.apply_import(assignments, dates)
        except sqlite3.Error as err:
            self._say_import(f"Could not tag the clips — {err}", DANGER)
            return
        finally:
            library.close()
        skipped = len(assignments) - written
        note = f", {skipped} left untagged" if skipped else ""
        self._say_import(f"Tagged {plural(written, 'clip')}{note}. Finish setup to "
                         f"see them.", ACCENT)


# --- App shell -------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        # className fixes the window's WM_CLASS, which would otherwise be the
        # generic "Tk" shared by every Tk app. The desktop entry's
        # StartupWMClass matches it, so the running window lands on the app's
        # own start-menu icon instead of a second, nameless taskbar entry.
        super().__init__(className=core.APP_ID)
        self.title(core.APP_NAME)
        self.geometry("1200x760")
        self.minsize(900, 600)
        self.configure(fg_color=MAIN_BG)
        # The window icon waits for the config below, which says which ink to
        # draw the logo in.

        # Remember Tk's X error handler now, while it is still installed: mpv
        # discards it whenever a video output is torn down (see xguard).
        xguard.capture()

        # Column 0 is the rail, column 1 the workspace beside it.
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # The window's half of the lit band — what shows in the margin around
        # the workspace. Built first, so everything gridded below sits on it.
        widgets.attach_glow(self, top=PAGE_GLOW, bottom=MAIN_BG,
                            plateau=GLOW_PLATEAU, height=GLOW_H)

        # The app's XDG folder is named after it, so the rename left any config
        # written before it under the old name. Adopted before anything reads
        # one, or an existing install would be sent back through first-run setup.
        core.adopt_legacy_config()

        # Config and the services derived from it are owned here and shared with
        # every view, so there's one thumbnail pool and one DB connection.
        self.config_data = self._load_config()
        apply_window_icon(self, self.config_data.logo_variant)
        self.thumbs = None
        self.library = None
        # On a first run the config names nothing usable yet, so the services
        # are built from what setup writes rather than from placeholder paths.
        self._setup_pending = core.needs_setup()
        # A folder named by a working config can still have been renamed or
        # unplugged since the last run. Checked before the services are built,
        # because opening the library would recreate a missing data folder as an
        # empty one — hiding the very thing the user needs to be told about.
        self._missing_dirs = ([] if self._setup_pending
                              else core.missing_dirs(self.config_data))
        if not self._setup_pending and not self._missing_dirs:
            self._build_services()

        self.rail = Rail(
            self, on_search=self._search_changed, on_facet=self._facet_changed,
            on_settings=self._show_settings, on_section=self._show_section,
            logo_variant=self.config_data.logo_variant,
        )
        self.rail.grid(row=0, column=0, sticky="ns")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=24, pady=(18, 16))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.current_view = None
        # Built once and kept alive across navigation (see _hide_current).
        self.clips_view = None
        if self._setup_pending:
            self._start_setup()
        elif self._missing_dirs:
            # Deferred: the dialog is modal on this window, which X has not
            # mapped yet at this point in __init__.
            self.after(80, self._ask_about_missing_dirs)
        else:
            self._navigate("Library")

        # One app-wide wheel handler scrolls whichever scroll area the pointer
        # is over. Bound once (not per view), so it can't stack across nav.
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.bind_all(seq, self._on_wheel, add="+")

        # Ctrl+A selects the whole field. Tk binds it to "jump to the start of
        # the line" out of the box — an emacs habit that no other application on
        # this desktop keeps — so the default is replaced rather than added to,
        # or the cursor would fly to the left after the selection was made.
        # Bound on the Entry class, so it covers the search box, the path
        # fields, the tag dialog and anything added later alike; Control-A is in
        # for the same keystroke pressed with Caps Lock on.
        for seq in ("<Control-a>", "<Control-A>"):
            self.bind_class("Entry", seq, self._select_all)

        # Escape backs out of Settings, the way it already backs out of the
        # editor. Bound app-wide rather than on the view, so it works wherever
        # focus happens to be sitting — including inside a path field.
        self.bind("<Escape>", self._on_escape, add="+")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _select_all(event):
        """Select everything in the focused entry, cursor left at the end."""
        try:
            event.widget.select_range(0, "end")
            event.widget.icursor("end")
        except tkinter.TclError:
            pass   # not a live entry any more
        return "break"

    def _on_wheel(self, event):
        canvas = find_scroll_canvas(event.widget)
        if canvas is None:
            return
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        elif getattr(event, "delta", 0):
            direction = -1 if event.delta > 0 else 1
        else:
            return
        bbox = canvas.bbox("all")
        if not bbox:
            return
        height = bbox[3] - bbox[1]
        if height > 0:
            top = canvas.yview()[0]
            canvas.yview_moveto(top + direction * SCROLL_STEP / height)

    def _load_config(self):
        try:
            return core.Config.load()
        except (OSError, ValueError):
            return core.Config()

    def _ask_about_missing_dirs(self):
        """Say which configured folders are gone, and offer to re-pick them."""
        missing, self._missing_dirs = self._missing_dirs, []
        # Path on its own line under its name: a path is what the user reads to
        # recognise which folder this is, and it is the part long enough to wrap.
        named = "\n\n".join(f"{FOLDER_NAMES[key]}\n{path}" for key, path in missing)
        one = len(missing) == 1
        answer = widgets.ChoiceDialog.ask(
            self,
            title="Folders missing",
            message=("A folder in your settings is missing." if one else
                     f"{plural(len(missing), 'folder')} in your settings are "
                     f"missing."),
            detail=f"{named}\n\nRenamed, moved, or on a drive that isn't "
                   f"mounted. Nothing has been deleted — point the app at where "
                   f"{'it is' if one else 'they are'} now and it picks up where "
                   f"it left off.",
            choices=[("Choose folders…", "setup", False)],
            cancel_text="Continue anyway",
            min_width=560,
        )
        if answer == "setup":
            self._start_setup(self.config_data, missing)
            return
        # Carrying on regardless: the clips list falls back to demo clips and a
        # missing data folder is remade empty, which is what the warning said.
        self._build_services()
        self._navigate("Library")

    def _start_setup(self, config=None, missing=()):
        """Show setup, with the rail hidden until it finishes.

        `config` seeds it with an existing install's settings, so coming back to
        re-point one folder does not also reset the others and the audio devices
        to their detected defaults; `missing` is what brought the user here.
        """
        self._hide_current()
        self.rail.grid_remove()
        self.current_view = FirstRunView(self.content, on_done=self._setup_done,
                                         config=config, missing=missing)
        self.current_view.grid(row=0, column=0, sticky="nsew")

    def _setup_done(self):
        """Setup wrote a complete config — bring up the app proper."""
        self._setup_pending = False
        self.rail.grid()
        self.config_data = self._load_config()
        self._build_services()
        self._navigate("Library")

    def _build_services(self):
        """(Re)create the thumbnail pool and DB from the current config dirs."""
        if self.thumbs is not None:
            self.thumbs.shutdown()
        if self.library is not None:
            self.library.close()
        self.thumbs = thumbnails.ThumbnailService(
            self.config_data.resolved_cache_dir(), tk_root=self
        )
        self.library = database.Library(self.config_data.resolved_data_dir())

    def open_clip(self, clip):
        """Replace the content area with the player for `clip`."""
        self._hide_current()
        self.current_view = player.PlayerView(
            self.content, clip.path, title=clip.name,
            on_back=lambda: self._navigate("Library"),
            on_delete=lambda: self._delete_open_clip(clip),
            on_trimmed=lambda mode, path: self._clip_trimmed(clip, mode, path),
            export_dir=self.config_data.export_path,
            library=self.library, clip_name=clip.name,
            config=self.config_data, recorded=clip.date,
        )
        self.current_view.grid(row=0, column=0, sticky="nsew")
        # The editor is the one view that takes the whole window. There is
        # nothing on the rail it can use — no search, no filter, no gauge worth
        # reading mid-trim — and Back is the way out, so the rail stands down
        # and the video gets the 250px.
        self.rail.grid_remove()

    def _clip_trimmed(self, clip, mode, trimmed_path):
        """The editor finished writing a trim of the open clip."""
        if self.clips_view is None or not self.clips_view.winfo_exists():
            return
        if mode == "copy":
            # A new file in the clip folder; it appears on the way back.
            self.clips_view.mark_stale()
            return
        # Replacing deletes the original, so leave the editor first: that
        # terminates mpv, which is still holding the file open.
        self._navigate("Library")
        self.clips_view.replace_clip(clip, trimmed_path)

    def _delete_open_clip(self, clip):
        """Delete from inside the editor, then drop back to the clip grid."""
        if not confirm_delete_clip(self, clip):
            return
        # Leave the editor first: that terminates mpv, so nothing is still
        # holding the file open when it moves to the Trash.
        self._navigate("Library")
        self.clips_view.remove_clip(clip)

    def _hide_current(self):
        """Take the current view off screen, keeping the clip grid alive.

        Rebuilding the grid means re-scanning the folder and recreating every
        card, which is slow enough to feel like a stall on the way back from the
        editor — and it would lose the scroll position with it.
        """
        view = self.current_view
        self.current_view = None
        if view is None:
            return
        if view is self.clips_view:
            view.save_scroll()
            view.grid_remove()
        else:
            view.destroy()

    def _navigate(self, name):
        self._hide_current()
        # Every view but the editor keeps the rail; the editor took it away.
        self.rail.grid()
        if name == "Library":
            if self.clips_view is None or not self.clips_view.winfo_exists():
                self.clips_view = ClipsView(
                    self.content, self.config_data, self.thumbs, self.library,
                    on_storage_changed=self.refresh_storage,
                )
            else:
                # The grid was only hidden, so a rename or a trim made in the
                # editor is not on its cards yet.
                self.clips_view.refresh()
            self.current_view = self.clips_view
        elif name == "Settings":
            self.current_view = SettingsView(
                self.content, on_saved=self._config_saved, library=self.library,
                on_imported=self._clips_imported,
            )
        else:
            self.current_view = ctk.CTkLabel(
                self.content, text=f"{name} — coming soon",
                text_color=TEXT_MUTED, font=ctk.CTkFont(size=18),
            )
        self.current_view.grid(row=0, column=0, sticky="nsew")
        if self.current_view is self.clips_view:
            self.current_view.restore_scroll()
            self._refresh_rail_lists()
        self.rail.set_mode("settings" if name == "Settings" else "library")
        self.refresh_storage()

    def _refresh_rail_lists(self):
        """Hand the rail the tags the grid has just loaded."""
        view = self.clips_view
        if view is None or not view.winfo_exists():
            return
        self.rail.set_library(view.tags(), view.favorites(), view.clip_count())

    def _search_changed(self):
        """The rail's search box settled. Re-filter whatever is on screen."""
        if self.clips_view is not None and self.current_view is self.clips_view:
            self.clips_view.set_query(self.rail.query())

    def _facet_changed(self, facet):
        """A rail row was clicked: narrow the grid to it, from wherever we are."""
        if self.clips_view is None or not self.clips_view.winfo_exists():
            return
        self.clips_view.set_facet(facet)
        if self.current_view is not self.clips_view:
            self._navigate("Library")

    def _show_section(self, section):
        if isinstance(self.current_view, SettingsView):
            self.current_view.show_section(section)

    def _show_settings(self, opening):
        """The cog: into Settings, and back out to the grid on a second press."""
        if not opening and not self._may_leave_settings():
            self.rail.set_mode("settings")   # the cog un-pressed itself
            return
        self._navigate("Settings" if opening else "Library")

    def _on_escape(self, _event=None):
        """Escape leaves Settings, the same as pressing the cog again.

        The editor binds Escape too (PlayerView._bind_keys) and this runs first,
        so it has to return None rather than "break" whenever Settings is not
        the view on screen — otherwise it would swallow the editor's own way
        out.
        """
        if not isinstance(self.current_view, SettingsView):
            return None
        self._show_settings(False)
        return "break"

    def _may_leave_settings(self):
        """Ask about unsaved settings. False means stay where we are.

        Every way out of Settings comes through here — the cog, Escape, and
        closing the window — because a guard one of them skips is not a guard.
        """
        view = self.current_view
        if not isinstance(view, SettingsView) or not view.is_dirty():
            return True
        answer = widgets.ChoiceDialog.ask(
            self,
            title="Unsaved settings",
            message="Save your settings before leaving?",
            # Named page by page, because Settings shows one at a time now: the
            # edit being asked about can be on a page that was never on screen.
            detail=f"{oxford(view.dirty_pages())} changed and hasn't been "
                   f"written yet.\n\nAnything you imported is already done and "
                   f"isn't affected either way.",
            choices=[("Save and go back", "save", False),
                     ("Discard changes", "discard", True)],
            cancel_text="Keep editing",
        )
        if answer == "save":
            # A failed write leaves the error on screen and us in Settings:
            # leaving anyway would throw away the edits the user just asked to
            # keep, which is the one thing this dialog exists to prevent.
            return view.save()
        return answer == "discard"

    def refresh_storage(self):
        """Re-read the clips drive and repaint the strip's gauge."""
        if self._setup_pending:
            return
        try:
            stats = core.storage_stats(self.config_data.clip_path)
        except OSError:
            stats = None   # folder gone or unreadable; leave the gauge blank
        self.rail.refresh_storage(stats)

    def _clips_imported(self):
        """An import from Settings changed the clips folder behind the grid."""
        if self.clips_view is not None and self.clips_view.winfo_exists():
            self.clips_view.mark_stale()
        # Those GB are on the drive now, and Settings no longer shows a meter
        # of its own — the strip's gauge is the only reading of them.
        self.refresh_storage()

    def _config_saved(self):
        # Reload config and rebuild services in case data/cache dirs changed.
        # The cached grid's cards hold the old thumbnail pool and DB, so it has
        # to go; the next navigation to the library builds a fresh one.
        self.config_data = self._load_config()
        self._build_services()
        # Branding is a live setting: redraw the rail and the window icon rather
        # than making the user restart to see the ink they just picked.
        self.rail.set_logo(self.config_data.logo_variant)
        apply_window_icon(self, self.config_data.logo_variant)
        # The clips folder may now be on a different drive entirely.
        self.refresh_storage()
        was_live = self.clips_view is not None and self.current_view is self.clips_view
        if self.clips_view is not None:
            if was_live:
                self.current_view = None
            self.clips_view.destroy()
            self.clips_view = None
        if was_live:
            self._navigate("Library")

    def _on_close(self):
        # Closing the window is the exit people use when they are done, so it is
        # the last one that should drop unsaved settings on the floor.
        if not self._may_leave_settings():
            return
        # mpv has to go before Tk starts destroying the surface it renders into.
        if isinstance(self.current_view, player.PlayerView):
            self.current_view.stop()
        # Both are still None if the window was closed during first-run setup.
        if self.thumbs is not None:
            self.thumbs.shutdown()
        if self.library is not None:
            self.library.close()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
