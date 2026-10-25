"""Real-data tests for bounded, non-hydraulic drainage-loss scenarios."""
import io
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from shapely import from_wkb, transform
from shapely.geometry import box, mapping

from backend.clogging import (CloggingScenarios, ScenarioStale, TO_GEO, TO_METRIC,
                              runoff_values, scenario_rgba, storage_depths, NODATA)
from backend.clogging_routes import create_clogging_router
from backend.pluvial import LocalPluvial
from backend.river_context import RiverContext

ROOT = Path(__file__).resolve().parents[1]


def selection_at(lon=23.267111, lat=42.684845, width=400):
    x,y = TO_METRIC.transform(lon,lat)
    return mapping(transform(box(x-width/2,y-width/2,x+width/2,y+width/2),TO_GEO.transform,interleaved=False))


@pytest.fixture(scope='module')
def real_scenario(tmp_path_factory):
    pluvial = LocalPluvial(ROOT/'data/cache')
    assert pluvial.available, 'Matching genuine restored terrain/water inputs required'
    service = CloggingScenarios(ROOT,pluvial,RiverContext(ROOT))
    service.directory = tmp_path_factory.mktemp('clogging-real')
    result = service.create(selection_at())
    return service,result


def test_water_balance_units_and_capacity_thresholds():
    assert runoff_values(30,60,15,100,.9) == (27,12,27)
    assert runoff_values(30,60,15,0,.9) == (27,12,12)
    assert runoff_values(10,120,20,50,1) == (10,0,0)
    assert runoff_values(0,60,15,100,.9) == (0,0,0)


def test_real_selection_sources_grid_green_and_volume(real_scenario):
    service,result = real_scenario
    stats = result['statistics']
    assert math.isclose(stats['selection_area_m2'],160000,abs_tol=.001)
    assert stats['green_excluded_area_m2'] > 0
    assert stats['rasterized_selection_area_m2'] == sum(stats[key] for key in ['eligible_nongreen_land_area_m2','green_excluded_area_m2','mapped_water_excluded_area_m2','screening_policy_excluded_area_m2','uncertain_or_missing_terrain_area_m2'])
    assert stats['affected_eligible_area_m2'] > 0
    assert result['route_counts']['existing'] >= 1
    assert result['selected_route_counts']['existing'] == result['route_counts']['existing']
    assert result['selected_route_counts']['planned'] == result['selected_route_counts']['open'] == 0
    assert result['grid']['resolution_m'] == 5
    with rasterio.open(service.path(result['scenario_id'])/'runoff.tif') as src:
        arrays = src.read()
        assert src.crs.to_epsg() == 7801 and src.nodata == NODATA
        assert src.descriptions == tuple(result['bands'])
        assert src.count == 6
        assert list(src.transform)[:2] == [5,0]
        assert (src.transform.c-299392)%5 == 0
        assert (4753611-src.transform.f)%5 == 0
        valid = arrays[0] != NODATA
        assert np.all(arrays[0][valid] == 12)
        assert set(np.unique(arrays[1][valid])) <= {12,27}
        assert set(np.unique(arrays[2][valid])) <= {0,15}
        assert np.array_equal(arrays[1][valid]-arrays[0][valid],arrays[2][valid])
        assert np.sum(arrays[2][valid],dtype='float64')*25/1000 == stats['additional_potential_unremoved_volume_m3']
        assert np.count_nonzero(valid) == stats['eligible_cell_count']
        # The known clicked position is in the full real green polygon union.
        x,y = TO_METRIC.transform(23.267111,42.684845)
        row,col = src.index(x,y)
        assert np.all(arrays[:,row,col] == NODATA)
    assert stats['clogged_potential_unremoved_volume_m3'] == stats['baseline_potential_unremoved_volume_m3']+stats['additional_potential_unremoved_volume_m3']
    assert 'not predicted flood' in result['interpretation']
    assert all(text.isascii() for text in result['formula'].values())
    assert 'not a measured capacity' in ' '.join(result['assumptions'])


