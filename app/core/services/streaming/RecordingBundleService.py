"""Derive a recording bundle's finished artifacts from its live logs.

:mod:`~core.services.streaming.RecordingSessionService` appends two
crash-safe logs while a recording runs — ``detections.jsonl`` and
``telemetry.jsonl``. This module turns those into the artifacts an
operator actually opens once the recording stops:

* ``ADIAT_Data.xml`` — an image-mode results file, so a streaming
  recording re-opens in the Images window via *Load Results File* with no
  new loader code. Each stored detection becomes one ``image`` entry
  pointing at its saved thumbnail, with a single ``areas_of_interest``
  re-projected onto that thumbnail.
* ``detections.csv`` — the same rows as a flat table, for spreadsheets
  and scripts.
* ``telemetry.csv`` — every fix recorded during the session.
* ``flight_map.html`` — a self-contained Leaflet page (path + pins).
* ``flight_path.kml`` — path + detection placemarks for CalTopo and
  Google Earth.

Deriving is deliberately separate from capturing. It reads only the
bundle directory, so it also serves as the repair path for a bundle left
behind by a crash: the logs are there, and calling
:func:`finalize_bundle` on the folder produces everything that was never
written.
"""

from __future__ import annotations

import csv
import json
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.services.LoggerService import LoggerService
from core.services.streaming.RecordingSessionService import (
    DETECTIONS_LOG,
    MANIFEST_FILE,
    TELEMETRY_LOG,
    read_jsonl,
    read_manifest,
)

RESULTS_XML = "ADIAT_Data.xml"
DETECTIONS_CSV = "detections.csv"
TELEMETRY_CSV = "telemetry.csv"
FLIGHT_MAP_HTML = "flight_map.html"
FLIGHT_PATH_KML = "flight_path.kml"

# Identifies the producing pipeline in the exported results file, the way
# an image-mode run records the algorithm it came from.
_XML_ALGORITHM_FALLBACK = "StreamingRecording"

_DETECTION_CSV_COLUMNS = [
    "seq",
    "track_id",
    "detection_type",
    "confidence",
    "video_time_seconds",
    "recorded_frame_index",
    "first_frame_index",
    "latitude",
    "longitude",
    "bbox_x",
    "bbox_y",
    "bbox_w",
    "bbox_h",
    "centroid_x",
    "centroid_y",
    "pixel_area",
    "frame_width",
    "frame_height",
    "thumbnail",
    "recorded_at_epoch_s",
]

_TELEMETRY_CSV_COLUMNS = [
    "video_time_seconds",
    "captured_at_ms",
    "aircraft_latitude",
    "aircraft_longitude",
    "aircraft_altitude_msl_m",
    "aircraft_altitude_agl_m",
    "aircraft_yaw_deg",
    "horizontal_speed_ms",
    "vertical_speed_ms",
    "agl_source",
    "recorded_at_epoch_s",
]


def _pair(value: Any, index: int) -> Optional[float]:
    """Read one element of a stored ``[a, b]`` pair, tolerating junk."""
    if isinstance(value, (list, tuple)) and len(value) > index:
        item = value[index]
        if isinstance(item, (int, float)):
            return item
    return None


