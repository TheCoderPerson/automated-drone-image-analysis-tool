"""
RedundantImageController - the viewer's "Skip Redundant" navigation filter.

Owns the Skip Redundant checkbox and the overlap-percentage spin box beside it.
Turning the filter on projects every result image's ground footprint on a
worker thread (``ImageOverlapService.compute_footprints``); after that,
``find_redundant`` decides which images Previous/Next skip. The decision is
cheap and is redone whenever the threshold, an image's hidden state or its
flagged AOIs change, so flagging an AOI in a skipped image brings it back at
once.

Like Skip Hidden, the filter only affects navigation: exports, reports and POD
still include every image.
"""

import traceback

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core.services.LoggerService import LoggerService
from core.views.images.viewer.dialogs.ExportProgressDialog import ExportProgressDialog
from helpers.TranslationMixin import TranslationMixin

THRESHOLD_SETTING = 'RedundantImageOverlapPercent'
DEFAULT_THRESHOLD_PERCENT = 90


class RedundantFootprintThread(QThread):
    """Runs ``ImageOverlapService.compute_footprints`` off the UI thread."""

    progressUpdated = Signal(int, int)
    footprintsReady = Signal(object)
    errorOccurred = Signal(str)
    canceled = Signal()

    def __init__(self, service, images):
        super().__init__()
        self.service = service
        self.images = images
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def run(self):
        try:
            result = self.service.compute_footprints(
                self.images,
                progress_callback=lambda current, total, _message: self.progressUpdated.emit(current, total),
                cancel_check=self.is_cancelled,
            )
            if result.cancelled or self.is_cancelled():
                self.canceled.emit()
                return
            self.footprintsReady.emit(result)
        except Exception as e:  # noqa: BLE001 - reported to the operator
            self.errorOccurred.emit(f"{e}\n\n{traceback.format_exc()}")


class RedundantImageController(TranslationMixin):
    """Decides which viewer images the Skip Redundant filter skips."""

    def __init__(self, parent, logger=None):
        """
        Args:
            parent: the Viewer. Uses its ``images``, ``show_hidden``,
                ``skipRedundant``, ``redundantOverlapSpinBox``,
                ``settings_service``, ``altitude_controller`` and
                ``status_controller``.
            logger: optional logger.
        """
        self.parent = parent
        self.logger = logger or LoggerService()
        self.enabled = False
        self.footprint_set = None            # FootprintSet once computed
        self._footprint_altitude_ft = None   # altitude override the footprints were built with
        self._decision_key = None            # inputs the cached decision was made from
        self._redundant = {}                 # image index -> RedundantMatch
        self._thread = None
        self._progress_dialog = None

        spin = parent.redundantOverlapSpinBox
        spin.blockSignals(True)
        spin.setValue(self._saved_threshold())
        spin.blockSignals(False)
        spin.valueChanged.connect(self._on_threshold_changed)
        parent.skipRedundant.setChecked(False)
        parent.skipRedundant.clicked.connect(self._on_skip_redundant_clicked)
        self._update_label()

    def is_skipped(self, index):
        """Whether navigation should skip image ``index``."""
        if not self.enabled:
            return False
        return index in self.redundant_images()

    def redundant_images(self):
        """Image index -> RedundantMatch under the current state (empty before compute)."""
        images = self.parent.images
        if self.footprint_set is None or len(self.footprint_set.footprints) != len(images):
            return {}
        from core.services.coverage.ImageOverlapService import find_redundant
        skip_hidden = not self.parent.show_hidden
        hidden = tuple(bool(image.get('hidden')) for image in images)
        flagged = tuple(self._has_flagged_aoi(image) for image in images)
        key = (self._threshold_percent(), skip_hidden, hidden, flagged)
        if key != self._decision_key:
            # An image the reviewer will not be shown cannot stand in for
            # another one, or both would vanish from navigation.
            eligible = {i for i in range(len(images)) if not (skip_hidden and hidden[i])}
            protected = {i for i in range(len(images)) if flagged[i]}
            self._redundant = find_redundant(
                self.footprint_set.footprints, self._threshold_percent() / 100.0,
                eligible=eligible, protected=protected)
            self._decision_key = key
        return self._redundant

    def on_image_loaded(self, index):
        """Refresh the count, and tell the reviewer when they have reached a
        skipped image directly (thumbnail, jump box): Previous/Next would have
        stepped over it."""
        if not self.enabled:
            return
        # Hiding an image or flagging an AOI changes the count; every image
        # load is a cheap point to pick that up (the decision is cached).
        self._update_label()
        match = self.redundant_images().get(index)
        if match is None:
            return
        images = self.parent.images
        other = images[match.covered_by]
        self._show_toast(
            self.tr("Redundant: {percent}% of this image's ground is also in {name}").format(
                percent=int(match.fraction * 100), name=other.get('name') or other.get('path', '')),
            4000, "#FFA726")

    def _on_skip_redundant_clicked(self, checked):
        if not checked:
            self.enabled = False
            self._update_label()
            return
        altitude = self._custom_altitude_ft()
        if self.footprint_set is None or altitude != self._footprint_altitude_ft:
            self._compute_footprints(altitude)
            return
        self.enabled = True
        self._update_label()

    def _on_threshold_changed(self, value):
        settings = getattr(self.parent, 'settings_service', None)
        if settings is not None:
            settings.set_setting(THRESHOLD_SETTING, int(value))
        self._update_label()

    def _compute_footprints(self, altitude):
        """Project every image on a worker thread, behind a cancellable progress dialog."""
        images = list(self.parent.images)
        try:
            service = self._build_service(altitude)
        except Exception as e:  # noqa: BLE001 - reported to the operator
            self.logger.error(f"Could not start the redundant-image comparison: {e}")
            self._on_error(str(e))
            return

        self._footprint_altitude_ft = altitude
        self._progress_dialog = ExportProgressDialog(
            self.parent, title=self.tr("Redundant Images"), total_items=len(images))
        self._progress_dialog.set_title(self.tr("Comparing image footprints..."))

        self._thread = RedundantFootprintThread(service, images)
        self._thread.progressUpdated.connect(self._on_progress)
        self._thread.footprintsReady.connect(self._on_footprints_ready)
        self._thread.errorOccurred.connect(self._on_error)
        self._thread.canceled.connect(self._on_cancelled)
        self._progress_dialog.cancel_requested.connect(self._thread.cancel)

        self._thread.start()
        self._progress_dialog.show()
        QApplication.processEvents()
        if self._progress_dialog.exec() == QDialog.Rejected:
            self._thread.cancel()

    def _build_service(self, altitude):
        # A fresh TerrainService per run: the worker thread must not share
        # the viewer's (see UnifiedMapExportController._build_pod_service).
        from core.services.terrain.TerrainService import TerrainService
        from core.services.coverage.ImageOverlapService import ImageOverlapService
        settings = getattr(self.parent, 'settings_service', None)
        return ImageOverlapService(
            TerrainService(settings_service=settings), custom_altitude_ft=altitude, logger=self.logger)

    def _on_progress(self, current, total):
        if self._progress_dialog is not None:
            self._progress_dialog.update_progress(
                current, total,
                self.tr("Projecting image {current} of {total}...").format(
                    current=min(current + 1, total), total=total))

    def _on_footprints_ready(self, footprint_set):
        self.footprint_set = footprint_set
        self._decision_key = None
        self.enabled = True
        if self._progress_dialog is not None:
            self._progress_dialog.accept()
        self._update_label()
        self._show_summary()

    def _on_cancelled(self):
        self._disable_checkbox()
        if self._progress_dialog is not None and self._progress_dialog.isVisible():
            self._progress_dialog.reject()
        self._show_toast(self.tr("Redundant image comparison cancelled"), 3000, "#FFA726")

    def _on_error(self, message):
        self._disable_checkbox()
        if self._progress_dialog is not None and self._progress_dialog.isVisible():
            self._progress_dialog.reject()
        self.logger.error(f"Redundant-image comparison failed: {message}")
        QMessageBox.critical(
            self.parent, self.tr("Redundant Images"),
            self.tr("Could not compare image footprints:\n{error}").format(error=message))

    def _disable_checkbox(self):
        self.enabled = False
        self.parent.skipRedundant.setChecked(False)
        self._update_label()

    def _show_summary(self):
        footprint_set = self.footprint_set
        redundant = len(self.redundant_images())
        message = self.tr("{redundant} of {total} images are redundant at {percent}% overlap").format(
            redundant=redundant, total=len(footprint_set.footprints),
            percent=self._threshold_percent())
        unplaced = len(footprint_set.skipped)
        if unplaced:
            message += self.tr("; {count} could not be placed and are always shown").format(count=unplaced)
        if footprint_set.flat_fallback:
            message += self.tr("; {count} had no terrain data and assumed flat ground").format(
                count=footprint_set.flat_fallback)
        self._show_toast(message, 6000, "#00C853")

    def _update_label(self):
        if self.enabled:
            text = self.tr("Skip Redundant ({count}) ").format(count=len(self.redundant_images()))
        else:
            text = self.tr("Skip Redundant")
        self.parent.skipRedundant.setText(text)

    def _threshold_percent(self):
        return int(self.parent.redundantOverlapSpinBox.value())

    def _saved_threshold(self):
        settings = getattr(self.parent, 'settings_service', None)
        if settings is None:
            return DEFAULT_THRESHOLD_PERCENT
        try:
            return int(settings.get_setting(THRESHOLD_SETTING, DEFAULT_THRESHOLD_PERCENT))
        except (TypeError, ValueError):
            return DEFAULT_THRESHOLD_PERCENT

    def _custom_altitude_ft(self):
        controller = getattr(self.parent, 'altitude_controller', None)
        if controller is None:
            return None
        return controller.get_effective_altitude()

    def _show_toast(self, text, msec, color):
        status = getattr(self.parent, 'status_controller', None)
        if status is not None:
            status.show_toast(text, msec, color=color)

    @staticmethod
    def _has_flagged_aoi(image):
        return any(aoi.get('flagged') for aoi in image.get('areas_of_interest') or [])
