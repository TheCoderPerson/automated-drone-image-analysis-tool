"""Tests for the per-character shape analysis of the Ground Message Detector."""

import cv2
import numpy as np
import pytest
from skimage.morphology import skeletonize

from algorithms.images.GroundMessage.services.GlyphShapeAnalyzer import (
    analyze_skeleton, glyph_evidence, is_structured, measure_glyph, piecewise_linear, polyline_segments,
    score_glyph, trapezoid)


def stick_mask(segments, size=140, thickness=10, pad=20):
    """Binary (0/255) mask of straight sticks given in unit coordinates."""
    mask = np.zeros((size + 2 * pad, size + 2 * pad), np.uint8)
    for (x0, y0), (x1, y1) in segments:
        p = (int(pad + x0 * size), int(pad + y0 * size))
        q = (int(pad + x1 * size), int(pad + y1 * size))
        cv2.line(mask, p, q, 255, thickness)
    return mask


H = [((0.15, 0), (0.15, 1)), ((0.85, 0), (0.85, 1)), ((0.15, 0.5), (0.85, 0.5))]
E = [((0.2, 0), (0.2, 1)), ((0.2, 0), (0.8, 0)), ((0.2, 0.5), (0.7, 0.5)), ((0.2, 1), (0.8, 1))]
X = [((0.1, 0), (0.9, 1)), ((0.9, 0), (0.1, 1))]
L = [((0.2, 0), (0.2, 1)), ((0.2, 1), (0.8, 1))]
STICK = [((0.5, 0), (0.5, 1))]


def test_trapezoid_shape():
    assert trapezoid(0, 1, 2, 3, 4) == 0.0
    assert trapezoid(1.5, 1, 2, 3, 4) == pytest.approx(0.5)
    assert trapezoid(2.5, 1, 2, 3, 4) == 1.0
    assert trapezoid(3.5, 1, 2, 3, 4) == pytest.approx(0.5)
    assert trapezoid(5, 1, 2, 3, 4) == 0.0


def test_piecewise_linear_interpolates_and_clamps():
    points = [(0, 0.0), (1, 1.0), (3, 0.0)]
    assert piecewise_linear(-1, points) == 0.0
    assert piecewise_linear(0.5, points) == pytest.approx(0.5)
    assert piecewise_linear(2, points) == pytest.approx(0.5)
    assert piecewise_linear(10, points) == 0.0


def test_skeleton_graph_of_h_has_two_junctions_and_four_ends():
    skel = skeletonize(stick_mask(H) > 0).astype(np.uint8)
    graph = analyze_skeleton(skel, spur_length=12)
    assert graph['junctions'] == 2
    assert graph['endpoints'] == 4


def test_skeleton_graph_of_ring_is_a_loop_without_ends():
    mask = np.zeros((160, 160), np.uint8)
    cv2.circle(mask, (80, 80), 55, 255, 10)
    skel = skeletonize(mask > 0).astype(np.uint8)
    graph = analyze_skeleton(skel, spur_length=12)
    assert graph['endpoints'] == 0
    assert any(branch['is_loop'] for branch in graph['branches'])


def test_short_spurs_are_pruned():
    """A small twig on a stick must not count as an extra stroke end."""
    mask = stick_mask(STICK + [((0.5, 0.5), (0.58, 0.45))], thickness=8)
    skel = skeletonize(mask > 0).astype(np.uint8)
    graph = analyze_skeleton(skel, spur_length=20)
    assert graph['endpoints'] == 2
    assert graph['junctions'] == 0


def test_polyline_segments_find_the_corner_of_an_l():
    points = np.array([(r, 10) for r in range(10, 110)] + [(110, c) for c in range(10, 80)], np.float32)
    segments = polyline_segments(points, is_loop=False, epsilon=2.0)
    assert len(segments) == 2
    angles = sorted(angle for _, angle in segments)
    assert angles[0] == pytest.approx(0, abs=3)
    assert angles[1] == pytest.approx(90, abs=3)


def test_measure_glyph_reports_stroke_width_and_size():
    features = measure_glyph(stick_mask(H, size=140, thickness=10))
    assert features is not None
    assert features['stroke_width'] == pytest.approx(10, abs=3)
    assert features['long_side'] == pytest.approx(150, abs=15)
    assert features['junctions'] == 2
    assert features['orientations'] >= 2
    assert 2.0 < features['complexity'] < 3.5


def test_measure_glyph_returns_none_for_empty_mask():
    assert measure_glyph(np.zeros((50, 50), np.uint8)) is None


@pytest.mark.parametrize('segments', [H, E, X])
def test_characters_score_well(segments):
    assert score_glyph(measure_glyph(stick_mask(segments))) >= 0.8


def test_single_stick_scores_low():
    assert score_glyph(measure_glyph(stick_mask(STICK))) < 0.35


def test_solid_blob_scores_low():
    mask = np.zeros((180, 180), np.uint8)
    cv2.ellipse(mask, (90, 90), (70, 50), 20, 0, 360, 255, -1)
    features = measure_glyph(mask)
    assert features is None or score_glyph(features) < 0.35


def test_two_stroke_shape_without_junction_scores_below_h():
    """An L is indistinguishable from a bent stick, so it gets less credit than an H."""
    l_features = measure_glyph(stick_mask(L))
    h_features = measure_glyph(stick_mask(H))
    assert not is_structured(l_features)
    assert is_structured(h_features)
    assert score_glyph(l_features) < score_glyph(h_features)


def test_evidence_terms_are_all_in_unit_range():
    evidence = glyph_evidence(measure_glyph(stick_mask(E)))
    assert evidence
    assert all(0.0 <= value <= 1.0 for value in evidence.values())
