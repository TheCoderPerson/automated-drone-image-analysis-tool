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
FLIGHT_VIEWER_ENABLED = False
