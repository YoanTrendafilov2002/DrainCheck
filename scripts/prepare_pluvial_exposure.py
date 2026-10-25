"""Join actual infrastructure records to the terrain screening grid, without a loss model.

Points are source records, not verified unique assets. Routes are historical geometry,
not working storm drains. Green polygons do not establish infiltration capacity.
All source datasets are opened read-only; only derived CSV/JSON files are written.
"""
import csv, hashlib, json, math, sqlite3,sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import Transformer, Geod
from shapely import from_wkb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.pluvial import LocalPluvial
from backend.open_water import OpenWaterMask
from backend.screening_exclusions import ScreeningExclusions
CACHE=ROOT/'data/cache'
LABELS=['Lower signal','Raised','Higher signal','Strongest signal','Uncertain terrain','No terrain data','Excluded open water','Excluded river channel / stadium']
MODES={'ponding':6,'concentration':7,'combined':8}
XY=Transformer.from_crs(4326,7801,always_xy=True)
GEOD=Geod(ellps='WGS84')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def classes(scores,flags):
    # Score thresholds are exploratory display choices, never probability cutoffs.
    code=np.searchsorted([50,70,85],scores,side='right').astype('uint8')
    missing=~np.isfinite(scores)|(scores<0)
    code[missing]=5
    code[flags>0]=4
    code[(flags&4)>0]=6
    code[(flags&8)>0]=7
    return code

def sample_grid_modes(src,lon,lat,water_src=None,exclusion_src=None):
    """Read actual base-resolution cells in grouped blocks; never interpolate scores."""
    if water_src is None:
        water=OpenWaterMask(CACHE)
        if not water.available:raise ValueError(water.error)
        with rasterio.open(water.path) as mask:return sample_grid_modes(src,lon,lat,mask,exclusion_src)
    if exclusion_src is None:
        exclusions=ScreeningExclusions(CACHE)
        if not exclusions.available:raise ValueError(exclusions.error)
        with rasterio.open(exclusions.path) as mask:return sample_grid_modes(src,lon,lat,water_src,mask)
    x,y=XY.transform(np.asarray(lon),np.asarray(lat))
    col=np.floor((x-src.transform.c)/src.transform.a).astype('int64')
    row=np.floor((y-src.transform.f)/src.transform.e).astype('int64')
    results={mode:np.full(len(col),-9999.,dtype='float32') for mode in MODES}
    flags={mode:np.zeros(len(col),dtype='uint8') for mode in MODES}
    inside=(row>=0)&(col>=0)&(row<src.height)&(col<src.width)
    ids=np.flatnonzero(inside)
    keys=(row[ids]//512)*(math.ceil(src.width/512))+col[ids]//512
    order=np.argsort(keys);ids=ids[order];keys=keys[order]
    for part in np.split(ids,np.flatnonzero(np.diff(keys))+1):
        if not len(part):continue
        r0=int(row[part[0]]//512*512);c0=int(col[part[0]]//512*512)
        a=src.read([1,5,6,7,8],window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))
        terrain=a[0,row[part]-r0,col[part]-c0]
        flag=a[1,row[part]-r0,col[part]-c0]
        water=water_src.read(1,window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))[row[part]-r0,col[part]-c0]
        policy=exclusion_src.read(1,window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))[row[part]-r0,col[part]-c0]
        for i,mode in enumerate(MODES):
            scores=a[i+2,row[part]-r0,col[part]-c0]
            flags[mode][part]=(flag==1).astype('uint8')
            flags[mode][part[(terrain!=-9999)&np.isfinite(terrain)&((scores<0)|~np.isfinite(scores))&(flag!=1)]]=2
            flags[mode][part[water==1]]|=4
            flags[mode][part[policy>0]]|=8
            results[mode][part]=scores
    return results,flags

def sample_grid(src,lon,lat,mode='combined'):
    """Backwards-compatible single-mode adapter, always using real base pixels."""
    if mode not in MODES:raise ValueError('Unknown screening mode')
    results,flags=sample_grid_modes(src,lon,lat)
    return results[mode],flags[mode]

