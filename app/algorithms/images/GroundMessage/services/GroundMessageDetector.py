"""Find ground messages: characters laid out from sticks, logs, rocks or cloth.

Pipeline
--------
1. Stroke maps. On an image pyramid, a straight-bar detector compares the
   mean brightness along a short line with the mean along two parallel
   lines either side of it, in eight directions. A stick or a row of rocks
   is brighter (or darker) than both of its flanks; ground texture averages
   out along the line, and an edge or a wide patch of sun or shadow has one
   flank like the line itself. The response is thinned to ridge centrelines
   and thresholded with hysteresis against *local* statistics, so a busy
   tree canopy elsewhere in the frame does not raise the bar for a message
   laid out in a clearing.
2. Glyph candidates. Each connected stroke component of character size is
   measured and scored for character-likeness (GlyphShapeAnalyzer).
3. Cross-scale persistence. Pyramid levels overlap in the sizes they cover, so
   a real character is usually found at an adjacent level too.
4. Messages. Text lines are grown from pairs of neighbouring candidates of
   similar size and stroke width: a line keeps the characters' height and
   baseline consistent and their spacing about one character apart. Light
   and dark candidates may share a line: pale branches read as light strokes
   in shade but as dark strokes in sun, where they cast shadows. A lone
   character can still be reported when its shape is strong.

Characters made of natural material are hard to tell apart from a single
bent branch or a few crossed sticks, so most of the precision comes from
step 4: random clutter rarely lines up as a row of consistent characters.

The module is pure numpy/OpenCV/scikit-image with no Qt dependency.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np

from algorithms.images.GroundMessage.services.GlyphShapeAnalyzer import measure_glyph, score_glyph

POLARITY_DARK = 'dark'
POLARITY_LIGHT = 'light'

# Character sizes (long side, in pyramid-level pixels) one level handles. Each
# level doubles the scale, so adjacent levels overlap and characters near a
# boundary are seen twice.
LEVEL_MIN_SIZE = 20.0
LEVEL_MAX_SIZE = 120.0
MAX_PYRAMID_FACTOR = 32
MIN_LEVEL_DIMENSION = 64

# Straight-bar stroke detector (level pixels). The flank offsets cover strokes
# up to about 12 px wide; wider strokes are found at a coarser level.
BAR_LENGTH = 15
BAR_ORIENTATIONS = 8
FLANK_OFFSETS = (2, 4, 7)

# Hysteresis on the bar response, against its mean and standard deviation in a
# window of a few characters around each pixel, with floors in grey levels.
THRESHOLD_WINDOW = 121
THRESHOLD_STATS_DOWNSCALE = 4
HIGH_SIGMA, LOW_SIGMA = 3.0, 1.0
HIGH_FLOOR, LOW_FLOOR = 10.0, 5.0

# Candidates below this shape score are not considered at all.
MIN_GLYPH_SCORE = 0.35
NON_PERSISTENT_PENALTY = 0.85
# Message score multiplier by number of characters: longer rows of consistent
# characters are much less likely to be chance arrangements of clutter.
COUNT_FACTORS = {2: 0.8, 3: 0.92}
MAX_MESSAGE_LENGTH = 16
SINGLE_MIN_GLYPH_SCORE = 0.9
SINGLE_FACTOR = 0.7
SINGLE_MIN_COMPLEXITY = 1.6
MAX_POINTS_PER_GLYPH = 400
# Neighbouring characters are at most this many character sizes apart.
MAX_NEIGHBOR_DISTANCE = 2.2
SPATIAL_CELL = 128


def _line_kernel(length, angle):
    """Normalised kernel averaging along a centred line at the given angle (radians)."""
    kernel = np.zeros((length, length), np.float32)
    center = (length - 1) / 2.0
    dx, dy = math.cos(angle), math.sin(angle)
    for t in np.linspace(-center, center, length * 4):
        x, y = center + t * dx, center + t * dy
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - x0, y - y0
        for xx, yy, weight in ((x0, y0, (1 - fx) * (1 - fy)), (x0 + 1, y0, fx * (1 - fy)),
                               (x0, y0 + 1, (1 - fx) * fy), (x0 + 1, y0 + 1, fx * fy)):
            if 0 <= xx < length and 0 <= yy < length:
                kernel[yy, xx] += weight
    return kernel / kernel.sum()


def _bar_directions():
    directions = []
    for index in range(BAR_ORIENTATIONS):
        angle = math.pi * index / BAR_ORIENTATIONS
        normal = (-math.sin(angle), math.cos(angle))
        flanks = [(int(round(normal[0] * d)), int(round(normal[1] * d))) for d in FLANK_OFFSETS]
        across = (int(round(normal[0])), int(round(normal[1])))
        directions.append((_line_kernel(BAR_LENGTH, angle), flanks, across))
    return directions


# (line kernel, integer flank offsets, one-pixel step across the bar) per direction.
_BAR_DIRECTIONS = _bar_directions()


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
    return np.ascontiguousarray(img)


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


def _shifted(padded, pad, dx, dy, height, width):
    """View of the unpadded image moved so that result[y, x] = image[y + dy, x + dx]."""
    return padded[pad + dy:pad + dy + height, pad + dx:pad + dx + width]


class _BoxGrid:
    """Uniform-grid index of boxes, so neighbour queries avoid all-pairs scans."""

    def __init__(self, cell=SPATIAL_CELL):
        self.cell = cell
        self.cells = defaultdict(list)

    def _span(self, box, margin):
        c = self.cell
        return (range(int((box[0] - margin) // c), int((box[2] + margin) // c) + 1),
                range(int((box[1] - margin) // c), int((box[3] + margin) // c) + 1))

    def add(self, key, box):
        xs, ys = self._span(box, 0)
        for cx in xs:
            for cy in ys:
                self.cells[(cx, cy)].append(key)

    def query(self, box, margin=0.0):
        """Keys of boxes that may lie within `margin` of this box."""
        found = set()
        xs, ys = self._span(box, margin)
        for cx in xs:
            for cy in ys:
                found.update(self.cells.get((cx, cy), ()))
        return found


def _grid_of(glyphs):
    grid = _BoxGrid()
    for index, glyph in enumerate(glyphs):
        grid.add(index, glyph.box)
    return grid


class GroundMessageDetector:
    """Detects messages spelled out on the ground in aerial images.

    Args:
        min_char_size: Smallest character to look for (long side, pixels of
            the image passed to detect()).
        max_char_size: Largest character to look for.
        polarities: Which strokes to look for: POLARITY_DARK (material darker
            than the ground), POLARITY_LIGHT, or both.
        detect_single_characters: Also report a lone character (an X or Y
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
        candidates = self._dedupe_glyphs(glyphs)
        messages = self._group_messages(candidates)
        if self.detect_single_characters:
            used = {id(g) for m in messages for g in m.glyphs}
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
            for polarity, (response, direction) in self.bar_responses(level_gray).items():
                strokes = self.stroke_mask(response, direction)
                glyphs.extend(self._extract_glyphs(strokes, polarity, level, min_size, max_size))
        return glyphs

    def bar_responses(self, gray):
        """Straight-bar response for each requested polarity.

        For each of BAR_ORIENTATIONS directions, the mean along a BAR_LENGTH
        line through each pixel is compared with the means along the parallel
        lines FLANK_OFFSETS away on either side: a light bar must beat the
        brighter flank, a dark bar must undercut the darker one.

        Returns:
            {polarity: (response, direction)}: uint8 response in grey levels
            and the index of the best direction (uint8) at each pixel.
        """
        height, width = gray.shape
        pad = max(FLANK_OFFSETS) + 1
        best = {p: np.zeros((height, width), np.uint8) for p in self.polarities}
        direction = {p: np.zeros((height, width), np.uint8) for p in self.polarities}
        for index, (kernel, flanks, _) in enumerate(_BAR_DIRECTIONS):
            mean = cv2.filter2D(gray, -1, kernel, borderType=cv2.BORDER_REPLICATE)
            padded = cv2.copyMakeBorder(mean, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
            responses = {p: np.zeros((height, width), np.uint8) for p in self.polarities}
            for dx, dy in flanks:
                side_a = _shifted(padded, pad, dx, dy, height, width)
                side_b = _shifted(padded, pad, -dx, -dy, height, width)
                if POLARITY_LIGHT in responses:
                    bar = cv2.subtract(mean, cv2.max(side_a, side_b))
                    cv2.max(responses[POLARITY_LIGHT], bar, dst=responses[POLARITY_LIGHT])
                if POLARITY_DARK in responses:
                    bar = cv2.subtract(cv2.min(side_a, side_b), mean)
                    cv2.max(responses[POLARITY_DARK], bar, dst=responses[POLARITY_DARK])
            for polarity, response in responses.items():
                better = response > best[polarity]
                best[polarity][better] = response[better]
                direction[polarity][better] = index
        return {p: (best[p], direction[p]) for p in self.polarities}

    @staticmethod
    def local_thresholds(response):
        """Low and high hysteresis thresholds from the response's local mean and spread."""
        height, width = response.shape
        scale = THRESHOLD_STATS_DOWNSCALE
        small_size = (max(1, width // scale), max(1, height // scale))
        window = max(3, (THRESHOLD_WINDOW // scale) | 1)
        r = cv2.resize(response, small_size, interpolation=cv2.INTER_AREA).astype(np.float32)
        r2 = cv2.resize(response.astype(np.uint16) ** 2, small_size, interpolation=cv2.INTER_AREA).astype(np.float32)
        mean = cv2.boxFilter(r, -1, (window, window), borderType=cv2.BORDER_REFLECT)
        mean_sq = cv2.boxFilter(r2, -1, (window, window), borderType=cv2.BORDER_REFLECT)
        std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
        high = np.clip(np.maximum(mean + HIGH_SIGMA * std, HIGH_FLOOR), 0, 255)
        low = np.clip(np.maximum(mean + LOW_SIGMA * std, LOW_FLOOR), 0, 255)
        full = (width, height)
        return (cv2.resize(low, full, interpolation=cv2.INTER_LINEAR).astype(np.uint8),
                cv2.resize(high, full, interpolation=cv2.INTER_LINEAR).astype(np.uint8))

    @classmethod
    def stroke_mask(cls, response, direction):
        """Threshold a bar response into a 0/255 stroke mask.

        Ridge centrelines (maxima across the bar) are kept by hysteresis, so
        a stroke is followed along its length without bleeding sideways into
        neighbouring texture; the kept centrelines are then widened over the
        stroke's own above-threshold pixels.
        """
        height, width = response.shape
        low, high = cls.local_thresholds(response)
        padded = cv2.copyMakeBorder(response, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        ridge = np.zeros((height, width), bool)
        for index, (_, _, (dx, dy)) in enumerate(_BAR_DIRECTIONS):
            here = direction == index
            ridge |= (here & (response >= _shifted(padded, 1, dx, dy, height, width))
                      & (response >= _shifted(padded, 1, -dx, -dy, height, width)))
        above_low = response > low
        weak = (ridge & above_low).astype(np.uint8)
        count, labels = cv2.connectedComponents(weak, connectivity=8)
        keep = np.zeros(count, bool)
        keep[np.unique(labels[(weak > 0) & (response > high)])] = True
        keep[0] = False
        centrelines = keep[labels].astype(np.uint8) * 255
        widened = cv2.dilate(centrelines, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        mask = np.where(above_low, widened, 0).astype(np.uint8)
        cv2.max(mask, centrelines, dst=mask)
        # Close the small gaps between rocks in a row or where sticks nearly meet.
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    # ---------------------------------------------------------------- glyphs

    def _extract_glyphs(self, strokes, polarity, level, min_size, max_size):
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
            region = labels[y:y + h, x:x + w]
            own = region == index
            crop = np.pad(own.astype(np.uint8) * 255, 2)
            features = measure_glyph(crop)
            if features is None or not (min_size * 0.85 <= features['long_side'] <= max_size * 1.25):
                continue
            own_pixels = int(own.sum())
            features['isolation'] = own_pixels / float(own_pixels + np.count_nonzero(region) - own_pixels)
            score = score_glyph(features)
            if score < MIN_GLYPH_SCORE:
                continue
            ys, xs = np.nonzero(crop)
            stride = max(1, len(xs) // MAX_POINTS_PER_GLYPH)
            points = (np.stack([xs[::stride], ys[::stride]], 1).astype(np.float32) + (x - 2, y - 2)) * level
            glyphs.append(GlyphCandidate(
                x0=x * level, y0=y * level, x1=(x + w) * level, y1=(y + h) * level,
                level=level, polarity=polarity, score=score,
                long_side=features['long_side'] * level, stroke_width=features['stroke_width'] * level,
                features=features, level_mask=crop, level_origin=(x - 2, y - 2), points=points))
        return glyphs

    @staticmethod
    def _mark_persistence(glyphs):
        """Flag glyphs also found at an adjacent level (either polarity); penalise the rest."""
        grid = _grid_of(glyphs)
        for glyph in glyphs:
            glyph.persistent = any(
                (other.level == 2 * glyph.level or 2 * other.level == glyph.level)
                and _box_iou(glyph.box, other.box) >= 0.4
                for other in (glyphs[i] for i in grid.query(glyph.box)))
            if not glyph.persistent:
                glyph.score *= NON_PERSISTENT_PENALTY

    @staticmethod
    def _is_composite(glyph, glyphs, grid):
        """Does this candidate contain two or more separate, smaller candidates?

        Closely spaced characters can merge into one component at a coarser
        level, and that merged shape can score as well as the characters do.
        When the separate parts were also found, the parts are the better
        reading.
        """
        parts = [other for other in (glyphs[i] for i in grid.query(glyph.box))
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
        """Keep the best-scoring candidate among overlapping ones, across levels and polarities.

        A pale branch in sun yields a light stroke and the dark stroke of its
        shadow at the same place; either reading of the character will do.
        """
        glyphs = [g for g in glyphs if g.score >= MIN_GLYPH_SCORE]
        grid = _grid_of(glyphs)
        glyphs = [g for g in glyphs if not cls._is_composite(g, glyphs, grid)]
        kept = []
        kept_grid = _BoxGrid()
        for glyph in sorted(glyphs, key=lambda g: -g.score):
            if all(_box_iou(glyph.box, kept[i].box) < iou_threshold for i in kept_grid.query(glyph.box)):
                kept_grid.add(len(kept), glyph.box)
                kept.append(glyph)
        return kept

    # -------------------------------------------------------------- messages

    @staticmethod
    def compatible(a, b):
        """Could glyphs a and b be neighbouring characters of one message?

        Brightness and polarity are deliberately not compared: light and
        shadow often fall across a message, so the same material can look
        pale in one character and dark in the next.
        """
        if not (1 / 1.6 <= a.long_side / max(b.long_side, 1e-6) <= 1.6):
            return False
        if not (1 / 1.8 <= a.stroke_width / max(b.stroke_width, 1e-6) <= 1.8):
            return False
        (ax, ay), (bx, by) = a.center, b.center
        distance = math.hypot(ax - bx, ay - by)
        mean_size = (a.long_side + b.long_side) / 2
        return 0.45 * mean_size <= distance <= MAX_NEIGHBOR_DISTANCE * mean_size

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

    @staticmethod
    def _line_ends(members):
        """Indices (into members) of the first and last glyph along the line."""
        centers = np.array([g.center for g in members], np.float64)
        direction = centers[-1] - centers[0] if len(members) == 2 else \
            np.linalg.svd(centers - centers.mean(0))[2][0]
        along = centers @ direction
        return int(np.argmin(along)), int(np.argmax(along))

    def _grow_line(self, chain, glyphs, neighbors):
        """Extend a two-glyph line at either end while it stays a consistent line.

        Each step adds the best-scoring neighbour of an end glyph that keeps
        line_check satisfied.
        """
        chain = list(chain)
        while len(chain) < MAX_MESSAGE_LENGTH:
            members = [glyphs[k] for k in chain]
            first, last = self._line_ends(members)
            best = None
            for end in {chain[first], chain[last]}:
                for k in neighbors[end]:
                    if k in chain or (best is not None and glyphs[k].score <= glyphs[best].score):
                        continue
                    if self.line_check(members + [glyphs[k]])[0]:
                        best = k
            if best is None:
                break
            chain.append(best)
        return chain

    def _group_messages(self, glyphs):
        """Grow text lines from compatible pairs of glyphs.

        Seeds are tried best pair first. Once a line is built, every pair of
        its glyphs is marked as covered, so the same line is not regrown from
        each of its other pairs.
        """
        grid = _grid_of(glyphs)
        neighbors = [[] for _ in glyphs]
        for i, glyph in enumerate(glyphs):
            for j in grid.query(glyph.box, MAX_NEIGHBOR_DISTANCE * glyph.long_side):
                if j > i and self.compatible(glyph, glyphs[j]):
                    neighbors[i].append(j)
                    neighbors[j].append(i)
        seeds = sorted(((i, j) for i in range(len(glyphs)) for j in neighbors[i] if j > i),
                       key=lambda pair: -(glyphs[pair[0]].score + glyphs[pair[1]].score))
        covered = set()
        lines = {}
        for i, j in seeds:
            if (i, j) in covered:
                continue
            covered.add((i, j))
            if not self.line_check([glyphs[i], glyphs[j]])[0]:
                continue
            chain = self._grow_line((i, j), glyphs, neighbors)
            covered.update((min(a, b), max(a, b)) for a in chain for b in chain if a != b)
            lines.setdefault(frozenset(chain), chain)

        messages = []
        for chain in lines.values():
            members = [glyphs[k] for k in chain]
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
        """Keep longer, then better messages; drop ones sharing a glyph or mostly covered by a kept one."""
        kept = []
        used = set()
        for message in sorted(messages, key=lambda m: (-len(m.glyphs), -m.score)):
            ids = {id(g) for g in message.glyphs}
            if ids & used:
                continue
            if all(_box_containment(message.box, k.box) < 0.5 for k in kept):
                kept.append(message)
                used |= ids
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
