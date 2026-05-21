"""Unit tests for core.services.shadow.ShadowSegmenter."""

import numpy as np
import pytest

from core.services.shadow.ShadowSegmenter import ShadowSegmenter, METHOD_OTSU


def _patch(size=60, background=210, shadow=70, shadow_box=None):
    """A BGR patch: a uniform bright background with an optional dark box.

    shadow_box is (y0, x0, y1, x1) in pixels.
    """
    patch = np.full((size, size, 3), background, dtype=np.uint8)
    if shadow_box is not None:
        y0, x0, y1, x1 = shadow_box
        patch[y0:y1, x0:x1] = shadow
    return patch


def test_relative_marks_the_dark_box():
    patch = _patch(shadow_box=(20, 20, 40, 40))
    mask = ShadowSegmenter().segment(patch)

    assert mask.shape == patch.shape[:2]
    # Interior of the box is shadow; interior of the background is not.
    assert mask[25:35, 25:35].mean() > 200
    assert mask[5:15, 5:15].mean() < 30


def test_relative_finds_no_shadow_in_a_uniform_patch():
    mask = ShadowSegmenter().segment(_patch())
    assert mask.max() == 0


def test_otsu_splits_a_bimodal_patch():
    patch = _patch()
    patch[:, 30:] = 70  # right half in shadow
    mask = ShadowSegmenter(method=METHOD_OTSU).segment(patch)

    assert mask[10:50, 40:55].mean() > 200   # dark half marked
    assert mask[10:50, 5:20].mean() < 30     # bright half not marked


def test_grayscale_patch_is_accepted():
    patch = np.full((60, 60), 210, dtype=np.uint8)
    patch[20:40, 20:40] = 70
    mask = ShadowSegmenter().segment(patch)
    assert mask[25:35, 25:35].mean() > 200
    assert mask[5:15, 5:15].mean() < 30


def test_isolated_speckle_is_suppressed():
    patch = _patch()
    # Scatter a few isolated dark pixels - sensor-noise-scale.
    for y, x in ((10, 10), (10, 50), (50, 10), (50, 50), (30, 30)):
        patch[y, x] = 70
    mask = ShadowSegmenter().segment(patch)
    assert mask.max() == 0


def test_cleanup_removes_small_blobs_but_keeps_large_ones():
    mask = np.zeros((60, 60), dtype=np.uint8)
    mask[5:7, 5:7] = 255       # tiny blob, smaller than the kernel
    mask[20:45, 20:45] = 255   # large blob

    cleaned = ShadowSegmenter(morph_kernel=3)._cleanup(mask)
    assert cleaned[4:8, 4:8].max() == 0          # speckle opened away
    assert cleaned[25:40, 25:40].mean() > 200    # large blob kept


def test_cleanup_disabled_when_kernel_is_zero():
    mask = np.zeros((60, 60), dtype=np.uint8)
    mask[5:7, 5:7] = 255
    unchanged = ShadowSegmenter(morph_kernel=0)._cleanup(mask)
    assert np.array_equal(unchanged, mask)


def test_segment_rejects_none():
    with pytest.raises(ValueError):
        ShadowSegmenter().segment(None)


def test_segment_rejects_empty():
    with pytest.raises(ValueError):
        ShadowSegmenter().segment(np.empty((0, 0, 3), dtype=np.uint8))


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        ShadowSegmenter(method='bogus')
