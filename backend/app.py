import json,math,os,sqlite3,mimetypes,gzip,hashlib
from importlib.metadata import version as package_version
from functools import lru_cache
from pathlib import Path
from typing import Literal
from contextlib import contextmanager
from fastapi import FastAPI,HTTPException,Query,Request
from fastapi.responses import Response,FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from dotenv import load_dotenv
from shapely import from_wkb
from shapely.geometry import mapping,box
from shapely.ops import transform
from pyproj import Transformer
import mapbox_vector_tile
from .terrain import LocalTerrain,tile_bounds
from .pluvial import LocalPluvial
from .tile_cache import get_tile_cache,file_signature,read_json_cached
from .vector import render_vector_tile,category_filter,VECTOR_VERSION
from .http_cache import CompressedStaticFiles,accepts_gzip,PerformanceMetrics,RequestTiming
from .context_layers import BuildingsContext,CadastralContext,HistoricalSurveyContext
from .rainfall import LocalRainfall
from .rainfall_routes import create_rainfall_router
from .cadastre_routes import create_cadastre_router
from .flood_assessment import FloodAssessmentContext,history_mechanism_meta,history_mechanism_collection
from .refinement import LocalReviewPriority
from .refinement_routes import create_refinement_router
from .rainfall_routes import representation
from .green_absorption import GreenAbsorption
from .river_context import RiverContext
from .clogging import CloggingScenarios
from .clogging_routes import create_clogging_router

ROOT=Path(__file__).resolve().parents[1];CACHE=ROOT/'data/cache'
# Windows registry associations can incorrectly classify .js as text/plain.
# Module scripts require a JavaScript MIME type, including MapLibre's worker.
mimetypes.init()
mimetypes.add_type('text/javascript','.js')
mimetypes.add_type('text/javascript','.mjs')
mimetypes.add_type('text/css','.css')
load_dotenv(ROOT/'.env')
native=Path(os.environ.get('SOFIA_DTM_PATH',str(ROOT.parent/'sofia_dtm_2024_1m_gee.tif')))
if not native.is_absolute():native=ROOT/native
terrain=LocalTerrain(native,CACHE)
pluvial=LocalPluvial(CACHE)
buildings=BuildingsContext(ROOT)
cadastre=CadastralContext(ROOT)
history_survey=HistoricalSurveyContext(ROOT)
rainfall=LocalRainfall(ROOT/'data/rainfall',CACHE)
assessment=FloodAssessmentContext(ROOT)
review_priority=LocalReviewPriority(ROOT,pluvial,cadastre,history_survey,assessment)
green_absorption=GreenAbsorption(ROOT)
pluvial.green=green_absorption
review_priority.green=green_absorption
river_context=RiverContext(ROOT)
clogging_scenarios=CloggingScenarios(ROOT,pluvial,river_context)
CONFIG=json.loads((ROOT/'config/map_config.json').read_text(encoding='utf-8'))
PROJECT=Transformer.from_crs(4326,3857,always_xy=True).transform
UNPROJECT=Transformer.from_crs(3857,4326,always_xy=True)
app=FastAPI(title='Sofia Terrain, Rainfall & Pluvial Screening',version='1.9.0')
RENDERER_REVISION='fast-map-'+hashlib.sha256(b''.join((ROOT/'backend'/name).read_bytes() for name in ['app.py','vector.py','terrain.py','pluvial.py','open_water.py','scale.py','http_cache.py','tile_cache.py','context_layers.py','rainfall.py','rainfall_routes.py','cadastre_routes.py','flood_assessment.py','refinement.py','refinement_routes.py','green_absorption.py','river_context.py','clogging.py','clogging_routes.py'])+(ROOT/'config/map_config.json').read_bytes()+((CACHE/'whole_scale.json').read_bytes() if (CACHE/'whole_scale.json').is_file() else b'')+package_version('mapbox-vector-tile').encode()).hexdigest()[:12]
TILE_CACHE=get_tile_cache(str(CACHE/'rendered_tiles'))
METRICS=PerformanceMetrics()
app.add_middleware(RequestTiming,metrics=METRICS)