def _coords(rows: Sequence[dict]) -> List[Tuple[float, float]]:
    """Extract the flight path as ordered ``(lat, lon)`` fixes.

    Two corrections turn the raw fix log into a path worth drawing:

    * **Order by video time where every fix carries one.** Fixes are logged
      in the order they were played, and an operator recording a video file
      can scrub backwards - which would otherwise draw a path zigzagging
      between wherever the playhead jumped. Sorting by the source's own
      timeline recovers the route the aircraft actually flew. Live feeds
      carry no video time and are already chronological, so they are left
      exactly as logged.
    * **Drop consecutive duplicate positions.** A hovering aircraft, and
      the second (DEM-corrected) emission of a fix, both repeat a position
      that adds nothing to a polyline. ``telemetry.csv`` still carries
      every row - this only tidies the path.
    """
    fixes: List[Tuple[Optional[float], float, float]] = []
    for row in rows:
        lat = row.get("aircraft_latitude")
        lon = row.get("aircraft_longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        seconds = row.get("video_time_seconds")
        fixes.append((
            float(seconds) if isinstance(seconds, (int, float)) else None,
            float(lat),
            float(lon),
        ))

    if fixes and all(seconds is not None for seconds, _lat, _lon in fixes):
        fixes.sort(key=lambda fix: fix[0])

    path: List[Tuple[float, float]] = []
    for _seconds, lat, lon in fixes:
        point = (lat, lon)
        if path and path[-1] == point:
            continue
        path.append(point)
    return path


def _has_location(detection: dict) -> bool:
    return (
        isinstance(detection.get("latitude"), (int, float))
        and isinstance(detection.get("longitude"), (int, float))
    )


def _detection_label(detection: dict) -> str:
    """Human-facing name for a detection in a map popup or placemark."""
    kind = detection.get("detection_type") or "detection"
    return f"{kind} #{int(detection.get('seq', 0)) + 1}"


def _detection_details(detection: dict) -> List[str]:
    """Popup/description lines: confidence, time, position."""
    details: List[str] = []
    confidence = detection.get("confidence")
    if isinstance(confidence, (int, float)) and confidence:
        details.append(f"Confidence: {float(confidence):.2f}")
    video_time = detection.get("video_time_seconds")
    if isinstance(video_time, (int, float)):
        details.append(f"Video time: {_format_clock(float(video_time))}")
    if _has_location(detection):
        details.append(
            f"Position: {float(detection['latitude']):.6f}, "
            f"{float(detection['longitude']):.6f}"
        )
    return details


def _format_clock(seconds: float) -> str:
    """Render seconds as ``h:mm:ss`` / ``m:ss`` for operator-facing text."""
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _bgr_to_rgb(color: Any) -> Optional[Tuple[int, int, int]]:
    """Convert a stored BGR triple into RGB for KML styling."""
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        try:
            b, g, r = int(color[0]), int(color[1]), int(color[2])
        except (TypeError, ValueError):
            return None
        return (r, g, b)
    return None


def write_detections_csv(bundle_dir: str, detections: Sequence[dict]) -> Optional[str]:
    """Write ``detections.csv``; returns its path, or ``None`` if empty."""
    if not detections:
        return None
    target = os.path.join(bundle_dir, DETECTIONS_CSV)
    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_DETECTION_CSV_COLUMNS)
        writer.writeheader()
        for detection in detections:
            bbox = detection.get("bbox") or []
            centroid = detection.get("centroid") or []
            resolution = detection.get("frame_resolution") or []
            writer.writerow({
                "seq": detection.get("seq"),
                "track_id": detection.get("track_id"),
                "detection_type": detection.get("detection_type"),
                "confidence": detection.get("confidence"),
                "video_time_seconds": detection.get("video_time_seconds"),
                "recorded_frame_index": detection.get("recorded_frame_index"),
                "first_frame_index": detection.get("first_frame_index"),
                "latitude": detection.get("latitude"),
                "longitude": detection.get("longitude"),
                "bbox_x": _pair(bbox, 0),
                "bbox_y": _pair(bbox, 1),
                "bbox_w": _pair(bbox, 2),
                "bbox_h": _pair(bbox, 3),
                "centroid_x": _pair(centroid, 0),
                "centroid_y": _pair(centroid, 1),
                "pixel_area": detection.get("pixel_area"),
                "frame_width": _pair(resolution, 0),
                "frame_height": _pair(resolution, 1),
                "thumbnail": detection.get("thumbnail"),
                "recorded_at_epoch_s": detection.get("recorded_at_epoch_s"),
            })
    return target


