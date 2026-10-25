"""The rainfall package adds inputs while retaining the earlier application's real data."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from backend.app import app,ROOT
from scripts.prepare_data import refresh_data_revision

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def test_complete_supplement_and_three_reference_scripts_remain_original_bytes():
    receipt=json.loads((ROOT/'handoff/rainfall_supplement_receipt.json').read_text())
    assert len(receipt['files'])==53
    for name,record in receipt['files'].items():
        assert digest(ROOT/'handoff/rainfall_supplement'/name)==record['sha256'],name
        if name.startswith('data/rainfall/') or name.startswith('earth_engine/'):
            assert digest(ROOT/name)==record['sha256'],name
    assert digest(ROOT/'handoff/Sofia_App_Codex_Handoff.rainfall.original.zip')==receipt['supplement_zip_sha256']

def test_supplement_preserves_originals_and_policy_derivatives_keep_source_identity():
    baseline=json.loads((ROOT/'handoff/pre_rainfall_app_manifest.json').read_text())
    required={'data/cache/spatial.sqlite','data/cache/pluvial_5m.tif','data/cache/open_water_mask_5m.tif',
              'data/derived/pluvial_land_screening_5m.tif'}
    # These four derivatives intentionally acquire the requested river/stadium
    # exclusion. Every original and every unrelated derivative retains its hash.
    recut={'data/derived/pluvial_land_screening_5m.tif',
           'data/derived/pluvial_land_screening_5m.json',
           'data/derived/infrastructure_terrain_screening.csv',
           'data/derived/sewer_route_terrain_screening.csv'}
    for name,record in baseline.items():
        if name.startswith(('data/raw/','data/derived/')) or name in required:
            if name in recut:continue
            assert digest(ROOT/name)==record['sha256'],name
    exposure=json.loads((ROOT/'data/cache/pluvial_exposure.json').read_text())
    policy=json.loads((ROOT/'data/cache/screening_exclusions_meta.json').read_text())
    export=json.loads((ROOT/'data/derived/pluvial_land_screening_5m.json').read_text())
    assert policy['exclusions_are_policy'] is True
    assert policy['sha256']==digest(ROOT/policy['file'])
    assert exposure['screening_exclusions_revision']==policy['revision']
    assert exposure['sources']['screening_exclusions_sha256']==policy['sha256']
    assert exposure['sources']['raster_sha256']==baseline['data/cache/pluvial_5m.tif']['sha256']
    assert exposure['sources']['open_water_sha256']==baseline['data/cache/open_water_mask_5m.tif']['sha256']
    assert export==exposure['land_raster_export']
    assert export['source_sha256']==exposure['sources']['raster_sha256']
    assert export['screening_exclusions_sha256']==policy['sha256']
    assert export['output_sha256']==digest(ROOT/'data/derived/pluvial_land_screening_5m.tif')
    assert export['verification']['all_nonexcluded_land_score_pixels_identical'] is True
    assert export['verification']['all_policy_score_pixels_nodata'] is True
    # Full source-record preservation and actual per-cell CSV classes/scores
    # remain independently checked in test_pluvial_exposure.py.

def test_rainfall_and_restored_display_curve_do_not_invalidate_existing_scales_or_exposure():
    before=(ROOT/'data/cache/revision.txt').read_text().strip()
    assert before=='af34c6d53d5b26fd'
    assert refresh_data_revision()==before
    client=TestClient(app)
    for mode in ['ponding','combined','concentration']:
        assert client.get('/api/pluvial/exposure',params={'mode':mode}).status_code==200
    assert client.get('/api/pluvial/sample?lon=23.30135&lat=42.75068').status_code==200
    assert client.get('/api/history/zones/meta').json()['feature_count']==136
    assert client.get('/api/history/meta').json()['record_count']==19
    assert client.get('/api/buildings/meta').json()['available'] is False
    assert client.get('/api/elevation?lon=23.30135&lat=42.75068').json()['sample_resolution_m']==1
    assert client.get('/api/rainfall/meta').json()['available'] is True

@pytest.mark.parametrize('zone,count,length_km',[('all',717,540.163013503),('inside',543,137.858698851),('outside',670,402.304314680)])
def test_original_route_filters_statistics_exports_still_work_beside_rainfall(zone,count,length_km):
    client=TestClient(app)
    statistics=client.get('/api/route-statistics',params={'zone':zone,'status':'existing,planned,open'}).json()
    assert statistics['count']==count
    assert statistics['length_m']/1000==pytest.approx(length_km,abs=1e-8)
    exported=client.get('/api/export/routes',params={'zone':zone,'status':'existing,planned,open'}).json()
    assert len(exported['features'])==count
