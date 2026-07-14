"""Tests for TileFetchThread + TileFetchController wiring."""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from core.controllers.images.viewer.exports.TileFetchController import (
    TileFetchThread,
    TileFetchController,
)
from core.services.terrain.TileFetchService import FetchResult


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_thread_runs_both_products(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.return_value = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"), None)
    service.fetch_meta_canopy.return_value = FetchResult('meta_chm', str(tmp_path / "chm"), None)
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=True)
    results = []
    thread.finished.connect(lambda r: results.append(r))
    thread.run()
    assert service.fetch_3dep_dem.called
    assert service.fetch_meta_canopy.called
    assert results and 'dem' in results[0] and 'canopy' in results[0]


def test_thread_dem_only(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.return_value = FetchResult('usgs_3dep_dem', str(tmp_path), None)
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=False)
    thread.run()
    assert service.fetch_3dep_dem.called
    assert not service.fetch_meta_canopy.called


def test_thread_emits_error(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.side_effect = RuntimeError("net down")
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=False)
    errors = []
    thread.errorOccurred.connect(lambda m: errors.append(m))
    thread.run()
    assert errors and "net down" in errors[0]


def test_register_results_writes_settings(app, tmp_path):
    settings = MagicMock()
    stored = {}
    settings.set_setting.side_effect = lambda k, v: stored.__setitem__(k, v)
    ctrl = TileFetchController(MagicMock(), settings)
    ctrl._register = True

    dem = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"),
                      str(tmp_path / "dem" / "dem_manifest.csv"))
    canopy = FetchResult('meta_chm', str(tmp_path / "chm"),
                         str(tmp_path / "chm" / "chm_manifest.csv"))
    ctrl._register_results({'dem': dem, 'canopy': canopy})

    assert stored['Terrain3DEPManifestPath'] == dem.manifest_path
    assert stored['Terrain3DEPTilesDir'] == dem.out_dir
    assert stored['TerrainProviderId'] == 'usgs_3dep_local'
    assert stored['CanopyManifestPath'] == canopy.manifest_path
    assert stored['CanopyTilesDir'] == canopy.out_dir
    assert stored['CanopyKind'] == 'meta'


def test_register_disabled_writes_nothing(app):
    settings = MagicMock()
    ctrl = TileFetchController(MagicMock(), settings)
    ctrl._register = False
    ctrl._register_results({'dem': FetchResult('usgs_3dep_dem', "d", "m.csv")})
    settings.set_setting.assert_not_called()


def test_fill_aoi_fills_dialog_from_mission(app):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog(has_mission=True)
    images = [{"path": "a.jpg"}, {"path": "b.jpg"}]

    with patch("core.services.coverage.aoi.compute_mission_gps_bounds",
               return_value=(-120.50, 38.70, -120.46, 38.72)), \
         patch("core.services.coverage.aoi.suggest_buffer_m", return_value=400.0):
        ctrl._fill_aoi(dialog, images, "loaded mission")

    assert dialog.get_buffer() == 400.0
    b = dialog.get_bounds()
    # Padded outward from the raw camera-position box.
    assert b is not None and b[0] < -120.50 and b[2] > -120.46


def test_fill_aoi_warns_when_no_gps(app):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog(has_mission=True)
    with patch("core.services.coverage.aoi.compute_mission_gps_bounds", return_value=None), \
         patch("core.controllers.images.viewer.exports.TileFetchController.QMessageBox") as mock_mb:
        ctrl._fill_aoi(dialog, [{"path": "a.jpg"}], "loaded mission")
    mock_mb.warning.assert_called_once()


def test_fill_aoi_respects_existing_buffer(app):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog(has_mission=True)
    dialog.set_buffer(900.0)   # user-set buffer must be kept
    with patch("core.services.coverage.aoi.compute_mission_gps_bounds",
               return_value=(-120.50, 38.70, -120.46, 38.72)), \
         patch("core.services.coverage.aoi.suggest_buffer_m", return_value=100.0) as mock_suggest:
        ctrl._fill_aoi(dialog, [{"path": "a.jpg"}], "loaded mission")
    mock_suggest.assert_not_called()
    assert dialog.get_buffer() == 900.0


