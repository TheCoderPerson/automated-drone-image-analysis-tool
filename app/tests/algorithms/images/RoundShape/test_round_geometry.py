"""Tests for the pure geometry behind the Round Shape detector.

Every fixture is synthesised with numpy/cv2, so the expected values follow
from the construction: a disk of diameter d has its outline at radius d / 2,
an ellipse's antipodal points straddle its centre, and a straight edge does
not turn with a curve laid along it.
"""

import math

import cv2
import numpy as np
import pytest

from algorithms.Shared.services import RectilinearGeometry
from algorithms.Shared.services import RoundGeometry as geometry
from algorithms.Shared.services.RoundGeometry import Ellipse

SIZE = 200
CENTRE = SIZE / 2


def _canvas(value=100, size=SIZE):
    return np.full((size, size), value, np.uint8)


def _ellipse_frame(major, minor, angle_deg, size=SIZE, inside=180, outside=100, cx=None, cy=None):
    """A flat frame holding one anti-aliased filled ellipse."""
    img = _canvas(outside, size)
    cx = size / 2 if cx is None else cx
    cy = size / 2 if cy is None else cy
    cv2.ellipse(img, (int(round(cx * 16)), int(round(cy * 16))), (int(round(major * 8)), int(round(minor * 8))),
                angle_deg, 0, 360, inside, -1, cv2.LINE_AA, 4)
    return cv2.GaussianBlur(img, (0, 0), 0.8)


def _rect_frame(length, width, angle_deg, inside=180, outside=100):
    img = _canvas(outside)
    corners = cv2.boxPoints(((CENTRE, CENTRE), (length, width), angle_deg))
    cv2.fillPoly(img, [np.rint(corners * 16).astype(np.int32)], inside, lineType=cv2.LINE_AA, shift=4)
    return cv2.GaussianBlur(img, (0, 0), 0.8)


def _arc_frame(diameter, start_deg, end_deg, thickness=6, inside=170, outside=100):
    """A curved stroke: part of a circle's outline, as a partly buried tire or a hose shows."""
    img = _canvas(outside)
    cv2.ellipse(img, (int(CENTRE * 16), int(CENTRE * 16)), (int(diameter * 8), int(diameter * 8)), 0,
                start_deg, end_deg, inside, thickness, cv2.LINE_AA, 4)
    return cv2.GaussianBlur(img, (0, 0), 0.8)


def _prepare(img, contrast=10.0):
    mag, ang = geometry.compute_gradients(img)
    return mag, ang, geometry.edge_map(img, mag, contrast)


def _fit(img, peak, radius_range, angle_tol=15.0):
    mag, ang, edges = _prepare(img)
    return geometry.fit_round(edges, mag, ang, peak[0], peak[1], radius_range, angle_tol, geometry.noise_floor(mag))


def _axial_offset(a_deg, b_deg):
    return abs(((a_deg - b_deg) + 90.0) % 180.0 - 90.0)


def _assert_ellipse(found, cx, cy, major, minor, angle=None, centre_tol=2.0, axis_tol=3.0):
    assert math.hypot(found.cx - cx, found.cy - cy) < centre_tol
    assert found.major == pytest.approx(major, abs=axis_tol)
    assert found.minor == pytest.approx(minor, abs=axis_tol)
    if angle is not None:
        assert _axial_offset(found.angle_deg, angle) < 4.0


def _best(hypotheses, cx, cy, major):
    return min(hypotheses, key=lambda e: math.hypot(e.cx - cx, e.cy - cy) + abs(e.major - major))


# --- Ellipse construction and sampling ----------------------------------------

def test_make_ellipse_orders_the_axes_and_turns_the_angle_with_them():
    assert geometry.make_ellipse(5, 6, 40, 60, 10) == Ellipse(5.0, 6.0, 60.0, 40.0, 100.0)
    assert geometry.make_ellipse(5, 6, 60, 40, 190).angle_deg == 10.0


@pytest.mark.parametrize('major, minor, angle', [(60, 60, 0), (80, 40, 30), (90, 50, 135)])
def test_ellipse_points_lie_on_the_outline_with_outward_unit_normals(major, minor, angle):
    ellipse = Ellipse(100, 120, major, minor, angle)
    points, normals = geometry.ellipse_points(ellipse, 72)
    theta = math.radians(angle)
    dx, dy = points[:, 0] - 100, points[:, 1] - 120
    u = dx * math.cos(theta) + dy * math.sin(theta)
    v = -dx * math.sin(theta) + dy * math.cos(theta)
    assert np.allclose((u / (major / 2)) ** 2 + (v / (minor / 2)) ** 2, 1.0, atol=1e-3)
    assert np.allclose(np.hypot(normals[:, 0], normals[:, 1]), 1.0, atol=1e-5)
    assert np.all(normals[:, 0] * dx + normals[:, 1] * dy > 0)