def revision():return (CACHE/'revision.txt').read_text(encoding='ascii').strip() if (CACHE/'revision.txt').exists() else 'unprepared'
@contextmanager
def database():
    path=CACHE/'spatial.sqlite'
    if not path.exists():raise HTTPException(503,'Spatial data unavailable. Run python scripts/prepare_data.py.')
    db=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:yield db
    finally:db.close()

def statuses(value):
    parts=[v for v in value.split(',') if v]
    if any(v not in ['existing','planned','open'] for v in parts):raise HTTPException(422,'Unknown route status')
    return sorted(set(parts))

def require_revision(v):
    if v!=revision():raise HTTPException(409,'Data revision changed; reload the app')

@app.get('/api/health')
def health():return {'status':'ok','spatial_ready':(CACHE/'spatial.sqlite').is_file(),'terrain_available':terrain.available}

@app.get('/api/meta')
def meta():
    result={'application_id':'sofia-terrain-explorer','revision':revision(),'renderer_revision':RENDERER_REVISION,'config':CONFIG,'terrain_available':terrain.available,
            'points_available':(CACHE/'spatial.sqlite').exists(),
            'basemap_style':os.environ.get('SOFIA_BASEMAP_STYLE','https://tiles.openfreemap.org/styles/positron'),
            'normalization_available':(CACHE/'whole_scale.json').exists(),
            'attribution':'SofiaPlan municipal DTM • supplied sewer routes (2009) • green areas (2020)',
            'handoff_warning':'The first ZIP was truncated and remains preserved. The complete rainfall supplement restores Script1, Script2, the rainfall reference, verification tools and the full 201-point Earth Engine colour curve. Native DTM and infrastructure points remain the existing real local inputs.',
            'terrain_sources':{'native_sample_m':1,'low_zoom_display_m':8,'native_display_min_zoom':15},
            'pluvial_available':pluvial.available,
            'limitations':'Relative terrain susceptibility and infrastructure overlap; no validated flood probability, flood depth, damage or sewer-capacity model.'}
    for name in ['vector_provenance','terrain_provenance','preflight']:
        path=CACHE/(name+'.json')
        if path.exists():result[name]=read_json_cached(path)
    return result

@app.get('/api/scales/{scale_id}')
def get_scale(scale_id:str):
    try:return terrain.scale(scale_id)
    except KeyError as e:raise HTTPException(404,str(e))

class ViewBounds(BaseModel):
    bounds:list[float]=Field(min_length=4,max_length=4)

@app.post('/api/scales/local')
def fit_local(request:ViewBounds):
    if not terrain.available:raise HTTPException(503,'Native municipal DTM unavailable; configure SOFIA_DTM_PATH')
    try:return terrain.local_scale(request.bounds,revision())
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'Terrain statistics request failed; previous colour scale is unchanged')

@app.get('/api/elevation')
def elevation(lon:float=Query(ge=-180,le=180),lat:float=Query(ge=-85,le=85)):
    if not math.isfinite(lon) or not math.isfinite(lat):raise HTTPException(422,'Finite coordinates required')
    if not terrain.available:raise HTTPException(503,'Native municipal DTM unavailable; configure SOFIA_DTM_PATH')
    try:return terrain.sample(lon,lat)
    except Exception:raise HTTPException(503,'Native elevation read failed; no substituted value is supplied')

@app.get('/api/route-statistics')
def route_statistics(zone:Literal['inside','outside','all']='inside',status:str='existing,planned,open'):
    enabled=statuses(status)
    if not enabled:return {'zone':zone,'count':0,'length_m':0,'by_status':{}}
    marks=','.join('?' for _ in enabled)
    with database() as db:
        rows=db.execute(f"SELECT status,COUNT(DISTINCT source_id) n,SUM(length_m) metres FROM features WHERE kind='routes' AND zone=? AND status IN ({marks}) GROUP BY status",[zone,*enabled]).fetchall()
    return {'zone':zone,'count':sum(r['n'] for r in rows),'length_m':sum(r['metres'] for r in rows),
            'by_status':{r['status']:{'count':r['n'],'length_m':r['metres']} for r in rows}}

