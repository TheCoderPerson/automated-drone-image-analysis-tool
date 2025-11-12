# Texture Analysis for False Positive Filtering

## Overview

The texture analysis feature helps identify and filter false positives in drone image detection by comparing the texture characteristics of detected anomaly pixels with their surrounding area (AOI circle).

## Concept

**Key Idea:** True positive detections often have distinctly different texture from their surroundings, while false positives tend to have similar texture to the background.

For each AOI (Area of Interest), we calculate:
1. **Detected Texture**: Texture features of only the anomaly pixels that were detected
2. **AOI Texture**: Texture features of the entire circular region around the detection
3. **Comparison Metrics**: Differences and ratios between these textures

## Texture Features

The system uses GLCM (Gray-Level Co-occurrence Matrix) to calculate several texture properties:

### Primary Features

- **Contrast**: Measures local variations in intensity. Higher values indicate more texture variation.
- **Dissimilarity**: Similar to contrast but increases linearly with intensity differences.
- **Homogeneity**: Measures closeness to the diagonal in the GLCM. Higher values indicate more uniform texture.
- **Energy**: Sum of squared elements in GLCM. Higher values indicate more uniform texture.
- **Correlation**: Linear dependency between gray levels.
- **ASM (Angular Second Moment)**: Same as energy, measures texture uniformity.

### Composite Metrics

- **Texture Score (0-100)**: Weighted combination of all features, normalized to 0-100 scale
  - Higher score = more texture complexity/variation
  - Lower score = smoother/more uniform texture

- **Texture Difference**: `detected_score - aoi_score`
  - Positive value: detected pixels have more texture than surroundings
  - Negative value: detected pixels have less texture than surroundings
  - Near zero: similar texture (potential false positive)

- **Texture Ratio**: `detected_score / aoi_score`
  - > 1.0: detected pixels more textured than surroundings
  - < 1.0: detected pixels less textured than surroundings
  - ≈ 1.0: similar texture (potential false positive)

## Usage

### 1. Analyze Existing Detections

Use the example script to analyze detections from an existing XML file:

```bash
python examples/texture_analysis_example.py input/DJI_0001.JPG output/DJI_0001.xml
```

This will:
- Load the image and AOI data
- Calculate texture features for each AOI
- Display detailed texture metrics
- Identify potential false positives based on statistical analysis
- Show AOIs with low texture differences or similar ratios

### 2. Programmatic Usage

```python
from app.core.services.TextureAnalysisService import TextureAnalysisService
from app.core.services.ImageService import ImageService
from app.core.services.XmlService import XmlService
import cv2

# Load image
img = cv2.imread('path/to/image.jpg')
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

# Load AOIs from XML
xml_service = XmlService('path/to/output.xml')
images = xml_service.get_images()
aois = images[0]['areas_of_interest']

# Initialize texture service
texture_service = TextureAnalysisService()

# Analyze all AOIs
aois_with_texture = texture_service.analyze_aoi_batch(img_rgb, aois)

# Access texture data
for aoi in aois_with_texture:
    texture_data = aoi['texture_data']
    print(f"Center: {aoi['center']}")
    print(f"Detected Texture Score: {texture_data['detected_texture']['texture_score']:.2f}")
    print(f"AOI Texture Score: {texture_data['aoi_texture']['texture_score']:.2f}")
    print(f"Difference: {texture_data['texture_difference']:.2f}")
    print(f"Ratio: {texture_data['texture_ratio']:.2f}")
```

### 3. Filter AOIs by Texture

```python
# Filter out false positives
filtered_aois = TextureAnalysisService.filter_aois_by_texture(
    aois_with_texture,
    min_difference=5.0,  # Minimum texture difference
    min_ratio=1.1        # Minimum ratio (detected must be 10% more textured)
)

print(f"Original: {len(aois_with_texture)} AOIs")
print(f"Filtered: {len(filtered_aois)} AOIs")
print(f"Removed: {len(aois_with_texture) - len(filtered_aois)} potential false positives")
```

### 4. Integrate with Detection Algorithms

Add texture analysis to detection pipeline:

```python
from app.algorithms.RXAnomaly.services.RXAnomalyService import RXAnomalyService

# Create algorithm service
algorithm = RXAnomalyService(...)

# Process image
result = algorithm.process_image(img, full_path, input_dir, output_dir)

# Add texture analysis to AOIs
if result.areas_of_interest:
    result.areas_of_interest = algorithm.add_texture_analysis(
        img,
        result.areas_of_interest,
        calculate_texture=True
    )
```

## Workflow for False Positive Filtering

### Step 1: Analyze Your Detections

Run the example script on your images to understand the texture characteristics:

```bash
python examples/texture_analysis_example.py input/image.jpg
```

### Step 2: Review Results

Look at the summary statistics and identify patterns:

- **Low Texture Difference**: AOIs where detected pixels have similar texture to surroundings
- **Ratio Near 1.0**: AOIs where texture complexity is nearly identical
- **Compare with Flagged Status**: Check if false positives you've flagged manually correlate with texture metrics

### Step 3: Determine Thresholds

Based on your analysis, determine filtering criteria:

**Example findings:**
- True positives typically have `texture_difference > 8.0`
- False positives typically have `0.85 < texture_ratio < 1.15`
- Flagged false positives have `texture_difference < 3.0`

### Step 4: Apply Filtering

Use the determined thresholds to filter detections:

```python
filtered_aois = TextureAnalysisService.filter_aois_by_texture(
    aois,
    min_difference=8.0,   # Based on your analysis
    min_ratio=1.15        # Based on your analysis
)
```

### Step 5: Validate Results

