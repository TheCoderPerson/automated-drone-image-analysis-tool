"""
WaldoMetadataService - Detect WALDO airplane images and synthesise
ADIAT-compatible XMP gimbal/altitude/heading fields on first folder load.

WALDO airframe assumptions (per user spec):
    - Two Canon EOS 5DS R DSLRs in left/right pods.
    - Filename prefix `0_*` = left camera, `1_*` = right camera.
    - 22.5° outward roll about the heading axis. Camera otherwise nadir.
    - Plane assumed roughly level (bank ignored).
    - GPS altitude is ellipsoidal (WGS84-native).

The synthesised XMP fields use the standard `drone-dji:` namespace so the
existing ADIAT pipeline (ImageService, AOIService, GPSMapView,
CoverageExtentService) reads them without modification:
    drone-dji:GimbalPitchDegree, GimbalYawDegree, GimbalRollDegree,
    drone-dji:FlightYawDegree, RelativeAltitude, AbsoluteAltitude.

Plus a custom marker so the pre-pass doesn't re-run on already-processed images:
    waldo:Processed = "true"
    waldo:ProcessorVersion = "<int>"
"""

import math
import os
import piexif
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from helpers.MetaDataHelper import MetaDataHelper
from helpers.LocationInfo import LocationInfo
from core.services.LoggerService import LoggerService
from core.services.shadow.SolarPosition import (
    SolarTimeUnresolvable,
    get_solar_position,
    resolve_capture_utc,
)


WALDO_NAMESPACE_URI = "http://adiat.io/ns/waldo/1.0/"
# Version 7: GimbalRollDegree is expressed about the FLIGHT axis
# (FlightYawDegree) rather than the gimbal-yaw axis (consumers key the
# convention off version >= 6), and GimbalYawDegree comes from the mounting
# model unless inter-frame motion measurement confidently CONTRADICTS it
# (catches datasets whose post-flight software re-orients the frames).
# Version 7 also retires v6's sun-shadow orientation measurement: on steep
# terrain at low sun, slope shear and charred fallen logs mislead it.
WALDO_PROCESSOR_VERSION = "7"

DRONE_DJI_NS = "http://www.dji.com/drone-dji/1.0/"

# Heading-derivation tunables
STATIONARY_THRESHOLD_M = 5.0
MAX_NEIGHBOR_DT_S = 30.0
OUTWARD_ROLL_DEG = 22.5

# Orientation-measurement tunables. Field imagery showed the mounting-model
# yaw assumption off by ~41 degrees (post-flight software had normalized the
# frames north-up), so orientation is measured from the imagery itself.
# The measurement: inter-frame content motion vs the GPS track (feature
# matching between consecutive frames). It carries tens-of-degrees of noise
# on tilted fixed-wing imagery over relief, so it never fine-tunes the
# model - it only OVERRIDES the model when it confidently disagrees by more
# than the override threshold (e.g. frames normalized north-up by post-flight
# software read ~180 deg away from the model; measurement noise never does).
ORIENTATION_SAMPLE_PAIRS = 16      # consecutive-image pairs sampled per camera
ORIENTATION_MIN_PAIRS = 4          # accept a measurement only with this many good pairs
ORIENTATION_MAX_STDERR_DEG = 8.0   # confidence required of the circular mean
ORIENTATION_MIN_BASELINE_M = 30.0  # pairs closer than this give unreliable bearings
ORIENTATION_MIN_INLIERS = 20       # ORB/RANSAC inliers required per pair
ORIENTATION_DOWNSCALE = 6          # feature matching runs at 1/N resolution
ORIENTATION_OVERRIDE_DEG = 60.0    # measured-vs-model gap that trips the override

# Filename prefix → cam index. 0_* = left, 1_* = right.
_WALDO_PREFIX_RE = re.compile(r'^(?P<cam>[01])_')


class WaldoHeadingUnavailable(Exception):
    """Raised when neither neighbour fill nor cross-cam fallback yields a heading."""


class WaldoCoverageError(Exception):
    """Raised when the configured DEM does not cover the image GPS location."""


class WaldoMissingGPSError(Exception):
    """Raised when an image has no GPS data to derive heading or AGL from."""


