"""Shape analysis for a single candidate character ("glyph").

A ground message is built by hand from sticks, logs, rocks or clothing, so
each character is a small set of fairly straight strokes of roughly constant
width. This module turns the binary mask of one connected stroke component
into shape measurements (stroke width, skeleton graph, straight segments) and
scores how character-like that shape is.

Everything here is pure numpy/OpenCV with no Qt or ADIAT dependencies, so it
can be tested in isolation.
"""

import math

import cv2
import numpy as np
from skimage.morphology import skeletonize

_NEIGHBOR_KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32)
_SHIFTS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

# Two straight segments closer in direction than this are one stroke.
_COLLINEAR_DEG = 20.0
# Major strokes within this angle of each other share one orientation.
_ORIENTATION_TOLERANCE_DEG = 22.0


def trapezoid(x, a, b, c, d):
    """Trapezoidal membership: 0 outside (a, d), 1 on [b, c], linear ramps between."""
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    if x <= c:
        return 1.0
    return (d - x) / (d - c)


def piecewise_linear(x, points):
    """Interpolate linearly through (x, y) points, clamping beyond the ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _neighbor_count(skel):
    """Number of 8-connected skeleton neighbours for every skeleton pixel."""
    return cv2.filter2D(skel, cv2.CV_16S, _NEIGHBOR_KERNEL, borderType=cv2.BORDER_CONSTANT) * skel


def _order_branch(coords):
    """Order the pixels of one skeleton branch into a walk.

    Args:
        coords: (N, 2) array of (row, col) pixels forming one branch.

    Returns:
        Tuple (points, is_loop) where points is an (M, 2) float array of
        (row, col) in walk order.
    """
    pixels = {(int(r), int(c)) for r, c in coords}
    if len(pixels) == 1:
        return np.array(list(pixels), np.float32), False

    def neighbours(p):
        return [(p[0] + dr, p[1] + dc) for dr, dc in _SHIFTS if (p[0] + dr, p[1] + dc) in pixels]

    start = next((p for p in sorted(pixels) if len(neighbours(p)) <= 1), None)
    is_loop = start is None
    if is_loop:
        start = min(pixels)
    order = [start]
    seen = {start}
    current = start
    while True:
        candidates = [q for q in neighbours(current) if q not in seen]
        if not candidates:
            break
        # Prefer 4-connected steps so a diagonal shortcut does not skip pixels.
        candidates.sort(key=lambda q: (abs(q[0] - current[0]) + abs(q[1] - current[1]), q))
        current = candidates[0]
        seen.add(current)
        order.append(current)
    return np.array(order, np.float32), is_loop


def analyze_skeleton(skel, spur_length, max_prune_passes=3):
    """Prune short spurs and describe a skeleton as a graph.

    Args:
        skel: uint8 array (0/1), a one-pixel-wide skeleton of one component.
        spur_length: Terminal branches shorter than this (pixels) are removed;
            they come from stroke-edge noise and small twigs, not from the
            character's own strokes.
        max_prune_passes: Upper bound on prune/re-thin iterations.

    Returns:
        dict with 'branches' (list of dicts with 'points' and 'is_loop'),
        'endpoints' and 'junctions' (counts after pruning).
    """
    skel = skel.astype(np.uint8)
    for prune_pass in range(max_prune_passes + 1):
        neighbors = _neighbor_count(skel)
        junction = ((neighbors >= 3) & (skel > 0)).astype(np.uint8)
        endpoint = (neighbors <= 1) & (skel > 0)
        path = ((skel > 0) & (junction == 0)).astype(np.uint8)
        n_branches, branch_labels = cv2.connectedComponents(path, connectivity=8)
        n_junctions, junction_labels = cv2.connectedComponents(junction, connectivity=8)

        # Which junction clusters does each branch touch? Compare the branch
        # label map with the junction label map shifted to each neighbour.
        adjacency = {}
        if n_junctions > 1 and n_branches > 1:
            height, width = skel.shape
            padded = np.pad(junction_labels, 1)
            for dr, dc in _SHIFTS:
                shifted = padded[1 + dr:1 + dr + height, 1 + dc:1 + dc + width]
                touching = (branch_labels > 0) & (shifted > 0)
                if touching.any():
                    pairs = zip(branch_labels[touching].tolist(), shifted[touching].tolist())
                    for branch, junction_id in set(pairs):
                        adjacency.setdefault(branch, set()).add(junction_id)
        has_endpoint = np.zeros(n_branches, bool)
        if n_branches > 1:
            has_endpoint[np.unique(branch_labels[endpoint & (branch_labels > 0)])] = True
        sizes = np.bincount(branch_labels.ravel(), minlength=n_branches)
        if prune_pass == max_prune_passes:
            break
        spurs = [b for b in range(1, n_branches)
                 if has_endpoint[b] and b in adjacency and sizes[b] < spur_length]
        if not spurs:
            break
        skel[np.isin(branch_labels, spurs)] = 0
        # Removing a spur can leave a two-pixel-thick stub at its junction.
        skel = skeletonize(skel > 0).astype(np.uint8)

    rows, cols = np.nonzero(branch_labels)
    labels = branch_labels[rows, cols]
    order = np.argsort(labels, kind='stable')
    rows, cols, labels = rows[order], cols[order], labels[order]
    bounds = np.searchsorted(labels, np.arange(1, n_branches + 1))
    branches = []
    for b in range(1, n_branches):
        span = slice(bounds[b - 1], bounds[b])
        points, is_loop = _order_branch(np.stack([rows[span], cols[span]], 1))
        touched = adjacency.get(b, set())
        # A branch leaving and re-entering the same junction is also a loop.
        is_loop = is_loop or (len(touched) == 1 and not has_endpoint[b] and len(points) > 4)
        branches.append({'points': points, 'is_loop': is_loop, 'junctions': touched})

    # Two junction clusters joined by a very short branch are one physical
    # junction (a thick crossing skeletonizes into two nearby forks).
    parent = list(range(n_junctions))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for branch in branches:
        touched = list(branch['junctions'])
        if len(touched) == 2 and len(branch['points']) < spur_length:
            parent[find(touched[0])] = find(touched[1])
    junction_count = len({find(j) for j in range(1, n_junctions)})
    return {'branches': branches, 'endpoints': int(endpoint.sum()), 'junctions': junction_count}


def _angle_difference(a, b):
    """Smallest difference between two undirected angles in degrees (0-90)."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _unwrap_angle(angle, reference):
    """Shift an undirected angle by multiples of 180 to sit within 90 of reference."""
    while angle - reference > 90:
        angle -= 180
    while reference - angle > 90:
        angle += 180
    return angle


