"""Instrumented: cancel then immediately press Z again."""
import sys
import time
import threading
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

from core.controllers.images.viewer.neighbor.AOINeighborTrackingController import (
    AOINeighborTrackingController,
)


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app, tmp_path, qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.images = [
        {'path': str(tmp_path / 'DJI_0001.JPG'),
         'areas_of_interest': [{'center': (100, 100), 'radius': 20, 'area': 400}]},
    ]
    widget.current_image = 0
    widget.current_image_array = None
    widget.aoi_controller = MagicMock()
    widget.gallery_mode = False
    widget.show()
    return widget


@pytest.fixture
def controller(viewer):
    return AOINeighborTrackingController(viewer)


def _stub_gps(monkeypatch, result):
    mod = sys.modules[
        'core.controllers.images.viewer.neighbor.AOINeighborTrackingController']
    service = MagicMock()
    service.estimate_aoi_gps.return_value = result
    monkeypatch.setattr(mod, 'AOIService', lambda *a, **k: service)
    return service


class _GPS:
    terrain_elevation_m = 250.0

    def to_tuple(self):
        return (32.0, -97.0)


def test_second_search_during_winddown(controller, viewer, qtbot, monkeypatch):
    _stub_gps(monkeypatch, _GPS())
    for name in ('information', 'warning', 'critical'):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)

    live = []
    lock = threading.Lock()
    peak = {'n': 0}
    starts = []

    def slow_search(**kwargs):
        with lock:
            live.append(1)
            peak['n'] = max(peak['n'], len(live))
            starts.append(time.time())
        should_cancel = kwargs.get('should_cancel')
        try:
            for i in range(150):
                if should_cancel and should_cancel():
                    return [], False
                time.sleep(0.02)
        finally:
            with lock:
                live.pop()
        return [], False

    svc = MagicMock()
    svc.find_aoi_in_neighbors.side_effect = slow_search
    controller.neighbor_service = svc

    controller.track_selected_aoi(image_idx=0, aoi_idx=0)
    qtbot.wait(300)
    print("A: thread=%r gen=%d dialog=%r" % (
        controller._thread, controller._generation, controller.progress_dialog))
    controller.progress_dialog.canceled.emit()   # what the Cancel button does
    print("B: after cancel thread=%r gen=%d cancelled=%r dialog=%r" % (
        controller._thread, controller._generation, controller._cancelled,
        controller.progress_dialog))
    controller.track_selected_aoi(image_idx=0, aoi_idx=0)
    print("C: after 2nd Z thread=%r gen=%d cancelled=%r dialog=%r" % (
        controller._thread, controller._generation, controller._cancelled,
        controller.progress_dialog))
    qtbot.wait(800)
    print("D: peak=%d starts=%d gen=%d retiring=%d thread=%r" % (
        peak['n'], len(starts), controller._generation,
        len(controller._retiring), controller._thread))
    if controller.progress_dialog is not None:
        controller.progress_dialog.cancel()
    qtbot.wait(2500)
    print("E: peak=%d gen=%d retiring=%d" % (
        peak['n'], controller._generation, len(controller._retiring)))
