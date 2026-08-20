"""Integration tests: StreamViewerWindow feeding a recording's session bundle.

Covers the wiring between what the operator sees and what a recording keeps:
confirmed detections, telemetry fixes, the recording options, and the
report that follows a finished bundle.
"""

import csv
import os
from importlib import import_module

import numpy as np
import pytest
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from core.controllers.streaming.StreamViewerWindow import StreamViewerWindow
from core.controllers.streaming.shared_widgets import Track
from core.services.streaming.RecordingSessionService import read_manifest
from core.services.streaming.RTMPStreamService import StreamType


@pytest.fixture
def window(qapp, isolated_stream_settings):
    """A streaming window with no algorithm loaded.

    ``isolated_stream_settings`` (autouse, in the streaming conftest) keeps
    the recording panel's persisted options out of the real settings store;
    it is named here so the dependency is visible rather than implied.
    """
    window = StreamViewerWindow(algorithm_name='', theme='dark')
    yield window
    window.close()
    QApplication.processEvents()


def _track(track_id=1, **overrides):
    payload = dict(
        track_id=track_id,
        bbox=(100, 120, 20, 24),
        centroid=(110, 132),
        thumbnail=np.full((30, 40, 3), 180, dtype=np.uint8),
        first_frame_index=150,
        first_timestamp=5.0,
        frame_resolution=(1280, 720),
        thumbnail_origin=(90, 108),
        detection_type="person",
        confidence=0.81,
        pixel_area=380.0,
        detection_color=(10, 20, 30),
    )
    payload.update(overrides)
    return Track(**payload)


class TestDetectionCapture:
    """Confirmed tracks reach the recording, and only while it runs."""

    def test_confirmed_track_is_stored_while_recording(self, window):
        window.stream_coordinator.is_recording = True
        stored = []
        window.stream_coordinator.append_detection_record = stored.append

        window.thumbnail_widget.tracker.track_confirmed.emit(_track())
        QApplication.processEvents()

        assert len(stored) == 1
        record = stored[0]
        assert record.track_id == 1
        assert record.bbox == (100, 120, 20, 24)
        assert record.detection_type == "person"
        assert record.thumbnail_origin == (90, 108)
        assert record.thumbnail is not None

    def test_video_time_is_derived_from_the_frame_index(self, window):
        """Track.first_timestamp is a perf_counter reading, not a position.

        Storing it produced clock times that meant nothing and could not be
        joined against telemetry.csv, so the frame index and source FPS are
        the authority.
        """
        window.stream_coordinator.is_recording = True
        window.stream_coordinator.stream_info["fps"] = 30.0
        stored = []
        window.stream_coordinator.append_detection_record = stored.append

        # first_timestamp is deliberately a value that is NOT the video time.
        window.thumbnail_widget.tracker.track_confirmed.emit(
            _track(first_frame_index=150, first_timestamp=98765.4)
        )
        QApplication.processEvents()

        assert stored[0].video_time_seconds == pytest.approx(5.0)

    def test_video_time_is_none_when_the_source_fps_is_unknown(self, window):
        """Better an absent time than a fabricated one."""
        window.stream_coordinator.is_recording = True
        window.stream_coordinator.stream_info["fps"] = 0
        stored = []
        window.stream_coordinator.append_detection_record = stored.append

        window.thumbnail_widget.tracker.track_confirmed.emit(_track())
        QApplication.processEvents()

        assert stored[0].video_time_seconds is None

    def test_nothing_is_stored_when_not_recording(self, window):
        window.stream_coordinator.is_recording = False
        stored = []
        window.stream_coordinator.append_detection_record = stored.append

        window.thumbnail_widget.tracker.track_confirmed.emit(_track())
        QApplication.processEvents()

        assert stored == []

    def test_thumbnail_is_copied_not_shared(self, window):
        """The gallery keeps its crop for the session; the writer needs its own."""
        window.stream_coordinator.is_recording = True
        stored = []
        window.stream_coordinator.append_detection_record = stored.append
        track = _track()

        window.thumbnail_widget.tracker.track_confirmed.emit(track)
        QApplication.processEvents()

        assert stored[0].thumbnail is not track.thumbnail
        np.testing.assert_array_equal(stored[0].thumbnail, track.thumbnail)

    def test_position_comes_from_the_same_source_as_the_map_pin(self, window):
        """One geotag resolution, so the stored record and the pin agree."""
        window.stream_coordinator.is_recording = True
        stored = []
        window.stream_coordinator.append_detection_record = stored.append
        window._resolve_track_position = lambda track: (30.25, -97.75)

        window.thumbnail_widget.tracker.track_confirmed.emit(_track())
        QApplication.processEvents()

        assert stored[0].latitude == pytest.approx(30.25)
        assert stored[0].longitude == pytest.approx(-97.75)

    def test_detection_without_a_position_is_still_stored(self, window):
        """A video with no telemetry still keeps its detections."""
        window.stream_coordinator.is_recording = True
        stored = []
        window.stream_coordinator.append_detection_record = stored.append
        window._resolve_track_position = lambda track: None

        window.thumbnail_widget.tracker.track_confirmed.emit(_track())
        QApplication.processEvents()

        assert len(stored) == 1
        assert stored[0].latitude is None
        assert stored[0].longitude is None


