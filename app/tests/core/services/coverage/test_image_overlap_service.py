"""Tests for ImageOverlapService: footprint projection and the redundancy rules."""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

pytest.importorskip("scipy")

from core.services.coverage.ImageOverlapService import (
    Footprint,
    ImageOverlapService,
    OverlapParams,
    coverage_fraction,
    find_redundant,
)
from core.services.coverage.contracts import SKIP_NO_POSE, SKIP_PITCH_TOO_SHALLOW
from core.services.image.FrameGeometry import FrameGeometry
from core.services.terrain.grid import GridSample, lonlat_to_mercator

LAT = 38.7
LON = -120.5
M_PER_DEG_LAT = 111320.0
T0 = datetime(2026, 6, 10, 12, 0, 0)

NADIR = np.array([0.0, 0.0, 1.0])


def _fg(east_m=0.0, north_m=0.0, pitch=-90.0, yaw=0.0, agl=120.0, focal=8.8,
        sensor_mm=(13.2, 8.8), image_size=(4000, 3000)):
    """A DJI-like frame (13.2 x 8.8 mm sensor, 4000 x 3000 px) offset from LAT/LON.

    At 120 m and 8.8 mm the footprint is 180 m east-west by 120 m north-south.
    """
    lat = LAT + north_m / M_PER_DEG_LAT
    lon = LON + east_m / (M_PER_DEG_LAT * math.cos(math.radians(LAT)))
    return FrameGeometry(
        lat=lat, lon=lon, agl_m=agl, yaw_deg=yaw, pitch_deg=pitch, roll_deg=0.0,
        focal_mm=focal, sensor_mm=sensor_mm, image_size=image_size,
        principal_point_mm=None, yaw_source='gimbal', bearing_confidence=1.0,
    )


class _FlatTerrain:
    def sample_grid_spec(self, spec):
        data = np.zeros((spec.height, spec.width), dtype=np.float32)
        return GridSample(data=data, transform=spec.transform, crs=spec.crs, datum_note="flat")


class _NoTerrain:
    def sample_grid_spec(self, spec):
        return None


def _service(terrain=None, params=None):
    """Images are dicts carrying '_fg' (FrameGeometry factory) and '_time'."""
    return ImageOverlapService(
        terrain if terrain is not None else _FlatTerrain(),
        params=params,
        frame_geometry_fn=lambda image: image['_fg']() if image.get('_fg') else None,
        anchor_fn=lambda image: None,
        capture_time_fn=lambda image: image.get('_time', T0),
    )


def _image(name, **fg_kwargs):
    return {'name': name, 'path': name, '_fg': lambda: _fg(**fg_kwargs)}


def _footprints(images, terrain=None, params=None):
    result = _service(terrain, params).compute_footprints(images)
    return result


# ---- projection ---------------------------------------------------------------

def test_identical_frames_cover_each_other_completely():
    result = _footprints([_image('a'), _image('b')])
    a, b = result.footprints
    assert coverage_fraction(b, a, 1.25) == pytest.approx(1.0)
    assert find_redundant(result.footprints, 0.9).keys() == {1}


def test_footprint_sits_on_the_global_lattice_north_up():
    """row0/col0 must place the footprint at its true position, or two frames
    would be compared against the wrong part of each other."""
    service = _service()
    footprint = service.compute_footprints([_image('a')]).footprints[0]
    cell = service.params.grid_res_m / math.cos(math.radians(LAT))  # 3857 units
    cam_x, cam_y = lonlat_to_mercator(LON, LAT)
    top_y = cam_y + 60.0 / math.cos(math.radians(LAT))
    left_x = cam_x - 90.0 / math.cos(math.radians(LAT))
    assert -footprint.row0 * cell == pytest.approx(top_y, abs=1.5 * cell)
    assert footprint.col0 * cell == pytest.approx(left_x, abs=1.5 * cell)
    assert footprint.visible.shape == pytest.approx((60, 90), abs=2)


@pytest.mark.parametrize("east_m, north_m", [(45.0, 0.0), (0.0, 30.0), (0.0, -30.0)])
def test_quarter_shift_covers_three_quarters(east_m, north_m):
    result = _footprints([_image('a'), _image('b', east_m=east_m, north_m=north_m)])
    a, b = result.footprints
    assert coverage_fraction(b, a, 1.25) == pytest.approx(0.75, abs=0.04)
    assert find_redundant(result.footprints, 0.9) == {}
    assert find_redundant(result.footprints, 0.7).keys() == {1}


def test_shifted_frames_do_not_overlap_at_all():
    result = _footprints([_image('a'), _image('b', east_m=400.0)])
    a, b = result.footprints
    assert coverage_fraction(b, a, 1.25) == 0.0


