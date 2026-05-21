"""ShadowDescriptor - the per-AOI shadow measurement and the match test.

A ShadowDescriptor records what shadow was measured beside an AOI, with no
assumption about the subject being searched for. ShadowMatcher produces it
once at analysis time; shadow_matches() tests it against a specific subject
height, posture set and tolerance. Keeping the measurement subject-independent
lets the viewer re-test instantly as the operator changes the search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple


# Descriptor status values.
STATUS_OK = 'ok'                      # a shadow was measured and is usable
STATUS_NO_SHADOW = 'no_shadow'        # no shadow found along the anti-solar ray
STATUS_UNMEASURABLE = 'unmeasurable'  # could not measure (metadata/geometry)

# Vertical extent of a person's shadow-casting form as a fraction of standing
# height, per posture. Standing is the full height; sitting is the seated
# head-top (PersonModel: torso 0.40 + head 0.135); lying is the body-slab
# thickness (PersonReferenceDialog.RECUMBENT_THICKNESS_FRACTION).
POSTURE_HEIGHT_FRACTION = {
    'standing': 1.0,
    'sitting': 0.53,
    'lying': 0.12,
}


@dataclass
class ShadowDescriptor:
    """A subject-independent shadow measurement for one AOI.

    Attributes:
        status: one of STATUS_OK / STATUS_NO_SHADOW / STATUS_UNMEASURABLE.
        implied_height_m: vertical extent implied by the shadow, metres
            (None unless status is 'ok').
        sigma_m: 1-sigma uncertainty on implied_height_m, metres.
        azimuth_residual_deg: measured shadow direction minus the expected
            anti-solar direction, degrees.
        shadow_contrast: how much darker the shadow is than the sunlit
            background, 0-1.
        attached: whether the measured shadow touches the AOI.
        sun_elevation_deg, sun_azimuth_deg: sun position for the image.
        detail: human-readable note, set for non-'ok' results.
    """

    status: str = STATUS_UNMEASURABLE
    implied_height_m: Optional[float] = None
    sigma_m: Optional[float] = None
    azimuth_residual_deg: Optional[float] = None
    shadow_contrast: Optional[float] = None
    attached: bool = False
    sun_elevation_deg: Optional[float] = None
    sun_azimuth_deg: Optional[float] = None
    detail: str = ''

    def to_xml_attribs(self) -> Dict[str, str]:
        """Serialise to a dict of 'shadow_'-prefixed XML attribute strings."""
        attribs = {
            'shadow_status': self.status,
            'shadow_attached': str(bool(self.attached)),
        }
        optional = (
            ('shadow_implied_height_m', self.implied_height_m),
            ('shadow_sigma_m', self.sigma_m),
            ('shadow_azimuth_residual_deg', self.azimuth_residual_deg),
            ('shadow_contrast', self.shadow_contrast),
            ('shadow_sun_elevation_deg', self.sun_elevation_deg),
            ('shadow_sun_azimuth_deg', self.sun_azimuth_deg),
        )
        for key, value in optional:
            if value is not None:
                attribs[key] = repr(float(value))
        if self.detail:
            attribs['shadow_detail'] = self.detail
        return attribs

    @classmethod
    def from_xml_attribs(cls, attribs: Dict[str, str]) -> 'ShadowDescriptor':
        """Rebuild a descriptor from 'shadow_'-prefixed XML attributes."""
        def number(key):
            raw = attribs.get(key)
            if raw is None or raw in ('', 'None'):
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        return cls(
            status=attribs.get('shadow_status', STATUS_UNMEASURABLE),
            implied_height_m=number('shadow_implied_height_m'),
            sigma_m=number('shadow_sigma_m'),
            azimuth_residual_deg=number('shadow_azimuth_residual_deg'),
            shadow_contrast=number('shadow_contrast'),
            attached=attribs.get('shadow_attached') == 'True',
            sun_elevation_deg=number('shadow_sun_elevation_deg'),
            sun_azimuth_deg=number('shadow_sun_azimuth_deg'),
            detail=attribs.get('shadow_detail', ''),
        )


def expected_shadow_height(height_m: float, posture: str) -> float:
    """Vertical shadow-casting extent for a standing height in a given posture.

    Raises:
        ValueError: posture is not one of POSTURE_HEIGHT_FRACTION.
    """
    try:
        return height_m * POSTURE_HEIGHT_FRACTION[posture]
    except KeyError:
        raise ValueError(f"Unknown posture: {posture!r}")


def shadow_matches(
    descriptor: ShadowDescriptor,
    height_m: float,
    postures: Iterable[str],
    tolerance_m: float,
    sigma_k: float = 2.0,
    max_azimuth_residual_deg: float = 25.0,
    min_contrast: float = 0.08,
) -> Tuple[bool, float]:
    """Test whether a descriptor is consistent with a given subject.

    Pure arithmetic - safe to call repeatedly as the operator drags the
    height/posture/tolerance controls. The subject matches when the operator's
    height interval [expected +/- tolerance] overlaps the measurement interval
    [implied +/- sigma_k * sigma] for any selected posture, with the shadow
    direction and contrast within their bands.

    Callers handle non-'ok' descriptors themselves (the viewer filter shows
    'unmeasurable' AOIs rather than hiding them); this returns (False, 0.0) for
    anything that is not a usable, attached measurement.

    Args:
        descriptor: the measured ShadowDescriptor.
        height_m: the subject's standing height, metres.
        postures: postures to accept (keys of POSTURE_HEIGHT_FRACTION).
        tolerance_m: +/- search tolerance on the subject height, metres.
        sigma_k: how many sigma of measurement uncertainty to allow.
        max_azimuth_residual_deg: reject shadows whose direction is off the
            expected anti-solar direction by more than this.
        min_contrast: reject shadows fainter than this contrast.

    Returns:
        (matched, score) - score is the best 0-1 fit across the postures,
        for ranking; 0.0 when not matched.
    """
    if descriptor.status != STATUS_OK:
        return (False, 0.0)
    if not descriptor.attached or descriptor.implied_height_m is None:
        return (False, 0.0)

    residual = descriptor.azimuth_residual_deg
    if residual is not None and abs(residual) > max_azimuth_residual_deg:
        return (False, 0.0)
    contrast = descriptor.shadow_contrast
    if contrast is not None and contrast < min_contrast:
        return (False, 0.0)

    implied = descriptor.implied_height_m
    sigma = descriptor.sigma_m or 0.0
    matched = False
    best_score = 0.0
    for posture in postures:
        expected = expected_shadow_height(height_m, posture)
        # Interval overlap between the search window and the measurement.
        low = max(expected - tolerance_m, implied - sigma_k * sigma)
        high = min(expected + tolerance_m, implied + sigma_k * sigma)
        if low <= high:
            matched = True
            error = abs(implied - expected) / max(expected, 1e-6)
            best_score = max(best_score, max(0.0, 1.0 - error))
    return (matched, best_score)
