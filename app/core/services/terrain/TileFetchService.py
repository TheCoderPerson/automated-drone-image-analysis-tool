"""
TileFetchService - download DEM / canopy tiles for an AOI and write the manifest.

* USGS 3DEP DEM  - ArcGIS ImageServer exportImage, tiled to keep each request
  under a pixel cap; writes GeoTIFF tiles + the manifest the USGS3DEPProvider
  reads. (No API key.)
* Meta/WRI CHM   - Bing-quadkey z9 COG tiles from the public S3 bucket; writes
  the COG bytes as local tiles + the manifest CanopyService reads.

Both mirror the SAR-Preflight fetch patterns (single blind retry for 3DEP;
linear-backoff retry with skip-on-404 for canopy). Network / file I/O only; no
Qt. A ``requests.Session`` may be injected for tests.
"""

import csv
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core.services.LoggerService import LoggerService


@dataclass
class FetchResult:
    product: str
    out_dir: str
    manifest_path: Optional[str]
    tiles_written: int = 0
    tiles_failed: int = 0
    tiles_skipped: int = 0
    errors: List[Tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


class TileFetchService:
    META_CHM_URL = ("https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/"
                    "alsgedi_global_v6_float/chm/{quadkey}.tif")
    DEP_EXPORT_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
                      "3DEPElevation/ImageServer/exportImage")
    MAX_RETRIES = 4
    BACKOFF_MS = 300
    METERS_PER_DEG = 111320.0

    def __init__(self, logger: Optional[LoggerService] = None, session=None,
                 timeout: float = 60.0, backoff_ms: Optional[int] = None):
        self.logger = logger or LoggerService()
        self._session = session
        self.timeout = timeout
        self.backoff_ms = self.BACKOFF_MS if backoff_ms is None else backoff_ms

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update({'User-Agent': 'ADIAT/1.0 (Drone Image Analysis Tool)'})
        return self._session

    # ---- slippy / quadkey math ----

    @staticmethod
    def lnglat_to_tile_xy(lon: float, lat: float, z: int) -> Tuple[int, int]:
        lat_rad = math.radians(lat)
        n = 2 ** z
        x = int((lon + 180.0) / 360.0 * n)
        y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        x = max(0, min(x, n - 1))
        y = max(0, min(y, n - 1))
        return x, y

    @staticmethod
    def tile_xy_to_quadkey(x: int, y: int, z: int) -> str:
        qk = []
        for i in range(z, 0, -1):
            digit = 0
            mask = 1 << (i - 1)
            if x & mask:
                digit += 1
            if y & mask:
                digit += 2
            qk.append(str(digit))
        return "".join(qk)

    @staticmethod
    def tile_xy_to_bounds(x: int, y: int, z: int) -> Tuple[float, float, float, float]:
        n = 2.0 ** z
        lon0 = x / n * 360.0 - 180.0
        lon1 = (x + 1) / n * 360.0 - 180.0
        lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return (lon0, lat0, lon1, lat1)

    @classmethod
    def tiles_covering_bbox(cls, bounds_wgs84, z: int) -> List[Tuple[int, int]]:
        min_lon, min_lat, max_lon, max_lat = bounds_wgs84
        x0, y0 = cls.lnglat_to_tile_xy(min_lon, max_lat, z)   # NW
        x1, y1 = cls.lnglat_to_tile_xy(max_lon, min_lat, z)   # SE
        tiles = []
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                tiles.append((x, y))
        return tiles

    # ---- HTTP ----

    def _get_with_retry(self, url, params=None):
        """GET with linear backoff. Returns bytes, or None for absent (403/404)
        or exhausted retries."""
        for attempt in range(self.MAX_RETRIES):
            if attempt > 0 and self.backoff_ms:
                time.sleep(self.backoff_ms * attempt / 1000.0)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except Exception as e:
                self.logger.warning(f"TileFetch: request error {url}: {e}")
                continue
            if resp.status_code == 200:
                return resp.content
            if resp.status_code in (403, 404):
                return None
            self.logger.warning(f"TileFetch: HTTP {resp.status_code} for {url}")
        return None

    @staticmethod
    def _write_manifest(rows, manifest_path, include_product):
        fields = ['filename']
        if include_product:
            fields.append('product')
        fields += ['minX', 'minY', 'maxX', 'maxY']
        # Merge with any existing manifest (dedupe by filename) for incremental AOIs.
        existing = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, newline='') as fh:
                    for r in csv.DictReader(fh):
                        existing[r['filename']] = r
            except Exception:
                existing = {}
        for r in rows:
            existing[r['filename']] = r
        with open(manifest_path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in existing.values():
                w.writerow({k: r.get(k, '') for k in fields})

    # ---- 3DEP DEM ----

    def fetch_3dep_dem(self, bounds_wgs84, out_dir, image_sr: int = 4326,
                       tile_px: int = 2048, native_res_m: float = 1.0,
                       progress_callback=None, cancel_check=None) -> FetchResult:
        min_lon, min_lat, max_lon, max_lat = bounds_wgs84
        os.makedirs(out_dir, exist_ok=True)
        mid_lat = (min_lat + max_lat) / 2.0
        m_per_deg_lon = self.METERS_PER_DEG * max(0.05, math.cos(math.radians(mid_lat)))

        # Ground span of one sub-tile at the target resolution.
        dlat_tile = tile_px * native_res_m / self.METERS_PER_DEG
        dlon_tile = tile_px * native_res_m / m_per_deg_lon
        n_x = max(1, math.ceil((max_lon - min_lon) / dlon_tile))
        n_y = max(1, math.ceil((max_lat - min_lat) / dlat_tile))

        result = FetchResult(product='usgs_3dep_dem', out_dir=out_dir, manifest_path=None)
        rows = []
        total = n_x * n_y
        done = 0
        for j in range(n_y):
            for i in range(n_x):
                if cancel_check and cancel_check():
                    result.cancelled = True
                    return result
                w = min_lon + i * dlon_tile
                e = min(max_lon, w + dlon_tile)
                s = min_lat + j * dlat_tile
                north = min(max_lat, s + dlat_tile)
                cols = max(1, min(tile_px, round((e - w) * m_per_deg_lon / native_res_m)))
                rows_px = max(1, min(tile_px, round((north - s) * self.METERS_PER_DEG / native_res_m)))
                params = {
                    'bbox': f"{w},{s},{e},{north}", 'bboxSR': 4326, 'imageSR': image_sr,
                    'size': f"{cols},{rows_px}", 'format': 'tiff', 'pixelType': 'F32',
                    'interpolation': 'RSP_BilinearInterpolation', 'f': 'image',
                }
                filename = f"dem_{j}_{i}.tif"
                content = self._get_with_retry(self.DEP_EXPORT_URL, params=params)
                if content is None:
                    # one blind retry (endpoint occasionally 502s)
                    content = self._get_with_retry(self.DEP_EXPORT_URL, params=params)
                if content is None:
                    result.tiles_failed += 1
                    result.errors.append((filename, "download failed"))
                else:
                    Path(out_dir, filename).write_bytes(content)
                    rows.append({'filename': filename, 'minX': w, 'minY': s,
                                 'maxX': e, 'maxY': north})
                    result.tiles_written += 1
                done += 1
                if progress_callback:
                    progress_callback(done, total, f"Downloading DEM tile {done}/{total}...")

        if rows:
            manifest = os.path.join(out_dir, "dem_manifest.csv")
            self._write_manifest(rows, manifest, include_product=False)
            result.manifest_path = manifest
        return result

    # ---- Meta/WRI canopy ----

    def fetch_meta_canopy(self, bounds_wgs84, out_dir, zoom: int = 9,
                          progress_callback=None, cancel_check=None) -> FetchResult:
        os.makedirs(out_dir, exist_ok=True)
        tiles = self.tiles_covering_bbox(bounds_wgs84, zoom)
        result = FetchResult(product='meta_chm', out_dir=out_dir, manifest_path=None)
        rows = []
        total = len(tiles)
        for done, (x, y) in enumerate(tiles, start=1):
            if cancel_check and cancel_check():
                result.cancelled = True
                return result
            qk = self.tile_xy_to_quadkey(x, y, zoom)
            url = self.META_CHM_URL.format(quadkey=qk)
            filename = f"chm_{qk}.tif"
            content = self._get_with_retry(url)
            if content is None:
                result.tiles_skipped += 1
            else:
                Path(out_dir, filename).write_bytes(content)
                lon0, lat0, lon1, lat1 = self.tile_xy_to_bounds(x, y, zoom)
                rows.append({'filename': filename, 'product': 'meta_chm',
                             'minX': lon0, 'minY': lat0, 'maxX': lon1, 'maxY': lat1})
                result.tiles_written += 1
            if progress_callback:
                progress_callback(done, total, f"Downloading canopy tile {done}/{total}...")

        if rows:
            manifest = os.path.join(out_dir, "chm_manifest.csv")
            self._write_manifest(rows, manifest, include_product=True)
            result.manifest_path = manifest
        return result
