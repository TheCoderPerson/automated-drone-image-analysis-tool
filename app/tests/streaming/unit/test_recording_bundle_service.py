"""Unit tests for RecordingBundleService (deriving a bundle's artifacts)."""

import csv
import json
import os
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from core.services.streaming.RecordingBundleService import (
    DETECTIONS_CSV,
    FLIGHT_MAP_HTML,
    FLIGHT_PATH_KML,
    RESULTS_XML,
    TELEMETRY_CSV,
    build_aoi,
    finalize_bundle,
)
from core.services.streaming.RecordingSessionService import (
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
    read_manifest,
)


def _thumbnail(width=40, height=30):
    return np.full((height, width, 3), 200, dtype=np.uint8)


def _record(seq=0, lat=30.1, lon=-97.2, **overrides):
    payload = dict(
        track_id=seq,
        bbox=(100, 120, 20, 24),
        centroid=(110, 132),
        confidence=0.75,
        detection_type="person",
        pixel_area=380.0,
        frame_resolution=(1280, 720),
        first_frame_index=150 + seq,
        video_time_seconds=5.0 + seq,
        recorded_frame_index=148 + seq,
        latitude=lat,
        longitude=lon,
        detection_color=(10, 20, 30),
        thumbnail=_thumbnail(),
        thumbnail_origin=(90, 108),
    )
    payload.update(overrides)
    return DetectionRecord(**payload)


def _build_bundle(tmp_path, *, detections=(), fixes=(), **config_overrides):
    """Run a real capture session, then return its finalized bundle path."""
    config = RecordingSessionConfig(
        root_dir=str(tmp_path),
        algorithm="ColorAnomalyAndMotionDetection",
        algorithm_options={"threshold": 12},
        source_url="C:/flights/dji.mp4",
        source_type="File",
        resolution=(1280, 720),
    )
    for key, value in config_overrides.items():
        setattr(config, key, value)

    writer = RecordingSessionWriter()
    bundle = writer.start_session(config)
    assert bundle is not None
    for record in detections:
        writer.append_detection(record)
    for fix in fixes:
        writer.append_telemetry(fix)
    writer.note_frame(2)
    writer.finalize()
    return bundle


def _fix(lat, lon, seconds=0.0):
    return {
        "aircraft_latitude": lat,
        "aircraft_longitude": lon,
        "aircraft_altitude_agl_m": 40.0,
        "aircraft_altitude_msl_m": 320.0,
        "aircraft_yaw_deg": 91.5,
        "video_time_seconds": seconds,
        "captured_at_ms": int(seconds * 1000),
        "agl_source": "reported",
    }


class TestAoiProjection:
    """The exported AOI has to land on the saved thumbnail crop."""

    def test_center_is_relative_to_the_crop_origin(self):
        aoi = build_aoi({
            "seq": 0,
            "bbox": [100, 120, 20, 24],
            "thumbnail_origin": [90, 108],
            "thumbnail_size": [40, 30],
            "pixel_area": 380.0,
        })

        # bbox center is (110, 132) in the frame; the crop starts at (90, 108).
        assert aoi["center"] == (20, 24)
        assert aoi["radius"] == 10
        assert aoi["area"] == 380
        assert aoi["number"] == 1

    def test_center_is_clamped_into_the_thumbnail(self):
        """A crop clamped at a frame edge can push the center off-image."""
        aoi = build_aoi({
            "seq": 3,
            "bbox": [0, 0, 400, 400],
            "thumbnail_origin": [0, 0],
            "thumbnail_size": [40, 30],
        })

        assert aoi["center"] == (39, 29)

    def test_missing_geometry_falls_back_without_raising(self):
        aoi = build_aoi({"seq": 0})

        assert aoi["center"] == (0, 0)
        assert aoi["radius"] == 20
        assert aoi["area"] == 100

    def test_comment_carries_type_time_and_position(self):
        aoi = build_aoi({
            "seq": 0,
            "bbox": [10, 10, 8, 8],
            "detection_type": "person",
            "video_time_seconds": 125.0,
            "latitude": 30.5,
            "longitude": -97.5,
        })

        assert "person" in aoi["user_comment"]
        assert "2:05" in aoi["user_comment"]
        assert "30.500000, -97.500000" in aoi["user_comment"]

    def test_confidence_becomes_a_score(self):
        aoi = build_aoi({"seq": 0, "bbox": [10, 10, 8, 8], "confidence": 0.62})

        assert aoi["confidence"] == 0.62
        assert aoi["score_type"] == "confidence"
        assert aoi["score_method"] == "StreamingRecording"


