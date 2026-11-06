"""
RoundGeometry.py - pure, stateless geometry for round, oval and arc shape detection.

The curved counterpart of RectilinearGeometry. Everything here works in
processing-resolution pixels and knows nothing of GSD, options dictionaries
or AOIs: RoundShapeService turns physical sizes into pixel ranges and hands
them in, so the geometry can be unit-tested on synthetic frames.

Pipeline the service runs:
    1. edge_map             - thin edges (Canny) above the contrast floor.
    2. radial_symmetry_map  - every edge pixel votes for a centre at +/- r
                              along its gradient; the normals of a circle,
                              an oval or an arc converge on its centre.
    3. symmetry_peaks       - candidate centres and their mean voting radius.
    4. fit_round            - at each peak, circles read off the distance
                              histogram and ovals from antipodal edge pairs,
                              each polished by least squares.
    5. outline_support      - how much of the outline is backed by an edge,
                              in one stretch or all round, and whether that
                              edge really curves.
    6. ring_contrast_lab,
       size_score           - the remaining score terms.
    7. ellipse_nms          - suppress duplicates and parts of one outline.

Conventions:
    * ``ang`` is gradient orientation in radians, as returned by arctan2(gy, gx);
      ``mag`` is on the step-height scale (see RectilinearGeometry).
    * An ellipse is an ``Ellipse``: centre, full major and minor axis lengths
      (diameters, not semi-axes) and the direction of the major axis in
      degrees, normalised to [0, 180). A circle has major == minor.
"""

import math
from collections import namedtuple

import cv2
import numpy as np

# Re-exported for RoundShapeService: the same gradient scale and the same
# log-ratio size decay as the rectilinear detector.
from algorithms.Shared.services.RectilinearGeometry import compute_gradients, size_score


# A rotated ellipse in pixel coordinates. ``major`` and ``minor`` are full
# axis lengths; ``major >= minor`` always holds for ellipses built here.
Ellipse = namedtuple('Ellipse', ['cx', 'cy', 'major', 'minor', 'angle_deg'])

# What outline_support measured about one ellipse. ``support`` is the
# supported fraction of the outline; ``arc_deg`` and ``gap_deg`` are its
# longest supported and unsupported stretches, in degrees of the outline;
# ``boxiness`` and ``curvature`` say whether that support comes from a curve
# (see outline_support); ``strength`` is the median gradient magnitude of the
# supporting edge, to compare against the frame's texture (noise_floor).
OutlineEvidence = namedtuple('OutlineEvidence', ['support', 'arc_deg', 'gap_deg', 'boxiness', 'curvature', 'strength'])

# Edge hysteresis thresholds as fractions of the operator's minimum edge
# contrast, on the step-height scale of ``mag`` (a blurred step of height h
# peaks a little above h / 2).
_EDGE_HIGH_PER_CONTRAST = 0.5
_EDGE_LOW_PER_CONTRAST = 0.25

# Multiple of the frame's median gradient treated as texture (see noise_floor).
_NOISE_MULTIPLE = 2.0

# Cap on one edge pixel's vote, in reference-contrast units, so a few very
# high-contrast edges (hard shadows) cannot outvote a whole fainter outline.
_WEIGHT_CAP_PER_REFERENCE = 3.0

# Edge pixels Canny leaves per pixel of outline length on a digital circle
# (8-connected chains are shorter than the true arc by about this factor).
_OUTLINE_PIXELS_PER_PX = 0.9

# Half-width (px) of the band searched along the outline's normal for its
# edge, as a floor and as a fraction of the semi-minor axis.
_EDGE_SEARCH_HALF_WIDTH = 2.0
_EDGE_SEARCH_FRACTION = 0.04

# |cos| of the largest angle between an edge's gradient and the radial
# direction for it to be considered at a candidate centre (55 degrees).
_RADIAL_PREFILTER_COS = math.cos(math.radians(55.0))

# Least share of a circle's outline that aligned edges at one radius must
# explain before that radius is worth polishing.
_MIN_MODEL_COVERAGE = 0.15

# Antipodal-pair search (see _antipodal_ellipse): gradient orientation bins,
# a cap on the edge pixels paired per candidate, the fewest pairs that must
# agree on a centre, and the fewest distinct chord directions (of the bins)
# they must span.
_PAIR_ORIENTATION_BINS = 18
_MAX_PAIR_POINTS = 1000
_MIN_PAIRS = 8
_MIN_CHORD_DIRECTIONS = 8

# Least angular span (degrees, about the centre) of fitted edge pixels for a
# free ellipse fit. Below it the five ellipse parameters are poorly
# constrained by an arc, so the polish keeps the model as it stands.
_ELLIPSE_MIN_SPAN_DEG = 200.0

# Polishing passes of the least-squares fit, each re-selecting inliers
# around the previous answer.
_POLISH_ITERATIONS = 3

# Samples used to measure a fitted outline's support.
_OUTLINE_SAMPLES = 72

# Consecutive unsupported outline samples bridged when measuring an arc's
# contiguous span (a stick across a tire should not split it in two).
_ARC_GAP_SAMPLES = 1

# Fewest consecutive supported samples (short gaps bridged) that count as
# a stretch of real edge rather than texture: 15 degrees of the outline.
_MIN_RUN_SAMPLES = 3

# Least turn of the outline's normal (degrees) across a supported stretch
# for that stretch to say whether the edge under it curves.
_CURVATURE_MIN_TURN_DEG = 12.0


def _axis_angle_deg(angle_deg):
    """Normalise an undirected axis direction to [0, 180)."""
    return float(angle_deg % 180.0)