def feature(row):
    p=json.loads(row['properties'])
    return {'type':'Feature','id':p.get('source_id',p.get('id',row['fid'])),
            'properties':p,'geometry':mapping(from_wkb(row['geometry']))}

@app.get('/api/routes/{source_id}')
def route(source_id:str,zone:Literal['inside','outside','all']='inside'):
    with database() as db:
        row=db.execute("SELECT * FROM features WHERE kind='routes' AND source_id=? AND zone=?",(source_id,zone)).fetchone()
    if row is None:raise HTTPException(404,'Route has no represented sections in this zone')
    return feature(row)

@app.get('/api/export/routes')
def export_routes(zone:Literal['inside','outside','all']='inside',status:str='existing,planned,open'):
    enabled=statuses(status)
    with database() as db:
        rows=db.execute("SELECT * FROM features WHERE kind='routes' AND zone=? AND status IN ("+','.join('?' for _ in enabled)+') ORDER BY fid',[zone,*enabled]).fetchall() if enabled else []
    result={'type':'FeatureCollection','name':'Sofia sewer sections - '+zone,
            'metadata':{'source_year':2009,'green_mask_year':2020,'zone':zone,'statuses':enabled,'revision':revision(),
                        'geometry':'Full-precision source/clip geometry; not simplified display tiles'},
            'features':[feature(r) for r in rows]}
    return Response(json.dumps(result,ensure_ascii=False),media_type='application/geo+json',
                    headers={'Content-Disposition':f'attachment; filename="sofia_sewers_{zone}.geojson"'})

@app.get('/api/green/{source_id}')
def green_feature(source_id:str):
    with database() as db:row=db.execute("SELECT * FROM features WHERE kind='green' AND source_id=?",(source_id,)).fetchone()
    if row is None:raise HTTPException(404,'Unknown or empty original green polygon')
    return feature(row)

@app.get('/api/buildings/meta')
def buildings_meta():return {**buildings.meta(),'renderer_revision':RENDERER_REVISION}

@app.get('/api/buildings/feature')
def building_feature(source_id:str):
    data=buildings.meta()
    if not data.get('available'):raise HTTPException(503,data.get('message','Real building source unavailable'))
    try:return buildings.feature(source_id)
    except KeyError:raise HTTPException(404,'Unknown original building ID')

@app.get('/api/buildings/download')
def building_download():
    data=buildings.meta()
    if not data.get('available'):raise HTTPException(503,data.get('message','Real building source unavailable'))
    return FileResponse(buildings.geojson,filename=buildings.geojson.name,media_type='application/geo+json')

@app.get('/api/buildings/tiles/{z}/{x}/{y}.pbf')
def building_tile(z:int,x:int,y:int,v:str,request:Request):
    meta=buildings.meta()
    if not meta.get('available'):raise HTTPException(503,meta.get('message','Real building source unavailable'))
    if v!=meta['revision']:raise HTTPException(409,'Building source revision changed; reload the app')
    try:tile_bounds(z,x,y)
    except ValueError as error:raise HTTPException(422,str(error))
    compressed=accepts_gzip(request.headers.get('accept-encoding',''))
    key=['buildings-mvt-v1',RENDERER_REVISION,file_signature(buildings.database),
         file_signature(buildings.metadata),file_signature(ROOT/'backend/vector.py'),v,z,x,y]
    producer=lambda:buildings.tile(z,x,y)
    if compressed:
        data=TILE_CACHE.get_or_render(['gzip3',*key],lambda:gzip.compress(TILE_CACHE.get_or_render(key,producer),compresslevel=3,mtime=0))
    else:data=TILE_CACHE.get_or_render(key,producer)
    etag='"'+hashlib.sha256(data).hexdigest()+'"'
    headers={'Cache-Control':'public,max-age=604800,immutable','Vary':'Accept-Encoding','ETag':etag}
    if compressed:headers['Content-Encoding']='gzip'
    validators=[value.strip().removeprefix('W/') for value in request.headers.get('if-none-match','').split(',')]
    if '*' in validators or etag in validators:return Response(status_code=304,headers=headers)
    return Response(data,media_type='application/vnd.mapbox-vector-tile',headers=headers)

