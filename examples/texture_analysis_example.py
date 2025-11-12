"""
Example script demonstrating texture analysis for AOI false positive filtering.

This script shows how to:
1. Load an image with existing detections from ADIAT_Data.xml
2. Calculate texture features for detected pixels vs. AOI circles
3. Analyze differences to identify potential false positives
4. Filter AOIs based on texture criteria

Usage:
    python examples/texture_analysis_example.py <image_path> <adiat_data_xml_path>

Example:
    python examples/texture_analysis_example.py input/DJI_0001.JPG output/ADIAT_Results/ADIAT_Data.xml
"""

import sys
import os
import cv2
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.services.TextureAnalysisService import TextureAnalysisService
from app.core.services.ImageService import ImageService
from app.core.services.XmlService import XmlService


def find_image_in_xml(xml_service, image_path):
    """
    Find the image entry in ADIAT_Data.xml that matches the given image path.

    Args:
        xml_service: XmlService instance with loaded ADIAT_Data.xml
        image_path: Path to the image to find

    Returns:
        dict: Image data with AOIs, or None if not found
    """
    images = xml_service.get_images()

    # Normalize the search path
    image_path_normalized = os.path.normpath(image_path)
    image_basename = os.path.basename(image_path)

    for img_data in images:
        # Check both full path and basename
        img_path = img_data.get('path', '')
        img_path_normalized = os.path.normpath(img_path)

        # Match by full path or basename
        if (img_path_normalized == image_path_normalized or
            os.path.basename(img_path) == image_basename or
            img_path == image_path):
            return img_data

    return None


def analyze_existing_detections(image_path: str, xml_path: str):
    """
    Analyze texture features for existing detections.

    Args:
        image_path: Path to the source image
        xml_path: Path to ADIAT_Data.xml file with AOI data
    """
    print(f"Loading image: {image_path}")

    # Load image
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        return

    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not load image at {image_path}")
        return
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Load ADIAT_Data.xml
    if not os.path.exists(xml_path):
        print(f"Error: ADIAT_Data.xml file not found at {xml_path}")
        print("\nPlease provide the correct path to ADIAT_Data.xml")
        print("Typical location: <output_folder>/ADIAT_Results/ADIAT_Data.xml")
        return

    print(f"Loading detection data from: {xml_path}")

    # Load XML and find this image's data
    xml_service = XmlService(xml_path)
    img_data = find_image_in_xml(xml_service, image_path)

    if img_data is None:
        print(f"\nError: Could not find detections for image: {image_path}")
        print("\nImages found in ADIAT_Data.xml:")
        images = xml_service.get_images()
        for i, img in enumerate(images, 1):
            print(f"  {i}. {img.get('path', 'Unknown')}")
        print("\nPlease check that the image path matches one of the above.")
        return

    aois = img_data.get('areas_of_interest', [])

    if not aois:
        print(f"No AOIs found for this image in the XML file")
        return

    print(f"Found {len(aois)} AOIs")

    # Initialize texture analysis service
    texture_service = TextureAnalysisService()

    # Analyze each AOI
    print("\nAnalyzing texture features...")
    print("-" * 80)

    results = []
    for i, aoi in enumerate(aois):
        print(f"\nAOI {i + 1}:")
        print(f"  Center: {aoi['center']}")
        print(f"  Radius: {aoi['radius']}")
        print(f"  Detected pixels: {len(aoi.get('detected_pixels', []))}")

        # Calculate textures
        texture_data = texture_service.calculate_aoi_textures(img_rgb, aoi)

        # Display results
        detected = texture_data['detected_texture']
        aoi_texture = texture_data['aoi_texture']

        print(f"\n  Detected Pixels Texture:")
        print(f"    Texture Score: {detected['texture_score']:.2f}")
        print(f"    Contrast: {detected['contrast']:.4f}")
        print(f"    Homogeneity: {detected['homogeneity']:.4f}")
        print(f"    Energy: {detected['energy']:.4f}")

        print(f"\n  AOI Circle Texture:")
        print(f"    Texture Score: {aoi_texture['texture_score']:.2f}")
        print(f"    Contrast: {aoi_texture['contrast']:.4f}")
        print(f"    Homogeneity: {aoi_texture['homogeneity']:.4f}")
        print(f"    Energy: {aoi_texture['energy']:.4f}")

        print(f"\n  Comparison:")
        print(f"    Texture Difference: {texture_data['texture_difference']:.2f}")
        print(f"    Texture Ratio: {texture_data['texture_ratio']:.2f}")

        # Store for analysis
        results.append({
            'aoi_index': i,
            'center': aoi['center'],
            'flagged': aoi.get('flagged', False),
            'texture_difference': texture_data['texture_difference'],
            'texture_ratio': texture_data['texture_ratio'],
            'detected_score': detected['texture_score'],
            'aoi_score': aoi_texture['texture_score']
        })

    # Summary analysis
    print("\n" + "=" * 80)
    print("SUMMARY ANALYSIS")
    print("=" * 80)

    # Calculate statistics
    differences = [r['texture_difference'] for r in results]
    ratios = [r['texture_ratio'] for r in results]

    print(f"\nTexture Difference Statistics:")
    print(f"  Mean: {np.mean(differences):.2f}")
    print(f"  Std Dev: {np.std(differences):.2f}")
    print(f"  Min: {np.min(differences):.2f}")
    print(f"  Max: {np.max(differences):.2f}")

    print(f"\nTexture Ratio Statistics:")
    print(f"  Mean: {np.mean(ratios):.2f}")
    print(f"  Std Dev: {np.std(ratios):.2f}")
    print(f"  Min: {np.min(ratios):.2f}")
    print(f"  Max: {np.max(ratios):.2f}")

    # Identify potential false positives
    print("\n" + "-" * 80)
    print("POTENTIAL FALSE POSITIVE IDENTIFICATION")
    print("-" * 80)

    # Low difference suggests similar texture to surroundings
    low_diff_threshold = np.mean(differences) - np.std(differences)
    low_diff_aois = [r for r in results if r['texture_difference'] < low_diff_threshold]

    print(f"\nAOIs with low texture difference (< {low_diff_threshold:.2f}):")
    print("(These have similar texture to surroundings, may be false positives)")
    if low_diff_aois:
        for r in low_diff_aois:
            flagged_status = "FLAGGED" if r['flagged'] else "NOT FLAGGED"
            print(f"  AOI {r['aoi_index'] + 1} at {r['center']}: "
                  f"diff={r['texture_difference']:.2f}, "
                  f"ratio={r['texture_ratio']:.2f} "
                  f"[{flagged_status}]")
    else:
        print("  None found")

    # Ratio close to 1.0 suggests very similar texture
    similar_texture_aois = [r for r in results if 0.8 < r['texture_ratio'] < 1.2]
    print(f"\nAOIs with similar texture ratio (0.8-1.2):")
    print("(Detected pixels have very similar texture to surroundings)")
    if similar_texture_aois:
        for r in similar_texture_aois:
            flagged_status = "FLAGGED" if r['flagged'] else "NOT FLAGGED"
            print(f"  AOI {r['aoi_index'] + 1} at {r['center']}: "
                  f"diff={r['texture_difference']:.2f}, "
                  f"ratio={r['texture_ratio']:.2f} "
                  f"[{flagged_status}]")
    else:
        print("  None found")

    print("\n" + "=" * 80)
    print("\nNext steps:")
    print("1. Review the flagged AOIs in the viewer")
    print("2. Compare texture metrics between true positives and false positives")
    print("3. Determine threshold values for automatic filtering")
    print("4. Use TextureAnalysisService.filter_aois_by_texture() to apply filters")


