"""ShadowMatcher - measure the shadow cast beside an AOI.

The corroboration engine of Phase 2. For an AOI another algorithm found, the
matcher segments the image band running anti-solar from the AOI, auto-detects
the shadow tip, and feeds the (base, tip) pixel pair into the existing
ShadowHeightEstimator. The result is a subject-independent ShadowDescriptor.

In short: this is ShadowHeightEstimator with the shadow tip found
automatically instead of clicked.
"""

from __future__ import annotations

import math
import traceback
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

from core.services.LoggerService import LoggerService
from core.services.shadow.ShadowDescriptor import (
    ShadowDescriptor,
    STATUS_NO_SHADOW,
    STATUS_OK,
    STATUS_UNMEASURABLE,
)
from core.services.shadow.ShadowGeometry import anti_solar_image_direction
from core.services.shadow.ShadowHeightEstimator import (
    ShadowHeightEstimator,
    MIN_SUN_ELEV_DEG,
    MAX_SUN_ELEV_DEG,
)
from core.services.shadow.ShadowImageContext import build_shadow_context
from core.services.shadow.ShadowSegmenter import ShadowSegmenter


# Tallest subject the search window is sized for; the band is extended past the
# shadow such a subject would cast so a real shadow is never clipped.
MAX_SUBJECT_HEIGHT_M = 2.5
SEARCH_MARGIN = 1.3
# Fallback search length, as a fraction of the image diagonal, when the camera
# geometry cannot give a metric bound.
DEFAULT_MAX_LEN_FRACTION = 0.35
# A shadow must begin within this fraction of the search length of the AOI to
# count as "attached" to it.
ATTACH_TOLERANCE_FRACTION = 0.25
MIN_ATTACH_TOLERANCE_PX = 25.0
# The search band is the base->tip strip expanded by this margin for width.
ROI_MARGIN_FRACTION = 0.4
MIN_ROI_MARGIN_PX = 15.0
# Floor on the search length so the ROI is never degenerate.
MIN_SEARCH_LEN_PX = 20.0


@dataclass
class ShadowBlob:
    """A shadow region located along the anti-solar ray from an AOI.

    Coordinates are in the frame of the mask passed to locate_shadow().
    """

    tip: Tuple[float, float]
    length_px: float
    width_px: float
    attached: bool
    pixel_rows: np.ndarray
    pixel_cols: np.ndarray


def locate_shadow(mask, base, direction, max_len_px, attach_tol_px) -> Optional[ShadowBlob]:
    """Find the shadow region running anti-solar from a base pixel.

    Walks the anti-solar ray from `base` until it enters a shadow-mask blob,
    then analyses that whole connected component. Walking the ray is the
    anti-solar constraint - a dark blob off to the side is never picked up.

    Args:
        mask: uint8 binary shadow mask (255 = shadow).
        base: (x, y) ray origin, in mask coordinates.
        direction: (dx, dy) anti-solar unit vector in image space.
        max_len_px: how far along the ray to search.
        attach_tol_px: the blob counts as attached when the ray reaches it
            within this distance of the base.

    Returns:
        a ShadowBlob, or None when no shadow lies along the ray.
    """
    height, width = mask.shape[:2]
    _, labels = cv2.connectedComponents(mask)

    shadow_label = 0
    attach_distance = None
    distance = 1.0
    while distance <= max_len_px:
        x = int(round(base[0] + distance * direction[0]))
        y = int(round(base[1] + distance * direction[1]))
        if 0 <= x < width and 0 <= y < height:
            label = labels[y, x]
            if label != 0:
                shadow_label = label
                attach_distance = distance
                break
        distance += 1.0

    if shadow_label == 0:
        return None

    rows, cols = np.where(labels == shadow_label)
    rel_x = cols.astype(np.float64) - base[0]
    rel_y = rows.astype(np.float64) - base[1]
    # Projection along, and perpendicular to, the anti-solar direction.
    along = rel_x * direction[0] + rel_y * direction[1]
    across = -rel_x * direction[1] + rel_y * direction[0]

    tip_index = int(np.argmax(along))
    tip = (float(cols[tip_index]), float(rows[tip_index]))
    length_px = float(along.max())
    width_px = float(across.max() - across.min())
    attached = attach_distance is not None and attach_distance <= attach_tol_px

    return ShadowBlob(
        tip=tip,
        length_px=length_px,
        width_px=width_px,
        attached=attached,
        pixel_rows=rows,
        pixel_cols=cols,
    )


