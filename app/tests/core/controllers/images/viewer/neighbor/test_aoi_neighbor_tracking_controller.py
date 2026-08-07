"""Tests for AOINeighborTrackingController (the Z shortcut).

Focused on the reported crash: pressing Z (AOI neighbour tracking) took the
entire application down with no Python traceback. The cause was a native
abort(), not an exception -- ``~QThread()`` calls ``qFatal()`` when the thread
is still running, so dropping the last Python reference to a live QThread kills
the process. Two defects combined to do exactly that:

* ``_on_progress`` called ``QApplication.processEvents()``, re-entering the
  event loop from inside a slot and delivering pending key events mid-search.
* ``track_selected_aoi`` had no in-flight guard, so the reentrant press ran
  ``self._thread = QThread()`` over a still-running thread.
"""

import inspect
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from core.controllers.images.viewer.neighbor.AOINeighborTrackingController import (
    AOINeighborTrackingController,
    NeighborSearchWorker,
)


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app, tmp_path, qtbot):
    """Minimal viewer stand-in carrying the attributes the controller reads."""
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
    widget.xml_path = str(tmp_path / 'ADIAT_Data.xml')
    widget.aoi_controller = MagicMock()
    widget.gallery_mode = False
    return widget


@pytest.fixture
def controller(viewer):
    return AOINeighborTrackingController(viewer)


# --------------------------------------------------------------------------- #
#  The crash: reentrancy over a running QThread                               #
# --------------------------------------------------------------------------- #

class TestReentrancyGuard:

    def test_second_search_while_one_runs_is_ignored(self, controller, viewer):
        """The regression test for the Z-key crash.

        Without the guard this reassigned self._thread, dropping the last
        reference to a running QThread -> qFatal() -> abort().
        """
        running = MagicMock()
        controller._thread = running

        controller.track_selected_aoi(image_idx=0, aoi_idx=0)

        assert controller._thread is running, \
            "an in-flight search must not be replaced"
        viewer.aoi_controller.get_selected_aoi.assert_not_called()

    def test_guard_applies_to_single_image_path_too(self, controller, viewer):
        running = MagicMock()
        controller._thread = running
        controller.track_selected_aoi()
        assert controller._thread is running

    def test_on_progress_does_not_pump_the_event_loop(self, controller):
        """processEvents() inside a slot is what let a reentrant Z press in."""
        source = inspect.getsource(controller._on_progress)
        assert 'processEvents' not in source or 'does NOT call' in source
        assert 'QApplication.processEvents()' not in source.replace(
            'QApplication.processEvents().', ''
        ).split('"""')[-1], "the executable body must not pump events"

    def test_on_progress_updates_label_without_reentering(self, controller):
        dialog = MagicMock()
        controller.progress_dialog = dialog
        controller._on_progress("halfway")
        dialog.setLabelText.assert_called_once_with("halfway")

    def test_on_progress_with_no_dialog_is_safe(self, controller):
        controller.progress_dialog = None
        controller._on_progress("ignored")  # must not raise


# --------------------------------------------------------------------------- #
#  Thread teardown must never destroy a running QThread, nor block the GUI     #
# --------------------------------------------------------------------------- #

class TestThreadTeardown:

    def test_running_thread_is_retained_not_destroyed(self, controller):
        worker, thread = MagicMock(), MagicMock()
        thread.isRunning.return_value = True
        controller._worker, controller._thread = worker, thread

        controller._cleanup_thread()

        worker.cancel.assert_called_once()
        thread.quit.assert_called_once()
        thread.wait.assert_not_called(), "must not block the GUI thread"
        assert controller._thread is None
        assert controller._retiring[thread] is worker, \
            "a running QThread must stay referenced until it reports finished"

    def test_stopped_thread_is_released_immediately(self, controller):
        worker, thread = MagicMock(), MagicMock()
        thread.isRunning.return_value = False
        controller._worker, controller._thread = worker, thread

        controller._cleanup_thread()

        thread.wait.assert_called_once()
        assert thread not in controller._retiring

    def test_release_after_finished_drops_reference(self, controller):
        worker, thread = MagicMock(), MagicMock()
        thread.isRunning.return_value = True
        controller._worker, controller._thread = worker, thread
        controller._cleanup_thread()

        controller._release_thread(thread)

        assert thread not in controller._retiring

    def test_release_survives_deleted_cpp_object(self, controller):
        thread = MagicMock()
        thread.wait.side_effect = RuntimeError("already deleted")
        controller._retiring[thread] = None
        controller._release_thread(thread)
        assert thread not in controller._retiring

    def test_cleanup_with_no_thread_is_noop(self, controller):
        controller._cleanup_thread()
        assert controller._retiring == {}


