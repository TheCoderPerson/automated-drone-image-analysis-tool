"""Unit tests for PathValidationController."""

import os
import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QMessageBox

from core.controllers.images.viewer.path.PathValidationController import (
    PathValidationController,
)


@pytest.fixture
def controller():
    return PathValidationController(MagicMock())


def test_validate_no_missing_paths(controller, tmp_path):
    # Create real files
    img_path = tmp_path / "real.jpg"
    img_path.write_text("fake")
    images = [{"path": str(img_path), "mask_path": ""}]
    result = controller.validate_and_fix_paths(images)
    assert result is True


def test_validate_empty_paths_treated_as_valid(controller):
    images = [{"path": "", "mask_path": ""}]
    result = controller.validate_and_fix_paths(images)
    assert result is True


def test_validate_missing_image_prompts_user(controller):
    images = [{"path": "/nonexistent/a.jpg", "mask_path": ""}]
    with patch.object(controller, "_prompt_for_source_folder", return_value=True):
        result = controller.validate_and_fix_paths(images)
    assert result is True


def test_validate_missing_mask_prompts_user(controller, tmp_path):
    img_path = tmp_path / "real.jpg"
    img_path.write_text("fake")
    images = [{"path": str(img_path), "mask_path": "/nonexistent/m.png"}]
    with patch.object(controller, "_prompt_for_mask_folder", return_value=True):
        result = controller.validate_and_fix_paths(images)
    assert result is True


def test_validate_cancelled_source_returns_false(controller):
    images = [{"path": "/nonexistent/a.jpg", "mask_path": ""}]
    with patch.object(controller, "_prompt_for_source_folder", return_value=False):
        result = controller.validate_and_fix_paths(images)
    assert result is False


def test_validate_cancelled_mask_returns_false(controller, tmp_path):
    img_path = tmp_path / "real.jpg"
    img_path.write_text("fake")
    images = [{"path": str(img_path), "mask_path": "/nonexistent/m.png"}]
    with patch.object(controller, "_prompt_for_mask_folder", return_value=False):
        result = controller.validate_and_fix_paths(images)
    assert result is False


def test_prompt_source_folder_user_cancels_at_info(controller):
    missing = [{"image": {"path": "a.jpg"}, "filename": "a.jpg"}]
    with patch(
        "core.controllers.images.viewer.path.PathValidationController.QMessageBox"
    ) as MockMsgBox:
        # Simulate user clicking Cancel on info
        mock_box = MagicMock()
        mock_box.exec.return_value = QMessageBox.Cancel
        MockMsgBox.return_value = mock_box
        MockMsgBox.Cancel = QMessageBox.Cancel
        MockMsgBox.Ok = QMessageBox.Ok
        MockMsgBox.Information = QMessageBox.Information
        result = controller._prompt_for_source_folder(missing)
    assert result is False


def test_prompt_source_folder_user_cancels_at_folder_select(controller):
    missing = [{"image": {"path": "a.jpg"}, "filename": "a.jpg"}]
    with patch(
        "core.controllers.images.viewer.path.PathValidationController.QMessageBox"
    ) as MockMsgBox, patch(
        "core.controllers.images.viewer.path.PathValidationController.QFileDialog"
    ) as MockFileDialog:
        mock_box = MagicMock()
        mock_box.exec.return_value = QMessageBox.Ok
        MockMsgBox.return_value = mock_box
        MockMsgBox.Ok = QMessageBox.Ok
        MockMsgBox.Information = QMessageBox.Information
        MockFileDialog.getExistingDirectory.return_value = ""  # cancelled

        result = controller._prompt_for_source_folder(missing)
    assert result is False


def test_prompt_long_list_truncates_message(controller):
    # >10 missing files triggers the "and N more" suffix
    missing = [
        {"image": {"path": f"img{i}.jpg"}, "filename": f"img{i}.jpg"}
        for i in range(15)
    ]
    with patch(
        "core.controllers.images.viewer.path.PathValidationController.QMessageBox"
    ) as MockMsgBox:
        mock_box = MagicMock()
        mock_box.exec.return_value = QMessageBox.Cancel
        MockMsgBox.return_value = mock_box
        MockMsgBox.Cancel = QMessageBox.Cancel
        MockMsgBox.Ok = QMessageBox.Ok
        MockMsgBox.Information = QMessageBox.Information
        controller._prompt_for_source_folder(missing)
    # Check that setText was called with message including "... and"
    call_args = mock_box.setText.call_args
    message = call_args[0][0]
    assert "5 more" in message or "... and" in message


