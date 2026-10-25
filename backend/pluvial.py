"""Read-only 5 m terrain screening. Scores are relative indicators, not probabilities.

There is intentionally no rain, runoff coefficient, sewer-capacity estimate, or
fabricated imperviousness in this adapter. The preprocessing receipt defines the
reference distribution and every analytical choice.
"""
import json, math,hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import Affine
from rasterio.windows import Window
from rasterio.warp import reproject
from rasterio.enums import Resampling

from .terrain import XY, RASTER_SLOTS, tile_bounds, png
from .tile_cache import file_signature,read_json_cached,get_tile_cache
from .open_water import OpenWaterMask

METHOD_VERSION = 'terrain-relative-screen-v1'
NODATA = -9999.0
SCORE_THRESHOLDS = (50, 70, 85)
CLASS_LABELS = ('Lower signal', 'Raised', 'Higher signal', 'Strongest signal')
PALETTE = np.array([[255, 225, 150, 65], [250, 173, 66, 135],
                    [238, 91, 56, 190], [143, 32, 107, 215]], dtype=np.uint8)
LAYERS = {'screening': 8, 'depressions': 6, 'heatmap': 6, 'concentration': 7, 'boundary': 5}
HEATMAP_STOPS = np.array([0, 25, 50, 70, 85, 100], dtype=np.float32)
HEATMAP_RGBA = np.array([[255, 246, 180, 0], [255, 225, 125, 25],
                        [255, 178, 45, 105], [246, 98, 33, 185],
                        [218, 37, 83, 225], [130, 24, 144, 245]], dtype=np.uint8)
BAND_NAMES = ('mean_ground_elevation_m', 'depression_fill_depth_m', 'slope_degrees',
              'upstream_contributing_area_m2', 'possible_missing_upstream_terrain',
              'depression_percentile', 'concentration_flatness_score', 'relative_screening_score')


def percentile_definition(values, count=201):
    """Compact deterministic percentile curve with equal values given a midrank."""
    values = np.asarray(values, dtype=np.float32)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError('No observations for percentile reference')
    q = np.quantile(values, np.linspace(0, 1, count))
    unique, inverse = np.unique(q, return_inverse=True)
    levels = np.linspace(0, 1, count)
    midranks = np.bincount(inverse, weights=levels) / np.bincount(inverse)
    return {'values': unique.tolist(), 'ranks': midranks.tolist(), 'sample_count': int(values.size),
            'quantile_count': count, 'tie_rule': 'mean percentile position of repeated quantiles'}


def rank(values, definition):
    a = np.asarray(values, dtype=np.float32)
    x = np.asarray(definition['values'], dtype=np.float64)
    y = np.asarray(definition['ranks'], dtype=np.float64)
    if (not len(x) or len(x) != len(y) or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y)) or np.any(np.diff(x) <= 0)
        or np.any(np.diff(y) < 0) or np.any((y < 0) | (y > 1))):
        raise ValueError('Invalid percentile reference')
    result = np.interp(a, x, y, left=0, right=1).astype(np.float32)
    return np.where(np.isfinite(a), result, np.nan).astype(np.float32)


def score_arrays(depth, slope, area, boundary, references, nodata=NODATA):
    """Separate terrain pathways; no fitted coefficients or missing-factor zeroes."""
    depth, slope, area, boundary = [np.asarray(v, dtype=np.float32) for v in (depth, slope, area, boundary)]
    valid = (np.isfinite(depth) & np.isfinite(slope) & np.isfinite(area) & np.isfinite(boundary)
             & (depth >= 0) & (slope >= 0) & (slope <= 90) & (area >= 25) & (boundary == 0))
    depression = np.zeros(depth.shape, dtype=np.float32)
    positive = depth > 0
    if references.get('depth_positive'):
        depression[positive] = rank(depth[positive], references['depth_positive'])
    # If no positive depressions exist in the reference, their pathway cannot be ranked.
    elif np.any(positive & valid):
        valid &= ~positive
    concentration = np.sqrt(np.clip(rank(area, references['area']) *
                                   (1-rank(slope, references['slope'])), 0, 1))
    combined = np.maximum(depression, concentration)
    for a in (depression, concentration, combined):
        a *= 100
        a[~valid] = nodata
    return depression, concentration, combined, valid


def class_indices(values):
    values = np.asarray(values)
    return np.searchsorted(SCORE_THRESHOLDS, values, side='right').astype(np.uint8)


