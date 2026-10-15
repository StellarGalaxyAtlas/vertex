"""The desktop's monitors as Qt reports them, handed to vertex.recorder as plain data."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from vertex.recorder import monitors


def desktop_screens() -> list[monitors.Screen]:
    """The monitors as the desktop arranges them, the primary one marked."""
    primary = QGuiApplication.primaryScreen()
    screens = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        screens.append(monitors.Screen(
            screen.name(), geometry.x(), geometry.y(), geometry.width(), geometry.height(),
            screen.model().strip() or screen.manufacturer().strip(),
            (round(geometry.width() * ratio), round(geometry.height() * ratio)),
            primary=screen is primary))
    return screens