class TestTelemetryCapture:
    """Telemetry envelopes bound the recording's flight map."""

    def test_envelope_reaches_the_recording(self, window):
        captured = []
        window.stream_coordinator.append_telemetry = captured.append

        window.on_telemetry_updated({
            "aircraft_latitude": 30.1,
            "aircraft_longitude": -97.2,
        })

        assert captured == [{"aircraft_latitude": 30.1, "aircraft_longitude": -97.2}]

    def test_non_dict_envelope_is_ignored(self, window):
        captured = []
        window.stream_coordinator.append_telemetry = captured.append

        window.on_telemetry_updated(None)

        assert captured == []


class TestRecordingOptions:
    """What the recording panel asks for is what gets captured."""

    def test_metadata_reflects_the_checkboxes(self, window):
        window.save_detections_check.setChecked(True)
        window.save_map_check.setChecked(True)

        metadata = window._recording_metadata()

        assert metadata["save_detections"] is True
        assert metadata["save_flight_map"] is True

    def test_detections_can_be_declined(self, window):
        window.save_detections_check.setChecked(False)

        assert window._recording_metadata()["save_detections"] is False

    def test_map_is_still_requested_before_telemetry_arrives(self, window):
        """A live feed reports its first fix *after* the stream is up.

        Gating the request on availability meant a recording started a
        moment early dropped every fix of the whole flight.
        """
        window.save_map_check.setChecked(True)
        window.telemetry_coordinator._available = False
        window._on_telemetry_availability_changed(False)

        assert window._recording_metadata()["save_flight_map"] is True

    def test_map_can_be_declined(self, window):
        window.save_map_check.setChecked(False)

        assert window._recording_metadata()["save_flight_map"] is False

    def test_map_option_stays_usable_whatever_the_source_reports(self, window):
        """It is a standing preference, so it must never be disabled."""
        window.telemetry_coordinator._available = False
        window._on_telemetry_availability_changed(False)
        assert window.save_map_check.isEnabled() is True
        unavailable_tip = window.save_map_check.toolTip()

        window.telemetry_coordinator._available = True
        window._on_telemetry_availability_changed(True)
        assert window.save_map_check.isEnabled() is True
        # The tooltip is what carries the availability, not the enabled state.
        assert window.save_map_check.toolTip() != unavailable_tip

    def test_start_recording_passes_the_metadata_through(self, window, tmp_path):
        calls = {}
        window.stream_coordinator.start_recording = (
            lambda directory, metadata=None: calls.update(
                directory=directory, metadata=metadata
            ) or True
        )

        window.on_start_recording_requested(str(tmp_path))

        assert calls["directory"] == str(tmp_path)
        assert "save_detections" in calls["metadata"]
        assert "save_flight_map" in calls["metadata"]


