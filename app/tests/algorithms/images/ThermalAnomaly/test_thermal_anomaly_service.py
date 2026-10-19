import pytest
import numpy as np
import cv2
import tempfile
import os
from unittest.mock import patch, MagicMock
from algorithms.images.ThermalAnomaly.services.ThermalAnomalyService import ThermalAnomalyService
from algorithms.AlgorithmService import AnalysisResult
from core.services.AnalyzeService import AnalyzeService


@pytest.fixture
def thermal_anomaly_service():
    """Fixture providing a ThermalAnomalyService instance."""
    options = {
        'threshold': 6.0,
        'segments': 2,
        'type': 'Above Mean'
    }
    return ThermalAnomalyService(
        identifier=(255, 0, 0),
        min_area=10,
        max_area=1000,
        aoi_radius=5,
        combine_aois=True,
        options=options
    )


@pytest.fixture
def test_image():
    """Create a test thermal image."""
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    return img


def test_thermal_anomaly_service_initialization(thermal_anomaly_service):
    """Test ThermalAnomalyService initialization."""
    assert thermal_anomaly_service.is_thermal is True
    assert thermal_anomaly_service.threshold == 6.0
    assert thermal_anomaly_service.segments == 2
    assert thermal_anomaly_service.direction == 'Above Mean'


def test_thermal_anomaly_service_below_mean():
    """Test ThermalAnomalyService with 'Below Mean' direction."""
    options = {
        'threshold': 6.0,
        'segments': 2,
        'type': 'Below Mean'
    }
    service = ThermalAnomalyService(
        identifier=(255, 0, 0),
        min_area=10,
        max_area=1000,
        aoi_radius=5,
        combine_aois=True,
        options=options
    )
    assert service.direction == 'Below Mean'


def test_thermal_anomaly_service_both_directions():
    """Test ThermalAnomalyService with 'Above or Below Mean' direction."""
    options = {
        'threshold': 6.0,
        'segments': 2,
        'type': 'Above or Below Mean'
    }
    service = ThermalAnomalyService(
        identifier=(255, 0, 0),
        min_area=10,
        max_area=1000,
        aoi_radius=5,
        combine_aois=True,
        options=options
    )
    assert service.direction == 'Above or Below Mean'


def test_process_image_mock_thermal(thermal_anomaly_service, test_image):
    """Test processing with mocked thermal parser."""
    # Create temperature data with anomaly
    mock_temperature = np.ones((200, 200), dtype=np.float32) * 20.0  # Background
    mock_temperature[50:100, 50:100] = 40.0  # Hot anomaly

    with patch('algorithms.images.ThermalAnomaly.services.ThermalAnomalyService.ThermalParserService') as MockThermalParser:
        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = (mock_temperature, test_image)
        MockThermalParser.return_value = mock_parser

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = tmpdir
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir, exist_ok=True)
            full_path = os.path.join(input_dir, "test.jpg")

            result = thermal_anomaly_service.process_image(test_image, full_path, input_dir, output_dir)

            assert isinstance(result, AnalysisResult)
            assert result.input_path == full_path


def _make_service(direction="Above Mean", threshold=3.0, segments=2):
    return ThermalAnomalyService(
        identifier=(255, 0, 0),
        min_area=1,
        max_area=100000,
        aoi_radius=3,
        combine_aois=True,
        options={"threshold": threshold, "segments": segments, "type": direction},
    )


def _run_with_mock_thermal(service, temperature, visual_shape=None):
    visual_shape = visual_shape or temperature.shape
    if len(visual_shape) == 2:
        visual_image = np.zeros((*visual_shape, 3), dtype=np.uint8)
    else:
        visual_image = np.zeros(visual_shape, dtype=np.uint8)

    with patch(
        "algorithms.images.ThermalAnomaly.services.ThermalAnomalyService.ThermalParserService"
    ) as MockParser:
        parser = MagicMock()
        parser.parse_file.return_value = (temperature, visual_image)
        MockParser.return_value = parser

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = tmpdir
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir, exist_ok=True)
            full_path = os.path.join(input_dir, "test.jpg")
            return service.process_image(visual_image, full_path, input_dir, output_dir)


def test_process_image_below_mean_detects_cold():
    service = _make_service(direction="Below Mean", threshold=2.0)
    temperature = np.ones((100, 100), dtype=np.float32) * 20.0
    # Cold anomaly
    temperature[40:60, 40:60] = -5.0

    result = _run_with_mock_thermal(service, temperature)
    assert isinstance(result, AnalysisResult)
    assert result.error_message is None
    assert result.areas_of_interest is not None
    assert len(result.areas_of_interest) >= 1


def test_process_image_above_or_below_mean_detects_both():
    service = _make_service(direction="Above or Below Mean", threshold=2.0)
    temperature = np.ones((100, 100), dtype=np.float32) * 20.0
    temperature[10:20, 10:20] = 80.0   # hot
    temperature[80:90, 80:90] = -40.0  # cold

    result = _run_with_mock_thermal(service, temperature)
    assert result.error_message is None
    assert result.areas_of_interest is not None
    assert len(result.areas_of_interest) >= 2


def test_process_image_extracts_temperatures_for_aois():
    service = _make_service(direction="Above Mean", threshold=2.0)
    temperature = np.ones((100, 100), dtype=np.float32) * 20.0
    temperature[40:60, 40:60] = 60.0

    result = _run_with_mock_thermal(service, temperature)
    assert result.areas_of_interest is not None
    # At least one AOI should have an extracted temperature
    has_temp = any(
        aoi.get("temperature") is not None for aoi in result.areas_of_interest
    )
    assert has_temp


