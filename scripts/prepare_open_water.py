"""Acquire/preserve real OSM water polygons and rasterize a conservative 5 m mask.

Default reuses the preserved snapshot. --refresh acquires a new dated snapshot;
original responses/queries are never overwritten. No source/pluvial pixels change.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window
import shapely
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, mapping
from shapely.ops import polygonize_full

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT/'data/reference'
CACHE = ROOT/'data/cache'
METHOD = 'osm-open-water-polygons-centres-v1'
SHAPE = (10869, 10345)
GRID = Affine(5, 0, 299392, 0, -5, 4753611)
SOURCE_URLS = ['https://www.openstreetmap.org/copyright',
               'https://wiki.openstreetmap.org/wiki/Tag:natural%3Dwater',
               'https://wiki.openstreetmap.org/wiki/Tag:water%3Driver',
               'https://wiki.openstreetmap.org/wiki/Relation:multipolygon',
               'https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL']
PROJECT = Transformer.from_crs(4326, 7801, always_xy=True)
UNPROJECT = Transformer.from_crs(7801, 4326, always_xy=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''): h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding='utf-8')


def acquire(source, refresh=False):
    REFERENCE.mkdir(parents=True, exist_ok=True)
    pointer = REFERENCE/'osm_open_water_acquisition.json'
    if pointer.exists() and not refresh:
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        raw = REFERENCE/receipt['raw_file']
        if not raw.is_file(): raise FileNotFoundError(raw)
        baseline = receipt.get('raw_sha256')
        # Preserve and validate a legacy first-acquisition receipt against the
        # installed mask's source receipt before adding missing digest fields.
        installed = CACHE/'open_water_meta.json'
        if not baseline and installed.is_file():
            previous = json.loads(installed.read_text(encoding='utf-8')).get('source',{})
            if previous.get('raw_file') == receipt['raw_file']:
                baseline = previous.get('raw_sha256')
        actual = digest(raw)
        if baseline and actual != baseline:
            raise ValueError('Preserved OSM source hash changed')
        receipt['raw_sha256'] = actual
        receipt['query_sha256'] = digest(REFERENCE/receipt['query_file'])
        manifest = REFERENCE/(raw.stem+'_acquisition.json')
        if not manifest.exists(): save_json(manifest,receipt)
        save_json(pointer,receipt)
        return receipt
    with rasterio.open(source) as src:
        west,south,east,north = transform_bounds(src.crs, 'EPSG:4326', *src.bounds, densify_pts=41)
    bbox = [west-.01,south-.01,east+.01,north+.01]
    w,s,e,n = bbox
    query = f'''[out:json][timeout:180];
(way["natural"="water"]({s},{w},{n},{e});
relation["natural"="water"]({s},{w},{n},{e});
way["waterway"="riverbank"]({s},{w},{n},{e});
relation["waterway"="riverbank"]({s},{w},{n},{e}););
out meta geom;'''
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    querypath = REFERENCE/('osm_open_water_'+stamp+'.overpass')
    querypath.write_text(query, encoding='utf-8')
    attempts = []
    for endpoint in ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']:
        print(json.dumps({'stage':'download','endpoint':endpoint}), flush=True)
        try:
            request = urllib.request.Request(endpoint,
                data=urllib.parse.urlencode({'data':query}).encode(),
                headers={'User-Agent':'SofiaTerrainExplorer/1.2 local open-water research','Accept':'application/json'})
            with urllib.request.urlopen(request, timeout=210) as response: raw = response.read()
            doc = json.loads(raw)
            if doc.get('remark'): raise ValueError(doc['remark'])
            if not doc.get('elements'): raise ValueError('Empty OSM response; do not install an empty substitute')
            rawpath = REFERENCE/('osm_open_water_'+stamp+'.json')
            rawpath.write_bytes(raw)
            receipt = {'endpoint':endpoint, 'download_utc':datetime.now(timezone.utc).isoformat(),
                       'raw_file':rawpath.name,'query_file':querypath.name,'bbox':bbox,
                       'elements':len(doc['elements']), 'osm_base_timestamp':doc.get('osm3s',{}).get('timestamp_osm_base'),
                       'raw_sha256':digest(rawpath),'query_sha256':digest(querypath),'attempts':attempts}
            save_json(REFERENCE/('osm_open_water_'+stamp+'_acquisition.json'), receipt)
            save_json(pointer, receipt)
            return receipt
        except Exception as error:
            attempts.append({'endpoint':endpoint,'error':str(error)})
    raise RuntimeError('No complete OSM response acquired: '+json.dumps(attempts))


def exclusion_reason(tags):
    false = {'no','false','0'}
    for key in ('intermittent','seasonal','dry','disused','abandoned','demolished','removed','razed','construction','proposed'):
        value = str(tags.get(key,'')).strip().lower()
        if value and value not in false: return key+'='+value
    for key,value in tags.items():
        if ':' in key and key.split(':')[0] in ('disused','abandoned','demolished','removed','razed','proposed','construction'):
            if value: return 'lifecycle:'+key
    if str(tags.get('indoor','no')).lower() not in false: return 'indoor'
    if str(tags.get('covered','no')).lower() not in false: return 'covered'
    if str(tags.get('tunnel','no')).lower() not in false: return 'tunnel'
    if tags.get('fountain') == 'splash_pad' or tags.get('playground') == 'splash_pad': return 'splash_pad_not_standing_water'
    return None


def polygon_parts(geometry):
    if geometry.is_empty: return []
    if geometry.geom_type == 'Polygon': return [geometry]
    if geometry.geom_type in ('MultiPolygon','GeometryCollection'):
        return [part for g in geometry.geoms for part in polygon_parts(g)]
    return []


def complete_rings(lines):
    if not lines: return []
    polygons, cuts, dangles, invalid = polygonize_full(MultiLineString(lines))
    if any(g.length > 1e-12 for g in (cuts,dangles,invalid)):
        raise ValueError('Incomplete or invalid ring linework; reject instead of filling missing boundaries')
    # Polygonize may make nested faces. Retaining their exterior rings lets the
    # declared outer/inner roles determine holes, rather than face ordering.
    return [Polygon(g.exterior) for g in polygons.geoms]


def relation_geometry(element):
    if element.get('tags',{}).get('type') != 'multipolygon':
        raise ValueError('Water relation is not type=multipolygon')
    lines = {'outer':[],'inner':[]}
    for member in element.get('members',[]):
        if member['type'] != 'way':
            if member['type'] == 'node': continue
            raise ValueError('Nested relation member unsupported; reject instead of inventing boundaries')
        role = member.get('role','')
        if role not in lines: raise ValueError('Unspecified/unsupported way role:'+role)
        geometry = member.get('geometry',[])
        if len(geometry)<2 or any('lon' not in p or 'lat' not in p for p in geometry):
            raise ValueError('Missing relation member geometry')
        lines[role].append([(p['lon'],p['lat']) for p in geometry])
    outer = complete_rings(lines['outer']); inner = complete_rings(lines['inner'])
    if not outer: raise ValueError('No complete outer rings')
    assigned = set(); parts = []
    for shell in outer:
        holes = []
        for i,hole in enumerate(inner):
            if shell.area > hole.area and shell.covers(hole):
                holes.append(hole); assigned.add(i)
        parts.append(shell.difference(shapely.union_all(holes)) if holes else shell)
    if len(assigned) != len(inner): raise ValueError('Inner ring has no enclosing outer ring')
    return shapely.union_all(parts)


def prepare_polygons(raw):
    accepted=[]; rejected=[]; repaired=[]
    relations=[e for e in raw['elements'] if e['type']=='relation']
    # Never re-add a separately returned member way as a filled water polygon:
    # that would erase relation holes or bypass a seasonal relation exclusion.
    member_ids={m['ref'] for e in relations for m in e.get('members',[]) if m['type']=='way'}
    for e in raw['elements']:
        sid=e['type']+'/'+str(e['id']);tags=e.get('tags',{})
        reason=exclusion_reason(tags)
        if e['type']=='way' and e['id'] in member_ids: reason='member_of_water_relation'
        if reason:
            rejected.append({'osm_id':sid,'reason':reason,'tags':tags}); continue
        try:
            if e['type']=='relation': geometry=relation_geometry(e)
            elif e['type']=='way':
                coords=[(p['lon'],p['lat']) for p in e.get('geometry',[])]
                if len(coords)<4 or coords[0]!=coords[-1]: raise ValueError('Not a closed polygon way')
                geometry=Polygon(coords)
            else: raise ValueError('Point features do not define water footprints')
            if not geometry.is_valid:
                geometry=shapely.make_valid(geometry);repaired.append(sid)
            parts=polygon_parts(geometry)
            if not parts: raise ValueError('No polygon area remains')
            geometry=shapely.union_all(parts)
            if geometry.is_empty or not geometry.is_valid: raise ValueError('No valid polygon result')
            accepted.append((e,geometry))
        except Exception as error:
            rejected.append({'osm_id':sid,'reason':'geometry:'+str(error),'tags':tags})
    return accepted,rejected,repaired


def control_point(mask, geometry, name, osm_id=None, expected=1):
    projected=shapely.transform(geometry,PROJECT.transform,interleaved=False)
    minx,miny,maxx,maxy=projected.bounds
    c0=max(0,int((minx-GRID.c)//5));c1=min(SHAPE[1],int((maxx-GRID.c)//5)+2)
    r0=max(0,int((GRID.f-maxy)//5));r1=min(SHAPE[0],int((GRID.f-miny)//5)+2)
    found=None
    for row,col in zip(*np.nonzero(mask[r0:r1,c0:c1]==expected)):
        row+=r0;col+=c0;x,y=GRID*(col+.5,row+.5)
        if projected.covers(Point(x,y)):
            found=(row,col,x,y);break
    if found is None: return None
    row,col,x,y=found;lon,lat=UNPROJECT.transform(x,y)
    return {'name':name,'osm_id':osm_id,'longitude':lon,'latitude':lat,'row':int(row),'column':int(col),
            'mask_value':int(mask[row,col]),'expected':expected,'point_is_actual_pixel_center_inside_source_polygon':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--source',type=Path,default=CACHE/'pluvial_5m.tif')
    args=parser.parse_args();started=time.monotonic()
    with rasterio.open(args.source) as src:
        if src.crs.to_epsg()!=7801 or src.shape!=SHAPE or src.transform!=GRID or src.nodata!=-9999:
            raise ValueError('Verified Sofia5m terrain grid required')
    acquisition=acquire(args.source,args.refresh)
    rawpath=REFERENCE/acquisition['raw_file'];raw_hash=digest(rawpath)
    raw=json.loads(rawpath.read_text(encoding='utf-8'))
    if raw.get('remark'): raise ValueError('Incomplete Overpass response:'+raw['remark'])
    accepted,rejected,repaired=prepare_polygons(raw)
    if not accepted: raise ValueError('No real accepted water polygons; do not substitute an empty mask')
    features=[];projected=[]
    gridbox=box(GRID.c,GRID.f-SHAPE[0]*5,GRID.c+SHAPE[1]*5,GRID.f)
    for e,g in accepted:
        features.append({'type':'Feature','id':e['type']+'/'+str(e['id']),
                         'properties':{'osm_type':e['type'],'osm_id':e['id'],'osm_version':e.get('version'),
                                       'osm_timestamp':e.get('timestamp'),'tags':e.get('tags',{}),
                                       'source_url':'https://www.openstreetmap.org/'+e['type']+'/'+str(e['id'])},
                         'geometry':mapping(g)})
        p=shapely.transform(g,PROJECT.transform,interleaved=False).intersection(gridbox)
        if not p.is_empty: projected.append(p)
    geojson=REFERENCE/'open_water_polygons.geojson'
    save_json(geojson,{'type':'FeatureCollection','name':'Qualifying OSM mapped water polygons',
                       'attribution':'© OpenStreetMap contributors; ODbL1.0',
                       'source_snapshot':acquisition['raw_file'],'features':features})
    save_json(REFERENCE/'open_water_geometry_review.json',{'accepted_features':len(accepted),'repaired_source_ids':repaired,
                                                         'rejected':rejected,'rejection_counts':dict(Counter(r['reason'] for r in rejected))})
    print(json.dumps({'stage':'rasterize','accepted':len(accepted),'rejected':len(rejected)}),flush=True)
    mask=rasterize([(g,1) for g in projected],out_shape=SHAPE,transform=GRID,fill=0,all_touched=False,dtype='uint8')
    outside_removed=0
    # No water is asserted outside the actual valid municipal terrain footprint.
    with rasterio.Env(GDAL_CACHEMAX=64000000),rasterio.open(args.source,OVERVIEW_LEVEL='NONE') as src:
        for row in range(0,SHAPE[0],512):
            for col in range(0,SHAPE[1],512):
                target=mask[row:row+512,col:col+512]
                if not np.any(target): continue
                terrain=src.read(1,window=Window(col,row,target.shape[1],target.shape[0]))
                invalid=~np.isfinite(terrain)|(terrain==src.nodata)
                outside_removed+=int(np.count_nonzero(target[invalid]));target[invalid]=0
    water=int(np.count_nonzero(mask));total=int(mask.size)
    if water==0: raise ValueError('No water pixel centres within real terrain coverage')
    controls=[]
    named=[('relation/2905862','Ariana lake water'),('relation/11943054','Pancharevo lake water'),('way/23149833','Lily lake water')]
    lookup={e['type']+'/'+str(e['id']):(e,g) for e,g in accepted}
    for sid,name in named:
        if sid in lookup:
            test=control_point(mask,lookup[sid][1],name,sid)
            if test: controls.append(test)
    river_candidates=[(e,g) for e,g in accepted if e.get('tags',{}).get('water')=='river']
    stadium=shapely.transform(Point(23.3352531692,42.6875642953),PROJECT.transform,interleaved=False)
    river_candidates.sort(key=lambda pair:shapely.transform(pair[1],PROJECT.transform,interleaved=False).distance(stadium))
    for e,g in river_candidates:
        test=control_point(mask,g,'Mapped river footprint; OSM water=river',e['type']+'/'+str(e['id']))
        if test: controls.append(test);break
    if 'relation/2905862' in lookup:
        for part in polygon_parts(lookup['relation/2905862'][1]):
            for ring in part.interiors:
                test=control_point(mask,Polygon(ring),'Ariana island hole is not masked','relation/2905862',0)
                if test:controls.append(test);break
    for name,lon,lat,expected in [('VasilLevski playing field remains unmasked',23.3352531692,42.6875642953,0)]:
        x,y=PROJECT.transform(lon,lat);col=int((x-GRID.c)//5);row=int((GRID.f-y)//5)
        controls.append({'name':name,'longitude':lon,'latitude':lat,'row':row,'column':col,'mask_value':int(mask[row,col]),'expected':expected})
    excluded_central=[r for r in rejected if r['osm_id'] in ['way/1341771831','way/1234109017']]
    if any(t['mask_value']!=t['expected'] for t in controls): raise AssertionError('Real water/land control failed')
    if not any(t['name'].startswith('Mapped river') for t in controls): raise AssertionError('No accepted river control found')
    CACHE.mkdir(parents=True,exist_ok=True)
    output=CACHE/'open_water_mask_5m.tif';pending=CACHE/'open_water_mask_5m.pending.tif'
    with rasterio.open(pending,'w',driver='GTiff',height=SHAPE[0],width=SHAPE[1],count=1,dtype='uint8',crs='EPSG:7801',
                       transform=GRID,nodata=None,tiled=True,blockxsize=512,blockysize=512,compress='DEFLATE',predictor=2) as dst:
        dst.write(mask,1);dst.set_band_description(1,'mapped_open_water_exclusion')
        dst.update_tags(METHOD=METHOD,SOURCE='© OpenStreetMap contributors',LICENSE='ODbL1.0',
                        OSM_BASE_TIMESTAMP=acquisition.get('osm_base_timestamp',''),RAW_SHA256=raw_hash,
                        VALUES='0=not mapped qualifying water or outside terrain;1=mapped qualifying water',
                        RASTERIZATION='pixel centres; all_touched=False; no width buffers')
        dst.build_overviews([2,4,8,16,32],Resampling.nearest)
    with rasterio.open(pending,OVERVIEW_LEVEL='NONE') as check:
        if check.shape!=SHAPE or check.transform!=GRID or check.crs.to_epsg()!=7801 or check.nodata is not None or check.dtypes!=('uint8',):
            raise AssertionError('Output grid/type changed')
        if not np.array_equal(check.read(1),mask): raise AssertionError('Saved raster values differ')
    pending.replace(output)
    if digest(rawpath)!=raw_hash: raise AssertionError('Original OSM response changed')
    output_hash=digest(output)
    source={'provider':'OpenStreetMap contributors via Overpass API','url':'https://www.openstreetmap.org',
            'license':'ODbL1.0','license_url':'https://www.openstreetmap.org/copyright',
            'attribution':'© OpenStreetMap contributors','download_utc':acquisition['download_utc'],
            'osm_base_timestamp':acquisition.get('osm_base_timestamp'),'endpoint':acquisition['endpoint'],
            'raw_file':acquisition['raw_file'],'raw_sha256':raw_hash,'query_file':acquisition['query_file'],
            'query_sha256':digest(REFERENCE/acquisition['query_file']),'geojson_file':str(geojson.relative_to(ROOT)),
            'geojson_sha256':digest(geojson)}
    receipt={'available':True,'enabled':True,'method':METHOD,'revision':output_hash[:16],'sha256':output_hash,
             'file':'data/cache/open_water_mask_5m.tif','source':source,'source_urls':SOURCE_URLS,
             'retrieved':acquisition['download_utc'],'coverage_bbox':acquisition['bbox'],
             'grid':{'crs':'EPSG:7801','shape':list(SHAPE),'transform':list(GRID)[:6],'dtype':'uint8','nodata':None,
                     'values':{'0':'not mapped qualifying water; also outside valid terrain','1':'mapped qualifying water exclusion'}},
             'counts':{'water_cells':water,'water_area_km2':water*25/1e6,'accepted_source_polygons':len(accepted),
                       'accepted_river_polygons':len(river_candidates),'rejected_source_objects':len(rejected),
                       'water_pixels_outside_valid_terrain_removed':outside_removed},
             'water_cells':water,'water_area_km2':water*25/1e6,'pixel_class_counts':{'0':total-water,'1':water},
             'policy':'Actual natural=water/legacy riverbank polygon interiors only; seasonal/intermittent/dry/disused/indoor/covered/splash-pad features excluded. Multipolygon holes preserved; no waterway-line buffers. Pixel-centre5m mask; outside valid terrain0.',
             'limitations':['OSM is community mapping, not a current surveyed water or flood boundary; missing/untagged narrow rivers remain unmasked.',
                            '0 means no qualifying mapped water, not verified land or absence of flood risk. No riverbank or floodplain safety exclusion is inferred.',
                            'Unmarked seasonality, source misclassification, bridge decks and changing water levels may affect mapped footprints.',
                            'Central Perlovska/canal polygons by VasilLevski are tagged intermittent=yes and deliberately remain unexcluded under this conservative rule.',
                            'At5m pixel-centre resolution narrow water slivers may contain no pixel centres. No arbitrary widening is applied.'],
             'known_water_examples':controls,'excluded_central_water_objects':excluded_central,
             'geometry_review':'data/reference/open_water_geometry_review.json',
             'verification':{'exact_grid_type_nodata_and_all_pixels_checked':True,'real_control_points_passed':True,
                             'original_osm_sha256_unchanged':True,'pluvial_source_opened_read_only':True,
                             'elapsed_seconds':round(time.monotonic()-started,2)}}
    save_json(CACHE/'open_water_meta.json',receipt)
    print(json.dumps({'stage':'complete','revision':receipt['revision'],'water_cells':water,'area_km2':water*25/1e6,
                      'controls':controls,'rejections':dict(Counter(r['reason'] for r in rejected))}),flush=True)


if __name__=='__main__': main()
