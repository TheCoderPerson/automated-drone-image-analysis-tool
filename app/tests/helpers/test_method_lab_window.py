"""Smoke test for the Method Test Lab window (dev tool).

Builds the window, loads a synthetic image, runs an in-process method,
and exercises the overlay refresh — without touching the production
algorithm services (those need models/large inputs and are covered by
their own suites).
"""

import os
import sys

import cv2
import numpy as np

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts')
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def test_lab_window_runs_in_process_method(app, qtbot, tmp_path):
    from method_lab.lab_window import MethodLabWindow

    image_path = tmp_path / "synthetic.png"
    img = np.full((200, 200, 3), 120, np.uint8)
    img[80:120, 80:120] = 220
    cv2.imwrite(str(image_path), img)

    window = MethodLabWindow(str(image_path))
    qtbot.addWidget(window)

    assert window.img_bgr is not None
    assert window.img_bgr.shape == (200, 200, 3)

    # Edge/Texture is a pure in-process method (no ONNX/model needed).
    window.run_method('Edge/Texture')
    result = window.results['Edge/Texture']
    assert result.error is None
    assert result.score_map is not None

    # Toggling the heatmap and the show checkbox must not raise.
    window.result_rows['Edge/Texture']['heat'].setChecked(True)
    window._refresh_display()
    window.result_rows['Edge/Texture']['show'].setChecked(False)
    window._refresh_display()
