"""
LAB Color Range Dialog - LAB color selection dialog with live preview

Provides an interface for selecting LAB color ranges with real-time visual feedback.
"""

import cv2
import numpy as np
from typing import Tuple, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFrame, QCheckBox, QGroupBox)

from .lab_range_picker import LABRangePickerWidget
from core.services.CustomColorsService import get_custom_colors_service


class LABColorRangeDialog(QDialog):
    """Advanced LAB color range selection dialog with live preview."""

    # Signal emitted when color selection is accepted
    colorSelected = Signal(dict)  # LAB range data

    def __init__(self, initial_image=None, initial_lab=(0.5, 0, 0),
                 initial_ranges=None, parent=None):
        super().__init__(parent)

        self.setWindowTitle("LAB Color Range Selection")
        self.setModal(True)
        self.resize(1000, 800)

        # Store initial values
        self.original_image = initial_image
        self.processed_image = None

        # Initialize ranges
        if initial_ranges is None:
            initial_ranges = {
                'l_minus': 0.1, 'l_plus': 0.1,
                'a_minus': 0.2, 'a_plus': 0.2,
                'b_minus': 0.2, 'b_plus': 0.2
            }

        # Setup UI
        self.setup_ui()

        # Set initial values
        l, a, b = initial_lab
        self.color_picker.set_lab(l, a, b)
        self.color_picker.l_minus = initial_ranges['l_minus']
        self.color_picker.l_plus = initial_ranges['l_plus']
        self.color_picker.a_minus = initial_ranges['a_minus']
        self.color_picker.a_plus = initial_ranges['a_plus']
        self.color_picker.b_minus = initial_ranges['b_minus']
        self.color_picker.b_plus = initial_ranges['b_plus']

        # Update spinboxes
        self.color_picker.l_minus_spin.setValue(int(initial_ranges['l_minus'] * 100))
        self.color_picker.l_plus_spin.setValue(int(initial_ranges['l_plus'] * 100))
        self.color_picker.a_minus_spin.setValue(int(initial_ranges['a_minus'] * 128))
        self.color_picker.a_plus_spin.setValue(int(initial_ranges['a_plus'] * 128))
        self.color_picker.b_minus_spin.setValue(int(initial_ranges['b_minus'] * 128))
        self.color_picker.b_plus_spin.setValue(int(initial_ranges['b_plus'] * 128))

        self.color_picker.update_from_lab()

        # Connect signals
        self.connect_signals()

        # Setup preview timer
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.setSingleShot(True)

        # Initial preview update
        if self.original_image is not None:
            self.update_preview()

    def setup_ui(self):
        """Setup the dialog UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Main content area
        content_layout = QHBoxLayout()

        # Left side - Color picker
        picker_group = QGroupBox("LAB Color Range Selection")
        picker_layout = QVBoxLayout(picker_group)

        self.color_picker = LABRangePickerWidget()
        picker_layout.addWidget(self.color_picker)

        content_layout.addWidget(picker_group)

        # Right side - Preview (if image provided)
        if self.original_image is not None:
            preview_group = self.create_preview_panel()
            content_layout.addWidget(preview_group)

        main_layout.addLayout(content_layout)

        # Bottom buttons
        button_layout = self.create_button_layout()
        main_layout.addLayout(button_layout)

    def create_preview_panel(self):
        """Create the image preview panel."""
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        # Original image
        self.original_label = QLabel("Original Image")
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setStyleSheet("QLabel { background-color: black; border: 1px solid gray; }")
        self.original_label.setMinimumSize(300, 225)
        self.original_label.setScaledContents(True)

        # Processed image
        self.processed_label = QLabel("Filtered Result")
        self.processed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.processed_label.setStyleSheet("QLabel { background-color: black; border: 1px solid gray; }")
        self.processed_label.setMinimumSize(300, 225)
        self.processed_label.setScaledContents(True)

        # Show mask option
        self.show_mask_cb = QCheckBox("Show mask only")
        self.show_mask_cb.toggled.connect(self.on_preview_option_changed)

        preview_layout.addWidget(QLabel("Original:"))
        preview_layout.addWidget(self.original_label)
        preview_layout.addWidget(QLabel("Result:"))
        preview_layout.addWidget(self.processed_label)
        preview_layout.addWidget(self.show_mask_cb)
        preview_layout.addStretch()

        # Set initial original image
        if self.original_image is not None:
            self.set_image_to_label(self.original_label, self.original_image)

        return preview_group

    def create_button_layout(self):
        """Create the bottom button layout."""
        button_layout = QHBoxLayout()

        # Test button (if image available)
        if self.original_image is not None:
            self.test_button = QPushButton("Test on Image")
            self.test_button.clicked.connect(self.update_preview)
            button_layout.addWidget(self.test_button)

        button_layout.addStretch()

        # Standard dialog buttons
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)

        return button_layout

    def connect_signals(self):
        """Connect widget signals."""
        self.color_picker.colorChanged.connect(self.on_color_changed)
        self.color_picker.rangeChanged.connect(self.on_range_changed)

    def on_color_changed(self, l, a, b):
        """Handle color changes."""
        if self.original_image is not None:
            # Debounce preview updates
            self.preview_timer.stop()
            self.preview_timer.start(100)

    def on_range_changed(self, l_minus, l_plus, a_minus, a_plus, b_minus, b_plus):
        """Handle range changes."""
        if self.original_image is not None:
            # Debounce preview updates
            self.preview_timer.stop()
            self.preview_timer.start(100)

    def on_preview_option_changed(self):
        """Handle preview option changes."""
        if self.original_image is not None:
            self.update_preview()

    def update_preview(self):
        """Update the preview image with current LAB settings."""
        if self.original_image is None:
            return

        try:
            # Convert image to LAB
            lab_image = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2LAB)

            # Get current LAB values and ranges
            lab_data = self.color_picker.get_lab_ranges()
            l, a, b = lab_data['l'], lab_data['a'], lab_data['b']
            l_minus, l_plus = lab_data['l_minus'], lab_data['l_plus']
            a_minus, a_plus = lab_data['a_minus'], lab_data['a_plus']
            b_minus, b_plus = lab_data['b_minus'], lab_data['b_plus']

            # Calculate bounds in OpenCV format
            l_center = int(l * 255)
            a_center = int((a + 1) * 127.5)
            b_center = int((b + 1) * 127.5)

            l_low = max(0, l_center - int(l_minus * 255))
            l_high = min(255, l_center + int(l_plus * 255))
            a_low = max(0, a_center - int(a_minus * 128))
            a_high = min(255, a_center + int(a_plus * 128))
            b_low = max(0, b_center - int(b_minus * 128))
            b_high = min(255, b_center + int(b_plus * 128))

            # Create mask
            lower_bound = np.array([l_low, a_low, b_low], dtype=np.uint8)
            upper_bound = np.array([l_high, a_high, b_high], dtype=np.uint8)
            mask = cv2.inRange(lab_image, lower_bound, upper_bound)

            # Create result image
            if self.show_mask_cb.isChecked():
                result = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            else:
                result = cv2.bitwise_and(self.original_image, self.original_image, mask=mask)

            # Display result
            self.set_image_to_label(self.processed_label, result)

        except Exception as e:
            print(f"Error updating preview: {e}")

    def set_image_to_label(self, label, image):
        """Set an OpenCV image to a QLabel."""
        if image is None:
            return

        # Convert BGR to RGB
        if len(image.shape) == 3 and image.shape[2] == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image

        h, w = image_rgb.shape[:2]
        bytes_per_line = 3 * w if len(image_rgb.shape) == 3 else w

        # Create QImage
        if len(image_rgb.shape) == 3:
            q_image = QImage(image_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        else:
            q_image = QImage(image_rgb.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)

        # Create pixmap and set to label
        pixmap = QPixmap.fromImage(q_image)
        label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))

    def get_lab_ranges(self):
        """Get the selected LAB ranges."""
        return self.color_picker.get_lab_ranges()

    def accept(self):
        """Override accept to emit signal with LAB data."""
        lab_data = self.get_lab_ranges()
        self.colorSelected.emit(lab_data)
        super().accept()