- Review filtered detections in the viewer
- Check if legitimate detections were removed
- Adjust thresholds as needed
- Iterate until optimal balance is achieved

## Interpretation Guide

### High Texture Difference (> 10)
- **Likely**: True positive
- **Reason**: Detected area has distinctly different texture from surroundings
- **Examples**: Object on smooth surface, anomaly with unique pattern

### Moderate Texture Difference (3-10)
- **Likely**: Needs review
- **Reason**: Some texture difference exists but not dramatic
- **Examples**: Partial detections, edge effects, textured backgrounds

### Low Texture Difference (< 3)
- **Likely**: False positive
- **Reason**: Very similar texture to surroundings
- **Examples**: Shadows, color variations in uniform texture, detection artifacts

### Ratio Considerations

- **Ratio > 1.5**: Detected area much more textured (strong indicator of true positive)
- **Ratio 1.1-1.5**: Moderately more textured (likely true positive)
- **Ratio 0.9-1.1**: Similar texture (potential false positive)
- **Ratio < 0.9**: Detected area smoother than surroundings (investigate further)

## Technical Details

### GLCM Parameters

The texture analysis uses the following GLCM parameters:

- **Distances**: [1, 2, 3] pixels
- **Angles**: [0°, 45°, 90°, 135°]
- **Gray Levels**: Normalized to 64 levels (from original 256) for performance
- **Symmetric**: True
- **Normalized**: True

These parameters provide rotation-invariant texture analysis at multiple scales.

### Performance Considerations

- **Processing Time**: ~50-200ms per AOI depending on size
- **Memory**: Minimal, processes each AOI independently
- **Optimization**: Gray level reduction (256 → 64) significantly improves speed with minimal accuracy loss

### Limitations

1. **Small Detections**: AOIs with very few pixels (< 4) may not have meaningful texture metrics
2. **Edge Effects**: Detections at image boundaries may have incomplete AOI circles
3. **Scale Dependency**: Texture features may vary with image resolution
4. **Lighting Variations**: Strong lighting changes can affect texture measurements

## Data Persistence

Texture data is automatically saved when you save AOIs:

```python
# Texture data is saved in XML as JSON
xml_service = XmlService()
xml_service.add_image_to_xml({
    'path': mask_path,
    'original_path': image_path,
    'aois': aois_with_texture  # texture_data included automatically
})
xml_service.save_xml_file(output_path)
```

Texture data structure in XML:
```xml
<areas_of_interest
    center="(100, 200)"
    radius="50"
    area="314.0"
    texture_data='{"detected_texture": {...}, "aoi_texture": {...}, "texture_difference": 12.5, "texture_ratio": 1.45}'>
</areas_of_interest>
```

## Best Practices

1. **Analyze First**: Always run texture analysis on a sample of images before applying filters
2. **Use Statistics**: Base thresholds on statistical analysis of your data (mean ± std dev)
3. **Consider Context**: Different detection types may need different thresholds
4. **Iterate**: Start with conservative thresholds and gradually adjust
5. **Validate**: Always manually review filtered results to ensure accuracy
6. **Document**: Record the thresholds you use for different image types or detection algorithms

## Examples

### Example 1: Smooth Surface Detections

**Scenario**: Detecting objects on concrete runway

```python
# Objects will have higher texture than smooth concrete
filtered_aois = TextureAnalysisService.filter_aois_by_texture(
    aois,
    min_difference=10.0,  # Require significant difference
    min_ratio=1.3         # Detected must be 30% more textured
)
```

### Example 2: Textured Background

**Scenario**: Detecting anomalies in vegetation

```python
# Both anomaly and background may be textured
# Use more subtle threshold
filtered_aois = TextureAnalysisService.filter_aois_by_texture(
    aois,
    min_difference=3.0,   # Lower threshold
    min_ratio=1.1         # Just need slight difference
)
```

### Example 3: Mixed Environment

**Scenario**: Various surface types in same image

```python
# May need to analyze regions separately or use broader thresholds
# Consider splitting analysis by region if possible
for region_aois in split_by_region(aois):
    analyze_and_filter_separately(region_aois)
```

## Future Enhancements

Potential additions to the texture analysis system:

1. **Additional Texture Methods**: LBP, Gabor filters, wavelet transforms
2. **Machine Learning**: Train classifier on texture features
3. **Adaptive Thresholds**: Automatically determine thresholds based on image characteristics
4. **Spatial Texture Maps**: Visualize texture variation across entire image
5. **Multi-scale Analysis**: Analyze texture at different spatial scales
6. **Directional Features**: Capture oriented texture patterns

## Troubleshooting

### Issue: All texture scores are very low

**Cause**: Image is very smooth or low contrast
**Solution**: Check image quality, may need different detection approach

### Issue: No meaningful difference between detected and AOI texture

**Cause**: Detection might be capturing texture variations rather than objects
**Solution**: Review detection algorithm parameters, consider increasing contrast thresholds

### Issue: Texture analysis is slow

**Cause**: Large AOIs or many detections
**Solution**:
- Reduce gray levels further (set `levels` parameter lower)
- Process in parallel if analyzing multiple images
- Consider reducing number of distances/angles in GLCM

### Issue: Texture data not saving to XML

**Cause**: JSON serialization error or missing import
**Solution**: Check that numpy types are converted to Python types in texture calculations

## References

- Haralick, R. M., et al. (1973). "Textural Features for Image Classification"
- GLCM Tutorial: [scikit-image documentation](https://scikit-image.org/docs/stable/auto_examples/features_detection/plot_glcm.html)
- [Texture Analysis Overview](https://en.wikipedia.org/wiki/Co-occurrence_matrix)
