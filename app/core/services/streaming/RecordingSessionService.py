"""Capture-time writer for a streaming recording session bundle.

A recording used to be a bare MP4 dropped into whatever directory the
operator picked. That loses everything the analysis produced: the
detections the operator was watching, and the flight the aircraft
actually flew. This service turns a recording into a **session bundle** —
one folder per recording holding the video alongside the record of what
was found and where::

    <recording dir>/ADIAT_Recording_20260819_142530/
        rtmp_recording_20260819_142530.mp4     video (+ rotated segments)
        detections/detection_0000.jpg ...      one thumbnail per confirmed track
        detections.jsonl                       appended live (crash-safe)
        telemetry.jsonl                        appended live (crash-safe)
        manifest.json                          session header + counts

The derived artifacts (``ADIAT_Data.xml``, ``detections.csv``,
``telemetry.csv``, ``flight_map.html``, ``flight_path.kml``) are built
from those JSONL logs by :mod:`~core.services.streaming.\
RecordingBundleService` when the recording stops.

``telemetry.jsonl`` holds each envelope verbatim, so it carries every
altitude reference the publisher and desktop enrichment produced —
``aircraft_altitude_agl_m`` is above the takeoff point (ATO) and
``aircraft_altitude_agl_terrain_m`` is above the terrain, never the
reverse. ``telemetry.csv`` writes an explicit column list, so a new key
reaches it only when that list names it.

Two properties drive the design:

* **Append-as-you-go.** Every confirmed detection is flushed to
  ``detections.jsonl`` and its thumbnail written the moment it arrives, so
  an app crash three hours into a flight leaves a bundle that still holds
  every detection up to the crash. Only the derived artifacts are lost,
  and :func:`RecordingBundleService.finalize_bundle` can rebuild those
  from the logs alone.
* **Off the UI thread.** JPEG encoding and file I/O run on this writer's
  own daemon thread, fed by a queue, so a burst of confirmed tracks cannot
  stall frame presentation. Deliberately a plain thread rather than a
  ``QThread``: the writer emits nothing and needs no event loop, and a
  ``QThread`` that loses its last reference while still running aborts the
  process, which is a poor trade for a background file writer.

The unit of record is the **confirmed track**, not the per-frame
detection. A per-frame log at 30 fps is mostly the same blob re-reported;
confirmed tracks are what the Detection Gallery shows and what the
operator actually reviews. Per-frame activity is kept as counters in the
manifest, and callers that genuinely need the raw stream can set
``frame_level_detections`` to also get ``frames.jsonl``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from queue import Queue, Empty
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from core.services.LoggerService import LoggerService

# Bump when the on-disk layout changes in a way a reader must notice.
BUNDLE_SCHEMA_VERSION = 1

BUNDLE_DIR_PREFIX = "ADIAT_Recording"
DETECTIONS_SUBDIR = "detections"
DETECTIONS_LOG = "detections.jsonl"
TELEMETRY_LOG = "telemetry.jsonl"
FRAMES_LOG = "frames.jsonl"
MANIFEST_FILE = "manifest.json"

# Thumbnails are already small crops from the tracker; 85 keeps them
# legible without bloating a long flight's bundle.
_THUMBNAIL_JPEG_QUALITY = 85

# Sentinel pushed onto the queue to wake the writer for shutdown.
_STOP = object()


@dataclass
class RecordingSessionConfig:
    """What the operator asked for, and what the session is recording."""

    root_dir: str
    save_detections: bool = True
    save_flight_map: bool = True
    frame_level_detections: bool = False
    algorithm: str = ""
    algorithm_options: Dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    source_type: str = ""
    resolution: Tuple[int, int] = (0, 0)
    fps_limit: Optional[int] = None
    # Which feed this recording came from, for multi-feed sessions (the
    # Flight Viewer records each drone independently). Recorded verbatim
    # in the manifest; a ``label`` key also names the bundle folder so two
    # drones recording at the same second stay distinguishable on disk.
    feed: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionRecord:
    """One confirmed track, in the shape it is stored.

    Coordinates follow the streaming contract (see
    :class:`~core.services.streaming.contracts.StreamDetection`): ``bbox``
    and ``centroid`` are source-frame pixels with a top-left origin, and
    ``frame_resolution`` is the frame they were measured against.

    Two time references are kept deliberately, and they answer different
    questions:

    * ``video_time_seconds`` places the detection on the *source's* clock,
      derived from its frame index and frame rate. For a video file that is
      the playback position, and seeking there finds the detection again.
      For a live feed the source has no timeline of its own, so it is the
      elapsed time since the stream connected — which is not the same as
      time since the recording started, and is only as accurate as the
      measured frame rate. It is also the column to join
      ``detections.csv`` to ``telemetry.csv`` on.
    * ``recorded_frame_index`` is the video writer's own frame counter when
      the track was confirmed, for locating the moment in the written MP4.
      Best-effort: the writer runs at a fixed frame rate and drops frames
      when its queue is full, so its timeline can drift from the source's.

    Either may be ``None`` when the source has not reported enough to
    derive it — an absent time is better than a fabricated one.
    """

    track_id: int
    bbox: Tuple[int, int, int, int]
    centroid: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    detection_type: str = "detection"
    # ADIAT Flight identifies tracks by string key, not integer id; both
    # are kept so either pipeline's identity survives into the record.
    track_key: Optional[str] = None
    # The publisher's wall clock for the detection, in ms (ADIAT Flight).
    # The natural join key against a flight session's telemetry rows,
    # which carry the same clock.
    captured_at_ms: Optional[int] = None
    # Normalized [x, y, w, h] in 0..1, when the detection arrived that way
    # (flight envelopes). Kept alongside the pixel bbox because the pixel
    # projection depends on a frame having been seen.
    bbox_norm: Optional[Tuple[float, float, float, float]] = None
    pixel_area: float = 0.0
    frame_resolution: Tuple[int, int] = (0, 0)
    first_frame_index: Optional[int] = None
    video_time_seconds: Optional[float] = None
    recorded_frame_index: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # The detection's own color where the algorithm reports one, as BGR
    # (the convention Track uses). Carried through so a color-based
    # result keeps its color in the exported KML.
    detection_color: Optional[Tuple[int, int, int]] = None
    # BGR crop, encoded to JPEG on the writer thread. Callers must hand
    # over a copy they will not mutate.
    thumbnail: Optional[np.ndarray] = None
    # Alternative to ``thumbnail``: an already-encoded JPEG (ADIAT Flight
    # ships mobile-cropped thumbs over the data channel). Written to disk
    # verbatim - no decode/re-encode round trip. When both are set, the
    # pre-encoded bytes win.
    thumbnail_jpeg: Optional[bytes] = None
    # Top-left of the crop within the source frame, so a consumer can
    # re-project bbox/centroid onto the saved thumbnail. ``None`` means
    # the crop geometry is unknown (a thumbnail produced elsewhere, e.g.
    # on the mobile publisher) - consumers must then center on the
    # thumbnail rather than project the bbox into it.
    thumbnail_origin: Optional[Tuple[int, int]] = (0, 0)


def _json_safe(value: Any) -> Any:
    """Coerce a value into something ``json.dump`` will accept.

    Total by design: a single unserializable value used to raise partway
    through ``json.dump``, leaving a half-written ``manifest.json`` that
    then read back as ``{}`` - losing the entire session header. The
    manifest records provenance, so a value rendered as its ``repr`` is
    worth far more than a corrupt file.

    Algorithm options are the reason this matters in practice: streaming
    controllers report their configuration straight from the widgets, and
    ``ColorAnomalyAndMotionDetection`` - the default - includes ``Enum``
    members (motion algorithm, contour method, colour space, fusion mode).
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, Enum):
        # Enums carry a stable primitive value; prefer it over the repr.
        return _json_safe(value.value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _sanitize_label(label: Optional[str]) -> str:
    """Reduce a feed label to filesystem-safe characters.

    Aircraft names are operator-typed ("TEXSAR 01 / thermal"), so anything
    outside a conservative set becomes ``-``. Capped so a runaway label
    cannot produce an unwieldy path.
    """
    if not label:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(label)).strip("-")
    return cleaned[:40]


