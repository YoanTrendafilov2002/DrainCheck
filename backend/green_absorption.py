"""Explicit full-green absorption scenario; never modifies terrain or source scores.

The user requests that every mapped green polygon be treated as absorbing water
and excluded from the displayed risk scenario. This is an assumption, not a
measurement of infiltration, storage, soil condition or drainage performance.
"""
import hashlib
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import Window

from .terrain import tile_bounds
from .tile_cache import file_signature, read_json_cached

METHOD = 'all-mapped-green-absorption-pixel-centres-v1'
SHAPE = (10869, 10345)
GRID = Affine(5, 0, 299392, 0, -5, 4753611)
BAND = 'assumed_absorbing_green_area'
VALIDATION_LOCK = threading.RLock()


class GreenAbsorption:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root/'data/cache/green_absorption_5m.tif'
        self.receipt = self.root/'data/cache/green_absorption_meta.json'
        self.error = 'Prepare the full mapped-green absorption scenario first.'

    @property
    def available(self):
        try:
            meta = read_json_cached(self.receipt)
            if (not meta.get('available') or meta.get('method') != METHOD
                    or meta.get('sha256', '')[:16] != meta.get('revision')
                    or len(meta.get('sha256', '')) != 64
                    or meta.get('source_counts', {}).get('nonempty_green_polygons') != 64956):
                raise ValueError('Green absorption receipt is incomplete or inconsistent')
            for record in meta['source_files'].values():
                path = (self.root/record['file']).resolve()
                if not path.is_relative_to(self.root.resolve()):
                    raise ValueError('Green source receipt contains an invalid path')
                signature = file_signature(path)
                if signature[1] != record['size_bytes']:
                    raise ValueError('Green absorption source signature changed; rebuild the scenario mask')
                if signature[2] != record['mtime_ns']:
                    # Identical restored files and a no-op revision refresh can
                    # have new timestamps. Content, rather than mtime alone,
                    # determines whether the prepared scenario is still valid.
                    self._validate_source_content(signature, record['sha256'])
            revision = read_json_cached(self.root/'data/cache/spatial_revision_inputs.json')['revision']
            if revision != meta.get('source_revision'):
                raise ValueError('Green absorption spatial revision changed')
            count = meta['counts']['green_cells']
            if not isinstance(count, int) or not 0 < count < SHAPE[0]*SHAPE[1]:
                raise ValueError('Green absorption cell counts are invalid')
            with VALIDATION_LOCK:
                self._validate(file_signature(self.path), file_signature(self.receipt), meta['sha256'], count)
            self.error = ''
            return True
        except (OSError, KeyError, TypeError, ValueError, rasterio.errors.RasterioError) as error:
            self.error = 'Green absorption scenario unavailable or invalid: '+str(error)
            return False

    @staticmethod
    @lru_cache(maxsize=32)
    def _validate_source_content(signature, expected_sha256):
        h = hashlib.sha256()
        with Path(signature[0]).open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                h.update(block)
        if h.hexdigest() != expected_sha256:
            raise ValueError('Green absorption source signature changed and checksum differs; rebuild the scenario mask')

    @staticmethod
    @lru_cache(maxsize=4)
    def _validate(signature, receipt_signature, expected_sha256, expected_count):
        h = hashlib.sha256()
        with Path(signature[0]).open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                h.update(block)
        if h.hexdigest() != expected_sha256:
            raise ValueError('Green absorption raster checksum differs from its receipt')
        with rasterio.open(signature[0]) as src:
            if (src.crs is None or src.crs.to_epsg() != 7801 or src.shape != SHAPE
                    or src.count != 1 or src.dtypes != ('uint8',) or src.nodata is not None
                    or src.transform != GRID or src.descriptions != (BAND,)):
                raise ValueError('Green absorption raster grid differs from the verified 5 m grid')
            count = 0
            for _, window in src.block_windows(1):
                a = src.read(1, window=window)
                if np.any((a != 0) & (a != 1)):
                    raise ValueError('Green absorption raster contains unsupported classes')
                count += int(np.count_nonzero(a))
            if count != expected_count:
                raise ValueError('Green absorption cell count differs from its receipt')

    def meta(self):
        if not self.available:
            return {'available': False, 'enabled_by_default': True, 'message': self.error}
        result = read_json_cached(self.receipt)
        return {**result, 'enabled_by_default': True,
                'interpretation': 'User-defined full absorption scenario; mapped green areas are excluded from the displayed risk, without changing original terrain scores.',
                'cell_count': result['counts']['green_cells'],
                'area_km2': result['counts']['green_area_km2']}

    def sample_cell(self, row, col):
        if not self.available:
            raise ValueError(self.error)
        if not (0 <= row < SHAPE[0] and 0 <= col < SHAPE[1]):
            return False
        with rasterio.open(self.path) as src:
            return int(src.read(1, window=Window(col, row, 1, 1))[0, 0]) == 1

    def tile_mask(self, z, x, y):
        bounds = tile_bounds(z, x, y)
        if not self.available:
            raise ValueError(self.error)
        return self._tile_mask(file_signature(self.path), file_signature(self.receipt), z, x, y, bounds)

    @staticmethod
    @lru_cache(maxsize=128)
    def _tile_mask(signature, receipt_signature, z, x, y, bounds):
        west, south, east, north = bounds
        destination = np.full((256, 256), 255, dtype='uint8')
        transform = Affine((east-west)/256, 0, west, 0, -(north-south)/256, north)
        with rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=64000000), rasterio.open(signature[0]) as src:
            reproject(rasterio.band(src, 1), destination,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=None,
                      dst_transform=transform, dst_crs='EPSG:3857', dst_nodata=255,
                      resampling=Resampling.nearest, init_dest_nodata=True, num_threads=1)
        result = destination == 1
        result.flags.writeable = False
        return result
