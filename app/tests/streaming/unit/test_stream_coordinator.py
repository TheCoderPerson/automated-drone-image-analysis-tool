"""Unit tests for StreamCoordinator."""

import os

import pytest
import numpy as np
from unittest.mock import Mock, MagicMock, patch
from PySide6.QtCore import QObject, Signal

from core.controllers.streaming.components.StreamCoordinator import StreamCoordinator
from core.services.streaming.FlightStreamService import FlightStreamManager
from core.services.streaming.RecordingSessionService import (
    BUNDLE_DIR_PREFIX,
    MANIFEST_FILE,
    DetectionRecord,
    read_manifest,
)
from core.services.streaming.RTMPStreamService import StreamManager, StreamType


def _detection_record(**overrides):
    """A confirmed detection in the shape the viewer hands over."""
    payload = dict(
        track_id=1,
        bbox=(10, 20, 30, 40),
        centroid=(25, 40),
        confidence=0.7,
        detection_type="person",
        pixel_area=120.0,
        frame_resolution=(1280, 720),
        first_frame_index=42,
        video_time_seconds=1.4,
        recorded_frame_index=40,
        latitude=30.0,
        longitude=-97.0,
        thumbnail=np.full((16, 16, 3), 120, dtype=np.uint8),
        thumbnail_origin=(10, 20),
    )
    payload.update(overrides)
    return DetectionRecord(**payload)


