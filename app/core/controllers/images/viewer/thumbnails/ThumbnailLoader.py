"""
Simple thumbnail loader that runs in a background thread without blocking UI.
"""

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QPixmap, QIcon, QImageReader
from PySide6.QtCore import QSize
import hashlib
import os
from pathlib import Path

from core.services.LoggerService import LoggerService
from core.services.cache.ThumbnailBlobStore import ThumbnailBlobStore


class ThumbnailLoader(QObject):
    """Background thumbnail loader that processes thumbnails on demand."""

    thumbnail_loaded = Signal(int, QIcon)

    def __init__(self, images, thumbnail_size=(100, 56), results_dir=None, input_root=None):
        super().__init__()
        self.images = images
        self.thumbnail_size = QSize(*thumbnail_size)
        self.loaded_indices = set()
        self.results_dir = results_dir
        self.input_root = input_root
        # Container for the current results_dir, opened on first use. Reopened
        # when results_dir is pointed elsewhere (CachePathService does that).
        self._blob_store = None

    def _get_blob_store(self, thumb_dir):
        """
        Return the thumbnails.db container in thumb_dir, or None if there is none.

        Never creates one: a results folder from an older build holds only
        loose .jpg files, and the viewer must not write into it (it may sit
        on read-only media) just to look thumbnails up.
        """
        db_path = thumb_dir / ThumbnailBlobStore.DB_FILENAME
        if not db_path.exists():
            return None
        # is_cached runs on the GUI thread and loading on the loader thread;
        # a race here at worst opens the same file twice, and the store opens
        # a fresh connection per operation, so no lock is needed
        store = self._blob_store
        if store is None or store.db_path != str(db_path):
            store = ThumbnailBlobStore(thumb_dir, logger=LoggerService())
            self._blob_store = store
        return store

    @Slot(int)
    def load_thumbnail(self, index):
        """Load a single thumbnail (called from main thread via signal)."""
        if index in self.loaded_indices:
            return
        if index < 0 or index >= len(self.images):
            return

        try:
            image_path = self.images[index].get('path', '')
            if not image_path:
                return

            # First, try to load from cache
            cached_thumb = self._load_cached_thumbnail(image_path)
            if cached_thumb:
                icon = QIcon(cached_thumb)
                self.thumbnail_loaded.emit(index, icon)
                self.loaded_indices.add(index)
                return

            # Fallback: Load from original image and scale
            reader = QImageReader(image_path)
            reader.setScaledSize(self.thumbnail_size)
            pixmap = QPixmap.fromImage(reader.read())
            if not pixmap.isNull():
                icon = QIcon(pixmap)
                self.thumbnail_loaded.emit(index, icon)
                self.loaded_indices.add(index)
        except Exception:
            pass  # Skip failed thumbnails

    def is_cached(self, image_path):
        """
        Check if a thumbnail is cached without loading it.

        Checks both new (portable) and legacy cache keys for backward compatibility.
        Also checks legacy .image_thumbnails directory for old datasets.

        Args:
            image_path: Path to the original image

        Returns:
            bool: True if cached, False otherwise
        """
        try:
            # If we don't have a results directory, can't check cache
            if not self.results_dir:
                return False

            results_path = Path(self.results_dir)

            # Try unified .thumbnails directory first (new format)
            thumb_dir = results_path / '.thumbnails'

            # Try new (portable) key - relative path to input root when available
            key_source = None
            if getattr(self, 'input_root', None):
                try:
                    key_source = str(Path(image_path).relative_to(Path(self.input_root)))
                except Exception:
                    try:
                        key_source = os.path.relpath(image_path, self.input_root)
                    except Exception:
                        key_source = None

            if not key_source:
                # Fall back to filename only (legacy)
                key_source = os.path.basename(image_path)

            norm_key = key_source.replace('\\', '/').lower()
            path_hash = hashlib.md5(norm_key.encode()).hexdigest()

            # Container written by current builds
            store = self._get_blob_store(thumb_dir)
            if store is not None and store.has(path_hash):
                return True

            # Loose .jpg written by older builds
            thumb_path = thumb_dir / f"{path_hash}.jpg"

            if thumb_path.exists():
                return True

            # Try legacy key - absolute path
            abs_path = os.path.abspath(image_path)
            legacy_hash = hashlib.md5(abs_path.encode()).hexdigest()
            legacy_thumb_path = thumb_dir / f"{legacy_hash}.jpg"

            if legacy_thumb_path.exists():
                return True

            # Backward compatibility: Try legacy .image_thumbnails directory
            legacy_thumb_dir = results_path / '.image_thumbnails'
            if legacy_thumb_dir.exists():
                legacy_path = legacy_thumb_dir / f"{path_hash}.jpg"
                if legacy_path.exists():
                    return True

                legacy_abs_path = legacy_thumb_dir / f"{legacy_hash}.jpg"
                if legacy_abs_path.exists():
                    return True

            return False
        except Exception:
            return False

    def _load_cached_thumbnail(self, image_path):
        """
        Load a cached thumbnail if it exists.

        Tries both new (portable) and legacy cache keys for backward compatibility.
        Also checks legacy .image_thumbnails directory for old datasets.

        Args:
            image_path: Path to the original image

        Returns:
            QPixmap or None
        """
        try:
            # If we don't have a results directory, can't load cache
            if not self.results_dir:
                return None

            results_path = Path(self.results_dir)

            # Try unified .thumbnails directory first (new format)
            thumb_dir = results_path / '.thumbnails'

            # Try new (portable) key - relative path to input root when available
            key_source = None
            if getattr(self, 'input_root', None):
                try:
                    key_source = str(Path(image_path).relative_to(Path(self.input_root)))
                except Exception:
                    try:
                        key_source = os.path.relpath(image_path, self.input_root)
                    except Exception:
                        key_source = None

            if not key_source:
                # Fall back to filename only (legacy)
                key_source = os.path.basename(image_path)

            norm_key = key_source.replace('\\', '/').lower()
            path_hash = hashlib.md5(norm_key.encode()).hexdigest()

            # Container written by current builds
            store = self._get_blob_store(thumb_dir)
            if store is not None:
                jpeg_bytes = store.get(path_hash)
                if jpeg_bytes:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(jpeg_bytes):
                        return pixmap

            # Loose .jpg written by older builds
            thumb_path = thumb_dir / f"{path_hash}.jpg"

            if thumb_path.exists():
                return QPixmap(str(thumb_path))

            # Try legacy key - absolute path
            abs_path = os.path.abspath(image_path)
            legacy_hash = hashlib.md5(abs_path.encode()).hexdigest()
            legacy_thumb_path = thumb_dir / f"{legacy_hash}.jpg"

            if legacy_thumb_path.exists():
                return QPixmap(str(legacy_thumb_path))

            # Backward compatibility: Try legacy .image_thumbnails directory
            legacy_thumb_dir = results_path / '.image_thumbnails'
            if legacy_thumb_dir.exists():
                legacy_path = legacy_thumb_dir / f"{path_hash}.jpg"
                if legacy_path.exists():
                    return QPixmap(str(legacy_path))

                legacy_abs_path = legacy_thumb_dir / f"{legacy_hash}.jpg"
                if legacy_abs_path.exists():
                    return QPixmap(str(legacy_abs_path))

            return None
        except Exception:
            return None
