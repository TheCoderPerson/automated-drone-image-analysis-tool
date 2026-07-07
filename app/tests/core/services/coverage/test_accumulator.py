"""Spec section 8-4: multi-look combination (max within a bin, product across
bins, common-mode ceiling, per-frame cap, confidence haircut, lazy growth)."""

import numpy as np
import pytest

from core.services.coverage.params import PodParams
from core.services.coverage.accumulator import MissionAccumulator
from core.services.terrain.grid import make_lattice_spec

CELL = 3.0
C = 0.90  # common_mode_ceiling default


def _spec(x0=0.0, y0=0.0, n=30.0):
    return make_lattice_spec((x0, y0, x0 + n, y0 + n), CELL)


def _const_pod(spec, value):
    return np.full((spec.height, spec.width), value, dtype=np.float32)


def _fresh(params=None):
    params = params or PodParams()
    return MissionAccumulator(CELL, params), params


# Each of these tests fills a single constant-valued frame region on an otherwise
# zero mission grid, so the grid max equals the accumulated value at that region
# (independent of where the coarse-snapped mission grid places the frame).


def test_two_frames_same_bin_do_not_compound():
    acc, _ = _fresh()
    spec = _spec()
    for _ in range(2):
        assert acc.add_frame(0, _const_pod(spec, 0.5), spec, yaw_deg=0.0,
                             pitch_deg=-90.0, bearing_confidence=1.0)
    pod, look, _, _, _ = acc.finalize()
    assert float(pod.max()) == pytest.approx(C * 0.5, abs=1e-4)


def test_two_frames_different_bins_combine():
    acc, _ = _fresh()
    spec = _spec()
    acc.add_frame(0, _const_pod(spec, 0.5), spec, 0.0, -90.0, 1.0)     # bin 0
    acc.add_frame(1, _const_pod(spec, 0.5), spec, 180.0, -90.0, 1.0)   # bin 2
    pod, _, _, _, _ = acc.finalize()
    assert float(pod.max()) == pytest.approx(C * 0.75, abs=1e-4)


def test_eight_bins_at_cap_asymptote_to_ceiling():
    acc, _ = _fresh()
    spec = _spec()
    for i, (yaw, pitch) in enumerate([(y, p) for p in (-90.0, -50.0)
                                      for y in (0.0, 90.0, 180.0, 270.0)]):
        acc.add_frame(i, _const_pod(spec, 1.0), spec, yaw, pitch, 1.0)
    pod, _, _, _, _ = acc.finalize()
    v = float(pod.max())
    assert v == pytest.approx(C, abs=1e-3)
    assert v < 1.0


def test_per_frame_cap_applied():
    acc, _ = _fresh()
    spec = _spec()
    acc.add_frame(0, _const_pod(spec, 1.0), spec, 0.0, -90.0, 1.0)
    pod, _, _, _, _ = acc.finalize()
    assert float(pod.max()) == pytest.approx(C * 0.85, abs=1e-4)


def test_low_confidence_haircut():
    acc, params = _fresh()
    spec = _spec()
    acc.add_frame(0, _const_pod(spec, 0.8), spec, 0.0, -90.0, bearing_confidence=0.4)
    pod, _, _, _, _ = acc.finalize()
    expected = C * (0.8 * params.low_confidence_haircut)
    assert float(pod.max()) == pytest.approx(expected, abs=1e-4)


def test_look_count_counts_positive_frames():
    acc, _ = _fresh()
    spec = _spec()
    acc.add_frame(0, _const_pod(spec, 0.5), spec, 0.0, -90.0, 1.0)
    acc.add_frame(1, _const_pod(spec, 0.5), spec, 90.0, -90.0, 1.0)
    _, look, _, _, _ = acc.finalize()
    assert int(look.max()) == 2


def test_lazy_growth_preserves_both_frames():
    acc, _ = _fresh()
    a = _spec(0.0, 0.0)
    b = _spec(3000.0, 3000.0)  # far away -> triggers growth
    assert acc.add_frame(0, _const_pod(a, 0.6), a, 0.0, -90.0, 1.0)
    assert acc.add_frame(1, _const_pod(b, 0.4), b, 0.0, -90.0, 1.0)
    pod, look, _, fidx, transform = acc.finalize()
    from core.services.coverage.contracts import CoverageResult
    res = CoverageResult(pod=pod, look_count=look, transform=transform,
                         image_count=2, skipped=[], stats={}, gap_polygons=[],
                         cancelled=False, frame_index=fidx)
    # Both frame regions carry their values in the grown grid.
    from core.services.terrain.grid import mercator_to_lonlat
    for spec, val, fid in ((a, C * 0.6, 0), (b, C * 0.4, 1)):
        xs, ys = spec.cell_centers()
        cx, cy = float(xs[spec.width // 2]), float(ys[spec.height // 2])
        lon, lat = mercator_to_lonlat(cx, cy)
        s = res.sample(lat, lon)
        assert s is not None
        assert s['pod'] == pytest.approx(val, abs=1e-3)
        assert fid in s['frames']


def test_budget_refusal_returns_false():
    params = PodParams(mem_budget_mb=1)  # tiny budget
    acc = MissionAccumulator(CELL, params)
    a = _spec(0.0, 0.0)
    b = _spec(3000.0, 3000.0)  # union ~1e6 cells -> exceeds 1 MB
    assert acc.add_frame(0, _const_pod(a, 0.6), a, 0.0, -90.0, 1.0)
    assert acc.add_frame(1, _const_pod(b, 0.6), b, 0.0, -90.0, 1.0) is False


@pytest.mark.parametrize("yaw,pitch,expected", [
    (0.0, -90.0, 0), (89.0, -90.0, 1), (91.0, -90.0, 1),
    (181.0, -90.0, 2), (271.0, -90.0, 3),
    (0.0, -50.0, 4), (0.0, -10.0, 4), (271.0, -50.0, 7),
])
def test_bin_for_frame_table(yaw, pitch, expected):
    assert MissionAccumulator.bin_for_frame(yaw, pitch, PodParams()) == expected