def write_telemetry_csv(bundle_dir: str, fixes: Sequence[dict]) -> Optional[str]:
    """Write ``telemetry.csv``; returns its path, or ``None`` if empty."""
    if not fixes:
        return None
    target = os.path.join(bundle_dir, TELEMETRY_CSV)
    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=_TELEMETRY_CSV_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for fix in fixes:
            writer.writerow({key: fix.get(key) for key in _TELEMETRY_CSV_COLUMNS})
    return target


def build_aoi(detection: dict) -> dict:
    """Compose one ``areas_of_interest`` entry for a stored detection.

    The exported image is the detection's own thumbnail crop, so the AOI
    is expressed in thumbnail pixels: the crop is centered on the
    detection but clamped at the frame edges, which is why
    ``thumbnail_origin`` is needed rather than assuming the center.
    """
    bbox = detection.get("bbox") or []
    x = _pair(bbox, 0) or 0
    y = _pair(bbox, 1) or 0
    width = _pair(bbox, 2) or 0
    height = _pair(bbox, 3) or 0
    origin_x = _pair(detection.get("thumbnail_origin"), 0) or 0
    origin_y = _pair(detection.get("thumbnail_origin"), 1) or 0

    center_x = int(round(x + width / 2.0 - origin_x))
    center_y = int(round(y + height / 2.0 - origin_y))

    thumb_size = detection.get("thumbnail_size")
    thumb_w = _pair(thumb_size, 0)
    thumb_h = _pair(thumb_size, 1)
    if thumb_w and thumb_h:
        # A clamped crop can put the nominal center outside the saved
        # image; keep the marker on the thumbnail either way.
        center_x = max(0, min(int(thumb_w) - 1, center_x))
        center_y = max(0, min(int(thumb_h) - 1, center_y))

    radius = max(8, int(round(min(width, height) / 2.0))) if width and height else 20
    pixel_area = detection.get("pixel_area")
    if isinstance(pixel_area, (int, float)) and pixel_area > 0:
        area = int(round(pixel_area))
    else:
        area = int(round(width * height)) or 100

    aoi: Dict[str, Any] = {
        "center": (center_x, center_y),
        "radius": radius,
        "area": area,
        "number": int(detection.get("seq", 0)) + 1,
    }

    confidence = detection.get("confidence")
    if isinstance(confidence, (int, float)):
        aoi["confidence"] = float(confidence)
        aoi["score_type"] = "confidence"
        aoi["raw_score"] = float(confidence)
        aoi["score_method"] = "StreamingRecording"

    comment_parts: List[str] = []
    kind = detection.get("detection_type")
    if kind:
        comment_parts.append(str(kind))
    video_time = detection.get("video_time_seconds")
    if isinstance(video_time, (int, float)):
        comment_parts.append(f"at {_format_clock(float(video_time))}")
    if _has_location(detection):
        comment_parts.append(
            f"GPS: {float(detection['latitude']):.6f}, "
            f"{float(detection['longitude']):.6f}"
        )
    if comment_parts:
        aoi["user_comment"] = " | ".join(comment_parts)

    return aoi


