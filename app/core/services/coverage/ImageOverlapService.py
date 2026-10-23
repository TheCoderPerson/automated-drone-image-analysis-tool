"""
ImageOverlapService - find images whose ground another image already saw.

A drone that hovers, or a pilot who shoots the same spot twice, produces
images of the same ground. When both produce AOIs, the reviewer works the
same patch twice. An image is *redundant* when ONE other image saw at least a
threshold share of its ground, under three further conditions:

* **comparable resolution** - a ground cell only counts as seen when the other
  image's GSD there is no more than ``gsd_tolerance`` times coarser. A zoomed
  shot inside a wide shot is the sharper look, not a copy of it.
* **similar look direction** - the optical axes are within
  ``max_look_angle_deg``. Two obliques of a hillside from opposite sides see
  different faces of every tree and rock.
* **close in time** - captured within ``max_time_apart_s``. The same ground
  an hour later is a new search; the subject may have moved.
* **same sensor** - same sensor size and pixel dimensions. A dual-sensor
  payload (M30T, M3T, H20T...) shoots thermal and RGB of the same ground at
  the same instant; the RGB frame is finer, but it cannot show what the
  thermal frame shows.

The comparison is pairwise, never against the union of several images: a
normal mapping grid at 70-80% overlap covers each frame with its neighbours
combined, and thinning it would discard the second viewing angle.

Footprints come from ``CoveragePodService.project_frame``, the POD projection
path: full camera pose (position, yaw, gimbal pitch and roll), field of view
from the focal length (so optical zoom is honoured), terrain-anchored camera
elevation, and DEM line-of-sight occlusion. A frame with no DEM falls back to
flat ground rather than dropping out of the filter.

The expensive part, ``compute_footprints``, runs once; ``find_redundant`` is
cheap and is re-run whenever the threshold or the hidden/flagged state changes.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Collection, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.services.LoggerService import LoggerService
from core.services.coverage.CoveragePodService import CoveragePodService
from core.services.coverage.contracts import (
    LIMIT_TERRAIN,
    SKIP_EMPTY_FOOTPRINT,
    SKIP_ERROR,
    SKIP_NO_DEM,
    SKIP_NO_DEM_AT_NADIR,
    SKIP_NO_POSE,
    SKIP_PITCH_TOO_SHALLOW,
)
from core.services.coverage.kernel import build_camera_rotation, frame_pod_kernel
from core.services.coverage.params import PodParams
from core.services.terrain.grid import GridSample, mercator_units_per_meter

# Median GSDs closer than this ratio are treated as equal when choosing which
# image of a redundant group to keep.
GSD_TIE_RATIO = 1.05


@dataclass(frozen=True)
class OverlapParams:
    grid_res_m: float = 2.0             # footprint cell size, true ground meters
    gsd_tolerance: float = 1.25         # a covering image may be this much coarser per cell
    max_look_angle_deg: float = 20.0    # optical axes further apart see different faces
    max_time_apart_s: float = 300.0     # later than this the subject may have moved; 0 disables


@dataclass
class Footprint:
    """The ground one image saw, cropped to its visible cells on the shared lattice.

    ``row0``/``col0`` are global lattice indices of ``visible[0, 0]``. Rows
    count downward, so two footprints built on the same lattice compare by
    integer offset alone.
    """

    row0: int
    col0: int
    visible: np.ndarray                  # bool (H, W): inside the frustum and not terrain-blocked
    gsd_cm: np.ndarray                   # float32 (H, W): per-cell GSD, NaN where not visible
    look: np.ndarray                     # unit optical axis in NED
    capture_time: Optional[datetime]
    sensor: Tuple[float, float, int, int]  # (sensor w mm, sensor h mm, image w px, image h px)
    median_gsd_cm: float
    cell_count: int                      # number of visible cells (> 0)

    @property
    def row1(self) -> int:
        return self.row0 + self.visible.shape[0]

    @property
    def col1(self) -> int:
        return self.col0 + self.visible.shape[1]


@dataclass
class FootprintSet:
    """``compute_footprints`` output; ``footprints`` is aligned with the input images."""

    footprints: List[Optional[Footprint]]
    skipped: List[Tuple[str, str]]       # (image name, SKIP_* reason)
    flat_fallback: int = 0               # images projected onto flat ground for want of a DEM
    cancelled: bool = False


@dataclass
class RedundantMatch:
    covered_by: int                      # index of the kept image that saw this one's ground
    fraction: float                      # share of this image's ground it saw, 0..1


class _FlatTerrain:
    """Zero-elevation DEM for any grid: the fallback when no DEM covers a frame.

    With the ground at 0 the camera sits at the reported AGL, which is the
    flat-ground model every ADIAT footprint used before terrain support.
    """

    def sample_grid_spec(self, spec):
        data = np.zeros((spec.height, spec.width), dtype=np.float32)
        return GridSample(data=data, transform=spec.transform, crs=spec.crs,
                          datum_note="flat fallback")


def _default_anchor(image) -> Optional[float]:
    """Takeoff elevation of the flight this image belongs to, or None.

    Uses the per-flight-segment registry the viewer registers its images
    with, so one flight's launch site never anchors another's frames.
    """
    from core.services.image.AltitudeAnchorService import mission_anchor_elevation
    path = image.get('path') or None
    if path is None:
        return None
    return mission_anchor_elevation(offline_only=False, image_path=path)


def _default_capture_time(image) -> Optional[datetime]:
    from helpers.MetaDataHelper import MetaDataHelper
    path = image.get('path', '')
    if not path:
        return None
    return MetaDataHelper.get_exif_timestamp(MetaDataHelper.get_exif_data_piexif(path))


class ImageOverlapService:
    """Compute image footprints and decide which images are redundant."""

    def __init__(self, terrain, custom_altitude_ft: Optional[float] = None,
                 params: Optional[OverlapParams] = None,
                 logger: Optional[LoggerService] = None,
                 frame_geometry_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 anchor_fn: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
                 capture_time_fn: Optional[Callable[[Dict[str, Any]], Optional[datetime]]] = None):
        """
        Args:
            terrain: a TerrainService (or test double) with ``sample_grid_spec``.
                Use a fresh one per worker thread, as POD does.
            custom_altitude_ft: the viewer's AGL override, if any.
            params: overlap rules; defaults to ``OverlapParams()``.
            logger: optional logger.
            frame_geometry_fn: ``image -> FrameGeometry`` for tests; None reads
                metadata the way POD does.
            anchor_fn: ``image -> takeoff elevation`` for tests; None uses the
                per-flight anchor registry.
            capture_time_fn: ``image -> datetime`` for tests; None reads EXIF.
        """
        self.params = params or OverlapParams()
        self.logger = logger or LoggerService()
        pod_params = PodParams(grid_res_m=self.params.grid_res_m)
        self.projector = CoveragePodService(
            terrain, None, pod_params, custom_altitude_ft=custom_altitude_ft, logger=self.logger)
        self.flat_projector = CoveragePodService(
            _FlatTerrain(), None, pod_params, custom_altitude_ft=custom_altitude_ft, logger=self.logger)
        self._frame_geometry = frame_geometry_fn or self.projector.frame_geometry
        self._anchor = anchor_fn or _default_anchor
        self._capture_time = capture_time_fn or _default_capture_time

    def compute_footprints(self, images: Sequence[Dict[str, Any]], progress_callback=None,
                           cancel_check=None) -> FootprintSet:
        """Project every image onto the ground.

        Args:
            images: image records carrying at least ``path``.
            progress_callback: ``(current, total, message)``.
            cancel_check: ``() -> bool``; True stops early with ``cancelled``.

        Returns:
            FootprintSet: one entry per image, None where it could not be placed.
        """
        footprints: List[Optional[Footprint]] = []
        skipped: List[Tuple[str, str]] = []
        flat_fallback = 0
        cell_size_3857 = None
        meters_per_unit = 1.0
        total = len(images)

        for idx, image in enumerate(images):
            if cancel_check and cancel_check():
                return FootprintSet(footprints, skipped, flat_fallback, cancelled=True)
            name = image.get('name') or image.get('path') or str(idx)
            if progress_callback:
                progress_callback(idx, total, f"Projecting {name}...")

            try:
                fg = self._frame_geometry(image)
                if fg is None:
                    footprints.append(None)
                    skipped.append((name, SKIP_NO_POSE))
                    continue
                if fg.pitch_deg > self.projector.params.min_pitch_deg:
                    footprints.append(None)
                    skipped.append((name, SKIP_PITCH_TOO_SHALLOW))
                    continue

                # One lattice for the whole set, sized at the first frame's
                # latitude exactly as POD sizes its mission grid.
                if cell_size_3857 is None:
                    meters_per_unit = math.cos(math.radians(fg.lat))
                    cell_size_3857 = self.params.grid_res_m * mercator_units_per_meter(fg.lat)

                look = build_camera_rotation(
                    fg.pitch_deg, fg.yaw_deg, fg.roll_deg, roll_axis_deg=fg.roll_axis_deg)[:, 2]
                sensor = (round(fg.sensor_mm[0], 2), round(fg.sensor_mm[1], 2),
                          int(fg.image_size[0]), int(fg.image_size[1]))
                frame = self.projector.project_frame(
                    image, fg, self._anchor(image), cell_size_3857, meters_per_unit)
                projector = self.projector
                if frame.skip_reason in (SKIP_NO_DEM, SKIP_NO_DEM_AT_NADIR):
                    # project_frame updated agl_m in place; start from fresh metadata.
                    fg = self._frame_geometry(image)
                    frame = self.flat_projector.project_frame(
                        image, fg, None, cell_size_3857, meters_per_unit)
                    projector = self.flat_projector
                    if frame.skip_reason is None:
                        flat_fallback += 1
                if frame.skip_reason is not None:
                    footprints.append(None)
                    skipped.append((name, frame.skip_reason))
                    continue

                footprint = self._footprint(frame, projector.params, meters_per_unit,
                                            cell_size_3857, look, self._capture_time(image), sensor)
                footprints.append(footprint)
                if footprint is None:
                    # Every cell in the frustum was hidden behind terrain.
                    skipped.append((name, SKIP_EMPTY_FOOTPRINT))
            except Exception as e:  # noqa: BLE001 - one bad frame must not stop the set
                self.logger.error(f"Redundant-image footprint for '{name}' failed: {e}")
                footprints.append(None)
                skipped.append((name, SKIP_ERROR))

        if progress_callback:
            progress_callback(total, total, "Comparing footprints...")
        return FootprintSet(footprints, skipped, flat_fallback)

    @staticmethod
    def _footprint(frame, pod_params, meters_per_unit, cell_size_3857, look,
                   capture_time, sensor) -> Optional[Footprint]:
        """Crop a projected frame to the cells it could actually see."""
        _, factor = frame_pod_kernel(
            frame.dem, None, None, frame.spec.transform, frame.cam_xyz, frame.mask,
            frame.gsd, pod_params, meters_per_unit=meters_per_unit, return_factors=True)
        visible = frame.mask & (factor != LIMIT_TERRAIN)
        rows = np.flatnonzero(visible.any(axis=1))
        cols = np.flatnonzero(visible.any(axis=0))
        if rows.size == 0:
            return None
        r0, r1 = int(rows[0]), int(rows[-1]) + 1
        c0, c1 = int(cols[0]), int(cols[-1]) + 1
        visible = visible[r0:r1, c0:c1]
        gsd = np.where(visible, frame.gsd[r0:r1, c0:c1], np.nan).astype(np.float32)

        # Lattice edges sit on integer multiples of the cell size, so the
        # frame's origin converts to an exact global index.
        transform = frame.spec.transform
        col_origin = int(round(transform.c / cell_size_3857))
        row_origin = int(round(-transform.f / cell_size_3857))
        return Footprint(
            row0=row_origin + r0,
            col0=col_origin + c0,
            visible=visible,
            gsd_cm=gsd,
            look=np.asarray(look, dtype=np.float64),
            capture_time=capture_time,
            sensor=sensor,
            median_gsd_cm=float(np.nanmedian(gsd)),
            cell_count=int(visible.sum()),
        )


def coverage_fraction(target: Footprint, other: Footprint, gsd_tolerance: float) -> float:
    """Share of ``target``'s visible ground that ``other`` saw at comparable GSD.

    Not symmetric: a small zoomed footprint inside a wide one is fully covered
    by area, but the wide image's coarser GSD fails the tolerance test.
    """
    r0 = max(target.row0, other.row0)
    r1 = min(target.row1, other.row1)
    c0 = max(target.col0, other.col0)
    c1 = min(target.col1, other.col1)
    if r0 >= r1 or c0 >= c1:
        return 0.0
    t_rows = slice(r0 - target.row0, r1 - target.row0)
    t_cols = slice(c0 - target.col0, c1 - target.col0)
    o_rows = slice(r0 - other.row0, r1 - other.row0)
    o_cols = slice(c0 - other.col0, c1 - other.col0)
    both = target.visible[t_rows, t_cols] & other.visible[o_rows, o_cols]
    with np.errstate(invalid='ignore'):
        comparable = other.gsd_cm[o_rows, o_cols] <= target.gsd_cm[t_rows, t_cols] * gsd_tolerance
    covered = int(np.count_nonzero(both & comparable))
    return covered / target.cell_count


def _gsd_rank(gsd_cm: float) -> int:
    """Bucket a GSD on a log scale so GSDs within GSD_TIE_RATIO sort as equal."""
    if not gsd_cm or not math.isfinite(gsd_cm) or gsd_cm <= 0:
        return 0
    return int(round(math.log(gsd_cm) / math.log(GSD_TIE_RATIO)))


def _comparable(target: Footprint, other: Footprint, params: OverlapParams) -> bool:
    """Whether ``other`` may stand in for ``target`` at all (sensor, direction, time)."""
    if (target.row0 >= other.row1 or other.row0 >= target.row1
            or target.col0 >= other.col1 or other.col0 >= target.col1):
        return False
    if target.sensor != other.sensor:
        return False
    cos_angle = float(np.clip(np.dot(target.look, other.look), -1.0, 1.0))
    if math.degrees(math.acos(cos_angle)) > params.max_look_angle_deg:
        return False
    if params.max_time_apart_s > 0:
        # Without both times there is no way to know the subject stayed put,
        # so the pair is not compared.
        if target.capture_time is None or other.capture_time is None:
            return False
        apart = abs((target.capture_time - other.capture_time).total_seconds())
        if apart > params.max_time_apart_s:
            return False
    return True


def find_redundant(footprints: Sequence[Optional[Footprint]], threshold: float,
                   eligible: Optional[Collection[int]] = None,
                   protected: Collection[int] = (),
                   params: Optional[OverlapParams] = None) -> Dict[int, RedundantMatch]:
    """Decide which images are redundant.

    Images are visited protected first, then finest median GSD first, then in
    list order; each one is kept unless an already-kept image covers at least
    ``threshold`` of it. Only kept images can cover, so a run of near-identical
    frames collapses onto the single best one rather than chaining. GSDs within
    ``GSD_TIE_RATIO`` of each other count as equal, so of a hover's identical
    frames the first in the list is kept rather than whichever won a
    sub-percent rounding race.

    Args:
        footprints: per-image footprints (None = never redundant, covers nothing).
        threshold: minimum ``coverage_fraction``, 0..1.
        eligible: indices taking part (e.g. not hidden); None means all.
            An ineligible image is neither hidden nor allowed to cover another.
        protected: indices that are always kept (e.g. images with flagged AOIs).
        params: overlap rules; defaults to ``OverlapParams()``.

    Returns:
        dict: redundant image index -> RedundantMatch.
    """
    params = params or OverlapParams()
    protected = set(protected)
    candidates = [i for i, fp in enumerate(footprints)
                  if fp is not None and (eligible is None or i in eligible)]
    candidates.sort(key=lambda i: (i not in protected, _gsd_rank(footprints[i].median_gsd_cm), i))

    kept: List[int] = []
    redundant: Dict[int, RedundantMatch] = {}
    for i in candidates:
        target = footprints[i]
        best = None
        if i not in protected:
            for k in kept:
                other = footprints[k]
                if not _comparable(target, other, params):
                    continue
                fraction = coverage_fraction(target, other, params.gsd_tolerance)
                if fraction >= threshold and (best is None or fraction > best.fraction):
                    best = RedundantMatch(covered_by=k, fraction=fraction)
        if best is None:
            kept.append(i)
        else:
            redundant[i] = best
    return redundant
