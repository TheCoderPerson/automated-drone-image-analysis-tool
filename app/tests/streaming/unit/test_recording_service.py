"""Unit tests for RecordingService — one recording, end to end.

Extracted from StreamCoordinator so the streaming window and every Flight
Viewer tile share one recording lifecycle. The property that extraction
exists to provide — and the one pinned hardest here — is independence:
two instances recording at once are two bundles with no shared state.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.RecordingService import RecordingService  # noqa: E402
from core.services.streaming.RecordingSessionService import (  # noqa: E402
    DetectionRecord,
    read_manifest,
)


class FakeRecordingManager(QObject):
    """Stands in for the video writer; recording tests are about the bundle."""

    recordingStateChanged = Signal(bool, str)
    recordingStats = Signal(dict)

    def __init__(self, output_dir):
        super().__init__()
        self.output_dir = output_dir
        self.frames = 0
        self.stopped = False

    def start_recording(self, resolution, filename_prefix="rtmp_recording"):
        return True

    def stop_recording(self):
        self.stopped = True

    def add_frame(self, frame, timestamp=None):
        self.frames += 1
        return True

    def get_recording_info(self):
        return {"total_frames": self.frames}


@pytest.fixture
def fake_manager():
    with patch(
        "core.services.streaming.RecordingService.RecordingManager",
        FakeRecordingManager,
    ):
        yield


def _detection(track_id=1, **overrides):
    payload = dict(
        track_id=track_id,
        bbox=(10, 20, 30, 40),
        centroid=(25, 40),
        confidence=0.7,
        detection_type="person",
        frame_resolution=(1280, 720),
        latitude=30.0,
        longitude=-97.0,
        thumbnail=np.full((16, 16, 3), 120, dtype=np.uint8),
        thumbnail_origin=(10, 20),
    )
    payload.update(overrides)
    return DetectionRecord(**payload)


def _frame(width=64, height=48):
    return np.zeros((height, width, 3), dtype=np.uint8)


class TestLifecycle:
    def test_start_records_into_a_bundle(self, fake_manager, tmp_path, qapp):
        service = RecordingService()

        assert service.start(str(tmp_path), (1280, 720), {"algorithm": "X"}) is True
        assert service.is_recording is True
        bundle = service.recording_bundle_dir
        assert bundle is not None and os.path.isdir(bundle)
        # The video writer records inside the bundle, not beside it.
        assert service.recording_manager.output_dir == bundle

        service.stop()

    def test_stop_finalizes_and_reports(self, fake_manager, tmp_path, qapp):
        service = RecordingService()
        results = []
        service.recordingBundleReady.connect(results.append)

        service.start(str(tmp_path), (1280, 720))
        bundle = service.recording_bundle_dir
        service.append_detection(_detection())
        service.append_telemetry({"aircraft_latitude": 30.0, "aircraft_longitude": -97.0})
        service.stop()

        assert len(results) == 1
        assert results[0]["bundle_dir"] == bundle
        assert results[0]["counts"]["detections_stored"] == 1
        assert results[0]["counts"]["telemetry_fixes"] == 1
        assert os.path.isfile(os.path.join(bundle, "detections.csv"))
        assert service.is_recording is False
        # Kept for inspection, replaced on the next start.
        assert service.recording_manager is not None

    def test_double_start_is_refused(self, fake_manager, tmp_path, qapp):
        service = RecordingService()
        errors = []
        service.errorOccurred.connect(errors.append)

        assert service.start(str(tmp_path), (640, 480)) is True
        first_bundle = service.recording_bundle_dir
        assert service.start(str(tmp_path), (640, 480)) is False

        assert service.recording_bundle_dir == first_bundle
        assert any("already in progress" in e for e in errors)
        service.stop()

    def test_capture_outside_a_recording_is_ignored(self, fake_manager, qapp):
        service = RecordingService()

        service.add_frame(_frame())
        service.append_detection(_detection())
        service.append_telemetry({"aircraft_latitude": 1.0, "aircraft_longitude": 2.0})

        assert service.recorded_frame_index() is None
        assert service.session_writer is None

    def test_cleanup_finalizes_an_active_recording(self, fake_manager, tmp_path, qapp):
        service = RecordingService()
        results = []
        service.recordingBundleReady.connect(results.append)

        service.start(str(tmp_path), (640, 480))
        service.append_detection(_detection())
        service.cleanup()

        assert len(results) == 1
        assert results[0]["counts"]["detections_stored"] == 1
        assert service.is_recording is False

    def test_recorder_initiated_stop_finalizes(self, fake_manager, tmp_path, qapp):
        """A frame-write error stops the recorder without anyone calling stop."""
        service = RecordingService()
        results = []
        service.recordingBundleReady.connect(results.append)

        service.start(str(tmp_path), (640, 480))
        service.append_detection(_detection())
        manager = service.recording_manager

        service._on_manager_state_changed(False, "Error: disk full")

        assert service.is_recording is False
        assert manager.stopped is True  # the spinning thread is wound down
        assert len(results) == 1
        # The operator's later stop is a harmless no-op.
        assert service.stop() is None
        assert len(results) == 1

    def test_failed_video_start_discards_the_empty_bundle(self, tmp_path, qapp):
        class RefusingManager(FakeRecordingManager):
            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return False

        with patch(
            "core.services.streaming.RecordingService.RecordingManager",
            RefusingManager,
        ):
            service = RecordingService()
            assert service.start(str(tmp_path), (640, 480)) is False

        assert service.is_recording is False
        assert service.recording_bundle_dir is None
        # No orphan ADIAT_Recording_* folder left behind.
        assert list(tmp_path.iterdir()) == []


class TestIndependence:
    """The Flight Viewer property: each feed records on its own."""

    def test_two_services_record_two_separate_bundles(self, fake_manager, tmp_path, qapp):
        drone_a = RecordingService()
        drone_b = RecordingService()
        results_a, results_b = [], []
        drone_a.recordingBundleReady.connect(results_a.append)
        drone_b.recordingBundleReady.connect(results_b.append)

        assert drone_a.start(str(tmp_path), (1280, 720),
                             {"feed": {"label": "TEXSAR-01"}}) is True
        assert drone_b.start(str(tmp_path), (1920, 1080),
                             {"feed": {"label": "TEXSAR-02"}}) is True

        bundle_a = drone_a.recording_bundle_dir
        bundle_b = drone_b.recording_bundle_dir
        assert bundle_a != bundle_b
        assert "TEXSAR-01" in os.path.basename(bundle_a)
        assert "TEXSAR-02" in os.path.basename(bundle_b)

        # Interleaved capture stays with its own feed.
        drone_a.append_detection(_detection(1))
        drone_b.append_detection(_detection(2))
        drone_b.append_detection(_detection(3))
        drone_a.append_telemetry({"aircraft_latitude": 30.0, "aircraft_longitude": -97.0})
        for _ in range(5):
            drone_b.add_frame(_frame())

        drone_a.stop()
        # A stopped first feed must not disturb the still-recording second.
        assert drone_b.is_recording is True
        drone_b.append_detection(_detection(4))
        drone_b.stop()

        assert results_a[0]["counts"]["detections_stored"] == 1
        assert results_a[0]["counts"]["telemetry_fixes"] == 1
        assert results_b[0]["counts"]["detections_stored"] == 3
        assert results_b[0]["counts"]["telemetry_fixes"] == 0

        manifest_a = read_manifest(bundle_a)
        manifest_b = read_manifest(bundle_b)
        # Frame counters live in the manifest, per feed.
        assert manifest_a["counts"]["frames_recorded"] == 0
        assert manifest_b["counts"]["frames_recorded"] == 5
        assert manifest_a["feed"]["label"] == "TEXSAR-01"
        assert manifest_b["feed"]["label"] == "TEXSAR-02"
        assert manifest_a["video"]["resolution"] == [1280, 720]
        assert manifest_b["video"]["resolution"] == [1920, 1080]

    def test_one_feeds_error_does_not_stop_the_other(self, fake_manager, tmp_path, qapp):
        drone_a = RecordingService()
        drone_b = RecordingService()
        drone_a.start(str(tmp_path), (640, 480))
        drone_b.start(str(tmp_path), (640, 480))

        drone_a._on_manager_state_changed(False, "Error: disk full")

        assert drone_a.is_recording is False
        assert drone_b.is_recording is True
        drone_b.stop()


class TestFrames:
    def test_frames_reach_the_video_writer_and_the_counters(self, fake_manager, tmp_path, qapp):
        service = RecordingService()
        service.start(str(tmp_path), (640, 480))

        service.add_frame(_frame(), detection_count=2)
        service.add_frame(_frame(), detection_count=0)

        assert service.recording_manager.frames == 2
        assert service.session_writer.counts["frames_recorded"] == 2
        assert service.session_writer.counts["raw_detections"] == 2
        assert service.recorded_frame_index() == 2

        service.stop()

    def test_stats_are_forwarded(self, fake_manager, tmp_path, qapp):
        service = RecordingService()
        received = []
        service.recordingStatsUpdated.connect(received.append)
        service.start(str(tmp_path), (640, 480))

        service.recording_manager.recordingStats.emit({"recording_fps": 24.0})

        assert received == [{"recording_fps": 24.0}]
        service.stop()