# --------------------------------------------------------------------------- #
#  Cancellation                                                               #
# --------------------------------------------------------------------------- #

class TestCancellation:

    def test_cancel_sets_flag_and_cancels_worker(self, controller):
        worker, thread = MagicMock(), MagicMock()
        thread.isRunning.return_value = False
        controller._worker, controller._thread = worker, thread

        controller._on_cancelled()

        assert controller._cancelled is True
        worker.cancel.assert_called_once()

    def test_cancelled_search_does_not_open_the_gallery(self, controller, monkeypatch):
        """`finished` is queued, so it lands after the user cancelled."""
        shown = MagicMock()
        monkeypatch.setattr(controller, '_show_gallery_dialog', shown)
        controller._cancelled = True

        controller._on_search_complete([{'image_idx': 1, 'pixel_x': 5, 'pixel_y': 5}])

        shown.assert_not_called()

    def test_completed_search_still_opens_the_gallery(self, controller, monkeypatch):
        shown = MagicMock()
        monkeypatch.setattr(controller, '_show_gallery_dialog', shown)
        controller._cancelled = False

        results = [{'image_idx': 1, 'pixel_x': 5, 'pixel_y': 5}]
        controller._on_search_complete(results)

        shown.assert_called_once_with(results)

    def test_closing_progress_dialog_does_not_read_as_cancelled(self, controller,
                                                                monkeypatch):
        """QProgressDialog emits canceled() from its own closeEvent.

        If the handler is still connected when a *completed* search closes the
        dialog, the results are silently discarded as "cancelled".
        """
        shown = MagicMock()
        monkeypatch.setattr(controller, '_show_gallery_dialog', shown)

        dialog = MagicMock()

        def emit_canceled_on_close():
            controller._on_cancelled()

        dialog.close.side_effect = emit_canceled_on_close
        # Disconnecting is what prevents that; simulate a real disconnect by
        # making close() a no-op once canceled has been disconnected.
        disconnected = {'yes': False}

        def disconnect(_handler):
            disconnected['yes'] = True

        dialog.canceled.disconnect.side_effect = disconnect

        def close():
            if not disconnected['yes']:
                emit_canceled_on_close()

        dialog.close.side_effect = close
        controller.progress_dialog = dialog

        controller._on_search_complete([{'image_idx': 1, 'pixel_x': 5, 'pixel_y': 5}])

        dialog.canceled.disconnect.assert_called_once_with(controller._on_cancelled)
        assert controller._cancelled is False
        shown.assert_called_once()

    def test_close_progress_dialog_tolerates_missing_connection(self, controller):
        dialog = MagicMock()
        dialog.canceled.disconnect.side_effect = TypeError("not connected")
        controller.progress_dialog = dialog
        controller._close_progress_dialog()
        dialog.close.assert_called_once()
        assert controller.progress_dialog is None


# --------------------------------------------------------------------------- #
#  Worker contract                                                            #
# --------------------------------------------------------------------------- #

class TestWorker:

    def test_cancel_before_run_skips_the_service(self, app):
        service = MagicMock()
        worker = NeighborSearchWorker(service, [], 0, (1.0, 2.0))
        finished = []
        worker.finished.connect(finished.append)

        worker.cancel()
        worker.run()

        service.find_aoi_in_neighbors.assert_not_called()
        assert finished == [[]]

    def test_run_emits_results(self, app):
        service = MagicMock()
        service.find_aoi_in_neighbors.return_value = [{'image_idx': 1}]
        worker = NeighborSearchWorker(service, [], 0, (1.0, 2.0))
        finished = []
        worker.finished.connect(finished.append)

        worker.run()

        assert finished == [[{'image_idx': 1}]]

    def test_service_exception_emits_error(self, app):
        service = MagicMock()
        service.find_aoi_in_neighbors.side_effect = RuntimeError("boom")
        worker = NeighborSearchWorker(service, [], 0, (1.0, 2.0))
        errors = []
        worker.error.connect(errors.append)

        worker.run()

        assert errors == ["boom"]


