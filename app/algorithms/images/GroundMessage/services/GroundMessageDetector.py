"""Find ground messages: characters laid out from sticks, logs, rocks or cloth.

Pipeline
--------
1. Stroke maps. On an image pyramid, a morphological black-hat (dark strokes)
   or top-hat (light strokes) keeps features thinner than a stroke-sized
   element. Texture *inside* objects wider than a stroke (bark on a log, a
   shadow) is subtracted, then the response is hysteresis-thresholded.
2. Glyph candidates. Each connected stroke component of character size is
   measured and scored for character-likeness (GlyphShapeAnalyzer).
3. Cross-scale persistence. Pyramid levels overlap in the sizes they cover, so
   a real character is usually found at an adjacent level too.
4. Messages. Candidates are grouped into text lines: neighbours of similar
   size, stroke width and brightness, evenly spaced, sharing a baseline and
   a height. A lone character can still be reported when its shape is strong.

Characters made of natural material are hard to tell apart from a single
bent branch or a few crossed sticks, so most of the precision comes from
step 4: random clutter rarely lines up as a row of consistent characters.

The module is pure numpy/OpenCV/scikit-image with no Qt dependency.
"""

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.filters import apply_hysteresis_threshold

from algorithms.images.GroundMessage.services.GlyphShapeAnalyzer import measure_glyph, score_glyph

POLARITY_DARK = 'dark'
POLARITY_LIGHT = 'light'

# Character sizes (long side, in pyramid-level pixels) one level handles. Each
# level doubles the scale, so adjacent levels overlap and characters near a
# boundary are seen twice.
LEVEL_MIN_SIZE = 20.0
LEVEL_MAX_SIZE = 120.0
# Widest stroke the per-level black-/top-hat captures, in level pixels.
MAX_STROKE_WIDTH = 12
MAX_PYRAMID_FACTOR = 32
MIN_LEVEL_DIMENSION = 64

# Hysteresis thresholds on the stroke response: robust z-scores, with floors in
# grey levels so near-uniform images do not turn noise into strokes.
HIGH_SIGMA, LOW_SIGMA = 5.0, 2.5
HIGH_FLOOR, LOW_FLOOR = 20.0, 10.0

# Candidates below this shape score are not considered at all.
MIN_GLYPH_SCORE = 0.35
NON_PERSISTENT_PENALTY = 0.85
# Message score multiplier by number of characters: longer rows of consistent
# characters are much less likely to be chance arrangements of clutter.
COUNT_FACTORS = {2: 0.8, 3: 0.92}
SINGLE_MIN_GLYPH_SCORE = 0.9
SINGLE_FACTOR = 0.7
SINGLE_MIN_COMPLEXITY = 1.6
MAX_POINTS_PER_GLYPH = 400


