"""Tests for the TileFetchDialog getters."""

import pytest
from PySide6.QtWidgets import QApplication

from core.views.images.viewer.dialogs.TileFetchDialog import TileFetchDialog


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_defaults(app):
    d = TileFetchDialog()
    assert d.want_dem() is True
    assert d.want_canopy() is True
    assert d.should_register() is True
    assert d.get_output_dir() == ""


def test_prefill_and_bounds(app):
    d = TileFetchDialog(default_bounds=(-120.5, 38.7, -120.4, 38.8))
    assert d.get_bounds() == pytest.approx((-120.5, 38.7, -120.4, 38.8))


def test_invalid_bounds_return_none(app):
    d = TileFetchDialog()
    assert d.get_bounds() is None            # empty fields
    d.min_lon_edit.setText("-120.4")
    d.min_lat_edit.setText("38.7")
    d.max_lon_edit.setText("-120.5")         # max < min
    d.max_lat_edit.setText("38.8")
    assert d.get_bounds() is None
