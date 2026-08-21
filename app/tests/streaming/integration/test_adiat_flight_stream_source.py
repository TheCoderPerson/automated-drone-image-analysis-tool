"""Integration tests: ADIAT Flight as a streaming-analysis video source.

Exercises the full desktop path — setup guide / stream controls ->
:class:`StreamViewerWindow` -> :class:`StreamCoordinator` ->
:class:`FlightStreamManager` -> frame display — with the WebRTC receive
service stubbed out, so no network or aiortc is involved.
"""

import numpy as np
import pytest
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.controllers.streaming.StreamViewerWindow import StreamViewerWindow
from core.services.streaming.FlightStreamService import FlightStreamManager
from core.services.streaming.RTMPStreamService import (
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    StreamType,
)


class StubReceiveService(QObject):
    """Minimal stand-in for the WebRTC receive service."""

    frameReady = Signal(np.ndarray, float, int)
    connectionStatusChanged = Signal(bool, str)
    streamStatsChanged = Signal(dict)
    errorOccurred = Signal(str)
    dataChannelOpened = Signal(str)
    dataChannelMessage = Signal(str, bytes)
    finished = Signal()

    def __init__(self, signaling=None, pairing_code=None, fps_limit=None):
        super().__init__()
        self.pairing_code = pairing_code
        self.fps_limit = fps_limit
        self.dropped_frames = 0
        self.disconnect_calls = 0
        self.terminal_disconnect_calls = 0

    def request_connect(self):
        pass

    def request_disconnect(self):
        # Terminal on the Worker — the manager must NOT use this.
        self.terminal_disconnect_calls += 1

    def cleanup(self, wait=False):
        self.disconnect_calls += 1

    def isRunning(self):
        return False

    def wait(self, ms):
        return True

    def set_fps_limit(self, fps_limit):
        self.fps_limit = fps_limit
        return fps_limit


@pytest.fixture
def stub_services():
    """Patch FlightStreamManager so every instance uses a stub service."""
    created = []

    def factory(self, signaling, code, fps_limit):
        service = StubReceiveService(signaling, code, fps_limit)
        created.append(service)
        return service

    with patch.object(FlightStreamManager, "_build_service", factory), \
            patch(
                "core.services.streaming.FlightStreamService.default_signaling_channel",
                return_value=Mock(),
            ):
        yield created


@pytest.fixture
def viewer(qapp):
    window = StreamViewerWindow(algorithm_name='', theme='dark')
    yield window
    window.close()
    QApplication.processEvents()


