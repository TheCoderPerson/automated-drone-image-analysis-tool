"""Unit tests for the standalone flight-map page written into a recording bundle."""

import os
import re

from core.services.export.FlightMapHtmlService import (
    build_flight_map_html,
    pin_color_for,
    write_flight_map_html,
)
from core.views.components.FlightMapView import DEFAULT_PIN_COLOR, DETECTOR_PALETTE

PATH = [(30.0, -97.0), (30.01, -97.01), (30.02, -97.02)]
DETECTIONS = [
    {
        "lat": 30.005,
        "lon": -97.005,
        "label": "person #1",
        "details": ["Confidence: 0.82", "Video time: 0:05"],
        "detection_type": "person",
        "thumbnail": "detections/detection_0000.jpg",
    }
]


class TestPageStructure:
    """The page has to stand on its own on any machine."""

    def test_is_a_complete_document(self):
        page = build_flight_map_html(path=PATH, detections=DETECTIONS)

        assert page.startswith("<!DOCTYPE html>")
        assert page.rstrip().endswith("</html>")
        assert '<div id="map">' in page

    def test_leaflet_is_inlined_not_linked(self):
        """A bundle opened offline still has to draw."""
        page = build_flight_map_html(path=PATH)

        # The vendored copy is inlined as <style>/<script>; only the basemap
        # tile servers should appear as remote hosts.
        assert "unpkg.com" not in page
        assert "<style>" in page and "L.tileLayer" in page

    def test_no_remote_script_or_stylesheet_references(self):
        page = build_flight_map_html(path=PATH)

        assert not re.search(r'<script[^>]+src="https?://', page)
        assert not re.search(r'<link[^>]+href="https?://', page)

    def test_title_and_caption_are_rendered(self):
        page = build_flight_map_html(
            path=PATH, title="Search Flight 3", caption="12 detections"
        )

        assert "<title>Search Flight 3</title>" in page
        assert "12 detections" in page


class TestData:
    """Coordinates and pins survive into the baked-in payload."""

    def test_path_coordinates_are_present(self):
        page = build_flight_map_html(path=PATH)

        assert "30.02" in page
        assert "-97.02" in page

    def test_detection_pin_and_popup_are_present(self):
        page = build_flight_map_html(path=PATH, detections=DETECTIONS)

        assert "person #1" in page
        assert "Confidence: 0.82" in page
        assert "detections/detection_0000.jpg" in page

    def test_non_numeric_coordinates_are_dropped(self):
        page = build_flight_map_html(
            path=[(30.0, -97.0), (None, None), ("x", "y"), (30.1, -97.1)],
            detections=[{"lat": None, "lon": -97.0}, {"lat": 31.0, "lon": -98.0}],
        )

        assert '"path":[[30.0,-97.0],[30.1,-97.1]]' in page
        assert page.count('"lat":31.0') == 1

    def test_empty_input_still_produces_a_page(self):
        page = build_flight_map_html(path=[])

        assert page.startswith("<!DOCTYPE html>")
        assert '"path":[]' in page
        assert "No location data was recorded" in page

    def test_popup_text_is_escaped(self):
        """Labels are operator-visible strings, not trusted markup."""
        page = build_flight_map_html(
            path=PATH,
            detections=[{
                "lat": 30.0,
                "lon": -97.0,
                "label": "<img onerror=alert(1)>",
                "details": ["a & b"],
            }],
        )

        assert "<img onerror" not in page
        assert "&lt;img onerror" in page
        assert "a &amp; b" in page

    def test_script_close_sequences_cannot_break_out(self):
        page = build_flight_map_html(
            path=PATH,
            detections=[{"lat": 30.0, "lon": -97.0, "label": "</script><b>x"}],
        )

        # Escaped by the HTML escape and again by the JSON payload guard.
        assert "</script><b>" not in page


class TestPinColors:
    """Pin colors match what the live map drew during the flight."""

    def test_known_detector_uses_the_palette(self):
        assert pin_color_for("person") == DETECTOR_PALETTE["person"]
        assert pin_color_for("MOTION") == DETECTOR_PALETTE["motion"]

    def test_unknown_and_missing_fall_back(self):
        assert pin_color_for("no-such-detector") == DEFAULT_PIN_COLOR
        assert pin_color_for(None) == DEFAULT_PIN_COLOR

    def test_explicit_color_overrides_the_palette(self):
        page = build_flight_map_html(
            path=PATH,
            detections=[{"lat": 30.0, "lon": -97.0, "color": "#123456"}],
        )

        assert "#123456" in page


class TestWriting:
    """write_flight_map_html puts the page on disk."""

    def test_writes_utf8_file(self, tmp_path):
        target = str(tmp_path / "flight_map.html")

        assert write_flight_map_html(target, path=PATH, detections=DETECTIONS) == target
        assert os.path.isfile(target)
        assert "<!DOCTYPE html>" in open(target, encoding="utf-8").read()
