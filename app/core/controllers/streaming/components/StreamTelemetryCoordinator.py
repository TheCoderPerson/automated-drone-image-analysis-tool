"""Single telemetry source for the streaming window.

Streaming analysis can get aircraft location from two very different
places:

* a **video file**, sampled by playback position — from a metadata file
  the operator selected (a DJI ``.SRT`` or a ``.csv`` flight log), a
  sidecar ``.SRT``, or a subtitle stream embedded in the MP4; or
* a **live ADIAT Flight feed**, pushing envelopes over WebRTC.

Rather than teach the window about both, this component normalizes them
into one ``telemetryUpdated(dict)`` signal carrying the envelope shape
:class:`~core.views.flight.TelemetryHud.TelemetryHud` already renders. The
HUD and map therefore have exactly one input regardless of source, and a
future source only has to feed this class.

Every envelope is routed through
:class:`~core.services.telemetry.TelemetryEnrichmentService.\
TelemetryEnrichmentService` so AGL is terrain-corrected where DEM coverage
exists — without ever blocking the UI thread on a tile fetch.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from core.services.LoggerService import LoggerService
from core.services.streaming.RTMPStreamService import StreamType
from core.services.telemetry import (
    SOURCE_EMBEDDED,
    SOURCE_EXPLICIT_FILE,
    SOURCE_SIDECAR,
    TelemetryEnrichmentService,
    TelemetryTrack,
    load_telemetry_for_video,
)


class StreamTelemetryCoordinator(QObject):
    """Normalizes file-derived and live telemetry into one signal."""

    # Enriched envelope ready for the HUD / map.
    telemetryUpdated = Signal(dict)
    # Flight path so far, as ``[(lat, lon), ...]``. Emitted for file sources
    # where seeking can shorten the trail; live sources append instead.
    trackUpdated = Signal(list)
    # Human-readable note about where telemetry came from (or that there
    # is none), for the window's info panel.
    telemetryStatus = Signal(str)
    # True once a source with usable location data is active.
    availabilityChanged = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None, logger=None):
        super().__init__(parent)
        self.logger = logger or LoggerService()

        self._track: Optional[TelemetryTrack] = None
        self._stream_type: Optional[StreamType] = None
        self._available = False
        self._last_envelope: Optional[dict] = None
        # Guards against re-emitting the identical fix for every frame at
        # the same playhead — DJI writes one cue per frame, but the video
        # position only advances a few times a second at low FPS caps.
        self._last_point_time: Optional[float] = None

        self._enrichment = TelemetryEnrichmentService(self)
        self._enrichment.envelopeEnriched.connect(self._on_envelope_enriched)

    # ------------------------------------------------------------------
    # source lifecycle
    # ------------------------------------------------------------------

    def begin_source(self, url: str, stream_type, metadata_path: Optional[str] = None) -> bool:
        """Prepare for a new source; load a telemetry track for files.

        Args:
            url: Stream URL, file path, or pairing code.
            stream_type: The resolved :class:`StreamType`.
            metadata_path: Optional operator-selected metadata file — a
                DJI ``.SRT`` or a ``.csv`` flight log. Only meaningful for
                file sources, and takes precedence over a sidecar or an
                embedded track when given.

        Returns:
            True when this source has usable location data available now.
            Live sources return False here and become available when their
            first envelope arrives.
        """
        self.reset()
        self._stream_type = stream_type

        if stream_type == StreamType.FILE and url:
            self._load_file_track(url, metadata_path)
        elif stream_type == StreamType.WEBRTC:
            # Availability is decided by the first live envelope.
            self.telemetryStatus.emit(
                self.tr("Waiting for telemetry from ADIAT Flight...")
            )

        return self._available

    def _load_file_track(self, path: str, metadata_path: Optional[str] = None) -> None:
        try:
            resolution = load_telemetry_for_video(
                path, metadata_path, logger=self.logger
            )
        except Exception as exc:  # noqa: BLE001 - never block playback
            self.logger.error(f"Telemetry load failed for {path}: {exc}")
            self.telemetryStatus.emit(self.tr("Could not read location data from video"))
            return

        if not resolution.found:
            if resolution.source == SOURCE_EXPLICIT_FILE and resolution.detail:
                # The operator picked this file, so say what went wrong with
                # it rather than the generic "no location data" — a missing
                # column or an unaligned timestamp is fixable, and they can
                # only fix what they're told about.
                self.telemetryStatus.emit(
                    self.tr("Could not use the selected metadata file: {reason}").format(
                        reason=resolution.detail
                    )
                )
            else:
                self.telemetryStatus.emit(self.tr("No location data in this video"))
            return

        self._track = resolution.track
        self._set_available(True)

        if resolution.source == SOURCE_EMBEDDED:
            self.telemetryStatus.emit(
                self.tr("Location data embedded in video ({count} fixes)").format(
                    count=len(resolution.track)
                )
            )
        elif resolution.source == SOURCE_SIDECAR:
            self.telemetryStatus.emit(
                self.tr("Location data from SRT file ({count} fixes)").format(
                    count=len(resolution.track)
                )
            )
        elif resolution.source == SOURCE_EXPLICIT_FILE:
            self.telemetryStatus.emit(
                self.tr("Location data from {name} ({count} fixes)").format(
                    name=os.path.basename(resolution.path or ""),
                    count=len(resolution.track),
                )
            )
        else:
            self.telemetryStatus.emit(
                self.tr("Location data loaded ({count} fixes)").format(
                    count=len(resolution.track)
                )
            )

    def reset(self) -> None:
        """Drop all per-source state."""
        self._track = None
        self._stream_type = None
        self._last_envelope = None
        self._last_point_time = None
        self._enrichment.reset()
        self._set_available(False)

    def cleanup(self) -> None:
        """Release the enrichment worker thread."""
        self._enrichment.cleanup()

    # ------------------------------------------------------------------
    # file playback
    # ------------------------------------------------------------------

    @Slot(float)
    def on_position_changed(self, current_time_seconds: float) -> None:
        """Sample the loaded track at the current playback position."""
        if self._track is None:
            return

        point = self._track.point_at(current_time_seconds)
        if point is None:
            return
        if self._last_point_time == point.time_seconds:
            return
        self._last_point_time = point.time_seconds

        envelope = self._enrichment.enrich(point.to_envelope())
        self._last_envelope = envelope
        self.telemetryUpdated.emit(envelope)
        # Recompute the whole trail so scrubbing backwards shortens it
        # rather than leaving a path the aircraft has not flown yet.
        self.trackUpdated.emit(self._track.path_until(current_time_seconds))

    # ------------------------------------------------------------------
    # live feed
    # ------------------------------------------------------------------

    @Slot(dict)
    def on_live_telemetry(self, envelope: dict) -> None:
        """Accept an envelope pushed by a live source (ADIAT Flight)."""
        if not isinstance(envelope, dict):
            return
        if not self._available:
            self._set_available(True)
            self.telemetryStatus.emit(self.tr("Receiving telemetry from ADIAT Flight"))

        enriched = self._enrichment.enrich(envelope)
        self._last_envelope = enriched
        self.telemetryUpdated.emit(enriched)

    # ------------------------------------------------------------------
    # accessors
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True when the active source is producing location data."""
        return self._available

    @property
    def track(self) -> Optional[TelemetryTrack]:
        """The loaded file track, or None for live/absent sources."""
        return self._track

    @property
    def last_envelope(self) -> Optional[dict]:
        return self._last_envelope

    def position_at(self, seconds: float) -> Optional[Tuple[float, float]]:
        """``(lat, lon)`` at a video time — used to geotag detections."""
        if self._track is None:
            return None
        point = self._track.point_at(seconds)
        if point is None or point.latitude is None or point.longitude is None:
            return None
        return (point.latitude, point.longitude)

    def current_position(self) -> Optional[Tuple[float, float]]:
        """``(lat, lon)`` of the most recent envelope, from either source."""
        envelope = self._last_envelope or {}
        lat = envelope.get("aircraft_latitude")
        lon = envelope.get("aircraft_longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return (float(lat), float(lon))
        return None

    def full_path(self) -> List[Tuple[float, float]]:
        """Every fix in the loaded file track (empty for live sources)."""
        return self._track.full_path() if self._track is not None else []

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @Slot(dict)
    def _on_envelope_enriched(self, envelope: dict) -> None:
        """Re-emit an envelope once the DEM has supplied a corrected AGL."""
        self._last_envelope = envelope
        self.telemetryUpdated.emit(envelope)

    def _set_available(self, value: bool) -> None:
        if value != self._available:
            self._available = value
            self.availabilityChanged.emit(value)
