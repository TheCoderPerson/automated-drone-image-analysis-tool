"""Unit tests for RecordingLibrary — the registry behind "Open Recording…"."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from PySide6.QtCore import QSettings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from core.services.streaming.RecordingLibrary import RecordingLibrary  # noqa: E402
from core.services.streaming.RecordingSessionService import (  # noqa: E402
    DetectionRecord,
    RecordingSessionConfig,
    RecordingSessionWriter,
)


@pytest.fixture
def library(tmp_path):
    """A library backed by an INI file, never the user's real store."""
    settings = QSettings(
        str(tmp_path / "library.ini"), QSettings.IniFormat
    )
    return RecordingLibrary(settings=settings)


def _bundle(root, label="TEXSAR-01", detections=1):
    writer = RecordingSessionWriter()
    bundle = writer.start_session(RecordingSessionConfig(
        root_dir=str(root), algorithm="ADIAT Flight",
        feed={"label": label},
    ))
    with open(os.path.join(bundle, "rec.mp4"), "wb") as fp:
        fp.write(b"\x00")
    for index in range(detections):
        writer.append_detection(DetectionRecord(
            track_id=index, bbox=(10, 10, 8, 8),
            thumbnail=np.full((10, 10, 3), 90, dtype=np.uint8),
        ))
    writer.finalize()
    return bundle


class TestRemember:
    def test_newest_first(self, library, tmp_path):
        first = _bundle(tmp_path / "a", "ALPHA")
        second = _bundle(tmp_path / "b", "BRAVO")

        library.remember(first)
        library.remember(second)

        titles = [e["title"] for e in library.recent()]
        assert titles == ["BRAVO", "ALPHA"]

    def test_re_remembering_moves_to_the_front_without_duplicating(self, library, tmp_path):
        first = _bundle(tmp_path / "a", "ALPHA")
        second = _bundle(tmp_path / "b", "BRAVO")
        library.remember(first)
        library.remember(second)

        library.remember(first)

        entries = library.recent()
        assert [e["title"] for e in entries] == ["ALPHA", "BRAVO"]
        assert len(entries) == 2

    def test_the_list_is_capped(self, library, tmp_path):
        from core.services.streaming import RecordingLibrary as module

        for index in range(module._MAX_ENTRIES + 5):
            path = tmp_path / f"fake_{index:03d}"
            path.mkdir()
            library.remember(str(path))

        assert len(library._read_paths()) == module._MAX_ENTRIES

    def test_empty_paths_are_ignored(self, library):
        library.remember("")
        assert library.recent() == []


class TestRecent:
    def test_entries_carry_what_the_picker_shows(self, library, tmp_path):
        bundle = _bundle(tmp_path, "TEXSAR-01", detections=2)
        library.remember(bundle)

        entry = library.recent()[0]

        assert entry["title"] == "TEXSAR-01"
        assert entry["detections"] == 2
        assert entry["video"] == os.path.join(bundle, "rec.mp4")
        assert entry["started_at"]

    def test_deleted_bundles_drop_off_and_are_pruned(self, library, tmp_path):
        import shutil

        keep = _bundle(tmp_path / "keep", "KEEP")
        gone = _bundle(tmp_path / "gone", "GONE")
        library.remember(keep)
        library.remember(gone)
        shutil.rmtree(gone)

        entries = library.recent()

        assert [e["title"] for e in entries] == ["KEEP"]
        # Pruned from storage too, not just filtered from this read.
        assert library._read_paths() == [os.path.abspath(keep)]

    def test_a_bundle_without_video_lists_with_video_none(self, library, tmp_path):
        writer = RecordingSessionWriter()
        bundle = writer.start_session(RecordingSessionConfig(root_dir=str(tmp_path)))
        writer.append_detection(DetectionRecord(
            track_id=0, bbox=(1, 1, 2, 2),
            thumbnail=np.full((8, 8, 3), 10, dtype=np.uint8),
        ))
        writer.finalize()
        library.remember(bundle)

        assert library.recent()[0]["video"] is None

    def test_corrupt_storage_reads_as_empty(self, library):
        library._settings.setValue("library/recent", "{not json")

        assert library.recent() == []
