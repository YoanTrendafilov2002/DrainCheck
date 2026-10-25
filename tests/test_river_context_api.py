"""Integrated source-backed context without rewriting observed flood causes."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import app, history_survey
from backend.flood_assessment import history_mechanism_collection

ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


def test_river_context_metadata_and_actual_sample_thresholds_in_all_readouts():
    meta = CLIENT.get('/api/river-context/meta')
    assert meta.status_code == 200 and meta.json()['available']
    assert meta.json()['source_counts']['included_river_geometries'] == 37
    lon, lat = 23.337247642167377, 42.690042699335194
    # Actual Ariana lake point is 34.2 m from a designated river reach. The lake
    # itself is not a river source, and changing a threshold must not change P.
    for endpoint in ['/api/river-context/sample', '/api/pluvial/sample', '/api/refinement/sample']:
        near = CLIENT.get(endpoint, params={'lon': lon, 'lat': lat, 'river_proximity_m': 100})
        away = CLIENT.get(endpoint, params={'lon': lon, 'lat': lat, 'river_proximity_m': 5})
        assert near.status_code == away.status_code == 200
        a, b = near.json(), away.json()
        context_a = a if endpoint == '/api/river-context/sample' else a.pop('river_context')
        context_b = b if endpoint == '/api/river-context/sample' else b.pop('river_context')
        assert context_a['category'] == 'river_adjacent_possible_mixed'
        assert context_b['category'] == 'away_from_mapped_river'
        assert 30 < context_a['nearest_distance_m'] < 40
        assert context_a['nearest_distance_m'] == context_b['nearest_distance_m']
        assert context_a['causation'] == context_b['causation'] == 'not_determined'
        if endpoint != '/api/river-context/sample':
            assert a == b, 'Proximity threshold cannot change original source scores or review categories'


def test_all_136_historical_polygons_keep_geometry_mechanisms_and_source_revision():
    metadata = CLIENT.get('/api/history/zones/meta').json()
    source = history_mechanism_collection(history_survey)
    assert metadata['river_context']['source_counts']['official_river_reaches'] == 19
    version = metadata['revision']
    response = CLIENT.get('/api/history/zones.geojson', params={'v': version, 'river_proximity_m': 100})
    assert response.status_code == 200
    features = response.json()['features']
    assert len(features) == len(source['features']) == 136
    for original, enriched in zip(source['features'], features):
        assert enriched['geometry'] == original['geometry']
        context = enriched['properties']['river_context']
        assert {k: v for k, v in enriched['properties'].items() if k != 'river_context'} == original['properties']
        assert context['available'] and context['threshold_m'] == 100
        assert context['reported_mechanism'] == original['properties']['mechanism'] == 'unknown'
        assert context['causation'] == 'not_determined'
        assert enriched['properties']['mechanism_confidence'] == 'unknown'
    assert CLIENT.get('/api/history/zones/meta').json()['revision'] == version
    assert CLIENT.get('/api/history/zones.geojson', params={'v': version, 'river_proximity_m': 100},
                      headers={'If-None-Match': response.headers['etag']}).status_code == 304
    smaller = CLIENT.get('/api/history/zones.geojson', params={'v': version, 'river_proximity_m': 5})
    assert smaller.status_code == 200
    assert all(f['properties']['river_context']['threshold_m'] == 5 for f in smaller.json()['features'])
    near100 = sum(f['properties']['river_context']['category'] == 'river_adjacent_possible_mixed' for f in features)
    near5 = sum(f['properties']['river_context']['category'] == 'river_adjacent_possible_mixed' for f in smaller.json()['features'])
    assert near5 <= near100
    assert CLIENT.get('/api/history/zones.geojson', params={'v': 'stale-version'}).status_code == 409


def test_river_context_api_rejects_nonfinite_and_out_of_range_parameters():
    coordinates = {'lon': 23.3, 'lat': 42.7}
    version = CLIENT.get('/api/history/zones/meta').json()['revision']
    for endpoint in ['/api/river-context/sample', '/api/pluvial/sample', '/api/refinement/sample', '/api/history/zones.geojson']:
        params = {'v': version} if endpoint.endswith('geojson') else coordinates
        for value in ['nan', 'inf', '-inf', -1, 0, 1001]:
            assert CLIENT.get(endpoint, params={**params, 'river_proximity_m': value}).status_code == 422
    for endpoint in ['/api/river-context/sample', '/api/pluvial/sample', '/api/refinement/sample']:
        for value in ['nan', 'inf', '-inf', 181]:
            assert CLIENT.get(endpoint, params={**coordinates, 'lon': value}).status_code == 422
