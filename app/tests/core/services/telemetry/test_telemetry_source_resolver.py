"""Tests for telemetry source resolution and embedded extraction.

Precedence under test: an explicitly chosen file beats a sidecar, which
beats a track embedded in the MP4. ffmpeg is mocked throughout; the
real-video check lives in ``test_dji_video_telemetry.py`` and skips when
the sample file is absent.
"""

import os
import tempfile

import pytest
from unittest.mock import MagicMock, patch

from core.services.telemetry.TelemetrySourceResolver import (
    SOURCE_EMBEDDED,
    SOURCE_EXPLICIT_FILE,
    SOURCE_NONE,
    SOURCE_SIDECAR,
    find_sidecar_srt,
    load_telemetry_for_video,
    read_srt_track,
)

SRT_TEXT = """\
1
00:00:00,000 --> 00:00:00,033
FrameCnt: 0 2026-07-25 14:38:26.477
[latitude: 30.648730] [longitude: -97.675867] [rel_alt: 14.885 abs_alt: 207.027]

2
00:00:00,033 --> 00:00:00,066
FrameCnt: 1 2026-07-25 14:38:26.511
[latitude: 30.648740] [longitude: -97.675877] [rel_alt: 15.885 abs_alt: 208.027]
"""

RESOLVER = "core.services.telemetry.TelemetrySourceResolver"


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "DJI_0001.MP4")
        with open(video, "wb") as handle:
            handle.write(b"not really a video")
        yield tmp, video


def _write(path, text=SRT_TEXT):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class TestSidecarDiscovery:
    def test_finds_uppercase_sidecar(self, workspace):
        tmp, video = workspace
        srt = _write(os.path.join(tmp, "DJI_0001.SRT"))
        assert find_sidecar_srt(video) == srt

    def test_finds_lowercase_sidecar(self, workspace):
        tmp, video = workspace
        srt = _write(os.path.join(tmp, "DJI_0001.srt"))
        assert os.path.samefile(find_sidecar_srt(video), srt)

    def test_absent_sidecar(self, workspace):
        _tmp, video = workspace
        assert find_sidecar_srt(video) is None

    def test_none_input(self):
        assert find_sidecar_srt(None) is None


class TestReadSrtTrack:
    def test_reads_a_valid_file(self, workspace):
        tmp, _video = workspace
        srt = _write(os.path.join(tmp, "t.srt"))
        track = read_srt_track(srt, source="test")
        assert len(track) == 2
        assert track.source == "test"

    def test_empty_file_yields_none(self, workspace):
        tmp, _video = workspace
        srt = _write(os.path.join(tmp, "empty.srt"), "")
        assert read_srt_track(srt, source="test") is None

    def test_missing_file_yields_none(self, workspace):
        tmp, _video = workspace
        assert read_srt_track(os.path.join(tmp, "nope.srt"), source="test") is None

    def test_tolerates_a_bom(self, workspace):
        tmp, _video = workspace
        srt = os.path.join(tmp, "bom.srt")
        with open(srt, "w", encoding="utf-8-sig") as handle:
            handle.write(SRT_TEXT)
        assert len(read_srt_track(srt, source="test")) == 2


class TestPrecedence:
    def test_explicit_file_wins_over_embedded(self, workspace):
        tmp, video = workspace
        chosen = _write(os.path.join(tmp, "chosen.srt"))

        with patch(f"{RESOLVER}.find_embedded_telemetry_stream") as find_embedded:
            resolution = load_telemetry_for_video(video, chosen)

        assert resolution.source == SOURCE_EXPLICIT_FILE
        assert resolution.found
        # The embedded route must not even be probed.
        find_embedded.assert_not_called()

    def test_sidecar_used_when_no_explicit_file(self, workspace):
        tmp, video = workspace
        _write(os.path.join(tmp, "DJI_0001.SRT"))

        with patch(f"{RESOLVER}.find_embedded_telemetry_stream") as find_embedded:
            resolution = load_telemetry_for_video(video, None)

        assert resolution.source == SOURCE_SIDECAR
        assert len(resolution.track) == 2
        find_embedded.assert_not_called()

    def test_embedded_used_when_nothing_else_exists(self, workspace):
        tmp, video = workspace
        extracted = _write(os.path.join(tmp, "extracted.srt"))

        with patch(f"{RESOLVER}.find_embedded_telemetry_stream", return_value=3), \
                patch(f"{RESOLVER}.extract_embedded_subtitles", return_value=extracted):
            resolution = load_telemetry_for_video(video, None)

        assert resolution.source == SOURCE_EMBEDDED
        assert len(resolution.track) == 2
        assert "embedded" in resolution.detail

    def test_extracted_temp_file_is_deleted(self, workspace):
        """The parsed track is what we keep; the temp file must not linger."""
        tmp, video = workspace
        extracted = _write(os.path.join(tmp, "extracted.srt"))

        with patch(f"{RESOLVER}.find_embedded_telemetry_stream", return_value=3), \
                patch(f"{RESOLVER}.extract_embedded_subtitles", return_value=extracted):
            load_telemetry_for_video(video, None)

        assert not os.path.exists(extracted)

    def test_no_telemetry_anywhere(self, workspace):
        _tmp, video = workspace
        with patch(f"{RESOLVER}.find_embedded_telemetry_stream", return_value=None):
            resolution = load_telemetry_for_video(video, None)
        assert resolution.source == SOURCE_NONE
        assert not resolution.found
        assert resolution.track is None

    def test_csv_choice_is_not_ours_to_resolve(self, workspace):
        """The Skydio CSV path stays in VideoParserService."""
        tmp, video = workspace
        csv_path = os.path.join(tmp, "flight.csv")
        with open(csv_path, "w") as handle:
            handle.write("Datetime (UTC),Latitude\n")
        resolution = load_telemetry_for_video(video, csv_path)
        assert resolution.source == SOURCE_NONE

    def test_unparseable_explicit_file_is_reported(self, workspace):
        tmp, video = workspace
        bad = _write(os.path.join(tmp, "bad.srt"), "not an srt at all")
        resolution = load_telemetry_for_video(video, bad)
        assert resolution.source == SOURCE_EXPLICIT_FILE
        assert not resolution.found
        assert "no usable telemetry" in resolution.detail

    def test_extraction_failure_degrades_gracefully(self, workspace):
        _tmp, video = workspace
        with patch(f"{RESOLVER}.find_embedded_telemetry_stream", return_value=3), \
                patch(f"{RESOLVER}.extract_embedded_subtitles", return_value=None):
            resolution = load_telemetry_for_video(video, None)
        assert resolution.source == SOURCE_NONE


