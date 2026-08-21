"""Integration tests: replaying a recording bundle in the streaming window.

Opening a bundle's MP4 is the whole replay gesture: the stored detections
appear in the Detection Gallery immediately (click to jump), their
positions pin the map, the sidecar SRT drives the HUD/trail from the
playhead — and detectors do NOT run. The record is the record.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.controllers.streaming.StreamViewerWindow import StreamViewerWindow  # noqa: E402
from core.services.streaming.RecordingBundleService import finalize_bundle  # noqa: E402
from core.services.streaming.RecordingSessionService import (  # noqa: E402
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
)
from core.services.streaming.RTMPStreamService import StreamType  # noqa: E402


@pytest.fixture
def window(qapp, isolated_stream_settings):
    window = StreamViewerWindow(algorithm_name='', theme='dark')
    yield window
    window.close()
    QApplication.processEvents()


def _make_bundle(root, *, detections=2, fixes=3):
    """A real finalized bundle with a placeholder MP4 and spread-out fixes."""
    import json

    from core.services.streaming.RecordingSessionService import (
        TELEMETRY_LOG,
        read_jsonl,
        read_manifest,
    )

    writer = RecordingSessionWriter()
    bundle = writer.start_session(RecordingSessionConfig(
        root_dir=str(root), algorithm="ADIAT Flight",
        source_url="K3F9PM", source_type="webrtc",
        resolution=(1280, 720),
    ))
    with open(os.path.join(bundle, "rec_0001.mp4"), "wb") as fp:
        fp.write(b"\x00")
    for index in range(detections):
        writer.append_detection(DetectionRecord(
            track_id=index,
            bbox=(100 + index * 40, 120, 20, 24),
            centroid=(110 + index * 40, 132),
            confidence=0.8,
            detection_type="person",
            frame_resolution=(1280, 720),
            recorded_frame_index=90 + index * 30,
            latitude=30.25 + index * 0.001,
            longitude=-97.75,
            thumbnail=np.full((30, 40, 3), 180, dtype=np.uint8),
            thumbnail_origin=(90, 108),
        ))
    for _ in range(fixes):
        writer.append_telemetry({
            "aircraft_latitude": 30.25, "aircraft_longitude": -97.75,
            "aircraft_altitude_agl_m": 40.0, "aircraft_altitude_msl_m": 320.0,
        })
    writer.finalize()

    # Spread the fix stamps so SRT cues cover a playable window.
    started = read_manifest(bundle)["started_at_epoch_s"]
    rows = read_jsonl(os.path.join(bundle, TELEMETRY_LOG))
    for index, row in enumerate(rows):
        row["recorded_at_epoch_s"] = started + index * 2.0
        row["aircraft_latitude"] = 30.25 + index * 0.01
    with open(os.path.join(bundle, TELEMETRY_LOG), "w", encoding="utf-8") as fp:
        fp.write("\n".join(json.dumps(r) for r in rows) + "\n")

    finalize_bundle(bundle)
    return bundle


class TestEnteringReplay:
    def test_opening_a_bundle_video_loads_the_stored_detections(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        video = os.path.join(bundle, "rec_0001.mp4")

        window._enter_replay_if_bundle(video)

        assert window._replay_mode is True
        assert window.gallery_widget.gallery_list.count() == 2
        assert len(window._gallery_tracks_by_key) == 2
        # Jump targets come from the stored record, not from a detector.
        track = window._gallery_tracks_by_key["replay-0"]
        assert track.first_frame_index == 90
        assert track.detection_type == "person"
        text = window.ui.infoPanel.toPlainText()
        assert "2" in text and "Detectors are off" in text

    def test_stored_positions_pin_the_map(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        pinned = []
        window.map_view.add_detection = pinned.append

        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))

        assert len(pinned) == 2
        assert pinned[0]["location"]["lat"] == pytest.approx(30.25)
        assert pinned[0]["track_key"] == "replay-0"

    def test_an_ordinary_video_does_not_enter_replay(self, window, tmp_path):
        loose = tmp_path / "DJI_0042.MP4"
        loose.write_bytes(b"\x00")

        window._enter_replay_if_bundle(str(loose))

        assert window._replay_mode is False
        assert window.gallery_widget.gallery_list.count() == 0

    def test_bundle_telemetry_replays_through_the_sidecar_srt(self, window, tmp_path):
        """The same path a DJI card video takes: sidecar discovered, HUD fed."""
        bundle = _make_bundle(tmp_path)
        video = os.path.join(bundle, "rec_0001.mp4")

        available = window.telemetry_coordinator.begin_source(video, StreamType.FILE)

        assert available is True
        assert window.telemetry_coordinator.position_at(2.0) == pytest.approx(
            (30.26, -97.75)
        )

    def test_detections_missing_thumbnails_still_pin_without_gallery_rows(
            self, window, tmp_path):
        bundle = _make_bundle(tmp_path, detections=1)
        # Delete the thumbnail file the row references.
        os.remove(os.path.join(bundle, "detections", "detection_0000.jpg"))

        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))

        assert window._replay_mode is True
        assert window.gallery_widget.gallery_list.count() == 0


class TestDetectorsStayOff:
    def test_frames_bypass_the_algorithm_during_replay(self, window, tmp_path):
        """The record is the record - replay never re-runs a detector."""
        bundle = _make_bundle(tmp_path)
        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))

        algorithm = Mock()
        algorithm.process_frame = Mock(return_value=[])
        window.algorithm_widget = algorithm
        window.algorithm_renders_frame = False
        presented = []
        window._present_frame = lambda frame, pos, source: presented.append(source) or True

        window.on_frame_received(np.zeros((720, 1280, 3), dtype=np.uint8), 0.0, 0)

        algorithm.process_frame.assert_not_called()
        # The frame still displays - via the raw path.
        assert presented == ["raw"]

    def test_the_same_frame_processes_when_not_in_replay(self, window):
        algorithm = Mock()
        algorithm.process_frame = Mock(return_value=[])
        algorithm.get_config = Mock(return_value={})
        window.algorithm_widget = algorithm
        window.algorithm_renders_frame = False
        window._present_frame = lambda frame, pos, source: True

        window.on_frame_received(np.zeros((720, 1280, 3), dtype=np.uint8), 0.0, 0)

        algorithm.process_frame.assert_called_once()

    def test_replay_state_clears_on_disconnect(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))
        assert window._replay_mode is True
        window._connection_established = True

        window.on_connection_changed(False, "Disconnected")

        assert window._replay_mode is False
        assert window.gallery_widget.gallery_list.count() == 0


class TestJumpToDetection:
    def test_gallery_click_arms_a_seek_to_the_stored_frame(self, window, tmp_path):
        """Click a stored detection -> the video pauses and jumps there."""
        bundle = _make_bundle(tmp_path)
        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))
        track = window._gallery_tracks_by_key["replay-1"]

        window.stream_coordinator.current_stream_type = StreamType.FILE
        manager = Mock()
        manager.is_playing = Mock(return_value=True)
        manager.play_pause = Mock()
        window.stream_coordinator.stream_manager = manager

        window._on_gallery_track_clicked(track)

        manager.play_pause.assert_called_once()
        assert window._highlight_track is track

    def test_map_pin_click_selects_the_stored_detection(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        window._enter_replay_if_bundle(os.path.join(bundle, "rec_0001.mp4"))
        selected = []
        window._on_gallery_track_clicked = selected.append

        window._on_map_pin_clicked("replay-0")

        assert selected == [window._gallery_tracks_by_key["replay-0"]]
