"""Tests for TerrainCacheService."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
import json
import os
from PIL import Image
import io

import math

from core.services.terrain.TerrainCacheService import (
    TerrainCacheService,
    bounds_for_radius,
)
from core.services.terrain.ElevationProvider import TerrariumProvider


class TestTerrainCacheService:
    """Tests for TerrainCacheService class."""

    def create_test_tile(self, size=256):
        """Create a valid test PNG tile."""
        img = Image.new('RGB', (size, size), (128, 0, 0))
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def test_initialization(self):
        """Test service initializes correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            assert service.cache_dir == Path(tmpdir)
            assert service.tiles_dir.exists()
            assert service.provider is not None

    def test_initialization_default_dir(self):
        """Test initialization with default cache directory."""
        service = TerrainCacheService()
        assert service.cache_dir == Path.home() / '.adiat' / 'terrain_cache'

    def test_get_tile_path(self):
        """Test tile path generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            path = service._get_tile_path(12, 100, 200)
            assert '12' in str(path)
            assert '100' in str(path)
            assert '200.png' in str(path)

    def test_is_tile_cached_false(self):
        """Test checking for non-existent tile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            assert not service.is_tile_cached(12, 100, 200)

    def test_is_tile_cached_true(self):
        """Test checking for existing tile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Create a fake tile
            tile_path = service._get_tile_path(12, 100, 200)
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(self.create_test_tile())

            assert service.is_tile_cached(12, 100, 200)

    def test_get_tile_if_cached_not_exists(self):
        """Test getting non-existent tile from cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            result = service.get_tile_if_cached(12, 100, 200)
            assert result is None

    def test_get_tile_if_cached_exists(self):
        """Test getting existing tile from cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Create a fake tile
            tile_path = service._get_tile_path(12, 100, 200)
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(self.create_test_tile())

            result = service.get_tile_if_cached(12, 100, 200)
            assert result is not None
            assert isinstance(result, Image.Image)
            assert service._hits == 1

    def test_get_tile_from_cache(self):
        """Test getting tile from cache (cache hit)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Pre-populate cache
            tile_path = service._get_tile_path(12, 100, 200)
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(self.create_test_tile())

            result = service.get_tile(12, 100, 200)
            assert result is not None
            assert service._hits == 1
            assert service._misses == 0

    @patch.object(TerrariumProvider, 'download_tile')
    def test_get_tile_download(self, mock_download):
        """Test getting tile triggers download on cache miss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            mock_download.return_value = self.create_test_tile()

            result = service.get_tile(12, 100, 200)

            assert result is not None
            mock_download.assert_called_once_with(12, 100, 200)
            assert service._misses == 1
            assert service._downloads == 1

            # Verify tile was cached
            assert service.is_tile_cached(12, 100, 200)

    @patch.object(TerrariumProvider, 'download_tile')
    def test_get_tile_download_fails(self, mock_download):
        """Test handling of download failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            mock_download.return_value = None

            result = service.get_tile(12, 100, 200)

            assert result is None
            assert service._misses == 1
            assert service._downloads == 0

    def test_get_cache_info(self):
        """Test cache info retrieval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Add some tiles
            for i in range(3):
                tile_path = service._get_tile_path(12, i, i)
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile_path.write_bytes(self.create_test_tile())

            info = service.get_cache_info()

            assert info['total_tiles'] == 3
            assert info['total_size_mb'] >= 0  # May be very small for test tiles
            assert 'cache_dir' in info
            assert 'provider' in info
            assert 'session_stats' in info

    def test_clear_cache(self):
        """Test cache clearing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Add some tiles
            for i in range(5):
                tile_path = service._get_tile_path(12, i, i)
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile_path.write_bytes(self.create_test_tile())

            assert service.get_cache_info()['total_tiles'] == 5

            count = service.clear_cache()

            assert count == 5
            assert service.get_cache_info()['total_tiles'] == 0

    def test_metadata_persistence(self):
        """Test that metadata is saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create service and add a tile
            service1 = TerrainCacheService(cache_dir=tmpdir)
            tile_path = service1._get_tile_path(12, 0, 0)
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(self.create_test_tile())
            service1._update_metadata_stats()

            # Create new service instance and check metadata was loaded
            service2 = TerrainCacheService(cache_dir=tmpdir)
            assert service2._metadata['stats']['total_tiles'] == 1

    def test_corrupt_tile_handling(self):
        """Test handling of corrupt cached tile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            # Create a corrupt tile (not valid PNG)
            tile_path = service._get_tile_path(12, 100, 200)
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(b'not a valid png')

            # Mock provider to return valid tile
            with patch.object(service.provider, 'download_tile', return_value=self.create_test_tile()):
                result = service.get_tile(12, 100, 200)

                # Should have downloaded new tile
                assert result is not None
                # Corrupt file should have been removed and replaced
                assert service.is_tile_cached(12, 100, 200)

    @patch.object(TerrariumProvider, 'download_tile')
    def test_prefetch_tiles(self, mock_download):
        """A radius prefetch downloads every tile covering that radius."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            mock_download.return_value = self.create_test_tile()

            count = service.prefetch_tiles(40.7128, -74.0060, radius_km=10, zoom=10)

            assert count > 0
            assert mock_download.call_count == count
            # Nothing left uncached: the previous version of this test
            # asserted only ``count >= 0``, which is how a longitude
            # conversion 35x too narrow went unnoticed.
            assert service.count_missing_tiles(
                bounds_for_radius(40.7128, -74.0060, 10), zoom=10) == 0

    @patch.object(TerrariumProvider, 'download_tile')
    def test_prefetch_covers_the_requested_ground(self, mock_download):
        """Regression guard for the longitude conversion.

        Scaling ``dlon`` by the latitude instead of its cosine collapsed the
        box: at 30 degrees a 10 km radius became a few hundred metres of
        longitude, so the prefetch fetched a sliver and every lookup outside
        it still hit the network.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            mock_download.return_value = self.create_test_tile()
            service.prefetch_tiles(30.0, -97.0, radius_km=10, zoom=12)

            # 8 km east of centre is inside a 10 km radius, so its tile must
            # be cached. Under the old arithmetic it was far outside the box
            # that actually got fetched.
            east_lon = -97.0 + 8.0 / (111.0 * math.cos(math.radians(30.0)))
            tile_x, tile_y = TerrariumProvider.lat_lon_to_tile(30.0, east_lon, 12)
            assert service.is_tile_cached(12, tile_x, tile_y)

    @patch.object(TerrariumProvider, 'download_tile')
    def test_is_online(self, mock_download):
        """Test online connectivity check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)

            mock_download.return_value = self.create_test_tile()
            assert service.is_online()

            mock_download.return_value = None
            assert not service.is_online()


class TestBoundsForRadius:
    """Longitude degrees shrink with the cosine of latitude."""

    def test_east_west_span_matches_the_radius(self):
        """The property the bug broke: 10 km east is inside a 10 km radius."""
        for lat in (0.0, 30.0, 45.0, 60.0):
            min_lon, _min_lat, max_lon, _max_lat = bounds_for_radius(lat, -97.0, 10)
            half_width_km = ((max_lon - min_lon) / 2.0) * 111.0 * math.cos(
                math.radians(lat))
            assert half_width_km == pytest.approx(10.0, rel=0.02), lat

    def test_north_south_span_is_latitude_independent(self):
        for lat in (0.0, 30.0, 60.0):
            _min_lon, min_lat, _max_lon, max_lat = bounds_for_radius(lat, -97.0, 10)
            half_height_km = ((max_lat - min_lat) / 2.0) * 111.0
            assert half_height_km == pytest.approx(10.0, rel=0.02), lat

    def test_the_box_widens_in_longitude_toward_the_poles(self):
        equator = bounds_for_radius(0.0, 0.0, 10)
        mid = bounds_for_radius(60.0, 0.0, 10)
        assert (mid[2] - mid[0]) > (equator[2] - equator[0]) * 1.9

    def test_at_the_equator_the_box_is_square_in_degrees(self):
        min_lon, min_lat, max_lon, max_lat = bounds_for_radius(0.0, 0.0, 10)
        assert (max_lon - min_lon) == pytest.approx(max_lat - min_lat, rel=1e-6)

    def test_near_the_poles_the_width_is_clamped(self):
        """cos(lat) approaches zero; an unclamped divisor would explode."""
        min_lon, _min_lat, max_lon, _max_lat = bounds_for_radius(89.9, 0.0, 10)
        assert (max_lon - min_lon) <= 20.0


class TestPrefetchBounds:
    """The bbox form every acquisition path actually uses."""

    @staticmethod
    def _tile():
        # Reuse the suite's PNG builder rather than keeping a second copy.
        return TestTerrainCacheService().create_test_tile()

    @patch.object(TerrariumProvider, 'download_tile')
    def test_cached_tiles_are_not_refetched(self, mock_download):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            mock_download.return_value = self._tile()
            bounds = (-97.01, 30.0, -97.0, 30.01)

            first = service.prefetch_bounds(bounds, zoom=12)
            calls_after_first = mock_download.call_count
            second = service.prefetch_bounds(bounds, zoom=12)

            assert first > 0
            assert second == 0
            assert mock_download.call_count == calls_after_first

    @patch.object(TerrariumProvider, 'download_tile')
    def test_cancellation_stops_before_the_first_tile(self, mock_download):
        """A prefetch is opportunistic; it must never hold up its caller."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            mock_download.return_value = self._tile()
            written = service.prefetch_bounds(
                (-97.5, 30.0, -97.0, 30.5), zoom=12, cancel_check=lambda: True)
            assert written == 0
            mock_download.assert_not_called()

    @patch.object(TerrariumProvider, 'download_tile')
    def test_progress_reaches_the_total(self, mock_download):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            mock_download.return_value = self._tile()
            seen = []
            service.prefetch_bounds(
                (-97.01, 30.0, -97.0, 30.01), zoom=12,
                progress_callback=lambda d, t, m: seen.append((d, t)))
            assert seen
            assert seen[-1][0] == seen[-1][1]

    def test_count_missing_reports_everything_uncached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = TerrainCacheService(cache_dir=tmpdir)
            bounds = (-97.01, 30.0, -97.0, 30.01)
            min_x, min_y, max_x, max_y = service.tile_range(bounds, 12)
            span = (max_x - min_x + 1) * (max_y - min_y + 1)
            assert service.count_missing_tiles(bounds, 12) == span
