# Algorithm Test Images for Automated Drone Image Analysis Tool

This directory contains comprehensive SVG test images designed to validate all algorithms in the automated drone image analysis tool. Each test image is crafted to test specific input features and verify correct algorithm behavior.

## Directory Structure

```
test_images/
├── batch_algorithms/          # Static image analysis algorithms
│   ├── AIPersonDetector/
│   ├── ColorRange/
│   ├── HSVColorRange/
│   ├── MRMap/
│   ├── MatchedFilter/
│   ├── RXAnomaly/
│   ├── ThermalAnomaly/
│   └── ThermalRange/
└── realtime_algorithms/       # Real-time video stream algorithms
    ├── RealtimeColorDetector/
    ├── RealtimeAnomalyDetector/
    └── RealtimeMotionDetector/
```

---

## Batch Processing Algorithms

### 1. AIPersonDetector
**Purpose:** AI-based person detection using ONNX model with sliding window approach

**Test Images:**
- **test_1.1_multi_scale_persons.svg** (2000x2000px)
  - **Content:** 3 person silhouettes at different scales
  - **Features Tested:** min_area, max_area, aoi_radius, sliding window processing
  - **Expected Output:** All 3 persons detected with appropriate AOIs

- **test_1.2_overlapping_detections.svg** (1600x1200px)
  - **Content:** 2 person silhouettes overlapping by 30%
  - **Features Tested:** combine_aois, non-maximum suppression, confidence threshold
  - **Expected Output:** Either 2 separate AOIs or 1 merged AOI depending on settings

---

### 2. ColorRange
**Purpose:** RGB color range detection with simple thresholding

**Test Images:**
- **test_2.1_rgb_color_targets.svg** (1000x1000px)
  - **Content:** Red, green, blue rectangles of various sizes + tiny red dot
  - **Features Tested:** color_range boundaries, min_area/max_area filtering
  - **Expected Output (red detection):** Large red + tiny red dot detected, others ignored

- **test_2.2_gradient_edge_cases.svg** (800x800px)
  - **Content:** Horizontal red gradient (255,0,0) → (255,100,100) + solid target
  - **Features Tested:** RGB range boundaries, partial region detection
  - **Expected Output:** Center of gradient + solid target detected

---

### 3. HSVColorRange
**Purpose:** HSV-based color detection with hue wrapping support

**Test Images:**
- **test_3.1_hue_variation.svg** (1200x800px)
  - **Content:** Pure red, orange-red, deep red, pink, purple rectangles
  - **Features Tested:** hue_threshold, saturation_threshold, value_threshold
  - **Expected Output:** All red variations detected except purple (hue too far)

- **test_3.2_hue_wrapping.svg** (1000x800px)
  - **Content:** Red (0°), near-red (348°), near-red (12°)
  - **Features Tested:** Hue wrapping around 0°/360° boundary
  - **Expected Output:** All 3 regions detected (tests critical hue wrapping logic)

---

### 4. MRMap (Multi-Resolution Map)
**Purpose:** Spectral anomaly detection via quantized histogram analysis

**Test Images:**
- **test_4.1_rare_color_anomalies.svg** (1600x1200px)
  - **Content:** Common green background + yellow, cyan, magenta anomalies
  - **Features Tested:** threshold, segments, window, quantized histogram
  - **Expected Output:** 3 rare-color anomalies detected

- **test_4.2_clustered_vs_sparse.svg** (1200x1200px)
  - **Content:** 5 clustered red circles + 3 sparse red circles on blue background
  - **Features Tested:** combine_aois, window parameter, rectangle merging
  - **Expected Output:** Clustered → 1 merged AOI, Sparse → separate AOIs

---

### 5. MatchedFilter
**Purpose:** Spectral matched filter for target signature matching

**Test Images:**
- **test_5.1_spectral_signature_matching.svg** (1000x1000px)
  - **Content:** Exact match, close match, poor match on varied background
  - **Features Tested:** selected_color, match_filter_threshold, correlation
  - **Expected Output (threshold=0.7):** Exact + close detected, poor match rejected

---

