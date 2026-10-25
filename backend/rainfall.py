"""Native rainfall snapshots, independent of terrain and pluvial screening.

COGs are verified against every supplied Earth Engine value/mask. Rendering is
the only resampling operation. Native readouts, statistics and downloads remain
unchanged by display smoothing or threshold choices.
"""
import copy
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject

from .terrain import tile_bounds, png
from .tile_cache import file_signature, get_tile_cache

PRODUCTS = {
    'merged_250m': ('Merged radar + stations', 30, 250),
    'radar_bias_corrected_250m': ('Bias-corrected radar', 30, 250),
    'radar_raw_1km': ('Raw radar daily accumulation', 110, 1000),
}
PALETTE = ['f7fbff', 'c6dbef', '6baed6', '2171b5', '08306b', '54278f', 'e7298a']
PERIOD = {'local_date': '2025-06-27', 'timezone': 'Europe/Sofia',
          'start_utc': '2025-06-26T21:00:00Z', 'end_utc': '2025-06-27T21:00:00Z',
          'utc_start_inclusive': '2025-06-26T21:00:00Z',
          'utc_end_exclusive': '2025-06-27T21:00:00Z',
          'aggregation_window_verified_from_upstream_code': False}
LIMITATIONS = [
    'Daily accumulated precipitation in mm, not mm/hour; no sub-daily time series is supplied.',
    'The 250 m / 1 km names describe nominal output grids. Stored cells are geographic and their metric sizes vary; 250 m is not independently measured rainfall resolution.',
    'Outside each product or in its native mask rainfall is unavailable, not zero. Products have different coverage.',
    'OPERA radar and Weather Underground station attribution is retained. Upstream aggregation, station QC thresholds, correction/interpolation algorithms and uncertainty were not independently audited; their named programs are absent.',
    'No additional factor-of-four correction is applied. The supplied corrected/final totals are used as stored.',
    'Precipitation volume is rainfall falling on valid cells, not runoff, sewer load, floodwater, flood depth or flood probability.',
    'The event day is interpreted from the Europe/Sofia label; upstream temporal aggregation code is not supplied.',
    'Public redistribution rights for upstream OPERA / Weather Underground inputs were not independently verified.'
]
RENDER_VERSION = 'rainfall-native-mask-png-v1-zero-valid'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def product_id(value):
    if value not in PRODUCTS:
        raise ValueError('Unknown rainfall product')
    return value


def threshold_value(product, threshold):
    if threshold is None:
        return None
    if product != 'merged_250m':
        raise ValueError('The display threshold applies only to final merged rainfall')
    if not math.isfinite(threshold) or not 0 <= threshold <= 110:
        raise ValueError('Display threshold must be finite and between 0 and 110 mm')
    return float(threshold)


def ellipsoidal_statistics(values, valid, transform):
    """All valid native cells, WGS84 geodesic corner-polygon area per row.

    The arrays are north-up EPSG:4326, so each cell in a row has the same area.
    No fractional viewport selection or display threshold enters this sum.
    """
    geod = Geod(ellps='WGS84')
    areas = np.empty(values.shape, dtype=np.float64)
    for row in range(values.shape[0]):
        west, north = transform @ (0, row)
        east, south = transform @ (1, row + 1)
        area, _ = geod.polygon_area_perimeter([west, east, east, west], [north, north, south, south])
        areas[row, :] = abs(area)
    selected = values[valid].astype(np.float64)
    area = float(areas[valid].sum())
    volume = float((selected / 1000 * areas[valid]).sum())
    return {
        'scope': 'whole product; all valid native cells; outside / masked cells excluded',
        'area_method': 'WGS84 ellipsoidal four-corner geographic-cell polygon areas (pyproj.Geod); no display resampling',
        'valid_coverage_area_m2': area, 'valid_area_km2': area / 1e6,
        'valid_cell_count': int(valid.sum()), 'total_cell_count': int(valid.size),
        'masked_cell_count': int((~valid).sum()), 'min_mm': float(selected.min()),
        'max_mm': float(selected.max()), 'area_weighted_mean_mm': volume * 1000 / area,
        'mean_mm_unweighted': float(selected.mean()), 'precipitation_volume_m3': volume,
        'quantity': 'precipitation volume, not runoff or floodwater',
        'display_threshold_affects_statistics': False,
    }