def test_ellipse_points_are_evenly_spaced_along_an_oval():
    """Equal arc length, so the pointed ends are not over-represented."""
    points, _ = geometry.ellipse_points(Ellipse(0, 0, 100, 40, 0), 72)
    steps = np.hypot(*np.diff(np.vstack([points, points[:1]]), axis=0).T)
    assert steps.max() / steps.min() < 1.1


def test_ellipse_perimeter():
    assert geometry.ellipse_perimeter(Ellipse(0, 0, 60, 60, 0)) == pytest.approx(math.pi * 60)
    # A 2:1 ellipse with semi-axes 40 and 20 has perimeter 193.77 to two decimals.
    assert geometry.ellipse_perimeter(Ellipse(0, 0, 80, 40, 30)) == pytest.approx(193.77, abs=0.01)
    assert geometry.ellipse_perimeter(Ellipse(0, 0, 0, 0, 0)) == 0.0


def test_size_score_is_the_rectilinear_size_decay():
    ranges = (55.0, 95.0, 50.0, 95.0)
    for major, minor in ((70, 70), (120, 80), (40, 30)):
        assert geometry.size_score(major, minor, ranges, 0.2) == RectilinearGeometry.size_score(major, minor, ranges, 0.2)


# --- edges and the symmetry map ------------------------------------------------

def test_edge_map_on_a_blank_frame_is_empty():
    img = _canvas()
    mag, _ = geometry.compute_gradients(img)
    assert not geometry.edge_map(img, mag, 10.0).any()


def test_edge_map_drops_edges_fainter_than_the_contrast_setting():
    faint = _ellipse_frame(60, 60, 0, inside=106, outside=100)
    mag, _ = geometry.compute_gradients(faint)
    assert not geometry.edge_map(faint, mag, 10.0).any()


def test_edge_map_rises_above_busy_texture():
    """On noisy ground the floor follows the texture, not just the contrast setting."""
    rng = np.random.default_rng(0)
    noisy = cv2.GaussianBlur(np.clip(rng.normal(110, 8, (SIZE, SIZE)), 0, 255).astype(np.uint8), (0, 0), 0.8)
    mag, _ = geometry.compute_gradients(noisy)
    assert geometry.noise_floor(mag) > 0.5 * 10.0
    with_floor = np.count_nonzero(geometry.edge_map(noisy, mag, 10.0))
    contrast_only = np.count_nonzero(cv2.Canny(noisy, 10.0, 20.0, L2gradient=True))
    assert with_floor < 0.75 * contrast_only


def test_a_disk_votes_for_its_centre_and_radius():
    img = _ellipse_frame(60, 60, 0)
    mag, ang, edges = _prepare(img)
    symmetry, radius = geometry.radial_symmetry_map(edges, mag, ang, (15, 45), 3, 5.0)
    peaks = geometry.symmetry_peaks(symmetry, radius, 0.25, 15, 3)
    assert peaks
    cx, cy, voting_radius, strength = peaks[0]
    assert math.hypot(cx - CENTRE, cy - CENTRE) <= 3.0
    assert voting_radius == pytest.approx(30, abs=3)
    assert strength > 1.0


def test_isotropic_noise_casts_no_peaks():
    rng = np.random.default_rng(1)
    noisy = cv2.GaussianBlur(np.clip(rng.normal(110, 8, (300, 300)), 0, 255).astype(np.uint8), (0, 0), 0.8)
    mag, ang, edges = _prepare(noisy)
    symmetry, _ = geometry.radial_symmetry_map(edges, mag, ang, (15, 45), 3, 5.0)
    assert float(symmetry.max()) < 0.25


def test_a_flat_frame_has_no_symmetry():
    img = _canvas()
    mag, ang, edges = _prepare(img)
    symmetry, radius = geometry.radial_symmetry_map(edges, mag, ang, (10, 30), 2, 5.0)
    assert not symmetry.any()
    assert geometry.symmetry_peaks(symmetry, radius, 0.25, 10, 2) == []


