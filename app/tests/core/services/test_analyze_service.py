"""
Comprehensive tests for AnalyzeService.

Tests the core image analysis orchestration service.
"""

import pytest
import tempfile
import os
import numpy as np
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QObject
from core.services.AnalyzeService import AnalyzeService


@pytest.fixture
def analyze_service():
    """Fixture providing an AnalyzeService instance."""
    algorithm = {
        'name': 'ColorRange',
        'type': 'RGB',
        'service': 'ColorRangeService'
    }
    options = {
        'color_ranges': [
            {'color_range': [(100, 150, 200), (120, 170, 220)]}
        ]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, 'input')
        output_dir = os.path.join(tmpdir, 'output')
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        service = AnalyzeService(
            id=1,
            algorithm=algorithm,
            input=input_dir,
            output=output_dir,
            identifier_color=(100, 150, 200),
            min_area=10,
            num_processes=1,
            max_aois=100,
            aoi_radius=5,
            histogram_reference_path=None,
            kmeans_clusters=None,
            options=options,
            max_area=1000,
            processing_resolution=1.0
        )
        yield service


def test_analyze_service_initialization(analyze_service):
    """Test AnalyzeService initialization."""
    assert analyze_service.algorithm is not None
    assert analyze_service.min_area == 10
    assert analyze_service.max_area == 1000
    assert analyze_service.num_processes == 1
    assert analyze_service.processing_resolution == 1.0


def test_analyze_service_thermal_detection():
    """Test that thermal algorithms are properly detected."""
    algorithm = {
        'name': 'ThermalRange',
        'type': 'Thermal',
        'service': 'ThermalRangeService'
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, 'input')
        output_dir = os.path.join(tmpdir, 'output')
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        service = AnalyzeService(
            id=1,
            algorithm=algorithm,
            input=input_dir,
            output=output_dir,
            identifier_color=(255, 0, 0),
            min_area=10,
            num_processes=1,
            max_aois=100,
            aoi_radius=5,
            histogram_reference_path=None,
            kmeans_clusters=None,
            options={'minTemp': 20.0, 'maxTemp': 30.0},
            max_area=1000,
            processing_resolution=1.0
        )

        assert service.is_thermal is True


def test_analyze_service_processing_resolution():
    """Test processing resolution scaling."""
    algorithm = {
        'name': 'ColorRange',
        'type': 'RGB',
        'service': 'ColorRangeService'
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, 'input')
        output_dir = os.path.join(tmpdir, 'output')
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        service = AnalyzeService(
            id=1,
            algorithm=algorithm,
            input=input_dir,
            output=output_dir,
            identifier_color=(100, 150, 200),
            min_area=10,
            num_processes=1,
            max_aois=100,
            aoi_radius=5,
            histogram_reference_path=None,
            kmeans_clusters=None,
            options={},
            max_area=1000,
            processing_resolution=0.5  # 50% resolution
        )

        assert service.processing_resolution == 0.5


def test_analyze_service_signals(analyze_service):
    """Test that signals are properly defined."""
    assert hasattr(analyze_service, 'sig_msg')
    assert hasattr(analyze_service, 'sig_aois')
    assert hasattr(analyze_service, 'sig_done')


def test_analyze_service_cancellation(analyze_service):
    """Test cancellation functionality."""
    assert analyze_service.cancelled is False
    analyze_service.cancelled = True
    assert analyze_service.cancelled is True


@patch('core.services.AnalyzeService.cv2.imdecode')
@patch('core.services.AnalyzeService.np.fromfile')
def test_process_file_unknown_algorithm_service_returns_error(mock_fromfile, mock_imdecode):
    """Unknown algorithm services should return an explicit error result."""
    mock_fromfile.return_value = np.array([1], dtype=np.uint8)
    mock_imdecode.return_value = np.zeros((20, 20, 3), dtype=np.uint8)

    algorithm = {
        'name': 'ColorRange',
        'type': 'RGB',
        'service': 'MissingService',
        'combine_overlapping_aois': True
    }

    result = AnalyzeService.process_file(
        algorithm=algorithm,
        identifier_color=(100, 150, 200),
        min_area=10,
        max_area=1000,
        aoi_radius=5,
        options={},
        full_path='/tmp/fake.jpg',
        input_dir='/tmp/input',
        output_dir='/tmp/output',
        hist_ref_path=None,
        kmeans_clusters=None,
        thermal=False,
        processing_resolution=1.0
    )

    assert result is not None
    assert result.input_path == '/tmp/fake.jpg'
    assert result.error_message is not None
    assert 'Unknown algorithm service: MissingService' in result.error_message


