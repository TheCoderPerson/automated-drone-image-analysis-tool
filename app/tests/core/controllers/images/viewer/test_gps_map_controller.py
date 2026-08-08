"""Unit tests for GPSMapController — terrain-preference threading.

The selected-AOI map marker must use the same UseTerrainElevation
preference as the viewer's AOI label and the exports, so the pin and the
label can never disagree.
"""

import pytest
from unittest.mock import patch, MagicMock


class _Parent:
    """Minimal plain-object viewer stub (avoids MagicMock's truthy getattr)."""

    def __init__(self, use_terrain=None):
        class _AOIController:
            selected_aoi_index = 0

        self.aoi_controller = _AOIController()
        self.images = [{'name': 'img1.jpg', 'areas_of_interest': [{'center': (10, 20)}]}]
        self.current_image = 0
        if use_terrain is not None:
            self.use_terrain_elevation = use_terrain


class _RecordingAOIService:
    """Records the use_terrain argument passed to the metadata helper."""

    calls = []

    def __init__(self, *_args, **_kwargs):
        pass

    def get_aoi_gps_with_metadata(self, image, aoi, aoi_index, custom_alt_ft, use_terrain=True):
        type(self).calls.append(use_terrain)
        return {'latitude': 38.0, 'longitude': -121.0}


@pytest.fixture
def make_controller():
    def _make(parent):
        with patch('core.controllers.images.viewer.GPSMapController.AOIService',
                   _RecordingAOIService):
            from core.controllers.images.viewer.GPSMapController import GPSMapController
            controller = GPSMapController(parent)
            _RecordingAOIService.calls = []
            result = controller.get_current_aoi_gps()
            return result, _RecordingAOIService.calls
    return _make


def test_marker_honors_terrain_pref_off(make_controller):
    result, calls = make_controller(_Parent(use_terrain=False))
    assert calls == [False]
    assert result['latitude'] == 38.0
    assert result['image_name'] == 'img1.jpg'


def test_marker_honors_terrain_pref_on(make_controller):
    _result, calls = make_controller(_Parent(use_terrain=True))
    assert calls == [True]


def test_marker_defaults_to_terrain_when_pref_absent(make_controller):
    _result, calls = make_controller(_Parent(use_terrain=None))
    assert calls == [True]


# ---------------------------------------------------------------------------
# Zoom-FOV throttle (freeze regression): a single wheel notch emits viewChanged
# up to twice, and each forward reruns the map's terrain-projected FOV redraw
# synchronously. update_zoom_fov must coalesce a burst into ~one redraw per
# window so it cannot saturate the GUI thread.
# ---------------------------------------------------------------------------

def _controller_with_open_dialog():
    from core.controllers.images.viewer.GPSMapController import GPSMapController
    controller = GPSMapController(_Parent())
    dialog = MagicMock()
    dialog.isVisible.return_value = True
    controller.map_dialog = dialog
    return controller, dialog


def test_update_zoom_fov_leading_edge_draws_immediately():
    controller, dialog = _controller_with_open_dialog()

    controller.update_zoom_fov('rectA')

    dialog.update_zoom_fov.assert_called_once_with('rectA')
    assert controller._fov_throttle.isActive()


def test_update_zoom_fov_coalesces_burst_to_latest():
    controller, dialog = _controller_with_open_dialog()

    controller.update_zoom_fov('r1')   # leading edge -> drawn immediately
    controller.update_zoom_fov('r2')   # coalesced
    controller.update_zoom_fov('r3')   # coalesced (latest wins)

    # Only the leading update has drawn while the throttle window is open.
    assert dialog.update_zoom_fov.call_count == 1

    # Simulate the throttle timer firing (trailing edge).
    controller._flush_zoom_fov()
    assert dialog.update_zoom_fov.call_count == 2
    assert dialog.update_zoom_fov.call_args_list[-1].args == ('r3',)

    # Nothing left pending -> a second fire is a no-op.
    controller._flush_zoom_fov()
    assert dialog.update_zoom_fov.call_count == 2


def test_update_zoom_fov_noop_when_dialog_hidden():
    controller, dialog = _controller_with_open_dialog()
    dialog.isVisible.return_value = False

    controller.update_zoom_fov('rectA')

    dialog.update_zoom_fov.assert_not_called()
    assert not controller._fov_throttle.isActive()