class TestWizardAutoRecord:
    """``auto_record`` from the wizard, which no wizard page sets yet.

    The plumbing is complete and reachable via ``apply_wizard_data``, so it
    is worth pinning: whoever adds the wizard control should find working
    machinery, and should find out here if they break it.
    """

    def _fake_recording_manager(self, monkeypatch):
        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                return True

            def get_recording_info(self):
                return {"total_frames": 30}

        monkeypatch.setattr(coordinator_module, "RecordingManager", FakeRecordingManager)

    def test_auto_record_arms_from_wizard_data(self, window, tmp_path):
        window.apply_wizard_data({
            "auto_record": True,
            "recording_dir": str(tmp_path),
        })

        assert window._pending_auto_record is True
        assert window._pending_record_dir == str(tmp_path)

    def test_auto_record_starts_once_the_resolution_is_known(
            self, window, tmp_path, monkeypatch):
        """File/RTMP report a resolution before reporting connected."""
        self._fake_recording_manager(monkeypatch)
        window.apply_wizard_data({
            "auto_record": True, "recording_dir": str(tmp_path),
        })

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.RTMP
        coordinator.stream_info["resolution"] = (1280, 720)
        coordinator.stream_info["fps"] = 30.0

        window.on_connection_changed(True, "Connected")
        QApplication.processEvents()

        assert coordinator.is_recording is True
        assert coordinator.recording_bundle_dir is not None
        # Fires once - a reconnect must not start a second recording.
        assert window._pending_auto_record is False

        window.on_stop_recording_requested()
        QApplication.processEvents()

    def test_auto_record_waits_for_a_frame_when_resolution_is_unknown(
            self, window, tmp_path, monkeypatch):
        """A WebRTC pair connects before any frame exists.

        Starting at connect would size the writer from the 1280x720
        fallback and silently downscale a 4K feed.
        """
        self._fake_recording_manager(monkeypatch)
        window.apply_wizard_data({
            "auto_record": True, "recording_dir": str(tmp_path),
        })

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.WEBRTC
        coordinator.stream_info["resolution"] = (0, 0)

        window.on_connection_changed(True, "Connected")
        QApplication.processEvents()
        assert coordinator.is_recording is False
        assert window._pending_auto_record is True

        # First frame arrives, carrying the real resolution.
        coordinator.stream_info["resolution"] = (3840, 2160)
        coordinator.stream_info["fps"] = 30.0
        window.on_frame_received(
            np.zeros((2160, 3840, 3), dtype=np.uint8), 0.0, 0
        )
        QApplication.processEvents()

        assert coordinator.is_recording is True
        window.on_stop_recording_requested()
        QApplication.processEvents()

    def test_auto_recorded_session_stores_detections_and_map(
            self, window, tmp_path, monkeypatch):
        """An auto-started recording is a full recording, not a video-only one."""
        self._fake_recording_manager(monkeypatch)
        window.apply_wizard_data({
            "auto_record": True, "recording_dir": str(tmp_path),
        })

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.RTMP
        coordinator.stream_info["resolution"] = (1280, 720)
        coordinator.stream_info["fps"] = 30.0
        window.telemetry_coordinator._available = True
        window._resolve_track_position = lambda track: (30.4, -97.4)

        results = []
        coordinator.recordingBundleReady.connect(results.append)

        window.on_connection_changed(True, "Connected")
        QApplication.processEvents()
        bundle = coordinator.recording_bundle_dir
        assert bundle is not None

        window.thumbnail_widget.tracker.track_confirmed.emit(_track(1))
        window.on_telemetry_updated(
            {"aircraft_latitude": 30.4, "aircraft_longitude": -97.4}
        )
        window.on_telemetry_updated(
            {"aircraft_latitude": 30.5, "aircraft_longitude": -97.5}
        )
        QApplication.processEvents()

        window.on_stop_recording_requested()
        QApplication.processEvents()

        assert results[0]["counts"]["detections_stored"] == 1
        for name in ("detections.csv", "ADIAT_Data.xml", "flight_map.html"):
            assert os.path.isfile(os.path.join(bundle, name)), name


