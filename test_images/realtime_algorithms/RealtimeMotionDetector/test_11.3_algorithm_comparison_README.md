# RealtimeMotionDetector Test 11.3: Algorithm Comparison

## Overview
This test validates the different motion detection algorithms available in RealtimeMotionDetector by running the same test sequence with each algorithm and comparing their performance and accuracy.

## Test Sequence
**Use Test 11.1 frames (Static Camera) for this comparison test.**

The test sequence consists of:
- Frame 1: Baseline (no motion)
- Frames 2-5: Red object moving from x=200 to x=500 (100px per frame)

## Algorithms to Test

### 1. Frame Differencing (`algorithm='frame_diff'`)
**Description:** Simple pixel-wise difference between consecutive frames

**Expected Results:**
- ✓ Motion detected in all frames 2-5
- ✓ Fastest processing time
- ✓ Bounding box around moving object
- ✓ Basic accuracy

**Performance Target:** Fastest of all algorithms

**Strengths:**
- Very fast
- Low computational cost
- Simple implementation

**Weaknesses:**
- Sensitive to noise
- May detect shadows
- Less accurate boundary detection

---

### 2. MOG2 (`algorithm='mog2'`)
**Description:** Gaussian Mixture Model background subtraction (GPU-accelerated)

**Expected Results:**
- ✓ Motion detected with high accuracy
- ✓ Clean foreground segmentation
- ✓ GPU acceleration benefit visible
- ✓ Adapts to lighting changes

**Performance Target:** Fast with GPU, moderate without

**Strengths:**
- Robust to lighting changes
- Good accuracy
- GPU support (CUDA)
- Handles shadows better

**Weaknesses:**
- Requires warm-up frames
- More memory usage
- GPU dependency for best performance

**Parameters Tested:**
- `gpu_acceleration=True` vs `False`
- History frames adaptation

---

### 3. KNN (`algorithm='knn'`)
**Description:** K-Nearest Neighbors background subtraction

**Expected Results:**
- ✓ Motion detected accurately
- ✓ Good segmentation
- ✓ Similar to MOG2 but different statistical model

**Performance Target:** Moderate speed

**Strengths:**
- Robust background modeling
- Adapts to scene changes
- Good accuracy

**Weaknesses:**
- Slower than frame_diff
- Higher computational cost than MOG2
- No GPU acceleration

---

### 4. Optical Flow (`algorithm='optical_flow'`)
**Description:** Dense optical flow for motion vector calculation

**Expected Results:**
- ✓ Motion detected with velocity vectors
- ✓ Detailed motion field visualization
- ✓ Accurate velocity estimation (~100px/frame rightward)
- ✓ Motion vectors shown if `show_vectors=True`

**Performance Target:** Slowest but most detailed

**Strengths:**
- Provides motion vectors
- Detailed motion field
- Good for velocity analysis
- Useful for tracking

**Weaknesses:**
- Computationally expensive
- Slowest algorithm
- May be overkill for simple detection

---

### 5. Feature Matching (`algorithm='feature_match'`)
**Description:** Feature-based motion estimation (used for camera motion compensation)

**Expected Results:**
- ✓ Motion detected via feature tracking
- ✓ Robust to partial occlusion
- ✓ Better for textured objects

**Performance Target:** Moderate to slow

**Strengths:**
- Robust to scale changes
- Works well with textured objects
- Good for camera motion estimation
- Handles partial occlusion

**Weaknesses:**
- Requires sufficient features
- May fail on textureless regions
- More complex

---

## Test Configuration

### Common Parameters for All Tests:
```python
{
    "mode": "static",  # Static camera mode
    "sensitivity": 0.5,
    "min_area": 500,
    "max_area": 100000,
    "motion_threshold": 25.0,
    "show_vectors": True,  # Visualize motion vectors
    "processing_resolution": None  # Full resolution
}
```

### Algorithm-Specific Parameters:
```python
# Frame Diff
{"algorithm": "frame_diff"}

# MOG2
{"algorithm": "mog2", "gpu_acceleration": True, "history_frames": 5}

# KNN
{"algorithm": "knn", "history_frames": 5}

# Optical Flow
{"algorithm": "optical_flow"}

# Feature Match
{"algorithm": "feature_match"}
```

---

## Expected Performance Comparison

### Processing Speed (Fastest → Slowest):
1. **frame_diff** - ~5-10ms per frame
2. **mog2 (GPU)** - ~10-15ms per frame
3. **knn** - ~15-20ms per frame
4. **mog2 (CPU)** - ~20-30ms per frame
5. **feature_match** - ~25-35ms per frame
6. **optical_flow** - ~40-60ms per frame

### Accuracy (Best → Good):
1. **optical_flow** - Most detailed, velocity vectors
2. **mog2** - Excellent segmentation
3. **knn** - Very good segmentation
4. **feature_match** - Good for tracking
5. **frame_diff** - Basic but functional

---

## Success Criteria

For each algorithm:
- ✓ Detects motion in frames 2-5
- ✓ No false positives in frame 1
- ✓ Bounding box encompasses moving object
- ✓ Velocity vector approximately (+100, 0) px/frame
- ✓ Confidence scores present
- ✓ Performance within expected range
- ✓ No crashes or errors

---

## Test Execution

Run the same sequence (test_11.1_static_camera_frame1-5.svg) with each algorithm:

```python
for algorithm in ['frame_diff', 'mog2', 'knn', 'optical_flow', 'feature_match']:
    detector = RealtimeMotionDetector(
        mode='static',
        algorithm=algorithm,
        sensitivity=0.5,
        min_area=500,
        max_area=100000,
        show_vectors=True
    )

    # Process frames 1-5
    for frame in [frame1, frame2, frame3, frame4, frame5]:
        detections = detector.process_frame(frame)
        # Verify detections match expectations
```

---

## Additional Tests

### GPU Acceleration Test (MOG2 only):
Compare `gpu_acceleration=True` vs `gpu_acceleration=False`
- Expect significant speedup with GPU
- Results should be identical

### Sensitivity Test:
Run with `sensitivity` values: 0.1, 0.5, 0.9
- Low sensitivity: May miss subtle motion
- High sensitivity: May detect noise as motion

### Area Filtering Test:
- `min_area=50`: Should detect object (10,000 px > 50)
- `min_area=20000`: Should NOT detect object (10,000 px < 20,000)

---

## Conclusion

This comparison test validates that all motion detection algorithms:
1. Successfully detect motion in the test scenario
2. Perform within expected latency ranges
3. Provide appropriate output formats
4. Handle the static camera case correctly
5. Can be swapped without code changes (algorithm parameter only)

The choice of algorithm should be based on:
- **Speed requirements** → frame_diff or mog2 (GPU)
- **Accuracy requirements** → optical_flow or mog2
- **Detailed motion analysis** → optical_flow
- **Real-time with quality** → mog2 (GPU)
- **Simple/fast** → frame_diff
