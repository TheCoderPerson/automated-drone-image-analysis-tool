"""
TileFetchController - drive the DEM / canopy tile download and register paths.

Clones the CoverageExtent export threading pattern (QThread + ExportProgressDialog
with progress/cancel). On success it writes each product into a subfolder and,
if requested, registers the manifest/tiles paths into settings so the freshly
downloaded data is immediately usable.
"""

import os
import glob

from PySide6.QtWidgets import QMessageBox, QDialog, QApplication, QFileDialog
from PySide6.QtCore import QThread, Signal, Qt

from core.services.LoggerService import LoggerService
from core.services.terrain.TileFetchService import TileFetchService
from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog
from core.views.images.viewer.dialogs.ExportProgressDialog import ExportProgressDialog
from helpers.TranslationMixin import TranslationMixin


class TileFetchThread(QThread):
    finished = Signal(dict)
    errorOccurred = Signal(str)
    progressUpdated = Signal(int, int, str)
    canceled = Signal()

    def __init__(self, service, bounds, output_dir, want_dem, want_canopy):
        super().__init__()
        self.service = service
        self.bounds = bounds
        self.output_dir = output_dir
        self.want_dem = want_dem
        self.want_canopy = want_canopy
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        try:
            results = {}
            n_phases = int(self.want_dem) + int(self.want_canopy)
            phase = 0

            def make_progress(prefix):
                def progress(current, total, message):
                    if not self.is_cancelled():
                        self.progressUpdated.emit(current, total, f"{prefix}{message}")
                return progress

            if self.want_dem and not self.is_cancelled():
                phase += 1
                prefix = f"Step {phase}/{n_phases}: " if n_phases > 1 else ""
                # Reset the bar and announce the phase immediately so the dialog
                # never shows a stale message while a phase runs.
                self.progressUpdated.emit(0, 1, f"{prefix}Starting elevation (DEM) download...")
                dem_dir = os.path.join(self.output_dir, "dem")
                results['dem'] = self.service.fetch_3dep_dem(
                    self.bounds, dem_dir, progress_callback=make_progress(prefix),
                    cancel_check=self.is_cancelled)
            if self.want_canopy and not self.is_cancelled():
                phase += 1
                prefix = f"Step {phase}/{n_phases}: " if n_phases > 1 else ""
                self.progressUpdated.emit(0, 1, f"{prefix}Starting canopy height download...")
                chm_dir = os.path.join(self.output_dir, "chm")
                results['canopy'] = self.service.fetch_meta_canopy(
                    self.bounds, chm_dir, progress_callback=make_progress(prefix),
                    cancel_check=self.is_cancelled)

            if self.is_cancelled():
                self.canceled.emit()
                return
            self.finished.emit(results)
        except Exception as e:
            import traceback
            self.errorOccurred.emit(f"{str(e)}\n\n{traceback.format_exc()}")