def test_zoomed_frame_inside_wide_frame_is_not_redundant():
    """The zoomed shot is entirely inside the wide one by area, but the wide
    image saw that ground at a quarter of the resolution."""
    result = _footprints([_image('wide'), _image('zoom', focal=35.2)])
    wide, zoom = result.footprints
    assert zoom.median_gsd_cm < wide.median_gsd_cm
    assert coverage_fraction(zoom, wide, 1.25) == 0.0
    assert coverage_fraction(wide, zoom, 1.25) < 0.1
    assert find_redundant(result.footprints, 0.5) == {}


def test_thermal_frame_inside_the_rgb_frame_is_not_redundant():
    """Seen on a real H20T set: the thermal frame lies wholly inside the
    simultaneous wide RGB frame, at coarser GSD. It must stay visible."""
    thermal = dict(focal=13.5, sensor_mm=(7.68, 6.14), image_size=(640, 512))
    result = _footprints([_image('wide'), _image('thermal', **thermal)])
    wide, thermal_fp = result.footprints
    assert wide.sensor != thermal_fp.sensor
    assert find_redundant(result.footprints, 0.5) == {}


def test_finer_frame_is_kept_and_the_coarser_one_hidden():
    """Same spot, 130 m vs 120 m: the lower (finer) frame is visited first even
    though it comes second, and covers ~85% of the higher one's ground at
    comparable GSD."""
    result = _footprints([_image('high', agl=130.0), _image('low', agl=120.0)])
    redundant = find_redundant(result.footprints, 0.8)
    assert redundant.keys() == {0}
    assert redundant[0].covered_by == 1


def test_near_equal_gsd_keeps_the_first_frame():
    """Frames 2% apart in GSD are a tie: the earlier one is kept."""
    result = _footprints([_image('first', agl=122.0), _image('second', agl=120.0)])
    redundant = find_redundant(result.footprints, 0.9)
    assert redundant.keys() == {1}
    assert redundant[1].covered_by == 0


class _ConstantTerrain:
    def __init__(self, elevation_m):
        self.elevation_m = elevation_m

    def sample_grid_spec(self, spec):
        data = np.full((spec.height, spec.width), self.elevation_m, dtype=np.float32)
        return GridSample(data=data, transform=spec.transform, crs=spec.crs, datum_note="const")


class _RidgeTerrain:
    """Flat ground with a 100 m wall running east-west, 100-110 m north of LAT."""

    def sample_grid_spec(self, spec):
        _, cam_y = lonlat_to_mercator(LON, LAT)
        units_per_m = 1.0 / math.cos(math.radians(LAT))
        _, ys = spec.cell_centers()
        north_m = (ys - cam_y) / units_per_m
        row_elev = np.where((north_m > 100.0) & (north_m < 110.0), 100.0, 0.0)
        data = np.repeat(row_elev[:, np.newaxis], spec.width, axis=1).astype(np.float32)
        return GridSample(data=data, transform=spec.transform, crs=spec.crs, datum_note="ridge")


def test_ground_above_takeoff_shrinks_the_footprint():
    """Takeoff at 0 m, ground at 60 m, 120 m above takeoff: the camera is only
    60 m above this ground, so it sees a quarter of the flat-ground area."""
    flat = _footprints([_image('a')]).footprints[0]
    service = ImageOverlapService(
        _ConstantTerrain(60.0),
        frame_geometry_fn=lambda image: image['_fg'](),
        anchor_fn=lambda image: 0.0,
        capture_time_fn=lambda image: T0)
    raised = service.compute_footprints([_image('a')]).footprints[0]
    assert raised.cell_count == pytest.approx(flat.cell_count / 4.0, rel=0.08)


def test_ground_behind_a_ridge_is_not_counted_as_seen():
    looking_north = dict(pitch=-30.0, yaw=0.0)
    flat = _footprints([_image('a', **looking_north)]).footprints[0]
    ridge = _footprints([_image('a', **looking_north)], terrain=_RidgeTerrain()).footprints[0]
    assert ridge.cell_count < 0.8 * flat.cell_count


def test_frame_with_no_pose_is_skipped():
    images = [{'name': 'x', 'path': 'x'}]
    result = _footprints(images)
    assert result.footprints == [None]
    assert result.skipped == [('x', SKIP_NO_POSE)]


def test_near_horizon_frame_is_skipped():
    result = _footprints([_image('h', pitch=-5.0)])
    assert result.footprints == [None]
    assert result.skipped == [('h', SKIP_PITCH_TOO_SHALLOW)]


def test_missing_dem_falls_back_to_flat_ground():
    result = _footprints([_image('a'), _image('b')], terrain=_NoTerrain())
    assert result.flat_fallback == 2
    assert all(fp is not None for fp in result.footprints)
    assert find_redundant(result.footprints, 0.9).keys() == {1}


def test_compute_footprints_honours_cancel():
    result = _service().compute_footprints([_image('a'), _image('b')], cancel_check=lambda: True)
    assert result.cancelled
    assert result.footprints == []