def colour_rainfall(values, valid, maximum, threshold=None):
    """Continuous source palette, with explicit endpoint clipping."""
    levels = np.linspace(0, maximum, len(PALETTE))
    colours = np.asarray([[int(c[i:i + 2], 16) for i in (0, 2, 4)] for c in PALETTE])
    safe = np.where(np.isfinite(values), values, 0)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    for channel in range(3):
        rgba[..., channel] = np.rint(np.interp(safe, levels, colours[:, channel])).astype(np.uint8)
    shown = valid & np.isfinite(values)
    if threshold is not None:
        shown &= values > threshold
    rgba[..., 3] = np.where(shown, 255, 0)
    return rgba


class LocalRainfall:
    def __init__(self, data_dir, cache_dir):
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir)
        self.tiles = get_tile_cache(str(self.cache_dir / 'rendered_tiles'))

    def _paths(self):
        result = [self.data_dir / 'earth_engine_metadata.json', self.data_dir / 'wu_stations.geojson']
        for name in PRODUCTS:
            result += [self.data_dir / (name + '.tif'), self.data_dir / 'native_arrays' / (name + '.json')]
        return result

    def _signature(self):
        return tuple(file_signature(path) for path in self._paths())

    def _load(self):
        return self._validated(str(self.data_dir.resolve()), self._signature())

    @staticmethod
    @lru_cache(maxsize=4)
    def _validated(directory, signature):
        base = Path(directory)
        metadata = json.loads((base / 'earth_engine_metadata.json').read_text(encoding='utf-8'))
        stations = json.loads((base / 'wu_stations.geojson').read_text(encoding='utf-8'))
        features = stations['features']
        if len(features) != 55 or sum(f['properties'].get('qc') == 'ok' for f in features) != 43:
            raise ValueError('Rainfall station snapshot must retain all 55 records (43 accepted, 12 rejected)')
        station_ids = [f['properties']['station_id'] for f in features]
        if len(set(station_ids)) != 55 or any(f['geometry']['type'] != 'Point' for f in features):
            raise ValueError('Station IDs or original point geometry are invalid')
        for feature in features:
            props = feature['properties']
            lon, lat = feature['geometry']['coordinates'][:2]
            if not (-180 <= lon <= 180 and -90 <= lat <= 90 and
                    isinstance(props.get('rows'), int) and math.isfinite(props['rain_mm'])):
                raise ValueError('Original station value/coordinates are invalid')
        arrays, products = {}, {}
        paths = [base / 'earth_engine_metadata.json', base / 'wu_stations.geojson']
        for name, (label, maximum, nominal) in PRODUCTS.items():
            raster_path, array_path = base / (name + '.tif'), base / 'native_arrays' / (name + '.json')
            paths += [raster_path, array_path]
            record = json.loads(array_path.read_text(encoding='utf-8'))
            source = metadata['rasters'][name]
            band = source['bands'][0]
            if record['metadata'] != source or record['source_asset'] != source['id']:
                raise ValueError('Rainfall numeric snapshot and Earth Engine metadata differ')
            expected = np.asarray(record['values'], dtype=np.float32)
            valid = np.asarray(record['mask']) > 0
            width, height = band['dimensions']
            transform = Affine(*band['crs_transform'])
            if (band['id'] != 'rain_mm' or band['crs'] != 'EPSG:4326' or
                    expected.shape != valid.shape or expected.shape != (height, width) or
                    transform.b or transform.d or transform.a <= 0 or transform.e >= 0):
                raise ValueError('Unexpected rainfall native grid or band semantics')
            if not np.isfinite(expected[valid]).all() or (expected[valid] < 0).any() or not valid.any():
                raise ValueError('Rainfall snapshot contains invalid native totals')
            # A full-size read with no out_shape is native. GDAL's explicit
            # OVERVIEW_LEVEL=NONE virtual view omits the COG band description.
            with rasterio.open(raster_path) as src:
                values, mask = src.read(1), src.read_masks(1) > 0
                if (src.crs.to_string() != band['crs'] or src.transform != transform or
                        src.shape != expected.shape or src.count != 1 or src.dtypes[0] != 'float32' or
                        src.nodata != -9999 or src.descriptions[0] != 'rain_mm' or
                        not np.array_equal(mask, valid) or
                        not np.array_equal(values, np.where(valid, expected, np.float32(-9999)))):
                    raise ValueError('Rainfall COG values, masks or native grid differ from supplied snapshot')
                bbox = list(src.bounds)
                tiff_band_description = src.descriptions[0]
            values.setflags(write=False)
            valid.setflags(write=False)
            arrays[name] = (values, valid, transform)
            summary = ellipsoidal_statistics(values, valid, transform)
            products[name] = {
                'id': name, 'label': label, 'asset_id': source['id'], 'source_version': source.get('version'),
                'units': 'mm', 'band': 'rain_mm', 'range_mm': [0, maximum], 'display_range_mm': [0, maximum],
                'palette': PALETTE, 'colour_interpolation': 'continuous',
                'legend': [{'value': float(v), 'colour': '#' + c} for v, c in zip(np.linspace(0, maximum, 7), PALETTE)],
                'endpoint_clipping': f'Colours clamp to 0–{maximum} mm; native values remain unchanged',
                'default_threshold_mm': .5 if name == 'merged_250m' else None,
                'default_display_threshold_mm': .5 if name == 'merged_250m' else None,
                'bbox': bbox, 'coverage_bbox_wgs84': bbox,
                'grid': {'crs': band['crs'], 'transform': list(transform)[:6], 'width': width, 'height': height,
                         'nodata': -9999, 'band': 'rain_mm', 'tiff_band_index': 1,
                         'tiff_band_description': tiff_band_description, 'nominal_product_grid_m': nominal,
                         'note': 'Stored geographic cells; metric dimensions vary. Nominal output grid is not independently measured rainfall resolution.'},
                'summary': summary,
            }
        hashes = {str(p.relative_to(base)).replace('\\', '/'): sha256(p) for p in paths}
        revision = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
        for name in products:
            products[name]['revision'] = revision + '-' + name
        result = {'meta': {'available': True, 'revision': revision,
                          'title': 'Rainfall — 27 June 2025', 'units': 'mm',
                          'quantity': 'daily accumulated precipitation', 'period': PERIOD,
                          'default_product': 'merged_250m', 'default_visible': True, 'default_opacity': .7,
                          'products': products, 'palette': PALETTE,
                          'smoothing_options': ['nearest', 'bilinear'], 'default_smoothing': 'nearest',
                          'stations': {'total': 55, 'accepted': 43, 'rejected': 12,
                                       'accepted_count': 43, 'rejected_count': 12, 'accepted_qc': 'ok',
                                       'accepted_default_visible': True, 'rejected_default_visible': False},
                          'source_label': 'Supplied Earth Engine native-pixel copies; OPERA radar + Weather Underground stations',
                          'source_script': 'handoff/rainfall_supplement/earth_engine/Rainfall_20250627_original.js',
                          'provenance': 'Complete native numeric asset snapshots, not original pre-upload TIFF bytes; no resampling during transfer',
                          'source_files_sha256': hashes, 'limitations': LIMITATIONS},
                  'arrays': arrays, 'stations': stations}
        actual = tuple(file_signature(path) for path in paths)
        if actual != signature:
            raise ValueError('Rainfall source files changed while validating; reload after transfer completes')
        return result

    @property
    def available(self):
        try:
            self._load()
            return True
        except (OSError, ValueError, KeyError, TypeError, rasterio.errors.RasterioError):
            return False

    def meta(self):
        try:
            return copy.deepcopy(self._load()['meta'])
        except (OSError, ValueError, KeyError, TypeError, rasterio.errors.RasterioError) as error:
            return {'available': False, 'revision': 'unavailable', 'title': 'Rainfall — 27 June 2025',
                    'products': {}, 'period': PERIOD, 'units': 'mm',
                    'message': 'Native rainfall snapshot is missing or fails verification; no substituted totals are supplied.',
                    'validation_error': str(error), 'limitations': LIMITATIONS}

    def statistics(self, product):
        product_id(product)
        data = self._load()['meta']
        return {**copy.deepcopy(data['products'][product]['summary']), 'product': product,
                'label': data['products'][product]['label'], 'units': 'mm', 'period': PERIOD,
                'revision': data['revision']}

    def stations(self):
        return copy.deepcopy(self._load()['stations'])

    def sample(self, lon, lat, product=None, threshold=None):
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError('Finite geographic coordinates required')
        if product is not None:
            product_id(product)
        threshold_value(product or 'merged_250m', threshold)
        loaded = self._load()
        results = {}
        for name, (values, valid, transform) in loaded['arrays'].items():
            column, row = (~transform) @ (lon, lat)
            row, column = math.floor(row), math.floor(column)
            result = {'product': name, 'label': PRODUCTS[name][0], 'status': 'nodata', 'rain_mm': None,
                      'row': row, 'column': column, 'sampling': 'containing native cell; no interpolation',
                      'reason': 'outside_coverage', 'hidden_by_display_threshold': False}
            if 0 <= row < values.shape[0] and 0 <= column < values.shape[1]:
                center = transform @ (column + .5, row + .5)
                result.update(pixel_center_longitude=center[0], pixel_center_latitude=center[1])
                if valid[row, column]:
                    value = float(values[row, column])
                    result.update(status='ok', reason=None, rain_mm=value,
                                  hidden_by_display_threshold=name == 'merged_250m' and threshold is not None and value <= threshold)
                else:
                    result['reason'] = 'masked_native_cell'
            results[name] = result
        result = {'status': 'ok', 'longitude': lon, 'latitude': lat, 'products': results,
                  'revision': loaded['meta']['revision'], 'period': PERIOD, 'units': 'mm'}
        if product:
            result.update(selected_product=product, **{k: v for k, v in results[product].items() if k != 'product'})
        return result

    def _warped_values(self, product, z, x, y, smoothing='nearest'):
        product_id(product)
        if smoothing not in ['nearest', 'bilinear']:
            raise ValueError('Unknown rainfall display smoothing')
        west, south, east, north = tile_bounds(z, x, y)
        destination_transform = Affine((east - west) / 256, 0, west, 0, -(north - south) / 256, north)
        values, valid, transform = self._load()['arrays'][product]
        output = np.full((256, 256), np.nan, dtype=np.float32)
        # Zero is valid both as rainfall and as a validity-mask value. Never use
        # destination_nodata=0 for the 0/1 mask: it can expand water/coverage.
        coverage = np.full((256, 256), np.nan, dtype=np.float32)
        with rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=16000000):
            options = {'src_transform': transform, 'src_crs': 'EPSG:4326',
                       'dst_transform': destination_transform, 'dst_crs': 'EPSG:3857',
                       'num_threads': 1, 'warp_mem_limit': 16}
            reproject(values, output, src_nodata=-9999, dst_nodata=np.nan,
                      resampling=Resampling.nearest if smoothing == 'nearest' else Resampling.bilinear, **options)
            reproject(valid.astype(np.float32), coverage, src_nodata=None, dst_nodata=np.nan,
                      resampling=Resampling.nearest, **options)
        return output, np.isfinite(coverage) & (coverage > .5)

    def tile(self, product, z, x, y, smoothing='nearest', threshold=None):
        product_id(product)
        threshold = threshold_value(product, threshold)
        tile_bounds(z, x, y)
        revision = self._load()['meta']['revision']
        key = [RENDER_VERSION, file_signature(__file__), revision, product, z, x, y, smoothing, threshold]
        def render():
            values, valid = self._warped_values(product, z, x, y, smoothing)
            return png(colour_rainfall(values, valid, PRODUCTS[product][1], threshold))
        return self.tiles.get_or_render(key, render)

    def write_cache(self):
        data = self.meta()
        if not data['available']:
            raise ValueError(data['message'] + ' ' + data.get('validation_error', ''))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / 'rainfall_meta.json'
        path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')
        return path
