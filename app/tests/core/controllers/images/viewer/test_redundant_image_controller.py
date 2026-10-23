"""RedundantImageController: the Skip Redundant toggle, threshold and decision cache."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QSpinBox, QWidget

from core.controllers.images.viewer.RedundantImageController import (
    DEFAULT_THRESHOLD_PERCENT,
    THRESHOLD_SETTING,
    RedundantImageController,
)
from core.services.coverage.ImageOverlapService import Footprint, FootprintSet

T0 = datetime(2026, 6, 10, 12, 0, 0)


def _square(col0=0, size=10, gsd=5.0):
    return Footprint(
        row0=0, col0=col0, visible=np.ones((size, size), dtype=bool),
        gsd_cm=np.full((size, size), gsd, dtype=np.float32),
        look=np.array([0.0, 0.0, 1.0]), capture_time=T0, sensor=(13.2, 8.8, 4000, 3000),
        median_gsd_cm=gsd, cell_count=size * size)


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, name, default_value=None):
        return self.values.get(name, default_value)

    def set_setting(self, name, value):
        self.values[name] = value


class _FakeService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def compute_footprints(self, images, progress_callback=None, cancel_check=None):
        self.calls += 1
        if self.error:
            raise self.error
        if progress_callback:
            progress_callback(len(images), len(images), "done")
        return self.result


def _image(name, flagged=False):
    return {'name': name, 'path': name, 'hidden': False,
            'areas_of_interest': [{'flagged': flagged}]}


@pytest.fixture
def viewer(qtbot):
    """A stand-in viewer: a real QWidget (dialog parent) with the real widgets."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.skipRedundant = QCheckBox(parent)
    parent.redundantOverlapSpinBox = QSpinBox(parent)
    parent.redundantOverlapSpinBox.setRange(50, 100)
    parent.redundantOverlapSpinBox.setValue(90)
    parent.settings_service = _Settings({THRESHOLD_SETTING: 85})
    parent.status_controller = MagicMock()
    parent.altitude_controller = MagicMock()
    parent.altitude_controller.get_effective_altitude.return_value = None
    parent.show_hidden = False
    # 0 and 1 are 90% overlapping; 2 is elsewhere.
    parent.images = [_image('a.jpg'), _image('b.jpg'), _image('c.jpg')]
    return parent


def _footprint_set():
    return FootprintSet(footprints=[_square(0), _square(1), _square(40)], skipped=[])


def _ready(controller):
    """Footprints computed, filter on (as after a completed worker run)."""
    controller._on_footprints_ready(_footprint_set())
    return controller


def test_threshold_is_restored_from_settings(viewer):
    RedundantImageController(viewer)
    assert viewer.redundantOverlapSpinBox.value() == 85
    assert viewer.skipRedundant.text() == "Skip Redundant"
    assert not viewer.skipRedundant.isChecked()


def test_threshold_defaults_without_a_saved_value(viewer):
    viewer.settings_service = _Settings()
    RedundantImageController(viewer)
    assert viewer.redundantOverlapSpinBox.value() == DEFAULT_THRESHOLD_PERCENT


def test_nothing_is_skipped_before_the_filter_is_on(viewer):
    controller = RedundantImageController(viewer)
    controller.footprint_set = _footprint_set()
    assert not any(controller.is_skipped(i) for i in range(3))


def test_redundant_image_is_skipped_once_computed(viewer):
    controller = _ready(RedundantImageController(viewer))
    assert [controller.is_skipped(i) for i in range(3)] == [False, True, False]
    assert viewer.skipRedundant.text() == "Skip Redundant (1) "


def test_threshold_change_is_saved_and_redecides(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.redundantOverlapSpinBox.setValue(95)
    assert viewer.settings_service.values[THRESHOLD_SETTING] == 95
    assert not controller.is_skipped(1)
    assert viewer.skipRedundant.text() == "Skip Redundant (0) "


def test_flagging_an_aoi_brings_the_image_back(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.images[1]['areas_of_interest'][0]['flagged'] = True
    assert not controller.is_skipped(1)


def test_hidden_image_cannot_stand_in_while_skip_hidden_is_on(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.images[0]['hidden'] = True
    assert not controller.is_skipped(1)
    # With Skip Hidden off the hidden image is shown, so it covers again.
    viewer.show_hidden = True
    assert controller.is_skipped(1)


def test_unchecking_turns_the_filter_off(viewer, qtbot):
    controller = _ready(RedundantImageController(viewer))
    viewer.skipRedundant.setChecked(True)
    qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
    assert not controller.enabled
    assert not controller.is_skipped(1)
    assert viewer.skipRedundant.text() == "Skip Redundant"


def test_turning_on_computes_footprints_on_a_worker(viewer, qtbot):
    controller = RedundantImageController(viewer)
    service = _FakeService(result=_footprint_set())
    with patch.object(controller, '_build_service', return_value=service):
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.waitUntil(lambda: controller.enabled, timeout=5000)
    assert service.calls == 1
    assert controller.is_skipped(1)
    viewer.status_controller.show_toast.assert_called()

    # Turning it off and on again reuses the footprints.
    with patch.object(controller, '_build_service', return_value=service):
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
    assert controller.enabled
    assert service.calls == 1
    controller._thread.wait(2000)


def test_changed_altitude_override_recomputes(viewer, qtbot):
    controller = RedundantImageController(viewer)
    service = _FakeService(result=_footprint_set())
    with patch.object(controller, '_build_service', return_value=service):
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.waitUntil(lambda: controller.enabled, timeout=5000)
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        viewer.altitude_controller.get_effective_altitude.return_value = 300.0
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.waitUntil(lambda: service.calls == 2 and controller.enabled, timeout=5000)
    controller._thread.wait(2000)


def test_cancelled_computation_unchecks_the_box(viewer, qtbot):
    controller = RedundantImageController(viewer)
    cancelled = FootprintSet(footprints=[], skipped=[], cancelled=True)
    with patch.object(controller, '_build_service', return_value=_FakeService(result=cancelled)):
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.waitUntil(lambda: not viewer.skipRedundant.isChecked(), timeout=5000)
    assert not controller.enabled
    assert controller.footprint_set is None
    controller._thread.wait(2000)


def test_failed_computation_unchecks_the_box_and_reports(viewer, qtbot):
    controller = RedundantImageController(viewer)
    failing = _FakeService(error=RuntimeError("no terrain"))
    with patch.object(controller, '_build_service', return_value=failing), \
            patch('core.controllers.images.viewer.RedundantImageController.QMessageBox') as box:
        qtbot.mouseClick(viewer.skipRedundant, Qt.LeftButton)
        qtbot.waitUntil(lambda: box.critical.called, timeout=5000)
    assert not viewer.skipRedundant.isChecked()
    assert not controller.enabled
    assert "no terrain" in box.critical.call_args[0][2]
    controller._thread.wait(2000)


def test_reaching_a_redundant_image_directly_says_why(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.status_controller.reset_mock()
    controller.on_image_loaded(1)
    text = viewer.status_controller.show_toast.call_args[0][0]
    assert "90%" in text and "a.jpg" in text


def test_loading_a_kept_image_says_nothing(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.status_controller.reset_mock()
    controller.on_image_loaded(0)
    viewer.status_controller.show_toast.assert_not_called()


def test_stale_footprints_for_a_different_image_list_skip_nothing(viewer):
    controller = _ready(RedundantImageController(viewer))
    viewer.images.append(_image('d.jpg'))
    assert controller.redundant_images() == {}
