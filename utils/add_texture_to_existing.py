"""
Utility script to add texture analysis to existing detection XML files.

This script processes ADIAT_Data.xml files and adds texture data to all AOIs,
then saves the updated XML back to the same location.

Usage:
    python utils/add_texture_to_existing.py <adiat_data_xml_path>
    python utils/add_texture_to_existing.py output/ADIAT_Results/ADIAT_Data.xml

    # Process all XML files in a directory (useful for multiple result folders)
    python utils/add_texture_to_existing.py output/ --recursive
"""

import sys
import os
import cv2
import glob
import argparse
from pathlib import Path

# Add parent and app directories to path for imports
project_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'app'))

# Import using the internal import style (compatible with dev branch)
try:
    # Try dev branch import style first
    from core.services.image.TextureAnalysisService import TextureAnalysisService
except ImportError:
    try:
        # Try current branch location
        from core.services.TextureAnalysisService import TextureAnalysisService
    except ImportError:
        # Fallback to app-prefixed imports
        from app.core.services.TextureAnalysisService import TextureAnalysisService

from core.services.XmlService import XmlService

try:
    import tifffile
except ImportError:
    tifffile = None


def load_detected_pixels_from_mask(mask_path, aoi):
    """
    Load detected pixels from the mask file for an AOI.

    Args:
        mask_path: Path to the mask TIFF file
        aoi: AOI dictionary with 'center' and 'radius'

    Returns:
        list: List of [x, y] pixel coordinates within the AOI
    """
    if not mask_path or not os.path.exists(mask_path):
        return []

    try:
        # Load mask file (band 0 is the detection mask)
        if tifffile:
            mask_data = tifffile.imread(mask_path)
            if len(mask_data.shape) == 3:  # Multi-band
                mask = mask_data[0]  # First band is the mask
            else:
                mask = mask_data
        else:
            # Fallback to OpenCV
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            if mask is None:
                return []

        # Get all detected pixels in the mask
        import numpy as np
        detected_coords = np.argwhere(mask > 0)
        detected_pixels = detected_coords[:, [1, 0]].tolist()  # Convert to [x, y] format

        # Filter to only pixels within this AOI's circle
        center = aoi['center']
        radius = aoi['radius']

        aoi_pixels = []
        for px, py in detected_pixels:
            # Check if pixel is within the AOI circle
            dist = np.sqrt((px - center[0])**2 + (py - center[1])**2)
            if dist <= radius:
                aoi_pixels.append([px, py])

        return aoi_pixels

    except Exception as e:
        print(f"    Warning: Could not load mask file: {e}")
        return []


def process_xml_file(xml_path: str, overwrite: bool = True, backup: bool = True):
    """
    Add texture analysis to an existing XML file.

    Args:
        xml_path: Path to the XML file
        overwrite: Whether to overwrite the original file (default: True)
        backup: Whether to create a backup before overwriting (default: True)

    Returns:
        bool: True if successful, False otherwise
    """
    print(f"\nProcessing: {xml_path}")

    if not os.path.exists(xml_path):
        print(f"  Error: XML file not found at {xml_path}")
        return False

    try:
        # Load XML
        xml_service = XmlService(xml_path)
        images = xml_service.get_images()

        if not images:
            print("  No images found in XML")
            return False

        print(f"  Found {len(images)} image(s)")

        texture_service = TextureAnalysisService()
        updated_count = 0
        skipped_count = 0

        for img_data in images:
            image_path = img_data['path']
            aois = img_data['areas_of_interest']

            if not aois:
                continue

            # Check if texture data already exists
            has_texture = any('texture_data' in aoi and aoi['texture_data'] for aoi in aois)
            if has_texture:
                print(f"  Skipping {os.path.basename(image_path)}: already has texture data")
                skipped_count += 1
                continue

            # Load image
            if not os.path.exists(image_path):
                print(f"  Warning: Image not found at {image_path}, skipping")
                skipped_count += 1
                continue

            img = cv2.imread(image_path)
            if img is None:
                print(f"  Warning: Could not load image {image_path}, skipping")
                skipped_count += 1
                continue

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # Load detected_pixels from mask file if missing
            mask_path = img_data.get('mask_path', '')
            if mask_path and not os.path.isabs(mask_path):
                xml_dir = os.path.dirname(xml_path)
                mask_path = os.path.join(xml_dir, mask_path)

            missing_pixels_count = sum(1 for aoi in aois if not aoi.get('detected_pixels') or len(aoi.get('detected_pixels', [])) == 0)
            if missing_pixels_count > 0 and mask_path and os.path.exists(mask_path):
                print(f"    Loading detected pixels from mask file for {missing_pixels_count} AOI(s)...")
                for aoi in aois:
                    if not aoi.get('detected_pixels') or len(aoi.get('detected_pixels', [])) == 0:
                        aoi['detected_pixels'] = load_detected_pixels_from_mask(mask_path, aoi)

            # Add texture analysis
            print(f"  Analyzing {len(aois)} AOIs in {os.path.basename(image_path)}...")
            aois_with_texture = texture_service.analyze_aoi_batch(img_rgb, aois)

            # Update the image data
            img_data['areas_of_interest'] = aois_with_texture
            updated_count += 1

        if updated_count == 0:
            print(f"  No images needed texture analysis (skipped {skipped_count})")
            return True

        # Create backup if requested
        if backup and overwrite:
            backup_path = xml_path + '.backup'
            import shutil
            shutil.copy2(xml_path, backup_path)
            print(f"  Created backup: {backup_path}")

        # Save updated XML
        output_path = xml_path if overwrite else xml_path.replace('.xml', '_with_texture.xml')

        # Create new XML service to rebuild the XML structure
        new_xml_service = XmlService()

        # Add settings from original
        settings, _ = xml_service.get_settings()
        new_xml_service.add_settings_to_xml(**settings)

        # Add images with updated AOI data
        for img_data in images:
            # Convert areas_of_interest to aois format expected by add_image_to_xml
            aois_list = []
            for aoi in img_data['areas_of_interest']:
                aois_list.append(aoi)

            new_xml_service.add_image_to_xml({
                'path': os.path.basename(img_data.get('mask_path', img_data['path'])),
                'original_path': img_data['path'],
                'aois': aois_list
            })

        new_xml_service.save_xml_file(output_path)
        print(f"  Saved updated XML to: {output_path}")
        print(f"  Successfully processed {updated_count} image(s), skipped {skipped_count}")

        return True

    except Exception as e:
        print(f"  Error processing XML: {e}")
        import traceback
        traceback.print_exc()
        return False


