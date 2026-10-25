"""Reproduce scalar/batched MVT equivalence and uncached direct-render timings.

Run from the app directory with its Python environment:
    python scripts/benchmark_vectors.py

Both renderers use the same actual read-only SQLite data in one process. No HTTP
or application tile cache is involved, no features are sampled/clustered, and no
server cache is cleared. Timings are local observations, not a performance SLA.
The default includes a substantial city tile; --skip-city omits that case.
"""
import argparse
from datetime import datetime, timezone
import gc
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import time

from shapely import from_wkb, get_parts, union_all
from shapely.geometry import box
from shapely.ops import transform
import mapbox_vector_tile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.vector import (PROJECT, UNPROJECT, VECTOR_VERSION, category_filter,
                            render_vector_tile)
from backend.terrain import tile_bounds


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def legacy_scalar(dbpath, kind, z, x, y, zone='inside', display='all'):
    """Pre-optimization backend/app.py vector_tile body, without its LRU wrapper.

    Keep this intentionally scalar for an inspectable comparison. Its source
    geometry, feature properties, clipping, tolerance and encoder options match
    the previously delivered application. Request-category filtering was client
    side in that version, so the legacy point renderer returns all categories.
    """
    bounds = tile_bounds(z, x, y)
    west, south, east, north = UNPROJECT.transform_bounds(*bounds, densify_pts=8)
    extra = (' AND f.zone=?' if kind == 'routes' else
             ' AND f.display=1' if kind == 'green' and display == 'subset' else '')
    params = [east, west, north, south, kind] + ([zone] if kind == 'routes' else [])
    db = sqlite3.connect('file:' + Path(dbpath).as_posix() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute('''SELECT f.* FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid
            WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=? AND f.kind=?'''
                          + extra, params).fetchall()
    finally:
        db.close()
    width = bounds[2] - bounds[0]
    clip = box(*bounds).buffer(width / 256 * 4)
    features = []
    for row in rows:
        geometry = transform(PROJECT.transform, from_wkb(row['geometry']))
        if kind != 'points':
            geometry = geometry.intersection(clip).simplify(width / 4096 * .5,
                                                           preserve_topology=True)
        if geometry.is_empty:
            continue
        if geometry.geom_type == 'GeometryCollection':
            wanted = [g for g in get_parts(geometry)
                      if (g.geom_type in ('Polygon', 'MultiPolygon') if kind == 'green'
                          else g.geom_type in ('LineString', 'MultiLineString'))]
            if not wanted:
                continue
            geometry = union_all(wanted)
        props = {k: v for k, v in json.loads(row['properties']).items()
                 if isinstance(v, (str, int, float, bool))}
        features.append({'id': row['fid'], 'geometry': geometry, 'properties': props})
    return mapbox_vector_tile.encode({'name': kind, 'features': features}, default_options={
        'quantize_bounds': bounds, 'extents': 4096, 'y_coord_down': False})


def decoded_by_id(data, kind):
    layer = mapbox_vector_tile.decode(data)[kind]
    features = layer['features']
    keyed = {f['id']: f for f in features}
    if len(keyed) != len(features):
        raise AssertionError('Duplicate MVT feature IDs would conceal lost records')
    if layer['extent'] != 4096:
        raise AssertionError('MVT extent changed')
    return keyed


def write_receipt(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.pending.json')
    pending.write_text(json.dumps(result, indent=2), encoding='utf-8')
    pending.replace(path)


def benchmark_case(dbpath, case, repeats, selected_categories):
    kind, z, x, y, display = (case[k] for k in ('kind', 'z', 'x', 'y', 'display'))
    times = {'legacy': [], 'batch': []}
    payload = {}
    for iteration in range(repeats):
        # Alternate first renderer to reduce filesystem-cache/order bias. The OS
        # cache is not flushed; comparisons exclude HTTP queueing and tile caches.
        order = ('legacy', 'batch') if iteration % 2 == 0 else ('batch', 'legacy')
        for method in order:
            started = time.perf_counter()
            data = (legacy_scalar(dbpath, kind, z, x, y, display=display)
                    if method == 'legacy' else
                    render_vector_tile(dbpath, kind, z, x, y, display=display))
            elapsed = time.perf_counter() - started
            times[method].append(elapsed)
            payload[method] = data
            print(json.dumps({'stage': 'render', 'case': case['name'], 'method': method,
                              'iteration': iteration + 1, 'seconds': elapsed,
                              'pbf_bytes': len(data)}), flush=True)
    old = decoded_by_id(payload['legacy'], kind)
    new = decoded_by_id(payload['batch'], kind)
    mismatches = [fid for fid in old.keys() & new.keys() if old[fid] != new[fid]]
    result = {**case, 'repetitions_per_renderer': repeats,
              'timings_seconds': times,
              'median_legacy_seconds': statistics.median(times['legacy']),
              'median_batch_seconds': statistics.median(times['batch']),
              'speedup_median': statistics.median(times['legacy']) / statistics.median(times['batch']),
              'old_features': len(old), 'new_features': len(new),
              'same_id_set': old.keys() == new.keys(),
              'same_decoded_geometry_properties': not mismatches,
              'mismatch_ids': mismatches[:10],
              'legacy_pbf_bytes': len(payload['legacy']), 'batch_pbf_bytes': len(payload['batch']),
              'batch_gzip_level3_bytes': len(gzip.compress(payload['batch'], compresslevel=3, mtime=0)),
              'legacy_pbf_sha256': hashlib.sha256(payload['legacy']).hexdigest(),
              'batch_pbf_sha256': hashlib.sha256(payload['batch']).hexdigest()}
    if not result['same_id_set'] or mismatches:
        raise AssertionError(json.dumps({'case': case['name'], 'comparison': result}))
    if kind == 'points':
        started = time.perf_counter()
        selected = render_vector_tile(dbpath, kind, z, x, y, display=display,
                                      categories=selected_categories)
        elapsed = time.perf_counter() - started
        expected = {fid: f for fid, f in old.items()
                    if f['properties']['category'] in selected_categories}
        actual = decoded_by_id(selected, kind)
        if actual != expected:
            raise AssertionError('Selected-category tile is not the exact old-feature subset')
        result['selected_categories'] = {
            'categories': list(selected_categories), 'features': len(actual),
            'same_id_geometry_properties_as_legacy_subset': True,
            'direct_render_seconds': elapsed, 'pbf_bytes': len(selected),
            'gzip_level3_bytes': len(gzip.compress(selected, compresslevel=3, mtime=0)),
            'interpretation': 'Different requested payload: exact selected-category subset, not a like-for-like all-points timing.'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/cache/spatial.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'test-artifacts/vector_performance_after.json')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--city-repeats', type=int, default=1)
    parser.add_argument('--skip-city', action='store_true')
    parser.add_argument('--categories', default='3,4')
    args = parser.parse_args()
    if args.repeats < 1 or args.city_repeats < 1:
        parser.error('Repeat counts must be positive')
    categories = category_filter(args.categories)
    dbpath = args.database.resolve()
    before = sha256(dbpath)
    db = sqlite3.connect('file:' + dbpath.as_posix() + '?mode=ro', uri=True)
    try:
        indexes = db.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name").fetchall()
        counts = db.execute('SELECT kind,COUNT(*) FROM features GROUP BY kind').fetchall()
    finally:
        db.close()
    result = {'status': 'running', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'method': 'Same-process direct uncached scalar/batch rendering; identical actual SQLite input; no HTTP timing or profiler overhead.',
              'timing_limitations': 'OS filesystem cache is not cleared. Small cases alternate renderer order; the default city case has one legacy-then-batch pair. Background machine load may affect wall time.',
              'comparison': 'Decoded MVT features compared by unique ID, including every geometry and property; feature/dictionary ordering may change encoded bytes.',
              'database': {'file': str(dbpath), 'sha256_before': before,
                           'indexes': [r[0] for r in indexes], 'feature_counts': dict(counts)},
              'versions': {name: version(name) for name in ('numpy', 'shapely', 'pyproj', 'mapbox-vector-tile')},
              'python': platform.python_version(), 'vector_version': VECTOR_VERSION,
              'source_sha256': {'benchmark': sha256(__file__),
                                'vector_renderer': sha256(ROOT / 'backend/vector.py')}, 'records': []}
    cases = [
        {'name': 'points-street', 'kind': 'points', 'z': 15, 'x': 18506, 'y': 12077, 'display': 'all'},
        {'name': 'green-subset-central', 'kind': 'green', 'z': 13, 'x': 4626, 'y': 3019, 'display': 'subset'},
        {'name': 'routes-inside-central', 'kind': 'routes', 'z': 13, 'x': 4626, 'y': 3019, 'display': 'all'}]
    if not args.skip_city:
        cases.append({'name': 'points-city', 'kind': 'points', 'z': 12, 'x': 2313, 'y': 1509, 'display': 'all'})
    write_receipt(args.output, result)
    try:
        for case in cases:
            print(json.dumps({'stage': 'start-case', 'case': case['name']}), flush=True)
            record = benchmark_case(dbpath, case, args.city_repeats if case['name'] == 'points-city' else args.repeats, categories)
            result['records'].append(record)
            write_receipt(args.output, result)
            print(json.dumps({'stage': 'case-verified', 'case': case['name'],
                              'features': record['new_features'], 'speedup_median': record['speedup_median']}), flush=True)
            gc.collect()
        after = sha256(dbpath)
        result['database'].update(sha256_after=after, unchanged_before_after=before == after)
        if before != after:
            raise AssertionError('SQLite input changed during the read-only benchmark')
        result.update(status='passed', finished_utc=datetime.now(timezone.utc).isoformat())
        write_receipt(args.output, result)
        print(json.dumps({'stage': 'complete', 'output': str(args.output),
                          'status': result['status'], 'cases': len(result['records'])}), flush=True)
    except BaseException as error:
        result.update(status='failed', error=str(error), finished_utc=datetime.now(timezone.utc).isoformat())
        write_receipt(args.output, result)
        raise


if __name__ == '__main__':
    main()
