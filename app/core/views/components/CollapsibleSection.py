"""A titled panel whose contents can be collapsed away.

The streaming window's right-hand column stacks several control groups
plus a map. On a laptop screen they do not all fit at once, and which
ones matter depends on what the operator is doing — during setup it is
Stream Controls, while flying it is the map and the algorithm. Letting
sections fold down keeps the useful one on screen without forcing a
scroll.

Behaves like a ``QGroupBox`` with a clickable title: the header toggles,
the body hides, and the collapsed state is reported so callers can
persist it.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """A section with a toggling header and a hideable body."""

    collapsedChanged = Signal(bool)  # True when collapsed

    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._toggle = QToolButton(self)
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)          # expanded
        self._toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.DownArrow)
        self._toggle.setAutoRaise(True)
        self._toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._toggle.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 2px; }"
        )
        self._toggle.toggled.connect(self._on_toggled)

        self._content = QFrame(self)
        self._content.setObjectName("collapsibleContent")
        self._content.setFrameShape(QFrame.StyledPanel)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(6, 6, 6, 6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

    # ------------------------------------------------------------------
    # content
    # ------------------------------------------------------------------

    @property
    def content_layout(self) -> QVBoxLayout:
        """Layout callers add their widgets to."""
        return self._content_layout

    @property
    def content_widget(self) -> QFrame:
        return self._content

    def addWidget(self, widget: QWidget) -> None:
        """Convenience passthrough to the content layout."""
        self._content_layout.addWidget(widget)

    # ------------------------------------------------------------------
    # collapsing
    # ------------------------------------------------------------------

    def setTitle(self, title: str) -> None:
        self._toggle.setText(title)

    def title(self) -> str:
        return self._toggle.text()

    def isCollapsed(self) -> bool:
        return not self._toggle.isChecked()

    def setCollapsed(self, collapsed: bool) -> None:
        """Collapse or expand without emitting a redundant signal."""
        if bool(collapsed) == self.isCollapsed():
            return
        self._toggle.setChecked(not bool(collapsed))

    def _on_toggled(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        self._toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        # A collapsed section must not keep reserving its body's height,
        # or folding it away would free no space at all.
        self.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Preferred if expanded else QSizePolicy.Fixed,
        )
        self.collapsedChanged.emit(not expanded)