def write_results_xml(
    bundle_dir: str,
    detections: Sequence[dict],
    manifest: dict,
) -> Optional[str]:
    """Write an image-mode ``ADIAT_Data.xml`` for the stored detections.

    Mirrors the Mission Gallery export: one ``image`` per detection
    pointing at its thumbnail, so the Images window's *Load Results File*
    opens a streaming recording with no receiving-side changes.
    """
    if not detections:
        return None

    # Imported lazily so the streaming stack does not pull XmlService (and
    # its dependencies) in at module import time.
    from core.services.XmlService import XmlService

    target = os.path.join(bundle_dir, RESULTS_XML)
    xml = XmlService()
    xml.xml_path = target

    options = {
        "source": "ADIAT Streaming Recording",
        "recorded_at": manifest.get("started_at") or "",
        "stream_source": (manifest.get("source") or {}).get("url") or "",
        "stream_type": (manifest.get("source") or {}).get("type") or "",
    }
    for key, value in (manifest.get("algorithm_options") or {}).items():
        # Namespaced so an algorithm option can never collide with the
        # provenance keys above.
        options[f"algorithm.{key}"] = value

    xml.add_settings_to_xml(**{
        "output_dir": bundle_dir,
        "input_dir": bundle_dir,
        "num_processes": 1,
        "identifier_color": (0, 255, 0),
        "aoi_radius": 20,
        "min_area": 1,
        "max_area": 0,
        "hist_ref_path": "",
        "kmeans_clusters": 0,
        "algorithm": manifest.get("algorithm") or _XML_ALGORITHM_FALLBACK,
        "thermal": "False",
        "options": options,
    })

    for detection in detections:
        thumbnail = detection.get("thumbnail")
        if not thumbnail:
            # Without an image there is nothing for the viewer to show;
            # the row still lives in detections.csv.
            continue
        thumb_size = detection.get("thumbnail_size") or []
        xml.add_image_to_xml({
            # Stored relative to the XML, with forward slashes: XmlService
            # resolves a relative path against the file's own directory, so
            # the whole bundle can be copied to a team drive and still open.
            # An absolute path would break the moment the folder moved.
            "path": str(thumbnail),
            "width": int(_pair(thumb_size, 0) or 0),
            "height": int(_pair(thumb_size, 1) or 0),
            "aois": [build_aoi(detection)],
        })

    xml.save_xml_file(target)
    return target


def _flight_map_requested(manifest: dict) -> bool:
    """Whether the operator asked for a flight map for this recording.

    Defaults to ``True`` when the manifest cannot say: a bundle recovered
    from a crash is better off with a map it may not have wanted than
    silently missing the one it did.
    """
    options = manifest.get("options")
    if not isinstance(options, dict) or "save_flight_map" not in options:
        return True
    return bool(options.get("save_flight_map"))


def write_flight_map(
    bundle_dir: str,
    path: Sequence[Tuple[float, float]],
    detections: Sequence[dict],
    manifest: dict,
) -> Optional[str]:
    """Write ``flight_map.html``; ``None`` when there is nothing to plot.

    Detections are geotagged whether or not a map was asked for, so the
    operator's choice has to be checked here - otherwise unchecking "Save
    flight map" would still produce one from the detections alone.
    """
    if not _flight_map_requested(manifest):
        return None
    geotagged = [d for d in detections if _has_location(d)]
    if not path and not geotagged:
        return None

    from core.services.export.FlightMapHtmlService import write_flight_map_html

    pins = [{
        "lat": float(d["latitude"]),
        "lon": float(d["longitude"]),
        "label": _detection_label(d),
        "details": _detection_details(d),
        "detection_type": d.get("detection_type"),
        "thumbnail": d.get("thumbnail"),
    } for d in geotagged]

    started = manifest.get("started_at") or ""
    caption_parts = []
    if started:
        caption_parts.append(started.replace("T", " "))
    caption_parts.append(f"{len(pins)} detection{'s' if len(pins) != 1 else ''}")
    caption_parts.append(f"{len(path)} fix{'es' if len(path) != 1 else ''}")
    algorithm = manifest.get("algorithm")
    if algorithm:
        caption_parts.append(str(algorithm))

    return write_flight_map_html(
        os.path.join(bundle_dir, FLIGHT_MAP_HTML),
        path=path,
        detections=pins,
        title="ADIAT Flight Map",
        caption=" · ".join(caption_parts),
    )


