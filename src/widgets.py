"""Small widgets shared by the clip grid and the clip editor.

Kept out of gui.py because player.py needs them too, and gui.py imports
player.py — the dependency only works one way.
"""

import tkinter

import customtkinter as ctk

import core
import paint
from theme import (
    ACCENT, ACCENT_HOVER, CARD_BG, DANGER, DANGER_HOVER, FIELD_BG, HOVER_BG,
    MAIN_BG, PRIMARY_BUTTON, RADIUS_CONTROL, SIDEBAR_BG, TEXT_BRIGHT,
    TEXT_MUTED,
)


def attach_glow(widget, *, top, bottom, plateau, height, offset=0):
    """Light the top edge of `widget` with a band that fades into its ground.

    Build it before the widget's own children: Tk stacks siblings in creation
    order, so a backdrop made first sits under everything added afterwards.
    That is what makes this work at all — CustomTkinter has no transparency, so
    any widget over the band paints a flat rectangle, and the only way to have
    a gradient is to arrange for the widgets to sit where it is already flat
    (`plateau`) and to let it fall in the gap below them.

    `plateau` and `height` are in pixels from the top of the *window*, and
    `offset` is how far down the window `widget` starts — a view partway down
    the page passes its own offset and so continues the window's band instead
    of starting a second one out of step with it.
    """
    label = tkinter.Label(widget, bd=0, highlightthickness=0, bg=bottom)
    label.place(x=0, y=-offset, relwidth=1, height=height)

    def repaint(_event=None):
        width = widget.winfo_width()
        if width <= 1 or not label.winfo_exists():
            return      # not laid out yet; the <Configure> for it is coming
        image = paint.glow_surface(width, height, top=top, bottom=bottom,
                                   plateau=plateau / height)
        label.configure(image=image)
        label.image = image     # Tk drops an image nothing else refers to

    # Misc.bind: a CTk frame forwards bind to its canvas, and it is the frame
    # whose width the band has to match.
    tkinter.Misc.bind(widget, "<Configure>", repaint, add="+")
    widget.after(0, repaint)
    return label


