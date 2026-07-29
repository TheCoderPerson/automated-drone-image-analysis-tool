"""DEM-corrected AGL for live telemetry, off the UI thread.

Drone-reported AGL is relative to the **takeoff point** — DJI's
``rel_alt``, and the equivalent field from ADIAT Flight. Fly from a
ridge into a valley and the reported figure drifts from reality by the
whole terrain delta, which is exactly the situation where a SAR crew
cares most about height above ground.

ADIAT already ships a DEM stack (:mod:`core.services.terrain`) that
image analysis uses for terrain-corrected AOI geolocation. This service
brings the same correction to live telemetry.

**Why not simply ``MSL − terrain``.** DJI's ``abs_alt`` is a GPS height
above the WGS84 *ellipsoid*, not an orthometric MSL height. Measured
against the project's own test flight, the geoid undulation in central
Texas is −27 m: ``abs_alt`` reads 207.0 m where the DEM reports 215.0 m
of terrain, so the naive subtraction yields a *negative* AGL for an
aircraft that was demonstrably 14.9 m up. Applying the correction that
way would be worse than not correcting at all.

Instead the aircraft is anchored to the terrain under its **first fix**,
which is datum-free because it only ever uses *relative* altitude and
*differences* between DEM samples::

    reference_ground = DEM(first fix)
    aircraft_elevation(t) = reference_ground + reported_AGL(t)
    AGL(t) = aircraft_elevation(t) − DEM(lat(t), lon(t))

Over flat ground this returns the reported figure unchanged; flying into
a valley it grows by exactly the terrain drop, which is the whole point
of the correction. This mirrors the takeoff-anchored reasoning in
:meth:`TerrainService.get_effective_altitude_agl`.

When no relative altitude exists at all, the service falls back to
``MSL − terrain`` and converts the height through
:meth:`TerrainService.convert_ellipsoidal_to_orthometric` first, so the
geoid is accounted for rather than ignored.

**The UI thread is never blocked.** A DEM lookup can hit the network for
a tile, and telemetry arrives at ~4 Hz live (or per displayed frame for
file playback), so a synchronous lookup would stutter the video. Instead:

* :meth:`enrich` returns immediately with the reported value, and
* a corrected envelope is emitted later on :attr:`envelopeEnriched`.

Lookups are additionally cached and throttled so a hovering aircraft
produces one tile fetch rather than four per second.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Signal, Slot

from core.services.LoggerService import LoggerService
from core.services.telemetry.TelemetryTrack import haversine_meters

# Cache key resolution: 1e-4 degrees is ~11 m at the equator, comfortably
# finer than the DEM's own ~38 m resolution at the default zoom, so
# rounding costs no accuracy while collapsing a hover into one entry.
_CACHE_PRECISION = 4
_CACHE_MAX_ENTRIES = 4096

# Re-query only after the aircraft has moved this far, or this long has
# passed. Terrain does not change; the aircraft's position does.
DEFAULT_MIN_MOVE_METERS = 15.0
DEFAULT_MIN_INTERVAL_SECONDS = 2.0

AGL_SOURCE_TERRAIN = "terrain"
AGL_SOURCE_REPORTED = "reported"


def _build_terrain_service(logger=None):
    """Construct a :class:`TerrainService` for this module's DEM worker.

    Two deliberate choices, both of which exist to stop the process
    crashing — do not "optimize" either away:

    **1. Geoid support is OFF.** :class:`GeoidService` mutates *global*
    PROJ state (``pyproj.datadir.append_data_dir``,
    ``pyproj.network.set_network_enabled``) and caches a
    ``pyproj.Transformer``. PROJ contexts are thread-affine, so doing
    that from a background thread while the Qt main thread also uses
    PROJ faults hard: a real playback session died with
    ``Windows fatal exception: access violation`` inside
    ``pyproj.transformer.__call__``, reached via
    ``TerrainService.get_elevation`` -> ``GeoidService.get_undulation``.
    The undulation is only carried as metadata on the result, and the
    anchored AGL this service computes uses *differences* of DEM samples
    (``anchor_elev + reported_agl - terrain_here``), so a constant datum
    offset cancels out exactly. Turning the geoid off costs nothing here
    and removes pyproj from the worker thread entirely.

    **2. Not shared between threads.** Each :class:`_ElevationWorker`
    builds its own instance, on its own thread. The duplication is only
    in-memory — the DEM tile cache lives on disk and is still shared.
    """
    try:
        from core.services.terrain import TerrainService
        return TerrainService(enable_geoid=False)
    except Exception as exc:  # noqa: BLE001 - degrade, never crash
        if logger is not None:
            logger.warning(f"Terrain service unavailable for telemetry: {exc}")
        return None


class _ElevationWorker(QObject):
    """Runs blocking DEM lookups on a dedicated thread.

    Owns its own :class:`TerrainService`, built on first use so it lives
    entirely on this worker's thread — see :func:`_build_terrain_service`
    for why sharing one across threads is unsafe.
    """

    # lat, lon, terrain elevation | None, geoid undulation | None. Both are
    # resolved in one trip so the fallback path never needs a second
    # blocking call from the UI thread.
    resolved = Signal(float, float, object, object)

    def __init__(self):
        super().__init__()
        self.logger = LoggerService()
        self._terrain = None
        self._terrain_failed = False

    def _get_terrain_service(self):
        """Build (once) and return this worker's own terrain service.

        Constructed lazily so it is created on the worker thread that will
        use it — see :func:`_build_terrain_service` for why it must not be
        shared. Refreshes the offline floor from preferences on every call,
        mirroring :func:`core.services.image.AOIService._get_terrain_service`,
        so toggling "Offline Only" takes effect mid-flight.
        """
        if self._terrain_failed:
            return None
        if self._terrain is None:
            self._terrain = _build_terrain_service(self.logger)
            if self._terrain is None:
                self._terrain_failed = True
                return None
        try:
            from core.services.SettingsService import SettingsService
            self._terrain.offline_only = SettingsService().get_bool_setting(
                "OfflineOnly", False
            )
        except Exception:  # noqa: BLE001 - leave the existing flag alone
            pass
        return self._terrain

    @Slot(float, float)
    def lookup(self, lat: float, lon: float) -> None:
        """Resolve terrain elevation and geoid undulation for one position.

        Runs on the worker thread. Both values are fetched together and
        cached by the caller, so neither the anchored path nor the
        absolute fallback ever blocks the UI thread later.
        """
        terrain = self._get_terrain_service()
        if terrain is None:
            self.resolved.emit(lat, lon, None, None)
            return

        elevation = None
        undulation = None
        try:
            result = terrain.get_elevation(lat, lon)
            if result is not None and getattr(result, "source", None) == "terrain":
                elevation = result.elevation_m
        except Exception as exc:  # noqa: BLE001 - a DEM miss is not fatal
            self.logger.debug(f"Terrain lookup failed at {lat:.5f},{lon:.5f}: {exc}")

        # No geoid undulation is fetched: the service is built with the
        # geoid disabled to keep pyproj (and its global, thread-affine PROJ
        # state) off this thread. See _build_terrain_service. The anchored
        # AGL path does not need it; the absolute fallback simply stays
        # inactive and the drone-reported AGL stands.
        self.resolved.emit(lat, lon, elevation, undulation)


class TelemetryEnrichmentService(QObject):
    """Augments telemetry envelopes with terrain-corrected AGL.

    Used by both the streaming window and the Flight Viewer so the two
    surfaces agree on what "AGL" means.

    Usage::

        service = TelemetryEnrichmentService()
        service.envelopeEnriched.connect(hud.apply_envelope)
        hud.apply_envelope(service.enrich(envelope))   # immediate, reported
        # ...corrected envelope arrives on envelopeEnriched shortly after
    """

    envelopeEnriched = Signal(dict)
    # Internal: crossing this signal into the worker's thread is what makes
    # the lookup asynchronous. Calling ``worker.lookup(...)`` directly would
    # run the blocking DEM fetch on the *caller's* thread — ``moveToThread``
    # only reroutes queued signal delivery, not plain method calls.
    _lookupRequested = Signal(float, float)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        min_move_meters: float = DEFAULT_MIN_MOVE_METERS,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    ):
        super().__init__(parent)
        self.logger = LoggerService()
        self._min_move = float(min_move_meters)
        self._min_interval = float(min_interval_seconds)

        self._cache: "OrderedDict[Tuple[float, float], Optional[float]]" = OrderedDict()
        self._geoid_cache: "OrderedDict[Tuple[float, float], float]" = OrderedDict()
        self._last_query_pos: Optional[Tuple[float, float]] = None
        self._last_query_time: float = 0.0
        self._inflight: Optional[Tuple[float, float]] = None
        self._last_envelope: Optional[dict] = None

        # Datum-free anchor: the aircraft's elevation implied by the first
        # fix we see (that position's terrain + its reported AGL). Every
        # later AGL is measured against this, so the ellipsoidal-vs-MSL
        # question never enters the arithmetic. See the module docstring.
        self._anchor_position: Optional[Tuple[float, float]] = None
        self._anchor_reported_agl: Optional[float] = None
        self._anchor_elevation: Optional[float] = None

        self._thread: Optional[QThread] = None
        self._worker: Optional[_ElevationWorker] = None
        self._enabled = self._read_preference()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def enrich(self, envelope: dict) -> dict:
        """Return ``envelope`` immediately, scheduling a DEM correction.

        The returned dict always carries a usable AGL — the reported one,
        or a cached terrain-corrected value when we already have the
        elevation for this position. It never waits on the network.
        """
        if not isinstance(envelope, dict):
            return envelope

        enriched = dict(envelope)
        lat = enriched.get("aircraft_latitude")
        lon = enriched.get("aircraft_longitude")

        if enriched.get("agl_source") is None and enriched.get("aircraft_altitude_agl_m") is not None:
            enriched["agl_source"] = AGL_SOURCE_REPORTED

        self._enabled = self._read_preference()
        if not self._enabled or not _is_coord(lat) or not _is_coord(lon):
            self._last_envelope = enriched
            return enriched

        # Anchor on the first fix that carries BOTH a position and a
        # reported AGL. Anchoring on position alone would latch
        # ``_anchor_reported_agl = None`` when the publisher's first
        # envelope omits altitude (every telemetry field is individually
        # nullable), and the anchored path would then be disabled for the
        # rest of the session.
        reported = envelope.get("aircraft_altitude_agl_m")
        if self._anchor_position is None and _is_coord(reported):
            self._anchor_position = (float(lat), float(lon))
            self._anchor_reported_agl = float(reported)

        key = _cache_key(lat, lon)
        if key in self._cache:
            self._apply_elevation(enriched, self._cache[key])
        else:
            self._maybe_request(float(lat), float(lon))

        self._last_envelope = enriched
        return enriched

    def reset(self) -> None:
        """Drop per-session state. Caches are kept — terrain doesn't move."""
        self._last_query_pos = None
        self._last_query_time = 0.0
        self._inflight = None
        self._last_envelope = None
        self._anchor_position = None
        self._anchor_reported_agl = None
        self._anchor_elevation = None

    def cleanup(self) -> None:
        """Stop the worker thread. Safe to call more than once."""
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            if not thread.wait(2000):
                self.logger.warning("Telemetry enrichment thread did not stop within 2s")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _read_preference(self) -> bool:
        try:
            from core.services.SettingsService import SettingsService
            return bool(SettingsService().get_bool_setting("UseTerrainElevation", True))
        except Exception:  # noqa: BLE001 - default to on, matching image analysis
            return True

    def _ensure_worker(self) -> Optional[_ElevationWorker]:
        if self._worker is not None:
            return self._worker
        try:
            thread = QThread()
            worker = _ElevationWorker()
            worker.moveToThread(thread)
            worker.resolved.connect(self._on_resolved)
            # Queued across the thread boundary because the worker lives on
            # ``thread``; this is what actually gets the blocking lookup off
            # the caller's thread.
            self._lookupRequested.connect(worker.lookup)
            thread.start()
            self._thread = thread
            self._worker = worker
            return worker
        except Exception as exc:  # noqa: BLE001 - run without terrain
            self.logger.warning(f"Could not start terrain worker: {exc}")
            return None

    def _maybe_request(self, lat: float, lon: float) -> None:
        """Throttle by movement and time before spending a tile fetch."""
        now = time.monotonic()
        if self._inflight is not None:
            return
        if self._last_query_pos is not None:
            moved = haversine_meters(
                self._last_query_pos[0], self._last_query_pos[1], lat, lon
            )
            if moved < self._min_move and (now - self._last_query_time) < self._min_interval:
                return

        worker = self._ensure_worker()
        if worker is None:
            return

        self._last_query_pos = (lat, lon)
        self._last_query_time = now
        self._inflight = (lat, lon)
        # Emit rather than call: a direct call would execute the blocking
        # DEM fetch here on the UI thread.
        self._lookupRequested.emit(lat, lon)

    @Slot(float, float, object, object)
    def _on_resolved(self, lat: float, lon: float, elevation, undulation=None) -> None:
        """Cache the results and re-emit the latest envelope corrected."""
        self._inflight = None
        key = _cache_key(lat, lon)
        value = float(elevation) if isinstance(elevation, (int, float)) else None
        self._cache[key] = value
        if isinstance(undulation, (int, float)):
            self._geoid_cache[key] = float(undulation)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        while len(self._geoid_cache) > _CACHE_MAX_ENTRIES:
            self._geoid_cache.popitem(last=False)

        if value is None or not isinstance(self._last_envelope, dict):
            return

        # Only re-emit when the aircraft is still near where we queried;
        # otherwise the correction belongs to a stale position.
        current_lat = self._last_envelope.get("aircraft_latitude")
        current_lon = self._last_envelope.get("aircraft_longitude")
        if not _is_coord(current_lat) or not _is_coord(current_lon):
            return
        if haversine_meters(lat, lon, float(current_lat), float(current_lon)) > self._min_move * 2:
            return

        corrected = dict(self._last_envelope)
        if self._apply_elevation(corrected, value):
            self._last_envelope = corrected
            self.envelopeEnriched.emit(corrected)

    def _apply_elevation(self, envelope: dict, elevation) -> bool:
        """Write terrain-derived AGL into ``envelope``. True if changed."""
        if not isinstance(elevation, (int, float)):
            return False

        terrain_here = float(elevation)
        envelope["terrain_elevation_m"] = terrain_here

        # Prefer the anchored path whenever a relative altitude exists. Do
        # NOT fall through to the absolute path when anchoring is merely
        # *not ready yet* — the anchor's own terrain lands a moment later,
        # and until then the drone-reported figure is the better answer
        # than a geoid-converted absolute height.
        if _is_coord(envelope.get("aircraft_altitude_agl_m")):
            agl = self._anchored_agl(envelope, terrain_here)
        else:
            agl = self._absolute_agl(envelope, terrain_here)
        if agl is None:
            return False

        # An aircraft cannot be below ground; a small negative is DEM
        # resolution error (AWS Terrain tiles are ~30 m), not a
        # subterranean drone.
        envelope["aircraft_altitude_agl_m"] = max(0.0, agl)
        envelope["agl_source"] = AGL_SOURCE_TERRAIN
        return True

    def _anchored_agl(self, envelope: dict, terrain_here: float) -> Optional[float]:
        """Preferred path: measure against the first fix's terrain.

        Uses only relative altitude and a *difference* of DEM samples, so
        it is immune to whether the aircraft reports ellipsoidal or
        orthometric height. Returns None until the anchor's own terrain
        elevation is known.
        """
        reported = envelope.get("aircraft_altitude_agl_m")
        if not _is_coord(reported) or self._anchor_reported_agl is None:
            return None

        if self._anchor_elevation is None:
            anchor = self._anchor_position
            if anchor is None:
                return None
            cached = self._cache.get(_cache_key(anchor[0], anchor[1]))
            if cached is None:
                # Anchor terrain not resolved yet — a later envelope will
                # pick it up once the lookup lands.
                return None
            self._anchor_elevation = float(cached)

        # Aircraft's true elevation, anchored at the first fix.
        aircraft_elevation = self._anchor_elevation + float(self._anchor_reported_agl)
        # ...advanced by however much the aircraft has climbed since then.
        aircraft_elevation += float(reported) - float(self._anchor_reported_agl)
        return aircraft_elevation - terrain_here

    def _absolute_agl(self, envelope: dict, terrain_here: float) -> Optional[float]:
        """Fallback when no relative altitude exists: MSL − terrain.

        The reported height is GPS-derived and therefore ellipsoidal, so
        the geoid undulation is applied first — skipping that step
        introduces the full undulation as error (−27 m in central Texas,
        enough to report a flying aircraft as underground).

        Uses only the cached undulation resolved alongside the terrain
        sample, so this never blocks.
        """
        msl = envelope.get("aircraft_altitude_msl_m")
        if not _is_coord(msl):
            return None
        lat = envelope.get("aircraft_latitude")
        lon = envelope.get("aircraft_longitude")
        if not _is_coord(lat) or not _is_coord(lon):
            return None

        undulation = self._geoid_cache.get(_cache_key(lat, lon))
        if undulation is None:
            # No geoid data for this spot; correcting with a raw
            # ellipsoidal height would be worse than leaving the
            # reported value alone.
            return None
        # h_ellipsoidal = H_orthometric + N  =>  H = h - N
        orthometric = float(msl) - float(undulation)
        return orthometric - terrain_here


def _cache_key(lat, lon) -> Tuple[float, float]:
    return (round(float(lat), _CACHE_PRECISION), round(float(lon), _CACHE_PRECISION))


def _is_coord(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
