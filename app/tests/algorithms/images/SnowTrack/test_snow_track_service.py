"""Tests for SnowTrackService: gait-cadence detection of foot tracks in snow."""

import json
import os
import tempfile
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from algorithms.AlgorithmService import AnalysisResult
from algorithms.images.SnowTrack.services import SnowTrackService as snow_track_module
from algorithms.images.SnowTrack.services.SnowTrackOptions import (
    DEFAULT_OPTIONS,
    OPTION_LIMITS,
    TRACK_PRESETS,
    SnowTrackParams,
)
from algorithms.images.SnowTrack.services.SnowTrackService import (
    SEGMENT_MAX_PRINTS,
    PixelScales,
    SnowTrackService,
    snr_threshold_for_sensitivity,
)
from core.services.AnalyzeService import AnalyzeService

from .snow_scenes import SnowScene, matched_fraction

GSDS = (6.0, 9.0, 12.0)


def _service(min_area=1, max_area=0, aoi_radius=0, combine_aois=False, **options):
    merged = {'gsd_mode': 'manual'}
    merged.update(options)
    return SnowTrackService((255, 0, 0), min_area, max_area, aoi_radius, combine_aois, merged)


def _walk(scene, **kwargs):
    params = dict(start_cm=(0.15 * scene.width_cm, 0.3 * scene.height_cm), heading_deg=25, prints=40)
    params.update(kwargs)
    return scene.add_walk(**params)


def _in_frame(scene, points_px, margin=3):
    keep = ((points_px[:, 0] > margin) & (points_px[:, 0] < scene.width_px - margin)
            & (points_px[:, 1] > margin) & (points_px[:, 1] < scene.height_px - margin))
    return points_px[keep]


# --------------------------------------------------------------- options


def test_defaults_when_options_are_missing():
    params = SnowTrackParams.from_options({})

    assert params.gsd_mode == DEFAULT_OPTIONS['gsd_mode']
    assert params.gsd_cm == DEFAULT_OPTIONS['gsd_cm']
    assert params.print_diameter_cm == DEFAULT_OPTIONS['print_diameter_cm']
    assert params.step_min_cm == DEFAULT_OPTIONS['step_min_cm']
    assert params.step_max_cm == DEFAULT_OPTIONS['step_max_cm']
    assert params.min_prints == DEFAULT_OPTIONS['min_prints']
    assert params.max_step_variation == pytest.approx(DEFAULT_OPTIONS['max_step_variation'] / 100.0)
    assert params.sensitivity == DEFAULT_OPTIONS['sensitivity']


@pytest.mark.parametrize('options', [None, 'not a dict', 42])
def test_non_dict_options_fall_back_to_defaults(options):
    service = SnowTrackService((255, 0, 0), 1, 0, 0, False, options)

    assert service.params == SnowTrackParams.from_options({})


def test_malformed_and_out_of_range_values_are_repaired():
    params = SnowTrackParams.from_options({
        'gsd_mode': 'telepathy',
        'gsd_cm': 'abc',
        'print_diameter_cm': 1e9,
        'step_min_cm': float('nan'),
        'min_prints': '7.0',
        'sensitivity': -3,
    })

    assert params.gsd_mode == DEFAULT_OPTIONS['gsd_mode']
    assert params.gsd_cm == DEFAULT_OPTIONS['gsd_cm']
    assert params.print_diameter_cm == OPTION_LIMITS['print_diameter_cm'][1]
    assert params.step_min_cm == DEFAULT_OPTIONS['step_min_cm']
    assert params.min_prints == 7
    assert params.sensitivity == OPTION_LIMITS['sensitivity'][0]


def test_inverted_step_range_is_reordered():
    params = SnowTrackParams.from_options({'step_min_cm': 90, 'step_max_cm': 40})

    assert (params.step_min_cm, params.step_max_cm) == (40.0, 90.0)


def test_presets_are_complete_and_physically_ordered():
    for preset in TRACK_PRESETS.values():
        params = SnowTrackParams.from_options(preset)
        assert params.step_min_cm < params.step_max_cm
        # Prints narrower than the shortest step, or consecutive prints would merge
        assert params.print_diameter_cm < params.step_min_cm


