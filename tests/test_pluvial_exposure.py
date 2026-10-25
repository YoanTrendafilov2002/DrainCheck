"""Consequential integration checks against the real source records and raster."""
import csv,json,sys,math
from pathlib import Path
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app import app,pluvial
from scripts.prepare_pluvial_exposure import classes,sample_grid,sample_grid_modes,route_samples,LABELS,MODES
from shapely.geometry import LineString
from pyproj import Geod

client=TestClient(app)

def test_uncertain_and_nodata_are_never_lower_signal():
    values=np.array([0,49.9,50,69.9,70,84.9,85,100,-9999,np.nan,100],dtype='float32')
    flags=np.array([0]*10+[1],dtype='uint8')
    assert classes(values,flags).tolist()==[0,0,1,1,2,2,3,3,5,5,4]

def test_route_quadrature_preserves_geodesic_traversal_length():
    line=LineString([(23.3,42.7),(23.301,42.7002),(23.3,42.7)])
    lon,lat,length=route_samples(line)
    assert len(lon)==len(lat)==len(length) and len(length)>20
    assert length.sum()==pytest.approx(abs(Geod(ellps='WGS84').geometry_length(line)),abs=1e-8)

@pytest.mark.parametrize('mode',list(MODES))
def test_actual_exposure_partitions_all_source_records_and_routes(mode):
    result=client.get('/api/pluvial/exposure',params={'mode':mode})
    assert result.status_code==200
    body=result.json()
    assert body['mode']==mode
    assert sum(c['point_count'] for c in body['by_class'].values())==322025
    assert sum(c['count'] for c in body['categories'])==322025
    assert body['routes']['source_count']==717
    summary=json.loads((ROOT/'data/derived/summary.json').read_text(encoding='utf-8'))
    assert body['routes']['length_m']==pytest.approx(summary['zone_length_m']['all'],abs=.002)
    assert sum(c['route_length_m'] for c in body['by_class'].values())==pytest.approx(body['routes']['length_m'],abs=1e-7)
    counts=[c['point_records_at_or_above'] for c in body['sensitivity']]
    assert counts[0]>=counts[1]>=counts[2]


def test_mode_choice_changes_actual_overlap_without_changing_the_population():
    bodies={mode:client.get('/api/pluvial/exposure',params={'mode':mode}).json() for mode in MODES}
    assert bodies['ponding']['by_class']['Strongest signal']['point_count']!=bodies['combined']['by_class']['Strongest signal']['point_count']
    assert len({body['routes']['length_m'] for body in bodies.values()})==1
    assert len({body['by_class']['Uncertain terrain']['point_count'] for body in bodies.values()})==1
    assert all(body['by_class']['Uncertain terrain']['point_count']<=62 for body in bodies.values())
    assert len({body['by_class']['Excluded open water']['point_count'] for body in bodies.values()})==1
    for mode in MODES:
        terrain=bodies[mode]['terrain_by_mode'][mode]
        assert sum(c['cells'] for c in terrain['classes'])==terrain['terrain_cells']==53682786
        assert sum(c['cells'] for c in terrain['classes'][:4])==terrain['eligible_cells']<53187833
        assert terrain['uncertain_cells']<=494953
        assert terrain['water_excluded_cells']>0
        assert terrain['eligible_cells']+terrain['uncertain_cells']+terrain['no_terrain_data_cells']+terrain['water_excluded_cells']+terrain['screening_policy_excluded_cells']==terrain['terrain_cells']
        assert sum(c['area_km2'] for c in terrain['classes'])==pytest.approx(terrain['terrain_cells']*25/1e6)

