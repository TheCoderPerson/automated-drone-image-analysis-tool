"""Tests for the TileFetchDialog getters."""

import pytest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

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


def test_use_mission_button_gated_on_has_mission(app):
    assert TileFetchDialog(has_mission=False).use_mission_btn.isEnabled() is False
    assert TileFetchDialog(has_mission=True).use_mission_btn.isEnabled() is True


def test_set_aoi_and_buffer(app):
    d = TileFetchDialog()
    d.set_aoi((-120.51, 38.69, -120.45, 38.73))
    assert d.get_bounds() == pytest.approx((-120.51, 38.69, -120.45, 38.73))
    d.set_buffer(650.0)
    assert d.get_buffer() == pytest.approx(650.0)


def test_get_buffer_empty_is_none(app):
    d = TileFetchDialog()
    assert d.get_buffer() is None


# ---------------------------------------------------------------------------
# qtbot-driven interaction tests (button clicks, signals, gating)
# ---------------------------------------------------------------------------


def _shown_dialog(qtbot, **kwargs):
    """Create, register and expose a TileFetchDialog for mouse interaction."""
    d = TileFetchDialog(**kwargs)
    qtbot.addWidget(d)
    with qtbot.waitExposed(d):
        d.show()
    return d


def test_use_mission_click_populates_aoi_from_injected_extent(app, qtbot):
    """Clicking 'Use loaded mission extent' fills the AOI via caller wiring.

    The dialog exposes ``use_mission_btn`` but leaves the click handler to the
    caller (see TileFetchController.run_fetch). Simulate that wiring and confirm
    a real mouse click populates the four AOI fields from the mission extent.
    """
    d = _shown_dialog(qtbot, has_mission=True)
    extent = (-121.10, 39.20, -121.02, 39.27)
    d.use_mission_btn.clicked.connect(lambda: d.set_aoi(extent))

    assert d.get_bounds() is None  # empty before the click
    qtbot.mouseClick(d.use_mission_btn, Qt.LeftButton)
    assert d.get_bounds() == pytest.approx(extent)


def test_use_mission_click_ignored_when_disabled(app, qtbot):
    """Gating: with no mission the button is disabled and the click is a no-op."""
    d = _shown_dialog(qtbot, has_mission=False)
    fired = []
    d.use_mission_btn.clicked.connect(lambda: fired.append(True))

    assert d.use_mission_btn.isEnabled() is False
    qtbot.mouseClick(d.use_mission_btn, Qt.LeftButton)
    assert fired == []
    assert d.get_bounds() is None


def test_browse_button_updates_output_edit(app, qtbot, tmp_path):
    """Clicking Browse... writes the chosen folder into the output edit."""
    d = _shown_dialog(qtbot)
    target = str(tmp_path)
    with patch("core.views.images.viewer.dialogs.TileFetchDialog.QFileDialog") as MockFile:
        MockFile.getExistingDirectory.return_value = target
        qtbot.mouseClick(d.output_button, Qt.LeftButton)
        MockFile.getExistingDirectory.assert_called_once()
    assert d.output_edit.text() == target
    assert d.get_output_dir() == target


def test_browse_button_cancel_leaves_output_unchanged(app, qtbot):
    """A cancelled folder picker (empty string) must not clear the output edit."""
    d = _shown_dialog(qtbot)
    d.output_edit.setText("C:/existing/output")
    with patch("core.views.images.viewer.dialogs.TileFetchDialog.QFileDialog") as MockFile:
        MockFile.getExistingDirectory.return_value = ""  # user cancelled
        qtbot.mouseClick(d.output_button, Qt.LeftButton)
    assert d.output_edit.text() == "C:/existing/output"


def test_download_button_emits_accepted_with_full_payload(app, qtbot, tmp_path):
    """Download emits accepted; getters expose the payload the caller reads."""
    d = _shown_dialog(qtbot)
    bounds = (-120.60, 38.65, -120.44, 38.79)
    out_dir = str(tmp_path)
    d.set_aoi(bounds)
    d.dem_checkbox.setChecked(True)
    d.canopy_checkbox.setChecked(False)
    d.output_edit.setText(out_dir)
    d.register_checkbox.setChecked(False)

    with qtbot.waitSignal(d.accepted, timeout=1000):
        qtbot.mouseClick(d.download_button, Qt.LeftButton)

    assert d.result() == QDialog.Accepted
    assert d.get_bounds() == pytest.approx(bounds)
    assert d.want_dem() is True
    assert d.want_canopy() is False
    assert d.get_output_dir() == out_dir
    assert d.should_register() is False


def test_cancel_button_emits_rejected(app, qtbot):
    """Cancel rejects the dialog."""
    d = _shown_dialog(qtbot)
    with qtbot.waitSignal(d.rejected, timeout=1000):
        qtbot.mouseClick(d.cancel_button, Qt.LeftButton)
    assert d.result() == QDialog.Rejected


def test_download_button_not_gated_by_bounds_validity(app, qtbot):
    """The Download button has no validity gating.

    It stays enabled and still accepts even with an empty/invalid AOI; the
    caller validates get_bounds()/get_output_dir() afterward (see
    TileFetchController.run_fetch).
    """
    d = _shown_dialog(qtbot)
    assert d.download_button.isEnabled() is True
    assert d.get_bounds() is None  # nothing entered yet

    with qtbot.waitSignal(d.accepted, timeout=1000):
        qtbot.mouseClick(d.download_button, Qt.LeftButton)

    assert d.result() == QDialog.Accepted
    assert d.get_bounds() is None