def terrain_summaries(src,water_src,exclusion_src=None):
    """Full base-resolution cell counts per mode; outside coverage is not lower signal."""
    if exclusion_src is None:
        exclusions=ScreeningExclusions(CACHE)
        if not exclusions.available:raise ValueError(exclusions.error)
        with rasterio.open(exclusions.path) as mask:return terrain_summaries(src,water_src,mask)
    counts={mode:np.zeros(len(LABELS),dtype='int64') for mode in MODES}
    sensitivity={mode:np.zeros(3,dtype='int64') for mode in MODES}
    terrain_count=0
    for r0 in range(0,src.height,512):
        for c0 in range(0,src.width,512):
            a=src.read([1,5,6,7,8],window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))
            known=np.isfinite(a[0])&(a[0]!=-9999)
            water=water_src.read(1,window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))
            policy=exclusion_src.read(1,window=Window(c0,r0,min(512,src.width-c0),min(512,src.height-r0)))
            terrain_count+=int(known.sum())
            for i,mode in enumerate(MODES):
                score=a[i+2];flag=(a[1]==1).astype('uint8')
                flag[known&((score<0)|~np.isfinite(score))&(a[1]!=1)]=2
                flag[water==1]|=4
                flag[policy>0]|=8
                code=classes(score,flag)
                counts[mode]+=np.bincount(code[known],minlength=len(LABELS))
                for j,t in enumerate([70,80,90]):
                    sensitivity[mode][j]+=int((known&(code<4)&(score>=t)).sum())
    result={}
    for mode in MODES:
        eligible=int(counts[mode][:4].sum())
        result[mode]={'terrain_cells':terrain_count,'eligible_cells':eligible,
            'uncertain_cells':int(counts[mode][4]),'no_terrain_data_cells':int(counts[mode][5]),
            'water_excluded_cells':int(counts[mode][6]),
            'screening_policy_excluded_cells':int(counts[mode][7]),
            'classes':[{'label':label,'cells':int(counts[mode][i]),'area_km2':float(counts[mode][i]*25/1e6)} for i,label in enumerate(LABELS)],
            'sensitivity':[{'threshold':t,'cells':int(sensitivity[mode][j]),'area_km2':float(sensitivity[mode][j]*25/1e6),
                            'percent_eligible':float(sensitivity[mode][j]/eligible*100) if eligible else None} for j,t in enumerate([70,80,90])]}
    return result