# --------------------------------------------------------------------------- #
#  Path recovery: choosing a correct folder must actually recover the images.  #
#                                                                             #
#  Reported bug: after picking the right folder, the load still reported the   #
#  images as missing. Root cause was os.path.basename() on a Windows-authored  #
#  stored path -- on POSIX it does not split backslashes, so the derived       #
#  "filename" was the entire path and could never be found in any folder.      #
#  That made the failure macOS/Linux-only; ntpath.basename splits both.        #
# --------------------------------------------------------------------------- #

_MODULE = "core.controllers.images.viewer.path.PathValidationController"


def _mock_msgbox(MockMsgBox, info_result=QMessageBox.Ok, buttons=None, clicked_index=None):
    """Wire up a mocked QMessageBox class.

    Args:
        info_result: What the initial "not found" confirmation returns.
        buttons: Sentinels returned by successive addButton() calls.
        clicked_index: Index into *buttons* that clickedButton() reports.
    """
    mock_box = MagicMock()
    mock_box.exec.return_value = info_result
    MockMsgBox.return_value = mock_box
    for name in ("Ok", "Cancel", "Information", "Warning",
                 "AcceptRole", "DestructiveRole"):
        setattr(MockMsgBox, name, getattr(QMessageBox, name))
    if buttons is not None:
        mock_box.addButton.side_effect = list(buttons)
        mock_box.clickedButton.return_value = (
            buttons[clicked_index] if clicked_index is not None else None
        )
    return mock_box


def test_windows_authored_path_recovers_from_chosen_folder(controller, tmp_path):
    """The headline regression: a Windows-written path, recovered on POSIX."""
    (tmp_path / "DJI_0042.JPG").write_text("x")
    image = {"path": r"C:\Users\pilot\Flight1\DJI_0042.JPG", "mask_path": ""}

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([image]) is True

    assert image["path"] == str(tmp_path / "DJI_0042.JPG")


def test_recovery_finds_images_in_subfolders(controller, tmp_path):
    """Drone media is normally nested; the old flat join never looked deeper."""
    nested = tmp_path / "DCIM" / "100MEDIA"
    nested.mkdir(parents=True)
    (nested / "DJI_0007.JPG").write_text("x")
    image = {"path": "/old/place/DJI_0007.JPG", "mask_path": ""}

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([image]) is True

    assert image["path"] == str(nested / "DJI_0007.JPG")


def test_recovery_matches_extension_case_difference(controller, tmp_path):
    (tmp_path / "DJI_0009.jpg").write_text("x")
    image = {"path": "/old/DJI_0009.JPG", "mask_path": ""}

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([image]) is True

    assert image["path"] == str(tmp_path / "DJI_0009.jpg")


def test_partial_recovery_continue_anyway_loads(controller, tmp_path):
    """One deleted capture must not cost the whole review."""
    (tmp_path / "a.jpg").write_text("x")
    found = {"path": "/old/a.jpg", "mask_path": ""}
    lost = {"path": "/old/gone.jpg", "mask_path": ""}
    retry, cont, cancel = MagicMock(name="retry"), MagicMock(name="cont"), MagicMock(name="cancel")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox, buttons=[retry, cont, cancel], clicked_index=1)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([found, lost]) is True

    assert found["path"] == str(tmp_path / "a.jpg"), "found file must still be repaired"
    assert lost["path"] == "/old/gone.jpg", "unresolved file is left alone"


def test_partial_recovery_cancel_aborts_load(controller, tmp_path):
    (tmp_path / "a.jpg").write_text("x")
    images = [{"path": "/old/a.jpg", "mask_path": ""},
              {"path": "/old/gone.jpg", "mask_path": ""}]
    retry, cont, cancel = MagicMock(name="retry"), MagicMock(name="cont"), MagicMock(name="cancel")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox, buttons=[retry, cont, cancel], clicked_index=2)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths(images) is False


