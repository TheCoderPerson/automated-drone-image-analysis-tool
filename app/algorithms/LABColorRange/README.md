# LAB Color Range Algorithm

## Overview

The LAB Color Range algorithm provides color-based image analysis using the **LAB colorspace**, which offers more perceptually uniform color representation compared to RGB. LAB colorspace separates luminance (L) from chromaticity (A and B channels), making it excellent for color-based object detection where lighting conditions may vary.

## What is LAB Colorspace?

LAB (also called CIELAB) is a color space that separates:

- **L (Lightness)**: Ranges from 0 (black) to 100 (white)
- **A**: Ranges from -128 (green) to +127 (red)
- **B**: Ranges from -128 (blue) to +127 (yellow)

### Advantages of LAB over HSV/RGB

1. **Perceptually Uniform**: Color differences in LAB space correspond more closely to human perception
2. **Lighting Independent**: The L channel separates brightness from color, making it robust to lighting changes
3. **No Hue Wraparound**: Unlike HSV, there's no circular hue component, simplifying range selection
4. **Better for Specific Colors**: Excellent for detecting yellows, greens, and other colors that may be hard to isolate in HSV

## Algorithm Features

### Color Selection Interface

The LAB Color Range algorithm provides an intuitive interface for selecting colors and defining search ranges:

1. **A/B Color Plane**: Interactive 2D selector showing all possible A/B color combinations at the current lightness level
2. **Lightness Slider**: Vertical gradient slider for selecting the L value (0-100)
3. **Range Controls**: Separate +/- spinboxes for each channel (L, A, B)
4. **Color Picker**: Standard color picker integration
5. **Custom Colors**: Save and reuse frequently used colors
6. **Live Preview**: See filtering results in real-time when analyzing images

### Algorithm Parameters

The algorithm accepts the following parameters:

#### LAB Color Values (Normalized 0-1 range internally)
- **L (Lightness)**: 0-255 in OpenCV (0-1 normalized)
- **A (green-red)**: 0-255 in OpenCV, where 128=neutral (-1 to 1 normalized)
- **B (blue-yellow)**: 0-255 in OpenCV, where 128=neutral (-1 to 1 normalized)

#### Range Tolerances
- **L Minus/Plus**: How much lighter or darker (0-255)
- **A Minus/Plus**: How much greener or redder (0-128)
- **B Minus/Plus**: How much bluer or yellower (0-128)

## Usage

### Basic Workflow

1. **Select Algorithm**: Choose "Color Range (LAB)" from the algorithm dropdown
2. **Pick Color**: Click the "Pick Color" button to open the LAB color picker
3. **Adjust Color**:
   - Click on the A/B plane to select the color (green-red vs blue-yellow)
   - Adjust the L slider to set the lightness
   - Use the hex input or basic colors for quick selection
4. **Set Ranges**:
   - Adjust the L-, L+, A-, A+, B-, B+ spinboxes to set tolerance ranges
   - Larger ranges = more colors detected, but less specific
   - Smaller ranges = more precise detection, but may miss similar colors
5. **Test**: Click "View Range" to see the color filtering preview (if implemented)
6. **Run Analysis**: Process your images using the configured LAB ranges

### Tips for Best Results

#### When to Use LAB Instead of HSV

- **Detecting specific colors under varying lighting**: LAB's L channel makes it robust to brightness changes
- **Yellows and greens**: These colors can be challenging in HSV but work well in LAB
- **Precise color matching**: LAB's perceptual uniformity provides more intuitive color selection
- **Scientific/industrial applications**: LAB is a standard in color science

#### Recommended Range Settings

| Color Type | L Range | A Range | B Range | Notes |
|------------|---------|---------|---------|-------|
| **Bright Colors** | ±10-20 | ±15-25 | ±15-25 | Tight L range, moderate A/B |
| **Dark Colors** | ±15-30 | ±20-30 | ±20-30 | Wider ranges needed |
| **Pastels** | ±5-15 | ±10-20 | ±10-20 | Tight ranges for precision |
| **Neutral Colors** | ±20-40 | ±5-10 | ±5-10 | Wide L, tight A/B |

