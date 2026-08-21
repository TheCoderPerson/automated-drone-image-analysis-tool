"""Recording Replay — a dedicated window for watching a recording bundle.

Watching a recording is not analysis. There is no source to configure, no
detector to tune, and nothing new to detect — the detections were found
live and stored with the flight. So replay gets its own window: the video
with its timeline, the stored detections as a click-to-jump gallery, the
flight on a map, and the telemetry HUD following the playhead. Nothing
else. (Re-*analyzing* a recorded video with different detector settings
remains possible the ordinary way: open the MP4 as a File source in the
streaming analysis window.)

The window composes the same components the live windows already trust —
:class:`StreamCoordinator` drives file playback and seeking,
:class:`StreamingVideoDisplay` renders, :class:`PlaybackControlBar` seeks
(its record toggle hidden: you don't record a replay),
:class:`TrackGalleryWidget` and :class:`FlightMapView` show the stored
record, and :class:`StreamTelemetryCoordinator` replays the bundle's
sidecar SRT against the playhead.

One replay window per app, reused by every entry point — the tile's
"Replay Recording", the analysis window's post-stop Replay button, and
"Open Recording…" pickers — via :func:`open_replay`.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QObject, Slot
from PySide6.QtWidgets import QApplication, QMainWindow

from core.controllers.streaming.components import StreamTelemetryCoordinator
from core.controllers.streaming.components.StreamCoordinator import StreamCoordinator
from core.controllers.streaming.shared_widgets import Track
from core.services.LoggerService import LoggerService
from core.services.streaming.RecordingBundleService import (
    find_bundle_for_video,
    load_replay_detections,
)
from core.services.streaming.RecordingSessionService import read_manifest
from core.services.streaming.contracts import FocusTarget
from core.services.streaming.RTMPStreamService import StreamType
from core.views.components.FlightMapView import FlightMapView
from core.views.flight.TelemetryHud import TelemetryHud
from core.views.streaming.components import PlaybackControlBar, StreamingVideoDisplay
from core.views.streaming.components.TrackGalleryWidget import TrackGalleryWidget
from core.views.streaming.ReplayWindow_ui import Ui_ReplayWindow
from helpers.TranslationMixin import TranslationMixin


class ReplayWindow(TranslationMixin, QMainWindow):
    """Plays one recording bundle: video, detections, telemetry, map."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = LoggerService()
        self.ui = Ui_ReplayWindow()
        self.ui.setupUi(self)
        self._apply_translations()

        self._bundle_dir: Optional[str] = None
        self._tracks_by_key: Dict[str, Track] = {}
        # Zoom armed by a gallery/map click, applied by the frame the seek
        # produces. A request/consume handoff, not a timed guess: the
        # display can only zoom once it actually holds the sought frame.
        self._pending_focus: Optional[FocusTarget] = None

        # Playback engine — the same coordinator the analysis window
        # trusts for file playback, minus everything it does for
        # algorithms (none run here, by design).
        self.coordinator = StreamCoordinator(self.logger)
        self.telemetry_coordinator = StreamTelemetryCoordinator(logger=self.logger)

        # --- video pane -------------------------------------------------
        self.video_display = StreamingVideoDisplay(window=self)
        self.ui.videoLayout.replaceWidget(self.ui.videoPlaceholder, self.video_display)
        self.ui.videoPlaceholder.deleteLater()

        self.playback_controls = PlaybackControlBar()
        # A replay is a finished recording; recording it again is not a
        # thing this window offers.
        self.playback_controls.record_btn.setVisible(False)
        self.ui.videoLayout.replaceWidget(self.ui.playbackPlaceholder, self.playback_controls)
        self.ui.playbackPlaceholder.deleteLater()

        # Telemetry HUD rides the video pane, as it does live - but with
        # staleness tracking off: a replay's fixes are never "late", they
        # are wherever the operator put the playhead, so a "stale 8s"
        # badge would be nonsense.
        self.telemetry_hud = TelemetryHud(self.video_display)
        self.telemetry_hud.set_staleness_tracking(False)
        self.telemetry_hud.setVisible(False)
        self.video_display.installEventFilter(self)

        # --- stored record ----------------------------------------------
        self.gallery_widget = TrackGalleryWidget()
        self.ui.sideSplitter.replaceWidget(
            self.ui.sideSplitter.indexOf(self.ui.galleryPlaceholder), self.gallery_widget
        )
        self.ui.galleryPlaceholder.deleteLater()

        self.map_view = FlightMapView()
        self.ui.sideSplitter.replaceWidget(
            self.ui.sideSplitter.indexOf(self.ui.mapPlaceholder), self.map_view
        )
        self.ui.mapPlaceholder.deleteLater()

        # Roughly two parts gallery to one part map: the map needs enough
        # basemap to place the flight (a sliver tells the operator
        # nothing), while the gallery is the column's working surface.
        self.map_view.setMinimumHeight(260)
        self.gallery_widget.setMinimumHeight(240)
        self.ui.sideSplitter.setSizes([600, 300])
        self.ui.sideSplitter.setStretchFactor(0, 2)
        self.ui.sideSplitter.setStretchFactor(1, 1)

        self.ui.splitter.setStretchFactor(0, 3)
        self.ui.splitter.setStretchFactor(1, 2)

        self._connect_signals()

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.coordinator.frameReceived.connect(self._on_frame)
        self.coordinator.streamInfoUpdated.connect(self._on_stream_info)

        self.playback_controls.playPauseToggled.connect(self._toggle_play)
        self.playback_controls.seekRequested.connect(self._on_seek_requested)
        self.video_display.playPauseRequested.connect(self._toggle_play)

        self.gallery_widget.track_clicked.connect(self._jump_to_track)
        self.map_view.pinClicked.connect(self._on_pin_clicked)

        self.telemetry_coordinator.telemetryUpdated.connect(self._on_telemetry)
        self.telemetry_coordinator.trackUpdated.connect(self.map_view.set_track)

        self.ui.exportButton.clicked.connect(self._export_bundle)
        self.ui.openFolderButton.clicked.connect(self._open_bundle_folder)

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    def load_recording(self, video_path: str) -> bool:
        """Open a recording's video and its stored record, ready to play."""
        video_path = os.path.abspath(str(video_path))
        bundle_dir = find_bundle_for_video(video_path)

        self._reset()
        self._bundle_dir = bundle_dir

        if not self.coordinator.connect_stream(video_path, StreamType.FILE):
            self.ui.headerLabel.setText(
                self.tr("Could not open {name}").format(name=os.path.basename(video_path))
            )
            return False
        self.playback_controls.show_for_file()

        # Telemetry replays through the ordinary file path — the bundle's
        # sidecar SRT is discovered exactly like a DJI card clip's.
        try:
            self.telemetry_coordinator.begin_source(video_path, StreamType.FILE)
        except Exception as exc:  # noqa: BLE001 - telemetry must not block playback
            self.logger.error(f"Replay telemetry failed to load: {exc}")

        detection_count = self._load_detections(bundle_dir)
        self._set_header(bundle_dir, video_path, detection_count)
        self.ui.exportButton.setEnabled(bundle_dir is not None)
        self.ui.openFolderButton.setEnabled(bundle_dir is not None)
        return True

    def _load_detections(self, bundle_dir: Optional[str]) -> int:
        """Fill the gallery and map from the bundle's stored detections.

        Nothing here detects anything: these are the rows the original run
        stored, thumbnails and positions included.
        """
        if bundle_dir is None:
            return 0
        loaded = 0
        for row in load_replay_detections(bundle_dir):
            track = self._row_to_track(row)
            if track is None:
                continue
            key = f"replay-{row.get('seq', loaded)}"
            self._tracks_by_key[key] = track
            self.gallery_widget.add_track(track)
            latitude = row.get("latitude")
            longitude = row.get("longitude")
            if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
                self.map_view.add_detection({
                    "track_key": key,
                    "location": {"lat": float(latitude), "lon": float(longitude)},
                    "class_name": row.get("detection_type") or "detection",
                    "confidence": float(row.get("confidence") or 0.0),
                })
            loaded += 1
        return loaded

    @staticmethod
    def _row_to_track(row: dict) -> Optional[Track]:
        """A stored detection row as a gallery Track.

        The gallery is thumbnail-driven, so a row whose thumbnail file is
        missing is skipped — it still exists in detections.csv.
        """
        thumbnail_path = row.get("thumbnail_path")
        if not thumbnail_path:
            return None
        thumbnail = cv2.imread(thumbnail_path)
        if thumbnail is None or thumbnail.size == 0:
            return None

        bbox = row.get("bbox") or [0, 0, 0, 0]
        centroid = row.get("centroid")
        if not (isinstance(centroid, (list, tuple)) and len(centroid) >= 2):
            centroid = (int(bbox[0]) + int(bbox[2]) // 2, int(bbox[1]) + int(bbox[3]) // 2)
        resolution = row.get("frame_resolution") or [0, 0]
        recorded_frame = row.get("recorded_frame_index")

        return Track(
            track_id=int(row.get("seq", 0)),
            bbox=tuple(int(v) for v in bbox[:4]),
            centroid=(int(centroid[0]), int(centroid[1])),
            thumbnail=thumbnail,
            # The jump target in the recorded video: the writer's frame
            # counter when the detection was stored. Best-effort by design;
            # rows without one land at the start rather than nowhere.
            first_frame_index=int(recorded_frame) if isinstance(recorded_frame, (int, float)) else 0,
            first_timestamp=float(row.get("video_time_seconds") or 0.0),
            frame_resolution=(int(resolution[0] or 0), int(resolution[1] or 0)),
            is_confirmed=True,
            detection_type=str(row.get("detection_type") or "detection"),
            confidence=float(row.get("confidence") or 0.0),
        )

    def _set_header(self, bundle_dir: Optional[str], video_path: str, detections: int) -> None:
        manifest = read_manifest(bundle_dir) if bundle_dir else {}
        feed = manifest.get("feed") or {}
        title = (
            feed.get("label")
            or manifest.get("algorithm")
            or os.path.basename(os.path.dirname(video_path))
        )
        started = str(manifest.get("started_at") or "").replace("T", " ")
        self.ui.headerLabel.setText(
            self.tr("{title} — {when} · {count} detections").format(
                title=title, when=started, count=detections
            )
        )
        self.setWindowTitle(self.tr("Recording Replay — {title}").format(title=title))

    def _reset(self) -> None:
        self.coordinator.disconnect_stream()
        self.telemetry_coordinator.reset()
        self.gallery_widget.clear()
        self.map_view.reset()
        self.telemetry_hud.setVisible(False)
        self._tracks_by_key.clear()
        self._pending_focus = None
        self.playback_controls.reset()

    # ------------------------------------------------------------------
    # playback
    # ------------------------------------------------------------------

    @Slot(np.ndarray, float, int)
    def _on_frame(self, frame: np.ndarray, _timestamp: float, _position: int) -> None:
        self.video_display.update_frame(frame)
        # A click armed a zoom; this is the frame it was waiting for.
        target = self._pending_focus
        if target is not None:
            self._pending_focus = None
            self.video_display.focus_on(target)

    @Slot(dict)
    def _on_stream_info(self, info: dict) -> None:
        if "current_time" in info and "total_time" in info:
            self.playback_controls.update_time(info["current_time"], info["total_time"])
            # The HUD and trail follow the playhead, scrubbing included.
            self.telemetry_coordinator.on_position_changed(info["current_time"])
        if "is_playing" in info:
            self.playback_controls.update_play_state(info["is_playing"])

    def _toggle_play(self) -> None:
        manager = self.coordinator.stream_manager
        if manager is not None and hasattr(manager, "play_pause"):
            manager.play_pause()

    @Slot(float)
    def _on_seek_requested(self, seconds: float) -> None:
        manager = self.coordinator.stream_manager
        if manager is not None and hasattr(manager, "seek_to_time"):
            manager.seek_to_time(seconds)

    def _jump_to_track(self, track) -> None:
        """Pause, jump to a stored detection, and zoom in on it.

        The zoom is armed rather than applied: the display can only centre
        on the detection once it is holding the sought frame, which arrives
        on ``frameReceived``. Seeking to ``first_frame_index - 1`` decodes
        the detection's own frame (the reader reports the position *after*
        the frame it just read).
        """
        manager = self.coordinator.stream_manager
        if manager is None:
            return
        if hasattr(manager, "is_playing") and manager.is_playing():
            manager.play_pause()
        self._pending_focus = self._focus_target_for(track)
        if hasattr(manager, "seek_to_frame"):
            manager.seek_to_frame(max(0, int(track.first_frame_index) - 1))

    @staticmethod
    def _focus_target_for(track) -> Optional[FocusTarget]:
        """Where to centre the zoom for a stored detection, if known.

        ``None`` when the record carries no pixel geometry - a flight
        detection stored before any frame had been seen has only a
        normalized bbox, and guessing a centre would zoom somewhere
        arbitrary.
        """
        centroid = getattr(track, "centroid", None)
        width, height = getattr(track, "frame_resolution", (0, 0)) or (0, 0)
        if not centroid or width <= 0 or height <= 0:
            return None
        return FocusTarget(
            center_xy=(int(centroid[0]), int(centroid[1])),
            reference_size=(int(width), int(height)),
        )

    def _on_pin_clicked(self, track_key: str) -> None:
        track = self._tracks_by_key.get(track_key)
        if track is not None:
            self._jump_to_track(track)

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    def _export_bundle(self) -> None:
        """Write the shareable files for this recording, on demand.

        The bundle keeps only what internal replay needs; the Images-window
        results file, the CSVs, the offline map page and the KML exist for
        other tools, so they are produced here - when someone actually
        wants to hand the recording onward - and land in the bundle folder.
        """
        if not self._bundle_dir:
            return
        from core.services.streaming.RecordingBundleService import export_bundle

        result = export_bundle(self._bundle_dir, self.logger)
        written = sum(1 for v in (result.get("artifacts") or {}).values() if v)
        if result.get("errors"):
            self.ui.headerLabel.setText(
                self.tr("Export finished with problems - see the log")
            )
        else:
            self.ui.headerLabel.setText(
                self.tr("Exported {count} files to the recording folder").format(
                    count=written
                )
            )
        self._open_bundle_folder()

    def _open_bundle_folder(self) -> None:
        if self._bundle_dir and os.path.isdir(self._bundle_dir):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._bundle_dir))

    # ------------------------------------------------------------------
    # telemetry
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_telemetry(self, envelope: dict) -> None:
        if not isinstance(envelope, dict):
            return
        self.telemetry_hud.apply_envelope(envelope)
        if not self.telemetry_hud.isVisible():
            self.telemetry_hud.setVisible(True)
        self._reposition_hud()
        self.map_view.update_aircraft(envelope, extend_track=False)

    #: Gap between the HUD and the bottom of the video pane. Flush against
    #: the edge reads as an artifact of the window rather than an overlay.
    _HUD_BOTTOM_MARGIN = 8

    def _reposition_hud(self) -> None:
        """Pin the HUD near the bottom of the video pane, with a margin."""
        hud_height = self.telemetry_hud.sizeHint().height()
        self.telemetry_hud.setGeometry(
            0,
            max(0, self.video_display.height() - hud_height - self._HUD_BOTTOM_MARGIN),
            self.video_display.width(),
            hud_height,
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt name
        if watched is self.video_display and event.type() == QEvent.Resize:
            self._reposition_hud()
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802 - Qt name
        try:
            self.coordinator.cleanup()
            self.telemetry_coordinator.cleanup()
        except Exception:  # noqa: BLE001 - closing must not raise
            self.logger.warning("Replay window cleanup raised")
        super().closeEvent(event)


def open_replay(video_path: str) -> Optional[ReplayWindow]:
    """Open (or re-point) the app's replay window at a recording video.

    One replay window per app, like the other cross-window navigation
    entries: reused and raised when already open, created otherwise.
    """
    app = QApplication.instance()
    window = getattr(app, "_replay_window", None) if app else None
    try:
        alive = window is not None and window.isVisible()
    except RuntimeError:  # underlying C++ object deleted
        alive = False
    if not alive:
        window = ReplayWindow()
        if app is not None:
            app._replay_window = window
    window.load_recording(video_path)
    window.show()
    window.raise_()
    window.activateWindow()
    return window


__all__ = ["ReplayWindow", "open_replay"]
