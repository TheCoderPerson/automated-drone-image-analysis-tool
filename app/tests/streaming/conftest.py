"""Pytest fixtures for streaming algorithm tests."""

import importlib
import sys
import os
import pytest
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog
from unittest.mock import Mock, MagicMock, patch

from algorithms.Shared.views.ColorRangeDialog import ColorRangeDialog

# Add the app directory to the Python path
app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)


@pytest.fixture(scope='session')
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_stream_settings(tmp_path_factory, request, monkeypatch):
    """Keep StreamViewerWindow's settings out of the user's real store.

    On Windows ``QSettings("ADIAT", "StreamViewer")`` resolves to
    ``HKCU\\Software\\ADIAT``, so any test that builds the window edits the
    developer's own configuration - the recording panel persists its
    options, and ``apply_wizard_data`` writes the recording directory. An
    operator with a custom "Save to" folder would find it replaced by their
    home directory after a test run.

    Neither ``QSettings.setDefaultFormat`` nor ``setPath`` can prevent this:
    the first does not apply to the ``(organization, application)``
    constructor and the second does nothing for NativeFormat on Windows
    (see the note at the top of ``app/tests/conftest.py``). The workable fix
    is to intercept the constructor the module itself calls, before the
    window is built - the recording panel reads settings inside
    ``__init__``.

    Autouse so a new streaming test cannot reintroduce the leak by
    forgetting to ask for isolation.
    """
    # Both windows persist settings: the streaming window's recording
    # panel, and each Flight Viewer tile's recording folder. Isolate every
    # module that constructs QSettings for either.
    modules = []
    for name in (
        "core.controllers.streaming.StreamViewerWindow",
        "core.controllers.flight.FlightTileController",
    ):
        try:
            modules.append(importlib.import_module(name))
        except Exception:  # deps absent - nothing to isolate for that one
            continue
    if not modules:
        yield None
        return

    QSettings.setPath(
        QSettings.IniFormat,
        QSettings.UserScope,
        str(tmp_path_factory.mktemp("qsettings")),
    )
    store = QSettings(
        QSettings.IniFormat,
        QSettings.UserScope,
        "ADIAT-Tests",
        request.node.name[:64],
    )
    for module in modules:
        monkeypatch.setattr(module, "QSettings", lambda *a, **k: store)
    yield store
    store.clear()
    store.sync()


@pytest.fixture
def sample_frame():
    """Create a sample test frame (640x480 BGR)."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_detections():
    """Create sample detection dictionaries."""
    return [
        {
            'bbox': (100, 100, 50, 50),
            'confidence': 0.85,
            'class_name': 'person',
            'id': 1
        },
        {
            'bbox': (200, 200, 80, 80),
            'confidence': 0.92,
            'class_name': 'vehicle',
            'id': 2
        }
    ]


@pytest.fixture
def algorithm_config():
    """Default algorithm configuration."""
    return {
        'name': 'TestAlgorithm',
        'version': '1.0.0',
        'description': 'Test algorithm',
        'category': 'streaming'
    }


@pytest.fixture
def mock_logger():
    """Mock logger service."""
    logger = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    return logger


@pytest.fixture
def mock_stream_manager():
    """Mock stream manager."""
    manager = Mock()
    manager.connect = Mock(return_value=True)
    manager.disconnect = Mock(return_value=True)
    manager.is_connected = False
    manager.get_stream_info = Mock(return_value={'fps': 30, 'width': 640, 'height': 480})
    return manager


@pytest.fixture
def mock_recording_manager():
    """Mock recording manager."""
    manager = Mock()
    manager.start_recording = Mock(return_value=True)
    manager.stop_recording = Mock(return_value=True)
    manager.is_recording = False
    return manager


@pytest.fixture(autouse=True)
def auto_close_color_dialogs():
    """Automatically close any color selection dialogs that open during tests."""
    # Patch ColorRangeDialog.exec() to automatically accept

    def mock_exec(self):
        # Automatically accept the dialog
        # Return Accepted status (which is 1 for QDialog.Accepted)
        return QDialog.DialogCode.Accepted

    # Patch get_hsv_ranges to return default valid data
    original_get_hsv_ranges = ColorRangeDialog.get_hsv_ranges

    def mock_get_hsv_ranges(self):
        # Return default HSV range data that matches expected format
        try:
            # Try to call original first, but if it fails, return defaults
            return original_get_hsv_ranges(self)
        except (AttributeError, RuntimeError):
            # Return default HSV range data
            return {
                'center_hsv': (0, 1, 1),
                'h_range': (0, 1),
                's_range': (0, 1),
                'v_range': (0, 1),
                'h': 0,
                's': 1,
                'v': 1,
                'h_minus': 20 / 360,
                'h_plus': 20 / 360,
                's_minus': 0.2,
                's_plus': 0.2,
                'v_minus': 0.2,
                'v_plus': 0.2
            }

    with patch.object(ColorRangeDialog, 'exec', mock_exec), \
            patch.object(ColorRangeDialog, 'get_hsv_ranges', mock_get_hsv_ranges):
        yield
