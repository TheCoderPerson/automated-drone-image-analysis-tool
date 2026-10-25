"""
ImagePopoutController - Shows the viewer's image pane in a separate window.

Full-gallery review: once the operator drags the divider so the gallery fills
the viewer, clicking a thumbnail opens that AOI in a separate window. Closing
the window returns the operator to the gallery at the same spot.

The window borrows the viewer's own widgets; it does not build a second image
view. Roughly thirty controllers take the Viewer as their parent and reach the
image, toolbar and status bar through it (main_image, showOverlayToggle,
statusBar, ...). Moving those same widgets keeps all of them working. A
second view would need an object that mimics the Viewer, plus state kept in
sync in both directions.
"""

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QAbstractItemView, QWidget

from core.services.LoggerService import LoggerService
from core.views.images.viewer.widgets.ImagePopoutWindow import ImagePopoutWindow


class ImagePopoutController:
    """Moves the viewer's toolbar, image pane and status bar into ImagePopoutWindow and back."""

    # Window geometry (base64 QWidget.saveGeometry), so the window reopens
    # where the operator last put it, on a second monitor for example.
    GEOMETRY_SETTING = 'viewer/image_popout_geometry'

    def __init__(self, parent_viewer):
        """Initialize the controller.

        Args:
            parent_viewer: The main Viewer instance.
        """
        self.parent = parent_viewer
        self.logger = LoggerService()
        # Created on first open, then hidden and reused.
        self.popout_window = None
        # Fills the image pane's splitter slot while the pane is away. The
        # splitter keeps two children (sizes() callers expect two) and the
        # slot's collapsed state.
        self._placeholder = None
        # The status bar's position in the viewer's outer layout.
        self._status_bar_index = -1

    def is_open(self):
        """True while the image pane is in the pop-out window."""
        return self._placeholder is not None

    def open(self):
        """Move the image pane into the pop-out window and show the window."""
        if self.is_open():
            return
        viewer = self.parent
        window = self._ensure_window()
        splitter = viewer.image_gallery_splitter

        self._placeholder = QWidget()
        # Zero maximum width: dragging the divider while the pane is away
        # cannot open an empty gap beside the gallery.
        self._placeholder.setMaximumWidth(0)
        # replaceWidget hands the slot's geometry and collapsed state to the
        # placeholder, and back to the image pane on close.
        splitter.replaceWidget(splitter.indexOf(viewer.imageWidget), self._placeholder)
        self._status_bar_index = viewer.verticalLayout.indexOf(viewer.statusBarWidget)

        window.hostLayout.addWidget(viewer.mainHeaderWidget)
        window.hostLayout.addWidget(viewer.imageWidget, 1)
        window.hostLayout.addWidget(viewer.statusBarWidget)
        # Reparenting hides a widget; show them for when the window appears.
        for widget in (viewer.mainHeaderWidget, viewer.imageWidget, viewer.statusBarWidget):
            widget.show()
        viewer._sync_aoi_header_width()

        self._show_window(window)
        viewer.main_image.setFocus()

    def close(self):
        """Close the pop-out window and return the operator to the gallery."""
        if not self.is_open():
            return
        self._restore_widgets()
        self._return_to_gallery()

    def cleanup(self):
        """Give the borrowed widgets back before the viewer closes."""
        if self.is_open():
            self._restore_widgets()

    def handle_key(self, event):
        """Esc or G closes the pop-out window and returns to the gallery.

        Called first from Viewer.keyPressEvent, which receives keys from both
        windows. QtImageViewer forwards its unhandled keys to the viewer
        directly, and the pop-out window forwards the rest.

        Returns:
            bool: True if the key was consumed.
        """
        if not self.is_open() or event.modifiers() != Qt.NoModifier:
            return False
        if event.key() in (Qt.Key_Escape, Qt.Key_G):
            self.close()
            return True
        return False

    def _ensure_window(self):
        if self.popout_window is None:
            window = ImagePopoutWindow(self.parent)
            window.closeRequested.connect(self.close)
            window.keyPressed.connect(self.parent.keyPressEvent)
            window.activationChanged.connect(self.parent._end_dwell_if_review_unfocused)
            self.popout_window = window
        return self.popout_window

    def _show_window(self, window):
        saved = self.parent.settings_service.get_setting(self.GEOMETRY_SETTING, None)
        restored = False
        if saved:
            try:
                restored = window.restoreGeometry(QByteArray.fromBase64(str(saved).encode('ascii')))
            except Exception as e:
                self.logger.warning(f"Ignoring unreadable image pop-out geometry: {e}")
        if restored:
            window.show()
        else:
            # First open: fill the viewer's screen, the space the image pane
            # gave up to the gallery.
            window.setGeometry(self.parent.geometry())
            window.showMaximized()
        window.raise_()
        window.activateWindow()

    def _restore_widgets(self):
        viewer = self.parent
        window = self.popout_window
        geometry = bytes(window.saveGeometry().toBase64()).decode('ascii')
        viewer.settings_service.set_setting(self.GEOMETRY_SETTING, geometry)

        # The AOI header still spans the whole row. If the toolbar rejoined
        # beside it visible, the row would briefly need the toolbar's width
        # on top of the window's. The viewer would grow to fit and stay
        # that wide, and the reflowed gallery would lose its scroll
        # position. So the toolbar goes back hidden, the AOI header is
        # resized to fit beside it, and only then does the toolbar show.
        viewer.mainHeaderWidget.hide()
        viewer._header_layout.insertWidget(0, viewer.mainHeaderWidget)
        viewer._sync_aoi_header_width()
        viewer.mainHeaderWidget.show()

        splitter = viewer.image_gallery_splitter
        splitter.replaceWidget(splitter.indexOf(self._placeholder), viewer.imageWidget)
        self._placeholder.deleteLater()
        self._placeholder = None
        viewer.verticalLayout.insertWidget(self._status_bar_index, viewer.statusBarWidget)
        viewer.statusBarWidget.show()
        window.hide()

    def _return_to_gallery(self):
        viewer = self.parent
        viewer.activateWindow()
        gallery_view = viewer.gallery_controller.ui_component.gallery_view
        if gallery_view is None:
            return
        current = gallery_view.currentIndex()
        if current.isValid():
            # The gallery never resizes while the pop-out is open, and arrow
            # keys in the pop-out scroll it as they step, so the current tile
            # is normally on screen and EnsureVisible changes nothing. It
            # scrolls only if a gallery reload while the window was open (a
            # flagged-only filter dropping a tile, a newly drawn AOI) moved
            # the tile off screen.
            gallery_view.scrollTo(current, QAbstractItemView.EnsureVisible)
        gallery_view.setFocus()
