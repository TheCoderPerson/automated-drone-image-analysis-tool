"""
StreamCoordinator - Manages stream connection, recording, and frame flow.

This component handles all the plumbing for streaming detection:
- Stream connection/disconnection
- Recording start/stop, including the recording's session bundle
- Frame queue management
- Coordinate frame flow from stream to algorithm to display

A recording is a *bundle*, not a bare file: the coordinator creates one
folder per recording (see
:mod:`~core.services.streaming.RecordingSessionService`), points the video
writer at it, and accepts detections and telemetry fixes alongside the
frames so the folder ends up holding the record of what was found and
where the aircraft flew. The finished artifacts are derived when the
recording stops.
"""

from PySide6.QtCore import QObject, Signal
from typing import Optional, Callable
import numpy as np

from core.services.LoggerService import LoggerService
from core.services.streaming.RTMPStreamService import (
    StreamManager,
    StreamType,
    stream_type_from_source_label,
)
from core.services.streaming.FlightStreamService import FlightStreamManager
from core.services.streaming.VideoRecordingService import RecordingManager, RecordingConfig
from core.services.streaming.RecordingBundleService import finalize_bundle
from core.services.streaming.RecordingSessionService import (
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
)
from helpers import FeatureFlags


class StreamCoordinator(QObject):
    """
    Coordinates streaming, recording, and frame processing.

    This class manages the lifecycle of a streaming session including:
    - Connecting/disconnecting from streams
    - Starting/stopping recording
    - Routing frames from stream to algorithm
    - Coordinating frame processing flow
    """

    # Signals
    connectionChanged = Signal(bool, str)  # (connected, message)
    frameReceived = Signal(np.ndarray, float, int)  # (frame, timestamp, video_frame_pos)
    recordingStateChanged = Signal(bool, str)  # (recording, path)
    recordingStatsUpdated = Signal(dict)  # Recording performance/queue stats
    recordingBundleReady = Signal(dict)  # finalize_bundle result for the finished recording
    streamInfoUpdated = Signal(dict)  # Stream info (fps, resolution, etc.)
    errorOccurred = Signal(str)  # Error message
    seekCompleted = Signal(int, int, bool)  # (request_id, frame_position, success)
    telemetryReceived = Signal(dict)  # Live aircraft telemetry (ADIAT Flight)

    def __init__(self, logger: Optional[LoggerService] = None):
        super().__init__()

        self.logger = logger or LoggerService()

        # Stream management
        self.stream_manager: Optional[StreamManager] = None
        self.is_connected = False
        self.current_stream_url = ""
        self.current_stream_type: Optional[StreamType] = None

        # Recording management
        self.recording_manager: Optional[RecordingManager] = None
        self.is_recording = False
        self.current_recording_path = ""

        # Session bundle: the folder this recording's video, detections,
        # telemetry and derived artifacts all live in.
        self.session_writer: Optional[RecordingSessionWriter] = None
        self.recording_bundle_dir: Optional[str] = None

        # Stream info
        self.stream_info = {
            'fps': 0.0,
            'resolution': (0, 0),
            'latency': 0.0,
            'dropped_frames': 0
        }

    def connect_stream(self, url: str, stream_type: StreamType,
                       hdmi_backend: Optional[int] = None,
                       fps_limit: Optional[int] = None) -> bool:
        """
        Connect to a stream.

        Args:
            url: Stream URL, file path, or — for ADIAT Flight — the pairing code
            stream_type: Type of stream (RTMP, HLS, File, HDMI, ADIAT Flight) -
                can be a StreamType enum or a canonical source label
            hdmi_backend: Optional OpenCV backend ID for HDMI capture
            fps_limit: Optional target FPS limit (`None`/`0` = safe default cap,
                `>0` = explicit cap)

        Returns:
            True if connection initiated successfully
        """
        try:
            # Disconnect existing stream if any
            if self.stream_manager:
                self.disconnect_stream()

            # Handle both enum and string (canonical source label) types
            stream_type = stream_type_from_source_label(stream_type)

            # self.logger.info(f"Connecting to {stream_type.value} stream: {url}")

            # Create the manager that backs this source type. ADIAT Flight
            # feeds arrive over WebRTC, which OpenCV cannot open, so they use
            # a dedicated manager exposing the same signals/methods.
            self.stream_manager = self._create_stream_manager(stream_type)
            if self.stream_manager is None:
                # Transport unavailable in this build (see
                # _create_stream_manager). Already logged; fail quietly
                # rather than popping a modal for a disabled feature.
                self.connectionChanged.emit(False, "Source unavailable")
                return False

            # Connect signals
            self.stream_manager.frameReceived.connect(self._on_frame_ready)
            self.stream_manager.connectionChanged.connect(self._on_connection_status_changed)
            # StreamManager provides stats and video position updates
            if hasattr(self.stream_manager, "statsUpdated"):
                self.stream_manager.statsUpdated.connect(self._on_stream_stats_updated)
            if hasattr(self.stream_manager, "videoPositionChanged"):
                self.stream_manager.videoPositionChanged.connect(self._on_video_position_changed)
            if hasattr(self.stream_manager, "seekCompleted"):
                self.stream_manager.seekCompleted.connect(self.seekCompleted)
            # Only the ADIAT Flight manager publishes live telemetry; the
            # OpenCV-backed manager has no such signal.
            if hasattr(self.stream_manager, "telemetryReceived"):
                self.stream_manager.telemetryReceived.connect(self.telemetryReceived)

            # Connect to stream (pass hdmi_backend for HDMI capture, fps_limit for rate control)
            if self.stream_manager.connect_to_stream(url, stream_type, hdmi_backend=hdmi_backend, fps_limit=fps_limit):
                self.current_stream_url = url
                self.current_stream_type = stream_type
                # self.logger.info("Stream connection initiated")
                return True
            else:
                self.logger.error("Failed to start stream")
                self.errorOccurred.emit("Failed to start stream")
                return False

        except Exception as e:
            error_msg = f"Error connecting to stream: {str(e)}"
            self.logger.error(error_msg)
            self.errorOccurred.emit(error_msg)
            return False

    def _create_stream_manager(self, stream_type: StreamType):
        """Build the manager appropriate to ``stream_type``.

        Kept as a single, explicit two-way branch rather than a registry:
        there are exactly two transports (OpenCV-backed and WebRTC-backed)
        and the ADIAT Flight path needs no per-algorithm configuration.
        Both managers expose the identical signal/method surface, so every
        caller downstream of this method is transport-agnostic.

        The WebRTC transport is gated on the Flight Viewer feature flag.
        The UI already hides the source when it is off; this is the
        backstop for a stale persisted ``StreamingSourceType`` or a direct
        caller, so a disabled feature can never spin up a pairing session.

        Returns None when the requested transport is unavailable. It
        deliberately does not raise: an exception here surfaces through
        ``connect_stream``'s handler as a modal error dialog, and a
        feature that is simply switched off in this build is not an error
        worth interrupting the operator for.
        """
        if stream_type == StreamType.WEBRTC:
            if not FeatureFlags.FLIGHT_VIEWER_ENABLED:
                self.logger.warning(
                    "Ignoring ADIAT Flight source request: "
                    "FLIGHT_VIEWER_ENABLED is off in this build"
                )
                return None
            return FlightStreamManager()
        return StreamManager()

    def disconnect_stream(self):
        """Disconnect from current stream."""
        if self.stream_manager:
            # self.logger.info("Disconnecting stream")

            # Stop recording if active
            if self.is_recording:
                self.stop_recording()

            # Disconnect signals
            try:
                self.stream_manager.frameReceived.disconnect(self._on_frame_ready)
                self.stream_manager.connectionChanged.disconnect(self._on_connection_status_changed)
                if hasattr(self.stream_manager, "statsUpdated"):
                    try:
                        self.stream_manager.statsUpdated.disconnect(self._on_stream_stats_updated)
                    except TypeError:
                        pass
                if hasattr(self.stream_manager, "videoPositionChanged"):
                    try:
                        self.stream_manager.videoPositionChanged.disconnect(self._on_video_position_changed)
                    except TypeError:
                        pass
                if hasattr(self.stream_manager, "seekCompleted"):
                    try:
                        self.stream_manager.seekCompleted.disconnect(self.seekCompleted)
                    except TypeError:
                        pass
                if hasattr(self.stream_manager, "telemetryReceived"):
                    try:
                        self.stream_manager.telemetryReceived.disconnect(self.telemetryReceived)
                    except TypeError:
                        pass
            except Exception:
                pass

            # Disconnect stream
            self.stream_manager.disconnect_stream()
            self.stream_manager = None

            self.is_connected = False
            self.current_stream_url = ""
            self.current_stream_type = None

            self.connectionChanged.emit(False, "Disconnected")

    def update_fps_limit(self, fps_limit: Optional[int]) -> bool:
        """
        Update active stream FPS limit while connected.

        Args:
            fps_limit: Requested FPS limit (`None`/`0` = safe default cap)

        Returns:
            True if update applied, False otherwise.
        """
        if not self.stream_manager:
            return False
        if not hasattr(self.stream_manager, "set_fps_limit"):
            return False
        try:
            return bool(self.stream_manager.set_fps_limit(fps_limit))
        except Exception as e:
            self.logger.error(f"Failed to update FPS limit: {e}")
            self.errorOccurred.emit(f"Failed to update FPS limit: {e}")
            return False

    def start_recording(self, output_directory: str, metadata: Optional[dict] = None) -> bool:
        """
        Start recording the stream.

        Args:
            output_directory: Directory the recording bundle is created in
            metadata: What to capture alongside the video, and the context
                to record in the bundle's manifest. Recognized keys:
                ``save_detections``, ``save_flight_map``,
                ``frame_level_detections``, ``algorithm``,
                ``algorithm_options``. Source, resolution and FPS cap are
                filled in from the live stream rather than passed in.

        Returns:
            True if recording started successfully
        """
        if not self.is_connected:
            self.errorOccurred.emit("Cannot record: not connected to stream")
            return False

        if self.is_recording:
            self.errorOccurred.emit("Recording already in progress")
            return False

        try:
            # self.logger.info(f"Starting recording to: {output_directory}")

            # Determine recording resolution from stream info
            resolution = self.stream_info.get('resolution', (0, 0))
            if not resolution or resolution == (0, 0):
                resolution = (1280, 720)

            # Create the session bundle and record the video inside it. A
            # bundle that cannot be created is not worth failing the
            # recording over - fall back to the operator's directory and
            # write video only, exactly as before this existed.
            bundle_dir = self._start_session_bundle(output_directory, metadata, resolution)
            video_dir = bundle_dir or output_directory

            # Create recording manager (expects output directory path)
            self.recording_manager = RecordingManager(video_dir)
            # Connect signals BEFORE starting so we catch the initial recording started signal
            self.recording_manager.recordingStateChanged.connect(self._on_recording_manager_state_changed)
            if hasattr(self.recording_manager, "recordingStats"):
                try:
                    self.recording_manager.recordingStats.connect(self._on_recording_manager_stats)
                except Exception:
                    pass

            # Start recording
            success = self.recording_manager.start_recording(resolution)
            if success:
                self.is_recording = True
                # self.logger.info(f"Recording started in: {output_directory}")
                return True
            else:
                self.is_recording = False
                # The video never started, so the bundle would only ever
                # hold an empty manifest. Close it out rather than leaving
                # an orphan folder behind.
                self._discard_session_bundle()
                self.errorOccurred.emit("Failed to start recording")
                return False

        except Exception as e:
            error_msg = f"Error starting recording: {str(e)}"
            self.logger.error(error_msg)
            self._discard_session_bundle()
            self.errorOccurred.emit(error_msg)
            return False

    def _start_session_bundle(self, output_directory: str, metadata: Optional[dict],
                              resolution) -> Optional[str]:
        """Create this recording's bundle directory and start its writer."""
        meta = metadata or {}
        config = RecordingSessionConfig(
            root_dir=output_directory,
            save_detections=bool(meta.get("save_detections", True)),
            save_flight_map=bool(meta.get("save_flight_map", True)),
            frame_level_detections=bool(meta.get("frame_level_detections", False)),
            algorithm=str(meta.get("algorithm") or ""),
            algorithm_options=dict(meta.get("algorithm_options") or {}),
            source_url=self.current_stream_url,
            source_type=self.current_stream_type.value if self.current_stream_type else "",
            resolution=tuple(resolution),
            fps_limit=self.stream_info.get("fps_limit"),
        )
        writer = RecordingSessionWriter(self.logger)
        self.session_writer = writer
        self.recording_bundle_dir = writer.start_session(config)
        if self.recording_bundle_dir is None:
            # Video still records to the operator's directory, but nothing
            # else will be kept - worth interrupting for, because the
            # alternative is finding out after the flight.
            self.session_writer = None
            self.errorOccurred.emit(
                "Could not create the recording folder, so detections and the "
                f"flight map will not be saved: {writer.last_error or 'unknown error'}"
            )
        return self.recording_bundle_dir

    def _discard_session_bundle(self) -> None:
        """Tear down a session bundle that never got a recording.

        Unlike :meth:`_finalize_session_bundle` this derives nothing and
        removes the folder when it holds no content, so a failed start does
        not leave an empty recording behind.
        """
        if self.session_writer is not None:
            self.session_writer.discard()
            self.session_writer = None
        self.recording_bundle_dir = None

    def stop_recording(self) -> Optional[str]:
        """
        Stop recording.

        Returns:
            Path to recorded file if successful, None otherwise
        """
        if not self.is_recording or not self.recording_manager:
            return None

        try:
            # self.logger.info("Stopping recording")

            # Save the path before stopping
            recording_path = self.current_recording_path

            # Stop recording - the state change will be handled by the signal
            self.recording_manager.stop_recording()

            # Keep recording_manager reference for test compatibility
            # It will be cleaned up on disconnect or next start_recording

            # Close the bundle's live logs, then derive its finished
            # artifacts off-thread. Ordering matters: the video writer has
            # already been released above, so the manifest can list the
            # files that were actually written.
            self._finalize_session_bundle()

            return recording_path

        except Exception as e:
            error_msg = f"Error stopping recording: {str(e)}"
            self.logger.error(error_msg)
            self.errorOccurred.emit(error_msg)
            return None

    def record_frame(self, frame: np.ndarray, detections: Optional[list] = None,
                     video_time_seconds: Optional[float] = None):
        """
        Record a frame (if recording is active).

        Args:
            frame: Frame to record
            detections: Detections drawn on this frame. Not stored
                individually - the stored record is the confirmed track
                (see :meth:`append_detection_record`) - but counted so the
                bundle's manifest reports how much raw activity the run saw.
            video_time_seconds: Source playback position, for frame-level
                logging when the operator asked for it.
        """
        if self.is_recording and self.recording_manager:
            self.recording_manager.add_frame(frame)
            if self.session_writer is not None:
                self.session_writer.note_frame(
                    len(detections) if detections else 0, video_time_seconds
                )

    def append_detection_record(self, record: DetectionRecord) -> None:
        """Store one confirmed detection in the active recording's bundle."""
        if self.is_recording and self.session_writer is not None:
            self.session_writer.append_detection(record)

    def append_telemetry(self, envelope: dict) -> None:
        """Store one telemetry fix in the active recording's bundle."""
        if self.is_recording and self.session_writer is not None:
            self.session_writer.append_telemetry(envelope)

    def recorded_frame_index(self) -> Optional[int]:
        """The video writer's frame count so far, or ``None`` when idle.

        Best-effort: the writer runs at a fixed frame rate and drops
        frames when its queue is full, so this can drift from the source's
        own timeline. Stored alongside - never instead of - the source
        video time.
        """
        if not self.is_recording or not self.recording_manager:
            return None
        info = self.recording_manager.get_recording_info() or {}
        total = info.get("total_frames")
        return int(total) if isinstance(total, (int, float)) else None

    def _finalize_session_bundle(self) -> None:
        """Close the session logs and derive the bundle's artifacts.

        Synchronous on purpose. Stopping a recording already blocks here
        while the video writer flushes and releases its file (up to five
        seconds), so deriving a CSV, an XML file and a map alongside it
        adds no new class of delay - and doing it inline keeps the bundle
        complete even when the app is closing, which a background thread
        could not promise.
        """
        if self.session_writer is None:
            return
        bundle_dir = self.session_writer.finalize()
        self.session_writer = None
        self.recording_bundle_dir = None
        if not bundle_dir:
            return

        try:
            result = finalize_bundle(bundle_dir, self.logger)
        except Exception as exc:  # noqa: BLE001 - a failed export is reported, not raised
            self.logger.error(f"Could not finalize recording bundle {bundle_dir}: {exc}")
            result = {
                "bundle_dir": bundle_dir,
                "artifacts": {},
                "counts": {},
                "errors": [str(exc)],
            }
        self.recordingBundleReady.emit(result)

    def _on_frame_ready(self, frame: np.ndarray, timestamp: float, video_frame_pos: int = 0):
        """Handle frame received from stream."""
        # Signals queued before a disconnect or emitted by a replaced manager
        # must not escape into the viewer. Direct calls have no QObject sender;
        # they are retained for diagnostic/unit-test use.
        sender = self.sender()
        if sender is not None:
            if sender is not self.stream_manager or not self.is_connected:
                return

        # Store video frame position for access by StreamViewerWindow
        self._current_video_frame_pos = video_frame_pos

        # Update stream info
        self._update_stream_info()

        # Emit frame for processing with video position
        self.frameReceived.emit(frame, timestamp, video_frame_pos)

    def _on_connection_status_changed(self, connected: bool, message: str):
        """Handle connection status change."""
        self.is_connected = connected
        if not connected and self.is_recording:
            self.stop_recording()
        self.connectionChanged.emit(connected, message)

    def _on_stream_error(self, error: str):
        """Handle stream error."""
        self.logger.error(f"Stream error: {error}")
        self.errorOccurred.emit(error)

    def _on_stream_stats_updated(self, stats: dict):
        """Handle stats updates from StreamManager/RTMP service."""
        # Merge stats into stream_info dictionary
        self.stream_info.update(stats)
        self.streamInfoUpdated.emit(self.stream_info)

    def _on_video_position_changed(self, current_time: float, total_time: float):
        """Handle video position updates for file playback."""
        self.stream_info["current_time"] = current_time
        self.stream_info["total_time"] = total_time
        self.streamInfoUpdated.emit(self.stream_info)

    def _on_recording_manager_state_changed(self, recording: bool, path_or_message: str):
        """Handle recording state changes from RecordingManager."""
        if recording:
            # Recording started - path_or_message is the actual file path
            self.current_recording_path = path_or_message
            # self.logger.info(f"Recording started: {path_or_message}")
        else:
            # Recording stopped - path_or_message is completion/error message
            self.is_recording = False
            # self.logger.info(f"Recording stopped: {path_or_message}")
            # The recorder can stop itself: a frame-write failure or a failed
            # segment rotation reports here without anyone calling
            # stop_recording(). Both are handled from this side too, because
            # clearing is_recording above makes the operator's later Stop
            # return early - so this is the only chance to wind the recording
            # down properly.
            #
            # First make sure the recorder thread is actually finished. A
            # failed segment rotation reports the error but leaves the thread
            # spinning with no writer, and nothing else ever sets its stop
            # flag. A no-op when the recorder already stopped on its own.
            if self.recording_manager is not None:
                try:
                    self.recording_manager.stop_recording()
                except Exception as exc:  # noqa: BLE001 - already an error path
                    self.logger.error(f"Error stopping recorder after failure: {exc}")
            # Then close out the bundle, so the operator still gets what was
            # recorded before the failure instead of a folder of raw logs.
            # Idempotent - the normal stop path finds nothing left to do.
            self._finalize_session_bundle()

        # Forward to UI
        self.recordingStateChanged.emit(recording, path_or_message)

    def _on_recording_manager_stats(self, stats: dict):
        """Forward live recording stats to UI consumers."""
        if isinstance(stats, dict):
            self.recordingStatsUpdated.emit(stats)

    def _update_stream_info(self):
        """Update stream statistics (polling fallback)."""
        if self.stream_manager:
            # Get info from stream manager/service
            info = self.stream_manager.get_stream_info()
            if info:
                self.stream_info.update(info)
                self.streamInfoUpdated.emit(self.stream_info)

    def get_stream_info(self) -> dict:
        """Get current stream information."""
        return self.stream_info.copy()

    def is_stream_connected(self) -> bool:
        """Check if stream is connected."""
        return self.is_connected

    def is_stream_recording(self) -> bool:
        """Check if recording is active."""
        return self.is_recording

    def cleanup(self):
        """Clean up resources."""
        # self.logger.info("StreamCoordinator cleanup")

        # Stop recording
        if self.is_recording:
            self.stop_recording()

        # A recording stopped by the window closing still has to finish
        # writing its bundle - otherwise the operator loses the artifacts
        # for the flight they just recorded. stop_recording() above already
        # finalized an active one; this catches a bundle opened for a
        # recording that never started.
        self._discard_session_bundle()

        # Disconnect stream
        if self.is_connected:
            self.disconnect_stream()
