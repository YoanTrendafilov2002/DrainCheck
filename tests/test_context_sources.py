"""Real history evidence and isolated building-index fixtures, never demo data."""
import csv,hashlib,json,math,sys
from pathlib import Path
import mapbox_vector_tile
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import backend.app as api_module
from backend.app import app
from backend.context_layers import BuildingsContext,HistoricalSurveyContext
from scripts.prepare_buildings_index import prepare

client=TestClient(app)

def fixture_buildings(tmp_path,verified_height=False,duplicate=False):
    """Two labelled mathematical fixtures in a temporary root, not app map inputs."""
    derived=tmp_path/'data/derived';cache=tmp_path/'data/cache'
    derived.mkdir(parents=True);cache.mkdir(parents=True)
    ring=[[23.32,42.70],[23.3201,42.70],[23.3201,42.7001],[23.32,42.7001],[23.32,42.70]]
    props={'source_id':'test-a','height_m':12.5,'source_note':'Unit-test fixture only'}
    feature={'type':'Feature','properties':props,'geometry':{'type':'Polygon','coordinates':[ring]}}
    features=[feature,{**feature,'properties':{**props,'source_id':'test-a' if duplicate else 'test-b'}}]
    data=derived/'digital_twin_buildings.geojson'
    data.write_text(json.dumps({'type':'FeatureCollection','features':features}))
    meta=cache/'digital_twin_buildings_meta.json'
    meta.write_text(json.dumps({'available':True,'revision':'fixture-v1','feature_count':2,
                                'height':{'available':verified_height,'semantics':'height_above_ground_m' if verified_height else 'unknown'}}))
    return data,meta,cache/'digital_twin_buildings.sqlite'

def test_missing_real_building_source_never_substitutes_research_data(tmp_path,monkeypatch):
    layer=BuildingsContext(tmp_path);assert layer.meta()['available'] is False
    monkeypatch.setattr(api_module,'buildings',layer)
    assert client.get('/api/buildings/meta').json()['available'] is False
    for url in ['/api/buildings/download','/api/buildings/feature?source_id=x','/api/buildings/tiles/15/18506/12077.pbf?v=x']:
        assert client.get(url).status_code==503

@pytest.mark.parametrize('verified_height',[False,True])
def test_independent_index_preserves_ids_source_and_verified_height_semantics(tmp_path,verified_height):
    data,meta,index=fixture_buildings(tmp_path,verified_height)
    before=hashlib.sha256(data.read_bytes()).hexdigest();prepare(data,meta,index)
    assert hashlib.sha256(data.read_bytes()).hexdigest()==before
    layer=BuildingsContext(tmp_path);assert layer.meta()['available'] is True
    feature=layer.feature('test-a')
    assert feature['properties']['source_id']=='test-a'
    assert shape(feature['geometry']).equals(shape(json.loads(data.read_text())['features'][0]['geometry']))
    props=feature['properties']
    if verified_height:assert props['height_m']==12.5
    else:assert 'height_m' not in props and props['source_height_m']==12.5
    z=14;lon,lat=23.32005,42.70005;n=2**z
    x=int((lon+180)/360*n);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    tile=mapbox_vector_tile.decode(layer.tile(z,x,y))['buildings']['features']
    assert {v['properties']['source_id'] for v in tile}=={'test-a','test-b'}
    assert len({v['id'] for v in tile})==2

def test_duplicate_building_source_id_is_rejected(tmp_path):
    data,meta,index=fixture_buildings(tmp_path,duplicate=True)
    with pytest.raises(ValueError,match='unique'):prepare(data,meta,index)

def test_building_api_accepts_only_its_own_index_revision_and_compresses_tiles(tmp_path,monkeypatch):
    data,meta,index=fixture_buildings(tmp_path);prepare(data,meta,index)
    monkeypatch.setattr(api_module,'buildings',BuildingsContext(tmp_path))
    z=14;lon,lat=23.32005,42.70005;n=2**z
    x=int((lon+180)/360*n);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    url=f'/api/buildings/tiles/{z}/{x}/{y}.pbf'
    assert client.get(url,params={'v':'stale'}).status_code==409
    raw=client.get(url,params={'v':'fixture-v1'},headers={'Accept-Encoding':'identity'})
    compressed=client.get(url,params={'v':'fixture-v1'},headers={'Accept-Encoding':'gzip'})
    assert raw.status_code==compressed.status_code==200 and raw.content==compressed.content
    assert compressed.headers['Content-Encoding']=='gzip' and 'Content-Encoding' not in raw.headers
    assert len(mapbox_vector_tile.decode(raw.content)['buildings']['features'])==2
    assert client.get('/api/buildings/feature?source_id=test-a').json()['id']=='test-a'
    assert client.get('/api/buildings/download').status_code==200

