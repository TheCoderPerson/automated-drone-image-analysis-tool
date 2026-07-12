"""
TileFetchDialog - options for downloading DEM / canopy tiles for an AOI.

Code-built (matching the MapExportDialog family) so no generated UI changes are
needed. Collects an AOI bounding box, product selection, and an output folder.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QGroupBox, QFileDialog
)
from PySide6.QtGui import QDoubleValidator
from helpers.TranslationMixin import TranslationMixin


class TileFetchDialog(TranslationMixin, QDialog):
    def __init__(self, parent=None, default_bounds=None, has_mission=False):
        """
        Args:
            default_bounds: optional (min_lon, min_lat, max_lon, max_lat) to prefill.
            has_mission: whether a mission is loaded (enables the auto-fill button).
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Download Coverage Data"))
        self.setMinimumWidth(460)
        self._setup_ui(default_bounds, has_mission)
        self._apply_translations()

    def _setup_ui(self, default_bounds, has_mission):
        layout = QVBoxLayout(self)

        aoi_group = QGroupBox(self.tr("Area of Interest (WGS84)"))
        aoi_layout = QVBoxLayout()

        # Auto-fill row: derive the AOI from the loaded mission or an image folder.
        fill_row = QHBoxLayout()
        self.use_mission_btn = QPushButton(self.tr("Use loaded mission extent"))
        self.use_mission_btn.setEnabled(bool(has_mission))
        self.use_mission_btn.setToolTip(self.tr(
            "Fill the AOI from the GPS positions of the currently loaded mission's images."))
        self.load_folder_btn = QPushButton(self.tr("Load extent from image folder..."))
        self.load_folder_btn.setToolTip(self.tr(
            "Read image GPS from a folder to fill the AOI (use when no mission is loaded)."))
        fill_row.addWidget(self.use_mission_btn)
        fill_row.addWidget(self.load_folder_btn)
        fill_row.addStretch()
        aoi_layout.addLayout(fill_row)

        grid = QGridLayout()
        self.min_lon_edit = QLineEdit()
        self.min_lat_edit = QLineEdit()
        self.max_lon_edit = QLineEdit()
        self.max_lat_edit = QLineEdit()
        for e in (self.min_lon_edit, self.min_lat_edit, self.max_lon_edit, self.max_lat_edit):
            e.setValidator(QDoubleValidator())
        if default_bounds:
            self.set_aoi(default_bounds)
        grid.addWidget(QLabel(self.tr("Min longitude:")), 0, 0)
        grid.addWidget(self.min_lon_edit, 0, 1)
        grid.addWidget(QLabel(self.tr("Min latitude:")), 0, 2)
        grid.addWidget(self.min_lat_edit, 0, 3)
        grid.addWidget(QLabel(self.tr("Max longitude:")), 1, 0)
        grid.addWidget(self.max_lon_edit, 1, 1)
        grid.addWidget(QLabel(self.tr("Max latitude:")), 1, 2)
        grid.addWidget(self.max_lat_edit, 1, 3)
        aoi_layout.addLayout(grid)

        buffer_row = QHBoxLayout()
        buffer_row.addWidget(QLabel(self.tr("Footprint buffer (m):")))
        self.buffer_edit = QLineEdit()
        self.buffer_edit.setValidator(QDoubleValidator(0.0, 100000.0, 1))
        self.buffer_edit.setFixedWidth(90)
        self.buffer_edit.setToolTip(self.tr(
            "Padding added around the camera positions so downloaded tiles cover the "
            "image footprints. Auto-sized from the mission; edit and re-fill to change."))
        buffer_row.addWidget(self.buffer_edit)
        buffer_row.addStretch()
        aoi_layout.addLayout(buffer_row)

        aoi_group.setLayout(aoi_layout)
        layout.addWidget(aoi_group)

        data_group = QGroupBox(self.tr("Datasets"))
        data_layout = QVBoxLayout()
        self.dem_checkbox = QCheckBox(self.tr("USGS 3DEP DEM"))
        self.dem_checkbox.setChecked(True)
        self.canopy_checkbox = QCheckBox(self.tr("Meta/WRI Canopy Height"))
        self.canopy_checkbox.setChecked(True)
        data_layout.addWidget(self.dem_checkbox)
        data_layout.addWidget(self.canopy_checkbox)
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(self.tr("Output folder:")))
        self.output_edit = QLineEdit()
        self.output_button = QPushButton(self.tr("Browse..."))
        self.output_button.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.output_button)
        layout.addLayout(out_row)

        self.register_checkbox = QCheckBox(self.tr("Register in Preferences when complete"))
        self.register_checkbox.setChecked(True)
        layout.addWidget(self.register_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.download_button = QPushButton(self.tr("Download"))
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.download_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def _browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, self.tr("Select output folder"))
        if directory:
            self.output_edit.setText(directory)

    def set_aoi(self, bounds):
        """Fill the four AOI fields from (min_lon, min_lat, max_lon, max_lat)."""
        self.min_lon_edit.setText(f"{bounds[0]:.6f}")
        self.min_lat_edit.setText(f"{bounds[1]:.6f}")
        self.max_lon_edit.setText(f"{bounds[2]:.6f}")
        self.max_lat_edit.setText(f"{bounds[3]:.6f}")

    def set_buffer(self, buffer_m):
        self.buffer_edit.setText(f"{buffer_m:.0f}")

    def get_buffer(self):
        """Buffer in meters, or None if empty/invalid."""
        try:
            v = float(self.buffer_edit.text())
            return v if v > 0 else None
        except ValueError:
            return None

    def get_bounds(self):
        """(min_lon, min_lat, max_lon, max_lat) or None if incomplete/invalid."""
        try:
            b = (float(self.min_lon_edit.text()), float(self.min_lat_edit.text()),
                 float(self.max_lon_edit.text()), float(self.max_lat_edit.text()))
        except ValueError:
            return None
        if b[0] >= b[2] or b[1] >= b[3]:
            return None
        return b

    def want_dem(self):
        return self.dem_checkbox.isChecked()

    def want_canopy(self):
        return self.canopy_checkbox.isChecked()

    def get_output_dir(self):
        return self.output_edit.text().strip()

    def should_register(self):
        return self.register_checkbox.isChecked()
