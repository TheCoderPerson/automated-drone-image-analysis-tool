"""Tests for ResultsLoadingDialog stepping aside for prompts.

The heartbeat is always-on-top, so any prompt raised while a results file
opens (missing images, folder picker, custom AGL, bearing recovery, ...)
used to open behind it, and the operator could not see the dialog waiting
for them. The heartbeat now hides itself while any other dialog the app
opens is up, and comes back when they have all closed.
"""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLabel, QMessageBox, QWidget
from shiboken6 import delete as qt_delete

from core.views.images.viewer.dialogs.ResultsLoadingDialog import ResultsLoadingDialog


@pytest.fixture
def heartbeat(qtbot):
    dialog = ResultsLoadingDialog(parent=None)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.isVisible()
    yield dialog
    dialog.close()


def _prompt(qtbot, cls=QMessageBox):
    prompt = cls()
    qtbot.addWidget(prompt)
    return prompt


def test_heartbeat_hides_while_message_box_is_open(heartbeat, qtbot):
    prompt = _prompt(qtbot)

    prompt.show()
    assert not heartbeat.isVisible()
    assert prompt.isVisible()

    prompt.hide()
    assert heartbeat.isVisible()


def test_modal_prompt_is_unobstructed_inside_its_exec_loop(heartbeat):
    """The real flows block in exec(); the heartbeat must be gone while they do."""
    seen = {}

    def inspect_and_close():
        prompt = QApplication.activeModalWidget()
        seen['prompt_visible'] = prompt.isVisible()
        seen['heartbeat_visible'] = heartbeat.isVisible()
        prompt.reject()

    QTimer.singleShot(0, inspect_and_close)
    # The custom AGL prompt uses exactly this static call
    QInputDialog.getDouble(None, "Custom AGL", "Altitude:", 100.0, 0.1, 10000.0, 1)

    assert seen == {'prompt_visible': True, 'heartbeat_visible': False}
    assert heartbeat.isVisible()


def test_heartbeat_waits_for_every_open_prompt(heartbeat, qtbot):
    """A prompt opened from another prompt: back only when both have closed."""
    first = _prompt(qtbot)
    second = _prompt(qtbot, QInputDialog)
    first.show()
    second.show()

    first.hide()
    assert not heartbeat.isVisible()

    second.hide()
    assert heartbeat.isVisible()


def test_caller_hide_is_respected_after_prompt_closes(heartbeat, qtbot):
    """The viewer hides the heartbeat itself around the WALDO pre-pass."""
    heartbeat.hide()
    prompt = _prompt(qtbot)
    prompt.show()
    prompt.hide()

    assert not heartbeat.isVisible()

    heartbeat.show()
    assert heartbeat.isVisible()


def test_caller_show_waits_while_prompt_is_open(heartbeat, qtbot):
    """The existing per-prompt workarounds call show() once their own prompt
    returns; that must not put the heartbeat over a prompt still open."""
    prompt = _prompt(qtbot)
    prompt.show()

    heartbeat.show()
    assert not heartbeat.isVisible()

    prompt.hide()
    assert heartbeat.isVisible()


def test_tooltips_and_child_widgets_do_not_hide_heartbeat(heartbeat, qtbot):
    tooltip = QWidget(None, Qt.ToolTip)
    qtbot.addWidget(tooltip)
    tooltip.show()
    assert heartbeat.isVisible()

    host = QDialog()
    qtbot.addWidget(host)
    child = QLabel("child", host)
    child.hide()
    child.show()  # a widget inside an already-open window, not a new window
    assert heartbeat.isVisible()


def test_deleted_prompt_does_not_keep_heartbeat_hidden(heartbeat):
    prompt = QMessageBox()
    prompt.show()
    assert not heartbeat.isVisible()

    qt_delete(prompt)

    assert heartbeat.isVisible()


def test_closed_heartbeat_never_comes_back(heartbeat, qtbot):
    """After the viewer closes it, later prompts must not resurrect it."""
    prompt = _prompt(qtbot)
    prompt.show()
    heartbeat.close()
    prompt.hide()
    assert not heartbeat.isVisible()

    another = _prompt(qtbot)
    another.show()
    another.hide()
    assert not heartbeat.isVisible()
