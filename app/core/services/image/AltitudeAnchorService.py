"""Resolve one takeoff elevation per mission, so altitude stops being per-frame.

The drone's only *precise* altitude is barometric ATO — height above the
takeoff point, good to about a metre across a flight. Everything else is
noisy (per-frame GPS vertical is 3–10 m) or datum-ambiguous (EXIF
``GPSAltitude`` may be ellipsoidal or orthometric depending on airframe and
firmware, and nothing in the metadata says which). The defensible model is
therefore to estimate the one unknown constant — the takeoff point's
elevation in the DEM's own datum — once per mission, and let the barometer
carry every frame from there::

    camera_elevation(i) = anchor + ATO(i)
    AGL at ground point  = camera_elevation(i) − DEM(point)

Every consumer of "how high above the ground" shares this resolution: AOI
geolocation, GSD, coverage/POD, the altitude readout and the exports. It
was extracted from ``CoveragePodService``, which pioneered it; POD now
delegates here.

Two ways to resolve the anchor, best evidence first:

* **near-ground frame** — a frame whose ATO is nearly zero was taken at
  the launch point, so the DEM elevation at its position *is* the takeoff
  elevation. Entirely datum-free.
* **GPS ensemble** — each frame implies a takeoff elevation,
  ``(GPSAltitude − geoid) − ATO``, constant across the flight when the GPS
  datum and the barometer agree. The median over a bounded sample averages
  the GPS noise down; the spread is a direct coherence test.

Both are validated for physical plausibility (the anchor must leave the
aircraft above ground and within a sane height of it over the terrain
actually flown). Known limitation, inherited from POD and unchanged: a
constant datum mismatch in ``GPSAltitude`` is indistinguishable from a
genuine launch elevation, so only offsets large enough to fail the
plausibility check are caught — which is why the near-ground rule outranks
the ensemble, and why the resolved anchor and its source are reported
rather than silently applied.

The mission registry at the bottom is how per-image code reaches a
mission-level constant: the viewer registers its image list once, and
``get_mission_anchor()`` resolves lazily on first use. Resolution issues
DEM lookups, so display-path callers pass ``offline_only=True`` and simply
get no anchor until the tiles are local (terrain acquisition stocks them in
the background).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from core.services.LoggerService import LoggerService

# A camera resolved at or below the ground is bad data, not a small AGL.
MIN_AGL_M = 1.0

# A frame this close to the takeoff plane was taken at the launch site;
# below typical tree height, so a mid-air mission start cannot fake it.
NEAR_GROUND_ATO_M = 10.0

# Bounded pre-pass: a median over this many frames is plenty, and spreading
# them across the flight makes barometric drift show up in the spread
# rather than hiding at one end.
ANCHOR_SAMPLE_FRAMES = 40
ANCHOR_MIN_SAMPLES = 3            # below this the estimate cannot be cross-checked
ANCHOR_MAX_MAD_M = 15.0           # spread above which the GPS/baro chains disagree

# Plausibility ceiling when the caller has no better bound (POD passes its
# sensor max range instead). Far above any legal or practical SAR altitude.
DEFAULT_MAX_PLAUSIBLE_AGL_M = 2000.0

ANCHOR_SOURCE_NEAR_GROUND = 'near_ground'
ANCHOR_SOURCE_GPS_ENSEMBLE = 'gps_ensemble'
ANCHOR_SOURCE_DATUM_TEST = 'baro_datum_test'

REASON_OK = 'ok'
REASON_INSUFFICIENT = 'insufficient_samples'
REASON_INCOHERENT = 'incoherent'
REASON_IMPLAUSIBLE = 'implausible_agl'
REASON_DATUM_UNRESOLVED = 'datum_unresolved'

# The datum test's ground band: a takeoff-elevation candidate counts as
# "on the ground" when it is within this of terrain the flight actually
# overflew. Tight enough that the two candidates - separated by a full
# geoid undulation, 20-35 m across CONUS - cannot both qualify there.
GROUND_BAND_M = 10.0
# Below this separation the two candidates are closer than the ground
# band can distinguish; the test refuses rather than coin-flips (and the
# cost of the fallback is bounded by the same small separation).
MIN_DATUM_SEPARATION_M = 15.0

# A gap in capture time longer than this starts a new flight segment.
# Battery swaps at the same launch site can be quicker - merging those is
# harmless, the takeoff elevation is the same ground - while relocating to
# a different launch site takes longer than this in practice.
MISSION_SEGMENT_GAP_S = 600.0


@dataclass
class AltitudeAnchor:
    """The mission's takeoff elevation, or why it could not be resolved."""

    elevation_m: Optional[float] = None
    source: Optional[str] = None       # ANCHOR_SOURCE_* when resolved
    reason: str = REASON_OK            # REASON_* explaining an unresolved anchor
    spread_m: Optional[float] = None   # MAD of the ensemble, when computed
    sample_count: int = 0

    @property
    def resolved(self) -> bool:
        return self.elevation_m is not None and math.isfinite(self.elevation_m)


