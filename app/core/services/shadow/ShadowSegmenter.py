"""ShadowSegmenter - classify shadow pixels in a small image patch.

The shadow-detection side of the matcher: given a BGR patch cropped around an
AOI, produce a binary mask marking pixels that are likely in shadow. A cast
shadow is darker than the sunlit ground around it, so the default strategy
thresholds lightness relative to the patch's sunlit background instead of
using a fixed cutoff.

Deliberately self-contained - pixels in, mask out, with no dependency on the
rest of the shadow pipeline - so the strategy can be tuned or swapped without
touching ShadowMatcher.
"""

from __future__ import annotations

import cv2
import numpy as np


# Segmentation strategies accepted by ShadowSegmenter.
METHOD_RELATIVE = 'relative'
METHOD_OTSU = 'otsu'


class ShadowSegmenter:
    """Threshold a BGR image patch into a binary shadow mask.

    Parameters are fixed at construction; segment() holds no other state, so
    one instance can be reused across every patch of a run.
    """

    def __init__(self, method: str = METHOD_RELATIVE, darkness_ratio: float = 0.65,
                 background_percentile: float = 70.0, morph_kernel: int = 3):
        """
        Args:
            method: 'relative' thresholds against the sunlit background
                lightness; 'otsu' uses an automatic bimodal split.
            darkness_ratio: ('relative' only) a pixel is shadow when its
                lightness falls below this fraction of the background.
            background_percentile: ('relative' only) percentile of patch
                lightness taken to represent the sunlit background.
            morph_kernel: side length (px) of the morphological cleanup
                kernel; 0 or less disables cleanup.

        Raises:
            ValueError: method is not a recognised strategy.
        """
        if method not in (METHOD_RELATIVE, METHOD_OTSU):
            raise ValueError(f"Unknown segmentation method: {method!r}")
        self.method = method
        self.darkness_ratio = float(darkness_ratio)
        self.background_percentile = float(background_percentile)
        self.morph_kernel = int(morph_kernel)

    def segment(self, patch) -> np.ndarray:
        """Return a binary shadow mask for an image patch.

        Args:
            patch: a 3-channel BGR array, or a 2-D array already representing
                lightness.

        Returns:
            uint8 mask the same height and width as patch; 255 = shadow.

        Raises:
            ValueError: patch is None or empty.
        """
        if patch is None:
            raise ValueError("ShadowSegmenter.segment: patch is None")
        if getattr(patch, 'size', 0) == 0:
            raise ValueError("ShadowSegmenter.segment: patch is empty")

        lightness = self._lightness(patch)
        # A light blur stops single-pixel sensor noise from fragmenting the
        # mask without noticeably smearing the shadow boundary.
        lightness = cv2.GaussianBlur(lightness, (3, 3), 0)

        if self.method == METHOD_OTSU:
            _, mask = cv2.threshold(
                lightness, 0, 255,
                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
            )
        else:
            background = np.percentile(lightness, self.background_percentile)
            threshold = self.darkness_ratio * background
            mask = np.where(lightness < threshold, 255, 0).astype(np.uint8)

        return self._cleanup(mask)

    @staticmethod
    def _lightness(patch) -> np.ndarray:
        """Extract a single-channel uint8 lightness image from a patch."""
        if patch.ndim == 2:
            return patch.astype(np.uint8, copy=False)
        # LAB L tracks perceived lightness better than a plain BGR average,
        # which helps keep merely saturated ground colour out of the mask.
        lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)
        return lab[:, :, 0]

    def _cleanup(self, mask: np.ndarray) -> np.ndarray:
        """Open then close the mask to drop speckle and fill small gaps."""
        if self.morph_kernel <= 0:
            return mask
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (self.morph_kernel, self.morph_kernel)
        )
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
        return closed