def test_sampled_exposure_export_matches_real_base_grid_and_source_rows():
    with (ROOT/'data/raw/sofia_infrastructure_points.csv').open(encoding='utf-8',newline='') as f:raw=list(csv.DictReader(f))
    with (ROOT/'data/derived/infrastructure_terrain_screening.csv').open(encoding='utf-8',newline='') as f:export=list(csv.DictReader(f))
    assert len(raw)==len(export)==322025
    ids=np.linspace(0,len(raw)-1,101,dtype=int)
    with rasterio.open(pluvial.path,OVERVIEW_LEVEL='NONE') as src:
        scores,flags=sample_grid_modes(src,[float(raw[i]['longitude']) for i in ids],[float(raw[i]['latitude']) for i in ids])
    codes={mode:classes(scores[mode],flags[mode]) for mode in MODES}
    for j,i in enumerate(ids):
        assert export[i]['source_record_id']==str(i+1)
        assert export[i]['longitude']==raw[i]['longitude'] and export[i]['latitude']==raw[i]['latitude']
        assert export[i]['terrain_signal_class']==LABELS[codes['combined'][j]]
        if codes['combined'][j]<4:assert float(export[i]['terrain_score_0_100'])==float(scores['combined'][j])
        else:assert export[i]['terrain_score_0_100']==''
        for mode in MODES:
            assert export[i][mode+'_signal_class']==LABELS[codes[mode][j]]
            if codes[mode][j]<4:assert float(export[i][mode+'_score_0_100'])==float(scores[mode][j])
            else:assert export[i][mode+'_score_0_100']==''


def test_route_csv_retains_all717_routes_and_length_for_every_mode():
    exposure=json.loads((ROOT/'data/cache/pluvial_exposure.json').read_text(encoding='utf-8'))
    with (ROOT/'data/derived/sewer_route_terrain_screening.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
    for mode in MODES:
        selected=[r for r in rows if r['screening_mode']==mode]
        assert len({r['source_route_id'] for r in selected})==717
        assert len(selected)==717*len(LABELS)
        assert sum(float(r['approximate_length_m']) for r in selected)==pytest.approx(exposure['modes'][mode]['routes']['length_m'],abs=1e-7)
        for status,by_class in exposure['modes'][mode]['routes']['by_status'].items():
            for label,length in by_class.items():
                actual=sum(float(r['approximate_length_m']) for r in selected if r['source_status']==status and r['terrain_signal_class']==label)
                assert actual==pytest.approx(length,abs=1e-7)


def test_routing_limitation_receipt_records_real_grid_and_caveats():
    receipt=json.loads((ROOT/'test-artifacts/pluvial_routing_diagnostic.json').read_text(encoding='utf-8'))
    assert receipt['pluvial_revision']==pluvial.meta()['terrain_revision']
    assert receipt['window']['bounds_epsg7801']==[320277,4730161,322837,4732721]
    assert receipt['valid_cells']==261627
    assert receipt['high85_concentration_cells']<=receipt['high85_cells']
    assert 'not' in receipt['conclusion'].lower()
    assert len(receipt['unknowns'])>=3
    assert (ROOT/'docs/PLUVIAL_ROUTING_LIMITATIONS.md').is_file()

def test_pluvial_endpoints_reject_stale_revision_and_bad_mode():
    assert client.get('/api/pluvial/combined/14/9252/6038.png?v=stale').status_code==409
    rev=client.get('/api/meta').json()['revision']
    assert client.get('/api/pluvial/fake/14/1/1.png',params={'v':rev}).status_code==422
    assert client.get('/api/pluvial/sample?lon=999&lat=42').status_code==422
    assert client.get('/api/pluvial/sample?lon=22&lat=42').json()['status']=='nodata'
    assert client.get('/api/pluvial/exposure?mode=fake').status_code==422

def test_evidence_is_primary_linked_and_does_not_claim_calibration():
    data=client.get('/api/pluvial/meta').json()
    assert data['available'] is True
    assert len(data['evidence'])>=6 and all(s['url'].startswith('https://') for s in data['evidence'])
    assert 'unvalidated' in data['method']['description'].lower()
    assert '20 m' in data['method']['formula']