class ShadowMatcher:
    """Measure the shadow beside an AOI and describe it subject-independently."""

    def __init__(self, segmenter: Optional[ShadowSegmenter] = None,
                 estimator: Optional[ShadowHeightEstimator] = None,
                 logger: Optional[LoggerService] = None):
        """
        Args:
            segmenter: ShadowSegmenter used to threshold the search band.
            estimator: ShadowHeightEstimator used to turn the (base, tip)
                pair into an implied height. Injectable for testing.
            logger: optional LoggerService.
        """
        self.segmenter = segmenter or ShadowSegmenter()
        self.estimator = estimator or ShadowHeightEstimator()
        self.logger = logger or LoggerService()

    def measure(self, image: dict, aoi: dict, context=None) -> ShadowDescriptor:
        """Measure the shadow cast beside one AOI.

        Never raises: any failure yields an 'unmeasurable' descriptor so a
        batch annotation pass is not interrupted.

        Args:
            image: the ADIAT image-metadata dict.
            aoi: the AOI dict (must have 'center').
            context: an optional pre-built ShadowImageContext; one is built
                when omitted.

        Returns:
            a ShadowDescriptor for the AOI.
        """
        try:
            if context is None:
                context = build_shadow_context(image)
            if not context.is_valid():
                return self._unmeasurable(
                    context.error or "Image metadata unavailable.", context
                )

            sun_elev = context.sun_elevation_deg
            sun_az = context.sun_azimuth_deg
            if sun_elev < MIN_SUN_ELEV_DEG:
                return self._unmeasurable(
                    f"Sun too low ({sun_elev:.1f} deg) for a usable shadow.", context
                )
            if sun_elev > MAX_SUN_ELEV_DEG:
                return self._unmeasurable(
                    f"Sun nearly overhead ({sun_elev:.1f} deg); shadow too short.",
                    context,
                )

            base = (float(aoi['center'][0]), float(aoi['center'][1]))
            direction = anti_solar_image_direction(context.camera, base, sun_az)
            if direction is None:
                return self._unmeasurable(
                    "Could not project the anti-solar direction at this AOI.", context
                )

            img_h, img_w = context.img_bgr.shape[:2]
            max_len = self._search_length(context.camera, base, sun_elev, sun_az,
                                          img_w, img_h)

            blob, patch_origin, lightness = self._locate(
                context.img_bgr, base, direction, max_len, img_w, img_h
            )
            if blob is None:
                return ShadowDescriptor(
                    status=STATUS_NO_SHADOW,
                    attached=False,
                    sun_elevation_deg=sun_elev,
                    sun_azimuth_deg=sun_az,
                    detail="No shadow found along the anti-solar direction.",
                )

            tip = (blob.tip[0] + patch_origin[0], blob.tip[1] + patch_origin[1])
            contrast = self._contrast(lightness, blob)

            result = self.estimator.estimate(image, base, tip, context=context)
            if result.confidence == 'rejected':
                return ShadowDescriptor(
                    status=STATUS_UNMEASURABLE,
                    shadow_contrast=contrast,
                    attached=blob.attached,
                    sun_elevation_deg=sun_elev,
                    sun_azimuth_deg=sun_az,
                    detail=result.rejection_reason or "Shadow geometry rejected.",
                )

            return ShadowDescriptor(
                status=STATUS_OK,
                implied_height_m=result.height_m,
                sigma_m=result.sigma_m,
                azimuth_residual_deg=result.delta_az_deg,
                shadow_contrast=contrast,
                attached=blob.attached,
                sun_elevation_deg=sun_elev,
                sun_azimuth_deg=sun_az,
            )
        except Exception as exc:
            self.logger.error(traceback.format_exc())
            return self._unmeasurable(f"Shadow measurement error: {exc}", context)

    @staticmethod
    def _unmeasurable(detail: str, context) -> ShadowDescriptor:
        """Build an 'unmeasurable' descriptor, keeping sun angles if known."""
        sun_elev = getattr(context, 'sun_elevation_deg', None) if context else None
        sun_az = getattr(context, 'sun_azimuth_deg', None) if context else None
        return ShadowDescriptor(
            status=STATUS_UNMEASURABLE,
            attached=False,
            sun_elevation_deg=sun_elev,
            sun_azimuth_deg=sun_az,
            detail=detail,
        )

    @staticmethod
    def _search_length(camera, base, sun_elev_deg, sun_az_deg, img_w, img_h) -> float:
        """How far (px) along the anti-solar ray to search for the shadow."""
        diagonal = math.hypot(img_w, img_h)
        fallback = DEFAULT_MAX_LEN_FRACTION * diagonal
        try:
            ground = camera.pixel_to_ground(base[0], base[1])
            if ground is None:
                return max(fallback, MIN_SEARCH_LEN_PX)
            north, east, down = ground
            length_m = (MAX_SUBJECT_HEIGHT_M * SEARCH_MARGIN) / math.tan(
                math.radians(sun_elev_deg)
            )
            anti = math.radians(sun_az_deg + 180.0)
            far = camera.project(
                north + length_m * math.cos(anti),
                east + length_m * math.sin(anti),
                down,
            )
            if far is None:
                return max(fallback, MIN_SEARCH_LEN_PX)
            length_px = math.hypot(far[0] - base[0], far[1] - base[1])
            length_px = min(length_px, diagonal)
            return max(length_px, MIN_SEARCH_LEN_PX)
        except Exception:
            return max(fallback, MIN_SEARCH_LEN_PX)

    def _locate(self, img_bgr, base, direction, max_len, img_w, img_h):
        """Segment the search band and locate the shadow blob.

        Returns:
            (blob, patch_origin, lightness) where patch_origin is the (x, y)
            offset of the search patch in the full image and lightness is the
            patch LAB-L channel. blob is None when no shadow is found.
        """
        far_x = base[0] + max_len * direction[0]
        far_y = base[1] + max_len * direction[1]
        margin = max(MIN_ROI_MARGIN_PX, ROI_MARGIN_FRACTION * max_len)

        x0 = int(max(0, math.floor(min(base[0], far_x) - margin)))
        y0 = int(max(0, math.floor(min(base[1], far_y) - margin)))
        x1 = int(min(img_w, math.ceil(max(base[0], far_x) + margin)))
        y1 = int(min(img_h, math.ceil(max(base[1], far_y) + margin)))
        if x1 - x0 < 3 or y1 - y0 < 3:
            return None, (0, 0), None

        patch = img_bgr[y0:y1, x0:x1]
        mask = self.segmenter.segment(patch)
        lightness = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)[:, :, 0]

        base_in_patch = (base[0] - x0, base[1] - y0)
        attach_tol = max(MIN_ATTACH_TOLERANCE_PX, ATTACH_TOLERANCE_FRACTION * max_len)
        blob = locate_shadow(mask, base_in_patch, direction, max_len, attach_tol)
        return blob, (x0, y0), lightness

    @staticmethod
    def _contrast(lightness, blob: ShadowBlob) -> float:
        """How much darker the shadow blob is than the sunlit background, 0-1."""
        shadow_mean = float(np.mean(lightness[blob.pixel_rows, blob.pixel_cols]))
        background = float(np.percentile(lightness, 75))
        if background <= 1.0:
            return 0.0
        return float(np.clip(1.0 - shadow_mean / background, 0.0, 1.0))
