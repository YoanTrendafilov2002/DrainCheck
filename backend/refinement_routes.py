"""Revision-bound review raster and independent official assessment routes."""
import math
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from .rainfall_routes import representation

def create_refinement_router(review, assessment, renderer, green=None, rivers=None):
    router = APIRouter(tags=['evidence review'])
    def verified(layer, version=None):
        meta = layer.meta()
        if not meta.get('available'):
            raise HTTPException(503, meta.get('message', 'Source unavailable'))
        if version is not None and version != meta['revision']:
            raise HTTPException(409, 'Evidence source revision changed; reload the app')
        return meta

    @router.get('/api/refinement/meta')
    def meta(request: Request):
        return representation(request, {**review.meta(), 'renderer_revision': renderer})

    @router.get('/api/refinement/sample')
    def sample(request: Request, lon: float = Query(ge=-180,le=180), lat: float = Query(ge=-85,le=85), green_absorption:bool=False, river_proximity_m:float=Query(default=100,ge=5,le=1000)):
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise HTTPException(422, 'Finite coordinates required')
        verified(review)
        if green_absorption and (green is None or not green.available):raise HTTPException(503,'Green absorption scenario unavailable')
        try:
            result=review.sample(lon,lat,green_absorption)
            if rivers is not None:result={**result,'river_context':rivers.sample(lon,lat,river_proximity_m)}
            return representation(request,result)
        except ValueError as error:
            raise HTTPException(503, str(error))

    @router.get('/api/refinement/tiles/{z}/{x}/{y}.png')
    def tile(request: Request, z: int, x: int, y: int, v: str, green_absorption:bool=False):
        verified(review, v)
        if green_absorption and (green is None or not green.available):raise HTTPException(503,'Green absorption scenario unavailable')
        try:
            data = review.tile(z,x,y,renderer,green_absorption)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return representation(request, data, 'image/png', immutable=True)

    @router.get('/api/refinement/download')
    def download():
        verified(review)
        return FileResponse(review.path, filename=review.path.name, media_type='image/tiff')

    @router.get('/api/flood-assessment/meta')
    def assessment_meta(request: Request):
        return representation(request, {**assessment.meta(), 'renderer_revision': renderer})

    @router.get('/api/flood-assessment/geojson')
    def assessment_geometry(request: Request, v: str):
        verified(assessment, v)
        return representation(request, assessment.collection(), 'application/geo+json', immutable=True)

    return router
