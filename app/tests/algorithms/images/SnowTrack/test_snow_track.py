"""pytest-qt tests for the SnowTrack panel and wizard controllers."""

import pytest
from PySide6.QtCore import Qt

from algorithms.images.SnowTrack.controllers.SnowTrackController import SnowTrackController
from algorithms.images.SnowTrack.controllers.SnowTrackWizardController import (
    AGGRESSIVENESS_PRESETS,
    DEFAULT_AGGRESSIVENESS,
    SnowTrackWizardController,
)
from algorithms.images.SnowTrack.services.SnowTrackOptions import (
    DEFAULT_OPTIONS,
    GSD_MODE_AUTO,
    GSD_MODE_MANUAL,
    TRACK_PRESETS,
    TRACK_TYPE_BOOT,
    TRACK_TYPE_POSTHOLE,
    SnowTrackParams,
)

SERVICE_KEYS = tuple(DEFAULT_OPTIONS)


def _config():
    return {
        'name': 'SnowTrack',
        'label': 'Snow Footprint Tracks',
        'controller': 'SnowTrackController',
        'wizard_controller': 'SnowTrackWizardController',
        'service': 'SnowTrackService',
        'combine_overlapping_aois': False,
        'platforms': ['Windows', 'Darwin'],
        'type': 'RGB',
    }


@pytest.fixture
def panel(app, qtbot):
    widget = SnowTrackController(_config(), 'Dark')
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def wizard(app, qtbot):
    widget = SnowTrackWizardController(_config(), 'Dark')
    qtbot.addWidget(widget)
    return widget


def _normalized(options):
    """Service view of an options dict (what the algorithm would actually run with)."""
    return SnowTrackParams.from_options(options)


# ------------------------------------------------------------------ panel


def test_panel_starts_at_the_service_defaults(panel):
    assert not panel.is_thermal
    assert _normalized(panel.get_options()) == _normalized(DEFAULT_OPTIONS)
    assert set(panel.get_options()) == set(SERVICE_KEYS)


def test_panel_round_trips_custom_options(app, qtbot, panel):
    custom = {
        'gsd_mode': GSD_MODE_MANUAL,
        'gsd_cm': 11.5,
        'print_diameter_cm': 22.0,
        'step_min_cm': 45.0,
        'step_max_cm': 110.0,
        'max_trail_width_cm': 35.0,
        'min_prints': 9,
        'max_step_variation': 25,
        'sensitivity': 8,
    }
    panel.load_options(custom)

    assert panel.get_options() == custom
    restored = SnowTrackController(_config(), 'Dark')
    qtbot.addWidget(restored)
    restored.load_options(panel.get_options())
    assert restored.get_options() == custom


def test_gsd_mode_uses_stable_item_data_not_display_text(panel):
    # Display text is translatable; the stored value must not depend on it
    panel.gsdModeComboBox.setItemText(1, "Valeur fixe")
    panel.gsdModeComboBox.setCurrentIndex(1)

    assert panel.get_options()['gsd_mode'] == GSD_MODE_MANUAL
    panel.gsdModeComboBox.setCurrentIndex(0)
    assert panel.get_options()['gsd_mode'] == GSD_MODE_AUTO


def test_gsd_label_names_the_value_by_its_role(panel):
    panel.gsdModeComboBox.setCurrentIndex(panel.gsdModeComboBox.findData(GSD_MODE_AUTO))
    auto_text = panel.gsdValueLabel.text()
    panel.gsdModeComboBox.setCurrentIndex(panel.gsdModeComboBox.findData(GSD_MODE_MANUAL))

    assert 'Fallback' in auto_text
    assert 'Fixed' in panel.gsdValueLabel.text()


def test_sensitivity_slider_updates_its_label(qtbot, panel):
    panel.sensitivitySlider.setFocus()
    qtbot.keyClick(panel.sensitivitySlider, Qt.Key_Right)

    assert panel.sensitivityValueLabel.text() == str(DEFAULT_OPTIONS['sensitivity'] + 1)
    assert panel.get_options()['sensitivity'] == DEFAULT_OPTIONS['sensitivity'] + 1


def test_panel_loads_partial_legacy_and_malformed_options(panel):
    panel.load_options({'sensitivity': 9})
    assert panel.get_options()['sensitivity'] == 9
    assert panel.get_options()['print_diameter_cm'] == DEFAULT_OPTIONS['print_diameter_cm']

    panel.load_options({'gsd_mode': 'bogus', 'min_prints': 'many', 'gsd_cm': 1e9})
    options = panel.get_options()
    assert options['gsd_mode'] == DEFAULT_OPTIONS['gsd_mode']
    assert options['min_prints'] == DEFAULT_OPTIONS['min_prints']
    assert options['gsd_cm'] == 50.0

    before = panel.get_options()
    panel.load_options(None)
    assert panel.get_options() == before


def test_panel_validation(panel):
    assert panel.validate() is None

    panel.stepMinSpinBox.setValue(80)
    panel.stepMaxSpinBox.setValue(80)
    assert 'step length' in panel.validate()

    panel.stepMaxSpinBox.setValue(120)
    panel.printDiameterSpinBox.setValue(80)
    assert 'print diameter' in panel.validate()

    panel.printDiameterSpinBox.setValue(30)
    assert panel.validate() is None