def test_oblique_footprint_records_its_look_direction():
    result = _footprints([_image('o', pitch=-45.0, yaw=90.0)])
    look = result.footprints[0].look
    # 45 deg below the horizon, pointing east (NED: north, east, down).
    assert look == pytest.approx([0.0, math.sqrt(0.5), math.sqrt(0.5)], abs=1e-6)


# ---- redundancy rules on synthetic footprints ----------------------------------

RGB_SENSOR = (13.2, 8.8, 4000, 3000)
THERMAL_SENSOR = (7.68, 6.14, 640, 512)


def _square(row0=0, col0=0, size=10, gsd=5.0, look=NADIR, time=T0, sensor=RGB_SENSOR):
    visible = np.ones((size, size), dtype=bool)
    return Footprint(
        row0=row0, col0=col0, visible=visible,
        gsd_cm=np.full((size, size), gsd, dtype=np.float32),
        look=np.asarray(look, dtype=float), capture_time=time, sensor=sensor,
        median_gsd_cm=gsd, cell_count=size * size)


def test_a_different_sensor_never_stands_in():
    """A dual-sensor payload's RGB frame is finer than its thermal frame of
    the same instant, but it cannot show what the thermal frame shows."""
    footprints = [_square(gsd=2.0), _square(gsd=10.0, sensor=THERMAL_SENSOR)]
    assert find_redundant(footprints, 0.5) == {}


def test_look_directions_far_apart_are_not_compared():
    east = [0.0, math.sqrt(0.5), math.sqrt(0.5)]
    west = [0.0, -math.sqrt(0.5), math.sqrt(0.5)]
    assert find_redundant([_square(look=east), _square(look=west)], 0.9) == {}


def test_look_directions_within_the_limit_are_compared():
    tilted = [0.0, math.sin(math.radians(10)), math.cos(math.radians(10))]
    assert find_redundant([_square(), _square(look=tilted)], 0.9).keys() == {1}


def test_frames_far_apart_in_time_are_not_compared():
    later = T0 + timedelta(seconds=301)
    assert find_redundant([_square(), _square(time=later)], 0.9) == {}
    sooner = T0 + timedelta(seconds=299)
    assert find_redundant([_square(), _square(time=sooner)], 0.9).keys() == {1}


def test_missing_capture_time_is_not_compared_unless_the_window_is_off():
    footprints = [_square(), _square(time=None)]
    assert find_redundant(footprints, 0.9) == {}
    no_window = OverlapParams(max_time_apart_s=0.0)
    assert find_redundant(footprints, 0.9, params=no_window).keys() == {1}


def test_protected_image_is_never_redundant_and_is_kept_first():
    footprints = [_square(gsd=5.0), _square(gsd=5.5)]
    # Unprotected: the finer first frame is kept, the second hidden.
    assert find_redundant(footprints, 0.9).keys() == {1}
    # Protecting the coarser frame keeps it, and it then covers the finer one
    # (5.0 <= 5.5 * 1.25 still holds the other way round).
    redundant = find_redundant(footprints, 0.9, protected={1})
    assert redundant.keys() == {0}
    assert redundant[0].covered_by == 1


def test_ineligible_image_neither_hides_nor_covers():
    footprints = [_square(), _square(), _square()]
    redundant = find_redundant(footprints, 0.9, eligible={1, 2})
    assert redundant.keys() == {2}
    assert redundant[2].covered_by == 1


def test_run_of_duplicates_collapses_onto_one_kept_frame():
    footprints = [_square(col0=0), _square(col0=1), _square(col0=2)]
    redundant = find_redundant(footprints, 0.8)
    assert redundant.keys() == {1, 2}
    assert {match.covered_by for match in redundant.values()} == {0}


def test_best_covering_frame_is_reported():
    footprints = [_square(col0=0, gsd=4.0), _square(col0=3, gsd=4.5), _square(col0=1, gsd=5.0)]
    # Frame 2 is 90% covered by frame 0 and 80% by frame 1 (which is itself
    # kept: only 70% covered by frame 0).
    redundant = find_redundant(footprints, 0.75)
    assert redundant.keys() == {2}
    assert redundant[2].covered_by == 0
    assert redundant[2].fraction == pytest.approx(0.9)


def test_threshold_is_inclusive():
    footprints = [_square(col0=0), _square(col0=1)]
    assert find_redundant(footprints, 0.9).keys() == {1}
    assert find_redundant(footprints, 0.91) == {}


def test_partial_visibility_counts_only_seen_cells():
    """Cells hidden behind terrain are not ground the image saw, so they are
    neither covered nor part of the denominator."""
    other = _square()
    target = _square()
    target.visible[:, 5:] = False
    target.gsd_cm[:, 5:] = np.nan
    target.cell_count = int(target.visible.sum())
    assert coverage_fraction(target, other, 1.25) == pytest.approx(1.0)