def export_land_raster(src,water_src,meta,exclusion_src=None):
    """Separate download product; original factors/scores are never overwritten."""
    if exclusion_src is None:
        exclusions=ScreeningExclusions(CACHE)
        if not exclusions.available:raise ValueError(exclusions.error)
        with rasterio.open(exclusions.path) as mask:return export_land_raster(src,water_src,meta,mask)
    output=ROOT/'data/derived/pluvial_land_screening_5m.tif';pending=output.with_suffix('.pending.tif')
    profile=src.profile.copy();profile.update(count=5,compress='DEFLATE',predictor=3,interleave='band',tiled=True,
        blockxsize=512,blockysize=512,bigtiff='IF_SAFER',nodata=-9999)
    names=['ponding_score_0_100','concentration_score_0_100','combined_score_0_100','open_water_excluded','user_screening_exclusion_flags']
    with rasterio.open(pending,'w',**profile) as dst:
        for i,name in enumerate(names,1):dst.set_band_description(i,name)
        dst.update_tags(SCREENING_REVISION=meta['revision'],TERRAIN_REVISION=meta['terrain_revision'],
            OPEN_WATER_REVISION=meta['water_exclusion']['revision'],VERTICAL_DATUM='Baltic 1982',
            SCREENING_EXCLUSIONS_REVISION=meta['screening_exclusions']['revision'],
            POLICY='Mapped water, river channels and stadiums are NoData in score bands, never zero or safe; no hydrology recomputed. User flags:1=river,2=stadium,3=both.')
        for _,window in src.block_windows(1):
            a=src.read([1,6,7,8],window=window);water=water_src.read(1,window=window)
            policy=exclusion_src.read(1,window=window)
            known=np.isfinite(a[0])&(a[0]!=-9999);scores=a[1:].copy();scores[:,(water==1)|(policy>0)]=-9999
            flag=np.where(known,water.astype('float32'),np.float32(-9999))
            policy_flag=np.where(known,policy.astype('float32'),np.float32(-9999))
            dst.write(np.concatenate((scores,flag[None,:,:],policy_flag[None,:,:])),window=window)
    # Full verification proves land scores are unchanged and water scores excluded.
    with rasterio.open(pending) as exported:
        for _,window in src.block_windows(1):
            a=src.read([1,6,7,8],window=window);water=water_src.read(1,window=window);out=exported.read(window=window)
            policy=exclusion_src.read(1,window=window);excluded=(water==1)|(policy>0)
            if not np.array_equal(out[:3,~excluded],a[1:,~excluded],equal_nan=True):raise AssertionError('Nonexcluded land scores changed in export')
            if np.any(out[:3,excluded]!=-9999):raise AssertionError('Excluded footprint retains a score in export')
            known=np.isfinite(a[0])&(a[0]!=-9999)
            if not np.array_equal(out[3],np.where(known,water.astype('float32'),np.float32(-9999))):raise AssertionError('Export water flag differs from source mask')
            if not np.array_equal(out[4],np.where(known,policy.astype('float32'),np.float32(-9999))):raise AssertionError('Export policy flag differs from source mask')
    pending.replace(output)
    receipt={'pluvial_revision':meta['revision'],'terrain_revision':meta['terrain_revision'],
        'open_water_revision':meta['water_exclusion']['revision'],'output_sha256':digest(output),
        'screening_exclusions_revision':meta['screening_exclusions']['revision'],'screening_exclusions_sha256':meta['screening_exclusions']['sha256'],
        'source_sha256':meta['verification']['output_sha256'],'open_water_sha256':meta['water_exclusion']['sha256'],
        'grid':meta['grid'],'bands':names,'nodata':-9999,
        'policy':'Score bands equal original scores outside all exclusions and NoData over mapped water, channels and stadiums. Flags are NoData outside known terrain; zero is not a safety conclusion. Policy flags:1=river,2=stadium,3=both.',
        'verification':{'all_nonexcluded_land_score_pixels_identical':True,'all_water_score_pixels_nodata':True,'all_policy_score_pixels_nodata':True,'all_flag_pixels_match':True}}
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt

def route_samples(geometry,spacing=2.5):
    """Midpoint quadrature <=2.5 projected metres; lengths preserve source traversals.

    Assignment to a 5m cell is approximate at grid boundaries. Length per original
    WGS84 segment comes from Geod, so total route length retains its source measure.
    """
    lon=[];lat=[];length=[]
    parts=[geometry] if geometry.geom_type=='LineString' else list(geometry.geoms)
    for part in parts:
        coords=np.asarray(part.coords)
        if len(coords)<2:continue
        x,y=XY.transform(coords[:,0],coords[:,1])
        _,_,metres=GEOD.inv(coords[:-1,0],coords[:-1,1],coords[1:,0],coords[1:,1])
        for i,m in enumerate(metres):
            count=max(1,int(math.ceil(math.hypot(x[i+1]-x[i],y[i+1]-y[i])/spacing)))
            t=(np.arange(count)+.5)/count
            lon.extend(coords[i,0]+t*(coords[i+1,0]-coords[i,0]))
            lat.extend(coords[i,1]+t*(coords[i+1,1]-coords[i,1]))
            length.extend(np.full(count,float(m)/count))
    return np.asarray(lon),np.asarray(lat),np.asarray(length)

