"""Release feature flags.

Central switches for features that are code-complete but held back from
the current release. UI entry points check these flags; the underlying
code stays in the tree so releasing later only means flipping the flag.
"""

# Flight Viewer (live WebRTC drone feeds, pairing with ADIAT Mobile).
# Held back from the current release build. When False, the Selection
# dialog's Flight Viewer button and the Flight Viewer menu entries in the
# Images and Streaming windows are hidden. The implementation stays in the
# tree, so releasing later is just flipping this back to True (and the
# matching assertion in
# app/tests/core/controllers/test_selection_dialog_controller.py).
#
# This also gates ADIAT Flight as a *streaming source*: it pairs over the
# same WebRTC/signaling stack, so the two ship together. Split this into a
# second flag if the streaming source ever needs to release on its own.
FLIGHT_VIEWER_ENABLED = True

# Review Results (open a completed analysis straight into review, bypassing
# the analysis setup screen). Held back from the current release build. When
# False, the Selection dialog's Review Results tile is hidden and its click
# handler is left unconnected, so the entry point is unreachable. The tile
# stays in resources/views/SelectionDialog.ui and the handler, signal and
# MainWindow.open_results_for_review() stay in the tree, so releasing later
# is just flipping this back to True (and the matching assertion in
# app/tests/core/controllers/test_selection_dialog_controller.py).
# Note: File > Open Recent Results in the Images window is NOT gated by this
# flag - it is a convenience over the pre-existing Load File flow.
REVIEW_RESULTS_ENABLED = False
