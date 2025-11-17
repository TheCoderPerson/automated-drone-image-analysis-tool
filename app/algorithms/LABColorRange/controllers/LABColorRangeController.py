from ast import literal_eval

from algorithms.AlgorithmController import AlgorithmController
from algorithms.LABColorRange.views.LABColorRange_ui import Ui_LABColorRange
from algorithms.LABColorRange.views.lab_color_range_dialog import LABColorRangeDialog
from core.services.LoggerService import LoggerService

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
import cv2
import numpy as np


class LABColorRangeController(QWidget, Ui_LABColorRange, AlgorithmController):
    """Controller for the LAB Color Range algorithm widget."""

    def __init__(self, config):
        """
        Initializes the LABColorRangeController widget and sets up the UI.

        Connects UI elements like threshold spinboxes and color selection button
        to their respective event handlers.
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, config)
        self.logger = LoggerService()
        self.setupUi(self)
        self.viewRangeButton.hide()
        self.selectedColor = None

        # Connect button events
        self.colorButton.clicked.connect(self.color_button_clicked)
        self.viewRangeButton.clicked.connect(self.view_range_button_clicked)

        # Connect spinbox events for separate ranges
        self.lMinusSpinBox.valueChanged.connect(self.on_ranges_changed)
        self.lPlusSpinBox.valueChanged.connect(self.on_ranges_changed)
        self.aMinusSpinBox.valueChanged.connect(self.on_ranges_changed)
        self.aPlusSpinBox.valueChanged.connect(self.on_ranges_changed)
        self.bMinusSpinBox.valueChanged.connect(self.on_ranges_changed)
        self.bPlusSpinBox.valueChanged.connect(self.on_ranges_changed)

        # LAB window data from new dialog
        self._lab_window = None

    def on_ranges_changed(self):
        """Handle changes to the individual range spinboxes."""
        if self.selectedColor and self._lab_window:
            # Update the LAB window data with new ranges
            # Convert spinbox values to normalized range
            # L: 0-255 maps to 0-1
            self._lab_window['l_minus'] = self.lMinusSpinBox.value() / 255
            self._lab_window['l_plus'] = self.lPlusSpinBox.value() / 255
            # A and B: 0-128 maps to 0-1 (representing half the range)
            self._lab_window['a_minus'] = self.aMinusSpinBox.value() / 128
            self._lab_window['a_plus'] = self.aPlusSpinBox.value() / 128
            self._lab_window['b_minus'] = self.bMinusSpinBox.value() / 128
            self._lab_window['b_plus'] = self.bPlusSpinBox.value() / 128

    def color_button_clicked(self):
        """
        Handles the color selection button click.

        Opens the LAB color range dialog for advanced color selection.
        """
        try:
            # Prepare initial values
            initial_lab = (0.5, 0, 0)  # Default: 50% lightness, neutral A/B
            initial_ranges = None

            # Set current values if available
            if self._lab_window:
                # Use existing LAB window data
                l, a, b = self._lab_window['l'], self._lab_window['a'], self._lab_window['b']
                initial_lab = (l, a, b)

                initial_ranges = {
                    'l_minus': self._lab_window['l_minus'],
                    'l_plus': self._lab_window['l_plus'],
                    'a_minus': self._lab_window['a_minus'],
                    'a_plus': self._lab_window['a_plus'],
                    'b_minus': self._lab_window['b_minus'],
                    'b_plus': self._lab_window['b_plus']
                }

            elif self.selectedColor and self.selectedColor.isValid():
                # Convert existing RGB color to LAB
                rgb_color = np.uint8([[[self.selectedColor.red(),
                                        self.selectedColor.green(),
                                        self.selectedColor.blue()]]])
                lab_color = cv2.cvtColor(rgb_color, cv2.COLOR_RGB2LAB)[0][0]

                # Normalize to 0-1 range for L, and -1 to 1 for A and B
                l = lab_color[0] / 255
                a = (lab_color[1] - 128) / 128
                b = (lab_color[2] - 128) / 128
                initial_lab = (l, a, b)

                # Use current spinbox ranges
                initial_ranges = {
                    'l_minus': self.lMinusSpinBox.value() / 255,
                    'l_plus': self.lPlusSpinBox.value() / 255,
                    'a_minus': self.aMinusSpinBox.value() / 128,
                    'a_plus': self.aPlusSpinBox.value() / 128,
                    'b_minus': self.bMinusSpinBox.value() / 128,
                    'b_plus': self.bPlusSpinBox.value() / 128
                }

            # Create and show dialog
            dialog = LABColorRangeDialog(None, initial_lab, initial_ranges, self)

            if dialog.exec() == LABColorRangeDialog.Accepted:
                lab_data = dialog.get_lab_ranges()

                # Store the data in our format for the service
                self._lab_window = lab_data

                # Save any custom colors that may have been modified
                from core.services.CustomColorsService import get_custom_colors_service
                custom_colors_service = get_custom_colors_service()
                custom_colors_service.sync_with_dialog()

                # Convert LAB to RGB for display
                l, a, b = lab_data['l'], lab_data['a'], lab_data['b']

                # Convert normalized LAB to OpenCV LAB
                lab_cv = np.uint8([[[l * 255, (a + 1) * 127.5, (b + 1) * 127.5]]])
                rgb_cv = cv2.cvtColor(lab_cv, cv2.COLOR_LAB2RGB)[0][0]

                self.selectedColor = QColor(int(rgb_cv[0]), int(rgb_cv[1]), int(rgb_cv[2]))

                # Update the separate range spinboxes
                self.lMinusSpinBox.setValue(int(lab_data['l_minus'] * 255))
                self.lPlusSpinBox.setValue(int(lab_data['l_plus'] * 255))
                self.aMinusSpinBox.setValue(int(lab_data['a_minus'] * 128))
                self.aPlusSpinBox.setValue(int(lab_data['a_plus'] * 128))
                self.bMinusSpinBox.setValue(int(lab_data['b_minus'] * 128))
                self.bPlusSpinBox.setValue(int(lab_data['b_plus'] * 128))

                self.update_colors()

        except Exception as e:
            self.logger.error(f"Error in color button click: {e}")

    def view_range_button_clicked(self):
        """
        Handles the view range button click.

        Opens a dialog displaying the selected color and threshold values for L, A, B.
        """
        # This could be implemented similar to HSV if needed
        # For now, we'll just log that the button was clicked
        self.logger.info("View range button clicked - feature not yet implemented for LAB")

    def update_colors(self):
        """
        Updates the color of the selected color box and shows the view range button.
        """
        if self.selectedColor is not None:
            self.colorSample.setStyleSheet("background-color: " + self.selectedColor.name())
            self.viewRangeButton.show()

    def get_options(self):
        """Get the current configuration options."""
        options = dict()
        if self._lab_window is not None:
            # Use LAB range data
            options['lab_ranges'] = self._lab_window

            # Convert LAB to RGB for backward compatibility
            l, a, b = self._lab_window['l'], self._lab_window['a'], self._lab_window['b']
            lab_cv = np.uint8([[[l * 255, (a + 1) * 127.5, (b + 1) * 127.5]]])
            rgb_cv = cv2.cvtColor(lab_cv, cv2.COLOR_LAB2RGB)[0][0]

            options['selected_color'] = (int(rgb_cv[0]), int(rgb_cv[1]), int(rgb_cv[2]))

            # For backward compatibility, provide average threshold values
            options['l_threshold'] = int((self._lab_window['l_minus'] + self._lab_window['l_plus']) * 127.5)
            options['a_threshold'] = int((self._lab_window['a_minus'] + self._lab_window['a_plus']) * 64)
            options['b_threshold'] = int((self._lab_window['b_minus'] + self._lab_window['b_plus']) * 64)

        elif self.selectedColor is not None:
            # Create LAB window data from separate spinboxes
            rgb_color = np.uint8([[[self.selectedColor.red(),
                                    self.selectedColor.green(),
                                    self.selectedColor.blue()]]])
            lab_color = cv2.cvtColor(rgb_color, cv2.COLOR_RGB2LAB)[0][0]

            l = lab_color[0] / 255
            a = (lab_color[1] - 128) / 128
            b = (lab_color[2] - 128) / 128

            options['lab_ranges'] = {
                'l': l, 'a': a, 'b': b,
                'l_minus': self.lMinusSpinBox.value() / 255,
                'l_plus': self.lPlusSpinBox.value() / 255,
                'a_minus': self.aMinusSpinBox.value() / 128,
                'a_plus': self.aPlusSpinBox.value() / 128,
                'b_minus': self.bMinusSpinBox.value() / 128,
                'b_plus': self.bPlusSpinBox.value() / 128
            }

            options['selected_color'] = (self.selectedColor.red(),
                                          self.selectedColor.green(),
                                          self.selectedColor.blue())

            # For backward compatibility
            options['l_threshold'] = int((self.lMinusSpinBox.value() + self.lPlusSpinBox.value()) / 2)
            options['a_threshold'] = int((self.aMinusSpinBox.value() + self.aPlusSpinBox.value()) / 2)
            options['b_threshold'] = int((self.bMinusSpinBox.value() + self.bPlusSpinBox.value()) / 2)
        else:
            options['selected_color'] = None
            options['l_threshold'] = None
            options['a_threshold'] = None
            options['b_threshold'] = None

        return options

    def validate(self):
        """
        Validates that the required values have been provided.

        Returns:
            str: An error message if validation fails, otherwise None.
        """
        if self._lab_window is None and self.selectedColor is None:
            return "Please select a search color."
        return None

    def load_options(self, options):
        """
        Sets UI elements based on the provided options.

        Args:
            options (dict): The options to use to set UI attributes.
        """
        # Load LAB ranges if available
        if 'lab_ranges' in options:
            if isinstance(options['lab_ranges'], str):
                self._lab_window = literal_eval(options['lab_ranges'])
            else:
                self._lab_window = options['lab_ranges']

            # Update UI from LAB ranges
            l, a, b = self._lab_window['l'], self._lab_window['a'], self._lab_window['b']

            # Convert LAB to RGB for display
            lab_cv = np.uint8([[[l * 255, (a + 1) * 127.5, (b + 1) * 127.5]]])
            rgb_cv = cv2.cvtColor(lab_cv, cv2.COLOR_LAB2RGB)[0][0]

            self.selectedColor = QColor(int(rgb_cv[0]), int(rgb_cv[1]), int(rgb_cv[2]))
            self.colorSample.setStyleSheet("background-color: " + self.selectedColor.name())
            self.viewRangeButton.show()

            # Update range spinboxes
            self.lMinusSpinBox.setValue(int(self._lab_window['l_minus'] * 255))
            self.lPlusSpinBox.setValue(int(self._lab_window['l_plus'] * 255))
            self.aMinusSpinBox.setValue(int(self._lab_window['a_minus'] * 128))
            self.aPlusSpinBox.setValue(int(self._lab_window['a_plus'] * 128))
            self.bMinusSpinBox.setValue(int(self._lab_window['b_minus'] * 128))
            self.bPlusSpinBox.setValue(int(self._lab_window['b_plus'] * 128))

        elif 'selected_color' in options:
            # Fallback to simple color selection
            selected_color = literal_eval(options['selected_color'])
            self.selectedColor = QColor(selected_color[0], selected_color[1], selected_color[2])
            self.colorSample.setStyleSheet("background-color: " + self.selectedColor.name())
            self.viewRangeButton.show()

            # Set range spinboxes if available
            if 'l_threshold' in options:
                l_val = int(options['l_threshold'])
                self.lMinusSpinBox.setValue(l_val)
                self.lPlusSpinBox.setValue(l_val)

            if 'a_threshold' in options:
                a_val = int(options['a_threshold'])
                self.aMinusSpinBox.setValue(a_val)
                self.aPlusSpinBox.setValue(a_val)

            if 'b_threshold' in options:
                b_val = int(options['b_threshold'])
                self.bMinusSpinBox.setValue(b_val)
                self.bPlusSpinBox.setValue(b_val)
