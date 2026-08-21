"""Tests for the per-flight altitude anchor.

The model: a SAR mission folder holds several flights by several pilots
from several launch sites, so the estimated constant — the takeoff
elevation — is resolved per *flight segment* (aircraft serial + capture
time gaps), never per mission. Within a segment, camera = anchor + ATO.

Anchoring evidence, strongest first:
* a near-ground frame (datum never enters the arithmetic);
* the baro datum test — DJI slaves recorded altitude to the barometer
  (measured: spread exactly 0.0 over 238 real frames), so
  ``median(GPSAltitude − ATO)`` is the firmware's takeoff estimate and the
  datum question is a binary choice that overflown ground settles.

All numbers in the field-case tests are DJI_0064's: ATO 46.0 m, ground
307.2 m, GPSAltitude 358.1 m, geoid −26.6 m, surveyed launch 310.9 m. The
raw constant is 312.1 m — within 1.2 m of survey; the geoid-corrected one
(338.7 m) was the 254 ft error.

No files, no network (CLAUDE.md §3.3): frames and terrain are synthetic.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.services.image import AltitudeAnchorService as registry
from core.services.image.AltitudeAnchorService import (
    ANCHOR_SOURCE_DATUM_TEST,
    ANCHOR_SOURCE_GPS_ENSEMBLE,
    ANCHOR_SOURCE_NEAR_GROUND,
    MISSION_SEGMENT_GAP_S,
    NEAR_GROUND_ATO_M,
    REASON_DATUM_UNRESOLVED,
    REASON_IMPLAUSIBLE,
    REASON_INCOHERENT,
    REASON_INSUFFICIENT,
    AltitudeAnchor,
    AltitudeAnchorService,
    clear_mission,
    get_mission_anchor,
    mission_anchor_elevation,
    set_mission_images,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """The mission registry is module state; never leak between tests."""
    clear_mission()
    yield
    clear_mission()


class FakeTerrain:
    """Point elevations from a dict, one geoid value, call counting."""

    def __init__(self, elevations=None, default_elev=307.2, undulation=-26.6):
        self.elevations = elevations or {}
        self.default_elev = default_elev
        self.undulation = undulation
        self.elevation_calls = []
        self.geoid_calls = []

    def get_elevation(self, lat, lon, offline_only=False):
        self.elevation_calls.append((lat, lon, offline_only))
        elev = self.elevations.get((round(lat, 4), round(lon, 4)), self.default_elev)
        return SimpleNamespace(source='terrain', elevation_m=elev)

    def get_geoid_undulation(self, lat, lon, offline_only=False):
        self.geoid_calls.append((lat, lon))
        return self.undulation


def _fg(lat=30.6535, lon=-97.9536, agl=46.0, asl=358.1):
    return SimpleNamespace(lat=lat, lon=lon, agl_m=agl, asl_alt_m=asl)


def _service(frames, terrain=None, **kwargs):
    """A resolver whose frame reader is the given synthetic list."""
    frames = list(frames)
    reader = MagicMock(side_effect=lambda image: frames[image['i']])
    return AltitudeAnchorService(
        terrain_service=terrain or FakeTerrain(),
        logger=MagicMock(),
        frame_geometry_fn=reader,
        **kwargs,
    ), [{'path': f'img_{i}.jpg', 'i': i} for i in range(len(frames))]


class TestGpsEnsemble:
    """POD's path: strict_datum off, sensor-range plausibility governing."""

    def test_the_median_implied_takeoff_wins(self):
        frames = [_fg(agl=46.0 + i, asl=358.1 + i) for i in range(5)]
        terrain = FakeTerrain(default_elev=330.0)
        service, images = _service(frames, terrain)
        anchor = service.resolve(images)

        assert anchor.resolved
        assert anchor.source == ANCHOR_SOURCE_GPS_ENSEMBLE
        assert anchor.elevation_m == pytest.approx(338.7, abs=0.01)
        assert anchor.spread_m == pytest.approx(0.0, abs=0.01)

    def test_gps_noise_averages_down(self):
        noise = [7.5, -6.0, 2.0, -1.5, 0.0, 5.0, -8.0]
        frames = [_fg(asl=358.1 + n) for n in noise]
        terrain = FakeTerrain(default_elev=330.0)
        service, images = _service(frames, terrain)
        anchor = service.resolve(images)
        assert anchor.resolved
        assert abs(anchor.elevation_m - 338.7) < 3.0

    def test_incoherent_chains_are_refused(self):
        frames = [_fg(asl=358.1 + i * 40.0) for i in range(6)]
        service, images = _service(frames)
        anchor = service.resolve(images)
        assert not anchor.resolved
        assert anchor.reason == REASON_INCOHERENT

    def test_too_few_samples_are_refused(self):
        frames = [_fg(), _fg(asl=None), _fg(asl=None)]
        service, images = _service(frames)
        anchor = service.resolve(images)
        assert not anchor.resolved
        assert anchor.reason == REASON_INSUFFICIENT

    def test_no_readable_frames_is_the_same_bucket(self):
        """POD pinned this reason string before the extraction."""
        service = AltitudeAnchorService(
            terrain_service=FakeTerrain(), logger=MagicMock(),
            frame_geometry_fn=lambda image: None)
        anchor = service.resolve([{'path': 'a.jpg'}])
        assert anchor.reason == REASON_INSUFFICIENT

    def test_an_implausible_anchor_is_refused(self):
        frames = [_fg() for _ in range(5)]
        terrain = FakeTerrain(default_elev=307.2)
        service, images = _service(frames, terrain, max_plausible_agl_m=70.0)
        anchor = service.resolve(images)
        assert not anchor.resolved
        assert anchor.reason == REASON_IMPLAUSIBLE