@dataclass
class WaldoImageRecord:
    """In-memory record built per WALDO image during the pre-pass."""
    path: str
    name: str
    cam_idx: int  # 0 or 1
    lat: Optional[float] = None
    lon: Optional[float] = None
    gps_alt_ellipsoidal: Optional[float] = None
    timestamp: Optional[datetime] = None
    heading_deg: Optional[float] = None
    error: Optional[str] = None


@dataclass
class WaldoProcessResult:
    """Aggregate result of process_folder."""
    processed: int = 0
    already_current: int = 0
    skipped: int = 0  # non-WALDO files
    errors: List[Tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


class WaldoMetadataService:
    """Pure-logic service: detection, heading derivation, XMP synthesis."""

    def __init__(self, terrain_service=None):
        self.terrain_service = terrain_service
        self.logger = LoggerService()

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_waldo_image(filename: str) -> Optional[int]:
        """Return cam_idx (0 or 1) for WALDO files; None otherwise."""
        if not filename:
            return None
        base = os.path.basename(filename)
        m = _WALDO_PREFIX_RE.match(base)
        if not m:
            return None
        return int(m.group('cam'))

    @staticmethod
    def is_already_processed(image_path: str) -> bool:
        """True if the image's XMP carries the WALDO processed marker at the current version."""
        try:
            xmp = MetaDataHelper.get_xmp_data_merged(image_path) or {}
        except Exception:
            return False
        for key in ('waldo:Processed', 'Processed', 'XMP-waldo:Processed'):
            if key in xmp and str(xmp[key]).lower() in ('true', '1', 'yes'):
                version = (
                    xmp.get('waldo:ProcessorVersion')
                    or xmp.get('ProcessorVersion')
                    or xmp.get('XMP-waldo:ProcessorVersion')
                )
                if str(version) == WALDO_PROCESSOR_VERSION:
                    return True
                # Marker present but version mismatch: re-process.
                return False
        return False

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_optical_axis_angles(heading_deg: float, cam_idx: int,
                                    image_up_deg: Optional[float] = None) -> Dict[str, float]:
        """Return drone-dji-style gimbal triple for a WALDO capture.

        Yaw — the compass bearing of the stored JPEG's top edge, which is
        what AOIService and the FOV-box renderer consume:

        - When `image_up_deg` is given it is the *measured* orientation
          (from inter-frame content motion vs the GPS track; see
          measure_image_up_bearing) and is used directly. Field imagery
          proved the mounting model below wrong by ~41° on flights whose
          post-flight software had normalized frames north-up, so a
          measurement always wins over the model.
        - Fallback (no measurement): the pod-mounting model, per WALDO
          operator 2026-05-04 + screenshot. Cam 0 (`0_*`, RIGHT pod) is
          stored rotated 180° by post-flight software; cam 1 (`1_*`,
          LEFT pod) has body top facing the tail. Both stored images then
          share image-top = plane backward: `yaw = heading + 180°`.

        Roll — the pods physically tilt ±OUTWARD_ROLL_DEG cross-track
        (cam 0 to plane RIGHT, cam 1 to plane LEFT). As of processor
        version 6 the roll is expressed about the FLIGHT axis
        (FlightYawDegree), which stays physically meaningful whatever the
        stored image orientation is. About the *forward* flight axis a
        positive Rodrigues roll tilts the optical axis to plane LEFT, so
        cam 0 (right tilt) takes -OUTWARD_ROLL_DEG and cam 1 takes
        +OUTWARD_ROLL_DEG — the opposite signs from version 5, which
        expressed roll about the backward gimbal-yaw axis. Consumers pick
        the axis by ProcessorVersion. Pitch is fixed at nadir.
        """
        if cam_idx not in (0, 1):
            raise ValueError(f"Invalid WALDO cam_idx {cam_idx}")
        if image_up_deg is not None:
            yaw = float(image_up_deg) % 360.0
        else:
            yaw = (float(heading_deg) + 180.0) % 360.0
        roll = (-OUTWARD_ROLL_DEG) if cam_idx == 0 else (+OUTWARD_ROLL_DEG)
        return {
            'pitch': -90.0,
            'yaw': yaw,
            'roll': roll,
        }

    # ------------------------------------------------------------------
    # Image-orientation measurement
    # ------------------------------------------------------------------

    @staticmethod
    def _pair_orientation_sample(path_a: str, path_b: str,
                                 bearing_deg: float) -> Optional[Tuple[float, int]]:
        """Measure image-top bearing from one consecutive image pair.

        Feature-matches the two frames, takes the content shift, and derives
        which compass bearing the image's top edge points to: the camera's
        world motion (GPS bearing a->b) appears in image coordinates as the
        negated content shift, and the angle between them is the rotation of
        the image frame relative to north.

        Returns:
            (image_up_bearing_deg, inlier_count), or None when the pair
            cannot be matched confidently.
        """
        try:
            f = ORIENTATION_DOWNSCALE
            imgs = []
            for p in (path_a, path_b):
                img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    return None
                imgs.append(cv2.resize(img, (img.shape[1] // f, img.shape[0] // f),
                                       interpolation=cv2.INTER_AREA))
            a, b = imgs

            orb = cv2.ORB_create(3000)
            ka, da = orb.detectAndCompute(a, None)
            kb, db = orb.detectAndCompute(b, None)
            if da is None or db is None or len(ka) < ORIENTATION_MIN_INLIERS:
                return None
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = sorted(matcher.match(da, db), key=lambda m: m.distance)[:800]
            if len(matches) < ORIENTATION_MIN_INLIERS:
                return None
            src = np.float32([ka[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
            dst = np.float32([kb[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
            M, inliers = cv2.estimateAffinePartial2D(src, dst, ransacReprojThreshold=3.0)
            if M is None or inliers is None:
                return None
            n_inliers = int(inliers.sum())
            if n_inliers < ORIENTATION_MIN_INLIERS:
                return None
            # Consecutive frames share orientation; a big relative rotation
            # means the affine locked onto repeating texture, not real overlap
            rel_rot = math.degrees(math.atan2(M[1, 0], M[0, 0]))
            if abs(rel_rot) > 8.0:
                return None

            # Ground content at a's centre appears in b displaced by the
            # camera's motion, negated
            c = np.array([a.shape[1] / 2.0, a.shape[0] / 2.0, 1.0])
            mapped = M @ c
            content_dx, content_dy = mapped[0] - c[0], mapped[1] - c[1]
            cam_dx, cam_dy = -content_dx, -content_dy
            if abs(cam_dx) < 1e-6 and abs(cam_dy) < 1e-6:
                return None
            # Camera motion direction in image terms, clockwise from image-up
            motion_img_deg = math.degrees(math.atan2(cam_dx, -cam_dy)) % 360.0
            image_up = (float(bearing_deg) - motion_img_deg) % 360.0
            return image_up, n_inliers
        except Exception:
            return None

    @staticmethod
    def _circular_stats(angles_deg: List[float],
                        weights: List[float]) -> Tuple[float, float]:
        """Weighted circular mean and spread (degrees) of compass angles."""
        angles = np.radians(np.asarray(angles_deg, dtype=float))
        wgt = np.asarray(weights, dtype=float)
        sin_sum = float((wgt * np.sin(angles)).sum())
        cos_sum = float((wgt * np.cos(angles)).sum())
        mean_deg = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
        resultant = math.hypot(sin_sum, cos_sum) / float(wgt.sum())
        resultant = min(1.0, max(1e-9, resultant))
        spread_deg = math.degrees(math.sqrt(-2.0 * math.log(resultant)))
        return mean_deg, spread_deg

    def _pair_motion_bearing(self, group: List["WaldoImageRecord"]) -> Optional[Tuple[float, float, int]]:
        """Coarse image-top bearing from inter-frame motion vs the GPS track.

        Returns:
            (mean_deg, spread_deg, sample_count), or None with no usable pairs.
        """
        candidates = []
        for a, b in zip(group, group[1:]):
            north_m = (b.lat - a.lat) * 111320.0
            east_m = (b.lon - a.lon) * 111320.0 * math.cos(math.radians(a.lat))
            dist = math.hypot(north_m, east_m)
            if dist < ORIENTATION_MIN_BASELINE_M:
                continue
            bearing = math.degrees(math.atan2(east_m, north_m)) % 360.0
            candidates.append((a.path, b.path, bearing))
        if not candidates:
            return None

        step = max(1, len(candidates) // ORIENTATION_SAMPLE_PAIRS)
        samples = []
        for path_a, path_b, bearing in candidates[::step][:ORIENTATION_SAMPLE_PAIRS]:
            result = self._pair_orientation_sample(path_a, path_b, bearing)
            if result is not None:
                samples.append(result)
        if len(samples) < 2:
            return None
        mean_deg, spread_deg = self._circular_stats(
            [s[0] for s in samples], [s[1] for s in samples])
        return mean_deg, spread_deg, len(samples)

    def measure_image_up_bearing(self, records: List["WaldoImageRecord"],
                                 cam_idx: int) -> Optional[float]:
        """Return a measured image-top bearing ONLY when it refutes the model.

        The inter-frame-motion measurement is too noisy on tilted fixed-wing
        imagery over relief to fine-tune the mounting model, but a dataset
        whose frames were re-oriented by post-flight software reads far away
        from the model (typically ~180 deg) - far beyond measurement noise.
        So: measure, and return the measurement only when it is confident
        AND disagrees with the model by more than ORIENTATION_OVERRIDE_DEG.
        Returns None otherwise (caller stamps the mounting model).
        """
        group = [r for r in records
                 if r.cam_idx == cam_idx and r.lat is not None and r.lon is not None]
        group.sort(key=lambda r: r.name)
        if not group:
            return None

        motion = self._pair_motion_bearing(group)
        if motion is None:
            return None
        mean_deg, spread_deg, count = motion
        stderr_deg = spread_deg / math.sqrt(count)
        if count < ORIENTATION_MIN_PAIRS or stderr_deg > ORIENTATION_MAX_STDERR_DEG:
            self.logger.info(
                f"WALDO cam {cam_idx}: orientation measurement inconclusive "
                f"({count} pairs, stderr {stderr_deg:.1f} deg); using the mounting model"
            )
            return None

        headings = [r.heading_deg for r in group if r.heading_deg is not None]
        if not headings:
            return None
        mean_heading, _ = self._circular_stats(headings, [1.0] * len(headings))
        model_deg = (mean_heading + 180.0) % 360.0
        gap = abs((mean_deg - model_deg + 180.0) % 360.0 - 180.0)
        if gap <= ORIENTATION_OVERRIDE_DEG:
            self.logger.info(
                f"WALDO cam {cam_idx}: measured orientation {mean_deg:.1f} deg agrees "
                f"with the mounting model {model_deg:.1f} deg (gap {gap:.1f} deg); "
                f"stamping the model"
            )
            return None
        self.logger.warning(
            f"WALDO cam {cam_idx}: measured orientation {mean_deg:.1f} deg "
            f"({count} pairs, stderr {stderr_deg:.1f} deg) contradicts the mounting "
            f"model {model_deg:.1f} deg (gap {gap:.1f} deg); stamping the measurement"
        )
        return mean_deg

    def compute_relative_altitude_m(
        self, lat: float, lon: float, gps_alt_ellipsoidal_m: float
    ) -> Tuple[float, float]:
        """Return (agl_m, absolute_orthometric_m) using terrain + geoid.

        Raises WaldoCoverageError when the DEM has no coverage at lat/lon.
        """
        if self.terrain_service is None:
            raise WaldoCoverageError("No terrain service configured for WALDO pre-pass.")

        geoid_undulation = self.terrain_service.get_geoid_undulation(lat, lon) or 0.0
        absolute_orthometric = gps_alt_ellipsoidal_m - geoid_undulation

        elev_result = self.terrain_service.get_elevation(lat, lon)
        if elev_result.source != 'terrain' or elev_result.elevation_m is None:
            raise WaldoCoverageError(
                f"DEM has no coverage at ({lat:.6f}, {lon:.6f})"
            )
        agl = absolute_orthometric - elev_result.elevation_m
        agl = max(1.0, agl)
        return agl, absolute_orthometric

    # ------------------------------------------------------------------
    # EXIF reading
    # ------------------------------------------------------------------

    @staticmethod
    def _read_record(path: str, cam_idx: int) -> WaldoImageRecord:
        """Read EXIF/GPS/timestamp into a WaldoImageRecord (errors land in record.error)."""
        rec = WaldoImageRecord(path=path, name=os.path.basename(path), cam_idx=cam_idx)
        try:
            exif = MetaDataHelper.get_exif_data_piexif(path)
        except Exception as e:
            rec.error = f"EXIF read failed: {e}"
            return rec

        gps = LocationInfo.get_gps(exif_data=exif)
        if not gps:
            rec.error = "Missing GPS in EXIF"
            return rec
        rec.lat = gps['latitude']
        rec.lon = gps['longitude']

        gps_ifd = exif.get('GPS') or {}
        alt = gps_ifd.get(piexif.GPSIFD.GPSAltitude)
        if alt is not None:
            try:
                if isinstance(alt, tuple):
                    rec.gps_alt_ellipsoidal = alt[0] / alt[1]
                else:
                    rec.gps_alt_ellipsoidal = float(alt)
                if gps_ifd.get(piexif.GPSIFD.GPSAltitudeRef, 0) == 1:
                    rec.gps_alt_ellipsoidal = -rec.gps_alt_ellipsoidal
            except (TypeError, ValueError, ZeroDivisionError):
                rec.gps_alt_ellipsoidal = None

        rec.timestamp = WaldoMetadataService._parse_exif_timestamp(exif)
        return rec

    @staticmethod
    def _parse_exif_timestamp(exif: dict) -> Optional[datetime]:
        """Parse DateTimeOriginal + SubSecTimeOriginal + OffsetTimeOriginal into UTC."""
        exif_ifd = exif.get('Exif') or {}
        dt_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        if dt_raw is None:
            return None
        try:
            dt_str = dt_raw.decode('utf-8') if isinstance(dt_raw, bytes) else str(dt_raw)
            dt = datetime.strptime(dt_str.strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:
            return None

        sub_raw = exif_ifd.get(piexif.ExifIFD.SubSecTimeOriginal)
        if sub_raw is not None:
            try:
                sub_str = sub_raw.decode('utf-8') if isinstance(sub_raw, bytes) else str(sub_raw)
                sub_str = sub_str.strip()
                if sub_str:
                    micros = int(round(float("0." + sub_str) * 1_000_000))
                    dt = dt.replace(microsecond=micros)
            except Exception:
                pass

        offset_raw = exif_ifd.get(piexif.ExifIFD.OffsetTimeOriginal)
        if offset_raw is not None:
            try:
                offset_str = offset_raw.decode('utf-8') if isinstance(offset_raw, bytes) else str(offset_raw)
                offset_str = offset_str.strip()
                m = re.match(r'^([+-])(\d{2}):(\d{2})$', offset_str)
                if m:
                    sign = 1 if m.group(1) == '+' else -1
                    hh = int(m.group(2))
                    mm = int(m.group(3))
                    tz = timezone(sign * timedelta(hours=hh, minutes=mm))
                    dt = dt.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

        return dt

    # ------------------------------------------------------------------
    # Heading derivation
    # ------------------------------------------------------------------

    def derive_headings(self, records: List[WaldoImageRecord]):
        """Populate `record.heading_deg` for every record that has GPS."""
        # Group by cam_idx, sort by timestamp (fall back to filename for missing).
        groups: Dict[int, List[WaldoImageRecord]] = {0: [], 1: []}
        for r in records:
            if r.lat is None or r.lon is None:
                continue
            groups.setdefault(r.cam_idx, []).append(r)

        for cam_idx, group in groups.items():
            if not group:
                continue
            group.sort(key=lambda r: (r.timestamp or datetime.min, r.name))
            self._derive_for_group(group)

        # Cross-cam fallback: if a record still has no heading, try the other
        # cam group's nearest-timestamp heading.
        all_with_heading = [r for r in records if r.heading_deg is not None]
        for r in records:
            if r.heading_deg is None and r.lat is not None and r.timestamp is not None:
                neighbour = self._nearest_other_cam(r, all_with_heading)
                if neighbour is not None:
                    r.heading_deg = neighbour.heading_deg

    @staticmethod
    def _nearest_other_cam(target: WaldoImageRecord,
                           candidates: List[WaldoImageRecord]) -> Optional[WaldoImageRecord]:
        best: Optional[WaldoImageRecord] = None
        best_dt = None
        for c in candidates:
            if c.cam_idx == target.cam_idx or c.timestamp is None:
                continue
            dt = abs((c.timestamp - target.timestamp).total_seconds())
            if best_dt is None or dt < best_dt:
                best_dt = dt
                best = c
        return best

    @staticmethod
    def _derive_for_group(group: List[WaldoImageRecord]):
        n = len(group)
        if n == 0:
            return

        def neighbour_search(idx: int, direction: int) -> Optional[int]:
            """Find next non-stationary, in-window neighbour from idx in given direction."""
            j = idx + direction
            anchor = group[idx]
            while 0 <= j < n:
                cand = group[j]
                if cand.timestamp and anchor.timestamp:
                    dt = abs((cand.timestamp - anchor.timestamp).total_seconds())
                    if dt > MAX_NEIGHBOR_DT_S:
                        return None
                dist = LocationInfo.haversine_m(anchor.lat, anchor.lon, cand.lat, cand.lon)
                if dist >= STATIONARY_THRESHOLD_M:
                    return j
                j += direction
            return None

        # Pass 1: bearing(prev → next) for interior images.
        for i in range(n):
            prev_idx = neighbour_search(i, -1)
            next_idx = neighbour_search(i, +1)
            if prev_idx is not None and next_idx is not None:
                group[i].heading_deg = LocationInfo.bearing(
                    group[prev_idx].lat, group[prev_idx].lon,
                    group[next_idx].lat, group[next_idx].lon
                )

        # Pass 2: forward fill (first images inherit from the next valid).
        last_seen: Optional[float] = None
        for r in group:
            if r.heading_deg is None and last_seen is not None:
                r.heading_deg = last_seen
            elif r.heading_deg is not None:
                last_seen = r.heading_deg

        # Pass 3: backward fill for any still-missing (e.g. very first image).
        last_seen = None
        for r in reversed(group):
            if r.heading_deg is None and last_seen is not None:
                r.heading_deg = last_seen
            elif r.heading_deg is not None:
                last_seen = r.heading_deg

        # Pass 4: if the entire group is stationary or has only 1 record,
        # fall back to bearing(first → last) when at least 2 distinct points exist.
        missing = [r for r in group if r.heading_deg is None]
        if missing and n >= 2:
            heading = LocationInfo.bearing(
                group[0].lat, group[0].lon, group[-1].lat, group[-1].lon
            )
            if not (math.isnan(heading)):
                for r in missing:
                    r.heading_deg = heading

    # ------------------------------------------------------------------
    # Public folder pipeline
    # ------------------------------------------------------------------

    def process_folder(
        self,
        image_paths: List[str],
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> WaldoProcessResult:
        """Run the full WALDO synthesis pass on the given image paths.

        Args:
            image_paths: Absolute paths of every image considered for the pass.
                Non-WALDO files are silently skipped.
            progress_cb: Optional callback (current, total, status_text) for UI
                updates. total == 0 signals an indeterminate phase (the dialog
                paints a busy spinner). total > 0 signals determinate per-image
                progress.
            cancel_cb: Optional cancellation predicate; returning True aborts cleanly.

        Returns:
            WaldoProcessResult with counts + per-image errors.
        """
        result = WaldoProcessResult()
        cancel_cb = cancel_cb or (lambda: False)

        def emit(current: int, total: int, status_text: str):
            if progress_cb is None:
                return
            try:
                progress_cb(current, total, status_text)
            except Exception:
                pass

        # 1. Filter + classify (EXIF reads happen here; tick the bar so a long
        #    folder of 500+ images doesn't sit at 0% during this pass).
        emit(0, 0, "Reading image metadata...")
        records: List[WaldoImageRecord] = []
        n_paths = len(image_paths)
        for i, path in enumerate(image_paths):
            if cancel_cb():
                result.cancelled = True
                return result
            if i % 10 == 0 or i == n_paths - 1:
                emit(i + 1, n_paths, f"Reading metadata {i + 1}/{n_paths}")
            cam_idx = self.is_waldo_image(path)
            if cam_idx is None:
                result.skipped += 1
                continue
            if self.is_already_processed(path):
                result.already_current += 1
                continue
            rec = self._read_record(path, cam_idx)
            records.append(rec)

        if not records:
            return result

        # 2. Warm up terrain services so the multi-second EGM96 grid load
        #    happens behind a clear status message instead of stalling the
        #    first per-image iteration.
        if self.terrain_service is not None:
            emit(0, 0, "Loading geoid grid + DEM index...")
            try:
                self.terrain_service.warmup()
            except Exception as e:
                self.logger.warning(f"Terrain warmup failed: {e}")

        # 3. Derive headings across the full flight (no per-image progress;
        #    runs in milliseconds even for thousands of records).
        emit(0, 0, "Deriving plane heading from GPS track...")
        self.derive_headings(records)

        # 3b. Measure the stored image orientation per camera by comparing
        #     inter-frame content motion against the GPS track. Post-flight
        #     software may normalize frames (field data showed north-up
        #     imagery ~41 deg away from the mounting model), so measurement
        #     always wins; the model is only the fallback.
        image_up_by_cam: Dict[int, Optional[float]] = {}
        for cam_idx in sorted({r.cam_idx for r in records}):
            if cancel_cb():
                result.cancelled = True
                return result
            emit(0, 0, f"Measuring image orientation (cam {cam_idx})...")
            image_up_by_cam[cam_idx] = self.measure_image_up_bearing(records, cam_idx)

        # 4. Per-image XMP synthesis
        total = len(records)
        for i, rec in enumerate(records):
            if cancel_cb():
                result.cancelled = True
                break

            emit(i + 1, total, f"Writing XMP {i + 1}/{total}: {rec.name}")

            if rec.error:
                result.errors.append((rec.name, rec.error))
                continue
            if rec.lat is None or rec.lon is None or rec.gps_alt_ellipsoidal is None:
                result.errors.append((rec.name, "Missing GPS lat/lon/altitude"))
                continue
            if rec.heading_deg is None:
                result.errors.append((rec.name, "Heading unavailable (single image / all stationary)"))
                continue

            try:
                agl_m, abs_orthometric = self.compute_relative_altitude_m(
                    rec.lat, rec.lon, rec.gps_alt_ellipsoidal
                )
            except WaldoCoverageError as e:
                result.errors.append((rec.name, str(e)))
                continue
            except Exception as e:
                result.errors.append((rec.name, f"AGL computation failed: {e}"))
                continue

            angles = self.compute_optical_axis_angles(
                rec.heading_deg, rec.cam_idx,
                image_up_deg=image_up_by_cam.get(rec.cam_idx)
            )

            try:
                self._write_synthesised_xmp(
                    rec.path, angles, rec.heading_deg, agl_m, abs_orthometric
                )
            except Exception as e:
                result.errors.append((rec.name, f"XMP write failed: {e}"))
                continue

            result.processed += 1

        return result

    @staticmethod
    def _write_synthesised_xmp(image_path: str, angles: Dict[str, float],
                               plane_heading_deg: float,
                               agl_m: float, abs_orthometric_m: float):
        """Write the synthesised drone-dji + waldo:Processed fields in one batch.

        FlightYawDegree carries the plane's true heading (drone-body direction).
        GimbalYawDegree carries the per-camera body orientation, which differs
        from FlightYaw by 180° for cam 1 because that pod is mounted with its
        body top facing the tail.
        """
        flight_yaw = float(plane_heading_deg) % 360.0
        fields = [
            (DRONE_DJI_NS, "GimbalPitchDegree", f"{angles['pitch']:+.4f}"),
            (DRONE_DJI_NS, "GimbalYawDegree", f"{angles['yaw']:+.4f}"),
            (DRONE_DJI_NS, "GimbalRollDegree", f"{angles['roll']:+.4f}"),
            (DRONE_DJI_NS, "FlightYawDegree", f"{flight_yaw:+.4f}"),
            (DRONE_DJI_NS, "RelativeAltitude", f"{agl_m:+.4f}"),
            (DRONE_DJI_NS, "AbsoluteAltitude", f"{abs_orthometric_m:+.4f}"),
            (WALDO_NAMESPACE_URI, "Processed", "true"),
            (WALDO_NAMESPACE_URI, "ProcessorVersion", WALDO_PROCESSOR_VERSION),
        ]
        MetaDataHelper.add_xmp_fields(image_path, fields)
