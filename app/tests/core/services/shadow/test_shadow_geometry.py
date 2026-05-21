"""Unit tests for core.services.shadow.ShadowGeometry."""

import math

import pytest

from core.services.CameraModel import CameraModel
from core.services.shadow.ShadowGeometry import anti_solar_image_direction


def _nadir_camera():
    """A straight-down, north-aligned camera at 100 m AGL.

    In a nadir frame image-right (+u) is east and image-down (+v) is south.
    """
    return CameraModel(
        agl_m=100.0, pitch_deg=-90.0, yaw_deg=0.0,
        focal_mm=10.0, sensor_w_mm=13.2, sensor_h_mm=8.8,
        width=4000, height=3000,
    )


def test_anti_solar_points_south_when_sun_in_north():
    cam = _nadir_camera()
    du, dv = anti_solar_image_direction(cam, (2000.0, 1500.0), sun_azimuth_deg=0.0)
    assert du == pytest.approx(0.0, abs=1e-6)
    assert dv == pytest.approx(1.0, abs=1e-6)  # shadow runs south = +v


def test_anti_solar_points_west_when_sun_in_east():
    cam = _nadir_camera()
    du, dv = anti_solar_image_direction(cam, (2000.0, 1500.0), sun_azimuth_deg=90.0)
    assert du == pytest.approx(-1.0, abs=1e-6)  # shadow runs west = -u
    assert dv == pytest.approx(0.0, abs=1e-6)


def test_anti_solar_is_a_unit_vector():
    cam = _nadir_camera()
    du, dv = anti_solar_image_direction(cam, (2500.0, 1200.0), sun_azimuth_deg=215.0)
    assert math.hypot(du, dv) == pytest.approx(1.0, abs=1e-6)


def test_anti_solar_flips_with_opposite_sun():
    cam = _nadir_camera()
    forward = anti_solar_image_direction(cam, (2000.0, 1500.0), 35.0)
    reverse = anti_solar_image_direction(cam, (2000.0, 1500.0), 215.0)
    assert forward[0] == pytest.approx(-reverse[0], abs=1e-6)
    assert forward[1] == pytest.approx(-reverse[1], abs=1e-6)


def test_anti_solar_none_when_pixel_cannot_project():
    # An oblique camera looking 10 deg below horizontal: a pixel at the top
    # of the frame casts a ray above the horizon that never reaches ground.
    cam = CameraModel(
        agl_m=100.0, pitch_deg=-10.0, yaw_deg=0.0,
        focal_mm=10.0, sensor_w_mm=13.2, sensor_h_mm=8.8,
        width=4000, height=3000,
    )
    assert anti_solar_image_direction(cam, (2000.0, 0.0), 0.0) is None
