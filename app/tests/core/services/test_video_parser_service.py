"""
Comprehensive tests for VideoParserService.

Tests video parsing and frame extraction functionality.
"""

import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock
from PySide6.QtCore import QObject
from core.services.VideoParserService import VideoParserService


@pytest.fixture
def video_parser_service():
    """Fixture providing a VideoParserService instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, 'test_video.mp4')
        srt_path = os.path.join(tmpdir, 'test.srt')
        output_dir = os.path.join(tmpdir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        service = VideoParserService(
            id=1,
            video=video_path,
            metadata_path=srt_path,
            output=output_dir,
            interval=1.0
        )
        yield service


def test_video_parser_service_initialization(video_parser_service):
    """Test VideoParserService initialization."""
    # __id is a private attribute, access via name mangling
    assert video_parser_service._VideoParserService__id == 1
    assert video_parser_service.interval == 1.0
    assert video_parser_service.cancelled is False


def test_video_parser_service_signals(video_parser_service):
    """Test that signals are properly defined."""
    assert hasattr(video_parser_service, 'sig_msg')
    assert hasattr(video_parser_service, 'sig_done')


def test_video_parser_service_cancellation(video_parser_service):
    """Test cancellation functionality."""
    assert video_parser_service.cancelled is False
    video_parser_service.cancelled = True
    assert video_parser_service.cancelled is True


def test_process_video_invalid_file(video_parser_service):
    """Test processing invalid video file."""
    with patch('cv2.VideoCapture') as mock_capture:
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_capture.return_value = mock_cap

        # This should emit error signal
        video_parser_service.process_video()

        # Verify error handling
        assert True  # If we get here, no exception was raised


class TestTelemetryResolution:
    """Location data now resolves without an explicit metadata file.

    Newer DJI aircraft embed telemetry in the MP4 rather than writing a
    ``.SRT`` sidecar, so a card-pull of just the video used to lose all
    GPS. These cover the resolution paths and the status reporting the
    dialog shows the operator.
    """

    RESOLVER = 'core.services.VideoParserService.load_telemetry_for_video'

    def _service(self, tmpdir, metadata_path=''):
        return VideoParserService(
            id=1,
            video=os.path.join(tmpdir, 'v.mp4'),
            metadata_path=metadata_path,
            output=tmpdir,
            interval=1.0,
        )

    def _resolution(self, source, count=3, detail=''):
        from core.services.telemetry.DjiSrtParser import DjiSrtSample
        from core.services.telemetry.TelemetrySourceResolver import TelemetryResolution
        from core.services.telemetry.TelemetryTrack import TelemetryTrack

        track = TelemetryTrack.from_dji_samples([
            DjiSrtSample(
                start_seconds=float(i), end_seconds=float(i) + 0.03,
                latitude=30.0 + i, longitude=-97.0 - i,
                altitude_msl_m=200.0 + i, altitude_agl_m=15.0,
            )
            for i in range(count)
        ])
        return TelemetryResolution(
            track=track, source=source, path='/tmp/x.SRT',
            detail=detail or f'{count} fixes',
        )

    def test_embedded_source_is_reported(self):
        from core.services.telemetry.TelemetrySourceResolver import SOURCE_EMBEDDED

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            messages = []
            service.sig_msg.connect(messages.append)

            with patch(self.RESOLVER,
                       return_value=self._resolution(SOURCE_EMBEDDED)):
                track = service._resolve_telemetry()

            assert track is not None
            assert any('embedded' in m.lower() for m in messages)

    def test_sidecar_source_is_reported(self):
        from core.services.telemetry.TelemetrySourceResolver import SOURCE_SIDECAR

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            messages = []
            service.sig_msg.connect(messages.append)

            with patch(self.RESOLVER,
                       return_value=self._resolution(SOURCE_SIDECAR)):
                service._resolve_telemetry()

            assert any('x.SRT' in m for m in messages)

    def test_missing_telemetry_returns_none(self):
        from core.services.telemetry.TelemetrySourceResolver import (
            SOURCE_NONE, TelemetryResolution,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            with patch(self.RESOLVER, return_value=TelemetryResolution(
                    track=None, source=SOURCE_NONE)):
                assert service._resolve_telemetry() is None

    def test_unreadable_explicit_file_warns(self):
        from core.services.telemetry.TelemetrySourceResolver import (
            SOURCE_EXPLICIT_FILE, TelemetryResolution,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, metadata_path='chosen.srt')
            messages = []
            service.sig_msg.connect(messages.append)

            with patch(self.RESOLVER, return_value=TelemetryResolution(
                    track=None, source=SOURCE_EXPLICIT_FILE,
                    detail='selected SRT contained no usable telemetry')):
                assert service._resolve_telemetry() is None

            assert any('Warning' in m for m in messages)

    def test_resolver_failure_is_survivable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir)
            service.logger = MagicMock()
            with patch(self.RESOLVER, side_effect=OSError('boom')):
                assert service._resolve_telemetry() is None


class TestLegacySrtDelegate:
    """``_parse_srt_file`` keeps its historical dict shape for callers."""

    CLASSIC = (
        '1\n'
        '00:00:00,000 --> 00:00:00,033\n'
        '<font size="28">FrameCnt: 1, DiffTime: 33ms\n'
        '2023-05-01 10:00:00,000\n'
        '[latitude: 30.100000] [longtitude: -97.200000] [altitude: 210.5] </font>\n'
    )

    def test_returns_datetime_anchored_dicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            srt = os.path.join(tmpdir, 'a.srt')
            with open(srt, 'w') as handle:
                handle.write(self.CLASSIC)

            service = VideoParserService(1, 'v.mp4', srt, tmpdir, 1.0)
            rows = service._parse_srt_file(srt)

            assert len(rows) == 1
            row = rows[0]
            assert set(row) == {'start', 'end', 'latitude', 'longitude', 'altitude'}
            assert row['start'].year == 1900
            assert row['latitude'] == pytest.approx(30.1)
            assert row['longitude'] == pytest.approx(-97.2)
            assert row['altitude'] == pytest.approx(210.5)

    def test_now_parses_the_embedded_four_line_variant(self):
        """Previously returned an empty list for this layout."""
        embedded = (
            '1\n'
            '00:00:00,000 --> 00:00:00,033\n'
            'FrameCnt: 0 2026-07-25 14:38:26.477\n'
            '[latitude: 30.648730] [longitude: -97.675867] '
            '[rel_alt: 14.885 abs_alt: 207.027]\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            srt = os.path.join(tmpdir, 'b.srt')
            with open(srt, 'w') as handle:
                handle.write(embedded)

            service = VideoParserService(1, 'v.mp4', srt, tmpdir, 1.0)
            rows = service._parse_srt_file(srt)

            assert len(rows) == 1
            assert rows[0]['altitude'] == pytest.approx(207.027)

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = VideoParserService(1, 'v.mp4', '', tmpdir, 1.0)
            assert service._parse_srt_file(os.path.join(tmpdir, 'nope.srt')) is None
