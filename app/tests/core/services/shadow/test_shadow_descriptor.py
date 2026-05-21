"""Unit tests for core.services.shadow.ShadowDescriptor."""

import pytest

from core.services.shadow.ShadowDescriptor import (
    STATUS_OK,
    STATUS_UNMEASURABLE,
    ShadowDescriptor,
    expected_shadow_height,
    shadow_matches,
)


def _ok_descriptor(**overrides):
    """An 'ok' descriptor consistent with a ~1.75 m standing subject."""
    base = dict(
        status=STATUS_OK,
        implied_height_m=1.75,
        sigma_m=0.15,
        azimuth_residual_deg=5.0,
        shadow_contrast=0.5,
        attached=True,
        sun_elevation_deg=32.0,
        sun_azimuth_deg=140.0,
    )
    base.update(overrides)
    return ShadowDescriptor(**base)


def test_xml_attribs_round_trip_for_ok_descriptor():
    original = _ok_descriptor(detail='')
    restored = ShadowDescriptor.from_xml_attribs(original.to_xml_attribs())
    assert restored == original


def test_xml_attribs_round_trip_for_unmeasurable_descriptor():
    original = ShadowDescriptor(
        status=STATUS_UNMEASURABLE, detail='Sun too low (3.0 deg).'
    )
    restored = ShadowDescriptor.from_xml_attribs(original.to_xml_attribs())
    assert restored == original


def test_from_xml_attribs_tolerates_missing_values():
    descriptor = ShadowDescriptor.from_xml_attribs({'shadow_status': 'no_shadow'})
    assert descriptor.status == 'no_shadow'
    assert descriptor.implied_height_m is None
    assert descriptor.attached is False


def test_expected_shadow_height_per_posture():
    assert expected_shadow_height(1.8, 'standing') == pytest.approx(1.8)
    assert expected_shadow_height(1.8, 'sitting') == pytest.approx(0.954)
    assert expected_shadow_height(1.8, 'lying') == pytest.approx(0.216)


def test_expected_shadow_height_rejects_unknown_posture():
    with pytest.raises(ValueError):
        expected_shadow_height(1.8, 'crouching')


def test_shadow_matches_accepts_consistent_standing_subject():
    matched, score = shadow_matches(
        _ok_descriptor(), height_m=1.8, postures=['standing'], tolerance_m=0.2
    )
    assert matched is True
    assert score > 0.9


def test_shadow_matches_rejects_height_far_from_implied():
    matched, score = shadow_matches(
        _ok_descriptor(), height_m=1.0, postures=['standing'], tolerance_m=0.1
    )
    assert matched is False
    assert score == 0.0


def test_shadow_matches_rejects_non_ok_descriptor():
    descriptor = _ok_descriptor(status=STATUS_UNMEASURABLE)
    matched, _ = shadow_matches(descriptor, 1.8, ['standing'], 0.2)
    assert matched is False


def test_shadow_matches_rejects_unattached_shadow():
    matched, _ = shadow_matches(
        _ok_descriptor(attached=False), 1.8, ['standing'], 0.2
    )
    assert matched is False


def test_shadow_matches_rejects_large_azimuth_residual():
    matched, _ = shadow_matches(
        _ok_descriptor(azimuth_residual_deg=40.0), 1.8, ['standing'], 0.2
    )
    assert matched is False


def test_shadow_matches_rejects_faint_shadow():
    matched, _ = shadow_matches(
        _ok_descriptor(shadow_contrast=0.01), 1.8, ['standing'], 0.2
    )
    assert matched is False


def test_shadow_matches_handles_sitting_posture():
    # A 0.95 m implied extent matches a 1.8 m subject sitting (0.53 x 1.8).
    descriptor = _ok_descriptor(implied_height_m=0.95)
    matched, _ = shadow_matches(descriptor, 1.8, ['sitting'], tolerance_m=0.1)
    assert matched is True
    # ...but not a 1.8 m subject standing.
    matched_standing, _ = shadow_matches(descriptor, 1.8, ['standing'], 0.1)
    assert matched_standing is False
