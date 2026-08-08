"""ShadowTimeSolver - infer the capture time of day from a traced shadow.

Given the world azimuth a shadow points along (from the shadow caster's
base toward the shadow tip), find the moment on the capture date when the
sun would cast a shadow at exactly that azimuth. A shadow points directly
away from the sun, so the target sun azimuth is the shadow azimuth + 180°.
Through daylight hours the sun's azimuth sweeps (near-)monotonically, so
the inversion is well-posed; the solver still detects and reports the rare
ambiguous geometries (tropics / high latitudes) instead of guessing.

Used by the Person Size Reference tool: tracing a real shadow in the image
recovers the true time of day even when the camera clock is wrong, and the
recovered time drives the sun-based shadow rendering.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from core.services.shadow.SolarPosition import get_solar_position

# Below this sun elevation the shadow direction is treated as unusable:
# the sun is (nearly) set and shadows are indistinct.
MIN_SUN_ELEVATION_DEG = 0.5

# A candidate time only counts as a solution when the sun azimuth gets
# within this many degrees of the target. Larger residuals mean the traced
# direction cannot be produced by the sun that day.
MAX_AZIMUTH_ERROR_DEG = 15.0

# A second daylight minimum within this margin of the best one (and more
# than an hour away) marks the solution as ambiguous.
AMBIGUITY_MARGIN_DEG = 2.0
AMBIGUITY_MIN_SEPARATION_MIN = 60


@dataclass
class ShadowTimeSolution:
    """Result of inverting a traced shadow azimuth to a capture time."""
    utc: datetime               # solved capture moment (UTC, tz-aware)
    sun_elevation_deg: float    # sun elevation at the solved moment
    sun_azimuth_deg: float      # sun azimuth at the solved moment
    azimuth_error_deg: float    # residual |target - achieved| azimuth
    direction_flipped: bool     # matched only with base/tip swapped
    ambiguous: bool             # a second daylight time matched nearly as well


def _circular_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference between two azimuths."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _daylight_samples(lat: float, lon: float, start: datetime,
                      minutes: int, step_min: int) -> List[Tuple[datetime, float, float]]:
    """(time, elevation, azimuth) samples with the sun above the horizon."""
    samples = []
    for m in range(0, minutes + 1, step_min):
        dt = start + timedelta(minutes=m)
        elev, az = get_solar_position(lat, lon, dt)
        if elev >= MIN_SUN_ELEVATION_DEG:
            samples.append((dt, elev, az))
    return samples


def _best_match(samples, target_az):
    """(best_sample, error, ambiguous) for a target sun azimuth, or None."""
    if not samples:
        return None
    errors = [(_circular_diff_deg(az, target_az), dt, elev, az)
              for dt, elev, az in samples]
    errors.sort(key=lambda e: e[0])
    best_err, best_dt, best_elev, best_az = errors[0]
    if best_err > MAX_AZIMUTH_ERROR_DEG:
        return None
    ambiguous = any(
        err <= best_err + AMBIGUITY_MARGIN_DEG
        and abs((dt - best_dt).total_seconds()) > AMBIGUITY_MIN_SEPARATION_MIN * 60
        for err, dt, _elev, _az in errors[1:]
    )
    return (best_dt, best_elev, best_az), best_err, ambiguous


def _refine(lat, lon, coarse_dt, target_az):
    """Sharpen a coarse (1-minute) match with a 5-second local scan."""
    best = None
    for s in range(-90, 91, 5):
        dt = coarse_dt + timedelta(seconds=s)
        elev, az = get_solar_position(lat, lon, dt)
        if elev < MIN_SUN_ELEVATION_DEG:
            continue
        err = _circular_diff_deg(az, target_az)
        if best is None or err < best[0]:
            best = (err, dt, elev, az)
    return best


def solve_time_for_shadow_azimuth(
        lat: float, lon: float, capture_utc: datetime,
        shadow_azimuth_deg: float) -> Optional[ShadowTimeSolution]:
    """Find the time of day whose sun casts a shadow along a given azimuth.

    Args:
        lat, lon: Ground position of the shadow (degrees).
        capture_utc: The claimed capture moment (tz-aware UTC). Only its
            date matters - the scan covers the 24 h centred on it, so a
            camera clock that is hours wrong still resolves onto the
            correct solar day.
        shadow_azimuth_deg: World azimuth the shadow points along, from
            the caster's base toward the shadow tip (0 = north, CW).

    Returns:
        ShadowTimeSolution, or None when no daylight sun position matches
        the traced direction (in either orientation).
    """
    if capture_utc.tzinfo is None:
        raise ValueError("capture_utc must be timezone-aware")

    start = capture_utc - timedelta(hours=12)
    samples = _daylight_samples(lat, lon, start, 24 * 60, 1)

    # The shadow points away from the sun. If the traced direction has no
    # daylight match, try the reverse - users click tip-first often enough
    # that silently failing would be worse than saying "flipped".
    for flipped in (False, True):
        offset = 0.0 if flipped else 180.0
        target_az = (shadow_azimuth_deg + offset) % 360.0
        match = _best_match(samples, target_az)
        if match is None:
            continue
        (coarse_dt, elev, az), err, ambiguous = match
        refined = _refine(lat, lon, coarse_dt, target_az)
        if refined is not None:
            err, coarse_dt, elev, az = refined
        return ShadowTimeSolution(
            utc=coarse_dt,
            sun_elevation_deg=elev,
            sun_azimuth_deg=az,
            azimuth_error_deg=err,
            direction_flipped=flipped,
            ambiguous=ambiguous,
        )
    return None
