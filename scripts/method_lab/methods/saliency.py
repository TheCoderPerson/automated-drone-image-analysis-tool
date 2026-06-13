"""
saliency.py - Spectral-residual saliency scoring (pure functions).

Structure-aware anomaly detection for subjects whose color blends into
the environment: the spectral residual of an image's log-amplitude
spectrum highlights regions whose local structure does not fit the
scene's statistics — shapes, smooth patches and geometry that natural
clutter rarely produces.

Implemented directly with cv2.dft rather than cv2.saliency: the OpenCV
contrib implementation resizes input to 64x64 internally, which destroys
small SAR targets on large frames, and the contrib package is not a
declared dependency of ADIAT.

These functions are Qt-free and deterministic; they are the promotable
core for a future SaliencyAnomaly algorithm plugin.
"""

import math

import cv2
import numpy as np

# Per-segment downscale cap before the DFT. Bounds memory and runtime to
# O(segments * WORKING_MAX_DIM^2 log) regardless of input resolution.
WORKING_MAX_DIM = 1024


def sensitivity_percentile(sensitivity):
    """Map a 1..10 sensitivity to the saliency threshold percentile.

    Higher sensitivity keeps a lower percentile and therefore yields more
    detections: 1 -> 99.95 (top 0.05% of pixels), 10 -> 99.50.
    """
    s = min(10, max(1, int(sensitivity)))
    return 99.95 - ((s - 1) * 0.05)


def spectral_residual(gray_f32):
    """Compute the spectral-residual saliency map of one grayscale array.

    Args:
        gray_f32: 2-D float32 array.

    Returns:
        Float32 saliency map of the same shape, min-max normalized to
        [0, 1] (all zeros for a perfectly uniform input).
    """
    # A region with no intensity variance has no salient structure; the
    # DFT of a flat field is pure roundoff, which min-max normalization
    # would otherwise amplify into spurious "saliency".
    if float(gray_f32.std()) < 1e-6:
        return np.zeros(gray_f32.shape, np.float32)

    h, w = gray_f32.shape
    optimal_h = cv2.getOptimalDFTSize(h)
    optimal_w = cv2.getOptimalDFTSize(w)
    padded = cv2.copyMakeBorder(gray_f32, 0, optimal_h - h, 0, optimal_w - w,
                                cv2.BORDER_REFLECT)

    dft = cv2.dft(padded, flags=cv2.DFT_COMPLEX_OUTPUT)
    magnitude, phase = cv2.cartToPolar(dft[..., 0], dft[..., 1])

    log_amplitude = np.log1p(magnitude)
    residual = log_amplitude - cv2.boxFilter(log_amplitude, -1, (3, 3))

    real, imag = cv2.polarToCart(np.expm1(residual), phase)
    back = cv2.idft(np.dstack([real, imag]), flags=cv2.DFT_SCALE)
    saliency = (back[..., 0] ** 2) + (back[..., 1] ** 2)

    saliency = cv2.GaussianBlur(saliency, (9, 9), 2.5)
    saliency = saliency[:h, :w]

    low, high = float(saliency.min()), float(saliency.max())
    if high <= low:
        return np.zeros((h, w), np.float32)
    return ((saliency - low) / (high - low)).astype(np.float32)


def saliency_map(img_bgr, segments=4, working_max_dim=WORKING_MAX_DIM):
    """Compute a full-image saliency map, scored per grid segment.

    Per-segment scoring gives local context: a tan jacket in forest is
    salient within its segment even when the whole frame also contains a
    genuinely salient road. Each segment is downscaled to at most
    working_max_dim before the DFT and its map resized back.

    Args:
        img_bgr: BGR image array.
        segments: Number of grid segments (1, 4, 9, 16, ...).
        working_max_dim: Per-segment downscale cap in pixels.

    Returns:
        Float32 map in [0, 1] with the same height/width as the image,
        each segment normalized independently.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    rows = cols = max(1, int(round(math.sqrt(max(1, int(segments))))))

    out = np.zeros((h, w), np.float32)
    row_height = math.ceil(h / rows)
    col_width = math.ceil(w / cols)
    for i in range(rows):
        for j in range(cols):
            y0, y1 = i * row_height, min((i + 1) * row_height, h)
            x0, x1 = j * col_width, min((j + 1) * col_width, w)
            if y1 <= y0 or x1 <= x0:
                continue
            segment = gray[y0:y1, x0:x1]

            scale = min(1.0, working_max_dim / max(segment.shape))
            if scale < 1.0:
                small = cv2.resize(segment, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA)
            else:
                small = segment
            segment_saliency = spectral_residual(small)
            if scale < 1.0:
                segment_saliency = cv2.resize(segment_saliency,
                                              (x1 - x0, y1 - y0),
                                              interpolation=cv2.INTER_LINEAR)
            out[y0:y1, x0:x1] = segment_saliency
    return out


def saliency_mask(img_bgr, sensitivity=5, segments=4,
                  working_max_dim=WORKING_MAX_DIM):
    """Threshold the saliency map into a binary detection mask.

    The threshold is the sensitivity percentile with an absolute floor of
    mean + 3 sigma per map, so near-uniform scenes (open water, plowed
    field) do not emit their noise floor as detections. Morphological
    open/close kills speckle and joins fragmented blobs.

    Args:
        img_bgr: BGR image array.
        sensitivity: 1..10; higher keeps more pixels.
        segments: Number of grid segments for local scoring.
        working_max_dim: Per-segment downscale cap.

    Returns:
        (mask, score_map): uint8 mask (0/255) and the float32 saliency
        map in [0, 1].
    """
    score = saliency_map(img_bgr, segments, working_max_dim)
    if score.max() <= 0:
        return np.zeros(score.shape, np.uint8), score

    threshold = float(np.percentile(score, sensitivity_percentile(sensitivity)))
    floor = float(score.mean() + (3.0 * score.std()))
    threshold = max(threshold, floor)

    mask = ((score >= threshold).astype(np.uint8)) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return mask, score
