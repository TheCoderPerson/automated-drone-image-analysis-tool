"""Read hand-built characters by comparing them with stick-figure templates.

A character laid out from sticks or rocks is a handful of strokes, so each
template is drawn as the strokes a person would lay: straight lines in a unit
box (x across, y down, height 1). Several characters have more than one
common construction (a blocky or a rounded B, a rectangular or an octagonal
O), and each construction is a separate template.

A glyph is turned upright using the direction of its text line, scaled to the
template height and compared stroke-to-stroke with a symmetric chamfer
distance: how far the glyph's skeleton lies from the template's, and how far
the template's lies from the glyph's (so a missing stroke counts as much as a
stray one).

Pure numpy/OpenCV/scikit-image; no Qt dependency.
"""

import math

import cv2
import numpy as np
from skimage.morphology import skeletonize

CANVAS_HEIGHT = 40
CANVAS_WIDTH = 64
CANVAS_PAD = 4
GLYPH_HEIGHT = CANVAS_HEIGHT - 2 * CANVAS_PAD
# Small rotations tried around the upright pose: hand-laid characters are
# rarely square to their line.
ANGLE_OFFSETS_DEG = (-12.0, 0.0, 12.0)
# Chamfer error (fraction of character height) at which similarity is 1/e.
SIMILARITY_SCALE = 0.07


def _octagon(cx, cy, rx, ry):
    points = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)]
    return [points]


