"""ShadowGeometry - shadow-specific geometry helpers built on CameraModel.

Small composition helpers that bridge the sun position (from SolarPosition)
and the image's camera pose (CameraModel) for the shadow matcher. Kept apart
from PersonShadow, which stops at ground points and has no camera dependency.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


def anti_solar_image_direction(
    camera,
    base_pixel: Tuple[float, float],
    sun_azimuth_deg: float,
    probe_m: float = 5.0,
) -> Optional[Tuple[float, float]]:
    """Direction a cast shadow runs, in image pixels, at a given pixel.

    A shadow falls away from the sun. This projects a short ground vector
    pointing anti-solar from the pixel's ground point and returns the
    resulting pixel-space direction, so the matcher knows which way to look
    for the shadow and how to orient its search band.

    Args:
        camera: a CameraModel for the image.
        base_pixel: (u, v) pixel the shadow is cast from (the AOI base).
        sun_azimuth_deg: sun azimuth, degrees (0 = north, clockwise).
        probe_m: length of the ground probe vector, metres. Only its
            direction matters; a few metres keeps the projection well
            inside the frame.

    Returns:
        (du, dv) unit vector in pixel coordinates, or None when the base
        pixel or the probe point cannot be projected (e.g. the ray misses
        the ground, or the probe lands behind the image plane).
    """
    u, v = base_pixel
    ground = camera.pixel_to_ground(u, v)
    if ground is None:
        return None
    north, east, down = ground

    # Shadows fall away from the sun.
    anti_sun = math.radians(sun_azimuth_deg + 180.0)
    probe_north = north + probe_m * math.cos(anti_sun)
    probe_east = east + probe_m * math.sin(anti_sun)

    tip = camera.project(probe_north, probe_east, down)
    if tip is None:
        return None

    du = tip[0] - u
    dv = tip[1] - v
    norm = math.hypot(du, dv)
    if norm < 1e-9:
        return None
    return (du / norm, dv / norm)