def test_local_depression_storage_uses_separate_terrain_components():
    # Unit test only: these small arrays check the numerical method; app tests
    # below use genuine terrain and no synthetic source is installed in the app.
    beds=np.full((3,7),110.,dtype='float64')
    fills=np.zeros_like(beds)
    beds[1,1:3]=[100,99];fills[1,1:3]=[1,2]
    beds[1,4:6]=[150,149];fills[1,4:6]=[1,2]
    eligible=np.ones_like(beds,dtype=bool)
    runoff=np.zeros_like(beds);runoff[1,1:3]=100
    baseline,clogged,change,stats=storage_depths(beds,fills,eligible,runoff,runoff,eligible)
    assert stats['components']['count']==2
    assert np.all(clogged[1,4:6]==0), 'No transfer from one depression component to another'
    assert baseline[1,1]==0 and .1999 < baseline[1,2] <= .2
    assert np.all(change==0)
    assert stats['baseline']['source_runoff_volume_m3']==5
    assert math.isclose(stats['baseline']['stored_volume_m3'],5,abs_tol=1e-6)
    assert abs(stats['baseline']['volume_balance_error_m3'])<1e-9


def test_storage_cap_overflow_nondepression_and_nodata_close_volume():
    beds=np.full((3,3),100.,dtype='float64')
    fills=np.ones_like(beds)
    eligible=np.ones_like(beds,dtype=bool);eligible[0,0]=False
    fills[0,1]=0
    runoff=np.full_like(beds,2000.)
    d0,d1,change,stats=storage_depths(beds,fills,eligible,np.zeros_like(beds),runoff,eligible)
    assert d0[0,0]==d1[0,0]==change[0,0]==NODATA
    assert np.all(d0[eligible]==0)
    assert d1[0,1]==0
    assert d1.max()==1
    assert stats['clogged']['stored_volume_m3']==175
    assert stats['clogged']['overflow_volume_m3']==175
    assert stats['clogged']['unallocated_nondepression_volume_m3']==50
    assert stats['clogged']['source_runoff_volume_m3']==400
    assert stats['clogged']['volume_balance_error_m3']==0
    assert stats['components']['boundary_truncated_count']==1


def test_real_native_depression_depths_mask_cap_and_volume(real_scenario):
    service,result=real_scenario
    with rasterio.open(service.path(result['scenario_id'])/'runoff.tif') as src:
        runoff=src.read([1,2,3]);depth=src.read([4,5,6])
    grid=result['grid']
    from rasterio.windows import Window
    with rasterio.open(service.pluvial.path) as src:
        native=src.read([1,2],window=Window(grid['column_offset'],grid['row_offset'],grid['width'],grid['height']))
    eligible=runoff[0]!=NODATA
    assert np.array_equal(depth[0]!=NODATA,eligible)
    assert np.array_equal(depth[1]!=NODATA,eligible)
    assert np.all(depth[0][eligible]>=0)
    assert np.all(depth[1][eligible]>=depth[0][eligible])
    assert np.all(depth[1][eligible]<=native[1][eligible]+1e-7)
    assert np.all(depth[1][eligible & (native[1]==0)]==0)
    assert np.all(depth[2][eligible]>=0)
    for index,mode in enumerate(['baseline','clogged']):
        summary=result['depth_statistics'][mode]
        assert abs(summary['volume_balance_error_m3'])<1e-6
        assert math.isclose(summary['stored_volume_m3'],float(np.sum(depth[index][eligible],dtype='float64')*25),abs_tol=1e-8)
        assert math.isclose(summary['source_runoff_volume_m3'],result['statistics'][mode+'_potential_unremoved_volume_m3'],abs_tol=1e-7)
        assert summary['unallocated_total_volume_m3']>=0
    assert result['depth_statistics']['components']['count']>=1
    assert result['depth_legend']['maximum_m']>=result['depth_statistics']['clogged']['max_depth_m']


