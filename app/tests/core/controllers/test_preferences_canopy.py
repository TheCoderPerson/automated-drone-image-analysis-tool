"""Smoke tests for the code-built canopy source section in Preferences."""

import pytest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def prefs(app, monkeypatch):
    monkeypatch.setattr(
        "helpers.PickleHelper.PickleHelper.get_drone_sensor_file_version",
        staticmethod(lambda: {"Version": "1", "Date": "2020-01-01"}),
    )
    settings = {
        "Language": "en", "MaxAOIs": 100, "Theme": "Dark", "AOIRadius": 5,
        "PositionFormat": "Lat/Long - Decimal Degrees", "TemperatureUnit": "Fahrenheit",
        "DistanceUnit": "Feet",
    }
    parent = MagicMock()
    parent.settings_service.get_setting.side_effect = lambda k, d=None: settings.get(k, d)
    parent.settings_service.get_bool_setting.side_effect = lambda k, d=False: settings.get(k, d)
    parent.settings_service.set_setting.side_effect = lambda k, v: settings.__setitem__(k, v)

    from core.controllers.Preferences import Preferences
    dialog = Preferences(parent)
    return dialog, settings


def test_canopy_section_built(prefs):
    dialog, _ = prefs
    assert dialog.canopyKindComboBox.count() == 3
    ids = [dialog.canopyKindComboBox.itemData(i) for i in range(3)]
    assert ids == ["none", "landfire", "meta"]


def test_default_kind_none_hides_paths(prefs):
    dialog, _ = prefs
    # Default kind is 'none' -> path fields hidden.
    assert dialog.canopyKindComboBox.currentData() == "none"
    assert dialog.canopyManifestEdit.isVisible() is False


def test_changing_kind_persists_and_shows_paths(prefs):
    dialog, settings = prefs
    idx = dialog.canopyKindComboBox.findData("meta")
    dialog.canopyKindComboBox.setCurrentIndex(idx)
    assert settings["CanopyKind"] == "meta"
    # Path fields become relevant (widgets exist; visibility toggles on show).
    dialog.show()
    dialog._refresh_canopy_visibility()
    assert dialog.canopyManifestEdit.isVisibleTo(dialog.canopySourceGroup)
    dialog.hide()


def test_manifest_edit_persists(prefs):
    dialog, settings = prefs
    dialog.canopyManifestEdit.setText("C:/data/canopy.csv")
    dialog._update_canopy_manifest()
    assert settings["CanopyManifestPath"] == "C:/data/canopy.csv"