# Each template is a list of polylines in a unit-height box: (x, y), y down.
TEMPLATES = {
    'A': [[[(0, 1), (0.35, 0), (0.7, 1)], [(0.13, 0.62), (0.57, 0.62)]],
          [[(0, 1), (0, 0), (0.7, 0), (0.7, 1)], [(0, 0.5), (0.7, 0.5)]]],
    'B': [[[(0, 0), (0, 1), (0.65, 1), (0.65, 0.5), (0, 0.5)], [(0, 0), (0.55, 0), (0.55, 0.5)]],
          [[(0, 0), (0, 1)], [(0, 0), (0.5, 0), (0.65, 0.25), (0.5, 0.5), (0, 0.5)],
           [(0.5, 0.5), (0.7, 0.75), (0.5, 1), (0, 1)]]],
    'C': [[[(0.7, 0), (0, 0), (0, 1), (0.7, 1)]],
          [[(0.7, 0.15), (0.45, 0), (0.2, 0), (0, 0.25), (0, 0.75), (0.2, 1), (0.45, 1), (0.7, 0.85)]]],
    'D': [[[(0, 0), (0, 1), (0.45, 1), (0.7, 0.7), (0.7, 0.3), (0.45, 0), (0, 0)]]],
    'E': [[[(0.7, 0), (0, 0), (0, 1), (0.7, 1)], [(0, 0.5), (0.55, 0.5)]]],
    'F': [[[(0.7, 0), (0, 0), (0, 1)], [(0, 0.5), (0.55, 0.5)]]],
    'G': [[[(0.7, 0), (0, 0), (0, 1), (0.7, 1), (0.7, 0.55), (0.4, 0.55)]],
          [[(0.7, 0.15), (0.45, 0), (0.2, 0), (0, 0.25), (0, 0.75), (0.2, 1), (0.5, 1), (0.7, 0.8), (0.7, 0.55),
            (0.4, 0.55)]]],
    'H': [[[(0, 0), (0, 1)], [(0.7, 0), (0.7, 1)], [(0, 0.5), (0.7, 0.5)]]],
    'I': [[[(0.35, 0), (0.35, 1)]],
          [[(0.35, 0), (0.35, 1)], [(0.1, 0), (0.6, 0)], [(0.1, 1), (0.6, 1)]]],
    'J': [[[(0.6, 0), (0.6, 1), (0, 1), (0, 0.7)]],
          [[(0.6, 0), (0.6, 1), (0, 1), (0, 0.7)], [(0.25, 0), (0.85, 0)]]],
    'K': [[[(0, 0), (0, 1)], [(0.7, 0), (0, 0.55)], [(0.25, 0.42), (0.7, 1)]],
          [[(0, 0), (0, 1)], [(0.7, 0), (0, 0.5), (0.7, 1)]]],
    'L': [[[(0, 0), (0, 1), (0.65, 1)]]],
    'M': [[[(0, 1), (0, 0), (0.45, 0.6), (0.9, 0), (0.9, 1)]],
          [[(0, 1), (0.1, 0), (0.45, 0.6), (0.8, 0), (0.9, 1)]]],
    'N': [[[(0, 1), (0, 0), (0.7, 1), (0.7, 0)]]],
    'O': [[[(0, 0), (0.7, 0), (0.7, 1), (0, 1), (0, 0)]],
          _octagon(0.35, 0.5, 0.35, 0.5)],
    'P': [[[(0, 1), (0, 0), (0.7, 0), (0.7, 0.5), (0, 0.5)]],
          [[(0, 1), (0, 0), (0.5, 0), (0.7, 0.25), (0.5, 0.5), (0, 0.5)]]],
    'Q': [[[(0, 0), (0.7, 0), (0.7, 1), (0, 1), (0, 0)], [(0.45, 0.7), (0.85, 1.05)]]],
    'R': [[[(0, 1), (0, 0), (0.7, 0), (0.7, 0.5), (0, 0.5)], [(0.25, 0.5), (0.7, 1)]],
          [[(0, 1), (0, 0), (0.5, 0), (0.7, 0.25), (0.5, 0.5), (0, 0.5)], [(0.3, 0.5), (0.7, 1)]]],
    'S': [[[(0.7, 0), (0, 0), (0, 0.5), (0.7, 0.5), (0.7, 1), (0, 1)]],
          [[(0.7, 0.05), (0.15, 0), (0, 0.25), (0.7, 0.72), (0.6, 1), (0, 0.97)]]],
    'T': [[[(0, 0), (0.7, 0)], [(0.35, 0), (0.35, 1)]]],
    'U': [[[(0, 0), (0, 1), (0.7, 1), (0.7, 0)]],
          [[(0, 0), (0, 0.75), (0.2, 1), (0.5, 1), (0.7, 0.75), (0.7, 0)]]],
    'V': [[[(0, 0), (0.35, 1), (0.7, 0)]]],
    'W': [[[(0, 0), (0.22, 1), (0.45, 0.4), (0.68, 1), (0.9, 0)]]],
    'X': [[[(0, 0), (0.7, 1)], [(0.7, 0), (0, 1)]]],
    'Y': [[[(0, 0), (0.35, 0.5), (0.7, 0)], [(0.35, 0.5), (0.35, 1)]]],
    'Z': [[[(0, 0), (0.7, 0), (0, 1), (0.7, 1)]]],
    '0': [[[(0, 0), (0.55, 0), (0.55, 1), (0, 1), (0, 0)]],
          _octagon(0.28, 0.5, 0.28, 0.5)],
    '1': [[[(0.3, 0), (0.3, 1)], [(0.3, 0), (0.05, 0.25)]]],
    '2': [[[(0, 0), (0.7, 0), (0.7, 0.5), (0, 0.5), (0, 1), (0.7, 1)]],
          [[(0, 0.15), (0.2, 0), (0.6, 0), (0.7, 0.2), (0.7, 0.4), (0, 1), (0.7, 1)]]],
    '3': [[[(0, 0), (0.7, 0), (0.7, 1), (0, 1)], [(0.15, 0.5), (0.7, 0.5)]],
          [[(0, 0), (0.7, 0), (0.3, 0.45), (0.7, 0.7), (0.5, 1), (0, 0.95)]]],
    '4': [[[(0, 0), (0, 0.55), (0.7, 0.55)], [(0.55, 0), (0.55, 1)]],
          [[(0.55, 1), (0.55, 0), (0, 0.65), (0.7, 0.65)]]],
    '5': [[[(0.7, 0), (0, 0), (0, 0.45), (0.7, 0.45), (0.7, 1), (0, 1)]]],
    '6': [[[(0.7, 0), (0, 0), (0, 1), (0.7, 1), (0.7, 0.5), (0, 0.5)]]],
    '7': [[[(0, 0), (0.7, 0), (0.25, 1)]]],
    '8': [[[(0, 0), (0.7, 0), (0.7, 1), (0, 1), (0, 0)], [(0, 0.5), (0.7, 0.5)]]],
    '9': [[[(0.7, 0.5), (0, 0.5), (0, 0), (0.7, 0), (0.7, 1)]],
          [[(0.7, 0.5), (0, 0.5), (0, 0), (0.7, 0), (0.7, 1), (0, 1)]]],
}
ALPHABET = ''.join(sorted(TEMPLATES))