class TestDetectionArtifacts:
    """detections.csv and ADIAT_Data.xml."""

    def test_csv_has_one_row_per_detection(self, tmp_path):
        bundle = _build_bundle(tmp_path, detections=[_record(0), _record(1)])
        result = finalize_bundle(bundle)

        assert result["artifacts"]["detections_csv"] == DETECTIONS_CSV
        with open(os.path.join(bundle, DETECTIONS_CSV), encoding="utf-8", newline="") as fp:
            rows = list(csv.DictReader(fp))
        assert len(rows) == 2
        assert rows[0]["detection_type"] == "person"
        assert rows[0]["bbox_x"] == "100"
        assert rows[0]["bbox_w"] == "20"
        assert float(rows[0]["latitude"]) == pytest.approx(30.1)
        assert rows[1]["recorded_frame_index"] == "149"

    def test_results_xml_is_readable_by_xmlservice(self, tmp_path):
        """The whole point of the XML is that the Images window can load it."""
        from core.services.XmlService import XmlService

        bundle = _build_bundle(tmp_path, detections=[_record(0), _record(1)])
        finalize_bundle(bundle)

        xml_path = os.path.join(bundle, RESULTS_XML)
        assert os.path.isfile(xml_path)

        service = XmlService(xml_path)
        settings, image_count = service.get_settings()
        assert settings["algorithm"] == "ColorAnomalyAndMotionDetection"
        assert image_count == 2

        images = service.get_images()
        assert len(images) == 2
        for image in images:
            assert len(image["areas_of_interest"]) == 1
            assert os.path.isfile(image["path"])

    def test_results_xml_survives_the_bundle_being_moved(self, tmp_path):
        """A bundle copied to a team drive still has to open."""
        import shutil

        from core.services.XmlService import XmlService

        bundle = _build_bundle(tmp_path, detections=[_record(0)])
        finalize_bundle(bundle)

        moved = str(tmp_path / "copied_bundle")
        shutil.copytree(bundle, moved)
        shutil.rmtree(bundle)

        images = XmlService(os.path.join(moved, RESULTS_XML)).get_images()
        assert len(images) == 1
        assert os.path.isfile(images[0]["path"])
        assert moved in images[0]["path"]

    def test_results_xml_records_provenance_options(self, tmp_path):
        bundle = _build_bundle(tmp_path, detections=[_record(0)])
        finalize_bundle(bundle)

        root = ET.parse(os.path.join(bundle, RESULTS_XML)).getroot()
        options = {
            option.get("name"): option.get("value")
            for option in root.findall("./settings/options/option")
        }
        assert options["source"] == "ADIAT Streaming Recording"
        assert options["stream_type"] == "File"
        assert options["algorithm.threshold"] == "12"

    def test_detection_without_a_thumbnail_is_skipped_in_xml_but_kept_in_csv(self, tmp_path):
        bundle = _build_bundle(
            tmp_path, detections=[_record(0), _record(1, thumbnail=None)]
        )
        finalize_bundle(bundle)

        root = ET.parse(os.path.join(bundle, RESULTS_XML)).getroot()
        assert len(root.findall("./images/image")) == 1
        with open(os.path.join(bundle, DETECTIONS_CSV), encoding="utf-8", newline="") as fp:
            assert len(list(csv.DictReader(fp))) == 2

    def test_no_detections_writes_no_detection_artifacts(self, tmp_path):
        bundle = _build_bundle(tmp_path, fixes=[_fix(30.0, -97.0)])
        result = finalize_bundle(bundle)

        assert result["artifacts"]["detections_csv"] is None
        assert result["artifacts"]["results_xml"] is None
        assert not os.path.exists(os.path.join(bundle, RESULTS_XML))


