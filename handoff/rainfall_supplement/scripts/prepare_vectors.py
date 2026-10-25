#!/usr/bin/env python3
"""Rebuild derived vectors from immutable originals. Run from any directory."""
import argparse
import collections
import json
from pathlib import Path

from pyproj import Geod
from shapely import STRtree, make_valid, union_all
from shapely.geometry import LineString, MultiLineString, MultiPolygon, mapping, shape

ROOT = Path(__file__).resolve().parents[1]
PIPES = 'vik_kanal_26_sofpr_20090000.geojson'
GREENS = 'green_areas_26_sofp_20200518_a00bddf3-4189-4e65-8216-a8575de25e8c.geojson'

def pieces(geometry, kind):
    if geometry.is_empty:
        return []
    if geometry.geom_type == kind:
        return [geometry]
    if hasattr(geometry, 'geoms'):
        return [p for part in geometry.geoms for p in pieces(part, kind)]
    return []

def status_of(properties):
    label = properties.get('legso') or ''
    return 'planned' if 'проект' in label else 'open' if 'Открит' in label else 'existing'

def write_fc(path, features):
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features},
                              ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

def prepare(raw_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_pipes = json.loads((raw_dir / PIPES).read_text(encoding='utf-8'))['features']
    raw_greens = json.loads((raw_dir / GREENS).read_text(encoding='utf-8'))['features']
    greens, green_features = [], []
    repaired, empty = [], []
    for index, f in enumerate(raw_greens):
        geometry = shape(f['geometry']) if f.get('geometry') else MultiPolygon([])
        invalid = not geometry.is_valid
        if invalid:
            repaired.append(f['properties'].get('id', index))
            geometry = make_valid(geometry)
        polygons = pieces(geometry, 'Polygon')
        if not polygons:
            empty.append(f['properties'].get('id', index))
            continue
        geometry = MultiPolygon(polygons)
        greens.append(geometry)
        green_features.append({'type': 'Feature', 'id': f['properties'].get('id', index),
            'properties': {**f['properties'], 'geometry_repaired': invalid},
            'geometry': mapping(geometry)})
    tree = STRtree(greens)
    geod = Geod(ellps='WGS84')
    output = {zone: [] for zone in ['all', 'inside', 'outside']}
    used_green_indices = set()
    lengths = collections.defaultdict(float)
    by_status = collections.defaultdict(lambda: {'count': 0, 'length_m': 0.0})
    largest_partition_error = 0.0
    for f in raw_pipes:
        source = f['properties']
        geometry = shape(f['geometry'])
        candidates = tree.query(geometry, predicate='intersects')
        used_green_indices.update(int(i) for i in candidates)
        mask = union_all([greens[i] for i in candidates])
        # Preserve traversal multiplicity for self-crossing/overlapping routes.
        parts = [geometry] if geometry.is_simple else [
            LineString([a, b]) for line in pieces(geometry, 'LineString')
            for a, b in zip(list(line.coords)[:-1], list(line.coords)[1:])]
        zones = {'all': geometry,
            'inside': MultiLineString([line for p in parts for line in pieces(p.intersection(mask), 'LineString')]),
            'outside': MultiLineString([line for p in parts for line in pieces(p.difference(mask), 'LineString')])}
        route_lengths = {}
        for zone, geom in zones.items():
            lines = pieces(geom, 'LineString')
            route_lengths[zone] = sum(abs(geod.geometry_length(line)) for line in lines)
            if not lines:
                continue
            length = route_lengths[zone]
            status = status_of(source)
            properties = {**source, 'source_id': source['id'],
                'source_length_m': source.get('length_m'), 'length_m': length,
                'status': status, 'zone': zone, 'source_year': 2009, 'mask_year': 2020}
            output[zone].append({'type': 'Feature', 'id': source['id'] + ':' + zone,
                'properties': properties, 'geometry': mapping(geom)})
            lengths[zone] += length
            entry = by_status[zone + ':' + status]
            entry['count'] += 1
            entry['length_m'] += length
        largest_partition_error = max(largest_partition_error,
            abs(route_lengths['all'] - route_lengths['inside'] - route_lengths['outside']))
    for zone, features in output.items():
        write_fc(out_dir / ('sewer_routes_' + zone + '.geojson'), features)
    write_fc(out_dir / 'green_intersecting_routes.geojson',
             [green_features[i] for i in sorted(used_green_indices)])
    summary = {'raw_pipe_features': len(raw_pipes), 'raw_green_features': len(raw_greens),
        'nonempty_green_features': len(greens), 'empty_green_source_ids': empty,
        'repaired_green_source_ids': repaired, 'visible_green_features': len(used_green_indices),
        'source_status_counts': dict(collections.Counter(status_of(f['properties']) for f in raw_pipes)),
        'zone_feature_counts': {z: len(fs) for z, fs in output.items()},
        'zone_length_m': dict(lengths), 'zone_status_statistics': dict(by_status),
        'partition_error_m': abs(lengths['all'] - lengths['inside'] - lengths['outside']),
        'maximum_per_route_partition_error_m': largest_partition_error,
        'geometry_crs': 'EPSG:4326',
        'clipping_method': 'Planar WGS84 longitude/latitude intersection with the union of candidate green polygons; matches the existing prototype.',
        'length_method': 'WGS84 ellipsoidal geodesic length; route traversal multiplicity retained.'}
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert summary['zone_feature_counts'] == {'all': 717, 'inside': 543, 'outside': 670}, summary
    assert summary['visible_green_features'] == 2175, summary
    assert summary['partition_error_m'] < 1.0, summary
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'data/derived')
    args = parser.parse_args()
    prepare(args.raw_dir, args.out_dir)
