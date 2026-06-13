"""Tests for the Method Test Lab's promotable detection functions.

The functions under test live in scripts/method_lab/ (a dev tool outside
the app package); they are tested here because they are the candidate
core of a future production algorithm plugin.
"""

import os
import sys

import numpy as np
import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts')
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from method_lab.methods.saliency import (  # noqa: E402
    saliency_map, saliency_mask, sensitivity_percentile, spectral_residual,
)
from method_lab.methods.edge_texture import (  # noqa: E402
    edge_texture_mask, edge_texture_score,
)
from method_lab.adapters import mask_to_aois  # noqa: E402


def _uniform_image(value=128, size=400):
    return np.full((size, size, 3), value, np.uint8)


def _square_on_uniform(value=128, square_value=210, size=400, square=14):
    img = _uniform_image(value, size)
    y = x = (size - square) // 2
    img[y:y + square, x:x + square] = square_value
    return img, (y, x, square)


def _patch_on_texture(seed=0, size=400, square=28, bg_tex=10, patch_value=205):
    """A contrasting patch on a lightly textured background (SAR-like).

    Spectral-residual saliency is tuned for textured natural scenes, so a
    realistic test uses textured terrain rather than a dead-flat field.
    """
    rng = np.random.RandomState(seed)
    base = 128 + (rng.randn(size, size, 1) * bg_tex)
    img = base.clip(0, 255).astype(np.uint8).repeat(3, axis=2)
    y = x = (size - square) // 2
    img[y:y + square, x:x + square] = patch_value
    return img, (y, x, square)


# ---------------------------------------------------------------------------
# Saliency
# ---------------------------------------------------------------------------

def test_sensitivity_percentile_monotonic_and_clamped():
    values = [sensitivity_percentile(s) for s in range(1, 11)]
    assert values[0] == pytest.approx(99.95)
    assert values[-1] == pytest.approx(99.50)
    assert all(a > b for a, b in zip(values, values[1:]))
    # Out-of-range sensitivities clamp to the ends.
    assert sensitivity_percentile(0) == pytest.approx(99.95)
    assert sensitivity_percentile(99) == pytest.approx(99.50)


def test_spectral_residual_uniform_input_is_zero():
    flat = np.full((64, 64), 0.5, np.float32)
    assert spectral_residual(flat).max() == 0.0


def test_saliency_mask_empty_on_uniform_image():
    mask, score = saliency_mask(_uniform_image(), sensitivity=10, segments=1)
    assert mask.sum() == 0
    assert score.max() == 0.0


def test_saliency_mask_finds_patch_on_textured_background():
    img, (y, x, square) = _patch_on_texture()
    mask, score = saliency_mask(img, sensitivity=8, segments=1)

    pad = 24  # spectral residual spreads the response around the patch
    region = mask[max(0, y - pad):y + square + pad, max(0, x - pad):x + square + pad]
    assert region.any(), "the contrasting patch must be flagged"
    # Detections stay sparse: well under 2% of the frame.
    assert (mask > 0).mean() < 0.02
    assert score.shape == img.shape[:2]


def test_saliency_map_is_deterministic():
    rng = np.random.RandomState(42)
    img = rng.randint(0, 255, (300, 300, 3), np.uint8)
    first = saliency_map(img, segments=4)
    second = saliency_map(img, segments=4)
    assert np.array_equal(first, second)


def test_saliency_map_segments_match_image_shape():
    img, _ = _square_on_uniform(size=401)  # non-divisible by the 3x3 grid
    score = saliency_map(img, segments=9)
    assert score.shape == (401, 401)
    assert 0.0 <= score.min() and score.max() <= 1.0


# ---------------------------------------------------------------------------
# Edge/texture
# ---------------------------------------------------------------------------

def test_edge_texture_empty_on_uniform_image():
    mask, score = edge_texture_mask(_uniform_image())
    assert mask.sum() == 0
    assert score.max() == 0.0


def test_edge_texture_finds_square_on_uniform_background():
    img, (y, x, square) = _square_on_uniform()
    mask, score = edge_texture_mask(img, window=15, deviation_percentile=99.5)

    pad = 20  # window smear puts the response around the square's edges
    region = mask[max(0, y - pad):y + square + pad, max(0, x - pad):x + square + pad]
    assert region.any(), "the square's edges must be flagged"
    assert (mask > 0).mean() < 0.05


def test_edge_texture_score_is_deterministic():
    rng = np.random.RandomState(7)
    img = rng.randint(0, 255, (300, 300, 3), np.uint8)
    first = edge_texture_score(img)
    second = edge_texture_score(img)
    assert np.array_equal(first, second)


def test_edge_texture_percentile_clamps():
    img, _ = _square_on_uniform()
    # Out-of-range percentiles must not raise.
    mask_low, _ = edge_texture_mask(img, deviation_percentile=0)
    mask_high, _ = edge_texture_mask(img, deviation_percentile=100)
    assert mask_low.shape == mask_high.shape == img.shape[:2]


# ---------------------------------------------------------------------------
# mask_to_aois
# ---------------------------------------------------------------------------

def test_mask_to_aois_empty_mask():
    assert mask_to_aois(np.zeros((50, 50), np.uint8)) == []
    assert mask_to_aois(None) == []


def test_mask_to_aois_finds_blob_with_padding():
    mask = np.zeros((100, 100), np.uint8)
    mask[40:60, 40:60] = 255
    aois = mask_to_aois(mask, min_area=10, aoi_radius=15)
    assert len(aois) == 1
    center_x, center_y = aois[0]['center']
    assert abs(center_x - 49) <= 2 and abs(center_y - 49) <= 2
    assert aois[0]['radius'] > 15  # enclosing radius plus the pad
    assert aois[0]['area'] == pytest.approx(361.0, rel=0.1)


def test_mask_to_aois_area_filters():
    mask = np.zeros((100, 100), np.uint8)
    mask[10:12, 10:12] = 255    # tiny blob (area ~1-4 px)
    mask[40:80, 40:80] = 255    # large blob (~1521 px)
    aois = mask_to_aois(mask, min_area=50, max_area=0)
    assert len(aois) == 1
    aois = mask_to_aois(mask, min_area=50, max_area=500)
    assert aois == []
