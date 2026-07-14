"""Tests for the POD / look-count RGBA lookup tables."""

import numpy as np

from core.services.coverage.params import PodParams
from core.services.coverage.colormap import (
    _build_pod_lut,
    pod_to_rgba,
    look_count_to_rgba,
    chm_to_rgba,
)


def test_pod_lut_shape_and_alpha_ramp():
    lut = _build_pod_lut(0.05)
    assert lut.shape == (256, 4)
    floor_i = int(round(0.05 * 255))
    # Fully transparent below the floor, opaque-ish above.
    assert np.all(lut[:floor_i, 3] == 0)
    assert lut[floor_i:, 3].max() > 150
    # Alpha is monotonically non-decreasing above the floor.
    assert np.all(np.diff(lut[floor_i:, 3].astype(int)) >= 0)


def test_pod_to_rgba_transparent_where_no_looks():
    params = PodParams()
    pod = np.array([[0.0, 0.5], [0.8, 0.9]], dtype=np.float32)
    look = np.array([[0, 2], [0, 3]], dtype=np.uint16)
    rgba = pod_to_rgba(pod, look, params)
    assert rgba.shape == (2, 2, 4)
    # Cells with zero looks are fully transparent regardless of POD value.
    assert tuple(rgba[0, 0]) == (0, 0, 0, 0)
    assert tuple(rgba[1, 0]) == (0, 0, 0, 0)
    # Looked cells above the floor are opaque.
    assert rgba[0, 1, 3] > 0
    assert rgba[1, 1, 3] > 0


def test_chm_rgba_transparent_at_open_ground_and_nodata():
    chm = np.array([[np.nan, 0.0, 0.3, 5.0]], dtype=np.float32)
    rgba = chm_to_rgba(chm)
    assert rgba.shape == (1, 4, 4)
    # NaN, bare ground, and sub-threshold vegetation are all fully transparent.
    assert tuple(rgba[0, 0]) == (0, 0, 0, 0)
    assert tuple(rgba[0, 1]) == (0, 0, 0, 0)
    assert tuple(rgba[0, 2]) == (0, 0, 0, 0)
    assert rgba[0, 3, 3] > 0


def test_chm_rgba_darker_and_more_opaque_with_height():
    chm = np.array([[2.0, 15.0, 35.0, 80.0]], dtype=np.float32)
    rgba = chm_to_rgba(chm, max_height_m=35.0)
    # Green channel dominates and darkens as canopy gets taller.
    lum = rgba[0, :, :3].astype(int).sum(axis=1)
    assert lum[0] > lum[1] > lum[2]
    # Alpha rises with height, saturating at max_height_m.
    assert rgba[0, 0, 3] < rgba[0, 1, 3] < rgba[0, 2, 3]
    assert tuple(rgba[0, 2]) == tuple(rgba[0, 3])


def test_look_count_rgba_saturates():
    look = np.array([[0, 1, 2, 3, 4, 5, 9]], dtype=np.uint16)
    rgba = look_count_to_rgba(look)
    assert tuple(rgba[0, 0]) == (0, 0, 0, 0)   # 0 looks transparent
    assert rgba[0, 1, 3] > 0                    # 1 look visible
    # 5 and 9 saturate to the same top step.
    assert tuple(rgba[0, 5]) == tuple(rgba[0, 6])
