"""Exact metric proximity to documented river geometry, without inferring cause.

Only explicitly tagged OSM river polygons and actual official river-reach lines
are used. Lakes, reservoirs, ponds and schematic assessment points are excluded.
Distance identifies contextual proximity; it cannot prove fluvial/pluvial cause.
"""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
import shapely
from shapely.geometry import Point, shape

from .tile_cache import file_signature

METHOD = 'documented-river-geometry-exact-metric-proximity-v1'
DEFAULT_THRESHOLD_M = 100.0
CATEGORIES = ('river_adjacent_possible_mixed', 'away_from_mapped_river', 'unknown')
TO_METRIC = Transformer.from_crs(4326, 7801, always_xy=True)
INTERPRETATION = ('Proximity to mapped river geometry is contextual evidence only. River-adjacent land may have mixed rainfall, river or drainage influences; distance does not determine flood cause. Away from mapped rivers does not establish pluvial causation or absence of an unmapped river.')


def threshold(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 5000:
        raise ValueError('River proximity threshold must be finite and between 0 and 5000 metres')
    return float(value)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def river_features(water, assessment):
    """Keep source features intact; return selected records and source counts."""
    selected = []
    counts = {'open_water_source_polygons': len(water.get('features', [])),
              'osm_river_polygons': 0, 'nonriver_water_polygons_excluded': 0,
              'official_context_source_features': len(assessment.get('features', [])),
              'official_river_reaches': 0, 'schematic_or_nonreach_features_excluded': 0}
    for feature in water.get('features', []):
        props = feature.get('properties') or {}
        tags = props.get('tags') or {}
        geometry = feature.get('geometry') or {}
        if (geometry.get('type') in ('Polygon', 'MultiPolygon')
                and (tags.get('water') == 'river' or tags.get('waterway') == 'riverbank')):
            identifier = f"{props.get('osm_type')}/{props.get('osm_id')}"
            selected.append((feature, {'source_id': identifier, 'source_kind': 'osm_river_polygon',
                                      'source_url': props.get('source_url'),
                                      'label': tags.get('name') or 'Mapped river '+identifier}))
            counts['osm_river_polygons'] += 1
        else:
            counts['nonriver_water_polygons_excluded'] += 1
    for feature in assessment.get('features', []):
        props = feature.get('properties') or {}
        geometry = feature.get('geometry') or {}
        if props.get('geometry_role') == 'assessment_reach' and geometry.get('type') in ('LineString', 'MultiLineString'):
            selected.append((feature, {'source_id': props.get('source_id'), 'source_kind': 'official_assessment_reach',
                                      'source_url': props.get('source_url'),
                                      'label': props.get('location') or props.get('apsfrName') or props.get('source_id')}))
            counts['official_river_reaches'] += 1
        else:
            counts['schematic_or_nonreach_features_excluded'] += 1
    counts['included_river_geometries'] = len(selected)
    return selected, counts


@lru_cache(maxsize=4)
def grid_index(tree):
    """Short segment index avoids repeated scans of long river geometries.

    Polygon interiors are checked separately, because their distance is zero;
    boundary segments alone would incorrectly measure the distance to the bank.
    Segment distances are identical to their original straight source segments.
    """
    segments = []
    polygons = []
    for geom in tree.geometries:
        if geom.geom_type in ('Polygon', 'MultiPolygon'):
            parts = list(geom.geoms) if geom.geom_type == 'MultiPolygon' else [geom]
            polygons.extend(parts)
            lines = [ring for poly in parts for ring in [poly.exterior, *poly.interiors]]
        else:
            lines = list(geom.geoms) if geom.geom_type == 'MultiLineString' else [geom]
        for line in lines:
            coordinates = shapely.get_coordinates(line)
            if len(coordinates) >= 2:
                segments.append(np.stack([coordinates[:-1], coordinates[1:]], axis=1))
    segment_tree = shapely.STRtree(shapely.linestrings(np.concatenate(segments)))
    polygon_tree = shapely.STRtree(polygons) if polygons else None
    return segment_tree, polygon_tree


@lru_cache(maxsize=4)
def load_sources(water_signature, water_meta_signature, context_signature, assessment_meta_signature):
    water_meta = json.loads(Path(water_meta_signature[0]).read_text(encoding='utf-8'))
    assessment_meta = json.loads(Path(assessment_meta_signature[0]).read_text(encoding='utf-8'))
    water_hash = sha(water_signature[0])
    context_hash = sha(context_signature[0])
    if water_hash != water_meta.get('source', {}).get('geojson_sha256'):
        raise ValueError('Mapped-water geometry checksum differs from its preserved receipt')
    if context_hash != assessment_meta.get('context_sha256'):
        raise ValueError('Official assessment context checksum differs from its preserved receipt')
    water = json.loads(Path(water_signature[0]).read_text(encoding='utf-8'))
    context = json.loads(Path(context_signature[0]).read_text(encoding='utf-8'))
    for document in [water, context]:
        if document.get('type') != 'FeatureCollection' or not isinstance(document.get('features'), list):
            raise ValueError('River context source must be a real GeoJSON FeatureCollection')
    selected, counts = river_features(water, context)
    geometries = []
    records = []
    for feature, record in selected:
        geo = shape(feature['geometry'])
        if geo.is_empty or not geo.is_valid:
            raise ValueError('Selected river source geometry is empty or invalid')
        coordinates = shapely.get_coordinates(geo)
        if (not np.isfinite(coordinates).all() or np.any(np.abs(coordinates[:, 0]) > 180)
                or np.any(np.abs(coordinates[:, 1]) > 85)):
            raise ValueError('Selected river source is not finite WGS84 geometry')
        metric = shapely.transform(geo, TO_METRIC.transform, interleaved=False)
        if metric.is_empty or not np.isfinite(shapely.get_coordinates(metric)).all():
            raise ValueError('Selected river source cannot be projected to EPSG:7801')
        geometries.append(metric)
        records.append(record)
    identity = {'method': METHOD, 'water_sha256': water_hash, 'official_context_sha256': context_hash}
    revision = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    meta = {'available': bool(geometries), 'method': METHOD, 'revision': revision,
            'default_threshold_m': DEFAULT_THRESHOLD_M, 'distance_unit': 'metres', 'distance_crs': 'EPSG:7801',
            'source_counts': counts,
            'source_revisions': {'mapped_water': water_meta.get('revision'), 'official_assessment': assessment_meta.get('revision')},
            'source_hashes': {'open_water_polygons': water_hash, 'official_context': context_hash},
            'source_urls': sorted({r['source_url'] for r in records if r.get('source_url')}),
            'filter': 'Only exact water=river or legacy waterway=riverbank polygons, plus official geometry_role=assessment_reach LineString/MultiLineString. No schematic points, lake/reservoir/pond distance or invented river buffers enter nearest distances.',
            'interpretation': INTERPRETATION,
            'limitations': ['Source snapshots and designated reaches are incomplete river mapping; narrow, intermittent, covered or unmapped channels may be missing.',
                            'The threshold is an adjustable proximity screening choice, not a floodplain boundary, return period or hydraulic connection.',
                            'Distances to river polygons measure distance to their actual footprint; points inside have distance zero. Distances to reaches use their supplied line geometry.',
                            'Reported flood mechanisms are preserved. This context never relabels an observed event as fluvial or pluvial.',
                            'Official reaches are prospective designations, not observed flood extents. Source dates are retained under the requested time-compatible scenario.']}
    return geometries, records, shapely.STRtree(geometries) if geometries else None, meta


class RiverContext:
    def __init__(self, root):
        self.root = Path(root)
        self.water_path = self.root/'data/reference/open_water_polygons.geojson'
        self.water_meta = self.root/'data/cache/open_water_meta.json'
        self.context_path = self.root/'data/reference/flood_assessment/assessment_context.geojson'
        self.assessment_meta = self.root/'data/reference/flood_assessment/metadata.json'

    def _sources(self):
        return load_sources(*(file_signature(p) for p in [self.water_path, self.water_meta, self.context_path, self.assessment_meta]))

    def meta(self):
        try:
            return dict(self._sources()[3])
        except (OSError, KeyError, ValueError, TypeError) as error:
            return {'available': False, 'method': METHOD, 'default_threshold_m': DEFAULT_THRESHOLD_M,
                    'message': 'River proximity context unavailable: '+str(error),
                    'interpretation': INTERPRETATION}

    @staticmethod
    def _unknown(meta, threshold_m, reported_mechanism=None):
        return {'available': False, 'revision': meta.get('revision'), 'category': 'unknown',
                'nearest_distance_m': None, 'nearest_source': None, 'threshold_m': threshold_m,
                'reported_mechanism': reported_mechanism, 'causation': 'not_determined',
                'interpretation': INTERPRETATION, 'message': meta.get('message', 'No verified river geometry is available')}

    def sample(self, lon, lat, threshold_m=DEFAULT_THRESHOLD_M, reported_mechanism=None):
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in [lon, lat])
                or not -180 <= lon <= 180 or not -85 <= lat <= 85):
            raise ValueError('Finite WGS84 longitude/latitude required')
        result = self.classify_geometry({'type': 'Point', 'coordinates': [lon, lat]}, threshold_m, reported_mechanism)
        result['distance_basis'] = 'Point to nearest actual mapped river footprint or official river-reach line'
        return result

    def classify_geometry(self, geometry, threshold_m=DEFAULT_THRESHOLD_M, reported_mechanism=None):
        threshold_m = threshold(threshold_m)
        if not isinstance(geometry, dict):
            raise ValueError('Finite valid GeoJSON geometry required')
        if geometry.get('type') == 'Feature':
            if reported_mechanism is None:
                reported_mechanism = (geometry.get('properties') or {}).get('mechanism')
            geometry = geometry.get('geometry')
        if not geometry:
            raise ValueError('Finite valid GeoJSON geometry required')
        geo = shape(geometry)
        coordinates = shapely.get_coordinates(geo)
        if (geo.is_empty or not geo.is_valid or not coordinates.size or not np.isfinite(coordinates).all()
                or np.any(np.abs(coordinates[:, 0]) > 180) or np.any(np.abs(coordinates[:, 1]) > 85)):
            raise ValueError('Finite valid WGS84 geometry required')
        meta = self.meta()
        if not meta.get('available'):
            return self._unknown(meta, threshold_m, reported_mechanism)
        geometries, records, tree, _ = self._sources()
        metric = shapely.transform(geo, TO_METRIC.transform, interleaved=False)
        if not np.isfinite(shapely.get_coordinates(metric)).all():
            return self._unknown(meta, threshold_m, reported_mechanism)
        index = int(tree.nearest(metric))
        distance = float(metric.distance(geometries[index]))
        return {'available': True, 'revision': meta['revision'],
                'category': CATEGORIES[0] if distance <= threshold_m else CATEGORIES[1],
                'nearest_distance_m': distance, 'threshold_m': threshold_m, 'nearest_source': dict(records[index]),
                'reported_mechanism': reported_mechanism, 'causation': 'not_determined',
                'distance_basis': 'Minimum geometry-to-source distance; a large polygon may contain both adjacent and distant parts',
                'source_counts': meta['source_counts'], 'interpretation': INTERPRETATION}

    def classify_grid(self, grid_transform, eligible, threshold_m=DEFAULT_THRESHOLD_M):
        """Exact centre distances in bounded batches, not raster EDT approximation.

        Returns arrays for scenario stratification plus a JSON-safe area summary.
        Cells not eligible are NaN/False, and unknown cells are counted separately.
        """
        threshold_m = threshold(threshold_m)
        eligible = np.asarray(eligible, dtype=bool)
        grid = Affine(*list(grid_transform)[:6])
        cell_area = abs(grid.a*grid.e-grid.b*grid.d)
        if (eligible.ndim != 2 or eligible.size > 1_000_000 or not np.isfinite(list(grid)[:6]).all()
                or not math.isfinite(cell_area) or cell_area <= 0):
            raise ValueError('Finite metric grid with at most 1,000,000 cells required')
        meta = self.meta()
        distance = np.full(eligible.shape, np.nan, dtype='float32')
        near = np.zeros(eligible.shape, dtype=bool)
        eligible_count = int(np.count_nonzero(eligible))
        if meta.get('available'):
            _, _, tree, _ = self._sources()
            segment_tree, polygon_tree = grid_index(tree)
            rows, cols = np.nonzero(eligible)
            for offset in range(0, len(rows), 16384):
                rr, cc = rows[offset:offset+16384], cols[offset:offset+16384]
                x = grid.a*(cc+.5)+grid.b*(rr+.5)+grid.c
                y = grid.d*(cc+.5)+grid.e*(rr+.5)+grid.f
                points = shapely.points(x, y)
                inside = np.zeros(len(points), dtype=bool)
                if polygon_tree is not None:
                    pairs = polygon_tree.query(points, predicate='covered_by')
                    if pairs.size:
                        inside[np.unique(pairs[0])] = True
                exact = np.zeros(len(points), dtype='float64')
                if np.any(~inside):
                    _, exact[~inside] = segment_tree.query_nearest(points[~inside], return_distance=True, all_matches=False)
                distance[rr, cc] = exact.astype('float32')
                # Classify with Float64 exact distances; Float32 encoding cannot
                # move a centre across the configurable distance threshold.
                near[rr, cc] = exact <= threshold_m
        known = eligible & np.isfinite(distance)
        counts = {CATEGORIES[0]: int(np.count_nonzero(near)),
                  CATEGORIES[1]: int(np.count_nonzero(known & ~near)),
                  CATEGORIES[2]: int(np.count_nonzero(eligible & ~known))}
        areas = {key: value*cell_area for key, value in counts.items()}
        summary = {'available': bool(meta.get('available')), 'revision': meta.get('revision'),
                   'threshold_m': threshold_m, 'distance_basis': 'Exact EPSG:7801 point-to-source distances at eligible grid cell centres',
                   'class_cell_counts': counts, 'class_area_m2': areas,
                   'eligible_area_m2': eligible_count*cell_area,
                   'near_river_area_m2': areas[CATEGORIES[0]],
                   'away_from_mapped_river_area_m2': areas[CATEGORIES[1]], 'unknown_area_m2': areas[CATEGORIES[2]],
                   'source_counts': meta.get('source_counts', {}), 'causation': 'not_determined',
                   'interpretation': INTERPRETATION}
        if meta.get('message'):
            summary['message'] = meta['message']
        return {'distance_m': distance, 'near_river': near, 'summary': summary}
