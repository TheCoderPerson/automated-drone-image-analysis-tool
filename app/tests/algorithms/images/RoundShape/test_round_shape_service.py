"""End-to-end tests for RoundShapeService.process_image on synthetic frames.

Frames are built with numpy/cv2 from a fixed seed: a filled circle, oval or
ring, or part of one, of known physical size on Gaussian or fractal-noise
ground. GSD is supplied by stubbing the service's lookup, so at 1 cm/px a
70 cm life ring is a 70 px circle.
"""

import math
import os
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from algorithms.AlgorithmService import AnalysisResult
from algorithms.images.RoundShape.services.RoundPresets import DEFAULT_OPTIONS, normalize_options
from algorithms.images.RoundShape.services.RoundShapeService import RoundShapeService
from core.services.XmlService import XmlService

FRAME = 300
CENTRE = FRAME / 2

# A 60 x 40 cm oval target, as the custom size an operator would enter.
OVAL = {
    'target_preset': 'custom',
    'long_diameter_cm_min': 50.0, 'long_diameter_cm_max': 80.0,
    'short_diameter_cm_min': 30.0, 'short_diameter_cm_max': 55.0,
}


def _gaussian_ground(rng, size=FRAME, sigma=8.0):
    return rng.normal(110, sigma, (size, size)).astype(np.float32)


def _fractal_ground(rng, size=FRAME, amplitude=12.0):
    """Octave-summed noise: large soft blotches like mixed vegetation."""
    ground = np.zeros((size, size), np.float32)
    for octave in range(1, 7):
        cells = 2 ** octave
        layer = rng.normal(0, 1, (cells, cells)).astype(np.float32)
        ground += cv2.resize(layer, (size, size), interpolation=cv2.INTER_CUBIC) * amplitude / octave
    return ground + 110 + rng.normal(0, 3, (size, size)).astype(np.float32)


def _blend(ground, mask, value):
    """Blend ``value`` into ``ground`` through a slightly blurred mask."""
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.8)
    return ground * (1.0 - alpha) + value * alpha


def _ellipse_mask(shape, cx, cy, major, minor, angle, start=0, end=360, thickness=-1):
    mask = np.zeros(shape, np.uint8)
    cv2.ellipse(mask, (int(round(cx * 8)), int(round(cy * 8))), (int(round(major * 4)), int(round(minor * 4))),
                angle, start, end, 255, thickness, cv2.LINE_8, 3)
    return mask


def _with_ellipse(ground, cx, cy, major, minor, angle, value):
    return _blend(ground, _ellipse_mask(ground.shape, cx, cy, major, minor, angle), value)


def _with_ring(ground, cx, cy, outer, inner, value):
    """A tire or life ring: the ground shows through the middle."""
    ringed = _with_ellipse(ground, cx, cy, outer, outer, 0, value)
    alpha = cv2.GaussianBlur(_ellipse_mask(ground.shape, cx, cy, inner, inner, 0).astype(np.float32) / 255.0, (0, 0), 0.8)
    return ringed * (1.0 - alpha) + ground * alpha


def _partly_hidden(ground, cx, cy, diameter, visible_deg, start_deg, value):
    """A disk with all but ``visible_deg`` of its outline under ground-coloured cover."""
    disk = _with_ellipse(ground, cx, cy, diameter, diameter, 0, value)
    cover = np.zeros(ground.shape, np.uint8)
    cv2.ellipse(cover, (int(cx), int(cy)), (int(diameter), int(diameter)), 0,
                start_deg, start_deg + 360 - visible_deg, 255, -1)
    alpha = cv2.GaussianBlur(cover.astype(np.float32) / 255.0, (0, 0), 0.8)
    return disk * (1.0 - alpha) + ground * alpha


def _with_rectangle(ground, cx, cy, length, width, angle, value):
    corners = cv2.boxPoints(((cx, cy), (length, width), angle))
    mask = np.zeros(ground.shape, np.uint8)
    cv2.fillPoly(mask, [np.rint(corners * 8).astype(np.int32)], 255, shift=3)
    return _blend(ground, mask, value)


def _bgr(gray):
    return cv2.cvtColor(np.clip(gray, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def _service(gsd_cm=1.0, min_area=10, max_area=0, **options):
    service = RoundShapeService((255, 0, 0), min_area, max_area, 0, False, options)
    service._resolve_gsd_cm = lambda img, path: (gsd_cm, None)
    return service


def _run(service, img, tmp_path):
    return service.process_image(img, str(tmp_path / 'frame.jpg'), str(tmp_path), str(tmp_path / 'out'))


def _hit(aois, cx, cy, radius):
    return any(math.hypot(a['center'][0] - cx, a['center'][1] - cy) <= radius for a in aois or [])


def _hits_only_at(aois, cx, cy, radius):
    return _hit(aois, cx, cy, radius) and all(
        math.hypot(a['center'][0] - cx, a['center'][1] - cy) <= radius for a in aois
    )


# --- positives ----------------------------------------------------------------

@pytest.mark.parametrize('ground, contrast, min_hits', [
    ('gaussian', 40, 35),
    ('gaussian', 20, 34),
    ('fractal', 40, 35),
    ('fractal', 25, 32),
])
def test_ovals_are_found_at_every_rotation(tmp_path, ground, contrast, min_hits):
    """A 60 x 40 cm oval at 0-175 degrees in 5 degree steps.

    A hit is an AOI centred within a quarter of the short diameter of the
    truth, with nothing emitted anywhere else. Low contrast on blotchy ground
    is genuinely ambiguous - the outline vanishes wherever a blotch matches
    it - so the cases assert a rate.
    """
    rng = np.random.default_rng(1)
    service = _service(**OVAL)
    hits = 0
    for angle in range(0, 180, 5):
        base = _gaussian_ground(rng) if ground == 'gaussian' else _fractal_ground(rng)
        img = _bgr(_with_ellipse(base, CENTRE, CENTRE, 60, 40, angle, 110 + contrast))
        result = _run(service, img, tmp_path)
        assert result.error_message is None
        hits += _hits_only_at(result.areas_of_interest, CENTRE, CENTRE, 0.25 * 40)
    assert hits >= min_hits


@pytest.mark.parametrize('ground, contrast', [('gaussian', 40), ('gaussian', -20), ('fractal', 25)])
def test_circles_are_found(tmp_path, ground, contrast):
    """A 70 cm life ring or tire, lighter or darker than the ground."""
    rng = np.random.default_rng(2)
    service = _service()
    hits = 0
    for _ in range(8):
        base = _gaussian_ground(rng) if ground == 'gaussian' else _fractal_ground(rng)
        result = _run(service, _bgr(_with_ellipse(base, CENTRE, CENTRE, 70, 70, 0, 110 + contrast)), tmp_path)
        hits += _hits_only_at(result.areas_of_interest, CENTRE, CENTRE, 0.25 * 70)
    assert hits >= 7


@pytest.mark.parametrize('make_ground', [_gaussian_ground, _fractal_ground], ids=['gaussian', 'fractal'])
def test_a_tire_is_one_aoi_at_its_outer_size(tmp_path, make_ground):
    """Dark rubber with the ground showing through: inner and outer edges, one object."""
    img = _bgr(_with_ring(make_ground(np.random.default_rng(3)), CENTRE, CENTRE, 70, 40, 50))
    result = _run(_service(), img, tmp_path)
    assert result.areas_of_interest and len(result.areas_of_interest) == 1
    aoi = result.areas_of_interest[0]
    assert math.hypot(aoi['center'][0] - CENTRE, aoi['center'][1] - CENTRE) < 4
    assert aoi['radius'] == pytest.approx(35, abs=4)


def test_aois_carry_a_shape_confidence(tmp_path):
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(4)), CENTRE, CENTRE, 70, 66, 25, 160))
    result = _run(_service(), img, tmp_path)
    assert isinstance(result, AnalysisResult)
    assert result.areas_of_interest
    for aoi in result.areas_of_interest:
        assert aoi['score_type'] == 'shape'
        assert isinstance(aoi['confidence'], float)
        assert 0.0 <= aoi['confidence'] <= 100.0
        assert isinstance(aoi['center'][0], int)
    assert result.output_path is not None


@pytest.mark.parametrize('major_cm, minor_cm, gsd, options', [
    (32, 28, 1.0, {'target_preset': 'hat_helmet', 'long_diameter_cm_min': 22, 'long_diameter_cm_max': 45,
                   'short_diameter_cm_min': 18, 'short_diameter_cm_max': 40}),
    (75, 75, 1.5, {}),
    (120, 115, 1.5, {'target_preset': 'umbrella', 'long_diameter_cm_min': 85, 'long_diameter_cm_max': 160,
                     'short_diameter_cm_min': 80, 'short_diameter_cm_max': 160}),
    (240, 200, 2.5, {'target_preset': 'dome_tent', 'long_diameter_cm_min': 180, 'long_diameter_cm_max': 300,
                     'short_diameter_cm_min': 140, 'short_diameter_cm_max': 260}),
])
def test_targets_are_found_across_presets_and_scales(tmp_path, major_cm, minor_cm, gsd, options):
    rng = np.random.default_rng(5)
    img = _bgr(_with_ellipse(_gaussian_ground(rng, 400), 200, 200, major_cm / gsd, minor_cm / gsd, 35, 150))
    result = _run(_service(gsd, **options), img, tmp_path)
    assert _hits_only_at(result.areas_of_interest, 200, 200, 0.25 * minor_cm / gsd)


@pytest.mark.parametrize('visible_deg', [180, 240])
def test_a_partly_hidden_target_is_found_as_an_arc(tmp_path, visible_deg):
    """A tire half under brush still shows an unbroken arc of its outline."""
    rng = np.random.default_rng(6)
    service = _service()
    hits = 0
    for k in range(12):
        img = _bgr(_partly_hidden(_gaussian_ground(rng), CENTRE, CENTRE, 70, visible_deg, 30 * k, 150))
        hits += _hit(_run(service, img, tmp_path).areas_of_interest, CENTRE, CENTRE, 0.25 * 70)
    assert hits >= 11


def test_arcs_can_be_switched_off(tmp_path):
    """Without arcs, a half-hidden target no longer qualifies; a whole one still does."""
    rng = np.random.default_rng(6)
    service = _service(detect_arcs=False)
    hidden_hits = 0
    for k in range(12):
        img = _bgr(_partly_hidden(_gaussian_ground(rng), CENTRE, CENTRE, 70, 180, 30 * k, 150))
        hidden_hits += _hit(_run(service, img, tmp_path).areas_of_interest, CENTRE, CENTRE, 0.25 * 70)
    assert hidden_hits <= 3
    whole = _bgr(_with_ellipse(_gaussian_ground(rng), CENTRE, CENTRE, 70, 70, 0, 150))
    assert _hit(_run(service, whole, tmp_path).areas_of_interest, CENTRE, CENTRE, 0.25 * 70)


def test_a_curved_stroke_is_found_as_an_arc(tmp_path):
    """A hose or rope laid in a curve, or a tire seen edge-on in grass."""
    rng = np.random.default_rng(7)
    service = _service()
    hits = 0
    for k in range(12):
        ground = _gaussian_ground(rng)
        stroke = _ellipse_mask(ground.shape, CENTRE, CENTRE, 70, 70, 0, 30 * k, 30 * k + 180, thickness=6)
        hits += _hit(_run(service, _bgr(_blend(ground, stroke, 160)), tmp_path).areas_of_interest,
                     CENTRE, CENTRE, 0.35 * 70)
    assert hits >= 11


def test_a_shape_larger_than_the_batch_max_area_is_still_emitted(tmp_path):
    """The preset governs size; the guide's batch area limits are diagnostic only."""
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(8)), CENTRE, CENTRE, 70, 70, 0, 160))
    service = _service(min_area=10, max_area=100)
    service.logger = MagicMock()
    result = _run(service, img, tmp_path)
    assert _hit(result.areas_of_interest, CENTRE, CENTRE, 10)
    assert any('batch area limits' in str(c) for c in service.logger.info.call_args_list)


# --- negatives ----------------------------------------------------------------

@pytest.mark.parametrize('major_cm, minor_cm, options', [
    (160, 160, {}),
    (25, 25, {}),
    (160, 100, OVAL),
], ids=['too_large', 'too_small', 'oversized_oval'])
def test_shapes_of_the_wrong_physical_size_are_ignored(tmp_path, major_cm, minor_cm, options):
    """Including the ends of an oversized oval, which on their own would fit a smaller circle."""
    rng = np.random.default_rng(9)
    for angle in (0, 40, 100):
        img = _bgr(_with_ellipse(_gaussian_ground(rng, 400), 200, 200, major_cm, minor_cm, angle, 150))
        assert not _run(_service(**options), img, tmp_path).areas_of_interest


def _trail(rng):
    ground = _gaussian_ground(rng)
    angle = math.radians(rng.uniform(0, 180))
    dx, dy = 400 * math.cos(angle), 400 * math.sin(angle)
    cv2.line(ground, (int(CENTRE - dx), int(CENTRE - dy)), (int(CENTRE + dx), int(CENTRE + dy)), 150, 8)
    return _bgr(cv2.GaussianBlur(ground, (0, 0), 0.8))


def _rectangles(rng):
    """Suitcases, coolers and a square box: straight sides the size of the target."""
    ground = _gaussian_ground(rng)
    sizes = ((60, 40), (70, 70), (90, 50), (55, 50))
    for (cx, cy), (length, width) in zip(((80, 80), (220, 80), (80, 220), (220, 220)), sizes):
        ground = _with_rectangle(ground, cx, cy, length, width, rng.uniform(0, 180), rng.uniform(140, 180))
    return _bgr(ground)


def _polygons(rng):
    """Triangles, squares and pentagons - closed and the right size, but not curved."""
    ground = _gaussian_ground(rng)
    for cx, cy in ((80, 80), (220, 80), (80, 220), (220, 220)):
        sides = int(rng.choice([3, 4, 5]))
        radius = rng.uniform(25, 40)
        angles = rng.uniform(0, 2 * np.pi) + np.arange(sides) * 2 * np.pi / sides
        points = np.stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)], 1).astype(np.int32)
        cv2.fillPoly(ground, [points], float(rng.uniform(140, 180)))
    return _bgr(cv2.GaussianBlur(ground, (0, 0), 0.8))


def _jpeg_blocking(rng):
    yy, xx = np.mgrid[0:FRAME, 0:FRAME]
    smooth = 110 + 30 * np.sin(xx / 40.0 + rng.uniform(0, 3)) * np.cos(yy / 55.0)
    ok, encoded = cv2.imencode('.jpg', _bgr(smooth), [cv2.IMWRITE_JPEG_QUALITY, 30])
    assert ok
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def _block_pattern(rng):
    """Constant 8 x 8 blocks: the axis-aligned, balanced edges JPEG leaves in flat areas."""
    blocks = rng.normal(0, 4, (FRAME // 8 + 1, FRAME // 8 + 1)).astype(np.float32)
    return _bgr(110 + np.kron(blocks, np.ones((8, 8), np.float32))[:FRAME, :FRAME])


@pytest.mark.parametrize('options', [{}, OVAL], ids=['ring_preset', 'oval_size'])
@pytest.mark.parametrize('make', [
    lambda rng: _bgr(_gaussian_ground(rng)),
    lambda rng: _bgr(_fractal_ground(rng, amplitude=25)),
    _trail,
    _rectangles,
    _polygons,
    _jpeg_blocking,
    _block_pattern,
], ids=['gaussian_noise', 'fractal_noise', 'trail', 'rectangles', 'polygons', 'jpeg_blocking', 'block_pattern'])
def test_negatives_produce_no_aois(tmp_path, make, options):
    service = _service(**options)
    for seed in range(3):
        result = _run(service, make(np.random.default_rng(seed)), tmp_path)
        assert result.error_message is None
        assert not result.areas_of_interest, f"seed {seed}: {result.areas_of_interest}"


# --- options ------------------------------------------------------------------

def _several_targets(rng):
    ground = _gaussian_ground(rng, 500)
    for k, (cx, cy) in enumerate(((100, 100), (250, 100), (400, 100), (100, 300), (300, 330))):
        ground = _with_ellipse(ground, cx, cy, 70, 60 + 2 * k, 15 * k, 125 + 12 * k)
    return _bgr(ground)


def test_the_top_n_cap_keeps_the_strongest(tmp_path):
    img = _several_targets(np.random.default_rng(10))
    everything = _run(_service(), img, tmp_path).areas_of_interest
    capped = _run(_service(max_detections_per_image=2), img, tmp_path).areas_of_interest
    assert len(everything) > 2
    assert len(capped) == 2
    best_two = sorted((a['confidence'] for a in everything), reverse=True)[:2]
    assert sorted((a['confidence'] for a in capped), reverse=True) == best_two


def test_min_confidence_is_honoured(tmp_path):
    img = _several_targets(np.random.default_rng(10))
    result = _run(_service(min_confidence=80.0), img, tmp_path)
    assert all(a['confidence'] >= 80.0 for a in result.areas_of_interest or [])
    assert not _run(_service(min_confidence=100.0), img, tmp_path).areas_of_interest


def test_missing_option_keys_take_defaults():
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {'min_confidence': '35.0'})
    assert service.settings == dict(normalize_options({}), min_confidence=35.0)


@pytest.mark.parametrize('frame', [
    np.zeros((120, 120), np.uint8),
    np.zeros((120, 120, 4), np.uint8),
    np.zeros((120, 120, 3), np.uint16),
], ids=['gray', 'bgra', 'sixteen_bit'])
def test_unusual_decodes_are_accepted(tmp_path, frame):
    result = _run(_service(), frame, tmp_path)
    assert result.error_message is None


# --- GSD and the resolution floor ---------------------------------------------

def test_below_the_resolution_floor_the_image_is_skipped_with_a_warning(tmp_path):
    """A 50 cm short diameter at 5 cm/px is 10 px, under the default 12 px floor."""
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(11)), CENTRE, CENTRE, 14, 14, 0, 160))
    service = _service(gsd_cm=5.0)
    service.logger = MagicMock()
    result = _run(service, img, tmp_path)
    assert result.error_message is None
    assert not result.areas_of_interest
    warning = str(service.logger.warning.call_args)
    assert 'below the 12 px floor' in warning
    assert 'frame.jpg' in warning


def test_no_gsd_and_no_fallback_is_an_error_result_not_an_exception(tmp_path):
    """The file does not exist, so the real metadata lookup finds nothing."""
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {})
    result = service.process_image(np.zeros((100, 100, 3), np.uint8), str(tmp_path / 'missing.jpg'),
                                   str(tmp_path), str(tmp_path))
    assert result.error_message
    assert 'missing.jpg' in result.error_message
    assert 'RoundShape' in result.error_message


def test_the_fallback_gsd_is_used_and_scaled_to_processing_resolution(tmp_path):
    """Fallback is a full-resolution figure: 0.5 cm/px native at 50% is 1 cm/px processed."""
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(12)), CENTRE, CENTRE, 70, 70, 0, 160))
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {'fallback_gsd_cm': 0.5})
    service.set_scale_factor(0.5)
    gsd, gsd_service = service._resolve_gsd_cm(img, str(tmp_path / 'missing.jpg'))
    assert gsd == pytest.approx(1.0)
    assert gsd_service is None
    result = service.process_image(img, str(tmp_path / 'missing.jpg'), str(tmp_path), str(tmp_path))
    assert _hit(result.areas_of_interest, CENTRE, CENTRE, 10)


class _FakeImageService:
    """Stands in for ImageService: records how it was asked, answers a fixed GSD."""

    calls = []

    def __init__(self, path, defer_load=False):
        self.path = path
        self.defer_load = defer_load

    def get_gsd_service(self, **kwargs):
        _FakeImageService.calls.append((self.defer_load, kwargs))
        gsd_service = MagicMock()
        gsd_service.compute_average_gsd.return_value = 0.5
        gsd_service.image = (800, 600)
        gsd_service.title_angle = 0.0
        return gsd_service


def test_metadata_gsd_is_cache_only_and_rescaled_to_the_processed_frame(monkeypatch):
    """0.5 cm per EXIF pixel on an 800 px frame processed at 400 px is 1 cm/px."""
    monkeypatch.setattr('core.services.image.ImageService.ImageService', _FakeImageService)
    _FakeImageService.calls = []
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {})
    service.set_scale_factor(0.5)
    gsd, _ = service._resolve_gsd_cm(np.zeros((300, 400, 3), np.uint8), 'frame.jpg')
    assert gsd == pytest.approx(1.0)
    defer_load, kwargs = _FakeImageService.calls[0]
    assert defer_load is True
    assert kwargs['offline_only'] is True
    assert kwargs['use_terrain'] is True
    assert kwargs['frame_size'] == (800, 600)


def test_an_oblique_frame_widens_the_size_tolerance():
    gsd_service = MagicMock()
    gsd_service.title_angle = 30.0
    gsd_service.image = (4000, 3000)
    gsd_service.compute_gsd.side_effect = lambda row, col: 1.0 if row == 0 else 1.5
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {})
    assert service._effective_tolerance(0.2, gsd_service, 'frame.jpg') == pytest.approx(1.2 * 1.5 - 1.0)


def test_a_nadir_frame_keeps_the_size_tolerance():
    gsd_service = MagicMock()
    gsd_service.title_angle = 3.0
    service = RoundShapeService((255, 0, 0), 10, 0, 0, False, {})
    assert service._effective_tolerance(0.2, gsd_service, 'frame.jpg') == 0.2
    gsd_service.compute_gsd.assert_not_called()


# --- outputs ------------------------------------------------------------------

def test_the_debug_overlay_is_written_only_when_enabled(tmp_path):
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(13)), CENTRE, CENTRE, 70, 70, 0, 160))
    debug_file = tmp_path / 'out' / 'round_debug' / 'frame_debug.jpg'
    _run(_service(), img, tmp_path)
    assert not debug_file.exists()
    _run(_service(debug_output=True), img, tmp_path)
    assert debug_file.exists()
    assert cv2.imread(str(debug_file)).shape == img.shape


def test_aois_and_options_survive_an_adiat_data_round_trip(tmp_path):
    """Only keys the XML writer already persists are emitted, and options read back typed."""
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(14)), CENTRE, CENTRE, 70, 70, 0, 160))
    options = dict(DEFAULT_OPTIONS, detect_arcs=False, fallback_gsd_cm=None, min_confidence=40.0)
    result = _run(_service(**options), img, tmp_path)
    assert result.areas_of_interest

    writer = XmlService()
    writer.add_settings_to_xml(algorithm='RoundShape', options=options)
    writer.add_image_to_xml({'path': str(tmp_path / 'frame.jpg'), 'aois': result.areas_of_interest})
    xml_path = str(tmp_path / 'ADIAT_Data.xml')
    writer.save_xml_file(xml_path)

    reader = XmlService(xml_path)
    settings, _ = reader.get_settings()
    assert normalize_options(settings['options']) == normalize_options(options)
    images = reader.get_images()
    loaded = images[0]['areas_of_interest']
    assert [a['confidence'] for a in loaded] == [a['confidence'] for a in result.areas_of_interest]
    assert {a['score_type'] for a in loaded} == {'shape'}


def test_a_target_cut_by_the_frame_edge_stays_inside_the_frame(tmp_path):
    """Two thirds of the outline visible at the image edge: an arc, but no out-of-frame pixels."""
    img = _bgr(_with_ellipse(_gaussian_ground(np.random.default_rng(15)), 12, CENTRE, 70, 70, 0, 170))
    result = _run(_service(), img, tmp_path)
    assert result.areas_of_interest
    for aoi in result.areas_of_interest:
        for x, y in aoi['contour'] + aoi['detected_pixels']:
            assert 0 <= x < FRAME and 0 <= y < FRAME


def test_contours_are_clipped_to_the_frame():
    from algorithms.Shared.services.RoundGeometry import Ellipse
    contour = RoundShapeService._contour_in_frame(Ellipse(5, 50, 60, 40, 0), (100, 120, 3))
    xs, ys = contour[:, 0, 0], contour[:, 0, 1]
    assert xs.min() == 0 and xs.max() == 35
    assert ys.min() == 30 and ys.max() == 70


def test_no_detections_store_no_mask(tmp_path):
    result = _run(_service(), _bgr(_gaussian_ground(np.random.default_rng(16))), tmp_path)
    assert result.output_path is None
    assert not os.path.exists(tmp_path / 'out' / 'frame.tif')
