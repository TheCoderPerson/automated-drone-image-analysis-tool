"""
VideoFileHelper.py - Utilities for handling video files with non-standard stream layouts.

Detects and works around MP4 files that embed a thumbnail/cover image as the
first video stream (e.g. Skydio X10), which causes OpenCV to grab the wrong track.
Also provides utilities for extracting metadata from video containers.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import json
import cv2
from datetime import datetime, timezone


def get_video_timing(video_path, logger=None):
    """Read a video's start time and duration from its container.

    Both come from one ffprobe call because both answer the same question —
    *which slice of wall-clock time does this video cover?* — which is what
    a CSV flight log's absolute UTC timestamps have to be aligned against
    (see :mod:`core.services.telemetry.FlightLogCsvParser`).

    Args:
        video_path: Path to the video file.
        logger: Optional logger for error reporting.

    Returns:
        ``(creation_time_utc, duration_seconds)``. Either element may be
        None when the container does not carry it.
    """
    try:
        ffprobe = _find_ffprobe()
        if not ffprobe:
            if logger:
                logger.error(_FFMPEG_MISSING_MSG)
            return (None, None)

        result = subprocess.run(
            [
                ffprobe, '-v', 'error',
                '-show_entries', 'format=duration:format_tags=creation_time',
                '-of', 'json', video_path
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            if logger:
                logger.error(f"ffprobe failed: {result.stderr}")
            return (None, None)

        container = json.loads(result.stdout).get('format', {})

        creation_time = None
        creation_time_str = container.get('tags', {}).get('creation_time')
        if creation_time_str:
            # Parse ISO 8601 UTC timestamp (e.g. "2024-02-24T19:09:57.000000Z")
            creation_time_str = creation_time_str.replace('Z', '+00:00')
            creation_time = datetime.fromisoformat(
                creation_time_str).astimezone(timezone.utc)

        duration = None
        try:
            duration_value = float(container.get('duration'))
            if duration_value > 0:
                duration = duration_value
        except (TypeError, ValueError):
            pass

        return (creation_time, duration)

    except Exception as e:
        if logger:
            logger.error(f"Error extracting video timing: {e}")
        return (None, None)


def get_video_creation_time(video_path, logger=None):
    """Extract creation_time from MP4 container via ffprobe.

    Args:
        video_path: Path to the video file.
        logger: Optional logger for error reporting.

    Returns:
        A timezone-aware UTC datetime, or None if extraction fails.
    """
    return get_video_timing(video_path, logger)[0]


# Common Homebrew binary directories that may not be in PATH when the app
# is launched outside a terminal (e.g. from Finder or a .app bundle).
_HOMEBREW_BIN_DIRS = [
    '/opt/homebrew/bin',      # Apple Silicon
    '/usr/local/bin',         # Intel Mac
]


def _which_with_fallback(name):
    """Find an executable by name, checking PATH then common Homebrew locations."""
    path = shutil.which(name)
    if path:
        return path
    if platform.system() == 'Darwin':
        for d in _HOMEBREW_BIN_DIRS:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _find_ffprobe():
    """Locate the ffprobe binary.

    Checks the system PATH first, then common Homebrew locations on macOS,
    then falls back to the imageio-ffmpeg bundled binary.

    Returns:
        Absolute path to ffprobe, or None if not found.
    """
    path = _which_with_fallback('ffprobe')
    if path:
        return path
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        # imageio-ffmpeg bundles ffprobe next to ffmpeg
        ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe')
        if os.path.isfile(ffprobe_path):
            return ffprobe_path
    except (ImportError, RuntimeError):
        pass
    return None


def _find_ffmpeg():
    """Locate the ffmpeg binary.

    Checks the system PATH first, then common Homebrew locations on macOS,
    then falls back to the imageio-ffmpeg bundled binary.

    Returns:
        Absolute path to ffmpeg, or None if not found.
    """
    path = _which_with_fallback('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        pass
    return None


_FFMPEG_MISSING_MSG = (
    "ffmpeg not found. Install via 'brew install ffmpeg' on macOS "
    "or add imageio-ffmpeg to your environment."
)

_FFMPEG_USER_MSG = (
    "This video requires ffmpeg to process, but ffmpeg was not found. "
    "Please install ffmpeg (on macOS: 'brew install ffmpeg') and restart the application."
)


def is_ffmpeg_available():
    """Check whether both ffmpeg and ffprobe can be found.

    Returns:
        True if both binaries are available, False otherwise.
    """
    return _find_ffprobe() is not None and _find_ffmpeg() is not None


def detect_thumbnail_track(cap) -> bool:
    """Check if OpenCV grabbed a thumbnail track instead of the real video.

    Some drones (e.g. Skydio X10) embed an MJPEG cover image as stream 0.
    OpenCV picks it up, reports an absurd FPS (the MP4 timescale), and fails
    to read a second frame. This function detects that situation.

    After calling, the capture position is reset to frame 0.

    Args:
        cap: An opened cv2.VideoCapture instance.

    Returns:
        True if the capture appears to be on a thumbnail track.
    """
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps > 1000:
        return True
    # Also check if second frame fails immediately
    ret2, _ = cap.read()
    if not ret2:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return True
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return False


def remux_to_main_track(source_path, logger=None):
    """Remux an MP4 to select the main video track, skipping thumbnail/cover tracks.

    Uses ffprobe to identify the real video stream (highest resolution, not
    marked as attached_pic), then ffmpeg to remux with -c copy (no re-encoding).

    Args:
        source_path: Path to the source MP4 file.
        logger: Optional logger instance with .info() and .error() methods.

    Returns:
        Path to a temporary remuxed MP4 file on success, None on failure.
        Caller is responsible for deleting the temp file when done.
    """
    try:
        ffprobe = _find_ffprobe()
        ffmpeg = _find_ffmpeg()
        if not ffprobe or not ffmpeg:
            if logger:
                logger.error(_FFMPEG_MISSING_MSG)
            return None

        # Use ffprobe to find the real video stream
        probe = subprocess.run(
            [ffprobe, '-v', 'error', '-show_streams', '-of', 'json', source_path],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode != 0:
            if logger:
                logger.error(f"ffprobe failed: {probe.stderr}")
            return None

        streams = json.loads(probe.stdout).get('streams', [])

        # Find best video stream: not attached_pic, highest resolution
        best_idx = None
        best_pixels = 0
        for s in streams:
            if s.get('codec_type') != 'video':
                continue
            if s.get('disposition', {}).get('attached_pic', 0):
                continue
            pixels = int(s.get('width', 0)) * int(s.get('height', 0))
            if pixels > best_pixels:
                best_pixels = pixels
                best_idx = s['index']

        if best_idx is None:
            if logger:
                logger.error("No suitable video stream found in file")
            return None

        # Remux to temp file (copy codec, no re-encoding)
        temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
        os.close(temp_fd)
        result = subprocess.run(
            [ffmpeg, '-y', '-i', source_path, '-map', f'0:{best_idx}', '-c', 'copy', temp_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            if logger:
                logger.error(f"ffmpeg remux failed: {result.stderr}")
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return None

        if logger:
            logger.info(f"Remuxed video to temp file: {temp_path}")
        return temp_path

    except Exception as e:
        if logger:
            logger.error(f"Remux error: {e}")
        return None


# Subtitle codecs DJI uses to embed per-frame telemetry inside the MP4.
# ``mov_text`` (tag ``tx3g``) is what current firmware writes; ``subrip``
# and ``text`` appear on some models and in remuxed files.
_TELEMETRY_SUBTITLE_CODECS = {'mov_text', 'subrip', 'text', 'ssa', 'ass'}


def find_embedded_telemetry_stream(video_path, logger=None):
    """Locate an embedded subtitle stream carrying telemetry.

    Newer DJI aircraft write per-frame GPS as a ``tx3g``/``mov_text``
    subtitle track inside the MP4 rather than (or as well as) a ``.SRT``
    sidecar, so an operator who copies only the video still has telemetry
    on the card — it just isn't visible without demuxing.

    Args:
        video_path: Path to the video file.
        logger: Optional logger with ``.debug()`` / ``.error()``.

    Returns:
        The ffmpeg stream index of the first telemetry-bearing subtitle
        stream, or None when the file has none (or ffprobe is missing).
    """
    try:
        ffprobe = _find_ffprobe()
        if not ffprobe:
            if logger:
                logger.debug(_FFMPEG_MISSING_MSG)
            return None

        probe = subprocess.run(
            [ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode != 0:
            if logger:
                logger.debug(f"ffprobe failed while scanning for telemetry: {probe.stderr}")
            return None

        for stream in json.loads(probe.stdout).get('streams', []):
            if stream.get('codec_type') != 'subtitle':
                continue
            codec = str(stream.get('codec_name', '')).lower()
            if codec in _TELEMETRY_SUBTITLE_CODECS:
                return stream.get('index')
        return None

    except Exception as e:
        if logger:
            logger.debug(f"Embedded telemetry scan error: {e}")
        return None


def extract_embedded_subtitles(video_path, logger=None, stream_index=None):
    """Demux an embedded telemetry subtitle track to a temporary ``.srt``.

    The extracted text is byte-for-byte the DJI SRT format, so it feeds
    the same parser as a sidecar file.

    Args:
        video_path: Path to the video file.
        logger: Optional logger with ``.info()`` / ``.debug()`` / ``.error()``.
        stream_index: Stream to extract; discovered automatically when None.

    Returns:
        Path to a temporary ``.srt`` on success, None on failure or when
        the file carries no telemetry track. **The caller owns the temp
        file** and must delete it, matching :func:`remux_to_main_track`.
    """
    temp_path = None
    try:
        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            if logger:
                logger.debug(_FFMPEG_MISSING_MSG)
            return None

        if stream_index is None:
            stream_index = find_embedded_telemetry_stream(video_path, logger)
        if stream_index is None:
            return None

        temp_fd, temp_path = tempfile.mkstemp(suffix='.srt')
        os.close(temp_fd)

        result = subprocess.run(
            [ffmpeg, '-y', '-v', 'error', '-i', str(video_path),
             '-map', f'0:{stream_index}', '-c:s', 'srt', temp_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            if logger:
                logger.debug(f"Subtitle extraction failed: {result.stderr}")
            _quiet_unlink(temp_path)
            return None

        # An empty result is a failure for our purposes — the track existed
        # but carried nothing parseable, and returning it would look like
        # success to the caller.
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            _quiet_unlink(temp_path)
            return None

        if logger:
            logger.info(
                f"Extracted embedded telemetry from stream {stream_index} to {temp_path}"
            )
        return temp_path

    except Exception as e:
        if logger:
            logger.debug(f"Embedded subtitle extraction error: {e}")
        if temp_path:
            _quiet_unlink(temp_path)
        return None


def get_video_device_tags(video_path, logger=None):
    """Return container tags that identify the capturing device.

    DJI writes the airframe into the MP4's ``encoder`` tag — e.g.
    ``"DJI DJI Matrice 4E"`` — which is the video equivalent of the EXIF
    Make/Model that image analysis matches against. Other vendors use
    ``make``/``model`` tags, so both are returned when present.

    Args:
        video_path: Path to the video file.
        logger: Optional logger.

    Returns:
        A dict of lower-cased tag name -> value (possibly empty). Never
        raises; an unreadable file yields ``{}``.
    """
    try:
        ffprobe = _find_ffprobe()
        if not ffprobe:
            return {}

        probe = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format_tags',
             '-of', 'json', str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode != 0:
            if logger:
                logger.debug(f"ffprobe device-tag read failed: {probe.stderr}")
            return {}

        tags = (json.loads(probe.stdout).get('format') or {}).get('tags') or {}
        return {
            str(key).lower(): str(value)
            for key, value in tags.items()
            if value is not None
        }

    except Exception as e:
        if logger:
            logger.debug(f"Device tag read error: {e}")
        return {}


def _quiet_unlink(path):
    """Delete ``path``, ignoring the case where it is already gone."""
    try:
        os.unlink(path)
    except OSError:
        pass
