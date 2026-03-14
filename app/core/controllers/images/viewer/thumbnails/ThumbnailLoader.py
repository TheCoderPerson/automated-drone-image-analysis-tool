"""
Simple thumbnail loader that runs in a background thread without blocking UI.

Supports reading from ZIP archive (.thumbnails.zip) or loose files (.thumbnails/).
"""

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QPixmap, QIcon, QImageReader
from PySide6.QtCore import QSize
import hashlib
import os
from pathlib import Path

from core.services.cache.ThumbnailZipStore import ThumbnailZipStore


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

        # Open ZIP store if available
        self._zipStore = None
        if results_dir:
            zipPath = Path(results_dir) / '.thumbnails.zip'
            if zipPath.exists():
                try:
                    self._zipStore = ThumbnailZipStore(str(zipPath))
                except Exception:
                    pass

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

    def _get_path_hash(self, image_path):
        """Compute the portable MD5 hash for a main image thumbnail key."""
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
            key_source = os.path.basename(image_path)

        norm_key = key_source.replace('\\', '/').lower()
        return hashlib.md5(norm_key.encode()).hexdigest()

    def is_cached(self, image_path):
        """
        Check if a thumbnail is cached without loading it.

        Checks ZIP archive first, then loose files, then legacy directories.

        Args:
            image_path: Path to the original image

        Returns:
            bool: True if cached, False otherwise
        """
        try:
            if not self.results_dir:
                return False

            path_hash = self._get_path_hash(image_path)

            # Check ZIP store first (fast in-memory lookup)
            if self._zipStore and self._zipStore.contains(path_hash):
                return True

            results_path = Path(self.results_dir)
            thumb_dir = results_path / '.thumbnails'

            # Check loose files with portable key
            thumb_path = thumb_dir / f"{path_hash}.jpg"
            if thumb_path.exists():
                return True

            # Try legacy key - absolute path
            abs_path = os.path.abspath(image_path)
            legacy_hash = hashlib.md5(abs_path.encode()).hexdigest()

            # Check ZIP with legacy key
            if self._zipStore and self._zipStore.contains(legacy_hash):
                return True

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

    def _pixmap_from_zip(self, cacheKey):
        """Load a QPixmap from the ZIP store by cache key, or return None."""
        if not self._zipStore:
            return None
        jpegBytes = self._zipStore.read(cacheKey)
        if not jpegBytes:
            return None
        pixmap = QPixmap()
        if pixmap.loadFromData(jpegBytes):
            return pixmap
        return None

    def _load_cached_thumbnail(self, image_path):
        """
        Load a cached thumbnail if it exists.

        Checks ZIP archive first, then loose files, then legacy directories.

        Args:
            image_path: Path to the original image

        Returns:
            QPixmap or None
        """
        try:
            if not self.results_dir:
                return None

            path_hash = self._get_path_hash(image_path)

            # Try ZIP store first (fast seek + read)
            pixmap = self._pixmap_from_zip(path_hash)
            if pixmap:
                return pixmap

            results_path = Path(self.results_dir)
            thumb_dir = results_path / '.thumbnails'

            # Try loose file with portable key
            thumb_path = thumb_dir / f"{path_hash}.jpg"
            if thumb_path.exists():
                return QPixmap(str(thumb_path))

            # Try legacy key - absolute path
            abs_path = os.path.abspath(image_path)
            legacy_hash = hashlib.md5(abs_path.encode()).hexdigest()

            # Try ZIP with legacy key
            pixmap = self._pixmap_from_zip(legacy_hash)
            if pixmap:
                return pixmap

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
