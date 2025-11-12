# HSV Parameter Reference Guide

## OpenCV HSV Color Space

### Range Differences from Standard HSV
OpenCV uses a scaled-down range to fit HSV values in 8-bit integers:

| Channel | Standard HSV | OpenCV HSV | Conversion |
|---------|--------------|------------|------------|
| **H (Hue)** | 0-360° | 0-179 | OpenCV = Degrees ÷ 2 |
| **S (Saturation)** | 0-100% | 0-255 | OpenCV = Percent × 2.55 |
| **V (Value/Brightness)** | 0-100% | 0-255 | OpenCV = Percent × 2.55 |

---

## HSVColorRange Threshold Parameters

### `hue_threshold`
- **Range:** 0-179 (OpenCV scale)
- **Meaning:** Plus/minus deviation from target hue
- **Applied as:** `target_hue ± hue_threshold`
- **Conversion to degrees:** `hue_threshold × 2 = degrees`

**Examples:**
```python
hue_threshold = 10  # Accepts ±10 OpenCV units = ±20 degrees
hue_threshold = 15  # Accepts ±15 OpenCV units = ±30 degrees
hue_threshold = 20  # Accepts ±20 OpenCV units = ±40 degrees
```

**Important:** Hue wrapping is automatically handled!
- If `target_hue - hue_threshold < 0`: wraps from high values (e.g., 175-179 and 0-15)
- If `target_hue + hue_threshold > 179`: wraps to low values (e.g., 165-179 and 0-5)

### `saturation_threshold`
- **Range:** 0-255
- **Meaning:** Plus/minus deviation from target saturation
- **Applied as:** `target_saturation ± saturation_threshold`
- **Clamped to:** [0, 255]

**Examples:**
```python
saturation_threshold = 30   # Accepts ±30 units on 0-255 scale (≈12% in standard HSV)
saturation_threshold = 50   # Accepts ±50 units (≈20%)
saturation_threshold = 100  # Accepts ±100 units (≈39%)
```

### `value_threshold`
- **Range:** 0-255
- **Meaning:** Plus/minus deviation from target value/brightness
- **Applied as:** `target_value ± value_threshold`
- **Clamped to:** [0, 255]

**Examples:**
```python
value_threshold = 30   # Accepts ±30 units on 0-255 scale (≈12% in standard HSV)
value_threshold = 50   # Accepts ±50 units (≈20%)
value_threshold = 100  # Accepts ±100 units (≈39%)
```

---

## Test Image Specifications

### Test 3.1: Hue Variation Test

**Parameters:**
```python
target_color = RGB(255, 0, 0)  # Red
# Converts to OpenCV HSV: H=0, S=255, V=255

hue_threshold = 10           # ±20 degrees
saturation_threshold = 30    # ±30 units (255±30 = [225, 255])
value_threshold = 30         # ±30 units (255±30 = [225, 255])
```

**Test Colors:**

| Color | RGB | Standard HSV | OpenCV HSV | Detection? | Reason |
|-------|-----|--------------|------------|------------|--------|
| Pure Red | (255,0,0) | 0°, 100%, 100% | 0, 255, 255 | ✅ YES | Exact match |
| Orange-Red | (255,64,0) | 15°, 100%, 100% | 7, 255, 255 | ✅ YES | H=7 within 0±10 |
| Deep Red | (200,0,0) | 0°, 100%, 78% | 0, 255, 200 | ✅ YES | V=200 within 255±30 |
| Pink | (255,128,128) | 0°, 50%, 100% | 0, 128, 255 | ❌ NO | S=128 outside 255±30 |
| Purple | (128,0,128) | 300°, 100%, 50% | 150, 255, 128 | ❌ NO | H=150 outside 0±10, V=128 outside 255±30 |

**Expected Detections:** 3 (Pure Red, Orange-Red, Deep Red)

### Test 3.2: Hue Wrapping Test