class TileFetchController(TranslationMixin):
    def __init__(self, parent_widget, settings_service, logger=None):
        self.parent = parent_widget
        self.settings_service = settings_service
        self.logger = logger or LoggerService()
        self.thread = None
        self.progress_dialog = None
        self._register = True
        # Per-product FetchResults of the last COMPLETED run (None when the
        # dialog was dismissed or the download cancelled/failed before
        # finishing) — lets callers chain follow-up steps after a download.
        self.last_results = None

    def run_fetch(self, default_bounds=None, mission_images=None, default_output_dir=None):
        self.last_results = None
        self._mission_images = mission_images
        dialog = TileFetchDialog(self.parent, default_bounds=default_bounds,
                                 has_mission=bool(mission_images),
                                 default_output_dir=default_output_dir)
        dialog.fill_source_activated.connect(lambda key: self._on_fill_source(dialog, key))
        if mission_images:
            self._fill_aoi(dialog, mission_images, "loaded mission", warn_if_empty=False)

        if dialog.exec() != QDialog.Accepted:
            return

        bounds = dialog.get_bounds()
        out_dir = dialog.get_output_dir()
        if bounds is None:
            QMessageBox.warning(self.parent, self.tr("Invalid Area"),
                                self.tr("Please enter a valid bounding box."))
            return
        if not out_dir:
            QMessageBox.warning(self.parent, self.tr("No Output Folder"),
                                self.tr("Please choose an output folder."))
            return
        if not (dialog.want_dem() or dialog.want_canopy()):
            QMessageBox.warning(self.parent, self.tr("No Dataset"),
                                self.tr("Please select at least one dataset."))
            return

        self._register = dialog.should_register()
        service = TileFetchService(logger=self.logger)

        self.progress_dialog = ExportProgressDialog(
            self.parent, title="Downloading Coverage Data", total_items=100)
        self.progress_dialog.set_title("Downloading tiles...")

        self.thread = TileFetchThread(service, bounds, out_dir,
                                      dialog.want_dem(), dialog.want_canopy())
        self.thread.finished.connect(self._on_finished)
        self.thread.errorOccurred.connect(self._on_error)
        self.thread.progressUpdated.connect(self._on_progress)
        self.thread.canceled.connect(self._on_cancelled)
        self.progress_dialog.cancel_requested.connect(self.thread.cancel)

        self.thread.start()
        self.progress_dialog.show()
        QApplication.processEvents()
        if self.progress_dialog.exec() == QDialog.Rejected:
            self.thread.cancel()

    _IMAGE_GLOBS = ("*.jpg", "*.jpeg", "*.JPG", "*.JPEG", "*.tif", "*.tiff", "*.png")

    def _on_fill_source(self, dialog, key):
        """Dispatch an AOI fill-source choice from the dialog's dropdown."""
        if key == 'mission':
            self._fill_aoi(dialog, self._mission_images, "loaded mission")
        elif key == 'folder':
            self._fill_from_folder(dialog)

    def _fill_aoi(self, dialog, images, source_label, warn_if_empty=True):
        """Compute the AOI (+ buffer) from ``images`` and fill the dialog fields."""
        if not images:
            return
        from core.services.coverage.aoi import (
            compute_mission_gps_bounds, suggest_buffer_m, pad_bounds)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            raw = compute_mission_gps_bounds(images)
            if raw is None:
                if warn_if_empty:
                    QMessageBox.warning(
                        self.parent, self.tr("No GPS Found"),
                        self.tr("No GPS positions were found in the {source} images.").format(
                            source=source_label))
                return
            buffer_m = dialog.get_buffer()
            if buffer_m is None:
                buffer_m = suggest_buffer_m(images)
                dialog.set_buffer(buffer_m)
            dialog.set_aoi(pad_bounds(raw, buffer_m))
        finally:
            QApplication.restoreOverrideCursor()

    def _fill_from_folder(self, dialog):
        folder = QFileDialog.getExistingDirectory(
            self.parent, self.tr("Select image folder"))
        if not folder:
            return
        paths = []
        for pattern in self._IMAGE_GLOBS:
            paths.extend(glob.glob(os.path.join(folder, pattern)))
        images = [{'path': p} for p in sorted(set(paths))]
        if not images:
            QMessageBox.warning(
                self.parent, self.tr("No Images"),
                self.tr("No images were found in the selected folder."))
            return
        # A fresh folder -> re-suggest the buffer for it.
        dialog.buffer_edit.clear()
        self._fill_aoi(dialog, images, "selected folder")

    def _on_progress(self, current, total, message):
        if self.progress_dialog:
            self.progress_dialog.update_progress(current, total, message)
            QApplication.processEvents()

    def _register_results(self, results):
        """Register downloaded products into settings. Returns {product: bool}
        so the completion dialog can state exactly what was (not) registered."""
        registered = {}
        if not self._register or self.settings_service is None:
            return registered
        dem = results.get('dem')
        if dem is not None and dem.manifest_path:
            self.settings_service.set_setting('Terrain3DEPManifestPath', dem.manifest_path)
            self.settings_service.set_setting('Terrain3DEPTilesDir', dem.out_dir)
            self.settings_service.set_setting('TerrainProviderId', 'usgs_3dep_local')
            registered['dem'] = True
        canopy = results.get('canopy')
        if canopy is not None and canopy.manifest_path:
            if self._confirm_canopy_overwrite():
                self.settings_service.set_setting('CanopyManifestPath', canopy.manifest_path)
                self.settings_service.set_setting('CanopyTilesDir', canopy.out_dir)
                self.settings_service.set_setting('CanopyKind', 'meta')
                registered['canopy'] = True
            else:
                registered['canopy'] = False
        return registered

    def _confirm_canopy_overwrite(self):
        """Guard a configured LANDFIRE canopy source from being silently
        replaced by the downloaded Meta/WRI data. Returns True to proceed."""
        try:
            kind = self.settings_service.get_setting('CanopyKind', '')
            manifest = self.settings_service.get_setting('CanopyManifestPath', '')
            tiles = self.settings_service.get_setting('CanopyTilesDir', '')
        except Exception:
            return True
        if kind != 'landfire' or not (manifest and tiles):
            return True
        resp = QMessageBox.question(
            self.parent, self.tr("Replace Canopy Source?"),
            self.tr("A LANDFIRE canopy source is currently configured.\n\n"
                    "Register the downloaded Meta/WRI canopy tiles instead? "
                    "(Your LANDFIRE files stay on disk; only the selected source changes.)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return resp == QMessageBox.StandardButton.Yes

    def _product_labels(self):
        # Literal tr() calls so lupdate extracts them.
        return {'dem': self.tr("Elevation (DEM)"), 'canopy': self.tr("Canopy height")}

    def _on_finished(self, results):
        self.last_results = results
        if self.progress_dialog:
            self.progress_dialog.accept()
        registered = self._register_results(results)

        labels = self._product_labels()
        written = sum(getattr(r, 'tiles_written', 0) for r in results.values())
        problems = []
        for product, r in results.items():
            label = labels.get(product, product)
            failed = getattr(r, 'tiles_failed', 0)
            skipped = getattr(r, 'tiles_skipped', 0)
            wrote = getattr(r, 'tiles_written', 0)
            if getattr(r, 'cancelled', False):
                problems.append(self.tr("{product}: cancelled before completion.").format(product=label))
            elif failed:
                problems.append(self.tr("{product}: {failed} tile(s) failed to download.").format(
                    product=label, failed=failed))
            elif wrote == 0 and skipped:
                problems.append(self.tr("{product}: no data covers this area.").format(product=label))
            elif wrote == 0:
                problems.append(self.tr("{product}: nothing was downloaded.").format(product=label))

        reg_lines = []
        if self._register:
            for product in results:
                label = labels.get(product, product)
                if registered.get(product):
                    reg_lines.append(self.tr("{product}: registered as the active source.").format(
                        product=label))
                else:
                    reg_lines.append(self.tr("{product}: NOT registered (no usable tiles).").format(
                        product=label))

        if problems:
            body = self.tr("Downloaded {count} tiles.").format(count=written)
            body += "\n\n" + "\n".join(problems)
            if reg_lines:
                body += "\n\n" + "\n".join(reg_lines)
            QMessageBox.warning(
                self.parent, self.tr("Download Finished with Problems"), body)
        else:
            body = self.tr("Downloaded {count} tiles.").format(count=written)
            if reg_lines:
                body += "\n\n" + "\n".join(reg_lines)
            QMessageBox.information(
                self.parent, self.tr("Download Complete"), body)

    def _on_cancelled(self):
        if self.thread and self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait()
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.reject()
        # A silent close here reads as success; say explicitly that nothing
        # was registered so a cancelled download is never mistaken for one.
        QMessageBox.warning(
            self.parent, self.tr("Download Cancelled"),
            self.tr("The download was cancelled. No tiles were registered."))

    def _on_error(self, message):
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.reject()
        self.logger.error(f"Tile fetch error: {message}")
        QMessageBox.critical(
            self.parent, self.tr("Download Error"),
            self.tr("Tile download failed:\n{error}").format(error=message))
