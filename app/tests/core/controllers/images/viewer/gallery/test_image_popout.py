"""Full-screen gallery and the image pop-out window.

The workflow under test: the operator drags the gallery divider to the screen
edge so thumbnails fill the viewer, clicks one to review that AOI in a
separate window with all the image tools, then closes the window and lands
back in the gallery where they left off.

The tests drive the real viewer UI (Viewer.ui), splitter, gallery and image
widgets through the Viewer's own layout and key methods. Only the parts that
load images and record review state are stubbed.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from core.controllers.images.viewer.Viewer import Viewer
from core.controllers.images.viewer.gallery.GalleryController import GalleryController
from core.controllers.images.viewer.gallery.ImagePopoutController import ImagePopoutController
from core.services.AOIInteractionLogService import REASON_WINDOW_UNFOCUSED
from core.views.images.viewer.ui.Viewer_ui import Ui_Viewer
from core.views.images.viewer.widgets.QtImageViewer import QtImageViewer

AOI_COUNT = 60
IMAGE_COUNT = 7


class _Settings:
    """Dict-backed SettingsService stand-in, so no test writes real QSettings."""

    def __init__(self):
        self.values = {}

    def get_setting(self, name, default_value=None):
        return self.values.get(name, default_value)

    def set_setting(self, name, value):
        self.values[name] = value


class _ViewerHarness(QMainWindow, Ui_Viewer):
    """The real viewer UI, laid out and keyed by the Viewer's own methods."""

    _tighten_header = staticmethod(Viewer._tighten_header)
    _setup_splitter_layout = Viewer._setup_splitter_layout
    _sync_aoi_header_width = Viewer._sync_aoi_header_width
    _resize_main_image_and_reposition_overlay = Viewer._resize_main_image_and_reposition_overlay
    _on_gallery_mode_clicked = Viewer._on_gallery_mode_clicked
    _end_dwell_if_review_unfocused = Viewer._end_dwell_if_review_unfocused
    keyPressEvent = Viewer.keyPressEvent

    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.logger = MagicMock()
        self.settings_service = _Settings()
        # No images: the gallery draws placeholder tiles and loads nothing.
        self.images = []
        self.current_image = -1
        self.gallery_mode = False
        self.gallery_widget = None
        self.interaction_log = MagicMock()
        self.grid_review_controller = MagicMock()
        self.grid_review_controller.handle_key.return_value = False
        self.aoi_controller = MagicMock()
        self.load_image_with_zoom = MagicMock()
        self.main_image = QtImageViewer(self, self.imageWidget)
        self.main_image.setMinimumSize(400, 300)  # as Viewer._setupViewer
        self.gallery_controller = GalleryController(self)
        self.image_popout_controller = ImagePopoutController(self)
        self._setup_splitter_layout()
        self.galleryModeButton.clicked.connect(self._on_gallery_mode_clicked)

    def _update_gallery_mode_button_style(self):
        pass


def _aoi(n):
    return {'center': (100 + n, 100 + n), 'radius': 10, 'area': 50 + n, 'number': n + 1}


@pytest.fixture
def viewer(qtbot):
    """A shown viewer in gallery mode with a page-spanning set of AOI tiles."""
    harness = _ViewerHarness()
    qtbot.addWidget(harness)
    harness.resize(1920, 1040)
    harness.show()
    qtbot.waitExposed(harness)
    harness.galleryModeButton.click()
    assert harness.gallery_mode
    items = [(n % IMAGE_COUNT, n, _aoi(n)) for n in range(AOI_COUNT)]
    harness.gallery_controller.model.set_aoi_items(items, skip_color_calc=True)
    yield harness
    harness.image_popout_controller.cleanup()


def _gallery_view(viewer):
    return viewer.gallery_controller.ui_component.gallery_view


