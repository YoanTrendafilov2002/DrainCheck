"""Create a separate, rule-based review map from real preserved source data.

This is an inspection-priority scenario, NOT a calibrated flood-risk model.
The original terrain, P/C/S, rainfall, cadastre and historical data are read-only.
Run: python scripts/prepare_review_priority.py
"""
from pathlib import Path
import hashlib, json, os, sqlite3, time
from datetime import datetime, timezone
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import bounds as window_bounds, transform as window_transform
from rasterio.warp import transform_bounds
from pyproj import Transformer
from shapely import from_wkb, transform as transform_coordinates
from shapely.geometry import shape, mapping, box
from shapely.ops import transform, unary_union

APP=Path(__file__).resolve().parents[1]
LABELS={0:'Lower ponding terrain signal',1:'Raised ponding terrain signal',
        2:'Higher ponding terrain signal',3:'Higher ponding + potential building footprint',
        4:'Historical flood footprint',5:'Historical footprint + potential building footprint',
        253:'Excluded mapped open water',254:'Uncertain terrain',255:'Outside terrain'}
PALETTE={0:'#fff1c4',1:'#fbc66e',2:'#ed824b',3:'#bb3d40',4:'#8b75c2',5:'#632476',
         253:'#00000000',254:'#80878c',255:'#00000000'}
METHOD='evidence-review-priority-v1'
SCENARIO=('At the user’s request, the available datasets are treated as compatible '
          'for a combined review scenario. Actual source dates, spatial gaps and '
          'unknown currency remain recorded. This does not establish that the '
          '2025 rainfall caused the 2021 mapped flooding or calibrate forecast skill.')

def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def classify(p,known,water,uncertain,history,buildings):
    """Ordered review rules; no numerical averaging or alteration of P."""
    result=np.full(p.shape,255,dtype='uint8')
    eligible=known&~water&~uncertain
    result[eligible]=0
    result[eligible&(p>=50)]=1
    result[eligible&(p>=70)]=2
    result[eligible&(p>=70)&buildings]=3
    result[eligible&history]=4
    result[eligible&history&buildings]=5
    result[known&uncertain&~water]=254
    result[known&water]=253
    return result

