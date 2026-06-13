"""
adapters.py - Uniform run interface over experimental and baseline methods.

Every method, whether a new pure function from method_lab.methods or a
production AlgorithmService, is exposed as
    run_xxx(img_bgr, image_path, params) -> LabResult
so the lab window can treat them identically. Baselines call the real
production process_image() into a temporary output directory and read
the written mask back, so the comparison is faithful to what an actual
analysis run would produce.

ADIAT service imports are deferred into the runner functions: importing
this module needs only numpy/cv2, which keeps the pure-function tests
and the lab bootstrap light.
"""

import os
import time
import colorsys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from method_lab.methods.saliency import saliency_mask
from method_lab.methods.edge_texture import edge_texture_mask


@dataclass
class LabResult:
    """Outcome of running one method on one image."""
    method: str
    mask: np.ndarray = None          # uint8 0/255 detection mask, or None
    aois: list = field(default_factory=list)   # dicts with 'center'/'radius'
    score_map: np.ndarray = None     # float32 [0, 1] heatmap, or None
    elapsed_s: float = 0.0
    error: str = None


def mask_to_aois(mask, min_area=10, max_area=0, aoi_radius=15):
    """Convert a binary mask to AOI dicts (min enclosing circles).

    Mirrors the shape of production AOIs ('center', 'radius', 'area') so
    the lab renders experimental and baseline results identically.

    Args:
        mask: uint8 mask (0/255).
        min_area: Minimum contour area in pixels.
        max_area: Maximum contour area in pixels (0 = unlimited).
        aoi_radius: Radius padding added to each enclosing circle.

    Returns:
        List of AOI dicts.
    """
    if mask is None or not mask.any():
        return []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    aois = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        if max_area and area > max_area:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        aois.append({
            'center': (int(x), int(y)),
            'radius': int(radius) + int(aoi_radius),
            'area': float(area),
        })
    return aois


# --------------------------------------------------------------------- #
#  Experimental methods (pure functions, in-process)
# --------------------------------------------------------------------- #

def run_saliency(img_bgr, image_path, params):
    """Spectral-residual saliency."""
    start = time.perf_counter()
    try:
        mask, score = saliency_mask(
            img_bgr,
            sensitivity=params.get('sensitivity', 5),
            segments=params.get('segments', 4),
        )
        aois = mask_to_aois(mask, params.get('min_area', 10),
                            params.get('max_area', 0), params.get('aoi_radius', 15))
        return LabResult('Saliency', mask=mask, aois=aois, score_map=score,
                         elapsed_s=time.perf_counter() - start)
    except Exception as e:
        return LabResult('Saliency', error=str(e),
                         elapsed_s=time.perf_counter() - start)


def run_edge_texture(img_bgr, image_path, params):
    """Edge-density / texture anomaly."""
    start = time.perf_counter()
    try:
        mask, score = edge_texture_mask(
            img_bgr,
            canny_lo=params.get('canny_lo', 60),
            canny_hi=params.get('canny_hi', 180),
            window=params.get('window', 31),
            deviation_percentile=params.get('deviation_percentile', 99.5),
        )
        aois = mask_to_aois(mask, params.get('min_area', 10),
                            params.get('max_area', 0), params.get('aoi_radius', 15))
        return LabResult('Edge/Texture', mask=mask, aois=aois, score_map=score,
                         elapsed_s=time.perf_counter() - start)
    except Exception as e:
        return LabResult('Edge/Texture', error=str(e),
                         elapsed_s=time.perf_counter() - start)


# --------------------------------------------------------------------- #
#  Production baselines (real AlgorithmService.process_image)
# --------------------------------------------------------------------- #

# Identifier color is irrelevant in the lab (we draw our own overlays)
# but the service constructors require one.
_IDENTIFIER = (255, 0, 255)


