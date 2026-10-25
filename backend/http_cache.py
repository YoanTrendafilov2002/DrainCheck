"""Compressed representations and small, local-only performance diagnostics."""
import mimetypes,time,threading
from collections import Counter
from pathlib import Path
from starlette.staticfiles import StaticFiles
from starlette.datastructures import Headers

def accepts_gzip(value):
    choices={}
    for item in value.lower().split(','):
        bits=[v.strip() for v in item.split(';')];q=1.
        for param in bits[1:]:
            if param.startswith('q='):
                try:q=float(param[2:])
                except ValueError:q=0.
        choices[bits[0]]=q
    return choices.get('gzip',choices.get('*',0.))>0

class PerformanceMetrics:
    def __init__(self):self._lock=threading.Lock();self.counts=Counter()
    def snapshot(self):
        with self._lock:return dict(self.counts)
    def count(self,path):
        family=next((name for name,prefix in [('raster','/api/raster/'),('hillshade','/api/hillshade/'),('vector','/api/vector/'),('buildings','/api/buildings/tiles/'),('cadastre','/api/cadastre/tiles/'),('review_tile','/api/refinement/tiles/'),('assessment','/api/flood-assessment/geojson'),('history_survey','/api/history/zones.geojson'),('rainfall_tile','/api/rainfall/tiles/'),('rain_stations','/api/rainfall/stations'),('exposure','/api/pluvial/exposure'),('pluvial_tile','/api/pluvial/')] if path.startswith(prefix)),None)
        if family=='pluvial_tile' and not path.endswith('.png'):return
        if family:
            with self._lock:self.counts[family]+=1

class RequestTiming:
    def __init__(self,app,metrics):self.app=app;self.metrics=metrics
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        self.metrics.count(scope.get('path',''));start=time.perf_counter()
        async def timed(message):
            if message['type']=='http.response.start':
                message={**message,'headers':[*message.get('headers',[]),(b'server-timing',f'handler;dur={(time.perf_counter()-start)*1000:.2f}'.encode())]}
            await send(message)
        await self.app(scope,receive,timed)

class CompressedStaticFiles(StaticFiles):
    async def get_response(self,path,scope):
        # StaticFiles performs path traversal checks for either representation.
        request=Headers(scope=scope);compressed=False
        if accepts_gzip(request.get('accept-encoding','')) and Path(path).suffix.lower() in ('.js','.mjs','.css','.html','.svg','.json'):
            full,stat=self.lookup_path(path+'.gz')
            if stat is not None:
                result=await super().get_response(path+'.gz',scope);compressed=True
            else:result=await super().get_response(path,scope)
        else:result=await super().get_response(path,scope)
        result.headers['Vary']='Accept-Encoding'
        if compressed:
            result.headers['Content-Encoding']='gzip'
            result.headers['Content-Type']=mimetypes.guess_type(path)[0] or 'application/octet-stream'
        result.headers['Cache-Control']='public,max-age=31536000,immutable' if path.replace('\\','/').startswith('assets/') else 'no-cache'
        return result
