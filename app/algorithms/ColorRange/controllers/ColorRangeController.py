from ast import literal_eval

from algorithms.Algorithm import AlgorithmController
from algorithms.ColorRange.views.ColorRange_ui import Ui_ColorRange
from algorithms.ColorRange.controllers.ColorRangeRangeViewerController import ColorRangeRangeViewer

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QColorDialog

from helpers.ColorUtils import ColorUtils
from core.services.LoggerService import LoggerService


class ColorRangeController(QWidget, Ui_ColorRange, AlgorithmController):
    """Controller for the Color Range algorithm widget."""

    def __init__(self):
        """
        Initializes the ColorRangeController widget and sets up the UI.

        Connects UI elements like color selection button and range spin boxes to their respective event handlers.
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, 'ColorRange', False)
        self.logger = LoggerService()
        self.setupUi(self)
        self.selectedColor = None
        self.viewRangeButton.hide()
        self.colorButton.clicked.connect(self.colorButtonClicked)
        self.viewRangeButton.clicked.connect(self.viewRangeButtonClicked)

        self.rRangeSpinBox.valueChanged.connect(self.updateColors)
        self.gRangeSpinBox.valueChanged.connect(self.updateColors)
        self.bRangeSpinBox.valueChanged.connect(self.updateColors)

    def colorButtonClicked(self):
        """
        Handles the color selection button click.

        Opens a color picker dialog to allow the user to select a color. Updates
        the selected color if a valid color is chosen.
        """
        try:
            if self.selectedColor is not None:
                self.selectedColor = QColorDialog().getColor(self.selectedColor)
            else:
                self.selectedColor = QColorDialog().getColor()
            if self.selectedColor.isValid():
                self.updateColors()
        except Exception as e:
            self.logger.error(e)

    def viewRangeButtonClicked(self):
        """
        Handles the view range button click.

        Opens the View Range dialog, displaying the selected color range.
        """
        rangeDialog = ColorRangeRangeViewer(self.lowerColor, self.upperColor)
        rangeDialog.exec()

    def updateColors(self):
        """
        Updates the color range boxes based on the base color and range spin box values.

        Retrieves the minimum and maximum RGB colors relative to the base color and updates
        the displayed color boxes accordingly.
        """
        if self.selectedColor is not None:
            rgb = [self.selectedColor.red(), self.selectedColor.green(), self.selectedColor.blue()]
            self.lowerColor, self.upperColor = ColorUtils.getColorRange(
                rgb, self.rRangeSpinBox.value(), self.gRangeSpinBox.value(), self.bRangeSpinBox.value()
            )
            hex_lower = '#%02x%02x%02x' % self.lowerColor
            hex_upper = '#%02x%02x%02x' % self.upperColor
            self.minColor.setStyleSheet("background-color: " + hex_lower)
            self.midColor.setStyleSheet("background-color: " + self.selectedColor.name())
            self.maxColor.setStyleSheet("background-color: " + hex_upper)
            self.viewRangeButton.show()

    def getOptions(self):
        """
        Populates options based on user-selected values.

        Returns:
            dict: A dictionary containing selected options, including 'color_range', 'selected_color', and 'range_values'.
        """
        options = dict()
        options['color_range'] = [self.lowerColor, self.upperColor]
        options['selected_color'] = (self.selectedColor.red(), self.selectedColor.green(), self.selectedColor.blue())
        options['range_values'] = (self.rRangeSpinBox.value(), self.gRangeSpinBox.value(), self.bRangeSpinBox.value())
        return options

    def validate(self):
        """
        Validates that the required values have been provided.

        Returns:
            str: An error message if validation fails, otherwise None.
        """
        if self.selectedColor is None:
            return "Please select a search color."
        return None

    def loadOptions(self, options):
        """
        Sets UI elements based on the provided options.

        Args:
            options (dict): The options to use to set UI attributes, including 'range_values' and 'selected_color'.
        """
        if 'range_values' in options and 'selected_color' in options:
            ranges = literal_eval(options['range_values'])
            self.rRangeSpinBox.setValue(ranges[0])
            self.gRangeSpinBox.setValue(ranges[1])
            self.bRangeSpinBox.setValue(ranges[2])
            selected_color = literal_eval(options['selected_color'])
            self.selectedColor = QColor(selected_color[0], selected_color[1], selected_color[2])
            self.updateColors()