class TestStreamCoordinator:
    """Test suite for StreamCoordinator."""

    def test_initialization(self, mock_logger):
        """Test coordinator initialization."""
        coordinator = StreamCoordinator(mock_logger)

        assert coordinator.logger == mock_logger
        assert coordinator.is_connected is False
        assert coordinator.current_stream_url == ""
        assert coordinator.stream_manager is None
        assert coordinator.recording_manager is None

    def test_connect_stream(self, mock_logger, mock_stream_manager):
        """Test stream connection."""
        coordinator = StreamCoordinator(mock_logger)

        # Mock StreamManager to return our mock and have connect_to_stream return True
        mock_stream_manager.connect_to_stream = Mock(return_value=True)
        mock_stream_manager.frameReceived = Mock()
        mock_stream_manager.connectionChanged = Mock()

        with patch('core.controllers.streaming.components.StreamCoordinator.StreamManager', return_value=mock_stream_manager):
            success = coordinator.connect_stream("rtmp://test.com/stream", StreamType.RTMP)

            assert success is True
            assert coordinator.current_stream_url == "rtmp://test.com/stream"
            # Simulate connection status change signal
            coordinator._on_connection_status_changed(True, "Connected")
            assert coordinator.is_connected is True

    def test_disconnect_stream(self, mock_logger, mock_stream_manager):
        """Test stream disconnection."""
        coordinator = StreamCoordinator(mock_logger)

        # Mock StreamManager to return our mock and have connect_to_stream return True
        mock_stream_manager.connect_to_stream = Mock(return_value=True)
        mock_stream_manager.disconnect_stream = Mock()
        mock_stream_manager.frameReceived = Mock()
        mock_stream_manager.connectionChanged = Mock()

        with patch('core.controllers.streaming.components.StreamCoordinator.StreamManager', return_value=mock_stream_manager):
            coordinator.connect_stream("rtmp://test.com/stream", StreamType.RTMP)
            coordinator.disconnect_stream()

            assert coordinator.is_connected is False
            assert coordinator.current_stream_url == ""
            mock_stream_manager.disconnect_stream.assert_called_once()

    def test_start_recording(self, mock_logger, mock_recording_manager, tmp_path):
        """Test recording start."""
        coordinator = StreamCoordinator(mock_logger)

        # Set connected state (required for recording)
        coordinator.is_connected = True

        # Patch both RecordingConfig and RecordingManager to handle the coordinator's usage
        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingConfig'):
            with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager', return_value=mock_recording_manager):
                # Mock start_recording to return a path string (accepts any arguments)
                # The coordinator calls it without arguments, but actual method requires resolution
                mock_recording_manager.start_recording = Mock(return_value="/tmp/test.mp4")

                success = coordinator.start_recording(str(tmp_path))

                assert success is True
                assert coordinator.recording_manager is not None
                # Verify start_recording was called (even if with wrong signature, mock handles it)
                mock_recording_manager.start_recording.assert_called_once()

                coordinator.stop_recording()

    def test_start_recording_creates_a_session_bundle(self, mock_logger,
                                                      mock_recording_manager, tmp_path):
        """A recording is a folder holding the video plus its record."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager) as manager_cls:
            assert coordinator.start_recording(str(tmp_path)) is True

            bundle = coordinator.recording_bundle_dir
            assert bundle is not None
            assert os.path.isdir(bundle)
            assert os.path.basename(bundle).startswith(BUNDLE_DIR_PREFIX)
            assert os.path.isfile(os.path.join(bundle, MANIFEST_FILE))
            # The video writer records inside the bundle, not beside it.
            manager_cls.assert_called_once_with(bundle)

            coordinator.stop_recording()

    def test_start_recording_records_the_requested_metadata(self, mock_logger,
                                                            mock_recording_manager, tmp_path):
        """What to capture, and the context, reach the bundle's manifest."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        coordinator.current_stream_url = "rtmp://example/live"
        coordinator.stream_info["resolution"] = (1920, 1080)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path), {
                "save_detections": True,
                "save_flight_map": False,
                "algorithm": "ColorDetection",
                "algorithm_options": {"hue": 40},
            })
            bundle = coordinator.recording_bundle_dir
            coordinator.stop_recording()

        manifest = read_manifest(bundle)
        assert manifest["algorithm"] == "ColorDetection"
        assert manifest["algorithm_options"] == {"hue": 40}
        assert manifest["source"]["url"] == "rtmp://example/live"
        assert manifest["video"]["resolution"] == [1920, 1080]
        assert manifest["options"]["save_flight_map"] is False

    def test_failed_video_start_does_not_leave_an_open_bundle(self, mock_logger,
                                                              mock_recording_manager, tmp_path):
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        mock_recording_manager.start_recording = Mock(return_value=False)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            assert coordinator.start_recording(str(tmp_path)) is False

        assert coordinator.session_writer is None
        assert coordinator.recording_bundle_dir is None

    def test_unwritable_directory_still_records_video(self, mock_logger,
                                                      mock_recording_manager, tmp_path):
        """A bundle that cannot be created must not cost the recording."""
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        target = str(blocker / "bundles")
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        errors = []
        coordinator.errorOccurred.connect(errors.append)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager) as manager_cls:
            assert coordinator.start_recording(target) is True

        assert coordinator.recording_bundle_dir is None
        assert coordinator.session_writer is None
        manager_cls.assert_called_once_with(target)
        assert errors and "detections" in errors[0]

    def test_stop_recording(self, mock_logger, mock_recording_manager, tmp_path):
        """Test recording stop."""
        coordinator = StreamCoordinator(mock_logger)

        # Set connected state (required for recording)
        coordinator.is_connected = True

        # Patch both RecordingConfig and RecordingManager to handle the coordinator's usage
        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingConfig'):
            with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager', return_value=mock_recording_manager):
                # Mock start_recording to return a path string (accepts any arguments)
                mock_recording_manager.start_recording = Mock(return_value="/tmp/test.mp4")
                # Mock stop_recording to return a path string
                mock_recording_manager.stop_recording = Mock(return_value="/tmp/test.mp4")

                # Start recording first
                coordinator.start_recording(str(tmp_path))
                # Verify it was started
                assert coordinator.recording_manager is not None
                assert coordinator.is_recording is True

                # Now stop it
                coordinator.stop_recording()

                # Recording manager should still exist (not cleared until disconnect)
                assert coordinator.recording_manager is not None
                mock_recording_manager.stop_recording.assert_called_once()

    def test_stop_recording_finalizes_the_bundle(self, mock_logger,
                                                 mock_recording_manager, tmp_path, qapp):
        """Stopping derives the bundle's artifacts and announces them."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        results = []
        coordinator.recordingBundleReady.connect(results.append)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))
            coordinator.append_detection_record(_detection_record())
            coordinator.append_telemetry({"aircraft_latitude": 30.0, "aircraft_longitude": -97.0})
            coordinator.append_telemetry({"aircraft_latitude": 30.1, "aircraft_longitude": -97.1})
            bundle = coordinator.recording_bundle_dir
            coordinator.stop_recording()

        assert len(results) == 1
        result = results[0]
        assert result["bundle_dir"] == bundle
        assert result["counts"]["detections_stored"] == 1
        assert result["counts"]["telemetry_fixes"] == 2
        assert result["artifacts"]["detections_csv"] == "detections.csv"
        assert result["artifacts"]["flight_map_html"] == "flight_map.html"
        assert os.path.isfile(os.path.join(bundle, "ADIAT_Data.xml"))
        # The writer is released, so a second stop is a no-op.
        assert coordinator.session_writer is None

    def test_recorder_initiated_stop_still_finalizes_the_bundle(
            self, mock_logger, mock_recording_manager, tmp_path, qapp):
        """A recording error stops the recorder without anyone calling stop.

        The operator's later Stop then returned early, so the bundle was
        never derived and the writer thread was left running.
        """
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        results = []
        coordinator.recordingBundleReady.connect(results.append)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))
            coordinator.append_detection_record(_detection_record())
            bundle = coordinator.recording_bundle_dir

            # What VideoRecorder does on a frame-write or rotation failure.
            coordinator._on_recording_manager_state_changed(False, "Error: disk full")

        assert coordinator.is_recording is False
        assert coordinator.session_writer is None
        assert len(results) == 1
        assert results[0]["counts"]["detections_stored"] == 1
        assert os.path.isfile(os.path.join(bundle, "detections.csv"))

        # The operator's Stop afterwards is a harmless no-op.
        assert coordinator.stop_recording() is None
        assert len(results) == 1

    def test_recorder_error_also_winds_the_recorder_down(
            self, mock_logger, mock_recording_manager, tmp_path, qapp):
        """A failed segment rotation leaves the recorder thread spinning.

        It reports the error but never sets its own stop flag, and clearing
        is_recording makes the operator's Stop return early - so this is the
        only chance to shut it down.
        """
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))
            mock_recording_manager.stop_recording.reset_mock()

            coordinator._on_recording_manager_state_changed(
                False, "Error: Failed to rotate recording segment"
            )

        mock_recording_manager.stop_recording.assert_called_once()

    def test_normal_stop_finalizes_exactly_once(self, mock_logger,
                                                mock_recording_manager, tmp_path, qapp):
        """Both stop paths finalize, so neither may double-report."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        results = []
        coordinator.recordingBundleReady.connect(results.append)

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))
            coordinator.stop_recording()
            # The recorder's own stopped-report arrives afterwards.
            coordinator._on_recording_manager_state_changed(False, "Completed: 3.0s")

        assert len(results) == 1

    def test_capture_calls_outside_a_recording_are_ignored(self, mock_logger):
        """Detections and telemetry arrive constantly; only recordings keep them."""
        coordinator = StreamCoordinator(mock_logger)

        coordinator.append_detection_record(_detection_record())
        coordinator.append_telemetry({"aircraft_latitude": 1.0, "aircraft_longitude": 2.0})

        assert coordinator.session_writer is None
        assert coordinator.recorded_frame_index() is None

    def test_record_frame_counts_raw_detections(self, mock_logger, mock_recording_manager,
                                                sample_frame, tmp_path):
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))
            coordinator.record_frame(sample_frame, [{}, {}], 1.5)
            coordinator.record_frame(sample_frame, [], 1.6)

            assert coordinator.session_writer.counts["frames_recorded"] == 2
            assert coordinator.session_writer.counts["raw_detections"] == 2
            mock_recording_manager.add_frame.assert_called()

            coordinator.stop_recording()

    def test_recorded_frame_index_reports_the_writers_count(self, mock_logger,
                                                            mock_recording_manager, tmp_path):
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_connected = True
        mock_recording_manager.get_recording_info = Mock(return_value={"total_frames": 412})

        with patch('core.controllers.streaming.components.StreamCoordinator.RecordingManager',
                   return_value=mock_recording_manager):
            coordinator.start_recording(str(tmp_path))

            assert coordinator.recorded_frame_index() == 412

            coordinator.stop_recording()

    def test_connection_changed_signal(self, mock_logger, qapp):
        """Test connection changed signal."""
        coordinator = StreamCoordinator(mock_logger)

        # Create signal spy
        connection_state = None
        connection_message = None

        def on_connection_changed(connected, message):
            nonlocal connection_state, connection_message
            connection_state = connected
            connection_message = message

        coordinator.connectionChanged.connect(on_connection_changed)

        # Note: In a real test with qtbot, we'd use qtbot.waitSignal
        # For now, we just verify the signal exists
        assert coordinator.connectionChanged is not None

    def test_frame_received_signal(self, mock_logger, qapp, sample_frame):
        """Test frame received signal."""
        coordinator = StreamCoordinator(mock_logger)

        # Verify signal exists
        assert coordinator.frameReceived is not None

        # Simulate frame emission (would normally come from stream manager)
        coordinator.frameReceived.emit(sample_frame, 0.0, 0)

        # Signal should be emitted (async, so we just verify it exists)

    def test_frame_ready_does_not_record_raw_frame(self, mock_logger, sample_frame):
        """Recorded output should be controlled by StreamViewerWindow display path."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_recording = True
        coordinator.record_frame = Mock()

        coordinator._on_frame_ready(sample_frame, 1.25, 12)

        coordinator.record_frame.assert_not_called()

    def test_frame_signal_after_disconnect_is_not_forwarded(self, mock_logger, sample_frame):
        """A retained manager cannot forward frames while marked disconnected."""
        class FrameEmitter(QObject):
            frameReady = Signal(np.ndarray, float, int)

        coordinator = StreamCoordinator(mock_logger)
        emitter = FrameEmitter()
        coordinator.stream_manager = emitter
        coordinator.is_connected = False
        received = Mock()
        coordinator.frameReceived.connect(received)
        emitter.frameReady.connect(coordinator._on_frame_ready)

        emitter.frameReady.emit(sample_frame, 1.25, 12)

        received.assert_not_called()

    def test_replaced_manager_frame_is_not_forwarded(self, mock_logger, sample_frame):
        """A stale manager cannot forward a queued frame into a new session."""
        class FrameEmitter(QObject):
            frameReady = Signal(np.ndarray, float, int)

        coordinator = StreamCoordinator(mock_logger)
        stale_emitter = FrameEmitter()
        coordinator.stream_manager = FrameEmitter()
        coordinator.is_connected = True
        received = Mock()
        coordinator.frameReceived.connect(received)
        stale_emitter.frameReady.connect(coordinator._on_frame_ready)

        stale_emitter.frameReady.emit(sample_frame, 1.25, 12)

        received.assert_not_called()

    def test_update_fps_limit_returns_false_without_stream_manager(self, mock_logger):
        """FPS update should fail safely when no stream is active."""
        coordinator = StreamCoordinator(mock_logger)

        assert coordinator.update_fps_limit(15) is False

    def test_update_fps_limit_applies_when_supported(self, mock_logger):
        """FPS update should delegate to StreamManager when available."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.stream_manager = Mock()
        coordinator.stream_manager.set_fps_limit = Mock(return_value=True)

        assert coordinator.update_fps_limit(20) is True
        coordinator.stream_manager.set_fps_limit.assert_called_once_with(20)

    def test_connection_drop_stops_active_recording(self, mock_logger):
        """Unexpected disconnect should stop recording gracefully."""
        coordinator = StreamCoordinator(mock_logger)
        coordinator.is_recording = True
        coordinator.stop_recording = Mock()

        coordinator._on_connection_status_changed(False, "Disconnected")

        coordinator.stop_recording.assert_called_once()
        assert coordinator.is_connected is False

    def test_recording_stats_forwarded(self, mock_logger):
        """Recording stats should be forwarded to UI listeners."""
        coordinator = StreamCoordinator(mock_logger)
        received = []
        coordinator.recordingStatsUpdated.connect(received.append)

        payload = {"recording_fps": 24.0, "frame_count": 10}
        coordinator._on_recording_manager_stats(payload)

        assert received == [payload]

    def test_webrtc_source_uses_flight_stream_manager(self, mock_logger):
        """ADIAT Flight feeds are WebRTC; OpenCV cannot open them.

        The coordinator must pick the WebRTC-backed manager for that
        source type and the OpenCV-backed one for everything else.
        """
        coordinator = StreamCoordinator(mock_logger)

        assert isinstance(
            coordinator._create_stream_manager(StreamType.WEBRTC),
            FlightStreamManager,
        )
        for stream_type in (StreamType.FILE, StreamType.HDMI_CAPTURE, StreamType.RTMP):
            manager = coordinator._create_stream_manager(stream_type)
            assert isinstance(manager, StreamManager)
            assert not isinstance(manager, FlightStreamManager)

    def test_connect_stream_routes_adiat_flight_label_to_flight_manager(self, mock_logger):
        """The canonical source label resolves without the caller mapping it."""
        coordinator = StreamCoordinator(mock_logger)
        flight_manager = Mock()
        flight_manager.connect_to_stream = Mock(return_value=True)

        with patch.object(
            StreamCoordinator, "_create_stream_manager", return_value=flight_manager
        ) as create:
            assert coordinator.connect_stream("K7QM3P", "ADIAT Flight") is True

        create.assert_called_once_with(StreamType.WEBRTC)
        assert coordinator.current_stream_type == StreamType.WEBRTC
        assert coordinator.current_stream_url == "K7QM3P"
        flight_manager.connect_to_stream.assert_called_once_with(
            "K7QM3P", StreamType.WEBRTC, hdmi_backend=None, fps_limit=None
        )

    def test_connect_stream_still_resolves_legacy_string_labels(self, mock_logger):
        """Pre-existing lowercase/alias labels must keep working."""
        coordinator = StreamCoordinator(mock_logger)
        manager = Mock()
        manager.connect_to_stream = Mock(return_value=True)

        with patch.object(StreamCoordinator, "_create_stream_manager", return_value=manager):
            coordinator.connect_stream("rtmp://host/app/key", "rtmp")

        assert coordinator.current_stream_type == StreamType.RTMP
