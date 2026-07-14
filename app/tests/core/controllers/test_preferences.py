"""Tests for the Preferences dialog terrain-card arrangement."""

from unittest.mock import MagicMock

import pytest

from core.controllers.Preferences import Preferences


def _make_parent():
    parent = MagicMock()

    def get_setting(key, default=None):
        values = {
            'Language': 'en',
            'MaxAOIs': 200,
            'Theme': 'Dark',
            'AOIRadius': 15,
            'PositionFormat': 'Lat/Long - Decimal Degrees',
            'TemperatureUnit': 'Fahrenheit',
            'DistanceUnit': 'Feet',
            'TerrainProviderId': 'terrarium',
        }
        return values.get(key, default if default is not None else '')

    parent.settings_service.get_setting.side_effect = get_setting
    parent.settings_service.get_bool_setting.side_effect = lambda k, d=False: {
        'OfflineOnly': False,
        'UseTerrainElevation': True,
    }.get(k, d)
    return parent


@pytest.fixture
def preferences(qtbot):
    dialog = Preferences(_make_parent())
    qtbot.addWidget(dialog)
    return dialog


def _card_children(card):
    layout = card.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def test_terrain_card_groups_all_three_controls(preferences):
    """The three related terrain controls live inside one Terrain card, in
    order: Use Terrain Elevation, Elevation Source, Terrain Cache."""
    assert hasattr(preferences, 'terrainCard')
    children = _card_children(preferences.terrainCard)

    assert children == [
        preferences.terrainWidget,
        preferences.terrainProviderGroup,
        preferences.terrainCacheWidget,
    ]


def test_canopy_group_is_at_the_bottom_below_terrain(preferences):
    """The Canopy Data Source group is the last item, directly below the
    Terrain card."""
    layout = preferences.verticalLayout_2
    last = layout.itemAt(layout.count() - 1).widget()
    second_last = layout.itemAt(layout.count() - 2).widget()
    assert last is preferences.canopySourceGroup
    assert second_last is preferences.terrainCard


def test_preferences_use_scroll_area(preferences):
    """All settings live inside a scroll area so the dialog can stay compact."""
    assert hasattr(preferences, 'scrollArea')
    assert preferences.scrollArea.widgetResizable()
    assert preferences.scrollArea.widget() is preferences.mainWidget


def test_terrain_controls_not_left_in_top_level_layout(preferences):
    """The card's controls were moved out of the main layout (no duplicates)."""
    layout = preferences.verticalLayout_2
    top_level = {layout.itemAt(i).widget() for i in range(layout.count())}

    assert preferences.terrainWidget not in top_level
    assert preferences.terrainCacheWidget not in top_level
    assert preferences.terrainProviderGroup not in top_level
    # Only the card itself represents them at the top level.
    assert preferences.terrainCard in top_level
