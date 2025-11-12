"""
Service for batch processing chromatic aberration removal from images.

This service handles the batch removal of chromatic aberrations from
a folder of images, with progress tracking and cancellation support.
"""

import os
import cv2
import numpy as np
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from core.services.ChromaticAberrationService import ChromaticAberrationService
from core.services.LoggerService import LoggerService


class ChromaticAberrationRemovalService(QObject):
    """Service for batch processing chromatic aberration removal."""

    # Signals
    sig_msg = Signal(str)  # Progress messages
    sig_progress = Signal(int, int)  # (current, total)
    sig_done = Signal(int, int)  # (id, images_processed)

    # Supported image extensions
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp'}

    def __init__(
        self,
        service_id: int,
        input_folder: str,
        output_folder: str,
        method: str = "desaturate",
        sensitivity: float = 1.0,
        apply_lateral: bool = False,
        lateral_strength: float = 1.0,
        edge_threshold: int = 50
    ):
        """
        Initialize the ChromaticAberrationRemovalService.

        Args:
            service_id: Unique identifier for this service instance.
            input_folder: Path to folder containing input images.
            output_folder: Path to folder for output images.
            method: CA removal method ("desaturate", "replace", or "both").
            sensitivity: Detection sensitivity (0.5-2.0).
            apply_lateral: Whether to apply lateral CA correction.
            lateral_strength: Strength of lateral correction (0.0-2.0).
            edge_threshold: Canny edge detection threshold.
        """
        super().__init__()
        self.service_id = service_id
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.method = method
        self.sensitivity = sensitivity
        self.apply_lateral = apply_lateral
        self.lateral_strength = lateral_strength
        self.edge_threshold = edge_threshold
        self.cancelled = False
        self.logger = LoggerService()

    def process_cancel(self):
        """Cancel the processing operation."""
        self.cancelled = True
        self.logger.info("Chromatic aberration removal cancelled by user")

    def process_images(self):
        """
        Process all images in the input folder.

        This method is designed to run in a separate thread.
        """
        try:
            # Get list of image files
            image_files = self._get_image_files()

            if not image_files:
                self.sig_msg.emit("No image files found in input folder")
                self.sig_done.emit(self.service_id, 0)
                return

            total_images = len(image_files)
            self.sig_msg.emit(f"Found {total_images} images to process")

            # Create output folder if it doesn't exist
            os.makedirs(self.output_folder, exist_ok=True)

            # Initialize CA service
            ca_service = ChromaticAberrationService(sensitivity=self.sensitivity)

            # Process each image
            processed_count = 0
            for idx, image_path in enumerate(image_files, 1):
                if self.cancelled:
                    self.sig_msg.emit("Processing cancelled")
                    break

                try:
                    # Emit progress
                    self.sig_progress.emit(idx, total_images)
                    self.sig_msg.emit(f"Processing {idx}/{total_images}: {image_path.name}")

                    # Read image
                    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                    if img is None:
                        self.sig_msg.emit(f"  Warning: Could not read {image_path.name}")
                        continue

                    # Apply lateral correction if requested
                    if self.apply_lateral:
                        img = ca_service.apply_lateral_correction(
                            img,
                            strength=self.lateral_strength
                        )

                    # Remove chromatic aberration
                    corrected_img, ca_mask = ca_service.remove_chromatic_aberration(
                        img,
                        method=self.method,
                        edge_threshold=self.edge_threshold
                    )

                    # Count corrected pixels for logging
                    ca_pixels = np.count_nonzero(ca_mask)
                    if ca_pixels > 0:
                        self.sig_msg.emit(f"  Corrected {ca_pixels} CA pixels")
                    else:
                        self.sig_msg.emit(f"  No CA detected")

                    # Save corrected image
                    output_path = Path(self.output_folder) / image_path.name
                    cv2.imwrite(str(output_path), corrected_img)

                    processed_count += 1

                except Exception as e:
                    self.logger.error(f"Error processing {image_path.name}: {e}")
                    self.sig_msg.emit(f"  Error: {str(e)}")

            # Emit completion signal
            if not self.cancelled:
                self.sig_msg.emit(f"Successfully processed {processed_count} images")
            self.sig_done.emit(self.service_id, processed_count)

        except Exception as e:
            self.logger.error(f"Error in process_images: {e}")
            self.sig_msg.emit(f"Error: {str(e)}")
            self.sig_done.emit(self.service_id, 0)

    def _get_image_files(self):
        """
        Get list of image files from input folder.

        Returns:
            List of Path objects for image files.
        """
        input_path = Path(self.input_folder)

        if not input_path.exists() or not input_path.is_dir():
            return []

        image_files = []
        for file_path in input_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                image_files.append(file_path)

        # Sort by name for consistent processing order
        image_files.sort(key=lambda p: p.name)

        return image_files
