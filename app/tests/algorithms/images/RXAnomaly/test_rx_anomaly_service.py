import pytest
import numpy as np
import cv2
import tempfile
import os
from algorithms.images.RXAnomaly.services.RXAnomalyService import RXAnomalyService
from algorithms.AlgorithmService import AnalysisResult
from core.services.AnalyzeService import AnalyzeService


@pytest.fixture
def rx_anomaly_service():
    """Fixture providing an RXAnomalyService instance."""
    options = {
        'sensitivity': 7,
        'segments': 2
    }
    return RXAnomalyService(
        identifier=(255, 0, 0),
        min_area=10,
        max_area=1000,
        aoi_radius=5,
        combine_aois=True,
        options=options
    )


@pytest.fixture
def test_image():
    """Create a test image."""
    img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    return img


def test_rx_anomaly_service_initialization(rx_anomaly_service):
    """Test RXAnomalyService initialization."""
    assert rx_anomaly_service.name == 'RXAnomaly'
    assert rx_anomaly_service.chi_threshold is not None
    assert rx_anomaly_service.segments == 2


def test_get_threshold(rx_anomaly_service):
    """Test threshold calculation from sensitivity."""
    # Test different sensitivity values
    thresholds = []
    for sensitivity in range(1, 11):
        threshold = rx_anomaly_service.get_threshold(sensitivity)
        thresholds.append(threshold)

    # Thresholds should increase with sensitivity
    assert all(thresholds[i] <= thresholds[i + 1] for i in range(len(thresholds) - 1))


def test_process_image(rx_anomaly_service, test_image):
    """Test processing an image with RX Anomaly algorithm."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = tmpdir
        output_dir = os.path.join(tmpdir, "output")
        os.makedirs(output_dir, exist_ok=True)
        full_path = os.path.join(input_dir, "test.jpg")

        result = rx_anomaly_service.process_image(test_image, full_path, input_dir, output_dir)

        assert isinstance(result, AnalysisResult)
        assert result.input_path == full_path
        assert result.error_message is None


def test_process_image_hue_expansion(rx_anomaly_service, test_image):
    """Test processing with hue expansion enabled."""
    rx_anomaly_service.options['hue_expansion_enabled'] = True
    rx_anomaly_service.options['hue_expansion_range'] = 10

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = tmpdir
        output_dir = os.path.join(tmpdir, "output")
        os.makedirs(output_dir, exist_ok=True)
        full_path = os.path.join(input_dir, "test.jpg")

        result = rx_anomaly_service.process_image(test_image, full_path, input_dir, output_dir)

        assert isinstance(result, AnalysisResult)
        assert result.error_message is None


def test_add_confidence_scores(rx_anomaly_service):
    """Test adding confidence scores to AOIs."""
    areas_of_interest = [
        {
            'center': (50, 50),
            'radius': 10,
            'detected_pixels': [(45, 45), (46, 46), (47, 47)]
        }
    ]

    rx_values = np.zeros((100, 100), dtype=np.float32)
    rx_values[45:48, 45:48] = 100.0  # High RX value = anomaly

    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[45:48, 45:48] = 1

    result = rx_anomaly_service._add_confidence_scores(
        areas_of_interest, rx_values, mask
    )

    assert len(result) == 1
    assert 'confidence' in result[0]
    assert 'score_type' in result[0]
    assert result[0]['score_type'] == 'anomaly'  # Service uses 'anomaly', not 'rx_anomaly'


def test_add_confidence_scores_reads_aoi_pixels_unscaled(rx_anomaly_service):
    # Inside process_image() AOIs are at processing resolution, like rx_values:
    # AnalyzeService maps them to original resolution only after it returns. So at
    # 50% the pixel at (20, 20) is scored at (20, 20), not halved again to (10, 10).
    rx_anomaly_service.set_scale_factor(0.5)
    areas_of_interest = [{'center': (20, 20), 'detected_pixels': [(20, 20)]}]
    rx_values = np.zeros((30, 30), dtype=np.float32)
    rx_values[20, 20] = 80.0
    rx_values[10, 10] = 20.0
    mask = np.zeros((30, 30), dtype=np.uint8)
    mask[20, 20] = 1
    mask[10, 10] = 1

    result = rx_anomaly_service._add_confidence_scores(areas_of_interest, rx_values, mask)
    assert result[0]['raw_score'] == pytest.approx(80.0)
    assert result[0]['confidence'] == pytest.approx(100.0)


def _three_anomalies_frame():
    """A noisy grey 400x400 frame holding three anomalies of different strength.

    The noise is drawn at 200x200 and repeated over 2x2 blocks, and every
    anomaly edge sits on an even pixel, so a 50% INTER_AREA resize returns the
    same pixel population: the background statistics RX measures against are
    unchanged, and any score difference comes from the lookup, not resampling.
    """
    rng = np.random.default_rng(7)
    background = rng.normal(128, 6, (200, 200, 3)).clip(0, 255).astype(np.uint8)
    img = np.repeat(np.repeat(background, 2, axis=0), 2, axis=1)
    img[40:60, 40:60] = (40, 40, 220)
    img[40:60, 300:320] = (100, 170, 100)
    img[300:320, 300:320] = (200, 110, 60)
    return img


def _analyze_at_resolution(img, processing_resolution):
    """Run one frame through AnalyzeService.process_file, the production ordering."""
    algorithm = {'name': 'RXAnomaly', 'service': 'RXAnomalyService', 'combine_overlapping_aois': False}
    options = {'sensitivity': 5, 'segments': 1}
    with tempfile.TemporaryDirectory() as tmpdir:
        full_path = os.path.join(tmpdir, 'frame.png')
        cv2.imencode('.png', img)[1].tofile(full_path)
        # min_area 40 drops single noise blocks (4 px) and keeps the 400 px anomalies.
        result = AnalyzeService.process_file(
            algorithm, (255, 0, 0), 40, 0, 5, options, full_path, tmpdir,
            os.path.join(tmpdir, 'output'), None, None, False, processing_resolution)
    assert result.error_message is None
    return sorted(result.areas_of_interest, key=lambda aoi: aoi['center'])


def test_confidence_scores_match_at_half_processing_resolution():
    frame = _three_anomalies_frame()
    full = _analyze_at_resolution(frame, 1.0)
    half = _analyze_at_resolution(frame, 0.5)

    assert len(full) == len(half) == 3
    # The scene discriminates: the red block is the strongest anomaly, the green the weakest.
    assert [aoi['confidence'] for aoi in full] == [100.0, pytest.approx(0.0, abs=0.1), pytest.approx(16.7, abs=1)]
    for full_aoi, half_aoi in zip(full, half):
        assert half_aoi['center'] == pytest.approx(full_aoi['center'], abs=2)
        assert half_aoi['raw_score'] == pytest.approx(full_aoi['raw_score'], rel=1e-3)
        assert half_aoi['confidence'] == pytest.approx(full_aoi['confidence'], abs=0.5)
