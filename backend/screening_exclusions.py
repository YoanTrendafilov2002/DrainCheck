"""User-requested river-channel/stadium display policy, separate from terrain.

Bit 1 identifies mapped channels; bit 2 identifies mapped stadium footprints.
Neither exclusion is evidence that a location cannot flood. Original terrain,
water masks and historical observations are preserved.
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

SHAPE = (10869, 10345)
GRID = Affine(5, 0, 299392, 0, -5, 4753611)
VALIDATION_LOCK = threading.RLock()
REASONS = {1: 'river', 2: 'stadium', 3: 'river_and_stadium'}


class ScreeningExclusions:
    def __init__(self, cache):
        self.path = Path(cache)/'screening_exclusions_5m.tif'
        self.receipt = Path(cache)/'screening_exclusions_meta.json'
        self.error = 'Prepare the mapped river-channel and stadium screening exclusions.'

    @property
    def available(self):
        try:
            meta = read_json_cached(self.receipt)
            checksum = meta.get('sha256', '')
            counts = meta.get('counts', {})
            if (not meta.get('available') or meta.get('exclusions_are_policy') is not True
                    or len(checksum) != 64 or meta.get('revision') != checksum[:16]
                    or any(type(counts.get(key)) is not int or counts[key] <= 0
                           for key in ('river_channel_cells', 'stadium_cells', 'union_cells'))):
                raise ValueError('Screening-exclusion receipt is incomplete or inconsistent')
            grid = meta.get('grid', {})
            if (grid.get('crs') != 'EPSG:7801' or grid.get('height') != SHAPE[0]
                    or grid.get('width') != SHAPE[1] or grid.get('transform') != list(GRID)[:6]
                    or 'nodata' not in grid or grid['nodata'] is not None):
                raise ValueError('Screening-exclusion receipt declares a different grid')
            with VALIDATION_LOCK:
                self._validate(file_signature(self.path), file_signature(self.receipt), checksum,
                               tuple(counts[key] for key in ('river_channel_cells', 'stadium_cells', 'union_cells')))
            self.error = ''
            return True
        except (OSError, KeyError, TypeError, ValueError, rasterio.errors.RasterioError) as error:
            self.error = 'River/stadium screening exclusions unavailable or invalid: '+str(error)
            return False

    @staticmethod
    @lru_cache(maxsize=4)
    def _validate(signature, receipt_signature, expected_sha256, expected_counts):
        checksum = hashlib.sha256()
        with Path(signature[0]).open('rb') as stream:
            for block in iter(lambda: stream.read(8*1024*1024), b''):
                checksum.update(block)
        if checksum.hexdigest() != expected_sha256:
            raise ValueError('Screening-exclusion raster checksum differs from its receipt')
        counts = np.zeros(3, dtype='int64')
        with rasterio.open(signature[0]) as src:
            if (src.crs is None or src.crs.to_epsg() != 7801 or src.shape != SHAPE
                    or src.count != 1 or src.dtypes != ('uint8',) or src.nodata is not None
                    or src.transform != GRID):
                raise ValueError('Screening-exclusion raster is not the verified 5 m grid')
            for _, window in src.block_windows(1):
                values = src.read(1, window=window)
                if np.any(values > 3):
                    raise ValueError('Screening-exclusion raster contains unsupported flags')
                counts += [np.count_nonzero(values & 1), np.count_nonzero(values & 2),
                           np.count_nonzero(values)]
        if tuple(counts) != expected_counts:
            raise ValueError('Screening-exclusion counts differ from the receipt')

    def meta(self):
        if not self.available:
            return {'available': False, 'enabled': True, 'message': self.error}
        return {**read_json_cached(self.receipt), 'enabled': True,
                'interpretation': 'Mapped river channels and stadium footprints are omitted from screening and scenarios at the user’s request. Exclusion does not mean safe from flooding; original terrain and historical observations remain unchanged.'}

    def sample_cell(self, row, col):
        if not self.available:
            raise ValueError(self.error)
        if not (0 <= row < SHAPE[0] and 0 <= col < SHAPE[1]):
            return 0
        with rasterio.open(self.path) as src:
            return int(src.read(1, window=Window(col, row, 1, 1))[0, 0])

    def tile_mask(self, z, x, y):
        bounds = tile_bounds(z, x, y)
        if not self.available:
            raise ValueError(self.error)
        return self._tile_mask(file_signature(self.path), file_signature(self.receipt), bounds)

    @staticmethod
    @lru_cache(maxsize=128)
    def _tile_mask(signature, receipt_signature, bounds):
        west, south, east, north = bounds
        destination = np.full((256, 256), 255, dtype='uint8')
        transform = Affine((east-west)/256, 0, west, 0, -(north-south)/256, north)
        with rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=64000000), rasterio.open(signature[0]) as src:
            reproject(rasterio.band(src, 1), destination,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=None,
                      dst_transform=transform, dst_crs='EPSG:3857', dst_nodata=255,
                      resampling=Resampling.nearest, init_dest_nodata=True, num_threads=1)
        result = (destination > 0) & (destination != 255)
        result.flags.writeable = False
        return result
