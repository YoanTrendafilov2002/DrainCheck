"""Self-contained rainfall router; app integration does not alter terrain APIs."""
import gzip
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from .http_cache import accepts_gzip
from .rainfall import product_id, threshold_value

RainProduct = Literal['merged_250m', 'radar_bias_corrected_250m', 'radar_raw_1km']


def representation(request, data, media_type='application/json', immutable=False):
    if not isinstance(data, bytes):
        data = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    compressed = media_type != 'image/png' and accepts_gzip(request.headers.get('accept-encoding', ''))
    if compressed:
        data = gzip.compress(data, compresslevel=3, mtime=0)
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    headers = {'Vary': 'Accept-Encoding', 'ETag': etag,
               'Cache-Control': 'public,max-age=604800,immutable' if immutable else 'no-cache'}
    if compressed:
        headers['Content-Encoding'] = 'gzip'
    validators = [v.strip().removeprefix('W/') for v in request.headers.get('if-none-match', '').split(',')]
    if '*' in validators or etag in validators:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=media_type, headers=headers)


def create_rainfall_router(rainfall):
    router = APIRouter(prefix='/api/rainfall', tags=['rainfall'])

    def verified(revision=None):
        meta = rainfall.meta()
        if not meta.get('available'):
            raise HTTPException(503, meta.get('message', 'Native rainfall unavailable'))
        if revision is not None and revision != meta['revision']:
            raise HTTPException(409, 'Rainfall revision changed; reload the app')
        return meta

    @router.get('/meta')
    def meta(request: Request):
        return representation(request, rainfall.meta())

    @router.get('/sample')
    def sample(request: Request, lon: float = Query(ge=-180, le=180), lat: float = Query(ge=-90, le=90),
               product: RainProduct | None = None, threshold: float | None = None, v: str | None = None):
        verified(v)
        try:
            result = rainfall.sample(lon, lat, product, threshold)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return representation(request, result)

    @router.get('/stations')
    def stations(request: Request, v: str | None = None):
        verified(v)
        return representation(request, rainfall.stations(), 'application/geo+json', v is not None)

    @router.get('/statistics')
    def statistics(request: Request, product: RainProduct = 'merged_250m', v: str | None = None):
        verified(v)
        return representation(request, rainfall.statistics(product), immutable=v is not None)

    @router.get('/tiles/{product}/{z}/{x}/{y}.png')
    def tile(request: Request, product: RainProduct, z: int, x: int, y: int,
             smoothing: Literal['nearest', 'bilinear'] = 'nearest', threshold: float | None = None,
             v: str | None = None):
        verified(v)
        try:
            threshold_value(product, threshold)
            data = rainfall.tile(product, z, x, y, smoothing, threshold)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return representation(request, data, 'image/png', v is not None)

    @router.get('/download/{product}')
    def download(product: RainProduct, v: str | None = None):
        verified(v)
        product_id(product)
        path = rainfall.data_dir / (product + '.tif')
        return FileResponse(path, media_type='image/tiff', filename=path.name,
                            headers={'Cache-Control': 'no-cache'})

    return router