def make_ellipse(cx, cy, axis_a, axis_b, angle_a_deg):
    """Build an Ellipse from two full axis lengths, the first along ``angle_a_deg``."""
    if axis_a >= axis_b:
        return Ellipse(float(cx), float(cy), float(axis_a), float(axis_b), _axis_angle_deg(angle_a_deg))
    return Ellipse(float(cx), float(cy), float(axis_b), float(axis_a), _axis_angle_deg(angle_a_deg + 90.0))


def ellipse_points(ellipse, count=64):
    """``count`` points on the outline, evenly spaced by arc length.

    Returns:
        tuple: (points, normals) float32 (count, 2) arrays - outline points in
        pixel coordinates and the outward unit normal at each.
    """
    a = max(ellipse.major * 0.5, 1e-6)
    b = max(ellipse.minor * 0.5, 1e-6)
    # Dense parametric samples, then resampled at equal arc length so the
    # pointed ends of an oval are not over-represented.
    dense = np.linspace(0.0, 2.0 * np.pi, 8 * count + 1, dtype=np.float64)
    step = np.hypot(-a * np.sin(dense), b * np.cos(dense))
    arc = np.concatenate(([0.0], np.cumsum(0.5 * (step[1:] + step[:-1]) * np.diff(dense))))
    targets = (np.arange(count, dtype=np.float64) + 0.5) / count * arc[-1]
    t = np.interp(targets, arc, dense)
    local_x = a * np.cos(t)
    local_y = b * np.sin(t)
    normal_x = local_x / (a * a)
    normal_y = local_y / (b * b)
    norm = np.maximum(np.hypot(normal_x, normal_y), 1e-12)
    normal_x /= norm
    normal_y /= norm
    theta = math.radians(ellipse.angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    points = np.column_stack((
        ellipse.cx + local_x * cos_t - local_y * sin_t,
        ellipse.cy + local_x * sin_t + local_y * cos_t,
    )).astype(np.float32)
    normals = np.column_stack((
        normal_x * cos_t - normal_y * sin_t,
        normal_x * sin_t + normal_y * cos_t,
    )).astype(np.float32)
    return points, normals


def ellipse_perimeter(ellipse):
    """Outline length in pixels (Ramanujan's second approximation)."""
    a = ellipse.major * 0.5
    b = ellipse.minor * 0.5
    if a <= 0 or b <= 0:
        return 0.0
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1.0 + 3.0 * h / (10.0 + math.sqrt(4.0 - 3.0 * h)))


def noise_floor(mag, noise_multiple=_NOISE_MULTIPLE):
    """Gradient magnitude below which an edge is indistinguishable from ground texture.

    A multiple of the frame's median magnitude, as in
    RectilinearGeometry.boxiness_weights: texture is present at nearly every
    pixel, a target's outline only along its perimeter.
    """
    return noise_multiple * float(np.median(mag))


def edge_map(gray, mag, min_contrast):
    """Thin edges that clear both the contrast setting and the frame's texture.

    Args:
        gray (np.ndarray): uint8 working channel (already pre-blurred).
        mag (np.ndarray): Its gradient magnitude (compute_gradients).
        min_contrast (float): Minimum edge step on the 0-255 scale.

    Returns:
        np.ndarray: uint8 mask, 255 on edge pixels.
    """
    floor = noise_floor(mag)
    # Canny measures raw Sobel magnitude: four times the step-height scale.
    high = 4.0 * max(_EDGE_HIGH_PER_CONTRAST * float(min_contrast), floor)
    low = 4.0 * max(_EDGE_LOW_PER_CONTRAST * float(min_contrast), 0.6 * floor)
    return cv2.Canny(gray, low, high, L2gradient=True)