def write_flight_kml(
    bundle_dir: str,
    path: Sequence[Tuple[float, float]],
    detections: Sequence[dict],
    manifest: dict,
) -> Optional[str]:
    """Write ``flight_path.kml``; ``None`` when there is nothing to plot."""
    if not _flight_map_requested(manifest):
        return None
    geotagged = [d for d in detections if _has_location(d)]
    if len(path) < 2 and not geotagged:
        return None

    from core.services.export.KMLGeneratorService import KMLGeneratorService

    kml = KMLGeneratorService(use_terrain=False)
    started = manifest.get("started_at") or ""
    kml.add_flight_path(
        path,
        name="Flight Path",
        description=f"ADIAT streaming recording{f' - {started}' if started else ''}",
    )
    for detection in geotagged:
        kml.add_aoi_placemark(
            _detection_label(detection),
            float(detection["latitude"]),
            float(detection["longitude"]),
            "<br>".join(_detection_details(detection)),
            color_rgb=_bgr_to_rgb(detection.get("detection_color")),
        )

    target = os.path.join(bundle_dir, FLIGHT_PATH_KML)
    kml.save_kml(target)
    return target


def finalize_bundle(bundle_dir: str, logger: Optional[LoggerService] = None) -> Dict[str, Any]:
    """Derive every finished artifact for a bundle directory.

    Each artifact is attempted independently: a failure writing the KML
    must not cost the operator the results XML. Failures are logged and
    reported in the returned dict under ``errors``.

    Returns:
        ``{"bundle_dir", "artifacts", "counts", "errors"}``. Also rewrites
        ``manifest.json`` with the artifact list so the bundle describes
        itself.
    """
    log = logger or LoggerService()
    manifest = read_manifest(bundle_dir)
    detections = read_jsonl(os.path.join(bundle_dir, DETECTIONS_LOG))
    telemetry = read_jsonl(os.path.join(bundle_dir, TELEMETRY_LOG))
    path = _coords(telemetry)

    artifacts: Dict[str, Optional[str]] = {}
    errors: List[str] = []

    steps = (
        ("detections_csv", lambda: write_detections_csv(bundle_dir, detections)),
        ("results_xml", lambda: write_results_xml(bundle_dir, detections, manifest)),
        ("telemetry_csv", lambda: write_telemetry_csv(bundle_dir, telemetry)),
        ("flight_map_html", lambda: write_flight_map(bundle_dir, path, detections, manifest)),
        ("flight_path_kml", lambda: write_flight_kml(bundle_dir, path, detections, manifest)),
    )
    for name, step in steps:
        try:
            written = step()
        except Exception as exc:  # noqa: BLE001 - one artifact must not sink the rest
            log.error(f"Recording bundle {bundle_dir}: could not write {name}: {exc}")
            errors.append(f"{name}: {exc}")
            written = None
        artifacts[name] = os.path.basename(written) if written else None

    counts = {
        "detections_stored": len(detections),
        "detections_geotagged": sum(1 for d in detections if _has_location(d)),
        "telemetry_fixes": len(telemetry),
    }

    result = {
        "bundle_dir": bundle_dir,
        "artifacts": artifacts,
        "counts": counts,
        "errors": errors,
    }

    try:
        manifest.setdefault("counts", {}).update(counts)
        manifest["artifacts"] = artifacts
        manifest.setdefault("telemetry", {})["available"] = bool(path)
        manifest["finalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if errors:
            manifest["finalize_errors"] = errors
        with open(os.path.join(bundle_dir, MANIFEST_FILE), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
    except (OSError, TypeError, ValueError) as exc:
        log.error(f"Recording bundle {bundle_dir}: could not update manifest: {exc}")
        errors.append(f"manifest: {exc}")

    return result


__all__ = [
    "DETECTIONS_CSV",
    "FLIGHT_MAP_HTML",
    "FLIGHT_PATH_KML",
    "RESULTS_XML",
    "TELEMETRY_CSV",
    "build_aoi",
    "finalize_bundle",
    "write_detections_csv",
    "write_flight_kml",
    "write_flight_map",
    "write_results_xml",
    "write_telemetry_csv",
]