def test_dismissing_partial_dialog_does_not_silently_continue(controller, tmp_path):
    """clickedButton() can be None on Esc; that must not read as "continue"."""
    (tmp_path / "a.jpg").write_text("x")
    images = [{"path": "/old/a.jpg", "mask_path": ""},
              {"path": "/old/gone.jpg", "mask_path": ""}]
    retry, cont, cancel = MagicMock(name="retry"), MagicMock(name="cont"), MagicMock(name="cancel")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox, buttons=[retry, cont, cancel], clicked_index=None)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths(images) is False


def test_recovery_can_retry_with_a_different_folder(controller, tmp_path):
    """Picking the wrong folder first must not end the load."""
    wrong = tmp_path / "wrong"
    right = tmp_path / "right"
    wrong.mkdir()
    right.mkdir()
    (right / "a.jpg").write_text("x")
    image = {"path": "/old/a.jpg", "mask_path": ""}
    retry, cancel = MagicMock(name="retry"), MagicMock(name="cancel")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        # No file found in `wrong`, so no "Continue Anyway" button is offered:
        # addButton is called twice (retry, cancel). User clicks retry.
        _mock_msgbox(MockMsgBox, buttons=[retry, cancel], clicked_index=0)
        MockFileDialog.getExistingDirectory.side_effect = [str(wrong), str(right)]
        assert controller.validate_and_fix_paths([image]) is True

    assert image["path"] == str(right / "a.jpg")
    assert MockFileDialog.getExistingDirectory.call_count == 2


def test_recovery_persists_paths_and_updates_input_dir(controller, tmp_path):
    """Without persistence the same folder is re-requested on every open."""
    import xml.etree.ElementTree as ET
    (tmp_path / "a.jpg").write_text("x")
    element = ET.Element("image", {"path": r"C:\old\a.jpg"})
    image = {"path": r"C:\old\a.jpg", "mask_path": "", "xml": element}

    controller.parent.settings = {"input_dir": r"C:\old"}
    controller.parent.xml_path = str(tmp_path / "ADIAT_Data.xml")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([image]) is True

    assert element.get("path") == str(tmp_path / "a.jpg"), "repair must reach the XML"
    assert controller.parent.settings["input_dir"] == str(tmp_path)
    controller.parent.xml_service.save_xml_file.assert_called_once_with(
        str(tmp_path / "ADIAT_Data.xml")
    )


def test_unwritable_result_file_does_not_fail_the_load(controller, tmp_path):
    """A result file on read-only media still loads with an in-memory repair."""
    (tmp_path / "a.jpg").write_text("x")
    image = {"path": "/old/a.jpg", "mask_path": ""}
    controller.parent.xml_path = str(tmp_path / "ADIAT_Data.xml")
    controller.parent.xml_service.save_xml_file.side_effect = OSError("read-only")

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(tmp_path)
        assert controller.validate_and_fix_paths([image]) is True

    assert image["path"] == str(tmp_path / "a.jpg")


def test_mask_recovery_repairs_mask_path_only(controller, tmp_path):
    """Masks recover through the same matcher but must not touch 'path'."""
    img = tmp_path / "a.jpg"
    img.write_text("x")
    masks = tmp_path / "masks"
    masks.mkdir()
    (masks / "a_mask.tif").write_text("x")
    image = {"path": str(img), "mask_path": r"C:\old\results\a_mask.tif"}
    controller.parent.settings = {"input_dir": r"C:\old"}

    with patch(f"{_MODULE}.QMessageBox") as MockMsgBox, \
            patch(f"{_MODULE}.QFileDialog") as MockFileDialog:
        _mock_msgbox(MockMsgBox)
        MockFileDialog.getExistingDirectory.return_value = str(masks)
        assert controller.validate_and_fix_paths([image]) is True

    assert image["mask_path"] == str(masks / "a_mask.tif")
    assert image["path"] == str(img), "image path must be untouched"
    assert controller.parent.settings["input_dir"] == r"C:\old", \
        "mask recovery must not repoint the source image folder"