@dataclass
class GlyphCandidate:
    """One character-sized stroke component.

    Coordinates are pixels of the image passed to detect().
    """
    x0: int
    y0: int
    x1: int
    y1: int
    level: int
    polarity: str
    score: float
    long_side: float
    stroke_width: float
    brightness: float
    features: dict
    level_mask: np.ndarray = field(repr=False)
    level_origin: tuple = (0, 0)
    points: np.ndarray = field(default=None, repr=False)
    persistent: bool = False

    @property
    def center(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def box(self):
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class MessageCandidate:
    """One or more glyphs that read as a single message."""
    glyphs: list
    score: float

    @property
    def box(self):
        return (min(g.x0 for g in self.glyphs), min(g.y0 for g in self.glyphs),
                max(g.x1 for g in self.glyphs), max(g.y1 for g in self.glyphs))


def to_gray_u8(img):
    """Convert a BGR/BGRA/grey image of any integer or float depth to 8-bit grey."""
    if img is None or img.size == 0:
        raise ValueError("Empty image")
    if img.ndim == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        elif img.shape[2] == 1:
            img = img[:, :, 0]
        else:
            raise ValueError(f"Unsupported channel count: {img.shape[2]}")
    if img.dtype != np.uint8:
        img = cv2.normalize(img.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def _box_iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _box_containment(a, b):
    """Intersection over the smaller box's area."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / smaller if smaller > 0 else 0.0


def _robust_level(values):
    """Median and MAD-based sigma of a sample."""
    median = float(np.median(values))
    sigma = float(np.median(np.abs(values - median))) * 1.4826
    return median, sigma


class GroundMessageDetector:
    """Detects messages spelled out on the ground in aerial images.

    Args:
        min_char_size: Smallest character to look for (long side, pixels of
            the image passed to detect()).
        max_char_size: Largest character to look for.
        polarities: Which strokes to look for: POLARITY_DARK (material darker
            than the ground), POLARITY_LIGHT, or both.
        detect_single_characters: Also report a lone character (an X or V
            ground-to-air signal) when its shape alone is convincing.
    """

    def __init__(self, min_char_size=40, max_char_size=600, polarities=(POLARITY_DARK, POLARITY_LIGHT),
                 detect_single_characters=True):
        if min_char_size <= 0 or max_char_size <= min_char_size:
            raise ValueError(
                f"Invalid character size range: min={min_char_size}, max={max_char_size}")
        unknown = [p for p in polarities if p not in (POLARITY_DARK, POLARITY_LIGHT)]
        if unknown or not polarities:
            raise ValueError(f"Invalid stroke polarities: {polarities}")
        self.min_char_size = float(min_char_size)
        self.max_char_size = float(max_char_size)
        self.polarities = tuple(polarities)
        self.detect_single_characters = bool(detect_single_characters)

    # ------------------------------------------------------------------ public

    def pyramid_levels(self, height, width):
        """Downscale factors whose character-size window meets the requested range."""
        levels = []
        factor = 1
        while factor <= MAX_PYRAMID_FACTOR:
            covers_range = (LEVEL_MAX_SIZE * factor >= self.min_char_size
                            and LEVEL_MIN_SIZE * factor <= self.max_char_size)
            if covers_range and min(height, width) / factor >= MIN_LEVEL_DIMENSION:
                levels.append(factor)
            factor *= 2
        return levels

    def detect(self, img, min_score=0.0):
        """Find message candidates in an image.

        Args:
            img: BGR, BGRA or greyscale image.
            min_score: Discard messages scoring below this (0-1). Applied
                before overlapping messages are merged, so a long but weak
                message cannot hide a shorter, stronger one.

        Returns:
            List of MessageCandidate, best first, scores in [0, 1].
        """
        gray = to_gray_u8(img)
        glyphs = self.find_glyphs(gray)
        self._mark_persistence(glyphs)
        messages = []
        for polarity in self.polarities:
            candidates = self._dedupe_glyphs([g for g in glyphs if g.polarity == polarity])
            grouped = self._group_messages(candidates)
            messages.extend(grouped)
            if self.detect_single_characters:
                used = {id(g) for m in grouped for g in m.glyphs}
                messages.extend(self._single_messages([g for g in candidates if id(g) not in used]))
        return self._dedupe_messages([m for m in messages if m.score >= min_score])

    def find_glyphs(self, gray):
        """Character-like stroke components across all pyramid levels and polarities."""
        height, width = gray.shape
        glyphs = []
        for level in self.pyramid_levels(height, width):
            if level == 1:
                level_gray = gray
            else:
                level_gray = cv2.resize(gray, (width // level, height // level), interpolation=cv2.INTER_AREA)
            min_size = max(LEVEL_MIN_SIZE, self.min_char_size / level)
            max_size = min(LEVEL_MAX_SIZE, self.max_char_size / level)
            for polarity in self.polarities:
                response = self.stroke_response(level_gray, polarity)
                strokes = self.binarize(response)
                glyphs.extend(self._extract_glyphs(level_gray, strokes, polarity, level, min_size, max_size))
        return glyphs

    @staticmethod
    def stroke_response(gray, polarity):
        """Strength of thin dark (black-hat) or light (top-hat) features.

        A black-hat also responds to texture inside an object wider than its
        element (bark on a log, mottling inside a shadow). There, the local
        background (closing at stroke scale) is far darker than the background
        at three times that scale, so that excess is subtracted. Ordinary
        ground texture lifts the same difference a little everywhere, so only
        the part above the image's typical level counts.
        """
        size = 2 * MAX_STROKE_WIDTH + 1
        element = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        height, width = gray.shape
        small = cv2.resize(gray, (max(1, width // 3), max(1, height // 3)), interpolation=cv2.INTER_AREA)
        if polarity == POLARITY_DARK:
            near = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, element)
            far = cv2.morphologyEx(small, cv2.MORPH_CLOSE, element)
            far = cv2.resize(far, (width, height), interpolation=cv2.INTER_LINEAR)
            response = cv2.subtract(near, gray)
            wide = cv2.subtract(far, near)
        else:
            near = cv2.morphologyEx(gray, cv2.MORPH_OPEN, element)
            far = cv2.morphologyEx(small, cv2.MORPH_OPEN, element)
            far = cv2.resize(far, (width, height), interpolation=cv2.INTER_LINEAR)
            response = cv2.subtract(gray, near)
            wide = cv2.subtract(near, far)
        median, sigma = _robust_level(wide[::4, ::4].astype(np.float32))
        allowance = int(min(255, median + 3 * sigma + 5))
        excess = cv2.subtract(wide, np.full_like(wide, allowance))
        response = cv2.subtract(response, excess)
        return cv2.GaussianBlur(response, (3, 3), 0)

    @staticmethod
    def binarize(response):
        """Hysteresis-threshold a stroke response into a 0/255 stroke mask.

        Small gaps (between rocks in a row, or where two sticks nearly meet)
        are closed so a character stays one component.
        """
        median, sigma = _robust_level(response[::4, ::4].astype(np.float32))
        high = max(HIGH_FLOOR, median + HIGH_SIGMA * sigma)
        low = min(high, max(LOW_FLOOR, median + LOW_SIGMA * sigma))
        mask = apply_hysteresis_threshold(response, low, high).astype(np.uint8) * 255
        gap_closer = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, gap_closer)

    # ---------------------------------------------------------------- glyphs

    def _extract_glyphs(self, level_gray, strokes, polarity, level, min_size, max_size):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(strokes, connectivity=8)
        widths = stats[:, cv2.CC_STAT_WIDTH]
        heights = stats[:, cv2.CC_STAT_HEIGHT]
        areas = stats[:, cv2.CC_STAT_AREA]
        big = np.maximum(widths, heights)
        small = np.minimum(widths, heights)
        # Cheap vectorised screen before the per-component shape analysis.
        # Bounds are loose because the axis-aligned box of a rotated
        # character is up to sqrt(2) larger than the character.
        keep = ((big >= min_size * 0.75) & (big <= max_size * 1.45)
                & (areas <= 0.65 * widths * heights) & (small >= 0.12 * big))
        keep[0] = False
        glyphs = []
        for index in np.nonzero(keep)[0]:
            x, y, w, h = (int(v) for v in stats[index, :4])
            crop = np.pad((labels[y:y + h, x:x + w] == index).astype(np.uint8) * 255, 2)
            features = measure_glyph(crop)
            if features is None or not (min_size * 0.85 <= features['long_side'] <= max_size * 1.25):
                continue
            score = score_glyph(features)
            if score < MIN_GLYPH_SCORE:
                continue
            ys, xs = np.nonzero(crop)
            stride = max(1, len(xs) // MAX_POINTS_PER_GLYPH)
            points = (np.stack([xs[::stride], ys[::stride]], 1).astype(np.float32) + (x - 2, y - 2)) * level
            brightness = float(np.median(level_gray[ys + y - 2, xs + x - 2]))
            glyphs.append(GlyphCandidate(
                x0=x * level, y0=y * level, x1=(x + w) * level, y1=(y + h) * level,
                level=level, polarity=polarity, score=score,
                long_side=features['long_side'] * level, stroke_width=features['stroke_width'] * level,
                brightness=brightness, features=features, level_mask=crop, level_origin=(x - 2, y - 2),
                points=points))
        return glyphs

    @staticmethod
    def _mark_persistence(glyphs):
        for glyph in glyphs:
            glyph.persistent = any(
                other.polarity == glyph.polarity
                and (other.level == 2 * glyph.level or 2 * other.level == glyph.level)
                and _box_iou(glyph.box, other.box) >= 0.4
                for other in glyphs)
            if not glyph.persistent:
                glyph.score *= NON_PERSISTENT_PENALTY

    @staticmethod
    def _is_composite(glyph, glyphs):
        """Does this candidate contain two or more separate, smaller candidates?

        Closely spaced characters can merge into one component at a coarser
        level, and that merged shape can score as well as the characters do.
        When the separate parts were also found, the parts are the better
        reading.
        """
        parts = [other for other in glyphs
                 if other is not glyph and other.score >= MIN_GLYPH_SCORE
                 and other.long_side <= 0.75 * glyph.long_side
                 and _box_containment(other.box, glyph.box) >= 0.8]
        for i, first in enumerate(parts):
            for second in parts[i + 1:]:
                if _box_iou(first.box, second.box) < 0.2:
                    return True
        return False

    @classmethod
    def _dedupe_glyphs(cls, glyphs, iou_threshold=0.35):
        """Keep the best-scoring candidate among overlapping ones (one polarity)."""
        glyphs = [g for g in glyphs if not cls._is_composite(g, glyphs)]
        kept = []
        for glyph in sorted(glyphs, key=lambda g: -g.score):
            if glyph.score >= MIN_GLYPH_SCORE and all(_box_iou(glyph.box, k.box) < iou_threshold for k in kept):
                kept.append(glyph)
        return kept

    # -------------------------------------------------------------- messages

    @staticmethod
    def compatible(a, b):
        """Could glyphs a and b be neighbouring characters of one message?"""
        if a.polarity != b.polarity:
            return False
        if not (1 / 1.6 <= a.long_side / max(b.long_side, 1e-6) <= 1.6):
            return False
        if not (1 / 1.8 <= a.stroke_width / max(b.stroke_width, 1e-6) <= 1.8):
            return False
        (ax, ay), (bx, by) = a.center, b.center
        distance = math.hypot(ax - bx, ay - by)
        mean_size = (a.long_side + b.long_side) / 2
        if not (0.45 * mean_size <= distance <= 2.2 * mean_size):
            return False
        # Characters of one message are made of the same kind of material.
        return abs(a.brightness - b.brightness) <= max(30.0, 0.3 * max(a.brightness, b.brightness))

    @staticmethod
    def line_check(glyphs):
        """Do these glyphs read as one line of text?

        Measures each glyph's extent across the line through the glyph
        centres: characters share a height and a baseline, sit close to the
        line, and are spaced roughly one character apart.

        Returns:
            (is_line, index_of_worst_glyph)
        """
        centers = np.array([g.center for g in glyphs], np.float64)
        mean = centers.mean(0)
        if len(glyphs) == 2:
            direction = centers[1] - centers[0]
        else:
            _, _, vt = np.linalg.svd(centers - mean)
            direction = vt[0]
        direction = direction / (np.linalg.norm(direction) + 1e-9)
        normal = np.array([-direction[1], direction[0]])

        extents, mids = [], []
        for glyph in glyphs:
            across = glyph.points @ normal
            low, high = np.percentile(across, [3, 97])
            extents.append(high - low)
            mids.append((high + low) / 2)
        extents, mids = np.array(extents), np.array(mids)
        height = float(np.median(extents))
        if height <= 0:
            return False, 0

        along = (centers - mean) @ direction
        order = np.argsort(along)
        gaps = np.diff(along[order])
        if len(gaps):
            if gaps.min() < 0.4 * height:
                k = int(np.argmin(gaps))
                return False, int(order[k] if k == 0 else order[k + 1])
            if gaps.max() > 2.6 * height:
                k = int(np.argmax(gaps))
                return False, int(order[k] if k == 0 else order[k + 1])

        deviation = np.abs(mids - np.median(mids)) / (0.3 * height)                 # baseline
        deviation = np.maximum(deviation, np.abs(np.log(np.maximum(extents, 1e-6) / height)) / math.log(1.45))
        if len(glyphs) >= 3:
            off_line = np.abs((centers - mean) @ normal)
            deviation = np.maximum(deviation, off_line / (0.35 * height))
        worst = int(np.argmax(deviation))
        return bool(deviation.max() <= 1.0), worst

    @classmethod
    def prune_to_line(cls, members):
        """Remove glyphs until the rest read as one line (possibly leaving < 2).

        The line is fitted through every member, so an outlier also drags the
        fit and line_check may blame a good glyph. When one removal makes
        the rest a line, that removal is used (weakest glyph first); only
        otherwise is the glyph with the worst deviation dropped.
        """
        members = list(members)
        while len(members) >= 2:
            is_line, worst = cls.line_check(members)
            if is_line:
                return members
            if len(members) >= 3:
                for index in sorted(range(len(members)), key=lambda i: members[i].score):
                    rest = members[:index] + members[index + 1:]
                    if cls.line_check(rest)[0]:
                        return rest
            members = members[:worst] + members[worst + 1:]
        return members

    def _group_messages(self, glyphs):
        count = len(glyphs)
        parent = list(range(count))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for i in range(count):
            for j in range(i + 1, count):
                if self.compatible(glyphs[i], glyphs[j]):
                    parent[find(i)] = find(j)
        clusters = {}
        for i in range(count):
            clusters.setdefault(find(i), []).append(glyphs[i])

        messages = []
        for members in clusters.values():
            members = self.prune_to_line(members)
            if len(members) >= 2:
                best = sorted((g.score for g in members), reverse=True)[:4]
                score = float(np.mean(best)) * COUNT_FACTORS.get(len(members), 1.0)
                messages.append(MessageCandidate(members, score))
        return messages

    @staticmethod
    def _single_messages(glyphs):
        """Lone characters convincing enough on their own (e.g. an X or Y signal).

        A lone character must have a junction where strokes meet or cross.
        Junction-free shapes are excluded: two-stroke ones (V, L) look like a
        bent stick, and a bare closed loop (O, 0, D) looks like the outline of
        a building, vehicle or tent.
        """
        singles = []
        for glyph in glyphs:
            features = glyph.features
            if (glyph.score >= SINGLE_MIN_GLYPH_SCORE and glyph.persistent
                    and features['complexity'] >= SINGLE_MIN_COMPLEXITY
                    and features['junctions'] >= 1):
                singles.append(MessageCandidate([glyph], glyph.score * SINGLE_FACTOR))
        return singles

    @staticmethod
    def _dedupe_messages(messages):
        """Drop messages mostly covered by a longer or better one (e.g. the other polarity)."""
        kept = []
        for message in sorted(messages, key=lambda m: (-len(m.glyphs), -m.score)):
            if all(_box_containment(message.box, k.box) < 0.5 for k in kept):
                kept.append(message)
        return sorted(kept, key=lambda m: -m.score)


def paint_message_mask(messages, shape):
    """Rasterise the strokes of the given messages into a 0/255 mask.

    Args:
        messages: MessageCandidate list from GroundMessageDetector.detect().
        shape: (height, width) of the image passed to detect().
    """
    height, width = shape[:2]
    mask = np.zeros((height, width), np.uint8)
    for message in messages:
        for glyph in message.glyphs:
            level = glyph.level
            crop = glyph.level_mask
            if level != 1:
                crop = cv2.resize(crop, (crop.shape[1] * level, crop.shape[0] * level),
                                  interpolation=cv2.INTER_NEAREST)
            x0 = glyph.level_origin[0] * level
            y0 = glyph.level_origin[1] * level
            # Clip the (padded) crop to the image.
            cx0, cy0 = max(0, -x0), max(0, -y0)
            x0c, y0c = max(0, x0), max(0, y0)
            x1c = min(width, x0 + crop.shape[1])
            y1c = min(height, y0 + crop.shape[0])
            if x1c <= x0c or y1c <= y0c:
                continue
            region = crop[cy0:cy0 + (y1c - y0c), cx0:cx0 + (x1c - x0c)]
            np.maximum(mask[y0c:y1c, x0c:x1c], region, out=mask[y0c:y1c, x0c:x1c])
    return mask
