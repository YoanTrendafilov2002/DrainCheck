import io,itertools,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
import rasterio
from rasterio.windows import Window
from PIL import Image
from fastapi.testclient import TestClient
from pyproj import Transformer,Geod
from shapely import from_wkb,STRtree,union_all,make_valid
from shapely.geometry import shape,LineString
from backend.app import app,terrain,database,ROOT
from backend.scale import normalize,inverse

client=TestClient(app)
SUMMARY=json.loads((ROOT/'data/derived/summary.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('zone',['all','inside','outside'])
@pytest.mark.parametrize('enabled',[[],['existing'],['planned'],['open'],['existing','planned'],['existing','open'],['planned','open'],['existing','planned','open']])
def test_filter_statistics(zone,enabled):
    result=client.get('/api/route-statistics',params={'zone':zone,'status':','.join(enabled)}).json()
    expected=[SUMMARY['zone_status_statistics'].get(zone+':'+s,{'count':0,'length_m':0}) for s in enabled]
    assert result['count']==sum(r['count'] for r in expected)
    assert result['length_m']==pytest.approx(sum(r['length_m'] for r in expected),abs=.001)

def test_export_retains_source_ids_properties_and_full_geometry():
    exported=client.get('/api/export/routes?zone=inside&status=existing,planned,open').json()
    expected=json.loads((ROOT/'data/derived/sewer_routes_inside.geojson').read_text(encoding='utf-8'))
    assert len(exported['features'])==543
    for actual,original in zip(exported['features'],expected['features']):
        assert actual['properties']==original['properties']
        assert actual['geometry']==original['geometry']
    assert exported['features'][0]['properties']['legso'].startswith('01.Канален')

def test_no_filter_exports_no_routes_instead_of_silently_enabling_all():
    assert client.get('/api/export/routes?zone=all&status=').json()['features']==[]

def test_all_routes_partition_with_traversal_length_preserved():
    geod=Geod(ellps='WGS84');lengths={}
    for zone in ['all','inside','outside']:
        source=json.loads((ROOT/f'data/derived/sewer_routes_{zone}.geojson').read_text(encoding='utf-8'))
        lengths[zone]={f['properties']['source_id']:abs(geod.geometry_length(shape(f['geometry']))) for f in source['features']}
        assert sum(lengths[zone].values())==pytest.approx(SUMMARY['zone_length_m'][zone],abs=.001)
    for sid,total in lengths['all'].items():
        assert lengths['inside'].get(sid,0)+lengths['outside'].get(sid,0)==pytest.approx(total,abs=.001)

def test_native_sample_uses_actual_1m_source_pixel_without_interpolation():
    lon,lat=23.30135,42.75068
    result=client.get('/api/elevation',params={'lon':lon,'lat':lat}).json()
    x,y=Transformer.from_crs(4326,7801,always_xy=True).transform(lon,lat)
    with rasterio.open(terrain.native,OVERVIEW_LEVEL='NONE') as source:
        row,col=source.index(x,y)
        expected=float(source.read(1,window=Window(col,row,1,1))[0,0])
    assert result['status']=='ok' and result['sample_resolution_m']==1
    assert result['row']==row and result['column']==col
    assert result['elevation_m']==expected

def test_actual_nodata_is_distinct_from_request_error(monkeypatch):
    result=client.get('/api/elevation?lon=22&lat=42').json()
    assert result['status']=='nodata' and result['elevation_m'] is None
    monkeypatch.setattr(terrain,'native',ROOT/'data/external/missing.tif')
    error=client.get('/api/elevation?lon=23.3&lat=42.7')
    assert error.status_code==503
    assert 'detail' in error.json() and 'elevation_m' not in error.json()

def test_real_native_nodata_inside_the_raster_extent_stays_missing():
    with rasterio.open(terrain.native) as src:
        a=src.read(1,window=Window(0,0,512,512))
        row,col=np.argwhere(a==src.nodata)[0]
        x,y=src.xy(int(row),int(col))
    lon,lat=Transformer.from_crs(7801,4326,always_xy=True).transform(x,y)
    result=client.get('/api/elevation',params={'lon':lon,'lat':lat}).json()
    assert result['status']=='nodata' and result['elevation_m'] is None

def test_a_preview_image_cannot_be_used_as_the_native_elevation_source(tmp_path):
    from backend.terrain import LocalTerrain
    image=tmp_path/'preview.png';Image.new('RGB',(32,32),'green').save(image)
    assert LocalTerrain(image,tmp_path).available is False

def test_no_elevation_tiles_are_transparent_not_fake_zero_terrain():
    revision=client.get('/api/meta').json()['revision']
    response=client.get('/api/raster/whole/5/0/0.png',params={'v':revision})
    image=np.asarray(Image.open(io.BytesIO(response.content)))
    assert image.shape==(256,256,4)
    assert np.all(image[:,:,3]==0)

@pytest.mark.parametrize('kind',['routes','green','points'])
def test_real_vector_tiles_decode(kind):
    import mapbox_vector_tile
    z=14;lon,lat=23.30135,42.75068
    x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    rev=client.get('/api/meta').json()['revision']
    response=client.get(f'/api/vector/{kind}/{z}/{x}/{y}.pbf',params={'v':rev})
    assert response.status_code==200
    data=mapbox_vector_tile.decode(response.content)
    assert data[kind]['features']

def test_revision_and_invalid_coordinate_rejections():
    assert client.get('/api/raster/whole/14/1/1.png?v=stale').status_code==409
    rev=client.get('/api/meta').json()['revision']
    assert client.get('/api/vector/routes/14/-1/0.pbf',params={'v':rev}).status_code==422
    assert client.get('/api/elevation?lon=999&lat=42').status_code==422
    assert client.post('/api/scales/local',json={'bounds':[24,43,23,42]}).status_code==422

def test_full_green_mask_and_all_point_categories_indexed():
    with database() as db:
        assert db.execute("SELECT COUNT(*) FROM features WHERE kind='green'").fetchone()[0]==64956
        assert db.execute("SELECT COUNT(*) FROM features WHERE kind='green' AND display=1").fetchone()[0]==2175
        assert db.execute("SELECT COUNT(*) FROM features WHERE kind='points'").fetchone()[0]==322025
        assert db.execute("SELECT COUNT(*) FROM features WHERE kind='points' AND status='missing'").fetchone()[0]==83
    source=next((ROOT/'data/raw').glob('green_areas*.geojson'))
    assert len(json.loads(source.read_text(encoding='utf-8'))['features'])==64962

def test_route_intersections_recomputed_against_full_source_mask():
    with database() as db:
        allgreen=[from_wkb(r[0]) for r in db.execute("SELECT geometry FROM features WHERE kind='green'")]
    tree=STRtree(allgreen);geod=Geod(ellps='WGS84')
    original=json.loads((ROOT/'data/raw/vik_kanal_26_sofpr_20090000.geojson').read_text(encoding='utf-8'))
    expected={f['properties']['source_id']:f['properties']['length_m'] for f in json.loads((ROOT/'data/derived/sewer_routes_inside.geojson').read_text(encoding='utf-8'))['features']}
    def lines(g):
        if g.geom_type=='LineString':return [g] if g.length else []
        return [part for child in getattr(g,'geoms',[]) for part in lines(child)]
    # Verify every supplied route against candidates from all 64,956 polygons.
    for f in original['features']:
        route=shape(f['geometry']);candidates=tree.query(route,predicate='intersects')
        mask=union_all([allgreen[i] for i in candidates])
        parts=[route] if route.is_simple else [LineString([a,b]) for line in lines(route) for a,b in zip(list(line.coords)[:-1],list(line.coords)[1:])]
        length=sum(abs(geod.geometry_length(piece)) for part in parts for piece in lines(part.intersection(mask)))
        assert length==pytest.approx(expected.get(f['properties']['id'],0),abs=.002)

def test_polygon_holes_and_multipart_survive_indexing():
    source=json.loads(next((ROOT/'data/raw').glob('green_areas*.geojson')).read_text(encoding='utf-8'))
    checked=0
    for f in source['features']:
        geom=shape(f['geometry']) if f.get('geometry') else None
        if not geom or geom.is_empty or not geom.is_valid:continue
        polygons=[geom] if geom.geom_type=='Polygon' else list(geom.geoms)
        if any(len(p.interiors) for p in polygons) or len(polygons)>1:
            result=client.get('/api/green/'+f['properties']['id']).json()
            assert shape(result['geometry']).equals_exact(geom,1e-12)
            checked+=1
        if checked==10:break
    assert checked==10

def test_local_fit_is_cached_and_native_heights_remain_identical():
    point=client.get('/api/elevation?lon=23.30135&lat=42.75068').json()
    bounds=[23.29,42.74,23.32,42.76]
    a=client.post('/api/scales/local',json={'bounds':bounds});assert a.status_code==200
    scale=a.json();assert len(scale['quantiles'])==201 and scale['statistics_scale_m']==10
    assert scale['scope']=='locked-local-view'
    assert client.post('/api/scales/local',json={'bounds':bounds}).json()==scale
    for tick in scale['legend']:
        assert inverse(tick['level'],scale)==pytest.approx(tick['elevation_m'])
    assert client.get('/api/elevation?lon=23.30135&lat=42.75068').json()==point
    assert client.get('/api/scales/local-0000000000000000').status_code==404

def test_production_javascript_mime_type():
    index=client.get('/');assert index.status_code==200
    import re
    asset=re.search(r'src="([^"]+\.js)"',index.text)[1]
    response=client.get(asset)
    assert 'javascript' in response.headers['content-type']
