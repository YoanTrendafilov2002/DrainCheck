"""Real mapped-water footprints on the existing analysis grid; no inferred buffers."""
import hashlib,threading
from functools import lru_cache
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from .tile_cache import file_signature,read_json_cached

VALIDATION_LOCK=threading.RLock()


class OpenWaterMask:
    def __init__(self,cache):
        self.path=Path(cache)/'open_water_mask_5m.tif'
        self.receipt=Path(cache)/'open_water_meta.json'
        self.error='Mapped-water exclusion has not been prepared.'

    @property
    def available(self):
        try:
            meta=read_json_cached(self.receipt)
            if not meta.get('available') or not meta.get('revision') or not meta.get('sha256'):
                raise ValueError('Mapped-water receipt is incomplete')
            if meta['revision']!=meta['sha256'][:16]:raise ValueError('Mapped-water revision does not identify its raster checksum')
            expected_count=meta.get('counts',{}).get('water_cells')
            if not isinstance(expected_count,int) or expected_count<=0:raise ValueError('Mapped-water footprint counts are unavailable')
            with VALIDATION_LOCK:self._validate(file_signature(self.path),file_signature(self.receipt),meta['sha256'],expected_count)
            self.error='';return True
        except (OSError,ValueError,rasterio.errors.RasterioError) as error:
            self.error='Mapped-water exclusion unavailable or invalid: '+str(error);return False

    @staticmethod
    @lru_cache(maxsize=4)
    def _validate(signature,receipt_signature,expected_sha256,expected_count):
        path=Path(signature[0]);h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
        if h.hexdigest()!=expected_sha256:raise ValueError('Mapped-water raster checksum differs from its source receipt')
        with rasterio.open(path) as src:
            if (src.crs is None or src.crs.to_epsg()!=7801 or src.shape!=(10869,10345)
                or src.count!=1 or src.dtypes[0]!='uint8' or src.nodata is not None
                or list(src.transform)[:6]!=[5,0,299392,0,-5,4753611]):
                raise ValueError('Mapped-water grid differs from the real 5 m screening grid')
            water_count=0
            for _,window in src.block_windows(1):
                a=src.read(1,window=window)
                if np.any((a!=0)&(a!=1)):raise ValueError('Mapped-water raster contains unsupported classes')
                water_count+=int((a==1).sum())
            if water_count!=expected_count:raise ValueError('Mapped-water counts differ from the source receipt')

    def meta(self):
        if not self.available:return {'enabled':True,'available':False,'message':self.error}
        source=read_json_cached(self.receipt);provider=source.get('source',{})
        counts=source.get('counts',{})
        return {'enabled':True,'available':True,'revision':source['revision'],
                'area_km2':counts.get('water_area_km2'),'cell_count':counts.get('water_cells'),
                'source_label':provider.get('provider','OpenStreetMap mapped open-water polygons'),
                'source_url':provider.get('url',(source.get('source_urls') or ['https://www.openstreetmap.org/copyright'])[0]),
                'retrieved_at':provider.get('download_utc',source.get('download_utc')),
                'method':source.get('policy','Direct mapped polygon footprints on the aligned 5 m grid; no line buffering or upstream changes.'),
                'limitations':source.get('limitations',[]),'sha256':source['sha256']}

    def sample_cell(self,row,col):
        if not self.available:raise ValueError(self.error)
        if not (0<=row<10869 and 0<=col<10345):return False
        with rasterio.open(self.path) as src:return int(src.read(1,window=Window(col,row,1,1))[0,0])==1
