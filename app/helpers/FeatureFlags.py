"""Release feature flags.

Central switches for features that are code-complete but held back from
the current release. UI entry points check these flags; the underlying
code stays in the tree so releasing later only means flipping the flag.
"""

# Flight Viewer (live WebRTC drone feeds, pairing with ADIAT Mobile).
# Deferred again and held back from the current production release. When
# False, the Selection dialog's Flight Viewer button (dialog resizes to the
# two remaining tiles) and the Flight Viewer menu entries in the Images and
# Streaming windows are hidden. The feature code stays in the tree; releasing
# later means flipping this back to True.
FLIGHT_VIEWER_ENABLED = False
