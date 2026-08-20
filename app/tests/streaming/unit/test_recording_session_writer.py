"""Unit tests for RecordingSessionWriter (the recording bundle's live logs)."""

import json
import os
import time
from enum import Enum

import numpy as np
import pytest

from core.services.streaming.RecordingSessionService import (
    BUNDLE_DIR_PREFIX,
    DETECTIONS_LOG,
    DETECTIONS_SUBDIR,
    FRAMES_LOG,
    MANIFEST_FILE,
    TELEMETRY_LOG,
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
    allocate_bundle_dir,
    read_jsonl,
    read_manifest,
)


@pytest.fixture
def config(tmp_path):
    """A session that saves everything, rooted in a temp directory."""
    return RecordingSessionConfig(
        root_dir=str(tmp_path),
        algorithm="ColorAnomalyAndMotionDetection",
        algorithm_options={"threshold": 12},
        source_url="rtmp://example/live",
        source_type="RTMP",
        resolution=(1280, 720),
        fps_limit=10,
    )


def _thumbnail(width=40, height=30):
    return np.full((height, width, 3), 128, dtype=np.uint8)


def _record(**overrides):
    payload = dict(
        track_id=7,
        bbox=(100, 120, 20, 24),
        centroid=(110, 132),
        confidence=0.82,
        detection_type="person",
        pixel_area=380.0,
        frame_resolution=(1280, 720),
        first_frame_index=153,
        video_time_seconds=5.1,
        recorded_frame_index=150,
        latitude=30.123456,
        longitude=-97.654321,
        thumbnail=_thumbnail(),
        thumbnail_origin=(90, 108),
    )
    payload.update(overrides)
    return DetectionRecord(**payload)


def _finalized(writer, config):
    """Start, run ``body``-free, and finalize - returns the bundle path."""
    bundle = writer.start_session(config)
    assert bundle is not None
    return bundle


class TestBundleAllocation:
    """The per-recording folder."""

    def test_creates_named_directory(self, tmp_path):
        bundle = allocate_bundle_dir(str(tmp_path))

        assert bundle.is_dir()
        assert bundle.name.startswith(BUNDLE_DIR_PREFIX)
        assert bundle.parent == tmp_path

    def test_same_second_collision_gets_a_suffix(self, tmp_path):
        first = allocate_bundle_dir(str(tmp_path), now=1_700_000_000)
        second = allocate_bundle_dir(str(tmp_path), now=1_700_000_000)

        assert first != second
        assert second.name.endswith("_2")
        assert first.is_dir() and second.is_dir()


