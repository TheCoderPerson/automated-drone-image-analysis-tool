"""Option model for the SnowTrack algorithm.

Pure Python (no OpenCV/SciPy) so the controllers can share the defaults,
presets and parsing rules with the service without loading the detection
stack into the GUI process.

Options are stored with stable keys and physical units, never display text:

======================  =========  ==========================================
key                     unit       meaning
======================  =========  ==========================================
gsd_mode                'auto' |   GSD from image metadata (falling back to
                        'manual'   gsd_cm), or always gsd_cm
gsd_cm                  cm/px      fixed / fallback ground sample distance
print_diameter_cm       cm         size of one footprint depression
step_min_cm             cm         shortest accepted mean step length
step_max_cm             cm         longest accepted mean step length
max_trail_width_cm      cm         largest left/right spread of print centers
min_prints              count      fewest detected prints in a reported trail
max_step_variation      percent    largest coefficient of variation of steps
sensitivity             1-10       how faint a print may be
======================  =========  ==========================================
"""

import math
from dataclasses import dataclass

GSD_MODE_AUTO = 'auto'
GSD_MODE_MANUAL = 'manual'
GSD_MODES = (GSD_MODE_AUTO, GSD_MODE_MANUAL)

TRACK_TYPE_POSTHOLE = 'posthole'
TRACK_TYPE_BOOT = 'boot'

# Gait geometry presets, in centimeters. Step length is the distance between
# consecutive (left -> right) prints; trail width is the lateral spread of
# print centers (the straddle). Postholing in deep snow shortens steps and
# widens the straddle; firm snow lets a walker take longer, narrower steps
# with smaller prints.
TRACK_PRESETS = {
    TRACK_TYPE_POSTHOLE: {
        'print_diameter_cm': 30.0,
        'step_min_cm': 35.0,
        'step_max_cm': 90.0,
        'max_trail_width_cm': 50.0,
    },
    TRACK_TYPE_BOOT: {
        'print_diameter_cm': 20.0,
        'step_min_cm': 50.0,
        'step_max_cm': 100.0,
        'max_trail_width_cm': 40.0,
    },
}

DEFAULT_OPTIONS = {
    'gsd_mode': GSD_MODE_AUTO,
    'gsd_cm': 8.0,
    **TRACK_PRESETS[TRACK_TYPE_POSTHOLE],
    'min_prints': 6,
    'max_step_variation': 35,
    'sensitivity': 5,
}

# Accepted range of every numeric option. Out-of-range values are clamped, so
# a hand-edited or legacy options dictionary can never crash the service.
OPTION_LIMITS = {
    'gsd_cm': (0.5, 50.0),
    'print_diameter_cm': (5.0, 100.0),
    'step_min_cm': (10.0, 300.0),
    'step_max_cm': (10.0, 300.0),
    'max_trail_width_cm': (5.0, 200.0),
    'min_prints': (3, 50),
    'max_step_variation': (5, 100),
    'sensitivity': (1, 10),
}


def _as_int(value):
    """int() that also accepts numeric strings such as '6' or '6.0'."""
    return int(round(float(value)))


def _clamped(options, key, cast):
    """Read one numeric option, falling back to the default and clamping to its limits."""
    lo, hi = OPTION_LIMITS[key]
    try:
        value = cast(options.get(key, DEFAULT_OPTIONS[key]))
    except (TypeError, ValueError, OverflowError):
        value = cast(DEFAULT_OPTIONS[key])
    if isinstance(value, float) and not math.isfinite(value):
        value = cast(DEFAULT_OPTIONS[key])
    return min(hi, max(lo, value))


@dataclass(frozen=True)
class SnowTrackParams:
    """Validated, physically expressed algorithm options."""

    gsd_mode: str
    gsd_cm: float
    print_diameter_cm: float
    step_min_cm: float
    step_max_cm: float
    max_trail_width_cm: float
    min_prints: int
    max_step_variation: float  # fraction, e.g. 0.35
    sensitivity: int

    @classmethod
    def from_options(cls, options):
        """Build parameters from an options dictionary, tolerating missing or malformed keys.

        Args:
            options (dict): Algorithm options as produced by the controllers.

        Returns:
            SnowTrackParams: Normalized parameters.
        """
        options = options if isinstance(options, dict) else {}
        gsd_mode = str(options.get('gsd_mode', DEFAULT_OPTIONS['gsd_mode'])).lower()
        if gsd_mode not in GSD_MODES:
            gsd_mode = DEFAULT_OPTIONS['gsd_mode']
        step_min, step_max = sorted((
            _clamped(options, 'step_min_cm', float),
            _clamped(options, 'step_max_cm', float),
        ))
        return cls(
            gsd_mode=gsd_mode,
            gsd_cm=_clamped(options, 'gsd_cm', float),
            print_diameter_cm=_clamped(options, 'print_diameter_cm', float),
            step_min_cm=step_min,
            step_max_cm=step_max,
            max_trail_width_cm=_clamped(options, 'max_trail_width_cm', float),
            min_prints=_clamped(options, 'min_prints', _as_int),
            max_step_variation=_clamped(options, 'max_step_variation', float) / 100.0,
            sensitivity=_clamped(options, 'sensitivity', _as_int),
        )

    def to_options(self):
        """The service-facing options dictionary for these parameters."""
        return {
            'gsd_mode': self.gsd_mode,
            'gsd_cm': self.gsd_cm,
            'print_diameter_cm': self.print_diameter_cm,
            'step_min_cm': self.step_min_cm,
            'step_max_cm': self.step_max_cm,
            'max_trail_width_cm': self.max_trail_width_cm,
            'min_prints': self.min_prints,
            'max_step_variation': round(self.max_step_variation * 100.0, 6),
            'sensitivity': self.sensitivity,
        }


def closest_track_type(print_diameter_cm):
    """The preset whose print size is nearest a given diameter (for restoring wizard state)."""
    try:
        diameter = float(print_diameter_cm)
    except (TypeError, ValueError):
        return TRACK_TYPE_POSTHOLE
    return min(TRACK_PRESETS, key=lambda name: abs(TRACK_PRESETS[name]['print_diameter_cm'] - diameter))
