"""UI-surface tests for the secondary metadata file (SRT / CSV).

Requirement coverage: streaming analysis must accept an operator-selected
metadata file supplying location data, the way the image-analysis Video
Parser always has — and it must be reachable from *both* places a source
is configured: the streaming window's controls and the setup guide.

The load-bearing invariant beyond "the field exists" is that the path
cannot leak onto a source that can't use it. A live feed carries telemetry
in-band or not at all, so a path left behind by a previous File selection
would send the resolver looking for a track that cannot exist.
"""

from __future__ import annotations

import os
import sys

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.controllers.streaming.guidePages import StreamConnectionPage  # noqa: E402
from core.controllers.streaming.StreamingGuide import StreamingGuide  # noqa: E402
from core.controllers.streaming.shared_widgets import StreamControlWidget  # noqa: E402
from core.services.streaming.RTMPStreamService import (  # noqa: E402
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_HDMI,
    SOURCE_TYPE_RTMP,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def controls(qtbot):
    widget = StreamControlWidget(include_recording=False)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def guide(qtbot):
    dialog = StreamingGuide()
    qtbot.addWidget(dialog)
    return dialog


def _select_source(widget, source_type: str) -> None:
    index = widget.type_combo.findData(source_type)
    assert index >= 0, f"{source_type} missing from the stream type combo"
    widget.type_combo.setCurrentIndex(index)


# ----------------------------------------------------------------------
# Streaming window — StreamControlWidget
# ----------------------------------------------------------------------


class TestStreamControls:
    def test_row_is_present_for_the_default_file_source(self, controls):
        assert not controls.metadata_label.isHidden()
        assert not controls.metadata_input.isHidden()
        assert not controls.metadata_browse_button.isHidden()

    @pytest.mark.parametrize("source_type", [
        SOURCE_TYPE_HDMI, SOURCE_TYPE_RTMP, SOURCE_TYPE_ADIAT_FLIGHT,
    ])
    def test_row_is_hidden_for_live_sources(self, controls, source_type):
        _select_source(controls, source_type)
        assert controls.metadata_input.isHidden()
        assert controls.metadata_label.isHidden()
        assert controls.metadata_browse_button.isHidden()

    def test_row_returns_when_file_is_reselected(self, controls):
        _select_source(controls, SOURCE_TYPE_RTMP)
        _select_source(controls, SOURCE_TYPE_FILE)
        assert not controls.metadata_input.isHidden()

    def test_path_is_reported_for_a_file_source(self, controls):
        controls.set_metadata_path("C:/logs/flight.csv")
        assert controls.get_metadata_path() == "C:/logs/flight.csv"

    def test_whitespace_is_trimmed(self, controls):
        controls.set_metadata_path("  C:/logs/flight.srt  ")
        assert controls.get_metadata_path() == "C:/logs/flight.srt"

    def test_empty_by_default(self, controls):
        assert controls.get_metadata_path() == ""

    def test_switching_away_clears_the_field(self, controls):
        """Otherwise File -> RTMP -> File silently re-applies a metadata file
        the operator can no longer see."""
        controls.set_metadata_path("C:/logs/flight.csv")
        _select_source(controls, SOURCE_TYPE_RTMP)
        assert controls.metadata_input.text() == ""

    def test_live_sources_report_no_path(self, controls):
        controls.set_metadata_path("C:/logs/flight.csv")
        _select_source(controls, SOURCE_TYPE_ADIAT_FLIGHT)
        assert controls.get_metadata_path() == ""

    def test_disabled_while_connected(self, controls):
        controls.update_connection_status(True, "Connected")
        assert not controls.metadata_input.isEnabled()
        assert not controls.metadata_browse_button.isEnabled()

    def test_re_enabled_after_disconnect(self, controls):
        controls.update_connection_status(True, "Connected")
        controls.update_connection_status(False, "Disconnected")
        assert controls.metadata_input.isEnabled()
        assert controls.metadata_browse_button.isEnabled()

    def test_both_formats_are_offered(self, controls):
        tooltip = controls.metadata_input.toolTip()
        assert ".SRT" in tooltip
        assert ".CSV" in tooltip.upper()

    def test_field_makes_clear_it_is_optional(self, controls):
        """Auto-detection covers the common case; the field is an override."""
        assert "optional" in controls.metadata_input.placeholderText().lower()
        assert "optional" in controls.metadata_label.text().lower()


class TestWordingIsConsistentAcrossSurfaces:
    """The same field appears on three surfaces, so all three must say the
    same thing about it — above all that it is usually unnecessary.

    Operators reasonably assume a field means "fill me in". ADIAT finds a
    sidecar or an embedded track by itself, so the note that it isn't needed
    is the whole point of the wording, and it has to be identical whichever
    screen they happen to be on.
    """

    @pytest.fixture
    def image_ui(self, qtbot):
        """The image-analysis Video Parser, built straight from its .ui.

        A fixture rather than a helper so the owning dialog stays referenced —
        returning only the Ui object lets the dialog be collected and its
        children destroyed underneath it.
        """
        from PySide6.QtWidgets import QDialog
        from core.views.images.VideoParser_ui import Ui_VideoParser

        dialog = QDialog()
        qtbot.addWidget(dialog)
        ui = Ui_VideoParser()
        ui.setupUi(dialog)
        yield ui

    def test_all_three_share_one_field_tooltip(self, controls, guide, image_ui):
        """Compared against each other rather than a shared constant: the
        strings must stay literals for tr() extraction to see them, so
        equality between surfaces *is* the invariant."""
        tooltips = {
            "streaming window": controls.metadata_input.toolTip(),
            "streaming wizard": guide.metadataFileLineEdit.toolTip(),
            "video parser": image_ui.srtSelectLine.toolTip(),
        }
        assert len(set(tooltips.values())) == 1, (
            "field tooltips have drifted apart: "
            + "; ".join(f"{k}={v!r}" for k, v in tooltips.items())
        )

    def test_all_three_share_one_browse_tooltip(self, controls, guide, image_ui):
        tooltips = {
            "streaming window": controls.metadata_browse_button.toolTip(),
            "streaming wizard": guide.metadataBrowseButton.toolTip(),
            "video parser": image_ui.srtSelectButton.toolTip(),
        }
        assert len(set(tooltips.values())) == 1, (
            "browse tooltips have drifted apart: "
            + "; ".join(f"{k}={v!r}" for k, v in tooltips.items())
        )

    def test_all_three_share_one_label(self, controls, guide, image_ui):
        labels = {
            controls.metadata_label.text().strip(),
            guide.labelMetadataFile.text().strip(),
            image_ui.srtSelectLabel.text().strip(),
        }
        assert len(labels) == 1, f"labels disagree: {labels}"
        assert "optional" in labels.pop().lower()

    def test_all_three_share_one_placeholder(self, controls, guide, image_ui):
        placeholders = {
            controls.metadata_input.placeholderText().strip(),
            guide.metadataFileLineEdit.placeholderText().strip(),
            image_ui.srtSelectLine.placeholderText().strip(),
        }
        assert len(placeholders) == 1, f"placeholders disagree: {placeholders}"

    def test_the_note_names_both_automatic_routes(self, controls):
        """Sidecar *and* embedded — an operator who knows their video has no
        .SRT still shouldn't reach for this field."""
        text = controls.metadata_input.toolTip().lower()
        assert "optional" in text
        assert ".srt" in text and "next to the video" in text
        assert "embedded" in text

    def test_changing_the_video_clears_the_metadata_file(self, controls):
        """A metadata file *overrides* the video's embedded telemetry, so a
        leftover one geotags the new video with the old flight's positions —
        and SRT times are video-relative, so it looks plausible."""
        controls.url_input.setText("C:/videos/first.mp4")
        controls.set_metadata_path("C:/logs/first.srt")
        assert controls.get_metadata_path() == "C:/logs/first.srt"

        controls.url_input.setText("C:/videos/second.mp4")
        assert controls.get_metadata_path() == ""
        assert controls.metadata_input.text() == ""

    def test_reselecting_the_same_video_keeps_it(self, controls):
        controls.url_input.setText("C:/videos/first.mp4")
        controls.set_metadata_path("C:/logs/first.srt")
        controls.url_input.setText("C:/videos/first.mp4")
        assert controls.get_metadata_path() == "C:/logs/first.srt"

    def test_browsing_a_new_video_clears_it(self, controls):
        """The path users actually take: Browse... for a different video."""
        controls.url_input.setText("C:/videos/first.mp4")
        controls.set_metadata_path("C:/logs/first.csv")
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=("C:/videos/second.mp4", "")):
            controls.browse_for_file()
        assert controls.get_metadata_path() == ""