# ---------------------------------------------------------------------------
# Thread-slot handlers + run_fetch validation/wiring (uncovered lines 82-128).
# ---------------------------------------------------------------------------

_MODULE = "core.controllers.images.viewer.exports.TileFetchController"


# --- _on_finished ----------------------------------------------------------

def test_on_finished_shows_complete_and_counts(app, tmp_path):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock())
    ctrl.progress_dialog = MagicMock()
    ctrl._register = False
    dem = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"), None, tiles_written=5)
    canopy = FetchResult('meta_chm', str(tmp_path / "chm"), None, tiles_written=3)

    with patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._on_finished({'dem': dem, 'canopy': canopy})

    ctrl.progress_dialog.accept.assert_called_once()
    mb.information.assert_called_once()
    args = mb.information.call_args.args
    assert args[1] == "Download Complete"
    assert "8" in args[2]   # 5 + 3 tiles written


def test_on_finished_registers_when_requested(app, tmp_path):
    from unittest.mock import patch

    settings = MagicMock()
    stored = {}
    settings.set_setting.side_effect = lambda k, v: stored.__setitem__(k, v)
    ctrl = TileFetchController(MagicMock(), settings)
    ctrl.progress_dialog = MagicMock()
    ctrl._register = True
    dem = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"),
                      str(tmp_path / "dem" / "m.csv"), tiles_written=2)

    with patch(f"{_MODULE}.QMessageBox"):
        ctrl._on_finished({'dem': dem})

    assert stored['Terrain3DEPManifestPath'] == dem.manifest_path
    assert stored['Terrain3DEPTilesDir'] == dem.out_dir
    assert stored['TerrainProviderId'] == 'usgs_3dep_local'


def test_on_finished_handles_missing_progress_dialog(app, tmp_path):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock())
    ctrl.progress_dialog = None
    ctrl._register = False

    with patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._on_finished({'dem': FetchResult('d', 'o', None, tiles_written=1)})

    mb.information.assert_called_once()
    assert "1" in mb.information.call_args.args[2]


# --- _on_error -------------------------------------------------------------

def test_on_error_shows_critical_rejects_and_logs(app):
    from unittest.mock import patch

    logger = MagicMock()
    ctrl = TileFetchController(MagicMock(), MagicMock(), logger=logger)
    ctrl.progress_dialog = MagicMock()
    ctrl.progress_dialog.isVisible.return_value = True

    with patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._on_error("boom")

    ctrl.progress_dialog.reject.assert_called_once()
    logger.error.assert_called_once()
    mb.critical.assert_called_once()
    args = mb.critical.call_args.args
    assert args[1] == "Download Error"
    assert "boom" in args[2]


def test_on_error_skips_reject_when_dialog_hidden(app):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock(), logger=MagicMock())
    ctrl.progress_dialog = MagicMock()
    ctrl.progress_dialog.isVisible.return_value = False

    with patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._on_error("x")

    ctrl.progress_dialog.reject.assert_not_called()
    mb.critical.assert_called_once()


def test_on_error_handles_no_progress_dialog(app):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock(), logger=MagicMock())
    ctrl.progress_dialog = None

    with patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._on_error("x")   # must not raise

    mb.critical.assert_called_once()


# --- _on_cancelled ---------------------------------------------------------

def test_on_cancelled_terminates_thread_and_rejects(app):
    ctrl = TileFetchController(MagicMock(), MagicMock())
    ctrl.thread = MagicMock()
    ctrl.thread.isRunning.return_value = True
    ctrl.progress_dialog = MagicMock()
    ctrl.progress_dialog.isVisible.return_value = True

    ctrl._on_cancelled()

    ctrl.thread.terminate.assert_called_once()
    ctrl.thread.wait.assert_called_once()
    ctrl.progress_dialog.reject.assert_called_once()