class AltitudeAnchorService:
    """Estimate the takeoff elevation for a mission of images.

    Pure computation plus DEM/geoid lookups; no Qt, no module state. The
    mission registry below owns the session-level caching.
    """

    def __init__(self, terrain_service=None, logger=None,
                 custom_altitude_ft=None,
                 max_plausible_agl_m: float = DEFAULT_MAX_PLAUSIBLE_AGL_M,
                 frame_geometry_fn=None,
                 strict_datum: bool = False):
        self.logger = logger or LoggerService()
        self._terrain = terrain_service
        self.custom_altitude_ft = custom_altitude_ft
        self.max_plausible_agl_m = float(max_plausible_agl_m)
        # Callers with their own (cheaper, or test-injected) metadata reader
        # supply it here; POD does. None uses the built-in cheap parse.
        self._frame_geometry_fn = frame_geometry_fn
        # When True, an anchor requires its datum to be established: a
        # near-ground frame (datum never enters), or the baro datum test
        # (the datum is *measured* against ground the flight overflew).
        # The raw GPS ensemble is refused however coherent it is - a
        # constant datum offset is perfectly coherent. POD opts out: its
        # sensor-range bound governs its ensemble use, with a documented
        # conservative residual bias.
        self.strict_datum = bool(strict_datum)
        self._geoid_memo = {}

    @property
    def terrain(self):
        if self._terrain is None:
            from core.services.terrain import TerrainService
            self._terrain = TerrainService()
        return self._terrain

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    def resolve(self, images: Sequence[dict],
                offline_only: bool = False) -> AltitudeAnchor:
        """Resolve the mission's takeoff elevation from its own imagery.

        Args:
            images (list[dict]): Image records carrying at least ``path``.
            offline_only (bool): Use cached elevation data only. An anchor
                that cannot be resolved from cache is reported unresolved
                rather than fetched for — display callers must not block.

        Returns:
            AltitudeAnchor: Resolved, or carrying the reason it is not.
        """
        frames = self._collect_frames(images)
        if not frames:
            # Same bucket as "too few usable samples": whether the mission
            # had no readable frames or too few, the estimate cannot be
            # cross-checked. Matches the contract POD pinned before the
            # resolver was extracted.
            return AltitudeAnchor(reason=REASON_INSUFFICIENT)

        near_ground = self._near_ground_anchor(frames, offline_only)
        if near_ground is not None:
            anchor = AltitudeAnchor(
                elevation_m=near_ground,
                source=ANCHOR_SOURCE_NEAR_GROUND,
                sample_count=len(frames),
            )
        elif self.strict_datum:
            anchor = self._datum_test_anchor(frames, offline_only)
            if not anchor.resolved:
                return anchor
        else:
            anchor = self._gps_ensemble_anchor(frames, offline_only)
            if not anchor.resolved:
                return anchor

        if not self._plausible(anchor.elevation_m, frames, offline_only):
            self.logger.warning(
                f"AltitudeAnchor: a takeoff elevation of {anchor.elevation_m:.0f} m "
                "puts the aircraft at an impossible height over the terrain "
                "flown; not using it.")
            return AltitudeAnchor(reason=REASON_IMPLAUSIBLE,
                                  spread_m=anchor.spread_m,
                                  sample_count=anchor.sample_count)

        self.logger.info(
            f"AltitudeAnchor: takeoff elevation {anchor.elevation_m:.1f} m "
            f"({anchor.source}, {anchor.sample_count} frame(s)"
            + (f", spread {anchor.spread_m:.1f} m" if anchor.spread_m is not None else "")
            + ")")
        return anchor

    # ------------------------------------------------------------------
    # the two resolution rules
    # ------------------------------------------------------------------

    def _near_ground_anchor(self, frames, offline_only) -> Optional[float]:
        """DEM elevation under the lowest frame, when that frame is near ground.

        Datum-free: no GPS altitude and no geoid enter it, which is why it
        outranks the ensemble — the ensemble cannot detect a constant datum
        offset, this cannot have one.
        """
        lowest = min(frames, key=lambda fg: fg.agl_m)
        if lowest.agl_m > NEAR_GROUND_ATO_M:
            return None
        elev = self._point_elevation(lowest.lat, lowest.lon, offline_only)
        if elev is None:
            return None
        return float(elev)

    def _gps_ensemble_anchor(self, frames, offline_only) -> AltitudeAnchor:
        """Median implied takeoff elevation across the flight.

        ``implied(i) = (GPSAltitude(i) − geoid(i)) − ATO(i)`` is a constant
        when the GPS datum and the barometer agree; the median averages GPS
        noise down and the MAD is the coherence test. Ported verbatim from
        ``CoveragePodService._resolve_altitude_anchor``.
        """
        samples = []
        for fg in frames:
            if fg.asl_alt_m is None:
                continue
            undulation = self._geoid_undulation(fg.lat, fg.lon, offline_only)
            if undulation is None:
                continue
            implied = (fg.asl_alt_m - undulation) - fg.agl_m
            if math.isfinite(implied):
                samples.append(implied)

        if len(samples) < ANCHOR_MIN_SAMPLES:
            return AltitudeAnchor(reason=REASON_INSUFFICIENT,
                                  sample_count=len(samples))

        arr = np.asarray(samples, dtype=np.float64)
        anchor = float(np.median(arr))
        mad = float(np.median(np.abs(arr - anchor)))
        if mad > ANCHOR_MAX_MAD_M:
            self.logger.warning(
                f"AltitudeAnchor: GPS-altitude and barometric-ATO chains disagree "
                f"across the flight (spread {mad:.1f} m > {ANCHOR_MAX_MAD_M:.0f} m); "
                "cannot trust a takeoff elevation from them.")
            return AltitudeAnchor(reason=REASON_INCOHERENT, spread_m=mad,
                                  sample_count=len(samples))

        return AltitudeAnchor(elevation_m=anchor,
                              source=ANCHOR_SOURCE_GPS_ENSEMBLE,
                              spread_m=mad, sample_count=len(samples))

    def _datum_test_anchor(self, frames, offline_only) -> AltitudeAnchor:
        """Resolve the takeoff elevation by *measuring* the altitude datum.

        DJI slaves the recorded absolute altitude to the barometer:
        ``GPSAltitude = takeoff_estimate + ATO``, which a real mission
        confirmed with an implied-constant spread of exactly 0.0 (238
        frames). The raw constant ``median(GPSAltitude - ATO)`` is
        therefore the firmware's takeoff estimate, in whatever datum the
        firmware used - and the two possibilities differ by exactly the
        geoid undulation::

            orthometric candidate = C
            ellipsoidal candidate = C - N        (h = H + N)

        The aircraft took off from ground near the flight, so the
        candidate lying on terrain the mission overflew is the real one.
        Exactly one qualifying candidate resolves the anchor; both or
        neither - relief near the undulation, a valley launch outside the
        photographed area - refuses, and the caller falls back. Wrong
        answers require ground at *both* elevations within the flight,
        which the separation bound makes the check refuse instead.
        """
        samples = [fg.asl_alt_m - fg.agl_m for fg in frames
                   if fg.asl_alt_m is not None and math.isfinite(fg.asl_alt_m)]
        if len(samples) < ANCHOR_MIN_SAMPLES:
            return AltitudeAnchor(reason=REASON_INSUFFICIENT,
                                  sample_count=len(samples))
        arr = np.asarray(samples, dtype=np.float64)
        constant = float(np.median(arr))
        mad = float(np.median(np.abs(arr - constant)))
        if mad > ANCHOR_MAX_MAD_M:
            return AltitudeAnchor(reason=REASON_INCOHERENT, spread_m=mad,
                                  sample_count=len(samples))

        undulations = []
        elevations = []
        for fg in frames:
            n = self._geoid_undulation(fg.lat, fg.lon, offline_only)
            if n is not None:
                undulations.append(n)
            elev = self._point_elevation(fg.lat, fg.lon, offline_only)
            if elev is not None:
                elevations.append(elev)
        if not undulations or not elevations:
            return AltitudeAnchor(reason=REASON_DATUM_UNRESOLVED, spread_m=mad,
                                  sample_count=len(samples))

        undulation = float(np.median(np.asarray(undulations)))
        if abs(undulation) < MIN_DATUM_SEPARATION_M:
            # The candidates are closer than ground can tell apart; the
            # fallback's error is bounded by the same small separation.
            return AltitudeAnchor(reason=REASON_DATUM_UNRESOLVED, spread_m=mad,
                                  sample_count=len(samples))

        candidates = {
            'orthometric': constant,
            'ellipsoidal': constant - undulation,
        }
        grounded = {
            name: min(abs(value - elev) for elev in elevations)
            for name, value in candidates.items()
        }
        on_ground = [name for name, d in grounded.items() if d <= GROUND_BAND_M]
        if len(on_ground) != 1:
            self.logger.info(
                "AltitudeAnchor: baro datum test inconclusive "
                f"(orthometric {grounded['orthometric']:.1f} m off ground, "
                f"ellipsoidal {grounded['ellipsoidal']:.1f} m off ground)")
            return AltitudeAnchor(reason=REASON_DATUM_UNRESOLVED, spread_m=mad,
                                  sample_count=len(samples))

        winner = on_ground[0]
        self.logger.info(
            f"AltitudeAnchor: baro datum test resolved the recorded altitude "
            f"as {winner} (takeoff {candidates[winner]:.1f} m, "
            f"{grounded[winner]:.1f} m off overflown ground; the other "
            f"candidate was {grounded['ellipsoidal' if winner == 'orthometric' else 'orthometric']:.1f} m off)")
        return AltitudeAnchor(elevation_m=candidates[winner],
                              source=ANCHOR_SOURCE_DATUM_TEST,
                              spread_m=mad, sample_count=len(samples))

    def _plausible(self, anchor_elev, frames, offline_only) -> bool:
        """The anchor must leave the aircraft flying over the terrain flown."""
        implied_agls = []
        for fg in frames:
            elev = self._point_elevation(fg.lat, fg.lon, offline_only)
            if elev is None:
                continue
            implied_agls.append(anchor_elev + fg.agl_m - elev)
        if not implied_agls:
            # No terrain to test against: accept, the per-point floor in the
            # consumers still guards individual frames.
            return True
        median_agl = float(np.median(implied_agls))
        return MIN_AGL_M <= median_agl <= self.max_plausible_agl_m

    # ------------------------------------------------------------------
    # inputs
    # ------------------------------------------------------------------

    def _collect_frames(self, images):
        """Frame geometry for a bounded, evenly spaced sample of ``images``.

        Frames whose altitude is an explicit override are excluded: an
        override is a true AGL, not a height above takeoff, so it cannot
        inform the anchor (and such frames bypass it downstream anyway).
        """
        frames = []
        for image in self.sample(images):
            if self._agl_is_override(image):
                continue
            reader = self._frame_geometry_fn or self._frame_geometry
            try:
                fg = reader(image)
            except Exception:  # noqa: BLE001 - one bad frame is not a mission
                continue
            if fg is None or not fg.agl_m or fg.agl_m <= 0:
                continue
            frames.append(fg)
        return frames

    @staticmethod
    def segment_mission(images, metadata_fn=None):
        """Group ``images`` into flight segments.

        The anchored model's constant - the takeoff elevation - holds per
        *flight*, and a SAR folder holds many flights by many pilots. Two
        signals separate them, in order:

        * **aircraft serial** - simultaneous pilots interleave in capture
          time, so the serial has to partition first;
        * **capture-time gaps** - within one aircraft's images, a gap
          longer than :data:`MISSION_SEGMENT_GAP_S` is a new launch.

        An image with neither serial nor timestamp cannot be assigned to a
        flight, so it becomes a singleton segment: it will anchor nothing
        and fall back, rather than borrow another flight's launch site.

        Args:
            images (list[dict]): Records carrying ``path``.
            metadata_fn (callable, optional): ``image -> (serial, datetime)``
                for tests; None reads EXIF/XMP with the cheap parsers.

        Returns:
            list[list[dict]]: Segments, each a list of image records.
        """
        reader = metadata_fn or AltitudeAnchorService._segment_metadata
        keyed = []
        loners = []
        for image in images:
            try:
                serial, stamp = reader(image)
            except Exception:  # noqa: BLE001 - unreadable == unassignable
                serial, stamp = None, None
            if stamp is None:
                loners.append(image)
            else:
                keyed.append((serial or '', stamp, image))

        segments = []
        keyed.sort(key=lambda t: (t[0], t[1]))
        current = []
        prev_serial, prev_stamp = None, None
        for serial, stamp, image in keyed:
            new_flight = (
                prev_serial is None
                or serial != prev_serial
                or (stamp - prev_stamp).total_seconds() > MISSION_SEGMENT_GAP_S
            )
            if new_flight and current:
                segments.append(current)
                current = []
            current.append(image)
            prev_serial, prev_stamp = serial, stamp
        if current:
            segments.append(current)
        segments.extend([loner] for loner in loners)
        return segments

    @staticmethod
    def _segment_metadata(image):
        """``(aircraft serial, capture time)`` for one image, cheaply.

        The serial prefers the XMP drone serial (per-aircraft), then the
        EXIF body serial (per-camera - still separates two aircraft). Both
        read with the fast parsers; no ExifTool process.
        """
        import piexif
        from helpers.MetaDataHelper import MetaDataHelper
        path = image.get('path', '')
        if not path:
            return None, None
        exif_data = MetaDataHelper.get_exif_data_piexif(path)
        stamp = MetaDataHelper.get_exif_timestamp(exif_data)

        serial = None
        try:
            xmp_data = MetaDataHelper.get_xmp_data_direct(path)
            make = MetaDataHelper.get_drone_make(exif_data)
            if xmp_data and make:
                serial = MetaDataHelper.get_drone_xmp_attribute(
                    'Drone SN', make, xmp_data)
        except Exception:  # noqa: BLE001 - a serial is a nicety
            serial = None
        if not serial:
            raw = exif_data.get('Exif', {}).get(piexif.ExifIFD.BodySerialNumber)
            if isinstance(raw, bytes):
                serial = raw.decode('utf-8', 'replace').strip().rstrip('\x00')
            elif isinstance(raw, str):
                serial = raw.strip()
        return (serial or None), stamp

    @staticmethod
    def sample(images):
        """Evenly spaced, bounded subset of ``images`` for the pre-pass.

        Bounded so the cost is O(1) in mission size, and spread across the
        flight so barometric drift shows up in the spread rather than hiding
        at one end.
        """
        candidates = [im for im in images
                      if not im.get('hidden', False) and im.get('path', '') != '']
        if not candidates:
            return []
        step = max(1, len(candidates) // ANCHOR_SAMPLE_FRAMES)
        return candidates[::step][:ANCHOR_SAMPLE_FRAMES]

    def _agl_is_override(self, image) -> bool:
        if self.custom_altitude_ft is not None and self.custom_altitude_ft > 0:
            return True
        wingtra = image.get('wingtra_agl_ft')
        return wingtra is not None and wingtra > 0

    def _frame_geometry(self, image):
        """Pose + ATO for one image, via the cheap metadata parse.

        Mirrors POD's reader: piexif for EXIF and the direct byte-parser for
        XMP, so no ExifTool process is spawned per image; one full-reader
        retry for a GPS-tagged image the fast parse missed.
        """
        path = image.get('path', '')
        if not path:
            return None
        from helpers.MetaDataHelper import MetaDataHelper
        from helpers.LocationInfo import LocationInfo
        exif_data = MetaDataHelper.get_exif_data_piexif(path)
        fg = self._build_frame_geometry(image, path, exif_data,
                                        MetaDataHelper.get_xmp_data_direct(path))
        if fg is None and LocationInfo.get_gps(exif_data=exif_data):
            fg = self._build_frame_geometry(image, path, exif_data,
                                            MetaDataHelper.get_xmp_data_merged(path))
        return fg

    def _build_frame_geometry(self, image, path, exif_data, xmp_data):
        from core.services.image.ImageService import ImageService
        svc = ImageService(path, image.get('mask_path', ''),
                           img_array=_DUMMY_IMG,
                           calculated_bearing=image.get('bearing'),
                           exif_data=exif_data, xmp_data=xmp_data)
        # Drop the dummy pixels so FrameGeometry reads image size from EXIF
        # (the anchor never needs pixels -> skip the 20 MP decode cost).
        svc.img_array = None
        return svc.get_frame_geometry(
            custom_altitude_ft=self.custom_altitude_ft,
            bearing_quality=image.get('bearing_quality'),
            agl_override_ft=image.get('wingtra_agl_ft'))

    # ------------------------------------------------------------------
    # terrain access
    # ------------------------------------------------------------------

    def _point_elevation(self, lat, lon, offline_only) -> Optional[float]:
        getter = getattr(self.terrain, 'get_elevation', None)
        if getter is None:
            # Duck-typed samplers (POD may supply one) need not offer point
            # lookups at all; the resolver then leans on the other inputs.
            return None
        try:
            try:
                result = getter(lat, lon, offline_only=offline_only)
            except TypeError:
                # Pre-offline-flag signature; a full lookup is what it does.
                result = getter(lat, lon)
        except Exception:  # noqa: BLE001 - no terrain is "cannot resolve"
            return None
        if getattr(result, 'source', None) != 'terrain':
            return None
        elev = getattr(result, 'elevation_m', None)
        if elev is None or not math.isfinite(elev):
            return None
        return float(elev)

    def _geoid_undulation(self, lat, lon, offline_only) -> Optional[float]:
        """Memoised on a ~1 km key; the undulation field is smooth.

        Only successful lookups are memoised: the geoid grid loads lazily
        and a first-call failure must not poison the rest of the mission.
        """
        getter = getattr(self.terrain, 'get_geoid_undulation', None)
        if getter is None:
            return None
        key = (round(lat, 2), round(lon, 2))
        if key in self._geoid_memo:
            return self._geoid_memo[key]
        try:
            try:
                value = getter(lat, lon, offline_only=offline_only)
            except TypeError:
                value = getter(lat, lon)
        except Exception as e:  # noqa: BLE001
            self.logger.warning(
                f"AltitudeAnchor: geoid lookup failed at {lat:.5f},{lon:.5f}: {e}")
            return None
        if value is None:
            return None
        self._geoid_memo[key] = float(value)
        return self._geoid_memo[key]


# Deferred-decode placeholder for _build_frame_geometry; module level so the
# array is built once. Same trick as CoveragePodService.
_DUMMY_IMG = np.zeros((2, 2, 3), dtype=np.uint8)


# ----------------------------------------------------------------------
# mission registry
#
# Per-image code (ImageService, AOIService) has no mission context of its
# own, so the surface that does — the viewer, a batch run — registers the
# image list here once and everything downstream shares one lazily
# resolved anchor. Same module-singleton pattern as AOIService's shared
# TerrainService.
# ----------------------------------------------------------------------

_registry_lock = threading.Lock()
_mission_images: Optional[list] = None
_mission_custom_alt_ft: Optional[float] = None
_segments: Optional[list] = None            # list[list[image]]
_path_to_segment: Optional[dict] = None     # path -> segment index
_segment_anchors: dict = {}                 # index -> AltitudeAnchor
_segment_offline: dict = {}                 # index -> offline_only of that resolve


def set_mission_images(images, custom_altitude_ft=None) -> None:
    """Register the image set the current session is working.

    Replaces any previous mission and drops every cached per-flight anchor.
    Cheap: neither segmentation nor resolution happens until
    :func:`get_mission_anchor` is first called.
    """
    global _mission_images, _mission_custom_alt_ft
    global _segments, _path_to_segment
    with _registry_lock:
        _mission_images = list(images) if images else None
        _mission_custom_alt_ft = custom_altitude_ft
        _segments = None
        _path_to_segment = None
        _segment_anchors.clear()
        _segment_offline.clear()


def clear_mission() -> None:
    set_mission_images(None)


def _ensure_segments():
    """Segment the mission once, lazily. Caller holds no lock."""
    global _segments, _path_to_segment
    with _registry_lock:
        if _segments is not None or _mission_images is None:
            return
        images = list(_mission_images)
    segments = AltitudeAnchorService.segment_mission(images)
    mapping = {}
    for index, segment in enumerate(segments):
        for image in segment:
            path = image.get('path', '')
            if path:
                mapping[path] = index
    with _registry_lock:
        if _segments is None:
            _segments = segments
            _path_to_segment = mapping


def get_mission_anchor(offline_only: bool = True,
                       image_path: Optional[str] = None) -> Optional[AltitudeAnchor]:
    """The anchor for the flight ``image_path`` belongs to.

    Anchors are per *flight segment* - a SAR mission folder holds several
    flights from several launch sites, and a launch frame from one flight
    must never anchor another. Without ``image_path`` an anchor is returned
    only when the whole mission is a single segment.

    A resolved anchor is cached for the segment. An unresolved result is
    cached only against equally-capable calls: a failure under
    ``offline_only`` (tiles not local yet) is retried when a caller that
    may fetch asks; a full-access failure is final.

    Returns:
        AltitudeAnchor or None: None when no mission is registered or the
        image cannot be tied to a flight.
    """
    with _registry_lock:
        if _mission_images is None:
            return None
        custom_alt = _mission_custom_alt_ft
    _ensure_segments()
    with _registry_lock:
        segments = _segments
        mapping = _path_to_segment
    if not segments:
        return None

    if image_path is not None:
        index = mapping.get(image_path)
        if index is None:
            return None
    elif len(segments) == 1:
        index = 0
    else:
        return None

    with _registry_lock:
        cached = _segment_anchors.get(index)
        cached_offline = _segment_offline.get(index)
    if cached is not None:
        if cached.resolved or cached_offline is False or offline_only:
            return cached

    anchor = AltitudeAnchorService(
        custom_altitude_ft=custom_alt,
        strict_datum=True,
    ).resolve(segments[index], offline_only=offline_only)
    with _registry_lock:
        held = _segment_anchors.get(index)
        if held is None or not held.resolved:
            _segment_anchors[index] = anchor
            _segment_offline[index] = offline_only
        return _segment_anchors[index]


def mission_anchor_elevation(offline_only: bool = True,
                             image_path: Optional[str] = None) -> Optional[float]:
    """Convenience: the resolved elevation for one image, or None."""
    anchor = get_mission_anchor(offline_only=offline_only, image_path=image_path)
    if anchor is not None and anchor.resolved:
        return anchor.elevation_m
    return None
