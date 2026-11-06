"""pytest-qt tests for the Ground Message Detector settings and wizard widgets."""

import pytest
from PySide6.QtCore import QPoint, Qt

from algorithms.images.GroundMessage.controllers.GroundMessageController import (
    POLARITY_COMBO_VALUES, GroundMessageController)
from algorithms.images.GroundMessage.controllers.GroundMessageWizardController import (
    AGGRESSIVENESS_CONFIDENCE, GroundMessageWizardController, aggressiveness_index_for_confidence)
from algorithms.images.GroundMessage.services.GroundMessageService import (
    DEFAULT_MAX_CHAR_SIZE, DEFAULT_MIN_CHAR_SIZE, OPTION_CONFIDENCE, OPTION_MAX_CHAR_SIZE, OPTION_MIN_CHAR_SIZE,
    OPTION_POLARITY, OPTION_SINGLE_CHARACTERS, POLARITY_BOTH, POLARITY_DARK, POLARITY_LIGHT,
    GroundMessageService)

CONFIG = {
    'name': 'GroundMessage',
    'label': 'Ground Message Detector',
    'controller': 'GroundMessageController',
    'wizard_controller': 'GroundMessageWizardController',
    'service': 'GroundMessageService',
    'type': 'RGB',
}


def click(qtbot, button):
    """Click a check/radio button on its indicator.

    The widget may stretch across the layout, so its centre can fall outside
    the clickable indicator-and-label area.
    """
    qtbot.mouseClick(button, Qt.LeftButton, pos=QPoint(8, button.height() // 2))


@pytest.fixture
def controller(qtbot):
    widget = GroundMessageController(CONFIG, 'Dark')
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.fixture
def wizard(qtbot):
    widget = GroundMessageWizardController(CONFIG, 'Dark')
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


# --------------------------------------------------------------- controller

def test_controller_defaults_build_a_valid_service(controller):
    options = controller.get_options()
    assert options == {
        OPTION_CONFIDENCE: 50,
        OPTION_MIN_CHAR_SIZE: DEFAULT_MIN_CHAR_SIZE,
        OPTION_MAX_CHAR_SIZE: DEFAULT_MAX_CHAR_SIZE,
        OPTION_POLARITY: POLARITY_BOTH,
        OPTION_SINGLE_CHARACTERS: True,
    }
    assert controller.validate() is None
    assert controller.is_thermal is False
    GroundMessageService((255, 0, 0), 10, 0, 10, True, options)


def test_slider_updates_value_label(controller, qtbot):
    controller.confidenceSlider.setFocus()
    qtbot.keyClick(controller.confidenceSlider, Qt.Key_Right)
    assert controller.confidenceValueLabel.text() == str(controller.confidenceSlider.value())
    controller.confidenceSlider.setValue(72)
    assert controller.confidenceValueLabel.text() == '72'
    assert controller.get_options()[OPTION_CONFIDENCE] == 72


def test_validate_rejects_inverted_size_range(controller):
    controller.minCharSizeSpinBox.setValue(700)
    controller.maxCharSizeSpinBox.setValue(300)
    message = controller.validate()
    assert message and 'character size' in message


def test_polarity_uses_stable_values_not_display_text(controller):
    controller.polarityComboBox.setItemText(1, 'Mas oscuro que el suelo')  # e.g. translated
    controller.polarityComboBox.setCurrentIndex(1)
    assert controller.get_options()[OPTION_POLARITY] == POLARITY_DARK
    assert [controller.polarityComboBox.itemData(i) for i in range(3)] == list(POLARITY_COMBO_VALUES)


def test_single_character_checkbox_click(controller, qtbot):
    click(qtbot, controller.singleCharactersCheckBox)
    assert controller.get_options()[OPTION_SINGLE_CHARACTERS] is False


def test_controller_round_trips_options(controller, qtbot):
    saved = {OPTION_CONFIDENCE: 64, OPTION_MIN_CHAR_SIZE: 70, OPTION_MAX_CHAR_SIZE: 900,
             OPTION_POLARITY: POLARITY_LIGHT, OPTION_SINGLE_CHARACTERS: False}
    controller.load_options(saved)
    assert controller.get_options() == saved
    assert controller.confidenceValueLabel.text() == '64'


def test_controller_loads_options_saved_as_xml_text(controller):
    controller.load_options({OPTION_CONFIDENCE: '42.0', OPTION_MIN_CHAR_SIZE: '30', OPTION_MAX_CHAR_SIZE: '450',
                             OPTION_POLARITY: 'dark', OPTION_SINGLE_CHARACTERS: 'False'})
    options = controller.get_options()
    assert options[OPTION_CONFIDENCE] == 42
    assert (options[OPTION_MIN_CHAR_SIZE], options[OPTION_MAX_CHAR_SIZE]) == (30, 450)
    assert options[OPTION_POLARITY] == POLARITY_DARK
    assert options[OPTION_SINGLE_CHARACTERS] is False


def test_controller_ignores_unreadable_saved_values(controller):
    controller.load_options({OPTION_CONFIDENCE: 'n/a', OPTION_POLARITY: 'sideways'})
    options = controller.get_options()
    assert options[OPTION_CONFIDENCE] == 50
    assert options[OPTION_POLARITY] == POLARITY_BOTH
    controller.load_options(None)  # not a dict: no-op


def test_controller_accepts_wizard_options(controller, wizard):
    wizard.radioMaterialLight.setChecked(True)
    wizard.aggressivenessSlider.setValue(0)
    controller.load_options(wizard.get_options())
    options = controller.get_options()
    assert options[OPTION_POLARITY] == POLARITY_LIGHT
    assert options[OPTION_CONFIDENCE] == AGGRESSIVENESS_CONFIDENCE[0]


# ------------------------------------------------------------------- wizard

def test_wizard_defaults(wizard):
    options = wizard.get_options()
    assert options[OPTION_CONFIDENCE] == 50
    assert options[OPTION_POLARITY] == POLARITY_BOTH
    assert options[OPTION_SINGLE_CHARACTERS] is True
    assert options[OPTION_MIN_CHAR_SIZE] == DEFAULT_MIN_CHAR_SIZE
    assert options[OPTION_MAX_CHAR_SIZE] == DEFAULT_MAX_CHAR_SIZE
    assert wizard.validate() is None
    GroundMessageService((255, 0, 0), 10, 0, 10, True, options)


@pytest.mark.parametrize('radio, polarity', [
    ('radioMaterialDark', POLARITY_DARK),
    ('radioMaterialLight', POLARITY_LIGHT),
    ('radioMaterialEither', POLARITY_BOTH),
])
def test_wizard_material_answer_sets_polarity(wizard, qtbot, radio, polarity):
    click(qtbot, getattr(wizard, radio))
    assert wizard.get_options()[OPTION_POLARITY] == polarity


def test_wizard_single_symbol_answer(wizard, qtbot):
    click(qtbot, wizard.radioSingleNo)
    assert wizard.get_options()[OPTION_SINGLE_CHARACTERS] is False
    click(qtbot, wizard.radioSingleYes)
    assert wizard.get_options()[OPTION_SINGLE_CHARACTERS] is True


def test_wizard_aggressiveness_lowers_threshold(wizard):
    thresholds = []
    for index in range(len(AGGRESSIVENESS_CONFIDENCE)):
        wizard.aggressivenessSlider.setValue(index)
        thresholds.append(wizard.get_options()[OPTION_CONFIDENCE])
    assert thresholds == sorted(thresholds, reverse=True)
    assert len(set(thresholds)) == len(thresholds)


def test_wizard_round_trip(wizard, qtbot):
    wizard.radioMaterialDark.setChecked(True)
    wizard.radioSingleNo.setChecked(True)
    wizard.aggressivenessSlider.setValue(3)
    saved = wizard.get_options()
    restored = GroundMessageWizardController(CONFIG, 'Dark')
    qtbot.addWidget(restored)
    restored.load_options(saved)
    assert restored.get_options() == saved


def test_wizard_restores_aggressiveness_from_threshold_alone(wizard):
    """Options saved by the main window carry a threshold but no slider index."""
    wizard.load_options({OPTION_CONFIDENCE: '61'})
    assert wizard.aggressivenessSlider.value() == 1
    assert wizard.get_options()[OPTION_CONFIDENCE] == AGGRESSIVENESS_CONFIDENCE[1]


@pytest.mark.parametrize('confidence, index', [(90, 0), (70, 0), (55, 1), (50, 2), (44, 3), (10, 4)])
def test_aggressiveness_index_for_confidence(confidence, index):
    assert aggressiveness_index_for_confidence(confidence) == index
