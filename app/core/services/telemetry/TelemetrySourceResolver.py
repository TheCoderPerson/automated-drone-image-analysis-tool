"""Resolve where a video's telemetry comes from, and load it.

A video's location data can arrive by three routes, in descending order
of operator intent:

1. **An explicitly chosen metadata file** — a DJI ``.SRT`` or a ``.csv``
   flight log. The operator picked it, so it wins outright, even if the
   video also has an embedded track.
2. **A sibling ``.SRT``.** DJI writes ``FOO.SRT`` next to ``FOO.MP4``;
   finding it automatically saves the operator a second file-picker trip.
3. **An embedded subtitle track.** Newer DJI firmware writes telemetry
   only inside the MP4. This is the route that previously had no support
   at all — copying just the ``.MP4`` off the card lost all GPS.

Sidecar discovery is deliberately limited to ``.SRT``: DJI's naming
convention makes ``FOO.SRT`` next to ``FOO.MP4`` unambiguous, whereas a
CSV sitting in the same folder is just as likely to be an unrelated
export. CSV is therefore an explicit choice only.

Resolution is deliberately explicit about *which* route was used so the
UI can tell the operator, rather than leaving them guessing why a video
did or didn't get geotagged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.services.telemetry.VideoProfileService import datum_for_video
from core.services.telemetry.DjiSrtParser import parse_dji_srt
from core.services.telemetry.FlightLogCsvParser import read_flight_log_track
from core.services.telemetry.TelemetryTrack import TelemetryTrack
from helpers.VideoFileHelper import (
    extract_embedded_subtitles,
    find_embedded_telemetry_stream,
)

# Metadata files an operator may hand us, and how to read each.
METADATA_EXTENSIONS = (".srt", ".csv")

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


def read_srt_track(
    srt_path,
    *,
    source: str,
    altitude_datum: Optional[str] = None,
    datum_provider=None,
) -> Optional[TelemetryTrack]:
    """Parse an SRT file into a :class:`TelemetryTrack`, or None.

    Args:
        srt_path: File to read.
        source: Label recorded on the track.
        altitude_datum: A known datum, applied directly.
        datum_provider: Zero-argument callable returning the datum, invoked
            **only if the track actually needs one**. Resolving the datum
            costs an ffprobe spawn (~130 ms measured), and a track carrying
            the explicit ``rel_alt``/``abs_alt`` pair states both datums
            itself — so the lookup is skipped for those, which is the common
            case on modern aircraft.
    """
    try:
        # DJI writes UTF-8, occasionally with a BOM; some older units emit
        # latin-1. Decode leniently — losing an accented character in a
        # camera-setting field must not cost the whole GPS track.
        text = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeError):
        return None

    if altitude_datum is None and datum_provider is not None:
        # Only a legacy single-``altitude`` track is ambiguous. Checking the
        # raw text is free; identifying the aircraft is not.
        if "abs_alt" not in text and "rel_alt" not in text:
            try:
                altitude_datum = datum_provider()
            except Exception:  # noqa: BLE001 - inference is the fallback
                altitude_datum = None

    samples = parse_dji_srt(text, altitude_datum=altitude_datum)
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
        metadata_path: Operator-selected metadata file, if any — a DJI
            ``.SRT`` or a ``.csv`` flight log.
        logger: Optional logger.

    Returns:
        A :class:`TelemetryResolution`; check ``.found`` before use. An
        explicit choice that cannot be read comes back as
        ``SOURCE_EXPLICIT_FILE`` with ``found`` False and a ``detail``
        explaining why, so the UI can say more than "no location data".
    """
    # 1. Explicit operator choice wins.
    if metadata_path and str(metadata_path).strip():
        return _load_explicit_metadata(
            video_path, str(metadata_path).strip(), logger
        )

    # 2. Sidecar next to the video.
    sidecar = find_sidecar_srt(video_path)
    if sidecar:
        track = read_srt_track(
            sidecar,
            source=SOURCE_SIDECAR,
            datum_provider=lambda: datum_for_video(video_path, logger=logger),
        )
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
        # No datum lookup here: an embedded track means firmware new enough
        # to write the explicit rel_alt/abs_alt pair, which is never
        # ambiguous (verified on three Matrice 4E files — zero ambiguous
        # cues). Skipping it keeps an ffprobe call off the common path.
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


def _load_explicit_metadata(video_path, chosen: str, logger) -> TelemetryResolution:
    """Read the metadata file the operator selected.

    Always reports ``SOURCE_EXPLICIT_FILE`` — including on failure — so
    the caller can distinguish "the operator's file didn't work" (worth
    saying out loud) from "this video simply has no location data". An
    explicit choice deliberately suppresses the sidecar and embedded
    fallbacks: silently geotagging from a different source than the one
    that was picked would be worse than reporting the problem.
    """
    extension = os.path.splitext(chosen)[1].lower()

    def failure(detail: str) -> TelemetryResolution:
        return TelemetryResolution(
            track=None, source=SOURCE_EXPLICIT_FILE, path=chosen, detail=detail
        )

    if extension not in METADATA_EXTENSIONS:
        return failure(
            f"'{extension or os.path.basename(chosen)}' is not a supported "
            "metadata format (expected .srt or .csv)"
        )
    if not os.path.isfile(chosen):
        return failure(f"{os.path.basename(chosen)} could not be found")

    if extension == ".srt":
        track = read_srt_track(
            chosen,
            source=SOURCE_EXPLICIT_FILE,
            datum_provider=lambda: datum_for_video(video_path, logger=logger),
        )
        if track is None:
            return failure("selected SRT contained no usable telemetry")
        detail = f"{len(track)} fixes from selected file"
    else:
        try:
            track, detail = read_flight_log_track(chosen, video_path, logger=logger)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            if logger:
                logger.error(f"Flight log read failed for {chosen}: {exc}")
            return failure(f"could not read flight log ({exc})")
        if track is None:
            return failure(detail)

    return TelemetryResolution(
        track=track,
        source=SOURCE_EXPLICIT_FILE,
        path=chosen,
        detail=detail,
    )
