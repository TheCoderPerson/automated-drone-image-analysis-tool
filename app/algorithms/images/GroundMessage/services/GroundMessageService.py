"""ADIAT service for the Ground Message Detector algorithm."""

import math

import cv2

from algorithms.AlgorithmService import AlgorithmService, AnalysisResult
from algorithms.images.GroundMessage.services.GroundMessageDetector import (
    POLARITY_DARK, POLARITY_LIGHT, GroundMessageDetector, paint_message_mask)
from core.services.LoggerService import LoggerService

# Option keys and defaults. Persisted in ADIAT_Data.xml and wizard data, so the
# keys and stable values below must not change.
OPTION_CONFIDENCE = 'confidence_threshold'
OPTION_MIN_CHAR_SIZE = 'min_char_size'
OPTION_MAX_CHAR_SIZE = 'max_char_size'
OPTION_POLARITY = 'stroke_polarity'
OPTION_SINGLE_CHARACTERS = 'detect_single_characters'

POLARITY_BOTH = 'both'
POLARITY_CHOICES = {
    POLARITY_BOTH: (POLARITY_DARK, POLARITY_LIGHT),
    POLARITY_DARK: (POLARITY_DARK,),
    POLARITY_LIGHT: (POLARITY_LIGHT,),
}

DEFAULT_CONFIDENCE = 50
DEFAULT_MIN_CHAR_SIZE = 40
DEFAULT_MAX_CHAR_SIZE = 600
DEFAULT_POLARITY = POLARITY_BOTH
DEFAULT_SINGLE_CHARACTERS = True

SCORE_TYPE = 'character_shape'