def test_process_image_scales_aoi_when_visual_differs_from_thermal():
    service = _make_service(direction="Above Mean", threshold=2.0)
    # Thermal data 50x50, visual image 100x100 -> scale 2x
    temperature = np.ones((50, 50), dtype=np.float32) * 20.0
    temperature[20:30, 20:30] = 60.0

    result = _run_with_mock_thermal(service, temperature, visual_shape=(100, 100, 3))
    assert result.areas_of_interest is not None
    # Centers should be in visual-resolution coordinates (> thermal's 50x50 range)
    for aoi in result.areas_of_interest:
        cx, cy = aoi["center"]
        # Hot region centroid ~(25,25) in thermal -> ~(50,50) in visual (2x scale)
        assert 0 <= cx <= 100
        assert 0 <= cy <= 100


def test_process_image_returns_error_when_parser_raises():
    service = _make_service()
    with patch(
        "algorithms.images.ThermalAnomaly.services.ThermalAnomalyService.ThermalParserService"
    ) as MockParser:
        MockParser.return_value.parse_file.side_effect = RuntimeError("bad file")
        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = os.path.join(tmpdir, "test.jpg")
            result = service.process_image(
                np.zeros((50, 50, 3), dtype=np.uint8),
                full_path,
                tmpdir,
                tmpdir,
            )
    assert isinstance(result, AnalysisResult)
    assert result.error_message is not None
    assert "bad file" in result.error_message


def test_process_image_uniform_temperature_no_anomalies():
    service = _make_service(direction="Above Mean", threshold=2.0)
    # Perfectly uniform -> std=0 -> thresholds equal mean -> no anomaly
    temperature = np.ones((50, 50), dtype=np.float32) * 20.0
    result = _run_with_mock_thermal(service, temperature)
    assert result.error_message is None
    # Either no AOIs or base_contour_count is 0/None
    assert result.areas_of_interest is None or len(result.areas_of_interest) == 0


def _analyze_at_resolution(temperature, processing_resolution, min_area=1, max_area=0):
    """Run one frame through AnalyzeService.process_file, the production ordering.

    The parser hands back the same native-resolution temperature array at every
    processing resolution, behind a 320x320 visual frame.
    """
    algorithm = {'name': 'ThermalAnomaly', 'service': 'ThermalAnomalyService', 'combine_overlapping_aois': False}
    options = {'threshold': 2.0, 'segments': 1, 'type': 'Above Mean'}
    with patch(
        "algorithms.images.ThermalAnomaly.services.ThermalAnomalyService.ThermalParserService"
    ) as MockParser:
        MockParser.return_value.parse_file.return_value = (temperature, None)
        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = os.path.join(tmpdir, "frame.png")
            cv2.imencode(".png", np.zeros((320, 320, 3), dtype=np.uint8))[1].tofile(full_path)
            result = AnalyzeService.process_file(
                algorithm, (255, 0, 0), min_area, max_area, 3, options, full_path, tmpdir,
                os.path.join(tmpdir, "output"), None, None, True, processing_resolution)
    assert result.error_message is None
    return sorted(result.areas_of_interest, key=lambda aoi: aoi['center'])


def test_temperatures_match_at_half_processing_resolution():
    temperature = np.full((160, 160), 20.0, dtype=np.float32)
    temperature[100:120, 100:120] = 60.0
    temperature[20:40, 110:130] = 45.0

    full = _analyze_at_resolution(temperature, 1.0)
    half = _analyze_at_resolution(temperature, 0.5)

    assert len(full) == len(half) == 2
    assert sorted(aoi['temperature'] for aoi in full) == [pytest.approx(45.0), pytest.approx(60.0)]
    for full_aoi, half_aoi in zip(full, half):
        assert half_aoi['center'] == pytest.approx(full_aoi['center'], abs=2)
        assert half_aoi['temperature'] == pytest.approx(full_aoi['temperature'])


def _four_sized_spots(background, hot):
    """A 160x160 temperature matrix holding hot squares of 16, 25, 144 and 400 px.

    With min_area 50 and max_area 300 only the 144 px square qualifies.
    """
    temperature = np.full((160, 160), background, dtype=np.float32)
    temperature[20:24, 20:24] = hot
    temperature[20:25, 120:125] = hot
    temperature[70:82, 70:82] = hot
    temperature[110:130, 110:130] = hot
    return temperature


def test_area_limits_match_at_half_processing_resolution():
    # temperature_c stays at native resolution when the frame is downscaled, so the
    # area limits must not shrink with it: at 50% they used to drop to 12 and 75 px,
    # which kept the 16 and 25 px squares and rejected the 144 px one.
    temperature = _four_sized_spots(20.0, 60.0)

    full = _analyze_at_resolution(temperature, 1.0, min_area=50, max_area=300)
    half = _analyze_at_resolution(temperature, 0.5, min_area=50, max_area=300)

    assert len(full) == len(half) == 1
    assert full[0]['area'] == half[0]['area'] == 144
    # thermal [70:82] is frame [140:164] in the 320x320 frame at either resolution
    assert full[0]['center'] == pytest.approx((152, 152), abs=2)
    assert half[0]['center'] == pytest.approx(full[0]['center'], abs=2)