### 6. RXAnomaly
**Purpose:** RX (Reed-Xiaoli) anomaly detection with chi-squared distribution

**Test Images:**
- **test_6.1_statistical_anomalies.svg** (1600x1200px)
  - **Content:** Grass texture background + orange, purple, dark anomalies
  - **Features Tested:** sensitivity, segments, LAB color space, chi-squared scoring
  - **Expected Output:** All 3 anomalies detected with high scores

- **test_6.2_sensitivity_calibration.svg** (1200x1200px)
  - **Content:** Uniform gray + graduated anomalies (weak, medium, strong)
  - **Features Tested:** sensitivity parameter tuning (1-10 scale)
  - **Expected Output:** Detection varies by sensitivity level

---

### 7. ThermalAnomaly
**Purpose:** Statistical temperature anomaly detection

**Test Images:**
- **test_7.1_temperature_anomalies.svg** (1000x1000px)
  - **Content:** Grayscale thermal image with hot spots and cold spot
  - **Features Tested:** threshold (std dev), segments, type parameter
  - **Expected Output:** Hot/cold spots detected based on type setting

- **test_7.2_directional_detection.svg** (1000x1000px)
  - **Content:** Same as 7.1, tests directional filtering
  - **Features Tested:** type ('Above Mean', 'Below Mean', 'Above or Below Mean')
  - **Expected Output:** Directional filtering based on type

---

### 8. ThermalRange
**Purpose:** Direct temperature range thresholding

**Test Images:**
- **test_8.1_temperature_range_selection.svg** (1200x800px)
  - **Content:** Thermal gradient 0-50°C + discrete zones (15°C, 30°C, 42°C)
  - **Features Tested:** minTemp, maxTemp boundaries
  - **Expected Output (25-40°C range):** Only 30°C zone detected

---

## Real-Time Processing Algorithms

### 9. RealtimeColorDetector
**Purpose:** High-performance HSV color detection for RTMP streams (<100ms latency)

**Test Images:**
- **test_9.1_performance_and_accuracy.svg** (1920x1080px)
  - **Content:** Large, medium, small, tiny red objects + distractors
  - **Features Tested:** processing_resolution, min/max_area, performance, GPU
  - **Expected Output:** <100ms processing, all targets detected

- **test_9.2_hsv_range_precision.svg** (1280x720px)
  - **Content:** Red variations (pure, pinkish, dark, orange, magenta)
  - **Features Tested:** HSV thresholds, hue wrapping, real-time accuracy
  - **Expected Output:** Sub-100ms, red variations detected, others rejected

---

### 10. RealtimeAnomalyDetector
**Purpose:** Real-time RX-style anomaly detection (<50ms latency)

**Test Images:**
- **test_10.1_realtime_statistical_anomalies.svg** (1280x720px)
  - **Content:** Noisy background + yellow (strong), blue (medium), green (weak) anomalies
  - **Features Tested:** sensitivity, window_size, distance_metric, LAB processing
  - **Expected Output:** <50ms, color-coded by score (red/orange/yellow)

- **test_10.2_multiscale_anomalies.svg** (1920x1080px)
  - **Content:** Grass texture + tiny, small, medium, large anomalies
  - **Features Tested:** min/max_area, confidence, multi-scale detection, performance
  - **Expected Output:** Sub-50ms maintained, size-based filtering

---

### 11. RealtimeMotionDetector
**Purpose:** Motion detection with camera motion compensation

**Test Sequences:**

#### Test 11.1: Static Camera Motion (5 frames)
- **Frames:** test_11.1_static_camera_frame1-5.svg (1280x720px)
- **Content:** Building facade background, red object moving 200→500 (100px/frame)
- **Features Tested:** mode='static', algorithms (frame_diff, mog2, knn, optical_flow, feature_match)
- **Expected Output:** No camera motion, object velocity ~100px/frame rightward

#### Test 11.2: Moving Camera/Drone Flight (5 frames)
- **Frames:** test_11.2_moving_camera_frame1-5.svg (1920x1080px)
- **Content:** Landscape panning (-50,-10)/frame, car moving +150px/frame world space
- **Features Tested:** mode='moving', compensation_strength, feature matching, homography
- **Expected Output:** Camera motion detected, object motion compensated correctly