def _as_bool(value, default):
    """Read a boolean option that may have round-tripped through XML as text."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def coerce_options(options):
    """Read options leniently: anything missing or unparseable takes its default.

    For restoring UI state from saved settings, where values may have
    round-tripped through XML as strings. Never raises.
    """
    options = dict(options or {})
    defaults = {
        OPTION_CONFIDENCE: DEFAULT_CONFIDENCE,
        OPTION_MIN_CHAR_SIZE: DEFAULT_MIN_CHAR_SIZE,
        OPTION_MAX_CHAR_SIZE: DEFAULT_MAX_CHAR_SIZE,
    }
    values = {}
    for key, default in defaults.items():
        try:
            values[key] = int(round(float(options.get(key, default))))
        except (TypeError, ValueError):
            values[key] = default
    polarity = str(options.get(OPTION_POLARITY, DEFAULT_POLARITY)).strip().lower()
    values[OPTION_POLARITY] = polarity if polarity in POLARITY_CHOICES else DEFAULT_POLARITY
    values[OPTION_SINGLE_CHARACTERS] = _as_bool(options.get(OPTION_SINGLE_CHARACTERS), DEFAULT_SINGLE_CHARACTERS)
    return values


def normalize_options(options):
    """Return a complete, validated options dict with defaults filled in.

    Raises:
        ValueError: If a value is present but unusable (e.g. min >= max size).
    """
    options = dict(options or {})
    confidence = float(options.get(OPTION_CONFIDENCE, DEFAULT_CONFIDENCE))
    min_size = int(round(float(options.get(OPTION_MIN_CHAR_SIZE, DEFAULT_MIN_CHAR_SIZE))))
    max_size = int(round(float(options.get(OPTION_MAX_CHAR_SIZE, DEFAULT_MAX_CHAR_SIZE))))
    polarity = str(options.get(OPTION_POLARITY, DEFAULT_POLARITY)).strip().lower()
    if not 0 <= confidence <= 100:
        raise ValueError(f"{OPTION_CONFIDENCE} must be between 0 and 100, got {confidence}")
    if min_size <= 0 or max_size <= min_size:
        raise ValueError(
            f"Character size range is invalid: {OPTION_MIN_CHAR_SIZE}={min_size}, "
            f"{OPTION_MAX_CHAR_SIZE}={max_size}")
    if polarity not in POLARITY_CHOICES:
        raise ValueError(f"{OPTION_POLARITY} must be one of {sorted(POLARITY_CHOICES)}, got '{polarity}'")
    return {
        OPTION_CONFIDENCE: confidence,
        OPTION_MIN_CHAR_SIZE: min_size,
        OPTION_MAX_CHAR_SIZE: max_size,
        OPTION_POLARITY: polarity,
        OPTION_SINGLE_CHARACTERS: _as_bool(options.get(OPTION_SINGLE_CHARACTERS), DEFAULT_SINGLE_CHARACTERS),
    }


class GroundMessageService(AlgorithmService):
    """Detects letters, numbers and symbols laid out on the ground.

    Searchers in distress sometimes spell a message (SOS, HELP, an X) with
    branches, logs, rocks or clothing. This service looks for rows of
    hand-built, character-shaped strokes and reports each message as an area
    of interest, with a confidence derived from how character-like and how
    consistently aligned the strokes are.

    Character sizes in the options are in pixels of the original image; they
    are converted to the processing resolution set via set_scale_factor().
    """

    def __init__(self, identifier, min_area, max_area, aoi_radius, combine_aois, options):
        """Initialize the service.

        Args:
            identifier: RGB colour used to highlight areas of interest.
            min_area: Minimum area in pixels of one character's strokes.
            max_area: Maximum area in pixels of one character's strokes (0 = no limit).
            aoi_radius: Radius added around each detected character.
            combine_aois: Whether overlapping character AOIs are merged.
            options: Algorithm options (see normalize_options).

        Raises:
            ValueError: If the options are invalid.
        """
        self.logger = LoggerService()
        super().__init__('GroundMessage', identifier, min_area, max_area, aoi_radius, combine_aois, options)
        normalized = normalize_options(options)
        self.confidence_threshold = normalized[OPTION_CONFIDENCE]
        self.min_char_size = normalized[OPTION_MIN_CHAR_SIZE]
        self.max_char_size = normalized[OPTION_MAX_CHAR_SIZE]
        self.stroke_polarity = normalized[OPTION_POLARITY]
        self.detect_single_characters = normalized[OPTION_SINGLE_CHARACTERS]

    def build_detector(self):
        """Detector configured for the current processing resolution."""
        scale = self.scale_factor if self.scale_factor > 0 else 1.0
        return GroundMessageDetector(
            min_char_size=self.min_char_size * scale,
            max_char_size=self.max_char_size * scale,
            polarities=POLARITY_CHOICES[self.stroke_polarity],
            detect_single_characters=self.detect_single_characters,
        )

    def process_image(self, img, full_path, input_dir, output_dir):
        """Find ground messages in one image.

        Args:
            img: Image as a numpy array (BGR, BGRA or greyscale), at processing resolution.
            full_path: Path to the image being analysed.
            input_dir: Base input directory.
            output_dir: Base output directory.

        Returns:
            AnalysisResult with one AOI per message (or per character when
            AOIs are not combined), each carrying a confidence score.
        """
        try:
            detector = self.build_detector()
            messages = detector.detect(img, min_score=self.confidence_threshold / 100.0)
            if not messages:
                return AnalysisResult(full_path, None, output_dir, None, None)

            mask = paint_message_mask(messages, img.shape)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            areas_of_interest, base_contour_count = self.identify_areas_of_interest(img.shape, contours)
            if not areas_of_interest:
                return AnalysisResult(full_path, None, output_dir, None, None)

            self._add_confidence_scores(areas_of_interest, messages)
            output_path = self._construct_output_path(full_path, input_dir, output_dir)
            mask_path = self.store_mask(full_path, output_path, mask)
            return AnalysisResult(full_path, mask_path, output_dir, areas_of_interest, base_contour_count)
        except Exception as e:
            self.logger.error(f"Ground Message Detector failed on {full_path}: {e}")
            return AnalysisResult(full_path, error_message=str(e))

    @staticmethod
    def _add_confidence_scores(areas_of_interest, messages):
        """Give each AOI the score of the best message with a character inside it."""
        for aoi in areas_of_interest:
            ax, ay = aoi['center']
            reach = aoi['radius']
            best = None
            nearest, nearest_distance = None, float('inf')
            for message in messages:
                for glyph in message.glyphs:
                    gx, gy = glyph.center
                    distance = math.hypot(gx - ax, gy - ay)
                    if distance <= reach and (best is None or message.score > best):
                        best = message.score
                    if distance < nearest_distance:
                        nearest, nearest_distance = message.score, distance
            score = best if best is not None else (nearest if nearest is not None else 0.0)
            aoi['confidence'] = round(score * 100.0, 1)
            aoi['score_type'] = SCORE_TYPE
            aoi['raw_score'] = round(float(score), 3)
            aoi['score_method'] = 'max'
