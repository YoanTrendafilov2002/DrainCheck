"""Preserved legacy real tiles are independent oracles for display optimizations."""
import gzip,hashlib,json,sys
from pathlib import Path
import mapbox_vector_tile
import pytest
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app import app,revision,RENDERER_REVISION
from backend.vector import render_vector_tile,category_filter
from backend.http_cache import accepts_gzip

client=TestClient(app)
FIXTURES=ROOT/'tests/fixtures/mvt'
CASES=[('points',15,18506,12077,'inside','subset'),('green',13,4626,3019,'inside','all'),
       ('green',12,2313,1509,'inside','subset'),('routes',12,2313,1509,'all','subset')]
def keyed(data,kind):return {f['id']:f for f in mapbox_vector_tile.decode(data)[kind]['features']}
def baseline(kind,z,x,y,display):return (FIXTURES/f'vector_baseline_{kind}_{display}_{z}_{x}_{y}.pbf').read_bytes()

@pytest.mark.parametrize('kind,z,x,y,zone,display',CASES)
def test_optimized_real_tiles_preserve_legacy_geometry_ids_and_properties(kind,z,x,y,zone,display):
    expected=baseline(kind,z,x,y,display)
    actual=render_vector_tile(ROOT/'data/cache/spatial.sqlite',kind,z,x,y,zone,display)
    assert keyed(actual,kind)==keyed(expected,kind)

def test_point_filter_preserves_every_selected_record_and_full_display_properties():
    kind,z,x,y,zone,display=CASES[0]
    original=keyed(baseline(kind,z,x,y,display),kind)
    expected={fid:f for fid,f in original.items() if f['properties']['category'] in ('3','4')}
    response=client.get(f'/api/vector/points/{z}/{x}/{y}.pbf',params={'v':revision(),'categories':'4,3,3'})
    assert response.status_code==200 and keyed(response.content,kind)==expected
    assert len(expected)==476
    empty=client.get(f'/api/vector/points/{z}/{x}/{y}.pbf',params={'v':revision(),'categories':''})
    assert keyed(empty.content,kind)=={}
    assert client.get(f'/api/vector/points/{z}/{x}/{y}.pbf',params={'v':revision(),'categories':'99'}).status_code==422
    assert category_filter('4,3,3')==('3','4') and category_filter(None) is None

def test_compression_variants_decode_identically_and_support_conditional_requests():
    url='/api/vector/points/15/18506/12077.pbf?v='+revision()
    compressed=client.get(url,headers={'Accept-Encoding':'gzip'})
    identity=client.get(url,headers={'Accept-Encoding':'gzip;q=0, identity'})
    assert compressed.status_code==identity.status_code==200
    assert compressed.content==identity.content
    assert compressed.headers['Content-Encoding']=='gzip' and 'Content-Encoding' not in identity.headers
    assert int(compressed.headers['Content-Length'])<len(compressed.content)
    assert compressed.headers['ETag']!=identity.headers['ETag']
    assert compressed.headers['Vary']=='Accept-Encoding'
    assert 'immutable' in compressed.headers['Cache-Control'] and 'Server-Timing' in compressed.headers
    for value in [compressed.headers['ETag'],'W/'+compressed.headers['ETag'],'*']:
        again=client.get(url,headers={'Accept-Encoding':'gzip','If-None-Match':value})
        assert again.status_code==304 and again.content==b''

@pytest.mark.parametrize('header,expected',[('',False),('gzip',True),('br, gzip;q=0.5',True),('gzip;q=0, *;q=1',False),('*',True)])
def test_accept_encoding_quality_is_respected(header,expected):assert accepts_gzip(header)==expected

def test_static_gzip_is_exact_build_content_with_correct_mime_and_cache_scope():
    original=next(p for p in (ROOT/'dist/assets').glob('index-*.js') if not p.name.endswith('.gz'))
    assert original.with_name(original.name+'.gz').is_file(),'Run pnpm build before integration tests'
    response=client.get('/assets/'+original.name,headers={'Accept-Encoding':'gzip'})
    assert response.status_code==200 and response.content==original.read_bytes()
    assert response.headers['Content-Encoding']=='gzip' and 'javascript' in response.headers['Content-Type']
    assert 'immutable' in response.headers['Cache-Control']
    raw=client.get('/assets/'+original.name,headers={'Accept-Encoding':'identity'})
    assert raw.content==response.content and 'Content-Encoding' not in raw.headers
    assert client.get('/').headers['Cache-Control']=='no-cache'

def test_metadata_exposes_renderer_version_without_changing_analysis_revision():
    data=client.get('/api/meta').json()
    assert data['renderer_revision']==RENDERER_REVISION and data['revision']==revision()
    screening=client.get('/api/pluvial/meta').json()
    assert screening['terrain_revision']=='f42644a668cdc14d'
    assert screening['revision']!=screening['terrain_revision']
    assert screening['water_exclusion']['enabled'] is True
    assert client.get('/api/performance').json()['tile_cache']['inflight']==0
