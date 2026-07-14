"""Tests for GPSMapDialog overlay-control gating."""

import pytest
from PySide6.QtWidgets import QApplication

from core.views.images.viewer.dialogs.GPSMapDialog import GPSMapDialog


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    dlg = GPSMapDialog(None, [], None, offline_only=True)
    yield dlg
    dlg.close()
    dlg.deleteLater()


def _mode_keys(dlg):
    return [dlg.pod_mode_combo.itemData(i) for i in range(dlg.pod_mode_combo.count())]


def test_mode_combo_offers_canopy(dialog):
    assert _mode_keys(dialog) == ["pod", "looks", "canopy"]


def test_canopy_only_enables_toggle_and_hops_selection(dialog):
    model = dialog.pod_mode_combo.model()
    keys = _mode_keys(dialog)

    dialog.set_overlay_availability(False, True)
    assert dialog.pod_toggle_btn.isEnabled()
    assert model.item(keys.index("canopy")).isEnabled()
    assert not model.item(keys.index("pod")).isEnabled()
    assert not model.item(keys.index("looks")).isEnabled()
    # The unavailable default ('pod') hops to the only enabled mode.
    assert dialog.pod_mode_combo.currentData() == "canopy"


def test_pod_only_disables_canopy_and_hops_back(dialog):
    model = dialog.pod_mode_combo.model()
    keys = _mode_keys(dialog)

    dialog.set_overlay_availability(False, True)   # selection lands on canopy
    dialog.set_overlay_availability(True, False)
    assert model.item(keys.index("pod")).isEnabled()
    assert not model.item(keys.index("canopy")).isEnabled()
    assert dialog.pod_mode_combo.currentData() == "pod"


def test_nothing_available_disables_and_unchecks(dialog):
    dialog.set_overlay_availability(True, True)
    dialog.pod_toggle_btn.setChecked(True)
    dialog.set_overlay_availability(False, False)
    assert not dialog.pod_toggle_btn.isEnabled()
    assert not dialog.pod_toggle_btn.isChecked()


def test_set_pod_available_keeps_canopy_state(dialog):
    dialog.set_overlay_availability(False, True)
    dialog.set_pod_available(True)  # legacy entry point must not drop canopy
    model = dialog.pod_mode_combo.model()
    keys = _mode_keys(dialog)
    assert model.item(keys.index("pod")).isEnabled()
    assert model.item(keys.index("canopy")).isEnabled()