class TestNearGroundRule:
    def test_a_launch_frame_anchors_datum_free(self):
        launch = (30.6540, -97.9530)
        frames = [SimpleNamespace(lat=launch[0], lon=launch[1], agl_m=3.0,
                                  asl_alt_m=323.6)] + [_fg() for _ in range(4)]
        terrain = FakeTerrain(elevations={(30.654, -97.953): 311.0},
                              default_elev=307.2)
        service, images = _service(frames, terrain)
        anchor = service.resolve(images)

        assert anchor.resolved
        assert anchor.source == ANCHOR_SOURCE_NEAR_GROUND
        assert anchor.elevation_m == pytest.approx(311.0)

    def test_a_cruising_mission_has_no_near_ground_frame(self):
        frames = [_fg(agl=NEAR_GROUND_ATO_M + 5.0 + i) for i in range(5)]
        terrain = FakeTerrain(default_elev=330.0)
        service, images = _service(frames, terrain)
        anchor = service.resolve(images)
        assert anchor.source == ANCHOR_SOURCE_GPS_ENSEMBLE

    def test_overrides_never_inform_the_anchor(self):
        service = AltitudeAnchorService(
            terrain_service=FakeTerrain(), logger=MagicMock(),
            custom_altitude_ft=300.0,
            frame_geometry_fn=lambda image: _fg())
        anchor = service.resolve([{'path': 'a.jpg'} for _ in range(5)])
        assert anchor.reason == REASON_INSUFFICIENT


class TestBaroDatumTest:
    """The strict path: measure the datum instead of assuming one."""

    def _resolve(self, frames, terrain, **kwargs):
        service, images = _service(frames, terrain, strict_datum=True, **kwargs)
        return service.resolve(images)

    def test_the_field_case_resolves_orthometric(self):
        """DJI_0064: raw constant 312.1 sits on overflown ground (307.2);
        the geoid-corrected 338.7 sits 31.5 m above anything flown."""
        frames = [_fg() for _ in range(5)]
        anchor = self._resolve(frames, FakeTerrain(default_elev=307.2))

        assert anchor.resolved
        assert anchor.source == ANCHOR_SOURCE_DATUM_TEST
        assert anchor.elevation_m == pytest.approx(312.1, abs=0.01)
        # And the AGL it yields is the surveyed one, not the 254 ft error.
        agl = anchor.elevation_m + 46.0 - 307.2
        assert agl == pytest.approx(50.9, abs=0.1)      # ~167 ft

    def test_an_ellipsoidal_recorder_resolves_ellipsoidal(self):
        """SRT-style: recorded altitude ellipsoidal, per video.csv.

        Ground truly at 338.7: the corrected candidate lands on it and the
        raw one is 26.6 m below anything flown.
        """
        frames = [_fg() for _ in range(5)]
        anchor = self._resolve(frames, FakeTerrain(default_elev=338.7))

        assert anchor.resolved
        assert anchor.source == ANCHOR_SOURCE_DATUM_TEST
        assert anchor.elevation_m == pytest.approx(338.7, abs=0.01)

    def test_relief_matching_both_candidates_refuses(self):
        """Ground at both elevations: the test cannot know which launch."""
        frames = [_fg(lat=30.6535), _fg(lat=30.6600), _fg(lat=30.6535),
                  _fg(lat=30.6600), _fg(lat=30.6535)]
        terrain = FakeTerrain(elevations={(30.66, -97.9536): 338.0},
                              default_elev=312.0)
        anchor = self._resolve(frames, terrain)
        assert not anchor.resolved
        assert anchor.reason == REASON_DATUM_UNRESOLVED

    def test_a_valley_launch_outside_the_flight_refuses(self):
        """Neither candidate near overflown ground -> no coin flip."""
        frames = [_fg() for _ in range(5)]
        anchor = self._resolve(frames, FakeTerrain(default_elev=290.0))
        assert not anchor.resolved
        assert anchor.reason == REASON_DATUM_UNRESOLVED

    def test_a_small_undulation_refuses(self):
        """Candidates closer than ground can separate: refuse, cheaply.

        The fallback's error is bounded by the same small separation.
        """
        frames = [_fg() for _ in range(5)]
        terrain = FakeTerrain(default_elev=307.2, undulation=-8.0)
        anchor = self._resolve(frames, terrain)
        assert not anchor.resolved
        assert anchor.reason == REASON_DATUM_UNRESOLVED

    def test_an_unslaved_recorder_refuses(self):
        """Spread means the altitude is not baro-slaved; the constant is
        not a takeoff estimate and must not be used as one."""
        frames = [_fg(asl=358.1 + i * 40.0) for i in range(6)]
        anchor = self._resolve(frames, FakeTerrain(default_elev=307.2))
        assert not anchor.resolved
        assert anchor.reason == REASON_INCOHERENT

    def test_no_geoid_data_refuses(self):
        """Without the undulation there is no second candidate to test."""
        frames = [_fg() for _ in range(5)]
        terrain = FakeTerrain(default_elev=307.2, undulation=None)
        anchor = self._resolve(frames, terrain)
        assert not anchor.resolved
        assert anchor.reason == REASON_DATUM_UNRESOLVED

    def test_a_near_ground_frame_outranks_the_datum_test(self):
        launch = (30.6540, -97.9530)
        frames = [SimpleNamespace(lat=launch[0], lon=launch[1], agl_m=3.0,
                                  asl_alt_m=None)] + [_fg() for _ in range(4)]
        terrain = FakeTerrain(elevations={(30.654, -97.953): 311.0},
                              default_elev=307.2)
        anchor = self._resolve(frames, terrain)
        assert anchor.source == ANCHOR_SOURCE_NEAR_GROUND


