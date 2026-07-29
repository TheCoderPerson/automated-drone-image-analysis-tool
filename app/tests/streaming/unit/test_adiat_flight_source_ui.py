"""UI-surface tests for the ADIAT Flight streaming source.

Requirement coverage: the source must be selectable from *either* the
streaming window's stream controls or the streaming setup guide, and it
must behave like any other first-class source once chosen.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.controllers.streaming.guidePages import (  # noqa: E402
    StreamConnectionPage,
    StreamSourcePage,
)
from core.controllers.streaming.StreamingGuide import StreamingGuide  # noqa: E402
from core.controllers.streaming.shared_widgets import StreamControlWidget  # noqa: E402
from core.services.streaming.RTMPStreamService import (  # noqa: E402
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_HDMI,
    SOURCE_TYPE_RTMP,
    StreamType,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def controls(qtbot):
    widget = StreamControlWidget(include_recording=False)
    qtbot.addWidget(widget)
    return widget


def _select_source(widget, source_type: str) -> None:
    index = widget.type_combo.findData(source_type)
    assert index >= 0, f"{source_type} missing from the stream type combo"
    widget.type_combo.setCurrentIndex(index)


# ----------------------------------------------------------------------
# Streaming window — StreamControlWidget
# ----------------------------------------------------------------------


def test_stream_controls_offer_adiat_flight(controls):
    """ADIAT Flight sits alongside the other sources, keyed by stable data."""
    values = [
        controls.type_combo.itemData(i) for i in range(controls.type_combo.count())
    ]
    assert values == [
        SOURCE_TYPE_FILE,
        SOURCE_TYPE_HDMI,
        SOURCE_TYPE_RTMP,
        SOURCE_TYPE_ADIAT_FLIGHT,
    ]


def test_selecting_adiat_flight_shows_a_readonly_code_display(controls):
    """The code is collected at connect time, not typed here.

    Pairing codes are evicted ~30 s after ADIAT Flight issues them, so the
    field is a display of what we paired with rather than an input.
    """
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)

    assert controls.url_input.isVisibleTo(controls)
    assert controls.url_input.isReadOnly()
    assert not controls.hdmi_device_combo.isVisibleTo(controls)
    assert not controls.browse_button.isVisibleTo(controls)
    assert not controls.scan_button.isVisibleTo(controls)
    assert "connect" in controls.url_input.placeholderText().lower()


def test_switching_away_restores_an_editable_field(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    assert controls.url_input.isReadOnly()

    _select_source(controls, SOURCE_TYPE_RTMP)
    assert not controls.url_input.isReadOnly()


def test_paired_code_is_displayed_once_connected(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    controls.set_paired_code("K7QM3P")
    assert controls.url_input.text() == "K7QM3P"


def test_paired_code_can_be_cleared(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    controls.set_paired_code("K7QM3P")
    controls.set_paired_code("")
    assert controls.url_input.text() == ""


def test_clicking_pairing_field_does_not_open_file_browser(controls):
    """The click-to-browse shortcut is a File-source behaviour only."""
    point = QPointF(1.0, 1.0)
    event = QMouseEvent(
        QEvent.MouseButtonPress,
        point,
        point,
        point,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )

    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    with patch.object(controls, "browse_for_file") as browse:
        controls.on_url_input_clicked(event)
    browse.assert_not_called()

    _select_source(controls, SOURCE_TYPE_FILE)
    with patch.object(controls, "browse_for_file") as browse:
        controls.on_url_input_clicked(event)
    browse.assert_called_once()


def test_connect_asks_for_a_pairing_code(controls):
    """Connect delegates to the owning window's pairing prompt.

    It must not emit connectRequested with a stale/blank code — the code
    is read off the tablet only at this moment.
    """
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)

    connects, prompts = [], []
    controls.connectRequested.connect(lambda *args: connects.append(args))
    controls.pairingRequested.connect(lambda: prompts.append(True))
    controls.request_connect()

    assert prompts == [True]
    assert connects == []


def test_clicking_the_code_field_also_prompts(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    point = QPointF(1.0, 1.0)
    event = QMouseEvent(
        QEvent.MouseButtonPress, point, point, point,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )

    prompts = []
    controls.pairingRequested.connect(lambda: prompts.append(True))
    controls.on_url_input_clicked(event)

    assert prompts == [True]


def test_other_sources_still_connect_unchanged(controls):
    """Regression guard: the shared mapping must not alter File/RTMP."""
    _select_source(controls, SOURCE_TYPE_RTMP)
    controls.url_input.setText("rtmp://host:1935/app/key")

    emitted = []
    controls.connectRequested.connect(lambda *args: emitted.append(args))
    controls.request_connect()

    assert emitted == [("rtmp://host:1935/app/key", StreamType.RTMP, None)]


# ----------------------------------------------------------------------
# Streaming setup guide — source + connection pages
# ----------------------------------------------------------------------


@pytest.fixture
def guide(qtbot):
    wizard = StreamingGuide()
    qtbot.addWidget(wizard)
    return wizard


def test_guide_source_page_offers_adiat_flight(guide):
    source_page = guide.pages[0]
    assert isinstance(source_page, StreamSourcePage)
    assert SOURCE_TYPE_ADIAT_FLIGHT in source_page._source_buttons()
    assert guide.flightButton.isCheckable()


def test_guide_source_selection_records_adiat_flight(guide, qtbot):
    source_page = guide.pages[0]
    guide.flightButton.click()

    assert guide.wizard_data["stream_type"] == SOURCE_TYPE_ADIAT_FLIGHT
    assert source_page._current_stream_type() == SOURCE_TYPE_ADIAT_FLIGHT

    source_page.save_data()
    assert guide.wizard_data["stream_type"] == SOURCE_TYPE_ADIAT_FLIGHT


def test_guide_source_buttons_are_mutually_exclusive(guide):
    guide.flightButton.click()
    assert guide.flightButton.isChecked()
    assert not guide.fileButton.isChecked()

    guide.fileButton.click()
    assert guide.fileButton.isChecked()
    assert not guide.flightButton.isChecked()
    assert guide.wizard_data["stream_type"] == SOURCE_TYPE_FILE


def test_guide_restores_persisted_adiat_flight_selection(guide):
    source_page = guide.pages[0]
    source_page._set_stream_type(SOURCE_TYPE_ADIAT_FLIGHT)
    assert guide.flightButton.isChecked()
    assert source_page._current_stream_type() == SOURCE_TYPE_ADIAT_FLIGHT


def test_guide_does_not_ask_for_a_pairing_code(guide):
    """The code field is hidden entirely for ADIAT Flight.

    Codes are evicted ~30 s after ADIAT Flight issues them, and a pass
    through the remaining wizard pages takes longer than that, so asking
    here would hand the viewer an expired code.
    """
    connection_page = guide.pages[1]
    assert isinstance(connection_page, StreamConnectionPage)

    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    # The guide is never shown in tests, so assert on the explicit
    # hidden flag rather than effective visibility.
    assert guide.streamUrlLineEdit.isHidden()
    assert guide.labelStreamUrl.isHidden()
    assert guide.browseButton.isHidden()
    assert guide.deviceComboBox.isHidden()
    assert guide.scanDevicesButton.isHidden()


def test_guide_explains_when_the_code_is_needed(guide):
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    text = guide.labelConnectionInstructions.text()
    assert "ADIAT Flight" in text
    assert "expire" in text.lower()


def test_guide_page_needs_no_input_for_adiat_flight(guide):
    """Nothing to validate — the operator can always advance."""
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    guide.streamUrlLineEdit.setText("")
    assert connection_page.validate() is True


def test_guide_carries_no_pairing_code_forward(guide):
    """A stale code must never reach the viewer."""
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()
    connection_page.save_data()

    assert guide.wizard_data["stream_url"] == ""


def test_switching_to_flight_clears_a_previous_url(guide):
    """A file path left over from another source is not a pairing code."""
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
    connection_page.on_enter()
    guide.streamUrlLineEdit.setText("C:/videos/flight.mp4")

    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    assert guide.streamUrlLineEdit.text() == ""
    assert guide.wizard_data["stream_url"] == ""


def test_guide_connection_page_leaves_other_sources_alone(guide):
    """File paths must not be run through pairing-code normalization."""
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
    connection_page.on_enter()

    guide.streamUrlLineEdit.setText("C:/videos/flight.mp4")
    connection_page.save_data()

    assert guide.wizard_data["stream_url"].endswith("flight.mp4")
    assert connection_page.validate() is True


class TestFeatureFlagGating:
    """ADIAT Flight ships behind the Flight Viewer flag.

    Both pair over the same WebRTC/signaling stack, so they release
    together. When the flag is off the source must be absent from every
    surface — and unreachable even if a stale setting names it.
    """

    def test_source_is_offered_when_enabled(self, qtbot):
        with patch("helpers.FeatureFlags.FLIGHT_VIEWER_ENABLED", True):
            widget = StreamControlWidget(include_recording=False)
            qtbot.addWidget(widget)
        assert widget.type_combo.findData(SOURCE_TYPE_ADIAT_FLIGHT) >= 0

    def test_source_is_hidden_when_disabled(self, qtbot):
        with patch("helpers.FeatureFlags.FLIGHT_VIEWER_ENABLED", False):
            widget = StreamControlWidget(include_recording=False)
            qtbot.addWidget(widget)

        assert widget.type_combo.findData(SOURCE_TYPE_ADIAT_FLIGHT) == -1
        # The other sources are untouched.
        for source in (SOURCE_TYPE_FILE, SOURCE_TYPE_HDMI, SOURCE_TYPE_RTMP):
            assert widget.type_combo.findData(source) >= 0
        assert "ADIAT Flight" not in widget.type_combo.toolTip()

    def test_wizard_tile_is_hidden_when_disabled(self, qtbot):
        with patch("helpers.FeatureFlags.FLIGHT_VIEWER_ENABLED", False):
            wizard = StreamingGuide()
            qtbot.addWidget(wizard)

            assert wizard.flightButton.isHidden()
            assert SOURCE_TYPE_ADIAT_FLIGHT not in wizard.pages[0]._source_buttons()

    def test_stale_setting_falls_back_to_file_when_disabled(self, qtbot):
        """A persisted "ADIAT Flight" must not select an invisible tile."""
        with patch("helpers.FeatureFlags.FLIGHT_VIEWER_ENABLED", False):
            wizard = StreamingGuide()
            qtbot.addWidget(wizard)
            page = wizard.pages[0]

            page._set_stream_type(SOURCE_TYPE_ADIAT_FLIGHT)

            assert wizard.fileButton.isChecked()
            assert page._current_stream_type() == SOURCE_TYPE_FILE

    def test_coordinator_refuses_webrtc_when_disabled(self, qtbot):
        """Backstop: a direct caller cannot start a pairing session."""
        from core.controllers.streaming.components import StreamCoordinator
        from core.services.streaming.RTMPStreamService import StreamType

        coordinator = StreamCoordinator()
        with patch("helpers.FeatureFlags.FLIGHT_VIEWER_ENABLED", False):
            assert coordinator._create_stream_manager(StreamType.WEBRTC) is None
            # ...and connecting fails quietly rather than via a modal error.
            errors = []
            coordinator.errorOccurred.connect(errors.append)
            assert coordinator.connect_stream("K7QM3P", StreamType.WEBRTC) is False
            assert errors == []
