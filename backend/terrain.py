"""Read-only native raster adapter; web tiles are explicitly separate display products."""
import hashlib,io,json,math,threading,uuid
from functools import lru_cache
from pathlib import Path
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.windows import from_bounds,Window
from rasterio.warp import reproject,transform_bounds
from rasterio.warp import transform_geom
from rasterio.features import geometry_mask
from pyproj import Transformer
from PIL import Image
from .scale import knots,legend,rgba
from .tile_cache import file_signature,read_json_cached,get_tile_cache

HALF=20037508.342789244
RASTER_SLOTS=threading.BoundedSemaphore(2)
XY=Transformer.from_crs(4326,7801,always_xy=True)
MERCATOR=Transformer.from_crs(3857,4326,always_xy=True)

def tile_bounds(z,x,y):
    if not 0<=z<=22 or not 0<=x<2**z or not 0<=y<2**z:raise ValueError('Invalid tile coordinate')
    width=2*HALF/(2**z)
    return (-HALF+x*width,HALF-(y+1)*width,-HALF+(x+1)*width,HALF-y*width)

def png(a):
    stream=io.BytesIO();Image.fromarray(a).save(stream,format='PNG',compress_level=3)
    return stream.getvalue()

class LocalTerrain:
    def __init__(self,native:Path,cache:Path):
        self.native=Path(native);self.cache=Path(cache)
        self.tiles=get_tile_cache(str((self.cache/'rendered_tiles').resolve()))

    @property
    def available(self):
        try:
            s=self.native.stat();self.validate_native(str(self.native),s.st_size,s.st_mtime_ns);return True
        except (OSError,ValueError,rasterio.errors.RasterioError):return False

    @staticmethod
    @lru_cache(maxsize=4)
    def validate_native(path,size,modified):
        with rasterio.open(path) as src:
            if (src.crs is None or src.crs.to_epsg()!=7801 or src.shape!=(54343,51722)
                or src.count!=1 or src.dtypes[0]!='float32' or src.nodata!=-9999
                or list(src.transform)[:6]!=[1,0,299392,0,-1,4753611]):
                raise ValueError('File is not the native 1 m Sofia municipal DTM; previews/other DEMs are rejected')

    def sample(self,lon,lat):
        if not self.available:raise ValueError('Native source unavailable or invalid')
        x,y=XY.transform(lon,lat)
        with rasterio.Env(PROJ_NETWORK='OFF',GDAL_CACHEMAX=64000000),rasterio.open(self.native,OVERVIEW_LEVEL='NONE') as src:
            if src.crs.to_epsg()!=7801 or list(src.transform)[:6]!=[1,0,299392,0,-1,4753611]:
                raise ValueError('Native raster grid does not match Sofia municipal DTM')
            row,col=src.index(x,y)
            result={'longitude':lon,'latitude':lat,'crs':'EPSG:7801','vertical_datum':'Baltic 1982',
                    'sample_resolution_m':1,'row':int(row),'column':int(col)}
            if not (0<=row<src.height and 0<=col<src.width):return {**result,'status':'nodata','elevation_m':None}
            value=float(src.read(1,window=Window(col,row,1,1))[0,0])
            center=src.xy(row,col)
            return {**result,'pixel_center_easting':center[0],'pixel_center_northing':center[1],
                    'status':'ok' if value!=src.nodata and math.isfinite(value) else 'nodata',
                    'elevation_m':value if value!=src.nodata and math.isfinite(value) else None}

    def scale(self,scale_id):
        if scale_id=='whole':name='whole_scale.json'
        elif scale_id.startswith('local-') and len(scale_id)==22 and all(c in '0123456789abcdef' for c in scale_id[6:]):
            name=scale_id+'.json'
        else:raise KeyError('Unknown colour scale')
        path=self.cache/name
        if not path.is_file():raise KeyError('Saved scale is unavailable; fit this view or reset to whole area')
        result=read_json_cached(path)
        if scale_id!='whole' and result.get('dataset_revision')!=(self.cache/'revision.txt').read_text(encoding='ascii').strip():
            raise KeyError('Saved local scale belongs to a different data revision; fit again or reset')
        return result

    def local_scale(self,bounds,revision):
        if not self.available:raise ValueError('Native source unavailable or invalid')
        if len(bounds)!=4 or not all(math.isfinite(v) for v in bounds):raise ValueError('Four finite bounds required')
        w,s,e,n=bounds
        if not (-180<=w<e<=180 and -85<=s<n<=85):raise ValueError('Invalid geographic bounds')
        key=hashlib.sha256(json.dumps({'bbox':[round(v,6) for v in bounds],'revision':revision,
                                     'scale':10,'method':'hybrid-continuous-v2'}).encode()).hexdigest()[:16]
        scale_id='local-'+key;path=self.cache/(scale_id+'.json')
        if path.exists():return self.scale(scale_id)
        with RASTER_SLOTS,rasterio.Env(PROJ_NETWORK='OFF',GDAL_CACHEMAX=128000000),rasterio.open(self.native,OVERVIEW_LEVEL='NONE') as src:
            projected=transform_bounds(4326,7801,w,s,e,n,densify_pts=21)
            extent=(max(src.bounds.left,projected[0]),max(src.bounds.bottom,projected[1]),
                    min(src.bounds.right,projected[2]),min(src.bounds.top,projected[3]))
            if extent[0]>=extent[2] or extent[1]>=extent[3]:return {'status':'nodata','message':'No terrain coverage in this view'}
            window=from_bounds(*extent,transform=src.transform).round_offsets().round_lengths()
            spacing=max(10,math.ceil(math.sqrt(window.width*window.height/2000000)))
            height=max(1,math.ceil(window.height/spacing));width=max(1,math.ceil(window.width/spacing))
            data=src.read(1,window=window,out_shape=(height,width),resampling=Resampling.average,masked=True)
            polygon={'type':'Polygon','coordinates':[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}
            view_mask=geometry_mask([transform_geom(4326,src.crs,polygon)],out_shape=(height,width),
                transform=src.window_transform(window)*Affine.scale(window.width/width,window.height/height),invert=True)
            data.mask=np.ma.getmaskarray(data)|~view_mask
            values=data.compressed();values=values[np.isfinite(values)]
            if values.size<2:return {'status':'nodata','message':'No usable terrain samples in this view'}
            q=np.quantile(values,np.linspace(0,1,201)).tolist();heights,levels=knots(q)
            result={'id':scale_id,'status':'ok','scope':'locked-local-view','bbox':list(bounds),
                    'statistics_scale_m':spacing,'native_sample_scale_m':1,'quantiles':q,
                    'heights':heights,'levels':levels,'valid_statistic_cells':int(values.size),
                    'dataset_revision':revision,
                    'provenance':'Actual native DTM, coarse area-averaged view statistics within geographic view bounds; native samples unchanged'}
            result['legend']=legend(result)
            temporary=path.with_name(path.stem+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(result),encoding='utf-8');temporary.replace(path)
            return result

    def _tile_values(self,z,x,y,halo=0):
        if not self.available:raise ValueError('Native source unavailable or invalid')
        west,south,east,north=tile_bounds(z,x,y)
        spacing=(east-west)/256
        transform=Affine(spacing,0,west-halo*spacing,0,-spacing,north+halo*spacing)
        values=np.full((256+2*halo,256+2*halo),np.nan,dtype=np.float32)
        display=self.cache/'terrain_display_8m.tif'
        path=self.native if z>=15 or not display.exists() else display
        with RASTER_SLOTS,rasterio.Env(PROJ_NETWORK='OFF',GDAL_CACHEMAX=64000000),rasterio.open(path) as src:
            footprint=transform_bounds(src.crs,3857,*src.bounds,densify_pts=21)
            if west>footprint[2] or east<footprint[0] or south>footprint[3] or north<footprint[1]:return values
            reproject(rasterio.band(src,1),values,src_transform=src.transform,src_crs=src.crs,
                      src_nodata=src.nodata,dst_transform=transform,dst_crs='EPSG:3857',
                      dst_nodata=np.nan,resampling=Resampling.average,num_threads=1,warp_mem_limit=64)
        return values

    def colour_tile(self,z,x,y,scale_id,revision):
        definition=self.scale(scale_id)
        key=self._tile_key('colour',z,x,y,revision)
        key.append(file_signature(self.cache/('whole_scale.json' if scale_id=='whole' else scale_id+'.json')))
        return self.tiles.get_or_render(key,lambda:self._render_colour(z,x,y,definition))

    def _tile_key(self,kind,z,x,y,revision):
        if not self.available:raise ValueError('Native source unavailable or invalid')
        tile_bounds(z,x,y)
        display=self.cache/'terrain_display_8m.tif'
        path=self.native if z>=15 or not display.exists() else display
        # Fingerprints make cached bytes ineligible after input/style/code changes.
        return ['terrain-png-v1',rasterio.__version__,Image.__version__,kind,z,x,y,revision,
                file_signature(self.native),file_signature(path),file_signature(__file__),
                file_signature(Path(__file__).with_name('scale.py'))]

    def _render_colour(self,z,x,y,definition):
        values=self._tile_values(z,x,y)
        return png(rgba(values,definition))

    def shade_tile(self,z,x,y,revision):
        return self.tiles.get_or_render(self._tile_key('hillshade',z,x,y,revision),
                                        lambda:self._render_shade(z,x,y))

    def _render_shade(self,z,x,y):
        values=self._tile_values(z,x,y,halo=1)
        bounds=tile_bounds(z,x,y)
        latitude=MERCATOR.transform((bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2)[1]
        spacing=(bounds[2]-bounds[0])/256*math.cos(math.radians(latitude))
        dy,dx=np.gradient(values,spacing,spacing)
        az=math.radians(315);alt=math.radians(45)
        illumination=(math.sin(alt)+math.cos(alt)*(-dx*math.sin(az)+dy*math.cos(az)))/np.sqrt(1+dx*dx+dy*dy)
        gray=np.rint(np.nan_to_num(illumination,nan=0).clip(0,1)*255).astype(np.uint8)[1:-1,1:-1]
        valid=np.isfinite(illumination[1:-1,1:-1])
        return png(np.dstack([gray,gray,gray,valid.astype(np.uint8)*255]))
