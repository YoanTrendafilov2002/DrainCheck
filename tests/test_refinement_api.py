"""Real-source integration checks; no synthetic map inputs or fitted risk claims."""
import json, math
from pathlib import Path
import numpy as np
import rasterio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from io import BytesIO
from backend import app as api
from backend.refinement import LocalReviewPriority, rgba
from backend.refinement_routes import create_refinement_router

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(api.app)

def test_review_metadata_explains_rules_source_roles_and_unknown_clogging():
    meta = client.get('/api/refinement/meta').json()
    assert meta['available'] and meta['revision']
    assert meta['screening_exclusions']['enabled']
    assert meta['screening_exclusions']['revision'] == api.pluvial.meta()['screening_exclusions']['revision']
    assert [c['value'] for c in meta['classes']] == list(range(6))
    assert isinstance(meta['formula'], str) and 'P>=70' in meta['formula']
    assert meta['source_revisions']['pluvial'] == api.pluvial.meta()['revision']
    assert meta['clogging_analysis']['available'] is False
    assert len(meta['logic_links']) == 8
    assert 'user' in meta['scenario_assumption'].lower()
    with rasterio.open(ROOT/'data/derived/review_priority_5m.tif') as source:
        assert meta['scenario_assumption'] == source.tags()['SCENARIO_ASSUMPTION']
    assert meta['classes'][0]['color'][3] < meta['classes'][3]['color'][3]

def test_native_category_zero_remains_visible_and_exclusions_stay_distinct():
    classes = client.get('/api/refinement/meta').json()['classes']
    values = np.array([[0,1,2,3,4,5,253,254,255]], dtype=np.uint8)
    image = rgba(values, classes)
    assert all(image[0,:6,3] > 0)
    assert image[0,6,3] == image[0,8,3] == 0
    assert image[0,7,3] > 0

def test_actual_historical_land_category_is_separate_from_legacy_ponding():
    params = {'lon':23.361694114303877, 'lat':42.81236256982956}
    result = client.get('/api/refinement/sample', params=params)
    assert result.status_code == 200
    data = result.json()
    legacy = client.get('/api/pluvial/sample', params=params).json()
    assert data['status'] == 'ok' and data['review_class'] == 4
    assert data['history_intersection'] and data['historical_polygon_ids']
    assert data['legacy_ponding_score'] == legacy['ponding_score']
    assert data['drainage_context']['clogging_status'] == 'not_assessed'
    assert 'score' not in data and 'probability' not in data

def test_real_sewer_context_uses_statuses_geometry_and_preserves_low_ponding():
    data = client.get('/api/refinement/sample?lon=23.267111&lat=42.684845').json()
    context = data['drainage_context']
    assert data['review_class'] == 0 and data['legacy_ponding_score'] == 0
    assert context['available'] and context['search_radius_m'] == 100
    assert context['route_counts'] == {'existing':1, 'planned':0, 'open':0}
    assert context['point_counts'] == {'sewerage':26, 'collectors':40}
    assert context['route_length_m_in_radius']['existing'] == pytest.approx(128.7136915942)
    assert context['mapped_green_cover_at_point'] is True
    assert context['clogging_status'] == 'not_assessed' and context['review_flags'] == []

def test_missing_review_source_reports_unavailable_and_never_falls_back(tmp_path):
    missing = LocalReviewPriority(tmp_path, api.pluvial, api.cadastre, api.history_survey, api.assessment)
    app = FastAPI(); app.include_router(create_refinement_router(missing, api.assessment, 'test-renderer'))
    local = TestClient(app)
    assert local.get('/api/refinement/meta').json()['available'] is False
    for path in ['/api/refinement/sample?lon=23.3&lat=42.7', '/api/refinement/tiles/12/2313/1509.png?v=old', '/api/refinement/download']:
        assert local.get(path).status_code == 503

@pytest.mark.parametrize('query', ['lon=nan&lat=42.7','lon=23.3&lat=inf','lon=181&lat=42.7'])
def test_review_api_rejects_nonfinite_or_invalid_coordinates(query):
    assert client.get('/api/refinement/sample?'+query).status_code == 422

def test_review_tile_revision_grid_bounds_etag_and_native_download():
    meta = client.get('/api/refinement/meta').json()
    url = '/api/refinement/tiles/12/2313/1509.png'
    assert client.get(url,params={'v':'stale'}).status_code == 409
    assert client.get('/api/refinement/tiles/12/-1/0.png',params={'v':meta['revision']}).status_code == 422
    response = client.get(url,params={'v':meta['revision']})
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    array = np.asarray(Image.open(BytesIO(response.content)))
    assert array.shape == (256,256,4) and array[:,:,3].max() > 0
    assert client.get(url,params={'v':meta['revision']},headers={'If-None-Match':response.headers['etag']}).status_code == 304
    head = client.get('/api/refinement/download',headers={'Range':'bytes=0-63'})
    assert head.status_code == 206 and len(head.content) == 64
    assert head.content[:2] in (b'II', b'MM')

def test_observation_mechanism_enrichment_preserves_actual_source_geometry_and_properties():
    meta = client.get('/api/history/zones/meta').json()
    assert meta['mechanism_counts'] == {'unknown':136}
    assert meta['observation_confidence_counts'] == {'documented':136}
    response = client.get('/api/history/zones.geojson',params={'v':meta['revision']})
    original = json.loads((ROOT/'data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson').read_text())
    actual = response.json()
    assert len(actual['features']) == len(original['features']) == 136
    for before, after in zip(original['features'],actual['features']):
        assert before['geometry'] == after['geometry']
        assert all(after['properties'][key] == value for key,value in before['properties'].items())
        assert after['properties']['mechanism'] == after['properties']['mechanism_confidence'] == 'unknown'
        assert after['properties']['observation_confidence'] == 'documented'
    assert client.get('/api/history/zones.geojson',params={'v':meta['revision']},headers={'If-None-Match':response.headers['etag']}).status_code == 304

def test_assessment_sources_are_distinct_from_observations_and_serve_verified_light_geometry():
    meta = client.get('/api/flood-assessment/meta').json()
    assert meta['available'] and meta['zone_count'] == 6 and meta['context_count'] == 23
    response = client.get('/api/flood-assessment/geojson',params={'v':meta['revision']})
    assert response.status_code == 200
    features = response.json()['features']
    assert len(features) == 29 and len({f['properties']['source_id'] for f in features}) == 29
    zones = [f for f in features if f['properties']['geometry_role'] == 'assessment_zone']
    assert len(zones) == 6
    assert {f['properties']['assessment_level'] for f in zones} == {'high','medium','low'}
    assert all(f['properties']['mechanism'] == 'unknown' for f in zones)
    assert sum(f['geometry']['type'] == 'Point' for f in features) == 4
    assert client.get('/api/flood-assessment/geojson?v=stale').status_code == 409
    assert client.get('/api/flood-assessment/geojson',params={'v':meta['revision']},headers={'If-None-Match':response.headers['etag']}).status_code == 304

def test_register_causal_review_does_not_create_incident_coordinates_or_clogging_scores():
    events = client.get('/api/history/meta').json()['events']
    assert len(events) == 19
    reviews = [e['mechanism_review'] for e in events]
    assert all(r['geometry'] is None and r['spatial_override_eligible'] is False for r in reviews)
    assert sum('blockage_or_restricted_conveyance' in r['reported_coded_mechanisms'] for r in reviews) == 9
    assert all('clogging_probability' not in r for r in reviews)