def test_symmetry_peaks_come_strongest_first_and_are_capped():
    """The faint circle's edge sits below the vote cap; the strong one's at it."""
    img = _canvas()
    for x, value in ((50, 118), (150, 200)):
        cv2.circle(img, (x, 100), 20, value, -1, cv2.LINE_AA)
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    mag, ang, edges = _prepare(img)
    symmetry, radius = geometry.radial_symmetry_map(edges, mag, ang, (12, 30), 3, 5.0)
    peaks = geometry.symmetry_peaks(symmetry, radius, 0.25, 12, 3)
    assert [round(p[0] / 50) for p in peaks[:2]] == [3, 1]
    assert len(geometry.symmetry_peaks(symmetry, radius, 0.25, 12, 3, max_peaks=1)) == 1


# --- fitting --------------------------------------------------------------------

@pytest.mark.parametrize('diameter', [20, 45, 70])
def test_a_circle_is_fitted_from_its_centre(diameter):
    found = _fit(_ellipse_frame(diameter, diameter, 0), (CENTRE + 2, CENTRE - 1), (0.4 * diameter, 0.6 * diameter))
    _assert_ellipse(_best(found, CENTRE, CENTRE, diameter), CENTRE, CENTRE, diameter, diameter)


@pytest.mark.parametrize('major, minor, angle', [(60, 40, 0), (60, 40, 35), (80, 40, 110), (90, 55, 160)])
def test_an_oval_is_fitted_from_a_peak_at_one_end(major, minor, angle):
    """An oval's normals meet near its ends; antipodal pairs recover the true centre."""
    offset = 0.5 * (major - minor * minor / major)
    peak = (CENTRE + offset * math.cos(math.radians(angle)), CENTRE + offset * math.sin(math.radians(angle)))
    found = _fit(_ellipse_frame(major, minor, angle), peak, (0.4 * minor, 0.6 * major))
    _assert_ellipse(_best(found, CENTRE, CENTRE, major), CENTRE, CENTRE, major, minor, angle)


def test_a_ring_yields_both_its_edges():
    """A tire: dark rubber with the ground showing through the middle."""
    img = _canvas(150)
    cv2.circle(img, (int(CENTRE), int(CENTRE)), 35, 50, -1, cv2.LINE_AA)
    cv2.circle(img, (int(CENTRE), int(CENTRE)), 20, 150, -1, cv2.LINE_AA)
    found = _fit(cv2.GaussianBlur(img, (0, 0), 0.8), (CENTRE, CENTRE), (15, 40))
    diameters = sorted(round(e.major) for e in found if math.hypot(e.cx - CENTRE, e.cy - CENTRE) < 2)
    assert any(abs(d - 70) <= 3 for d in diameters)
    assert any(abs(d - 40) <= 3 for d in diameters)


def test_an_arc_is_fitted_as_the_circle_it_belongs_to():
    img = _arc_frame(70, 200, 340, thickness=3)
    found = _fit(img, (CENTRE, CENTRE), (25, 45))
    best = _best(found, CENTRE, CENTRE, 70)
    assert math.hypot(best.cx - CENTRE, best.cy - CENTRE) < 4.0
    assert best.major == pytest.approx(70, abs=6)


def test_nothing_is_fitted_where_there_are_no_edges():
    assert _fit(_canvas(), (CENTRE, CENTRE), (10, 40)) == []


# --- outline evidence -------------------------------------------------------------

def _evidence(img, ellipse, angle_tol=15.0):
    mag, ang = geometry.compute_gradients(img)
    return geometry.outline_support(ellipse, mag, ang, angle_tol, 5.0)


def test_a_true_outline_is_fully_supported_and_curved():
    evidence = _evidence(_ellipse_frame(80, 50, 25), Ellipse(CENTRE, CENTRE, 80, 50, 25))
    assert evidence.support > 0.95
    assert evidence.arc_deg == 360.0
    assert evidence.gap_deg == 0.0
    assert evidence.curvature > 0.9
    assert evidence.boxiness < 0.2
    assert evidence.strength > 20.0


def test_a_wrong_outline_is_not_supported():
    img = _ellipse_frame(80, 50, 25)
    rotated_wrong = _evidence(img, Ellipse(CENTRE, CENTRE, 80, 50, 115))
    elsewhere = _evidence(img, Ellipse(40, 40, 30, 30, 0))
    assert rotated_wrong.support < 0.4
    assert elsewhere.support == 0.0
    assert elsewhere.arc_deg == 0.0
    assert elsewhere.gap_deg == 360.0


def test_half_an_outline_is_one_arc_and_one_gap():
    evidence = _evidence(_arc_frame(70, 0, 180, thickness=2), Ellipse(CENTRE, CENTRE, 70, 70, 0))
    assert evidence.arc_deg == pytest.approx(180, abs=25)
    assert evidence.gap_deg == pytest.approx(180, abs=25)
    assert evidence.curvature > 0.8


