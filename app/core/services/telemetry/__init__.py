"""Shared drone-telemetry services.

One pipeline feeding every surface that shows aircraft location:

* image analysis (:class:`~core.services.VideoParserService.VideoParserService`)
* streaming analysis (``core.controllers.streaming``)
* the Flight Viewer (``core.controllers.flight``)

Telemetry reaches ADIAT from a ``.SRT`` sidecar, a subtitle track embedded
in the MP4, or a live ADIAT Flight WebRTC feed. All three normalize to the
envelope shape :class:`~core.views.flight.TelemetryHud.TelemetryHud`
consumes, so the same HUD renders any source.
"""

from core.services.telemetry.DjiSrtParser import (
    DjiSrtSample,
    extract_fields,
    parse_dji_srt,
    parse_timecode,
)
from core.services.telemetry.TelemetryEnrichmentService import (
    AGL_SOURCE_REPORTED,
    AGL_SOURCE_TERRAIN,
    TelemetryEnrichmentService,
)
from core.services.telemetry.TelemetrySourceResolver import (
    SOURCE_EMBEDDED,
    SOURCE_EXPLICIT_FILE,
    SOURCE_NONE,
    SOURCE_SIDECAR,
    TelemetryResolution,
    find_sidecar_srt,
    load_telemetry_for_video,
    read_srt_track,
)
from core.services.telemetry.TelemetryTrack import (
    TelemetryPoint,
    TelemetryTrack,
    haversine_meters,
)

__all__ = [
    "AGL_SOURCE_REPORTED",
    "AGL_SOURCE_TERRAIN",
    "DjiSrtSample",
    "SOURCE_EMBEDDED",
    "SOURCE_EXPLICIT_FILE",
    "SOURCE_NONE",
    "SOURCE_SIDECAR",
    "TelemetryEnrichmentService",
    "TelemetryPoint",
    "TelemetryResolution",
    "TelemetryTrack",
    "extract_fields",
    "find_sidecar_srt",
    "haversine_meters",
    "load_telemetry_for_video",
    "parse_dji_srt",
    "parse_timecode",
    "read_srt_track",
]
