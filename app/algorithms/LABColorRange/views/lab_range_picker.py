"""
LAB Range Picker Widget - Qt implementation of LAB color range selection

This widget provides an interface for selecting LAB color ranges with:
- L (Lightness) slider: 0-100
- A/B color plane: green-red (A) vs blue-yellow (B)
- Real-time range visualization
"""

import sys
import math
from typing import Tuple, Optional

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                           QFont, QMouseEvent, QImage, QPixmap)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFrame, QGridLayout,
                               QSlider, QSpinBox, QColorDialog)
import cv2
import numpy as np


class LABRangePickerWidget(QWidget):
    """Advanced LAB color range picker with visual feedback."""

    # Signals emitted when values change
    colorChanged = Signal(float, float, float)  # l, a, b (normalized range)
    rangeChanged = Signal(float, float, float, float, float, float)  # l-, l+, a-, a+, b-, b+

    def __init__(self, parent=None):
        super().__init__(parent)

        # LAB values (normalized)
        # L: 0-1 (0=black, 1=white)
        # A: -1 to 1 (green to red)
        # B: -1 to 1 (blue to yellow)
        self.l = 0.5
        self.a = 0.0
        self.b = 0.0

        # Range values (0-1 range, representing portion of full range)
        self.l_minus = 0.1   # 10% of L range
        self.l_plus = 0.1
        self.a_minus = 0.2   # 20% of A range
        self.a_plus = 0.2
        self.b_minus = 0.2   # 20% of B range
        self.b_plus = 0.2

        # Widget dimensions
        self.ab_plane_size = 300

        # Custom colors storage
        self.custom_colors = [QColor(255, 255, 255) for _ in range(16)]

        # Initialize UI
        self.setup_ui()
        self.setMinimumSize(800, 700)

    def setup_ui(self):
        """Setup the main UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header_layout = self.create_header()
        layout.addLayout(header_layout)

        # Main selector area
        selector_layout = self.create_selectors()
        layout.addLayout(selector_layout)

        # Range controls
        range_layout = self.create_range_controls()
        layout.addLayout(range_layout)

        # Color tools
        tools_layout = self.create_color_tools()
        layout.addLayout(tools_layout)

        # Info panel
        info_panel = self.create_info_panel()
        layout.addWidget(info_panel)

    def create_header(self):
        """Create header with hex input and reset button."""
        header_layout = QHBoxLayout()

        # Hex input
        hex_label = QLabel("HEX:")
        hex_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))

        self.hex_input = QLineEdit("#808080")
        self.hex_input.setMaxLength(7)
        self.hex_input.setFixedWidth(120)
        self.hex_input.setFont(QFont("Courier", 10))
        self.hex_input.textChanged.connect(self.on_hex_changed)

        # Reset button
        self.reset_button = QPushButton("Reset to Default")
        self.reset_button.setFixedHeight(30)
        self.reset_button.clicked.connect(self.reset_to_default)

        header_layout.addWidget(hex_label)
        header_layout.addWidget(self.hex_input)
        header_layout.addStretch()
        header_layout.addWidget(self.reset_button)

        return header_layout

    def create_selectors(self):
        """Create the main selector widgets."""
        selector_layout = QHBoxLayout()
        selector_layout.setSpacing(30)

        # A/B Plane section
        ab_layout = QVBoxLayout()
        ab_label = QLabel("A (Green-Red) / B (Blue-Yellow)")
        ab_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ab_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))

        self.ab_widget = ABPlaneWidget(self)
        self.ab_widget.setFixedSize(self.ab_plane_size, self.ab_plane_size)
        self.ab_widget.valueChanged.connect(self.on_ab_changed)

        ab_layout.addWidget(ab_label)
        ab_layout.addWidget(self.ab_widget)

        # L Slider section
        l_layout = QVBoxLayout()
        l_label = QLabel("Lightness (L)")
        l_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))

        self.l_widget = LightnessWidget(self)
        self.l_widget.setFixedSize(80, self.ab_plane_size)
        self.l_widget.valueChanged.connect(self.on_l_changed)

        l_layout.addWidget(l_label)
        l_layout.addWidget(self.l_widget)

        selector_layout.addLayout(ab_layout)
        selector_layout.addLayout(l_layout)

        return selector_layout

    def create_range_controls(self):
        """Create range control spinboxes."""
        range_layout = QVBoxLayout()
        range_label = QLabel("Color Range Tolerances:")
        range_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        range_layout.addWidget(range_label)

        controls_layout = QHBoxLayout()

        # L range controls
        l_group = self.create_range_group("L", self.l_minus, self.l_plus, 0, 100,
                                          self.on_l_range_changed)
        controls_layout.addLayout(l_group)

        # A range controls
        a_group = self.create_range_group("A", self.a_minus, self.a_plus, 0, 128,
                                          self.on_a_range_changed)
        controls_layout.addLayout(a_group)

        # B range controls
        b_group = self.create_range_group("B", self.b_minus, self.b_plus, 0, 128,
                                          self.on_b_range_changed)
        controls_layout.addLayout(b_group)

        range_layout.addLayout(controls_layout)
        return range_layout

    def create_range_group(self, label, minus_val, plus_val, min_val, max_val, callback):
        """Create a range control group for a channel."""
        group_layout = QHBoxLayout()

        # Label
        label_widget = QLabel(f"{label}:")
        label_widget.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        group_layout.addWidget(label_widget)

        # Minus spinbox
        minus_label = QLabel("-")
        group_layout.addWidget(minus_label)

        minus_spin = QSpinBox()
        minus_spin.setRange(min_val, max_val)
        minus_spin.setValue(int(minus_val * max_val))
        minus_spin.valueChanged.connect(lambda v: callback('minus', v))
        setattr(self, f'{label.lower()}_minus_spin', minus_spin)
        group_layout.addWidget(minus_spin)

        # Plus spinbox
        plus_label = QLabel("+")
        group_layout.addWidget(plus_label)

        plus_spin = QSpinBox()
        plus_spin.setRange(min_val, max_val)
        plus_spin.setValue(int(plus_val * max_val))
        plus_spin.valueChanged.connect(lambda v: callback('plus', v))
        setattr(self, f'{label.lower()}_plus_spin', plus_spin)
        group_layout.addWidget(plus_spin)

        return group_layout

    def on_l_range_changed(self, direction, value):
        """Handle L range changes."""
        if direction == 'minus':
            self.l_minus = value / 100
        else:
            self.l_plus = value / 100
        self.l_widget.update()
        self.emit_range_changed()

    def on_a_range_changed(self, direction, value):
        """Handle A range changes."""
        if direction == 'minus':
            self.a_minus = value / 128
        else:
            self.a_plus = value / 128
        self.ab_widget.update()
        self.emit_range_changed()

    def on_b_range_changed(self, direction, value):
        """Handle B range changes."""
        if direction == 'minus':
            self.b_minus = value / 128
        else:
            self.b_plus = value / 128
        self.ab_widget.update()
        self.emit_range_changed()

    def create_color_tools(self):
        """Create color tools section."""
        tools_layout = QVBoxLayout()
        tools_layout.setSpacing(15)

        # Buttons
        buttons_layout = QHBoxLayout()

        self.pick_screen_button = QPushButton("Pick Screen Color")
        self.pick_screen_button.setFixedHeight(35)
        self.pick_screen_button.clicked.connect(self.pick_screen_color)

        self.add_custom_button = QPushButton("Add to Custom Colors")
        self.add_custom_button.setFixedHeight(35)
        self.add_custom_button.clicked.connect(self.add_to_custom_colors)

        buttons_layout.addWidget(self.pick_screen_button)
        buttons_layout.addWidget(self.add_custom_button)
        buttons_layout.addStretch()

        tools_layout.addLayout(buttons_layout)

        # Color grids
        colors_layout = QHBoxLayout()

        # Basic colors
        basic_layout = QVBoxLayout()
        basic_label = QLabel("Basic Colors:")
        basic_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        basic_layout.addWidget(basic_label)
        basic_layout.addWidget(self.create_basic_colors_grid())

        # Custom colors
        custom_layout = QVBoxLayout()
        custom_label = QLabel("Custom Colors:")
        custom_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        custom_layout.addWidget(custom_label)
        self.custom_colors_grid_widget = self.create_custom_colors_grid()
        custom_layout.addWidget(self.custom_colors_grid_widget)

        colors_layout.addLayout(basic_layout)
        colors_layout.addLayout(custom_layout)
        colors_layout.addStretch()

        tools_layout.addLayout(colors_layout)

        return tools_layout

    def create_basic_colors_grid(self):
        """Create basic colors grid."""
        basic_colors = [
            QColor(255, 0, 0), QColor(255, 165, 0), QColor(255, 255, 0), QColor(0, 255, 0),
            QColor(0, 255, 255), QColor(0, 0, 255), QColor(128, 0, 128), QColor(255, 0, 255),
            QColor(192, 192, 192), QColor(128, 128, 128), QColor(128, 0, 0), QColor(128, 128, 0),
            QColor(0, 128, 0), QColor(0, 128, 128), QColor(0, 0, 128), QColor(64, 64, 64),
        ]

        grid_widget = QFrame()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(2)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        for i, color in enumerate(basic_colors):
            button = self.create_color_button(color, False, None)
            grid_layout.addWidget(button, i // 8, i % 8)

        return grid_widget

    def create_custom_colors_grid(self):
        """Create custom colors grid."""
        grid_widget = QFrame()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(2)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        for i in range(16):
            button = self.create_color_button(self.custom_colors[i], True, i)
            grid_layout.addWidget(button, i // 8, i % 8)

        return grid_widget

    def create_color_button(self, color, is_custom, index):
        """Create a clickable color button."""
        button = QPushButton()
        button.setFixedSize(25, 25)
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #888;
                border-radius: 2px;
            }}
            QPushButton:hover {{
                border: 2px solid #333;
            }}
        """)

        if is_custom:
            button.clicked.connect(lambda: self.select_custom_color(index))
        else:
            button.clicked.connect(lambda: self.select_basic_color(color))

        return button

    def select_basic_color(self, color):
        """Select a basic color."""
        l, a, b = self.rgb_to_lab(color.red(), color.green(), color.blue())
        self.set_lab(l, a, b)

    def select_custom_color(self, index):
        """Select a custom color."""
        color = self.custom_colors[index]
        l, a, b = self.rgb_to_lab(color.red(), color.green(), color.blue())
        self.set_lab(l, a, b)

    def pick_screen_color(self):
        """Pick a color from screen."""
        color = QColorDialog.getColor(options=QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            l, a, b = self.rgb_to_lab(color.red(), color.green(), color.blue())
            self.set_lab(l, a, b)

    def add_to_custom_colors(self):
        """Add current color to custom colors."""
        current_rgb = self.lab_to_rgb(self.l, self.a, self.b)
        current_color = QColor(*current_rgb)

        # Find first white slot or use slot 0
        slot_index = 0
        for i, color in enumerate(self.custom_colors):
            if color == QColor(255, 255, 255):
                slot_index = i
                break

        self.custom_colors[slot_index] = current_color

        # Recreate custom colors grid
        old_widget = self.custom_colors_grid_widget
        self.custom_colors_grid_widget = self.create_custom_colors_grid()
        old_widget.parent().layout().replaceWidget(old_widget, self.custom_colors_grid_widget)
        old_widget.deleteLater()

    def create_info_panel(self):
        """Create info panel showing current values."""
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Sunken)
        info_layout = QVBoxLayout(info_frame)

        self.info_label = QLabel()
        self.info_label.setFont(QFont("Courier", 9))
        self.update_info_label()

        info_layout.addWidget(self.info_label)
        return info_frame

    def update_info_label(self):
        """Update the info label with current values."""
        rgb = self.lab_to_rgb(self.l, self.a, self.b)
        lab_cv = (int(self.l * 255), int((self.a + 1) * 127.5), int((self.b + 1) * 127.5))

        info_text = f"""
Current Color:
  RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})
  LAB: L={lab_cv[0]}, A={lab_cv[1]}, B={lab_cv[2]}
  Normalized: L={self.l:.2f}, A={self.a:.2f}, B={self.b:.2f}

Ranges:
  L: -{int(self.l_minus*255):d} to +{int(self.l_plus*255):d}
  A: -{int(self.a_minus*128):d} to +{int(self.a_plus*128):d}
  B: -{int(self.b_minus*128):d} to +{int(self.b_plus*128):d}
        """
        self.info_label.setText(info_text.strip())

    def on_hex_changed(self, hex_str):
        """Handle hex input changes."""
        if len(hex_str) == 7 and hex_str.startswith('#'):
            try:
                color = QColor(hex_str)
                if color.isValid():
                    l, a, b = self.rgb_to_lab(color.red(), color.green(), color.blue())
                    self.set_lab(l, a, b, update_hex=False)
            except:
                pass

    def on_ab_changed(self, a, b):
        """Handle A/B plane changes."""
        self.a = a
        self.b = b
        self.update_from_lab()

    def on_l_changed(self, l):
        """Handle L slider changes."""
        self.l = l
        self.update_from_lab()

    def set_lab(self, l, a, b, update_hex=True):
        """Set LAB values and update UI."""
        self.l = max(0.0, min(1.0, l))
        self.a = max(-1.0, min(1.0, a))
        self.b = max(-1.0, min(1.0, b))
        self.update_from_lab(update_hex)

    def update_from_lab(self, update_hex=True):
        """Update all UI elements from current LAB values."""
        # Update widgets
        self.ab_widget.set_values(self.a, self.b, self.l)
        self.l_widget.set_value(self.l)

        # Update hex
        if update_hex:
            rgb = self.lab_to_rgb(self.l, self.a, self.b)
            hex_str = "#{:02X}{:02X}{:02X}".format(*rgb)
            self.hex_input.blockSignals(True)
            self.hex_input.setText(hex_str)
            self.hex_input.blockSignals(False)

        # Update info
        self.update_info_label()

        # Emit signal
        self.colorChanged.emit(self.l, self.a, self.b)

    def emit_range_changed(self):
        """Emit range changed signal."""
        self.update_info_label()
        self.rangeChanged.emit(self.l_minus, self.l_plus,
                               self.a_minus, self.a_plus,
                               self.b_minus, self.b_plus)

    def reset_to_default(self):
        """Reset to default values."""
        self.set_lab(0.5, 0.0, 0.0)

    def rgb_to_lab(self, r, g, b):
        """Convert RGB to LAB (normalized)."""
        rgb = np.uint8([[[r, g, b]]])
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[0][0]
        l = lab[0] / 255
        a = (lab[1] - 128) / 128
        b = (lab[2] - 128) / 128
        return l, a, b

    def lab_to_rgb(self, l, a, b):
        """Convert LAB (normalized) to RGB."""
        lab = np.uint8([[[l * 255, (a + 1) * 127.5, (b + 1) * 127.5]]])
        rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)[0][0]
        return int(rgb[0]), int(rgb[1]), int(rgb[2])

    def get_lab_ranges(self):
        """Get current LAB values and ranges."""
        return {
            'l': self.l, 'a': self.a, 'b': self.b,
            'l_minus': self.l_minus, 'l_plus': self.l_plus,
            'a_minus': self.a_minus, 'a_plus': self.a_plus,
            'b_minus': self.b_minus, 'b_plus': self.b_plus
        }


