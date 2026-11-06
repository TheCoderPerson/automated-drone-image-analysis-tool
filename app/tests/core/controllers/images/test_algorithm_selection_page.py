from unittest.mock import MagicMock

from core.controllers.images.guidePages.AlgorithmSelectionPage import AlgorithmSelectionPage


class _DummyWidget:
    def __init__(self):
        self.visible = True
        self.style = ""

    def setVisible(self, visible):
        self.visible = visible

    def setStyleSheet(self, style):
        self.style = style


class _DummyLabel(_DummyWidget):
    def __init__(self):
        super().__init__()
        self._text = ""

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class _DummyDialog:
    def __init__(self):
        self.labelCurrentQuestion = _DummyLabel()
        self.labelAlgorithmResult = _DummyLabel()
        self.buttonYes = _DummyWidget()
        self.buttonNo = _DummyWidget()
        self.resetAlgorithmButton = _DummyWidget()


def _create_page():
    wizard_data = {}
    settings_service = MagicMock()
    dialog = _DummyDialog()
    page = AlgorithmSelectionPage(wizard_data, settings_service, dialog)
    page.setup_ui()
    return page, wizard_data, dialog


def test_thermal_anomaly_branch_prompts_for_detector_choice():
    page, _, dialog = _create_page()

    page._on_algorithm_answer(True)   # Thermal imagery
    page._on_algorithm_answer(False)  # Not temperature range

    assert page.selected_algorithm is None
    assert "local surroundings" in dialog.labelCurrentQuestion.text().lower()


def test_thermal_anomaly_branch_can_select_residual_detector():
    page, wizard_data, _ = _create_page()

    page._on_algorithm_answer(True)   # Thermal imagery
    page._on_algorithm_answer(False)  # Not temperature range
    page._on_algorithm_answer(True)   # Use local residual detector

    assert page.selected_algorithm == "Temperature Residual Anomaly"
    assert wizard_data.get('algorithm') == "Temperature Residual Anomaly"


def test_thermal_anomaly_branch_can_select_standard_detector():
    page, wizard_data, _ = _create_page()

    page._on_algorithm_answer(True)   # Thermal imagery
    page._on_algorithm_answer(False)  # Not temperature range
    page._on_algorithm_answer(False)  # Use standard detector

    assert page.selected_algorithm == "Temperature Anomaly"
    assert wizard_data.get('algorithm') == "Temperature Anomaly"


def _answer_people_question(page, wants_people):
    if page.algorithm_decision_state['thermal'] is None:
        page._on_algorithm_answer(False)  # Not thermal (auto-answered on macOS)
    page._on_algorithm_answer(wants_people)


def test_people_branch_asks_about_foot_tracks():
    page, _, dialog = _create_page()

    _answer_people_question(page, True)

    assert page.selected_algorithm is None
    assert "foot tracks in snow" in dialog.labelCurrentQuestion.text()


def test_people_branch_can_select_snow_footprint_tracks():
    page, wizard_data, _ = _create_page()

    _answer_people_question(page, True)
    page._on_algorithm_answer(True)  # Foot tracks in snow

    assert page.selected_algorithm == "Snow Footprint Tracks"
    assert wizard_data.get('algorithm') == "Snow Footprint Tracks"


def test_people_branch_can_select_ai_person_detector():
    page, wizard_data, _ = _create_page()

    _answer_people_question(page, True)
    page._on_algorithm_answer(False)  # The people themselves

    assert page.selected_algorithm == "AI Person Detector"
    assert wizard_data.get('algorithm') == "AI Person Detector"


def test_anomaly_branch_is_unaffected_by_the_snow_track_question():
    page, _, _ = _create_page()

    _answer_people_question(page, False)
    page._on_algorithm_answer(False)  # No specific color
    page._on_algorithm_answer(True)   # Complex backgrounds

    assert page.selected_algorithm == "MRMap"


def test_reset_clears_the_snow_track_answer():
    page, _, _ = _create_page()
    _answer_people_question(page, True)
    page._on_algorithm_answer(True)

    page._reset_algorithm_selection()

    assert page.selected_algorithm is None
    assert page.algorithm_decision_state['snow_tracks'] is None


def test_every_selectable_algorithm_label_exists_in_the_registry():
    """The guide selects algorithms by label; a typo would silently select nothing."""
    import json
    import os
    import re
    import importlib
    import inspect

    module = importlib.import_module('core.controllers.images.guidePages.AlgorithmSelectionPage')

    source = inspect.getsource(module)
    selectable = set(re.findall(r'self\.selected_algorithm = "([^"]+)"', source))
    conf_path = os.path.join(os.path.dirname(module.__file__), '..', '..', '..', '..', 'algorithms.conf')
    with open(conf_path, encoding='utf-8') as handle:
        labels = {a['label'] for a in json.load(handle)['algorithms']}

    assert "Snow Footprint Tracks" in selectable
    assert selectable <= labels, selectable - labels