def test_sensitivity_lowers_the_contrast_threshold():
    thresholds = [snr_threshold_for_sensitivity(s) for s in range(1, 11)]

    assert thresholds == sorted(thresholds, reverse=True)
    assert len(set(thresholds)) == len(thresholds)
    assert thresholds[-1] > 2.0, "a threshold near the noise floor floods the linker with noise"


def test_pixel_scales_follow_gsd():
    params = SnowTrackParams.from_options({'print_diameter_cm': 30, 'step_min_cm': 40, 'step_max_cm': 100})

    fine = PixelScales.build(params, 6.0)
    coarse = PixelScales.build(params, 12.0)

    assert fine.step_min == pytest.approx(40 / 6.0)
    assert coarse.step_max == pytest.approx(100 / 12.0)
    assert fine.print_radius == pytest.approx(2 * coarse.print_radius)


# ------------------------------------------------------------------- GSD


def test_manual_gsd_is_used_as_given():
    service = _service(gsd_mode='manual', gsd_cm=7.5)

    with patch.object(snow_track_module, 'ImageService') as image_service:
        gsd, source = service.resolve_gsd('frame.jpg')

    image_service.assert_not_called()
    assert (gsd, source) == (7.5, 'manual')


def test_manual_gsd_accounts_for_processing_resolution():
    service = _service(gsd_mode='manual', gsd_cm=6.0)
    service.set_scale_factor(0.5)

    gsd, _ = service.resolve_gsd('frame.jpg')

    assert gsd == pytest.approx(12.0)


def _metadata(gsd, exif_width=4000):
    fake = patch.object(snow_track_module, 'ImageService').start()
    fake.return_value.get_average_gsd.return_value = gsd
    fake.return_value.exif_data = {'Exif': {0xA002: exif_width}}
    return fake


def test_auto_gsd_reads_metadata():
    service = _service(gsd_mode='auto', gsd_cm=8.0)
    try:
        _metadata(9.3)
        gsd, source = service.resolve_gsd('frame.jpg', original_width=4000)
    finally:
        patch.stopall()

    assert (gsd, source) == (pytest.approx(9.3), 'metadata')


def test_auto_gsd_corrects_for_resized_images_with_stale_exif():
    service = _service(gsd_mode='auto')
    try:
        _metadata(6.0, exif_width=8000)
        gsd, _ = service.resolve_gsd('frame.jpg', original_width=4000)
    finally:
        patch.stopall()

    assert gsd == pytest.approx(12.0)


@pytest.mark.parametrize('metadata_gsd', [None, 0.0, 500.0, float('nan'), 'n/a'])
def test_auto_gsd_falls_back_to_fixed_value(metadata_gsd):
    service = _service(gsd_mode='auto', gsd_cm=8.0)
    try:
        _metadata(metadata_gsd)
        gsd, source = service.resolve_gsd('frame.jpg', original_width=4000)
    finally:
        patch.stopall()

    assert (gsd, source) == (8.0, 'manual')


def test_auto_gsd_falls_back_when_metadata_cannot_be_read():
    service = _service(gsd_mode='auto', gsd_cm=8.0)

    with patch.object(snow_track_module, 'ImageService', side_effect=OSError("no such file")):
        gsd, source = service.resolve_gsd('missing.jpg')

    assert (gsd, source) == (8.0, 'manual')


# ------------------------------------------------------------- detection


@pytest.mark.parametrize('gsd', GSDS)
def test_walking_trail_is_detected_across_the_gsd_range(gsd):
    scene = SnowScene(gsd_cm=gsd, seed=1)
    expected = _in_frame(scene, scene.to_px(_walk(scene, step_cm=65, straddle_cm=22)))

    tracks = _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd)

    assert tracks, "no trail found"
    assert max(matched_fraction(t.prints, expected, 2.0) for t in tracks) >= 0.6
    for track in tracks:
        # Every reported print belongs to the trail
        assert matched_fraction(expected, track.prints, 2.0) == 1.0


def test_trail_statistics_are_reported_in_ground_units():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=2)
    _walk(scene, step_cm=65, straddle_cm=22)

    longest = max(_service(gsd_cm=gsd).detect_tracks(scene.render(), gsd), key=lambda t: len(t.prints))

    assert longest.mean_step_px * gsd == pytest.approx(65, rel=0.15)
    assert longest.trail_width_px * gsd < DEFAULT_OPTIONS['max_trail_width_cm']
    assert 0.0 < longest.confidence <= 100.0


