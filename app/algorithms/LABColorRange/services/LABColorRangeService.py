import numpy as np
import cv2

from helpers.ColorUtils import ColorUtils
from algorithms.AlgorithmService import AlgorithmService, AnalysisResult
from core.services.LoggerService import LoggerService


class LABColorRangeService(AlgorithmService):
    def __init__(self, identifier, min_area, max_area, aoi_radius, combine_aois, options):
        self.logger = LoggerService()
        super().__init__('LABColorRange', identifier, min_area, max_area, aoi_radius, combine_aois, options)

        self.target_color_lab = None
        selected_color = self.options.get('selected_color')
        if selected_color is not None:
            # Ensure shape (1,1,3) for cv2.cvtColor
            rgb_color = np.uint8([[selected_color]])
            # Convert RGB to LAB
            self.target_color_lab = cv2.cvtColor(rgb_color, cv2.COLOR_RGB2LAB)[0][0]

    def process_image(self, img, full_path, input_dir, output_dir):
        try:
            if self.target_color_lab is None:
                return AnalysisResult(full_path, error_message="No color selected for LAB Filter")

            # Convert the image from BGR to LAB color space
            lab_image = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)

            # Check if we have LAB ranges data
            lab_ranges = self.options.get('lab_ranges')
            if lab_ranges:
                # Use precise LAB ranges from the new picker
                l, a, b = lab_ranges['l'], lab_ranges['a'], lab_ranges['b']
                l_minus, l_plus = lab_ranges['l_minus'], lab_ranges['l_plus']
                a_minus, a_plus = lab_ranges['a_minus'], lab_ranges['a_plus']
                b_minus, b_plus = lab_ranges['b_minus'], lab_ranges['b_plus']

                # Calculate bounds in OpenCV format (L: 0-255, A: 0-255, B: 0-255)
                # L is normalized 0-1 in our picker, maps to 0-255 in OpenCV
                l_center = int(l * 255)
                # A and B are normalized -1 to 1 in our picker, map to 0-255 in OpenCV (128 = 0)
                a_center = int((a + 1) * 127.5)
                b_center = int((b + 1) * 127.5)

                # Calculate ranges
                # For L: ranges are 0-1, map to 0-255
                l_low = max(0, l_center - int(l_minus * 255))
                l_high = min(255, l_center + int(l_plus * 255))

                # For A and B: ranges are 0-1 (representing portion of -128 to 127 range)
                # Since A and B span 256 values (0-255), range of 1.0 means ±128
                a_low = max(0, a_center - int(a_minus * 128))
                a_high = min(255, a_center + int(a_plus * 128))
                b_low = max(0, b_center - int(b_minus * 128))
                b_high = min(255, b_center + int(b_plus * 128))

                # Create mask - LAB doesn't have circular wrapping like HSV hue
                lower_bound = np.array([l_low, a_low, b_low], dtype=np.uint8)
                upper_bound = np.array([l_high, a_high, b_high], dtype=np.uint8)
                mask = cv2.inRange(lab_image, lower_bound, upper_bound)

            else:
                # Fallback to simple threshold method
                l_threshold = self.options.get('l_threshold', 25)
                a_threshold = self.options.get('a_threshold', 25)
                b_threshold = self.options.get('b_threshold', 25)

                # Use the staticmethod to get LAB bounds
                lab_ranges = ColorUtils.get_lab_color_range(
                    self.target_color_lab, l_threshold, a_threshold, b_threshold
                )

                # Create mask
                lower_bound, upper_bound = lab_ranges
                mask = cv2.inRange(lab_image, lower_bound, upper_bound)

            # Identify contours in the masked image
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

            areas_of_interest, base_contour_count = self.identify_areas_of_interest(img, contours)
            output_path = self._construct_output_path(full_path, input_dir, output_dir)

            # Store mask instead of duplicating image
            mask_path = None
            if areas_of_interest:
                mask_path = self.store_mask(full_path, output_path, mask)

            # Return the mask path instead of output image path
            return AnalysisResult(full_path, mask_path, output_dir, areas_of_interest, base_contour_count)

        except Exception as e:
            self.logger.error(f"Error processing image {full_path}: {e}")
            return AnalysisResult(full_path, error_message=str(e))