class TestSessionLifecycle:
    """start_session / finalize."""

    def test_start_creates_bundle_and_manifest(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)

        try:
            assert writer.is_active is True
            assert os.path.isdir(os.path.join(bundle, DETECTIONS_SUBDIR))
            manifest = read_manifest(bundle)
            assert manifest["algorithm"] == "ColorAnomalyAndMotionDetection"
            assert manifest["algorithm_options"] == {"threshold": 12}
            assert manifest["source"] == {"url": "rtmp://example/live", "type": "RTMP"}
            assert manifest["video"]["resolution"] == [1280, 720]
            assert manifest["video"]["fps_limit"] == 10
            assert manifest["ended_at"] is None
        finally:
            writer.finalize()

    def test_finalize_stamps_end_and_returns_bundle(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)

        assert writer.finalize() == bundle
        assert writer.is_active is False
        manifest = read_manifest(bundle)
        assert manifest["ended_at"] is not None
        assert manifest["ended_at_epoch_s"] is not None

    def test_finalize_is_idempotent(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)

        assert writer.finalize() == bundle
        assert writer.finalize() == bundle

    def test_unwritable_root_reports_rather_than_raises(self, config, tmp_path):
        """A root that cannot hold a folder fails the bundle, not the app."""
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        config.root_dir = str(blocker / "bundles")
        writer = RecordingSessionWriter()

        assert writer.start_session(config) is None
        assert writer.is_active is False
        assert writer.bundle_dir is None

    def test_second_start_does_not_replace_the_active_session(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        try:
            assert writer.start_session(config) == bundle
        finally:
            writer.finalize()


class TestDiscard:
    """An abandoned bundle should not look like a recording that happened."""

    def test_empty_bundle_is_removed(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)

        writer.discard()

        assert not os.path.exists(bundle)
        assert writer.is_active is False

    def test_bundle_with_detections_is_kept(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record())

        writer.discard()

        assert os.path.isdir(bundle)
        assert read_jsonl(os.path.join(bundle, DETECTIONS_LOG))

    def test_bundle_with_a_video_is_kept(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        with open(os.path.join(bundle, "rtmp_recording_1.mp4"), "wb") as handle:
            handle.write(b"\x00")

        writer.discard()

        assert os.path.isdir(bundle)

    def test_discard_without_a_session_is_harmless(self):
        writer = RecordingSessionWriter()

        writer.discard()

        assert writer.bundle_dir is None


class TestDetectionCapture:
    """Confirmed detections land in the log with their thumbnails."""

    def test_detection_is_logged_with_thumbnail(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record())
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, DETECTIONS_LOG))
        assert len(rows) == 1
        row = rows[0]
        assert row["seq"] == 0
        assert row["track_id"] == 7
        assert row["bbox"] == [100, 120, 20, 24]
        assert row["detection_type"] == "person"
        assert row["video_time_seconds"] == pytest.approx(5.1)
        assert row["recorded_frame_index"] == 150
        assert row["latitude"] == pytest.approx(30.123456)
        assert row["thumbnail"] == f"{DETECTIONS_SUBDIR}/detection_0000.jpg"
        assert row["thumbnail_size"] == [40, 30]
        assert row["thumbnail_origin"] == [90, 108]
        assert os.path.isfile(os.path.join(bundle, DETECTIONS_SUBDIR, "detection_0000.jpg"))

    def test_sequence_numbers_increment(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        for index in range(3):
            writer.append_detection(_record(track_id=index))
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, DETECTIONS_LOG))
        assert [row["seq"] for row in rows] == [0, 1, 2]
        assert [row["thumbnail"] for row in rows] == [
            f"{DETECTIONS_SUBDIR}/detection_{i:04d}.jpg" for i in range(3)
        ]

    def test_detection_without_thumbnail_still_logged(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record(thumbnail=None))
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, DETECTIONS_LOG))
        assert len(rows) == 1
        assert rows[0]["thumbnail"] is None

    def test_numpy_scalars_survive_serialization(self, config):
        """Track fields arrive as numpy types from OpenCV maths."""
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record(
            confidence=np.float32(0.5),
            pixel_area=np.float64(120.0),
            centroid=(np.int64(11), np.int64(22)),
        ))
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, DETECTIONS_LOG))
        assert rows[0]["confidence"] == pytest.approx(0.5)
        assert rows[0]["centroid"] == [11, 22]

    def test_detections_off_writes_nothing(self, config):
        config.save_detections = False
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record())
        writer.finalize()

        assert not os.path.exists(os.path.join(bundle, DETECTIONS_LOG))
        assert not os.path.isdir(os.path.join(bundle, DETECTIONS_SUBDIR))

    def test_append_outside_a_session_is_ignored(self, config):
        writer = RecordingSessionWriter()

        writer.append_detection(_record())  # before start
        bundle = _finalized(writer, config)
        writer.finalize()
        writer.append_detection(_record())  # after finalize

        assert read_jsonl(os.path.join(bundle, DETECTIONS_LOG)) == []