def colour_rgba(values, layer='screening'):
    values = np.asarray(values)
    valid = np.isfinite(values) & (values != NODATA)
    if layer == 'boundary':
        result = np.zeros((*values.shape, 4), dtype=np.uint8)
        result[valid & (values == 1)] = [120, 127, 136, 185]
        return result
    result = PALETTE[class_indices(np.clip(np.nan_to_num(values), 0, 100))].copy()
    result[~valid] = 0
    return result


def heatmap_rgba(values):
    """Continuous colour of unchanged ponding P; no spatial smoothing or density fit.

    Zero is valid lower signal with transparent tint. Missing/out-of-range values
    remain transparent; the tile renderer separately applies uncertainty/water.
    """
    values = np.asarray(values, dtype=np.float32)
    valid = np.isfinite(values) & (values >= 0) & (values <= 100)
    safe = np.where(valid, values, 0)
    result = np.stack([np.interp(safe, HEATMAP_STOPS, HEATMAP_RGBA[:, channel])
                       for channel in range(4)], axis=-1)
    result = np.rint(result).astype(np.uint8)
    result[~valid] = 0
    return result


class LocalPluvial:
    def __init__(self, cache: Path):
        self.cache = Path(cache)
        self.path = self.cache/'pluvial_5m.tif'
        self.receipt = self.cache/'pluvial_provenance.json'
        self.tiles=get_tile_cache(str((self.cache/'rendered_tiles').resolve()))
        self.water=OpenWaterMask(self.cache)

    @property
    def available(self):
        return self.source_available and self.water.available

    @property
    def source_available(self):
        try:
            s = self.path.stat()
            self._validate(str(self.path), s.st_size, s.st_mtime_ns)
            return self.receipt.is_file()
        except (OSError, ValueError, rasterio.errors.RasterioError):
            return False

    @staticmethod
    @lru_cache(maxsize=2)
    def _validate(path, size, modified):
        with rasterio.open(path) as src:
            if (src.crs is None or src.crs.to_epsg() != 7801 or src.shape != (10869, 10345)
                or src.count != 8 or set(src.dtypes) != {'float32'} or src.nodata != NODATA
                or list(src.transform)[:6] != [5, 0, 299392, 0, -5, 4753611]
                or tuple(src.descriptions) != BAND_NAMES):
                raise ValueError('Invalid Sofia terrain-screening raster')

    def meta(self):
        if not self.source_available:
            return {'available': False, 'message': 'Run python scripts/prepare_pluvial.py with the real verified terrain inputs.'}
        water=self.water.meta()
        if not water.get('available'):
            return {'available':False,'terrain_available':True,'water_exclusion':water,'message':water.get('message','Mapped-water exclusion unavailable; screening cannot be rendered.')}
        result=read_json_cached(self.receipt);terrain_revision=result['revision']
        result['source_screening']={k:result.get(k) for k in ['classes','counts','sensitivity','revision']}
        result['terrain_revision']=terrain_revision
        result['revision']=hashlib.sha256(('mapped-water-v1:'+terrain_revision+':'+water['revision']).encode()).hexdigest()[:16]
        return {'available':True,**result,'water_exclusion':water}

    def sample(self, lon, lat):
        if not self.available:
            raise ValueError('Terrain screening unavailable')
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError('Finite coordinates required')
        x, y = XY.transform(lon, lat)
        result = {'longitude': lon, 'latitude': lat, 'analysis_resolution_m': 5,
                  'method': METHOD_VERSION, 'status': 'nodata', 'class': None, 'score': None,'water_excluded':False}
        with rasterio.open(self.path, OVERVIEW_LEVEL='NONE') as src:
            row, col = src.index(x, y)
            if not (0 <= row < src.height and 0 <= col < src.width):
                return result
            a = src.read(window=Window(col, row, 1, 1))[:, 0, 0]
            factors = {name: float(v) if math.isfinite(float(v)) and v != NODATA else None
                       for name, v in zip(BAND_NAMES, a)}
            result.update({'row': int(row), 'column': int(col), 'factors': factors,
                           'pixel_center': list(src.xy(row, col)), 'crs': 'EPSG:7801'})
            result.update(ponding_score=factors['depression_percentile'],
                          concentration_score=factors['concentration_flatness_score'],
                          depression_depth_m=factors['depression_fill_depth_m'],
                          slope_degrees=factors['slope_degrees'],
                          contributing_area_m2=factors['upstream_contributing_area_m2'],
                          boundary_influence=factors['possible_missing_upstream_terrain'] == 1,
                          class_label=None)
            if self.water.sample_cell(row,col):
                original={name:factors[name] for name in BAND_NAMES[5:]}
                for name in BAND_NAMES[5:]:factors[name]=None
                result.update(status='excluded_open_water',water_excluded=True,score=None,class_label=None,
                              ponding_score=None,concentration_score=None,unmasked_scores=original,
                              exclusion_reason='mapped-open-water',message='Mapped existing open water is excluded from terrestrial pluvial screening; no safe/unsafe score is assigned.')
            elif factors['possible_missing_upstream_terrain'] == 1:
                result.update(status='uncertain', exclusion_reason='boundary-influence', message='Upstream terrain may extend beyond the available DTM; no screening class assigned.')
            elif factors['relative_screening_score'] is not None:
                score = factors['relative_screening_score']
                idx = int(class_indices(score))
                depression = factors['depression_percentile']
                concentration = factors['concentration_flatness_score']
                result.update(status='ok', score=score, class_label=CLASS_LABELS[idx], **{'class': CLASS_LABELS[idx], 'class_index': idx},
                              dominant_pathway='depression' if depression > concentration else 'concentration / low slope')
            elif factors['mean_ground_elevation_m'] is not None:
                result.update(status='uncertain', exclusion_reason='invalid-factor', message='Terrain is present, but a required terrain factor is missing or invalid; no screening class assigned.')
            return result

    def tile(self, mode, z, x, y, revision=''):
        if not self.available:
            raise ValueError('Terrain screening unavailable')
        if mode not in LAYERS:
            raise ValueError('Unknown terrain screening layer')
        tile_bounds(z,x,y)
        key=['pluvial-mapped-water-png-v2-zero-valid',rasterio.__version__,Image.__version__,mode,z,x,y,revision,
             file_signature(self.path),file_signature(self.receipt),file_signature(self.water.path),
             file_signature(self.water.receipt),file_signature(__file__),file_signature(Path(__file__).with_name('open_water.py'))]
        return self.tiles.get_or_render(key,lambda:self._render_tile(mode,z,x,y))

    def _render_tile(self,mode,z,x,y):
        west, south, east, north = tile_bounds(z, x, y)
        spacing = (east-west)/256
        dst = np.full((256, 256), np.nan, dtype=np.float32)
        with RASTER_SLOTS, rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=64000000), rasterio.open(self.path) as src:
            reproject(rasterio.band(src, LAYERS[mode]), dst,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=NODATA,
                      dst_transform=Affine(spacing, 0, west, 0, -spacing, north), dst_crs='EPSG:3857',
                      dst_nodata=np.nan, resampling=Resampling.nearest, num_threads=1, warp_mem_limit=64)
            # Known terrain with an excluded score is grey; outside coverage remains transparent.
            terrain = np.full((256, 256), np.nan, dtype=np.float32)
            if mode != 'boundary':
                reproject(rasterio.band(src, 1), terrain,
                          src_transform=src.transform, src_crs=src.crs, src_nodata=NODATA,
                          dst_transform=Affine(spacing, 0, west, 0, -spacing, north), dst_crs='EPSG:3857',
                          dst_nodata=np.nan, resampling=Resampling.nearest, num_threads=1, warp_mem_limit=64)
            # Both0and1are valid source classes. Using dst_nodata=0 makes GDAL
            # treat the legitimate zero background as missing and can spread
            # water across land when upsampling. NaN is an unambiguous outside
            # sentinel; do not assign nodata to either binary source class.
            water=np.full((256,256),np.nan,dtype=np.float32)
            with rasterio.open(self.water.path) as mask:
                reproject(rasterio.band(mask,1),water,src_transform=mask.transform,src_crs=mask.crs,
                          src_nodata=None,
                          dst_transform=Affine(spacing,0,west,0,-spacing,north),dst_crs='EPSG:3857',
                          dst_nodata=np.nan,resampling=Resampling.nearest,num_threads=1,warp_mem_limit=64)
        rgba = heatmap_rgba(dst) if mode == 'heatmap' else colour_rgba(dst, mode)
        if mode != 'boundary':
            rgba[np.isfinite(terrain) & ~np.isfinite(dst)] = [120, 127, 136, 155]
        rgba[water==1,3]=0
        return png(rgba)