@app.get('/api/history/meta')
def historical_flood_meta():
    path=CACHE/'historical_floods_meta.json'
    if not path.is_file():return {'available':False,'title':'Historical flood evidence','message':'No verified geolocated flood observations have been acquired. No flood extent is fabricated.'}
    result=read_json_cached(path)
    review_path=ROOT/'data/reference/historical_floods/mechanism_review.json'
    if review_path.is_file():
        analysis=read_json_cached(review_path)
        by_id={entry['source_id']:entry for entry in analysis['register_records']}
        result={**result,'events':[{**event,'mechanism_review':by_id.get(event['id'])} for event in result.get('events',[])],
                'mechanism_review_sources':analysis['primary_sources']}
    return result

def historical_document(key,suffix):
    meta=historical_flood_meta()
    path=(ROOT/str(meta.get(key,''))).resolve()
    if (not path.is_relative_to((ROOT/'data/reference/historical_floods').resolve())
        or path.suffix!=suffix or not path.is_file()):
        raise HTTPException(503,'The preserved official historical document is unavailable')
    return path

@app.get('/api/history/map')
def historical_map():
    path=historical_document('map_file','.pdf')
    return FileResponse(path,filename=path.name,media_type='application/pdf',content_disposition_type='inline')

@app.get('/api/history/download')
def historical_register():
    path=historical_document('download_file','.csv')
    return FileResponse(path,filename=path.name,media_type='text/csv')

@app.get('/api/history/zones/meta')
def historical_zones_meta():return {**history_mechanism_meta(history_survey),'renderer_revision':RENDERER_REVISION,'river_context':river_context.meta()}

@app.get('/api/history/zones.geojson')
def historical_zones(request:Request,v:str,river_proximity_m:float=Query(default=100,ge=5,le=1000)):
    data=history_survey.meta()
    if not data.get('available'):raise HTTPException(503,data.get('message','Real historical survey unavailable'))
    if v!=data['revision']:raise HTTPException(409,'Historical survey revision changed; reload the app')
    try:
        source=history_mechanism_collection(history_survey)
        collection={**source,'features':[{**f,'properties':{**f.get('properties',{}),'river_context':river_context.classify_geometry(f['geometry'],river_proximity_m,f.get('properties',{}).get('mechanism'))}} for f in source['features']]}
    except ValueError as error:raise HTTPException(503,str(error))
    return representation(request,collection,media_type='application/geo+json',immutable=True)

def vector_tile(kind,z,x,y,zone,display,v,categories=None,compressed=False):
    tile_bounds(z,x,y)
    path=CACHE/'spatial.sqlite'
    if not path.is_file():raise HTTPException(503,'Spatial data unavailable')
    key=[VECTOR_VERSION,RENDERER_REVISION,file_signature(path),kind,z,x,y,zone,display,v,categories]
    if compressed:
        return TILE_CACHE.get_or_render(['gzip3',*key],lambda:gzip.compress(vector_tile(kind,z,x,y,zone,display,v,categories),compresslevel=3,mtime=0))
    return TILE_CACHE.get_or_render(key,lambda:render_vector_tile(path,kind,z,x,y,zone,display,categories))