def _render_template(polylines):
    """Thin-line rendering of a template, normalised like a glyph."""
    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH), np.uint8)
    xs = [x for line in polylines for x, _ in line]
    ys = [y for line in polylines for _, y in line]
    y_min, y_max = min(ys), max(ys)
    scale = GLYPH_HEIGHT / max(y_max - y_min, 1e-6)
    x_center = (min(xs) + max(xs)) / 2.0
    for line in polylines:
        pts = np.array([(CANVAS_WIDTH / 2.0 + (x - x_center) * scale, CANVAS_PAD + (y - y_min) * scale)
                        for x, y in line], np.float32)
        cv2.polylines(canvas, [np.round(pts).astype(np.int32)], False, 255, 1)
    return canvas


def _build_templates():
    labels, distance_maps, skeleton_points = [], [], []
    for char, variants in TEMPLATES.items():
        for polylines in variants:
            canvas = _render_template(polylines)
            labels.append(char)
            distance_maps.append(cv2.distanceTransform(255 - canvas, cv2.DIST_L2, 3))
            skeleton_points.append(np.argwhere(canvas > 0))
    return labels, np.stack(distance_maps), skeleton_points


_LABELS, _TEMPLATE_DISTANCES, _TEMPLATE_POINTS = _build_templates()
_LABEL_INDEX = {char: [i for i, label in enumerate(_LABELS) if label == char] for char in ALPHABET}


def upright_canvas(mask, origin, direction, angle_offset_deg=0.0):
    """Rotate and scale one glyph's stroke mask into the template frame.

    Args:
        mask: uint8 (0/255) stroke mask of the glyph at its pyramid level.
        origin: (x, y) of the mask's top-left corner in level pixels.
        direction: Unit vector (dx, dy) of the reading direction in image
            pixels (left to right along the text line).
        angle_offset_deg: Extra rotation tried around the upright pose.

    Returns:
        uint8 canvas of shape (CANVAS_HEIGHT, CANVAS_WIDTH), or None if the
        glyph has no extent across the line.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    angle = math.atan2(direction[1], direction[0]) + math.radians(angle_offset_deg)
    ux, uy = math.cos(angle), math.sin(angle)       # along the line
    vx, vy = -uy, ux                                  # down, across the line
    px = (xs + origin[0]).astype(np.float64)
    py = (ys + origin[1]).astype(np.float64)
    u = px * ux + py * uy
    v = px * vx + py * vy
    v_lo, v_hi = np.percentile(v, [2, 98])
    height = v_hi - v_lo
    if height <= 0:
        return None
    scale = GLYPH_HEIGHT / height
    u_mid = (u.min() + u.max()) / 2.0
    # Affine map from mask pixel (x, y) to canvas (column, row).
    a = np.array([[ux * scale, uy * scale, (origin[0] * ux + origin[1] * uy - u_mid) * scale + CANVAS_WIDTH / 2.0],
                  [vx * scale, vy * scale, (origin[0] * vx + origin[1] * vy - v_lo) * scale + CANVAS_PAD]],
                 np.float32)
    canvas = cv2.warpAffine(mask, a, (CANVAS_WIDTH, CANVAS_HEIGHT), flags=cv2.INTER_LINEAR)
    return ((canvas > 96) * 255).astype(np.uint8)


def chamfer_errors(canvas):
    """Symmetric chamfer error (fraction of character height) against every template."""
    skeleton = skeletonize(canvas > 0)
    points = np.argwhere(skeleton)
    if len(points) < 5:
        return None
    # glyph -> template: how far the glyph's strokes are from each template's strokes
    to_template = _TEMPLATE_DISTANCES[:, points[:, 0], points[:, 1]].mean(axis=1)
    # template -> glyph: how much of each template the glyph covers
    glyph_distance = cv2.distanceTransform(np.where(skeleton, 0, 255).astype(np.uint8), cv2.DIST_L2, 3)
    to_glyph = np.array([glyph_distance[p[:, 0], p[:, 1]].mean() for p in _TEMPLATE_POINTS])
    return (to_template + to_glyph) / (2.0 * GLYPH_HEIGHT)


def read_glyph(mask, origin, direction):
    """Similarity in [0, 1] of one glyph to each character, read along `direction`.

    Returns:
        dict {character: similarity}, or None when the glyph cannot be read.
    """
    best = None
    for offset in ANGLE_OFFSETS_DEG:
        canvas = upright_canvas(mask, origin, direction, offset)
        if canvas is None:
            continue
        errors = chamfer_errors(canvas)
        if errors is None:
            continue
        best = errors if best is None else np.minimum(best, errors)
    if best is None:
        return None
    similarity = np.exp(-best / SIMILARITY_SCALE)
    return {char: float(similarity[indices].max()) for char, indices in _LABEL_INDEX.items()}
