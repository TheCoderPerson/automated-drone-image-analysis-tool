"""Tests for the POD coverage overlay on GPSMapView."""

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

from core.views.images.viewer.widgets.GPSMapView import (
    GPSMapView,
    POD_OVERLAY_Z,
    WEB_MERCATOR_ORIGIN_SHIFT,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _transform6(cell=3.0, c=0.0, f=0.0):
    # (a, b, c, d, e, f): north-up, square cells (b=d=0, e=-a).
    return (cell, 0.0, c, 0.0, -cell, f)


def test_set_overlay_adds_item_at_correct_z(app):
    view = GPSMapView()
    view.current_zoom = 15
    view.set_pod_overlay(QPixmap(4, 4), _transform6())
    assert view.pod_overlay_item is not None
    assert view.pod_overlay_item.zValue() == POD_OVERLAY_Z
    assert view.pod_overlay_item.opacity() == pytest.approx(0.7)
    assert view.pod_overlay_item.scene() is view.scene


def test_opacity_setter(app):
    view = GPSMapView()
    view.set_pod_overlay(QPixmap(4, 4), _transform6())
    view.set_pod_overlay_opacity(0.35)
    assert view.pod_overlay_item.opacity() == pytest.approx(0.35)


def test_clear_removes_item(app):
    view = GPSMapView()
    view.set_pod_overlay(QPixmap(4, 4), _transform6())
    view.clear_pod_overlay()
    assert view.pod_overlay_item is None
    assert view._pod_pixmap is None


def test_placement_at_origin_is_world_center(app):
    view = GPSMapView()
    view.current_zoom = 15
    view.set_pod_overlay(QPixmap(4, 4), _transform6(c=0.0, f=0.0))
    world = 256 * (2 ** 15)
    pos = view.pod_overlay_item.pos()
    # c == 0 (lon 0) maps to the horizontal middle of the world.
    assert pos.x() == pytest.approx(world / 2, rel=1e-6)
    assert pos.y() == pytest.approx(world / 2, rel=1e-6)


def test_reanchor_on_zoom_doubles_position_and_scale(app):
    view = GPSMapView()
    view.current_zoom = 15
    c = WEB_MERCATOR_ORIGIN_SHIFT / 2
    view.set_pod_overlay(QPixmap(4, 4), _transform6(cell=3.0, c=c, f=c))
    pos15 = view.pod_overlay_item.pos()
    sx15 = view.pod_overlay_item.transform().m11()

    view.current_zoom = 16
    view._position_pod_overlay()
    pos16 = view.pod_overlay_item.pos()
    sx16 = view.pod_overlay_item.transform().m11()

    assert pos16.x() == pytest.approx(pos15.x() * 2, rel=1e-6)
    assert pos16.y() == pytest.approx(pos15.y() * 2, rel=1e-6)
    assert sx16 == pytest.approx(sx15 * 2, rel=1e-6)
