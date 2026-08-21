"""Registry of recordings the app has made, so replay starts from a list.

Recordings used to be findable only by remembering which folder a
recording landed in and browsing to its MP4. Every finalized bundle now
registers itself here (both the streaming window's recordings and each
Flight tile's — they share :class:`RecordingService`), and the Replay
window's picker lists them newest-first with the context an operator
recognizes a flight by: feed label, date, detection count.

Only paths are persisted; everything shown is read live from each
bundle's own ``manifest.json``, so a renamed feed or an edited manifest
shows current truth, and a deleted bundle folder silently drops off the
list instead of offering a dead entry.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from PySide6.QtCore import QSettings

from core.services.LoggerService import LoggerService
from core.services.streaming.RecordingSessionService import read_manifest

_RECENT_KEY = "library/recent"
_MAX_ENTRIES = 50


class RecordingLibrary:
    """Persisted list of recording bundle paths, newest first."""

    def __init__(self, settings: Optional[QSettings] = None):
        self.logger = LoggerService()
        self._settings = settings if settings is not None else QSettings("ADIAT", "Recordings")

    # ------------------------------------------------------------------
    # writing
    # ------------------------------------------------------------------

    def remember(self, bundle_dir: str) -> None:
        """Record a finished bundle at the head of the list."""
        if not bundle_dir:
            return
        bundle_dir = os.path.abspath(str(bundle_dir))
        paths = self._read_paths()
        paths = [bundle_dir] + [p for p in paths if p != bundle_dir]
        self._write_paths(paths[:_MAX_ENTRIES])

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def recent(self) -> List[dict]:
        """The library, newest first, described from each bundle's manifest.

        Entries whose folder no longer exists are pruned from the stored
        list as a side effect, so the picker never offers a dead row.

        Returns dicts with: ``bundle_dir``, ``video`` (absolute path to
        the first MP4, or None), ``title``, ``started_at``, ``detections``,
        ``fixes``.
        """
        entries: List[dict] = []
        kept: List[str] = []
        for path in self._read_paths():
            if not os.path.isdir(path):
                continue
            kept.append(path)
            entries.append(self._describe(path))
        self._write_paths(kept)
        return entries

    @staticmethod
    def first_video_in(bundle_dir: str) -> Optional[str]:
        """Absolute path of the bundle's first video segment, or None."""
        try:
            videos = sorted(
                name for name in os.listdir(bundle_dir)
                if name.lower().endswith(".mp4")
            )
        except OSError:
            return None
        return os.path.join(bundle_dir, videos[0]) if videos else None

    def _describe(self, bundle_dir: str) -> dict:
        manifest = read_manifest(bundle_dir)
        feed = manifest.get("feed") or {}
        title = (
            feed.get("label")
            or feed.get("aircraft_name")
            or manifest.get("algorithm")
            or os.path.basename(bundle_dir)
        )
        counts = manifest.get("counts") or {}
        return {
            "bundle_dir": bundle_dir,
            "video": self.first_video_in(bundle_dir),
            "title": str(title),
            "started_at": manifest.get("started_at") or "",
            "detections": int(counts.get("detections_stored") or 0),
            "fixes": int(counts.get("telemetry_fixes") or 0),
        }

    # ------------------------------------------------------------------
    # storage
    # ------------------------------------------------------------------

    def _read_paths(self) -> List[str]:
        raw = self._settings.value(_RECENT_KEY)
        if not raw:
            return []
        try:
            paths = json.loads(str(raw))
        except (TypeError, ValueError):
            return []
        return [str(p) for p in paths if isinstance(p, str)] if isinstance(paths, list) else []

    def _write_paths(self, paths: List[str]) -> None:
        try:
            self._settings.setValue(_RECENT_KEY, json.dumps(paths))
            self._settings.sync()
        except Exception as exc:  # noqa: BLE001 - the library is a convenience
            self.logger.warning(f"Could not persist recording library: {exc}")


__all__ = ["RecordingLibrary"]
