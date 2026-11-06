"""The Ground Message Detector is registered wherever ADIAT looks algorithms up."""

import json
import os

import pytest

from core.services.ConfigService import ConfigService

CONF_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'algorithms.conf')
SELECTION_PAGE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'core', 'controllers',
                                   'images', 'guidePages', 'AlgorithmSelectionPage.py')


@pytest.fixture(scope='module')
def entry():
    with open(CONF_PATH, encoding='utf-8') as handle:
        algorithms = json.load(handle)['algorithms']
    matches = [a for a in algorithms if a['name'] == 'GroundMessage']
    assert len(matches) == 1
    return matches[0]


def test_config_entry_is_complete(entry):
    assert entry == {
        'name': 'GroundMessage',
        'label': 'Ground Message Detector',
        'controller': 'GroundMessageController',
        'wizard_controller': 'GroundMessageWizardController',
        'service': 'GroundMessageService',
        'combine_overlapping_aois': True,
        'platforms': ['Windows', 'Darwin'],
        'type': 'RGB',
    }


def test_controllers_are_resolvable_where_they_are_looked_up(entry):
    """MainWindow and the guide resolve controllers from algorithms.conf by dotted path."""
    controller = ConfigService.resolve_image_algorithm_class(entry, 'controller')
    wizard = ConfigService.resolve_image_algorithm_class(entry, 'wizard_controller')
    assert controller.__name__ == entry['controller']
    assert wizard.__name__ == entry['wizard_controller']


def test_guide_selects_the_configured_name(entry):
    """The decision tree hands MainWindow the stable key and shows the label."""
    with open(SELECTION_PAGE_PATH, encoding='utf-8') as handle:
        source = handle.read()
    assert f'self.selected_algorithm = "{entry["name"]}"' in source
    assert f'self.tr("{entry["label"]}")' in source