def test_curving_trail_is_followed():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=3)
    expected = _in_frame(scene, scene.to_px(_walk(scene, turn_deg_per_step=4)))

    tracks = _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd)

    assert max(matched_fraction(t.prints, expected, 2.0) for t in tracks) >= 0.6


def test_missed_prints_are_bridged():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=4)
    centers = _walk(scene, prints=30)
    # Drift snow over two separate single prints and one pair of consecutive prints
    for gone in sorted((8, 15, 16), reverse=True):
        del scene.prints[gone]
    kept = np.delete(centers, [8, 15, 16], axis=0)

    tracks = _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd)

    longest = max(tracks, key=lambda t: len(t.prints))
    assert matched_fraction(longest.prints, _in_frame(scene, scene.to_px(kept)), 2.0) >= 0.8
    assert int((~longest.detected).sum()) >= 3


def test_two_walkers_side_by_side_are_both_found():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=5)
    first = _in_frame(scene, scene.to_px(_walk(scene)))
    second = _in_frame(scene, scene.to_px(scene.add_walk(
        (0.15 * scene.width_cm - 30, 0.3 * scene.height_cm + 110), 25, 40)))

    tracks = _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd)

    for trail in (first, second):
        assert max(matched_fraction(t.prints, trail, 2.0) for t in tracks) >= 0.6


def test_trail_is_found_among_scattered_clutter():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=6)
    scene.add_clutter(0.2)
    expected = _in_frame(scene, scene.to_px(_walk(scene)))

    tracks = _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd)

    assert max(matched_fraction(t.prints, expected, 2.0) for t in tracks) >= 0.6
    for track in tracks:
        assert matched_fraction(expected, track.prints, 2.0) >= 0.8


@pytest.mark.parametrize('seed', range(4))
@pytest.mark.parametrize('gsd', GSDS)
def test_scattered_clutter_alone_is_not_a_trail(gsd, seed):
    scene = SnowScene(gsd_cm=gsd, seed=100 + seed)
    scene.add_clutter(0.2)

    assert _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd) == []


@pytest.mark.parametrize('gsd', GSDS)
def test_continuous_furrows_are_not_trails(gsd):
    """Ski tracks, a posthole trench and a snowmobile band have no gaps between 'prints'."""
    scene = SnowScene(gsd_cm=gsd, seed=7)
    w, h = scene.width_cm, scene.height_cm
    for offset in (0, 20):
        scene.add_groove((0.1 * w, 0.15 * h + offset), (0.9 * w, 0.45 * h + offset), 10, 25)
    scene.add_groove((0.1 * w, 0.6 * h), (0.9 * w, 0.7 * h), 35, 32)
    scene.add_groove((0.1 * w, 0.9 * h), (0.9 * w, 0.8 * h), 90, 20)

    assert _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd) == []


@pytest.mark.parametrize('step_cm, prints, diameter_cm', [
    (20.0, 80, 12.0),   # small animal: far shorter than a human step
    (150.0, 20, 30.0),  # bounding animal: far longer
])
def test_spacing_outside_the_human_range_is_not_a_trail(step_cm, prints, diameter_cm):
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=8)
    _walk(scene, step_cm=step_cm, prints=prints, print_diameter_cm=diameter_cm, straddle_cm=10)

    assert _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd) == []


def test_trees_and_rocks_are_not_trails():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=9)
    for _ in range(25):
        scene.add_dark_object((scene.rng.uniform(0, scene.width_cm), scene.rng.uniform(0, scene.height_cm)),
                              scene.rng.uniform(80, 250))
    for i in range(12):
        for j in range(12):
            scene.add_dark_object((200 + i * 300, 200 + j * 300), 60)

    assert _service(gsd_cm=gsd).detect_tracks(scene.render(), gsd) == []


def test_snow_free_image_is_skipped():
    rng = np.random.default_rng(0)
    forest = np.clip(rng.normal((45, 80, 50), 12, (400, 400, 3)), 0, 255).astype(np.uint8)

    assert _service().detect_tracks(forest, 9.0) == []


