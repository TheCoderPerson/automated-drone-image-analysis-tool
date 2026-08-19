"""Time-indexed telemetry for a video, sampled by playback position.

Wraps the samples produced by :mod:`core.services.telemetry.DjiSrtParser`
(or any other source) in a structure that answers "where was the aircraft
at t seconds into this video?" — the question both the frame-extraction
path and live streaming playback need to ask.

Sampling uses binary search with a maximum-gap guard, mirroring
:meth:`VideoParserService._find_closest_csv_entry`: a fix that is too far
from the requested time is reported as *unknown* rather than silently
interpolated across a telemetry dropout.

Envelopes are emitted in the **same shape the Flight Viewer's**
:class:`~core.views.flight.TelemetryHud.TelemetryHud` **already consumes**,
so a DJI video and a live ADIAT Flight feed render through one widget with
no per-source branching.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from core.services.telemetry.DjiSrtParser import DjiSrtSample

# A fix further than this from the requested time is treated as a dropout.
# DJI writes one cue per frame (~33 ms), so a whole second of silence is
# already far outside normal cadence.
DEFAULT_MAX_GAP_SECONDS = 1.0

# Speed is derived from consecutive fixes. Below this separation the
# position delta is dominated by GPS jitter rather than real movement, so
# reporting a speed would be noise.
_MIN_SPEED_INTERVAL_SECONDS = 0.20

_EARTH_RADIUS_M = 6371008.8


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class TelemetryPoint:
    """A single resolved fix, enriched with derived motion."""

    time_seconds: float
    latitude: Optional[float]
    longitude: Optional[float]
    altitude_msl_m: Optional[float]
    altitude_agl_m: Optional[float]
    yaw_deg: Optional[float]
    horizontal_speed_ms: Optional[float]
    vertical_speed_ms: Optional[float]
    # The aircraft's own wall clock for this fix, in drone local time,
    # where the source carried one. This is what the frame-extraction
    # path stamps as EXIF capture time; time_seconds is only an offset
    # into the video and cannot date a frame on its own.
    captured_at: Optional[datetime] = None

    def to_envelope(self) -> Dict[str, object]:
        """Render in the shape ``TelemetryHud.apply_envelope`` expects.

        ``agl_source`` starts as ``reported`` — the drone's own
        takeoff-relative figure. :class:`~core.services.telemetry.\
TelemetryEnrichmentService.TelemetryEnrichmentService` may later replace
        the value with a DEM-derived one and flip this to ``terrain``.
        """
        return {
            "aircraft_latitude": self.latitude,
            "aircraft_longitude": self.longitude,
            "aircraft_altitude_msl_m": self.altitude_msl_m,
            "aircraft_altitude_agl_m": self.altitude_agl_m,
            # Gimbal yaw, surfaced as heading — the only bearing DJI's SRT
            # carries. See DjiSrtParser's note.
            "aircraft_yaw_deg": self.yaw_deg,
            "horizontal_speed_ms": self.horizontal_speed_ms,
            "vertical_speed_ms": self.vertical_speed_ms,
            "captured_at_ms": int(self.time_seconds * 1000),
            "video_time_seconds": self.time_seconds,
            "agl_source": "reported" if self.altitude_agl_m is not None else None,
        }


class TelemetryTrack:
    """An ordered, queryable set of fixes for one video."""

    def __init__(
        self,
        points: Sequence[TelemetryPoint],
        *,
        source: str = "unknown",
        max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    ):
        self._points: List[TelemetryPoint] = list(points)
        self._times: List[float] = [p.time_seconds for p in self._points]
        self._max_gap = float(max_gap_seconds)
        self.source = source

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def from_samples(
        cls,
        samples: Sequence,
        *,
        source: str = "unknown",
        max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    ) -> "TelemetryTrack":
        """Build a track from time-ordered samples, deriving speeds.

        Accepts anything exposing ``has_position``, ``start_seconds``,
        ``latitude``/``longitude``, ``altitude_msl_m``/``altitude_agl_m``
        and ``yaw_deg`` — DJI SRT cues
        (:class:`~core.services.telemetry.DjiSrtParser.DjiSrtSample`) and
        CSV flight-log rows
        (:class:`~core.services.telemetry.FlightLogCsvParser.\
FlightLogSample`) both qualify, so every source gets identical speed
        derivation and sampling behaviour.

        Neither source carries velocity, so horizontal and vertical speed
        are differentiated from consecutive fixes. Pairs closer together
        than :data:`_MIN_SPEED_INTERVAL_SECONDS` are skipped so per-frame
        GPS jitter does not masquerade as movement.
        """
        usable = [s for s in samples if s.has_position]
        points: List[TelemetryPoint] = []

        # ``reference`` trails ``index``, always pointing at the newest fix
        # that is at least ``_MIN_SPEED_INTERVAL_SECONDS`` older than the
        # current one. Because both indices only ever move forward this is
        # a single linear pass. The obvious alternative — scanning
        # ``usable[:index]`` backwards per sample — is quadratic *and*
        # copies the slice each time: 275 ms for a 10-minute clip and
        # several seconds for a full battery, all on the UI thread.
        reference = -1

        for index, sample in enumerate(usable):
            horizontal = None
            vertical = None

            while (
                reference + 1 < index
                and sample.start_seconds - usable[reference + 1].start_seconds
                >= _MIN_SPEED_INTERVAL_SECONDS
            ):
                reference += 1

            previous = usable[reference] if reference >= 0 else None
            if previous is not None and (
                sample.start_seconds - previous.start_seconds
                < _MIN_SPEED_INTERVAL_SECONDS
            ):
                # Nothing far enough back yet (start of the track).
                previous = None

            if previous is not None:
                dt = sample.start_seconds - previous.start_seconds
                if dt > 0:
                    horizontal = haversine_meters(
                        previous.latitude, previous.longitude,
                        sample.latitude, sample.longitude,
                    ) / dt
                    prev_alt = (
                        previous.altitude_msl_m
                        if previous.altitude_msl_m is not None
                        else previous.altitude_agl_m
                    )
                    curr_alt = (
                        sample.altitude_msl_m
                        if sample.altitude_msl_m is not None
                        else sample.altitude_agl_m
                    )
                    if prev_alt is not None and curr_alt is not None:
                        vertical = (curr_alt - prev_alt) / dt

            points.append(TelemetryPoint(
                time_seconds=sample.start_seconds,
                latitude=sample.latitude,
                longitude=sample.longitude,
                altitude_msl_m=sample.altitude_msl_m,
                altitude_agl_m=sample.altitude_agl_m,
                yaw_deg=sample.yaw_deg,
                horizontal_speed_ms=horizontal,
                vertical_speed_ms=vertical,
                # from_samples is structural, not nominal: DJI SRT cues
                # carry a wall clock, CSV flight-log rows do not, and
                # the CSV path dates its frames from the container's
                # start instead.
                captured_at=getattr(sample, "captured_at", None),
            ))

        return cls(points, source=source, max_gap_seconds=max_gap_seconds)

    @classmethod
    def from_dji_samples(
        cls,
        samples: Sequence[DjiSrtSample],
        *,
        source: str = "dji-srt",
        max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    ) -> "TelemetryTrack":
        """Build a track from parsed DJI SRT cues.

        Retained as the SRT-specific entry point (and for its default
        ``source`` label); :meth:`from_samples` is the general one.
        """
        return cls.from_samples(
            samples, source=source, max_gap_seconds=max_gap_seconds
        )

    # ------------------------------------------------------------------
    # querying
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._points)

    def __bool__(self) -> bool:
        return bool(self._points)

    @property
    def points(self) -> List[TelemetryPoint]:
        return list(self._points)

    @property
    def has_wall_clock(self) -> bool:
        """True when the source dated its fixes with the aircraft's clock.

        The frame-extraction path uses this to choose a timestamp datum for
        the whole video: the SRT's own drone-local clock when it has one,
        otherwise the MP4 container's UTC start plus each frame's offset.
        The two are never mixed within one video, so a frame landing in a
        telemetry dropout is left undated rather than stamped hours off its
        neighbours.
        """
        return any(p.captured_at is not None for p in self._points)

    @property
    def duration_seconds(self) -> float:
        if not self._points:
            return 0.0
        return self._points[-1].time_seconds

    def point_at(self, seconds: float) -> Optional[TelemetryPoint]:
        """Nearest fix to ``seconds``, or None beyond the max-gap guard."""
        if not self._points:
            return None

        position = bisect_left(self._times, seconds)
        best: Optional[TelemetryPoint] = None
        best_delta: Optional[float] = None
        for index in (position - 1, position):
            if 0 <= index < len(self._points):
                delta = abs(self._times[index] - seconds)
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best = self._points[index]

        if best_delta is not None and best_delta <= self._max_gap:
            return best
        return None

    def sample_at(self, seconds: float) -> Optional[Dict[str, object]]:
        """Envelope for ``seconds`` into the video, or None if unknown."""
        point = self.point_at(seconds)
        return point.to_envelope() if point is not None else None

    def path_until(self, seconds: float) -> List[tuple]:
        """``(lat, lon)`` fixes up to ``seconds`` — the flight path so far.

        Scrubbing backwards shortens the returned trail, so the map trail
        always reflects the position at the current playhead rather than
        everywhere the aircraft has ever been.
        """
        path: List[tuple] = []
        for point in self._points:
            if point.time_seconds > seconds:
                break
            if point.latitude is not None and point.longitude is not None:
                path.append((point.latitude, point.longitude))
        return path

    def full_path(self) -> List[tuple]:
        """Every ``(lat, lon)`` fix in the track."""
        return [
            (p.latitude, p.longitude)
            for p in self._points
            if p.latitude is not None and p.longitude is not None
        ]
