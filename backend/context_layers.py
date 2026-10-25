"""Independent source-backed context. These layers never enter terrain scores."""
import gzip,hashlib,json,sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from .tile_cache import file_signature,read_json_cached
from .vector import render_vector_tile

def sha256(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):value.update(chunk)
    return value.hexdigest()

class BuildingsContext:
    def __init__(self,root,stem='digital_twin_buildings',title='Sofia Digital Twin buildings'):
        self.root=Path(root)
        if stem not in ('digital_twin_buildings','cadastral_buildings'):raise ValueError('Unknown independent building dataset')
        self.title=title
        self.metadata=self.root/'data/cache'/(stem+'_meta.json')
        self.geojson=self.root/'data/derived'/(stem+'.geojson')
        self.database=self.root/'data/cache'/(stem+'.sqlite')

    def meta(self):
        if not self.metadata.is_file():
            return {'available':False,'title':self.title,
                    'message':'The official building source has not been acquired. No substitute buildings are supplied.'}
        data=read_json_cached(self.metadata)
        if not data.get('available'):return data
        try:
            if not data.get('revision'):raise ValueError('Building source revision is missing')
            self.validate(file_signature(self.database),file_signature(self.geojson),
                          file_signature(self.metadata),str(data['revision']),int(data['feature_count']))
        except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
            return {**data,'available':False,'message':'Building index unavailable or stale: '+str(error)}
        return {**data,'available':True,'minzoom':13,
                'interpretation':'Building context only. Not a hydraulic barrier model, building vulnerability or predicted damage.'}

    @staticmethod
    @lru_cache(maxsize=4)
    def validate(db_signature,geojson_signature,meta_signature,revision,count):
        with closing(sqlite3.connect('file:'+Path(db_signature[0]).as_posix()+'?mode=ro',uri=True)) as db:
            info=dict(db.execute('SELECT key,value FROM metadata'))
            if info.get('revision')!=revision or int(info.get('feature_count',-1))!=count:
                raise ValueError('Source metadata and indexed buildings differ')
            if info.get('geojson_sha256')!=sha256(geojson_signature[0]):
                raise ValueError('Building geometry changed; rebuild its independent index')
            if db.execute('SELECT COUNT(*) FROM features').fetchone()[0]!=count:
                raise ValueError('Building index is incomplete')

    def tile(self,z,x,y):
        return render_vector_tile(self.database,'buildings',z,x,y,zone='all',display='all')

    def feature(self,source_id):
        with closing(sqlite3.connect('file:'+self.database.as_posix()+'?mode=ro',uri=True)) as db:
            row=db.execute('SELECT properties,geometry FROM features WHERE source_id=?',(source_id,)).fetchone()
        if row is None:raise KeyError(source_id)
        from shapely import from_wkb
        from shapely.geometry import mapping
        return {'type':'Feature','id':source_id,'geometry':mapping(from_wkb(row[1])),
                'properties':json.loads(row[0])}


class CadastralContext(BuildingsContext):
    """Compact viewport tiles with complete original AGKK properties on inspection."""
    def __init__(self,root):
        super().__init__(root,stem='cadastral_buildings',title='Cadastral building outlines')

    @staticmethod
    @lru_cache(maxsize=2)
    def original_batch(signature,expected_sha256):
        if sha256(signature[0])!=expected_sha256:raise ValueError('Original cadastral batch checksum differs from its receipt')
        with gzip.open(signature[0],'rt',encoding='utf-8') as stream:doc=json.load(stream)
        if doc.get('type')!='FeatureCollection' or doc.get('exceededTransferLimit'):
            raise ValueError('Original cadastral batch is incomplete')
        records={}
        for feature in doc['features']:
            oid=str(feature['properties']['objectid'])
            if oid in records:raise ValueError('Original cadastral batch contains duplicate object IDs')
            records[oid]=feature
        return records

    def feature(self,source_id):
        feature=super().feature(source_id);props=feature['properties']
        relative=props.get('source_batch_file')
        if not relative:return feature
        path=(self.root/relative).resolve()
        allowed=(self.root/'data/reference/agkk_buildings/batches').resolve()
        if not path.is_relative_to(allowed) or not path.name.endswith('.geojson.gz'):
            raise ValueError('Original cadastral batch must remain within the preserved source directory')
        original=self.original_batch(file_signature(path),props['source_batch_sha256']).get(str(props['source_oid']))
        if original is None:raise ValueError('Original cadastral object is missing from its preserved batch')
        if original['properties'].get('id_localid')!=props.get('id_localid'):
            raise ValueError('Original cadastral identifier differs from the indexed source')
        return {**feature,'properties':{**original['properties'],**props},
                'source_attributes':'Complete original AGKK properties plus explicit index provenance',
                'geometry_note':'Full-precision WGS84 display geometry; any repair is documented in acquisition metadata'}


class HistoricalSurveyContext:
    """Small real survey FeatureCollection, served only when explicitly enabled."""
    def __init__(self,root):
        self.root=Path(root)
        self.metadata=self.root/'data/cache/historical_flood_zones_meta.json'

    def data_path(self,data):
        value=(self.root/str(data.get('data_file',''))).resolve()
        allowed=(self.root/'data/reference/historical_floods').resolve()
        if not value.is_relative_to(allowed) or value.suffix!='.geojson':
            raise ValueError('Historical survey geometry must be a preserved local GeoJSON source')
        return value

    def meta(self):
        if not self.metadata.is_file():return {'available':False,'title':'Historical Sofia flood survey','message':'No real mapped survey geometry is available.'}
        data=read_json_cached(self.metadata)
        if not data.get('available'):return data
        try:
            path=self.data_path(data)
            self.validate(file_signature(path),file_signature(self.metadata),data['sha256'],int(data['feature_count']))
        except (OSError,ValueError,TypeError,KeyError) as error:
            return {**data,'available':False,'message':'Historical survey source unavailable or invalid: '+str(error)}
        return data

    @staticmethod
    @lru_cache(maxsize=4)
    def validate(data_signature,meta_signature,expected_sha256,count):
        if sha256(data_signature[0])!=expected_sha256:raise ValueError('Historical geometry checksum differs from its receipt')
        data=read_json_cached(data_signature[0])
        if data.get('type')!='FeatureCollection' or len(data.get('features',[]))!=count:
            raise ValueError('Historical feature count differs from its receipt')
        from shapely.geometry import shape
        ids=set()
        for feature in data['features']:
            sid=feature.get('properties',{}).get('source_id')
            if sid is None or sid in ids:raise ValueError('Historical source IDs are missing or duplicated')
            ids.add(sid);geometry=shape(feature['geometry'])
            if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon'):
                raise ValueError('Historical source has invalid display polygons')
            w,s,e,n=geometry.bounds
            if not (-180<=w<=e<=180 and -90<=s<=n<=90):raise ValueError('Historical display geometry must be WGS84')