@app.get('/api/vector/{kind}/{z}/{x}/{y}.pbf')
def vectors(kind:Literal['routes','green','points'],z:int,x:int,y:int,v:str,request:Request,
            zone:Literal['inside','outside','all']='inside',display:Literal['subset','all']='subset',categories:str|None=None):
    require_revision(v)
    compressed=accepts_gzip(request.headers.get('accept-encoding',''))
    try:
        enabled=category_filter(categories) if kind=='points' else None
        data=vector_tile(kind,z,x,y,zone,display,v,enabled,compressed)
    except ValueError as e:raise HTTPException(422,str(e))
    etag='"'+hashlib.sha256(data).hexdigest()+'"'
    headers={'Cache-Control':'public,max-age=604800,immutable','Vary':'Accept-Encoding','ETag':etag}
    if compressed:headers['Content-Encoding']='gzip'
    validators=[value.strip().removeprefix('W/') for value in request.headers.get('if-none-match','').split(',')]
    if '*' in validators or etag in validators:return Response(status_code=304,headers=headers)
    return Response(data,media_type='application/vnd.mapbox-vector-tile',headers=headers)

@app.get('/api/raster/{scale_id}/{z}/{x}/{y}.png')
def raster(scale_id:str,z:int,x:int,y:int,v:str):
    require_revision(v)
    if not terrain.available:raise HTTPException(503,'Native municipal DTM unavailable')
    try:data=terrain.colour_tile(z,x,y,scale_id,v)
    except KeyError as e:raise HTTPException(404,str(e))
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'Terrain tile read failed; no substitute terrain is supplied')
    return Response(data,media_type='image/png',headers={'Cache-Control':'public,max-age=86400,immutable'})

@app.get('/api/hillshade/{z}/{x}/{y}.png')
def hillshade(z:int,x:int,y:int,v:str):
    require_revision(v)
    if not terrain.available:raise HTTPException(503,'Native municipal DTM unavailable')
    try:data=terrain.shade_tile(z,x,y,v)
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'Hillshade tile read failed')
    return Response(data,media_type='image/png',headers={'Cache-Control':'public,max-age=86400,immutable'})

@app.get('/api/pluvial/meta')
def pluvial_meta():
    result=pluvial.meta()
    result['renderer_revision']=RENDERER_REVISION
    path=ROOT/'docs/pluvial_evidence.json'
    if path.is_file():
        evidence=read_json_cached(path)
        result['evidence']=evidence['sources']
        result['data_interpretation']=evidence['available_data_interpretation']
        result['historical_evidence_leads']=evidence.get('historical_evidence_leads',[])
    if result.get('available'):
        result['summary']={'classes':result.get('classes',[]),'counts':result.get('counts',{}),'sensitivity':result.get('sensitivity',[])}
        exposure_path=CACHE/'pluvial_exposure.json'
        if exposure_path.is_file():
            exposure=read_json_cached(exposure_path)
            if exposure.get('pluvial_revision')==result['revision']:
                result['summary']['by_mode']=exposure.get('terrain_by_mode',{})
                combined=result['summary']['by_mode'].get('combined',{})
                result['summary'].update(classes=combined.get('classes',[]),counts={k:v for k,v in combined.items() if k.endswith('_cells')},sensitivity=combined.get('sensitivity',[]))
                result['classes']=combined.get('classes',[])
                result['counts']=result['summary']['counts']
                result['sensitivity']=combined.get('sensitivity',[])
                if result.get('water_exclusion',{}).get('enabled'):
                    water_cells=combined.get('water_excluded_cells')
                    if water_cells is not None:
                        result['water_exclusion'].update(mask_water_cells=result['water_exclusion'].get('cell_count'),cell_count=water_cells,area_km2=water_cells*25/1e6)
        if result.get('water_exclusion',{}).get('enabled') and not result['summary'].get('by_mode'):
            result['summary']={'classes':[],'counts':{},'sensitivity':[],
                'message':'Water-excluded land summaries are being prepared. Original water-inclusive totals are not substituted.'}
            result['classes']=[];result['counts']={};result['sensitivity']=[]
        result['recommended_view']='heatmap'
        result['heatmap']={'numeric_descriptor':'ponding','source_band':6,'units':'relative score 0–100',
            'stops':[0,25,50,70,85,100],
            'colors_rgba':[[255,246,180,0],[255,225,125,25],[255,178,45,105],[246,98,33,185],[218,37,83,225],[130,24,144,245]],
            'interpretation':'Continuous colour rendering of the original ponding P score; not flood probability, point density or a new risk calculation.',
            'sampling':'Nearest source cells and nearest display pixels; no smoothing across water, uncertainty or NoData boundaries.'}
        result['experimental_views']=['combined','concentration']
        result['routing_warning']='Real city-window inspection shows strong diagonal and parallel patterns in D8 contributing area. Combined and concentration scores amplify this routing structure; these patterns are not verified physical flood hotspots.'
        result.setdefault('method',{})
        if not isinstance(result['method'],dict):result['method']={'description':result['method']}
        result['method'].update(description='Relative terrain screening on a 5 m grid. Analyst-defined ranking, unvalidated against Sofia flood observations. Reference covers the whole available municipal DTM, including mountains, rather than only urban Sofia.',
            formula='P = 100 × rank of positive depression fill depth (zero where no depression); C = 100 × sqrt(rank(contributing area) × [1 − rank(slope)]); S = max(P, C). Ranks are fractions interpolated from 201 quantiles of a fixed 20 m systematic sample of 5 m cells.',
            limits=['Fill depth is geometric storage to spill, not event water depth. A deeper depression can store more water before spilling; its rank does not prove higher flood likelihood.',
                    'Mapped open-water footprints are excluded automatically. Unmapped channels and riverbank land may still score strongly; this does not distinguish all pluvial and fluvial flooding.',
                    'No rainfall, infiltration, building barriers, drainage capacity or independently validated flood probability is included.'])
    return result