# ----------------------------------------------------------------------
# Setup guide — StreamConnectionPage
# ----------------------------------------------------------------------


class TestSetupGuide:
    def _page(self, guide) -> StreamConnectionPage:
        page = guide.pages[1]
        assert isinstance(page, StreamConnectionPage)
        return page

    def test_field_is_offered_for_file_sources(self, guide):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()

        # The guide is never shown in tests, so assert on the explicit
        # hidden flag rather than effective visibility.
        assert not guide.labelMetadataFile.isHidden()
        assert not guide.metadataFileLineEdit.isHidden()
        assert not guide.metadataBrowseButton.isHidden()

    @pytest.mark.parametrize("source_type", [
        SOURCE_TYPE_HDMI, SOURCE_TYPE_RTMP, SOURCE_TYPE_ADIAT_FLIGHT,
    ])
    def test_field_is_hidden_for_live_sources(self, guide, source_type):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = source_type
        page.on_enter()

        assert guide.labelMetadataFile.isHidden()
        assert guide.metadataFileLineEdit.isHidden()
        assert guide.metadataBrowseButton.isHidden()

    def test_default_is_empty(self, guide):
        assert guide.wizard_data["metadata_path"] == ""

    def test_typed_path_reaches_wizard_data(self, guide):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()

        guide.metadataFileLineEdit.setText("C:/logs/flight.csv")
        page.save_data()

        assert guide.wizard_data["metadata_path"].endswith("flight.csv")

    def test_switching_to_a_live_source_clears_it(self, guide):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()
        guide.metadataFileLineEdit.setText("C:/logs/flight.csv")

        guide.wizard_data["stream_type"] = SOURCE_TYPE_RTMP
        page.on_enter()

        assert guide.metadataFileLineEdit.text() == ""
        assert guide.wizard_data["metadata_path"] == ""

    def test_save_drops_it_for_live_sources(self, guide):
        """Belt and braces: even if the field somehow still holds a path,
        it must not be carried forward for a source that can't use it."""
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_ADIAT_FLIGHT
        guide.metadataFileLineEdit.setText("C:/logs/flight.csv")
        page.save_data()

        assert guide.wizard_data["metadata_path"] == ""

    def test_a_metadata_file_is_never_required(self, guide):
        """Validation must not start demanding one — most videos carry their
        own telemetry."""
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()
        guide.streamUrlLineEdit.setText("C:/videos/flight.mp4")
        guide.metadataFileLineEdit.setText("")

        assert page.validate() is True

    def test_instructions_explain_that_it_is_optional(self, guide):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()

        text = guide.labelConnectionInstructions.text().lower()
        assert "optional" in text
        assert ".csv" in text

    def test_a_prefilled_path_is_restored(self, guide):
        page = self._page(guide)
        guide.wizard_data["metadata_path"] = "C:/logs/prior.srt"
        page.load_data()
        assert guide.metadataFileLineEdit.text() == "C:/logs/prior.srt"

    def test_changing_the_video_clears_the_metadata_file(self, guide):
        """Reported in use: switching to a video with embedded telemetry kept
        the previous video's SRT, which then overrode the embedded track."""
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()

        guide.streamUrlLineEdit.setText("C:/videos/first.mp4")
        guide.metadataFileLineEdit.setText("C:/logs/first.srt")
        assert guide.wizard_data["metadata_path"].endswith("first.srt")

        guide.streamUrlLineEdit.setText("C:/videos/second.mp4")

        assert guide.metadataFileLineEdit.text() == ""
        assert guide.wizard_data["metadata_path"] == ""
        page.save_data()
        assert guide.wizard_data["metadata_path"] == ""

    def test_reselecting_the_same_video_keeps_it(self, guide):
        page = self._page(guide)
        guide.wizard_data["stream_type"] = SOURCE_TYPE_FILE
        page.on_enter()

        guide.streamUrlLineEdit.setText("C:/videos/first.mp4")
        guide.metadataFileLineEdit.setText("C:/logs/first.srt")
        guide.streamUrlLineEdit.setText("C:/videos/first.mp4")

        assert guide.wizard_data["metadata_path"].endswith("first.srt")

    def test_a_restored_pair_survives_load(self, guide):
        """load_data sets the video then the metadata file; the clearing rule
        must not eat the value it is in the middle of restoring."""
        page = self._page(guide)
        guide.wizard_data["stream_url"] = "C:/videos/first.mp4"
        guide.wizard_data["metadata_path"] = "C:/logs/first.srt"
        page.load_data()

        assert guide.metadataFileLineEdit.text() == "C:/logs/first.srt"
        assert guide.wizard_data["metadata_path"].endswith("first.srt")
