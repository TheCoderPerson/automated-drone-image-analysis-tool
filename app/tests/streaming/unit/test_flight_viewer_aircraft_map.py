"""Flight Viewer: aircraft marker + flight path on the shared map dock.

The dock previously only pinned detections. These tests cover the
extension — live telemetry drives a per-feed aircraft marker and trail —
including the multi-tile case where two drones share one map.
"""

import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from core.controllers.flight.FlightTileController import FlightTileController
from core.services.streaming.signaling import InMemorySignalingChannel


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def envelope(lat=30.5, lon=-97.7, agl=40.0):
    return {
        "aircraft_latitude": lat,
        "aircraft_longitude": lon,
        "aircraft_altitude_msl_m": 210.0,
        "aircraft_altitude_agl_m": agl,
        "captured_at_ms": 1000,
    }


class TestTileControllerTelemetry:
    @pytest.fixture
    def controller(self):
        ctrl = FlightTileController(signaling=InMemorySignalingChannel())
        ctrl._pairing_code = "ABC234"
        # Neutralise DEM enrichment; it has its own suite and would start a
        # worker thread that reaches a live TerrainService.
        enrichment = MagicMock()
        enrichment.enrich.side_effect = lambda env: env
        ctrl._telemetry_enrichment = enrichment
        yield ctrl

    def test_envelope_is_forwarded_with_the_feed_id(self, controller):
        received = []
        controller.telemetryReceived.connect(
            lambda code, env: received.append((code, env))
        )
        controller._on_telemetry_envelope(envelope())

        assert len(received) == 1
        assert received[0][0] == "ABC234"
        assert received[0][1]["aircraft_latitude"] == 30.5

    def test_envelope_passes_through_enrichment(self, controller):
        controller._on_telemetry_envelope(envelope())
        controller._telemetry_enrichment.enrich.assert_called_once()

    def test_envelope_reaches_the_tile_hud(self, controller):
        tile = MagicMock()
        controller._tile = tile
        controller._on_telemetry_envelope(envelope())
        tile.apply_telemetry.assert_called_once()

    def test_hud_failure_does_not_break_the_feed(self, controller):
        tile = MagicMock()
        tile.apply_telemetry.side_effect = RuntimeError("hud exploded")
        controller._tile = tile

        received = []
        controller.telemetryReceived.connect(
            lambda code, env: received.append(env)
        )
        controller._on_telemetry_envelope(envelope())
        assert len(received) == 1

    def test_enrichment_failure_falls_back_to_the_raw_envelope(self, controller):
        controller._telemetry_enrichment.enrich.side_effect = RuntimeError("dem down")
        received = []
        controller.telemetryReceived.connect(
            lambda code, env: received.append(env)
        )
        controller._on_telemetry_envelope(envelope())
        assert received[0]["aircraft_latitude"] == 30.5

    def test_non_dict_is_ignored(self, controller):
        received = []
        controller.telemetryReceived.connect(
            lambda code, env: received.append(env)
        )
        controller._on_telemetry_envelope("nope")
        assert received == []

    def test_no_emit_without_a_pairing_code(self, controller):
        controller._pairing_code = None
        received = []
        controller.telemetryReceived.connect(
            lambda code, env: received.append(env)
        )
        controller._on_telemetry_envelope(envelope())
        assert received == []


class TestViewerMapWiring:
    """``FlightViewerController`` routes telemetry into the map dock."""

    @pytest.fixture
    def viewer(self):
        with patch("core.controllers.flight.FlightViewerController."
                   "FlightViewerWindow") as window_cls:
            from core.controllers.flight.FlightViewerController import (
                FlightViewerController,
            )
            window = MagicMock()
            window_cls.return_value = window
            controller = FlightViewerController(
                signaling=InMemorySignalingChannel()
            )
            controller.window = window
            yield controller

    def test_telemetry_moves_the_aircraft_for_its_feed(self, viewer):
        viewer.window.map_dock.update_aircraft.return_value = True
        viewer._on_telemetry_for_map("ABC234", envelope())

        viewer.window.map_dock.update_aircraft.assert_called_once()
        kwargs = viewer.window.map_dock.update_aircraft.call_args.kwargs
        assert kwargs["feed_id"] == "ABC234"

    def test_display_name_is_used_as_the_label(self, viewer):
        viewer.window.map_dock.update_aircraft.return_value = True
        viewer._remember_feed_display_name("ABC234", "Mavic 3T")
        viewer._on_telemetry_for_map("ABC234", envelope())

        kwargs = viewer.window.map_dock.update_aircraft.call_args.kwargs
        assert kwargs["label"] == "Mavic 3T"

    def test_falls_back_to_the_pairing_code(self, viewer):
        viewer.window.map_dock.update_aircraft.return_value = True
        viewer._on_telemetry_for_map("ABC234", envelope())
        kwargs = viewer.window.map_dock.update_aircraft.call_args.kwargs
        assert kwargs["label"] == "ABC234"

    def test_dock_is_revealed_on_the_first_fix(self, viewer):
        viewer.window.map_dock.update_aircraft.return_value = True
        viewer.window.map_dock.isVisible.return_value = False
        viewer._on_telemetry_for_map("ABC234", envelope())
        viewer.window.show_map_dock.assert_called_once()

    def test_dock_is_not_revealed_without_a_position(self, viewer):
        viewer.window.map_dock.update_aircraft.return_value = False
        viewer.window.map_dock.isVisible.return_value = False
        viewer._on_telemetry_for_map("ABC234", {"captured_at_ms": 1})
        viewer.window.show_map_dock.assert_not_called()

    def test_non_dict_is_ignored(self, viewer):
        viewer._on_telemetry_for_map("ABC234", None)
        viewer.window.map_dock.update_aircraft.assert_not_called()

    def test_closing_a_tile_retires_its_aircraft(self, viewer):
        """Detection pins stay; the aircraft and its trail go."""
        viewer._feed_display_names["ABC234"] = "Mavic"
        viewer._on_tile_closed("ABC234")

        viewer.window.map_dock.clear_aircraft.assert_called_once_with("ABC234")
        viewer.window.map_dock.clear_track.assert_called_once_with("ABC234")
        assert "ABC234" not in viewer._feed_display_names


class TestMultiFeedIsolation:
    def test_two_feeds_keep_separate_trails(self, qtbot):
        """A shared dock must not merge two drones into one path."""
        from core.views.flight.MapDock import MapDock

        dock = MapDock()
        qtbot.addWidget(dock)
        dock.map_view._run_js = lambda js: None

        dock.update_aircraft(envelope(30.0, -97.0), feed_id="A")
        dock.update_aircraft(envelope(31.0, -98.0), feed_id="B")
        dock.update_aircraft(envelope(30.1, -97.1), feed_id="A")

        assert dock.track_length("A") == 2
        assert dock.track_length("B") == 1
