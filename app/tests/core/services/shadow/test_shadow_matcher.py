"""Unit tests for core.services.shadow.ShadowMatcher."""

import numpy as np
import pytest

from core.services.CameraModel import CameraModel
from core.services.shadow.ShadowDescriptor import (
    STATUS_NO_SHADOW,
    STATUS_OK,
    STATUS_UNMEASURABLE,
)
from core.services.shadow.ShadowHeightEstimator import ShadowHeightResult
from core.services.shadow.ShadowImageContext import ShadowImageContext
from core.services.shadow.ShadowMatcher import ShadowMatcher, locate_shadow


# --- locate_shadow: pure mask analysis, no camera needed -------------------

def test_locate_shadow_finds_blob_along_ray():
    mask = np.zeros((120, 80), dtype=np.uint8)
    mask[30:70, 35:45] = 255
    blob = locate_shadow(mask, base=(40, 10), direction=(0.0, 1.0),
                         max_len_px=100, attach_tol_px=40)
    assert blob is not None
    assert blob.attached is True
    assert blob.tip[1] == pytest.approx(69, abs=1)   # farthest blob row
    assert blob.length_px == pytest.approx(59, abs=2)  # 69 - base row 10


def test_locate_shadow_returns_none_for_empty_mask():
    mask = np.zeros((100, 100), dtype=np.uint8)
    assert locate_shadow(mask, (50, 10), (0.0, 1.0), 80, 40) is None


def test_locate_shadow_ignores_blob_off_the_ray():
    mask = np.zeros((120, 120), dtype=np.uint8)
    mask[20:60, 80:100] = 255  # blob well to the right of the ray
    blob = locate_shadow(mask, base=(20, 10), direction=(0.0, 1.0),
                         max_len_px=100, attach_tol_px=40)
    assert blob is None


def test_locate_shadow_marks_distant_blob_unattached():
    mask = np.zeros((200, 80), dtype=np.uint8)
    mask[120:160, 35:45] = 255  # first hit is 110 px from the base
    blob = locate_shadow(mask, base=(40, 10), direction=(0.0, 1.0),
                         max_len_px=180, attach_tol_px=30)
    assert blob is not None
    assert blob.attached is False


# --- ShadowMatcher.measure -------------------------------------------------

class _FakeEstimator:
    """Stand-in for ShadowHeightEstimator with a canned result."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def estimate(self, image, base_px, tip_px, allow_azimuth_override=False, context=None):
        self.calls.append((base_px, tip_px))
        return self._result


def _nadir_camera():
    return CameraModel(
        agl_m=50.0, pitch_deg=-90.0, yaw_deg=0.0,
        focal_mm=10.0, sensor_w_mm=13.2, sensor_h_mm=8.8,
        width=400, height=400,
    )


def _context(img_bgr, sun_elevation_deg=30.0, sun_azimuth_deg=0.0, error=None):
    return ShadowImageContext(
        image={'path': 'synthetic'},
        img_bgr=img_bgr,
        camera=_nadir_camera(),
        sun_elevation_deg=sun_elevation_deg,
        sun_azimuth_deg=sun_azimuth_deg,
        error=error,
    )


def _image_with_shadow():
    """Bright 400x400 BGR image with a dark shadow below the AOI at (200, 150).

    With a nadir camera and the sun in the north, the shadow runs south (+v).
    """
    img = np.full((400, 400, 3), 210, dtype=np.uint8)
    img[155:185, 192:208] = 70
    return img


def test_measure_reports_ok_when_a_shadow_is_found():
    estimator = _FakeEstimator(ShadowHeightResult(
        confidence='ok', height_m=1.7, sigma_m=0.2, delta_az_deg=4.0,
    ))
    matcher = ShadowMatcher(estimator=estimator)

    descriptor = matcher.measure(
        {'path': 'synthetic'}, {'center': (200, 150)},
        context=_context(_image_with_shadow()),
    )

    assert descriptor.status == STATUS_OK
    assert descriptor.implied_height_m == 1.7
    assert descriptor.azimuth_residual_deg == 4.0
    assert descriptor.attached is True
    assert descriptor.shadow_contrast > 0.3
    assert len(estimator.calls) == 1


def test_measure_reports_no_shadow_for_a_uniform_image():
    matcher = ShadowMatcher(estimator=_FakeEstimator(None))
    descriptor = matcher.measure(
        {'path': 'synthetic'}, {'center': (200, 150)},
        context=_context(np.full((400, 400, 3), 210, dtype=np.uint8)),
    )
    assert descriptor.status == STATUS_NO_SHADOW


def test_measure_unmeasurable_when_context_invalid():
    matcher = ShadowMatcher(estimator=_FakeEstimator(None))
    descriptor = matcher.measure(
        {'path': 'synthetic'}, {'center': (200, 150)},
        context=_context(_image_with_shadow(), error='no camera pose'),
    )
    assert descriptor.status == STATUS_UNMEASURABLE
    assert 'no camera pose' in descriptor.detail


def test_measure_unmeasurable_when_sun_too_low():
    matcher = ShadowMatcher(estimator=_FakeEstimator(None))
    descriptor = matcher.measure(
        {'path': 'synthetic'}, {'center': (200, 150)},
        context=_context(_image_with_shadow(), sun_elevation_deg=2.0),
    )
    assert descriptor.status == STATUS_UNMEASURABLE
    assert 'Sun too low' in descriptor.detail


def test_measure_unmeasurable_when_estimator_rejects():
    estimator = _FakeEstimator(ShadowHeightResult(
        confidence='rejected', rejection_reason='inconsistent geometry',
    ))
    matcher = ShadowMatcher(estimator=estimator)
    descriptor = matcher.measure(
        {'path': 'synthetic'}, {'center': (200, 150)},
        context=_context(_image_with_shadow()),
    )
    assert descriptor.status == STATUS_UNMEASURABLE
    assert 'inconsistent geometry' in descriptor.detail