class TestSegmentation:
    """A SAR folder is many flights; the constant holds per flight."""

    T0 = datetime(2026, 8, 20, 10, 0, 0)

    def _meta(self, table):
        return lambda image: table[image['path']]

    def test_a_time_gap_starts_a_new_flight(self):
        table = {
            'a.jpg': ('SN1', self.T0),
            'b.jpg': ('SN1', self.T0 + timedelta(seconds=120)),
            'c.jpg': ('SN1', self.T0 + timedelta(seconds=MISSION_SEGMENT_GAP_S + 200)),
        }
        images = [{'path': p} for p in table]
        segments = AltitudeAnchorService.segment_mission(
            images, metadata_fn=self._meta(table))
        assert [[im['path'] for im in seg] for seg in segments] == [
            ['a.jpg', 'b.jpg'], ['c.jpg']]

    def test_simultaneous_pilots_are_split_by_serial(self):
        """Two aircraft interleave in capture time; time alone would merge
        them into one impossible flight."""
        table = {
            'a1.jpg': ('SN1', self.T0),
            'b1.jpg': ('SN2', self.T0 + timedelta(seconds=10)),
            'a2.jpg': ('SN1', self.T0 + timedelta(seconds=20)),
            'b2.jpg': ('SN2', self.T0 + timedelta(seconds=30)),
        }
        images = [{'path': p} for p in table]
        segments = AltitudeAnchorService.segment_mission(
            images, metadata_fn=self._meta(table))
        grouped = sorted([sorted(im['path'] for im in seg) for seg in segments])
        assert grouped == [['a1.jpg', 'a2.jpg'], ['b1.jpg', 'b2.jpg']]

    def test_unreadable_metadata_isolates_the_image(self):
        """No serial and no timestamp: the image can borrow no flight's
        launch site, so it anchors nothing and falls back."""
        table = {'a.jpg': ('SN1', self.T0), 'b.jpg': (None, None)}
        images = [{'path': p} for p in table]
        segments = AltitudeAnchorService.segment_mission(
            images, metadata_fn=self._meta(table))
        assert sorted(len(seg) for seg in segments) == [1, 1]

    def test_a_quick_battery_swap_merges_harmlessly(self):
        """Same site, sub-gap turnaround: same takeoff elevation anyway."""
        table = {
            'a.jpg': ('SN1', self.T0),
            'b.jpg': ('SN1', self.T0 + timedelta(seconds=MISSION_SEGMENT_GAP_S - 60)),
        }
        images = [{'path': p} for p in table]
        segments = AltitudeAnchorService.segment_mission(
            images, metadata_fn=self._meta(table))
        assert len(segments) == 1


