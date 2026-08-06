"""
MapExportDialog - Dialog for selecting map export options.

Allows users to choose between KML file export or CalTopo export,
and select which data to include (drone locations, flagged AOIs, coverage area).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QGroupBox, QCheckBox, QComboBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class MapExportDialog(QDialog):
    """
    Dialog for configuring map export options.

    Provides options to:
    - Choose export type (KML file or CalTopo)
    - Select what data to include (drone locations, flagged AOIs, coverage area)
    """

    def __init__(self, parent=None):
        """
        Initialize the map export dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Map Export Options")
        self.setMinimumWidth(400)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Title
        title_label = QLabel("Configure Map Export")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Export type selection
        export_type_group = QGroupBox("Export Type")
        export_type_layout = QVBoxLayout()

        self.kml_radio = QRadioButton("KML File")
        self.kml_radio.setChecked(True)  # Default selection
        self.kml_radio.setToolTip("Export to a KML file for use in Google Earth, etc.")

        self.caltopo_radio = QRadioButton("CalTopo")
        self.caltopo_radio.setToolTip("Export directly to a CalTopo map")

        self.export_type_group = QButtonGroup(self)
        self.export_type_group.addButton(self.kml_radio, 0)
        self.export_type_group.addButton(self.caltopo_radio, 1)

        export_type_layout.addWidget(self.kml_radio)
        export_type_layout.addWidget(self.caltopo_radio)
        export_type_group.setLayout(export_type_layout)
        layout.addWidget(export_type_group)

        # Data to include
        data_group = QGroupBox("Data to Include")
        data_layout = QVBoxLayout()

        self.include_locations = QCheckBox("Drone/Image Locations")
        self.include_locations.setChecked(True)  # Default: on
        self.include_locations.setToolTip("Include markers for each drone image location")

        self.include_flagged_aois = QCheckBox("Flagged Areas of Interest")
        self.include_flagged_aois.setChecked(True)  # Default: on
        self.include_flagged_aois.setToolTip("Include markers for flagged AOIs")

        self.include_coverage = QCheckBox("Coverage Area")
        self.include_coverage.setChecked(True)  # Default: on
        self.include_coverage.setToolTip("Include polygon(s) showing the geographic coverage extent")

        self.include_images_without_flagged_aois = QCheckBox("Include images without flagged AOIs")
        self.include_images_without_flagged_aois.setChecked(True)  # Default: on
        self.include_images_without_flagged_aois.setToolTip("If unchecked, only export locations for images that have flagged AOIs")
        self.include_images_without_flagged_aois.setEnabled(True)  # Enabled when locations are checked

        data_layout.addWidget(self.include_locations)
        data_layout.addWidget(self.include_flagged_aois)
        data_layout.addWidget(self.include_coverage)
        data_layout.addWidget(self.include_images_without_flagged_aois)
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # CalTopo-specific options
        self.caltopo_options_group = QGroupBox("CalTopo Options")
        caltopo_options_layout = QVBoxLayout()

        self.include_images = QCheckBox("Include Images")
        self.include_images.setChecked(True)  # Default: on
        self.include_images.setToolTip("Upload photos to CalTopo markers (CalTopo only)")
        self.include_images.setEnabled(False)  # Disabled by default, enabled when CalTopo is selected

        # Which photo(s) to attach to flagged AOI markers
        aoi_photo_layout = QHBoxLayout()
        self.aoi_photo_label = QLabel("Photo for flagged AOIs:")
        self.aoi_photo_mode = QComboBox()
        self.aoi_photo_mode.addItem("Full Image", 'full')
        self.aoi_photo_mode.addItem("AOI Thumbnail (Zoomed)", 'thumbnail')
        self.aoi_photo_mode.addItem("Both", 'both')
        self.aoi_photo_mode.setCurrentIndex(0)  # Default: full image (existing behavior)
        self.aoi_photo_mode.setToolTip(
            "Choose whether flagged AOI markers get the full overhead image, a zoomed\n"
            "crop centered on the detection, or both"
        )
        aoi_photo_layout.addWidget(self.aoi_photo_label)
        aoi_photo_layout.addWidget(self.aoi_photo_mode)
        aoi_photo_layout.addStretch()

        caltopo_options_layout.addWidget(self.include_images)
        caltopo_options_layout.addLayout(aoi_photo_layout)
        self.caltopo_options_group.setLayout(caltopo_options_layout)
        layout.addWidget(self.caltopo_options_group)

        # Connect export type changes to enable/disable CalTopo options
        self.kml_radio.toggled.connect(self._on_export_type_changed)
        self.caltopo_radio.toggled.connect(self._on_export_type_changed)

        # The AOI photo choice only matters when photos and flagged AOIs are exported
        self.include_images.toggled.connect(self._on_aoi_photo_options_changed)
        self.include_flagged_aois.toggled.connect(self._on_aoi_photo_options_changed)

        self._on_export_type_changed()  # Set initial state

        # Connect locations checkbox to enable/disable "Include Images without flagged AOIs"
        self.include_locations.toggled.connect(self._on_locations_changed)
        self._on_locations_changed()  # Set initial state

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.export_button = QPushButton("Export")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.accept)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

    def get_export_type(self):
        """
        Get the selected export type.

        Returns:
            str: 'kml' or 'caltopo'
        """
        return 'kml' if self.kml_radio.isChecked() else 'caltopo'

    def should_include_locations(self):
        """
        Check if drone/image locations should be included.

        Returns:
            bool: True if locations should be included
        """
        return self.include_locations.isChecked()

    def should_include_flagged_aois(self):
        """
        Check if flagged AOIs should be included.

        Returns:
            bool: True if flagged AOIs should be included
        """
        return self.include_flagged_aois.isChecked()

    def should_include_coverage(self):
        """
        Check if coverage area should be included.

        Returns:
            bool: True if coverage area should be included
        """
        return self.include_coverage.isChecked()

    def should_include_images(self):
        """
        Check if images should be included (CalTopo only).

        Returns:
            bool: True if images should be uploaded to CalTopo markers
        """
        return self.include_images.isChecked()

    def get_aoi_photo_mode(self):
        """
        Get the photo mode to use for flagged AOI markers (CalTopo only).

        Returns:
            str: 'full' for the full overhead image, 'thumbnail' for a zoomed crop
                 centered on the AOI, or 'both' to upload each.
        """
        return self.aoi_photo_mode.currentData() or 'full'

    def should_include_images_without_flagged_aois(self):
        """
        Check if images without flagged AOIs should be included in location exports.

        Returns:
            bool: True if images without flagged AOIs should be included
        """
        return self.include_images_without_flagged_aois.isChecked()

    def _on_export_type_changed(self):
        """Handle export type radio button changes."""
        is_caltopo = self.caltopo_radio.isChecked()
        self.include_images.setEnabled(is_caltopo)
        self.caltopo_options_group.setEnabled(is_caltopo)
        self._on_aoi_photo_options_changed()

    def _on_aoi_photo_options_changed(self):
        """Enable the AOI photo choice only when AOI photos will actually be uploaded."""
        enabled = (
            self.caltopo_radio.isChecked()
            and self.include_images.isChecked()
            and self.include_flagged_aois.isChecked()
        )
        self.aoi_photo_mode.setEnabled(enabled)
        self.aoi_photo_label.setEnabled(enabled)

    def _on_locations_changed(self):
        """Handle locations checkbox changes to enable/disable related option."""
        is_locations_checked = self.include_locations.isChecked()
        self.include_images_without_flagged_aois.setEnabled(is_locations_checked)
