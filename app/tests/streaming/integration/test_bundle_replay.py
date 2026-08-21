"""Integration tests: the dedicated Replay window.

Watching a recording is its own experience — video + timeline, the stored
detections as a click-to-jump gallery, the flight on a map, the HUD on the
playhead — with none of the analysis apparatus. These tests load real
bundles into :class:`ReplayWindow` and drive it the way an operator would.
The streaming analysis window is deliberately absent here: replay never
runs a detector, structurally, because the window has none to run.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.controllers.streaming.ReplayWindow import ReplayWindow, open_replay  # noqa: E402
from core.services.streaming.RecordingBundleService import finalize_bundle  # noqa: E402
from core.services.streaming.RecordingSessionService import (  # noqa: E402
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
)
from core.services.streaming.RTMPStreamService import StreamType  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp):
    window = ReplayWindow()
    yield window
    window.close()
    QApplication.processEvents()


def _make_bundle(root, *, detections=2, fixes=3):
    """A real finalized bundle with a placeholder MP4 and spread-out fixes."""
    import json

    from core.services.streaming.RecordingSessionService import (
        TELEMETRY_LOG,
        read_jsonl,
        read_manifest,
    )

    writer = RecordingSessionWriter()
    bundle = writer.start_session(RecordingSessionConfig(
        root_dir=str(root), algorithm="ADIAT Flight",
        source_url="K3F9PM", source_type="webrtc",
        resolution=(1280, 720),
        feed={"label": "TEXSAR-01", "pairing_code": "K3F9PM"},
    ))
    with open(os.path.join(bundle, "rec_0001.mp4"), "wb") as fp:
        fp.write(b"\x00")
    for index in range(detections):
        writer.append_detection(DetectionRecord(
            track_id=index,
            bbox=(100 + index * 40, 120, 20, 24),
            centroid=(110 + index * 40, 132),
            confidence=0.8,
            detection_type="person",
            frame_resolution=(1280, 720),
            recorded_frame_index=90 + index * 30,
            latitude=30.25 + index * 0.001,
            longitude=-97.75,
            thumbnail=np.full((30, 40, 3), 180, dtype=np.uint8),
            thumbnail_origin=(90, 108),
        ))
    for _ in range(fixes):
        writer.append_telemetry({
            "aircraft_latitude": 30.25, "aircraft_longitude": -97.75,
            "aircraft_altitude_agl_m": 40.0, "aircraft_altitude_msl_m": 320.0,
        })
    writer.finalize()

    # Spread the fix stamps onto the recorded clock so SRT cues cover a
    # playable window.
    started = read_manifest(bundle)["started_at_epoch_s"]
    rows = read_jsonl(os.path.join(bundle, TELEMETRY_LOG))
    for index, row in enumerate(rows):
        row["recorded_at_epoch_s"] = started + index * 2.0
        row["recorded_video_seconds"] = index * 2.0
        row["aircraft_latitude"] = 30.25 + index * 0.01
    with open(os.path.join(bundle, TELEMETRY_LOG), "w", encoding="utf-8") as fp:
        fp.write("\n".join(json.dumps(r) for r in rows) + "\n")

    finalize_bundle(bundle)
    return bundle


def _fake_playback(window):
    """Stand in for the file stream — the placeholder MP4 is not decodable."""
    manager = Mock()
    manager.is_playing = Mock(return_value=True)
    manager.play_pause = Mock()
    manager.seek_to_frame = Mock(return_value=100)
    manager.seek_to_time = Mock()
    window.coordinator.connect_stream = Mock(return_value=True)
    # load_recording() resets first; the real disconnect would null the
    # mocked manager before playback wiring is exercised.
    window.coordinator.disconnect_stream = Mock()
    window.coordinator.stream_manager = manager
    return manager


class TestLoading:
    def test_loading_a_bundle_fills_the_window(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)

        assert window.load_recording(os.path.join(bundle, "rec_0001.mp4")) is True

        # The stored detections are there the moment it loads.
        assert window.gallery_widget.gallery_list.count() == 2
        assert len(window._tracks_by_key) == 2
        header = window.ui.headerLabel.text()
        assert "TEXSAR-01" in header and "2" in header
        assert "TEXSAR-01" in window.windowTitle()

    def test_stored_positions_pin_the_map(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)
        pinned = []
        window.map_view.add_detection = pinned.append

        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))

        assert len(pinned) == 2
        assert pinned[0]["location"]["lat"] == pytest.approx(30.25)
        assert pinned[0]["track_key"] == "replay-0"

    def test_telemetry_replays_through_the_sidecar_srt(self, window, tmp_path):
        """Same path as a DJI card clip: sidecar discovered, HUD on the playhead."""
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)

        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))

        assert window.telemetry_coordinator.is_available is True
        assert window.telemetry_coordinator.position_at(2.0) == pytest.approx(
            (30.26, -97.75)
        )

    def test_a_plain_video_still_plays_without_a_record(self, window, tmp_path):
        """A loose MP4 has no bundle - the window plays it, gallery empty."""
        loose = tmp_path / "DJI_0042.MP4"
        loose.write_bytes(b"\x00")
        _fake_playback(window)

        assert window.load_recording(str(loose)) is True
        assert window.gallery_widget.gallery_list.count() == 0

    def test_loading_a_second_recording_replaces_the_first(self, window, tmp_path):
        first = _make_bundle(tmp_path / "a", detections=2)
        second = _make_bundle(tmp_path / "b", detections=1)
        _fake_playback(window)

        window.load_recording(os.path.join(first, "rec_0001.mp4"))
        _fake_playback(window)
        window.load_recording(os.path.join(second, "rec_0001.mp4"))

        assert window.gallery_widget.gallery_list.count() == 1
        assert len(window._tracks_by_key) == 1

    def test_missing_thumbnails_skip_gallery_rows(self, window, tmp_path):
        bundle = _make_bundle(tmp_path, detections=1)
        os.remove(os.path.join(bundle, "detections", "detection_0000.jpg"))
        _fake_playback(window)

        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))

        assert window.gallery_widget.gallery_list.count() == 0


class TestJumpToDetection:
    def test_gallery_click_pauses_and_seeks_to_the_stored_frame(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        manager = _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))
        track = window._tracks_by_key["replay-1"]

        window._jump_to_track(track)

        manager.play_pause.assert_called_once()
        manager.seek_to_frame.assert_called_once_with(119)  # 120 - 1

    def test_map_pin_click_jumps_too(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        manager = _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))

        window._on_pin_clicked("replay-0")

        manager.seek_to_frame.assert_called_once_with(89)

    def test_playhead_drives_the_bar_and_the_hud(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))
        sampled = []
        window.telemetry_coordinator.on_position_changed = sampled.append

        window._on_stream_info({"current_time": 2.0, "total_time": 10.0})

        assert sampled == [2.0]
        assert window.playback_controls.current_time == 2.0


class TestZoomOnClick:
    """Clicking a detection lands on it, zoomed."""

    def test_click_arms_a_zoom_consumed_by_the_sought_frame(self, window, tmp_path):
        """Request/consume, not a timed guess: the display can only zoom
        once it actually holds the frame the seek produced."""
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))
        focused = []
        window.video_display.focus_on = focused.append

        window._jump_to_track(window._tracks_by_key["replay-0"])
        # Armed, not yet applied - no frame has arrived.
        assert window._pending_focus is not None
        assert focused == []

        window._on_frame(np.zeros((720, 1280, 3), dtype=np.uint8), 0.0, 89)

        assert len(focused) == 1
        target = focused[0]
        # Centred on the stored detection, in the frame it was measured in.
        assert target.center_xy == (110, 132)
        assert target.reference_size == (1280, 720)
        # Consumed once: later frames must not re-zoom and fight the operator.
        window._on_frame(np.zeros((720, 1280, 3), dtype=np.uint8), 0.0, 90)
        assert len(focused) == 1

    def test_map_pin_click_zooms_too(self, window, tmp_path):
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))

        window._on_pin_clicked("replay-1")

        assert window._pending_focus is not None
        assert window._pending_focus.center_xy == (150, 132)

    def test_a_record_without_pixel_geometry_does_not_guess(self, window, tmp_path):
        """A flight detection stored before any frame has only a normalized
        bbox; zooming somewhere arbitrary would be worse than not zooming."""
        bundle = _make_bundle(tmp_path)
        _fake_playback(window)
        window.load_recording(os.path.join(bundle, "rec_0001.mp4"))
        track = window._tracks_by_key["replay-0"]
        track.frame_resolution = (0, 0)

        window._jump_to_track(track)

        assert window._pending_focus is None

    def test_loading_another_recording_disarms_a_pending_zoom(self, window, tmp_path):
        first = _make_bundle(tmp_path / "a")
        _fake_playback(window)
        window.load_recording(os.path.join(first, "rec_0001.mp4"))
        window._jump_to_track(window._tracks_by_key["replay-0"])
        assert window._pending_focus is not None

        second = _make_bundle(tmp_path / "b")
        _fake_playback(window)
        window.load_recording(os.path.join(second, "rec_0001.mp4"))

        assert window._pending_focus is None


class TestReadability:
    """Field report: the HUD was unreadable and claimed stale data."""

    def test_no_stale_badge_on_a_replay(self, window):
        """A replay's fixes are never late - they are where the playhead is."""
        assert window.telemetry_hud._staleness_enabled is False

    def test_the_hud_keeps_its_background_after_a_fix_arrives(self, window):
        """_clear_stale used to blank the whole sheet, stripping the backing."""
        hud = window.telemetry_hud
        hud.apply_envelope({"aircraft_latitude": 30.0, "aircraft_longitude": -97.0})

        sheet = hud.styleSheet()
        assert "background-color" in sheet
        assert "rgba(0, 0, 0" in sheet

    def test_the_hud_sits_off_the_bottom_edge(self, window):
        """Flush against the edge reads as a window artifact, not an overlay."""
        window.video_display.resize(800, 600)
        window._reposition_hud()

        hud = window.telemetry_hud
        gap = window.video_display.height() - (hud.y() + hud.height())
        assert gap == window._HUD_BOTTOM_MARGIN

    def test_the_map_gets_enough_height_to_place_the_flight(self, window):
        """A sliver of basemap tells the operator nothing about the flight,
        but the gallery is the column's working surface - roughly 2:1."""
        assert window.map_view.minimumHeight() >= 250
        # Splitter sizes only settle once laid out.
        window.resize(1280, 900)
        window.show()
        QApplication.processEvents()
        try:
            gallery_size, map_size = window.ui.sideSplitter.sizes()
            assert map_size >= 250, "the map is back to a sliver"
            assert gallery_size > map_size, "the gallery should lead"
            ratio = gallery_size / map_size
            assert 1.5 <= ratio <= 2.6, f"unexpected split ratio {ratio:.2f}"
        finally:
            window.hide()


class TestOwnExperience:
    """What makes replay replay: no analysis apparatus at all."""

    def test_the_window_has_no_detector_to_run(self, window):
        assert not hasattr(window, "algorithm_widget")
        assert not hasattr(window, "processing_worker")

    def test_the_record_toggle_is_hidden(self, window):
        """You don't record a replay."""
        assert window.playback_controls.record_btn.isVisibleTo(
            window.playback_controls
        ) is False

    def test_open_replay_reuses_one_window(self, qapp, tmp_path, monkeypatch):
        bundle = _make_bundle(tmp_path)
        video = os.path.join(bundle, "rec_0001.mp4")
        app = QApplication.instance()
        had = hasattr(app, "_replay_window")
        previous = getattr(app, "_replay_window", None)
        if had:
            delattr(app, "_replay_window")
        try:
            monkeypatch.setattr(
                "core.controllers.streaming.ReplayWindow.ReplayWindow.load_recording",
                lambda self, path: True,
            )
            first = open_replay(video)
            second = open_replay(video)

            assert first is second
            assert getattr(app, "_replay_window") is first
            first.close()
            QApplication.processEvents()
        finally:
            if had:
                app._replay_window = previous
            elif hasattr(app, "_replay_window"):
                delattr(app, "_replay_window")
