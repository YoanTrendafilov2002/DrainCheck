"""Separately attributed cadastral geometry; the Digital Twin adapter stays intact."""
import gzip,hashlib
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse,Response
from .terrain import tile_bounds
from .tile_cache import file_signature
from .http_cache import accepts_gzip

def create_cadastre_router(context,renderer_revision,cache):
    router=APIRouter(prefix='/api/cadastre',tags=['cadastral-building-context'])
    def ready(revision=None):
        meta=context.meta()
        if not meta.get('available'):raise HTTPException(503,meta.get('message','Cadastral building source unavailable'))
        if revision is not None and revision!=meta['revision']:raise HTTPException(409,'Cadastral source revision changed; reload the app')
        return meta

    @router.get('/meta')
    def metadata():return {**context.meta(),'renderer_revision':renderer_revision}

    @router.get('/feature')
    def feature(source_id:str):
        ready()
        try:return context.feature(source_id)
        except KeyError:raise HTTPException(404,'Unknown original cadastral building ID')
        except (OSError,ValueError) as error:raise HTTPException(503,'Original cadastral source details unavailable: '+str(error))

    @router.get('/download')
    def download():
        ready()
        return FileResponse(context.geojson,filename=context.geojson.name,media_type='application/geo+json')

    @router.get('/tiles/{z}/{x}/{y}.pbf')
    def tile(z:int,x:int,y:int,v:str,request:Request):
        ready(v)
        try:tile_bounds(z,x,y)
        except ValueError as error:raise HTTPException(422,str(error))
        compressed=accepts_gzip(request.headers.get('accept-encoding',''))
        key=['cadastral-buildings-mvt-v1',renderer_revision,file_signature(context.database),
             file_signature(context.metadata),file_signature(Path(__file__).with_name('vector.py')),v,z,x,y]
        producer=lambda:context.tile(z,x,y)
        if compressed:
            data=cache.get_or_render(['gzip3',*key],lambda:gzip.compress(cache.get_or_render(key,producer),compresslevel=3,mtime=0))
        else:data=cache.get_or_render(key,producer)
        etag='"'+hashlib.sha256(data).hexdigest()+'"'
        headers={'Cache-Control':'public,max-age=604800,immutable','Vary':'Accept-Encoding','ETag':etag}
        if compressed:headers['Content-Encoding']='gzip'
        validators=[value.strip().removeprefix('W/') for value in request.headers.get('if-none-match','').split(',')]
        if '*' in validators or etag in validators:return Response(status_code=304,headers=headers)
        return Response(data,media_type='application/vnd.mapbox-vector-tile',headers=headers)

    return router
