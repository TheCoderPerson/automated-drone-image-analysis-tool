"""Tests for the POD overlay orchestration + cell inspect on GPSMapController."""

import numpy as np
import pytest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from core.controllers.images.viewer.GPSMapController import GPSMapController
from core.services.coverage.params import PodParams
from core.services.coverage.contracts import CoverageResult, LIMIT_CANOPY
from core.services.terrain.grid import make_lattice_spec, lonlat_to_mercator


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _controller(app):
    parent = MagicMock()
    parent.images = [{"name": "A"}, {"name": "B"}]
    return GPSMapController(parent)


def _real_result(rows=40, cols=30):
    minx, miny = lonlat_to_mercator(-120.50, 38.70)
    spec = make_lattice_spec((minx, miny, minx + cols * 3.0, miny + rows * 3.0), 3.0)
    pod = np.full((spec.height, spec.width), 0.6, dtype=np.float32)
    look = np.full((spec.height, spec.width), 2, dtype=np.uint16)
    return CoverageResult(pod=pod, look_count=look, transform=spec.transform,
                          image_count=2, skipped=[], stats={}, gap_polygons=[],
                          cancelled=False, params=PodParams())


def test_click_with_overlay_shows_inspect_menu(app):
    ctrl = _controller(app)
    ctrl._pod_overlay_enabled = True
    ctrl._show_pod_inspect_menu = MagicMock()
    ctrl._reverse_locate = MagicMock()

    result = MagicMock()
    result.sample.return_value = {'pod': 0.6, 'looks': 2, 'limiting_factor': LIMIT_CANOPY, 'frames': [0]}
    cache = MagicMock()
    cache.has_result.return_value = True
    cache.get_result.return_value = result
    ctrl.parent.pod_result_cache = cache

    ctrl.on_map_gps_clicked(38.71, -120.49)
    ctrl._show_pod_inspect_menu.assert_called_once()
    ctrl._reverse_locate.assert_not_called()


def test_click_off_coverage_falls_back_to_reverse_locate(app):
    ctrl = _controller(app)
    ctrl._pod_overlay_enabled = True
    ctrl._show_pod_inspect_menu = MagicMock()
    ctrl._reverse_locate = MagicMock()

    result = MagicMock()
    result.sample.return_value = None
    cache = MagicMock()
    cache.has_result.return_value = True
    cache.get_result.return_value = result
    ctrl.parent.pod_result_cache = cache

    ctrl.on_map_gps_clicked(0.0, 0.0)
    ctrl._show_pod_inspect_menu.assert_not_called()
    ctrl._reverse_locate.assert_called_once()


def test_click_overlay_disabled_uses_reverse_locate(app):
    ctrl = _controller(app)
    ctrl._pod_overlay_enabled = False
    ctrl._reverse_locate = MagicMock()
    ctrl.on_map_gps_clicked(38.71, -120.49)
    ctrl._reverse_locate.assert_called_once()


def test_build_pod_pixmap_downsamples_and_rescales(app):
    ctrl = _controller(app)
    result = _real_result(rows=2100, cols=40)   # > 2048 -> shrinks
    pixmap, transform6 = ctrl._build_pod_pixmap(result, 'pod')
    assert pixmap.width() <= 2048 and pixmap.height() <= 2048
    a0 = tuple(result.transform)[0]
    # Cell size grows because the raster was downsampled.
    assert transform6[0] > a0


def test_on_pod_display_changed_sets_and_clears_overlay(app):
    ctrl = _controller(app)
    ctrl.map_dialog = MagicMock()
    view = MagicMock()
    ctrl.map_dialog.map_view = view
    cache = MagicMock()
    cache.has_result.return_value = True
    cache.get_result.return_value = _real_result()
    ctrl.parent.pod_result_cache = cache

    ctrl.on_pod_display_changed(True, 'pod', 60)
    assert ctrl._pod_overlay_enabled is True
    view.set_pod_overlay.assert_called_once()
    view.set_pod_overlay_opacity.assert_called_with(0.6)

    ctrl.on_pod_display_changed(False, 'pod', 60)
    assert ctrl._pod_overlay_enabled is False
    view.clear_pod_overlay.assert_called_once()