def _run_service(method_name, service, img_bgr, image_path):
    """Run a production service into a tempdir and read back its mask."""
    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix='method_lab_') as output_dir:
            input_dir = os.path.dirname(image_path) or '.'
            result = service.process_image(img_bgr.copy(), image_path,
                                           input_dir, output_dir)
            elapsed = time.perf_counter() - start
            if result.error_message:
                return LabResult(method_name, error=result.error_message,
                                 elapsed_s=elapsed)

            mask = None
            if result.output_path:
                mask_path = Path(output_dir) / result.output_path
                mask_path = mask_path.with_suffix('.tif')
                if mask_path.is_file():
                    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)

            return LabResult(method_name, mask=mask,
                             aois=result.areas_of_interest or [],
                             elapsed_s=elapsed)
    except Exception as e:
        return LabResult(method_name, error=str(e),
                         elapsed_s=time.perf_counter() - start)


def run_rx(img_bgr, image_path, params):
    """RX Anomaly baseline (production service)."""
    from algorithms.images.RXAnomaly.services.RXAnomalyService import RXAnomalyService
    service = RXAnomalyService(
        _IDENTIFIER, params.get('min_area', 10), params.get('max_area', 0),
        params.get('aoi_radius', 15), True,
        {'sensitivity': params.get('sensitivity', 5),
         'segments': params.get('segments', 4)},
    )
    return _run_service('RX Anomaly', service, img_bgr, image_path)


def run_mrmap(img_bgr, image_path, params):
    """MRMap baseline (production service)."""
    from algorithms.images.MRMap.services.MRMapService import MRMapService
    service = MRMapService(
        _IDENTIFIER, params.get('min_area', 10), params.get('max_area', 0),
        params.get('aoi_radius', 15), True,
        {'threshold': params.get('threshold', 100),
         'segments': params.get('segments', 4),
         'window': params.get('window', 5),
         'colorspace': params.get('colorspace', 'LAB')},
    )
    return _run_service('MRMap', service, img_bgr, image_path)


def run_hsv(img_bgr, image_path, params):
    """HSV color range baseline (production service, legacy window options).

    The hsv_window option format takes hue in degrees (0-360) and
    saturation/value in percent (0-100), matching the lab's sliders.
    """
    from algorithms.images.HSVColorRange.services.HSVColorRangeService import HSVColorRangeService
    h_min, h_max = params.get('h_min', 0), params.get('h_max', 30)
    s_min, s_max = params.get('s_min', 30), params.get('s_max', 100)
    v_min, v_max = params.get('v_min', 20), params.get('v_max', 100)
    # The legacy hsv_window path scores confidence against a reference
    # color; supply the window-center color so the service has one.
    center_rgb = _hsv_window_center_rgb(h_min, h_max, s_min, s_max, v_min, v_max)
    service = HSVColorRangeService(
        _IDENTIFIER, params.get('min_area', 10), params.get('max_area', 0),
        params.get('aoi_radius', 15), True,
        {'selected_color': center_rgb,
         'hsv_window': {
            'h_min': h_min, 'h_max': h_max,
            's_min': s_min, 's_max': s_max,
            'v_min': v_min, 'v_max': v_max,
         }},
    )
    return _run_service('HSV Range', service, img_bgr, image_path)


def _hsv_window_center_rgb(h_min, h_max, s_min, s_max, v_min, v_max):
    """RGB (0-255) of an HSV window's center (hue deg, sat/val percent)."""
    hue = ((h_min + h_max) / 2.0) % 360
    sat = (s_min + s_max) / 2.0
    val = (v_min + v_max) / 2.0
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, sat / 100.0, val / 100.0)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def run_ai(img_bgr, image_path, params):
    """AI person detector at an arbitrary (possibly very low) confidence.

    Evaluates the "AI as recall-maximizing prefilter" idea: drop the
    confidence floor, accept the false positives, and judge whether the
    candidate density is human-triageable. The ONNX model is loaded per
    run; expect a model-load pause on the first run.
    """
    from algorithms.images.AIPersonDetector.services.AIPersonDetectorService import AIPersonDetectorService
    service = AIPersonDetectorService(
        _IDENTIFIER, params.get('min_area', 10), params.get('max_area', 0),
        params.get('aoi_radius', 15), True,
        {'person_detector_confidence': params.get('confidence_pct', 10),
         'cpu_only': params.get('cpu_only', False)},
    )
    return _run_service('AI Person', service, img_bgr, image_path)
