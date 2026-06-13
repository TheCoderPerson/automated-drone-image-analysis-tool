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


def test_lab_window_folder_navigation(app, qtbot, tmp_path):
    from method_lab.lab_window import MethodLabWindow

    # Three images with distinct sizes so we can tell which one is loaded.
    sizes = [(100, 120), (140, 160), (180, 200)]
    paths = []
    for i, (h, w) in enumerate(sizes):
        p = tmp_path / f"img_{i}.png"
        cv2.imwrite(str(p), np.full((h, w, 3), 100 + (i * 30), np.uint8))
        paths.append(p)

    # Opening one file syncs the folder list to all three siblings.
    window = MethodLabWindow(str(paths[0]))
    qtbot.addWidget(window)
    assert len(window.folder_images) == 3
    assert window.folder_index == 0
    assert window.img_bgr.shape[:2] == sizes[0]
    assert window.position_label.text() == "1 / 3"
    assert not window.prev_button.isEnabled()
    assert window.next_button.isEnabled()

    # Next advances; the loaded image and label track the index.
    window._navigate(1)
    assert window.folder_index == 1
    assert window.img_bgr.shape[:2] == sizes[1]
    assert window.position_label.text() == "2 / 3"
    assert window.prev_button.isEnabled()

    # Navigation clamps at the last image.
    window._navigate(1)
    assert window.folder_index == 2
    assert window.next_button.isEnabled() is False
    window._navigate(1)
    assert window.folder_index == 2

    # Prev walks back.
    window._navigate(-1)
    assert window.folder_index == 1
    assert window.img_bgr.shape[:2] == sizes[1]