def test_on_cancelled_skips_when_thread_idle_and_dialog_hidden(app):
    ctrl = TileFetchController(MagicMock(), MagicMock())
    ctrl.thread = MagicMock()
    ctrl.thread.isRunning.return_value = False
    ctrl.progress_dialog = MagicMock()
    ctrl.progress_dialog.isVisible.return_value = False

    ctrl._on_cancelled()

    ctrl.thread.terminate.assert_not_called()
    ctrl.progress_dialog.reject.assert_not_called()


def test_on_cancelled_handles_none_state(app):
    ctrl = TileFetchController(MagicMock(), MagicMock())
    ctrl.thread = None
    ctrl.progress_dialog = None

    ctrl._on_cancelled()   # must not raise


# --- _fill_from_folder -----------------------------------------------------

def test_fill_from_folder_cancelled_is_noop(app):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog()

    with patch(f"{_MODULE}.QFileDialog.getExistingDirectory", return_value=""), \
         patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._fill_from_folder(dialog)

    mb.warning.assert_not_called()


def test_fill_from_folder_no_images_warns(app, tmp_path):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog()
    empty = tmp_path / "empty"
    empty.mkdir()

    with patch(f"{_MODULE}.QFileDialog.getExistingDirectory", return_value=str(empty)), \
         patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._fill_from_folder(dialog)

    mb.warning.assert_called_once()
    assert mb.warning.call_args.args[1] == "No Images"


def test_fill_from_folder_no_gps_warns(app, tmp_path):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog()
    folder = tmp_path / "imgs"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")
    (folder / "b.jpg").write_bytes(b"x")

    with patch(f"{_MODULE}.QFileDialog.getExistingDirectory", return_value=str(folder)), \
         patch("core.services.coverage.aoi.compute_mission_gps_bounds", return_value=None), \
         patch(f"{_MODULE}.QMessageBox") as mb:
        ctrl._fill_from_folder(dialog)

    mb.warning.assert_called_once()
    assert mb.warning.call_args.args[1] == "No GPS Found"


def test_fill_from_folder_with_gps_fills_aoi(app, tmp_path):
    from unittest.mock import patch
    from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    dialog = TileFetchDialog()
    dialog.set_buffer(999.0)   # a fresh folder must clear + re-suggest the buffer
    folder = tmp_path / "imgs"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")

    with patch(f"{_MODULE}.QFileDialog.getExistingDirectory", return_value=str(folder)), \
         patch("core.services.coverage.aoi.compute_mission_gps_bounds",
               return_value=(-120.50, 38.70, -120.46, 38.72)), \
         patch("core.services.coverage.aoi.suggest_buffer_m", return_value=250.0):
        ctrl._fill_from_folder(dialog)

    assert dialog.get_buffer() == 250.0
    b = dialog.get_bounds()
    assert b is not None and b[0] < -120.50 and b[2] > -120.46


# --- run_fetch validation --------------------------------------------------

def _accepted_dialog_mock(mock_dialog_cls):
    """Return the instance mock of a patched TileFetchDialog set to 'accepted'."""
    from PySide6.QtWidgets import QDialog
    dlg = mock_dialog_cls.return_value
    dlg.exec.return_value = QDialog.Accepted
    return dlg


def test_run_fetch_returns_when_dialog_cancelled(app):
    from unittest.mock import patch
    from PySide6.QtWidgets import QDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.QMessageBox") as mb:
        MockDlg.return_value.exec.return_value = QDialog.Rejected
        ctrl.run_fetch()

    mb.warning.assert_not_called()
    assert ctrl.thread is None


def test_run_fetch_invalid_area_warns(app):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.QMessageBox") as mb:
        dlg = _accepted_dialog_mock(MockDlg)
        dlg.get_bounds.return_value = None
        ctrl.run_fetch()

    mb.warning.assert_called_once()
    assert mb.warning.call_args.args[1] == "Invalid Area"
    assert ctrl.thread is None


