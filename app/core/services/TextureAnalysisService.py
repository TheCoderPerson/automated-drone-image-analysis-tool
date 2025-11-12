import numpy as np
import cv2
from skimage.feature import graycoprops, graycomatrix
from typing import Dict, List, Tuple, Optional


class TextureAnalysisService:
    """
    Service for analyzing texture properties of image regions.
    Uses GLCM (Gray-Level Co-occurrence Matrix) to compute texture features.
    """

    def __init__(self, distances: List[int] = None, angles: List[float] = None, levels: int = 256):
        """
        Initialize texture analysis service.

        Args:
            distances: List of pixel pair distances (default: [1, 2, 3])
            angles: List of angles in radians (default: [0, π/4, π/2, 3π/4])
            levels: Number of gray levels to use (default: 256, reduced to 64 for performance)
        """
        self.distances = distances if distances is not None else [1, 2, 3]
        self.angles = angles if angles is not None else [0, np.pi/4, np.pi/2, 3*np.pi/4]
        self.levels = levels
        self.normalized_levels = 64  # Reduce levels for GLCM performance

    def calculate_texture_features(self, image: np.ndarray, mask: Optional[np.ndarray] = None) -> Dict[str, float]:
        """
        Calculate texture features for an image region.

        Args:
            image: Input image (can be RGB or grayscale)
            mask: Optional binary mask indicating which pixels to analyze

        Returns:
            Dictionary containing texture feature values:
            - contrast: Local variations in the gray-level co-occurrence matrix
            - dissimilarity: Similar to contrast but increases linearly
            - homogeneity: Closeness of distribution to GLCM diagonal
            - energy: Sum of squared elements (uniformity)
            - correlation: Linear dependency of gray levels
            - asm: Angular Second Moment (same as energy)
            - texture_score: Composite score combining all features
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image.copy()

        # Apply mask if provided
        if mask is not None:
            # Create a masked region
            masked_gray = gray * (mask > 0)
            # Get bounding box of mask to reduce computation
            coords = np.argwhere(mask > 0)
            if len(coords) == 0:
                return self._get_empty_features()
            y_min, x_min = coords.min(axis=0)
            y_max, x_max = coords.max(axis=0)

            # Extract region of interest
            roi = masked_gray[y_min:y_max+1, x_min:x_max+1]
            roi_mask = mask[y_min:y_max+1, x_min:x_max+1]

            # Only analyze masked pixels
            if roi_mask.sum() < 4:  # Need minimum pixels for texture analysis
                return self._get_empty_features()
        else:
            roi = gray
            roi_mask = None

        # Normalize to reduced gray levels for performance
        normalized = (roi.astype(float) / self.levels * self.normalized_levels).astype(np.uint8)

        # Calculate GLCM
        try:
            glcm = graycomatrix(
                normalized,
                distances=self.distances,
                angles=self.angles,
                levels=self.normalized_levels,
                symmetric=True,
                normed=True
            )

            # Calculate texture properties
            contrast = graycoprops(glcm, 'contrast').mean()
            dissimilarity = graycoprops(glcm, 'dissimilarity').mean()
            homogeneity = graycoprops(glcm, 'homogeneity').mean()
            energy = graycoprops(glcm, 'energy').mean()
            correlation = graycoprops(glcm, 'correlation').mean()
            asm = graycoprops(glcm, 'ASM').mean()

            # Calculate composite texture score
            # Higher score = more texture variation/complexity
            # Normalized to 0-100 scale
            texture_score = self._calculate_composite_score({
                'contrast': contrast,
                'dissimilarity': dissimilarity,
                'homogeneity': homogeneity,
                'energy': energy,
                'correlation': correlation,
                'asm': asm
            })

            return {
                'contrast': float(contrast),
                'dissimilarity': float(dissimilarity),
                'homogeneity': float(homogeneity),
                'energy': float(energy),
                'correlation': float(correlation),
                'asm': float(asm),
                'texture_score': float(texture_score)
            }
        except Exception as e:
            print(f"Error calculating texture features: {e}")
            return self._get_empty_features()

    def calculate_aoi_textures(self, image: np.ndarray, aoi: Dict) -> Dict[str, Dict[str, float]]:
        """
        Calculate texture features for both detected pixels and full AOI circle.

        Args:
            image: Full image array (RGB or grayscale)
            aoi: Area of Interest dictionary containing:
                - center: (x, y) coordinates
                - radius: circle radius
                - detected_pixels: list of [x, y] coordinates

        Returns:
            Dictionary containing:
            - detected_texture: texture features for detected pixels only
            - aoi_texture: texture features for full AOI circle
            - texture_difference: difference between detected and AOI texture scores
            - texture_ratio: ratio of detected to AOI texture scores
        """
        center = aoi['center']
        radius = aoi['radius']
        detected_pixels = aoi.get('detected_pixels', [])

        # Create mask for detected pixels
        detected_mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
        for pixel in detected_pixels:
            if isinstance(pixel, (list, tuple)) and len(pixel) >= 2:
                px, py = int(pixel[0]), int(pixel[1])
                if 0 <= py < image.shape[0] and 0 <= px < image.shape[1]:
                    detected_mask[py, px] = 255

        # Create mask for full AOI circle
        aoi_mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
        cv2.circle(aoi_mask, (int(center[0]), int(center[1])), int(radius), 255, -1)

        # Calculate textures
        detected_texture = self.calculate_texture_features(image, detected_mask)
        aoi_texture = self.calculate_texture_features(image, aoi_mask)

        # Calculate differences and ratios
        detected_score = detected_texture['texture_score']
        aoi_score = aoi_texture['texture_score']

        texture_difference = detected_score - aoi_score
        texture_ratio = detected_score / aoi_score if aoi_score > 0 else 0

        return {
            'detected_texture': detected_texture,
            'aoi_texture': aoi_texture,
            'texture_difference': texture_difference,
            'texture_ratio': texture_ratio
        }

    def analyze_aoi_batch(self, image: np.ndarray, aois: List[Dict]) -> List[Dict]:
        """
        Analyze texture for multiple AOIs and add texture data to each AOI.

        Args:
            image: Full image array
            aois: List of AOI dictionaries

        Returns:
            Updated list of AOIs with texture data added
        """
        for aoi in aois:
            try:
                texture_data = self.calculate_aoi_textures(image, aoi)
                aoi['texture_data'] = texture_data
            except Exception as e:
                print(f"Error analyzing texture for AOI at {aoi.get('center')}: {e}")
                aoi['texture_data'] = None

        return aois

    def _calculate_composite_score(self, features: Dict[str, float]) -> float:
        """
        Calculate a composite texture score from individual features.

        Higher score indicates more texture complexity/variation.
        Lower score indicates smoother/more uniform texture.

        Args:
            features: Dictionary of texture features

        Returns:
            Composite score (0-100 scale)
        """
        # Normalize and weight features
        # Contrast and dissimilarity indicate texture variation (higher = more texture)
        # Homogeneity and energy indicate uniformity (lower = more texture)
        # Correlation indicates linear relationships

        contrast_norm = min(features['contrast'] / 10.0, 1.0)  # Normalize to 0-1
        dissimilarity_norm = min(features['dissimilarity'] / 5.0, 1.0)
        homogeneity_inv = 1.0 - features['homogeneity']  # Invert so higher = more texture
        energy_inv = 1.0 - features['energy']  # Invert so higher = more texture

        # Weighted average
        score = (
            contrast_norm * 0.3 +
            dissimilarity_norm * 0.3 +
            homogeneity_inv * 0.2 +
            energy_inv * 0.2
        ) * 100

        return score

    def _get_empty_features(self) -> Dict[str, float]:
        """Return empty/zero features for error cases."""
        return {
            'contrast': 0.0,
            'dissimilarity': 0.0,
            'homogeneity': 1.0,
            'energy': 1.0,
            'correlation': 0.0,
            'asm': 1.0,
            'texture_score': 0.0
        }

    @staticmethod
    def filter_aois_by_texture(aois: List[Dict],
                               min_difference: Optional[float] = None,
                               min_ratio: Optional[float] = None,
                               max_ratio: Optional[float] = None) -> List[Dict]:
        """
        Filter AOIs based on texture criteria.

        This can help remove false positives by filtering out detections
        that have similar texture to their surroundings.

        Args:
            aois: List of AOIs with texture_data
            min_difference: Minimum texture_difference (detected - aoi)
            min_ratio: Minimum texture_ratio (detected / aoi)
            max_ratio: Maximum texture_ratio (detected / aoi)

        Returns:
            Filtered list of AOIs
        """
        filtered = []

        for aoi in aois:
            if 'texture_data' not in aoi or aoi['texture_data'] is None:
                # Keep AOIs without texture data
                filtered.append(aoi)
                continue

            texture_data = aoi['texture_data']
            difference = texture_data['texture_difference']
            ratio = texture_data['texture_ratio']

            # Apply filters
            if min_difference is not None and difference < min_difference:
                continue
            if min_ratio is not None and ratio < min_ratio:
                continue
            if max_ratio is not None and ratio > max_ratio:
                continue

            filtered.append(aoi)

        return filtered
