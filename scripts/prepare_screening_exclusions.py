"""Prepare requested mapped-channel/stadium suppression without changing terrain.

Uses mapped channel polygons and the complete mapped open-waterway network.
Line-only channels occupy intersecting analysis cells; explicit source widths
also supply channel footprints. No floodplain or river-proximity buffer is used.
Reuses preserved snapshots by default; --refresh acquires new dated sources.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import re
import time
import urllib.parse
import urllib.request

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.windows import Window
import shapely
from shapely.geometry import LineString, Polygon, box, mapping

from prepare_open_water import (ROOT, REFERENCE, CACHE, SHAPE, GRID, PROJECT,
                                digest, save_json, polygon_parts,
                                relation_geometry, control_point)
from channel_grid import burn_centerline_cells
from channel_terrain import expand_terrain_connected_channels

METHOD = 'user-requested-terrain-aligned-open-channel-suppression-v3'
WATERWAYS = ('river', 'stream', 'canal', 'drain', 'ditch')
CHANNEL_SEARCH_M = 20.0


def acquire_waterways(bbox, refresh=False):
    pointer = REFERENCE/'screening_exclusions_waterways_acquisition.json'
    if pointer.exists() and not refresh:
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        for kind in ('raw', 'query'):
            if digest(REFERENCE/receipt[kind+'_file']) != receipt[kind+'_sha256']:
                raise ValueError('Preserved waterway '+kind+' checksum changed')
        return receipt
    west, south, east, north = bbox
    extent = f'({south},{west},{north},{east})'
    query = ('[out:json][timeout:180];('
             f'way["waterway"~"^(river|stream|canal|drain|ditch)$"]{extent};'
             f'way["waterway"="riverbank"]{extent};'
             f'relation["waterway"="riverbank"]{extent};);out meta geom;')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    querypath = REFERENCE/f'screening_exclusions_waterways_{stamp}.overpass'
    querypath.write_text(query, encoding='utf-8')
    attempts = []
    for endpoint in ['https://overpass-api.de/api/interpreter',
                     'https://overpass.private.coffee/api/interpreter']:
        try:
            print(json.dumps({'stage':'waterway_download', 'endpoint':endpoint}), flush=True)
            request = urllib.request.Request(endpoint+'?'+urllib.parse.urlencode({'data':query}),
                headers={'User-Agent':'DrainCheck mapped open-channel preparation',
                         'Accept':'application/json'})
            with urllib.request.urlopen(request, timeout=210) as response:
                body = response.read()
            doc = json.loads(body)
            if doc.get('remark') or not doc.get('elements'):
                raise ValueError(doc.get('remark', 'Empty waterway source'))
            rawpath = REFERENCE/f'screening_exclusions_waterways_{stamp}.json'
            rawpath.write_bytes(body)
            receipt = {'endpoint':endpoint, 'download_utc':datetime.now(timezone.utc).isoformat(),
                       'raw_file':rawpath.name, 'raw_sha256':digest(rawpath),
                       'query_file':querypath.name, 'query_sha256':digest(querypath),
                       'bbox':bbox, 'elements':len(doc['elements']),
                       'osm_base_timestamp':doc.get('osm3s',{}).get('timestamp_osm_base'),
                       'attempts':attempts}
            save_json(REFERENCE/f'screening_exclusions_waterways_{stamp}_acquisition.json', receipt)
            save_json(pointer, receipt)
            return receipt
        except Exception as error:
            attempts.append({'endpoint':endpoint, 'error':str(error)})
    raise RuntimeError('No complete waterway source: '+json.dumps(attempts))


def surface_channel_reason(tags):
    if lifecycle_inactive(tags):
        return 'inactive_lifecycle'
    for key in ('covered', 'tunnel', 'indoor'):
        if str(tags.get(key, '')).strip().lower() not in ('', 'no', 'false', '0'):
            return key+'='+str(tags[key])
    if str(tags.get('location', '')).lower() in ('underground', 'indoor'):
        return 'location='+tags['location']
    return None


def source_width_m(tags):
    """Accept an unambiguous positive OSM width, whose default unit is metres."""
    value = str(tags.get('width', '')).strip().lower()
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(m|metres?|meters?|ft|feet)?', value)
    if not match:
        return None
    width = float(match[1]) * (0.3048 if match[2] in ('ft', 'feet') else 1)
    return width if math.isfinite(width) and width > 0 else None


def acquire_stadiums(bbox, refresh=False):
    pointer = REFERENCE/'screening_exclusions_stadium_acquisition.json'
    if pointer.exists() and not refresh:
        receipt = json.loads(pointer.read_text(encoding='utf-8'))
        if digest(REFERENCE/receipt['raw_file']) != receipt['raw_sha256']:
            raise ValueError('Preserved stadium source checksum changed')
        if digest(REFERENCE/receipt['query_file']) != receipt['query_sha256']:
            raise ValueError('Preserved stadium query checksum changed')
        return receipt
    west, south, east, north = bbox
    extent = f'({south},{west},{north},{east})'
    query = ('[out:json][timeout:90];('
             f'way["leisure"="stadium"]{extent};relation["leisure"="stadium"]{extent};'
             f'way["building"="stadium"]{extent};relation["building"="stadium"]{extent};'
             ');out meta geom;')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    querypath = REFERENCE/f'screening_exclusions_stadium_{stamp}.overpass'
    querypath.write_text(query, encoding='utf-8')
    attempts = []
    for endpoint in ['https://overpass-api.de/api/interpreter',
                     'https://overpass.kumi.systems/api/interpreter']:
        try:
            print(json.dumps({'stage':'stadium_download', 'endpoint':endpoint}), flush=True)
            request = urllib.request.Request(endpoint,
                data=urllib.parse.urlencode({'data':query}).encode(),
                headers={'User-Agent':'DrainCheck mapped-footprint screening preparation',
                         'Accept':'application/json'})
            with urllib.request.urlopen(request, timeout=110) as response:
                body = response.read()
            doc = json.loads(body)
            if doc.get('remark') or not doc.get('elements'):
                raise ValueError(doc.get('remark', 'Empty source; refusing empty substitute'))
            rawpath = REFERENCE/f'screening_exclusions_stadium_{stamp}.json'
            rawpath.write_bytes(body)
            receipt = {'endpoint':endpoint, 'download_utc':datetime.now(timezone.utc).isoformat(),
                       'raw_file':rawpath.name, 'raw_sha256':digest(rawpath),
                       'query_file':querypath.name, 'query_sha256':digest(querypath),
                       'bbox':bbox, 'elements':len(doc['elements']),
                       'osm_base_timestamp':doc.get('osm3s',{}).get('timestamp_osm_base'),
                       'attempts':attempts}
            save_json(REFERENCE/f'screening_exclusions_stadium_{stamp}_acquisition.json', receipt)
            save_json(pointer, receipt)
            return receipt
        except Exception as error:
            attempts.append({'endpoint':endpoint, 'error':str(error)})
    raise RuntimeError('No complete stadium source: '+json.dumps(attempts))


def polygon(e):
    if e['type'] == 'relation':
        result = relation_geometry(e)
    else:
        coords = [(p['lon'],p['lat']) for p in e.get('geometry',[])]
        if len(coords)<4 or coords[0] != coords[-1]:
            raise ValueError('No closed footprint; no buffer is substituted')
        result = Polygon(coords)
    if not result.is_valid:
        result = shapely.make_valid(result)
    parts = polygon_parts(result)
    if not parts:
        raise ValueError('No polygon footprint')
    return shapely.union_all(parts)


def channel_candidate(tags):
    # Unlike the open-water layer this user-requested channel policy deliberately
    # includes seasonal/intermittent mapped channels. The source tags are retained.
    return (tags.get('water') in ('river','canal','stream')
            or tags.get('waterway') == 'riverbank'
            or (tags.get('natural') == 'water'
                and tags.get('intermittent') == 'yes'
                and tags.get('water') in (None,'river','canal','stream')))


def lifecycle_inactive(tags):
    inactive = ('disused','abandoned','demolished','removed','razed','construction','proposed')
    return any(str(value).lower() not in ('','no','false','0')
               for key,value in tags.items() if key.split(':')[0] in inactive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    start = time.monotonic()
    source = CACHE/'pluvial_5m.tif'
    with rasterio.open(source) as src:
        if src.shape != SHAPE or src.transform != GRID or src.crs.to_epsg()!=7801:
            raise ValueError('Exact verified municipal 5 m grid required')
    water_receipt = json.loads((REFERENCE/'osm_open_water_acquisition.json').read_text(encoding='utf-8'))
    water_path = REFERENCE/water_receipt['raw_file']
    if digest(water_path) != water_receipt['raw_sha256']:
        raise ValueError('Original water source checksum mismatch')
    stadium_receipt = acquire_stadiums(water_receipt['bbox'], args.refresh)
    waterway_receipt = acquire_waterways(water_receipt['bbox'], args.refresh)
    waterway_doc = json.loads((REFERENCE/waterway_receipt['raw_file']).read_text(encoding='utf-8'))
    snapshots = [(json.loads(water_path.read_text(encoding='utf-8')),1),
                 (waterway_doc,1),
                 (json.loads((REFERENCE/stadium_receipt['raw_file']).read_text(encoding='utf-8')),2)]
    features = []; shapes = {1:[],2:[]}; rejected = []; seen = set()
    gridbox = box(GRID.c, GRID.f-SHAPE[0]*5, GRID.c+SHAPE[1]*5, GRID.f)
    for raw,bit in snapshots:
        if raw.get('remark'):
            raise ValueError('Incomplete source response')
        selected = [e for e in raw['elements'] if not lifecycle_inactive(e.get('tags',{}))
                    and (bit==2 or channel_candidate(e.get('tags',{})))]
        relations = [e for e in selected if e['type']=='relation']
        member_ids = {m['ref'] for e in relations for m in e.get('members',[]) if m['type']=='way'}
        for e in selected:
            sid = e['type']+'/'+str(e['id'])
            if sid in seen or (e['type']=='way' and e['id'] in member_ids):
                continue
            try:
                geom = polygon(e)
                projected = shapely.transform(geom, PROJECT.transform, interleaved=False).intersection(gridbox)
                if projected.is_empty:
                    continue
                shapes[bit].append(projected)
                seen.add(sid)
                features.append({'type':'Feature','id':sid,
                    'properties':{'osm_type':e['type'],'osm_id':e['id'],'osm_version':e.get('version'),
                        'osm_timestamp':e.get('timestamp'),'source_url':'https://www.openstreetmap.org/'+sid,
                        'exclusion_bit':bit,'category':'mapped_channel' if bit==1 else 'stadium',
                        'tags':e.get('tags',{})}, 'geometry':mapping(geom)})
            except Exception as error:
                rejected.append({'osm_id':sid,'category_bit':bit,'reason':str(error),'tags':e.get('tags',{})})
    channel_polygons = len(shapes[1])
    channel_lines = []; omitted_lines = []; width_count = 0; line_lengths = 0.0
    if waterway_doc.get('remark'):
        raise ValueError('Incomplete waterway-network response')
    for e in waterway_doc['elements']:
        tags = e.get('tags', {})
        if e['type'] != 'way' or tags.get('waterway') not in WATERWAYS:
            continue
        sid = 'way/'+str(e['id'])
        reason = surface_channel_reason(tags)
        if reason:
            omitted_lines.append({'osm_id':sid,'reason':reason,'tags':tags})
            continue
        coords = [(p['lon'],p['lat']) for p in e.get('geometry', [])]
        if len(coords) < 2 or any(not all(math.isfinite(c) for c in xy) for xy in coords):
            raise ValueError('Incomplete mapped channel geometry: '+sid)
        geom = LineString(coords)
        metric = shapely.transform(geom, PROJECT.transform, interleaved=False)
        clipped = metric.intersection(gridbox)
        if clipped.is_empty:
            continue
        width = source_width_m(tags)
        channel_lines.append(clipped)
        line_lengths += clipped.length
        # A missing width is never replaced with an invented bank/floodplain.
        # The line itself still suppresses every intersecting native 5 m cell.
        footprint = metric.buffer(width/2) if width is not None else metric
        shapes[1].append(footprint.intersection(gridbox))
        width_count += int(width is not None)
        features.append({'type':'Feature','id':sid,
            'properties':{'osm_type':'way','osm_id':e['id'],'osm_version':e.get('version'),
                'osm_timestamp':e.get('timestamp'),'source_url':'https://www.openstreetmap.org/'+sid,
                'exclusion_bit':1,'category':'mapped_channel','geometry_role':'channel_centerline',
                'source_width_m':width,'width_policy':'explicit source width' if width is not None else 'intersecting 5 m analysis cells; physical width unknown',
                'tags':tags},'geometry':mapping(geom)})
    if not channel_lines:
        raise ValueError('No open waterway centerlines; refusing polygon-only coverage')
    ids = {f['id'] for f in features}
    required = {'way/341968882','way/1341771831','way/1234109017'}
    if not required.issubset(ids):
        raise ValueError('Required real stadium/central channel polygons absent: '+str(required-ids))
    print(json.dumps({'stage':'rasterize', 'channel_polygons':channel_polygons,
                     'channel_lines':len(channel_lines),'stadium_polygons':len(shapes[2])}),flush=True)
    mask = rasterize([(g,1) for g in shapes[1]], out_shape=SHAPE,transform=GRID,
                     dtype='uint8', fill=0, all_touched=True)
    # GDAL's line rasterizer can snap a near-horizontal crossing into one row.
    # Explicit segment/grid traversal retains every actually intersected cell.
    burn_centerline_cells(mask, channel_lines, GRID, flag=1)
    # Source lines may sit on a bank while the real DTM bed is several metres
    # beside them. The distance bounds a search, not an automatic exclusion:
    # only connected positive-fill terrain can be added; flat banks remain.
    corridor = rasterize([(g.buffer(CHANNEL_SEARCH_M, cap_style='flat'),1)
                          for g in channel_lines], out_shape=SHAPE, transform=GRID,
                         dtype='uint8', fill=0, all_touched=False).astype(bool)
    positive_fill = np.zeros(SHAPE, dtype=bool)
    invalid_river_seeds_removed = 0
    with rasterio.Env(GDAL_CACHEMAX=64000000), rasterio.open(source,OVERVIEW_LEVEL='NONE') as src:
        for row in range(0,SHAPE[0],512):
            for col in range(0,SHAPE[1],512):
                search = corridor[row:row+512,col:col+512]
                seed_block = mask[row:row+512,col:col+512]
                if not np.any(search) and not np.any(seed_block):
                    continue
                z, depth = src.read([1,2],window=Window(col,row,search.shape[1],search.shape[0]))
                valid_ground = np.isfinite(z)&(z!=src.nodata)
                invalid_river_seeds_removed += int(np.count_nonzero(seed_block[~valid_ground]))
                seed_block[~valid_ground] = 0
                positive_fill[row:row+search.shape[0],col:col+search.shape[1]] = (
                    valid_ground&np.isfinite(depth)&(depth!=src.nodata)&(depth>0))
    mask, alignment = expand_terrain_connected_channels(mask, corridor, positive_fill)
    del corridor, positive_fill
    print(json.dumps({'stage':'terrain_alignment',**alignment}),flush=True)
    stadium = rasterize([(g,2) for g in shapes[2]], out_shape=SHAPE,transform=GRID,
                        dtype='uint8', fill=0, all_touched=True)
    mask |= stadium
    del stadium
    outside_removed = 0
    with rasterio.Env(GDAL_CACHEMAX=64000000), rasterio.open(source,OVERVIEW_LEVEL='NONE') as src:
        for row in range(0,SHAPE[0],512):
            for col in range(0,SHAPE[1],512):
                target = mask[row:row+512,col:col+512]
                if not np.any(target):
                    continue
                z = src.read(1,window=Window(col,row,target.shape[1],target.shape[0]))
                invalid = ~np.isfinite(z)|(z==src.nodata)
                outside_removed += int(np.count_nonzero(target[invalid]))
                target[invalid] = 0
    controls = []
    for sid in sorted(required):
        feat = next(f for f in features if f['id']==sid)
        geom = shapely.geometry.shape(feat['geometry'])
        bit = feat['properties']['exclusion_bit']
        control = control_point((mask&bit).astype('uint8'),geom,
                                'Whole Vasil Levski stadium' if bit==2 else 'Mapped Perlovska channel',sid,bit)
        if not control:
            raise AssertionError('No masked centre inside mandatory footprint: '+sid)
        controls.append(control)
    x,y = PROJECT.transform(23.3352531692,42.6875642953)
    row,col = int((GRID.f-y)//5),int((x-GRID.c)//5)
    if not mask[row,col]&2:
        raise AssertionError('Confirmed Vasil Levski pitch is not suppressed')
    controls.append({'name':'Confirmed Vasil Levski pitch centroid','longitude':23.3352531692,
                     'latitude':42.6875642953,'row':row,'column':col,'mask_value':int(mask[row,col]),'expected':2})
    output = CACHE/'screening_exclusions_5m.tif'
    pending = CACHE/'screening_exclusions_5m.pending.tif'
    with rasterio.open(pending,'w',driver='GTiff',height=SHAPE[0],width=SHAPE[1],count=1,
                       dtype='uint8',crs='EPSG:7801',transform=GRID,nodata=None,
                       tiled=True,blockxsize=512,blockysize=512,compress='DEFLATE',predictor=2) as dst:
        dst.write(mask,1)
        dst.set_band_description(1,'user_requested_screening_exclusions')
        dst.update_tags(METHOD=METHOD,SOURCE='OpenStreetMap contributors; ODbL1.0',
                        VALUES='bits:1=river exclusion;2=stadium;4=inferred terrain-connected channel candidate (always with bit1)',
                        POLICY='User-requested screening suppression; not proof of safety',
                        RASTERIZATION='all intersecting 5 m cells; exact centerline supercover; explicit source widths only; no proximity buffer')
        dst.build_overviews([2,4,8,16,32],Resampling.nearest)
    with rasterio.open(pending,OVERVIEW_LEVEL='NONE') as check:
        if (check.shape!=SHAPE or check.transform!=GRID or check.crs.to_epsg()!=7801
                or check.nodata is not None or check.dtypes!=('uint8',)
                or not np.array_equal(check.read(1),mask)):
            raise AssertionError('Raster serialization/grid validation failed')
    pending.replace(output)
    output_hash = digest(output)
    geojson = REFERENCE/'screening_exclusions.geojson'
    save_json(geojson,{'type':'FeatureCollection','name':'Requested screening suppression footprints',
                      'attribution':'© OpenStreetMap contributors; ODbL1.0', 'features':features})
    counts = {'river_channel_cells':int(np.count_nonzero(mask&1)),
              'stadium_cells':int(np.count_nonzero(mask&2)),
              'union_cells':int(np.count_nonzero(mask)),
              'overlap_cells':int(np.count_nonzero((mask&3)==3)),
              'terrain_connected_cells':int(np.count_nonzero(mask&4)),
              'channel_polygons':channel_polygons,'channel_centerlines':len(channel_lines),
              'centerlines_with_source_width':width_count,'centerline_length_m':line_lengths,
              'omitted_covered_or_inactive_centerlines':len(omitted_lines),'stadium_polygons':len(shapes[2]),
              'invalid_river_seed_cells_removed_before_propagation':invalid_river_seeds_removed,
              'outside_valid_terrain_removed':outside_removed}
    metadata = {'available':True,'enabled':True,'method':METHOD,'revision':output_hash[:16],
        'sha256':output_hash,'file':'data/cache/screening_exclusions_5m.tif',
        'exclusions_are_policy':True,'retrieved':max(waterway_receipt['download_utc'],stadium_receipt['download_utc']),
        'grid':{'crs':'EPSG:7801','width':SHAPE[1],'height':SHAPE[0],'shape':list(SHAPE),
                'transform':list(GRID)[:6],'dtype':'uint8','count':1,'nodata':None,
                'values':{'0':'not suppressed','1':'mapped channel','2':'stadium','3':'mapped channel and stadium',
                          '5':'terrain-connected channel candidate','7':'terrain-connected channel candidate and stadium'}},
        'terrain_alignment':{**alignment,'search_distance_m':CHANNEL_SEARCH_M,
             'river_seed_cells_valid_before_propagation':True,
             'final_valid_river_cells':counts['river_channel_cells'],
             'search_policy':'Native cell centres within 20 m of open mapped centerlines; flat end caps. Distance alone never excludes land.',
             'criterion':'Finite positive depression fill depth and valid real 5 m terrain, 8-connected to a mapped river seed.',
             'terrain_file':'data/cache/pluvial_5m.tif','terrain_sha256':digest(source),
             'interpretation':'Inferred channel-alignment candidates excluded by screening policy, not observed water or surveyed bank boundaries.'},
        'counts':counts,'source':{'provider':'OpenStreetMap contributors','license':'ODbL1.0',
             'attribution':'© OpenStreetMap contributors','license_url':'https://www.openstreetmap.org/copyright',
             'water_acquisition':water_receipt,'stadium_acquisition':stadium_receipt,
             'waterway_acquisition':waterway_receipt,
             'geojson_file':geojson.relative_to(ROOT).as_posix(),'geojson_sha256':digest(geojson)},
        'policy':'Suppress mapped channel and whole stadium footprints in derived risk screening and scenario displays. Includes mapped intermittent channels. Original terrain and historical observations are retained.',
        'limitations':['This is a user-requested screening exclusion, not evidence of safety or absence of flood hazard.',
            'OSM community geometry may be incomplete, outdated or misclassified. Whole stadium footprint is used, not only the pitch.',
            'Mapped open river, stream, canal, drain and ditch centerlines supplement water/riverbank polygons. Explicit width tags supply width where present; otherwise only intersecting 5 m cells are excluded, not a measured physical channel width.',
            'Covered, tunnel, indoor, underground and inactive mapped line segments are omitted; culvert crossings do not automatically exclude surface roads.',
            'Terrain alignment adds only connected positive-fill candidates within a 20 m search allowance. It can include nearby connected depressions and does not independently establish actual bank boundaries; inference bit4 distinguishes these cells from mapped geometry.',
            'Every 5 m cell intersecting an actual footprint is suppressed (all_touched=True), including partial edge cells. This is grid-cell coverage, not a river/floodplain buffer.',
            'Unmapped channels and unknown bank widths remain source limitations. No river-distance or floodplain buffer is applied. River flooding is not simulated by suppressing channel pixels.'],
        'control_points':controls,'rejected_geometry':rejected,'omitted_centerlines':omitted_lines,
        'verification':{'exact_grid_type_nodata_and_pixels_checked':True,'mandatory_real_controls_passed':True,
            'exact_centerline_grid_supercover':True,
            'original_water_source_sha256_unchanged':digest(water_path)==water_receipt['raw_sha256'],
            'pluvial_source_read_only':True,'elapsed_seconds':round(time.monotonic()-start,2)}}
    save_json(CACHE/'screening_exclusions_meta.json',metadata)
    print(json.dumps({'stage':'complete','revision':metadata['revision'],'counts':counts,'controls':controls}),flush=True)


if __name__=='__main__':
    main()
