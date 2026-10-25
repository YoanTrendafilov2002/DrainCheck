"""Public API checks against independently mapped real river/lake footprints."""
import json,math,sys
from pathlib import Path
from io import BytesIO
import numpy as np
import pytest
import rasterio
from PIL import Image
from pyproj import Transformer
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import backend.app as api_module
from backend.app import app,pluvial,terrain

client=TestClient(app)
RIVER=(23.359073637791244,42.66766873740193)  # OSM way743562181 actual 5m centre
LAKE=(23.337247642167377,42.690042699335194)  # Ariana relation2905862
ISLAND=(23.336833150705026,42.68967465294718)  # Inner ring of same relation

@pytest.mark.parametrize('lon,lat',[LAKE])
def test_actual_water_api_is_excluded_without_replacing_native_elevation(lon,lat):
    response=client.get('/api/pluvial/sample',params={'lon':lon,'lat':lat})
    assert response.status_code==200
    value=response.json()
    assert value['status']=='excluded_open_water' and value['water_excluded'] is True
    assert all(value[name] is None for name in ['score','ponding_score','concentration_score','class','class_label'])
    assert value['factors']['mean_ground_elevation_m'] is not None
    native=client.get('/api/elevation',params={'lon':lon,'lat':lat})
    assert native.status_code==200 and native.json()==terrain.sample(lon,lat)

def test_actual_island_hole_keeps_original_land_scores():
    value=client.get('/api/pluvial/sample',params={'lon':ISLAND[0],'lat':ISLAND[1]}).json()
    assert value['water_excluded'] is False and value['status']=='ok'
    with rasterio.open(pluvial.path,OVERVIEW_LEVEL='NONE') as src:
        original=src.read([6,7,8],window=rasterio.windows.Window(value['column'],value['row'],1,1))[:,0,0]
    assert [value['ponding_score'],value['concentration_score'],value['score']]==original.tolist()

@pytest.mark.parametrize('mode',['ponding','concentration','combined'])
def test_water_screening_tiles_are_transparent_at_actual_lake_interior(mode):
    lon,lat=LAKE;z=18;n=2**z
    x=int((lon+180)/360*n);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    meta=client.get('/api/pluvial/meta').json()
    response=client.get(f'/api/pluvial/{mode}/{z}/{x}/{y}.png',params={'v':meta['revision']})
    assert response.status_code==200
    rgba=np.array(Image.open(BytesIO(response.content)).convert('RGBA'))
    px=int(((lon+180)/360*n-x)*256)
    py=int(((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n-y)*256)
    assert rgba[py,px,3]==0

def test_public_mask_metadata_and_summary_keep_water_separate():
    mask=client.get('/api/pluvial/water-mask/meta').json()
    meta=client.get('/api/pluvial/meta').json()
    assert mask['available'] is True and mask['source']['license']=='ODbL1.0'
    assert meta['water_exclusion']['enabled'] is True
    assert meta['water_exclusion']['revision']==mask['revision']
    assert meta['terrain_revision']=='f42644a668cdc14d' and meta['revision']!=meta['terrain_revision']
    for mode in ['ponding','concentration','combined']:
        summary=meta['summary']['by_mode'][mode]
        row=next(c for c in summary['classes'] if c['label']=='Excluded open water')
        assert row['cells']==summary['water_excluded_cells']
        assert row['cells']<=mask['counts']['water_cells']
        assert summary['screening_policy_excluded_cells']>0
        assert sum(c['cells'] for c in summary['classes'])==summary['terrain_cells']
    assert meta['water_exclusion']['mask_water_cells']==mask['counts']['water_cells']
    with rasterio.open(pluvial.water.path) as water,rasterio.open(pluvial.exclusions.path) as policy:
        overlap=sum(np.count_nonzero((water.read(1,window=w)==1)&(policy.read(1,window=w)>0))
                    for _,w in water.block_windows(1))
    assert meta['water_exclusion']['cell_count']+overlap==mask['counts']['water_cells']
    assert meta['water_exclusion']['cell_count']+summary['screening_policy_excluded_cells']==(
        mask['counts']['water_cells']+meta['screening_exclusions']['counts']['union_cells']-overlap)

def test_download_uses_masked_land_scores_and_explicit_water_flag():
    result=client.get('/api/pluvial/download/raster',headers={'Range':'bytes=0-31'})
    assert result.status_code==206 and len(result.content)==32
    assert 'pluvial_land_screening_5m.tif' in result.headers['Content-Disposition']
    with rasterio.open(ROOT/'data/derived/pluvial_land_screening_5m.tif') as src:
        assert src.count==5 and src.crs.to_epsg()==7801
        xy=Transformer.from_crs(4326,7801,always_xy=True)
        water=np.array(next(src.sample([xy.transform(*LAKE)])))
        land=np.array(next(src.sample([xy.transform(*ISLAND)])))
        assert np.all(water[:3]==src.nodata) and water[3]==1
        assert np.all(land[:3]>=0) and land[3]==0
    mask=client.get('/api/pluvial/download/water-mask',headers={'Range':'bytes=0-31'})
    assert mask.status_code==206 and len(mask.content)==32

def test_download_rejects_stale_land_export_receipt(monkeypatch):
    original=api_module.read_json_cached
    def changed(path):
        result=original(path)
        if Path(path).name=='pluvial_land_screening_5m.json':result['pluvial_revision']='stale'
        return result
    monkeypatch.setattr(api_module,'read_json_cached',changed)
    assert client.get('/api/pluvial/download/raster').status_code==409
