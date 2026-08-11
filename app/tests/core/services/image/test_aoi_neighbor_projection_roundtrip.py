"""The contract AOI-in-neighbouring-images rests on: the inverse is an inverse.

The feature computes an AOI's GPS with AOIService (forward: pixel -> ground),
then asks AOINeighborService where that GPS falls in each candidate image
(inverse: ground -> pixel). The two are only correct as a pair, and nothing
used to check that they were. They drifted: the forward path gained gimbal-roll
support and terrain-corrected AGL, the inverse got neither, and each omission
put the AOI hundreds or thousands of pixels from where it actually appears --
far outside the ~200 px thumbnail, so every crop showed unrelated ground with a
red circle confidently drawn on it. No error was raised and no test failed.

These tests close the loop numerically. A tolerance of 1 px is not
aspirational: the inversion is analytic, so anything above floating-point noise
means the two models disagree.
"""

import math

import pytest

from core.services.image.AOIService import AOIService
from core.services.image.AOINeighborService import AOINeighborService

# A DJI-class nadir rig: 5472x3648 at 8.8 mm on a 13.2x8.8 mm sensor.
WIDTH, HEIGHT = 5472, 3648
FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM = 8.8, 13.2, 8.8
DRONE_LAT, DRONE_LON = 32.0, -97.0

TOLERANCE_PX = 1.0


def _service():
    """An AOINeighborService without the LoggerService its __init__ builds."""
    return AOINeighborService.__new__(AOINeighborService)


def _coverage_info(yaw, pitch, altitude, roll=0.0, roll_axis=None):
    """The metadata dict get_image_coverage_info produces for this camera."""
    return {
        'center_lat': DRONE_LAT,
        'center_lon': DRONE_LON,
        'yaw': yaw,
        'pitch': pitch,
        'roll': roll,
        'roll_axis_azimuth': roll_axis,
        'altitude': altitude,
        'width': WIDTH,
        'height': HEIGHT,
        'focal_mm': FOCAL_MM,
        'sensor_w_mm': SENSOR_W_MM,
        'sensor_h_mm': SENSOR_H_MM,
        'fov_alignment': None,
    }


def _round_trip_error_px(pixel, yaw, pitch, altitude, roll=0.0, roll_axis=None):
    """Project *pixel* to ground and back; return the pixel distance."""
    u, v = pixel
    ground = AOIService._calculate_ground_position(
        DRONE_LAT, DRONE_LON, u, v, WIDTH / 2.0, HEIGHT / 2.0, WIDTH, HEIGHT,
        FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM, altitude, pitch, yaw, roll,
        roll_axis_azimuth_deg=roll_axis,
    )
    assert ground is not None, "forward projection found no ground intersection"

    back = _service().gps_to_pixel(
        ground[0], ground[1], _coverage_info(yaw, pitch, altitude, roll, roll_axis)
    )
    assert back is not None, "inverse projection rejected its own forward result"
    return math.hypot(back[0] - u, back[1] - v)


@pytest.mark.parametrize("pixel", [
    (WIDTH / 2, HEIGHT / 2),   # centre
    (4322, 471),               # the AOI from the sample dataset
    (10, 10),                  # corners, where any model error is largest
    (WIDTH - 10, HEIGHT - 10),
])
@pytest.mark.parametrize("yaw", [0.0, 45.0, 180.0, 271.5, 359.9])
def test_nadir_round_trip_is_exact(pixel, yaw):
    assert _round_trip_error_px(pixel, yaw, -90.0, 100.0) < TOLERANCE_PX


@pytest.mark.parametrize("pitch", [-80.0, -60.0, -45.0, -30.0])
def test_oblique_round_trip_is_exact(pitch):
    """Oblique imagery is where a wrong camera frame shows up first."""
    assert _round_trip_error_px((4322, 471), 45.0, pitch, 120.0) < TOLERANCE_PX


@pytest.mark.parametrize("roll", [22.5, -22.5, 40.0])
def test_gimbal_roll_round_trip_is_exact(roll):
    """Regression: the inverse never read roll, so a WALDO pod tilt was dropped.

    The forward path applied a Rodrigues roll and the inverse did not, which
    left the AOI ~1500 px away at +-22.5 degrees -- seven thumbnails' worth --
    with nothing reporting a problem.
    """
    assert _round_trip_error_px((4322, 471), 45.0, -90.0, 100.0, roll=roll) < TOLERANCE_PX