def main():
    raster=CACHE/'pluvial_5m.tif'
    pluvial=LocalPluvial(CACHE);meta=pluvial.meta()
    if not meta.get('available'):raise ValueError(meta.get('message','Screening or required water mask unavailable'))
    source_sha256=digest(raster)
    if source_sha256!=meta['verification']['output_sha256']:raise ValueError('Original screening source checksum differs from its verified receipt')
    source=ROOT/'data/raw/sofia_infrastructure_points.csv'
    records=list(csv.DictReader(source.open(encoding='utf-8',newline='')))
    lon=np.array([float(r['longitude']) for r in records]);lat=np.array([float(r['latitude']) for r in records])
    with rasterio.Env(GDAL_CACHEMAX=128000000),rasterio.open(raster,OVERVIEW_LEVEL='NONE') as src,rasterio.open(pluvial.water.path) as water_src:
        assert src.crs.to_epsg()==7801 and src.count==8 and src.transform.a==5
        scores,flags=sample_grid_modes(src,lon,lat,water_src)
        codes={mode:classes(scores[mode],flags[mode]) for mode in MODES}
        categories={mode:{} for mode in MODES}
        config=json.loads((ROOT/'config/map_config.json').read_text(encoding='utf-8'))
        labels={str(c['code']) if c['code'] is not None else 'missing':c['label'] for c in config['infrastructure']['categories']}
        out=ROOT/'data/derived/infrastructure_terrain_screening.csv'
        with out.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(['source_record_id','longitude','latitude','category','terrain_score_0_100','terrain_signal_class','boundary_influence','open_water_excluded','screening_policy_excluded',
                'ponding_score_0_100','ponding_signal_class','concentration_score_0_100','concentration_signal_class',
                'combined_score_0_100','combined_signal_class','interpretation'])
            for i,r in enumerate(records):
                category=str(int(float(r['type']))) if r['type'].strip() else 'missing'
                values=[]
                for mode in MODES:
                    categories[mode].setdefault(category,np.zeros(len(LABELS),dtype='int64'))[codes[mode][i]]+=1
                    values.extend([float(scores[mode][i]) if codes[mode][i]<4 else '',LABELS[codes[mode][i]]])
                combined_code=codes['combined'][i]
                writer.writerow([i+1,r['longitude'],r['latitude'],category,float(scores['combined'][i]) if combined_code<4 else '',
                    LABELS[combined_code],int((flags['combined'][i]&1)>0),int((flags['combined'][i]&4)>0),int((flags['combined'][i]&8)>0),*values,
                    'Spatial overlap only; not confirmed damage or flood probability'])
        print(json.dumps({'stage':'points_joined','records':len(records),'classes':{mode:dict(zip(LABELS,np.bincount(codes[mode],minlength=len(LABELS)).tolist())) for mode in MODES}}),flush=True)
        db=sqlite3.connect('file:'+(CACHE/'spatial.sqlite').as_posix()+'?mode=ro',uri=True)
        rows=db.execute("SELECT source_id,status,properties,geometry FROM features WHERE kind='routes' AND zone='all' ORDER BY source_id").fetchall()
        all_lon=[];all_lat=[];all_length=[];route_status=[];spans=[]
        for sid,status,props,wkb in rows:
            lons,lats,metres=route_samples(from_wkb(wkb))
            start=len(all_length)
            all_lon.extend(lons);all_lat.extend(lats);all_length.extend(metres)
            spans.append((start,len(all_length)))
            route_status.extend([status]*len(metres))
        db.close()
        rscores,rflags=sample_grid_modes(src,all_lon,all_lat,water_src)
        rcodes={mode:classes(rscores[mode],rflags[mode]) for mode in MODES}
        lengths=np.asarray(all_length);statuses=np.asarray(route_status)
        route_by_status={mode:{s:{LABELS[i]:float(lengths[(rcodes[mode]==i)&(statuses==s)].sum()) for i in range(len(LABELS))} for s in ['existing','planned','open']} for mode in MODES}
        with (ROOT/'data/derived/sewer_route_terrain_screening.csv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(['screening_mode','source_route_id','source_status','source_year','terrain_signal_class','approximate_length_m','interpretation'])
            for mode in MODES:
                for (sid,status,props,wkb),(start,end) in zip(rows,spans):
                    by_class=np.bincount(rcodes[mode][start:end],weights=lengths[start:end],minlength=len(LABELS))
                    # Explicit zero rows retain all717 full source routes in every mode.
                    for i in range(len(LABELS)):
                        writer.writerow([mode,sid,status,2009,LABELS[i],float(by_class[i]),'Geometric overlap; not drainage capacity or service failure'])
        print(json.dumps({'stage':'full_grid_counts_all_modes'}),flush=True)
        terrain_by_mode=terrain_summaries(src,water_src)
        print(json.dumps({'stage':'export_land_only_scores'}),flush=True)
        export_receipt=export_land_raster(src,water_src,meta)
    modes={}
    for mode in MODES:
        total=np.bincount(codes[mode],minlength=len(LABELS))
        modes[mode]={'mode':mode,
            'by_class':{name:{'point_count':int(total[i]),'route_length_m':float(lengths[rcodes[mode]==i].sum())} for i,name in enumerate(LABELS)},
            'categories':[{'category':c,'label':labels.get(c,c),'count':int(v.sum()),'classes':dict(zip(LABELS,v.tolist()))} for c,v in sorted(categories[mode].items())],
            'routes':{'source_count':len(rows),'source_year':2009,'length_m':float(lengths.sum()),'by_status':route_by_status[mode],
                      'method':'Original WGS84 segment geodesic lengths, assigned using midpoint samples at <=2.5 projected metres. Approximate at 5m cell boundaries; traversal multiplicity retained.'},
            'sensitivity':[{'threshold':t,'point_records_at_or_above':int(((scores[mode]>=t)&(codes[mode]<4)).sum()),
                            'route_length_m_at_or_above':float(lengths[(rscores[mode]>=t)&(rcodes[mode]<4)].sum())} for t in [70,80,90]]}
    if digest(raster)!=source_sha256:raise AssertionError('Original screening source changed during water-exclusion preparation')
    if digest(pluvial.water.path)!=meta['water_exclusion']['sha256']:raise AssertionError('Water mask changed during preparation')
    if digest(pluvial.exclusions.path)!=meta['screening_exclusions']['sha256']:raise AssertionError('Screening-exclusion mask changed during preparation')
    result={'dataset_revision':(CACHE/'revision.txt').read_text().strip(),'pluvial_revision':meta['revision'],
            'terrain_revision':meta['terrain_revision'],'open_water_revision':meta['water_exclusion']['revision'],
            'screening_exclusions_revision':meta['screening_exclusions']['revision'],'screening_exclusions':meta['screening_exclusions'],
            'water_exclusion':meta['water_exclusion'],'land_raster_export':export_receipt,
            'interpretation':'Potential exposure by geometric overlap with an unvalidated terrain index; no loss, probability, vulnerability or drainage-capacity calculation.',
            'scope':'All 322,025 source point records and all 717 full source routes. Independent of current map layer, route-zone and status filters.',
            'classes':LABELS,'thresholds':[50,70,85],'default_mode':'ponding',
            'modes':modes,'terrain_by_mode':terrain_by_mode,
            # Keep explicit combined compatibility fields for older downloaded clients.
            **{key:modes['combined'][key] for key in ['by_class','categories','routes','sensitivity']},
            'sources':{'points_sha256':digest(source),'raster_sha256':source_sha256,'open_water_sha256':meta['water_exclusion']['sha256'],'screening_exclusions_sha256':meta['screening_exclusions']['sha256'],
                       'original_screening_sha256_unchanged_before_after':True},
            'limitations':['Point records may contain repeated coordinates or multiple records per asset; counts are not unique buildings, residents or damaged assets.',
                          '2009 sewer routes do not establish current connectivity, capacity, drain inlets or condition.',
                          'Green area geometry is contextual; no infiltration credit or protection factor was assumed.',
                          'Uncertain terrain and NoData are retained as separate classes and never counted as lower signal.',
                          'Mapped existing open water is a separate excluded inventory bucket; it is not assigned a low or safe score. Unmapped waterways may remain; no line buffers or upstream terrain changes are inferred.',
                          'Mapped river channels and stadium footprints are a separate, higher-precedence user-policy exclusion bucket; exclusion does not establish safety and original terrain remains unchanged.',
                          'D8 concentration and combined scores contain strong grid/facet routing artefacts. Exposure overlaps for those experimental modes are especially sensitive to the routing method; they are not verified flood priorities.']}
    for mode in MODES:
        assert sum(v['point_count'] for v in modes[mode]['by_class'].values())==322025
        assert math.isclose(sum(v['route_length_m'] for v in modes[mode]['by_class'].values()),float(lengths.sum()),abs_tol=1e-7)
        assert sum(c['cells'] for c in terrain_by_mode[mode]['classes'])==terrain_by_mode[mode]['terrain_cells']
    (CACHE/'pluvial_exposure.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'stage':'exposure_ready','points':len(records),'routes':len(rows),'length_m':float(lengths.sum())}),flush=True)

if __name__=='__main__':main()
