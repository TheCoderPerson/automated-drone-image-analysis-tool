"""Real-thread exercise of the cancel path, with Qt warnings captured."""
import os
import sys
import time
import threading
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThread, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox

from core.controllers.images.viewer.neighbor.AOINeighborTrackingController import (
    AOINeighborTrackingController,
)

QT_MSGS = []


def _handler(mode, ctx, msg):
    QT_MSGS.append(msg)
    print("QTMSG:", msg, file=sys.stderr)


qInstallMessageHandler(_handler)


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
        {'path': str(tmp_path / 'DJI_0002.JPG'),
         'areas_of_interest': [{'center': (200, 200), 'radius': 30, 'area': 600}]},
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


def test_cancel_midflight(controller, viewer, qtbot, monkeypatch):
    """Cancel a *real* in-flight search. Watch for self-wait / hang / UAF."""
    _stub_gps(monkeypatch, _GPS())
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: None)

    observed = {}
    stop = threading.Event()

    def slow_search(**kwargs):
        observed['search_thread_is_gui'] = (
            QThread.currentThread() is QApplication.instance().thread())
        cb = kwargs.get('progress_callback')
        should_cancel = kwargs.get('should_cancel')
        for i in range(200):
            if should_cancel and should_cancel():
                observed['saw_cancel_at'] = i
                return [], False
            if cb:
                cb("Checking image %d of 200..." % i)
            time.sleep(0.02)
            if stop.is_set():
                break
        return [], False

    svc = MagicMock()
    svc.find_aoi_in_neighbors.side_effect = slow_search
    controller.neighbor_service = svc

    controller.track_selected_aoi(image_idx=0, aoi_idx=0)
    the_thread = controller._thread
    assert the_thread is not None

    # let it get going
    qtbot.wait(300)
    dialog = controller.progress_dialog
    assert dialog is not None

    t0 = time.time()
    dialog.cancel()          # exactly what the Cancel button does
    cancel_elapsed = time.time() - t0
    observed['cancel_elapsed_s'] = round(cancel_elapsed, 3)

    # spin the loop so queued work drains
    qtbot.wait(1500)
    stop.set()
    qtbot.wait(500)

    observed['retiring_len'] = len(controller._retiring)
    observed['thread_isRunning'] = the_thread.isRunning()
    observed['thread_isFinished'] = the_thread.isFinished()
    observed['generation'] = controller._generation
    observed['progress_dialog'] = controller.progress_dialog
    print("OBSERVED:", observed)
    print("QT WARNINGS:", QT_MSGS)

    assert cancel_elapsed < 1.0, "Cancel blocked the GUI thread"
    assert not any('wait on itself' in m for m in QT_MSGS), QT_MSGS


def test_second_search_during_winddown(controller, viewer, qtbot, monkeypatch):
    """Cancel then immediately press Z again: two workers alive at once?"""
    _stub_gps(monkeypatch, _GPS())
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: None)

    live = []
    lock = threading.Lock()
    peak = {'n': 0}

    def slow_search(**kwargs):
        with lock:
            live.append(1)
            peak['n'] = max(peak['n'], len(live))
        should_cancel = kwargs.get('should_cancel')
        try:
            for i in range(100):
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
    qtbot.wait(200)
    controller.progress_dialog.cancel()
    # user immediately presses Z again
    controller.track_selected_aoi(image_idx=0, aoi_idx=0)
    qtbot.wait(600)
    print("PEAK CONCURRENT WORKERS:", peak['n'])
    print("retiring:", len(controller._retiring), "gen:", controller._generation)
    if controller.progress_dialog:
        controller.progress_dialog.cancel()
    qtbot.wait(1500)
    print("QT WARNINGS:", QT_MSGS)