class TestEmbeddedHelpers:
    """``VideoFileHelper`` stream discovery + demux, with ffmpeg mocked."""

    def test_finds_a_mov_text_stream(self):
        from helpers.VideoFileHelper import find_embedded_telemetry_stream

        probe = MagicMock(returncode=0, stdout=(
            '{"streams": ['
            '{"index": 0, "codec_type": "video", "codec_name": "hevc"},'
            '{"index": 3, "codec_type": "subtitle", "codec_name": "mov_text"}'
            ']}'
        ))
        with patch("helpers.VideoFileHelper._find_ffprobe", return_value="ffprobe"), \
                patch("helpers.VideoFileHelper.subprocess.run", return_value=probe):
            assert find_embedded_telemetry_stream("v.mp4") == 3

    def test_ignores_non_telemetry_subtitle_codecs(self):
        from helpers.VideoFileHelper import find_embedded_telemetry_stream

        probe = MagicMock(returncode=0, stdout=(
            '{"streams": [{"index": 2, "codec_type": "subtitle", '
            '"codec_name": "dvd_subtitle"}]}'
        ))
        with patch("helpers.VideoFileHelper._find_ffprobe", return_value="ffprobe"), \
                patch("helpers.VideoFileHelper.subprocess.run", return_value=probe):
            assert find_embedded_telemetry_stream("v.mp4") is None

    def test_no_subtitle_stream(self):
        from helpers.VideoFileHelper import find_embedded_telemetry_stream

        probe = MagicMock(returncode=0, stdout='{"streams": [{"index": 0, '
                                               '"codec_type": "video"}]}')
        with patch("helpers.VideoFileHelper._find_ffprobe", return_value="ffprobe"), \
                patch("helpers.VideoFileHelper.subprocess.run", return_value=probe):
            assert find_embedded_telemetry_stream("v.mp4") is None

    def test_missing_ffprobe_is_not_an_error(self):
        from helpers.VideoFileHelper import find_embedded_telemetry_stream

        with patch("helpers.VideoFileHelper._find_ffprobe", return_value=None):
            assert find_embedded_telemetry_stream("v.mp4") is None

    def test_extraction_returns_a_temp_file(self, workspace):
        from helpers.VideoFileHelper import extract_embedded_subtitles

        tmp, video = workspace

        def fake_run(cmd, **_kwargs):
            # Write to whatever output path ffmpeg was handed.
            _write(cmd[-1])
            return MagicMock(returncode=0, stderr="")

        with patch("helpers.VideoFileHelper._find_ffmpeg", return_value="ffmpeg"), \
                patch("helpers.VideoFileHelper.subprocess.run", side_effect=fake_run):
            out = extract_embedded_subtitles(video, stream_index=3)

        assert out is not None
        assert os.path.getsize(out) > 0
        os.unlink(out)

    def test_empty_extraction_is_treated_as_failure(self, workspace):
        """A track that demuxes to nothing must not look like success."""
        from helpers.VideoFileHelper import extract_embedded_subtitles

        _tmp, video = workspace
        with patch("helpers.VideoFileHelper._find_ffmpeg", return_value="ffmpeg"), \
                patch("helpers.VideoFileHelper.subprocess.run",
                      return_value=MagicMock(returncode=0, stderr="")):
            assert extract_embedded_subtitles(video, stream_index=3) is None

    def test_ffmpeg_failure_cleans_up(self, workspace):
        from helpers.VideoFileHelper import extract_embedded_subtitles

        _tmp, video = workspace
        with patch("helpers.VideoFileHelper._find_ffmpeg", return_value="ffmpeg"), \
                patch("helpers.VideoFileHelper.subprocess.run",
                      return_value=MagicMock(returncode=1, stderr="boom")):
            assert extract_embedded_subtitles(video, stream_index=3) is None