def test_tiled_detection_matches_a_single_pass():
    """Tiles overlap by the full filter support, so tiling must not change the candidates."""
    gsd = 6.0
    scene = SnowScene(width_px=420, height_px=360, gsd_cm=gsd, seed=10)
    scene.add_clutter(0.3)
    _walk(scene)
    img = scene.render()
    service = _service(gsd_cm=gsd)
    scales = PixelScales.build(service.params, gsd)
    val_threshold, _ = service._snow_survey(img)

    with patch.object(snow_track_module, 'TILE_SIZE', 10_000):
        whole = service._detect_candidates(img, val_threshold, scales)
    with patch.object(snow_track_module, 'TILE_SIZE', 97):
        tiled = service._detect_candidates(img, val_threshold, scales)

    assert sorted(map(tuple, whole.points)) == sorted(map(tuple, tiled.points))
    np.testing.assert_allclose(np.sort(whole.snr), np.sort(tiled.snr), atol=1e-4)
    np.testing.assert_allclose(whole.smoothed, tiled.smoothed, atol=1e-3)


@pytest.mark.parametrize('convert', [
    lambda img: cv2.cvtColor(img, cv2.COLOR_BGR2BGRA),
    lambda img: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
    lambda img: img.astype(np.uint16) * 257,
], ids=['bgra', 'gray', 'uint16'])
def test_other_image_layouts_are_accepted(convert):
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=11)
    expected = _in_frame(scene, scene.to_px(_walk(scene)))

    tracks = _service(gsd_cm=gsd).detect_tracks(convert(scene.render()), gsd)

    assert max((matched_fraction(t.prints, expected, 2.0) for t in tracks), default=0.0) >= 0.6


# --------------------------------------------------------- process_image


@pytest.fixture
def trail_frame():
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=12)
    expected = _in_frame(scene, scene.to_px(_walk(scene, prints=40)))
    return scene.render(), expected, gsd


def _process(service, img):
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = os.path.join(tmpdir, 'out')
        result = service.process_image(img, os.path.join(tmpdir, 'frame.jpg'), tmpdir, output_dir)
        mask_exists = bool(result.output_path) and os.path.exists(os.path.join(output_dir, result.output_path))
    return result, mask_exists


def test_process_image_reports_track_segments_as_aois(trail_frame):
    img, expected, gsd = trail_frame

    result, mask_exists = _process(_service(gsd_cm=gsd), img)

    assert isinstance(result, AnalysisResult)
    assert result.error_message is None
    assert mask_exists
    assert result.areas_of_interest
    assert result.base_contour_count == len(result.areas_of_interest)
    for aoi in result.areas_of_interest:
        assert {'center', 'radius', 'area', 'contour', 'detected_pixels'} <= set(aoi)
        assert aoi['area'] == len(aoi['detected_pixels'])
        assert aoi['score_type'] == 'track_cadence'
        assert aoi['score_method'] == 'mean_step_cm'
        assert aoi['raw_score'] == aoi['track']['mean_step_cm']
        assert 0.0 < aoi['confidence'] <= 100.0
        assert aoi['track']['segment_prints'] <= SEGMENT_MAX_PRINTS
        assert aoi['track']['gsd_source'] == 'manual'
        # The AOI circle frames the prints it reports
        cx, cy = aoi['center']
        pixels = np.asarray(aoi['detected_pixels'])
        assert np.hypot(pixels[:, 0] - cx, pixels[:, 1] - cy).max() <= aoi['radius'] + 1
    # Segments of one long trail each carry the whole trail's statistics
    assert len({aoi['track']['prints'] for aoi in result.areas_of_interest}) < len(result.areas_of_interest)


def test_combine_aois_reports_each_trail_whole(trail_frame):
    img, _, gsd = trail_frame

    split, _ = _process(_service(gsd_cm=gsd), img)
    whole, _ = _process(_service(gsd_cm=gsd, combine_aois=True), img)

    assert len(whole.areas_of_interest) < len(split.areas_of_interest)
    for aoi in whole.areas_of_interest:
        assert aoi['track']['segment_prints'] == aoi['track']['prints']


