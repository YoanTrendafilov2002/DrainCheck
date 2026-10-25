"""Failure paths must never silently restore unmasked terrestrial screening."""
import hashlib,json,sys,shutil,math,io
from pathlib import Path
import pytest
import rasterio
import numpy as np
from rasterio.transform import Affine
from pyproj import Transformer
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.pluvial import LocalPluvial,PALETTE,class_indices
from backend.terrain import tile_bounds
from backend.open_water import OpenWaterMask


def with_real_terrain_but_fixture_mask(cache):
    local=LocalPluvial(cache)
    local.path=ROOT/'data/cache/pluvial_5m.tif'
    local.receipt=ROOT/'data/cache/pluvial_provenance.json'
    assert local.source_available
    return local


def test_missing_required_water_mask_fails_before_any_cached_tile_reuse(tmp_path):
    local=with_real_terrain_but_fixture_mask(tmp_path)
    before=local.tiles.stats
    assert not local.available
    assert local.meta()['water_exclusion']['enabled'] is True
    assert local.meta()['water_exclusion']['available'] is False
    with pytest.raises(ValueError,match='unavailable'):local.tile('screening',14,9254,6039,'previous-revision')
    assert local.tiles.stats==before


def test_modified_water_raster_without_new_verified_receipt_is_rejected(tmp_path):
    source=ROOT/'data/cache'
    shutil.copyfile(source/'open_water_mask_5m.tif',tmp_path/'open_water_mask_5m.tif')
    shutil.copyfile(source/'open_water_meta.json',tmp_path/'open_water_meta.json')
    target=tmp_path/'open_water_mask_5m.tif'
    with target.open('r+b') as stream:
        stream.seek(-1,2);value=stream.read(1);stream.seek(-1,2);stream.write(bytes([value[0]^1]))
    local=with_real_terrain_but_fixture_mask(tmp_path)
    assert not local.available
    assert 'checksum' in local.water.error
    with pytest.raises(ValueError,match='unavailable'):local.sample(23.337247642167377,42.690042699335194)


def test_wrong_water_grid_is_not_resampled_or_assumed_land(tmp_path):
    # Deliberately tiny invalid MASK fixture; never supplied as terrain/map data.
    path=tmp_path/'open_water_mask_5m.tif'
    with rasterio.open(path,'w',driver='GTiff',width=1,height=1,count=1,dtype='uint8',crs='EPSG:7801',transform=Affine(5,0,299392,0,-5,4753611)) as dst:
        dst.write(np.ones((1,1),dtype='uint8'),1)
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'open_water_meta.json').write_text(json.dumps({'available':True,'revision':sha[:16],'sha256':sha,'counts':{'water_cells':1}}))
    mask=OpenWaterMask(tmp_path)
    assert not mask.available
    assert 'grid differs' in mask.error


def test_receipt_revision_cannot_stay_stale_after_a_source_change(tmp_path):
    source=ROOT/'data/cache'
    shutil.copyfile(source/'open_water_mask_5m.tif',tmp_path/'open_water_mask_5m.tif')
    meta=json.loads((source/'open_water_meta.json').read_text(encoding='utf-8'));meta['revision']='old-revision'
    (tmp_path/'open_water_meta.json').write_text(json.dumps(meta),encoding='utf-8')
    mask=OpenWaterMask(tmp_path)
    assert not mask.available
    assert 'revision' in mask.error


@pytest.mark.parametrize('name,lon,lat',[
    ('Ariana real island',23.336833150705026,42.68967465294718),
    ('Vasil Levski real pitch',23.3352531692,42.6875642953)])
@pytest.mark.parametrize('mode,score_key',[
    ('depressions','ponding_score'),('concentration','concentration_score'),('screening','score')])
def test_high_zoom_valid_land_is_visible_with_its_actual_class(name,lon,lat,mode,score_key):
    local=LocalPluvial(ROOT/'data/cache');sample=local.sample(lon,lat)
    assert sample['status']=='ok' and sample['water_excluded'] is False
    z=18;x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    west,south,east,north=tile_bounds(z,x,y);mx,my=Transformer.from_crs(4326,3857,always_xy=True).transform(lon,lat)
    col=int((mx-west)/(east-west)*256);row=int((north-my)/(north-south)*256)
    rgba=np.asarray(Image.open(io.BytesIO(local.tile(mode,z,x,y,local.meta()['revision']))))
    assert rgba[row,col,3]>0,'A water-only alpha test must not pass because all land disappeared'
    np.testing.assert_array_equal(rgba[row,col],PALETTE[int(class_indices(sample[score_key]))])
    assert np.count_nonzero(rgba[:,:,3])>0
    if name=='Ariana real island':
        # The same actual tile contains lake AND island, proving spatial separation.
        assert np.count_nonzero(rgba[:,:,3]==0)>0


def test_high_zoom_outside_terrain_remains_transparent_without_water_expansion():
    local=LocalPluvial(ROOT/'data/cache');lon,lat=22.4,42.7;z=18
    x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    assert local.sample(lon,lat)['status']=='nodata'
    rgba=np.asarray(Image.open(io.BytesIO(local.tile('screening',z,x,y,local.meta()['revision']))))
    assert not np.any(rgba[:,:,3])