class TestFlightArtifacts:
    """telemetry.csv, flight_map.html and flight_path.kml."""

    def test_telemetry_csv_written(self, tmp_path):
        bundle = _build_bundle(
            tmp_path, fixes=[_fix(30.0, -97.0, 0.0), _fix(30.01, -97.01, 1.0)]
        )
        finalize_bundle(bundle)

        with open(os.path.join(bundle, TELEMETRY_CSV), encoding="utf-8", newline="") as fp:
            rows = list(csv.DictReader(fp))
        assert len(rows) == 2
        assert float(rows[1]["aircraft_latitude"]) == pytest.approx(30.01)
        assert rows[0]["agl_source"] == "reported"

    def test_flight_map_contains_path_and_pins(self, tmp_path):
        bundle = _build_bundle(
            tmp_path,
            detections=[_record(0, lat=30.005, lon=-97.005)],
            fixes=[_fix(30.0, -97.0, 0.0), _fix(30.01, -97.01, 1.0)],
        )
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_map_html"] == FLIGHT_MAP_HTML
        page = open(os.path.join(bundle, FLIGHT_MAP_HTML), encoding="utf-8").read()
        assert "30.005" in page
        assert "-97.01" in page
        assert "ColorAnomalyAndMotionDetection" in page

    def test_flight_kml_has_a_path_and_a_placemark(self, tmp_path):
        bundle = _build_bundle(
            tmp_path,
            detections=[_record(0)],
            fixes=[_fix(30.0, -97.0, 0.0), _fix(30.01, -97.01, 1.0)],
        )
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_path_kml"] == FLIGHT_PATH_KML
        kml = open(os.path.join(bundle, FLIGHT_PATH_KML), encoding="utf-8").read()
        assert "LineString" in kml
        assert "Flight Path" in kml
        assert "person #1" in kml

    def test_no_telemetry_skips_map_and_kml(self, tmp_path):
        """A source with no location data produces no flight artifacts."""
        bundle = _build_bundle(
            tmp_path, detections=[_record(0, lat=None, lon=None)]
        )
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_map_html"] is None
        assert result["artifacts"]["flight_path_kml"] is None
        assert result["artifacts"]["telemetry_csv"] is None
        # ...but the detections were still stored.
        assert result["artifacts"]["detections_csv"] == DETECTIONS_CSV

    def test_geotagged_detections_alone_still_produce_a_map(self, tmp_path):
        """A live feed can geotag detections before any path accumulates."""
        bundle = _build_bundle(tmp_path, detections=[_record(0)])
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_map_html"] == FLIGHT_MAP_HTML

    def test_declining_the_map_suppresses_it_entirely(self, tmp_path):
        """Detections are geotagged regardless, so the choice must be honoured.

        Without this the map and KML were still written from the geotagged
        detections even with "Save flight map" unchecked.
        """
        bundle = _build_bundle(
            tmp_path, detections=[_record(0)], save_flight_map=False
        )
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_map_html"] is None
        assert result["artifacts"]["flight_path_kml"] is None
        assert not os.path.exists(os.path.join(bundle, FLIGHT_MAP_HTML))
        assert not os.path.exists(os.path.join(bundle, FLIGHT_PATH_KML))
        # The detections themselves are unaffected.
        assert result["artifacts"]["detections_csv"] == DETECTIONS_CSV

    def test_a_manifestless_bundle_still_gets_its_map(self, tmp_path):
        """Crash recovery must not read a missing option as a refusal."""
        bundle = _build_bundle(tmp_path, detections=[_record(0)])
        os.remove(os.path.join(bundle, "manifest.json"))

        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_map_html"] == FLIGHT_MAP_HTML


