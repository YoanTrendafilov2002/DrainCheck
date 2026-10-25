"""Real-data and exclusion checks for the separate categorical review product."""
from pathlib import Path
import hashlib,json,sqlite3
import numpy as np
import pytest,rasterio
from rasterio.features import rasterize
from rasterio.windows import Window,bounds,transform as window_transform
from rasterio.warp import transform_bounds
from shapely import from_wkb,transform as coordinate_transform
from shapely.geometry import shape,mapping,box
from shapely.ops import unary_union
from pyproj import Transformer
from scripts.prepare_review_priority import classify

APP=Path(__file__).resolve().parents[1]
META=APP/'data/cache/review_priority_meta.json'
XY=Transformer.from_crs(4326,7801,always_xy=True)

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
@pytest.fixture(scope='module')
def meta():
    a=load(META);assert a['available'];return a

def test_actual_product_identity_and_source_hashes(meta):
    assert sha(APP/meta['output_file'])==meta['output_sha256']
    from backend.app import pluvial
    assert meta['source_revisions']=={'pluvial':pluvial.meta()['revision'],'screening_exclusions':pluvial.exclusions.meta()['revision'],'terrain':'f42644a668cdc14d',
        'water':'ee06795221a5005e','cadastre':'568d80b32ddb42f2','history':'7fbfbcee6ee933f4','rainfall_context':'88036868558c20ce'}
    for source in meta['source_files'].values():assert sha(APP/source['file'])==source['sha256']
    with rasterio.open(APP/meta['output_file']) as r:
        assert r.shape==(10869,10345) and r.count==1 and r.dtypes==('uint8',)
        assert r.crs.to_epsg()==7801 and list(r.transform)[:6]==[5,0,299392,0,-5,4753611]
        assert r.nodata==255 and r.descriptions==('evidence_based_review_priority',)

def test_full_grid_accounting_and_original_terrain_rules(meta):
    counts=np.zeros(256,dtype='int64')
    with rasterio.open(APP/meta['output_file']) as dst,rasterio.open(APP/'data/cache/pluvial_5m.tif') as src,rasterio.open(APP/'data/cache/open_water_mask_5m.tif') as water,rasterio.open(APP/'data/cache/screening_exclusions_5m.tif') as policy:
        for _,w in dst.block_windows(1):
            out=dst.read(1,window=w);a=src.read([1,5,6,7,8],window=w)
            known=np.isfinite(a[0])&(a[0]!=src.nodata);excluded=known&(policy.read(1,window=w)>0);wet=known&~excluded&(water.read(1,window=w)==1)
            good=known&~wet&~excluded&(a[1]==0)&np.all(np.isfinite(a[2:])&(a[2:]>=0),axis=0)
            assert np.array_equal(out==255,~known)
            assert np.array_equal(out==252,excluded)
            assert np.array_equal(out==253,wet)
            assert np.array_equal(out==254,known&~wet&~excluded&~good)
            assert np.array_equal(out<6,good)
            assert np.all(a[2][out==0]<50)
            assert np.all((a[2][out==1]>=50)&(a[2][out==1]<70))
            assert np.all(a[2][np.isin(out,[2,3])]>=70)
            counts+=np.bincount(out.ravel(),minlength=256)
    assert counts.sum()==10869*10345
    assert set(np.flatnonzero(counts))=={0,1,2,3,4,5,252,253,254,255}
    assert {c['code']:c['cell_count'] for c in meta['classes']}=={int(i):int(counts[i]) for i in np.flatnonzero(counts)}
    assert counts[:6].sum()==meta['counts']['eligible_land_cells']
    assert counts[252]==meta['counts']['screening_policy_excluded_cells']>0
    assert counts[253]==meta['counts']['mapped_water_cells']
    assert counts[254]==meta['counts']['uncertain_cells']
    assert meta['unmasked_review_counts']['eligible_land_cells']==51682623
    assert meta['unmasked_review_counts']['mapped_water_cells']==1519688
    assert meta['verification']['nonexcluded_review_pixels_identical']

