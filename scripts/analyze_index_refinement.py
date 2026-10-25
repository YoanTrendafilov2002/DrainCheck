"""Read-only actual-data comparisons; never calibrates flood probability.

Run from the app: python scripts/analyze_index_refinement.py
Native terrain follows SOFIA_DTM_PATH, resolved relative to the app if needed.
All distances/areas use the existing EPSG:7801 grid. Raster membership uses cell
centres. Rings are descriptive surroundings, not known non-flooded controls.
"""
from pathlib import Path
import csv, hashlib, json, math, os, sqlite3, time
from datetime import datetime, timezone
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds, Window, bounds as window_bounds, transform as window_transform
from pyproj import Transformer
from shapely.geometry import shape, mapping, box
from shapely.ops import transform, unary_union
from shapely import from_wkb

APP=Path(__file__).resolve().parents[1]
NATIVE_DTM=Path(os.environ.get('SOFIA_DTM_PATH',str(APP.parent/'sofia_dtm_2024_1m_gee.tif')))
if not NATIVE_DTM.is_absolute():NATIVE_DTM=APP/NATIVE_DTM
OUT=APP/'data/reference/index_refinement_analysis.json'
DOC=APP/'docs/INDEX_REFINEMENT_ANALYSIS.md'
XY=Transformer.from_crs(4326,7801,always_xy=True)
LL=Transformer.from_crs(7801,4326,always_xy=True)
NODATA=-9999
THRESHOLDS=[50,70,85]

def read(rel):return json.loads((APP/rel).read_text(encoding='utf-8'))
def source_key(path):
    try:return Path(path).resolve().relative_to(APP.resolve()).as_posix()
    except ValueError:return 'external_native_dtm/'+Path(path).name
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for a in iter(lambda:f.read(4*1024*1024),b''):h.update(a)
    return h.hexdigest()
def summary(a):
    a=np.asarray(a);a=a[np.isfinite(a)]
    if not a.size:return {'count':0}
    q=np.quantile(a,[0,.05,.25,.5,.75,.95,1])
    return dict(count=int(a.size),mean=float(np.mean(a,dtype='float64')),
                **dict(zip(['min','p05','p25','p50','p75','p95','max'],map(float,q))))
def features_stream(path):
    """Bounded GeoJSON FeatureCollection reader without a new dependency."""
    dec=json.JSONDecoder();buf='';started=False;done=False
    with Path(path).open(encoding='utf-8-sig') as f:
        while not done:
            chunk=f.read(1024*1024)
            if not chunk and not buf:break
            buf+=chunk
            if not started:
                marker=buf.find('"features"')
                if marker<0:
                    if not chunk:raise ValueError('No FeatureCollection features')
                    continue
                at=buf.find('[',marker)
                if at<0:continue
                buf=buf[at+1:];started=True
            while True:
                buf=buf.lstrip(' \t\r\n,')
                if buf.startswith(']'):done=True;break
                if not buf:break
                try:a,end=dec.raw_decode(buf)
                except json.JSONDecodeError:
                    if not chunk:raise
                    break
                if a.get('type')!='Feature':raise ValueError('Non-feature in array')
                yield a;buf=buf[end:]