def polyline_segments(points, is_loop, epsilon):
    """Simplify an ordered branch into straight segments.

    Args:
        points: (N, 2) array of (row, col) in walk order.
        is_loop: Whether the branch closes on itself.
        epsilon: Douglas-Peucker tolerance in pixels.

    Returns:
        List of (length, angle_degrees) with angle in [0, 180), consecutive
        near-collinear pieces merged into one segment.
    """
    if len(points) < 2:
        return []
    xy = points[:, ::-1].reshape(-1, 1, 2).astype(np.float32)
    approx = cv2.approxPolyDP(xy, epsilon, is_loop).reshape(-1, 2)
    if is_loop:
        approx = np.vstack([approx, approx[:1]])
    segments = []
    for a, b in zip(approx[:-1], approx[1:]):
        dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        if segments and _angle_difference(segments[-1][1], angle) < _COLLINEAR_DEG:
            prev_len, prev_angle = segments[-1]
            total = prev_len + length
            merged = (prev_angle * prev_len + _unwrap_angle(angle, prev_angle) * length) / total
            segments[-1] = (total, merged % 180.0)
        else:
            segments.append((length, angle))
    return segments


def _count_orientations(angles):
    """Number of distinct stroke directions among the given angles."""
    clusters = []
    for angle in angles:
        if not any(_angle_difference(angle, c) < _ORIENTATION_TOLERANCE_DEG for c in clusters):
            clusters.append(angle)
    return len(clusters)


