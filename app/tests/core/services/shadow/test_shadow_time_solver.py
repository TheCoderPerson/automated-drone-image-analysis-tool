"""Tests for ShadowTimeSolver - traced shadow azimuth -> capture time."""

from datetime import datetime, timedelta, timezone

import pytest

from core.services.shadow.SolarPosition import get_solar_position
from core.services.shadow.ShadowTimeSolver import (
    solve_time_for_shadow_azimuth,
    _circular_diff_deg,
)

# Mid-latitude test site (Inyo County, CA area).
_LAT, _LON = 36.8, -118.2


def _shadow_azimuth_at(utc):
    """The azimuth a real shadow points along at the test site at ``utc``."""
    _elev, sun_az = get_solar_position(_LAT, _LON, utc)
    return (sun_az + 180.0) % 360.0


def test_circular_diff():
    assert _circular_diff_deg(350.0, 10.0) == pytest.approx(20.0)
    assert _circular_diff_deg(10.0, 350.0) == pytest.approx(20.0)
    assert _circular_diff_deg(180.0, 180.0) == pytest.approx(0.0)


def test_round_trip_recovers_capture_time():
    """A shadow computed for a known moment solves back to that moment."""
    truth = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)  # 10:00 PDT
    shadow_az = _shadow_azimuth_at(truth)
    solution = solve_time_for_shadow_azimuth(_LAT, _LON, truth, shadow_az)
    assert solution is not None
    assert abs((solution.utc - truth).total_seconds()) < 120
    assert not solution.direction_flipped
    assert solution.azimuth_error_deg < 1.0
    assert solution.sun_elevation_deg > 0


def test_solves_even_when_camera_clock_is_hours_wrong():
    """Only the date matters: a claimed time hours off still resolves."""
    truth = datetime(2026, 6, 15, 22, 30, tzinfo=timezone.utc)  # 15:30 PDT
    shadow_az = _shadow_azimuth_at(truth)
    claimed = truth - timedelta(hours=7)  # broken clock
    solution = solve_time_for_shadow_azimuth(_LAT, _LON, claimed, shadow_az)
    assert solution is not None
    assert abs((solution.utc - truth).total_seconds()) < 120


def test_reversed_trace_is_detected_and_flipped():
    """Clicking tip-then-base yields the anti-azimuth; when that direction
    is unmatchable by any daylight sun the solver flips it and says so.

    Uses a near-solar-noon truth: its shadow points north, so the reversed
    trace (south-pointing shadow = northern sun) has no daylight match at
    mid latitudes and only the flipped interpretation fits.
    """
    truth = datetime(2026, 6, 15, 19, 50, tzinfo=timezone.utc)  # ~solar noon
    reversed_az = (_shadow_azimuth_at(truth) + 180.0) % 360.0
    solution = solve_time_for_shadow_azimuth(_LAT, _LON, truth, reversed_az)
    assert solution is not None
    assert solution.direction_flipped
    assert abs((solution.utc - truth).total_seconds()) < 300


def test_unmatchable_azimuth_returns_none(monkeypatch):
    """When no daylight sun position matches either orientation -> None."""
    import core.services.shadow.ShadowTimeSolver as solver_mod
    # Force "night all day": every sample is below the elevation floor.
    monkeypatch.setattr(solver_mod, 'MIN_SUN_ELEVATION_DEG', 91.0)
    truth = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)
    assert solve_time_for_shadow_azimuth(_LAT, _LON, truth, 45.0) is None


def test_winter_date_round_trip():
    """Solar geometry differs by season; a winter date must also invert."""
    truth = datetime(2026, 1, 20, 20, 0, tzinfo=timezone.utc)  # 12:00 PST
    shadow_az = _shadow_azimuth_at(truth)
    solution = solve_time_for_shadow_azimuth(_LAT, _LON, truth, shadow_az)
    assert solution is not None
    assert abs((solution.utc - truth).total_seconds()) < 120


def test_naive_capture_time_rejected():
    with pytest.raises(ValueError):
        solve_time_for_shadow_azimuth(
            _LAT, _LON, datetime(2026, 6, 15, 17, 0), 45.0)
