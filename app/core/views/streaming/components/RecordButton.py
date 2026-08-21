"""The app's record toggle: one look, wherever recording is offered.

A compact camera-idiom control — a red dot when idle, a white stop square
on a red field while recording. Used by the streaming window's playback
bar and by each Flight Viewer tile's status strip, so "start recording"
looks and behaves the same wherever the operator finds it.

Exposed as functions applied to an ordinary ``QPushButton`` rather than a
QPushButton subclass, so a button declared in a ``.ui`` file can adopt it
without widget promotion.

The glyphs are **painted pixmaps, not text**. A text "●" sits wherever the
font's bearing puts it, and any stylesheet on a QPushButton also takes
over Qt's native padding — together those rendered the dot visibly
off-centre. A pixmap centred by construction, with padding zeroed, cannot
drift. Note the square's side is even: an odd-sided square cannot sit
centred in an even canvas.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton

BUTTON_PX = 34
ICON_PX = 20
DOT_PX = 12
SQUARE_PX = 12  # even: see module docstring
RECORD_RED = "#e53935"
RECORD_RED_HOVER = "#b71c1c"

_CONTEXT = "RecordButton"


def _tr(text: str) -> str:
    return QCoreApplication.translate(_CONTEXT, text)


def _dot_icon(diameter: int, color: str) -> QIcon:
    """A filled circle, centred in a square canvas."""
    pixmap = QPixmap(ICON_PX, ICON_PX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        offset = (ICON_PX - diameter) / 2.0
        painter.drawEllipse(QRectF(offset, offset, diameter, diameter))
    finally:
        painter.end()
    return QIcon(pixmap)


def _square_icon(side: int, color: str) -> QIcon:
    """A filled square, centred in a square canvas."""
    pixmap = QPixmap(ICON_PX, ICON_PX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        offset = (ICON_PX - side) // 2
        painter.drawRect(offset, offset, side, side)
    finally:
        painter.end()
    return QIcon(pixmap)


def configure_record_button(button: QPushButton, *, size: int = BUTTON_PX) -> None:
    """Turn ``button`` into a record toggle, in its idle state.

    ``size`` lets a cramped host (a tile's status strip) use a smaller
    square without changing the glyph's proportions.
    """
    button.setFixedSize(size, size)
    button.setIconSize(QSize(ICON_PX, ICON_PX))
    button.setFlat(True)
    button.setText("")
    set_record_button_state(button, False)


def set_record_button_state(button: QPushButton, recording: bool) -> None:
    """Flip the toggle between idle (dot) and recording (stop square).

    The button is never disabled by this: a single always-enabled toggle
    means focus is never yanked off it mid-press, which is what the old
    enable/disable Start+Stop pair had to work around.
    """
    if recording:
        button.setIcon(_square_icon(SQUARE_PX, "#ffffff"))
        button.setStyleSheet(
            "QPushButton {"
            f" background-color: {RECORD_RED};"
            " border: none; border-radius: 4px; padding: 0px;"
            "}"
            f"QPushButton:hover {{ background-color: {RECORD_RED_HOVER}; }}"
        )
        button.setToolTip(_tr("Recording - click to stop and save."))
    else:
        button.setIcon(_dot_icon(DOT_PX, RECORD_RED))
        button.setStyleSheet(
            "QPushButton {"
            " background-color: transparent;"
            " border: none; border-radius: 4px; padding: 0px;"
            "}"
            "QPushButton:hover { background-color: rgba(229, 57, 53, 0.18); }"
        )
        button.setToolTip(_tr("Record this feed: video, detections, telemetry and map."))


__all__ = [
    "BUTTON_PX",
    "ICON_PX",
    "RECORD_RED",
    "configure_record_button",
    "set_record_button_state",
]
