"""Tests for DEM-corrected AGL.

Every test mocks :class:`TerrainService` — no network, no tile fetches
(CLAUDE.md §3.3). The worker thread is driven synchronously by calling
``_on_resolved`` directly, so the tests stay deterministic.

The central behaviour under test is the **datum-free anchoring**: AGL is
derived from relative altitude plus a *difference* of DEM samples, never
from ``MSL − terrain``. Measured against the project's DJI test flight,
the naive subtraction reported a hovering aircraft as 0 m AGL because
``abs_alt`` is an ellipsoidal GPS height and the local geoid undulation
is −27 m.
"""

import pytest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from core.services.telemetry.TelemetryEnrichmentService import (
    AGL_SOURCE_REPORTED,
    AGL_SOURCE_TERRAIN,
    TelemetryEnrichmentService,
    _cache_key,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def service():
    """A service whose DEM worker is a mock — no thread, no network.

    Without this the real ``_ElevationWorker`` spins up a live
    ``TerrainService`` and fetches elevation tiles, which would make these
    tests non-deterministic and network-dependent (CLAUDE.md §3.3).
    Tests drive resolution explicitly via ``_on_resolved``.
    """
    svc = TelemetryEnrichmentService()
    svc._worker = MagicMock()
    svc._ensure_worker = MagicMock(return_value=svc._worker)
    # Lookups are dispatched by emitting ``_lookupRequested`` (a *queued*
    # signal is what keeps the blocking DEM fetch off the caller's thread —
    # calling worker.lookup() directly would run it inline). Record the
    # emissions so throttling can be asserted on the real contract.
    svc.lookup_requests = []
    svc._lookupRequested.connect(
        lambda lat, lon: svc.lookup_requests.append((lat, lon))
    )
    yield svc
    svc.cleanup()


def envelope(lat=30.6487, lon=-97.6759, msl=207.0, agl=14.9):
    return {
        "aircraft_latitude": lat,
        "aircraft_longitude": lon,
        "aircraft_altitude_msl_m": msl,
        "aircraft_altitude_agl_m": agl,
    }


def _seed_terrain(service, lat, lon, elevation):
    """Pretend the DEM worker resolved this position."""
    service._cache[_cache_key(lat, lon)] = elevation


class TestPassthrough:
    def test_returns_immediately_with_reported_agl(self, service):
        """The UI thread must never wait on a DEM tile fetch."""
        out = service.enrich(envelope())
        assert out["aircraft_altitude_agl_m"] == pytest.approx(14.9)
        assert out["agl_source"] == AGL_SOURCE_REPORTED

    def test_does_not_mutate_the_input(self, service):
        original = envelope()
        service.enrich(original)
        assert "agl_source" not in original

    def test_non_dict_passes_through(self, service):
        assert service.enrich(None) is None
        assert service.enrich("nope") == "nope"

    def test_missing_coordinates_are_left_alone(self, service):
        out = service.enrich({"aircraft_altitude_agl_m": 10.0})
        assert out["aircraft_altitude_agl_m"] == 10.0
        assert out.get("terrain_elevation_m") is None


class TestPreferences:
    def test_disabled_preference_skips_terrain(self, service):
        with patch(
            "core.services.SettingsService.SettingsService.get_bool_setting",
            return_value=False,
        ):
            out = service.enrich(envelope())
        assert out.get("terrain_elevation_m") is None
        assert out["agl_source"] == AGL_SOURCE_REPORTED

    def test_disabled_preference_issues_no_lookup(self, service):
        with patch(
            "core.services.SettingsService.SettingsService.get_bool_setting",
            return_value=False,
        ):
            service.enrich(envelope())
        assert service._inflight is None


class TestAnchoredCorrection:
    """AGL measured against the terrain under the first fix."""

    def test_flat_terrain_returns_the_reported_value(self, service):
        """Hovering over the takeoff point: correction is a no-op.

        This is the real-flight case that exposed the bug — the naive
        ``MSL − terrain`` gave 0.0 m for an aircraft 14.9 m up.
        """
        lat, lon = 30.6487, -97.6759
        service.enrich(envelope(lat, lon))          # sets the anchor
        _seed_terrain(service, lat, lon, 215.0)     # DEM at the anchor
        out = service.enrich(envelope(lat, lon))

        assert out["agl_source"] == AGL_SOURCE_TERRAIN
        assert out["aircraft_altitude_agl_m"] == pytest.approx(14.9, abs=0.01)
        assert out["terrain_elevation_m"] == pytest.approx(215.0)

    def test_flying_over_lower_ground_increases_agl(self, service):
        """The whole point: terrain drop must add to height above ground."""
        service.enrich(envelope(30.0, -97.0, agl=100.0))
        _seed_terrain(service, 30.0, -97.0, 500.0)   # anchor terrain
        service.enrich(envelope(30.0, -97.0, agl=100.0))

        # Same reported AGL, but now over a valley 200 m lower.
        _seed_terrain(service, 30.1, -97.1, 300.0)
        out = service.enrich(envelope(30.1, -97.1, agl=100.0))

        assert out["aircraft_altitude_agl_m"] == pytest.approx(300.0)
        assert out["agl_source"] == AGL_SOURCE_TERRAIN

    def test_flying_over_higher_ground_decreases_agl(self, service):
        service.enrich(envelope(30.0, -97.0, agl=100.0))
        _seed_terrain(service, 30.0, -97.0, 500.0)
        service.enrich(envelope(30.0, -97.0, agl=100.0))

        _seed_terrain(service, 30.1, -97.1, 560.0)
        out = service.enrich(envelope(30.1, -97.1, agl=100.0))

        assert out["aircraft_altitude_agl_m"] == pytest.approx(40.0)

    def test_climbing_is_tracked(self, service):
        service.enrich(envelope(30.0, -97.0, agl=100.0))
        _seed_terrain(service, 30.0, -97.0, 500.0)
        out = service.enrich(envelope(30.0, -97.0, agl=150.0))
        assert out["aircraft_altitude_agl_m"] == pytest.approx(150.0)

    def test_never_reports_below_ground(self, service):
        """DEM resolution error must not produce a subterranean aircraft."""
        service.enrich(envelope(30.0, -97.0, agl=5.0))
        _seed_terrain(service, 30.0, -97.0, 500.0)
        service.enrich(envelope(30.0, -97.0, agl=5.0))

        _seed_terrain(service, 30.1, -97.1, 600.0)
        out = service.enrich(envelope(30.1, -97.1, agl=5.0))
        assert out["aircraft_altitude_agl_m"] == 0.0

    def test_a_first_fix_without_agl_does_not_poison_the_session(self, service):
        """Telemetry fields are individually nullable on the publisher side.

        Anchoring on the first *positioned* fix latched a null reported AGL
        and silently disabled DEM correction for the whole session; the
        anchor must wait for a fix that actually carries an altitude.
        """
        lat, lon = 30.0, -97.0
        # First envelope has a position but no AGL.
        service.enrich({"aircraft_latitude": lat, "aircraft_longitude": lon,
                        "aircraft_altitude_msl_m": 207.0})
        _seed_terrain(service, lat, lon, 500.0)

        # AGL starts arriving from here on.
        service.enrich(envelope(lat, lon, agl=100.0))
        out = service.enrich(envelope(lat, lon, agl=100.0))

        assert service._anchor_reported_agl == pytest.approx(100.0)
        assert out["agl_source"] == AGL_SOURCE_TERRAIN
        assert out["aircraft_altitude_agl_m"] == pytest.approx(100.0)

    def test_waits_for_the_anchor_elevation(self, service):
        """Until the anchor's terrain is known, the reported value stands."""
        service.enrich(envelope(30.0, -97.0, agl=50.0))
        # Terrain known here, but NOT at the anchor... which is the same
        # point, so seed a different current position instead.
        _seed_terrain(service, 30.5, -97.5, 400.0)
        out = service.enrich(envelope(30.5, -97.5, agl=50.0))
        assert out["agl_source"] == AGL_SOURCE_REPORTED
        assert out["aircraft_altitude_agl_m"] == pytest.approx(50.0)


class TestAbsoluteFallback:
    """No relative altitude: MSL − terrain, via the geoid."""

    def test_applies_the_geoid_undulation(self, service):
        """h_ellipsoidal 207.0 with N = −27.1 is 234.1 MSL, not 207.0.

        Measured on the project's DJI test flight; skipping this step put a
        flying aircraft underground.
        """
        lat, lon = 30.0, -97.0
        service.enrich(envelope(lat, lon, msl=207.0, agl=None))
        # Terrain and undulation are resolved together by the worker. These
        # are the values measured at the real test-flight location.
        service._on_resolved(lat, lon, 215.019, -27.103)
        out = service.enrich(envelope(lat, lon, msl=207.0, agl=None))

        # 207.0 − (−27.103) = 234.103 MSL; − 215.019 terrain = 19.08 AGL.
        assert out["aircraft_altitude_agl_m"] == pytest.approx(19.08, abs=0.01)
        assert out["agl_source"] == AGL_SOURCE_TERRAIN

    def test_without_a_geoid_the_reported_value_is_kept(self, service):
        """Subtracting a raw ellipsoidal height would be worse than nothing."""
        lat, lon = 30.0, -97.0
        service.enrich(envelope(lat, lon, msl=207.0, agl=None))
        service._on_resolved(lat, lon, 215.0, None)   # DEM but no geoid
        out = service.enrich(envelope(lat, lon, msl=207.0, agl=None))

        assert out.get("agl_source") != AGL_SOURCE_TERRAIN
        assert out.get("aircraft_altitude_agl_m") is None


class TestThrottling:
    def test_first_fix_issues_a_lookup(self, service):
        service.enrich(envelope(30.0, -97.0))
        assert len(service.lookup_requests) == 1
        assert service._inflight is not None

    def test_hovering_does_not_re_query(self, service):
        service.enrich(envelope(30.0, -97.0))
        service._on_resolved(30.0, -97.0, 200.0)
        before = len(service.lookup_requests)

        # Same spot again, well inside the movement + interval thresholds.
        service.enrich(envelope(30.0, -97.0))
        assert len(service.lookup_requests) == before

    def test_moving_far_enough_re_queries(self, service):
        service.enrich(envelope(30.0, -97.0))
        service._on_resolved(30.0, -97.0, 200.0)
        before = len(service.lookup_requests)

        service.enrich(envelope(30.01, -97.0))   # ~1.1 km away
        assert len(service.lookup_requests) == before + 1

    def test_only_one_lookup_in_flight(self, service):
        service.enrich(envelope(30.0, -97.0))
        service.enrich(envelope(31.0, -98.0))
        assert len(service.lookup_requests) == 1

    def test_cached_position_needs_no_lookup(self, service):
        _seed_terrain(service, 30.0, -97.0, 200.0)
        service.enrich(envelope(30.0, -97.0))
        assert service.lookup_requests == []

    def test_lookup_is_dispatched_by_signal_not_direct_call(self, service):
        """Regression guard for the UI-thread freeze.

        ``worker.lookup(...)`` executes on the *caller's* thread —
        ``moveToThread`` only reroutes queued signal delivery. Dispatch
        must therefore go through the signal.
        """
        service.enrich(envelope(30.0, -97.0))
        service._worker.lookup.assert_not_called()
        assert service.lookup_requests == [(30.0, -97.0)]


class TestResolution:
    def test_resolved_elevation_is_cached(self, service):
        service.enrich(envelope(30.0, -97.0))
        service._on_resolved(30.0, -97.0, 215.0)
        assert service._cache[_cache_key(30.0, -97.0)] == 215.0

    def test_resolution_re_emits_a_corrected_envelope(self, service):
        emitted = []
        service.envelopeEnriched.connect(emitted.append)

        service.enrich(envelope(30.0, -97.0, agl=50.0))
        service._on_resolved(30.0, -97.0, 400.0)

        assert len(emitted) == 1
        assert emitted[0]["agl_source"] == AGL_SOURCE_TERRAIN

    def test_stale_resolution_is_dropped(self, service):
        """A correction for a position the aircraft has long left is useless."""
        emitted = []
        service.envelopeEnriched.connect(emitted.append)

        service.enrich(envelope(30.0, -97.0))
        service.enrich(envelope(40.0, -100.0))       # far away now
        service._on_resolved(30.0, -97.0, 400.0)     # answer for the old spot

        assert emitted == []

    def test_no_coverage_emits_nothing(self, service):
        emitted = []
        service.envelopeEnriched.connect(emitted.append)
        service.enrich(envelope(30.0, -97.0))
        service._on_resolved(30.0, -97.0, None)
        assert emitted == []

    def test_cache_is_bounded(self, service):
        from core.services.telemetry.TelemetryEnrichmentService import _CACHE_MAX_ENTRIES
        for i in range(_CACHE_MAX_ENTRIES + 50):
            service._on_resolved(30.0 + i * 0.001, -97.0, 200.0)
        assert len(service._cache) <= _CACHE_MAX_ENTRIES


class TestLifecycle:
    def test_reset_clears_the_anchor(self, service):
        service.enrich(envelope(30.0, -97.0, agl=50.0))
        assert service._anchor_position is not None
        service.reset()
        assert service._anchor_position is None
        assert service._anchor_reported_agl is None

    def test_reset_keeps_the_cache(self, service):
        """Terrain doesn't move between sessions."""
        _seed_terrain(service, 30.0, -97.0, 200.0)
        service.reset()
        assert _cache_key(30.0, -97.0) in service._cache

    def test_cleanup_is_idempotent(self, service):
        service.cleanup()
        service.cleanup()


class TestTerrainServiceIsolation:
    """Each worker owns its TerrainService; it is never shared across threads.

    Regression guard for a hard crash: ``TerrainService`` caches a
    ``pyproj.Transformer`` inside its ``GeoidService``, and PROJ contexts
    are thread-affine. Sharing one instance between the Qt main thread and
    the DEM worker faulted the process with an access violation inside
    ``pyproj.transformer.__call__`` the moment playback and a terrain
    lookup overlapped.
    """

    def test_each_worker_builds_its_own(self):
        import sys
        mod = sys.modules["core.services.telemetry.TelemetryEnrichmentService"]

        built = []

        class FakeTerrain:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                built.append(self)

        with patch("core.services.terrain.TerrainService", FakeTerrain):
            first = mod._ElevationWorker()
            second = mod._ElevationWorker()
            a = first._get_terrain_service()
            b = second._get_terrain_service()

        assert a is not b
        assert len(built) == 2

    def test_one_worker_reuses_its_own(self):
        import sys
        mod = sys.modules["core.services.telemetry.TelemetryEnrichmentService"]
        built = []

        class FakeTerrain:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                built.append(self)

        with patch("core.services.terrain.TerrainService", FakeTerrain):
            worker = mod._ElevationWorker()
            assert worker._get_terrain_service() is worker._get_terrain_service()
        assert len(built) == 1

    def test_construction_failure_is_remembered(self):
        import sys
        mod = sys.modules["core.services.telemetry.TelemetryEnrichmentService"]
        attempts = []

        def boom(**_kwargs):
            attempts.append(1)
            raise RuntimeError("no terrain here")

        with patch("core.services.terrain.TerrainService", boom):
            worker = mod._ElevationWorker()
            assert worker._get_terrain_service() is None
            assert worker._get_terrain_service() is None

        # Retried once, then latched off rather than re-raising per fix.
        assert len(attempts) == 1

    def test_geoid_is_disabled_on_the_worker(self):
        """Regression guard for a hard crash.

        ``GeoidService`` mutates global PROJ state and caches a
        thread-affine ``pyproj.Transformer``. Reaching it from the DEM
        worker killed a real playback session with
        ``Windows fatal exception: access violation`` inside
        ``pyproj.transformer.__call__``. The anchored AGL uses differences
        of DEM samples, so the geoid buys nothing here.
        """
        import sys
        mod = sys.modules["core.services.telemetry.TelemetryEnrichmentService"]
        built = []

        class FakeTerrain:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                built.append(self)

        with patch("core.services.terrain.TerrainService", FakeTerrain):
            mod._ElevationWorker()._get_terrain_service()

        assert built[0].kwargs.get("enable_geoid") is False
