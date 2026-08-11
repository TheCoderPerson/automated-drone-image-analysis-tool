"""Does the coverage cache survive the terrain-adjusted altitude mutation,
across candidates and across two searches at different AOI elevations?"""
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from core.services.image.AOINeighborService import AOINeighborService

LAT, LON = 37.7749, -122.4194


class _Elev:
    def __init__(self, e, source='terrain'):
        self.elevation_m = e
        self.source = source


class _Terrain:
    enabled = True

    def __init__(self, camera_ground):
        self.camera_ground = camera_ground
        self.calls = []

    def get_elevation(self, lat, lon):
        self.calls.append((lat, lon))
        return _Elev(self.camera_ground)


@pytest.fixture
def svc():
    return AOINeighborService()


def _mock_image_service():
    m = MagicMock()
    m.get_camera_yaw.return_value = 0.0
    m.get_camera_pitch.return_value = -90.0
    m.get_gimbal_roll.return_value = None
    m.get_roll_axis_azimuth.return_value = None
    m.get_relative_altitude.return_value = 100.0
    m.get_camera_intrinsics.return_value = {
        'focal_length_mm': 24.0, 'sensor_width_mm': 23.5, 'sensor_height_mm': 15.6}
    m.img_array = np.zeros((1000, 1500, 3), dtype=np.uint8)
    return m


def test_cache_not_poisoned_across_searches(svc, monkeypatch):
    image = {'path': 'a.jpg', 'mask_path': '', 'bearing': 90.0}
    with patch('core.services.image.AOINeighborService.ImageService') as MIS, \
         patch('core.services.image.AOINeighborService.MetaDataHelper') as MMD, \
         patch('core.services.image.AOINeighborService.LocationInfo') as MLI, \
         patch('core.services.image.AOINeighborService.Image') as MPIL:
        MMD.get_exif_data_piexif.return_value = {}
        MLI.get_gps.return_value = {'latitude': LAT, 'longitude': LON}
        MIS.return_value = _mock_image_service()
        MPIL.open.side_effect = Exception("no header")

        import core.services.image.AOINeighborService as mod
        terrain = _Terrain(camera_ground=280.0)
        monkeypatch.setattr(mod, '_get_terrain_service', lambda: terrain)

        seen = []
        real_gps_to_pixel = svc.gps_to_pixel

        def spy(lat, lon, cov):
            seen.append(cov['altitude'])
            return real_gps_to_pixel(lat, lon, cov)
        monkeypatch.setattr(svc, 'gps_to_pixel', spy)

        # Search 1: AOI ground 250 m -> camera is 100 + (280-250) = 130 above it
        svc._check_image_for_aoi(image, 0, LAT, LON, None, 100, 250.0)
        # Search 2: AOI ground 310 m -> camera is 100 + (280-310) = 70 above it
        svc._check_image_for_aoi(image, 0, LAT, LON, None, 100, 310.0)
        # Search 3: no terrain elevation at all -> unadjusted
        svc._check_image_for_aoi(image, 0, LAT, LON, None, 100, None)

        assert seen == [130.0, 70.0, 100.0], seen
        # Cache itself keeps the raw altitude
        cached = list(svc._coverage_meta_cache.values())[0]['meta']
        assert cached['altitude'] == 100.0, cached['altitude']


def test_floor_can_produce_a_false_positive(svc, monkeypatch):
    """AOI ground far ABOVE the camera -> altitude floored to 1.0 m.

    What does the searcher see?
    """
    image = {'path': 'a.jpg', 'mask_path': '', 'bearing': 90.0}
    with patch('core.services.image.AOINeighborService.ImageService') as MIS, \
         patch('core.services.image.AOINeighborService.MetaDataHelper') as MMD, \
         patch('core.services.image.AOINeighborService.LocationInfo') as MLI, \
         patch('core.services.image.AOINeighborService.Image') as MPIL:
        MMD.get_exif_data_piexif.return_value = {}
        MLI.get_gps.return_value = {'latitude': LAT, 'longitude': LON}
        MIS.return_value = _mock_image_service()
        MPIL.open.side_effect = Exception("no header")

        import core.services.image.AOINeighborService as mod
        monkeypatch.setattr(mod, '_get_terrain_service', lambda: _Terrain(280.0))

        # AOI ground 600 m: 320 m ABOVE the camera's ground; camera at 100 AGL
        # is 220 m BELOW the AOI's ground plane. adjusted = -220 -> floored 1.0
        alt = svc._terrain_adjusted_altitude(
            {'altitude': 100.0, 'center_lat': LAT, 'center_lon': LON}, 600.0)
        assert alt == 1.0

        cov = {
            'center_lat': LAT, 'center_lon': LON, 'yaw': 0.0, 'pitch': -90.0,
            'roll': 0.0, 'roll_axis_azimuth': None, 'altitude': alt,
            'width': 1500, 'height': 1000, 'focal_mm': 24.0,
            'sensor_w_mm': 23.5, 'sensor_h_mm': 15.6, 'fov_alignment': None,
        }
        # AOI exactly at the camera's nadir GPS
        px = svc.gps_to_pixel(LAT, LON, cov)
        print("nadir AOI with floored altitude ->", px)
        assert px is not None
        assert svc.is_point_in_image(px[0], px[1], 1500, 1000, 50)

        # AOI 30 m north of nadir
        off_lat = LAT + 30.0 / 111320.0
        px2 = svc.gps_to_pixel(off_lat, LON, cov)
        print("30 m-north AOI with floored altitude ->", px2)
        print("in image?", px2 and svc.is_point_in_image(px2[0], px2[1], 1500, 1000, 50))
