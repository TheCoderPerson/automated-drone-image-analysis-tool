"""Tests for helpers.WidgetHelper.retire_widget."""

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from helpers.WidgetHelper import retire_widget


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def test_retire_hides_immediately_and_leaves_layout(app, qtbot):
    """The point of the helper: hidden NOW, destroyed later.

    deleteLater alone leaves the widget visible until the event loop runs its
    deferred-delete pass, so a swap followed by long synchronous work paints
    the retired panel under its replacement.
    """
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    outgoing = QLabel("outgoing", host)
    layout.addWidget(outgoing)
    host.show()
    qtbot.waitExposed(host)
    assert not outgoing.isHidden()

    retire_widget(outgoing, layout)

    # No event-loop turn has happened yet - exactly the field condition.
    assert outgoing.isHidden()
    assert layout.indexOf(outgoing) == -1


def test_retire_without_layout_still_hides(app, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    widget = QLabel("floating", host)
    host.show()
    qtbot.waitExposed(host)

    retire_widget(widget)

    assert widget.isHidden()


def test_retire_none_is_a_noop(app):
    retire_widget(None)          # no guard needed at call sites
    retire_widget(None, None)
