"""Unit tests for UnifiedMapExportController."""

import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QDialog

from core.controllers.images.viewer.exports.UnifiedMapExportController import (
    UnifiedMapExportController,
    UnifiedMapExportThread,
    CoveragePodExportThread,
)


def _parent():
    parent = MagicMock()
    parent.images = [
        {"path": "a.jpg", "hidden": False, "areas_of_interest": [{"id": 1}], "name": "A"},
        {"path": "b.jpg", "hidden": False, "areas_of_interest": [{"id": 2}], "name": "B"},
    ]
    parent.aoi_controller.flagged_aois = {0: {0}}
    parent.altitude_controller.get_effective_altitude.return_value = None
    parent.use_terrain_elevation = True
    parent.status_controller = MagicMock()
    return parent


@pytest.fixture
def controller():
    return UnifiedMapExportController(_parent())


# ---------------------------------------------------------------------------
# Thread behavior
# ---------------------------------------------------------------------------

def test_thread_cancel_sets_flag():
    thread = UnifiedMapExportThread(
        MagicMock(), MagicMock(), [], {},
        include_locations=False,
        include_images_without_flagged_aois=False,
        include_flagged_aois=False,
        include_coverage=False,
        output_path="/out.kml",
    )
    assert thread.is_cancelled() is False
    thread.cancel()
    assert thread.is_cancelled() is True


def test_thread_emits_finished_when_nothing_to_do():
    kml_service = MagicMock()
    thread = UnifiedMapExportThread(
        kml_service, MagicMock(),
        [{"path": "a.jpg", "hidden": False}],
        {},
        include_locations=False,
        include_images_without_flagged_aois=False,
        include_flagged_aois=False,
        include_coverage=False,
        output_path="/out.kml",
    )
    received = []
    thread.finished.connect(lambda: received.append(True))
    thread.run()
    assert received == [True]
    kml_service.save_kml.assert_called_once_with("/out.kml")


def test_thread_emits_error_on_exception():
    kml_service = MagicMock()
    kml_service.generate_image_locations_kml.side_effect = RuntimeError("fail")
    thread = UnifiedMapExportThread(
        kml_service, MagicMock(),
        [{"path": "a.jpg", "hidden": False}],
        {},
        include_locations=True,
        include_images_without_flagged_aois=True,
        include_flagged_aois=False,
        include_coverage=False,
        output_path="/out.kml",
    )
    errors = []
    thread.errorOccurred.connect(lambda msg: errors.append(msg))
    thread.run()
    assert len(errors) == 1
    assert "fail" in errors[0]


def test_thread_location_filter_skips_hidden_images():
    kml_service = MagicMock()
    thread = UnifiedMapExportThread(
        kml_service, MagicMock(),
        [
            {"path": "a.jpg", "hidden": True},
            {"path": "b.jpg", "hidden": False},
        ],
        {1: {0}},
        include_locations=True,
        include_images_without_flagged_aois=False,
        include_flagged_aois=False,
        include_coverage=False,
        output_path="/out.kml",
    )
    thread.run()
    # Only non-hidden image with flagged aoi should have been passed
    call_images = kml_service.generate_image_locations_kml.call_args[0][0]
    assert all(not img.get("hidden") for img in call_images)


# ---------------------------------------------------------------------------
# Controller callbacks
# ---------------------------------------------------------------------------

def test_on_progress_updated_forwards(controller):
    controller.progress_dialog = MagicMock()
    controller._on_progress_updated(1, 10, "msg")
    controller.progress_dialog.update_progress.assert_called_once_with(1, 10, "msg")


def test_on_export_finished_shows_toast(controller):
    controller.progress_dialog = MagicMock()
    controller._on_export_finished()
    controller.progress_dialog.accept.assert_called_once()
    controller.parent.status_controller.show_toast.assert_called_once()


def test_on_export_cancelled_terminates_thread(controller):
    controller.progress_dialog = MagicMock()
    controller.progress_dialog.isVisible.return_value = True
    controller.export_thread = MagicMock()
    controller.export_thread.isRunning.return_value = True

    controller._on_export_cancelled()

    controller.export_thread.terminate.assert_called_once()
    controller.export_thread.wait.assert_called_once()
    controller.progress_dialog.reject.assert_called_once()


def test_on_export_error_shows_critical(controller):
    controller.progress_dialog = MagicMock()
    controller.progress_dialog.isVisible.return_value = True
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.QMessageBox"
    ) as MockQMB:
        controller._on_export_error("boom")

    MockQMB.critical.assert_called_once()


# ---------------------------------------------------------------------------
# show_export_dialog flow: selection validation
# ---------------------------------------------------------------------------

def test_show_export_dialog_cancelled_by_user(controller):
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog:
        MockDialog.return_value.exec.return_value = QDialog.Rejected
        controller.show_export_dialog()


def test_show_export_dialog_no_data_selected_warns(controller):
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog, patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.QMessageBox"
    ) as MockQMB:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "kml"
        d.should_include_locations.return_value = False
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = False
        d.should_show_pod_on_map.return_value = False
        d.should_include_images.return_value = False

        controller.show_export_dialog()

    MockQMB.warning.assert_called_once()


def test_show_export_dialog_kml_export_calls_kml_method(controller):
    controller._export_to_kml = MagicMock()
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "kml"
        d.should_include_locations.return_value = True
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = False
        d.should_show_pod_on_map.return_value = False

        controller.show_export_dialog()

    controller._export_to_kml.assert_called_once()


