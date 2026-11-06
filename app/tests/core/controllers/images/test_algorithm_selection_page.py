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


def test_non_thermal_branch_asks_about_ground_messages_after_people():
    page, _, dialog = _create_page()

    page._on_algorithm_answer(False)  # Not thermal
    page._on_algorithm_answer(False)  # Not only people

    assert page.selected_algorithm is None
    assert "message laid out on the ground" in dialog.labelCurrentQuestion.text()


def test_ground_message_branch_selects_ground_message_detector():
    page, wizard_data, dialog = _create_page()

    page._on_algorithm_answer(False)  # Not thermal
    page._on_algorithm_answer(False)  # Not only people
    page._on_algorithm_answer(True)   # Looking for a ground message

    assert page.selected_algorithm == "Ground Message Detector"
    assert wizard_data.get('algorithm') == "Ground Message Detector"
    assert dialog.labelAlgorithmResult.visible


def test_declining_ground_message_continues_to_color_questions():
    page, wizard_data, dialog = _create_page()

    page._on_algorithm_answer(False)  # Not thermal
    page._on_algorithm_answer(False)  # Not only people
    page._on_algorithm_answer(False)  # Not a ground message
    assert "specific color" in dialog.labelCurrentQuestion.text()

    page._on_algorithm_answer(False)  # No specific color
    page._on_algorithm_answer(True)   # Complex backgrounds

    assert page.selected_algorithm == "MRMap"
    assert wizard_data.get('algorithm') == "MRMap"


def test_reset_clears_ground_message_answer():
    page, _, _ = _create_page()

    page._on_algorithm_answer(False)
    page._on_algorithm_answer(False)
    page._on_algorithm_answer(True)
    page._reset_algorithm_selection()

    assert page.algorithm_decision_state['ground_message'] is None
    assert page.selected_algorithm is None
