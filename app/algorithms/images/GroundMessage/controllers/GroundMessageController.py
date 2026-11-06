"""Controller for the Ground Message Detector settings widget."""

from PySide6.QtWidgets import QWidget

from algorithms.AlgorithmController import AlgorithmController
from algorithms.images.GroundMessage.services.GroundMessageService import (
    OPTION_CONFIDENCE, OPTION_MAX_CHAR_SIZE, OPTION_MIN_CHAR_SIZE, OPTION_POLARITY, OPTION_SINGLE_CHARACTERS,
    POLARITY_BOTH, POLARITY_DARK, POLARITY_LIGHT, coerce_options)
from algorithms.images.GroundMessage.views.GroundMessage_ui import Ui_GroundMessage
from helpers.TranslationMixin import TranslationMixin

# Stable option value for each row of polarityComboBox, in .ui order.
POLARITY_COMBO_VALUES = (POLARITY_BOTH, POLARITY_DARK, POLARITY_LIGHT)


class GroundMessageController(TranslationMixin, QWidget, Ui_GroundMessage, AlgorithmController):
    """Settings widget for the Ground Message Detector (main window)."""

    def __init__(self, config, theme):
        """Initialize the widget.

        Args:
            config: Algorithm config dictionary from algorithms.conf.
            theme: Name of the active theme (unused; part of the controller contract).
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, config)
        self.theme = theme
        self.setupUi(self)
        for index, value in enumerate(POLARITY_COMBO_VALUES):
            self.polarityComboBox.setItemData(index, value)
        self.fixComboBoxForMacOS(self.polarityComboBox)
        self.confidenceSlider.valueChanged.connect(self._update_confidence_label)
        self._update_confidence_label()

    def _update_confidence_label(self):
        """Show the slider value next to the slider."""
        self.confidenceValueLabel.setText(str(self.confidenceSlider.value()))

    def get_options(self):
        """Return the algorithm options selected in the widget.

        Returns:
            dict with confidence_threshold, min_char_size, max_char_size,
            stroke_polarity and detect_single_characters.
        """
        return {
            OPTION_CONFIDENCE: self.confidenceSlider.value(),
            OPTION_MIN_CHAR_SIZE: self.minCharSizeSpinBox.value(),
            OPTION_MAX_CHAR_SIZE: self.maxCharSizeSpinBox.value(),
            OPTION_POLARITY: self.polarityComboBox.currentData() or POLARITY_BOTH,
            OPTION_SINGLE_CHARACTERS: self.singleCharactersCheckBox.isChecked(),
        }

    def validate(self):
        """Check the options before processing starts.

        Returns:
            An error message, or None when the options are valid.
        """
        if self.minCharSizeSpinBox.value() >= self.maxCharSizeSpinBox.value():
            return self.tr("The minimum character size must be smaller than the maximum character size.")
        return None

    def load_options(self, options):
        """Restore the widget from saved options.

        Values may be strings (options saved in ADIAT_Data.xml); missing or
        unreadable values fall back to the defaults.

        Args:
            options: Options dictionary.
        """
        if not isinstance(options, dict):
            return
        values = coerce_options(options)
        self.confidenceSlider.setValue(max(0, min(100, values[OPTION_CONFIDENCE])))
        self.minCharSizeSpinBox.setValue(values[OPTION_MIN_CHAR_SIZE])
        self.maxCharSizeSpinBox.setValue(values[OPTION_MAX_CHAR_SIZE])
        index = self.polarityComboBox.findData(values[OPTION_POLARITY])
        self.polarityComboBox.setCurrentIndex(index if index >= 0 else 0)
        self.singleCharactersCheckBox.setChecked(values[OPTION_SINGLE_CHARACTERS])
