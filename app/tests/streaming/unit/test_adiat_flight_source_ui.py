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


def test_selecting_adiat_flight_shows_pairing_code_entry(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)

    assert controls.url_input.isVisibleTo(controls)
    assert not controls.hdmi_device_combo.isVisibleTo(controls)
    assert not controls.browse_button.isVisibleTo(controls)
    assert not controls.scan_button.isVisibleTo(controls)
    assert "pairing code" in controls.url_input.placeholderText().lower()


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


def test_connect_emits_webrtc_with_normalized_code(controls):
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    controls.url_input.setText(" k7q-m3p ")

    emitted = []
    controls.connectRequested.connect(
        lambda url, stream_type, backend: emitted.append((url, stream_type, backend))
    )
    controls.request_connect()

    assert emitted == [("K7QM3P", StreamType.WEBRTC, None)]


def test_connect_rejects_malformed_pairing_code(controls):
    """A typo is caught here rather than 30s later in signaling lookup."""
    _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
    controls.url_input.setText("BAD")

    emitted = []
    controls.connectRequested.connect(lambda *args: emitted.append(args))
    with patch(
        "core.controllers.streaming.shared_widgets.QMessageBox.warning"
    ) as warning:
        controls.request_connect()

    assert emitted == []
    warning.assert_called_once()


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


def test_guide_connection_page_prompts_for_pairing_code(guide):
    connection_page = guide.pages[1]
    assert isinstance(connection_page, StreamConnectionPage)

    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    # The guide is never shown in tests, so assert on the explicit
    # hidden flag rather than effective visibility.
    assert "pairing" in guide.labelStreamUrl.text().lower()
    assert not guide.streamUrlLineEdit.isHidden()
    assert guide.browseButton.isHidden()
    assert guide.deviceComboBox.isHidden()
    assert guide.scanDevicesButton.isHidden()
    assert "ADIAT Flight" in guide.labelConnectionInstructions.text()


def test_guide_connection_page_validates_pairing_code(guide):
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    guide.streamUrlLineEdit.setText("")
    assert connection_page.validate() is False

    guide.streamUrlLineEdit.setText("BAD")
    assert connection_page.validate() is False

    # ``I`` is deliberately outside the no-confusables alphabet.
    guide.streamUrlLineEdit.setText("ABCIL0")
    assert connection_page.validate() is False

    guide.streamUrlLineEdit.setText("k7q-m3p")
    assert connection_page.validate() is True


def test_guide_connection_page_stores_normalized_code(guide):
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
    connection_page.on_enter()

    guide.streamUrlLineEdit.setText(" k7q-m3p ")
    connection_page.save_data()

    assert guide.wizard_data["stream_url"] == "K7QM3P"


def test_guide_connection_page_leaves_other_sources_alone(guide):
    """File paths must not be run through pairing-code normalization."""
    connection_page = guide.pages[1]
    guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
    connection_page.on_enter()

    guide.streamUrlLineEdit.setText("C:/videos/flight.mp4")
    connection_page.save_data()

    assert guide.wizard_data["stream_url"].endswith("flight.mp4")
    assert connection_page.validate() is True
