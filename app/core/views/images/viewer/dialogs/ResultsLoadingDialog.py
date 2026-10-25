"""ResultsLoadingDialog - heartbeat status while a results file opens.

A small, frame-light, always-on-top window shown for the duration of
`Viewer.__init__` so the user has visible feedback during the synchronous
phases (path validation, source-folder scan, WALDO pre-pass coordination,
AOI initialisation, first-image decode). Without it, the app looks frozen
between picking a results file and the viewer appearing.

Always-on-top keeps the heartbeat above the launcher window, but it would
also bury every prompt the open flow raises: the missing-images message and
folder picker, the custom AGL input, bearing recovery, the WALDO pre-pass,
and any prompt added later. So the dialog **steps aside by itself**: an
application event filter hides it whenever the app opens another dialog or
window, and brings it back once all of those have closed. Native dialogs
(the Windows folder picker) are covered too - Qt still shows and hides the
QFileDialog that drives them. A caller's own hide() is respected: the
heartbeat never reappears after a prompt closes unless the caller wants it
visible.

The dialog is intentionally **non-modal**, so it never competes with those
prompts for input. `set_status()` is the only API the caller needs, and each
call processes pending events so the label repaints between long synchronous
operations.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QApplication
)
from PySide6.QtCore import Qt, QEvent
from shiboken6 import getCppPointer, isValid as _qt_is_valid

from helpers.TranslationMixin import TranslationMixin


# Window types the heartbeat steps aside for: anything the app opens to talk
# to the operator. Tooltips, popup menus and splash screens are left alone.
_COVERING_WINDOW_TYPES = (Qt.Dialog, Qt.Sheet, Qt.Window)


def _qt_address(obj):
    """The C++ object's address, a stable key for it.

    PySide hands a slot connected to destroyed a different Python wrapper
    than the one first seen for the same widget, so wrappers cannot be
    matched by identity; reading the address never calls into the widget,
    which is half torn down by then.
    """
    return getCppPointer(obj)[0]


class ResultsLoadingDialog(TranslationMixin, QDialog):
    """Indeterminate progress + status text while the viewer initialises."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set before setWindowFlags, which can reach setVisible below.
        # Whether the caller wants the heartbeat shown; covering windows
        # only ever defer that, never override it.
        self._wanted_visible = False
        # Windows the app opened while this dialog was up, which it has
        # hidden itself for, keyed by _qt_address; it comes back once every
        # one has closed.
        self._covering_windows = {}

        self.setWindowTitle(self.tr("Loading Results"))
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint
            | Qt.WindowStaysOnTopHint
        )
        self.setFixedSize(420, 130)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self._title = QLabel(self.tr("Opening results..."))
        title_font = self._title.font()
        title_font.setBold(True)
        self._title.setFont(title_font)
        layout.addWidget(self._title)

        self._bar = QProgressBar()
        # Indeterminate: no min/max progression, just the busy animation.
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

        self._status = QLabel(self.tr("Preparing..."))
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        QApplication.instance().installEventFilter(self)

    def set_status(self, status_text: str):
        """Update the visible status line and pump pending events.

        Calls QApplication.processEvents so the label repaints even when
        the caller is mid-way through a synchronous phase on the GUI
        thread (e.g. PIL.open across hundreds of images).
        """
        self._status.setText(status_text)
        QApplication.processEvents()

    def setVisible(self, visible):
        """Record the caller's show/hide; a show waits while a prompt is open."""
        self._wanted_visible = visible
        if visible and self._open_covering_windows():
            return
        super().setVisible(visible)

    def eventFilter(self, watched, event):
        """Hide while another window the app opens is up; return after."""
        event_type = event.type()
        # Spontaneous show/hide events come from the window system
        # minimising and restoring windows, not from the app opening or
        # closing one; the launcher being restored is not a prompt.
        if event_type == QEvent.Show and not event.spontaneous():
            if self._is_new_covering_window(watched):
                self._covering_windows[_qt_address(watched)] = watched
                # A window deleted while still open sends no Hide event
                watched.destroyed.connect(self._on_covering_window_destroyed)
                super().setVisible(False)
        elif event_type == QEvent.Hide and not event.spontaneous():
            if _qt_address(watched) in self._covering_windows:
                self._restore_if_uncovered()
        return False

    def closeEvent(self, event):
        # Closed for good (the viewer is up, or loading failed): stop
        # watching other windows so nothing can bring the heartbeat back.
        QApplication.instance().removeEventFilter(self)
        self._wanted_visible = False
        self._covering_windows = {}
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def _is_new_covering_window(self, obj):
        """Whether obj is a dialog or window, other than this one, not yet tracked."""
        return (
            obj is not self
            and obj.isWidgetType()
            and obj.isWindow()
            and obj.windowType() in _COVERING_WINDOW_TYPES
            and _qt_address(obj) not in self._covering_windows
        )

    def _open_covering_windows(self):
        """Drop covering windows that have closed or been deleted; return the rest."""
        self._covering_windows = {
            address: window for address, window in self._covering_windows.items()
            if _qt_is_valid(window) and window.isVisible()
        }
        return self._covering_windows

    def _restore_if_uncovered(self):
        """Come back once no covering window is open, if the caller wants us shown."""
        if not self._open_covering_windows() and self._wanted_visible:
            super().setVisible(True)

    def _on_covering_window_destroyed(self, obj):
        # Forget it by address before anything can call into the dying widget
        self._covering_windows.pop(_qt_address(obj), None)
        self._restore_if_uncovered()