class TestTelemetryCapture:
    """Telemetry fixes bound the recording's flight path."""

    def test_positioned_fix_is_logged(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_telemetry({
            "aircraft_latitude": 30.1,
            "aircraft_longitude": -97.2,
            "aircraft_altitude_agl_m": 42.0,
        })
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, TELEMETRY_LOG))
        assert len(rows) == 1
        assert rows[0]["aircraft_latitude"] == pytest.approx(30.1)
        assert "recorded_at_epoch_s" in rows[0]

    def test_fix_without_a_position_is_dropped(self, config):
        """An envelope with no lat/lon cannot contribute to a path."""
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_telemetry({"aircraft_altitude_agl_m": 42.0})
        writer.append_telemetry({"aircraft_latitude": None, "aircraft_longitude": None})
        writer.finalize()

        assert read_jsonl(os.path.join(bundle, TELEMETRY_LOG)) == []

    def test_map_off_skips_telemetry(self, config):
        config.save_flight_map = False
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_telemetry({"aircraft_latitude": 30.1, "aircraft_longitude": -97.2})
        writer.finalize()

        assert not os.path.exists(os.path.join(bundle, TELEMETRY_LOG))

    def test_missing_telemetry_is_explained_at_finalize(self, config):
        """A map was wanted and nothing arrived - the bundle should say so."""
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.finalize()

        manifest = read_manifest(bundle)
        assert manifest["telemetry"]["available"] is False
        assert "No location data arrived" in manifest["telemetry"]["note"]

    def test_no_note_when_fixes_arrived(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_telemetry({"aircraft_latitude": 30.0, "aircraft_longitude": -97.0})
        writer.finalize()

        manifest = read_manifest(bundle)
        assert manifest["telemetry"]["available"] is True
        assert manifest["telemetry"]["note"] is None

    def test_no_note_when_no_map_was_asked_for(self, config):
        config.save_flight_map = False
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.finalize()

        assert read_manifest(bundle)["telemetry"]["note"] is None


class TestManifestRobustness:
    """The manifest is the session header; it must never be left corrupt."""

    def test_enum_options_are_serialized_not_fatal(self, config):
        """Streaming controllers report Enum config values verbatim.

        ``ColorAnomalyAndMotionDetection`` - the default algorithm - puts
        Enum members in ``get_config()``. These used to raise partway
        through ``json.dump``, leaving a truncated file that read back as
        ``{}`` and lost the whole session header.
        """
        class MotionAlgorithm(Enum):
            MOG2 = "mog2"

        config.algorithm_options = {
            "motion_algorithm": MotionAlgorithm.MOG2,
            "threshold": 12,
        }
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.finalize()

        manifest = read_manifest(bundle)
        assert manifest != {}
        assert manifest["algorithm_options"]["motion_algorithm"] == "mog2"
        assert manifest["algorithm_options"]["threshold"] == 12
        # The rest of the header survived too.
        assert manifest["source"]["url"] == "rtmp://example/live"
        assert manifest["counts"]["frames_recorded"] == 0

    def test_arbitrary_objects_degrade_to_text(self, config):
        class Opaque:
            def __repr__(self):
                return "<opaque option>"

        config.algorithm_options = {
            "widget": Opaque(),
            "ranges": [(1, 2), (3, 4)],
            "flags": {True, False},
            "resolution": np.array([1920, 1080]),
        }
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.finalize()

        options = read_manifest(bundle)["algorithm_options"]
        assert options["widget"] == "<opaque option>"
        assert options["ranges"] == [[1, 2], [3, 4]]
        assert sorted(options["flags"]) == [False, True]
        assert options["resolution"] == [1920, 1080]

    def test_a_bad_manifest_does_not_destroy_the_previous_one(self, config, monkeypatch):
        """Opening with "w" truncates, so encoding must succeed first."""
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        try:
            before = open(os.path.join(bundle, MANIFEST_FILE), encoding="utf-8").read()
            assert json.loads(before)

            def boom(*_args, **_kwargs):
                raise TypeError("unserializable")

            monkeypatch.setattr(json, "dumps", boom)
            writer._write_manifest(ended=True)

            after = open(os.path.join(bundle, MANIFEST_FILE), encoding="utf-8").read()
            assert after == before
        finally:
            monkeypatch.undo()
            writer.finalize()


class TestFrameCounters:
    """Per-frame activity is counted, not logged, unless asked for."""

    def test_counts_frames_and_raw_detections(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.note_frame(3)
        writer.note_frame(0)
        writer.note_frame(2)
        writer.append_detection(_record())
        writer.append_telemetry({"aircraft_latitude": 1.0, "aircraft_longitude": 2.0})
        writer.finalize()

        counts = read_manifest(bundle)["counts"]
        assert counts["frames_recorded"] == 3
        assert counts["raw_detections"] == 5
        assert counts["detections_stored"] == 1
        assert counts["telemetry_fixes"] == 1

    def test_frame_level_logging_is_off_by_default(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.note_frame(4, 1.5)
        writer.finalize()

        assert not os.path.exists(os.path.join(bundle, FRAMES_LOG))

    def test_frame_level_logging_can_be_enabled(self, config):
        config.frame_level_detections = True
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.note_frame(4, 1.5)
        writer.finalize()

        rows = read_jsonl(os.path.join(bundle, FRAMES_LOG))
        assert rows == [
            {
                "detections": 4,
                "video_time_seconds": 1.5,
                "recorded_at_epoch_s": rows[0]["recorded_at_epoch_s"],
            }
        ]


class TestCrashTolerance:
    """A bundle interrupted mid-write is still readable."""

    def test_truncated_trailing_line_is_skipped(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        writer.append_detection(_record())
        writer.finalize()

        log = os.path.join(bundle, DETECTIONS_LOG)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write('{"seq": 1, "track_id": ')  # killed mid-line

        rows = read_jsonl(log)
        assert len(rows) == 1
        assert rows[0]["seq"] == 0

    def test_detections_reach_disk_without_a_finalize(self, config):
        """A crash mid-flight must still leave every detection on disk."""
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        log = os.path.join(bundle, DETECTIONS_LOG)
        try:
            for index in range(5):
                writer.append_detection(_record(track_id=index))

            # No finalize: wait for the writer thread to drain on its own,
            # which is all a crashed process would ever have done.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and len(read_jsonl(log)) < 5:
                time.sleep(0.02)

            rows = read_jsonl(log)
            assert len(rows) == 5
            assert [row["track_id"] for row in rows] == [0, 1, 2, 3, 4]
        finally:
            writer.finalize()

    def test_manifest_is_valid_json_while_recording(self, config):
        writer = RecordingSessionWriter()
        bundle = _finalized(writer, config)
        try:
            with open(os.path.join(bundle, MANIFEST_FILE), encoding="utf-8") as handle:
                assert isinstance(json.load(handle), dict)
        finally:
            writer.finalize()