def measure_glyph(component_mask):
    """Measure the shape of one candidate character.

    Args:
        component_mask: uint8 (0/255) crop containing exactly one connected
            stroke component, padded by at least one background pixel.

    Returns:
        dict of shape measurements, or None if the component has no usable
        skeleton. Lengths are in the mask's own pixels.
    """
    mask = component_mask > 0
    area = int(mask.sum())
    if area == 0:
        return None
    ys, xs = np.nonzero(mask)
    (_, _), (rect_w, rect_h), _ = cv2.minAreaRect(np.stack([xs, ys], 1).astype(np.float32))
    long_side = max(rect_w, rect_h, 1.0)
    short_side = max(min(rect_w, rect_h), 1.0)

    distance = cv2.distanceTransform(component_mask, cv2.DIST_L2, 3)
    skel = skeletonize(mask).astype(np.uint8)
    half_widths = distance[skel > 0]
    if len(half_widths) == 0:
        return None
    stroke_width = max(1.0, 2.0 * float(np.median(half_widths)))
    width_variation = float(np.std(half_widths) / (np.mean(half_widths) + 1e-6))

    spur_length = max(3.0, 1.2 * stroke_width, 0.12 * long_side)
    graph = analyze_skeleton(skel, spur_length)
    epsilon = max(1.5, 0.45 * stroke_width, 0.035 * long_side)
    segments = []
    loops = 0
    for branch in graph['branches']:
        segments.extend(polyline_segments(branch['points'], branch['is_loop'], epsilon))
        loops += int(branch['is_loop'])
    stroke_length = sum(length for length, _ in segments)
    if stroke_length <= 0:
        return None

    lengths = np.array([length for length, _ in segments])
    major = [(length, angle) for length, angle in segments if length >= 0.25 * long_side]
    return {
        'area': area,
        'long_side': float(long_side),
        'short_side': float(short_side),
        'aspect': float(short_side / long_side),
        'fill': float(area / (long_side * short_side)),
        'stroke_width': stroke_width,
        'size_to_stroke': float(long_side / stroke_width),
        'width_variation': width_variation,
        'complexity': float(stroke_length / long_side),
        'endpoints': graph['endpoints'],
        'junctions': graph['junctions'],
        'loops': loops,
        'segments': len(segments),
        'major_strokes': len(major),
        'orientations': _count_orientations([angle for _, angle in major]),
        'straightness': float(lengths[lengths >= 0.15 * long_side].sum() / stroke_length),
    }


# Weighted evidence terms for score_glyph. Each maps a measurement to [0, 1].
# Ranges describe characters built from a handful of straight strokes:
#   size_to_stroke  characters are several stroke-widths tall (blobs are not)
#   complexity      total stroke length / size: ~1 for a lone stick, 1.5-4 for
#                   characters, higher for tangles of vegetation
#   structure       a junction, a closed loop or 3+ major strokes; two-stroke
#                   shapes with no junction (L, V, 7) look like bent sticks
#   fill            strokes cover a modest share of the character's box
#   endpoints/junctions  few free ends and forks after spur pruning
#   straightness    most stroke length lies on long straight segments
#   orientations    strokes run in at least two directions
_SCORE_WEIGHTS = {
    'size_to_stroke': 1.0,
    'complexity': 1.5,
    'structure': 1.0,
    'fill': 1.0,
    'aspect': 0.7,
    'endpoints': 1.0,
    'junctions': 1.0,
    'straightness': 1.0,
    'orientations': 1.0,
    'segments': 0.5,
    'width_variation': 0.6,
}
_ENDPOINT_SCORES = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.7, 6: 0.4, 7: 0.15}
_JUNCTION_SCORES = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.6, 5: 0.3}


def is_structured(features):
    """True when a shape has more than the two strokes of a bent stick."""
    return features['junctions'] >= 1 or features['loops'] >= 1 or features['major_strokes'] >= 3


def glyph_evidence(features):
    """Per-term evidence in [0, 1] that a shape is a hand-built character."""
    return {
        'size_to_stroke': trapezoid(features['size_to_stroke'], 3.0, 5.0, 30.0, 45.0),
        'complexity': piecewise_linear(features['complexity'],
                                       [(0.9, 0.02), (1.3, 0.35), (1.8, 1.0), (3.8, 1.0), (6.0, 0.02)]),
        'structure': 1.0 if is_structured(features) else 0.4,
        'fill': trapezoid(features['fill'], 0.02, 0.06, 0.45, 0.62),
        'aspect': trapezoid(features['aspect'], 0.15, 0.38, 1.0, 1.01),
        'endpoints': _ENDPOINT_SCORES.get(features['endpoints'], 0.0),
        'junctions': _JUNCTION_SCORES.get(features['junctions'], 0.0),
        'straightness': trapezoid(features['straightness'], 0.3, 0.65, 1.0, 1.01),
        'orientations': {0: 0.0, 1: 0.3}.get(features['orientations'], 1.0),
        'segments': trapezoid(features['segments'], 0.5, 1.5, 12.0, 22.0),
        'width_variation': trapezoid(features['width_variation'], -1.0, 0.0, 0.5, 0.9),
    }


def score_glyph(features):
    """Character-likeness of a measured shape in [0, 1].

    A weighted geometric mean of the evidence terms: one clearly wrong
    property (a solid blob, a lone straight stick) pulls the score down
    regardless of the rest.
    """
    evidence = glyph_evidence(features)
    total_weight = sum(_SCORE_WEIGHTS.values())
    log_sum = sum(_SCORE_WEIGHTS[name] * math.log(max(value, 1e-3)) for name, value in evidence.items())
    return math.exp(log_sum / total_weight)