def test_changed_source_invalidates_independent_building_index(tmp_path):
    data,meta,index=fixture_buildings(tmp_path);prepare(data,meta,index)
    layer=BuildingsContext(tmp_path);assert layer.meta()['available'] is True
    doc=json.loads(data.read_text());doc['features'][0]['properties']['source_note']='Changed fixture'
    data.write_text(json.dumps(doc))
    assert layer.meta()['available'] is False and 'changed' in layer.meta()['message']

def test_real_historical_survey_retains_all136_valid_source_polygons():
    meta=client.get('/api/history/zones/meta').json()
    assert meta['available'] and meta['feature_count']==136 and meta['revision']=='7fbfbcee6ee933f4'
    data=client.get('/api/history/zones.geojson',params={'v':meta['revision']})
    assert data.status_code==200 and 'immutable' in data.headers['Cache-Control']
    doc=data.json();assert len(doc['features'])==136
    assert len({f['properties']['source_id'] for f in doc['features']})==136
    assert all(shape(f['geometry']).is_valid and shape(f['geometry']).area>0 for f in doc['features'])
    assert 'not confirmed pure pluvial' in meta['flood_type']
    assert meta['date_precision'].startswith('Year;')
    assert {v['object_id'] for v in meta['geometry_repairs']}=={41,72}
    assert client.get('/api/history/zones.geojson?v=stale').status_code==409

def test_historical_geometry_changes_fail_closed(tmp_path):
    reference=tmp_path/'data/reference/historical_floods';reference.mkdir(parents=True)
    cache=tmp_path/'data/cache';cache.mkdir(parents=True)
    original=json.loads((ROOT/'data/cache/historical_flood_zones_meta.json').read_text())
    original['data_file']='data/reference/historical_floods/changed.geojson'
    (reference/'changed.geojson').write_text('{"type":"FeatureCollection","features":[]}')
    (cache/'historical_flood_zones_meta.json').write_text(json.dumps(original))
    assert HistoricalSurveyContext(tmp_path).meta()['available'] is False

def test_register_preserves_rows_and_ambiguous_dates_without_invented_geometry():
    data=client.get('/api/history/meta').json()
    assert data['record_count']==len(data['events'])==19
    assert data['unique_source_event_ids']==15
    assert data['type_counts']=={'Pluvial':14,'Pluvial + river':2,'Pluvial + infrastructure':3}
    assert len({e['source_event_id'] for e in data['events']})==15
    assert all(e['source_row']>0 and e['description'] and 'geometry' not in e for e in data['events'])
    assert any(e['quality_notes'] for e in data['events'])
    assert 'draft' in data['register_status'].lower()
    assert 'not observed inundation' in data['map_description']
    exported=client.get('/api/history/download')
    assert exported.status_code==200
    assert len(list(csv.DictReader(exported.text.splitlines())))==19

def test_official_historical_pdf_is_original_and_range_downloadable():
    data=client.get('/api/history/meta').json()
    response=client.get('/api/history/map',headers={'Range':'bytes=0-31'})
    assert response.status_code==206 and response.content.startswith(b'%PDF')
    assert response.headers['Content-Type']=='application/pdf'
    assert response.headers['Content-Disposition'].startswith('inline;')
    path=ROOT/data['map_file']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==data['source_sha256'][path.name]

def test_new_context_preserves_spatial_and_screening_revisions():
    assert client.get('/api/meta').json()['revision']=='af34c6d53d5b26fd'
    meta=client.get('/api/pluvial/meta').json()
    assert meta['terrain_revision']=='f42644a668cdc14d'
    assert meta['revision']=='2a0d5f6899cd036c'