# ---------------------------------------------------------------------------
# _resolve_algorithm_service_class
# ---------------------------------------------------------------------------

def test_resolve_algorithm_service_class_for_known_algorithm():
    algorithm = {"name": "MRMap", "service": "MRMapService"}
    cls = AnalyzeService._resolve_algorithm_service_class(algorithm)
    assert cls.__name__ == "MRMapService"


def test_resolve_algorithm_service_class_missing_fields():
    with pytest.raises(ValueError, match="missing required fields"):
        AnalyzeService._resolve_algorithm_service_class({"name": "X"})


def test_resolve_algorithm_service_class_unknown_service():
    with pytest.raises(ValueError, match="Unknown algorithm service"):
        AnalyzeService._resolve_algorithm_service_class(
            {"name": "MRMap", "service": "DoesNotExistService"}
        )


def test_resolve_algorithm_service_handles_legacy_typo():
    algorithm = {"name": "AIPersonDetetor", "service": "AIPersonDetectorService"}
    cls = AnalyzeService._resolve_algorithm_service_class(algorithm)
    assert cls.__name__ == "AIPersonDetectorService"


# ---------------------------------------------------------------------------
# process_cancel
# ---------------------------------------------------------------------------

def test_process_cancel_sets_flag_and_terminates_pool(analyze_service):
    analyze_service.pool = MagicMock()
    analyze_service.process_cancel()
    assert analyze_service.cancelled is True
    analyze_service.pool.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# _setup_output_dir
# ---------------------------------------------------------------------------

def test_setup_output_dir_creates(analyze_service, tmp_path):
    analyze_service.output = str(tmp_path / "ADIAT_Results")
    analyze_service._setup_output_dir()
    assert os.path.exists(analyze_service.output)


def test_setup_output_dir_clears_existing(analyze_service, tmp_path):
    out = tmp_path / "ADIAT_Results"
    out.mkdir()
    (out / "stale.txt").write_text("stale")
    analyze_service.output = str(out)
    analyze_service._setup_output_dir()
    assert os.path.exists(analyze_service.output)
    assert not (out / "stale.txt").exists()


# ---------------------------------------------------------------------------
# _process_complete
# ---------------------------------------------------------------------------

def test_process_complete_error_path_skips_counter(analyze_service):
    from algorithms.AlgorithmService import AnalysisResult
    analyze_service.ttl_images = 10
    analyze_service._completed_images = 0

    messages = []
    analyze_service.sig_msg.connect(lambda msg: messages.append(msg))

    result = AnalysisResult(input_path="/input/img.jpg", error_message="bad file")
    analyze_service._process_complete(result)

    assert any("Unable to process" in m for m in messages)
    assert analyze_service._completed_images == 0


def test_process_complete_counts_aois(analyze_service):
    from algorithms.AlgorithmService import AnalysisResult
    analyze_service.ttl_images = 10
    analyze_service._completed_images = 0
    analyze_service._total_aois = 0
    analyze_service.max_aois_limit_exceeded = False

    result = AnalysisResult(
        input_path="/input/img.jpg",
        output_path="/output/img.jpg",
        output_dir="/output",
        areas_of_interest=[{"id": 1}, {"id": 2}],
        base_contour_count=2,
    )
    result.image_width = 100
    result.image_height = 200
    analyze_service._process_complete(result)

    assert analyze_service._completed_images == 1
    assert analyze_service._total_aois == 2
    assert len(analyze_service.images_with_aois) == 1