def main():
    start=time.time();stamp=datetime.now(timezone.utc).isoformat()
    hist_path=APP/'data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson'
    raster_path=APP/'data/cache/pluvial_5m.tif'
    water_path=APP/'data/cache/open_water_mask_5m.tif'
    db_path=APP/'data/cache/cadastral_buildings.sqlite'
    source_hist=read('data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson')
    hist_features=[(f['properties']['source_id'],transform(XY.transform,shape(f['geometry']))) for f in source_hist['features']]
    union=unary_union([g for _,g in hist_features])
    zones={'observed_union':union,'surrounding_0_50m':union.buffer(50).difference(union),
           'surrounding_50_250m':union.buffer(250).difference(union.buffer(50)),
           'surrounding_250_500m':union.buffer(500).difference(union.buffer(250))}
    region=union.buffer(500);region_ll=transform(LL.transform,region)
    tracked=[hist_path,raster_path,water_path,db_path,NATIVE_DTM,
             APP/'data/raw/sofia_infrastructure_points.csv',*list((APP/'data/rainfall').glob('*.tif'))]
    green_path=next((APP/'data/raw').glob('green_areas_*.geojson'));tracked.append(green_path)
    before={source_key(p):dict(size_bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns,sha256=digest(p)) for p in tracked}
    print('Source hashes verified; reading bounded historical region',flush=True)
    with rasterio.open(raster_path) as src,rasterio.open(water_path) as water:
        w=from_bounds(*region.bounds,src.transform).round_offsets().round_lengths()
        w=Window(max(0,w.col_off),max(0,w.row_off),w.width,w.height).intersection(Window(0,0,src.width,src.height))
        data=src.read(window=w);water_values=water.read(1,window=w)
        tr=window_transform(w,src.transform);shape2=data.shape[1:]
        labels=rasterize([(mapping(g),i+1) for i,(_,g) in reversed(list(enumerate(zones.items())))],
                         out_shape=shape2,transform=tr,all_touched=False,dtype='uint8')
        known=np.isfinite(data[0])&(data[0]!=NODATA)
        excluded=known&(water_values==1)
        eligible=known&~excluded&(data[4]==0)&np.all(np.isfinite(data[5:8])&(data[5:8]>=0),axis=0)
        uncertain=known&~excluded&~eligible
        def profile(mask):
            good=mask&eligible;n=int(good.sum());scores={}
            for name,b in [('ponding',5),('concentration',6),('combined',7)]:
                a=data[b][good];counts=np.bincount(np.searchsorted(THRESHOLDS,a,side='right'),minlength=4)
                scores[name]={'summary':summary(a),'class_counts':dict(zip(['Lower signal','Raised','Higher signal','Strongest signal'],map(int,counts))),
                              'at_least_70_pct':100*int((a>=70).sum())/n if n else None,
                              'at_least_85_pct':100*int((a>=85).sum())/n if n else None}
            return {'total_cell_centres':int(mask.sum()),'known_terrain_cells':int((mask&known).sum()),
                    'water_excluded_cells':int((mask&excluded).sum()),'uncertain_cells':int((mask&uncertain).sum()),
                    'eligible_land_cells':n,'eligible_land_area_m2':n*25,
                    'factors':{name:summary(data[b][good]) for name,b in [('mean_elevation_m',0),('depression_fill_depth_m',1),('slope_degrees',2),('contributing_area_m2',3)]},
                    'zero_fill_depth_pct':100*int((data[1][good]==0).sum())/n if n else None,
                    'concentration_dominates_pct':100*int((data[6][good]>=data[5][good]).sum())/n if n else None,
                    'score_classes':scores}
        zone_profiles={name:dict(vector_area_m2=float(g.area),**profile(labels==i+1)) for i,(name,g) in enumerate(zones.items())}
        print('Regional cell statistics complete',flush=True)
        per_feature=[]
        for fid,g in hist_features:
            inner=rasterize([(mapping(g),1)],out_shape=shape2,transform=tr,dtype='uint8').astype(bool)
            ring=g.buffer(250).difference(union.buffer(50))
            outer=rasterize([(mapping(ring),1)],out_shape=shape2,transform=tr,dtype='uint8').astype(bool)
            a=inner&eligible;b=outer&eligible
            item={'source_id':fid,'vector_area_m2':g.area,'inside_eligible_cells':int(a.sum()),'ring_eligible_cells':int(b.sum())}
            for name,band in [('ponding',5),('concentration',6),('combined',7)]:
                for suffix,mask in [('inside',a),('ring',b)]:
                    vals=data[band][mask]
                    item[f'{name}_{suffix}_p50']=float(np.median(vals)) if vals.size else None
                    item[f'{name}_{suffix}_ge70_pct']=100*int((vals>=70).sum())/vals.size if vals.size else None
            per_feature.append(item)
        paired={}
        for name in ['ponding','concentration','combined']:
            rows=[a for a in per_feature if a[f'{name}_inside_p50'] is not None and a[f'{name}_ring_p50'] is not None]
            delta=np.array([a[f'{name}_inside_p50']-a[f'{name}_ring_p50'] for a in rows])
            paired[name]={'pair_count':len(rows),'median_score_inside_minus_ring':summary(delta),
                          'inside_median_greater_count':int((delta>0).sum()),'equal_count':int((delta==0).sum()),
                          'inside_median_less_count':int((delta<0).sum())}
        grid_info={'crs':str(src.crs),'source_shape':list(src.shape),'source_transform':list(src.transform)[:6],
                   'window':dict(col_off=int(w.col_off),row_off=int(w.row_off),width=int(w.width),height=int(w.height)),
                   'window_bounds_epsg7801':list(window_bounds(w,src.transform)),'cell_area_m2':25,'raster_membership':'cell centre; all_touched=False'}
    del data,water_values,labels,known,excluded,eligible,uncertain,inner,outer,a,b
    print('Computing exact cadastral intersections using read-only spatial index',flush=True)
    c=sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro',uri=True);c.execute('pragma cache_size=-16384')
    q=region_ll.bounds
    rows=c.execute('select f.source_id,f.properties,f.geometry from features f join feature_bounds r using(fid) where r.maxx>=? and r.minx<=? and r.maxy>=? and r.miny<=?',(q[0],q[2],q[1],q[3]))
    buildings={name:{'record_count':0,'cadastral_ids':set(),'clipped_areas':[],'pieces':[]} for name in zones}
    historical_per={fid:{'intersecting_record_count':0,'positive_area_record_count':0,'footprint_overlap_area_sum_m2':0.} for fid,_ in hist_features}
    candidate_count=0
    for sid,ptext,wkb in rows:
        candidate_count+=1;g=transform(XY.transform,from_wkb(wkb));props=json.loads(ptext)
        for name,z in zones.items():
            if not g.intersects(z):continue
            clip=g.intersection(z)
            if clip.area<=0:continue
            item=buildings[name];item['record_count']+=1
            if props.get('cadastral_id'):item['cadastral_ids'].add(props['cadastral_id'])
            item['clipped_areas'].append(clip.area);item['pieces'].append(clip)
        if g.intersects(union):
            for fid,hg in hist_features:
                if not g.intersects(hg):continue
                historical_per[fid]['intersecting_record_count']+=1
                area=g.intersection(hg).area
                if area>0:
                    historical_per[fid]['positive_area_record_count']+=1
                    historical_per[fid]['footprint_overlap_area_sum_m2']+=area
    for name,item in buildings.items():
        area=unary_union(item.pop('pieces')).area
        item['distinct_cadastral_id_count']=len(item.pop('cadastral_ids'))
        item['summed_record_footprint_overlap_area_m2']=float(sum(item.pop('clipped_areas')))
        item['union_footprint_overlap_area_m2']=float(area)
        item['zone_footprint_area_fraction']=float(area/zones[name].area)
    c.close()
    print('Cadastral statistics complete; inspecting supplied green/sewer/point context',flush=True)
    green_geoms=[];green_count=0;green_total=0;green_repair=0
    for f in features_stream(green_path):
        green_total+=1
        if not f.get('geometry'):continue
        gll=shape(f['geometry'])
        if not gll.intersects(region_ll):continue
        g=transform(XY.transform,gll)
        if not g.is_valid:
            from shapely import make_valid
            g=make_valid(g);green_repair+=1
        if g.intersects(region):green_count+=1;green_geoms.append(g.intersection(region))
    greens=unary_union(green_geoms)
    green_stats={name:{'overlap_area_m2':float(greens.intersection(z).area),'zone_area_fraction':float(greens.intersection(z).area/z.area)} for name,z in zones.items()}
    sewer_path=APP/'data/derived/sewer_routes_all.geojson';routes=read('data/derived/sewer_routes_all.geojson')
    sewer_stats={name:{'intersecting_source_route_count':0,'length_inside_m':0.} for name in zones}
    for f in routes['features']:
        if not f.get('geometry'):continue
        g=transform(XY.transform,shape(f['geometry']))
        if not g.intersects(region):continue
        for name,z in zones.items():
            clip=g.intersection(z)
            if clip.length>0:sewer_stats[name]['intersecting_source_route_count']+=1;sewer_stats[name]['length_inside_m']+=clip.length
    point_stats={name:{} for name in zones};points_total=0;points_in_region=0
    with (APP/'data/raw/sofia_infrastructure_points.csv').open(newline='',encoding='utf-8-sig') as f:
        from shapely.geometry import Point
        for p in csv.DictReader(f):
            points_total+=1
            lon,lat=float(p['longitude']),float(p['latitude'])
            if not(q[0]<=lon<=q[2] and q[1]<=lat<=q[3]):continue
            pt=Point(*XY.transform(lon,lat))
            if not region.covers(pt):continue
            points_in_region+=1
            for name,z in zones.items():
                if z.covers(pt):point_stats[name][p['type']]=point_stats[name].get(p['type'],0)+1
    rain_meta=read('data/cache/rainfall_meta.json');rain={}
    for name,p in rain_meta['products'].items():
        path=APP/'data/rainfall'/({'merged_250m':'merged_250m.tif','corrected_250m':'radar_bias_corrected_250m.tif','radar_bias_corrected_250m':'radar_bias_corrected_250m.tif','raw_1km':'radar_raw_1km.tif','radar_raw_1km':'radar_raw_1km.tif'}.get(name,name+'.tif'))
        if not path.exists():continue
        with rasterio.open(path) as src:
            v=src.read(1,masked=True);mask=rasterize([(mapping(transform(LL.transform,union)),1)],out_shape=src.shape,transform=src.transform,dtype='uint8').astype(bool)
            bounds_overlap=box(*src.bounds).intersection(transform(LL.transform,union))
            rain[name]={'bbox':list(src.bounds),'native_shape':list(src.shape),'native_cell_centres_in_historical_union':int(mask.sum()),
                        'valid_cell_centres_in_union':int((mask&~np.ma.getmaskarray(v)).sum()),
                        'native_values_in_union_mm':summary(v.data[mask&~np.ma.getmaskarray(v)]),
                        'historical_vector_area_inside_product_bounds_m2':float(transform(XY.transform,bounds_overlap).area) if not bounds_overlap.is_empty else 0.,
                        'temporal_join_valid':False,'reason':'27 June2025 daily product is not the January/February2021 surveyed flood event'}
    changed=[]
    for p in tracked:
        old=before[source_key(p)]
        if p.stat().st_size!=old['size_bytes'] or p.stat().st_mtime_ns!=old['mtime_ns'] or digest(p)!=old['sha256']:changed.append(str(p))
    if changed:raise RuntimeError('Source changed during analysis: '+str(changed))
    result={'schema_version':1,'analysis':'descriptive-index-refinement-evidence-v1','analysed_utc':stamp,
      'production_scores_changed':False,'all_sources_unchanged':True,'source_hashes':before,
      'historical_evidence':{'source_url':read('data/cache/historical_flood_zones_meta.json')['source_url'],'feature_count':len(hist_features),
          'feature_sum_area_m2':float(sum(g.area for _,g in hist_features)),'union_area_m2':float(union.area),
          'overlap_area_removed_m2':float(sum(g.area for _,g in hist_features)-union.area),
          'date':'2021; January/February discrepancy; no per-feature date','mechanism':'mixed river/rainfall/snowmelt context; not labelled pure pluvial',
          'spatial_controls_status':'No known-negative survey footprint; surrounding rings are descriptive comparison areas only'},
      'method':{'grid':grid_info,'rings_m':[0,50,250,500],'eligibility':'known ground elevation, watermask0, boundaryflag0, valid originalP/C/S; water takes precedence over uncertainty',
          'per_feature_ring':'feature.buffer250 minus entire historicalunion.buffer50; may overlap other comparison rings, paired summaries do not claim independent observations',
          'scores':'unaltered original 0..100 P,C,S; existing50/70/85 exploratory classes, not calibrated probabilities',
          'building_exposure':'positive-area intersection of actual current snapshot footprint with historical zone; not proof of damage or building existence during2021',
          'footprint_proxy':'union cadastral footprints / exact metric zone area; building coverage only, not total imperviousness or runoff coefficient',
          'green':'all original green polygons streamed, intersected and unioned; invalid local geometries make_valid only in temporary analysis memory; label not measured infiltration',
          'sewer':'original full routes, metric intersection length only; no capacity model','source_preservation':'full SHA256 and stat before/after for every listed source'},
      'zone_profiles':zone_profiles,'paired_polygon_comparison':paired,'per_polygon':per_feature,
      'buildings':{'index_total_records':334033,'candidate_bbox_record_count':candidate_count,'by_zone':buildings,'per_historical_polygon':historical_per},
      'green':{'source_features_streamed':green_total,'regional_features':green_count,'temporary_geometry_repairs':green_repair,'by_zone':green_stats},
      'sewer':{'source_route_count':len(routes['features']),'by_zone':sewer_stats},
      'infrastructure_points':{'source_records':points_total,'regional_records':points_in_region,'by_zone_type':point_stats},
      'rainfall':{'period':rain_meta['period'],'products':rain},
      'historical_register':{'source_rows':19,'unique_event_ids':15,'period':'2020–2024','spatial_support':'text descriptions; not geocoded or joined as point labels'},
      'runtime_seconds':round(time.time()-start,3),'script_file':'scripts/analyze_index_refinement.py'}
    legacy=read('data/derived/summary.json')
    result['logical_dependency_audit']={'terrain_score_inputs':['depression_fill_depth_m','slope_degrees','D8_contributing_area_m2','upstream_boundary_flag'],
      'context_or_exposure_not_score_inputs':['green_polygons','sewer_routes_and_point_density','buildings','rainfall','historical_polygons'],
      'global_green_source_records':legacy['raw_green_features'],'nonempty_green_source_records':legacy['nonempty_green_features'],
      'former_display_subset':legacy['visible_green_features'],'all_green_used_in_existing_route_partition':True,
      'source_route_records':legacy['raw_pipe_features'],'route_status_counts':legacy['source_status_counts'],
      'zone_feature_counts':legacy['zone_feature_counts'],
      'routes_in_both_green_parts':legacy['zone_feature_counts']['inside']+legacy['zone_feature_counts']['outside']-legacy['zone_feature_counts']['all'],
      'zone_length_geodesic_m':legacy['zone_length_m'],'inside_length_pct':100*legacy['zone_length_m']['inside']/legacy['zone_length_m']['all'],
      'partition_error_m':legacy['partition_error_m'],'clogging_probability_available':False,
      'missing':['verified connected pipe graph','pipe diameters','invert and outfall levels','inlet condition','maintenance/inspection observations','subhourly rainfall hyetograph']}
    review_path=APP/'data/cache/review_priority_meta.json'
    if review_path.exists():
        review=json.loads(review_path.read_text(encoding='utf-8'))
        result['compatible_time_scenario_assumption']=review['scenario_assumption']
        result['review_priority_product']={'revision':review['revision'],'metadata_file':'data/cache/review_priority_meta.json','raster_file':review['output_file'],'native_values_unchanged':True}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'runtime_seconds':result['runtime_seconds'],'zone_profiles':zone_profiles,'paired':paired,'buildings':buildings,'rainfall':rain},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