def test_real_river_proximity_strata_and_display_filter(real_scenario):
    service,result=real_scenario
    river=result['river_context']
    assert river['available'] and river['threshold_m']==100
    counts=river['source_counts']
    assert counts['osm_river_centerlines']>0
    assert counts['included_river_geometries']==18+19+counts['osm_river_centerlines']
    assert math.isclose(sum(river['class_area_m2'].values()),result['statistics']['eligible_nongreen_land_area_m2'],abs_tol=1e-6)
    for mode in ['baseline','clogged']:
        strata=river['depth_by_proximity'][mode]
        assert math.isclose(sum(v['stored_volume_m3'] for v in strata.values()),result['depth_statistics'][mode]['stored_volume_m3'],abs_tol=1e-8)
    with rasterio.open(service.path(result['scenario_id'])/'river_classes.tif') as mask:
        classes=mask.read(1)
        assert set(np.unique(classes)) <= {0,1,2,255}
    # Reusing a scenario filter never changes its full-AOI result or ID.
    z=15;lon=23.267111;lat=42.684845
    x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    all_pixels=np.asarray(Image.open(io.BytesIO(service.tile(result['scenario_id'],'depth_clogged',z,x,y))))
    near=np.asarray(Image.open(io.BytesIO(service.tile(result['scenario_id'],'depth_clogged',z,x,y,river_filter='river_adjacent'))))
    away=np.asarray(Image.open(io.BytesIO(service.tile(result['scenario_id'],'depth_clogged',z,x,y,river_filter='away'))))
    assert np.all((near[:,:,3]==0)|(away[:,:,3]==0))
    assert np.array_equal(np.maximum(near[:,:,3],away[:,:,3]),all_pixels[:,:,3])
    assert service.result(result['scenario_id'])['statistics']==result['statistics']
    with pytest.raises(ValueError,match='river'):service.tile(result['scenario_id'],'depth_clogged',z,x,y,river_filter='invented')


def test_real_depth_increases_monotonically_with_rainfall_and_blockage(real_scenario):
    service,_=real_scenario
    dry=service.create(selection_at(),rainfall_mm=0)
    unblocked=service.create(selection_at(),rainfall_mm=30,blockage_percent=0)
    half=service.create(selection_at(),rainfall_mm=30,blockage_percent=50)
    blocked=service.create(selection_at(),rainfall_mm=30,blockage_percent=100)
    wetter=service.create(selection_at(),rainfall_mm=60,blockage_percent=100)
    arrays=[]
    for result in [dry,unblocked,half,blocked,wetter]:
        with rasterio.open(service.path(result['scenario_id'])/'runoff.tif') as src:
            arrays.append(src.read(5))
    eligible=arrays[0]!=NODATA
    assert np.all(arrays[0][eligible]==0)
    assert all(np.all(second[eligible]>=first[eligible]) for first,second in zip(arrays,arrays[1:]))
    assert blocked['depth_statistics']['clogged']['stored_volume_m3']>=unblocked['depth_statistics']['clogged']['stored_volume_m3']


def test_zero_blockage_and_empty_selection_do_not_invent_effect(real_scenario):
    service,_ = real_scenario
    no_blockage = service.create(selection_at(),blockage_percent=0)
    no_routes = service.create(selection_at(),selected_route_ids=[])
    assert no_blockage['statistics']['additional_potential_unremoved_volume_m3'] == 0
    assert no_routes['statistics']['affected_cell_count'] == 0
    assert no_routes['statistics']['additional_potential_unremoved_volume_m3'] == 0
    assert no_routes['candidate_routes'] and not no_routes['selected_routes']['features']


def test_planned_source_route_remains_nonfunctioning(real_scenario):
    service,_ = real_scenario
    with sqlite3.connect(service.database) as db:
        identity,blob = db.execute("SELECT source_id,geometry FROM features WHERE kind='routes' AND zone='all' AND status='planned' LIMIT 1").fetchone()
    point = from_wkb(blob).interpolate(.5,normalized=True)
    geometry = selection_at(point.x,point.y,200)
    result = service.create(geometry,selected_route_ids=[identity])
    assert result['selected_route_counts'] == {'existing':0,'planned':1,'open':0}
    assert result['selected_routes']['features'][0]['properties']['contributes_blockage'] is False
    assert result['statistics']['affected_cell_count'] == 0
    assert result['statistics']['additional_potential_unremoved_volume_m3'] == 0


