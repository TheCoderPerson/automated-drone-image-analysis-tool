"""
RoundPresets.py - target presets and option defaults for RoundShape.

Shared by the service and both controllers so the option keys, their defaults
and the preset sizes are defined exactly once. Preset ids and option keys are
persisted in ADIAT_Data.xml and must stay stable; display names live in the
controllers, behind self.tr().

Sizes are top-down diameters: the long diameter is the major axis of the
outline, the short diameter its minor axis. A circle has both equal.
"""

# Stable preset ids, in the order the combo boxes list them.
PRESET_HAT_HELMET = 'hat_helmet'
PRESET_RING_TIRE = 'ring_tire'
PRESET_UMBRELLA = 'umbrella'
PRESET_DOME_TENT = 'dome_tent'
PRESET_CUSTOM = 'custom'

PRESET_IDS = (
    PRESET_HAT_HELMET,
    PRESET_RING_TIRE,
    PRESET_UMBRELLA,
    PRESET_DOME_TENT,
    PRESET_CUSTOM,
)

# Top-down diameter ranges in cm: (long_min, long_max, short_min, short_max).
# Initial values from typical product dimensions; to be tuned with field
# data. 'custom' has no entry - its sizes are whatever the operator set.
PRESET_SIZES_CM = {
    # A bike helmet (27 x 20) up to a wide-brimmed hat or a bucket rim (45).
    PRESET_HAT_HELMET: (22.0, 45.0, 18.0, 40.0),
    # Life rings (60-76), inner tubes and car or light-truck tires lying flat.
    PRESET_RING_TIRE: (55.0, 95.0, 50.0, 95.0),
    # Compact (90) to golf (150) umbrellas, open on the ground.
    PRESET_UMBRELLA: (85.0, 160.0, 80.0, 160.0),
    # Two- to four-person dome tents; the fly makes a rounded footprint.
    PRESET_DOME_TENT: (180.0, 300.0, 140.0, 260.0),
}

# Stable sensitivity ids and the AOI emission threshold each implies.
SENSITIVITY_LOW = 'low'
SENSITIVITY_MEDIUM = 'medium'
SENSITIVITY_HIGH = 'high'
SENSITIVITY_IDS = (SENSITIVITY_LOW, SENSITIVITY_MEDIUM, SENSITIVITY_HIGH)
SENSITIVITY_TO_CONFIDENCE = {
    SENSITIVITY_LOW: 65.0,
    SENSITIVITY_MEDIUM: 50.0,
    SENSITIVITY_HIGH: 35.0,
}

# Every option the service reads, with its default. load_options() and the
# service both fill missing keys from here, so option dicts saved by earlier
# builds stay loadable as keys are added.
DEFAULT_OPTIONS = {
    'target_preset': PRESET_RING_TIRE,
    'long_diameter_cm_min': PRESET_SIZES_CM[PRESET_RING_TIRE][0],
    'long_diameter_cm_max': PRESET_SIZES_CM[PRESET_RING_TIRE][1],
    'short_diameter_cm_min': PRESET_SIZES_CM[PRESET_RING_TIRE][2],
    'short_diameter_cm_max': PRESET_SIZES_CM[PRESET_RING_TIRE][3],
    'size_tolerance': 0.20,
    'angle_tolerance_deg': 15.0,
    'min_edge_contrast': 10.0,
    'min_edge_support': 0.50,
    'detect_arcs': True,
    'min_arc_degrees': 150.0,
    'min_diameter_px': 12,
    'min_confidence': 50.0,
    'max_detections_per_image': 25,
    'fallback_gsd_cm': None,
    'debug_output': False,
}

# Types used to coerce option values read back from ADIAT_Data.xml, which
# stores every value as a string and writes falsy values (0, False, None) as "".
_FLOAT_KEYS = (
    'long_diameter_cm_min', 'long_diameter_cm_max', 'short_diameter_cm_min', 'short_diameter_cm_max',
    'size_tolerance', 'angle_tolerance_deg', 'min_edge_contrast', 'min_edge_support',
    'min_arc_degrees', 'min_confidence',
)
_INT_KEYS = ('min_diameter_px', 'max_detections_per_image')
_BOOL_KEYS = ('detect_arcs', 'debug_output')


def _to_bool(value, default):
    """Interpret a persisted boolean. "" is how the XML writer stores False."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes'):
        return True
    if text in ('false', '0', 'no', ''):
        return False
    return default


def _to_number(value, default, cast):
    """Interpret a persisted number; "" (a saved 0) maps to 0, garbage to the default."""
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == '':
        return cast(0)
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return default


def normalize_options(options):
    """Return a complete, correctly typed options dict.

    Missing keys take their defaults; values are coerced from the strings
    ADIAT_Data.xml round-trips them as. An unknown preset id becomes
    'custom' so the stored sizes are honoured rather than overwritten.

    Args:
        options (dict | None): Options as saved, loaded or produced by a controller.

    Returns:
        dict: A new dict holding every key in DEFAULT_OPTIONS.
    """
    source = options if isinstance(options, dict) else {}
    result = dict(DEFAULT_OPTIONS)
    for key, default in DEFAULT_OPTIONS.items():
        if key not in source:
            continue
        value = source[key]
        if key in _FLOAT_KEYS:
            result[key] = _to_number(value, default, float)
        elif key in _INT_KEYS:
            result[key] = _to_number(value, default, int)
        elif key in _BOOL_KEYS:
            result[key] = _to_bool(value, default)
        elif key == 'fallback_gsd_cm':
            # None, "" and 0 all mean "no fallback".
            fallback = _to_number(value, None, float)
            result[key] = fallback if fallback else None
        elif key == 'target_preset':
            preset = str(value) if value is not None else default
            result[key] = preset if preset in PRESET_IDS else PRESET_CUSTOM
    return result


def apply_preset(options, preset_id):
    """Write a preset's four size bounds into ``options`` (in place).

    'custom' and unknown ids leave the sizes untouched.
    """
    sizes = PRESET_SIZES_CM.get(preset_id)
    options['target_preset'] = preset_id
    if sizes is None:
        return options
    options['long_diameter_cm_min'], options['long_diameter_cm_max'], \
        options['short_diameter_cm_min'], options['short_diameter_cm_max'] = sizes
    return options


CM_PER_INCH = 2.54


def cm_to_display(value_cm, use_inches):
    """Convert a stored size (cm) to the operator's display unit."""
    return value_cm / CM_PER_INCH if use_inches else value_cm


def display_to_cm(value, use_inches):
    """Convert a displayed size back to the stored unit (cm)."""
    return value * CM_PER_INCH if use_inches else value


def size_range_error(long_min, long_max, short_min, short_max):
    """Which size-range rule is broken, as a stable key, or None when valid.

    Keys: 'long_order', 'short_order', 'short_exceeds_long'. Controllers
    turn the key into a translated message; the rules live here once.
    """
    if long_min > long_max:
        return 'long_order'
    if short_min > short_max:
        return 'short_order'
    if short_min > long_min or short_max > long_max:
        return 'short_exceeds_long'
    return None


def sensitivity_for_confidence(min_confidence):
    """Nearest sensitivity id for a stored ``min_confidence``.

    Lets the wizard restore its slider from an options dict that only
    carries the threshold.
    """
    best = SENSITIVITY_MEDIUM
    best_gap = None
    for sensitivity, confidence in SENSITIVITY_TO_CONFIDENCE.items():
        gap = abs(confidence - float(min_confidence))
        if best_gap is None or gap < best_gap:
            best, best_gap = sensitivity, gap
    return best