def test_roll_about_the_flight_axis_round_trips():
    """WALDO processor >= 6 stamps roll about the flight axis, not the gimbal's."""
    error = _round_trip_error_px(
        (4322, 471), 45.0, -60.0, 120.0, roll=-22.5, roll_axis=310.0
    )
    assert error < TOLERANCE_PX


def test_roll_actually_changes_the_projection():
    """Guard the guard: the roll tests would pass trivially if roll were ignored.

    If a future change drops roll from BOTH paths the round trip still closes,
    so this pins that roll is genuinely part of the model.
    """
    service = _service()
    ground = AOIService._calculate_ground_position(
        DRONE_LAT, DRONE_LON, 4322, 471, WIDTH / 2.0, HEIGHT / 2.0, WIDTH, HEIGHT,
        FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM, 100.0, -90.0, 45.0, 22.5,
    )
    without_roll = service.gps_to_pixel(
        ground[0], ground[1], _coverage_info(45.0, -90.0, 100.0, roll=0.0)
    )
    assert without_roll is not None
    assert math.hypot(without_roll[0] - 4322, without_roll[1] - 471) > 100.0


def test_inverse_rejects_a_point_behind_the_camera():
    """A GPS far behind an oblique camera has no valid forward ray."""
    service = _service()
    # 2 km due south of a camera looking north at 30 degrees below horizontal.
    behind_lat = DRONE_LAT - 2000.0 / 111320.0
    result = service.gps_to_pixel(
        behind_lat, DRONE_LON, _coverage_info(0.0, -30.0, 120.0)
    )
    if result is not None:
        # Not rejected outright, but it must not land inside the frame.
        u, v = result
        assert not (0 <= u < WIDTH and 0 <= v < HEIGHT)


# ------------------------- terrain-consistent altitude ---------------------- #


class _Elevation:
    def __init__(self, elevation_m, source='terrain'):
        self.elevation_m = elevation_m
        self.source = source


class _TerrainService:
    def __init__(self, elevation, enabled=True):
        self._elevation = elevation
        self.enabled = enabled

    def get_elevation(self, lat, lon):
        return self._elevation


def _patch_terrain(monkeypatch, service):
    import core.services.image.AOINeighborService as module
    monkeypatch.setattr(module, '_get_terrain_service', lambda: service)


def test_altitude_is_measured_to_the_aoi_ground_not_the_cameras(monkeypatch):
    """Regression: the inverse used raw EXIF AGL while the forward used terrain.

    30 m of relief at 100 m AGL moved the AOI ~625 px, which is why the
    originating image did not even project the AOI back onto its own pixel.
    """
    _patch_terrain(monkeypatch, _TerrainService(_Elevation(280.0)))
    coverage = _coverage_info(0.0, -90.0, 100.0)

    adjusted = _service()._terrain_adjusted_altitude(coverage, aoi_terrain_elevation_m=250.0)

    assert adjusted == pytest.approx(130.0)


def test_altitude_is_unchanged_without_an_aoi_elevation(monkeypatch):
    """A flat/no-DEM forward result must leave flat-earth behaviour alone."""
    _patch_terrain(monkeypatch, _TerrainService(_Elevation(280.0)))
    coverage = _coverage_info(0.0, -90.0, 100.0)

    assert _service()._terrain_adjusted_altitude(coverage, None) == 100.0


@pytest.mark.parametrize("terrain", [
    None,
    _TerrainService(_Elevation(None, source='none')),
    _TerrainService(_Elevation(280.0), enabled=False),
])
def test_altitude_degrades_to_unadjusted_when_the_dem_cannot_answer(monkeypatch, terrain):
    """A terrain gap must degrade to today's behaviour, not drop the image."""
    _patch_terrain(monkeypatch, terrain)
    coverage = _coverage_info(0.0, -90.0, 100.0)

    assert _service()._terrain_adjusted_altitude(coverage, 250.0) == 100.0


def test_altitude_is_floored_above_zero(monkeypatch):
    """An AOI on ground above the camera must not produce a non-positive AGL.

    A non-positive AGL has no ground intersection, which would silently drop
    the image from the results rather than place the AOI imprecisely.
    """
    _patch_terrain(monkeypatch, _TerrainService(_Elevation(10.0)))
    coverage = _coverage_info(0.0, -90.0, 100.0)

    assert _service()._terrain_adjusted_altitude(coverage, 250.0) == 1.0
