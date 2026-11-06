"""Wizard controller for the Ground Message Detector.

Asks plain-language questions in the Image Analysis Guide and maps the
answers onto the detector's options.
"""

from PySide6.QtWidgets import QButtonGroup, QVBoxLayout, QWidget

from algorithms.AlgorithmController import AlgorithmController
from algorithms.images.GroundMessage.services.GroundMessageService import (
    DEFAULT_MAX_CHAR_SIZE, DEFAULT_MIN_CHAR_SIZE, OPTION_CONFIDENCE, OPTION_MAX_CHAR_SIZE, OPTION_MIN_CHAR_SIZE,
    OPTION_POLARITY, OPTION_SINGLE_CHARACTERS, POLARITY_BOTH, POLARITY_DARK, POLARITY_LIGHT, coerce_options)
from algorithms.images.GroundMessage.views.GroundMessageWizard_ui import Ui_GroundMessageWizard
from core.views.components.LabeledSlider import TextLabeledSlider
from helpers.TranslationMixin import TranslationMixin

# Confidence threshold for each aggressiveness preset, from Very Conservative
# (index 0) to Very Aggressive (index 4).
AGGRESSIVENESS_CONFIDENCE = (70, 60, 50, 42, 35)
DEFAULT_AGGRESSIVENESS_INDEX = 2


def aggressiveness_index_for_confidence(confidence):
    """Preset index whose confidence threshold is closest to the given one."""
    return min(range(len(AGGRESSIVENESS_CONFIDENCE)),
               key=lambda i: (abs(AGGRESSIVENESS_CONFIDENCE[i] - confidence), i))


class GroundMessageWizardController(TranslationMixin, QWidget, Ui_GroundMessageWizard, AlgorithmController):
    """Guided settings for the Ground Message Detector."""

    def __init__(self, config, theme):
        """Initialize the wizard widget.

        Args:
            config: Algorithm config dictionary from algorithms.conf.
            theme: Name of the active theme (unused; part of the controller contract).
        """
        QWidget.__init__(self)
        AlgorithmController.__init__(self, config)
        self.theme = theme
        self.setupUi(self)
        self._wire_up_ui()

    def _wire_up_ui(self):
        """Group the radio buttons and add the aggressiveness slider."""
        self.materialGroup = QButtonGroup(self)
        for button in (self.radioMaterialDark, self.radioMaterialLight, self.radioMaterialEither):
            self.materialGroup.addButton(button)
        self.singleGroup = QButtonGroup(self)
        self.singleGroup.addButton(self.radioSingleNo)
        self.singleGroup.addButton(self.radioSingleYes)

        self.aggressivenessSlider = TextLabeledSlider(
            self,
            presets=[
                self.tr("Very \nConservative"),
                self.tr("Conservative"),
                self.tr("Moderate"),
                self.tr("Aggressive"),
                self.tr("Very \nAggressive"),
            ],
        )
        self.aggressivenessSlider.setValue(DEFAULT_AGGRESSIVENESS_INDEX)
        layout = QVBoxLayout(self.aggressivenessSliderPlaceholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.aggressivenessSlider)

    def _selected_polarity(self):
        if self.radioMaterialDark.isChecked():
            return POLARITY_DARK
        if self.radioMaterialLight.isChecked():
            return POLARITY_LIGHT
        return POLARITY_BOTH

    def get_options(self):
        """Translate the wizard answers into algorithm options.

        Returns:
            dict with the service options plus the wizard's own
            'aggressiveness_index' so the slider can be restored exactly.
        """
        index = max(0, min(len(AGGRESSIVENESS_CONFIDENCE) - 1, self.aggressivenessSlider.value()))
        return {
            OPTION_CONFIDENCE: AGGRESSIVENESS_CONFIDENCE[index],
            OPTION_MIN_CHAR_SIZE: DEFAULT_MIN_CHAR_SIZE,
            OPTION_MAX_CHAR_SIZE: DEFAULT_MAX_CHAR_SIZE,
            OPTION_POLARITY: self._selected_polarity(),
            OPTION_SINGLE_CHARACTERS: self.radioSingleYes.isChecked(),
            'aggressiveness_index': index,
        }

    def validate(self):
        """All wizard answers have defaults, so the page is always valid."""
        return None

    def load_options(self, options):
        """Restore the wizard answers from saved options.

        Args:
            options: Options dictionary; values may be strings.
        """
        if not isinstance(options, dict):
            return
        values = coerce_options(options)
        polarity = values[OPTION_POLARITY]
        self.radioMaterialDark.setChecked(polarity == POLARITY_DARK)
        self.radioMaterialLight.setChecked(polarity == POLARITY_LIGHT)
        self.radioMaterialEither.setChecked(polarity == POLARITY_BOTH)
        single = values[OPTION_SINGLE_CHARACTERS]
        self.radioSingleYes.setChecked(single)
        self.radioSingleNo.setChecked(not single)

        try:
            index = int(options['aggressiveness_index'])
        except (KeyError, TypeError, ValueError):
            index = aggressiveness_index_for_confidence(values[OPTION_CONFIDENCE])
        self.aggressivenessSlider.setValue(max(0, min(len(AGGRESSIVENESS_CONFIDENCE) - 1, index)))