def test_an_ellipse_inside_a_strip_is_supported_but_does_not_curve():
    """Laid along a rectangle's long sides, an ellipse finds edges that stay straight while it turns."""
    evidence = _evidence(_rect_frame(90, 40, 20), Ellipse(CENTRE, CENTRE, 120, 41, 20))
    assert evidence.support > 0.3
    assert evidence.curvature < 0.4


def test_a_circle_inside_a_square_is_boxy():
    evidence = _evidence(_rect_frame(50, 50, 10), Ellipse(CENTRE, CENTRE, 51, 51, 0))
    assert evidence.boxiness > 0.5


def test_scattered_texture_is_not_counted_as_support():
    """Texture backs scattered samples of any outline; only runs of them count."""
    rng = np.random.default_rng(2)
    noisy = cv2.GaussianBlur(np.clip(rng.normal(110, 8, (SIZE, SIZE)), 0, 255).astype(np.uint8), (0, 0), 0.8)
    for diameter in (14, 30, 60):
        assert _evidence(noisy, Ellipse(CENTRE, CENTRE, diameter, diameter, 0)).support < 0.3


def test_an_outline_cut_by_the_frame_edge_is_unsupported_outside_it():
    img = _ellipse_frame(60, 60, 0, cx=10, cy=CENTRE)
    evidence = _evidence(img, Ellipse(10, CENTRE, 60, 60, 0))
    assert 0.3 < evidence.support < 0.75


# --- ring contrast ------------------------------------------------------------------

def test_ring_contrast_measures_the_step_in_delta_e():
    grey = cv2.cvtColor(_ellipse_frame(60, 60, 0, inside=180, outside=100), cv2.COLOR_GRAY2BGR)
    lab = cv2.cvtColor(grey, cv2.COLOR_BGR2LAB)
    delta_e = geometry.ring_contrast_lab(lab, Ellipse(CENTRE, CENTRE, 60, 60, 0), 0.3)
    expected = (lab[int(CENTRE), int(CENTRE), 0] - lab[5, 5, 0]) * 100.0 / 255.0
    assert delta_e == pytest.approx(expected, abs=1.0)


def test_ring_contrast_reads_a_ring_target_on_its_own_material():
    """A tire shows the ground through its middle; the inside band still lands on rubber."""
    img = _canvas(150)
    cv2.circle(img, (int(CENTRE), int(CENTRE)), 35, 50, -1, cv2.LINE_AA)
    cv2.circle(img, (int(CENTRE), int(CENTRE)), 18, 150, -1, cv2.LINE_AA)
    lab = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2LAB)
    delta_e = geometry.ring_contrast_lab(lab, Ellipse(CENTRE, CENTRE, 70, 70, 0), 0.3)
    assert delta_e > 30.0


def test_ring_contrast_is_zero_on_a_flat_frame():
    lab = cv2.cvtColor(np.full((120, 120, 3), 90, np.uint8), cv2.COLOR_BGR2LAB)
    assert geometry.ring_contrast_lab(lab, Ellipse(60, 60, 40, 30, 15), 0.3) == 0.0


# --- suppression ----------------------------------------------------------------------

def test_duplicates_collapse_to_the_highest_score():
    ellipses = [Ellipse(100, 100, 60, 40, 10), Ellipse(102, 101, 58, 41, 12), Ellipse(99, 98, 61, 39, 8)]
    assert geometry.ellipse_nms(ellipses, [60.0, 80.0, 70.0], 0.3) == [1]


def test_separate_objects_both_survive():
    ellipses = [Ellipse(100, 100, 60, 40, 0), Ellipse(200, 100, 60, 40, 0)]
    assert sorted(geometry.ellipse_nms(ellipses, [50.0, 60.0], 0.3)) == [0, 1]


def test_an_outline_inside_a_stronger_one_is_suppressed():
    """A tire's inner edge, or one end of an oval fitted as a circle, is the same object."""
    outer = Ellipse(100, 100, 70, 70, 0)
    inner = Ellipse(100, 100, 40, 40, 0)
    end_of_oval = Ellipse(118, 100, 34, 34, 0)
    assert geometry.ellipse_nms([outer, inner], [90.0, 80.0], 0.3) == [0]
    assert geometry.ellipse_nms([Ellipse(100, 100, 80, 40, 0), end_of_oval], [90.0, 80.0], 0.3) == [0]


def test_kept_indices_are_highest_score_first():
    ellipses = [Ellipse(x, 100, 40, 40, 0) for x in (100, 300, 500)]
    assert geometry.ellipse_nms(ellipses, [10.0, 30.0, 20.0], 0.3) == [1, 2, 0]