class TestMissionRegistry:
    """Per-flight anchors, addressed by image path."""

    class FakeResolver:
        """Stands in for AltitudeAnchorService inside the registry."""

        calls = []
        anchors = {}
        segments = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def resolve(self, images, offline_only=False):
            type(self).calls.append((tuple(im['path'] for im in images),
                                     offline_only))
            key = images[0]['path']
            return type(self).anchors.get(
                key, AltitudeAnchor(reason=REASON_DATUM_UNRESOLVED))

        @classmethod
        def segment_mission(cls, images, metadata_fn=None):
            if cls.segments is not None:
                return cls.segments
            return [list(images)]

    @pytest.fixture(autouse=True)
    def fake_resolver(self, monkeypatch):
        self.FakeResolver.calls = []
        self.FakeResolver.anchors = {}
        self.FakeResolver.segments = None
        monkeypatch.setattr(registry, 'AltitudeAnchorService', self.FakeResolver)
        yield

    def test_no_mission_means_no_anchor(self):
        assert get_mission_anchor() is None
        assert mission_anchor_elevation() is None

    def test_a_single_flight_resolves_without_a_path(self):
        self.FakeResolver.anchors['a.jpg'] = AltitudeAnchor(
            elevation_m=311.0, source=ANCHOR_SOURCE_NEAR_GROUND)
        set_mission_images([{'path': 'a.jpg'}])
        assert mission_anchor_elevation() == pytest.approx(311.0)
        # Cached: a second ask does not re-resolve.
        assert mission_anchor_elevation() == pytest.approx(311.0)
        assert len(self.FakeResolver.calls) == 1

    def test_one_flights_launch_never_anchors_another(self):
        """The SAR scenario: two flights, one launch frame.

        Flight A (with the launch frame) anchors its own images; flight B's
        resolve nothing and fall back, rather than borrowing A's ground.
        """
        flight_a = [{'path': 'a1.jpg'}, {'path': 'a2.jpg'}]
        flight_b = [{'path': 'b1.jpg'}, {'path': 'b2.jpg'}]
        self.FakeResolver.segments = [flight_a, flight_b]
        self.FakeResolver.anchors['a1.jpg'] = AltitudeAnchor(
            elevation_m=250.0, source=ANCHOR_SOURCE_NEAR_GROUND)
        set_mission_images(flight_a + flight_b)

        assert mission_anchor_elevation(image_path='a2.jpg') == pytest.approx(250.0)
        assert mission_anchor_elevation(image_path='b1.jpg') is None
        # And with several flights, a pathless ask answers nothing.
        assert mission_anchor_elevation() is None

    def test_an_unknown_path_resolves_nothing(self):
        set_mission_images([{'path': 'a.jpg'}])
        assert mission_anchor_elevation(image_path='elsewhere.jpg') is None

    def test_a_new_mission_drops_every_anchor(self):
        self.FakeResolver.anchors['a.jpg'] = AltitudeAnchor(
            elevation_m=311.0, source=ANCHOR_SOURCE_NEAR_GROUND)
        set_mission_images([{'path': 'a.jpg'}])
        mission_anchor_elevation()
        set_mission_images([{'path': 'other.jpg'}])
        assert registry._segment_anchors == {}

    def test_an_offline_failure_is_retried_by_a_full_access_caller(self):
        attempts = []

        class OfflineAware(self.FakeResolver):
            def resolve(self, images, offline_only=False):
                attempts.append(offline_only)
                if offline_only:
                    return AltitudeAnchor(reason=REASON_INSUFFICIENT)
                return AltitudeAnchor(elevation_m=311.0,
                                      source=ANCHOR_SOURCE_NEAR_GROUND)

        with patch.object(registry, 'AltitudeAnchorService', OfflineAware):
            set_mission_images([{'path': 'a.jpg'}])
            assert mission_anchor_elevation(offline_only=True) is None
            assert mission_anchor_elevation(offline_only=True) is None
            assert attempts == [True]
            assert mission_anchor_elevation(offline_only=False) == pytest.approx(311.0)
            assert mission_anchor_elevation(offline_only=True) == pytest.approx(311.0)
            assert attempts == [True, False]

    def test_a_full_access_failure_is_final(self):
        set_mission_images([{'path': 'a.jpg'}])
        assert mission_anchor_elevation(offline_only=False) is None
        assert mission_anchor_elevation(offline_only=False) is None
        assert len(self.FakeResolver.calls) == 1

    def test_the_registry_requires_a_measured_datum(self, monkeypatch):
        captured = {}
        base = self.FakeResolver

        class SpyResolver(base):
            def __init__(self, **kwargs):
                captured.update(kwargs)
                super().__init__(**kwargs)

        monkeypatch.setattr(registry, 'AltitudeAnchorService', SpyResolver)
        set_mission_images([{'path': 'a.jpg'}])
        get_mission_anchor(offline_only=True)
        assert captured.get('strict_datum') is True
