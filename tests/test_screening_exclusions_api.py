"""Real mapped Perlovska/stadium policy exclusions across every risk surface."""
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from pyproj import Transformer
from shapely import transform
from shapely.geometry import box, mapping

from backend import app as api
from backend.clogging import CloggingScenarios, TO_GEO, TO_METRIC, NODATA
from backend.river_context import RiverContext
from backend.terrain import tile_bounds

ROOT=Path(__file__).resolve().parents[1]
CLIENT=TestClient(api.app)
STADIUM=(23.3352531692,42.6875642953)
PERLOVSKA=(23.335932930341258,42.6895156)  # Inside OSM river polygon way1341771831.
LAND=(23.33370350350254,42.6866436907843)
XY=Transformer.from_crs(4326,3857,always_xy=True)


def tile_pixel(location, route, revision, **params):
    lon,lat=location;z=18;n=2**z
    x=int((lon+180)/360*n)
    y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    west,south,east,north=tile_bounds(z,x,y)
    mx,my=XY.transform(lon,lat)
    col=int((mx-west)/(east-west)*256);row=int((north-my)/(north-south)*256)
    response=CLIENT.get(route.format(z=z,x=x,y=y),params={'v':revision,**params})
    assert response.status_code==200,response.text
    return np.asarray(Image.open(BytesIO(response.content)))[row,col],response


@pytest.mark.parametrize('location,reason',[(STADIUM,'stadium'),(PERLOVSKA,'river')])
def test_real_policy_samples_have_no_risk_scores_and_keep_native_elevation(location,reason):
    params=dict(zip(('lon','lat'),location))
    for green in (0,1):
        terrain=CLIENT.get('/api/pluvial/sample',params={**params,'green_absorption':green}).json()
        review=CLIENT.get('/api/refinement/sample',params={**params,'green_absorption':green}).json()
        for sample in (terrain,review):
            assert sample['status']=='excluded_user_screening'
            assert sample['screening_excluded'] is True
            assert sample['screening_exclusion_reason']==reason
        assert all(terrain[name] is None for name in ('score','ponding_score','concentration_score','class','class_label'))
        assert review['review_class'] is review['legacy_ponding_score'] is None
        assert terrain['factors']['mean_ground_elevation_m'] is not None
    assert CLIENT.get('/api/elevation',params=params).json()==api.terrain.sample(*location)


@pytest.mark.parametrize('location',[STADIUM,PERLOVSKA])
@pytest.mark.parametrize('mode',['heatmap','ponding','combined','concentration','review'])
def test_actual_rivers_and_whole_stadium_are_transparent_in_every_risk_view(location,mode):
    base='refinement' if mode=='review' else 'pluvial'
    meta=CLIENT.get(f'/api/{base}/meta').json()
    route='/api/refinement/tiles/{z}/{x}/{y}.png' if mode=='review' else f'/api/pluvial/{mode}/{{z}}/{{x}}/{{y}}.png'
    for green in (0,1):
        pixel,_=tile_pixel(location,route,meta['revision'],green_absorption=green)
        assert pixel[3]==0


def test_nearby_real_land_keeps_its_original_positive_signal_and_new_cache_revision():
    sample=CLIENT.get('/api/pluvial/sample',params=dict(zip(('lon','lat'),LAND))).json()
    assert sample['status']=='ok' and not sample.get('screening_excluded',False)
    with rasterio.open(api.pluvial.path,OVERVIEW_LEVEL='NONE') as src:
        native=src.read([6,7,8],window=rasterio.windows.Window(sample['column'],sample['row'],1,1))[:,0,0]
    assert [sample['ponding_score'],sample['concentration_score'],sample['score']]==native.tolist()
    meta=CLIENT.get('/api/pluvial/meta').json()
    assert meta['screening_exclusions']['enabled']
    assert meta['screening_exclusions']['revision']==api.pluvial.exclusions.meta()['revision']
    assert meta['revision'] not in (meta['terrain_revision'],'2a0d5f6899cd036c')
    pixel,response=tile_pixel(LAND,'/api/pluvial/heatmap/{z}/{x}/{y}.png',meta['revision'])
    assert pixel[3]>0
    assert 'immutable' in response.headers['cache-control']
    assert CLIENT.get(str(response.request.url).replace(meta['revision'],'2a0d5f6899cd036c')).status_code==409
    review=CLIENT.get('/api/refinement/meta').json()
    assert review['revision']!='853d77c47901ec54'
    assert CLIENT.get('/api/refinement/tiles/18/148068/96634.png',params={'v':'853d77c47901ec54'}).status_code==409


def test_river_and_stadium_cells_do_not_receive_scenario_runoff_or_ponding(tmp_path):
    service=CloggingScenarios(ROOT,api.pluvial,RiverContext(ROOT))
    service.directory=tmp_path
    x,y=TO_METRIC.transform(*STADIUM)
    selection=mapping(transform(box(x-350,y-350,x+350,y+350),TO_GEO.transform,interleaved=False))
    result=service.create(selection,rainfall_mm=100,blockage_percent=100)
    assert result['statistics']['screening_policy_excluded_area_m2']>0
    with rasterio.open(service.path(result['scenario_id'])/'runoff.tif') as src:
        for location in (STADIUM,PERLOVSKA):
            values=next(src.sample([TO_METRIC.transform(*location)]))
            assert np.all(values==NODATA)
        valid=src.read(1)!=NODATA
        assert np.any(valid),'Surrounding eligible land must remain calculated'
    revision=result['sources']['pluvial_revision'] if 'sources' in result else service.source_state()['pluvial_revision']
    assert revision==api.pluvial.meta()['revision']
