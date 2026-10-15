"""Vertex — record, organise, edit and share game clips on Linux.

The package is split by concern, and only `vertex.ui` imports Qt:

    vertex.core       clips on disk: scanning, file-name parsing, importing
    vertex.library    the SQLite library of per-clip edits (tags, trims, mixes)
    vertex.media      ffmpeg/ffprobe: probing, waveforms, trimming, exporting
    vertex.audio      Sonar: virtual Game/Chat/Media/Mic devices on PipeWire
    vertex.recorder   GPU Screen Recorder as the replay-buffer backend
    vertex.ui         the PySide6 application
"""

__version__ = "2.0.0.dev0"

APP_NAME = "Vertex"
APP_ID = "vertex"  # desktop entry, icon name, WM class, XDG directory name