def test_run_fetch_no_output_folder_warns(app):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.QMessageBox") as mb:
        dlg = _accepted_dialog_mock(MockDlg)
        dlg.get_bounds.return_value = (-120.5, 38.7, -120.4, 38.8)
        dlg.get_output_dir.return_value = ""
        ctrl.run_fetch()

    mb.warning.assert_called_once()
    assert mb.warning.call_args.args[1] == "No Output Folder"
    assert ctrl.thread is None


def test_run_fetch_no_dataset_warns(app):
    from unittest.mock import patch

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.QMessageBox") as mb:
        dlg = _accepted_dialog_mock(MockDlg)
        dlg.get_bounds.return_value = (-120.5, 38.7, -120.4, 38.8)
        dlg.get_output_dir.return_value = "/out"
        dlg.want_dem.return_value = False
        dlg.want_canopy.return_value = False
        ctrl.run_fetch()

    mb.warning.assert_called_once()
    assert mb.warning.call_args.args[1] == "No Dataset"
    assert ctrl.thread is None


# --- run_fetch success wiring ----------------------------------------------

def test_run_fetch_success_starts_thread_and_wires_slots(app):
    from unittest.mock import patch
    from PySide6.QtWidgets import QDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.TileFetchService") as MockSvc, \
         patch(f"{_MODULE}.ExportProgressDialog") as MockProg, \
         patch(f"{_MODULE}.TileFetchThread") as MockThread, \
         patch(f"{_MODULE}.QApplication"), \
         patch(f"{_MODULE}.QMessageBox") as mb:
        dlg = _accepted_dialog_mock(MockDlg)
        dlg.get_bounds.return_value = (-120.5, 38.7, -120.4, 38.8)
        dlg.get_output_dir.return_value = "/out"
        dlg.want_dem.return_value = True
        dlg.want_canopy.return_value = False
        dlg.should_register.return_value = True
        prog = MockProg.return_value
        prog.exec.return_value = QDialog.Accepted   # not rejected -> no cancel
        thread = MockThread.return_value

        ctrl.run_fetch()

    assert MockSvc.called
    assert ctrl._register is True
    thread.start.assert_called_once()
    prog.show.assert_called_once()
    thread.finished.connect.assert_called_once_with(ctrl._on_finished)
    thread.errorOccurred.connect.assert_called_once_with(ctrl._on_error)
    thread.progressUpdated.connect.assert_called_once_with(ctrl._on_progress)
    thread.canceled.connect.assert_called_once_with(ctrl._on_cancelled)
    prog.cancel_requested.connect.assert_called_once_with(thread.cancel)
    thread.cancel.assert_not_called()
    mb.warning.assert_not_called()


def test_run_fetch_cancels_thread_when_progress_rejected(app):
    from unittest.mock import patch
    from PySide6.QtWidgets import QDialog

    ctrl = TileFetchController(MagicMock(), MagicMock())
    with patch(f"{_MODULE}.TileFetchDialog") as MockDlg, \
         patch(f"{_MODULE}.TileFetchService"), \
         patch(f"{_MODULE}.ExportProgressDialog") as MockProg, \
         patch(f"{_MODULE}.TileFetchThread") as MockThread, \
         patch(f"{_MODULE}.QApplication"), \
         patch(f"{_MODULE}.QMessageBox"):
        dlg = _accepted_dialog_mock(MockDlg)
        dlg.get_bounds.return_value = (-120.5, 38.7, -120.4, 38.8)
        dlg.get_output_dir.return_value = "/out"
        dlg.want_dem.return_value = True
        dlg.want_canopy.return_value = True
        dlg.should_register.return_value = False
        MockProg.return_value.exec.return_value = QDialog.Rejected
        thread = MockThread.return_value

        ctrl.run_fetch()

    assert ctrl._register is False
    thread.start.assert_called_once()
    thread.cancel.assert_called_once()
