"""Resolve where a video's telemetry comes from, and load it.

A video's location data can arrive by three routes, in descending order
of operator intent:

1. **An explicitly chosen metadata file.** The operator picked it, so it
   wins outright — even if the video also has an embedded track.
2. **A sibling ``.SRT``.** DJI writes ``FOO.SRT`` next to ``FOO.MP4``;
   finding it automatically saves the operator a second file-picker trip.
3. **An embedded subtitle track.** Newer DJI firmware writes telemetry
   only inside the MP4. This is the route that previously had no support
   at all — copying just the ``.MP4`` off the card lost all GPS.

Resolution is deliberately explicit about *which* route was used so the
UI can tell the operator, rather than leaving them guessing why a video
did or didn't get geotagged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.services.telemetry.DjiSrtParser import parse_dji_srt
from core.services.telemetry.TelemetryTrack import TelemetryTrack
from helpers.VideoFileHelper import (
    extract_embedded_subtitles,
    find_embedded_telemetry_stream,
)

# Resolution outcomes, surfaced to the UI.
SOURCE_EXPLICIT_FILE = "explicit-file"
SOURCE_SIDECAR = "sidecar"
SOURCE_EMBEDDED = "embedded"
SOURCE_NONE = "none"


@dataclass
class TelemetryResolution:
    """What we found, where it came from, and how to describe it."""

    track: Optional[TelemetryTrack]
    source: str
    path: Optional[str] = None
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.track is not None and len(self.track) > 0


def find_sidecar_srt(video_path) -> Optional[str]:
    """Return a ``.SRT`` sitting beside ``video_path``, if one exists.

    Checks the common casings DJI and Windows produce rather than relying
    on a case-insensitive filesystem, so the lookup behaves the same on
    macOS and Linux.
    """
    if not video_path:
        return None
    base = Path(video_path)
    for suffix in (".SRT", ".srt", ".Srt"):
        candidate = base.with_suffix(suffix)
        if candidate.is_file():
            return str(candidate)
    return None


def read_srt_track(srt_path, *, source: str) -> Optional[TelemetryTrack]:
    """Parse an SRT file into a :class:`TelemetryTrack`, or None."""
    try:
        # DJI writes UTF-8, occasionally with a BOM; some older units emit
        # latin-1. Decode leniently — losing an accented character in a
        # camera-setting field must not cost the whole GPS track.
        text = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeError):
        return None

    samples = parse_dji_srt(text)
    if not samples:
        return None
    return TelemetryTrack.from_dji_samples(samples, source=source)


def load_telemetry_for_video(
    video_path,
    metadata_path: Optional[str] = None,
    logger=None,
) -> TelemetryResolution:
    """Load telemetry for ``video_path`` using the precedence above.

    Args:
        video_path: Path to the video.
        metadata_path: Operator-selected metadata file, if any. A ``.csv``
            is not handled here — the Skydio flight-log path stays in
            :class:`~core.services.VideoParserService.VideoParserService`.
        logger: Optional logger.

    Returns:
        A :class:`TelemetryResolution`; check ``.found`` before use.
    """
    # 1. Explicit operator choice wins.
    if metadata_path and str(metadata_path).strip():
        chosen = str(metadata_path).strip()
        if os.path.splitext(chosen)[1].lower() == ".srt" and os.path.isfile(chosen):
            track = read_srt_track(chosen, source=SOURCE_EXPLICIT_FILE)
            if track is not None:
                return TelemetryResolution(
                    track=track,
                    source=SOURCE_EXPLICIT_FILE,
                    path=chosen,
                    detail=f"{len(track)} fixes from selected file",
                )
            return TelemetryResolution(
                track=None,
                source=SOURCE_EXPLICIT_FILE,
                path=chosen,
                detail="selected SRT contained no usable telemetry",
            )
        # A non-SRT explicit choice (e.g. CSV) is not ours to resolve.
        return TelemetryResolution(track=None, source=SOURCE_NONE)

    # 2. Sidecar next to the video.
    sidecar = find_sidecar_srt(video_path)
    if sidecar:
        track = read_srt_track(sidecar, source=SOURCE_SIDECAR)
        if track is not None:
            return TelemetryResolution(
                track=track,
                source=SOURCE_SIDECAR,
                path=sidecar,
                detail=f"{len(track)} fixes from {os.path.basename(sidecar)}",
            )

    # 3. Embedded subtitle track inside the MP4.
    stream_index = find_embedded_telemetry_stream(video_path, logger)
    if stream_index is None:
        return TelemetryResolution(track=None, source=SOURCE_NONE)

    extracted = extract_embedded_subtitles(video_path, logger, stream_index=stream_index)
    if not extracted:
        return TelemetryResolution(track=None, source=SOURCE_NONE)

    try:
        track = read_srt_track(extracted, source=SOURCE_EMBEDDED)
    finally:
        # The temp file has served its purpose; the parsed track is what
        # callers keep. Leaving it behind would litter %TEMP% once per
        # video opened.
        try:
            os.unlink(extracted)
        except OSError:
            pass

    if track is None:
        return TelemetryResolution(track=None, source=SOURCE_NONE)

    return TelemetryResolution(
        track=track,
        source=SOURCE_EMBEDDED,
        path=None,
        detail=f"{len(track)} fixes embedded in video",
    )