class TestFlightPathOrdering:
    """The drawn path is the route flown, not the order it was watched in."""

    def test_scrubbed_playback_is_reordered_by_video_time(self, tmp_path):
        from core.services.streaming.RecordingBundleService import _coords
        from core.services.streaming.RecordingSessionService import (
            TELEMETRY_LOG, read_jsonl,
        )

        # Recorded while the operator jumped back and forth in the file.
        bundle = _build_bundle(tmp_path, fixes=[
            _fix(30.2, -97.2, 20.0),
            _fix(30.0, -97.0, 0.0),
            _fix(30.1, -97.1, 10.0),
        ])
        rows = read_jsonl(os.path.join(bundle, TELEMETRY_LOG))

        assert _coords(rows) == [(30.0, -97.0), (30.1, -97.1), (30.2, -97.2)]

    def test_live_fixes_keep_their_arrival_order(self):
        from core.services.streaming.RecordingBundleService import _coords

        # A live feed carries no video time; order as logged is the truth.
        rows = [
            {"aircraft_latitude": 30.2, "aircraft_longitude": -97.2},
            {"aircraft_latitude": 30.0, "aircraft_longitude": -97.0},
        ]

        assert _coords(rows) == [(30.2, -97.2), (30.0, -97.0)]

    def test_repeated_positions_collapse(self):
        from core.services.streaming.RecordingBundleService import _coords

        rows = [
            {"aircraft_latitude": 30.0, "aircraft_longitude": -97.0},
            {"aircraft_latitude": 30.0, "aircraft_longitude": -97.0},
            {"aircraft_latitude": 30.1, "aircraft_longitude": -97.1},
            {"aircraft_latitude": 30.0, "aircraft_longitude": -97.0},
        ]

        # Only *consecutive* repeats go: revisiting a spot is real movement.
        assert _coords(rows) == [(30.0, -97.0), (30.1, -97.1), (30.0, -97.0)]

    def test_partial_video_times_are_not_reordered(self):
        """A mixed log has no single timeline to sort on."""
        from core.services.streaming.RecordingBundleService import _coords

        rows = [
            {"aircraft_latitude": 30.2, "aircraft_longitude": -97.2, "video_time_seconds": 20.0},
            {"aircraft_latitude": 30.0, "aircraft_longitude": -97.0},
        ]

        assert _coords(rows) == [(30.2, -97.2), (30.0, -97.0)]

    def test_telemetry_csv_keeps_every_raw_row(self, tmp_path):
        """Tidying the path must not tidy the record it came from."""
        bundle = _build_bundle(tmp_path, fixes=[
            _fix(30.0, -97.0, 0.0),
            _fix(30.0, -97.0, 1.0),
            _fix(30.1, -97.1, 2.0),
        ])
        finalize_bundle(bundle)

        with open(os.path.join(bundle, TELEMETRY_CSV), encoding="utf-8", newline="") as fp:
            assert len(list(csv.DictReader(fp))) == 3


class TestManifestAndErrors:
    """The manifest describes the finished bundle."""

    def test_manifest_lists_artifacts_and_counts(self, tmp_path):
        bundle = _build_bundle(
            tmp_path,
            detections=[_record(0), _record(1, lat=None, lon=None)],
            fixes=[_fix(30.0, -97.0)],
        )
        finalize_bundle(bundle)

        manifest = read_manifest(bundle)
        assert manifest["counts"]["detections_stored"] == 2
        assert manifest["counts"]["detections_geotagged"] == 1
        assert manifest["counts"]["telemetry_fixes"] == 1
        assert manifest["artifacts"]["detections_csv"] == DETECTIONS_CSV
        assert manifest["telemetry"]["available"] is True
        assert manifest["finalized_at"] is not None

    def test_one_failing_artifact_does_not_sink_the_others(self, tmp_path, monkeypatch):
        bundle = _build_bundle(
            tmp_path, detections=[_record(0)], fixes=[_fix(30.0, -97.0), _fix(30.1, -97.1)]
        )

        import core.services.streaming.RecordingBundleService as module

        def boom(*_args, **_kwargs):
            raise RuntimeError("kml exploded")

        monkeypatch.setattr(module, "write_flight_kml", boom)
        result = finalize_bundle(bundle)

        assert result["artifacts"]["flight_path_kml"] is None
        assert any("kml exploded" in message for message in result["errors"])
        assert result["artifacts"]["detections_csv"] == DETECTIONS_CSV
        assert result["artifacts"]["flight_map_html"] == FLIGHT_MAP_HTML
        assert "kml exploded" in json.dumps(read_manifest(bundle))

    def test_finalizing_an_empty_bundle_is_harmless(self, tmp_path):
        bundle = _build_bundle(tmp_path)
        result = finalize_bundle(bundle)

        assert result["counts"]["detections_stored"] == 0
        assert set(result["artifacts"].values()) == {None}
        assert result["errors"] == []

    def test_finalize_rebuilds_from_logs_alone(self, tmp_path):
        """The crash-repair path: logs on disk, nothing else."""
        bundle = _build_bundle(
            tmp_path, detections=[_record(0)], fixes=[_fix(30.0, -97.0), _fix(30.1, -97.1)]
        )
        for name in (DETECTIONS_CSV, RESULTS_XML, FLIGHT_MAP_HTML, FLIGHT_PATH_KML):
            path = os.path.join(bundle, name)
            if os.path.exists(path):
                os.remove(path)

        result = finalize_bundle(bundle)

        assert result["artifacts"]["detections_csv"] == DETECTIONS_CSV
        assert result["artifacts"]["results_xml"] == RESULTS_XML
        assert os.path.isfile(os.path.join(bundle, FLIGHT_MAP_HTML))
