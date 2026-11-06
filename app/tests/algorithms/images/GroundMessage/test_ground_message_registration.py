"""The Ground Message Detector is registered wherever ADIAT looks algorithms up."""

import importlib
import json
import os

import pytest

# import_module, not "import ... as": the guidePages package re-exports the
# page class under the same name as its module.
main_window_module = importlib.import_module('core.controllers.images.MainWindow')
parameters_page_module = importlib.import_module('core.controllers.images.guidePages.AlgorithmParametersPage')

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
    """MainWindow and the guide resolve controllers by name from their module globals."""
    assert entry['controller'] in vars(main_window_module)
    assert entry['controller'] in vars(parameters_page_module)
    assert entry['wizard_controller'] in vars(parameters_page_module)


def test_guide_selects_the_configured_label(entry):
    """The decision tree selects by label, so the two must match exactly."""
    with open(SELECTION_PAGE_PATH, encoding='utf-8') as handle:
        assert f'"{entry["label"]}"' in handle.read()