#### Common Issues and Solutions

**Problem**: Too many false positives
- **Solution**: Reduce the range values, especially in the A and B channels

**Problem**: Missing parts of the target color
- **Solution**: Increase range values gradually; check if lighting is causing L channel variation

**Problem**: Color selection doesn't match expectation
- **Solution**: LAB colorspace can look different from RGB. Use the live preview to validate your selection

## Technical Details

### Color Conversion

The algorithm performs the following conversions:

1. **Input**: RGB color selection from user
2. **Conversion**: RGB → LAB using OpenCV's `cv2.cvtColor(img, cv2.COLOR_RGB2LAB)`
3. **Normalization**:
   - L: 0-255 → 0-1
   - A: 0-255 (128=neutral) → -1 to 1
   - B: 0-255 (128=neutral) → -1 to 1
4. **Processing**: Apply range filtering on LAB image
5. **Output**: Binary mask and detected contours

### Files Structure

```
LABColorRange/
├── __init__.py                           # Package initialization
├── README.md                             # This file
├── controllers/
│   ├── __init__.py
│   └── LABColorRangeController.py       # UI controller and event handling
├── services/
│   ├── __init__.py
│   └── LABColorRangeService.py          # Image processing service
└── views/
    ├── __init__.py
    ├── LABColorRange_ui.py              # Qt UI components
    ├── lab_color_range_dialog.py       # Color picker dialog
    └── lab_range_picker.py              # LAB color/range selector widget
```

### Key Classes

#### LABColorRangeService
- **Purpose**: Processes images using LAB color filtering
- **Key Methods**:
  - `process_image()`: Converts image to LAB, creates mask, finds contours
  - Uses `ColorUtils.get_lab_color_range()` for range calculations

#### LABColorRangeController
- **Purpose**: Manages UI interactions and user input
- **Key Methods**:
  - `color_button_clicked()`: Opens LAB color picker dialog
  - `get_options()`: Returns configuration for service
  - `load_options()`: Restores saved settings

#### LABRangePickerWidget
- **Purpose**: Interactive LAB color and range selection
- **Components**:
  - `ABPlaneWidget`: 2D A/B color plane selector
  - `LightnessWidget`: L channel slider
  - Range spinboxes for tolerance control

## Algorithm Comparison

| Feature | RGB | HSV | **LAB** |
|---------|-----|-----|---------|
| Perceptual Uniformity | Poor | Medium | **Excellent** |
| Lighting Independence | Poor | Medium | **Excellent** |
| Color Intuition | Good | **Excellent** | Medium |
| Hue Wraparound | N/A | Complex | **None** |
| Best For | Simple tasks | Colorful objects | **Precise color matching** |

## Example Use Cases

1. **Agricultural Monitoring**: Detect yellowing leaves (disease indicators) vs healthy green foliage
2. **Quality Control**: Identify color defects in manufacturing where lighting varies
3. **Medical Imaging**: Detect color changes in tissue samples
4. **Environmental Monitoring**: Track vegetation health with precise green detection
5. **Underwater Imaging**: Better color discrimination in challenging lighting

## Related Algorithms

- **Color Range (RGB)**: Simple RGB-based color detection
- **Color Range (HSV)**: Hue-based color detection with hue wraparound support

## References

- **CIELAB Color Space**: [Wikipedia](https://en.wikipedia.org/wiki/CIELAB_color_space)
- **OpenCV LAB Conversion**: [OpenCV Docs](https://docs.opencv.org/master/de/d25/imgproc_color_conversions.html)
- **Color Science**: CIE (International Commission on Illumination) standards

## Version History

- **v1.0**: Initial implementation with LAB color picker and range controls

## Contributing

When modifying this algorithm:
1. Maintain backward compatibility with saved configurations
2. Update this README with any new features
3. Test color conversions thoroughly (LAB ↔ RGB)
4. Ensure UI spinbox ranges match internal normalization

---

*Part of the Automated Drone Image Analysis Tool (ADIAT)*
