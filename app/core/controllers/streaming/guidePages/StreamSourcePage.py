"""Stream source selection page for the streaming setup wizard."""

from PySide6.QtWidgets import QButtonGroup

from .BasePage import BasePage
from core.services.streaming.RTMPStreamService import (
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_HDMI,
    SOURCE_TYPE_RTMP,
)
from helpers.IconHelper import IconHelper


class StreamSourcePage(BasePage):
    """Page for selecting video source type."""

    def setup_ui(self) -> None:
        # Apply icons if available (non-critical)
        try:
            self.dialog.fileButton.setIcon(IconHelper.create_icon("fa6s.folder-open", "Dark"))
            self.dialog.hdmiButton.setIcon(IconHelper.create_icon("fa6s.video", "Dark"))
            self.dialog.rtmpButton.setIcon(IconHelper.create_icon("fa6s.wifi", "Dark"))
            self.dialog.flightButton.setIcon(
                IconHelper.create_icon("fa6s.satellite-dish", "Dark")
            )
        except Exception:
            pass

        # Make buttons mutually exclusive
        self.button_group = QButtonGroup(self.dialog)
        self.button_group.setExclusive(True)
        for btn in self._source_buttons().values():
            btn.setCheckable(True)
            self.button_group.addButton(btn)
        self.dialog.fileButton.setChecked(True)

    def connect_signals(self) -> None:
        for source_type, btn in self._source_buttons().items():
            btn.clicked.connect(
                lambda _checked=False, value=source_type: self._on_stream_type_changed(value)
            )

    def load_data(self) -> None:
        stream_type = self.wizard_data.get("stream_type") or self.settings_service.get_setting(
            "StreamingSourceType", SOURCE_TYPE_FILE
        )

        self._set_stream_type(stream_type)

        # Initialize wizard data
        self.wizard_data["stream_type"] = self._current_stream_type()

    def validate(self) -> bool:
        return True

    def save_data(self) -> None:
        self.wizard_data["stream_type"] = self._current_stream_type()

    def _source_buttons(self) -> dict:
        """Map canonical source label -> its selection button.

        Keys are the stable, non-localized labels persisted in wizard data
        and settings; the buttons' visible text comes from the ``.ui`` and
        may be translated (CLAUDE.md §2.8).
        """
        return {
            SOURCE_TYPE_FILE: self.dialog.fileButton,
            SOURCE_TYPE_HDMI: self.dialog.hdmiButton,
            SOURCE_TYPE_RTMP: self.dialog.rtmpButton,
            SOURCE_TYPE_ADIAT_FLIGHT: self.dialog.flightButton,
        }

    def _on_stream_type_changed(self, stream_type: str) -> None:
        self.wizard_data["stream_type"] = stream_type
        if hasattr(self, "on_validation_changed"):
            self.on_validation_changed()

    def _current_stream_type(self) -> str:
        for source_type, btn in self._source_buttons().items():
            if btn.isChecked():
                return source_type
        return SOURCE_TYPE_FILE

    def _set_stream_type(self, stream_type: str) -> None:
        button = self._source_buttons().get(stream_type)
        if button is None:
            button = self.dialog.fileButton
        button.setChecked(True)
