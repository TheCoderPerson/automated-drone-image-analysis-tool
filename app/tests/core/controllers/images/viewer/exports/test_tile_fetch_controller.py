"""Tests for TileFetchThread + TileFetchController wiring."""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from core.controllers.images.viewer.exports.TileFetchController import (
    TileFetchThread,
    TileFetchController,
)
from core.services.terrain.TileFetchService import FetchResult


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_thread_runs_both_products(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.return_value = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"), None)
    service.fetch_meta_canopy.return_value = FetchResult('meta_chm', str(tmp_path / "chm"), None)
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=True)
    results = []
    thread.finished.connect(lambda r: results.append(r))
    thread.run()
    assert service.fetch_3dep_dem.called
    assert service.fetch_meta_canopy.called
    assert results and 'dem' in results[0] and 'canopy' in results[0]


def test_thread_dem_only(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.return_value = FetchResult('usgs_3dep_dem', str(tmp_path), None)
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=False)
    thread.run()
    assert service.fetch_3dep_dem.called
    assert not service.fetch_meta_canopy.called


def test_thread_emits_error(app, tmp_path):
    service = MagicMock()
    service.fetch_3dep_dem.side_effect = RuntimeError("net down")
    thread = TileFetchThread(service, (-120.5, 38.7, -120.4, 38.8), str(tmp_path),
                             want_dem=True, want_canopy=False)
    errors = []
    thread.errorOccurred.connect(lambda m: errors.append(m))
    thread.run()
    assert errors and "net down" in errors[0]


def test_register_results_writes_settings(app, tmp_path):
    settings = MagicMock()
    stored = {}
    settings.set_setting.side_effect = lambda k, v: stored.__setitem__(k, v)
    ctrl = TileFetchController(MagicMock(), settings)
    ctrl._register = True

    dem = FetchResult('usgs_3dep_dem', str(tmp_path / "dem"),
                      str(tmp_path / "dem" / "dem_manifest.csv"))
    canopy = FetchResult('meta_chm', str(tmp_path / "chm"),
                         str(tmp_path / "chm" / "chm_manifest.csv"))
    ctrl._register_results({'dem': dem, 'canopy': canopy})

    assert stored['Terrain3DEPManifestPath'] == dem.manifest_path
    assert stored['Terrain3DEPTilesDir'] == dem.out_dir
    assert stored['TerrainProviderId'] == 'usgs_3dep_local'
    assert stored['CanopyManifestPath'] == canopy.manifest_path
    assert stored['CanopyTilesDir'] == canopy.out_dir
    assert stored['CanopyKind'] == 'meta'


def test_register_disabled_writes_nothing(app):
    settings = MagicMock()
    ctrl = TileFetchController(MagicMock(), settings)
    ctrl._register = False
    ctrl._register_results({'dem': FetchResult('usgs_3dep_dem', "d", "m.csv")})
    settings.set_setting.assert_not_called()
