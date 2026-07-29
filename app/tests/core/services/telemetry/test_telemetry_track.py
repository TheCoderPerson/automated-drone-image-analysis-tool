"""Tests for time-indexed telemetry sampling and derived motion."""

import pytest

from core.services.telemetry.DjiSrtParser import DjiSrtSample
from core.services.telemetry.TelemetryTrack import (
    TelemetryTrack,
    haversine_meters,
)


def _sample(t, lat=30.0, lon=-97.0, msl=200.0, agl=15.0, yaw=90.0):
    return DjiSrtSample(
        start_seconds=t,
        end_seconds=t + 0.033,
        latitude=lat,
        longitude=lon,
        altitude_msl_m=msl,
        altitude_agl_m=agl,
        yaw_deg=yaw,
    )


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_meters(30.0, -97.0, 30.0, -97.0) == pytest.approx(0.0)

    def test_one_degree_latitude_is_about_111km(self):
        d = haversine_meters(30.0, -97.0, 31.0, -97.0)
        assert d == pytest.approx(111_195, rel=0.01)

    def test_symmetric(self):
        a = haversine_meters(30.0, -97.0, 30.1, -97.1)
        b = haversine_meters(30.1, -97.1, 30.0, -97.0)
        assert a == pytest.approx(b)


class TestSampling:
    def test_empty_track(self):
        track = TelemetryTrack([])
        assert len(track) == 0
        assert not track
        assert track.sample_at(0.0) is None
        assert track.duration_seconds == 0.0

    def test_returns_nearest_sample(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, lat=30.0), _sample(1.0, lat=31.0), _sample(2.0, lat=32.0),
        ])
        assert track.point_at(0.9).latitude == pytest.approx(31.0)
        assert track.point_at(1.4).latitude == pytest.approx(31.0)
        assert track.point_at(1.6).latitude == pytest.approx(32.0)

    def test_beyond_max_gap_returns_none(self):
        """A telemetry dropout reads as unknown, not silently interpolated."""
        track = TelemetryTrack.from_dji_samples(
            [_sample(0.0), _sample(60.0)], max_gap_seconds=1.0
        )
        assert track.point_at(30.0) is None
        assert track.sample_at(30.0) is None

    def test_exact_hit_within_gap(self):
        track = TelemetryTrack.from_dji_samples([_sample(5.0)], max_gap_seconds=1.0)
        assert track.point_at(5.0) is not None
        assert track.point_at(5.5) is not None
        assert track.point_at(7.0) is None

    def test_samples_without_position_are_dropped(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0),
            DjiSrtSample(start_seconds=1.0, end_seconds=1.0),  # no lat/lon
            _sample(2.0),
        ])
        assert len(track) == 2


class TestEnvelope:
    def test_matches_the_hud_field_names(self):
        """The HUD renders these exact keys; a rename here breaks it silently."""
        track = TelemetryTrack.from_dji_samples([_sample(0.0)])
        env = track.sample_at(0.0)
        for key in (
            "aircraft_latitude", "aircraft_longitude",
            "aircraft_altitude_msl_m", "aircraft_altitude_agl_m",
            "aircraft_yaw_deg", "horizontal_speed_ms", "vertical_speed_ms",
        ):
            assert key in env

    def test_reports_agl_source_as_reported(self):
        track = TelemetryTrack.from_dji_samples([_sample(0.0)])
        assert track.sample_at(0.0)["agl_source"] == "reported"

    def test_agl_source_none_without_agl(self):
        track = TelemetryTrack.from_dji_samples([_sample(0.0, agl=None)])
        assert track.sample_at(0.0)["agl_source"] is None

    def test_carries_video_time(self):
        track = TelemetryTrack.from_dji_samples([_sample(3.5)])
        env = track.sample_at(3.5)
        assert env["video_time_seconds"] == pytest.approx(3.5)
        assert env["captured_at_ms"] == 3500


class TestDerivedMotion:
    def test_first_sample_has_no_speed(self):
        track = TelemetryTrack.from_dji_samples([_sample(0.0)])
        assert track.points[0].horizontal_speed_ms is None
        assert track.points[0].vertical_speed_ms is None

    def test_horizontal_speed_from_position_delta(self):
        # ~111 m north over 1 s.
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, lat=30.0), _sample(1.0, lat=30.001),
        ])
        speed = track.points[1].horizontal_speed_ms
        assert speed == pytest.approx(111, rel=0.05)

    def test_vertical_speed_from_altitude_delta(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, msl=200.0), _sample(2.0, msl=210.0),
        ])
        assert track.points[1].vertical_speed_ms == pytest.approx(5.0)

    def test_descending_is_negative(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, msl=210.0), _sample(2.0, msl=200.0),
        ])
        assert track.points[1].vertical_speed_ms == pytest.approx(-5.0)

    def test_closely_spaced_fixes_do_not_produce_speed(self):
        """Below the minimum interval the delta is GPS jitter, not motion."""
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, lat=30.0), _sample(0.033, lat=30.00001),
        ])
        assert track.points[1].horizontal_speed_ms is None

    def test_falls_back_to_agl_when_msl_absent(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, msl=None, agl=10.0), _sample(2.0, msl=None, agl=20.0),
        ])
        assert track.points[1].vertical_speed_ms == pytest.approx(5.0)


class TestPath:
    def test_full_path(self):
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0, lat=30.0), _sample(1.0, lat=31.0), _sample(2.0, lat=32.0),
        ])
        assert track.full_path() == [(30.0, -97.0), (31.0, -97.0), (32.0, -97.0)]

    def test_path_until_truncates(self):
        """Scrubbing backwards must shorten the trail, not leave it ahead."""
        track = TelemetryTrack.from_dji_samples([
            _sample(0.0), _sample(1.0), _sample(2.0), _sample(3.0),
        ])
        assert len(track.path_until(0.0)) == 1
        assert len(track.path_until(2.0)) == 3
        assert len(track.path_until(99.0)) == 4

    def test_path_until_before_start_is_empty(self):
        track = TelemetryTrack.from_dji_samples([_sample(5.0)])
        assert track.path_until(0.0) == []
