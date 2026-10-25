"""Index acquired real building footprints separately from the source GIS/terrain.

No download, height inference, hydrological change or substitute building occurs.
"""
import argparse,json,sqlite3,sys
from contextlib import closing
from pathlib import Path
import shapely
from shapely.geometry import shape
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.context_layers import sha256

def prepare_stream(geojson,meta_path,output,feature_lines):
    """Bounded-memory indexing of an acquisition's equivalent NDJSON stream.

    The GeoJSON remains the portable display/download source. SQLite sorts IDs
    on disk, retaining the same deterministic IDs as the existing small builder.
    """
    geojson,meta_path,output,feature_lines=map(Path,(geojson,meta_path,output,feature_lines))
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    if not meta.get('available') or not meta.get('revision'):raise ValueError('A real acquired building source and revision are required')
    if not meta.get('feature_lines_sha256') or sha256(feature_lines)!=meta['feature_lines_sha256']:
        raise ValueError('Streaming features differ from the acquisition receipt')
    original_hash=sha256(geojson);output.parent.mkdir(parents=True,exist_ok=True)
    pending=output.with_suffix('.pending.sqlite')
    if pending.exists():pending.unlink()
    repaired=[];count=0;height=meta.get('height',{})
    verified=height.get('available') is True and height.get('semantics')=='height_above_ground_m'
    with closing(sqlite3.connect(pending)) as db,db:
        db.executescript('''PRAGMA temp_store=FILE; PRAGMA cache_size=-16384;
          CREATE TABLE staging(source_id TEXT PRIMARY KEY,properties TEXT NOT NULL,geometry BLOB NOT NULL,
            minx REAL,maxx REAL,miny REAL,maxy REAL);
          CREATE TABLE features(fid INTEGER PRIMARY KEY,source_id TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,
            properties TEXT NOT NULL,geometry BLOB NOT NULL);
          CREATE VIRTUAL TABLE feature_bounds USING rtree(fid,minx,maxx,miny,maxy);
          CREATE INDEX feature_kind ON features(kind);
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
        with feature_lines.open(encoding='utf-8') as stream:
            for line in stream:
                if not line.strip():continue
                feature=json.loads(line);props=dict(feature.get('properties') or {})
                source_id=str(props.get('source_id',feature.get('id','')))
                if not source_id:raise ValueError('Building source IDs must be present and unique')
                props.update(source_id=source_id,context_kind='buildings')
                if not verified and 'height_m' in props:props['source_height_m']=props.pop('height_m')
                if verified and props.get('height_m') is not None:
                    import math
                    value=props['height_m']
                    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                        raise ValueError('Verified building height must be finite nonnegative metres')
                geometry=shapely.force_2d(shape(feature['geometry']))
                if geometry.is_empty or geometry.geom_type not in ('Polygon','MultiPolygon'):raise ValueError('Real polygon building footprints required')
                if not geometry.is_valid:geometry=shapely.make_valid(geometry);repaired.append(source_id)
                if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon'):
                    raise ValueError('Building footprint has no valid polygon after documented repair')
                west,south,east,north=geometry.bounds
                if not (-180<=west<=east<=180 and -90<=south<=north<=90):raise ValueError('Building footprints are not WGS84 longitude/latitude')
                try:db.execute('INSERT INTO staging VALUES(?,?,?,?,?,?,?)',(source_id,json.dumps(props,ensure_ascii=False,allow_nan=False),shapely.to_wkb(geometry),west,east,south,north))
                except sqlite3.IntegrityError as error:raise ValueError('Building source IDs must be present and unique') from error
                count+=1
                if count%2000==0:db.commit()
        if not count or count!=int(meta.get('feature_count',-1)):raise ValueError('Acquired source and declared feature count differ')
        db.execute("INSERT INTO features SELECT ROW_NUMBER() OVER(ORDER BY source_id),source_id,'buildings',properties,geometry FROM staging")
        db.execute('INSERT INTO feature_bounds SELECT f.fid,s.minx,s.maxx,s.miny,s.maxy FROM staging s JOIN features f ON f.source_id=s.source_id')
        info={'revision':str(meta['revision']),'feature_count':str(count),'geojson_sha256':original_hash,
          'repair_source_ids':json.dumps(repaired),'method':'Streaming disk-staged independent display index; original source geometry retained'}
        db.executemany('INSERT INTO metadata VALUES(?,?)',info.items());db.execute('DROP TABLE staging');db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Building index failed integrity check')
        db.execute('VACUUM')
    if sha256(geojson)!=original_hash:raise AssertionError('Acquired source geometry changed during indexing')
    pending.replace(output)
    print(json.dumps({'output':str(output),'revision':meta['revision'],'feature_count':count,'source_unchanged':True,'streaming':True}),flush=True)
    return info

def prepare(geojson,meta_path,output):
    geojson,meta_path,output=map(Path,(geojson,meta_path,output))
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    if not meta.get('available') or not meta.get('revision'):raise ValueError('A real acquired building source and revision are required')
    original_hash=sha256(geojson)
    doc=json.loads(geojson.read_text(encoding='utf-8'))
    if doc.get('type')!='FeatureCollection':raise ValueError('WGS84 building FeatureCollection required')
    rows=[];seen=set();repaired=[]
    height=meta.get('height',{})
    verified_heights=height.get('available') is True and height.get('semantics')=='height_above_ground_m'
    for feature in doc.get('features',[]):
        props=dict(feature.get('properties') or {})
        source_id=str(props.get('source_id',feature.get('id','')))
        if not source_id or source_id in seen:raise ValueError('Building source IDs must be present and unique')
        seen.add(source_id);props['source_id']=source_id;props['context_kind']='buildings'
        # Unsupported height semantics must not accidentally become 3D heights.
        if not verified_heights and 'height_m' in props:
            props['source_height_m']=props.pop('height_m')
        if verified_heights and props.get('height_m') is not None:
            import math
            value=props['height_m']
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('Verified building height must be finite nonnegative metres')
        geometry=shapely.force_2d(shape(feature['geometry']))
        if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.is_empty:raise ValueError('Real polygon building footprints required')
        if not geometry.is_valid:
            geometry=shapely.make_valid(geometry);repaired.append(source_id)
        if geometry.geom_type not in ('Polygon','MultiPolygon') or geometry.is_empty or not geometry.is_valid:
            raise ValueError('Building footprint has no valid polygon after documented repair')
        west,south,east,north=geometry.bounds
        if not (-180<=west<=east<=180 and -90<=south<=north<=90):raise ValueError('Building footprints are not WGS84 longitude/latitude')
        rows.append((source_id,props,geometry))
    if not rows or len(rows)!=int(meta.get('feature_count',-1)):raise ValueError('Acquired source and declared feature count differ')
    output.parent.mkdir(parents=True,exist_ok=True)
    pending=output.with_suffix('.pending.sqlite')
    if pending.exists():pending.unlink()
    with closing(sqlite3.connect(pending)) as db,db:
        db.executescript('''CREATE TABLE features(fid INTEGER PRIMARY KEY, source_id TEXT NOT NULL UNIQUE,
          kind TEXT NOT NULL, properties TEXT NOT NULL, geometry BLOB NOT NULL);
          CREATE VIRTUAL TABLE feature_bounds USING rtree(fid,minx,maxx,miny,maxy);
          CREATE INDEX feature_kind ON features(kind);
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
        for fid,(source_id,props,geometry) in enumerate(sorted(rows,key=lambda r:r[0]),1):
            db.execute('INSERT INTO features VALUES(?,?,?,?,?)',(fid,source_id,'buildings',json.dumps(props,ensure_ascii=False,allow_nan=False),shapely.to_wkb(geometry)))
            west,south,east,north=geometry.bounds
            db.execute('INSERT INTO feature_bounds VALUES(?,?,?,?,?)',(fid,west,east,south,north))
        info={'revision':str(meta['revision']),'feature_count':str(len(rows)),
              'geojson_sha256':original_hash,'repair_source_ids':json.dumps(repaired),
              'method':'Independent display-only WGS84 building index; source geometry file retained unchanged'}
        db.executemany('INSERT INTO metadata VALUES(?,?)',info.items())
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Building index failed integrity check')
    if sha256(geojson)!=original_hash:raise AssertionError('Acquired source geometry changed during indexing')
    pending.replace(output)
    print(json.dumps({'output':str(output),'revision':meta['revision'],'feature_count':len(rows),
                      'derived_repaired_source_ids':repaired,'source_unchanged':True}),flush=True)
    return info

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geojson',type=Path,default=ROOT/'data/derived/digital_twin_buildings.geojson')
    parser.add_argument('--metadata',type=Path,default=ROOT/'data/cache/digital_twin_buildings_meta.json')
    parser.add_argument('--output',type=Path,default=ROOT/'data/cache/digital_twin_buildings.sqlite')
    parser.add_argument('--feature-lines',type=Path,help='Equivalent acquisition NDJSON intermediate for bounded-memory indexing')
    args=parser.parse_args()
    if args.feature_lines:prepare_stream(args.geojson,args.metadata,args.output,args.feature_lines)
    else:prepare(args.geojson,args.metadata,args.output)
