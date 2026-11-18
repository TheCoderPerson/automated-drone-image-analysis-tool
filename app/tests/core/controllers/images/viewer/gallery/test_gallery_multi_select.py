"""Ctrl+click multi-selection in the AOI gallery, and marking it as duplicates.

The first AOI selected is the primary: D (or the right-click menu) marks every
other selected AOI as its duplicate, with no picker. These tests drive a real
QListView with real mouse events, because the behaviour lives in how the view,
its selection model and GalleryUIComponent's event filter interact.
"""

import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from core.services.AOIDuplicateService import DuplicateChange

GALLERY_PACKAGE = "core.controllers.images.viewer.gallery"


def _images():
    """Three images, two numbered AOIs each: gallery rows 0-5 are AOIs #1-#6."""
    images = []
    number = 1
    for image_idx in range(3):
        aois = []
        for _ in range(2):
            aois.append({'center': (10 * number, 10 * number), 'radius': 5, 'area': 20, 'number': number})
            number += 1
        images.append({'name': f'DJI_000{image_idx + 1}.JPG', 'path': '', 'areas_of_interest': aois})
    return images


def _ref(row):
    """(image_idx, aoi_idx) of the AOI on a gallery row of _images()."""
    return (row // 2, row % 2)


@pytest.fixture
def gallery(app, qtbot):
    """A real GalleryController, model and view over _images(), shown on screen.

    Returns:
        GalleryController: its parent is a MagicMock viewer in gallery mode.
    """
    parent = MagicMock()
    parent.images = _images()
    parent.alternative_cache_dir = None
    parent.xml_path = None
    parent.gallery_mode = True
    parent.current_image = 0

    with patch(f"{GALLERY_PACKAGE}.AOIGalleryModel.ThumbnailLoader"):
        from core.controllers.images.viewer.gallery.GalleryController import GalleryController
        controller = GalleryController(parent)
    parent.gallery_controller = controller

    widget = controller.create_gallery_widget()
    qtbot.addWidget(widget)
    controller.model.set_aoi_items(controller._collect_all_aois(), skip_color_calc=True)
    widget.resize(700, 500)
    widget.show()
    qtbot.waitExposed(widget)

    yield controller

    # The patched ThumbnailLoader mock holds the model's bound slots (a reference
    # cycle); break it so the model is freed while QApplication is alive.
    controller.model.thumbnail_loader = None
    controller.model.viewer = None


def _view(controller):
    return controller.ui_component.gallery_view


def _click(qtbot, controller, row, modifier=Qt.NoModifier, button=Qt.LeftButton):
    view = _view(controller)
    position = view.visualRect(controller.model.index(row, 0)).center()
    qtbot.mouseClick(view.viewport(), button, modifier, position)


def _ctrl_click(qtbot, controller, row):
    _click(qtbot, controller, row, modifier=Qt.ControlModifier)


def _selected_rows(controller):
    return sorted(index.row() for index in _view(controller).selectionModel().selectedIndexes())


# ---------------------------------------------------------------------------
# Building the selection
# ---------------------------------------------------------------------------

def test_plain_click_selects_one_aoi_and_shows_it(gallery, qtbot):
    _click(qtbot, gallery, 3)

    assert gallery.get_selected_aois() == [_ref(3)]
    assert _view(gallery).currentIndex().row() == 3
    gallery.parent.aoi_controller.select_aoi.assert_called_once()


def test_ctrl_click_adds_aois_in_the_order_they_were_clicked(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    _ctrl_click(qtbot, gallery, 5)

    assert gallery.get_selected_aois() == [_ref(3), _ref(0), _ref(5)]
    assert _selected_rows(gallery) == [0, 3, 5]


def test_ctrl_click_keeps_the_first_aoi_current_and_does_not_navigate(gallery, qtbot):
    _click(qtbot, gallery, 3)
    gallery.parent.aoi_controller.select_aoi.reset_mock()
    gallery.parent.load_image_with_zoom.reset_mock()

    _ctrl_click(qtbot, gallery, 0)

    assert _view(gallery).currentIndex().row() == 3
    gallery.parent.aoi_controller.select_aoi.assert_not_called()
    gallery.parent.load_image_with_zoom.assert_not_called()


def test_ctrl_click_on_a_selected_aoi_takes_it_back_out(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    _ctrl_click(qtbot, gallery, 5)

    _ctrl_click(qtbot, gallery, 0)

    assert gallery.get_selected_aois() == [_ref(3), _ref(5)]


def test_ctrl_click_on_the_first_aoi_promotes_the_next_one(gallery, qtbot):
    """The release of that Ctrl+click must not reach the view: row 3 was the last
    tile it saw pressed, so it would emit clicked and select row 3 alone again."""
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    _ctrl_click(qtbot, gallery, 5)
    gallery.parent.aoi_controller.select_aoi.reset_mock()

    _ctrl_click(qtbot, gallery, 3)

    assert gallery.get_selected_aois() == [_ref(0), _ref(5)]
    # The new first AOI is the current one, and the viewer follows it
    assert _view(gallery).currentIndex().row() == 0
    gallery.parent.aoi_controller.select_aoi.assert_called_once()


def test_ctrl_click_never_empties_the_selection(gallery, qtbot):
    _click(qtbot, gallery, 3)

    _ctrl_click(qtbot, gallery, 3)

    assert gallery.get_selected_aois() == [_ref(3)]


def test_ctrl_click_with_nothing_selected_is_a_plain_click(gallery, qtbot):
    _ctrl_click(qtbot, gallery, 4)

    assert gallery.get_selected_aois() == [_ref(4)]
    assert _view(gallery).currentIndex().row() == 4
    gallery.parent.aoi_controller.select_aoi.assert_called_once()


def test_two_quick_ctrl_clicks_toggle_twice(gallery, qtbot):
    """The second of two quick clicks on one tile arrives as a double-click."""
    _click(qtbot, gallery, 3)
    view = _view(gallery)
    position = view.visualRect(gallery.model.index(0, 0)).center()

    qtbot.mouseClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, position)
    assert gallery.get_selected_aois() == [_ref(3), _ref(0)]
    qtbot.mouseDClick(view.viewport(), Qt.LeftButton, Qt.ControlModifier, position)

    assert gallery.get_selected_aois() == [_ref(3)]


def test_plain_click_starts_over(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    _click(qtbot, gallery, 5)

    assert gallery.get_selected_aois() == [_ref(5)]


def test_arrow_key_navigation_starts_over(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    gallery.navigate_gallery_aoi(1)

    assert gallery.get_selected_aois() == [_ref(4)]


def test_model_reset_drops_the_selection_order(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    gallery.model.set_aoi_items(gallery._collect_all_aois(), skip_color_calc=True)

    assert gallery.get_selected_aois() == []
    assert gallery.ui_component.multi_selection_primary() is None

    # A selection made after the reset starts a new order
    _click(qtbot, gallery, 0)
    _ctrl_click(qtbot, gallery, 3)
    assert gallery.get_selected_aois() == [_ref(0), _ref(3)]


def test_flag_refresh_keeps_the_selection(gallery, qtbot):
    """F on the first AOI repaints its flag; the other selected AOIs stay selected."""
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    gallery._refresh_gallery_flag_display(*_ref(3))

    assert gallery.get_selected_aois() == [_ref(3), _ref(0)]


# ---------------------------------------------------------------------------
# Right-click
# ---------------------------------------------------------------------------

def test_right_click_on_a_selected_aoi_keeps_the_selection(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    _click(qtbot, gallery, 0, button=Qt.RightButton)

    assert gallery.get_selected_aois() == [_ref(3), _ref(0)]
    menu_call = gallery.parent.aoi_controller.show_aoi_context_menu.call_args
    assert menu_call.args[5] == _ref(0)[1]
    assert menu_call.kwargs['image_idx'] == _ref(0)[0]


def test_right_click_on_another_aoi_selects_it_alone(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)

    _click(qtbot, gallery, 5, button=Qt.RightButton)

    assert gallery.get_selected_aois() == [_ref(5)]
    gallery.parent.aoi_controller.show_aoi_context_menu.assert_called_once()


# ---------------------------------------------------------------------------
# The "Primary" marker
# ---------------------------------------------------------------------------

def test_primary_is_named_only_while_several_are_selected(gallery, qtbot):
    _click(qtbot, gallery, 3)
    assert gallery.ui_component.multi_selection_primary() is None

    _ctrl_click(qtbot, gallery, 0)
    assert gallery.ui_component.multi_selection_primary() == _ref(3)


def test_delegate_draws_the_marker_on_the_first_selected_aoi_only(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    view = _view(gallery)
    delegate = view.itemDelegate()
    pixmap = QPixmap(200, 200)

    def paint(row, selected=True):
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 190, 190)
        if selected:
            option.state |= QStyle.State_Selected
        painter = QPainter(pixmap)
        try:
            with patch.object(delegate, '_draw_primary_marker') as marker:
                delegate.paint(painter, option, gallery.model.index(row, 0))
        finally:
            painter.end()
        return marker.called

    assert paint(3) is True
    assert paint(0) is False
    assert paint(5, selected=False) is False


def test_primary_marker_renders(gallery, qtbot):
    delegate = _view(gallery).itemDelegate()
    pixmap = QPixmap(200, 200)
    painter = QPainter(pixmap)
    try:
        delegate._draw_primary_marker(painter, QRect(5, 5, 180, 180))
    finally:
        painter.end()


# ---------------------------------------------------------------------------
# Marking the selection as duplicates
# ---------------------------------------------------------------------------

def test_mark_selected_duplicates_links_the_rest_to_the_first(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    _ctrl_click(qtbot, gallery, 5)
    similarity = gallery.parent.similarity_controller
    similarity.mark_duplicates_of_first.return_value = DuplicateChange(
        primary=_ref(3), changed=[_ref(0), _ref(5)], touched=[_ref(0), _ref(5)])

    assert gallery.mark_selected_duplicates() is True

    similarity.mark_duplicates_of_first.assert_called_once_with([_ref(3), _ref(0), _ref(5)])
    # The selection falls back to the primary alone
    assert gallery.get_selected_aois() == [_ref(3)]
    assert _view(gallery).currentIndex().row() == 3


def test_mark_selected_duplicates_leaves_a_single_selection_to_the_picker(gallery, qtbot):
    _click(qtbot, gallery, 3)

    assert gallery.mark_selected_duplicates() is False

    gallery.parent.similarity_controller.mark_duplicates_of_first.assert_not_called()


def test_mark_selected_duplicates_with_nothing_selected(gallery):
    assert gallery.mark_selected_duplicates() is False


def test_selection_survives_when_nothing_could_be_linked(gallery, qtbot):
    _click(qtbot, gallery, 3)
    _ctrl_click(qtbot, gallery, 0)
    gallery.parent.similarity_controller.mark_duplicates_of_first.return_value = None

    assert gallery.mark_selected_duplicates() is True

    assert gallery.get_selected_aois() == [_ref(3), _ref(0)]