def test_area_limits_filter_segments(trail_frame):
    img, _, gsd = trail_frame
    baseline, _ = _process(_service(gsd_cm=gsd), img)
    smallest = min(aoi['area'] for aoi in baseline.areas_of_interest)
    largest = max(aoi['area'] for aoi in baseline.areas_of_interest)

    above_min, _ = _process(_service(gsd_cm=gsd, min_area=largest + 1), img)
    below_max, _ = _process(_service(gsd_cm=gsd, max_area=smallest - 1), img)

    assert above_min.areas_of_interest is None
    assert below_max.areas_of_interest is None


def test_aoi_radius_pads_the_circle(trail_frame):
    img, _, gsd = trail_frame

    plain, _ = _process(_service(gsd_cm=gsd), img)
    padded, _ = _process(_service(gsd_cm=gsd, aoi_radius=7), img)

    assert [a['radius'] + 7 for a in plain.areas_of_interest] == [a['radius'] for a in padded.areas_of_interest]


def test_process_image_without_tracks_returns_no_aois():
    scene = SnowScene(gsd_cm=9.0, seed=13)

    result, mask_exists = _process(_service(gsd_cm=9.0), scene.render())

    assert result.error_message is None
    assert result.areas_of_interest is None
    assert not mask_exists


def test_process_image_reports_errors_with_context():
    result, _ = _process(_service(), np.zeros((0, 0, 3), dtype=np.uint8))

    assert result.areas_of_interest is None
    assert 'SnowTrack' in result.error_message


def test_downscaled_processing_uses_the_coarser_gsd():
    """At 50% processing resolution a 6 cm/px frame is analyzed at 12 cm/px."""
    scene = SnowScene(width_px=800, height_px=800, gsd_cm=6.0, seed=14)
    expected = scene.to_px(_walk(scene, prints=50)) * 0.5
    half = cv2.resize(scene.render(), (400, 400), interpolation=cv2.INTER_AREA)
    service = _service(gsd_cm=6.0)
    service.set_scale_factor(0.5)

    result, _ = _process(service, half)

    assert result.areas_of_interest
    prints = np.vstack([np.asarray(a['detected_pixels']) for a in result.areas_of_interest])
    assert matched_fraction(prints, expected[(expected > 3).all(axis=1) & (expected < 397).all(axis=1)], 2.0) >= 0.6
    assert result.areas_of_interest[0]['track']['gsd_cm'] == pytest.approx(6.0)


# ----------------------------------------------------------- registration


def _config_entry():
    conf_path = os.path.join(os.path.dirname(snow_track_module.__file__), '..', '..', '..', '..', 'algorithms.conf')
    with open(conf_path, encoding='utf-8') as handle:
        algorithms = json.load(handle)['algorithms']
    return next(a for a in algorithms if a['name'] == 'SnowTrack')


def test_algorithm_is_registered_with_complete_metadata():
    entry = _config_entry()

    for key in ('name', 'label', 'controller', 'wizard_controller', 'service', 'type', 'platforms'):
        assert entry[key], key
    assert entry['type'] == 'RGB'
    assert entry['combine_overlapping_aois'] is False
    assert AnalyzeService._resolve_algorithm_service_class(entry) is SnowTrackService


def test_analyze_service_runs_the_algorithm_end_to_end():
    """The worker path: decode from disk, resolve the service, transform and cache AOIs."""
    gsd = 9.0
    scene = SnowScene(gsd_cm=gsd, seed=15)
    _walk(scene)
    entry = _config_entry()
    options = dict(DEFAULT_OPTIONS, gsd_mode='auto', gsd_cm=gsd)

    with tempfile.TemporaryDirectory() as tmpdir:
        image_path = os.path.join(tmpdir, 'frame.jpg')
        assert cv2.imwrite(image_path, scene.render())
        output_dir = os.path.join(tmpdir, 'ADIAT_Results')
        # The bare JPEG carries no altitude/camera metadata: auto mode must fall back
        result = AnalyzeService.process_file(entry, (255, 0, 0), 1, 0, 0, options, image_path,
                                             tmpdir, output_dir, None, None, False, 1.0)

        assert result.error_message is None
        assert result.areas_of_interest
        assert result.image_width == scene.width_px
        assert result.areas_of_interest[0]['track']['gsd_source'] == 'manual'
        assert os.path.isdir(os.path.join(output_dir, '.thumbnails'))
