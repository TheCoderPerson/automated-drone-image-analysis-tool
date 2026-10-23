"""Previous/Next and the first image skip redundant images (Viewer._is_image_skipped)."""

from unittest.mock import MagicMock

from core.controllers.images.viewer.Viewer import Viewer


def _viewer(hidden=(), redundant=(), current=0, count=5, show_hidden=False):
    viewer = MagicMock()
    viewer.images = [{'hidden': i in hidden} for i in range(count)]
    viewer.show_hidden = show_hidden
    viewer.current_image = current
    viewer.redundant_image_controller.is_skipped.side_effect = lambda i: i in redundant
    viewer._is_image_skipped = lambda i: Viewer._is_image_skipped(viewer, i)
    return viewer


def test_next_steps_over_redundant_and_hidden_images():
    viewer = _viewer(hidden={1}, redundant={2})
    Viewer._nextImageButton_clicked(viewer)
    assert viewer.current_image == 3
    viewer._load_image.assert_called_once()


def test_previous_steps_over_redundant_images():
    viewer = _viewer(redundant={2, 3}, current=4)
    Viewer._previousImageButton_clicked(viewer)
    assert viewer.current_image == 1


def test_next_wraps_past_redundant_images():
    viewer = _viewer(redundant={0}, current=4)
    Viewer._nextImageButton_clicked(viewer)
    assert viewer.current_image == 1


def test_hidden_images_are_not_skipped_when_skip_hidden_is_off():
    viewer = _viewer(hidden={1}, show_hidden=True)
    assert not Viewer._is_image_skipped(viewer, 1)


def test_viewer_without_the_controller_skips_only_hidden_images():
    viewer = _viewer(hidden={1})
    del viewer.redundant_image_controller
    viewer.redundant_image_controller = None
    assert Viewer._is_image_skipped(viewer, 1)
    assert not Viewer._is_image_skipped(viewer, 2)


def test_everything_skipped_reports_no_more_images():
    viewer = _viewer(redundant={1, 2, 3, 4}, current=0)
    Viewer._nextImageButton_clicked(viewer)
    assert viewer.current_image == 0
    viewer._show_additional_images_message.assert_called_once()