def test_actual_historical_union_membership_and_exclusions(meta):
    source=load(APP/'data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson')
    union=unary_union([coordinate_transform(shape(f['geometry']),XY.transform,interleaved=False) for f in source['features']])
    inside=eligible=0
    with rasterio.open(APP/meta['output_file']) as r:
        for _,w in r.block_windows(1):
            if not box(*bounds(w,r.transform)).intersects(union):continue
            out=r.read(1,window=w)
            hist=rasterize([(mapping(union),1)],out_shape=out.shape,transform=window_transform(w,r.transform),all_touched=False,dtype='uint8')==1
            assert np.array_equal(np.isin(out,[4,5]),hist&(out<6))
            inside+=int(hist.sum());eligible+=int((hist&(out<6)).sum())
    assert inside==76343 and 0<eligible<=76020
    assert sum(c['cell_count'] for c in meta['classes'] if c['code'] in [4,5])==eligible

def test_potential_building_overlap_matches_real_geometry_in_independent_windows(meta):
    db=sqlite3.connect(f'file:{(APP/"data/cache/cadastral_buildings.sqlite").as_posix()}?mode=ro',uri=True)
    positions=[(23.33032128151407,42.69564895655974),(23.361694114303877,42.81236256982956)]
    with rasterio.open(APP/meta['output_file']) as dst,rasterio.open(APP/'data/cache/pluvial_5m.tif') as src:
        # Add a real historical/building class5 pixel and a raster-block seam.
        found=None
        for _,w in dst.block_windows(1):
            a=dst.read(1,window=w);idx=np.argwhere(a==5)
            if idx.size:
                rr,cc=idx[len(idx)//2];found=(int(w.col_off+cc),int(w.row_off+rr));break
        assert found is not None
        windows=[]
        for lon,lat in positions:
            row,col=dst.index(*XY.transform(lon,lat));windows.append(Window(col-32,row-32,64,64))
        windows.extend([Window(found[0]-32,found[1]-32,64,64),Window(4608-32,4608-32,64,64)])
        checked=0
        for w in windows:
            out=dst.read(1,window=w);p=src.read(6,window=w);b=bounds(w,dst.transform);ll=transform_bounds(7801,4326,*b,densify_pts=21)
            shapes=[]
            for (wkb,) in db.execute('select f.geometry from features f join feature_bounds r using(fid) where r.maxx>=? and r.minx<=? and r.maxy>=? and r.miny<=?',(ll[0],ll[2],ll[1],ll[3])):
                g=coordinate_transform(from_wkb(wkb),XY.transform,interleaved=False)
                if g.intersects(box(*b)):shapes.append((mapping(g),1))
            footprint=rasterize(shapes,out_shape=out.shape,transform=window_transform(w,dst.transform),all_touched=True,dtype='uint8')==1 if shapes else np.zeros(out.shape,dtype=bool)
            relevant=(out<6)&((p>=70)|np.isin(out,[4,5]))
            assert np.array_equal(np.isin(out,[3,5])[relevant],footprint[relevant])
            checked+=int(np.isin(out,[3,5]).sum())
        assert checked>0
    db.close()

def test_exclusion_precedence_and_historical_override_do_not_change_scores():
    p=np.array([99,99,99,0,70,69.99,0],dtype='float32');saved=p.copy()
    known=np.array([0,1,1,1,1,1,1],dtype=bool)
    water=np.array([0,1,0,0,0,0,0],dtype=bool)
    uncertain=np.array([0,1,1,0,0,0,0],dtype=bool)
    history=np.array([1,1,1,1,0,0,0],dtype=bool)
    footprint=np.array([1,1,1,1,1,1,1],dtype=bool)
    assert classify(p,known,water,uncertain,history,footprint).tolist()==[255,253,254,5,3,1,0]
    np.testing.assert_array_equal(p,saved)

def test_documented_context_and_area_semantics_are_explicit(meta):
    assert 'compatible' in meta['scenario_assumption']
    assert 'all_touched=True' in meta['formula']['building']
    assert 'not exposed building area' in ' '.join(meta['limitations'])
    assert set(meta['context_not_numerical_hazard_inputs'])=={'2025 daily rainfall','green-area labels',
        'sewer route/point density or status','reported clogging or drainage narratives without spatially resolved hydraulic inputs'}
    assert all(c['color_rgba'][3]==0 for c in meta['classes'] if c['code'] in [252,253,255])