# ----------------------------------------------------------------- wizard


def test_wizard_defaults_match_the_service_defaults(wizard):
    options = wizard.get_options()

    assert wizard.aggressivenessSlider.value() == DEFAULT_AGGRESSIVENESS
    assert _normalized(options) == _normalized(DEFAULT_OPTIONS)
    assert options['track_type'] == TRACK_TYPE_POSTHOLE
    assert wizard.validate() is None


def test_more_aggressive_presets_accept_fainter_prints_and_shorter_trails():
    sensitivities = [s for s, _ in AGGRESSIVENESS_PRESETS]
    min_prints = [m for _, m in AGGRESSIVENESS_PRESETS]

    assert sensitivities == sorted(sensitivities) and len(set(sensitivities)) == len(sensitivities)
    assert min_prints == sorted(min_prints, reverse=True)


def test_wizard_track_type_selects_the_preset_geometry(qtbot, wizard):
    qtbot.mouseClick(wizard.radioBoot, Qt.LeftButton)
    boot = wizard.get_options()
    qtbot.mouseClick(wizard.radioPosthole, Qt.LeftButton)
    posthole = wizard.get_options()

    for key, value in TRACK_PRESETS[TRACK_TYPE_BOOT].items():
        assert boot[key] == value
    for key, value in TRACK_PRESETS[TRACK_TYPE_POSTHOLE].items():
        assert posthole[key] == value


def test_wizard_gsd_choice(qtbot, wizard):
    qtbot.mouseClick(wizard.radioGsdManual, Qt.LeftButton)
    wizard.gsdSpinBox.setValue(10.5)

    options = wizard.get_options()

    assert options['gsd_mode'] == GSD_MODE_MANUAL
    assert options['gsd_cm'] == 10.5


@pytest.mark.parametrize('track_type', [TRACK_TYPE_POSTHOLE, TRACK_TYPE_BOOT])
@pytest.mark.parametrize('index', range(len(AGGRESSIVENESS_PRESETS)))
@pytest.mark.parametrize('gsd_mode', [GSD_MODE_AUTO, GSD_MODE_MANUAL])
def test_wizard_answers_round_trip(app, qtbot, track_type, index, gsd_mode):
    source = SnowTrackWizardController(_config(), 'Dark')
    qtbot.addWidget(source)
    (source.radioBoot if track_type == TRACK_TYPE_BOOT else source.radioPosthole).setChecked(True)
    (source.radioGsdManual if gsd_mode == GSD_MODE_MANUAL else source.radioGsdAuto).setChecked(True)
    source.gsdSpinBox.setValue(6.5)
    source.aggressivenessSlider.setValue(index)

    target = SnowTrackWizardController(_config(), 'Dark')
    qtbot.addWidget(target)
    target.load_options(source.get_options())

    assert target.get_options() == source.get_options()


def test_wizard_restores_from_panel_options_without_wizard_answers(wizard):
    """Options saved from the main-window panel carry no track_type/aggressiveness_index."""
    options = dict(DEFAULT_OPTIONS, **TRACK_PRESETS[TRACK_TYPE_BOOT])
    options.update(sensitivity=8, gsd_mode=GSD_MODE_MANUAL, gsd_cm=7.0)

    wizard.load_options(options)

    assert wizard.radioBoot.isChecked()
    assert wizard.radioGsdManual.isChecked()
    assert wizard.gsdSpinBox.value() == 7.0
    # Sensitivity 8 sits between Aggressive (7) and Very Aggressive (9): the tie goes conservative
    assert wizard.aggressivenessSlider.value() == 3


def test_wizard_ignores_invalid_saved_answers(wizard):
    wizard.load_options({'track_type': 'skis', 'aggressiveness_index': True, 'print_diameter_cm': 30})

    assert wizard.radioPosthole.isChecked()
    assert wizard.aggressivenessSlider.value() == DEFAULT_AGGRESSIVENESS

    wizard.load_options('garbage')
    assert wizard.radioPosthole.isChecked()


def test_wizard_options_hand_off_to_the_main_window_panel(qtbot, wizard, panel):
    """The guide passes its options to the main-window panel, which must run the same detection."""
    qtbot.mouseClick(wizard.radioBoot, Qt.LeftButton)
    qtbot.mouseClick(wizard.radioGsdManual, Qt.LeftButton)
    wizard.gsdSpinBox.setValue(9.5)
    wizard.aggressivenessSlider.setValue(4)
    wizard_options = wizard.get_options()

    panel.load_options(wizard_options)

    assert _normalized(panel.get_options()) == _normalized(wizard_options)


# ------------------------------------------------------------ discovery


def test_controllers_are_discoverable_by_the_app():
    """MainWindow and the guide resolve controllers by class name from their module globals."""
    import importlib

    parameters_page = importlib.import_module('core.controllers.images.guidePages.AlgorithmParametersPage')
    main_window = importlib.import_module('core.controllers.images.MainWindow')

    assert vars(parameters_page)['SnowTrackWizardController'] is SnowTrackWizardController
    assert vars(parameters_page)['SnowTrackController'] is SnowTrackController
    assert vars(main_window)['SnowTrackController'] is SnowTrackController