def demonstrate_filtering(image_path: str, xml_path: str,
                         min_difference: float = None,
                         min_ratio: float = None):
    """
    Demonstrate filtering AOIs based on texture criteria.

    Args:
        image_path: Path to source image
        xml_path: Path to ADIAT_Data.xml file
        min_difference: Minimum texture difference to keep
        min_ratio: Minimum texture ratio to keep
    """
    print("=" * 80)
    print("TEXTURE-BASED FILTERING DEMONSTRATION")
    print("=" * 80)

    # Load image
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not load image at {image_path}")
        return
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Load XML and find this image
    xml_service = XmlService(xml_path)
    img_data = find_image_in_xml(xml_service, image_path)

    if img_data is None:
        print(f"Error: Could not find detections for image in XML")
        return

    aois = img_data.get('areas_of_interest', [])

    print(f"\nOriginal AOI count: {len(aois)}")

    # Add texture data to AOIs
    texture_service = TextureAnalysisService()
    aois = texture_service.analyze_aoi_batch(img_rgb, aois)

    # Apply filters
    if min_difference is not None or min_ratio is not None:
        print(f"\nApplying filters:")
        if min_difference is not None:
            print(f"  Minimum texture difference: {min_difference}")
        if min_ratio is not None:
            print(f"  Minimum texture ratio: {min_ratio}")

        filtered_aois = TextureAnalysisService.filter_aois_by_texture(
            aois,
            min_difference=min_difference,
            min_ratio=min_ratio
        )

        print(f"\nFiltered AOI count: {len(filtered_aois)}")
        print(f"Removed: {len(aois) - len(filtered_aois)} AOIs")

        # Show removed AOIs
        removed = [a for a in aois if a not in filtered_aois]
        if removed:
            print("\nRemoved AOIs:")
            for aoi in removed:
                td = aoi['texture_data']
                print(f"  Center {aoi['center']}: "
                      f"diff={td['texture_difference']:.2f}, "
                      f"ratio={td['texture_ratio']:.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Texture Analysis for False Positive Filtering")
        print("=" * 80)
        print("\nUsage:")
        print("  python texture_analysis_example.py <image_path> <adiat_data_xml_path>")
        print("\nExample:")
        print("  python texture_analysis_example.py input/DJI_0001.JPG output/ADIAT_Results/ADIAT_Data.xml")
        print("\nArguments:")
        print("  image_path          : Path to the image file to analyze")
        print("  adiat_data_xml_path : Path to ADIAT_Data.xml (usually in ADIAT_Results folder)")
        print("\nNote:")
        print("  The ADIAT_Data.xml file is located in the output folder you selected")
        print("  when running the detection, typically: <output_folder>/ADIAT_Results/ADIAT_Data.xml")
        sys.exit(1)

    image_path = sys.argv[1]
    xml_path = sys.argv[2]

    # Run analysis
    analyze_existing_detections(image_path, xml_path)

    # Example filtering (uncomment and adjust thresholds as needed)
    # print("\n\n")
    # demonstrate_filtering(image_path, xml_path, min_difference=5.0, min_ratio=1.1)
