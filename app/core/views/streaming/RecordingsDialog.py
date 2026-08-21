"""Picker for the recording library — choose a recording, replay it.

Lists what :class:`~core.services.streaming.RecordingLibrary.\
RecordingLibrary` knows, newest first, each row named the way an operator
recognizes a flight: feed label, start time, detection count. Double-click
(or Replay) accepts with :attr:`selected_video` set; Browse… covers
recordings this machine never made (a bundle copied from another laptop).
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QListWidgetItem

from core.views.streaming.RecordingsDialog_ui import Ui_RecordingsDialog
from helpers.TranslationMixin import TranslationMixin


class RecordingsDialog(TranslationMixin, QDialog):
    """Modal list of known recordings; resolves to one video path."""

    def __init__(self, entries: List[dict], parent=None):
        super().__init__(parent)
        self.ui = Ui_RecordingsDialog()
        self.ui.setupUi(self)
        self._apply_translations()

        #: Absolute path of the chosen recording's video, set on accept.
        self.selected_video: Optional[str] = None

        playable = [e for e in entries if e.get("video")]
        for entry in playable:
            label = self.tr("{title} — {when} · {count} detections").format(
                title=entry.get("title") or self.tr("Recording"),
                when=str(entry.get("started_at") or "").replace("T", " "),
                count=entry.get("detections", 0),
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry["video"])
            item.setToolTip(entry.get("bundle_dir") or "")
            self.ui.recordingList.addItem(item)

        self.ui.emptyLabel.setVisible(not playable)
        self.ui.recordingList.setVisible(bool(playable))

        self.ui.recordingList.itemSelectionChanged.connect(self._on_selection_changed)
        self.ui.recordingList.itemDoubleClicked.connect(self._on_item_activated)
        self.ui.openButton.clicked.connect(self._on_open_clicked)
        self.ui.browseButton.clicked.connect(self._on_browse_clicked)
        self.ui.cancelButton.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # interaction
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self.ui.openButton.setEnabled(bool(self.ui.recordingList.selectedItems()))

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self._accept_video(item.data(Qt.UserRole))

    def _on_open_clicked(self) -> None:
        items = self.ui.recordingList.selectedItems()
        if items:
            self._accept_video(items[0].data(Qt.UserRole))

    def _on_browse_clicked(self) -> None:
        """Pick a recording video directly — bundles from other machines."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Open recording video"),
            os.path.expanduser("~"),
            self.tr("Videos (*.mp4)"),
        )
        if path:
            self._accept_video(path)

    def _accept_video(self, video) -> None:
        if not video:
            return
        self.selected_video = str(video)
        self.accept()


__all__ = ["RecordingsDialog"]
