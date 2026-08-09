"""WidgetHelper - shared widget lifecycle utilities.

Collects the small Qt lifecycle details that are easy to get wrong the same
way in several places.
"""


def retire_widget(widget, layout=None):
    """Remove *widget* from view and queue its destruction.

    ``deleteLater`` only *queues* destruction: until the event loop next runs
    its deferred-delete pass, the widget is still a visible child painted at
    its old geometry. Code that swaps a panel and then does long synchronous
    work - constructing the replacement, loading a model, opening a result set
    - keeps the event loop busy, and ``QApplication.processEvents()`` does not
    flush deferred deletes. The retired panel therefore stays on screen,
    stacked under its replacement (field report: an outgoing algorithm
    parameter panel visible beneath the incoming one).

    Hiding first makes the removal immediate and leaves the destruction
    deferred, which is what callers actually want.

    Args:
        widget: The widget to retire. ``None`` is accepted and ignored so
            callers need no separate guard.
        layout: Optional layout to remove *widget* from first.
    """
    if widget is None:
        return
    if layout is not None:
        layout.removeWidget(widget)
    widget.hide()
    widget.deleteLater()
