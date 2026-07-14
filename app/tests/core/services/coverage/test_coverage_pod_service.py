"""Orchestration tests for CoveragePodService with mocked geometry/terrain seams."""

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("shapely")

from core.services.coverage.params import PodParams
from core.services.coverage.CoveragePodService import CoveragePodService
from core.services.coverage.contracts import (
    SKIP_HIDDEN, SKIP_NO_POSE, SKIP_PITCH_TOO_SHALLOW, SKIP_NO_DEM, SKIP_ERROR,
)
from core.services.terrain.grid import GridSample
from ._kernel_helpers import make_fg


class _FakeProvider:
    def get_datum_info(self):
        return {"name": "FLAT", "type": "orthometric"}


class _FlatTerrain:
    """Returns a flat (zero-elevation) DEM co-registered to any requested spec."""
    def __init__(self):
        self.provider = _FakeProvider()

    def sample_grid_spec(self, spec):
        data = np.zeros((spec.height, spec.width), dtype=np.float32)
        return GridSample(data=data, transform=spec.transform, crs=spec.crs,
                          datum_note="flat")


class _NoTerrain:
    def __init__(self):
        self.provider = _FakeProvider()

    def sample_grid_spec(self, spec):
        return None


def _service(terrain, params=None):
    svc = CoveragePodService(terrain=terrain, canopy=None,
                             params=params or PodParams(grid_res_m=3.0))

    def fake_fg(image):
        if image.get('_raise'):
            raise RuntimeError("boom")
        return image.get('_fg')

    svc._frame_geometry = fake_fg
    return svc


def test_skip_taxonomy_and_processing():
    images = [
        {'name': 'hidden', 'hidden': True},
        {'name': 'nopose', '_fg': None},
        {'name': 'shallow', '_fg': make_fg(pitch=-5.0)},
        {'name': 'err', '_raise': True},
        {'name': 'good', '_fg': make_fg(pitch=-90.0)},
    ]
    calls = []
    svc = _service(_FlatTerrain())
    result = svc.calculate(images, progress_callback=lambda c, t, m: calls.append((c, t, m)))

    assert result.cancelled is False
    assert result.image_count == 1
    reasons = dict(result.skipped)
    assert reasons['hidden'] == SKIP_HIDDEN
    assert reasons['nopose'] == SKIP_NO_POSE
    assert reasons['shallow'] == SKIP_PITCH_TOO_SHALLOW
    assert reasons['err'] == SKIP_ERROR
    assert result.stats['skipped_counts'][SKIP_ERROR] == 1
    # Per-image progress (5) + 2 finalize ticks.
    assert len(calls) == len(images) + 2


def test_no_dem_skips_all():
    images = [{'name': 'g', '_fg': make_fg(pitch=-90.0)}]
    svc = _service(_NoTerrain())
    result = svc.calculate(images)
    # No frames could be placed (no accumulator) -> empty result.
    assert result.image_count == 0
    assert dict(result.skipped)['g'] == SKIP_NO_DEM
    assert result.pod.size == 0


def test_cancel_immediately():
    images = [{'name': 'g', '_fg': make_fg(pitch=-90.0)}]
    svc = _service(_FlatTerrain())
    result = svc.calculate(images, cancel_check=lambda: True)
    assert result.cancelled is True
    assert result.image_count == 0


def test_cancel_midway():
    images = [{'name': f'g{i}', '_fg': make_fg(pitch=-90.0)} for i in range(4)]
    svc = _service(_FlatTerrain())
    state = {'n': 0}

    def cancel():
        state['n'] += 1
        return state['n'] > 2   # allow a couple of frames, then cancel

    result = svc.calculate(images, cancel_check=cancel)
    assert result.cancelled is True


def test_processed_result_has_products():
    images = [
        {'name': 'a', '_fg': make_fg(pitch=-90.0, yaw=0.0)},
        {'name': 'b', '_fg': make_fg(pitch=-90.0, yaw=90.0)},
    ]
    svc = _service(_FlatTerrain())
    result = svc.calculate(images)
    assert result.image_count == 2
    assert result.pod.ndim == 2 and result.pod.size > 0
    assert result.limiting_factor is not None
    assert result.frame_index is not None
    assert 'area_sqm' in result.stats
    assert result.stats['terrain']['name'] == 'FLAT'
