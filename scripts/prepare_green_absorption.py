"""Rasterize ALL real mapped-green polygons as an explicit absorption scenario.

Run: python scripts/prepare_green_absorption.py
Uses a bounded 512-pixel block and read-only RTree queries. Source files, native
terrain and P/C/S remain unchanged. Polygon holes and overlaps are respected;
membership is the union at 5 m cell centres, independent of display selection.
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from rasterio.windows import bounds as window_bounds, transform as window_transform
import shapely
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.green_absorption import BAND, GRID, METHOD, SHAPE


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(root=ROOT):
    root = Path(root)
    start = time.monotonic()
    cache = root/'data/cache'
    output = cache/'green_absorption_5m.tif'
    partial = output.with_suffix('.partial.tif')
    green = next((root/'data/raw').glob('green_areas*.geojson'))
    sources = {'spatial_index': cache/'spatial.sqlite',
               'spatial_revision': cache/'spatial_revision_inputs.json',
               'vector_provenance': cache/'vector_provenance.json',
               'green_original': green,
               'terrain_screening_grid': cache/'pluvial_5m.tif'}
    before = {key: {'file': p.relative_to(root).as_posix(), 'size_bytes': p.stat().st_size,
                    'mtime_ns': p.stat().st_mtime_ns, 'sha256': sha(p)} for key, p in sources.items()}
    vector = load(sources['vector_provenance'])
    revision = load(sources['spatial_revision'])
    green_hashes = {value for name, value in vector['input_sha256'].items()
                    if Path(name.replace('\\', '/')).name == green.name}
    revision_hashes = {value for name, value in revision['inputs']['vectors'].items()
                      if Path(name.replace('\\', '/')).name == green.name}
    if green_hashes != {before['green_original']['sha256']} or green_hashes != revision_hashes:
        raise ValueError('Mapped-green source does not match the preserved spatial-index provenance')
    if vector['nonempty_green_count'] != 64956:
        raise ValueError('Expected the complete 64,956 nonempty green polygons')
    db = sqlite3.connect('file:'+sources['spatial_index'].as_posix()+'?mode=ro', uri=True)
    db.execute('PRAGMA cache_size=-16384')
    count = db.execute("SELECT count(*) FROM features WHERE kind='green'").fetchone()[0]
    display_count = db.execute("SELECT count(*) FROM features WHERE kind='green' AND display=1").fetchone()[0]
    if count != 64956:
        db.close()
        raise ValueError('Spatial index is missing mapped-green polygons')
    projector = Transformer.from_crs(4326, 7801, always_xy=True)
    green_cells = 0
    candidate_ids = set()
    query_rows = 0
    try:
        with rasterio.open(sources['terrain_screening_grid']) as src:
            if src.shape != SHAPE or src.transform != GRID or src.crs.to_epsg() != 7801:
                raise ValueError('Terrain-screening grid differs from the verified native 5 m alignment')
            profile = dict(driver='GTiff', width=SHAPE[1], height=SHAPE[0], count=1,
                           dtype='uint8', crs=src.crs, transform=GRID, nodata=None,
                           tiled=True, blockxsize=512, blockysize=512,
                           compress='DEFLATE', predictor=1, BIGTIFF='IF_SAFER')
            with rasterio.open(partial, 'w', **profile) as dst:
                dst.set_band_description(1, BAND)
                dst.update_tags(METHOD=METHOD, SCENARIO='All mapped green areas assumed to absorb water and excluded from displayed risk.',
                                MEMBERSHIP='Pixel centre in union of all 64,956 nonempty mapped polygons; holes retained; overlaps counted once.',
                                LIMITATION='Not measured infiltration or unlimited physical storage; no original terrain or scores changed.')
                windows = list(dst.block_windows(1))
                for n, (_, window) in enumerate(windows, 1):
                    metric = window_bounds(window, GRID)
                    ll = transform_bounds(7801, 4326, *metric, densify_pts=21)
                    records = db.execute("SELECT f.fid,f.geometry FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE b.maxx>=? AND b.minx<=? AND b.maxy>=? AND b.miny<=? AND f.kind='green'",
                                         (ll[0], ll[2], ll[1], ll[3])).fetchall()
                    a = np.zeros((int(window.height), int(window.width)), dtype='uint8')
                    if records:
                        query_rows += len(records)
                        candidate_ids.update(r[0] for r in records)
                        geometries = shapely.transform(shapely.from_wkb([r[1] for r in records]), projector.transform, interleaved=False)
                        clip = box(*metric)
                        geometries = shapely.intersection(geometries, clip)
                        shapes = [(mapping(g), 1) for g in geometries if not g.is_empty and g.area > 0]
                        if shapes:
                            rasterize(shapes, out=a, transform=window_transform(window, GRID), all_touched=False)
                    green_cells += int(np.count_nonzero(a))
                    dst.write(a, 1, window=window)
                    if n % 80 == 0:
                        print(json.dumps({'stage': 'green_absorption', 'blocks': n, 'total_blocks': len(windows), 'distinct_candidate_polygons': len(candidate_ids)}), flush=True)
        db.close()
        for key, path in sources.items():
            record = before[key]
            if (path.stat().st_size != record['size_bytes'] or path.stat().st_mtime_ns != record['mtime_ns']
                    or sha(path) != record['sha256']):
                raise ValueError('Original changed during green-scenario processing: '+key)
        os.replace(partial, output)
    except Exception:
        db.close()
        # Only incomplete derivatives are disposable. Original sources stay intact.
        partial.unlink(missing_ok=True)
        raise
    digest = sha(output)
    result = {'available': True, 'method': METHOD, 'revision': digest[:16], 'sha256': digest,
              'output_file': output.relative_to(root).as_posix(),
              'source_revision': revision['revision'], 'source_files': before,
              'source_counts': {'nonempty_green_polygons': count, 'empty_source_records': len(vector['empty_source_ids']),
                                'route_intersecting_display_subset': display_count,
                                'distinct_candidates_in_grid': len(candidate_ids), 'query_rows_including_repeats': query_rows},
              'grid': {'crs': 'EPSG:7801', 'shape': list(SHAPE), 'transform': list(GRID)[:6], 'nodata': None, 'dtype': 'uint8'},
              'band': BAND,
              'counts': {'all_cells': SHAPE[0]*SHAPE[1], 'green_cells': green_cells,
                         'non_green_cells': SHAPE[0]*SHAPE[1]-green_cells, 'green_area_km2': green_cells*25/1e6},
              'policy': 'Cell centres inside the union of every mapped nonempty green polygon are scenario-excluded. Holes are retained; overlaps count once. Display subset and visibility have no effect.',
              'scenario_assumption': 'At the user’s request, all mapped green areas are assumed to absorb water and therefore are excluded from displayed risk. This is a reversible scenario assumption, not measured infiltration or a hydraulic result.',
              'limitations': ['Mapped green areas do not establish soil permeability, infiltration rate, antecedent saturation or storage capacity.',
                              'This scenario assumes complete absorption; intense rainfall may exceed real infiltration or storage.',
                              '5 m cell-centre membership may omit narrow slivers; native source geometry and original terrain scores remain unchanged.',
                              'The mask covers the analysis rectangle; outside terrain, water and uncertainty retain their independent policies.'],
              'verification': {'all_sources_unchanged': True, 'source_hashes_checked_before_after': True},
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'runtime_seconds': round(time.monotonic()-start, 3),
              'reproduce': 'python scripts/prepare_green_absorption.py'}
    receipt = cache/'green_absorption_meta.json'
    temporary = receipt.with_suffix('.partial.json')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, receipt)
    print(json.dumps({key: result[key] for key in ['revision', 'sha256', 'counts', 'source_counts', 'runtime_seconds']}, indent=2), flush=True)
    return result


if __name__ == '__main__':
    prepare()