def test_closing_dialog_cancels_pending_fov_redraw():
    controller, dialog = _controller_with_open_dialog()

    controller.update_zoom_fov('r1')   # leading draw + starts throttle
    controller.update_zoom_fov('r2')   # pending trailing draw

    controller.on_map_dialog_closed()

    assert not controller._fov_throttle.isActive()
    assert controller._has_pending_fov is False

    # A stray timer fire after close must not touch the (closed) dialog.
    dialog.update_zoom_fov.reset_mock()
    controller._flush_zoom_fov()
    dialog.update_zoom_fov.assert_not_called()


# ---------------------------------------------------------------------------
# Draggable AOI marker: confirm + persist a user-corrected AOI position
# ---------------------------------------------------------------------------

import xml.etree.ElementTree as ET  # noqa: E402


def _controller_with_marker():
    """Controller wired to a stub dialog showing a marker for image 0, AOI 0."""
    from core.controllers.images.viewer.GPSMapController import GPSMapController
    parent = _Parent()
    xml_element = ET.Element('areas_of_interest')
    aoi = {'center': (10, 20), 'xml': xml_element}
    parent.images = [{'name': 'img1.jpg', 'areas_of_interest': [aoi]}]
    parent.xml_service = MagicMock()
    parent.xml_path = 'results/ADIAT_Data.xml'
    controller = GPSMapController(parent)
    dialog = MagicMock()
    dialog.isVisible.return_value = True
    view = MagicMock()
    view.aoi_data = {'latitude': 37.0, 'longitude': -117.0,
                     'aoi_index': 0, 'image_index': 0}
    dialog.map_view = view
    controller.map_dialog = dialog
    controller.update_aoi_on_map = MagicMock()  # marker redraw not under test
    return controller, parent, aoi, xml_element, view


def test_marker_drag_accept_persists_user_position():
    controller, parent, aoi, xml_element, view = _controller_with_marker()
    with patch('core.controllers.images.viewer.GPSMapController.QMessageBox') as box:
        box.question.return_value = box.StandardButton.Yes
        controller.on_aoi_marker_moved(37.001, -117.002)
    assert aoi['user_latitude'] == pytest.approx(37.001)
    assert aoi['user_longitude'] == pytest.approx(-117.002)
    assert float(xml_element.get('user_latitude')) == pytest.approx(37.001)
    assert float(xml_element.get('user_longitude')) == pytest.approx(-117.002)
    parent.xml_service.save_xml_file.assert_called_once_with(parent.xml_path)
    controller.update_aoi_on_map.assert_called_once()


def test_marker_drag_decline_restores_marker():
    controller, parent, aoi, xml_element, view = _controller_with_marker()
    with patch('core.controllers.images.viewer.GPSMapController.QMessageBox') as box:
        box.question.return_value = box.StandardButton.No
        controller.on_aoi_marker_moved(37.001, -117.002)
    view.reset_aoi_marker_position.assert_called_once()
    assert 'user_latitude' not in aoi
    assert xml_element.get('user_latitude') is None
    parent.xml_service.save_xml_file.assert_not_called()


def test_marker_reset_clears_user_position():
    controller, parent, aoi, xml_element, view = _controller_with_marker()
    aoi['user_latitude'] = 37.001
    aoi['user_longitude'] = -117.002
    xml_element.set('user_latitude', '37.001')
    xml_element.set('user_longitude', '-117.002')
    controller.on_aoi_reset_requested()
    assert 'user_latitude' not in aoi
    assert 'user_longitude' not in aoi
    assert xml_element.get('user_latitude') is None
    assert xml_element.get('user_longitude') is None
    parent.xml_service.save_xml_file.assert_called_once_with(parent.xml_path)


def test_marker_drag_with_stale_marker_metadata_is_safe():
    """A marker whose indices no longer resolve must not corrupt anything."""
    controller, parent, aoi, xml_element, view = _controller_with_marker()
    view.aoi_data = {'latitude': 37.0, 'longitude': -117.0,
                     'aoi_index': 5, 'image_index': 0}  # out of range
    controller.on_aoi_marker_moved(37.001, -117.002)
    view.reset_aoi_marker_position.assert_called_once()
    assert 'user_latitude' not in aoi
    parent.xml_service.save_xml_file.assert_not_called()
