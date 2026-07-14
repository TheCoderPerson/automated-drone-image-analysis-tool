"""Tests for the GeoTIFF / GeoJSON / stats writers (tmp_path + rasterio read-back)."""

import json

import numpy as np
import pytest

pytest.importorskip("rasterio")
pytest.importorskip("shapely")

import rasterio
from rasterio.enums import ColorInterp
from shapely.geometry import box

from core.services.coverage.params import PodParams
from core.services.coverage.colormap import pod_to_rgba
from core.services.coverage.contracts import CoverageResult
from core.services.coverage import writers
from core.services.terrain.grid import make_lattice_spec, lonlat_to_mercator


@pytest.fixture
def small_result():
    minx, miny = lonlat_to_mercator(-120.50, 38.70)
    spec = make_lattice_spec((minx, miny, minx + 300.0, miny + 240.0), 3.0)
    H, W = spec.height, spec.width
    pod = np.zeros((H, W), dtype=np.float32)
    look = np.zeros((H, W), dtype=np.uint16)
    # A covered patch with high POD in the middle.
    pod[H // 4: 3 * H // 4, W // 4: 3 * W // 4] = 0.8
    look[H // 4: 3 * H // 4, W // 4: 3 * W // 4] = 3
    params = PodParams()
    result = CoverageResult(
        pod=pod, look_count=look, transform=spec.transform, image_count=5,
        skipped=[("a.jpg", "no_dem"), ("b.jpg", "no_dem")], stats={},
        gap_polygons=[], cancelled=False, params=params)
    result.stats = writers.build_stats(
        pod, look, spec.transform, result.skipped, [], params,
        canopy_source="none", terrain_info={"name": "NAVD88"})
    return spec, result


def test_pod_geotiff_roundtrip(tmp_path, small_result):
    spec, result = small_result
    path = str(tmp_path / "coverage_pod.tif")
    rgba = pod_to_rgba(result.pod, result.look_count, result.params)
    writers.write_pod_geotiff(path, rgba, result.transform, result.params)

    with rasterio.open(path) as ds:
        assert ds.count == 4
        assert ds.dtypes[0] == "uint8"
        assert ds.crs.to_epsg() == 3857
        assert ds.colorinterp[3] == ColorInterp.alpha
        assert tuple(ds.transform)[:6] == pytest.approx(tuple(result.transform)[:6])
        alpha = ds.read(4)
        # Uncovered cells (look 0) are fully transparent.
        assert alpha[0, 0] == 0
        # The covered patch is opaque.
        assert alpha[spec.height // 2, spec.width // 2] > 0
        assert ds.tags().get("ADIAT_PRODUCT") == "coverage_pod"


def test_pod_values_geotiff_roundtrip(tmp_path, small_result):
    spec, result = small_result
    path = str(tmp_path / "coverage_pod_values.tif")
    writers.write_pod_values_geotiff(path, result.pod, result.look_count,
                                     result.transform, result.params)
    with rasterio.open(path) as ds:
        assert ds.count == 1
        assert ds.dtypes[0] == "float32"
        assert ds.crs.to_epsg() == 3857
        assert np.isnan(ds.nodata)
        assert tuple(ds.transform)[:6] == pytest.approx(tuple(result.transform)[:6])
        band = ds.read(1)
        looked = result.look_count > 0
        # Actual probabilities are queryable where looked; NaN elsewhere.
        assert band[looked] == pytest.approx(result.pod[looked], abs=1e-6)
        assert np.isnan(band[~looked]).all()
        assert ds.tags()["ADIAT_PRODUCT"] == "coverage_pod_values"


def test_looks_geotiff_roundtrip(tmp_path, small_result):
    spec, result = small_result
    path = str(tmp_path / "coverage_looks.tif")
    writers.write_looks_geotiff(path, result.look_count, result.transform)
    with rasterio.open(path) as ds:
        assert ds.count == 1
        assert ds.dtypes[0] == "uint16"
        assert ds.nodata == 0
        band = ds.read(1)
        assert band.max() == 3


def test_gaps_geojson_is_valid_wgs84(tmp_path, small_result):
    spec, result = small_result
    # A gap polygon in EPSG:3857 near the grid.
    minx, miny, maxx, maxy = spec.bounds
    gap = box(minx + 10, miny + 10, minx + 40, miny + 40)
    path = str(tmp_path / "coverage_gaps.geojson")
    writers.write_gaps_geojson(path, [gap], gap_threshold=0.25)
    with open(path) as fh:
        gj = json.load(fh)
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    feat = gj["features"][0]
    assert feat["properties"]["kind"] == "coverage_gap"
    # Coordinates are lon/lat (WGS84), near -120.5 / 38.7.
    lon, lat = feat["geometry"]["coordinates"][0][0]
    assert -121.0 < lon < -120.0
    assert 38.0 < lat < 39.0


def test_build_stats_keys_and_area(small_result):
    spec, result = small_result
    stats = result.stats
    assert set(stats["area_sqm"].keys()) == {
        "looks_ge_1", "pod_ge_0_25", "pod_ge_0_50", "pod_ge_0_75"}
    # Covered area = number of looked cells * ~9 m^2 (3 m cells), within Mercator scale.
    assert stats["area_sqm"]["looks_ge_1"] > 0
    assert stats["skipped_counts"]["no_dem"] == 2
    assert stats["canopy"]["source"] == "none"


def test_compute_gap_polygons_inside_hull(small_result):
    spec, result = small_result
    minx, miny, maxx, maxy = spec.bounds
    hull = box(minx, miny, maxx, maxy)
    polys = writers.compute_gap_polygons(
        result.pod, result.look_count, result.transform, hull, gap_threshold=0.25)
    # The uncovered border (POD 0 < 0.25) inside the hull yields gap polygon(s).
    assert len(polys) >= 1


def test_write_all_outputs(tmp_path, small_result):
    spec, result = small_result
    out = str(tmp_path / "coverage_pod")
    paths = writers.write_all_outputs(result, out)
    assert set(paths.keys()) == {"pod", "pod_values", "looks", "gaps", "stats"}
    for p in paths.values():
        import os
        assert os.path.exists(p)
