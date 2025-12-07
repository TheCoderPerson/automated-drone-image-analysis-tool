# Real-Time Detection Systems Analysis

This document provides a comprehensive technical analysis of the two real-time detection systems in ADIAT: **HSV Color Detection** and **Color Anomaly Detection**. It covers algorithm details, discovered issues, performance optimization opportunities, and code deduplication recommendations.

---

## Table of Contents

1. [Overview](#overview)
2. [Real-Time Color Anomaly Detection](#real-time-color-anomaly-detection)
   - [Algorithm Deep Dive](#algorithm-deep-dive)
   - [Processing Flow](#processing-flow)
   - [Detection Ranking](#detection-ranking)
   - [Discovered Bug: Early Stopping Before Sorting](#discovered-bug-early-stopping-before-sorting)
3. [Real-Time HSV Color Detection](#real-time-hsv-color-detection)
   - [Algorithm Overview](#algorithm-overview)
   - [Processing Flow](#hsv-processing-flow)
4. [Side-by-Side Comparison](#side-by-side-comparison)
5. [Shared Components Analysis](#shared-components-analysis)
6. [Performance Optimization Opportunities](#performance-optimization-opportunities)
7. [Recommendations](#recommendations)

---

## Overview

ADIAT includes two real-time detection services for live video streams:

| Service | Purpose | File |
|---------|---------|------|
| **HSV Color Detection** | Find specific target colors (user-defined HSV ranges) | `RealtimeColorDetectionService.py` |
| **Color Anomaly Detection** | Find rare/unusual colors using histogram analysis | `RealtimeIntegratedDetectionService.py` |

Both services share significant code and architectural patterns but were developed independently, leading to duplication and inconsistent approaches.

---

## Real-Time Color Anomaly Detection

### Algorithm Deep Dive

The color anomaly detection uses **histogram-based color quantization** to identify pixels with rare/unusual colors in each frame.

#### Step 1: Downsampling (Performance Optimization)

```python
# Reduce resolution by 2x (4x fewer pixels to process)
h, w = frame_bgr.shape[:2]
downsampled = cv2.resize(frame_bgr, (w // 2, h // 2), interpolation=cv2.INTER_LINEAR)
```

A 1280x720 frame becomes 640x360 for color analysis. **Note:** This is an *additional* 2x downsample on top of the processing resolution.

#### Step 2: Color Quantization

```python
# Reduce color depth from 8-bit (256 values) to N-bit (e.g., 32 values) per channel
bits = config.color_quantization_bits  # Default: 5
scale = 2 ** (8 - bits)  # = 8 for 5-bit
quantized = (downsampled // scale).astype(np.uint8)
```

This reduces the color space from 16.7 million colors (256³) to 32,768 colors (32³ for 5-bit), making histogram analysis tractable.

**Example:** RGB(137, 82, 201) → RGB(17, 10, 25) in quantized space

#### Step 3: Build Color Histogram

```python
# Convert each pixel's RGB to a single index
# idx = B + G*32 + R*32² (for 5-bit quantization)
color_indices = (
    quantized[:, :, 0].astype(np.int32) +           # Blue
    quantized[:, :, 1].astype(np.int32) * 32 +      # Green
    quantized[:, :, 2].astype(np.int32) * 32 ** 2   # Red
)

# Count occurrences of each color
histogram = np.bincount(color_indices.ravel(), minlength=32768)
```

#### Step 4: Identify Rare Colors

```python
# Find colors in the bottom N% by frequency
percentile_threshold = np.percentile(nonzero_counts, config.color_rarity_percentile)

# Cap at 5% of frame (prevents common colors being marked rare)
absolute_max = total_pixels * 0.05
threshold = min(percentile_threshold, absolute_max)

# Mark bins as "rare" if below threshold
rare_bins = (histogram > 0) & (histogram < threshold)
rare_bins[0] = False  # Exclude black/background
```

#### Step 5: Create Binary Mask

```python
# For each pixel, check if its color is in a "rare" bin
rare_mask_small = rare_bins[color_indices].astype(np.uint8) * 255

# Upscale back to processing resolution
rare_mask = cv2.resize(rare_mask_small, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)

# Clean up noise with morphology
rare_mask = cv2.morphologyEx(rare_mask, cv2.MORPH_OPEN, kernel)
rare_mask = cv2.morphologyEx(rare_mask, cv2.MORPH_CLOSE, kernel)
```

#### Step 6: Find Contours

```python
contours, _ = cv2.findContours(rare_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
```

OpenCV's `findContours` uses the **Suzuki-Abe algorithm** which scans the image in **raster order** (top-to-bottom, left-to-right). Contours are returned in the order their first pixel is encountered during this scan.

#### Step 7: Process Contours into Detections

```python
for contour in contours:
    area = cv2.contourArea(contour)
    x, y, w, h = cv2.boundingRect(contour)

    # Calculate confidence based on color rarity
    bin_idx = color_indices[cy // 2, cx // 2]
    bin_count = histogram[bin_idx]
    rarity = 1.0 - (bin_count / total_pixels)
    confidence = min(1.0, rarity * 2.0)

    detection = Detection(bbox, centroid, area, confidence, ...)
```

### Processing Flow

```
Original Frame (1920x1080)
        │
        ▼
Processing Resolution (640x360)      ◄── First downsample (configurable)
        │
        ├──► Motion Detection (640x360 grayscale)
        │
        ▼
Color Analysis Resolution (320x180)  ◄── Second downsample (hardcoded 2x)
        │
        ▼
Build Histogram & Find Rare Colors
        │
        ▼
Mask at 320x180
        │
        ▼
Upscale Mask to 640x360              ◄── Unnecessary resize
        │
        ▼
Find Contours (at 640x360)
        │
        ▼
Detections (coords at 640x360)
        │
        ▼
Rendering (scale to original or render at processing res)
```

### Detection Ranking

#### How Detections Are Ranked

Detections are ranked by **confidence** (descending):

```python
# Confidence based on color rarity
rarity = 1.0 - (bin_count / total_pixels)  # Rare colors = high value
confidence = min(1.0, rarity * 2.0)        # Scale to 0-1
```

#### Render Limiting

When `max_detections_to_render` is exceeded, detections are re-sorted by `confidence × area`:

```python
if config.max_detections_to_render > 0 and len(detections) > config.max_detections_to_render:
    sorted_detections = sorted(detections, key=lambda d: d.confidence * d.area, reverse=True)
    render_detections = sorted_detections[:config.max_detections_to_render]
```

### Discovered Bug: Early Stopping Before Sorting

#### The Problem

**Early stopping is applied BEFORE confidence-based sorting**, causing detections to be limited based on **spatial position** rather than **quality/confidence**.

#### Root Cause

**Step 1 - Detection limit is calculated:**
```python
# Line 1710-1711
max_to_detect = config.max_detections_to_render * 2 if config.max_detections_to_render > 0 else 0
```

**Step 2 - Early stopping happens DURING contour processing:**
```python
# Lines 1035-1038
for contour in contours:
    if max_detections > 0 and len(detections) >= max_detections:
        break  # STOPS BEFORE SORTING!
```

**Step 3 - Sorting only happens at RENDER time on the already-limited subset:**
```python
# Lines 1784-1789
if config.max_detections_to_render > 0 and len(detections) > config.max_detections_to_render:
    detections_sorted = sorted(detections, key=lambda d: d.confidence * d.area, reverse=True)
    detections_to_render = detections_sorted[:config.max_detections_to_render]
```

#### Impact

If `max_detections_to_render = 10`:
- `max_to_detect = 10 * 2 = 20`
- Only first 20 contours are processed (spatial order from raster scan)
- Contours 21-100 are **never evaluated**
- Those 20 are sorted, top 10 rendered

**Result:** You get the best 10 out of the first 20 spatially, NOT the best 10 out of all detections.

#### Affected Methods

This bug exists in all four detection methods:
- `_baseline_detect_720p()` (line 659-662)
- `_mog2_detect()` (line 736-739)
- `_knn_detect()` (line 804-807)
- `_color_quantization_detect()` (line 1035-1038)

#### Recommended Fix

**Option 1: Pre-sort Contours by Area (Recommended)**

Sort contours by area BEFORE processing, then apply early stopping:

```python
def _color_quantization_detect(self, frame_bgr, config, max_detections=0):
    contours, _ = cv2.findContours(rare_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Pre-sort contours by area (largest first) - cv2.contourArea is cheap
    contours_with_area = [(c, cv2.contourArea(c)) for c in contours]
    contours_with_area.sort(key=lambda x: x[1], reverse=True)

    detections = []
    for contour, area in contours_with_area:
        # Early stopping now works on LARGEST contours first
        if max_detections > 0 and len(detections) >= max_detections:
            break

        # Area already calculated, skip redundant call
        if area < config.min_area or area > config.max_area:
            continue

        # ... rest of processing ...
```

**Cost:** One extra `cv2.contourArea()` call per contour + sort
**Benefit:** Early stopping now prioritizes larger (more visible) detections

---

## Real-Time HSV Color Detection

### Algorithm Overview

HSV color detection finds pixels matching **specific target colors** (user-defined HSV ranges), unlike anomaly detection which finds **rare/unusual colors**.

```
Input Frame → Downsample (1x) → Convert to HSV → Apply HSV Range Mask →
Morphology → Find Contours → Process Detections → Scale to Original
```

### HSV Processing Flow

```
Original Frame (1920x1080)
        │
        ▼
Processing Resolution (640x360)      ◄── Single downsample (configurable)
        │
        ├──► Motion Detection (can use separate resolution)
        │
        ▼
Convert BGR → HSV                    ◄── Color space conversion
        │
        ▼
cv2.inRange(hsv, lower, upper)       ◄── Create binary mask for target color
        │
        ▼
Morphology (open/close)              ◄── Noise reduction
        │
        ▼
cv2.findContours()                   ◄── Find blobs (at processing resolution)
        │
        ▼
Process Contours → Detections        ◄── Calculate confidence, bbox, etc.
        │
        ▼
Scale Detections to Original Res     ◄── coords × (1/scale_factor)
        │
        ▼
Detections (coords at original resolution)
```

### Key Differences from Anomaly Detection

| Aspect | HSV Color Detection | Color Anomaly Detection |
|--------|---------------------|------------------------|
| Downsampling | 1x to processing resolution | 2x (processing + additional 2x) |
| Mask Upscaling | None | Yes (320→640 before findContours) |
| Detection Coords | Stored at original resolution | Stored at processing resolution |
| Early Stopping | No | Yes (bug) |

---

## Side-by-Side Comparison

### Processing Differences

| Aspect | HSV Color Detection | Color Anomaly Detection |
|--------|---------------------|------------------------|
| **Purpose** | Find specific target colors | Find rare/unusual colors |
| **Color Space** | HSV | BGR (quantized) |
| **Mask Creation** | `cv2.inRange(hsv, lower, upper)` | Histogram percentile threshold |
| **Downsampling** | 1x to processing resolution | 2x (1x to processing, then 1x additional) |
| **Mask Upscaling** | None | Yes (320→640 before findContours) |
| **Contour Finding** | At processing resolution | At processing resolution (after upscale) |
| **Detection Coords** | Stored at original resolution | Stored at processing resolution |
| **Confidence Calc** | `(size_score + solidity) / 2` | `rarity * 2.0` (color bin frequency) |
| **Early Stopping** | No | Yes (bug) |
| **Motion Support** | Yes (optional, separate resolution) | Yes (built-in) |

### Visual Flow Comparison

#### HSV Color Detection
```
Original Frame (1920x1080)
        │
        ▼
SINGLE DOWNSAMPLE to 640x360
        │
        ├──► Color Detection (BGR→HSV, inRange, findContours)
        │    Coords: 640x360
        │
        ├──► Motion Detection (optional, can be separate resolution)
        │    Coords: 640x360
        │
        ▼
SCALE DETECTIONS TO ORIGINAL (1920x1080) IMMEDIATELY
        │
        ▼
Fusion / Temporal / Clustering (at original coords)
        │
        ▼
Rendering
```

#### Color Anomaly Detection
```
Original Frame (1920x1080)
        │
        ▼
FIRST DOWNSAMPLE to 640x360
        │
        ├──► Motion Detection (at 640x360)
        │    Early stopping! ◄── BUG
        │    Coords: 640x360
        │
        ├──► Color Anomaly Detection
        │    │
        │    ▼
        │    2ND DOWNSAMPLE to 320x180
        │    │
        │    ▼
        │    Quantize, Histogram, Find Rare Colors
        │    │
        │    ▼
        │    UPSCALE MASK to 640x360
        │    │
        │    ▼
        │    findContours (at 640x360)
        │    Early stopping! ◄── BUG
        │    Coords: 640x360
        │
        ▼
Fusion / Temporal / Clustering (at processing coords)
        │
        ▼
Rendering (scale coords UP to original)
```

---

## Shared Components Analysis

### Duplicated Code

Both services contain significant code duplication:

| Component | Lines of Code | Duplication Status |
|-----------|--------------|-------------------|
| `Detection` dataclass | ~20 | Fully duplicated |
| `MotionAlgorithm` enum | ~5 | Fully duplicated |
| `FusionMode` enum | ~5 | Fully duplicated |
| `FrameQueue` class | ~60 | Fully duplicated |
| `ThreadedCaptureWorker` class | ~90 | Fully duplicated |
| Motion detection (3 algorithms) | ~300 | Similar but not identical |
| Temporal voting | ~50 | Similar |
| Detection clustering | ~40 | Similar |
| Aspect ratio filter | ~20 | Similar |
| Fusion logic | ~80 | Similar |
| Rendering | ~150 | Similar |
| **Total duplicated/similar** | **~820 lines** | |

### Detailed Duplication Examples

#### Detection Data Structure
```python
# Both services define their own Detection dataclass:

# RealtimeColorDetectionService.py:254
@dataclass
class Detection:
    bbox: Tuple[int, int, int, int]
    centroid: Tuple[int, int]
    area: float
    confidence: float
    timestamp: float
    contour: np.ndarray
    detection_type: str = "color"
    color: Optional[Tuple[int, int, int]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

#### Enums
```python
# Both files define identical enums:

class MotionAlgorithm(Enum):
    FRAME_DIFF = "frame_diff"
    MOG2 = "mog2"
    KNN = "knn"

class FusionMode(Enum):
    UNION = "union"
    INTERSECTION = "intersection"
    COLOR_PRIORITY = "color_priority"
    MOTION_PRIORITY = "motion_priority"
```

#### Threaded Capture Infrastructure
Both services contain ~150 lines of identical threaded capture code:
- `FrameQueue` class
- `ThreadedCaptureWorker` class

---

## Performance Optimization Opportunities

### 1. Eliminate Double Downsampling

**Current (Anomaly Detection):**
```
1920x1080 → 640x360 → 320x180 (two resize operations)
Then: 320x180 mask → 640x360 mask (upscale)
Then: findContours at 640x360
```

**Proposed:**
```
1920x1080 → 320x180 (single resize, direct to analysis resolution)
findContours at 320x180
Scale detection coords × 6 to original
```

**Savings:** ~1-1.5ms per frame (removes one resize + mask upscale + faster contour finding)

### 2. Use Connected Components Instead of findContours

```python
# Current approach
contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
for contour in contours:
    area = cv2.contourArea(contour)      # Extra call
    x, y, w, h = cv2.boundingRect(contour)  # Extra call
    M = cv2.moments(contour)              # Extra call for centroid

# Proposed approach
num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
for i in range(1, num_labels):
    x, y, w, h, area = stats[i]          # All in one call
    cx, cy = centroids[i]                 # Already computed
```

**Savings:** ~0.5-1ms per frame (single pass vs multiple operations per contour)

### 3. Make Additional Downsampling Configurable

Current: Always 2x additional downsample (hardcoded)
Proposed: Add `color_analysis_scale` config option

```python
color_analysis_scale: float = 0.5  # 0.5 = 2x downsample, 1.0 = no additional
```

### 4. Add Color Space Options

Current: Always BGR for anomaly detection
Proposed: Allow LAB color space for better perceptual anomaly detection

```python
color_analysis_space: str = "BGR"  # Options: "BGR", "HSV", "LAB"
```

LAB would produce better anomaly detection (more perceptually accurate) at ~1-2ms additional cost.

### 5. Fix Early Stopping Bug

See [Discovered Bug section](#discovered-bug-early-stopping-before-sorting) for details.

### 6. Quantization Bits Impact

| Bits | Colors per Channel | Total Bins | Memory | Speed | Precision |
|------|-------------------|------------|--------|-------|-----------|
| 4 | 16 | 4,096 | ~4KB | Fastest | Low |
| 5 | 32 | 32,768 | ~33KB | Fast | Medium |
| 6 | 64 | 262,144 | ~262KB | Medium | High |
| 7 | 128 | 2,097,152 | ~2MB | Slow | Very High |

Current default (5 bits) is a good balance.

---

## Recommendations

### High Priority

1. **Fix Early Stopping Bug**
   - Pre-sort contours by area before processing
   - Apply early stopping on sorted list
   - Ensures highest-quality detections are always evaluated

2. **Eliminate Double Downsampling**
   - Downsample directly to color analysis resolution
   - Find contours at smaller resolution
   - Scale coordinates to original at the end
   - Expected savings: ~1-1.5ms per frame

### Medium Priority

3. **Extract Shared Components**

   Proposed structure:
   ```
   app/core/services/streaming/
   ├── common/
   │   ├── detection.py           # Detection dataclass
   │   ├── enums.py               # MotionAlgorithm, FusionMode
   │   ├── threaded_capture.py    # FrameQueue, ThreadedCaptureWorker
   │   ├── motion_detection.py    # Frame diff, MOG2, KNN algorithms
   │   ├── post_processing.py     # Temporal voting, clustering, aspect ratio
   │   └── rendering.py           # Annotation rendering
   ├── RealtimeColorDetectionService.py    # HSV-specific logic only
   └── RealtimeIntegratedDetectionService.py  # Anomaly-specific logic only
   ```

   Benefits:
   - Reduce codebase by ~400-500 lines
   - Bug fixes apply to both services
   - Easier maintenance

4. **Unify Detection Coordinate System**

   | Service | Current | Proposed |
   |---------|---------|----------|
   | HSV | Original resolution | Keep as-is |
   | Anomaly | Processing resolution | Change to original resolution |

   HSV's approach (scale immediately after detection) is cleaner.

5. **Use Connected Components**
   - Replace `findContours` + multiple calls with `connectedComponentsWithStats`
   - Single-pass extraction of bbox, centroid, and area
   - Expected savings: ~0.5-1ms per frame

### Low Priority

6. **Add Color Space Options**
   - Allow LAB for anomaly detection (better perceptual accuracy)
   - Small performance cost (~1-2ms)

7. **Make Analysis Resolution Configurable**
   - Allow users to control the additional downsampling factor
   - Default to current behavior for backward compatibility

---

## Appendix: Configuration Reference

### HSV Color Detection (HSVConfig)

```python
@dataclass
class HSVConfig:
    target_color_rgb: Tuple[int, int, int]
    hue_threshold: int = 20
    saturation_threshold: int = 50
    value_threshold: int = 50
    min_area: int = 100
    max_area: int = 50000
    confidence_threshold: float = 0.0
    morphology_enabled: bool = True
    processing_resolution: Optional[Tuple[int, int]] = None

    # Motion options
    enable_motion_detection: bool = False
    motion_algorithm: MotionAlgorithm = MotionAlgorithm.KNN
    motion_processing_resolution: Optional[Tuple[int, int]] = None

    # Post-processing
    enable_temporal_voting: bool = False
    enable_detection_clustering: bool = False
    enable_aspect_ratio_filter: bool = False

    # Rendering
    render_shape: int = 0  # 0=box, 1=circle, 2=dot, 3=off
    render_at_processing_res: bool = False
    max_detections_to_render: int = 0  # 0 = unlimited
```

### Color Anomaly Detection (IntegratedDetectionConfig)

```python
@dataclass
class IntegratedDetectionConfig:
    # Detection toggles
    enable_motion: bool = True
    enable_color_quantization: bool = False

    # Color quantization
    color_quantization_bits: int = 5
    color_rarity_percentile: float = 20.0
    color_min_detection_area: int = 50
    color_max_detection_area: int = 50000

    # Motion
    motion_algorithm: MotionAlgorithm = MotionAlgorithm.MOG2
    min_detection_area: int = 100
    max_detection_area: int = 50000

    # Post-processing
    enable_temporal_voting: bool = True
    enable_aspect_ratio_filter: bool = True
    enable_detection_clustering: bool = False

    # Rendering
    render_shape: int = 1  # 0=box, 1=circle, 2=dot, 3=off
    render_at_processing_res: bool = False
    max_detections_to_render: int = 20
```

---

*Document generated from code analysis session on the `dev` branch.*
