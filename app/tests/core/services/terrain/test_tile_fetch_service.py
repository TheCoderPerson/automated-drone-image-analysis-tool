"""Tests for TileFetchService (quadkey math + mocked 3DEP / Meta downloads)."""

import csv
import os

import pytest

from core.services.terrain.TileFetchService import TileFetchService


class _Resp:
    def __init__(self, status, content=b"TILE"):
        self.status_code = status
        self.content = content


class _Session:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._handler(url, params, len(self.calls))


def _svc(handler):
    return TileFetchService(session=_Session(handler), backoff_ms=0)


# --- quadkey / tiling math ---

def test_quadkey_known_value():
    # Bing docs example: tile (3, 5) at z=3 -> "213".
    assert TileFetchService.tile_xy_to_quadkey(3, 5, 3) == "213"
    assert len(TileFetchService.tile_xy_to_quadkey(10, 20, 9)) == 9


def test_tiles_covering_bbox_count():
    tiles = TileFetchService.tiles_covering_bbox((-120.5, 38.7, -120.48, 38.72), 9)
    assert len(tiles) >= 1
    # A tiny AOI at z9 sits in one or two tiles.
    assert len(tiles) <= 4


def test_tile_bounds_roundtrip():
    x, y, z = 84, 202, 9
    lon0, lat0, lon1, lat1 = TileFetchService.tile_xy_to_bounds(x, y, z)
    assert lon0 < lon1 and lat0 < lat1
    xx, yy = TileFetchService.lnglat_to_tile_xy((lon0 + lon1) / 2, (lat0 + lat1) / 2, z)
    assert (xx, yy) == (x, y)


# --- 3DEP DEM ---

def test_fetch_3dep_params_and_manifest(tmp_path):
    svc = _svc(lambda url, params, n: _Resp(200))
    result = svc.fetch_3dep_dem((-120.50, 38.70, -120.49, 38.71), str(tmp_path),
                                tile_px=2048, native_res_m=1.0)
    assert result.tiles_written >= 1
    assert result.manifest_path and os.path.exists(result.manifest_path)
    # exportImage params carry the required fields.
    _, params = svc.session.calls[0]
    assert params['bboxSR'] == 4326
    assert params['pixelType'] == 'F32'
    assert params['format'] == 'tiff'
    assert 'size' in params and 'bbox' in params
    # Manifest has the USGS3DEPProvider schema (no product column).
    with open(result.manifest_path, newline="") as fh:
        header = next(csv.reader(fh))
    assert header == ['filename', 'minX', 'minY', 'maxX', 'maxY']


def test_fetch_3dep_tiles_large_aoi(tmp_path):
    svc = _svc(lambda url, params, n: _Resp(200))
    # Small tile_px + coarse res forces multiple sub-tiles.
    result = svc.fetch_3dep_dem((-120.60, 38.60, -120.50, 38.70), str(tmp_path),
                                tile_px=256, native_res_m=10.0)
    assert result.tiles_written > 1
    assert len(svc.session.calls) > 1


# --- Meta canopy ---

def test_fetch_meta_url_and_manifest(tmp_path):
    svc = _svc(lambda url, params, n: _Resp(200))
    result = svc.fetch_meta_canopy((-120.50, 38.70, -120.49, 38.71), str(tmp_path))
    assert result.tiles_written >= 1
    url, _ = svc.session.calls[0]
    assert "dataforgood-fb-data.s3.amazonaws.com" in url
    assert url.endswith(".tif") and "/chm/" in url
    with open(result.manifest_path, newline="") as fh:
        header = next(csv.reader(fh))
    assert header == ['filename', 'product', 'minX', 'minY', 'maxX', 'maxY']


def test_fetch_meta_retry_then_success(tmp_path):
    state = {'n': 0}

    def handler(url, params, n):
        state['n'] += 1
        return _Resp(500) if state['n'] == 1 else _Resp(200)

    svc = _svc(handler)
    result = svc.fetch_meta_canopy((-120.50, 38.70, -120.499, 38.701), str(tmp_path))
    assert result.tiles_written >= 1
    assert len(svc.session.calls) >= 2   # retried after the 500


def test_fetch_meta_404_is_skipped(tmp_path):
    svc = _svc(lambda url, params, n: _Resp(404))
    result = svc.fetch_meta_canopy((-120.50, 38.70, -120.49, 38.71), str(tmp_path))
    assert result.tiles_written == 0
    assert result.tiles_skipped >= 1
    assert result.manifest_path is None   # nothing written


def test_fetch_cancel(tmp_path):
    svc = _svc(lambda url, params, n: _Resp(200))
    result = svc.fetch_meta_canopy((-120.50, 38.70, -120.40, 38.80), str(tmp_path),
                                   cancel_check=lambda: True)
    assert result.cancelled is True
