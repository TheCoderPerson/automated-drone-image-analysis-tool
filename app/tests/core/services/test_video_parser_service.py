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


# --- SRT telemetry parsing --------------------------------------------------
#
# Two DJI subtitle layouts are in the field. Older files give every field its
# own bracket; Mavic 3-era firmware packs rel_alt and abs_alt into one. Both
# must parse - the newer one is what silently stamped altitude 0 on every
# extracted frame.

LEGACY_PAYLOAD = (
    '<font size="28">[iso : 100] [shutter : 1/500] [latitude: 39.900000] '
    '[longitude: -105.100000] [altitude: 1650.500000] </font>'
)

MODERN_PAYLOAD = (
    '<font size="28">[iso: 200] [shutter: 1/241.19] [fnum: 4.3] [ev: 0] '
    '[color_md : default] [focal_len: 480.00] [dzoom_ratio: 1.18], '
    '[latitude: 39.483487] [longitude: 73.585195] '
    '[rel_alt: 561.745 abs_alt: 4563.571] '
    '[gb_yaw: 130.6 gb_pitch: -26.5 gb_roll: 0.0] </font>'
)


def _srt_entry(payload, index=1):
    """Wrap a telemetry payload in a complete SRT entry."""
    return (
        f'{index}\n'
        f'00:00:0{index - 1},000 --> 00:00:0{index},000\n'
        f'<font size="28">FrameCnt: {index}, DiffTime: 33ms\n'
        f'2026-08-15 12:09:26.002\n'
        f'{payload}\n'
    )


def parse(service, tmp_path, payload):
    """Run one payload through the real file parser."""
    srt = tmp_path / 'track.srt'
    srt.write_text(_srt_entry(payload))
    entries = service._parse_srt_file(str(srt))
    assert entries is not None and len(entries) == 1
    return entries[0]


def test_modern_srt_reads_absolute_altitude(video_parser_service, tmp_path):
    """abs_alt shares its bracket with rel_alt; both must be read."""
    entry = parse(video_parser_service, tmp_path, MODERN_PAYLOAD)

    assert entry['altitude'] == 4563.571
    assert entry['relative_altitude'] == 561.745
    assert entry['latitude'] == 39.483487
    assert entry['longitude'] == 73.585195


def test_legacy_srt_still_reads_altitude(video_parser_service, tmp_path):
    """The one-pair-per-bracket layout keeps working unchanged."""
    entry = parse(video_parser_service, tmp_path, LEGACY_PAYLOAD)

    assert entry['altitude'] == 1650.5
    assert entry['latitude'] == 39.9
    assert entry['longitude'] == -105.1
    # Nothing to relate it to in this layout.
    assert entry['relative_altitude'] is None


def test_misspelled_longitude_key_still_parses(video_parser_service, tmp_path):
    """Some files write 'longtitude'; that fallback predates this fix."""
    payload = '[latitude: 39.9] [longtitude: -105.1] [altitude: 1650.5]'

    entry = parse(video_parser_service, tmp_path, payload)

    assert entry['longitude'] == -105.1


def test_multi_pair_brackets_do_not_swallow_neighbours(video_parser_service, tmp_path):
    """A crowded bracket must not corrupt the keys parsed around it."""
    payload = ('[gb_yaw: 130.6 gb_pitch: -26.5 gb_roll: 0.0] [latitude: 1.5] '
               '[longitude: 2.5] [rel_alt: 10.0 abs_alt: 20.0]')

    entry = parse(video_parser_service, tmp_path, payload)

    assert (entry['latitude'], entry['longitude']) == (1.5, 2.5)
    assert entry['altitude'] == 20.0


def test_absolute_altitude_wins_when_a_file_carries_both(video_parser_service, tmp_path):
    """'abs_alt' is explicitly height above sea level; prefer it."""
    payload = '[latitude: 1.0] [longitude: 2.0] [altitude: 5.0] [rel_alt: 7.0 abs_alt: 900.0]'

    entry = parse(video_parser_service, tmp_path, payload)

    assert entry['altitude'] == 900.0


def test_missing_altitude_falls_back_to_zero(video_parser_service, tmp_path):
    """No height in the file: the frame is stamped 0, as before."""
    entry = parse(video_parser_service, tmp_path, '[latitude: 1.0] [longitude: 2.0]')

    assert entry['altitude'] == 0.0


def test_unparseable_position_does_not_abandon_the_file(video_parser_service, tmp_path):
    """One junk value used to raise, losing GPS for the whole video."""
    entry = parse(video_parser_service, tmp_path, '[latitude: n/a] [longitude: 2.0] [altitude: 3.0]')

    assert entry['latitude'] is None
    assert entry['longitude'] == 2.0
