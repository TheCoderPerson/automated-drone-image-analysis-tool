"""The record toggle on a Flight Viewer tile, and the HUD's flight mode.

Recording used to be reachable only from the tile's right-click menu,
which buried the one action an operator reaches for mid-flight. The
toggle now sits on the status strip, sharing its look with the streaming
window's playback bar.
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.views.flight.FlightTile import FlightTile  # noqa: E402
from core.views.flight.TelemetryHud import TelemetryHud  # noqa: E402
from core.views.streaming.components.RecordButton import (  # noqa: E402
    configure_record_button,
    set_record_button_state,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tile(qapp):
    widget = FlightTile(pairing_code="K3F9PM")
    yield widget
    widget.deleteLater()


def _centroid(button):
    """Centre of mass of the painted glyph, in icon pixels."""
    image = button.icon().pixmap(button.iconSize()).toImage()
    xs = ys = count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 40:
                xs += x
                ys += y
                count += 1
    assert count, "the glyph painted nothing"
    return xs / count, ys / count, image.width()


class TestSharedRecordButton:
    """One look wherever recording is offered."""

    def test_configure_produces_a_centred_idle_dot(self, qapp):
        button = QPushButton()
        configure_record_button(button)

        assert button.text() == ""            # painted, not a font glyph
        assert button.icon().isNull() is False
        x, y, width = _centroid(button)
        assert abs(x - (width - 1) / 2) < 0.01
        assert abs(y - (width - 1) / 2) < 0.01

    def test_recording_state_is_centred_too(self, qapp):
        button = QPushButton()
        configure_record_button(button)
        set_record_button_state(button, True)

        x, y, width = _centroid(button)
        assert abs(x - (width - 1) / 2) < 0.01
        assert abs(y - (width - 1) / 2) < 0.01
        assert "e53935" in button.styleSheet()

    def test_a_cramped_host_can_size_it_down(self, qapp):
        """The tile's status strip is tighter than the playback bar."""
        button = QPushButton()
        configure_record_button(button, size=24)

        assert button.width() == button.height() == 24
        # The glyph keeps its proportions and its centring.
        x, y, width = _centroid(button)
        assert abs(x - (width - 1) / 2) < 0.01

    def test_the_toggle_is_never_disabled(self, qapp):
        """A disabled button hands focus away mid-press."""
        button = QPushButton()
        configure_record_button(button)
        for recording in (True, False, True):
            set_record_button_state(button, recording)
            assert button.isEnabled() is True


class TestTileRecordButton:
    def test_the_strip_carries_a_record_button(self, tile):
        button = tile.ui.recordButton
        assert button.icon().isNull() is False
        assert button.width() == button.height() == 24
        assert tile.is_recording is False

    def test_click_requests_start_then_stop(self, tile):
        """One button, two meanings - the controller owns what happens."""
        events = []
        tile.recordingStartRequested.connect(lambda t: events.append("start"))
        tile.recordingStopRequested.connect(lambda t: events.append("stop"))

        tile.ui.recordButton.click()
        assert events == ["start"]

        # The controller reports back; the button becomes Stop.
        tile.set_recording_state(True, "REC ● flight.mp4")
        tile.ui.recordButton.click()

        assert events == ["start", "stop"]

    def test_state_changes_flip_the_glyph(self, tile):
        button = tile.ui.recordButton

        tile.set_recording_state(True, "REC")
        assert "e53935" in button.styleSheet()

        tile.set_recording_state(False)
        assert "transparent" in button.styleSheet()

    def test_a_finished_recording_returns_the_button_to_idle(self, tile):
        tile.set_recording_state(True, "REC")

        tile.set_recording_result("Recording saved", "C:/bundles/rec")

        assert tile.is_recording is False
        assert "transparent" in tile.ui.recordButton.styleSheet()

    def test_the_context_menu_entry_still_exists(self, tile):
        """The strip button is an addition, not a replacement."""
        assert hasattr(tile, "_on_context_menu")
        assert tile.recordingStartRequested is not None


class TestFlightModeReadout:
    """Field report: "Unknown" beside BAT read as a battery value."""

    @pytest.fixture
    def hud(self, qapp):
        widget = TelemetryHud()
        yield widget
        widget.deleteLater()

    def test_the_mode_is_captioned(self, hud):
        """Unlabelled, it read as part of the battery chip beside it."""
        assert hud.flightModeCaption.text() == "MODE"

    @pytest.mark.parametrize(
        "placeholder", ["Unknown", "unknown", "UNKNOWN", "none", "N/A", "na", "-", "--", ""]
    )
    def test_placeholder_modes_render_as_absent(self, hud, placeholder):
        """The publisher's "I don't know" is not data to display."""
        hud._render_flight_mode(None, placeholder)

        assert hud.flightModeLabel.text() == "—"

    def test_a_real_mode_is_shown(self, hud):
        hud._render_flight_mode(None, "GPS_ATTI")

        assert hud.flightModeLabel.text() == "GPS_ATTI"

    def test_flying_shows_with_the_mode(self, hud):
        hud._render_flight_mode(True, "GPS_ATTI")

        assert hud.flightModeLabel.text() == "FLY · GPS_ATTI"

    def test_flying_with_an_unknown_mode_still_shows_flying(self, hud):
        hud._render_flight_mode(True, "Unknown")

        assert hud.flightModeLabel.text() == "FLY"

    def test_a_non_string_mode_is_absent(self, hud):
        hud._render_flight_mode(None, 42)

        assert hud.flightModeLabel.text() == "—"
