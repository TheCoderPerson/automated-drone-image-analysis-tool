"""Tests for CanopyServiceFactory.create_from_settings and the create_canopy_service alias."""

from unittest.mock import MagicMock

from core.services.terrain.CanopyServiceFactory import (
    CanopyServiceFactory,
    create_canopy_service,
    CANOPY_KIND_NONE,
)


def _settings(values):
    s = MagicMock()
    s.get_setting.side_effect = lambda k, d=None: values.get(k, d)
    return s


def test_none_settings_returns_none():
    assert CanopyServiceFactory.create_from_settings(None) is None


def test_kind_none_returns_none():
    s = _settings({'CanopyKind': CANOPY_KIND_NONE})
    assert CanopyServiceFactory.create_from_settings(s) is None


def test_landfire_missing_paths_returns_none():
    s = _settings({'CanopyKind': 'landfire'})
    assert CanopyServiceFactory.create_from_settings(s) is None


def test_meta_with_paths_builds_service(tmp_path):
    manifest = tmp_path / "m.csv"
    manifest.write_text("filename,product,minX,minY,maxX,maxY\n")
    s = _settings({'CanopyKind': 'meta',
                   'CanopyManifestPath': str(manifest),
                   'CanopyTilesDir': str(tmp_path)})
    svc = CanopyServiceFactory.create_from_settings(s)
    assert svc is not None
    assert svc.kind == 'meta'


def test_alias_matches_classmethod():
    s = _settings({'CanopyKind': CANOPY_KIND_NONE})
    assert create_canopy_service(s) is None


def test_available_kinds_shape():
    kinds = CanopyServiceFactory.available_kinds()
    ids = [k['id'] for k in kinds]
    assert ids == ['none', 'landfire', 'meta']
    assert all('label' in k and 'requires_paths' in k for k in kinds)
