"""The clip editor: video, transport, live per-track mixer, timeline and trim.

Edits are saved to the library as they are made (debounced) and the clip file
is never touched — except by an explicit trim, which writes a new file.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vertex import fmt
from vertex.core import clips as clips_mod
from vertex.media import mixing, probe, trim, waveform
from vertex.media import tracks as track_labels
from vertex.media.export import copy_estimate
from vertex.media.ffmpeg import MediaError
from vertex.ui import theme, workers
from vertex.ui.dialogs.export import ExportDialog
from vertex.ui.dialogs.tags import TagDialog
from vertex.ui.editor.mixer import PANEL_W, TrackRow
from vertex.ui.editor.timeline import LANE_GAP, LANE_H, RULER_H, Timeline
from vertex.ui.widgets import ChoiceDialog, EditableLabel, IconButton, button, label

SEEK_STEP = 5.0
SAVE_DELAY_MS = 800


class EditorView(QWidget):
    back = Signal()
    delete_requested = Signal(object)            # clip
    trimmed = Signal(object, str, str)           # clip, mode ("copy"|"replace"), path

    def __init__(self, context, state, clip, parent=None):
        super().__init__(parent)
        self.context = context
        self.state = state
        self.clip = clip
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        try:
            self.info = probe.probe(clip.path)
        except MediaError:
            self.info = probe.MediaInfo()
        self.tracks = track_labels.label_tracks(self.info.tracks)
        self.duration = self.info.duration
        self.trim_start, self.trim_end = 0.0, self.duration
        self.position = 0.0
        self._suppress_until = 0.0
        self._closing = False
        self._waves_cancel = workers.Cancel()
        self._waves_started = False
        self._waves_pool = None
        self._trim_job = None
        self._restore()

        self._save_timer = QTimer(self, singleShot=True, interval=SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)
        self._poll_timer = QTimer(self, interval=50)
        self._poll_timer.timeout.connect(self._poll)

        self.player_widget = None        # created by _build
        self._build()
        QTimer.singleShot(0, self._start_player)
        QTimer.singleShot(150, self._start_waves)

    # --- Saved state ---------------------------------------------------------

    def _restore(self) -> None:
        library = self.context.library
        if library is None:
            return
        edit = library.get_edit(self.clip.name)
        if self.duration:
            if edit.trim_start is not None:
                self.trim_start = max(0.0, min(edit.trim_start, self.duration))
            if edit.trim_end is not None:
                self.trim_end = max(self.trim_start + 0.1, min(edit.trim_end, self.duration))
        for track in self.tracks:
            saved = edit.mix_for(track.name)
            if saved is not None:
                track.volume, track.muted = max(0.0, min(1.5, saved.volume)), saved.muted

    def _mark_dirty(self) -> None:
        self._save_timer.start()

    def _save(self) -> None:
        library = self.context.library
        if library is None or not self.duration:
            return
        trimmed = self.trim_start > 0.05 or self.trim_end < self.duration - 0.05
        library.set_trim(self.clip.name, self.trim_start if trimmed else None,
                         self.trim_end if trimmed else None)
        library.set_volumes(self.clip.name, {
            track.name: {"volume": round(track.volume, 3), "muted": track.muted}
            for track in self.tracks})

    # --- Layout ----------------------------------------------------------------

    def _build(self) -> None:
        from vertex.ui.editor.mpv_widget import MpvWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.CONTENT_MARGIN - 8, 14, theme.CONTENT_MARGIN - 8, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        back = button("Back", "ghost", "back", self.back.emit, "Back to the library (Esc)")
        header.addWidget(back)
        self.title = EditableLabel(self.state.title_of(self.clip), self.clip.name)
        self.title.display.setObjectName("Subheading")
        self.title.committed.connect(self._rename)
        self.title.setMaximumWidth(520)
        header.addWidget(self.title, 1)
        meta = label(self._meta(), "Muted")
        header.addWidget(meta)
        self.tags_button = QPushButton(self._tag_text())
        self.tags_button.setObjectName("Chip")
        theme.style(self.tags_button, lambda: (
            f"QPushButton {{ background: {theme.CARD_BG}; border-radius: 8px; padding: 5px 12px;"
            f" color: {theme.TEXT_MUTED}; }} QPushButton:hover {{ color: {theme.TEXT}; }}"))
        self.tags_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tags_button.clicked.connect(self._edit_tags)
        header.addWidget(self.tags_button)
        header.addStretch(0)
        delete = button("Delete", "danger", "trash",
                        lambda: self.delete_requested.emit(self.clip))
        header.addWidget(delete)
        layout.addLayout(header)

        self.player_widget = MpvWidget()
        self.player_widget.clicked.connect(self.toggle_play)
        self.player_widget.double_clicked.connect(self._toggle_fullscreen)
        layout.addWidget(self.player_widget, 1)

        transport = QHBoxLayout()
        transport.setSpacing(6)
        self.in_button = IconButton("mark-in", "Set In at the playhead (I)", 20)
        self.in_button.clicked.connect(self.set_in)
        transport.addWidget(self.in_button)
        self.play_button = IconButton("pause", "Play / pause (Space)", 22, "ON_ACCENT",
                                      kind="")
        theme.style(self.play_button, lambda: (
            f"QToolButton {{ background: {theme.ACCENT_FILL}; border-radius: 10px; padding: 7px; "
            f"border: 1px solid {theme.ACCENT_FILL_EDGE}; }}"
            f"QToolButton:hover {{ background: {theme.ACCENT_HOVER}; }}"))
        self.play_button.clicked.connect(self.toggle_play)
        transport.addWidget(self.play_button)
        self.out_button = IconButton("mark-out", "Set Out at the playhead (O)", 20)
        self.out_button.clicked.connect(self.set_out)
        transport.addWidget(self.out_button)
        reset = IconButton("reset", "Select the whole clip", 18)
        reset.clicked.connect(self.reset_trim)
        transport.addSpacing(6)
        transport.addWidget(reset)
        self.time_label = label("0:00 / 0:00")
        self.time_label.setMinimumWidth(110)
        transport.addSpacing(10)
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        self.status = label("", "Muted")
        transport.addWidget(self.status)
        transport.addSpacing(8)
        self.trim_button = button("Trim", icon="scissors", on_click=self.confirm_trim,
                                  tooltip="Cut the clip down to the selection")
        transport.addWidget(self.trim_button)
        self.export_button = button("Export", "primary", "export", self.start_export,
                                    "Make a shareable file of the selection")
        transport.addWidget(self.export_button)
        for widget in (self.trim_button, self.export_button):
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addLayout(transport)

        editor = QGridLayout()
        editor.setHorizontalSpacing(8)
        editor.setVerticalSpacing(0)
        mixer = QWidget()
        mixer.setFixedWidth(PANEL_W)
        column = QVBoxLayout(mixer)
        # Each row sits beside its lane: lanes start LANE_GAP below the ruler.
        column.setContentsMargins(0, RULER_H + LANE_GAP, 0, 0)
        column.setSpacing(LANE_GAP)
        video_row = label("   Video", "Dim")
        video_row.setFixedHeight(LANE_H)
        column.addWidget(video_row)
        self.rows = []
        for position, track in enumerate(self.tracks):
            row = TrackRow(track, theme.channel_colour(track.channel, position))
            row.changed.connect(self._mix_changed)
            column.addWidget(row)
            self.rows.append(row)
        if not self.tracks:
            column.addWidget(label("This clip has no audio.", "Dim"))
        column.addStretch(1)
        self.timeline = Timeline()
        self.timeline.set_lanes(self._lanes())
        self.timeline.set_duration(self.duration)
        self.timeline.set_trim(self.trim_start, self.trim_end)
        self.timeline.seek_requested.connect(self.seek)
        self.timeline.trim_changed.connect(self._trim_dragged)
        self.timeline.trim_committed.connect(self._trim_committed)
        mixer.setFixedHeight(self.timeline.height())
        editor.addWidget(mixer, 0, 0, Qt.AlignmentFlag.AlignTop)
        editor.addWidget(self.timeline, 0, 1, Qt.AlignmentFlag.AlignTop)
        editor.setColumnStretch(1, 1)
        layout.addLayout(editor)
        self._update_estimate()

    def _lanes(self) -> list[tuple[str, bool]]:
        return [(theme.channel_colour(track.channel, position), track.muted)
                for position, track in enumerate(self.tracks)]

    def _meta(self) -> str:
        parts = []
        if self.info.width and self.info.height:
            parts.append(f"{self.info.width}×{self.info.height} @ {round(self.info.fps)} fps")
        if self.clip.date:
            parts.append(fmt.date(self.clip.date))
        return "   ·   ".join(parts)

    def _tag_text(self) -> str:
        game, people = self.state.tags_of(self.clip)
        return "  ·  ".join(part for part in (game, ", ".join(people)) if part) or "Add tags"

    # --- Player ---------------------------------------------------------------

    def _start_player(self) -> None:
        if self._closing or self.player_widget is None:
            return
        player = self.player_widget.player
        self._apply_mix()
        if self.trim_start > 0:
            try:
                player["start"] = f"{self.trim_start:.3f}"
            except Exception:        # playback just starts at 0
                pass
            self.position = self.trim_start
        player.play(self.clip.path)
        self._poll_timer.start()
        self._update_time()

    def _apply_mix(self) -> None:
        if self.player_widget is None or self.player_widget.player is None:
            return
        graph = mixing.mpv_graph(self.tracks)
        if graph is None:
            return
        try:
            self.player_widget.player["lavfi-complex"] = graph
        except Exception:            # playback goes on without the mix
            pass

    def _poll(self) -> None:
        if self._closing or self.player_widget is None or self.player_widget.player is None:
            return
        player = self.player_widget.player
        try:
            position, duration, paused = player.time_pos, player.duration, player.pause
        except Exception:
            return
        if paused is not None:
            self.play_button.set_icon("play" if paused else "pause", "ON_ACCENT")
        if duration and not self.duration:
            # ffprobe could not say how long the clip is; mpv can.
            self.duration = duration
            self.trim_end = duration
            self.timeline.set_duration(duration)
            self.timeline.set_trim(self.trim_start, self.trim_end)
            self._start_waves()
        if position is not None and time.monotonic() > self._suppress_until:
            self.position = position
            self.timeline.set_position(position)
            self._update_time()

    def _update_time(self) -> None:
        self.time_label.setText(f"{fmt.duration(self.position)} / {fmt.duration(self.duration)}")

    def toggle_play(self) -> None:
        player = self.player_widget.player if self.player_widget else None
        if player is None:
            return
        paused = bool(player.pause)
        # Starting from outside the selection is almost never what is wanted.
        if paused and not (self.trim_start <= self.position <= self.trim_end - 0.05):
            self.seek(self.trim_start)
        player.pause = not paused
        self.play_button.set_icon("pause" if paused else "play", "ON_ACCENT")

    def seek(self, seconds: float) -> None:
        player = self.player_widget.player if self.player_widget else None
        if player is None or not self.duration:
            return
        seconds = max(0.0, min(self.duration, seconds))
        self.position = seconds
        self._suppress_until = time.monotonic() + 0.3
        self.timeline.set_position(seconds)
        self._update_time()
        try:
            player.command("seek", seconds, "absolute", "exact")
        except Exception:
            pass

    def _frame_step(self, forward: bool) -> None:
        player = self.player_widget.player if self.player_widget else None
        if player is not None:
            try:
                player.command("frame-step" if forward else "frame-back-step")
            except Exception:
                pass

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    # --- Mixer and trim ---------------------------------------------------------

    def _mix_changed(self) -> None:
        self._apply_mix()
        self.timeline.set_lanes(self._lanes())
        self._mark_dirty()

    def set_in(self) -> None:
        self.trim_start = min(self.position, self.trim_end - 0.1)
        self._trim_committed()

    def set_out(self) -> None:
        self.trim_end = max(self.position, self.trim_start + 0.1)
        self._trim_committed()

    def reset_trim(self) -> None:
        self.trim_start, self.trim_end = 0.0, self.duration
        self._trim_committed()

    def _trim_dragged(self, start: float, end: float) -> None:
        self.trim_start, self.trim_end = start, end
        self._update_estimate()

    def _trim_committed(self) -> None:
        self.timeline.set_trim(self.trim_start, self.trim_end)
        self._update_estimate()
        self._mark_dirty()

    @property
    def selection(self) -> float:
        return max(0.0, self.trim_end - self.trim_start)

    def _has_trim(self) -> bool:
        return bool(self.duration) and self.selection >= 0.05 and (
            self.trim_start > 0.05 or self.trim_end < self.duration - 0.05)

    def _update_estimate(self) -> None:
        if self.selection < 0.05:
            self.status.setText("The selection is empty.")
            return
        parts = [fmt.duration(self.selection)]
        if self.info.summary:
            parts.append(self.info.summary)
        estimate = copy_estimate(self.info, self.selection)
        if estimate:
            parts.append(f"≈{fmt.size(estimate, 0)}")
        self.status.setText("  ·  ".join(parts))
        theme.style(self.status, lambda: f"color: {theme.TEXT_MUTED};")

    # --- Waveforms -------------------------------------------------------------

    def _start_waves(self) -> None:
        if self._closing or not self.tracks or not self.duration or self._waves_started:
            return
        self._waves_started = True
        cancel, path, duration = self._waves_cancel, self.clip.path, self.duration
        for lane, track in enumerate(self.tracks):
            workers.run(lambda index=track.index: waveform.peaks(path, index, duration,
                                                                 cancel=cancel),
                        lambda levels, lane=lane: self._wave_ready(lane, levels),
                        lambda _exc: None, executor=self._wave_executor())

    def _wave_executor(self):
        # One at a time: they all read the same file, and the first lane
        # appearing sooner is worth more than all of them together.
        if self._waves_pool is None:
            self._waves_pool = workers.serial_executor("waveforms")
        return self._waves_pool

    def _wave_ready(self, lane: int, levels) -> None:
        if not self._closing and levels:
            self.timeline.set_wave(lane, levels)

    # --- Header actions --------------------------------------------------------

    def _rename(self, text: str) -> None:
        shown = self.state.set_title(self.clip, text)
        self.title.set_text(shown)

    def _edit_tags(self) -> None:
        library = self.context.library
        if library is None:
            return
        game, people = self.state.tags_of(self.clip)
        result = TagDialog.ask(self, self.state.title_of(self.clip), game, people,
                               library.known_games(), library.known_people())
        if result is not None:
            self.state.set_tags(self.clip, *result)
            self.tags_button.setText(self._tag_text())

    # --- Export -----------------------------------------------------------------

    def start_export(self) -> None:
        if self.selection < 0.05:
            self.status.setText("The selection is empty.")
            return
        if self.player_widget and self.player_widget.player and \
                not self.player_widget.player.pause:
            self.toggle_play()
        dialog = ExportDialog(self, self.context, self.clip, self.trim_start, self.trim_end,
                              [*self.tracks], self.info)
        dialog.exec()

    # --- Trim to disk -----------------------------------------------------------

    def confirm_trim(self) -> None:
        if self._trim_job is not None:
            return
        if not self._has_trim():
            self.status.setText("Set the In and Out markers first.")
            return
        span = (f"{fmt.duration(self.trim_start)} – {fmt.duration(self.trim_end)} "
                f"({fmt.duration(self.selection)})")
        choice = ChoiceDialog.ask(
            self, "Trim clip", "Trim this clip to the selection?",
            f"{span}\n\nThe trimmed file keeps the original quality and every audio track, "
            "so it can be edited again. It starts at the nearest keyframe before the In "
            "marker.\n\nReplacing keeps the clip's name, tags and mix and moves the "
            "original to your Trash.",
            [("Save as Copy", "copy", ""), ("Replace Original", "replace", "primary")])
        if choice is not None:
            self._start_trim(choice)

    def _start_trim(self, mode: str) -> None:
        if mode == "copy":
            target = clips_mod.trimmed_copy_path(self.clip.path)
        else:
            target = clips_mod.staging_path(self.clip.path, "vertex-trim")
        self.trim_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status.setText("Trimming…")
        start, end, source = self.trim_start, self.trim_end, self.clip.path
        self._trim_job = (mode, target)
        workers.run(lambda: trim.trim(source, target, start, end),
                    lambda size: self._trim_done(mode, target, size),
                    self._trim_failed)

    def _trim_done(self, mode: str, target: str, size: int) -> None:
        self._trim_job = None
        if self._closing:
            if mode == "replace":
                _remove(target)       # the swap is never going to happen now
            return
        self.trim_button.setEnabled(True)
        self.export_button.setEnabled(True)
        if mode == "copy" and self.context.library is not None:
            self.context.library.copy_edits(self.clip.name, os.path.basename(target),
                                            title_suffix=" (trimmed)")
            self.status.setText(f"Saved {os.path.basename(target)} · {fmt.size(size)}")
            theme.style(self.status, lambda: f"color: {theme.OK};")
        self.trimmed.emit(self.clip, mode, target)

    def _trim_failed(self, exc: BaseException) -> None:
        _mode, target = self._trim_job or ("", "")
        self._trim_job = None
        _remove(target)
        if self._closing:
            return
        self.trim_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.status.setText(str(exc))
        theme.style(self.status, lambda: f"color: {theme.DANGER};")

    # --- Keyboard -----------------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Left:
            self.seek(self.position - (1.0 if shift else SEEK_STEP))
        elif key == Qt.Key.Key_Right:
            self.seek(self.position + (1.0 if shift else SEEK_STEP))
        elif key == Qt.Key.Key_Comma:
            self._frame_step(False)
        elif key == Qt.Key.Key_Period:
            self._frame_step(True)
        elif key == Qt.Key.Key_I:
            self.set_in()
        elif key == Qt.Key.Key_O:
            self.set_out()
        elif key == Qt.Key.Key_Home:
            self.seek(self.trim_start)
        elif key == Qt.Key.Key_End:
            self.seek(self.trim_end)
        elif key == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.window().showNormal()
            else:
                self.back.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    # --- Teardown ---------------------------------------------------------------

    def close_editor(self) -> None:
        """Stop playback and background work. Must run before deletion."""
        if self._closing:
            return
        self._closing = True
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()
        self._poll_timer.stop()
        self._waves_cancel.set()
        if self._waves_pool is not None:
            self._waves_pool.shutdown(wait=False, cancel_futures=True)
        if self.player_widget is not None:
            self.player_widget.shutdown()


def _remove(path: str) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass
