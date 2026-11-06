"""Tests for GroundMessageDetector on deterministic synthetic aerial scenes."""

import cv2
import numpy as np
import pytest

from algorithms.images.GroundMessage.services.GroundMessageDetector import (
    POLARITY_DARK, POLARITY_LIGHT, GlyphCandidate, GroundMessageDetector, MessageCandidate, paint_message_mask,
    to_gray_u8)
from tests.algorithms.images.GroundMessage.conftest import (
    boxes_overlap, draw_stick, draw_word, finish, make_ground, scatter_sticks)


def _messages_on(messages, boxes):
    return [m for m in messages if any(boxes_overlap(m.box, b) for b in boxes)]


def test_finds_help_spelled_in_sticks(help_scene):
    img, boxes = help_scene
    messages = GroundMessageDetector().detect(img)
    assert messages, "no message found"
    best = messages[0]
    assert any(boxes_overlap(best.box, b) for b in boxes)
    assert len(best.glyphs) >= 3
    assert best.score >= 0.6


@pytest.mark.parametrize('angle', [35, -70, 180])
def test_detection_is_rotation_tolerant(angle):
    """A message reads at any heading from the air."""
    img = make_ground(600, 900, seed=4)
    boxes = draw_word(img, 'HELP', (450, 300), 90, angle_deg=angle)
    messages = GroundMessageDetector().detect(finish(img, seed=4), min_score=0.5)
    hits = _messages_on(messages, boxes)
    assert hits and max(len(m.glyphs) for m in hits) >= 3


def test_plain_ground_has_no_messages(empty_scene):
    assert GroundMessageDetector().detect(empty_scene, min_score=0.5) == []


def test_single_log_is_not_a_message():
    img = make_ground(600, 900, seed=7)
    draw_stick(img, (100, 300), 600, 10, 14)
    assert GroundMessageDetector().detect(finish(img, seed=7), min_score=0.5) == []


def test_message_outscores_surrounding_clutter():
    img = make_ground(700, 1000, seed=21)
    scatter_sticks(img, 15, (30, 100), 9, seed=3)
    boxes = draw_word(img, 'SOS', (500, 350), 110)
    messages = GroundMessageDetector().detect(finish(img, seed=21))
    assert messages
    assert any(boxes_overlap(messages[0].box, b) for b in boxes)


def test_light_material_found_when_searching_light_strokes():
    img = make_ground(600, 900, seed=5, base=(40, 60, 60))
    boxes = draw_word(img, 'SOS', (450, 300), 100, color=(200, 205, 210))
    img = finish(img, seed=5)
    light = GroundMessageDetector(polarities=(POLARITY_LIGHT,)).detect(img, min_score=0.5)
    hits = _messages_on(light, boxes)
    assert hits and max(len(m.glyphs) for m in hits) >= 3
    assert all(g.polarity == POLARITY_LIGHT for m in light for g in m.glyphs)


def test_single_character_reported_only_when_enabled():
    img = make_ground(600, 900, seed=6)
    boxes = draw_word(img, 'X', (450, 300), 120)
    img = finish(img, seed=6)
    with_singles = GroundMessageDetector(detect_single_characters=True).detect(img, min_score=0.5)
    without = GroundMessageDetector(detect_single_characters=False).detect(img, min_score=0.5)
    assert _messages_on(with_singles, boxes)
    assert not _messages_on(without, boxes)


def test_lone_closed_outline_is_not_reported_as_a_character():
    """A building or vehicle outline reads like an O; a lone loop is not a signal."""
    img = make_ground(600, 900, seed=8)
    cv2.rectangle(img, (380, 230), (500, 370), (30, 40, 55), 10)
    messages = GroundMessageDetector(detect_single_characters=True).detect(finish(img, seed=8), min_score=0.5)
    assert messages == []


def test_single_characters_score_below_words(help_scene):
    """A lone character is weaker evidence than a row of them."""
    img = make_ground(600, 900, seed=6)
    draw_word(img, 'X', (450, 300), 120)
    single = GroundMessageDetector().detect(finish(img, seed=6))
    word = GroundMessageDetector().detect(help_scene[0])
    assert max(m.score for m in single) < max(m.score for m in word)


def test_character_size_range_excludes_out_of_range_messages(help_scene):
    img, boxes = help_scene  # characters are ~90 px
    too_big_only = GroundMessageDetector(min_char_size=250, max_char_size=900).detect(img, min_score=0.5)
    assert not _messages_on(too_big_only, boxes)