def prepare(app=APP):
    app=Path(app);start=time.time();xy=Transformer.from_crs(4326,7801,always_xy=True)
    cache=app/'data/cache';out=app/'data/derived/review_priority_5m.tif';partial=out.with_suffix('.partial.tif')
    sources={'terrain_scores':cache/'pluvial_5m.tif','water_mask':cache/'open_water_mask_5m.tif',
             'historical_polygons':app/'data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson',
             'cadastre_index':cache/'cadastral_buildings.sqlite'}
    before={key:{'file':p.relative_to(app).as_posix(),'size_bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns,'sha256':sha(p)} for key,p in sources.items()}
    historical=load(sources['historical_polygons'])
    historic_union=unary_union([transform_coordinates(shape(f['geometry']),xy.transform,interleaved=False) for f in historical['features']])
    terrain_meta=load(cache/'pluvial_meta.json');water_meta=load(cache/'open_water_meta.json')
    cad_meta=load(cache/'cadastral_buildings_meta.json');hist_meta=load(cache/'historical_flood_zones_meta.json')
    if cad_meta['sha256']!=sha(app/cad_meta['data_file']):raise ValueError('Cadastre source GeoJSON checksum mismatch')
    db=sqlite3.connect(f'file:{sources["cadastre_index"].as_posix()}?mode=ro',uri=True)
    db.execute('pragma cache_size=-16384')
    db_meta=dict(db.execute('select key,value from metadata'))
    if db_meta.get('revision')!=cad_meta['revision']:raise ValueError('Cadastre index revision mismatch')
    counts=np.zeros(256,dtype='int64');eligible_footprint_cells=0;all_footprint_cells=0
    history_cells=0;history_known_cells=0;query_rows=0;query_ids=set();processed=0
    # The derivative carries categorical codes only. Original Float32 factors stay intact.
    try:
        with rasterio.open(sources['terrain_scores']) as src,rasterio.open(sources['water_mask']) as water:
            if (src.crs.to_epsg()!=7801 or src.count!=8 or src.shape!=(10869,10345)
                or list(src.transform)[:6]!=[5,0,299392,0,-5,4753611]
                or water.shape!=src.shape or water.transform!=src.transform or water.crs!=src.crs):
                raise ValueError('Source grids do not match the verified 5m alignment')
            profile=src.profile.copy();profile.update(count=1,dtype='uint8',nodata=255,
                tiled=True,blockxsize=512,blockysize=512,compress='DEFLATE',predictor=1,bigtiff='IF_SAFER')
            with rasterio.open(partial,'w',**profile) as dst:
                dst.set_band_description(1,'evidence_based_review_priority')
                dst.update_tags(METHOD=METHOD,INTERPRETATION='Review categories only; not flood probability, depth or damage',
                                SCENARIO_ASSUMPTION=SCENARIO,BUILDINGS='Potential 5m cell-footprint intersection; all_touched=True')
                windows=list(dst.block_windows(1));total=len(windows)
                for _,window in windows:
                    a=src.read([1,5,6,7,8],window=window)
                    known=np.isfinite(a[0])&(a[0]!=src.nodata)
                    water_mask=water.read(1,window=window)==1
                    eligible=known&~water_mask&(a[1]==0)&np.all(np.isfinite(a[2:])&(a[2:]>=0),axis=0)
                    uncertain=known&~eligible&~water_mask
                    tr=window_transform(window,src.transform);bounds=window_bounds(window,src.transform)
                    history=np.zeros(known.shape,dtype='uint8');footprint=np.zeros(known.shape,dtype='uint8')
                    if historic_union.intersects(box(*bounds)):
                        rasterize([(mapping(historic_union),1)],out=history,transform=tr,all_touched=False)
                    if np.any(known):
                        ll=transform_bounds(src.crs,4326,*bounds,densify_pts=21)
                        rows=db.execute('select f.source_id,f.geometry from features f join feature_bounds r using(fid) where r.maxx>=? and r.minx<=? and r.maxy>=? and r.miny<=?',(ll[0],ll[2],ll[1],ll[3]))
                        shapes=[];tile_box=box(*bounds)
                        for sid,wkb in rows:
                            query_rows+=1;query_ids.add(sid)
                            geom=transform_coordinates(from_wkb(wkb),xy.transform,interleaved=False)
                            if geom.intersects(tile_box):shapes.append((mapping(geom.intersection(tile_box)),1))
                        if shapes:rasterize(shapes,out=footprint,transform=tr,all_touched=True)
                    code=classify(a[2],known,water_mask,uncertain,history.astype(bool),footprint.astype(bool))
                    counts+=np.bincount(code.ravel(),minlength=256)
                    all_footprint_cells+=int((known&(footprint==1)).sum())
                    eligible_footprint_cells+=int((eligible&(footprint==1)).sum())
                    history_cells+=int((history==1).sum());history_known_cells+=int(((history==1)&known).sum())
                    dst.write(code,1,window=window);processed+=1
                    if processed%50==0:print(f'review derivative: {processed}/{total} blocks; queried {len(query_ids):,} distinct cadastral records',flush=True)
        db.close()
        for key,p in sources.items():
            b=before[key]
            if p.stat().st_size!=b['size_bytes'] or p.stat().st_mtime_ns!=b['mtime_ns'] or sha(p)!=b['sha256']:
                raise ValueError(f'Original changed during processing: {key}')
        os.replace(partial,out)
    except Exception:
        db.close()
        if partial.exists():partial.unlink()
        raise
    output_sha=sha(out)
    identity={'method':METHOD,'source_hashes':{k:v['sha256'] for k,v in before.items()},
              'rules':[50,70],'historical_membership':'pixel-centre','footprint_membership':'all_touched',
              'scenario_assumption':SCENARIO,'output_sha256':output_sha}
    revision=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    result={'available':True,'revision':revision,'method':METHOD,'title':'Evidence-informed review priority',
      'interpretation':'Rule-based inspection categories; no calibrated flood likelihood, intensity, depth, vulnerability or damage',
      'scenario_assumption':SCENARIO,'output_file':out.relative_to(app).as_posix(),'output_sha256':output_sha,
      'grid':{'crs':'EPSG:7801','shape':[10869,10345],'transform':[5,0,299392,0,-5,4753611],'nodata':255},
      'band':'evidence_based_review_priority','classes':[{'code':k,'label':v,'colour':PALETTE[k],
                'color_rgba':[int(PALETTE[k][i:i+2],16) for i in [1,3,5]]+([0] if k in [253,255] else [185] if k==254 else [190]),
                'cell_count':int(counts[k]),'area_km2':int(counts[k])*25/1e6} for k,v in LABELS.items()],
      'counts':{'all_cells':int(counts.sum()),'eligible_land_cells':int(counts[:6].sum()),'known_terrain_cells':int(counts[:255].sum()),
                'mapped_water_cells':int(counts[253]),'uncertain_cells':int(counts[254]),'outside_cells':int(counts[255]),
                'potential_footprint_cells_known_terrain':all_footprint_cells,'potential_footprint_cells_eligible_land':eligible_footprint_cells,
                'historical_union_cell_centres':history_cells,'historical_union_known_terrain_cells':history_known_cells,
                'queried_distinct_cadastral_source_records':len(query_ids),'query_rows_including_repeated_window_candidates':query_rows},
      'formula':{'ordered_rules':['Outside known DTM =>255','Mapped qualifying water on known terrain=>253',
                    'Known nonwater terrain with boundary influence or invalid required P/C/S factor=>254',
                    'Eligible historical footprint plus potential cadastral footprint=>5','Eligible historical footprint=>4',
                    'Eligible P>=70 plus potential cadastral footprint=>3','Eligible P>=70=>2','Eligible50<=P<70=>1','Other eligible land=>0'],
                 'historical':'Union of actual136 display polygons; no overlap double-count; pixel centres',
                 'building':'Actual AGKK geometry queried via read-only RTree, reprojected into existing EPSG7801 cells; all_touched=True; source record != unique physical building',
                 'thresholds':'Existing exploratory P thresholds50 and70 reused; no fitted weights or predictive validation',
                 'unchanged':'Original P/C/S raster, ground heights and source values remain unchanged; historical evidence changes this separate display class only'},
      'source_revisions':{'pluvial':hashlib.sha256(('mapped-water-v1:'+terrain_meta['revision']+':'+water_meta['revision']).encode()).hexdigest()[:16],
                          'terrain':terrain_meta['revision'],'water':water_meta['revision'],'cadastre':cad_meta['revision'],'history':hist_meta['revision'],
                          'rainfall_context':load(cache/'rainfall_meta.json')['revision']},
      'source_dates':{'terrain':'Source filename2024; measurement date/vertical accuracy unverified','historical':'2021; January/February discrepancy; no per-feature timestamp',
                      'cadastre':'Source date unknown; snapshot retrieved25Oct2026','rainfall':'27June2025 Europe/Sofia daily totals','green':'Supplied municipal2020-labelled source',
                      'sewer':'Supplied municipal2009-labelled route source; some planned routes'},
      'source_files':before,'source_counts':{'historical_features':len(historical['features']),'cadastre_source_records':cad_meta['feature_count']},
      'source_urls':{'historical':hist_meta['source_url'],'cadastre':cad_meta['source_url'],
                     'open_water':'https://www.openstreetmap.org','terrain':'https://api.sofiaplan.bg/datasets/656'},
      'context_not_numerical_hazard_inputs':['2025 daily rainfall','green-area labels','sewer route/point density or status','reported clogging or drainage narratives without spatially resolved hydraulic inputs'],
      'limitations':['This is review priority, not a calibrated flood hazard/risk index; category ordering is an explicit analyst operational choice.',
        'Historical footprints are partial northern survey coverage and mixed river/rainfall/snowmelt context. No polygon does not mean no previous flooding.',
        'Cadastral footprints indicate potential exposure only; no floor levels, occupancy, protective measures or damage model enter the classification.',
        'All-touched5m building membership can include a small footprint sliver; cells are not treated as100% sealed and cell area is not exposed building area.',
        'Rainfall daily totals provide event context, not short-duration intensity or sewer exceedance; fine-rain grids have zero spatial overlap with2021 survey polygons.',
        'Green polygons do not establish soil infiltration; route/point presence does not establish operational drainage or blockage probability.',
        'Original concentration/combined modes retain D8 routing/terrain-facet limitations; C is intentionally not added to review priority.',
        'Open-water exclusions preserve source policy, including unmapped/intermittent channel gaps; adjacent land is not assumed safe.',
        'No changes to buildings as terrain barriers, upstream hydrology, DTM resolution, original source files or legacy map modes.'],
      'verification':{'all_listed_sources_unchanged':True,'source_hashes_checked_before_after':True},
      'created_utc':datetime.now(timezone.utc).isoformat(),'runtime_seconds':round(time.time()-start,3),
      'reproduce':'python scripts/prepare_review_priority.py'}
    target=cache/'review_priority_meta.json';temp=target.with_suffix('.partial.json')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,target)
    print(json.dumps({'revision':revision,'output':str(out),'size_bytes':out.stat().st_size,'counts':result['counts'],'classes':result['classes'],'runtime_seconds':result['runtime_seconds']},ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':prepare()