class ABPlaneWidget(QWidget):
    """A/B color plane widget."""

    valueChanged = Signal(float, float)  # a, b

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_picker = parent
        self.a = 0.0
        self.b = 0.0
        self.l = 0.5
        self.setMouseTracking(True)

    def set_values(self, a, b, l):
        """Set A, B, and L values."""
        self.a = a
        self.b = b
        self.l = l
        self.update()

    def paintEvent(self, event):
        """Paint the A/B plane."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Create A/B plane image
        size = min(self.width(), self.height())
        image = QImage(size, size, QImage.Format.Format_RGB888)

        # Fill with colors
        for y in range(size):
            for x in range(size):
                # Map x, y to A, B values (-1 to 1)
                a = (x / size) * 2 - 1
                b = 1 - (y / size) * 2  # Invert Y axis

                # Convert LAB to RGB
                lab_cv = np.uint8([[[self.l * 255, (a + 1) * 127.5, (b + 1) * 127.5]]])
                try:
                    rgb = cv2.cvtColor(lab_cv, cv2.COLOR_LAB2RGB)[0][0]
                    color = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
                except:
                    color = QColor(128, 128, 128)

                image.setPixelColor(x, y, color)

        # Draw image
        painter.drawImage(0, 0, image)

        # Draw current position marker
        x = int((self.a + 1) / 2 * size)
        y = int((1 - self.b) / 2 * size)

        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawEllipse(x - 5, y - 5, 10, 10)
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.drawEllipse(x - 6, y - 6, 12, 12)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        self.update_from_mouse(event.position().toPoint())

    def mouseMoveEvent(self, event):
        """Handle mouse move."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.update_from_mouse(event.position().toPoint())

    def update_from_mouse(self, pos):
        """Update A/B values from mouse position."""
        size = min(self.width(), self.height())
        a = (pos.x() / size) * 2 - 1
        b = 1 - (pos.y() / size) * 2

        self.a = max(-1.0, min(1.0, a))
        self.b = max(-1.0, min(1.0, b))

        self.valueChanged.emit(self.a, self.b)
        self.update()


