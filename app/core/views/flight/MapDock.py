"""Map dock for the Flight Viewer (plan §15 M3).

Renders aircraft position, flight path, and detection locations on an
interactive map alongside the Mission Gallery. Clicking a row in the
gallery centers the map on the corresponding pin (plan §15).

The map itself now lives in
:class:`~core.views.components.FlightMapView.FlightMapView` so the
streaming window can embed the same widget without dock chrome. This
class is the ``QDockWidget`` wrapper: it owns docking behaviour and
forwards the map API unchanged, so existing Flight Viewer callers are
unaffected.

``LEAFLET_HTML``, ``DETECTOR_PALETTE`` and ``DEFAULT_PIN_COLOR`` are
re-exported here for backward compatibility with anything importing them
from this module.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QWidget

from core.views.components.FlightMapView import (
    AIRCRAFT_COLOR,
    DEFAULT_FEED_ID,
    DEFAULT_PIN_COLOR,
    DETECTOR_PALETTE,
    LEAFLET_HTML,
    FlightMapView,
)
from helpers.TranslationMixin import TranslationMixin

__all__ = [
    "AIRCRAFT_COLOR",
    "DEFAULT_FEED_ID",
    "DEFAULT_PIN_COLOR",
    "DETECTOR_PALETTE",
    "LEAFLET_HTML",
    "MapDock",
]


class MapDock(TranslationMixin, QDockWidget):
    """Dock widget showing aircraft position, path, and detection pins."""

    rowActivated = Signal(dict)
    pinClicked = Signal(str)  # track_key of the clicked pin (plan §19.4.4)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Map"))
        # ``objectName`` is required for QMainWindow.saveState() / restoreState()
        # to round-trip this dock — without it Qt logs
        # ``QMainWindow::saveState(): 'objectName' not set for QDockWidget``
        # and silently drops the dock's state from the saved layout.
        self.setObjectName("mapDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )

        self._map = FlightMapView(self)
        self._map.rowActivated.connect(self.rowActivated)
        self._map.pinClicked.connect(self.pinClicked)
        self.setWidget(self._map)

    # ------------------------------------------------------------------
    # map API — forwarded to the embedded view
    # ------------------------------------------------------------------

    @property
    def map_view(self) -> FlightMapView:
        """The embedded map, for callers needing the full widget API."""
        return self._map

    def add_detection(self, detection: dict) -> None:
        """Plot (or update) a detection's pin on the map."""
        self._map.add_detection(detection)

    def focus_detection(self, detection: dict) -> None:
        """Center the map (or scroll the list) on a single detection."""
        self._map.focus_detection(detection)

    def update_aircraft(
        self,
        envelope: dict,
        *,
        feed_id: str = DEFAULT_FEED_ID,
        label: Optional[str] = None,
        extend_track: bool = True,
    ) -> bool:
        """Move an aircraft marker and extend its flight path."""
        return self._map.update_aircraft(
            envelope, feed_id=feed_id, label=label, extend_track=extend_track
        )

    def set_track(
        self,
        points: Sequence[Tuple[float, float]],
        *,
        feed_id: str = DEFAULT_FEED_ID,
    ) -> None:
        """Replace one feed's flight path."""
        self._map.set_track(points, feed_id=feed_id)

    def clear_track(self, feed_id: Optional[str] = None) -> None:
        """Erase one feed's flight path, or all of them."""
        self._map.clear_track(feed_id)

    def clear_aircraft(self, feed_id: Optional[str] = None) -> None:
        """Remove one aircraft marker, or all of them."""
        self._map.clear_aircraft(feed_id)

    def set_follow(self, enabled: bool) -> None:
        """Whether the map re-centres as the aircraft moves."""
        self._map.set_follow(enabled)

    def track_length(self, feed_id: str = DEFAULT_FEED_ID) -> int:
        """Fixes currently plotted in ``feed_id``'s flight path."""
        return self._map.track_length(feed_id)

    def clear(self) -> None:
        """Remove detection pins (aircraft and tracks are left alone)."""
        self._map.clear()

    def reset(self) -> None:
        """Clear detections, aircraft, and tracks."""
        self._map.reset()

    @property
    def detection_count(self) -> int:
        return self._map.detection_count

    @property
    def is_interactive(self) -> bool:
        """``True`` when the dock is using the Leaflet view."""
        return self._map.is_interactive
