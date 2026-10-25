"""Cache correctness; unchanged native tiles and land pixels after water exclusion."""
import hashlib,json,sys,threading,time,subprocess,io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import reproject
from rasterio.transform import Affine
from rasterio.enums import Resampling
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.tile_cache import ByteTileCache,file_signature,read_json_cached
from backend.terrain import LocalTerrain,tile_bounds,png
from backend.pluvial import LocalPluvial,LAYERS,NODATA,colour_rgba

BASELINE=json.loads((ROOT/'test-artifacts/raster_performance_baseline.json').read_text(encoding='utf-8'))

def unmasked_reference(pluvial,mode,z,x,y):
    """Original rendering algorithm, checked against pre-water baseline hashes."""
    west,south,east,north=tile_bounds(z,x,y);spacing=(east-west)/256
    transform=Affine(spacing,0,west,0,-spacing,north)
    values=np.full((256,256),np.nan,dtype='float32');terrain=values.copy();water=np.full((256,256),255,dtype='uint8')
    with rasterio.Env(PROJ_NETWORK='OFF',GDAL_CACHEMAX=64000000),rasterio.open(pluvial.path) as src,rasterio.open(pluvial.water.path) as mask:
        for band,dst in [(LAYERS[mode],values),(1,terrain)]:
            reproject(rasterio.band(src,band),dst,src_transform=src.transform,src_crs=src.crs,src_nodata=NODATA,
                dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=np.nan,resampling=Resampling.nearest,num_threads=1,warp_mem_limit=64)
        reproject(rasterio.band(mask,1),water,src_transform=mask.transform,src_crs=mask.crs,
            src_nodata=255,dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=255,resampling=Resampling.nearest,num_threads=1,warp_mem_limit=64)
    rgba=colour_rgba(values,mode);rgba[np.isfinite(terrain)&~np.isfinite(values)]=[120,127,136,155]
    return rgba,water


def test_persistent_bytes_survive_new_cache_instance(tmp_path):
    one=ByteTileCache(tmp_path);assert one.get_or_render(['mvt','v1'],lambda:b'actual-tile-bytes')==b'actual-tile-bytes'
    two=ByteTileCache(tmp_path)
    def forbidden():raise AssertionError('Existing verified disk entry must avoid a second render')
    assert two.get_or_render(['mvt','v1'],forbidden)==b'actual-tile-bytes'
    assert two.stats['disk_hits']==1 and two.stats['renders']==0


def test_persistent_bytes_survive_a_fresh_python_process(tmp_path):
    ByteTileCache(tmp_path).get_or_render(['cross-process','v1'],lambda:b'persisted-real-bytes')
    script="from backend.tile_cache import ByteTileCache; import sys; c=ByteTileCache(sys.argv[1]); value=c.get_or_render(['cross-process','v1'],lambda:(_ for _ in ()).throw(AssertionError('must not render'))); assert value==b'persisted-real-bytes'; assert c.stats['disk_hits']==1 and c.stats['renders']==0"
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_identical_concurrent_requests_render_once(tmp_path):
    cache=ByteTileCache(tmp_path);entered=threading.Event();release=threading.Event();calls=[]
    def render():
        calls.append(1);entered.set();assert release.wait(3);return b'one-render'
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs=[pool.submit(cache.get_or_render,['same','tile'],render) for _ in range(8)]
        assert entered.wait(3)
        # Allow workers to reach the shared in-flight request before releasing it.
        deadline=time.monotonic()+2
        while cache.stats['coalesced']<7 and time.monotonic()<deadline:time.sleep(.005)
        release.set();assert all(j.result()==b'one-render' for j in jobs)
    assert len(calls)==1 and cache.stats['coalesced']==7 and cache.stats['inflight']==0


def test_failed_render_is_not_cached_or_left_inflight(tmp_path):
    cache=ByteTileCache(tmp_path)
    def fail():raise ValueError('Real data read failed')
    with pytest.raises(ValueError,match='Real data'):cache.get_or_render('tile',fail)
    assert cache.stats['inflight']==0
    assert cache.get_or_render('tile',lambda:b'retry-real-data')==b'retry-real-data'
    assert cache.stats['renders']==2


def test_corrupt_persistent_payload_is_regenerated(tmp_path):
    cache=ByteTileCache(tmp_path);cache.get_or_render('tile',lambda:b'correct-bytes')
    entry=next(tmp_path.glob('*.tile'));content=bytearray(entry.read_bytes());content[-1]^=1;entry.write_bytes(content)
    new=ByteTileCache(tmp_path)
    assert new.get_or_render('tile',lambda:b'recomputed-bytes')==b'recomputed-bytes'
    assert new.stats['corrupt']==1 and new.stats['renders']==1