def _drag_divider_to(viewer, x):
    """Drag the splitter handle with the mouse to splitter-local ``x``."""
    splitter = viewer.image_gallery_splitter
    handle = splitter.handle(1)

    def send(event_type, local, button, buttons):
        global_pos = QPointF(handle.mapToGlobal(local))
        QApplication.sendEvent(handle, QMouseEvent(event_type, QPointF(local), global_pos, button, buttons, Qt.NoModifier))

    start = handle.rect().center()
    target = handle.mapFromGlobal(splitter.mapToGlobal(QPoint(x, splitter.height() // 2)))
    send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    send(QEvent.MouseMove, target, Qt.NoButton, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, target, Qt.LeftButton, Qt.NoButton)


def _fill_screen_with_gallery(viewer):
    _drag_divider_to(viewer, 2)
    assert viewer.image_gallery_splitter.sizes()[0] == 0
    view = _gallery_view(viewer)
    view.doItemsLayout()
    return view


def _click_tile(viewer, row):
    view = _gallery_view(viewer)
    index = view.model().index(row, 0)
    view.scrollTo(index)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, view.visualRect(index).center())
    return view.model().get_aoi_info(index)


def _window_of(widget):
    # QWidget.window() spelled out: QtImageViewer keeps its Viewer in an
    # attribute named ``window``, which shadows the method.
    return QWidget.window(widget)


def _assert_pane_in_viewer(viewer):
    """The toolbar, image pane and status bar are all back in their viewer slots."""
    splitter = viewer.image_gallery_splitter
    assert splitter.count() == 2
    assert splitter.widget(0) is viewer.imageWidget
    assert viewer._header_layout.itemAt(0).widget() is viewer.mainHeaderWidget
    assert viewer.statusBarWidget.parentWidget() is viewer.outerWidget
    for widget in (viewer.mainHeaderWidget, viewer.imageWidget, viewer.statusBarWidget):
        assert _window_of(widget) is viewer


def _columns(viewer):
    gallery_width = viewer.image_gallery_splitter.sizes()[1]
    controller = viewer.gallery_controller
    return (gallery_width - controller.GALLERY_OVERHEAD) // controller.GALLERY_COLUMN_WIDTH


# ---------------------------------------------------------------------------
# The divider
# ---------------------------------------------------------------------------

def test_divider_drags_past_the_toolbar_width(viewer):
    """Regression: the image pane was held at the toolbar's minimum width
    (about 1300 px), which stopped the gallery at two columns on a 1920 px
    screen. Short of collapsing, the pane now stops at its own content (the
    navigation bar), well left of that."""
    _drag_divider_to(viewer, 600)

    image_width = viewer.image_gallery_splitter.sizes()[0]
    assert 0 < image_width < viewer.mainHeaderWidget.minimumSizeHint().width()
    assert _columns(viewer) > 2


def test_divider_reaches_the_screen_edge(viewer):
    _fill_screen_with_gallery(viewer)

    splitter = viewer.image_gallery_splitter
    assert splitter.sizes()[1] == splitter.width() - splitter.handleWidth()
    assert viewer.gallery_controller.is_full_gallery()


def test_full_gallery_cannot_start_the_runaway_window_growth(viewer):
    """The toolbar and AOI header share a header row; it must never need more
    width than the window has, or the window's minimum creeps past its width
    on every resize."""
    _fill_screen_with_gallery(viewer)

    assert viewer._header_row.minimumSizeHint().width() <= viewer.image_gallery_splitter.width()
    assert viewer.minimumSizeHint().width() <= viewer.width()


def test_divider_drags_back_out_of_full_gallery(viewer):
    _fill_screen_with_gallery(viewer)

    _drag_divider_to(viewer, 900)

    assert viewer.image_gallery_splitter.sizes()[0] > 0
    assert not viewer.gallery_controller.is_full_gallery()


def test_leaving_gallery_mode_reopens_the_collapsed_image_pane(viewer):
    _fill_screen_with_gallery(viewer)

    viewer.galleryModeButton.click()

    splitter = viewer.image_gallery_splitter
    assert not viewer.gallery_mode
    assert splitter.sizes()[0] > 0
    assert not splitter.isCollapsible(0)


def test_full_gallery_is_remembered_for_the_next_gallery_visit(viewer):
    _fill_screen_with_gallery(viewer)
    viewer.galleryModeButton.click()  # single image

    viewer.galleryModeButton.click()  # gallery again

    assert viewer.gallery_controller.is_full_gallery()


# ---------------------------------------------------------------------------
# Opening the pop-out window
# ---------------------------------------------------------------------------

def test_thumbnail_click_in_full_gallery_opens_the_image_window(viewer, qtbot):
    _fill_screen_with_gallery(viewer)

    image_idx, aoi_idx, _ = _click_tile(viewer, 3)

    popout = viewer.image_popout_controller
    assert popout.is_open()
    window = popout.popout_window
    qtbot.waitExposed(window)
    # The window holds the viewer's own toolbar, image pane and status bar.
    for widget in (viewer.mainHeaderWidget, viewer.imageWidget, viewer.statusBarWidget, viewer.main_image):
        assert _window_of(widget) is window
    # ...and the clicked AOI is loaded into it through the normal click path.
    viewer.load_image_with_zoom.assert_called_once()
    assert viewer.load_image_with_zoom.call_args.args[0] == image_idx
    viewer.aoi_controller.select_aoi.assert_called_once()
    assert viewer.aoi_controller.select_aoi.call_args.args[0] == aoi_idx


def test_gallery_keeps_the_whole_viewer_while_the_window_is_open(viewer):
    _fill_screen_with_gallery(viewer)

    _click_tile(viewer, 3)

    splitter = viewer.image_gallery_splitter
    assert splitter.count() == 2
    assert splitter.sizes()[0] == 0
    assert viewer.minimumSizeHint().width() <= viewer.width()


def test_thumbnail_click_with_the_image_pane_showing_stays_in_the_viewer(viewer):
    _drag_divider_to(viewer, 900)

    _click_tile(viewer, 3)

    assert not viewer.image_popout_controller.is_open()
    assert _window_of(viewer.main_image) is viewer
    viewer.load_image_with_zoom.assert_called_once()


def test_second_thumbnail_click_reuses_the_open_window(viewer):
    _fill_screen_with_gallery(viewer)
    _click_tile(viewer, 3)
    window = viewer.image_popout_controller.popout_window

    image_idx, _, _ = _click_tile(viewer, 4)

    assert viewer.image_popout_controller.popout_window is window
    assert _window_of(viewer.main_image) is window
    assert viewer.load_image_with_zoom.call_args.args[0] == image_idx


def test_arrow_keys_in_the_window_step_through_the_gallery(viewer):
    _fill_screen_with_gallery(viewer)
    _click_tile(viewer, 3)
    view = _gallery_view(viewer)

    QTest.keyClick(viewer.main_image, Qt.Key_Right)

    assert view.currentIndex().row() == 4
    next_image_idx = view.model().get_aoi_info(view.currentIndex())[0]
    assert viewer.load_image_with_zoom.call_args.args[0] == next_image_idx
    assert viewer.image_popout_controller.is_open()


# ---------------------------------------------------------------------------
# Closing it: back to the gallery where the operator left off
# ---------------------------------------------------------------------------

def _open_from_a_scrolled_gallery(viewer):
    view = _fill_screen_with_gallery(viewer)
    scroll_bar = view.verticalScrollBar()
    assert scroll_bar.maximum() > 0, "the test needs a scrollable gallery"
    scroll_bar.setValue(scroll_bar.maximum() // 2)
    scroll_value = scroll_bar.value()
    # A tile already on screen, so the click itself does not scroll.
    row = view.indexAt(view.viewport().rect().center()).row()
    assert row >= 0
    view.setCurrentIndex(view.model().index(row, 0))
    QTest.mouseClick(
        view.viewport(), Qt.LeftButton, Qt.NoModifier,
        view.visualRect(view.model().index(row, 0)).center())
    assert viewer.image_popout_controller.is_open()
    return view, scroll_value, row


def test_esc_closes_the_window_back_to_the_same_gallery_spot(viewer, qtbot):
    view, scroll_value, row = _open_from_a_scrolled_gallery(viewer)

    QTest.keyClick(viewer.main_image, Qt.Key_Escape)

    assert not viewer.image_popout_controller.is_open()
    assert not viewer.image_popout_controller.popout_window.isVisible()
    _assert_pane_in_viewer(viewer)
    assert viewer.gallery_mode
    assert viewer.gallery_controller.is_full_gallery()
    assert view.verticalScrollBar().value() == scroll_value
    assert view.currentIndex().row() == row
    qtbot.waitUntil(view.hasFocus)


def test_closing_the_window_does_not_widen_the_viewer(viewer, qtbot):
    """Regression: the toolbar rejoined the header row beside an AOI header
    still sized for the whole row. For a moment the row asked for about
    3000 px, the viewer grew to fit and stayed that wide, and the reflowed
    gallery lost the operator's scroll position."""
    view, scroll_value, _ = _open_from_a_scrolled_gallery(viewer)
    width = viewer.width()
    gallery_width = view.viewport().width()

    QTest.keyClick(viewer.main_image, Qt.Key_Escape)
    qtbot.wait(50)  # let any posted layout requests run

    assert viewer.width() == width
    assert view.viewport().width() == gallery_width
    assert view.verticalScrollBar().value() == scroll_value


def test_g_key_in_the_window_returns_to_the_gallery(viewer):
    _open_from_a_scrolled_gallery(viewer)

    # Sent to the window itself, as when a toolbar button has focus.
    QTest.keyClick(viewer.image_popout_controller.popout_window, Qt.Key_G)

    assert not viewer.image_popout_controller.is_open()
    _assert_pane_in_viewer(viewer)
    assert viewer.gallery_mode


def test_gallery_button_in_the_window_returns_to_the_gallery(viewer):
    _open_from_a_scrolled_gallery(viewer)

    viewer.galleryModeButton.click()

    assert not viewer.image_popout_controller.is_open()
    assert viewer.gallery_mode
    assert viewer.galleryModeButton.isChecked()
    assert viewer.gallery_controller.is_full_gallery()


def test_title_bar_close_returns_to_the_gallery(viewer):
    view, scroll_value, _ = _open_from_a_scrolled_gallery(viewer)

    viewer.image_popout_controller.popout_window.close()

    assert not viewer.image_popout_controller.is_open()
    _assert_pane_in_viewer(viewer)
    assert view.verticalScrollBar().value() == scroll_value


def test_first_open_fills_the_screen(viewer, qtbot):
    _open_from_a_scrolled_gallery(viewer)

    assert viewer.image_popout_controller.popout_window.isMaximized()


def test_window_geometry_is_remembered_for_the_next_open(viewer, qtbot):
    _open_from_a_scrolled_gallery(viewer)
    window = viewer.image_popout_controller.popout_window
    window.showNormal()
    window.close()
    saved = viewer.settings_service.values[ImagePopoutController.GEOMETRY_SETTING]
    assert saved

    _click_tile(viewer, 5)
    qtbot.waitExposed(window)

    # Reopened from the saved geometry, not re-maximized. (The exact size
    # is left to the platform, which fits a restored window to its screen.)
    assert viewer.image_popout_controller.is_open()
    assert not window.isMaximized()


def test_unreadable_saved_geometry_falls_back_to_filling_the_screen(viewer, qtbot):
    viewer.settings_service.values[ImagePopoutController.GEOMETRY_SETTING] = 'not a geometry'

    _open_from_a_scrolled_gallery(viewer)

    assert viewer.image_popout_controller.popout_window.isMaximized()


def test_leaving_gallery_mode_from_the_window_puts_the_pane_back(viewer):
    _open_from_a_scrolled_gallery(viewer)

    viewer.gallery_controller.toggle_gallery_mode()

    assert not viewer.gallery_mode
    assert not viewer.image_popout_controller.is_open()
    _assert_pane_in_viewer(viewer)
    assert viewer.image_gallery_splitter.sizes()[0] > 0


def test_viewer_close_cleanup_returns_the_pane(viewer):
    _open_from_a_scrolled_gallery(viewer)

    viewer.image_popout_controller.cleanup()

    assert not viewer.image_popout_controller.is_open()
    _assert_pane_in_viewer(viewer)


# ---------------------------------------------------------------------------
# Review-time logging across the two windows
# ---------------------------------------------------------------------------

def _dwell_stub(viewer_active, popout_active):
    popout_window = None
    if popout_active is not None:
        popout_window = SimpleNamespace(isActiveWindow=lambda: popout_active)
    return SimpleNamespace(
        interaction_log=MagicMock(),
        isActiveWindow=lambda: viewer_active,
        image_popout_controller=SimpleNamespace(popout_window=popout_window),
    )


def test_focus_moving_to_the_image_window_keeps_the_dwell_interval():
    stub = _dwell_stub(viewer_active=False, popout_active=True)

    Viewer._end_dwell_if_review_unfocused(stub)

    stub.interaction_log.end_current_interval.assert_not_called()


def test_focus_leaving_both_windows_ends_the_dwell_interval():
    stub = _dwell_stub(viewer_active=False, popout_active=False)

    Viewer._end_dwell_if_review_unfocused(stub)

    stub.interaction_log.end_current_interval.assert_called_once_with(REASON_WINDOW_UNFOCUSED)


def test_focus_leaving_the_viewer_without_a_window_ends_the_dwell_interval():
    stub = _dwell_stub(viewer_active=False, popout_active=None)

    Viewer._end_dwell_if_review_unfocused(stub)

    stub.interaction_log.end_current_interval.assert_called_once_with(REASON_WINDOW_UNFOCUSED)


def test_active_viewer_keeps_the_dwell_interval():
    stub = _dwell_stub(viewer_active=True, popout_active=False)

    Viewer._end_dwell_if_review_unfocused(stub)

    stub.interaction_log.end_current_interval.assert_not_called()