def test_show_export_dialog_caltopo_method_cancelled(controller):
    controller._export_to_caltopo = MagicMock()
    controller._export_to_caltopo_via_api = MagicMock()
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog, patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.CalTopoMethodDialog"
    ) as MockMethod:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "caltopo"
        d.should_include_locations.return_value = True
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = False
        d.should_show_pod_on_map.return_value = False
        d.should_include_images.return_value = True
        MockMethod.return_value.exec.return_value = QDialog.Rejected

        controller.show_export_dialog()

    controller._export_to_caltopo.assert_not_called()
    controller._export_to_caltopo_via_api.assert_not_called()


def test_show_export_dialog_caltopo_api_path(controller):
    controller._export_to_caltopo_via_api = MagicMock()
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog, patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.CalTopoMethodDialog"
    ) as MockMethod:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "caltopo"
        d.should_include_locations.return_value = True
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = False
        d.should_show_pod_on_map.return_value = False
        d.should_include_images.return_value = True
        MockMethod.return_value.exec.return_value = QDialog.Accepted
        MockMethod.return_value.get_selected_method.return_value = "api"

        controller.show_export_dialog()

    controller._export_to_caltopo_via_api.assert_called_once()


def test_show_export_dialog_caltopo_browser_path(controller):
    controller._export_to_caltopo = MagicMock()
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog, patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.CalTopoMethodDialog"
    ) as MockMethod:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "caltopo"
        d.should_include_locations.return_value = True
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = False
        d.should_show_pod_on_map.return_value = False
        d.should_include_images.return_value = True
        MockMethod.return_value.exec.return_value = QDialog.Accepted
        MockMethod.return_value.get_selected_method.return_value = "browser"

        controller.show_export_dialog()

    controller._export_to_caltopo.assert_called_once()


def test_export_to_kml_file_dialog_cancelled(controller):
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.QFileDialog"
    ) as MockFile:
        MockFile.getSaveFileName.return_value = ("", "")
        assert controller._export_to_kml(True, False, True, False) is None


# ---------------------------------------------------------------------------
# POD pass: standalone thread + controller wiring
# ---------------------------------------------------------------------------

def test_pod_dir_for_kml():
    import os
    d = UnifiedMapExportController._pod_dir_for_kml(os.path.join("out", "mission.kml"))
    assert d == os.path.join("out", "mission_coverage_pod")


def _make_result(cancelled=False):
    r = MagicMock()
    r.cancelled = cancelled
    return r


def test_pod_thread_completes_and_writes(tmp_path):
    pod_service = MagicMock()
    result = _make_result(cancelled=False)
    pod_service.calculate.return_value = result
    thread = CoveragePodExportThread(pod_service, [{"path": "a"}], str(tmp_path))

    completed, finished = [], []
    thread.podCompleted.connect(lambda r: completed.append(r))
    thread.finished.connect(lambda: finished.append(True))
    with patch(
        "core.services.coverage.writers.write_all_outputs"
    ) as mock_write:
        thread.run()

    # calculate was driven with progress + cancel plumbing.
    assert pod_service.calculate.called
    _, kwargs = pod_service.calculate.call_args
    assert "progress_callback" in kwargs and "cancel_check" in kwargs
    mock_write.assert_called_once()
    assert completed == [result]
    assert finished == [True]


def test_pod_thread_cancelled_result_does_not_write(tmp_path):
    pod_service = MagicMock()
    pod_service.calculate.return_value = _make_result(cancelled=True)
    thread = CoveragePodExportThread(pod_service, [], str(tmp_path))

    canceled, completed = [], []
    thread.canceled.connect(lambda: canceled.append(True))
    thread.podCompleted.connect(lambda r: completed.append(r))
    with patch("core.services.coverage.writers.write_all_outputs") as mock_write:
        thread.run()

    assert canceled == [True]
    assert completed == []
    mock_write.assert_not_called()


def test_pod_thread_emits_error(tmp_path):
    pod_service = MagicMock()
    pod_service.calculate.side_effect = RuntimeError("kaboom")
    thread = CoveragePodExportThread(pod_service, [], str(tmp_path))
    errors = []
    thread.errorOccurred.connect(lambda m: errors.append(m))
    thread.run()
    assert len(errors) == 1 and "kaboom" in errors[0]


def test_on_pod_completed_populates_cache(controller):
    controller.parent.pod_result_cache = MagicMock()
    result = _make_result()
    controller._on_pod_completed(result)
    controller.parent.pod_result_cache.set_result.assert_called_once_with(result)


def test_pod_only_export_is_valid(controller):
    """A POD-only selection must pass validation and trigger the POD pass."""
    controller._export_to_kml = MagicMock(return_value="C:/tmp/mission.kml")
    controller._run_pod_export = MagicMock()
    with patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.MapExportDialog"
    ) as MockDialog, patch(
        "core.controllers.images.viewer.exports.UnifiedMapExportController.QMessageBox"
    ) as MockQMB:
        d = MockDialog.return_value
        d.exec.return_value = QDialog.Accepted
        d.get_export_type.return_value = "kml"
        d.should_include_locations.return_value = False
        d.should_include_images_without_flagged_aois.return_value = False
        d.should_include_flagged_aois.return_value = False
        d.should_include_coverage.return_value = False
        d.should_include_pod.return_value = True
        d.should_show_pod_on_map.return_value = True

        controller.show_export_dialog()

    MockQMB.warning.assert_not_called()
    controller._run_pod_export.assert_called_once()
