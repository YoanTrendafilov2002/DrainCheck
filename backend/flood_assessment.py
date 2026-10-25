"""Verified official assessment geometry, distinct from observed inundation."""
import json
from functools import lru_cache
from pathlib import Path
from shapely.geometry import shape, Point
from .context_layers import sha256
from .tile_cache import file_signature, read_json_cached

MECHANISMS = ('pluvial', 'river', 'mixed', 'infrastructure', 'unknown')

class FloodAssessmentContext:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root/'data/reference/flood_assessment'
        self.metadata = self.directory/'metadata.json'

    def path(self, relative):
        path = (self.root/relative).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise ValueError('Assessment source must be a preserved file in its source directory')
        return path

    @staticmethod
    @lru_cache(maxsize=8)
    def load(signature, expected, count):
        if sha256(signature[0]) != expected:
            raise ValueError('Assessment checksum differs from its source receipt')
        doc = read_json_cached(signature[0])
        if doc.get('type') != 'FeatureCollection' or len(doc.get('features', [])) != count:
            raise ValueError('Assessment feature count differs from its receipt')
        seen = set()
        for feature in doc['features']:
            props = feature['properties']; identity = props['source_id']
            geom = shape(feature['geometry'])
            if identity in seen or not geom.is_valid or geom.is_empty:
                raise ValueError('Assessment geometry or source identifier is invalid')
            seen.add(identity)
            if props.get('mechanism', 'unknown') not in MECHANISMS:
                raise ValueError('Unsupported assessment flood mechanism')
            if geom.geom_type not in ('Polygon', 'MultiPolygon', 'Point', 'LineString', 'MultiLineString'):
                raise ValueError('Unsupported assessment geometry type')
            w, s, e, n = geom.bounds
            if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
                raise ValueError('Assessment display coordinates must be WGS84')
        return doc

    def documents(self, browser=False):
        data = read_json_cached(self.metadata)
        zones = self.path(data.get('browser_zones_file', data['data_file']) if browser else data['data_file'])
        zones_sha = data.get('browser_sha256', data['sha256']) if browser else data['sha256']
        context = self.path(data['context_file'])
        return data, self.load(file_signature(zones), zones_sha, int(data['zone_features'])), self.load(file_signature(context), data['context_sha256'], int(data['context_features']))

    @staticmethod
    @lru_cache(maxsize=8)
    def geometries(signature, expected, count):
        doc = FloodAssessmentContext.load(signature, expected, count)
        return tuple((f['properties'], shape(f['geometry'])) for f in doc['features'])

    def spatial(self):
        data = read_json_cached(self.metadata)
        zones = self.path(data['data_file']); context = self.path(data['context_file'])
        return (self.geometries(file_signature(zones), data['sha256'], int(data['zone_features'])),
                self.geometries(file_signature(context), data['context_sha256'], int(data['context_features'])))

    def meta(self):
        try:
            data, zones, context = self.documents()
            features = zones['features'] + context['features']
            spatial_zones, spatial_context = self.spatial()
            bounds = [geom.bounds for _, geom in spatial_zones + spatial_context]
            counts = {key: sum(f['properties'].get('mechanism', 'unknown') == key for f in features) for key in MECHANISMS}
            return {**data, 'available': True, 'feature_count': len(features),
                    'zone_count': len(zones['features']), 'context_count': len(context['features']),
                    'coverage_bbox_wgs84': [min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)],
                    'mechanism_counts': counts, 'levels': ['high', 'medium', 'low'],
                    'status': 'Earlier municipal assessment zones; 2026 draft PFRA reaches and schematic identifiers',
                    'source_urls': data.get('source_urls', [{'label': 'Municipal assessment service', 'url': data['sources'][0]['url']}, {'label': 'Official PFRA publication', 'url': data['publication_page']}]),
                    'interpretation': 'Supplier assessment zones, designated reaches and schematic area identifiers; not observed flood footprints or parcel-specific probabilities.'}
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {'available': False, 'title': 'Official flood assessment context', 'message': str(error)}

    def collection(self):
        _, zones, context = self.documents(browser=True)
        return {'type': 'FeatureCollection', 'features': zones['features'] + context['features']}

    def intersections(self, lon, lat):
        if not self.meta().get('available'):
            return {'available': False, 'zones': [], 'interpretation': 'Assessment coverage unavailable; no absence of risk inferred.'}
        zones, _ = self.spatial()
        point = Point(lon, lat)
        selected = [props for props, geom in zones if geom.covers(point)]
        return {'available': True, 'zones': selected,
                'interpretation': 'Exact full-precision assessment-zone containment. Reaches and schematic identifiers have no invented buffer or flood extent.'}


def history_mechanism_meta(history):
    data = history.meta()
    if not data.get('available'):
        return data
    return {**data, 'mechanism_counts': {'unknown': data['feature_count']},
            'mechanism_confidence_counts': {'unknown': data['feature_count']},
            'observation_confidence_counts': {'documented': data['feature_count']},
            'mechanism_interpretation': 'Documented mapped flooding; no per-polygon source mechanism is supplied. Study-level river/rain context is separate from polygon classification.',
            'review_index_use': 'Historical intersection contributes to the separate categorical review map; the original P/C/S scores remain unchanged.'}


def history_mechanism_collection(history):
    data = history.meta()
    original = read_json_cached(history.data_path(data))
    review_path = history.root/'data/reference/historical_floods/mechanism_review.json'
    reviews = {str(r['source_id']): r for r in read_json_cached(review_path)['survey_polygons']} if review_path.is_file() else {}
    features = []
    for feature in original['features']:
        props = feature['properties']; reviewed = reviews.get(str(props['source_id']), {})
        if reviewed.get('mechanism', 'unknown') != 'unknown' or reviewed.get('mechanism_confidence', 'unknown') != 'unknown':
            raise ValueError('A survey mechanism requires per-polygon source evidence; no unsupported classification is supplied')
        features.append({**feature, 'properties': {**props,
            'mechanism': 'unknown', 'mechanism_confidence': 'unknown', 'observation_confidence': 'documented',
            'mechanism_basis': reviewed.get('mechanism_basis', 'No per-polygon flood-mechanism field is supplied.'),
            'mechanism_source_url': reviewed.get('source_url', data['source_url']),
            'event_date_label': data['survey_date_label'],
            'evidence_kind': 'municipal_mapped_observation', 'geometry_role': 'surveyed_flood_zone'}})
    return {**original, 'features': features}