def test_revision_and_actual_file_changes_invalidate_reuse(tmp_path):
    source=tmp_path/'source';source.write_text('original')
    cache=ByteTileCache(tmp_path/'cache');first=file_signature(source)
    assert cache.get_or_render(['rev1',first],lambda:b'old')==b'old'
    assert cache.get_or_render(['rev2',first],lambda:b'revision')==b'revision'
    source.write_text('changed real input');second=file_signature(source)
    assert first!=second
    assert cache.get_or_render(['rev1',second],lambda:b'changed')==b'changed'
    assert cache.stats['renders']==3


def test_unwritable_cache_location_still_returns_real_render(tmp_path):
    obstacle=tmp_path/'not-a-directory';obstacle.write_text('keep')
    cache=ByteTileCache(obstacle)
    assert not cache.disk_enabled
    assert cache.get_or_render('tile',lambda:b'uncached-real-render')==b'uncached-real-render'
    assert obstacle.read_text()=='keep'


def test_disk_and_memory_budgets_remain_bounded(tmp_path):
    cache=ByteTileCache(tmp_path,max_bytes=2000,max_files=5,memory_bytes=150)
    for i in range(30):cache.get_or_render(i,lambda:b'x'*100)
    entries=list(tmp_path.glob('*.tile'))
    assert len(entries)<=5 and sum(p.stat().st_size for p in entries)<=2000
    assert cache.stats['memory_entries']<=1
    assert not list(tmp_path.glob('*.tmp'))


def test_cached_json_tracks_changes_and_does_not_share_mutable_values(tmp_path):
    path=tmp_path/'metadata.json';path.write_text('{"values":[1]}')
    first=read_json_cached(path);first['values'][0]=99
    assert read_json_cached(path)=={'values':[1]}
    path.write_text('{"values":[2,3]}')
    assert read_json_cached(path)=={'values':[2,3]}


@pytest.mark.parametrize('record',BASELINE['records'],ids=lambda r:f"{r['location']}-{r['layer']}-z{r['z']}")
def test_native_tiles_exact_and_pluvial_changes_only_at_mapped_water(record,tmp_path):
    native=ROOT.parent/'sofia_dtm_2024_1m_gee.tif'
    terrain=LocalTerrain(native,ROOT/'data/cache');pluvial=LocalPluvial(ROOT/'data/cache')
    shared=ByteTileCache(tmp_path);terrain.tiles=shared;pluvial.tiles=shared
    z,x,y=(record[k] for k in ['z','x','y'])
    revision=(ROOT/'data/cache/revision.txt').read_text().strip()
    def call():
        if record['layer']=='terrain':return terrain.colour_tile(z,x,y,'whole',revision)
        if record['layer']=='hillshade':return terrain.shade_tile(z,x,y,revision)
        return pluvial.tile('depressions' if record['layer']=='ponding' else 'concentration',z,x,y,pluvial.meta()['revision'])
    actual=call()
    if record['layer']=='terrain':
        # Historical hashes used the locally estimated curve. The complete
        # supplement restores the genuine EE curve (tested against its original
        # JS module in reference_scale.test.mjs). Keep the old hashes intact
        # and prove the same real pixels still render identically with that
        # archived style; only the display curve is intentionally different.
        previous=ROOT/'data/reference/previous_whole_scales/whole-1334de799254274d.json'
        if previous.is_file():
            legacy=terrain._render_colour(z,x,y,json.loads(previous.read_text(encoding='utf-8')))
            assert hashlib.sha256(legacy).hexdigest()==record['sha256']
            np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(actual)))[...,3],
                                          np.asarray(Image.open(io.BytesIO(legacy)))[...,3])
        else:
            assert hashlib.sha256(actual).hexdigest()==record['sha256']
    elif record['layer']=='hillshade':
        assert hashlib.sha256(actual).hexdigest()==record['sha256']
    else:
        mode='depressions' if record['layer']=='ponding' else 'concentration'
        reference,water=unmasked_reference(pluvial,mode,z,x,y)
        assert hashlib.sha256(png(reference)).hexdigest()==record['sha256']
        rendered=np.asarray(Image.open(io.BytesIO(actual)))
        np.testing.assert_array_equal(rendered[water!=1],reference[water!=1])
        np.testing.assert_array_equal(rendered[:,:,:3],reference[:,:,:3])
        assert not np.any(rendered[water==1,3])
    # New memory-cache instance forces the persistent-cache read path.
    terrain.tiles=pluvial.tiles=ByteTileCache(tmp_path)
    assert call()==actual
    assert terrain.tiles.stats['disk_hits']==1 and terrain.tiles.stats['renders']==0


def test_native_and_terrain_factor_samples_unchanged():
    lon,lat=23.3352531692,42.6875642953
    terrain=LocalTerrain(ROOT.parent/'sofia_dtm_2024_1m_gee.tif',ROOT/'data/cache')
    pluvial=LocalPluvial(ROOT/'data/cache')
    assert terrain.sample(lon,lat)==BASELINE['samples']['native']
    result=pluvial.sample(lon,lat)
    for key,value in BASELINE['samples']['pluvial'].items():assert result[key]==value
    assert result['water_excluded'] is False
