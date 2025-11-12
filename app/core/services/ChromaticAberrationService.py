"""
Service for detecting and removing chromatic aberrations from images.

Chromatic aberration (CA) is a lens defect that causes color fringing around
high-contrast edges, typically appearing as purple, magenta, or cyan halos.
This service provides methods to detect and remove these artifacts.
"""

import cv2
import numpy as np
from typing import Tuple, Optional


class ChromaticAberrationService:
    """Service for detecting and removing chromatic aberration artifacts."""

    # Common chromatic aberration hue ranges in HSV (hue is 0-180 in OpenCV)
    CA_HUE_RANGES = [
        (135, 165),  # Purple to magenta (270-330° mapped to 0-180 scale)
        (85, 105),   # Cyan to light blue (170-210° mapped to 0-180 scale)
    ]

    # Minimum saturation for CA detection (0-255)
    CA_MIN_SATURATION = 76  # ~0.3 * 255

    def __init__(self, sensitivity: float = 1.0):
        """
        Initialize the ChromaticAberrationService.

        Args:
            sensitivity: Detection sensitivity (0.5 = low, 1.0 = normal, 2.0 = high).
                        Higher values detect more CA but may include legitimate colors.
        """
        self.sensitivity = sensitivity

    def remove_chromatic_aberration(
        self,
        image: np.ndarray,
        method: str = "desaturate",
        edge_threshold: int = 50
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Remove chromatic aberration from an image.

        Args:
            image: Input image in BGR format (OpenCV default).
            method: Removal method - "desaturate", "replace", or "both".
                   - "desaturate": Convert CA pixels to grayscale
                   - "replace": Replace with interpolated values from neighbors
                   - "both": Apply desaturation then replacement
            edge_threshold: Canny edge detection threshold (higher = fewer edges detected).

        Returns:
            Tuple of (corrected_image, mask) where mask shows detected CA pixels (255 = CA).
        """
        if image is None or image.size == 0:
            raise ValueError("Invalid input image")

        # Detect edges using Canny edge detector
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, edge_threshold, edge_threshold * 2)

        # Dilate edges slightly to include fringing pixels
        kernel = np.ones((3, 3), np.uint8)
        edges_dilated = cv2.dilate(edges, kernel, iterations=1)

        # Convert to HSV for color analysis
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Create mask for chromatic aberration pixels
        ca_mask = self._detect_ca_pixels(hsv, edges_dilated)

        # Apply correction based on method
        corrected = image.copy()

        if method in ("desaturate", "both"):
            corrected = self._desaturate_ca_pixels(corrected, ca_mask)

        if method in ("replace", "both"):
            corrected = self._replace_ca_pixels(corrected, ca_mask)

        return corrected, ca_mask

    def _detect_ca_pixels(self, hsv_image: np.ndarray, edge_mask: np.ndarray) -> np.ndarray:
        """
        Detect chromatic aberration pixels based on color and edge proximity.

        Args:
            hsv_image: Image in HSV color space.
            edge_mask: Binary mask of detected edges.

        Returns:
            Binary mask where 255 = likely CA pixel, 0 = normal pixel.
        """
        h, s, v = cv2.split(hsv_image)
        ca_mask = np.zeros(h.shape, dtype=np.uint8)

        # Adjust saturation threshold based on sensitivity
        sat_threshold = int(self.CA_MIN_SATURATION / self.sensitivity)

        for hue_min, hue_max in self.CA_HUE_RANGES:
            # Create mask for pixels in this hue range with sufficient saturation
            hue_mask = cv2.inRange(h, hue_min, hue_max)
            sat_mask = s > sat_threshold

            # Combine hue and saturation conditions
            color_mask = cv2.bitwise_and(hue_mask, sat_mask.astype(np.uint8) * 255)

            # Only consider pixels near edges
            edge_color_mask = cv2.bitwise_and(color_mask, edge_mask)

            # Add to cumulative CA mask
            ca_mask = cv2.bitwise_or(ca_mask, edge_color_mask)

        return ca_mask

    def _desaturate_ca_pixels(self, image: np.ndarray, ca_mask: np.ndarray) -> np.ndarray:
        """
        Desaturate chromatic aberration pixels by converting to grayscale.

        Args:
            image: Input image in BGR format.
            ca_mask: Binary mask of CA pixels.

        Returns:
            Image with CA pixels desaturated.
        """
        result = image.copy()

        # Convert image to grayscale to get luminance values
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Replace CA pixels with their grayscale values
        ca_pixels = ca_mask > 0
        result[ca_pixels] = cv2.merge([gray, gray, gray])[ca_pixels]

        return result

    def _replace_ca_pixels(self, image: np.ndarray, ca_mask: np.ndarray) -> np.ndarray:
        """
        Replace chromatic aberration pixels with interpolated values from neighbors.

        Uses OpenCV's inpainting to fill CA pixels based on surrounding colors.

        Args:
            image: Input image in BGR format.
            ca_mask: Binary mask of CA pixels.

        Returns:
            Image with CA pixels replaced.
        """
        # Use inpainting to fill CA regions based on surrounding pixels
        # INPAINT_TELEA is fast and works well for small regions
        result = cv2.inpaint(image, ca_mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)

        return result

    def is_likely_ca_artifact(
        self,
        hue: float,
        saturation: float,
        area: int,
        aspect_ratio: float
    ) -> bool:
        """
        Determine if an AOI is likely a chromatic aberration artifact.

        Args:
            hue: Hue value in degrees (0-360).
            saturation: Saturation value (0-1).
            area: Pixel area of the AOI.
            aspect_ratio: Width/height ratio of the AOI's bounding box.

        Returns:
            True if the AOI matches CA characteristics.
        """
        # Convert hue from 0-360° to 0-180° (OpenCV HSV format)
        hue_cv = int(hue / 2)

        # Check if hue matches common CA colors
        hue_matches = False
        for hue_min, hue_max in self.CA_HUE_RANGES:
            if hue_min <= hue_cv <= hue_max:
                hue_matches = True
                break

        # Adjust thresholds based on sensitivity
        sat_threshold = 0.3 / self.sensitivity
        max_area = int(500 * self.sensitivity)
        min_aspect_ratio = 2.0 / self.sensitivity

        # CA characteristics:
        # - Hue in purple/magenta or cyan range
        # - High saturation
        # - Small area
        # - Elongated shape (high aspect ratio) typical of edge fringing
        is_ca = (
            hue_matches and
            saturation > sat_threshold and
            area < max_area and
            aspect_ratio > min_aspect_ratio
        )

        return is_ca

    def apply_lateral_correction(
        self,
        image: np.ndarray,
        strength: float = 1.0
    ) -> np.ndarray:
        """
        Apply lateral chromatic aberration correction by realigning color channels.

        This corrects the misalignment of RGB channels that causes colored halos,
        particularly toward image edges.

        Args:
            image: Input image in BGR format.
            strength: Correction strength (0.0 = none, 1.0 = full, 2.0 = strong).
                     Higher values apply more aggressive correction.

        Returns:
            Corrected image with realigned color channels.
        """
        if strength <= 0:
            return image.copy()

        height, width = image.shape[:2]
        center_x, center_y = width / 2, height / 2

        # Split channels
        b, g, r = cv2.split(image)

        # Calculate radial scaling factors
        # Blue channel typically has more aberration, red less
        # We'll scale channels radially from the center
        scale_b = 1.0 + (0.002 * strength)  # Expand blue slightly
        scale_r = 1.0 - (0.002 * strength)  # Contract red slightly

        # Create transformation matrices for each channel
        # These apply radial scaling from the image center
        def create_radial_map(scale: float):
            """Create a radial transformation map for a given scale factor."""
            # Create coordinate grids
            y_coords, x_coords = np.mgrid[0:height, 0:width].astype(np.float32)

            # Calculate offsets from center
            dx = x_coords - center_x
            dy = y_coords - center_y

            # Apply radial scaling
            x_coords = center_x + dx * scale
            y_coords = center_y + dy * scale

            return x_coords, y_coords

        # Apply transformations
        x_map_b, y_map_b = create_radial_map(scale_b)
        x_map_r, y_map_r = create_radial_map(scale_r)

        # Remap channels
        b_corrected = cv2.remap(b, x_map_b, y_map_b, cv2.INTER_LINEAR)
        r_corrected = cv2.remap(r, x_map_r, y_map_r, cv2.INTER_LINEAR)

        # Merge corrected channels
        corrected = cv2.merge([b_corrected, g, r_corrected])

        return corrected
