"""Tests for the viewer filmstrip ThumbnailLoader's cache lookups.

Analysis writes each image's filmstrip thumbnail into the results folder's
.thumbnails/thumbnails.db; results folders from older builds hold loose
.jpg files instead, and both must keep loading.
"""

import hashlib

import cv2
import numpy as np
import pytest

from core.controllers.images.viewer.thumbnails.ThumbnailLoader import ThumbnailLoader
from core.services.AnalyzeService import AnalyzeService
from core.services.cache.ThumbnailBlobStore import ThumbnailBlobStore


RED_BGR = (0, 0, 255)
GREEN_BGR = (0, 255, 0)


@pytest.fixture
def dataset(tmp_path):
    """An input root with one nested image path and an empty results folder."""
    input_root = tmp_path / 'input'
    image_path = input_root / 'FlightA' / 'DJI_0001.JPG'
    results_dir = tmp_path / 'results'
    return input_root, image_path, results_dir


def _write_with_analysis(color_bgr, image_path, results_dir, input_root):
    img = np.zeros((200, 400, 3), dtype=np.uint8)
    img[:, :] = color_bgr
    AnalyzeService._generate_main_image_thumbnail(
        img, str(image_path), str(results_dir), input_root=str(input_root)
    )


def _write_loose_jpg(color_bgr, thumb_dir, rel_key):
    """Write a thumbnail the way builds before the container did."""
    thumb_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(rel_key.encode()).hexdigest()
    img = np.zeros((50, 100, 3), dtype=np.uint8)
    img[:, :] = color_bgr
    cv2.imwrite(str(thumb_dir / f'{key}.jpg'), img)


def _make_loader(image_path, results_dir, input_root):
    return ThumbnailLoader(
        [{'path': str(image_path)}], results_dir=str(results_dir), input_root=str(input_root)
    )


def _center_color(pixmap):
    return pixmap.toImage().pixelColor(pixmap.width() // 2, pixmap.height() // 2)


def test_loader_reads_thumbnail_written_by_analysis(app, dataset):
    """Writer and reader agree on the key, so the container entry is found."""
    input_root, image_path, results_dir = dataset
    _write_with_analysis(RED_BGR, image_path, results_dir, input_root)
    loader = _make_loader(image_path, results_dir, input_root)

    assert loader.is_cached(str(image_path)) is True
    pixmap = loader._load_cached_thumbnail(str(image_path))

    # The source image does not exist, so only the cache can have answered
    assert pixmap is not None
    assert (pixmap.width(), pixmap.height()) == (100, 50)
    color = _center_color(pixmap)
    assert color.red() > 200 and color.blue() < 60


def test_loader_reads_container_entry_with_no_loose_file(app, dataset):
    """The container alone is enough; nothing loose needs to sit beside it."""
    input_root, image_path, results_dir = dataset
    thumb_dir = results_dir / '.thumbnails'
    thumb_dir.mkdir(parents=True)
    img = np.zeros((50, 100, 3), dtype=np.uint8)
    img[:, :] = GREEN_BGR
    _, encoded = cv2.imencode('.jpg', img)
    key = hashlib.md5('flighta/dji_0001.jpg'.encode()).hexdigest()
    ThumbnailBlobStore(thumb_dir).put(key, encoded.tobytes())
    loader = _make_loader(image_path, results_dir, input_root)

    assert loader.is_cached(str(image_path)) is True
    pixmap = loader._load_cached_thumbnail(str(image_path))

    assert pixmap is not None
    assert _center_color(pixmap).green() > 200


def test_load_thumbnail_emits_icon_from_container(app, qtbot, dataset):
    input_root, image_path, results_dir = dataset
    _write_with_analysis(RED_BGR, image_path, results_dir, input_root)
    loader = _make_loader(image_path, results_dir, input_root)

    with qtbot.waitSignal(loader.thumbnail_loaded, timeout=1000) as blocker:
        loader.load_thumbnail(0)

    index, icon = blocker.args
    assert index == 0
    assert not icon.isNull()


def test_old_results_folder_loose_jpg_still_loads(app, dataset):
    """A folder from an older build has no container, only loose files."""
    input_root, image_path, results_dir = dataset
    thumb_dir = results_dir / '.thumbnails'
    _write_loose_jpg(GREEN_BGR, thumb_dir, 'flighta/dji_0001.jpg')
    loader = _make_loader(image_path, results_dir, input_root)

    assert loader.is_cached(str(image_path)) is True
    pixmap = loader._load_cached_thumbnail(str(image_path))

    assert pixmap is not None
    assert _center_color(pixmap).green() > 200


def test_reading_old_results_folder_does_not_create_container(app, dataset):
    """The viewer only reads; it must not add a thumbnails.db to an old folder."""
    input_root, image_path, results_dir = dataset
    thumb_dir = results_dir / '.thumbnails'
    _write_loose_jpg(GREEN_BGR, thumb_dir, 'flighta/dji_0001.jpg')
    loader = _make_loader(image_path, results_dir, input_root)

    loader.is_cached(str(image_path))
    loader._load_cached_thumbnail(str(image_path))

    assert not (thumb_dir / ThumbnailBlobStore.DB_FILENAME).exists()


def test_container_with_only_aoi_entries_falls_back_to_loose_jpg(app, dataset):
    """Builds between the AOI and filmstrip moves: container holds AOIs, filmstrip is loose."""
    input_root, image_path, results_dir = dataset
    thumb_dir = results_dir / '.thumbnails'
    _write_loose_jpg(GREEN_BGR, thumb_dir, 'flighta/dji_0001.jpg')
    ThumbnailBlobStore(thumb_dir).put('aoi-thumbnail-key', b'\xff\xd8not-this-one')
    loader = _make_loader(image_path, results_dir, input_root)

    assert loader.is_cached(str(image_path)) is True
    pixmap = loader._load_cached_thumbnail(str(image_path))

    assert pixmap is not None
    assert _center_color(pixmap).green() > 200


def test_uncached_image_reports_not_cached(app, dataset):
    input_root, image_path, results_dir = dataset
    other_image = input_root / 'FlightA' / 'DJI_0002.JPG'
    _write_with_analysis(RED_BGR, other_image, results_dir, input_root)
    loader = _make_loader(image_path, results_dir, input_root)

    assert loader.is_cached(str(image_path)) is False
    assert loader._load_cached_thumbnail(str(image_path)) is None


def test_repointed_results_dir_reads_the_new_container(app, tmp_path, dataset):
    """CachePathService repoints results_dir at a relocated copy; lookups must follow."""
    input_root, image_path, results_dir = dataset
    relocated_dir = tmp_path / 'relocated'
    _write_with_analysis(RED_BGR, image_path, results_dir, input_root)
    _write_with_analysis(GREEN_BGR, image_path, relocated_dir, input_root)
    loader = _make_loader(image_path, results_dir, input_root)
    assert _center_color(loader._load_cached_thumbnail(str(image_path))).red() > 200

    loader.results_dir = str(relocated_dir)
    pixmap = loader._load_cached_thumbnail(str(image_path))

    assert _center_color(pixmap).green() > 200