def radial_symmetry_map(edges, mag, ang, radius_range_px, cell_px, reference_contrast):
    """Vote for the centres that edge normals converge on.

    Each edge pixel votes at distance r in both directions along its
    gradient (targets may be lighter or darker than the ground) for every r
    in the radius range. A circle of radius r sends its whole outline to one
    cell; an oval or an arc sends proportionally less, spread a little.

    A vote weighs the pixel's magnitude above the frame's noise floor, so
    the thousands of texture edges on grass or gravel add up to little while
    a target's outline, a few hundred pixels, still stands out. Votes are
    counted on a grid of ``cell_px`` pixels, which keeps the accumulator
    small on 48 MP frames, then summed over each 3 x 3 block.

    Args:
        edges (np.ndarray): uint8 edge mask (from edge_map).
        mag (np.ndarray): Gradient magnitude, full resolution.
        ang (np.ndarray): Gradient orientation in radians, full resolution.
        radius_range_px (tuple): (min, max) radius in pixels.
        cell_px (int): Accumulator cell size in pixels.
        reference_contrast (float): Edge weight (magnitude above the noise
            floor) that counts as one full vote.

    Returns:
        tuple: (symmetry, radius) float32 maps on the cell grid. ``symmetry``
        is the weighted vote divided by what a perfect circle at the
        reference contrast would cast there - about 1 for such a circle, more
        for a crisper one, less for an oval, an arc or a fainter outline;
        ``radius`` is the mean voting radius in pixels.
    """
    cell = max(1, int(cell_px))
    height, width = edges.shape[:2]
    grid_w = (width + cell - 1) // cell
    grid_h = (height + cell - 1) // cell
    votes = np.zeros(grid_w * grid_h, dtype=np.float64)
    radius_sum = np.zeros(grid_w * grid_h, dtype=np.float64)

    r_lo, r_hi = (max(1.0, float(v)) for v in radius_range_px)
    if r_hi < r_lo:
        r_lo, r_hi = r_hi, r_lo
    step = float(cell)
    radii = np.arange(r_lo, r_hi + 0.5 * step, step, dtype=np.float32)

    ys, xs = np.nonzero(edges)
    if len(xs) and len(radii):
        reference = max(float(reference_contrast), 1e-3)
        weights = np.clip(mag[ys, xs] - noise_floor(mag), 0.0, _WEIGHT_CAP_PER_REFERENCE * reference) / reference
        live = weights > 0
        xs, ys, weights = xs[live], ys[live], weights[live].astype(np.float64)
        theta = ang[ys, xs]
        ux = np.cos(theta).astype(np.float32)
        uy = np.sin(theta).astype(np.float32)
        xs = xs.astype(np.float32)
        ys = ys.astype(np.float32)
        for radius in radii:
            for sign in (1.0, -1.0):
                vx = xs + sign * radius * ux
                vy = ys + sign * radius * uy
                inside = (vx >= 0) & (vx < width) & (vy >= 0) & (vy < height)
                index = (vy[inside] // cell).astype(np.int64) * grid_w + (vx[inside] // cell).astype(np.int64)
                counts = np.bincount(index, weights=weights[inside], minlength=grid_w * grid_h)
                votes += counts
                radius_sum += counts * float(radius)

    votes = votes.reshape(grid_h, grid_w).astype(np.float32)
    radius_sum = radius_sum.reshape(grid_h, grid_w).astype(np.float32)
    block_votes = cv2.boxFilter(votes, -1, (3, 3), normalize=False, borderType=cv2.BORDER_CONSTANT)
    block_radius = cv2.boxFilter(radius_sum, -1, (3, 3), normalize=False, borderType=cv2.BORDER_CONSTANT)
    radius = np.where(block_votes > 0, block_radius / np.maximum(block_votes, 1e-6), 0.0).astype(np.float32)

    # A perfect circle of radius R puts ~2 pi R votes (one per outline pixel)
    # into the centre block from each radius within 1.5 cells of R.
    radii_in_block = float(min(3, max(1, len(radii))))
    expected = 2.0 * np.pi * np.maximum(radius, 1.0) * radii_in_block * _OUTLINE_PIXELS_PER_PX
    symmetry = np.where(block_votes > 0, block_votes / expected, 0.0).astype(np.float32)
    return symmetry, radius


def symmetry_peaks(symmetry, radius, min_symmetry, nms_radius_px, cell_px, max_peaks=500):
    """Local maxima of the symmetry map, strongest first.

    Args:
        symmetry (np.ndarray): Map from radial_symmetry_map.
        radius (np.ndarray): Mean voting radius map from radial_symmetry_map.
        min_symmetry (float): Peak threshold.
        nms_radius_px (float): Peak suppression radius, full-resolution px.
        cell_px (int): Grid cell size of the maps.
        max_peaks (int): Cap on peaks returned.

    Returns:
        list[tuple]: (cx, cy, radius_px, symmetry) per peak, full-resolution px.
    """
    cell = max(1, int(cell_px))
    reach = max(1, int(round(nms_radius_px / cell)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1))
    dilated = cv2.dilate(symmetry, kernel)
    peaks = np.argwhere((symmetry >= min_symmetry) & (symmetry >= dilated))
    if len(peaks) == 0:
        return []
    strengths = symmetry[peaks[:, 0], peaks[:, 1]]
    order = np.argsort(-strengths, kind='stable')[:max_peaks]
    result = []
    for row, col in peaks[order]:
        result.append((
            (col + 0.5) * cell,
            (row + 0.5) * cell,
            float(radius[row, col]),
            float(symmetry[row, col]),
        ))
    return result


def _window_edges(edges, mag, ang, cx, cy, half):
    """Edge pixels within ``half`` px of (cx, cy): coordinates, gradient unit vectors and magnitudes."""
    height, width = edges.shape[:2]
    x0, x1 = max(0, int(cx - half)), min(width, int(cx + half) + 1)
    y0, y1 = max(0, int(cy - half)), min(height, int(cy + half) + 1)
    if x1 <= x0 or y1 <= y0:
        empty = np.zeros(0, np.float32)
        return empty, empty, empty, empty, empty
    ys, xs = np.nonzero(edges[y0:y1, x0:x1])
    theta = ang[y0:y1, x0:x1][ys, xs]
    return (
        (xs + x0).astype(np.float32),
        (ys + y0).astype(np.float32),
        np.cos(theta).astype(np.float32),
        np.sin(theta).astype(np.float32),
        mag[y0:y1, x0:x1][ys, xs].astype(np.float32),
    )


def _normalised_radius(px, py, gx, gy, angle_deg, aspect):
    """Map points into the frame where the model ellipse is a circle.

    Returns:
        tuple: (rho, alignment) - each point's radius in that frame (equal to
        the semi-major axis for a point on the outline) and |cos| of the angle
        between its gradient and the model's normal there.
    """
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    u = px * cos_t + py * sin_t
    v = -px * sin_t + py * cos_t
    rho = np.sqrt(u * u + (v / aspect) ** 2)
    nu = u
    nv = v / (aspect * aspect)
    norm = np.maximum(np.hypot(nu, nv), 1e-6)
    gu = gx * cos_t + gy * sin_t
    gv = -gx * sin_t + gy * cos_t
    alignment = np.abs(gu * nu + gv * nv) / norm
    return rho, alignment


def _best_radii(distances, lo, hi, band, top=2):
    """Most populated radii among ``distances`` in [lo, hi], at least ``3 * band`` apart.

    Returns:
        list[tuple]: (radius, count within +/- band) per radius, strongest first.
    """
    if hi <= lo or len(distances) == 0:
        return []
    bins = max(1, int(math.ceil((hi - lo) / 0.5)))
    hist, edges = np.histogram(distances, bins=bins, range=(lo, hi))
    # Count within +/- band of each bin. A windowed sum rather than
    # np.convolve(mode='same'), whose output takes the kernel's length when
    # the kernel is the longer of the two (a narrow radius range).
    width = max(1, int(round(band / 0.5)))
    running = np.concatenate(([0.0], np.cumsum(np.pad(hist.astype(np.float64), width))))
    smoothed = running[2 * width + 1:] - running[:len(hist)]
    centres = 0.5 * (edges[1:] + edges[:-1])
    found = []
    for index in np.argsort(-smoothed, kind='stable'):
        value = float(smoothed[index])
        if value <= 0:
            break
        candidate = float(centres[index])
        if all(abs(candidate - other) >= 3.0 * band for other, _ in found):
            found.append((candidate, value))
            if len(found) == top:
                break
    return found


def _fit_circle(xs, ys):
    """Algebraic (Kasa) circle fit. Returns (cx, cy, r) or None."""
    if len(xs) < 3:
        return None
    design = np.column_stack((xs, ys, np.ones_like(xs))).astype(np.float64)
    target = -(xs.astype(np.float64) ** 2 + ys.astype(np.float64) ** 2)
    try:
        (d, e, f), *_ = np.linalg.lstsq(design, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = -0.5 * d, -0.5 * e
    r_sq = cx * cx + cy * cy - f
    if not np.isfinite(r_sq) or r_sq <= 1.0:
        return None
    return float(cx), float(cy), float(math.sqrt(r_sq))


def _fit_ellipse(xs, ys):
    """Direct least-squares ellipse fit. Returns an Ellipse or None."""
    if len(xs) < 6:
        return None
    try:
        (cx, cy), (axis_w, axis_h), angle = cv2.fitEllipseDirect(np.column_stack((xs, ys)).astype(np.float32))
    except cv2.error:
        return None
    if not all(np.isfinite(v) for v in (cx, cy, axis_w, axis_h, angle)) or min(axis_w, axis_h) < 2.0:
        return None
    return make_ellipse(cx, cy, axis_w, axis_h, angle)


def _angular_span_deg(xs, ys, cx, cy, bins=36):
    """Degrees of the circle about (cx, cy) that the points occupy."""
    if len(xs) == 0:
        return 0.0
    angles = np.arctan2(ys - cy, xs - cx)
    occupied = np.unique(((angles + np.pi) / (2.0 * np.pi) * bins).astype(np.int64) % bins)
    return 360.0 * len(occupied) / bins


def _inliers(xs, ys, gx, gy, ellipse, band, cos_tol):
    """Edge pixels within ``band`` of the outline whose gradient follows its normal."""
    a = max(ellipse.major * 0.5, 1e-6)
    aspect = max(ellipse.minor / max(ellipse.major, 1e-6), 1e-3)
    rho, alignment = _normalised_radius(xs - ellipse.cx, ys - ellipse.cy, gx, gy, ellipse.angle_deg, aspect)
    # rho - a overstates the distance along the minor axis by up to 1/aspect.
    return (np.abs(rho - a) * aspect <= band) & (alignment >= cos_tol)


def fit_round(edges, mag, ang, cx, cy, radius_range_px, angle_tol_deg, floor=0.0):
    """Circle and ellipse hypotheses explaining the edges around a candidate centre.

    Two routes, because a symmetry peak means different things for the two
    shapes. The normals of a circle (or of an arc of one) meet at its centre,
    so circles are read straight off a histogram of edge distance from the
    peak; the two strongest radii both become hypotheses so a ring's inner
    and outer edges (a tire) are each tried. The normals of an oval meet
    near the centres of curvature of its ends instead, so ovals come from
    antipodal pairs (see _antipodal_ellipse), which find the true centre from
    a peak at either end. Every hypothesis is then polished by least squares
    on its own inliers; scoring and suppression decide between them.

    Args:
        edges (np.ndarray): uint8 edge mask.
        mag (np.ndarray): Gradient magnitude.
        ang (np.ndarray): Gradient orientation in radians.
        cx, cy (float): Candidate centre (a symmetry peak).
        radius_range_px (tuple): (min, max) semi-axis range in pixels.
        angle_tol_deg (float): Allowed angle between an edge's gradient and
            the outline's normal.
        floor (float): Frame noise floor (noise_floor); antipodal pairs are
            weighted by magnitude above it.

    Returns:
        list[Ellipse]
    """
    r_lo, r_hi = radius_range_px
    band = max(_EDGE_SEARCH_HALF_WIDTH, _EDGE_SEARCH_FRACTION * r_lo)
    cos_tol = math.cos(math.radians(angle_tol_deg))
    cos_loose = math.cos(math.radians(min(60.0, 1.5 * angle_tol_deg)))
    hypotheses = []

    xs, ys, gx, gy, _ = _window_edges(edges, mag, ang, cx, cy, r_hi + 2.0 * band + 1.0)
    if len(xs) >= 8:
        px = xs - cx
        py = ys - cy
        distance = np.hypot(px, py)
        radial = np.abs(px * gx + py * gy) / np.maximum(distance, 1e-6)
        aligned = (radial >= cos_loose) & (distance >= r_lo - band) & (distance <= r_hi + band)
        for radius, count in _best_radii(distance[aligned], r_lo, r_hi, band):
            if count < _MIN_MODEL_COVERAGE * 2.0 * math.pi * radius * _OUTLINE_PIXELS_PER_PX:
                continue
            circle = Ellipse(float(cx), float(cy), 2.0 * radius, 2.0 * radius, 0.0)
            polished = _polish(xs, ys, gx, gy, circle, cos_loose, cos_tol)
            if polished is not None:
                hypotheses.append(polished)

    # An end-of-oval peak sits less than one semi-major axis from the centre.
    wx, wy, wgx, wgy, wmag = _window_edges(edges, mag, ang, cx, cy, 2.0 * r_hi + 2.0 * band + 1.0)
    weights = np.maximum(wmag - float(floor), 0.0)
    oval = _antipodal_ellipse(wx, wy, wgx, wgy, weights, (cx, cy), r_lo, r_hi, band, cos_tol)
    if oval is not None:
        polished = _polish(wx, wy, wgx, wgy, oval, cos_loose, cos_tol)
        if polished is not None and not any(_same_ellipse(polished, h, band) for h in hypotheses):
            hypotheses.append(polished)
    return hypotheses


def _same_ellipse(first, second, tolerance):
    """True when two ellipses differ by less than ``tolerance`` px in centre and both axes."""
    return (
        math.hypot(first.cx - second.cx, first.cy - second.cy) <= tolerance
        and abs(first.major - second.major) <= 2.0 * tolerance
        and abs(first.minor - second.minor) <= 2.0 * tolerance
    )


def _antipodal_pairs(xs, ys, gx, gy, weights, length_range, cos_tol):
    """Pairs of edge pixels that could be opposite ends of a diameter.

    On any ellipse the two points with parallel tangents are diametrically
    opposite, so their midpoint is the centre. A pair qualifies when the two
    gradients are parallel within the tolerance, the chord between them is
    a plausible diameter, the chord runs roughly along both normals (two
    points on one straight edge do not pair) and both gradients point into
    or both out of the chord (one consistent target polarity).

    Returns:
        tuple: (mid_x, mid_y, chord_angle, half_length, weight) float arrays;
        a pair weighs the weaker of its two edge weights.
    """
    live = weights > 0
    xs, ys, gx, gy, weights = xs[live], ys[live], gx[live], gy[live], weights[live]
    count = len(xs)
    if count > _MAX_PAIR_POINTS:
        # Keep the strongest edges: the pairing cost stays bounded, and a
        # target's outline outranks most of the texture around it.
        pick = np.sort(np.argpartition(-weights, _MAX_PAIR_POINTS - 1)[:_MAX_PAIR_POINTS])
        xs, ys, gx, gy, weights = xs[pick], ys[pick], gx[pick], gy[pick], weights[pick]
    phi = np.arctan2(gy, gx) % np.pi
    bins = _PAIR_ORIENTATION_BINS
    bin_of = (phi / np.pi * bins).astype(np.int64) % bins
    members = [np.flatnonzero(bin_of == k) for k in range(bins)]
    tol = math.acos(max(-1.0, min(1.0, cos_tol)))
    length_lo, length_hi = length_range
    found = ([], [], [], [], [])
    for k in range(bins):
        first = members[k]
        if len(first) == 0:
            continue
        for other_bin in (k, (k + 1) % bins):
            second = members[other_bin]
            if len(second) == 0:
                continue
            dx = xs[second][None, :] - xs[first][:, None]
            dy = ys[second][None, :] - ys[first][:, None]
            length = np.hypot(dx, dy)
            dphi = np.abs(((phi[second][None, :] - phi[first][:, None] + 0.5 * np.pi) % np.pi) - 0.5 * np.pi)
            ok = (length >= length_lo) & (length <= length_hi) & (dphi <= tol)
            if other_bin == k:
                ok &= np.arange(len(first))[:, None] < np.arange(len(second))[None, :]
            safe = np.maximum(length, 1e-6)
            along_first = (gx[first][:, None] * dx + gy[first][:, None] * dy) / safe
            along_second = (gx[second][None, :] * dx + gy[second][None, :] * dy) / safe
            ok &= (np.abs(along_first) >= _RADIAL_PREFILTER_COS) & (np.abs(along_second) >= _RADIAL_PREFILTER_COS)
            ok &= along_first * along_second < 0
            rows, cols = np.nonzero(ok)
            if len(rows) == 0:
                continue
            i = first[rows]
            j = second[cols]
            found[0].append((xs[i] + xs[j]) * 0.5)
            found[1].append((ys[i] + ys[j]) * 0.5)
            found[2].append(np.arctan2(ys[j] - ys[i], xs[j] - xs[i]))
            found[3].append(length[rows, cols] * 0.5)
            found[4].append(np.minimum(weights[i], weights[j]))
    if not found[0]:
        empty = np.zeros(0, np.float32)
        return empty, empty, empty, empty, empty
    return tuple(np.concatenate(part).astype(np.float32) for part in found)


def _antipodal_ellipse(xs, ys, gx, gy, weights, peak, r_lo, r_hi, band, cos_tol):
    """The ellipse implied by antipodal pairs around a candidate, or None.

    The pairs' midpoints are histogrammed, weighted by edge strength, and
    the densest spot within one semi-major axis of the symmetry peak is the
    centre. The pairs voting there give the radius r in their chord
    direction theta, and an ellipse centred on the origin satisfies
        1 / r^2 = A cos^2 theta + B sin theta cos theta + C sin^2 theta,
    which is linear in (A, B, C): a least-squares fit, trimmed once, gives
    the axes and orientation directly.
    """
    if len(xs) < 12:
        return None
    mid_x, mid_y, theta, half, pair_weight = _antipodal_pairs(
        xs, ys, gx, gy, weights, (2.0 * (r_lo - band), 2.0 * (r_hi + band)), cos_tol
    )
    near_peak = (np.hypot(mid_x - peak[0], mid_y - peak[1]) <= r_hi + band) & (pair_weight > 0)
    mid_x, mid_y, theta, half, pair_weight = (v[near_peak] for v in (mid_x, mid_y, theta, half, pair_weight))
    if len(mid_x) < _MIN_PAIRS:
        return None

    x0 = math.floor(float(mid_x.min()))
    y0 = math.floor(float(mid_y.min()))
    grid_w = int(math.floor(float(mid_x.max()))) - x0 + 1
    grid_h = int(math.floor(float(mid_y.max()))) - y0 + 1
    cells = (np.floor(mid_y).astype(np.int64) - y0) * grid_w + (np.floor(mid_x).astype(np.int64) - x0)
    density = np.bincount(cells, weights=pair_weight, minlength=grid_w * grid_h).reshape(grid_h, grid_w).astype(np.float32)
    spread = 2 * int(math.ceil(band)) + 1
    density = cv2.boxFilter(density, -1, (spread, spread), normalize=False, borderType=cv2.BORDER_CONSTANT)
    row, col = np.unravel_index(int(np.argmax(density)), density.shape)
    centre_x, centre_y = x0 + col + 0.5, y0 + row + 0.5

    voting = np.hypot(mid_x - centre_x, mid_y - centre_y) <= 1.5 * band
    if voting.sum() < _MIN_PAIRS:
        return None
    # Chords must cover enough directions to pin down three parameters; the
    # pairs across a strip or a rectangle run in one or two directions only.
    directions = np.unique(((theta[voting] % np.pi) / np.pi * _PAIR_ORIENTATION_BINS).astype(np.int64))
    if len(directions) < _MIN_CHORD_DIRECTIONS:
        return None
    centre_x = float(mid_x[voting].mean())
    centre_y = float(mid_y[voting].mean())
    ellipse = _quadratic_form_ellipse(centre_x, centre_y, theta[voting], half[voting])
    if ellipse is None:
        return None
    # One trimmed refit: drop chords far off the first answer.
    predicted = _ellipse_radius(ellipse, theta[voting])
    residual = np.abs(half[voting] - predicted)
    keep = residual <= max(band, 2.0 * float(np.median(residual)))
    if keep.sum() >= _MIN_PAIRS:
        refined = _quadratic_form_ellipse(centre_x, centre_y, theta[voting][keep], half[voting][keep])
        ellipse = refined if refined is not None else ellipse
    if ellipse.minor < 2.0 * (r_lo - band) * 0.5 or ellipse.major > 2.0 * (r_hi + band) * 1.5:
        return None
    return ellipse


def _quadratic_form_ellipse(cx, cy, theta, half):
    """Least-squares ellipse from (direction, radius) samples about a known centre."""
    cos_t = np.cos(theta).astype(np.float64)
    sin_t = np.sin(theta).astype(np.float64)
    design = np.column_stack((cos_t * cos_t, sin_t * cos_t, sin_t * sin_t))
    target = 1.0 / np.maximum(half.astype(np.float64), 1e-6) ** 2
    try:
        (a_coef, b_coef, c_coef), *_ = np.linalg.lstsq(design, target, rcond=None)
    except np.linalg.LinAlgError:
        return None
    matrix = np.array([[a_coef, 0.5 * b_coef], [0.5 * b_coef, c_coef]])
    values, vectors = np.linalg.eigh(matrix)
    if not np.all(np.isfinite(values)) or values[0] <= 0:
        return None
    semi_major = 1.0 / math.sqrt(values[0])
    semi_minor = 1.0 / math.sqrt(values[1])
    angle = math.degrees(math.atan2(vectors[1, 0], vectors[0, 0]))
    return make_ellipse(cx, cy, 2.0 * semi_major, 2.0 * semi_minor, angle)


def _ellipse_radius(ellipse, theta):
    """Distance from the centre to the outline in each direction ``theta`` (radians)."""
    a = max(ellipse.major * 0.5, 1e-6)
    b = max(ellipse.minor * 0.5, 1e-6)
    relative = theta - math.radians(ellipse.angle_deg)
    return 1.0 / np.sqrt((np.cos(relative) / a) ** 2 + (np.sin(relative) / b) ** 2)


def _polish(xs, ys, gx, gy, ellipse, cos_loose, cos_tol):
    """Least-squares refinement of a model on its own inliers, re-selected each pass.

    A circle model is refitted as a circle. An ellipse model is refitted as
    an ellipse while its inliers span enough of the outline to constrain
    one; otherwise it is kept as it stands rather than collapsed.
    """
    current = ellipse
    is_circle = ellipse.minor >= 0.97 * ellipse.major
    for iteration in range(_POLISH_ITERATIONS):
        band = max(_EDGE_SEARCH_HALF_WIDTH, _EDGE_SEARCH_FRACTION * current.minor * 0.5)
        if iteration == 0:
            band *= 1.5
        tol = cos_loose if iteration == 0 else cos_tol
        keep = _inliers(xs, ys, gx, gy, current, band, tol)
        if keep.sum() < 8:
            return None if iteration == 0 else current
        in_x, in_y = xs[keep], ys[keep]
        if is_circle:
            circle = _fit_circle(in_x, in_y)
            candidate = None if circle is None else make_ellipse(circle[0], circle[1], 2 * circle[2], 2 * circle[2], 0.0)
        elif _angular_span_deg(in_x, in_y, current.cx, current.cy) >= _ELLIPSE_MIN_SPAN_DEG:
            candidate = _fit_ellipse(in_x, in_y)
        else:
            candidate = None
        if candidate is None:
            return current
        moved = math.hypot(candidate.cx - current.cx, candidate.cy - current.cy)
        current = candidate
        if moved < 0.25 and iteration > 0:
            break
    return current


def outline_support(ellipse, mag, ang, angle_tol_deg, contrast_floor, n_samples=_OUTLINE_SAMPLES):
    """How much of an outline is backed by an edge that follows it, and whether that edge curves.

    A sample counts when, within a couple of pixels along the outline's
    normal, some pixel has magnitude above ``contrast_floor`` and an
    orientation within ``angle_tol_deg`` of that normal (either polarity),
    and it lies in a run of such samples at least _MIN_RUN_SAMPLES long.

    Support alone cannot tell a curve from straight edges the outline
    happens to graze: an ellipse inside a rectangle is supported where it
    touches the sides, and a long flat one hugs both sides of a strip. Two
    further measures settle it:

    * ``curvature`` - along each supported stretch, the edge's own
      orientation should turn with the outline's normal. On a straight
      side it stays put while the normal turns, so the residual (edge minus
      normal) falls with slope -1 against the normal angle. ``curvature``
      is 1 plus the stretch-weighted mean slope, clipped to [0, 1]: about 1
      for real curves, about 0 for straight edges, 1 when no stretch turns
      far enough to tell.
    * ``boxiness`` - C4 * (1 - C2) of the supported normals, the
      RectilinearGeometry statistic: they spread smoothly round a curve
      but bunch at four right angles when the support is a box's sides.

    Returns:
        OutlineEvidence
    """
    if ellipse.major <= 0 or ellipse.minor <= 0:
        return OutlineEvidence(0.0, 0.0, 360.0, 0.0, 0.0, 0.0)
    points, normals = ellipse_points(ellipse, n_samples)
    half_width = max(_EDGE_SEARCH_HALF_WIDTH, _EDGE_SEARCH_FRACTION * ellipse.minor * 0.5)
    offsets = np.arange(-math.floor(half_width), math.floor(half_width) + 1, dtype=np.float32)
    xs = points[:, 0:1] + normals[:, 0:1] * offsets[None, :]
    ys = points[:, 1:2] + normals[:, 1:2] * offsets[None, :]
    height, width = mag.shape[:2]
    cols = np.rint(xs).astype(np.int64)
    rows = np.rint(ys).astype(np.int64)
    in_frame = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    cols = np.clip(cols, 0, width - 1)
    rows = np.clip(rows, 0, height - 1)
    sample_mag = mag[rows, cols]
    sample_ang = np.degrees(ang[rows, cols])
    normal_deg = np.degrees(np.arctan2(normals[:, 1], normals[:, 0]))[:, None]
    residual = ((sample_ang - normal_deg + 90.0) % 180.0) - 90.0
    qualifies = (sample_mag >= contrast_floor) & (np.abs(residual) <= angle_tol_deg) & in_frame
    raw_hits = np.any(qualifies, axis=1)
    # Only hits in coherent stretches count. Texture supports scattered
    # samples of any outline by chance (more so the smaller the outline,
    # since the search band is then a larger share of it), but rarely
    # several in a row; a real edge supports long runs.
    bridged = _bridge(raw_hits)
    coherent = np.zeros(n_samples, dtype=bool)
    for run in _circular_runs(bridged):
        if len(run) >= _MIN_RUN_SAMPLES:
            coherent[run] = True
    hits = raw_hits & coherent
    support = float(np.mean(hits))
    arc_deg = 360.0 * _longest_circular_run(coherent) / n_samples
    gap_deg = 360.0 * _longest_circular_run(~coherent) / n_samples

    # The strongest qualifying pixel per supported sample.
    best = np.argmax(np.where(qualifies, sample_mag, -1.0), axis=1)
    rows = np.arange(n_samples)
    best_residual = residual[rows, best]
    strength = float(np.median(sample_mag[rows, best][hits])) if hits.any() else 0.0
    turning = np.degrees(np.unwrap(np.arctan2(normals[:, 1], normals[:, 0]).astype(np.float64)))
    curvature = _curvature_agreement(hits, turning, best_residual)
    return OutlineEvidence(support, arc_deg, gap_deg, _normal_boxiness(normals[hits]), curvature, strength)


def _curvature_agreement(hits, turning_deg, residual_deg):
    """1 + weighted mean slope of residual against normal angle over supported runs, in [0, 1]."""
    slope_sum = 0.0
    weight_sum = 0.0
    for run in _circular_runs(hits):
        if len(run) < 4:
            continue
        # Unwrapped normal angles, continued across the seam of the outline.
        turn = turning_deg[run] + 360.0 * (run < run[0])
        span = float(turn.max() - turn.min())
        if span < _CURVATURE_MIN_TURN_DEG:
            continue
        slope = float(np.polyfit(turn, residual_deg[run], 1)[0])
        slope_sum += slope * span
        weight_sum += span
    if weight_sum <= 0:
        return 1.0
    return float(min(1.0, max(0.0, 1.0 + slope_sum / weight_sum)))


def _normal_boxiness(normals):
    """C4 * (1 - C2) of a set of unit normals (0 when there are none)."""
    if len(normals) == 0:
        return 0.0
    phi = np.arctan2(normals[:, 1], normals[:, 0])
    c4 = math.hypot(float(np.mean(np.cos(4.0 * phi))), float(np.mean(np.sin(4.0 * phi))))
    c2 = math.hypot(float(np.mean(np.cos(2.0 * phi))), float(np.mean(np.sin(2.0 * phi))))
    return float(min(1.0, c4) * (1.0 - min(1.0, c2)))


def _bridge(hits):
    """``hits`` with misses of up to _ARC_GAP_SAMPLES between two hits filled in (circularly)."""
    count = len(hits)
    bridged = hits.copy()
    if count == 0 or _ARC_GAP_SAMPLES <= 0:
        return bridged
    for index in np.flatnonzero(~hits):
        before = any(hits[(index - k) % count] for k in range(1, _ARC_GAP_SAMPLES + 1))
        after = any(hits[(index + k) % count] for k in range(1, _ARC_GAP_SAMPLES + 1))
        if before and after:
            bridged[index] = True
    return bridged


def _circular_runs(mask):
    """Index arrays of each circular run of True in ``mask``."""
    count = len(mask)
    if count == 0 or not mask.any():
        return []
    if mask.all():
        return [np.arange(count)]
    # Start just after a False so no run wraps past the end of the scan.
    start = int(np.flatnonzero(~mask)[0]) + 1
    runs = []
    current = []
    for step in range(count):
        index = (start + step) % count
        if mask[index]:
            current.append(index)
        elif current:
            runs.append(np.array(current))
            current = []
    if current:
        runs.append(np.array(current))
    return runs


def _longest_circular_run(mask):
    """Length of the longest circular run of True in ``mask``."""
    runs = _circular_runs(mask)
    return max((len(run) for run in runs), default=0)


def _scaled(ellipse, factor, pad=0.0):
    """The ellipse with both axes scaled by ``factor`` and then grown by ``pad`` px each side."""
    return Ellipse(
        ellipse.cx, ellipse.cy,
        max(0.0, ellipse.major * factor + 2.0 * pad),
        max(0.0, ellipse.minor * factor + 2.0 * pad),
        ellipse.angle_deg,
    )


def ellipse_polygon(ellipse, count=48):
    """Outline polygon as a float32 (count, 2) array."""
    return ellipse_points(ellipse, count)[0]


def ring_contrast_lab(lab, ellipse, ring_frac):
    """CIE76 colour difference between a band just inside the outline and a ring outside it.

    The inside sample is the band between 60 % and 90 % of the outline rather
    than the whole interior, so a ring-shaped target (a tire, a life ring)
    is measured on its own material, not on the ground showing through its
    middle. Medians are used on both sides so a few edge or shadow pixels do
    not swing the result.

    Args:
        lab (np.ndarray): 8-bit OpenCV LAB image.
        ellipse (Ellipse): Outline to test.
        ring_frac (float): Ring width as a fraction of the minor axis.

    Returns:
        float: Delta E (CIE76), 0 when either region is empty.
    """
    ring_px = max(2.0, ring_frac * ellipse.minor)
    gap_px = 1.5
    inner_outer = _scaled(ellipse, 0.9)
    inner_inner = _scaled(ellipse, 0.6)
    gap = _scaled(ellipse, 1.0, gap_px)
    outer = _scaled(ellipse, 1.0, gap_px + ring_px)
    outer_points = ellipse_polygon(outer)
    height, width = lab.shape[:2]
    x0 = max(0, int(math.floor(outer_points[:, 0].min())))
    y0 = max(0, int(math.floor(outer_points[:, 1].min())))
    x1 = min(width, int(math.ceil(outer_points[:, 0].max())) + 1)
    y1 = min(height, int(math.ceil(outer_points[:, 1].max())) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    roi = lab[y0:y1, x0:x1]
    offset = np.array([x0, y0], dtype=np.float32)
    shape = (y1 - y0, x1 - x0)

    def _mask(e):
        mask = np.zeros(shape, dtype=np.uint8)
        cv2.fillPoly(mask, [np.rint((ellipse_polygon(e) - offset) * 8).astype(np.int32)], 255, shift=3)
        return mask

    inside_mask = cv2.subtract(_mask(inner_outer), _mask(inner_inner))
    if not inside_mask.any():
        inside_mask = _mask(inner_outer)
    ring_mask = cv2.subtract(_mask(outer), _mask(gap))
    inside = roi[inside_mask > 0]
    around = roi[ring_mask > 0]
    if len(inside) == 0 or len(around) == 0:
        return 0.0
    inside_median = np.median(inside.reshape(-1, 3).astype(np.float32), axis=0)
    around_median = np.median(around.reshape(-1, 3).astype(np.float32), axis=0)
    delta = inside_median - around_median
    # OpenCV stores L as L * 255 / 100; a and b are already in CIE units.
    delta[0] *= 100.0 / 255.0
    return float(np.sqrt(np.sum(delta * delta)))


def _ellipse_overlap(ellipse_a, ellipse_b):
    """Intersection area of two ellipses, via their convex polygons."""
    area, _ = cv2.intersectConvexConvex(ellipse_polygon(ellipse_a), ellipse_polygon(ellipse_b))
    return max(0.0, float(area))


def ellipse_area(ellipse):
    """Area enclosed by the outline."""
    return math.pi * ellipse.major * ellipse.minor * 0.25


def ellipse_nms(ellipses, scores, iou_thresh, containment_thresh=0.8):
    """Greedy non-maximum suppression over ellipses.

    A weaker ellipse is dropped when it overlaps a kept one by ``iou_thresh``
    IoU, or when either lies mostly inside the other (``containment_thresh``
    of the smaller one's area): a tire's inner edge, or the end of an oval
    fitted as a circle, is the same object as the outline around it.

    Returns:
        list[int]: Indices of kept ellipses, highest score first.
    """
    order = sorted(range(len(ellipses)), key=lambda k: -scores[k])
    kept = []
    for index in order:
        candidate = ellipses[index]
        candidate_area = ellipse_area(candidate)
        suppressed = False
        for kept_index in kept:
            other = ellipses[kept_index]
            reach = (candidate.major + other.major) * 0.5
            if math.hypot(candidate.cx - other.cx, candidate.cy - other.cy) > reach:
                continue
            other_area = ellipse_area(other)
            inter = _ellipse_overlap(candidate, other)
            union = candidate_area + other_area - inter
            smaller = min(candidate_area, other_area)
            if (union > 0 and inter / union >= iou_thresh) or (smaller > 0 and inter / smaller >= containment_thresh):
                suppressed = True
                break
        if not suppressed:
            kept.append(index)
    return kept