def test_process_complete_triggers_max_aois_signal(analyze_service):
    from algorithms.AlgorithmService import AnalysisResult
    analyze_service.ttl_images = 10
    analyze_service._completed_images = 0
    analyze_service._total_aois = 0
    analyze_service.max_aois = 5
    analyze_service.max_aois_limit_exceeded = False

    triggered = []
    analyze_service.sig_aois.connect(lambda: triggered.append(True))

    result = AnalysisResult(
        input_path="/input/img.jpg",
        output_path="/output/img.jpg",
        output_dir="/output",
        areas_of_interest=[{"id": i} for i in range(10)],
        base_contour_count=10,
    )
    result.image_width = 100
    result.image_height = 200
    analyze_service._process_complete(result)

    assert triggered == [True]
    assert analyze_service.max_aois_limit_exceeded is True


def test_process_complete_zero_aois(analyze_service):
    from algorithms.AlgorithmService import AnalysisResult
    analyze_service.ttl_images = 10
    analyze_service._completed_images = 0
    analyze_service._total_aois = 0

    messages = []
    analyze_service.sig_msg.connect(lambda msg: messages.append(msg))

    result = AnalysisResult(
        input_path="/input/img.jpg",
        output_path="/output/img.jpg",
        output_dir="/output",
        areas_of_interest=None,
        base_contour_count=None,
    )
    analyze_service._process_complete(result)
    assert any("No areas of interest" in m for m in messages)
    assert analyze_service._completed_images == 1


# ---------------------------------------------------------------------------
# _generate_main_image_thumbnail
# ---------------------------------------------------------------------------

def test_generate_thumbnail_creates_file(tmp_path):
    img = np.random.randint(0, 255, (200, 400, 3), dtype=np.uint8)
    AnalyzeService._generate_main_image_thumbnail(
        img, image_path="/input/test.jpg", output_dir=str(tmp_path), input_root="/input"
    )
    thumbs = list((tmp_path / ".thumbnails").iterdir())
    assert len(thumbs) == 1
    assert thumbs[0].suffix == ".jpg"


def test_generate_thumbnail_handles_grayscale(tmp_path):
    img = np.random.randint(0, 255, (200, 300), dtype=np.uint8)
    AnalyzeService._generate_main_image_thumbnail(
        img, image_path="/input/test.jpg", output_dir=str(tmp_path)
    )


def test_generate_thumbnail_handles_rgba(tmp_path):
    img = np.random.randint(0, 255, (100, 100, 4), dtype=np.uint8)
    AnalyzeService._generate_main_image_thumbnail(
        img, image_path="/input/test.png", output_dir=str(tmp_path)
    )


def test_generate_thumbnail_handles_tall_image(tmp_path):
    img = np.zeros((400, 100, 3), dtype=np.uint8)
    AnalyzeService._generate_main_image_thumbnail(
        img, image_path="/input/test.jpg", output_dir=str(tmp_path)
    )


def test_generate_thumbnail_swallows_exceptions():
    # None image + invalid output dir → should silently return
    AnalyzeService._generate_main_image_thumbnail(
        None, image_path="/input/test.jpg", output_dir="/no/such/path"
    )


# ---------------------------------------------------------------------------
# assign_aoi_numbers
# ---------------------------------------------------------------------------

def test_assign_aoi_numbers_sequential_across_images():
    """AOI numbers run 1..N across images in order, then within each image."""
    images_with_aois = [
        {"path": "a.jpg", "aois": [{"center": (1, 1)}, {"center": (2, 2)}]},
        {"path": "b.jpg", "aois": [{"center": (3, 3)}]},
        {"path": "c.jpg", "aois": [{"center": (4, 4)}, {"center": (5, 5)}]},
    ]
    AnalyzeService.assign_aoi_numbers(images_with_aois)

    numbers = [aoi["number"] for img in images_with_aois for aoi in img["aois"]]
    assert numbers == [1, 2, 3, 4, 5]


def test_assign_aoi_numbers_handles_empty_and_missing_aois():
    """assign_aoi_numbers tolerates empty input and images with no AOIs."""
    AnalyzeService.assign_aoi_numbers([])
    AnalyzeService.assign_aoi_numbers(None)

    images_with_aois = [
        {"path": "a.jpg", "aois": []},
        {"path": "b.jpg", "aois": [{"center": (1, 1)}]},
    ]
    AnalyzeService.assign_aoi_numbers(images_with_aois)
    assert images_with_aois[1]["aois"][0]["number"] == 1
