"""Reaching the end of a video file is an ending, not five failures.

Field report from a replay: watching a recording to its end logged
``Failed to read frame (1/5)`` … ``(4/5)`` and spun for half a second
before pausing. The reader discovered EOF only by exhausting the budget
it keeps for *transient* decode errors. It now ends immediately and
quietly when the position says there is nothing left, and keeps the
retries for what they were meant for.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.RTMPStreamService import RTMPStreamService  # noqa: E402


def _service(*, total_frames: int, position: int):
    """A service positioned in a file, with capture and locks stubbed."""
    service = RTMPStreamService.__new__(RTMPStreamService)
    service.logger = Mock()
    service._is_file = True
    service._total_frames = total_frames
    service._current_frame_pos = position
    service._total_duration = total_frames / 30.0 if total_frames else 0.0
    service._awaiting_seek_frame = False
    service._active_seek_id = None
    service._is_playing = True
    service._cap = Mock()

    import threading
    service._playback_lock = threading.RLock()

    service.videoPositionChanged = Mock()
    service.streamStatsChanged = Mock()
    service.seekCompleted = Mock()
    return service


class TestEndOfFileDetection:
    def test_at_the_last_frame_is_the_end(self):
        """The position has already advanced past the last decoded frame."""
        assert _service(total_frames=100, position=99)._is_at_end_of_file() is True

    def test_past_the_count_is_the_end(self):
        assert _service(total_frames=100, position=140)._is_at_end_of_file() is True

    def test_mid_file_is_not_the_end(self):
        """A hiccup with frames still ahead must keep its retries."""
        assert _service(total_frames=100, position=40)._is_at_end_of_file() is False

    @pytest.mark.parametrize("total", [0, -1])
    def test_an_unknown_frame_count_defers_to_the_retry_path(self, total):
        """Some containers report no frame count; do not guess from it."""
        assert _service(total_frames=total, position=10)._is_at_end_of_file() is False


class TestPauseAtEnd:
    def test_it_lands_paused_on_the_last_frame(self):
        service = _service(total_frames=100, position=99)

        service._pause_at_end_of_file()

        assert service._is_playing is False
        # Rewound onto the last real frame so the operator can scrub back in.
        import cv2
        service._cap.set.assert_called_once_with(cv2.CAP_PROP_POS_FRAMES, 99)
        assert service._current_frame_pos == 99

    def test_it_reports_the_end_to_the_ui(self):
        service = _service(total_frames=100, position=99)

        service._pause_at_end_of_file()

        service.videoPositionChanged.emit.assert_called_once_with(
            service._total_duration, service._total_duration
        )
        service.streamStatsChanged.emit.assert_called_once_with({"is_playing": False})

    def test_it_does_not_disconnect(self):
        """The capture stays open - scrubbing back needs it."""
        service = _service(total_frames=100, position=99)

        service._pause_at_end_of_file()

        service._cap.release.assert_not_called()

    def test_a_pending_seek_is_reported_as_failed(self):
        """Otherwise the UI waits forever for a frame that cannot arrive."""
        service = _service(total_frames=100, position=99)
        service._awaiting_seek_frame = True
        service._active_seek_id = 7

        service._pause_at_end_of_file()

        service.seekCompleted.emit.assert_called_once_with(7, -1, False)
        assert service._awaiting_seek_frame is False

    def test_no_seek_pending_reports_nothing(self):
        service = _service(total_frames=100, position=99)

        service._pause_at_end_of_file()

        service.seekCompleted.emit.assert_not_called()

    def test_it_is_quiet(self):
        """An ending is not a warning."""
        service = _service(total_frames=100, position=99)

        service._pause_at_end_of_file()

        service.logger.warning.assert_not_called()
        service.logger.error.assert_not_called()
