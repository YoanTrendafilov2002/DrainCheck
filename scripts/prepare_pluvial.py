"""Build a relative, terrain-only screening raster from real verified Sofia inputs.

No source raster is written. Rank references are deterministic 20 m samples of
the aligned 5 m analysis grid, with 201 quantiles; they are not a full-cell ECDF.
The resulting score has no calibrated probability, event frequency or depth.
"""
import argparse, hashlib, json, sys, time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from rasterio.warp import transform_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pluvial import (BAND_NAMES, CLASS_LABELS, METHOD_VERSION, NODATA,
                            SCORE_THRESHOLDS, class_indices, percentile_definition, score_arrays)

EXPECTED_INPUT_HASH = '62f71c04d766d8d5688655f0b2230429154a61a92d6a488a3a485dfc479ca71e'
EXPECTED_NATIVE_HASH = 'bc76434415d1ea6ee7dccb44d1dcaf35381914ff3129fb7398f38a9cc7e212a3'
INPUT_NAMES = ('mean_ground_elevation_m', 'depression_fill_depth_m', 'slope_degrees',
               'upstream_contributing_area_m2', 'possible_missing_upstream_terrain',
               'imperviousness_density_2024_pct', 'upstream_sealed_area_m2',
               'missing_upstream_imperviousness')
STRIDE = 4


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def windows(src, size=512):
    for row in range(0, src.height, size):
        for col in range(0, src.width, size):
            yield Window(col, row, min(size, src.width-col), min(size, src.height-row))


def validate_source(src):
    if (src.crs is None or src.crs.to_epsg() != 7801 or src.shape != (10869, 10345)
        or src.count != 8 or set(src.dtypes) != {'float32'} or src.nodata != NODATA
        or list(src.transform)[:6] != [5, 0, 299392, 0, -5, 4753611]
        or tuple(src.descriptions) != INPUT_NAMES):
        raise ValueError('Only the verified aligned 5 m Sofia input raster is supported')


def make_references(src):
    depth_parts, slope_parts, area_parts = [], [], []
    excluded = [0, 0, 0]
    for window in windows(src):
        a = src.read(window=window)
        for i in range(3):
            excluded[i] += int(np.count_nonzero(a[5+i] != NODATA))
        # Global row/column modulo4, independent of IO block size.
        ro = (-int(window.row_off)) % STRIDE
        co = (-int(window.col_off)) % STRIDE
        depth, slope, area, boundary = a[1:5, ro::STRIDE, co::STRIDE]
        valid = (np.isfinite(depth) & np.isfinite(slope) & np.isfinite(area)
                 & (depth >= 0) & (slope >= 0) & (slope <= 90) & (area >= 25) & (boundary == 0))
        depth_parts.append(depth[valid & (depth > 0)])
        slope_parts.append(slope[valid])
        area_parts.append(area[valid])
    if excluded != [0, 0, 0]:
        raise ValueError('The expected missing imperviousness bands changed; review source provenance')
    depth = np.concatenate(depth_parts)
    return {'depth_positive': percentile_definition(depth) if depth.size else None,
            'slope': percentile_definition(np.concatenate(slope_parts)),
            'area': percentile_definition(np.concatenate(area_parts))}


