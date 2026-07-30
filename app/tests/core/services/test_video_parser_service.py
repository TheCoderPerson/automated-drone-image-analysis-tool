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


class TestCsvFlightLog:
    """CSV reading is shared with the streaming window's metadata-file path.

    The shape this method returns is load-bearing: ``process_video`` and
    ``_find_closest_csv_entry`` have consumed ``utc_time`` /
    ``latitude`` / ``longitude`` / ``altitude_m`` since the Skydio path was
    added, so the delegation must not change it.
    """

    SKYDIO = (
        'Datetime (UTC),Latitude,Longitude,GPS Altitude (ft MSL)\n'
        '2026-07-25T14:38:26Z,30.648730,-97.675867,679.2\n'
        '2026-07-25T14:38:27Z,30.648740,-97.675877,682.5\n'
    )

    def _service(self, tmpdir, csv_path):
        return VideoParserService(1, os.path.join(tmpdir, 'v.mp4'),
                                  csv_path, tmpdir, 1.0)

    def _write(self, tmpdir, text, name='flight.csv'):
        path = os.path.join(tmpdir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def test_detects_the_csv_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, 'log.csv')
            assert service._detect_metadata_format('log.csv') == 'csv'
            assert service._detect_metadata_format('a.SRT') == 'srt'
            assert service._detect_metadata_format('') is None

    def test_returns_the_historical_entry_shape(self):
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = self._write(tmpdir, self.SKYDIO)
            service = self._service(tmpdir, csv_path)
            start = datetime(2026, 7, 25, 14, 38, 26, tzinfo=timezone.utc)

            with patch('core.services.VideoParserService.get_video_creation_time',
                       return_value=start):
                video_start, entries = service._parse_csv_flight_log(
                    csv_path, 'v.mp4')

            assert video_start == start
            assert len(entries) == 2
            entry = entries[0]
            assert {'utc_time', 'latitude', 'longitude', 'altitude_m'} <= set(entry)
            assert entry['latitude'] == pytest.approx(30.648730)
            # Feet in the log, metres in the entry.
            assert entry['altitude_m'] == pytest.approx(679.2 * 0.3048)

    def test_entries_feed_the_closest_match_lookup(self):
        """The delegated rows must still be sortable/searchable by time."""
        from datetime import datetime, timedelta, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = self._write(tmpdir, self.SKYDIO)
            service = self._service(tmpdir, csv_path)
            start = datetime(2026, 7, 25, 14, 38, 26, tzinfo=timezone.utc)

            with patch('core.services.VideoParserService.get_video_creation_time',
                       return_value=start):
                _video_start, entries = service._parse_csv_flight_log(
                    csv_path, 'v.mp4')

            match = service._find_closest_csv_entry(
                entries, start + timedelta(seconds=1))
            assert match['latitude'] == pytest.approx(30.648740)

    def test_missing_columns_are_reported_and_abort(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = self._write(tmpdir, 'Time,Alt\n1,2\n')
            service = self._service(tmpdir, csv_path)
            messages = []
            service.sig_msg.connect(messages.append)

            assert service._parse_csv_flight_log(csv_path, 'v.mp4') is None
            assert any('missing required columns' in m for m in messages)

    def test_a_zero_coordinate_is_a_real_position(self):
        """Regression: the CSV branch tested coordinates for truth, so a
        flight on the prime meridian or the equator lost its geotag. The SRT
        branch in the same method already used ``is not None``."""
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = self._write(tmpdir, (
                'Datetime (UTC),Latitude,Longitude,GPS Altitude (ft MSL)\n'
                '2026-07-25T14:38:26Z,0.0,0.0,679.2\n'
            ))
            service = self._service(tmpdir, csv_path)
            start = datetime(2026, 7, 25, 14, 38, 26, tzinfo=timezone.utc)

            with patch('core.services.VideoParserService.get_video_creation_time',
                       return_value=start):
                _video_start, entries = service._parse_csv_flight_log(
                    csv_path, 'v.mp4')

            entry = entries[0]
            assert entry['latitude'] == 0.0 and entry['longitude'] == 0.0
            # The guard the frame loop applies must accept this row.
            assert (entry['latitude'] is not None
                    and entry['longitude'] is not None)

    def test_unreadable_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._service(tmpdir, 'nope.csv')
            messages = []
            service.sig_msg.connect(messages.append)

            assert service._parse_csv_flight_log(
                os.path.join(tmpdir, 'nope.csv'), 'v.mp4') is None
            assert any('Error' in m for m in messages)