#### Test 11.3: Algorithm Comparison
- **Reference:** test_11.3_algorithm_comparison_README.md
- **Content:** Reuses Test 11.1 sequence with all algorithms
- **Features Tested:** Algorithm performance/accuracy comparison
- **Expected Output:** All algorithms detect motion, performance within expected ranges

---

## Usage Instructions

### Converting SVG to Raster Formats

Most algorithms require raster images (PNG, TIFF, JPG). Convert SVG files using:

```bash
# Using ImageMagick
convert -density 300 test_image.svg test_image.png

# Using Inkscape
inkscape --export-type=png --export-dpi=300 test_image.svg -o test_image.png

# Using rsvg-convert
rsvg-convert -d 300 -p 300 test_image.svg -o test_image.png
```

### Running Tests

```python
# Example: Testing ColorRange algorithm
from app.algorithms.ColorRange.services.ColorRangeService import ColorRangeService

service = ColorRangeService()
result = service.analyze(
    input_path='test_images/batch_algorithms/ColorRange/test_2.1_rgb_color_targets.png',
    output_dir='test_results/',
    identifier=(255, 0, 0),  # Red
    min_area=100,
    max_area=50000,
    color_range=[(250, 0, 0), (255, 5, 5)]
)

# Verify expected outputs
assert len(result.areas_of_interest) == 2  # Large red + tiny red
```

### Automated Test Suite

Create automated tests using these images:

```python
import pytest
from pathlib import Path

TEST_IMAGE_DIR = Path('test_images/batch_algorithms')

@pytest.mark.parametrize('test_image,expected_detections', [
    ('ColorRange/test_2.1_rgb_color_targets.png', 2),
    ('HSVColorRange/test_3.1_hue_variation.png', 4),
    # Add more test cases
])
def test_algorithm(test_image, expected_detections):
    result = run_algorithm(TEST_IMAGE_DIR / test_image)
    assert len(result.areas_of_interest) == expected_detections
```

---

## Test Image Design Principles

All test images follow these principles:

1. **Repeatability:** Deterministic, no randomness
2. **Clarity:** Clear expected outputs documented
3. **Comprehensive:** Cover all input parameters
4. **Edge Cases:** Test boundaries, wrapping, thresholds
5. **Real-World:** Simulate actual drone imagery scenarios
6. **Scalable:** Range of image sizes matching real usage
7. **Annotated:** Embedded labels showing expected results

---

## Performance Benchmarks

### Batch Algorithms
- Small images (800x800): <1 second
- Medium images (1600x1200): <3 seconds
- Large images (2000x2000): <5 seconds
- AI models: <10 seconds with GPU

### Real-Time Algorithms
- RealtimeColorDetector: <100ms/frame
- RealtimeAnomalyDetector: <50ms/frame
- RealtimeMotionDetector: Varies by algorithm (5-60ms)

---

## Contributing New Test Images

When adding new test images:

1. Use SVG format for vector precision
2. Document expected outputs clearly
3. Test all relevant input parameters
4. Include edge cases and failure modes
5. Add to this README with full documentation
6. Verify images work with the algorithm
7. Include performance expectations

---

## File Naming Convention

```
test_[number].[sequence]_[descriptive_name].svg
```

Examples:
- `test_1.1_multi_scale_persons.svg`
- `test_11.2_moving_camera_frame3.svg`

---

## Validation Checklist

For each test image, verify:

- ✓ Image renders correctly
- ✓ Algorithm processes without errors
- ✓ Expected outputs match actual outputs
- ✓ Performance within acceptable range
- ✓ Edge cases handled properly
- ✓ Documentation complete and accurate

---

## License

These test images are part of the Automated Drone Image Analysis Tool and are provided for testing and validation purposes.

---

## Contact

For questions about test images or to report issues, please open an issue on the project repository.

---

**Last Updated:** 2025-11-08
**Total Test Images:** 30+ images/sequences
**Coverage:** 11 algorithms, all input parameters tested