@app.get('/api/green-absorption/meta')
def green_absorption_meta():return green_absorption.meta()

@app.get('/api/river-context/meta')
def river_context_meta():return river_context.meta()

@app.get('/api/river-context/sample')
def river_context_sample(lon:float=Query(ge=-180,le=180),lat:float=Query(ge=-85,le=85),river_proximity_m:float=Query(default=100,ge=5,le=1000)):
    return river_context.sample(lon,lat,river_proximity_m)

@app.get('/api/pluvial/sample')
def pluvial_sample(lon:float=Query(ge=-180,le=180),lat:float=Query(ge=-85,le=85),green_absorption:bool=False,river_proximity_m:float=Query(default=100,ge=5,le=1000)):
    if not math.isfinite(lon) or not math.isfinite(lat):raise HTTPException(422,'Finite coordinates required')
    if not pluvial.available:raise HTTPException(503,pluvial.meta().get('message','Terrain screening or required open-water mask unavailable'))
    if green_absorption and not pluvial.green.available:raise HTTPException(503,pluvial.green.error)
    try:
        result=pluvial.sample(lon,lat,green_absorption)
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'Screening pixel read failed; no substituted score')
    factors=result.get('factors',{})
    known=factors.get('mean_ground_elevation_m') is not None
    water_excluded=result['status']=='excluded_open_water'
    green_excluded=result['status']=='excluded_green_absorption'
    uncertain=not (water_excluded or green_excluded) and (result['status']=='boundary-excluded' or (known and result.get('score') is None))
    return {**result,'river_context':river_context.sample(lon,lat,river_proximity_m),'status':'uncertain' if uncertain else result['status'],
            'class_label':result.get('class'),
            'ponding_score':factors.get('depression_percentile'),
            'concentration_score':factors.get('concentration_flatness_score'),
            'depression_depth_m':factors.get('depression_fill_depth_m'),
            'slope_degrees':factors.get('slope_degrees'),
            'contributing_area_m2':factors.get('upstream_contributing_area_m2'),
            'boundary_influence':factors.get('possible_missing_upstream_terrain')==1,
            'interpretation':'Mapped green area is assumed to absorb all rainfall and excluded for this scenario.' if green_excluded else 'Existing mapped water is excluded from land pluvial screening; river flooding is not assessed.' if water_excluded else 'Relative terrain signal, not flood probability or event flood depth.'}

