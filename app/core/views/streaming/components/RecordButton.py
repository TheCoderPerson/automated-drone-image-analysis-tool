"""Compact media controls: the record toggle, and the play button.

The record toggle is a camera-idiom control — a red dot when idle, a white
stop square on a red field while recording — and the play button is the
grey triangle that appears beside it once a feed has a recording worth
watching. Both are used by the streaming window's playback bar and by each
Flight Viewer tile's status strip, so a control means the same thing
wherever the operator finds it.

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
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QPushButton

BUTTON_PX = 34
ICON_PX = 20
DOT_PX = 12
SQUARE_PX = 12  # even: see module docstring
PLAY_W_PX = 11
PLAY_H_PX = 12
PLAY_GREY = "#d6d6d6"
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


def _play_icon(width: int, height: int, color: str) -> QIcon:
    """A right-pointing triangle whose centroid is the canvas centre.

    A triangle's centroid is not its bounding box's centre, and the eye
    reads the centroid - so the vertices are solved for it rather than the
    box being centred (which looks left-heavy). For a triangle with two
    vertices on the left edge and one at the right point, centroid_x is
    ``(2*left + right) / 3``; putting that at the centre means the left
    edge sits a third of the width to the left of it.

    The centre is ``ICON_PX / 2`` in *coordinate* space, not
    ``(ICON_PX - 1) / 2``: Qt fills the pixel at index x across
    coordinates [x, x+1), so that is what puts the glyph on the same
    centre the dot and square already use.
    """
    pixmap = QPixmap(ICON_PX, ICON_PX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        centre = ICON_PX / 2.0
        left = centre - width / 3.0
        right = centre + 2.0 * width / 3.0
        top = centre - height / 2.0
        bottom = centre + height / 2.0
        path = QPainterPath()
        path.moveTo(left, top)
        path.lineTo(left, bottom)
        path.lineTo(right, centre)
        path.closeSubpath()
        painter.drawPath(path)
    finally:
        painter.end()
    return QIcon(pixmap)


def configure_play_button(button: QPushButton, *, size: int = BUTTON_PX) -> None:
    """Turn ``button`` into a play control for a finished recording."""
    button.setFixedSize(size, size)
    button.setIconSize(QSize(ICON_PX, ICON_PX))
    button.setFlat(True)
    button.setText("")
    button.setIcon(_play_icon(PLAY_W_PX, PLAY_H_PX, PLAY_GREY))
    button.setStyleSheet(
        "QPushButton {"
        " background-color: transparent;"
        " border: none; border-radius: 4px; padding: 0px;"
        "}"
        "QPushButton:hover { background-color: rgba(255, 255, 255, 0.14); }"
    )
    button.setToolTip(_tr("Watch this feed's last recording."))


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
    "configure_play_button",
    "configure_record_button",
    "set_record_button_state",
]
