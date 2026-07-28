"""Tests for the shared stream source-label registry.

The label -> :class:`StreamType` mapping is the single point that the
stream controls, the setup guide, and :class:`StreamCoordinator` all
resolve through, so it carries the ADIAT Flight source's first-class
status. These tests pin the canonical labels and the legacy aliases.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.RTMPStreamService import (  # noqa: E402
    SOURCE_TYPE_ADIAT_FLIGHT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_HDMI,
    SOURCE_TYPE_RTMP,
    StreamType,
    is_live_source,
    stream_type_from_source_label,
)


@pytest.mark.parametrize(
    "label,expected",
    [
        (SOURCE_TYPE_FILE, StreamType.FILE),
        (SOURCE_TYPE_HDMI, StreamType.HDMI_CAPTURE),
        (SOURCE_TYPE_RTMP, StreamType.RTMP),
        (SOURCE_TYPE_ADIAT_FLIGHT, StreamType.WEBRTC),
    ],
)
def test_canonical_labels_resolve(label, expected):
    assert stream_type_from_source_label(label) is expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("file", StreamType.FILE),
        ("HDMI CAPTURE", StreamType.HDMI_CAPTURE),
        ("  adiat flight  ", StreamType.WEBRTC),
        ("rtmp", StreamType.RTMP),
        ("hls", StreamType.HLS),
        ("webrtc", StreamType.WEBRTC),
    ],
)
def test_aliases_and_case_insensitivity(label, expected):
    """Older persisted values and short aliases must keep resolving."""
    assert stream_type_from_source_label(label) is expected


def test_stream_type_passes_through():
    assert stream_type_from_source_label(StreamType.WEBRTC) is StreamType.WEBRTC


@pytest.mark.parametrize("value", ["not a source", "", None, 42, object()])
def test_unknown_values_fall_back_to_default(value):
    """A stale setting degrades to File rather than breaking the window."""
    assert stream_type_from_source_label(value) is StreamType.FILE
    assert stream_type_from_source_label(value, StreamType.RTMP) is StreamType.RTMP


@pytest.mark.parametrize(
    "stream_type,expected",
    [
        (StreamType.FILE, False),
        (StreamType.HDMI_CAPTURE, True),
        (StreamType.RTMP, True),
        (StreamType.HLS, True),
        (StreamType.WEBRTC, True),
        (None, False),
    ],
)
def test_is_live_source(stream_type, expected):
    """ADIAT Flight is a live source: no timeline, capped cadence estimate."""
    assert is_live_source(stream_type) is expected