@app.get('/api/pluvial/exposure')
def pluvial_exposure(mode:Literal['ponding','combined','concentration']='ponding'):
    path=CACHE/'pluvial_exposure.json'
    if not path.is_file():raise HTTPException(503,'Infrastructure overlap has not been prepared')
    result=read_json_cached(path)
    if result['dataset_revision']!=revision() or result['pluvial_revision']!=pluvial.meta().get('revision'):
        raise HTTPException(409,'Infrastructure overlap belongs to a different data revision; rerun scripts/prepare_pluvial_exposure.py')
    if mode not in result.get('modes',{}):raise HTTPException(503,'Mode-specific infrastructure overlap is being prepared; no combined values are substituted')
    selected={k:v for k,v in result.items() if k!='modes'}
    selected.update(result['modes'][mode]);selected['mode']=mode
    if mode in ['combined','concentration']:selected['routing_warning']='Experimental: observed D8/grid patterns influence these class overlaps; not reliable street-level flood risk.'
    return selected

@app.get('/api/pluvial/evidence')
def pluvial_evidence():return FileResponse(ROOT/'docs/pluvial_evidence.json',media_type='application/json')

@app.get('/api/pluvial/water-mask/meta')
def pluvial_water_mask_meta():
    path=CACHE/'open_water_meta.json'
    if not path.is_file():raise HTTPException(503,'The real open-water exclusion mask has not been prepared')
    return read_json_cached(path)

@app.get('/api/pluvial/download/{kind}')
def pluvial_download(kind:Literal['raster','points','routes','water-mask']):
    paths={'raster':ROOT/'data/derived/pluvial_land_screening_5m.tif','points':ROOT/'data/derived/infrastructure_terrain_screening.csv',
           'routes':ROOT/'data/derived/sewer_route_terrain_screening.csv','water-mask':CACHE/'open_water_mask_5m.tif'}
    path=paths[kind]
    if not pluvial.available or not path.exists():raise HTTPException(503,'Screening export unavailable')
    if kind in ('points','routes'):pluvial_exposure('ponding')
    if kind=='raster':
        receipt=ROOT/'data/derived/pluvial_land_screening_5m.json'
        if not receipt.is_file() or read_json_cached(receipt).get('pluvial_revision')!=pluvial.meta()['revision']:
            raise HTTPException(409,'Land-only raster belongs to a different screening revision; rerun scripts/prepare_pluvial_exposure.py')
    return FileResponse(path,filename=path.name,media_type='image/tiff' if kind in ('raster','water-mask') else 'text/csv')

@app.get('/api/pluvial/{mode}/{z}/{x}/{y}.png')
def pluvial_tile(request:Request,mode:Literal['heatmap','combined','ponding','concentration'],z:int,x:int,y:int,v:str,green_absorption:bool=False):
    if not pluvial.available:raise HTTPException(503,'Terrain screening unavailable')
    if v!=pluvial.meta()['revision']:raise HTTPException(409,'Screening data revision changed; reload the app')
    if green_absorption and not pluvial.green.available:raise HTTPException(503,pluvial.green.error)
    try:data=pluvial.tile({'heatmap':'heatmap','combined':'screening','ponding':'depressions','concentration':'concentration'}[mode],z,x,y,pluvial.meta()['revision'],green_absorption)
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'Screening tile failed; no substituted risk surface')
    return representation(request,data,'image/png',True)

@app.get('/api/performance')
def performance():
    return {'renderer_revision':RENDERER_REVISION,'requests':METRICS.snapshot(),'tile_cache':TILE_CACHE.stats,
            'note':'Local implementation diagnostics; no source values or analysis scores are changed by caching.'}

app.include_router(create_rainfall_router(rainfall))
app.include_router(create_cadastre_router(cadastre,RENDERER_REVISION,TILE_CACHE))
app.include_router(create_refinement_router(review_priority,assessment,RENDERER_REVISION,green_absorption,river_context))
app.include_router(create_clogging_router(clogging_scenarios,RENDERER_REVISION))

if (ROOT/'dist').is_dir():app.mount('/',CompressedStaticFiles(directory=ROOT/'dist',html=True),name='frontend')
else:
    @app.get('/')
    def unbuilt():return {'message':'Frontend not built yet. Run pnpm build, then restart this API; or run pnpm dev.'}