class Tooltip:
    """A lightweight hover label (CustomTkinter has no built-in tooltip)."""

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._tip is not None or not self.widget.winfo_exists():
            return
        cx = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        top = self.widget.winfo_rooty()
        self._tip = tw = tkinter.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.configure(background=SIDEBAR_BG)
        tkinter.Label(
            tw, text=self.text, background=SIDEBAR_BG, foreground=TEXT_BRIGHT,
            padx=8, pady=4, font=("", 9),
        ).pack()
        tw.update_idletasks()
        tw.wm_geometry(f"+{cx - tw.winfo_width() // 2}+{top - tw.winfo_height() - 6}")

    def _hide(self, _=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _cancel(self):
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None


class Modal(ctk.CTkToplevel):
    """Shared plumbing for the app's small modal windows.

    A subclass builds its body in __init__ and calls `_present()` last; `ask`
    then shows it and returns whatever the subclass passed to `close`.
    """

    MIN_WIDTH = 400

    @classmethod
    def ask(cls, master, **kwargs):
        """Show the dialog and block until the user answers."""
        dialog = cls(master, **kwargs)
        try:
            master.wait_window(dialog)
        except tkinter.TclError:
            pass   # answered and torn down while it was still coming up
        return dialog.result

    def __init__(self, master, title, min_width=None):
        super().__init__(master)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=MAIN_BG)
        self.transient(master.winfo_toplevel())
        self.min_width = min_width or self.MIN_WIDTH

    def _present(self, master):
        """Place the window, take the grab, and wire the usual dismissals."""
        self.bind("<Escape>", lambda _e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(None))
        self._center_on(master)
        # A Toplevel can only be grabbed once X has actually mapped it. That
        # wait pumps events, so an answer can already have arrived (and torn
        # this window down) by the time it returns.
        try:
            self.wait_visibility()
            self.grab_set()
            self.focus_force()
        except tkinter.TclError:
            pass

    def _center_on(self, master):
        self.update_idletasks()
        width = max(self.min_width, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        top = master.winfo_toplevel()
        # A third of the way down reads better than dead centre.
        x = top.winfo_rootx() + (top.winfo_width() - width) // 2
        y = top.winfo_rooty() + (top.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def close(self, result=None):
        self.result = result
        try:
            self.grab_release()
        except tkinter.TclError:
            pass
        self.destroy()


class ChoiceDialog(Modal):
    """A small modal question. `ask` returns the chosen value, or None.

    `choices` are (label, value, danger) in the order they should be offered.
    One choice lays out as the familiar OK/Cancel row; more than one stacks into
    a column, which stays readable when the labels are whole sentences.
    """

    def __init__(self, master, title, message, detail="", choices=(),
                 cancel_text="Cancel", min_width=None):
        super().__init__(master, title, min_width)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        wrap = self.min_width - 60
        ctk.CTkLabel(
            body, text=message, font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w", justify="left", wraplength=wrap,
        ).pack(anchor="w")
        if detail:
            ctk.CTkLabel(
                body, text=detail, text_color=TEXT_MUTED, anchor="w",
                justify="left", font=ctk.CTkFont(size=12), wraplength=wrap,
            ).pack(anchor="w", pady=(10, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(22, 0))
        if len(choices) > 1:
            self._stacked_buttons(actions, choices, cancel_text)
        else:
            self._row_buttons(actions, choices, cancel_text)

        # Only a single-choice dialog gets a default action: with several, one
        # of them is usually destructive and Return should not pick anything.
        if len(choices) == 1:
            self.bind("<Return>", lambda _e: self.close(choices[0][1]))
        self._present(master)

    @staticmethod
    def _choice_colours(danger):
        """A choice button's fill. The safe one carries the lit accent edge."""
        if danger:
            return {"fg_color": DANGER, "hover_color": DANGER_HOVER}
        return dict(PRIMARY_BUTTON)

    def _row_buttons(self, actions, choices, cancel_text):
        for label, value, danger in choices:
            ctk.CTkButton(
                actions, text=label, width=110, corner_radius=RADIUS_CONTROL,
                command=lambda v=value: self.close(v),
                **self._choice_colours(danger),
            ).pack(side="right")
        ctk.CTkButton(
            actions, text=cancel_text, width=110, fg_color=CARD_BG,
            corner_radius=RADIUS_CONTROL, hover_color=HOVER_BG,
            command=lambda: self.close(None),
        ).pack(side="right", padx=(0, 8))

    def _stacked_buttons(self, actions, choices, cancel_text):
        for index, (label, value, danger) in enumerate(choices):
            ctk.CTkButton(
                actions, text=label, height=36, anchor="center",
                corner_radius=RADIUS_CONTROL,
                command=lambda v=value: self.close(v),
                **self._choice_colours(danger),
            ).pack(fill="x", pady=(0 if index == 0 else 8, 0))
        ctk.CTkButton(
            actions, text=cancel_text, height=36, fg_color=CARD_BG,
            corner_radius=RADIUS_CONTROL, hover_color=HOVER_BG,
            command=lambda: self.close(None),
        ).pack(fill="x", pady=(8, 0))


class SuggestEntry(ctk.CTkEntry):
    """Entry that offers tags already used elsewhere in the library.

    `suggestions()` is called each time the list is rebuilt, so it reflects the
    tags on the field right now — one already picked is not offered again.
    `on_commit(text)` fires on Return, or when a suggestion is picked with the
    mouse or the arrow keys.
    """

    MAX_ROWS = 6          # a taller list would cover the rest of the dialog
    HIDE_DELAY = 120      # ms; long enough for a click on a row to land first

    def __init__(self, master, suggestions, on_commit, placeholder="", width=200):
        super().__init__(
            master, width=width, height=30, corner_radius=6, border_width=1,
            border_color=FIELD_BG, fg_color=FIELD_BG, font=ctk.CTkFont(size=12),
            placeholder_text=placeholder,
        )
        self._suggestions = suggestions
        self._on_commit = on_commit
        self._popup = None      # borderless Toplevel holding the list, while shown
        self._list = None
        self._hide_job = None
        # The list is a plain Listbox, so it needs the entry's font handed to it
        # to match — and a reference held, or the Tcl font goes with the garbage.
        self._list_font = ctk.CTkFont(size=12)

        self.bind("<KeyRelease>", self._on_key)
        self.bind("<Return>", self._on_return)
        self.bind("<Escape>", self._on_escape)
        self.bind("<Down>", lambda _e: self._step(1))
        self.bind("<Up>", lambda _e: self._step(-1))
        # Leaving the field puts the list away, but not before a click that is
        # landing on one of its rows has been dispatched.
        self.bind("<FocusOut>", lambda _e: self._hide_soon())
        self.bind("<Destroy>", lambda _e: self._hide())

    # --- Matching ----------------------------------------------------------

    def _matches(self):
        """Suggestions for what is typed: prefix matches first, then the rest."""
        typed = core.clean_tag(self.get()).casefold()
        pool = [tag for tag in self._suggestions() if tag]
        starts = [tag for tag in pool if tag.casefold().startswith(typed)]
        rest = [tag for tag in pool
                if typed in tag.casefold() and tag not in starts]
        return (starts + rest)[:self.MAX_ROWS]

    # --- Suggestion list ---------------------------------------------------

    def _on_key(self, event=None):
        # Return/Escape/arrows have their own handlers and must not also
        # rebuild (and so deselect) the list underneath them.
        if event is not None and event.keysym in (
            "Return", "Escape", "Up", "Down", "Tab",
        ):
            return
        self._cancel_hide()
        self._show(self._matches())

    def _show(self, options):
        if not options or not self.winfo_exists():
            self._hide()
            return
        if self._popup is None:
            # A borderless Toplevel, like the tooltip in gui.py: it floats over
            # the dialog without becoming a window in its own right. Its 1px of
            # padding around the list is what draws the accent border.
            self._popup = tkinter.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.configure(bg=ACCENT)
            self._list = tkinter.Listbox(
                self._popup, activestyle="none", borderwidth=0, takefocus=False,
                highlightthickness=0, exportselection=False, bg=CARD_BG,
                fg=TEXT_BRIGHT, selectbackground=ACCENT, selectforeground="#ffffff",
                selectborderwidth=0, font=self._list_font,
            )
            self._list.pack(fill="both", expand=True, padx=1, pady=1)
            self._list.bind("<ButtonRelease-1>", self._on_click)

        self._list.delete(0, "end")
        for option in options:
            self._list.insert("end", option)
        self._list.configure(height=len(options))
        self._place()

    def _place(self):
        """Hang the list off the bottom-left of the field."""
        self._popup.update_idletasks()
        width = max(self.winfo_width(), 160)
        height = self._popup.winfo_reqheight()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        self._popup.wm_geometry(f"{width}x{height}+{x}+{y}")
        self._popup.lift()

    def _hide(self, _event=None):
        self._cancel_hide()
        popup, self._popup, self._list = self._popup, None, None
        if popup is not None:
            try:
                popup.destroy()
            except tkinter.TclError:
                pass   # already went with the window that owned it

    def _hide_soon(self):
        self._cancel_hide()
        try:
            self._hide_job = self.after(self.HIDE_DELAY, self._hide)
        except tkinter.TclError:
            pass

    def _cancel_hide(self):
        job, self._hide_job = self._hide_job, None
        if job is not None:
            try:
                self.after_cancel(job)
            except (tkinter.TclError, ValueError):
                pass

    def _selected(self):
        if self._list is None:
            return None
        selection = self._list.curselection()
        return self._list.get(selection[0]) if selection else None

    def _step(self, delta):
        """Arrow keys walk the list, opening it first if it is not up yet."""
        if self._list is None:
            self._show(self._matches())
            if self._list is None:
                return "break"
        size = self._list.size()
        current = self._list.curselection()
        index = (current[0] + delta) % size if current else (0 if delta > 0 else size - 1)
        self._list.selection_clear(0, "end")
        self._list.selection_set(index)
        self._list.see(index)
        return "break"

    # --- Committing --------------------------------------------------------

    def _on_click(self, event):
        index = self._list.nearest(event.y)
        if index >= 0:
            self._commit(self._list.get(index))
        return "break"

    def _on_return(self, _event=None):
        # A highlighted suggestion wins over the half-typed text that matched it.
        picked = self._selected()
        self._commit(picked if picked is not None else self.get())
        return "break"

    def _on_escape(self, _event=None):
        # Only swallow Escape while the list is up; otherwise it should still
        # reach the dialog and close it.
        if self._popup is None:
            return None
        self._hide()
        return "break"

    def commit_typed(self):
        """Take whatever is half-typed as a tag. Used when the dialog is saved:
        nobody types a name and then means to throw it away."""
        if self.winfo_exists():
            self._commit(self.get())

    def _commit(self, text):
        text = core.clean_tag(text)
        self._hide()
        if not text:
            return
        # Clear before handing the tag over: the callback may take the field
        # away (a single-tag field hides it once it is filled).
        self.delete(0, "end")
        self._on_commit(text)


class TagChip(ctk.CTkFrame):
    """One tag, with an × that takes it off the clip."""

    def __init__(self, master, text, on_remove):
        super().__init__(master, fg_color=FIELD_BG, corner_radius=13, height=26)
        ctk.CTkLabel(
            self, text=text, font=ctk.CTkFont(size=12), text_color=TEXT_BRIGHT,
        ).pack(side="left", padx=(10, 4))
        # A label rather than a button: removing a chip destroys it from inside
        # this very callback, and a CTkButton would still be running its click
        # animation on the widget that just went away.
        close = ctk.CTkLabel(
            self, text="✕", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
            width=14, cursor="hand2",
        )
        close.pack(side="left", padx=(0, 8))
        close.bind("<Button-1>", lambda _e: on_remove(text))
        close.bind("<Enter>", lambda _e: close.configure(text_color=DANGER))
        close.bind("<Leave>", lambda _e: close.configure(text_color=TEXT_MUTED))


class TagField(ctk.CTkFrame):
    """A row of tag chips plus an entry that suggests tags used elsewhere.

    `single` keeps at most one tag — the game a clip was recorded in — and puts
    the entry away while it is set; otherwise the field collects a list, such as
    the people in the clip. `suggestions` is the pool of tags typed on any clip
    so far; the ones already on this field are filtered out of it as it is shown.
    """

    def __init__(self, master, tags=(), single=False, suggestions=(),
                 placeholder="Add a tag…", on_change=None, entry_width=220):
        super().__init__(master, fg_color="transparent")
        self._tags = core.clean_tags([tags] if isinstance(tags, str) else tags)
        self._single = single
        self._pool = list(suggestions)
        self._on_change = on_change
        self._chips = []

        self.entry = SuggestEntry(self, self._offer, self.add,
                                  placeholder=placeholder, width=entry_width)
        self._render()

    # --- Tags --------------------------------------------------------------

    def get(self):
        """The tags on the field, in the order they were added."""
        return list(self._tags)

    def add(self, text):
        tag = core.clean_tag(text)
        if not tag:
            return
        if self._single:
            self._tags = [tag]
        elif tag.casefold() in {existing.casefold() for existing in self._tags}:
            return   # already on this clip
        else:
            self._tags.append(tag)
        self._render()
        self._changed()

    def remove(self, tag):
        self._tags = [t for t in self._tags if t.casefold() != tag.casefold()]
        self._render()
        self._changed()
        # Removing the one tag of a single field brings the entry back; put the
        # cursor in it, since replacing the tag is the reason to remove it.
        if self._single:
            self.entry.focus_set()

    def _changed(self):
        if self._on_change is not None:
            self._on_change(self.get())

    def commit_pending(self):
        """Adopt anything still sitting in the entry, uncommitted."""
        self.entry.commit_typed()

    def _offer(self):
        """The suggestion pool minus what this clip already carries."""
        taken = {tag.casefold() for tag in self._tags}
        return [tag for tag in self._pool if tag.casefold() not in taken]

    # --- Layout ------------------------------------------------------------

    def _render(self):
        for chip in self._chips:
            chip.destroy()
        self._chips = [TagChip(self, tag, self.remove) for tag in self._tags]
        for chip in self._chips:
            chip.pack(side="left", padx=(0, 6), pady=2)
        # Repacked after the chips every time, so it stays at the end of the row.
        self.entry.pack_forget()
        if not (self._single and self._tags):
            self.entry.pack(side="left", pady=2)


class TagDialog(Modal):
    """Edit one clip's tags. `ask` returns (game, people), or None if cancelled.

    `games` and `people_pool` are every tag typed on any clip so far — see
    database.Library.known_games / known_people.
    """

    MIN_WIDTH = 460

    def __init__(self, master, clip="", game="", people=(), games=(),
                 people_pool=()):
        super().__init__(master, "Tags")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(22, 18))
        ctk.CTkLabel(
            body, text="Tags", font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
        ).pack(anchor="w")
        if clip:
            ctk.CTkLabel(
                body, text=clip, text_color=TEXT_MUTED, anchor="w",
                font=ctk.CTkFont(size=12), wraplength=self.MIN_WIDTH - 60,
            ).pack(anchor="w", pady=(2, 0))

        self.game_field = self._section(
            body, "GAME", tags=game, single=True, suggestions=games,
            placeholder="Which game?", pady=(18, 0),
        )
        self.people_field = self._section(
            body, "PEOPLE (OPTIONAL)", tags=people, single=False,
            suggestions=people_pool, placeholder="Who was in it?", pady=(16, 0),
        )

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(22, 0))
        ctk.CTkButton(
            actions, text="Save", width=110, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self._save,
        ).pack(side="right")
        ctk.CTkButton(
            actions, text="Cancel", width=110, fg_color=CARD_BG,
            hover_color=HOVER_BG, command=lambda: self.close(None),
        ).pack(side="right", padx=(0, 8))

        # Return inside a field adds the tag being typed (the field swallows it
        # first); anywhere else it saves.
        self.bind("<Return>", lambda _e: self._save())
        self._present(master)
        self.game_field.entry.focus_set()

    def _section(self, body, heading, tags, single, suggestions, placeholder,
                 pady):
        ctk.CTkLabel(
            body, text=heading, text_color=TEXT_MUTED, anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", pady=pady)
        field = TagField(
            body, tags=tags, single=single, suggestions=suggestions,
            placeholder=placeholder,
        )
        field.pack(fill="x", anchor="w", pady=(4, 0))
        return field

    def _save(self):
        self.game_field.commit_pending()
        self.people_field.commit_pending()
        game = self.game_field.get()
        self.close((game[0] if game else "", self.people_field.get()))


class EditableLabel(ctk.CTkFrame):
    """A label that swaps to an entry when clicked, for renaming in place.

    `on_commit(text)` receives the new text (stripped) and returns the text to
    display — so the caller can fall back to a default when the field is
    cleared. Nothing here touches the clip on disk; the title is display-only
    metadata as far as this widget is concerned.

    `display(text, pixels)` shortens what the label shows without touching what
    is stored or what you get when you click to edit. Tk labels clip rather
    than ellipsize, so on a narrow card a long file name otherwise runs under
    whatever sits beside it with no sign it has been cut.

    `pixels` is how much room the text actually has, and it is re-applied every
    time that changes. A card's width follows the window and the rail, so a
    caller shortening to a fixed number of characters is wrong at every size
    but one — cutting names that would have fitted, and still overflowing when
    the card is narrower than it guessed.
    """

    # Auto-fit bounds, so a long clip name neither squeezes the row it sits in
    # nor leaves a tiny field to type into.
    MIN_WIDTH = 140
    MAX_WIDTH = 520

    # What the label's own padding costs, so `pixels` is room for text and not
    # room for the widget.
    LABEL_PAD = 12

    def __init__(self, master, text, on_commit, font=None, text_color=None,
                 anchor="w", height=24, hover_color=HOVER_BG, autofit=False,
                 display=None):
        # Square-cornered for speed, not for looks: rounding a CustomTkinter
        # frame draws anti-aliased corner shapes onto its canvas, and a
        # transparent frame paints nothing for them to round.
        super().__init__(master, fg_color="transparent", height=height,
                         corner_radius=0)
        self._text = text
        self._on_commit = on_commit
        self._font = font or ctk.CTkFont(size=13, weight="bold")
        self._hover_color = hover_color
        self._autofit = autofit
        self._display = display or (lambda value, _pixels: value)
        self._entry = None
        self._pixels = 0      # room for the text; set by the first <Configure>

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_propagate(False)
        self._fit()

        self.label = ctk.CTkLabel(
            self, text=self._shown(), font=self._font,
            text_color=text_color,
            anchor=anchor, height=height, corner_radius=6, padx=4,
            cursor="xterm",
        )
        self.label.grid(row=0, column=0, sticky="ew")
        self.label.bind("<Button-1>", self.begin_edit)
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)
        # Misc.bind, not self.bind: a CTk frame forwards bind to its canvas,
        # and it is this frame's width that says how much room the text has.
        tkinter.Misc.bind(self, "<Configure>", self._on_resize, add="+")

    # --- Text --------------------------------------------------------------

    def get(self):
        return self._text

    def _shown(self):
        """What the label displays: the text, cut to the room it has."""
        return self._display(self._text, self._pixels)

    def set(self, text):
        """Update the displayed text from outside (e.g. after a reload)."""
        self._text = text
        if self._entry is None and self.label.winfo_exists():
            self.label.configure(text=self._shown())
            self._fit()

    def _on_resize(self, event):
        """Re-cut the text when the room for it changes.

        Nothing here feeds back into the layout: propagation is off, so the
        frame's own width is whatever it was given and never follows the text
        inside it. That is what makes re-cutting on every resize safe.
        """
        pixels = max(0, event.width - self.LABEL_PAD)
        if pixels == self._pixels:
            return
        self._pixels = pixels
        if self._entry is None and self.label.winfo_exists():
            self.label.configure(text=self._shown())

    def _fit(self):
        """Size the frame to its text — pack/grid can't do it: propagation is
        off, which is what keeps the height fixed while swapping in the entry."""
        if not self._autofit:
            return
        width = self._font.measure(self._text) + 28
        self.configure(width=max(self.MIN_WIDTH, min(width, self.MAX_WIDTH)))

    # --- Hover -------------------------------------------------------------

    def _on_enter(self, _event=None):
        if self._entry is None:
            self.label.configure(fg_color=self._hover_color)

    def _on_leave(self, _event=None):
        if self._entry is None:
            self.label.configure(fg_color="transparent")

    # --- Editing -----------------------------------------------------------

    def begin_edit(self, _event=None):
        if self._entry is not None:
            return "break"
        self.label.configure(fg_color="transparent")
        self.label.grid_remove()

        entry = self._entry = ctk.CTkEntry(
            self, font=self._font, height=self.cget("height"),
            corner_radius=6, border_width=1, border_color=ACCENT,
            fg_color=FIELD_BG,
        )
        entry.grid(row=0, column=0, sticky="ew")
        entry.insert(0, self._text)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.focus_set()
        # "break" keeps Return/Escape from also reaching the editor's global
        # shortcuts, which would toggle playback or leave the clip.
        entry.bind("<Return>", lambda _e: self._finish(commit=True))
        entry.bind("<Escape>", lambda _e: self._finish(commit=False))
        # Clicking away is a commit, like every other rename field.
        entry.bind("<FocusOut>", lambda _e: self._finish(commit=True, refocus=False))
        return "break"

    def _finish(self, commit, refocus=True):
        entry, self._entry = self._entry, None
        if entry is None:
            return "break"
        text = entry.get().strip() if commit else None
        try:
            entry.destroy()
        except tkinter.TclError:
            pass   # already torn down with the view

        if text is not None:
            result = self._on_commit(text)
            self._text = result if result is not None else text
        if not self.label.winfo_exists():
            return "break"
        self.label.configure(text=self._shown())
        self.label.grid()
        self._fit()
        # Hand focus back so Space/Escape drive the player again — but not when
        # the user clicked elsewhere, or we would steal focus from what they hit.
        if refocus:
            try:
                self.winfo_toplevel().focus_set()
            except tkinter.TclError:
                pass
        return "break"