def prepare(source, native, cache, force=False):
    started = time.monotonic()
    source, native, cache = Path(source).resolve(), Path(native).resolve(), Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise FileNotFoundError('Acquire the actual verified Sofia 5 m terrain input: '+str(source))
    source_hash = sha256(source)
    if source_hash != EXPECTED_INPUT_HASH:
        raise ValueError('Input SHA256 differs from the verified real Sofia raster')
    native_hash = sha256(native) if native.is_file() else None
    if native_hash is not None and native_hash != EXPECTED_NATIVE_HASH:
        raise ValueError('Native DTM differs from the verified unmodified municipal source')
    output = cache/'pluvial_5m.tif'
    receipt_path = cache/'pluvial_provenance.json'
    if output.exists() and receipt_path.exists() and not force:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('method') == METHOD_VERSION and receipt.get('source', {}).get('sha256') == source_hash:
            print(json.dumps({'stage': 'already-prepared', 'output': str(output)}), flush=True)
            return receipt
    temporary = cache/'pluvial_5m.pending.tif'
    # A full-resolution window read uses base pixels without out_shape. GDAL's
    # OVERVIEW_LEVEL=NONE virtual dataset drops band descriptions, so do not use
    # that option when checking this signed input's descriptive band schema.
    with rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=128000000), rasterio.open(source) as src:
        validate_source(src)
        print(json.dumps({'stage': 'reference-distributions', 'source_hash_verified': True}), flush=True)
        refs = make_references(src)
        profile = src.profile.copy()
        profile.update(count=8, compress='DEFLATE', predictor=3, tiled=True, blockxsize=512,
                       blockysize=512, interleave='band', bigtiff='IF_SAFER', nodata=NODATA)
        classes = np.zeros(4, dtype=np.int64)
        sensitivity = {str(v): 0 for v in (70, 80, 90)}
        valid_total = terrain_total = boundary_total = invalid_factors = positive_depressions = 0
        depression_dominant = concentration_dominant = 0
        with rasterio.open(temporary, 'w', **profile) as dst:
            for i, name in enumerate(BAND_NAMES, 1):
                dst.set_band_description(i, name)
            dst.update_tags(METHOD=METHOD_VERSION, VERTICAL_DATUM='Baltic 1982',
                            SCORE_UNITS='0..100 relative terrain indicator; not probability or flood depth',
                            RANK_REFERENCE='Global row/column modulo4 of 5 m grid: deterministic20 m sample;201quantiles',
                            SOURCE_SHA256=source_hash, BOUNDARY_POLICY='Excluded from scores; retained as explicit band5')
            for index, window in enumerate(windows(src)):
                a = src.read([1, 2, 3, 4, 5], window=window)
                depression, concentration, combined, valid = score_arrays(*a[1:5], refs)
                terrain = np.isfinite(a[0]) & (a[0] != NODATA)
                valid &= terrain
                for score in (depression, concentration, combined):
                    score[~valid] = NODATA
                output_values = np.concatenate((a, np.stack((depression, concentration, combined))))
                dst.write(output_values, window=window)
                terrain_total += int(terrain.sum())
                boundary_total += int((terrain & (a[4] == 1)).sum())
                invalid_factors += int((terrain & (a[4] != 1) & ~valid).sum())
                valid_total += int(valid.sum())
                positive_depressions += int((valid & (a[1] > 0)).sum())
                classes += np.bincount(class_indices(combined[valid]), minlength=4)
                depression_dominant += int((valid & (depression > concentration)).sum())
                concentration_dominant += int((valid & (depression <= concentration)).sum())
                for threshold in sensitivity:
                    sensitivity[threshold] += int((valid & (combined >= int(threshold))).sum())
                if index % 100 == 0:
                    print(json.dumps({'stage': 'write-screening', 'blocks': index, 'valid_cells': valid_total}), flush=True)
            dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
            dst.update_tags(ns='rio_overview', resampling='nearest')
        # Full 5 m factor verification, not just a sparse spot check.
        with rasterio.open(temporary, OVERVIEW_LEVEL='NONE') as actual:
            for window in windows(src):
                expected = src.read([1, 2, 3, 4, 5], window=window)
                factors = actual.read([1, 2, 3, 4, 5], window=window)
                if not np.array_equal(expected, factors, equal_nan=True):
                    raise AssertionError('A source factor changed during metadata-preserving copy')
                scores = actual.read([6, 7, 8], window=window)
                nonmissing = scores != NODATA
                if np.any(~np.isfinite(scores[nonmissing])) or np.any((scores[nonmissing] < 0) | (scores[nonmissing] > 100)):
                    raise AssertionError('Invalid relative score')
    if sha256(source) != source_hash:
        raise AssertionError('Source raster changed during preprocessing')
    if native_hash is not None and sha256(native) != native_hash:
        raise AssertionError('Original native terrain changed during preprocessing')
    temporary.replace(output)
    receipt = {
        'method': METHOD_VERSION, 'title': 'Terrain-only pluvial screening',
        'score_units': '0..100 relative terrain signal; not flood likelihood, frequency, depth or calibrated risk',
        'analysis_resolution_m': 5, 'native_terrain_resolution_m': 1,
        'grid': {'crs': 'EPSG:7801', 'shape': [10869, 10345], 'transform': [5, 0, 299392, 0, -5, 4753611], 'nodata': NODATA},
        'bands': list(BAND_NAMES), 'source': {'file': str(source), 'sha256': source_hash,
                                             'missing_imperviousness_bands_confirmed': [6, 7, 8]},
        'native_source': {'file': str(native), 'sha256': native_hash, 'unchanged_before_after': native_hash is not None},
        'formula': {'depression': '100 × percentile of positive depression-fill depth; exactly zero depth ->0',
                    'concentration': '100 × sqrt(percentile(contributing area) × (1−percentile(slope)))',
                    'combined': 'max(depression, concentration)',
                    'choice_status': 'Analyst-designed exploratory index. Formula, reference and thresholds have not been calibrated against observed Sofia floods.'},
        'rank_reference': {'spacing_m': 20, 'sampling': 'Global row and column divisible by4 on the aligned5m grid; valid unflagged cells only',
                           'quantiles': 201, 'scope': 'Entire available municipal DTM coverage, including mountains; not city-only',
                           'approximation': 'Interpolated201quantile reference; not exact full5m-cell empirical CDF', 'references': refs},
        'classes': [{'label': label, 'minimum': float(([0]+list(SCORE_THRESHOLDS))[i]),
                     'maximum': float((list(SCORE_THRESHOLDS)+[100])[i]), 'cells': int(classes[i]),
                     'area_km2': float(classes[i]*25/1e6)} for i, label in enumerate(CLASS_LABELS)],
        'threshold_status': '50/70/85 are analyst-selected display cutoffs, not validated flood thresholds',
        'counts': {'terrain_cells': terrain_total, 'eligible_cells': valid_total,
                   'boundary_excluded_cells': boundary_total, 'other_invalid_factor_cells': invalid_factors,
                   'positive_depression_cells': positive_depressions,
                   'depression_dominant_cells': depression_dominant, 'concentration_dominant_cells': concentration_dominant},
        'sensitivity': [{'score_at_least': int(v), 'cells': n, 'area_km2': n*25/1e6,
                         'percent_eligible': n/valid_total*100} for v, n in sensitivity.items()],
        'exclusion_policy': 'Boundary-influenced cells and invalid slope/other factors receive no score. Known terrain with no score is grey; outside DTM is transparent.',
        'limitations': ['Depression-fill depth measures potential topographic storage against a filled surface; it is not predicted floodwater depth.',
                        'Contributing area and low slope indicate potential concentration; mapped river channels can also score strongly, so this does not isolate pluvial from fluvial flooding.',
                        'No rainfall intensity/duration, infiltration, imperviousness, sewer capacity, building barriers, kerbs, culverts or flood observations enter the score.',
                        'Green-area polygons and sewer points/routes are context or exposure; neither establishes infiltration nor functioning storm-drain capacity.',
                        'DTM1m grid spacing does not establish1m vertical accuracy. Feature age/contour derivation and drainage changes limit street-level interpretation.',
                        'No ranking is a safe/unsafe verdict. Quantitative risk requires hazard, exposed assets and vulnerability, with event observations for validation.'],
        'verification': {'source_grid_and_hash_verified': True, 'all_missing_imd_cells_checked': True,
                         'all_first5bands_pixel_equal_to_source': True, 'score_range_checked_all_cells': True,
                         'source_hash_unchanged_before_after': True, 'native_hash_unchanged_before_after': native_hash is not None,
                         'output_sha256': sha256(output), 'elapsed_seconds': round(time.monotonic()-started, 1)}
    }
    receipt['revision'] = receipt['verification']['output_sha256'][:16]
    pending = receipt_path.with_suffix('.pending.json')
    pending.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    pending.replace(receipt_path)
    (cache/'pluvial_meta.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'stage': 'complete', 'output': str(output), 'counts': receipt['counts'],
                      'sensitivity': receipt['sensitivity'], 'seconds': round(time.monotonic()-started, 1)}), flush=True)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent/'sofia_pluvial_demo/sofia_pluvial_inputs_5m.tif')
    parser.add_argument('--native', type=Path, default=ROOT.parent/'sofia_dtm_2024_1m_gee.tif')
    parser.add_argument('--cache', type=Path, default=ROOT/'data/cache')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    prepare(args.source, args.native, args.cache, args.force)
