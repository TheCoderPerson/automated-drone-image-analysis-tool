"""Tests for GroundMessageService (the ADIAT AlgorithmService adapter)."""

import os
import tempfile

import cv2
import numpy as np
import pytest

from algorithms.AlgorithmService import AnalysisResult
from algorithms.images.GroundMessage.services.GroundMessageService import (
    DEFAULT_CONFIDENCE, DEFAULT_MAX_CHAR_SIZE, DEFAULT_MIN_CHAR_SIZE, OPTION_CONFIDENCE, OPTION_MAX_CHAR_SIZE,
    OPTION_MIN_CHAR_SIZE, OPTION_POLARITY, OPTION_SINGLE_CHARACTERS, POLARITY_BOTH, POLARITY_DARK, SCORE_TYPE,
    GroundMessageService, coerce_options, normalize_options)
from core.services.AnalyzeService import AnalyzeService
from tests.algorithms.images.GroundMessage.conftest import boxes_overlap


def make_service(options=None, combine_aois=True, min_area=10, max_area=0):
    return GroundMessageService(identifier=(255, 0, 0), min_area=min_area, max_area=max_area, aoi_radius=10,
                                combine_aois=combine_aois, options=options or {})


def run(service, img):
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = os.path.join(tmpdir, 'output')
        os.makedirs(output_dir)
        full_path = os.path.join(tmpdir, 'frame.jpg')
        cv2.imwrite(full_path, img)
        result = service.process_image(img, full_path, tmpdir, output_dir)
        mask_exists = bool(result.output_path) and os.path.exists(os.path.join(output_dir, result.output_path))
    return result, mask_exists


def test_defaults_when_options_are_empty():
    service = make_service({})
    assert service.name == 'GroundMessage'
    assert service.confidence_threshold == DEFAULT_CONFIDENCE
    assert service.min_char_size == DEFAULT_MIN_CHAR_SIZE
    assert service.max_char_size == DEFAULT_MAX_CHAR_SIZE
    assert service.stroke_polarity == POLARITY_BOTH
    assert service.detect_single_characters is True


def test_options_saved_as_xml_strings_still_load():
    """ADIAT_Data.xml stores every option value as text."""
    service = make_service({
        OPTION_CONFIDENCE: '65.0', OPTION_MIN_CHAR_SIZE: '50', OPTION_MAX_CHAR_SIZE: '400',
        OPTION_POLARITY: 'Dark', OPTION_SINGLE_CHARACTERS: 'False',
    })
    assert service.confidence_threshold == 65.0
    assert (service.min_char_size, service.max_char_size) == (50, 400)
    assert service.stroke_polarity == POLARITY_DARK
    assert service.detect_single_characters is False


@pytest.mark.parametrize('options', [
    {OPTION_MIN_CHAR_SIZE: 500, OPTION_MAX_CHAR_SIZE: 100},
    {OPTION_CONFIDENCE: 150},
    {OPTION_POLARITY: 'sideways'},
    {OPTION_MIN_CHAR_SIZE: 'abc'},
])
def test_invalid_options_fail_clearly(options):
    with pytest.raises(ValueError):
        make_service(options)


def test_coerce_options_falls_back_to_defaults_without_raising():
    values = coerce_options({OPTION_CONFIDENCE: 'abc', OPTION_POLARITY: 'sideways', OPTION_SINGLE_CHARACTERS: None})
    assert values[OPTION_CONFIDENCE] == DEFAULT_CONFIDENCE
    assert values[OPTION_POLARITY] == POLARITY_BOTH
    assert values[OPTION_SINGLE_CHARACTERS] is True
    assert coerce_options(None)[OPTION_MIN_CHAR_SIZE] == DEFAULT_MIN_CHAR_SIZE


def test_normalize_options_fills_every_key():
    assert set(normalize_options({})) == {
        OPTION_CONFIDENCE, OPTION_MIN_CHAR_SIZE, OPTION_MAX_CHAR_SIZE, OPTION_POLARITY, OPTION_SINGLE_CHARACTERS}


def test_process_image_reports_message_with_confidence(help_scene):
    img, boxes = help_scene
    result, mask_exists = run(make_service(), img)
    assert isinstance(result, AnalysisResult)
    assert result.error_message is None
    assert result.areas_of_interest
    assert mask_exists
    word_box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    on_word = [a for a in result.areas_of_interest
               if boxes_overlap((a['center'][0] - a['radius'], a['center'][1] - a['radius'],
                                 a['center'][0] + a['radius'], a['center'][1] + a['radius']), word_box)]
    assert on_word
    for aoi in result.areas_of_interest:
        assert aoi['score_type'] == SCORE_TYPE
        assert 0 <= aoi['confidence'] <= 100
        assert aoi['raw_score'] == pytest.approx(aoi['confidence'] / 100, abs=0.01)
        assert aoi['detected_pixels']
    assert max(a['confidence'] for a in on_word) >= DEFAULT_CONFIDENCE


def test_combined_aois_merge_the_characters_of_a_word(help_scene):
    img, _ = help_scene
    combined, _ = run(make_service(combine_aois=True), img)
    separate, _ = run(make_service(combine_aois=False), img)
    assert len(separate.areas_of_interest) > len(combined.areas_of_interest)


def test_no_message_returns_empty_result(empty_scene):
    result, mask_exists = run(make_service(), empty_scene)
    assert result.error_message is None
    assert not result.areas_of_interest
    assert not mask_exists


def test_confidence_threshold_suppresses_weaker_detections(help_scene):
    img, _ = help_scene
    result, _ = run(make_service({OPTION_CONFIDENCE: 100}), img)
    assert result.error_message is None
    assert not result.areas_of_interest


def test_max_area_filters_individual_characters(help_scene):
    img, _ = help_scene
    result, _ = run(make_service(max_area=50), img)
    assert not result.areas_of_interest


def test_character_sizes_follow_processing_resolution():
    service = make_service({OPTION_MIN_CHAR_SIZE: 60, OPTION_MAX_CHAR_SIZE: 800})
    service.set_scale_factor(0.5)
    detector = service.build_detector()
    assert detector.min_char_size == pytest.approx(30)
    assert detector.max_char_size == pytest.approx(400)


def test_downscaled_processing_still_finds_the_message(help_scene):
    img, boxes = help_scene
    service = make_service()
    service.set_scale_factor(0.75)
    small = cv2.resize(img, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
    result, _ = run(service, small)
    assert result.areas_of_interest
    aois = service.transform_aois_to_original_resolution(result.areas_of_interest)
    centers = [a['center'] for a in aois]
    assert any(b[0] - 60 <= x <= b[2] + 60 and b[1] - 60 <= y <= b[3] + 60 for x, y in centers for b in boxes)


def test_greyscale_and_alpha_images_are_accepted(help_scene):
    img, _ = help_scene
    gray, _ = run(make_service(), cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    bgra, _ = run(make_service(), cv2.cvtColor(img, cv2.COLOR_BGR2BGRA))
    assert gray.error_message is None and gray.areas_of_interest
    assert bgra.error_message is None and bgra.areas_of_interest


def test_processing_error_names_the_file():
    service = make_service()
    result = service.process_image(np.zeros((0, 0, 3), np.uint8), '/data/flight/IMG_0001.JPG', '/data', '/out')
    assert result.error_message
    assert result.input_path == '/data/flight/IMG_0001.JPG'


def test_service_resolves_from_algorithm_config():
    cls = AnalyzeService._resolve_algorithm_service_class({'name': 'GroundMessage', 'service': 'GroundMessageService'})
    assert cls is GroundMessageService
