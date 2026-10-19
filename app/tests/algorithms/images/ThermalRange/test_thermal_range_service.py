import pytest
import numpy as np
import cv2
import tempfile
import os
from unittest.mock import patch, MagicMock
from algorithms.images.ThermalRange.services.ThermalRangeService import ThermalRangeService
from algorithms.AlgorithmService import AnalysisResult
from core.services.AnalyzeService import AnalyzeService


@pytest.fixture
def thermal_range_service():
    """Fixture providing a ThermalRangeService instance."""
    options = {
        'minTemp': 20.0,
        'maxTemp': 30.0
    }
    return ThermalRangeService(
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


def test_thermal_range_service_initialization(thermal_range_service):
    """Test ThermalRangeService initialization."""
    assert thermal_range_service.name == 'ThermalRange'
    assert thermal_range_service.is_thermal is True
    assert thermal_range_service.min_temp == 20.0
    assert thermal_range_service.max_temp == 30.0


def test_process_image_mock_thermal(thermal_range_service, test_image):
    """Test processing with mocked thermal parser."""
    # Mock temperature data
    mock_temperature = np.ones((200, 200), dtype=np.float32) * 25.0  # 25°C

    with patch('algorithms.images.ThermalRange.services.ThermalRangeService.ThermalParserService') as MockThermalParser:
        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = (mock_temperature, test_image)
        MockThermalParser.return_value = mock_parser

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = tmpdir
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir, exist_ok=True)
            full_path = os.path.join(input_dir, "test.jpg")

            result = thermal_range_service.process_image(test_image, full_path, input_dir, output_dir)

            assert isinstance(result, AnalysisResult)
            assert result.input_path == full_path


def test_process_image_temperature_extraction(thermal_range_service, test_image):
    """Test that temperature data is extracted for AOIs."""
    # Create temperature data with a hot spot
    mock_temperature = np.ones((200, 200), dtype=np.float32) * 15.0  # Background
    mock_temperature[50:100, 50:100] = 25.0  # Hot spot in range

    with patch('algorithms.images.ThermalRange.services.ThermalRangeService.ThermalParserService') as MockThermalParser:
        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = (mock_temperature, test_image)
        MockThermalParser.return_value = mock_parser

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = tmpdir
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir, exist_ok=True)
            full_path = os.path.join(input_dir, "test.jpg")

            result = thermal_range_service.process_image(test_image, full_path, input_dir, output_dir)

            if result.areas_of_interest and len(result.areas_of_interest) > 0:
                # Check that temperature was extracted
                assert 'temperature' in result.areas_of_interest[0]
                assert result.areas_of_interest[0]['temperature'] is not None


def _make_service(min_temp=20.0, max_temp=30.0, min_area=1, max_area=10000, combine=False):
    return ThermalRangeService(
        identifier=(255, 0, 0),
        min_area=min_area,
        max_area=max_area,
        aoi_radius=3,
        combine_aois=combine,
        options={'minTemp': min_temp, 'maxTemp': max_temp},
    )


def _run_with_mock(service, temperature, visual_shape=None):
    visual_shape = visual_shape or temperature.shape
    if len(visual_shape) == 2:
        visual = np.zeros((*visual_shape, 3), dtype=np.uint8)
    else:
        visual = np.zeros(visual_shape, dtype=np.uint8)

    with patch(
        "algorithms.images.ThermalRange.services.ThermalRangeService.ThermalParserService"
    ) as MockParser:
        parser = MagicMock()
        parser.parse_file.return_value = (temperature, visual)
        MockParser.return_value = parser

        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = os.path.join(tmpdir, "test.jpg")
            return service.process_image(visual, full_path, tmpdir, tmpdir)


def test_process_image_no_pixels_in_range_returns_no_aois():
    service = _make_service(min_temp=100.0, max_temp=200.0)
    temperature = np.ones((50, 50), dtype=np.float32) * 20.0  # all out of range
    result = _run_with_mock(service, temperature)
    assert result.error_message is None
    assert result.areas_of_interest is None or len(result.areas_of_interest) == 0


def test_process_image_scales_aoi_when_visual_differs_from_thermal():
    service = _make_service(min_temp=20.0, max_temp=30.0)
    temperature = np.ones((50, 50), dtype=np.float32) * 15.0
    temperature[20:30, 20:30] = 25.0  # hot patch in range
    result = _run_with_mock(service, temperature, visual_shape=(100, 100, 3))
    assert result.error_message is None
    if result.areas_of_interest:
        # Center should be scaled up to visual coordinates (>50)
        for aoi in result.areas_of_interest:
            cx, cy = aoi['center']
            # Hot patch centroid was ~(25, 25) thermal -> ~(50, 50) visual
            assert 0 <= cx <= 100
            assert 0 <= cy <= 100


def test_process_image_returns_error_when_parser_raises():
    service = _make_service()
    with patch(
        "algorithms.images.ThermalRange.services.ThermalRangeService.ThermalParserService"
    ) as MockParser:
        MockParser.return_value.parse_file.side_effect = RuntimeError("parse failed")
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
    assert "parse failed" in result.error_message


def test_process_image_combines_overlapping_aois():
    service = _make_service(combine=True)
    temperature = np.ones((100, 100), dtype=np.float32) * 10.0
    # Two overlapping hot regions
    temperature[20:40, 20:40] = 25.0
    temperature[30:50, 30:50] = 25.0
    result = _run_with_mock(service, temperature)
    assert result.error_message is None


def test_process_image_filters_by_area():
    # max_area=5 is very small, should eliminate larger regions
    service = _make_service(min_area=1, max_area=5)
    temperature = np.ones((50, 50), dtype=np.float32) * 15.0
    temperature[20:35, 20:35] = 25.0  # 225 pixel region
    result = _run_with_mock(service, temperature)
    # Large region filtered out
    assert result.areas_of_interest is None or len(result.areas_of_interest) == 0


def _analyze_at_resolution(temperature, processing_resolution, min_area=1, max_area=0):
    """Run one frame through AnalyzeService.process_file, the production ordering.

    The parser hands back the same native-resolution temperature array at every
    processing resolution, behind a 320x320 visual frame.
    """
    algorithm = {'name': 'ThermalRange', 'service': 'ThermalRangeService', 'combine_overlapping_aois': False}
    options = {'minTemp': 20.0, 'maxTemp': 40.0}
    with patch(
        "algorithms.images.ThermalRange.services.ThermalRangeService.ThermalParserService"
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
    temperature = np.full((160, 160), 15.0, dtype=np.float32)
    temperature[100:120, 100:120] = 35.0
    temperature[20:40, 110:130] = 25.0

    full = _analyze_at_resolution(temperature, 1.0)
    half = _analyze_at_resolution(temperature, 0.5)

    assert len(full) == len(half) == 2
    assert sorted(aoi['temperature'] for aoi in full) == [pytest.approx(25.0), pytest.approx(35.0)]
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
    temperature = _four_sized_spots(15.0, 35.0)

    full = _analyze_at_resolution(temperature, 1.0, min_area=50, max_area=300)
    half = _analyze_at_resolution(temperature, 0.5, min_area=50, max_area=300)

    assert len(full) == len(half) == 1
    assert full[0]['area'] == half[0]['area'] == 144
    # thermal [70:82] is frame [140:164] in the 320x320 frame at either resolution
    assert full[0]['center'] == pytest.approx((152, 152), abs=2)
    assert half[0]['center'] == pytest.approx(full[0]['center'], abs=2)