class TestBundleReport:
    """The finished bundle is reported and reachable."""

    def test_report_names_the_folder_and_counts(self, window, tmp_path):
        bundle = str(tmp_path)

        window.on_recording_bundle_ready({
            "bundle_dir": bundle,
            "counts": {"detections_stored": 3, "telemetry_fixes": 120},
            "artifacts": {"flight_map_html": "flight_map.html"},
            "errors": [],
        })

        text = window.ui.infoPanel.toPlainText()
        assert bundle in text
        assert "3" in text and "120" in text
        assert "flight_map.html" in text
        assert window._last_recording_bundle == bundle
        assert window.open_recording_btn.isHidden() is False

    def test_errors_are_surfaced(self, window, tmp_path):
        window.on_recording_bundle_ready({
            "bundle_dir": str(tmp_path),
            "counts": {},
            "artifacts": {},
            "errors": ["flight_path_kml: disk full"],
        })

        assert "disk full" in window.ui.infoPanel.toPlainText()

    def test_result_without_a_bundle_is_ignored(self, window):
        window.on_recording_bundle_ready({"bundle_dir": None})

        assert window._last_recording_bundle is None
        assert window.open_recording_btn.isHidden() is True

    def test_open_folder_only_opens_a_real_directory(self, window, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(
            "core.controllers.streaming.StreamViewerWindow.QDesktopServices.openUrl",
            lambda url: opened.append(url.toLocalFile()),
        )

        window._last_recording_bundle = os.path.join(str(tmp_path), "gone")
        window._open_last_recording_folder()
        assert opened == []

        window._last_recording_bundle = str(tmp_path)
        window._open_last_recording_folder()
        assert len(opened) == 1


class TestEndToEndBundle:
    """A recording from start to finished folder, without a real stream."""

    def test_detections_and_flight_land_in_the_bundle(self, window, tmp_path, monkeypatch):
        """The operator's whole loop: start, detect, fly, stop, read the folder."""
        # `import ...components.StreamCoordinator` binds the class, not the
        # module: the components package re-exports it under the same name.
        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        # Stands in for the video writer only: this test is about the bundle,
        # and a real cv2.VideoWriter needs a live frame source to produce a
        # playable MP4.
        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()
                self.output_dir = output_dir
                self.frames = 0

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                self.frames += 1
                return True

            def get_recording_info(self):
                return {"total_frames": self.frames}

        monkeypatch.setattr(
            coordinator_module, "RecordingManager", FakeRecordingManager
        )

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.FILE
        window.telemetry_coordinator._available = True
        window._resolve_track_position = lambda track: (30.5, -97.5)
        window.save_detections_check.setChecked(True)
        window.save_map_check.setEnabled(True)
        window.save_map_check.setChecked(True)

        results = []
        coordinator.recordingBundleReady.connect(results.append)

        window.on_start_recording_requested(str(tmp_path))
        bundle = coordinator.recording_bundle_dir
        assert bundle is not None

        window.thumbnail_widget.tracker.track_confirmed.emit(_track(1))
        window.thumbnail_widget.tracker.track_confirmed.emit(_track(2))
        window.on_telemetry_updated({"aircraft_latitude": 30.4, "aircraft_longitude": -97.4})
        window.on_telemetry_updated({"aircraft_latitude": 30.6, "aircraft_longitude": -97.6})
        QApplication.processEvents()

        window.on_stop_recording_requested()
        QApplication.processEvents()

        assert len(results) == 1
        assert results[0]["counts"]["detections_stored"] == 2
        assert results[0]["counts"]["telemetry_fixes"] == 2
        for name in ("detections.csv", "ADIAT_Data.xml", "flight_map.html",
                     "flight_path.kml", "telemetry.csv", "manifest.json"):
            assert os.path.isfile(os.path.join(bundle, name)), name
        assert os.path.isfile(os.path.join(bundle, "detections", "detection_0000.jpg"))

        # The map has to show the flight, not just the detections.
        page = open(os.path.join(bundle, "flight_map.html"), encoding="utf-8").read()
        assert "30.4" in page and "-97.6" in page
        assert "30.5" in page

    def test_telemetry_arriving_after_the_start_still_makes_the_map(
            self, window, tmp_path, monkeypatch):
        """The live-feed case: pair, record, then the first fix lands.

        The whole flight used to be discarded because the flight-map option
        was read from a checkbox that only became enabled with that fix.
        """
        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                return True

            def get_recording_info(self):
                return {}

        monkeypatch.setattr(coordinator_module, "RecordingManager", FakeRecordingManager)

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        window.save_map_check.setChecked(True)
        # Nothing has been received yet - exactly the state a freshly paired
        # ADIAT Flight feed is in.
        window.telemetry_coordinator._available = False
        window._on_telemetry_availability_changed(False)

        results = []
        coordinator.recordingBundleReady.connect(results.append)

        window.on_start_recording_requested(str(tmp_path))
        bundle = coordinator.recording_bundle_dir

        # ...and now the aircraft starts reporting.
        window.telemetry_coordinator._available = True
        for i in range(4):
            window.on_telemetry_updated({
                "aircraft_latitude": 30.0 + i * 0.001,
                "aircraft_longitude": -97.0 - i * 0.001,
            })
        QApplication.processEvents()

        window.on_stop_recording_requested()
        QApplication.processEvents()

        assert results[0]["counts"]["telemetry_fixes"] == 4
        assert os.path.isfile(os.path.join(bundle, "flight_map.html"))
        assert os.path.isfile(os.path.join(bundle, "flight_path.kml"))

    def test_a_source_with_no_telemetry_still_records_its_detections(
            self, window, tmp_path, monkeypatch):
        """RTMP / HLS / HDMI have no telemetry path at all.

        They must still get the full detection record - the map is the only
        thing they lose, and the bundle has to say why rather than looking
        like it failed.
        """
        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                return True

            def get_recording_info(self):
                return {"total_frames": 120}

        monkeypatch.setattr(coordinator_module, "RecordingManager", FakeRecordingManager)

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.RTMP
        coordinator.current_stream_url = "rtmp://example/live"
        coordinator.stream_info["fps"] = 30.0
        # An RTMP source never makes telemetry available - StreamTelemetryCoordinator
        # only resolves a track for FILE and awaits envelopes for WEBRTC.
        assert window.telemetry_coordinator.is_available is False
        window.save_detections_check.setChecked(True)
        window.save_map_check.setChecked(True)

        results = []
        coordinator.recordingBundleReady.connect(results.append)

        window.on_start_recording_requested(str(tmp_path))
        bundle = coordinator.recording_bundle_dir

        window.thumbnail_widget.tracker.track_confirmed.emit(_track(1, first_frame_index=150))
        window.thumbnail_widget.tracker.track_confirmed.emit(_track(2, first_frame_index=300))
        QApplication.processEvents()

        window.on_stop_recording_requested()
        QApplication.processEvents()

        result = results[0]
        # The detections are all there...
        assert result["counts"]["detections_stored"] == 2
        assert result["artifacts"]["detections_csv"] == "detections.csv"
        assert result["artifacts"]["results_xml"] == "ADIAT_Data.xml"
        assert os.path.isfile(os.path.join(bundle, "detections", "detection_0000.jpg"))
        # ...and they still carry a usable position in the recording's timeline,
        # from the frame index, even with no aircraft position to geotag with.
        with open(os.path.join(bundle, "detections.csv"), encoding="utf-8", newline="") as fp:
            rows = list(csv.DictReader(fp))
        assert [row["video_time_seconds"] for row in rows] == ["5.0", "10.0"]
        assert [row["latitude"] for row in rows] == ["", ""]

        # ...but nothing pretends there was a flight.
        assert result["counts"]["telemetry_fixes"] == 0
        assert result["counts"]["detections_geotagged"] == 0
        assert result["artifacts"]["flight_map_html"] is None
        assert result["artifacts"]["flight_path_kml"] is None
        assert result["artifacts"]["telemetry_csv"] is None

        manifest = read_manifest(bundle)
        assert manifest["source"]["type"] == "rtmp"
        assert manifest["telemetry"]["available"] is False
        assert "No location data arrived" in manifest["telemetry"]["note"]

    def test_results_xml_from_a_non_telemetry_source_still_loads(
            self, window, tmp_path, monkeypatch):
        """The point of the XML is re-opening it; that must not need GPS."""
        from core.services.XmlService import XmlService

        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                return True

            def get_recording_info(self):
                return {}

        monkeypatch.setattr(coordinator_module, "RecordingManager", FakeRecordingManager)

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        coordinator.current_stream_type = StreamType.HDMI_CAPTURE
        window.save_detections_check.setChecked(True)

        window.on_start_recording_requested(str(tmp_path))
        bundle = coordinator.recording_bundle_dir
        window.thumbnail_widget.tracker.track_confirmed.emit(_track(1))
        QApplication.processEvents()
        window.on_stop_recording_requested()
        QApplication.processEvents()

        service = XmlService(os.path.join(bundle, "ADIAT_Data.xml"))
        settings, image_count = service.get_settings()
        assert image_count == 1
        images = service.get_images()
        assert len(images) == 1
        assert os.path.isfile(images[0]["path"])
        assert len(images[0]["areas_of_interest"]) == 1

    def test_declining_detections_records_video_only(self, window, tmp_path, monkeypatch):
        # `import ...components.StreamCoordinator` binds the class, not the
        # module: the components package re-exports it under the same name.
        coordinator_module = import_module(
            'core.controllers.streaming.components.StreamCoordinator'
        )

        class FakeRecordingManager(QObject):
            recordingStateChanged = Signal(bool, str)
            recordingStats = Signal(dict)

            def __init__(self, output_dir):
                super().__init__()

            def start_recording(self, resolution, filename_prefix="rtmp_recording"):
                return True

            def stop_recording(self):
                return None

            def add_frame(self, frame, timestamp=None):
                return True

            def get_recording_info(self):
                return {}

        monkeypatch.setattr(coordinator_module, "RecordingManager", FakeRecordingManager)

        coordinator = window.stream_coordinator
        coordinator.is_connected = True
        window.save_detections_check.setChecked(False)
        window.save_map_check.setChecked(False)

        window.on_start_recording_requested(str(tmp_path))
        bundle = coordinator.recording_bundle_dir
        window.thumbnail_widget.tracker.track_confirmed.emit(_track(1))
        QApplication.processEvents()
        window.on_stop_recording_requested()
        QApplication.processEvents()

        assert not os.path.exists(os.path.join(bundle, "detections.jsonl"))
        assert not os.path.exists(os.path.join(bundle, "ADIAT_Data.xml"))
        # The manifest still records that the session happened.
        assert os.path.isfile(os.path.join(bundle, "manifest.json"))
