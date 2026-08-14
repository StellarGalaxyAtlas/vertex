"""'Export clip' window: a preview, a file size to aim for, and a progress bar.

Modelled on the SteelSeries Moments share sheet — pick how big the file may be,
and the clip is written into the configured Exports folder. "Original" copies
the source video through untouched; the capped sizes re-encode down to fit the
tier chat platforms enforce.

The encode is staged next to its destination under a hidden name and moved into
place only once it finishes, so a cancelled export leaves nothing behind.

export.py holds the sizing maths and the ffmpeg commands; this is only the
window around them.
"""

import os
import queue
import shutil
import subprocess
import tempfile
import threading
import tkinter

import customtkinter as ctk
from PIL import Image, ImageTk

import core
import export

PANEL_BG = "#15181e"
CARD_BG = "#20242d"
ACCENT = "#4c6ef5"
ACCENT_HOVER = "#3b5bdb"
TEXT_MUTED = "#8b93a1"
OK_GREEN = "#3fb950"
WARN = "#e6b422"
DANGER = "#e5534b"

THUMB_W = 460


class ExportWindow(ctk.CTkToplevel):
    def __init__(self, master, clip_path, start, end, tracks, info,
                 clip_name="clip", export_dir=""):
        super().__init__(master)
        self.title("Export clip")
        self.geometry("520x600")
        self.resizable(False, False)
        self.configure(fg_color=PANEL_BG)
        self.transient(master.winfo_toplevel())

        self.clip_path = clip_path
        self.start, self.end = start, end
        self.tracks, self.info = tracks, info
        self.clip_name = clip_name
        self.export_dir = export_dir

        self.selection = max(0.0, end - start)
        self.limit = export.SIZE_CHOICES[0][1]     # "Original" to begin with
        self.out_path = None        # the finished file, once there is one

        self._events = queue.Queue()
        self._cancel = threading.Event()
        self._thread = None
        self._staged = None         # partial file, until it is moved into place
        self._photo = None          # ImageTk reference, or the preview is collected
        self._workdir = tempfile.mkdtemp(prefix="gsm-export-")   # preview frame

        self._build()
        self._describe_choice()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self._pump()
        self._start_preview()

    # --- Layout ------------------------------------------------------------

    def _build(self):
        ctk.CTkLabel(
            self, text="Export clip", font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(16, 2))
        ctk.CTkLabel(
            self,
            text=f"{core.format_duration(self.start)} – "
                 f"{core.format_duration(self.end)}  "
                 f"({core.format_duration(self.selection)})",
            text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
        ).pack()

        ctk.CTkLabel(
            self, text="Choose a File Size",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(pady=(16, 6))
        self.sizes = ctk.CTkSegmentedButton(
            self, values=[label for label, _ in export.SIZE_CHOICES],
            # fg_color is what shows between the segments; matching the
            # unselected ones turns the row into one bar with a lit-up pill.
            fg_color=CARD_BG, border_width=2,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            unselected_color=CARD_BG, unselected_hover_color="#2c3242",
            font=ctk.CTkFont(size=12), height=32, command=self._on_size,
        )
        self.sizes.set(export.SIZE_CHOICES[0][0])
        self.sizes.pack(padx=20, fill="x")
        self.detail = ctk.CTkLabel(
            self, text="", text_color=TEXT_MUTED, font=ctk.CTkFont(size=11),
        )
        self.detail.pack(pady=(6, 0))

        # Fixed-size holder: a Tk label sizes in characters while it shows text
        # and in pixels once it shows an image, so the frame keeps the layout
        # from jumping when the preview arrives.
        holder = tkinter.Frame(self, bg=CARD_BG, highlightthickness=0,
                               width=THUMB_W, height=int(THUMB_W * 9 / 16))
        holder.pack(padx=20, pady=12)
        holder.pack_propagate(False)
        self.thumb = tkinter.Label(
            holder, bg=CARD_BG, bd=0, highlightthickness=0,
            text="Preparing preview…", fg=TEXT_MUTED,
        )
        self.thumb.pack(fill="both", expand=True)
        tkinter.Label(
            holder, text=core.format_duration(self.selection), bg="#0b0d11",
            fg="#e8eaed", bd=0, highlightthickness=0, padx=6, pady=1,
        ).place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")

        self.progress = ctk.CTkProgressBar(self, progress_color=ACCENT, height=10)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20)
        self.status = ctk.CTkLabel(
            self, text=f"Saves to {self._display_dir()}", text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11), wraplength=THUMB_W,
        )
        self.status.pack(pady=(8, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", padx=20, pady=16)
        self.cancel_btn = ctk.CTkButton(
            buttons, text="Close", width=100, fg_color=CARD_BG,
            hover_color="#2c3242", command=self.close,
        )
        self.cancel_btn.pack(side="left")
        self.export_btn = ctk.CTkButton(
            buttons, text="Export", width=110, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, command=self.start_export,
        )
        self.export_btn.pack(side="right")
        self.folder_btn = ctk.CTkButton(
            buttons, text="Open folder", width=110, fg_color=CARD_BG,
            hover_color="#2c3242", command=self.open_folder, state="disabled",
        )
        self.folder_btn.pack(side="right", padx=8)

    # --- Size choice -------------------------------------------------------

    def _on_size(self, label):
        for name, limit in export.SIZE_CHOICES:
            if name == label:
                self.limit = limit
                break
        self._describe_choice()

    def _describe_choice(self):
        """Say what the selected size would produce, and whether it can."""
        text, possible = self._describe(self.limit)
        self.detail.configure(text=text,
                              text_color=TEXT_MUTED if possible else WARN)
        if self._thread is None:
            self.export_btn.configure(state="normal" if possible else "disabled")

    def _describe(self, limit):
        """(description, can it be exported at all) for one size choice."""
        original = export.copy_estimate(self.info, self.selection)
        if limit is None:
            summary = self.info.summary or "Source quality"
            if original:
                summary += f" · ≈{core.format_size(original, 0)}"
            # The video is copied, so the cut lands on a keyframe and the export
            # can open a moment before the In marker. Worth saying: the capped
            # sizes re-encode and are exact.
            return f"{summary}  —  untouched video, cut on a keyframe", True

        try:
            plan = export.plan(
                self.selection, self.info.width, self.info.height, self.info.fps,
                export.audio_filter(self.tracks) is not None, limit,
            )
        except export.ExportError as exc:
            return str(exc), False
        estimate = (plan.video_kbps + plan.audio_kbps) * 1000 * self.selection / 8
        text = f"{plan.summary} · ≈{core.format_size(estimate, 0)}"
        if original and original <= limit:
            # Re-encoding to a cap the untouched clip already meets only costs
            # quality, so it is worth saying so before they spend the time.
            text += "  —  Original already fits"
        return text, True

    # --- Preview -----------------------------------------------------------

    def _start_preview(self):
        threading.Thread(target=self._preview_worker, daemon=True).start()

    def _preview_worker(self):
        try:
            path = os.path.join(self._workdir, "preview.jpg")
            export.grab_frame(self.clip_path, self.start, path, THUMB_W)
            self._events.put(("preview", path))
        except (export.ExportError, OSError):
            self._events.put(("preview", None))

    def _show_preview(self, path):
        if not path or not os.path.exists(path):
            self.thumb.configure(text="No preview")
            return
        try:
            self._photo = ImageTk.PhotoImage(Image.open(path))
        except OSError:
            self.thumb.configure(text="No preview")
            return
        self.thumb.configure(image=self._photo, text="")

    # --- Export ------------------------------------------------------------

    def _target_dir(self):
        """The Exports folder, or the clip's own folder if none is configured."""
        folder = core.normalize_path(self.export_dir)
        return folder or os.path.dirname(os.path.abspath(self.clip_path))

    def _display_dir(self):
        """The destination as it is worth showing — home written as '~'."""
        folder = self._target_dir()
        home = os.path.expanduser("~")
        if folder == home or folder.startswith(home + os.sep):
            return "~" + folder[len(home):]
        return folder

    def _target_paths(self, folder, label):
        """(final, staged) names in `folder`, tagged with the size asked for.

        The staged name keeps the .mp4 suffix — ffmpeg picks its muxer from the
        extension — and leads with a dot, so a folder scan mid-export ignores a
        half-written file.
        """
        stem = os.path.splitext(os.path.basename(self.clip_name))[0]
        base = f"{stem} ({label.replace(' ', '')})"
        count = 2
        candidate = os.path.join(folder, f"{base}.mp4")
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{base} {count}.mp4")
            count += 1
        staged = os.path.join(
            folder, f".{os.path.splitext(os.path.basename(candidate))[0]}"
                    ".gsm-export.mp4"
        )
        return candidate, staged

    def start_export(self):
        if self._thread is not None:
            return
        folder = self._target_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self._fail(f"Could not open the export folder: {exc}")
            return

        # Staged beside the destination, so the move into place is a rename on
        # the same filesystem and a cancelled export leaves nothing behind.
        final, self._staged = self._target_paths(folder, self.sizes.get())

        self._cancel.clear()
        self.progress.set(0)
        self.sizes.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")
        self.status.configure(text="Starting…", text_color=TEXT_MUTED)
        self._thread = threading.Thread(
            target=self._worker, args=(self._staged, final, self.limit),
            daemon=True,
        )
        self._thread.start()

    def _worker(self, staged, final, limit):
        try:
            size = export.run(
                self.clip_path, staged, self.start, self.end,
                self.tracks, self.info, limit=limit,
                on_progress=lambda f: self._events.put(("progress", f)),
                cancel=self._cancel,
            )
            os.replace(staged, final)
            self._events.put(("done", (final, size, limit)))
        except export.ExportError as exc:
            self._events.put(("failed", str(exc)))
        except OSError as exc:
            self._events.put(("failed", f"Could not save the export: {exc}"))
        except Exception as exc:                          # noqa: BLE001
            self._events.put(("failed", f"Export failed: {exc}"))

    # --- Events ------------------------------------------------------------

    def _pump(self):
        if not self.winfo_exists():
            return
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "preview":
                self._show_preview(payload)
            elif kind == "progress":
                self.progress.set(payload)
                verb = "Copying" if self.limit is None else "Converting"
                self.status.configure(text=f"{verb}… {payload * 100:.0f}%",
                                      text_color=TEXT_MUTED)
            elif kind == "done":
                self._finish(*payload)
            elif kind == "failed":
                self._fail(payload)
        self.after(100, self._pump)

    def _finish(self, path, size, limit):
        self._thread = None
        self._staged = None         # moved into place; nothing left to clean up
        self.out_path = path
        self.progress.set(1)
        self._release_controls()
        self.folder_btn.configure(state="normal")
        over = limit is not None and size > limit
        self.status.configure(
            text=f"Saved {os.path.basename(path)} · {core.format_size(size)}"
                 + ("  —  over the size limit" if over else ""),
            text_color=WARN if over else OK_GREEN,
        )

    def _fail(self, message):
        self._thread = None
        self._discard_staged()
        self.progress.set(0)
        self._release_controls()
        self.status.configure(text=message, text_color=DANGER)

    def _release_controls(self):
        """Hand the window back so another size can be exported."""
        self.sizes.configure(state="normal")
        self._describe_choice()

    def _discard_staged(self):
        staged, self._staged = self._staged, None
        if not staged:
            return
        try:
            os.remove(staged)
        except OSError:
            pass   # never written, or already gone

    # --- Actions -----------------------------------------------------------

    def open_folder(self):
        folder = os.path.dirname(self.out_path or "") or self._target_dir()
        try:
            subprocess.Popen(["xdg-open", folder])
        except OSError:
            pass

    # --- Teardown ----------------------------------------------------------

    def close(self):
        self._cancel.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        self._discard_staged()
        shutil.rmtree(self._workdir, ignore_errors=True)
        self.destroy()
