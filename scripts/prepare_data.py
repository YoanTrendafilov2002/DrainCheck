"""Index real input vectors/points and derive display/statistics from native DTM.
Originals are only read. Run from the app root: python scripts/prepare_data.py.
"""
import argparse,csv,gc,hashlib,json,math,os,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.transform import Affine
from shapely.geometry import shape,Point
from shapely import make_valid,to_wkb
from pyproj import CRS
from dotenv import load_dotenv
from backend.scale import knots,legend
from scripts.restore_reference_scale import restore_reference_scale

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
CACHE=ROOT/'data/cache';CACHE.mkdir(parents=True,exist_ok=True)
DTM=Path(os.environ.get('SOFIA_DTM_PATH',str(ROOT.parent/'sofia_dtm_2024_1m_gee.tif')))
if not DTM.is_absolute():DTM=ROOT/DTM

def log(stage,**details):print(json.dumps({'stage':stage,**details}),flush=True)
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def preflight():
    baseline=load(ROOT/'data/derived/summary.json');result={'archive_status':'truncated; CRC-verified complete entries recovered',
      'supplied_verify_handoff':'Not recoverable from truncated ZIP; cannot run',
      'supplied_scale_tests':'Not recoverable from truncated ZIP; cannot run',
      'original_script_snapshots':'Script1/Script2 not recoverable; original ZIP preserved',
      'archived_whole_area_curve':'Not recoverable; recompute 201 quantiles from actual native DTM',
      'independent_baseline_checks':[]}
    if (ROOT/'handoff/rainfall_supplement/MANIFEST.json').is_file():
        result.update(archive_status='Original truncated ZIP preserved; complete rainfall supplement also preserved and manifest verified separately',
          supplied_verify_handoff='Available: handoff/rainfall_supplement/scripts/verify_handoff.py',
          supplied_scale_tests='Available: handoff/rainfall_supplement/tests/elevation_scale.test.mjs',
          original_script_snapshots='Script1, Script2 and Rainfall_20250627_original.js preserved byte-for-byte in earth_engine/',
          archived_whole_area_curve='Complete supplied 201-point Earth Engine snapshot available in data/reference/')
    for zone in ['all','inside','outside']:
        features=load(ROOT/f'data/derived/sewer_routes_{zone}.geojson')['features']
        assert len(features)==baseline['zone_feature_counts'][zone]
        assert abs(sum(f['properties']['length_m'] for f in features)-baseline['zone_length_m'][zone])<.001
        result['independent_baseline_checks'].append({'zone':zone,'status':'PASS','count':len(features)})
    assert sum(baseline['source_status_counts'].values())==717
    for name,record in load(ROOT/'handoff/recovered_originals_manifest.json').items():
        assert digest(ROOT/name)==record['sha256'],name
    result['originals_unchanged']='PASS'
    (CACHE/'preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def vectors(rebuild=False):
    dbpath=CACHE/'spatial.sqlite'
    # Context and rainfall supplements must not trigger a rebuild of the legacy index.
    source_files=sorted(list((ROOT/'data/raw').glob('*'))+[ROOT/'data/derived'/name for name in
       ['green_intersecting_routes.geojson','sewer_routes_all.geojson','sewer_routes_inside.geojson','sewer_routes_outside.geojson']])
    input_hashes={str(p.relative_to(ROOT)):digest(p) for p in source_files if p.is_file()}
    previous=load(CACHE/'vector_provenance.json') if (CACHE/'vector_provenance.json').exists() else {}
    if dbpath.exists() and not rebuild and previous.get('input_sha256')==input_hashes:
        with sqlite3.connect(dbpath,timeout=60) as db:
            db.execute("CREATE INDEX IF NOT EXISTS green_display_lookup ON features(kind,display) WHERE kind='green' AND display=1")
        log('reuse_spatial_index');return
    # Build a separate staging DB, then atomically replace only the derived index.
    db=sqlite3.connect(CACHE/'spatial.build.sqlite')
    db.executescript('''DROP TABLE IF EXISTS features; DROP TABLE IF EXISTS feature_bounds;
      CREATE TABLE features(fid INTEGER PRIMARY KEY,kind TEXT NOT NULL,zone TEXT,status TEXT,
      source_id TEXT,properties TEXT,geometry BLOB,length_m REAL,display INTEGER);
      CREATE VIRTUAL TABLE feature_bounds USING rtree(fid,minx,maxx,miny,maxy);
      CREATE INDEX feature_lookup ON features(kind,zone,status,source_id);
      CREATE INDEX route_lookup ON features(source_id,zone);
      CREATE INDEX green_display_lookup ON features(kind,display) WHERE kind='green' AND display=1;''')
    fid=0
    def insert(kind,geometry,props,zone='',status='',display=0):
        nonlocal fid
        fid+=1
        bounds=geometry.bounds
        db.execute('INSERT INTO features VALUES(?,?,?,?,?,?,?,?,?)',
          (fid,kind,zone,status,str(props.get('source_id',props.get('id',fid))),
           json.dumps(props,ensure_ascii=False),to_wkb(geometry),float(props.get('length_m',0) or 0),display))
        db.execute('INSERT INTO feature_bounds VALUES(?,?,?,?,?)',(fid,bounds[0],bounds[2],bounds[1],bounds[3]))
    for zone in ['all','inside','outside']:
        log('index_routes',zone=zone)
        for f in load(ROOT/f'data/derived/sewer_routes_{zone}.geojson')['features']:
            insert('routes',shape(f['geometry']),f['properties'],zone,f['properties']['status'])
    display_ids={str(f['properties']['id']) for f in load(ROOT/'data/derived/green_intersecting_routes.geojson')['features']}
    greenfile=next((ROOT/'data/raw').glob('green_areas*.geojson'))
    green=load(greenfile);empty=[];repaired=[];green_count=0
    log('index_all_green_polygons',source_records=len(green['features']))
    for f in green['features']:
        geom=shape(f['geometry']) if f.get('geometry') else None
        props=dict(f['properties']);sid=str(props['id'])
        if geom is None or geom.is_empty:empty.append(sid);continue
        if not geom.is_valid:
            geom=make_valid(geom);repaired.append(sid)
        if geom.geom_type=='GeometryCollection':
            from shapely.geometry import MultiPolygon
            geom=MultiPolygon([g for g in geom.geoms if g.geom_type=='Polygon'])
        props.update(source_year=2020,geometry_repaired=sid in repaired)
        insert('green',geom,props,display=int(sid in display_ids));green_count+=1
    assert green_count==64956 and len(empty)==6 and len(repaired)==1
    del green;gc.collect()
    log('index_all_infrastructure_points')
    point_count=0;counts={}
    with (ROOT/'data/raw/sofia_infrastructure_points.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            point_count+=1
            code=str(int(float(row['type']))) if row['type'].strip() else 'missing'
            counts[code]=counts.get(code,0)+1
            props={'source_record_id':point_count,'category':code,'type':None if code=='missing' else int(code),
                   'longitude':float(row['longitude']),'latitude':float(row['latitude'])}
            insert('points',Point(props['longitude'],props['latitude']),props,status=code)
    assert point_count==322025 and counts['missing']==83
    db.commit();db.close()
    os.replace(CACHE/'spatial.build.sqlite',dbpath)
    provenance={'nonempty_green_count':green_count,'empty_source_ids':empty,'repaired_source_ids':repaired,
                'display_green_count':len(display_ids),'points_count':point_count,'point_categories':counts,
                'originals_unchanged':True,'clipping':'Prepared sections from handoff; all nonempty source greens used in analysis mask',
                'schema_version':'sofia-spatial-v1','input_sha256':input_hashes}
    (CACHE/'vector_provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    log('spatial_index_ready',bytes=dbpath.stat().st_size,**provenance)

def terrain():
    if not DTM.exists():log('native_dtm_unavailable',path=str(DTM));return
    with rasterio.open(DTM,OVERVIEW_LEVEL='NONE') as src:
        assert src.crs.to_epsg()==7801 and src.shape==(54343,51722) and src.count==1
        assert list(src.transform)[:6]==[1,0,299392,0,-1,4753611] and src.nodata==-9999
        assert not CRS(src.crs).is_compound
        native_hash=digest(DTM)
        previous=load(CACHE/'terrain_provenance.json') if (CACHE/'terrain_provenance.json').exists() else {}
        if previous and previous.get('native_dtm_sha256')!=native_hash:
            # Only disposable derivatives are invalidated; source rasters are read-only.
            for name in ['terrain_display_8m.tif','whole_scale.json']:
                path=CACHE/name
                if path.exists():path.unlink()
        display=CACHE/'terrain_display_8m.tif'
        if not display.exists():
            log('derive_display_overview_from_real_1m_dtm',spacing_m=8)
            height,width=math.ceil(src.height/8),math.ceil(src.width/8)
            transform=Affine(8,0,src.transform.c,0,-8,src.transform.f)
            a=np.full((height,width),-9999,dtype=np.float32)
            reproject(rasterio.band(src,1),a,src_transform=src.transform,src_crs=src.crs,
              src_nodata=-9999,dst_transform=transform,dst_crs=src.crs,dst_nodata=-9999,
              resampling=Resampling.average,num_threads=2,warp_mem_limit=128)
            with rasterio.open(display,'w',driver='GTiff',width=width,height=height,count=1,dtype='float32',
              crs=src.crs,transform=transform,nodata=-9999,tiled=True,blockxsize=256,blockysize=256,
              compress='deflate',predictor=3) as dst:
                dst.write(a,1);dst.update_tags(PURPOSE='WEB_DISPLAY_ONLY; native readouts use separate immutable 1 m source',VERTICAL_DATUM='Baltic 1982')
                dst.build_overviews([2,4,8,16,32],Resampling.average)
            del a;gc.collect()
        whole=CACHE/'whole_scale.json'
        if restore_reference_scale(ROOT,native_hash):log('supplied_whole_area_reference_restored')
        if not whole.exists():
            log('recompute_real_whole_area_201_quantiles',statistics_scale_m=60)
            h,w=math.ceil(src.height/60),math.ceil(src.width/60)
            a=np.full((h,w),-9999,dtype=np.float32)
            reproject(rasterio.band(src,1),a,src_transform=src.transform,src_crs=src.crs,src_nodata=-9999,
              dst_transform=Affine(60,0,src.transform.c,0,-60,src.transform.f),dst_crs=src.crs,
              dst_nodata=-9999,resampling=Resampling.average,num_threads=2,warp_mem_limit=128)
            q=np.quantile(a[(a!=-9999)&np.isfinite(a)],np.linspace(0,1,201)).tolist()
            heights,levels=knots(q)
            definition={'id':'whole','scope':'whole-study-area','quantiles':q,'heights':heights,'levels':levels,
                'statistics_scale_m':60,'native_sample_scale_m':1,'bbox':[23,42.4,23.7,42.95],
                'provenance':'Locally recomputed from native DTM because archived 201-point curve is in truncated ZIP tail; not the archived EE snapshot',
                'method':'201 continuous percentiles, 80% empirical percentile + 20% linear height; base-raster 60 m area averages',
                'valid_statistic_cells':int(np.count_nonzero(a!=-9999)),'source_sha256':native_hash}
            definition['legend']=legend(definition)
            whole.write_text(json.dumps(definition,indent=2),encoding='utf-8')
            log('whole_scale_ready',legend=definition['legend'])
        elif 'source_sha256' not in load(whole):
            existing=load(whole);existing['source_sha256']=native_hash
            whole.write_text(json.dumps(existing,indent=2),encoding='utf-8')
    sources={'native_dtm_sha256':native_hash,'native_dtm_bytes':DTM.stat().st_size,
             'native_dtm_basename':DTM.name,'native_grid_unchanged':True,
             'display_spacing_m':8,'native_sample_spacing_m':1,'display_native_switch_zoom':15}
    (CACHE/'terrain_provenance.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')

def refresh_data_revision():
    """Identify scientific source inputs independently of added display/context settings."""
    inputs={'vectors':load(CACHE/'vector_provenance.json').get('input_sha256',{}),
            'native_dtm_sha256':load(CACHE/'terrain_provenance.json').get('native_dtm_sha256')}
    fingerprint=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
    path=CACHE/'spatial_revision_inputs.json'
    previous=load(path) if path.is_file() else {}
    revision=previous['revision'] if previous.get('fingerprint')==fingerprint else fingerprint[:16]
    path.write_text(json.dumps({'fingerprint':fingerprint,'revision':revision,'inputs':inputs},indent=2),encoding='utf-8')
    (CACHE/'revision.txt').write_text(revision,encoding='ascii')
    return revision

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-only',action='store_true');parser.add_argument('--rebuild-vectors',action='store_true')
    args=parser.parse_args();log('preflight',result=preflight())
    if not args.preflight_only:
        with rasterio.Env(GDAL_CACHEMAX=128000000,PROJ_NETWORK='OFF'):
            vectors(args.rebuild_vectors);terrain()
        revision=refresh_data_revision()
        log('preparation_complete',revision=revision)