def allocate_bundle_dir(root_dir: str, *, now: Optional[float] = None,
                        label: Optional[str] = None) -> Path:
    """Create and return a fresh, uniquely named bundle directory.

    Named for the wall clock so a folder listing sorts chronologically,
    plus an optional feed ``label`` so two feeds recording at the same
    moment (a multi-drone Flight Viewer session) stay tellable apart in a
    folder listing. A same-second collision still gets a ``_2``, ``_3``,
    ... suffix rather than being written into.
    """
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now if now is not None else time.time()))
    name = f"{BUNDLE_DIR_PREFIX}_{stamp}"
    suffix_label = _sanitize_label(label)
    if suffix_label:
        name = f"{name}_{suffix_label}"
    base = Path(root_dir) / name
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{suffix}")
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


class RecordingSessionWriter:
    """Owns a recording session's bundle directory and its live logs.

    Lifecycle: :meth:`start_session` → any number of
    :meth:`append_detection` / :meth:`append_telemetry` / :meth:`note_frame`
    calls from the UI thread → :meth:`finalize`. Calls made outside an
    active session are ignored, so a caller never has to guard them.

    Not a ``QObject``: nothing here needs signals or an event loop, and
    keeping it out of Qt's object graph means an abandoned writer is
    collected quietly instead of aborting the process.
    """

    def __init__(self, logger: Optional[LoggerService] = None):
        self.logger = logger or LoggerService()

        self._config: Optional[RecordingSessionConfig] = None
        self._bundle_dir: Optional[Path] = None
        self._queue: Queue = Queue()
        self._active = False
        self._started_at: Optional[float] = None
        self._thread: Optional[Thread] = None
        # Why the last start_session failed, for the caller to report. The
        # writer has no signals of its own by design.
        self.last_error: Optional[str] = None

        # Counters shared with the caller thread.
        self._counter_lock = Lock()
        self._frames_recorded = 0
        self._raw_detections = 0
        self._detections_stored = 0
        self._telemetry_fixes = 0
        self._detection_seq = 0

        # Filled in at finalize when a flight map was wanted but no fixes
        # arrived, so a bundle explains its own missing flight map.
        self._telemetry_note: Optional[str] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True between :meth:`start_session` and :meth:`finalize`."""
        return self._active

    @property
    def bundle_dir(self) -> Optional[str]:
        """The current session's bundle directory, or ``None``."""
        return str(self._bundle_dir) if self._bundle_dir is not None else None

    def start_session(self, config: RecordingSessionConfig) -> Optional[str]:
        """Create the bundle directory and begin accepting records.

        Returns the bundle directory, or ``None`` if it could not be
        created — in which case the caller should carry on recording video
        to the operator's chosen directory rather than fail the recording.
        """
        if self._active:
            self.logger.warning("Recording session already active; ignoring start_session")
            return self.bundle_dir

        self.last_error = None
        try:
            self._bundle_dir = allocate_bundle_dir(
                config.root_dir, label=(config.feed or {}).get("label")
            )
        except OSError as exc:
            self._bundle_dir = None
            self.last_error = str(exc)
            self.logger.error(f"Could not create recording bundle in {config.root_dir}: {exc}")
            return None

        self._config = config
        self._started_at = time.time()
        self._active = True
        with self._counter_lock:
            self._frames_recorded = 0
            self._raw_detections = 0
            self._detections_stored = 0
            self._telemetry_fixes = 0
            self._detection_seq = 0
        self._telemetry_note = None

        if config.save_detections:
            (self._bundle_dir / DETECTIONS_SUBDIR).mkdir(exist_ok=True)

        self._write_manifest(ended=False)
        self._thread = Thread(
            target=self._run,
            name="ADIAT-RecordingSessionWriter",
            daemon=True,
        )
        self._thread.start()
        return str(self._bundle_dir)

    def finalize(self, *, timeout_s: float = 10.0) -> Optional[str]:
        """Drain the queue, stop the thread, and stamp the final manifest.

        Returns the bundle directory so the caller can report or open it.
        Deriving ``ADIAT_Data.xml`` / the map is a separate step — see
        :func:`RecordingBundleService.finalize_bundle` — so the two
        concerns stay independently testable.
        """
        if not self._active:
            return self.bundle_dir

        self._active = False
        self._queue.put(_STOP)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout_s)
            if thread.is_alive():
                self.logger.warning("Recording session writer did not stop within timeout")
        self._thread = None

        # Only now are the counters final - fixes queued moments before the
        # stop are counted by the writer thread, not by the caller. Deciding
        # any earlier produced a manifest that said no location data arrived
        # while also reporting telemetry as available.
        #
        # Decided here rather than at start for the same reason in reverse: a
        # live feed's availability is unknown until its first envelope lands,
        # so a note written at start could contradict the flight that followed.
        if (self._config is not None and self._config.save_flight_map
                and self.counts["telemetry_fixes"] == 0):
            self._telemetry_note = (
                "No location data arrived while recording, so there is no flight map."
            )

        bundle = str(self._bundle_dir) if self._bundle_dir is not None else None
        self._write_manifest(ended=True)
        return bundle

    def discard(self) -> None:
        """Finalize, then delete the bundle if it never got any content.

        A bundle is created before the video writer is asked to start, so a
        failed start - or a window closed straight after - can leave a
        folder holding nothing but a manifest. Removing it keeps the
        operator's recordings folder honest: every ADIAT_Recording_* folder
        in there is a recording that actually happened.

        Deliberately narrow: anything beyond the manifest and an empty
        detections folder means real content, and the folder stays.
        """
        bundle = self._bundle_dir
        self.finalize()
        if bundle is None:
            return

        try:
            leftovers = {entry.name for entry in bundle.iterdir()}
        except OSError:
            return

        detections_dir = bundle / DETECTIONS_SUBDIR
        if DETECTIONS_SUBDIR in leftovers:
            try:
                if any(detections_dir.iterdir()):
                    return
            except OSError:
                return
            leftovers.discard(DETECTIONS_SUBDIR)
        if leftovers - {MANIFEST_FILE}:
            return

        try:
            if detections_dir.is_dir():
                detections_dir.rmdir()
            (bundle / MANIFEST_FILE).unlink(missing_ok=True)
            bundle.rmdir()
        except OSError as exc:
            self.logger.warning(f"Could not remove empty recording bundle {bundle}: {exc}")
        finally:
            self._bundle_dir = None

    # ------------------------------------------------------------------
    # capture
    # ------------------------------------------------------------------

    def append_detection(self, record: DetectionRecord) -> None:
        """Queue a confirmed detection for storage. No-op when inactive."""
        if not self._active or self._config is None or not self._config.save_detections:
            return
        self._queue.put(("detection", record))

    def append_telemetry(self, envelope: dict) -> None:
        """Queue one telemetry fix. No-op when inactive or map is off."""
        if not self._active or self._config is None or not self._config.save_flight_map:
            return
        if not isinstance(envelope, dict):
            return
        # Only fixes that actually carry a position can contribute to a
        # flight path; an envelope with no lat/lon is not worth a line.
        lat = envelope.get("aircraft_latitude")
        lon = envelope.get("aircraft_longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return
        self._queue.put(("telemetry", dict(envelope)))

    def note_frame(self, detection_count: int = 0, video_time_seconds: Optional[float] = None) -> None:
        """Record that one frame was written, with its raw detection count.

        Called once per recorded frame from the presentation path, so it
        stays deliberately cheap: two counter increments, and a queued
        line only when frame-level logging was explicitly asked for.
        """
        if not self._active:
            return
        with self._counter_lock:
            self._frames_recorded += 1
            self._raw_detections += max(0, int(detection_count))
        if self._config is not None and self._config.frame_level_detections:
            self._queue.put(("frame", {
                "detections": int(detection_count),
                "video_time_seconds": video_time_seconds,
            }))

    def next_detection_index(self) -> int:
        """Peek at the sequence number the next detection will be given."""
        with self._counter_lock:
            return self._detection_seq

    @property
    def counts(self) -> Dict[str, int]:
        """Live counters, safe to read from any thread."""
        with self._counter_lock:
            return {
                "frames_recorded": self._frames_recorded,
                "raw_detections": self._raw_detections,
                "detections_stored": self._detections_stored,
                "telemetry_fixes": self._telemetry_fixes,
            }

    # ------------------------------------------------------------------
    # writer thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Consume the queue, writing to the bundle's append-only logs.

        The log handles are opened and closed here so they are only ever
        touched by this thread. The manifest is written by the caller
        thread instead, and only when this thread is not running.
        """
        if self._bundle_dir is None:
            return

        handles: Dict[str, Any] = {}
        try:
            while True:
                try:
                    item = self._queue.get(timeout=0.5)
                except Empty:
                    if not self._active:
                        break
                    continue

                if item is _STOP:
                    break

                kind, payload = item
                try:
                    if kind == "detection":
                        self._write_detection(handles, payload)
                    elif kind == "telemetry":
                        self._write_telemetry(handles, payload)
                    elif kind == "frame":
                        self._write_frame(handles, payload)
                except Exception as exc:  # noqa: BLE001 - never kill the thread
                    self.logger.error(
                        f"Failed to store {kind} record in {self._bundle_dir}: {exc}"
                    )
        finally:
            for handle in handles.values():
                try:
                    handle.close()
                except OSError:
                    pass

    def _log_handle(self, handles: Dict[str, Any], filename: str):
        """Open (once) and return an append handle for a bundle log."""
        handle = handles.get(filename)
        if handle is None:
            handle = open(self._bundle_dir / filename, "a", encoding="utf-8")
            handles[filename] = handle
        return handle

    def _append_line(self, handles: Dict[str, Any], filename: str, payload: dict) -> None:
        """Append one JSON object and flush, so a crash keeps the line."""
        handle = self._log_handle(handles, filename)
        handle.write(json.dumps(_json_safe(payload), separators=(",", ":")) + "\n")
        handle.flush()

    def _write_detection(self, handles: Dict[str, Any], record: DetectionRecord) -> None:
        with self._counter_lock:
            seq = self._detection_seq
            self._detection_seq += 1

        payload = asdict(record)
        thumbnail = payload.pop("thumbnail", None)
        thumbnail_jpeg = payload.pop("thumbnail_jpeg", None)
        payload["seq"] = seq
        payload["recorded_at_epoch_s"] = time.time()

        thumb_name, thumb_size = self._write_thumbnail(seq, thumbnail, thumbnail_jpeg)
        payload["thumbnail"] = thumb_name
        if thumb_size is not None:
            # Saved so a consumer can size the exported AOI against the
            # thumbnail without re-decoding every JPEG.
            payload["thumbnail_size"] = [int(thumb_size[0]), int(thumb_size[1])]

        self._append_line(handles, DETECTIONS_LOG, payload)
        with self._counter_lock:
            self._detections_stored += 1

    def _write_thumbnail(
        self, seq: int, thumbnail, thumbnail_jpeg=None,
    ) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
        """Store a detection thumbnail.

        Returns ``(bundle-relative path, (width, height))`` or
        ``(None, None)`` when there is nothing to store.

        Pre-encoded JPEG bytes (ADIAT Flight's mobile-cropped thumbs) win
        over a raw crop and are written verbatim; they are decoded once
        here - on the writer thread - only to learn their dimensions for
        the AOI export.
        """
        relative = f"{DETECTIONS_SUBDIR}/detection_{seq:04d}.jpg"
        target = self._bundle_dir / relative

        if isinstance(thumbnail_jpeg, (bytes, bytearray)) and thumbnail_jpeg:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(bytes(thumbnail_jpeg))
            size = None
            try:
                decoded = cv2.imdecode(
                    np.frombuffer(bytes(thumbnail_jpeg), dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if decoded is not None and decoded.ndim >= 2:
                    size = (int(decoded.shape[1]), int(decoded.shape[0]))
            except Exception:  # noqa: BLE001 - size is a convenience, not a requirement
                size = None
            return relative, size

        if thumbnail is None or not isinstance(thumbnail, np.ndarray) or thumbnail.size == 0:
            return None, None
        ok, buffer = cv2.imencode(
            ".jpg", thumbnail, [int(cv2.IMWRITE_JPEG_QUALITY), _THUMBNAIL_JPEG_QUALITY]
        )
        if not ok:
            self.logger.warning(f"Could not encode thumbnail for detection {seq}")
            return None, None
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(buffer.tobytes())
        return relative, (int(thumbnail.shape[1]), int(thumbnail.shape[0]))

    def _write_telemetry(self, handles: Dict[str, Any], envelope: dict) -> None:
        payload = dict(envelope)
        payload["recorded_at_epoch_s"] = time.time()
        self._append_line(handles, TELEMETRY_LOG, payload)
        with self._counter_lock:
            self._telemetry_fixes += 1

    def _write_frame(self, handles: Dict[str, Any], payload: dict) -> None:
        payload = dict(payload)
        payload["recorded_at_epoch_s"] = time.time()
        self._append_line(handles, FRAMES_LOG, payload)

    # ------------------------------------------------------------------
    # manifest
    # ------------------------------------------------------------------

    def _write_manifest(self, *, ended: bool) -> None:
        """Write ``manifest.json``. Called only from the caller thread."""
        if self._bundle_dir is None or self._config is None:
            return
        try:
            # Serialized in full before the file is opened: opening with "w"
            # truncates, so a failure mid-encode would destroy the previous
            # manifest and leave an unparseable one in its place.
            payload = json.dumps(self.build_manifest(ended=ended), indent=2)
        except (TypeError, ValueError) as exc:
            self.logger.error(f"Could not build manifest for {self._bundle_dir}: {exc}")
            return
        try:
            with open(self._bundle_dir / MANIFEST_FILE, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as exc:
            self.logger.error(f"Could not write manifest in {self._bundle_dir}: {exc}")

    def build_manifest(self, *, ended: bool) -> dict:
        """Compose the manifest dict for the current session."""
        config = self._config
        counts = self.counts
        videos: List[str] = []
        if self._bundle_dir is not None:
            videos = sorted(p.name for p in self._bundle_dir.glob("*.mp4"))

        manifest: Dict[str, Any] = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "produced_by": "ADIAT Streaming",
            "started_at_epoch_s": self._started_at,
            "started_at": _iso(self._started_at),
            "ended_at_epoch_s": time.time() if ended else None,
            "ended_at": _iso(time.time()) if ended else None,
            "algorithm": config.algorithm if config else "",
            "algorithm_options": _json_safe(config.algorithm_options) if config else {},
            "source": {
                "url": config.source_url if config else "",
                "type": config.source_type if config else "",
            },
            "video": {
                "resolution": list(config.resolution) if config else [0, 0],
                "fps_limit": config.fps_limit if config else None,
                "files": videos,
            },
            "feed": _json_safe(config.feed) if config else {},
            "counts": counts,
            "options": {
                "save_detections": bool(config.save_detections) if config else False,
                "save_flight_map": bool(config.save_flight_map) if config else False,
                "frame_level_detections": bool(config.frame_level_detections) if config else False,
            },
            "telemetry": {
                "available": counts["telemetry_fixes"] > 0,
                "note": self._telemetry_note,
            },
        }
        return manifest


def _crop_with_context(frame: np.ndarray, bbox_px: Tuple[int, int, int, int]):
    """Crop a detection from ``frame`` with the gallery's context padding.

    Mirrors the streaming tracker's thumbnail crop (1.5x context, minimum
    120 px, clamped at the frame edges) so a desktop-cropped flight thumb
    looks like every other thumbnail in the app. Returns
    ``(crop, (origin_x, origin_y))`` or ``(None, None)`` when the bbox is
    unusable.
    """
    x, y, w, h = bbox_px
    if w <= 0 or h <= 0:
        return None, None
    frame_h, frame_w = frame.shape[:2]
    zoom_w = max(120, int(w * 1.5))
    zoom_h = max(120, int(h * 1.5))
    cx = x + w // 2
    cy = y + h // 2
    x1 = max(0, cx - zoom_w // 2)
    y1 = max(0, cy - zoom_h // 2)
    x2 = min(frame_w, cx + zoom_w // 2)
    y2 = min(frame_h, cy + zoom_h // 2)
    if x2 <= x1 or y2 <= y1:
        return None, None
    return frame[y1:y2, x1:x2].copy(), (x1, y1)


def detection_record_from_flight_envelope(
    envelope: dict,
    *,
    recorded_frame_index: Optional[int] = None,
    frame_bgr: Optional[np.ndarray] = None,
) -> DetectionRecord:
    """Build a :class:`DetectionRecord` from an ADIAT Flight envelope.

    Flight detections arrive over the data channel in a different shape
    from streaming tracks: a normalized bbox, a mobile-cropped JPEG thumb,
    and a ``location`` the *publisher* geotagged (so no desktop-side
    position resolution is needed or wanted). This converter maps that
    shape onto the bundle's record:

    * ``bbox_norm`` is stored as-is; the pixel ``bbox``/``centroid`` are
      projected against ``frame_bgr`` when a frame is available (they stay
      zero otherwise - normalized coordinates are the flight source of
      truth).
    * The mobile thumb passes through as ``thumbnail_jpeg`` with
      ``thumbnail_origin=None`` (its crop geometry is unknown, so the AOI
      export centers on it). When the envelope has no thumb, the latest
      video frame stands in: the detection is cropped with the gallery's
      context padding, and the known origin makes the AOI projection
      exact.
    * ``video_time_seconds`` stays ``None`` - a live feed has no seekable
      timeline; ``captured_at_ms`` (the publisher's clock) joins against
      the same session's telemetry, and ``recorded_frame_index`` locates
      the moment in the recorded MP4.
    """
    envelope = envelope if isinstance(envelope, dict) else {}

    bbox_norm = envelope.get("bbox_norm")
    norm: Optional[Tuple[float, float, float, float]] = None
    if isinstance(bbox_norm, (list, tuple)) and len(bbox_norm) >= 4:
        try:
            norm = tuple(float(v) for v in bbox_norm[:4])
        except (TypeError, ValueError):
            norm = None

    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)
    centroid: Optional[Tuple[int, int]] = None
    frame_resolution: Tuple[int, int] = (0, 0)
    pixel_area = 0.0
    if frame_bgr is not None and getattr(frame_bgr, "ndim", 0) >= 2 and norm is not None:
        frame_h, frame_w = frame_bgr.shape[:2]
        frame_resolution = (int(frame_w), int(frame_h))
        bbox = (
            int(round(norm[0] * frame_w)),
            int(round(norm[1] * frame_h)),
            int(round(norm[2] * frame_w)),
            int(round(norm[3] * frame_h)),
        )
        centroid = (bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
        pixel_area = float(bbox[2] * bbox[3])

    thumb = envelope.get("thumb_bytes")
    thumbnail_jpeg = bytes(thumb) if isinstance(thumb, (bytes, bytearray)) and thumb else None
    thumbnail = None
    thumbnail_origin: Optional[Tuple[int, int]] = None
    if thumbnail_jpeg is None and frame_bgr is not None and bbox != (0, 0, 0, 0):
        thumbnail, thumbnail_origin = _crop_with_context(frame_bgr, bbox)

    location = envelope.get("location") if isinstance(envelope.get("location"), dict) else {}
    lat = location.get("lat")
    lon = location.get("lon")

    confidence = envelope.get("confidence")
    captured = envelope.get("captured_at_ms")

    return DetectionRecord(
        track_id=0,
        bbox=bbox,
        centroid=centroid,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        detection_type=str(
            envelope.get("class_name") or envelope.get("detector_id") or "detection"
        ),
        track_key=str(envelope.get("track_key")) if envelope.get("track_key") else None,
        captured_at_ms=int(captured) if isinstance(captured, (int, float)) else None,
        bbox_norm=norm,
        pixel_area=pixel_area,
        frame_resolution=frame_resolution,
        first_frame_index=None,
        video_time_seconds=None,
        recorded_frame_index=recorded_frame_index,
        latitude=float(lat) if isinstance(lat, (int, float)) else None,
        longitude=float(lon) if isinstance(lon, (int, float)) else None,
        thumbnail=thumbnail,
        thumbnail_jpeg=thumbnail_jpeg,
        thumbnail_origin=thumbnail_origin,
    )


def _iso(epoch_s: Optional[float]) -> Optional[str]:
    """Render an epoch as a local-time ISO-8601 string."""
    if epoch_s is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch_s))


def read_manifest(bundle_dir: str) -> dict:
    """Read a bundle's manifest, or ``{}`` when absent/unreadable."""
    try:
        with open(os.path.join(bundle_dir, MANIFEST_FILE), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        return manifest if isinstance(manifest, dict) else {}
    except (OSError, ValueError):
        return {}


def read_jsonl(path: str) -> List[dict]:
    """Read a JSONL log, skipping any truncated trailing line.

    A bundle left behind by a crash can end mid-line; every complete line
    before it is still good data, so a partial tail is dropped rather than
    failing the whole read.
    """
    rows: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BUNDLE_DIR_PREFIX",
    "DETECTIONS_LOG",
    "DETECTIONS_SUBDIR",
    "FRAMES_LOG",
    "MANIFEST_FILE",
    "TELEMETRY_LOG",
    "DetectionRecord",
    "RecordingSessionConfig",
    "RecordingSessionWriter",
    "allocate_bundle_dir",
    "detection_record_from_flight_envelope",
    "read_jsonl",
    "read_manifest",
]