# --------------------------------------------------------------------------- #
#  Full-flight search scope (Z must not be blind to detection-less images)    #
# --------------------------------------------------------------------------- #

class TestFullFlightSearchScope:
    """The search must cover the whole flight, not just the AOI-bearing subset.

    The result XML only carries images that produced detections, so handing
    ``parent.images`` to the neighbor search silently skipped every capture
    with no AOIs of its own -- exactly the images a reviewer wants Z to check.
    """

    def test_search_scope_prefers_source_images(self, controller, viewer, tmp_path):
        viewer.source_images = [
            {'path': str(tmp_path / 'DJI_0000.JPG'), 'name': 'DJI_0000.JPG', 'has_aoi': False},
            {'path': viewer.images[0]['path'], 'name': 'DJI_0001.JPG', 'has_aoi': True},
            {'path': str(tmp_path / 'DJI_0001_5.JPG'), 'name': 'DJI_0001_5.JPG', 'has_aoi': False},
            {'path': viewer.images[1]['path'], 'name': 'DJI_0002.JPG', 'has_aoi': True},
        ]

        images, idx = controller._build_search_scope(viewer.images[0], 0)

        assert images is viewer.source_images
        assert idx == 1  # located by path, not by viewer index

    def test_search_scope_falls_back_without_source_images(self, controller, viewer):
        images, idx = controller._build_search_scope(viewer.images[1], 1)

        assert images is viewer.images
        assert idx == 1

    def test_search_scope_falls_back_when_current_image_missing(self, controller, viewer, tmp_path):
        viewer.source_images = [
            {'path': str(tmp_path / 'OTHER.JPG'), 'name': 'OTHER.JPG', 'has_aoi': False},
        ]

        images, idx = controller._build_search_scope(viewer.images[0], 0)

        assert images is viewer.images
        assert idx == 0


class TestGalleryClickMapsToViewerIndex:
    """Result indices live in full-flight space; navigation lives in viewer space."""

    def test_click_navigates_by_path_not_search_index(self, controller, viewer):
        # Full-flight index 3 corresponds to the viewer's image 1
        controller._neighbor_results = [
            {'image_idx': 3, 'image_path': viewer.images[1]['path'],
             'image_name': 'DJI_0002.JPG', 'pixel_x': None, 'pixel_y': None},
        ]
        viewer._load_image = MagicMock()

        controller._on_gallery_image_clicked(3)

        assert viewer.current_image == 1
        viewer._load_image.assert_called_once()

    def test_click_on_detection_less_capture_does_not_navigate(self, controller, viewer, tmp_path):
        controller._neighbor_results = [
            {'image_idx': 2, 'image_path': str(tmp_path / 'NO_AOI.JPG'),
             'image_name': 'NO_AOI.JPG', 'pixel_x': 10, 'pixel_y': 10},
        ]
        viewer._load_image = MagicMock()
        before = viewer.current_image

        controller._on_gallery_image_clicked(2)

        assert viewer.current_image == before
        viewer._load_image.assert_not_called()

    def test_detection_less_results_are_labeled_in_the_gallery(self, controller, viewer,
                                                               monkeypatch, tmp_path):
        import core.views.images.viewer.dialogs.AOINeighborGalleryDialog as gallery_module
        monkeypatch.setattr(gallery_module, 'AOINeighborGalleryDialog', MagicMock())

        results = [
            {'image_idx': 1, 'image_path': viewer.images[0]['path'],
             'image_name': 'DJI_0001.JPG', 'thumbnail': None, 'pixel_x': 0, 'pixel_y': 0},
            {'image_idx': 5, 'image_path': str(tmp_path / 'NO_AOI.JPG'),
             'image_name': 'NO_AOI.JPG', 'thumbnail': None, 'pixel_x': 0, 'pixel_y': 0},
        ]

        controller._show_gallery_dialog(results)

        assert results[0]['image_name'] == 'DJI_0001.JPG'
        assert 'no detections' in results[1]['image_name']
