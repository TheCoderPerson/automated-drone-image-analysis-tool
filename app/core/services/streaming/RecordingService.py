"""One recording, end to end: the video writer plus its session bundle.

Extracted from ``StreamCoordinator`` so the same recording lifecycle can
serve two very different owners:

* the **streaming window**, which records the single stream it is
  connected to (``StreamCoordinator`` now delegates here); and
* the **Flight Viewer**, where every tile owns its own instance — each
  inbound feed is independently recordable, and two drones recording at
  once produce two separate bundles with no shared state.

The service owns exactly one recording at a time:

1. :meth:`start` creates the bundle folder (via
   :class:`~core.services.streaming.RecordingSessionService.\
RecordingSessionWriter`), points a
   :class:`~core.services.streaming.VideoRecordingService.VideoRecorder`
   at it, and seeds the manifest from the caller's metadata.
2. :meth:`add_frame` / :meth:`append_detection` / :meth:`append_telemetry`
   capture as the flight happens.
3. :meth:`stop` releases the video writer, closes the live logs, derives
   the finished artifacts (:func:`~core.services.streaming.\
RecordingBundleService.finalize_bundle`) and announces the result on
   :attr:`recordingBundleReady`.

The recorder can also stop itself — a frame-write failure or a failed
segment rotation reports through ``recordingStateChanged(False, ...)``
without anyone calling :meth:`stop`. That path winds the recorder down
and finalizes too, so a recording interrupted by an error still yields
its artifacts instead of a folder of raw logs.

Every instance is fully independent: separate video writer, separate
bundle directory, separate session logs. Nothing here is process-global,
which is the property the Flight Viewer's per-tile recording rests on.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from core.services.LoggerService import LoggerService
from core.services.streaming.RecordingBundleService import finalize_bundle
from core.services.streaming.RecordingSessionService import (
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
)
from core.services.streaming.VideoRecordingService import RecordingManager


class RecordingService(QObject):
    """Owns the lifecycle of a single recording and its bundle."""

    recordingStateChanged = Signal(bool, str)   # (recording, path_or_message)
    recordingStatsUpdated = Signal(dict)        # live encoder stats
    recordingBundleReady = Signal(dict)         # finalize_bundle result
    errorOccurred = Signal(str)

    def __init__(self, logger: Optional[LoggerService] = None, parent=None,
                 library=None):
        super().__init__(parent)
        self.logger = logger or LoggerService()
        # RecordingLibrary (or None). Production owners pass one so every
        # finished bundle shows up in the Replay window's picker; tests
        # omit it so they never touch the user's persisted library.
        self._library = library

        # Video writer. Kept (not cleared) after stop so callers can
        # inspect the finished recording; replaced on the next start.
        self.recording_manager: Optional[RecordingManager] = None
        self.is_recording = False
        self.current_recording_path = ""

        # Session bundle: the folder this recording's video, detections,
        # telemetry and derived artifacts all live in.
        self.session_writer: Optional[RecordingSessionWriter] = None
        self.recording_bundle_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self, output_directory: str, resolution, metadata: Optional[dict] = None) -> bool:
        """Start recording into a fresh bundle under ``output_directory``.

        Args:
            output_directory: Directory the recording bundle is created in.
            resolution: ``(width, height)`` the video writer is sized to.
                Mismatched frames are downscaled to it, so pass the
                source resolution, not a display size.
            metadata: What to capture and the context for the manifest.
                Recognized keys: ``save_detections``, ``save_flight_map``,
                ``frame_level_detections``, ``algorithm``,
                ``algorithm_options``, ``source_url``, ``source_type``,
                ``fps_limit``, and ``feed`` (a dict identifying the feed —
                label, aircraft — recorded verbatim in the manifest and
                used to name the bundle folder).

        Returns:
            True if recording started successfully.
        """
        if self.is_recording:
            self.errorOccurred.emit("Recording already in progress")
            return False

        try:
            resolution = tuple(resolution) if resolution else (0, 0)
            if not resolution or resolution == (0, 0):
                resolution = (1280, 720)

            # Create the session bundle and record the video inside it. A
            # bundle that cannot be created is not worth failing the
            # recording over - fall back to the caller's directory and
            # write video only.
            bundle_dir = self._start_session_bundle(output_directory, metadata, resolution)
            video_dir = bundle_dir or output_directory

            self.recording_manager = RecordingManager(video_dir)
            # Connect signals BEFORE starting so we catch the initial
            # recording-started signal.
            self.recording_manager.recordingStateChanged.connect(
                self._on_manager_state_changed
            )
            if hasattr(self.recording_manager, "recordingStats"):
                try:
                    self.recording_manager.recordingStats.connect(self._on_manager_stats)
                except Exception:
                    pass

            success = self.recording_manager.start_recording(resolution)
            if success:
                self.is_recording = True
                return True

            self.is_recording = False
            # The video never started, so the bundle would only ever hold
            # an empty manifest. Close it out rather than leaving an
            # orphan folder behind.
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
            source_url=str(meta.get("source_url") or ""),
            source_type=str(meta.get("source_type") or ""),
            resolution=tuple(resolution),
            fps_limit=meta.get("fps_limit"),
            feed=dict(meta.get("feed") or {}),
        )
        writer = RecordingSessionWriter(self.logger)
        self.session_writer = writer
        self.recording_bundle_dir = writer.start_session(config)
        if self.recording_bundle_dir is None:
            # Video still records to the caller's directory, but nothing
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
        removes the folder when it holds no content, so a failed start
        does not leave an empty recording behind.
        """
        if self.session_writer is not None:
            self.session_writer.discard()
            self.session_writer = None
        self.recording_bundle_dir = None

    def stop(self) -> Optional[str]:
        """Stop recording, finalize the bundle, and announce the result.

        Returns:
            Path to the recorded video file if a recording was active,
            None otherwise.
        """
        if not self.is_recording or not self.recording_manager:
            return None

        try:
            recording_path = self.current_recording_path

            # The caller asked to stop, so the service is no longer
            # recording from this line - not when the recorder thread's
            # queued stopped-signal eventually lands. Frames arriving in
            # that gap must already be refused. The signal still fires and
            # finds everything below idempotent.
            self.is_recording = False

            # Stop the video writer. The manager reference is kept for
            # inspection; it is replaced on the next start.
            self.recording_manager.stop_recording()

            # Close the bundle's live logs, then derive its finished
            # artifacts. Ordering matters: the video writer has already
            # been released above, so the manifest can list the files
            # that were actually written.
            self._finalize_session_bundle()

            return recording_path

        except Exception as e:
            error_msg = f"Error stopping recording: {str(e)}"
            self.logger.error(error_msg)
            self.errorOccurred.emit(error_msg)
            return None

    def cleanup(self) -> None:
        """Stop any active recording and release resources."""
        if self.is_recording:
            self.stop()
        # A recording stopped above already finalized its bundle; this
        # catches a bundle opened for a recording that never started.
        self._discard_session_bundle()

    # ------------------------------------------------------------------
    # capture
    # ------------------------------------------------------------------

    def add_frame(self, frame: np.ndarray, detection_count: int = 0,
                  video_time_seconds: Optional[float] = None) -> None:
        """Record one frame (if recording is active).

        Args:
            frame: BGR frame to record.
            detection_count: Raw detections drawn on this frame. Not
                stored individually - the stored record is the confirmed
                detection (see :meth:`append_detection`) - but counted so
                the manifest reports how much activity the run saw.
            video_time_seconds: Source playback position, for frame-level
                logging when it was explicitly asked for.
        """
        if self.is_recording and self.recording_manager:
            self.recording_manager.add_frame(frame)
            if self.session_writer is not None:
                self.session_writer.note_frame(detection_count, video_time_seconds)

    def append_detection(self, record: DetectionRecord) -> None:
        """Store one confirmed detection in the active recording's bundle."""
        if self.is_recording and self.session_writer is not None:
            self.session_writer.append_detection(record)

    def append_telemetry(self, envelope: dict) -> None:
        """Store one telemetry fix, stamped with the recorded video's clock.

        Wall-clock stamps alone cannot align replay: the video writer
        splices connection gaps out (no frames arrive, none are written),
        so after an outage the MP4's timeline is shorter than wall time by
        the outage - and every wall-clock cue after it would lag the
        picture for the rest of the replay. Stamping each fix with the
        writer's frame count at arrival puts telemetry on the same clock
        as the video, so gaps compress identically in both.
        """
        if not (self.is_recording and self.session_writer is not None):
            return
        stamped = dict(envelope) if isinstance(envelope, dict) else envelope
        frames = self.recorded_frame_index()
        if isinstance(stamped, dict) and frames is not None:
            stamped["recorded_frame_index"] = frames
            fps = self._configured_fps()
            if fps:
                stamped["recorded_video_seconds"] = frames / fps
        self.session_writer.append_telemetry(stamped)

    def _configured_fps(self) -> Optional[float]:
        """The video writer's fixed frame rate, or None when unknowable."""
        manager = self.recording_manager
        accessor = getattr(manager, "configured_fps", None)
        if accessor is None:
            return None
        try:
            fps = float(accessor())
        except Exception:  # noqa: BLE001 - test doubles may not implement this
            return None
        return fps if fps > 0 else None

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

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _finalize_session_bundle(self) -> None:
        """Close the session logs and derive the bundle's artifacts.

        Synchronous on purpose. Stopping a recording already blocks while
        the video writer flushes and releases its file (up to five
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

        if self._library is not None:
            try:
                self._library.remember(bundle_dir)
            except Exception as exc:  # noqa: BLE001 - the library is a convenience
                self.logger.warning(f"Could not register recording in library: {exc}")

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

    def _on_manager_state_changed(self, recording: bool, path_or_message: str) -> None:
        """Handle recording state changes from the video writer."""
        if recording:
            # Recording started - path_or_message is the actual file path.
            self.current_recording_path = path_or_message
        else:
            self.is_recording = False
            # The recorder can stop itself: a frame-write failure or a
            # failed segment rotation reports here without anyone calling
            # stop(). Both are handled from this side too, because
            # clearing is_recording above makes a later stop() return
            # early - so this is the only chance to wind the recording
            # down properly.
            #
            # First make sure the recorder thread is actually finished. A
            # failed segment rotation reports the error but leaves the
            # thread spinning with no writer, and nothing else ever sets
            # its stop flag. A no-op when the recorder already stopped on
            # its own.
            if self.recording_manager is not None:
                try:
                    self.recording_manager.stop_recording()
                except Exception as exc:  # noqa: BLE001 - already an error path
                    self.logger.error(f"Error stopping recorder after failure: {exc}")
            # Then close out the bundle, so the operator still gets what
            # was recorded before the failure instead of a folder of raw
            # logs. Idempotent - the normal stop path finds nothing left
            # to do.
            self._finalize_session_bundle()

        self.recordingStateChanged.emit(recording, path_or_message)

    def _on_manager_stats(self, stats: dict) -> None:
        """Forward live recording stats to UI consumers."""
        if isinstance(stats, dict):
            self.recordingStatsUpdated.emit(stats)


__all__ = ["RecordingService"]
