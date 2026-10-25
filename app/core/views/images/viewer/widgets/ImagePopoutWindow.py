"""
ImagePopoutWindow - Separate top-level window for the viewer's image pane.

With the gallery dragged to fill the viewer, a thumbnail click opens this
window. It holds no image widgets of its own: ImagePopoutController moves the
viewer's toolbar, image pane and status bar into ``hostLayout`` and hands them
back on close, so every controller that reaches them through the Viewer keeps
working unchanged.
"""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QWidget

from core.views.images.viewer.ui.ImagePopoutWindow_ui import Ui_ImagePopoutWindow


class ImagePopoutWindow(QWidget, Ui_ImagePopoutWindow):
    """Window owned by the Viewer that reports its close, key and focus events.

    Owning it (a parent plus the ``Qt.Window`` flag) keeps it above the viewer
    and closes it with the viewer. It is deliberately not a QDialog:
    ``Viewer.keyPressEvent`` ignores keys whenever a dialog is the active
    window, and every shortcut must keep working here.
    """

    # The user closed the window (title-bar X, Alt+F4).
    closeRequested = Signal()
    # A key press no child widget consumed. Carries the QKeyEvent, which is
    # only valid during the (direct, synchronous) emission.
    keyPressed = Signal(object)
    # The window gained or lost activation.
    activationChanged = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Window)
        self.setupUi(self)

    def closeEvent(self, event):
        """Let the controller return the borrowed widgets before the window hides."""
        self.closeRequested.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Forward unconsumed keys so the viewer's shortcuts work in this window."""
        self.keyPressed.emit(event)

    def changeEvent(self, event):
        """Report activation changes; review time spans this window and the viewer."""
        if event.type() == QEvent.ActivationChange:
            self.activationChanged.emit()
        super().changeEvent(event)
