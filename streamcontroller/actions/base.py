"""What every Vertex key has in common: it follows Vertex's state and redraws
when it changes, and it sends commands without making the deck wait."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402
from GtkHelper.FileDialogRow import FileDialogFilter, FileDialogRow  # noqa: E402
from loguru import logger as log  # noqa: E402
from src.backend.PluginManager.ActionBase import ActionBase  # noqa: E402

CHANNELS = (("game", "Game"), ("chat", "Chat"), ("media", "Media"), ("mic", "Microphone"))
IMAGES = FileDialogFilter("Images", ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.svg"])


class VertexAction(ActionBase):
    # The faces a key changes between, each with a picture the user can pick
    # in the key's settings: (face, the setting's title).
    FACES: tuple[tuple[str, str], ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = False
        self._face: str | None = ""      # the picture shown; None: show it again

    @property
    def vertex(self):
        return self.plugin_base.vertex

    def on_ready(self) -> None:
        self.vertex.add_listener(self._on_vertex)
        self._redraw(self.vertex.state)

    def on_remove(self) -> None:
        self.vertex.remove_listener(self._on_vertex)

    def _on_vertex(self, event: str, data) -> None:
        if event == "state":
            self._redraw(data)
        elif event == "notice":
            self.on_notice(data or {})

    def _redraw(self, state) -> None:
        try:
            self.show(state)
        except Exception as exc:      # StreamController dropped the key mid-draw
            log.debug(f"Vertex: couldn't redraw {self.action_id}: {exc}")

    def show(self, state: dict | None) -> None:
        """Draw the key for `state` (None: Vertex isn't running)."""

    def show_labels(self, top: str = "", center: str = "", bottom: str = "") -> None:
        """All three labels at once, so a face never keeps another's text."""
        self.set_top_label(top)
        self.set_center_label(center)
        self.set_bottom_label(bottom)

    def face(self, name: str) -> None:
        """Show the face `name`: the picture picked for it in the key's
        settings, else the plugin's own `assets/<name>.png` if it has one.
        With neither, a picture another face put up goes away; a key that
        never had one keeps the image it was given in StreamController."""
        path = self.images().get(name, "")
        if not os.path.isfile(path):
            bundled = os.path.join(getattr(self.plugin_base, "PATH", ""), "assets", f"{name}.png")
            path = bundled if os.path.isfile(bundled) else ""
        if path == self._face:
            return
        if path:
            self.set_media(media_path=path)
        elif self._face != "":            # ours, or the one just unpicked
            self.set_media()
        self._face = path

    def images(self) -> dict[str, str]:
        """The pictures picked in the key's settings, by face."""
        images = self.setting("images", {})
        return dict(images) if isinstance(images, dict) else {}

    def set_image(self, face: str, path: str) -> None:
        settings = self.get_settings()
        images = self.images()
        if path:
            images[face] = path
        else:
            images.pop(face, None)
        settings["images"] = images
        self.set_settings(settings)
        self._face = None
        self._redraw(self.vertex.state)

    def on_notice(self, notice: dict) -> None:
        """A notification from Vertex (kind, category, title, body)."""

    def send(self, command: str, **args) -> None:
        """Send `command`; the key shows an error briefly if it fails."""
        def done(reply: dict) -> None:
            if not reply.get("ok"):
                log.info(f"Vertex {command}: {reply.get('message')}")
                try:
                    self.show_error(duration=1)
                except Exception:
                    pass
        self.vertex.request(command, done, **args)

    # --- Settings ---------------------------------------------------------------

    def setting(self, key: str, default):
        return self.get_settings().get(key, default)

    def choice_row(self, title: str, key: str, choices, default,
                   subtitle: str = "") -> Adw.ComboRow:
        """A drop-down row for the setting `key`, from (value, label) pairs."""
        values = [value for value, _label in choices]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _v, label in choices]))
        if subtitle:
            row.set_subtitle(subtitle)
        current = self.setting(key, default)
        row.set_selected(values.index(current) if current in values else values.index(default))

        def changed(combo, _param):
            settings = self.get_settings()
            settings[key] = values[combo.get_selected()]
            self.set_settings(settings)
            self._redraw(self.vertex.state)
        row.connect("notify::selected", changed)
        return row

    def number_row(self, title: str, key: str, low: int, high: int,
                   default: int) -> Adw.SpinRow:
        """A whole-number row for the setting `key`."""
        row = Adw.SpinRow.new_with_range(low, high, 1)
        row.set_title(title)
        row.set_value(self.setting(key, default))

        def changed(spin, _param):
            settings = self.get_settings()
            settings[key] = int(spin.get_value())
            self.set_settings(settings)
            self._redraw(self.vertex.state)
        row.connect("notify::value", changed)
        return row

    def image_rows(self) -> list[Adw.PreferencesRow]:
        """A picture row for each of the key's faces."""
        rows = []
        for face, title in self.FACES:
            row = FileDialogRow(title=title, dialog_title=title, filters=[IMAGES],
                                file_change_callback=lambda file, face=face:
                                self.set_image(face, file.get_path() or ""))
            current = self.images().get(face)
            if current:
                row.selected_file = Gio.File.new_for_path(current)
            row.update_label()
            clear = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="No picture")

            def cleared(_button, face=face, row=row):
                self.set_image(face, "")
                row.selected_file = None
                row.update_label()
            clear.connect("clicked", cleared)
            row.add_suffix(clear)
            rows.append(row)
        return rows