def test_selection_and_parameter_guards_are_fail_closed(real_scenario):
    service,_ = real_scenario
    for geometry in [{'type':'Point','coordinates':[23,42]},
                     {'type':'Polygon','coordinates':[[[23,42],[24,43],[23,43],[24,42],[23,42]]]},
                     {'type':'Polygon','coordinates':[[[float('nan'),42],[23,43],[24,42],[float('nan'),42]]]}]:
        with pytest.raises(ValueError): service.create(geometry)
    with pytest.raises(ValueError,match='25 square'): service.create(selection_at(width=6000))
    with pytest.raises(ValueError,match='intersect'): service.create(selection_at(),selected_route_ids=['invented-pipe'])
    with pytest.raises(ValueError,match='finite'): service.create(selection_at(),rainfall_mm=float('nan'))
    with pytest.raises(ValueError,match='Unknown scenario parameter'): service.create(selection_at(),invented_capacity=10)
    with pytest.raises(KeyError): service.result('../result')


def test_deterministic_id_cache_and_source_staleness(real_scenario,monkeypatch):
    service,result = real_scenario
    path = service.path(result['scenario_id'])/'runoff.tif'
    signature = (path.stat().st_size,path.stat().st_mtime_ns)
    again = service.create(selection_at())
    assert result['scenario_id'] == again['scenario_id']
    assert signature == (path.stat().st_size,path.stat().st_mtime_ns)
    assert service.result(result['scenario_id'])['raster_sha256'] == result['raster_sha256']
    source = service.source_state()
    monkeypatch.setattr(service,'source_state',lambda: {**source,'spatial_revision':'changed'})
    with pytest.raises(ScenarioStale,match='snapshot changed'): service.result(result['scenario_id'])


def test_continuous_palette_zero_missing_and_common_scale():
    image = scenario_rgba(np.array([[0,5,10,20,NODATA,np.nan]],dtype='float32'),20)
    assert image.dtype == np.uint8 and image.shape == (1,6,4)
    assert image[0,0,3] == image[0,4,3] == image[0,5,3] == 0
    assert 0 < image[0,1,3] < image[0,2,3] < image[0,3,3]


def test_actual_api_post_result_tile_etag_and_download(real_scenario):
    service,result = real_scenario
    app = FastAPI()
    app.include_router(create_clogging_router(service,'test'))
    client = TestClient(app)
    response = client.post('/api/clogging/scenarios',json={'geometry':selection_at()})
    assert response.status_code == 200
    identity = response.json()['scenario_id']
    response = client.get('/api/clogging/scenarios/'+identity)
    assert response.status_code == 200 and response.json()['revision'] == identity
    assert client.get('/api/clogging/scenarios/'+identity,headers={'If-None-Match':response.headers['etag']}).status_code == 304
    # Genuine selected neighbourhood in XYZ tile; no invented sample raster.
    z=15;lon=23.267111;lat=42.684845
    x=int((lon+180)/360*2**z)
    y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    tile=client.get(f'/api/clogging/scenarios/{identity}/tiles/change/{z}/{x}/{y}.png')
    assert tile.status_code == 200
    image=Image.open(io.BytesIO(tile.content))
    assert image.size==(256,256) and image.mode=='RGBA'
    assert np.asarray(image)[:,:,3].max()>0
    assert client.get(f'/api/clogging/scenarios/{identity}/tiles/change/{z}/{x}/{y}.png',headers={'If-None-Match':tile.headers['etag']}).status_code==304
    assert client.get(f'/api/clogging/scenarios/{identity}/tiles/change/0/1/0.png').status_code==422
    downloaded=client.get(f'/api/clogging/scenarios/{identity}/download',headers={'Range':'bytes=0-15'})
    assert downloaded.status_code==206 and len(downloaded.content)==16
    assert client.post('/api/clogging/scenarios',json={'geometry':selection_at(),'rainfall_mm':-1}).status_code==422
    assert client.get('/api/clogging/scenarios/'+'a'*32).status_code==404