class TestAdiatFlightStreamSource:
    """ADIAT Flight behaves as a first-class source end to end."""

    def test_connect_builds_flight_manager_and_pairs(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)

        manager = viewer.stream_coordinator.stream_manager
        assert isinstance(manager, FlightStreamManager)
        assert viewer.stream_coordinator.current_stream_type == StreamType.WEBRTC
        assert viewer.stream_coordinator.current_stream_url == "K7QM3P"
        assert len(stub_services) == 1
        assert stub_services[0].pairing_code == "K7QM3P"

    def test_frames_reach_the_viewer(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        service = stub_services[0]
        service.connectionStatusChanged.emit(True, "connected")
        QApplication.processEvents()

        received = []
        viewer.stream_coordinator.frameReceived.connect(
            lambda f, ts, pos: received.append((f.shape, pos))
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        service.frameReady.emit(frame, 1.5, 3)
        QApplication.processEvents()

        assert received == [((720, 1280, 3), 3)]

    def test_live_feed_shows_the_record_only_strip(self, viewer, stub_services):
        """No timeline for a live source — but recording stays reachable.

        The bar used to hide entirely for live feeds; now it shows as a
        record-only strip, because a live feed is exactly what the
        operator records.
        """
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        with patch.object(viewer.playback_controls, "show_for_live") as live, \
                patch.object(viewer.playback_controls, "show_for_file") as show:
            viewer.on_connection_changed(True, "connected")

        live.assert_called_once()
        show.assert_not_called()

    def test_seek_is_inert_for_live_feed(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        manager = viewer.stream_coordinator.stream_manager

        assert manager.is_file_playback() is False
        assert manager.seek_to_frame(10) is None
        assert viewer._is_file_playback_paused() is False

    def test_applied_source_fps_treats_flight_as_live(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        viewer._active_stream_fps_limit = None

        # Live sources are capped at 60 when the source rate is unknown, and
        # follow the reported rate otherwise.
        assert viewer._get_applied_source_fps(0) == 60.0
        assert viewer._get_applied_source_fps(24.0) == 24.0

    def test_stats_populate_resolution_for_recording(self, viewer, stub_services):
        """Recording sizes itself from stream_info['resolution']."""
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        service = stub_services[0]
        service.streamStatsChanged.emit({"fps": 30.0, "width": 1920, "height": 1080})
        QApplication.processEvents()

        assert viewer.stream_coordinator.stream_info["resolution"] == (1920, 1080)

    def test_disconnect_releases_the_session(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        service = stub_services[0]

        viewer.on_disconnect_requested()
        QApplication.processEvents()

        assert service.disconnect_calls == 1
        assert viewer.stream_coordinator.stream_manager is None
        assert viewer.stream_coordinator.current_stream_type is None

    def test_detections_from_flight_are_not_ingested(self, viewer, stub_services):
        """Requirement: ignore detection information from ADIAT Flight.

        The desktop's own algorithm owns detections for this session, so a
        publisher promotion must not create a gallery row or a thumbnail.
        """
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        service = stub_services[0]
        service.connectionStatusChanged.emit(True, "connected")
        QApplication.processEvents()

        service.dataChannelOpened.emit("detections.meta")
        service.dataChannelMessage.emit(
            "detections.meta",
            b'{"event":"promote","track_key":"t1","bbox":[0,0,10,10]}',
        )
        service.dataChannelMessage.emit("detections.thumb", b"\xff\xd8\xff\xdb")
        QApplication.processEvents()

        assert viewer.gallery_widget.gallery_list.count() == 0
        assert viewer._latest_detections_for_rendering == []
        assert viewer.thumbnail_widget.tracker.tracks == {}

    def test_switching_from_file_to_flight_swaps_the_manager(self, viewer, stub_services):
        """A replacement source must not inherit the previous transport."""
        file_manager = Mock()
        file_manager.connect_to_stream = Mock(return_value=True)
        file_manager.frameReceived = Mock()
        file_manager.connectionChanged = Mock()

        with patch(
            "core.controllers.streaming.components.StreamCoordinator.StreamManager",
            return_value=file_manager,
        ):
            viewer.on_connect_requested("C:/videos/flight.mp4", StreamType.FILE)
        assert viewer.stream_coordinator.stream_manager is file_manager

        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        assert isinstance(viewer.stream_coordinator.stream_manager, FlightStreamManager)


class TestAdiatFlightWizardHandoff:
    """The setup guide's ADIAT Flight selection reaches the viewer intact."""

    def test_wizard_data_selects_flight_source(self, viewer, stub_services):
        viewer.apply_wizard_data({
            "stream_type": SOURCE_TYPE_ADIAT_FLIGHT,
            "stream_url": "K7QM3P",
            "auto_connect": False,
        })

        combo = viewer.stream_controls.type_combo
        assert combo.currentData() == SOURCE_TYPE_ADIAT_FLIGHT
        assert viewer.stream_controls.url_input.text() == "K7QM3P"

    def test_wizard_auto_connect_prompts_for_a_code(self, viewer, stub_services):
        """Auto-connect means "ask now", not "use a code from minutes ago".

        Codes expire ~30 s after ADIAT Flight issues them, so the wizard
        never carries one; it opens the pairing prompt on arrival instead.
        """
        with patch.object(viewer, "open_flight_pairing_dialog") as prompt:
            viewer.apply_wizard_data({
                "stream_type": SOURCE_TYPE_ADIAT_FLIGHT,
                "stream_url": "",
                "auto_connect": True,
            })

        prompt.assert_called_once()
        # Nothing connected yet — no code has been supplied.
        assert stub_services == []

    def test_wizard_without_auto_connect_does_not_prompt(self, viewer, stub_services):
        with patch.object(viewer, "open_flight_pairing_dialog") as prompt:
            viewer.apply_wizard_data({
                "stream_type": SOURCE_TYPE_ADIAT_FLIGHT,
                "stream_url": "",
                "auto_connect": False,
            })
        prompt.assert_not_called()

    def test_wizard_file_source_still_routes_to_opencv(self, viewer, stub_services):
        """Regression guard for the findData-based combo lookup."""
        viewer.apply_wizard_data({
            "stream_type": SOURCE_TYPE_FILE,
            "stream_url": "C:/videos/flight.mp4",
            "auto_connect": False,
        })

        combo = viewer.stream_controls.type_combo
        assert combo.currentData() == SOURCE_TYPE_FILE
        assert stub_services == []


class TestConnectionProgressIsNotADisconnect:
    """``connected=False`` during pairing must not tear the session down.

    A WebRTC pair reports progress as ``connected=False`` ("Looking up
    pairing code...", "Connecting..."), and RTMP does the same while
    retrying. Running the disconnect teardown on those discarded state the
    pending connection still needed — most visibly the wizard's processing
    resolution, which is applied when the first frame arrives.
    """

    def test_wizard_resolution_survives_pairing(self, viewer, stub_services):
        viewer.apply_wizard_data({
            "stream_type": SOURCE_TYPE_ADIAT_FLIGHT,
            "stream_url": "K7QM3P",
            "auto_connect": True,
            "processing_resolution": 50,      # 720p
        })
        assert viewer._pending_processing_resolution == (1280, 720)

    def test_progress_messages_do_not_notify_the_algorithm(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        algorithm = Mock()
        viewer.algorithm_widget = algorithm

        service = stub_services[0]
        service.connectionStatusChanged.emit(False, "Looking up pairing code...")
        service.connectionStatusChanged.emit(False, "Connecting...")
        QApplication.processEvents()

        algorithm.on_stream_disconnected.assert_not_called()

    def test_progress_does_not_clear_the_gallery(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        with patch.object(viewer.gallery_widget, "clear") as clear:
            stub_services[0].connectionStatusChanged.emit(False, "Connecting...")
            QApplication.processEvents()
        clear.assert_not_called()

    def test_a_real_disconnect_still_tears_down(self, viewer, stub_services):
        """The edge trigger must not suppress genuine losses."""
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        service = stub_services[0]
        algorithm = Mock()
        viewer.algorithm_widget = algorithm

        service.connectionStatusChanged.emit(True, "connected")
        QApplication.processEvents()
        service.connectionStatusChanged.emit(False, "remote-closed")
        QApplication.processEvents()

        algorithm.on_stream_disconnected.assert_called_once()
        assert viewer._pending_processing_resolution is None

    def test_status_bar_says_connecting_not_disconnected(self, viewer, stub_services):
        viewer.on_connect_requested("K7QM3P", StreamType.WEBRTC)
        stub_services[0].connectionStatusChanged.emit(False, "Connecting...")
        QApplication.processEvents()

        text = viewer.ui.statusbar.currentMessage()
        assert "Connecting" in text
        assert "Disconnected" not in text


class TestConnectTimePairing:
    """The pairing prompt is the only place a code is entered.

    ADIAT Flight codes are evicted after ~30 s of inactivity, so the
    handshake has to follow entry within seconds. The prompt reuses the
    Flight Viewer's dialog so both surfaces report the same states.
    """

    def test_connect_button_opens_the_prompt(self, viewer, stub_services):
        index = viewer.stream_controls.type_combo.findData(SOURCE_TYPE_ADIAT_FLIGHT)
        viewer.stream_controls.type_combo.setCurrentIndex(index)

        with patch.object(viewer, "open_flight_pairing_dialog") as prompt:
            viewer.stream_controls.request_connect()
        prompt.assert_called_once()

    def test_submitting_a_code_starts_the_handshake(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        assert dialog is not None

        dialog.codeEdit.setText("k7q-m3p")
        dialog._on_connect_clicked()
        QApplication.processEvents()

        assert stub_services and stub_services[0].pairing_code == "K7QM3P"
        assert viewer.stream_coordinator.current_stream_type == StreamType.WEBRTC

    def test_malformed_code_stays_in_the_prompt(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog

        dialog.codeEdit.setText("BAD")
        dialog._on_connect_clicked()
        QApplication.processEvents()

        assert stub_services == []
        assert dialog.codeErrorLabel.text()      # inline, next to the field

    def test_progress_is_shown_in_the_prompt(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        dialog.codeEdit.setText("K7QM3P")
        dialog._on_connect_clicked()

        stub_services[0].connectionStatusChanged.emit(False, "Looking up pairing code...")
        QApplication.processEvents()

        assert dialog.negotiatingDetail.text() == "Looking up pairing code..."

    def test_failure_is_shown_in_the_prompt(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        dialog.codeEdit.setText("K7QM3P")
        dialog._on_connect_clicked()

        stub_services[0].errorOccurred.emit("no session for code 'K7QM3P'")
        QApplication.processEvents()

        assert "no session" in dialog.failedDetail.text()
        # The "Error: " marker is plumbing, not something to show operators.
        assert not dialog.failedDetail.text().startswith("Error:")

    def test_success_dismisses_the_prompt_and_shows_the_code(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        dialog.codeEdit.setText("K7QM3P")
        dialog._on_connect_clicked()

        stub_services[0].connectionStatusChanged.emit(True, "connected")
        QApplication.processEvents()

        assert viewer._pairing_dialog is None
        assert viewer.stream_controls.url_input.text() == "K7QM3P"

    def test_cancelling_abandons_the_attempt(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        dialog.codeEdit.setText("K7QM3P")
        dialog._on_connect_clicked()
        assert viewer.stream_coordinator.stream_manager is not None

        dialog._on_cancel_clicked()
        QApplication.processEvents()

        assert viewer.stream_coordinator.stream_manager is None

    def test_only_one_prompt_at_a_time(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        first = viewer._pairing_dialog
        viewer.open_flight_pairing_dialog()
        assert viewer._pairing_dialog is first

    def test_disconnect_clears_the_displayed_code(self, viewer, stub_services):
        viewer.open_flight_pairing_dialog()
        dialog = viewer._pairing_dialog
        dialog.codeEdit.setText("K7QM3P")
        dialog._on_connect_clicked()
        stub_services[0].connectionStatusChanged.emit(True, "connected")
        QApplication.processEvents()
        assert viewer.stream_controls.url_input.text() == "K7QM3P"

        viewer.on_disconnect_requested()
        QApplication.processEvents()

        assert viewer.stream_controls.url_input.text() == ""
