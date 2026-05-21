"""Unit tests for ShadowImageContext and the ShadowHeightEstimator context reuse."""

from types import SimpleNamespace

import numpy as np

from core.services.shadow import ShadowHeightEstimator as she_module
from core.services.shadow.ShadowHeightEstimator import ShadowHeightEstimator
from core.services.shadow.ShadowImageContext import ShadowImageContext


def test_context_is_valid_when_complete():
    context = ShadowImageContext(
        image={'path': 'x'},
        img_bgr=np.zeros((4, 4, 3), dtype=np.uint8),
        camera=object(),
        sun_elevation_deg=30.0,
        sun_azimuth_deg=120.0,
    )
    assert context.is_valid() is True


def test_context_is_invalid_with_error():
    context = ShadowImageContext(
        image={'path': 'x'},
        img_bgr=np.zeros((4, 4, 3), dtype=np.uint8),
        camera=object(),
        sun_elevation_deg=30.0,
        sun_azimuth_deg=120.0,
        error='no camera',
    )
    assert context.is_valid() is False


def test_context_is_invalid_when_pieces_missing():
    assert ShadowImageContext(image={'path': 'x'}).is_valid() is False
    assert ShadowImageContext(
        image={'path': 'x'},
        img_bgr=np.zeros((4, 4, 3), dtype=np.uint8),
        camera=object(),
    ).is_valid() is False  # no sun position


def test_estimate_reuses_context_instead_of_reading_exif(monkeypatch):
    """With a context supplied, estimate() must not re-read the file's EXIF."""
    def boom(*args, **kwargs):
        raise AssertionError("EXIF should not be read when a context is given")

    monkeypatch.setattr(she_module.MetaDataHelper, 'get_exif_data_piexif', boom)

    # aoi_service present -> the context branch is taken; empty exif_data then
    # makes resolve_capture_utc reject, which is fine: it proves we got past
    # the EXIF read without calling it.
    context = SimpleNamespace(aoi_service=object(), exif_data={}, xmp_data=None)
    result = ShadowHeightEstimator().estimate(
        {'path': 'does-not-exist.jpg'}, (10.0, 10.0), (20.0, 20.0), context=context
    )
    assert result.confidence == 'rejected'
    assert 'Could not read EXIF' not in (result.rejection_reason or '')
