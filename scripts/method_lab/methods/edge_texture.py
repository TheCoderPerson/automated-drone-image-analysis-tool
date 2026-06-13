"""
edge_texture.py - Edge-density and texture anomaly scoring (pure functions).

People and their gear introduce structure that natural clutter rarely
makes: straight lines (trekking poles, pack frames), regular curves, and
locally smooth fabric patches inside rough natural texture. This module
scores each pixel's neighborhood by how strongly its edge density and
local texture (intensity standard deviation) deviate from the frame's
own statistics, so it adapts to the terrain in view.

Works best over homogeneous backgrounds (grass, snow, scree); rocky or
deadfall-heavy terrain raises the false-positive rate — exactly the
trade-off the Method Lab exists to measure.

Qt-free and deterministic; promotable to a production algorithm plugin.
"""

import cv2
import numpy as np


def edge_density_map(gray_u8, canny_lo=60, canny_hi=180, window=31):
    """Fraction of Canny edge pixels in each pixel's window neighborhood.

    Args:
        gray_u8: 2-D uint8 grayscale image.
        canny_lo: Canny lower hysteresis threshold.
        canny_hi: Canny upper hysteresis threshold.
        window: Box-filter window size in pixels (odd recommended).

    Returns:
        Float32 map in [0, 1].
    """
    edges = cv2.Canny(gray_u8, canny_lo, canny_hi)
    window = max(3, int(window))
    return cv2.boxFilter(edges.astype(np.float32) / 255.0, -1, (window, window))


def local_std_map(gray_u8, window=31):
    """Local intensity standard deviation per window neighborhood.

    Low values inside otherwise rough texture flag smooth patches
    (fabric, tarps); high values flag busy structure.

    Args:
        gray_u8: 2-D uint8 grayscale image.
        window: Box-filter window size in pixels.

    Returns:
        Float32 map of local standard deviations.
    """
    gray = gray_u8.astype(np.float32)
    window = max(3, int(window))
    mean = cv2.boxFilter(gray, -1, (window, window))
    mean_sq = cv2.boxFilter(gray * gray, -1, (window, window))
    variance = np.maximum(mean_sq - (mean * mean), 0.0)
    return np.sqrt(variance)


def edge_texture_score(img_bgr, canny_lo=60, canny_hi=180, window=31):
    """Combined edge/texture anomaly score relative to the frame.

    Each feature map (edge density, local std) is converted to absolute
    z-scores against its own frame-wide distribution; the per-pixel
    maximum of the z-scores is normalized to [0, 1]. A feature that is
    constant across the frame (e.g. zero edges everywhere) contributes
    nothing, so a featureless image scores zero.

    Args:
        img_bgr: BGR image array.
        canny_lo: Canny lower hysteresis threshold.
        canny_hi: Canny upper hysteresis threshold.
        window: Neighborhood window size in pixels.

    Returns:
        Float32 anomaly score map in [0, 1].
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    z_maps = []
    for feature in (edge_density_map(gray, canny_lo, canny_hi, window),
                    local_std_map(gray, window)):
        std = float(feature.std())
        if std > 1e-6:
            z_maps.append(np.abs(feature - float(feature.mean())) / std)

    if not z_maps:
        return np.zeros(gray.shape, np.float32)

    score = np.maximum.reduce(z_maps)
    high = float(score.max())
    if high <= 0:
        return np.zeros(gray.shape, np.float32)
    return (score / high).astype(np.float32)


def edge_texture_mask(img_bgr, canny_lo=60, canny_hi=180, window=31,
                      deviation_percentile=99.5):
    """Threshold the edge/texture anomaly score into a detection mask.

    The threshold is the given percentile of the score distribution with
    an absolute floor of mean + 3 sigma, mirroring the saliency method's
    guard against flagging a uniform frame's noise floor.

    Args:
        img_bgr: BGR image array.
        canny_lo: Canny lower hysteresis threshold.
        canny_hi: Canny upper hysteresis threshold.
        window: Neighborhood window size in pixels.
        deviation_percentile: Score percentile kept as detections
            (clamped to [90, 99.99]).

    Returns:
        (mask, score_map): uint8 mask (0/255) and the float32 score map.
    """
    score = edge_texture_score(img_bgr, canny_lo, canny_hi, window)
    if score.max() <= 0:
        return np.zeros(score.shape, np.uint8), score

    percentile = min(99.99, max(90.0, float(deviation_percentile)))
    threshold = float(np.percentile(score, percentile))
    floor = float(score.mean() + (3.0 * score.std()))
    threshold = max(threshold, floor)

    mask = ((score >= threshold).astype(np.uint8)) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return mask, score