def process_directory(directory: str, recursive: bool = False, overwrite: bool = True, backup: bool = True):
    """
    Process all XML files in a directory.

    Args:
        directory: Path to directory containing XML files
        recursive: Whether to search subdirectories recursively
        overwrite: Whether to overwrite original files
        backup: Whether to create backups
    """
    if recursive:
        pattern = os.path.join(directory, '**', '*.xml')
        xml_files = glob.glob(pattern, recursive=True)
    else:
        pattern = os.path.join(directory, '*.xml')
        xml_files = glob.glob(pattern)

    # Filter out backup files
    xml_files = [f for f in xml_files if not f.endswith('.backup')]

    if not xml_files:
        print(f"No XML files found in {directory}")
        return

    print(f"Found {len(xml_files)} XML file(s) to process")

    success_count = 0
    fail_count = 0

    for xml_path in xml_files:
        if process_xml_file(xml_path, overwrite=overwrite, backup=backup):
            success_count += 1
        else:
            fail_count += 1

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Successfully processed: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total: {len(xml_files)}")


def main():
    parser = argparse.ArgumentParser(
        description='Add texture analysis to existing detection XML files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process ADIAT_Data.xml file
  python utils/add_texture_to_existing.py output/ADIAT_Results/ADIAT_Data.xml

  # Process all XML files in ADIAT_Results directory
  python utils/add_texture_to_existing.py output/ADIAT_Results/

  # Process recursively (useful if you have multiple result folders)
  python utils/add_texture_to_existing.py output/ --recursive

  # Create new file instead of overwriting
  python utils/add_texture_to_existing.py output/ADIAT_Results/ADIAT_Data.xml --no-overwrite

  # Don't create backups
  python utils/add_texture_to_existing.py output/ADIAT_Results/ADIAT_Data.xml --no-backup
        """
    )

    parser.add_argument(
        'path',
        help='Path to XML file or directory containing XML files'
    )
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        help='Process XML files in subdirectories recursively'
    )
    parser.add_argument(
        '--no-overwrite',
        action='store_true',
        help='Create new files (*_with_texture.xml) instead of overwriting originals'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Do not create backup files when overwriting'
    )

    args = parser.parse_args()

    path = args.path
    overwrite = not args.no_overwrite
    backup = not args.no_backup

    if not os.path.exists(path):
        print(f"Error: Path not found: {path}")
        sys.exit(1)

    if os.path.isfile(path):
        # Process single file
        if not path.endswith('.xml'):
            print("Error: File must be an XML file")
            sys.exit(1)

        success = process_xml_file(path, overwrite=overwrite, backup=backup)
        sys.exit(0 if success else 1)

    elif os.path.isdir(path):
        # Process directory
        process_directory(path, recursive=args.recursive, overwrite=overwrite, backup=backup)
        sys.exit(0)

    else:
        print(f"Error: Invalid path: {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