class LightnessWidget(QWidget):
    """Lightness slider widget."""

    valueChanged = Signal(float)  # l value

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_picker = parent
        self.l = 0.5
        self.setMouseTracking(True)

    def set_value(self, l):
        """Set L value."""
        self.l = l
        self.update()

    def paintEvent(self, event):
        """Paint the lightness gradient."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Draw gradient from black to white
        gradient = QLinearGradient(0, height, 0, 0)
        gradient.setColorAt(0, QColor(0, 0, 0))
        gradient.setColorAt(1, QColor(255, 255, 255))

        painter.fillRect(0, 0, width, height, gradient)

        # Draw current position marker
        y = int((1 - self.l) * height)

        painter.setPen(QPen(Qt.GlobalColor.red, 3))
        painter.drawLine(0, y, width, y)

    def mousePressEvent(self, event):
        """Handle mouse press."""
        self.update_from_mouse(event.position().toPoint())

    def mouseMoveEvent(self, event):
        """Handle mouse move."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.update_from_mouse(event.position().toPoint())

    def update_from_mouse(self, pos):
        """Update L value from mouse position."""
        self.l = 1 - (pos.y() / self.height())
        self.l = max(0.0, min(1.0, self.l))

        self.valueChanged.emit(self.l)
        self.update()