def test_min_score_filters_messages(help_scene):
    img, _ = help_scene
    assert GroundMessageDetector().detect(img, min_score=1.01) == []


@pytest.mark.parametrize('kwargs', [
    {'min_char_size': 0},
    {'min_char_size': 100, 'max_char_size': 100},
    {'polarities': ()},
    {'polarities': ('purple',)},
])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        GroundMessageDetector(**kwargs)


def test_pyramid_levels_cover_requested_sizes():
    detector = GroundMessageDetector(min_char_size=40, max_char_size=600)
    assert detector.pyramid_levels(4000, 6000) == [1, 2, 4, 8, 16]
    # Level 4 handles 80-480 px characters, so a 70 px ceiling stops at level 2.
    small_only = GroundMessageDetector(min_char_size=40, max_char_size=70)
    assert small_only.pyramid_levels(4000, 6000) == [1, 2]
    # Levels that would shrink the image below the minimum are skipped.
    assert 16 not in detector.pyramid_levels(600, 900)


@pytest.mark.parametrize('image', [
    np.zeros((50, 60, 4), np.uint8),
    np.zeros((50, 60), np.uint16),
    np.zeros((50, 60, 1), np.uint8),
    np.zeros((50, 60, 3), np.float32),
])
def test_to_gray_accepts_common_image_formats(image):
    gray = to_gray_u8(image)
    assert gray.shape == (50, 60)
    assert gray.dtype == np.uint8


def test_to_gray_rejects_empty_image():
    with pytest.raises(ValueError):
        to_gray_u8(np.zeros((0, 0, 3), np.uint8))


def _glyph(x0, y0, size, polarity=POLARITY_DARK, brightness=50.0):
    xs = np.linspace(x0, x0 + size * 0.7, 20)
    ys = np.linspace(y0, y0 + size, 20)
    points = np.stack([np.concatenate([xs, xs]), np.concatenate([ys, ys[::-1]])], 1).astype(np.float32)
    return GlyphCandidate(x0=int(x0), y0=int(y0), x1=int(x0 + size * 0.7), y1=int(y0 + size), level=1,
                          polarity=polarity, score=0.9, long_side=size, stroke_width=size / 10,
                          brightness=brightness, features={}, level_mask=np.zeros((1, 1), np.uint8),
                          points=points)


def test_line_check_accepts_an_evenly_spaced_row():
    row = [_glyph(100 + i * 110, 200, 100) for i in range(4)]
    is_line, _ = GroundMessageDetector.line_check(row)
    assert is_line


def test_line_check_rejects_a_glyph_off_the_baseline():
    row = [_glyph(100, 200, 100), _glyph(210, 200, 100), _glyph(320, 290, 100)]
    is_line, _ = GroundMessageDetector.line_check(row)
    assert not is_line


def test_prune_to_line_drops_the_outlier_not_a_good_glyph():
    good = [_glyph(100 + i * 110, 200, 100) for i in range(3)]
    outlier = _glyph(320, 330, 100)
    outlier.score = 0.95  # even a strong outlier is the one removed
    kept = GroundMessageDetector.prune_to_line(good + [outlier])
    assert outlier not in kept
    assert all(g in kept for g in good)


def test_compatible_requires_matching_material_and_size():
    a = _glyph(100, 200, 100)
    assert GroundMessageDetector.compatible(a, _glyph(210, 200, 100))
    assert not GroundMessageDetector.compatible(a, _glyph(210, 200, 100, polarity=POLARITY_LIGHT))
    assert not GroundMessageDetector.compatible(a, _glyph(210, 200, 200))
    assert not GroundMessageDetector.compatible(a, _glyph(210, 200, 100, brightness=200.0))
    assert not GroundMessageDetector.compatible(a, _glyph(600, 200, 100))  # too far apart


def test_paint_message_mask_clips_at_image_edges():
    crop = np.full((10, 10), 255, np.uint8)
    glyph = _glyph(0, 0, 10)
    glyph.level_mask = crop
    glyph.level_origin = (-3, 15)  # partly outside the left and bottom edges
    glyph.level = 2
    mask = paint_message_mask([MessageCandidate([glyph], 0.9)], (40, 30))
    assert mask.shape == (40, 30)
    assert mask[30:40, 0:14].min() == 255
    assert mask[:30].max() == 0