**Parameters:**
```python
target_color = RGB(255, 0, 0)  # Red at H=0
# Converts to OpenCV HSV: H=0, S=255, V=255

hue_threshold = 15           # ±30 degrees
saturation_threshold = 50    # ±50 units
value_threshold = 50         # ±50 units
```

**Accepted Hue Range:**
- Lower wrap: H = [0 - 15, 0 + 15] with wrapping
- Actual range: [165-179] OR [0-15] (wraps around 0/180)
- In degrees: ~330° to ~30°

**Test Colors:**

| Color | RGB | Degrees | OpenCV H | Detection? | Reason |
|-------|-----|---------|----------|------------|--------|
| Target Red | (255,0,0) | 0° | 0 | ✅ YES | Within [0-15] |
| Near-Red 1 | (255,0,50) | 348° | 174 | ✅ YES | Within [165-179] (wraps below 0°) |
| Near-Red 2 | (255,50,0) | 12° | 6 | ✅ YES | Within [0-15] |

**Expected Detections:** 3 (all detected - tests hue wrapping)

---

## Conversion Formulas

### Degrees to OpenCV Hue
```python
opencv_hue = int(degrees / 2)
# Example: 30° → 15 OpenCV units
```

### Percent to OpenCV S/V
```python
opencv_value = int(percent * 2.55)
# Example: 50% → 127-128 OpenCV units
```

### OpenCV to Standard
```python
degrees = opencv_hue * 2
percent = (opencv_value / 255) * 100
```

---

## Common Threshold Values

### Tight Tolerance (precise color matching)
```python
hue_threshold = 5          # ±10 degrees
saturation_threshold = 20  # ±8% saturation
value_threshold = 20       # ±8% brightness
```

### Medium Tolerance (typical use case)
```python
hue_threshold = 10         # ±20 degrees
saturation_threshold = 30  # ±12% saturation
value_threshold = 30       # ±12% brightness
```

### Loose Tolerance (wide color range)
```python
hue_threshold = 20         # ±40 degrees
saturation_threshold = 50  # ±20% saturation
value_threshold = 50       # ±20% brightness
```

---

## Real-Time Algorithms

### RealtimeColorDetector Default Values
```python
hue_threshold = 20           # ±40 degrees (loose for real-time)
saturation_threshold = 50    # ±20%
value_threshold = 50         # ±20%
```

These are more permissive for real-time detection to handle:
- Varying lighting conditions
- Camera noise
- Motion blur
- Compression artifacts in RTMP streams

---

## Testing Tips

### For Color Picker Tools
When creating test data:
1. Convert desired RGB to OpenCV HSV
2. Apply thresholds: `[H-h_range, H+h_range]`, `[S-s_range, S+s_range]`, `[V-v_range, V+v_range]`
3. Check for hue wrapping (if lower < 0 or upper > 179)
4. Create two ranges if wrapping occurs

### Python Conversion Example
```python
import cv2
import numpy as np

# Convert RGB to OpenCV HSV
rgb = np.uint8([[[255, 0, 0]]])  # Red
hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
print(f"OpenCV HSV: {hsv[0][0]}")  # [0, 255, 255]

# Apply thresholds
h, s, v = hsv[0][0]
hue_threshold = 10
saturation_threshold = 30
value_threshold = 30

h_low = max(0, h - hue_threshold)
h_high = min(179, h + hue_threshold)
s_low = max(0, s - saturation_threshold)
s_high = min(255, s + saturation_threshold)
v_low = max(0, v - value_threshold)
v_high = min(255, v + value_threshold)

print(f"Hue range: [{h_low}, {h_high}]")       # [0, 10]
print(f"Sat range: [{s_low}, {s_high}]")       # [225, 255]
print(f"Val range: [{v_low}, {v_high}]")       # [225, 255]
```

---

## Algorithm Code References

See implementations at:
- `app/algorithms/HSVColorRange/services/HSVColorRangeService.py` (lines 93-100)
- `app/helpers/ColorUtils.py` (lines 33-91)
- `app/core/services/RealtimeColorDetectionService.py` (real-time variant)
