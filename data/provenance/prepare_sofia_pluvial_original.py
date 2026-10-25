"""Prepare real Sofia terrain and optional native Copernicus IMD for the GEE demo.

The original 1 m terrain files are opened read-only. All hydrology is derived on
a separate aligned 5 m or 10 m grid. Absent IMD never becomes zero imperviousness.
Run this script with work/hydro_env/Scripts/python.exe from the workspace root.
"""
import argparse
import gc
import hashlib
import json
import math
import os
import time
from contextlib import ExitStack
from pathlib import Path

os.environ.setdefault('NUMBA_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
import numpy as np
import rasterio
from affine import Affine
from pysheds.grid import Grid
from pysheds.sview import Raster, ViewFinder
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import reproject, transform_bounds
from scipy.ndimage import binary_erosion
from numba import njit

# pysheds 0.5 calls the retired numpy.in1d API. np.isin on its 1-D inputs is
# equivalent; this compatibility alias does not change the routing algorithm.
if not hasattr(np, 'in1d'):
    np.in1d = np.isin

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent if OUT.parent.name == 'outputs' else OUT
SOURCE = ROOT / 'outputs/sofia_dtm_2024_1m_gee.tif' if OUT.parent.name == 'outputs' else OUT / 'sofia_dtm_2024_1m_gee.tif'
CRS = 'EPSG:7801'
CELL = 5
TRANSFORM = Affine(CELL, 0, 299392, 0, -CELL, 4753611)
SHAPE = (math.ceil(54343/CELL), math.ceil(51722/CELL))
CACHE = ROOT / 'work/pluvial_5m'
MEAN_NAME = 'terrain_mean_5m.tif'
DIRECTIONS = (64, 128, 1, 2, 4, 8, 16, 32)
FLAT_ROUTING_METHOD = 'equal-height-BFS-v1'
NODATA = -9999.0
START = time.monotonic()


def configure(cell_size):
    global CELL, TRANSFORM, SHAPE, CACHE, MEAN_NAME
    CELL = cell_size
    TRANSFORM = Affine(CELL, 0, 299392, 0, -CELL, 4753611)
    SHAPE = (math.ceil(54343/CELL), math.ceil(51722/CELL))
    CACHE = ROOT / ('work/pluvial' if CELL == 10 else 'work/pluvial_5m')
    CACHE.mkdir(exist_ok=True, parents=True)
    MEAN_NAME = 'terrain_mean_%dm.tif' % CELL


def log(stage, **details):
    message = {'stage': stage, 'elapsed_seconds': round(time.monotonic()-START, 1), **details}
    print(json.dumps(message), flush=True)
    (CACHE / 'progress.json').write_text(json.dumps(message, indent=2))


def save(path, data, description, dtype='float32', nodata=NODATA):
    with rasterio.open(path, 'w', driver='GTiff', width=SHAPE[1], height=SHAPE[0],
                       count=1, dtype=dtype, crs=CRS, transform=TRANSFORM,
                       nodata=nodata, tiled=True, blockxsize=512, blockysize=512,
                       compress='DEFLATE', predictor=3 if dtype == 'float32' else 2,
                       bigtiff='IF_SAFER') as dst:
        dst.write(np.asarray(data, dtype=dtype), 1)
        dst.set_band_description(1, description)
        dst.update_tags(VERTICAL_DATUM='Baltic 1982', VERTICAL_CRS_REFERENCE='EPSG:5786',
                        ANALYSIS_GRID='%d m; aligned to the original 1 m grid' % CELL,
                        MODEL_STATUS='Uncalibrated terrain/runoff screening inputs')


def read(path):
    with rasterio.open(path) as src:
        assert src.shape == SHAPE and src.transform == TRANSFORM
        return src.read(1)


def weighted(grid, fdir, values):
    vf = ViewFinder(affine=TRANSFORM, shape=SHAPE, crs=grid.crs, nodata=0)
    return grid.accumulation(fdir, weights=Raster(np.asarray(values, dtype=np.float64), vf),
                             dirmap=DIRECTIONS, routing='d8', algorithm='iterative')


@njit(cache=True)
def route_equal_height_flats(elevation, valid, boundary, fdir):
    """Route ties by outward BFS from downhill cells / open mask edges.

    Strict downhill D8 directions remain intact. Every newly routed flat cell
    points to an earlier routed equal-height cell, so tie routing is acyclic.
    No elevations, physical slopes, or pit-fill descriptors are changed.
    """
    h, w = elevation.shape
    dy = (-1,-1,0,1,1,1,0,-1)
    dx = (0,1,1,1,0,-1,-1,-1)
    codes = (64,128,1,2,4,8,16,32)
    initial = valid & ((fdir != 0) | boundary)
    queue = np.empty(np.count_nonzero(valid & ~initial), dtype=np.int64)
    tail = 0
    # Use the frozen initial mask to seed all outlet-adjacent flat cells first.
    for row in range(h):
        for col in range(w):
            if valid[row,col] and not initial[row,col]:
                for k in range(8):
                    rr, cc = row+dy[k], col+dx[k]
                    if (0 <= rr < h and 0 <= cc < w and initial[rr,cc]
                            and elevation[rr,cc] == elevation[row,col]):
                        fdir[row,col] = codes[k]
                        queue[tail] = row*w+col
                        tail += 1
                        break
    known = initial
    for k in range(tail):
        known.flat[queue[k]] = True
    head = 0
    while head < tail:
        row, col = queue[head]//w, queue[head]%w
        head += 1
        for k in range(8):
            rr, cc = row+dy[k], col+dx[k]
            if (0 <= rr < h and 0 <= cc < w and valid[rr,cc] and not known[rr,cc]
                    and elevation[rr,cc] == elevation[row,col]):
                fdir[rr,cc] = codes[(k+4)%8]
                known[rr,cc] = True
                queue[tail] = rr*w+cc
                tail += 1
    return fdir, np.count_nonzero(valid & ~known)


def terrain():
    mean_path = CACHE / MEAN_NAME
    if not mean_path.exists():
        log('averaging_complete_municipal_1m_terrain')
        elevation = np.full(SHAPE, NODATA, dtype=np.float32)
        with rasterio.open(SOURCE, OVERVIEW_LEVEL='NONE') as src:
            assert src.crs.to_epsg() == 7801
            assert src.shape == (54343, 51722)
            assert list(src.transform)[:6] == [1, 0, 299392, 0, -1, 4753611]
            assert src.nodata == NODATA
            reproject(rasterio.band(src, 1), elevation, src_transform=src.transform,
                      src_crs=CRS, src_nodata=src.nodata, dst_transform=TRANSFORM,
                      dst_crs=CRS, dst_nodata=NODATA, resampling=Resampling.average,
                      num_threads=2, warp_mem_limit=128)
        save(mean_path, elevation, 'mean_ground_elevation_m')
        del elevation
        gc.collect()
    if not (CACHE / 'filled_terrain.tif').exists():
        log('priority_flood_fill_for_depression_descriptor')
        grid = Grid.from_raster(str(mean_path))
        original = grid.read_raster(str(mean_path)).astype(np.float64)
        # The priority-flood implementation can mutate its working input array.
        # Save its result, then read the untouched mean raster separately below.
        filled = grid.fill_depressions(original)
        save(CACHE / 'filled_terrain.tif', filled, 'filled_ground_elevation_m')
        del grid, original, filled
        gc.collect()
    log('derive_depression_depth_against_unchanged_mean_raster')
    base = read(mean_path)
    filled = read(CACHE / 'filled_terrain.tif')
    valid = base != NODATA
    delta = np.where(valid, np.maximum(filled-base, 0), NODATA)
    save(CACHE / 'depression_depth.tif', delta, 'depression_fill_depth_m')
    del base, filled, valid, delta
    gc.collect()
    if not (CACHE / 'slope.tif').exists():
        elevation = read(mean_path)
        elevation[elevation == NODATA] = np.nan
        dy, dx = np.gradient(elevation, float(CELL), float(CELL))
        slope = np.degrees(np.arctan(np.hypot(dx, dy)))
        slope[~np.isfinite(slope)] = NODATA
        save(CACHE / 'slope.tif', slope, 'slope_degrees')
        del elevation, dy, dx, slope
        gc.collect()
    flow_path = CACHE / 'flow_direction.tif'
    reroute = not flow_path.exists()
    if not reroute:
        with rasterio.open(flow_path) as cached_flow:
            reroute = cached_flow.tags().get('FLAT_ROUTING_METHOD') != FLAT_ROUTING_METHOD
    if reroute:
        log('derive_strict_downhill_d8_then_equal_height_flat_routes')
        filled_path = CACHE / 'filled_terrain.tif'
        grid = Grid.from_raster(str(filled_path))
        filled = grid.read_raster(str(filled_path)).astype(np.float64)
        valid = read(mean_path) != NODATA
        boundary = valid & ~binary_erosion(valid, structure=np.ones((3,3)), border_value=0)
        fdir = grid.flowdir(filled, routing='d8', dirmap=DIRECTIONS, nodata_out=0,
                           flats=0, pits=0).astype(np.uint8)
        del filled, grid
        gc.collect()
        elevation = read(filled_path)
        routed, unresolved = route_equal_height_flats(elevation, valid, boundary, np.asarray(fdir))
        if unresolved:
            raise RuntimeError('Unresolved interior flat cells: %d; do not use routing output' % unresolved)
        log('flat_routing_verified', unresolved_interior_cells=int(unresolved))
        save(CACHE / 'flow_direction.tif', fdir, 'd8_flow_direction', dtype='uint8', nodata=0)
        with rasterio.open(flow_path, 'r+') as dst:
            dst.update_tags(FLAT_ROUTING_METHOD=FLAT_ROUTING_METHOD)
        # Any previously routed sealing totals must be rebuilt on a new graph.
        for stale in ('upstream_sealed_area.tif','missing_upstream_imd.tif'):
            if (CACHE/stale).exists():
                (CACHE/stale).unlink()
        del elevation, valid, boundary, routed, fdir
        gc.collect()
    grid = Grid.from_raster(str(mean_path))
    fdir = grid.read_raster(str(CACHE / 'flow_direction.tif'))
    elevation = read(mean_path)
    valid = elevation != NODATA
    if reroute or not (CACHE / 'contributing_area.tif').exists():
        log('accumulate_all_valid_terrain_cells')
        accumulation = weighted(grid, fdir, valid.astype(np.float64) * CELL**2)
        assert np.all(np.asarray(accumulation)[valid] >= CELL**2)
        save(CACHE / 'contributing_area.tif', np.where(valid, accumulation, NODATA),
             'upstream_contributing_area_m2')
        del accumulation
        gc.collect()
    if reroute or not (CACHE / 'boundary_influence.tif').exists():
        log('propagate_potential_upstream_boundary_gaps')
        boundary = valid & ~binary_erosion(valid, structure=np.ones((3, 3)), border_value=0)
        influence = weighted(grid, fdir, boundary.astype(np.float64))
        save(CACHE / 'boundary_influence.tif',
             np.where(valid, (np.asarray(influence) > 0).astype(np.float32), NODATA),
             'possible_missing_upstream_terrain')
        del boundary, influence
        gc.collect()
    log('terrain_ready', analysis_cell_size_m=CELL, valid_analysis_cells=int(valid.sum()),
        terrain_area_nominal_km2=float(valid.sum()*CELL**2/1000000))


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def imperviousness(paths):
    log('check_native_imperviousness', inputs=[str(path) for path in paths])
    provenance = []
    # Mosaic only the small native-10-m window covering the municipal grid.
    # This supports downloads spanning multiple 100-km tiles without merging Europe.
    bounds = rasterio.transform.array_bounds(*SHAPE, TRANSFORM)
    native_bounds = transform_bounds(CRS, 'EPSG:3035', *bounds, densify_pts=41)
    native_bounds = (math.floor(native_bounds[0]/10)*10-20,
                     math.floor(native_bounds[1]/10)*10-20,
                     math.ceil(native_bounds[2]/10)*10+20,
                     math.ceil(native_bounds[3]/10)*10+20)
    with ExitStack() as stack:
        sources = []
        for path in paths:
            label = path.name.upper()
            if 'IMD' not in label or '2024' not in label or 'IMDC' in label:
                raise ValueError('Keep the original IMD 2024 density filename; do not supply confidence, RGB or another year: '+str(path))
            src = stack.enter_context(rasterio.open(path))
            if src.count != 1 or src.dtypes[0] != 'uint8':
                raise ValueError('Expected the single-band Byte density raster: '+str(path))
            if src.crs is None or src.crs.to_epsg() != 3035:
                raise ValueError('Expected the native EPSG:3035 CLMS product: '+str(path))
            if not np.allclose([src.transform.a, src.transform.e, src.transform.b, src.transform.d],
                               [10, -10, 0, 0], rtol=0, atol=1e-7):
                raise ValueError('Expected native 10 m pixels, not the 100 m product or resampled data')
            if src.nodata not in (None, 255):
                raise ValueError('Expected IMD NoData 255 (or an undeclared 255); zero is valid pervious land')
            sources.append(src)
            provenance.append({'file': str(path), 'sha256': file_hash(path),
                               'crs': str(src.crs), 'resolution_m': list(src.res),
                               'nodata': src.nodata, 'dtype': src.dtypes[0]})
        mosaic, native_transform = merge(sources, bounds=native_bounds, res=10,
                                         nodata=255, dtype='uint8', method='first')
    values = mosaic[0]
    if np.any((values > 100) & (values != 255)):
        raise ValueError('The raw density window contains codes outside 0..100 and NoData 255')
    native_valid = (values <= 100).astype(np.uint8)
    log('align_native_imperviousness', native_window_shape=list(values.shape))
    imd = np.full(SHAPE, NODATA, dtype=np.float32)
    reproject(values, imd, src_transform=native_transform, src_crs='EPSG:3035',
              src_nodata=255, dst_transform=TRANSFORM, dst_crs=CRS, dst_nodata=NODATA,
              resampling=Resampling.average, num_threads=2, warp_mem_limit=128)
    coverage = np.full(SHAPE, NODATA, dtype=np.float32)
    reproject(native_valid, coverage, src_transform=native_transform, src_crs='EPSG:3035',
              dst_transform=TRANSFORM, dst_crs=CRS, dst_nodata=NODATA,
              resampling=Resampling.average, num_threads=2, warp_mem_limit=128)
    valid = read(CACHE / MEAN_NAME) != NODATA
    known = (imd >= 0) & (imd <= 100) & (coverage >= 0.999)
    del coverage, mosaic, values, native_valid
    gc.collect()
    if not np.any(known & valid):
        raise ValueError('No valid density percentages overlap the municipal terrain')
    save(CACHE / 'imperviousness_2024.tif', np.where(known & valid, imd, NODATA),
         'imperviousness_density_2024_pct')
    grid = Grid.from_raster(str(CACHE / MEAN_NAME))
    fdir = grid.read_raster(str(CACHE / 'flow_direction.tif'))
    log('accumulate_upstream_sealed_area')
    sealed = weighted(grid, fdir, np.where(known & valid, imd * CELL**2 / 100, 0))
    # Percent / 100 * cell area = sealed area per analysis cell, in m2.
    unknown = weighted(grid, fdir, (valid & ~known).astype(np.float64))
    complete = valid & (np.asarray(unknown) == 0)
    save(CACHE / 'upstream_sealed_area.tif', np.where(complete, sealed, NODATA),
         'upstream_sealed_area_m2')
    save(CACHE / 'missing_upstream_imd.tif',
         np.where(valid, (np.asarray(unknown) > 0).astype(np.float32), NODATA),
         'missing_upstream_imperviousness')
    log('imperviousness_ready', covered_valid_cells=int(np.count_nonzero(known & valid)),
        total_valid_cells=int(valid.sum()), complete_upstream_imd_cells=int(complete.sum()))
    (CACHE / 'imperviousness_provenance.json').write_text(json.dumps({
        'product': 'Copernicus CLMS Imperviousness Density 2024, native 10 m',
        'source_url': 'https://land.copernicus.eu/en/products/high-resolution-layer-imperviousness/imperviousness-density-2024',
        'inputs': provenance, 'native_window_bounds_epsg3035': native_bounds,
        'resampling': 'area average to aligned %d m grid; no additional 10 m information' % CELL,
        'coverage_policy': 'Require at least 99.9% valid source coverage per target pixel; flag unknown upstream IMD.'
    }, indent=2))


def bundle():
    bands = [('mean_ground_elevation_m', MEAN_NAME),
             ('depression_fill_depth_m', 'depression_depth.tif'),
             ('slope_degrees', 'slope.tif'),
             ('upstream_contributing_area_m2', 'contributing_area.tif'),
             ('possible_missing_upstream_terrain', 'boundary_influence.tif'),
             ('imperviousness_density_2024_pct', 'imperviousness_2024.tif'),
             ('upstream_sealed_area_m2', 'upstream_sealed_area.tif'),
             ('missing_upstream_imperviousness', 'missing_upstream_imd.tif')]
    target = OUT / ('sofia_pluvial_inputs_%dm.tif' % CELL)
    with rasterio.open(target, 'w', driver='GTiff', width=SHAPE[1], height=SHAPE[0],
                       count=len(bands), dtype='float32', crs=CRS, transform=TRANSFORM,
                       nodata=NODATA, tiled=True, blockxsize=512, blockysize=512,
                       compress='DEFLATE', predictor=3, bigtiff='IF_SAFER',
                       interleave='band', num_threads=2) as dst:
        for index, (name, filename) in enumerate(bands, 1):
            path = CACHE / filename
            data = read(path) if path.exists() else np.full(SHAPE, NODATA, dtype=np.float32)
            dst.write(data, index)
            dst.set_band_description(index, name)
            del data
        dst.update_tags(VERTICAL_DATUM='Baltic 1982', MODEL_STATUS='UNCALIBRATED_SCREENING',
                        IMPERVIOUSNESS_AVAILABLE=str(all((CACHE/f).exists() for f in
                            ('imperviousness_2024.tif','upstream_sealed_area.tif','missing_upstream_imd.tif'))),
                        ROUTING='Strict-downhill D8 on priority-flood-filled terrain; equal-height BFS ties',
                        SOURCE_DTM='SofiaPlan dataset 656; original 1 m grid averaged to %d m' % CELL)
    report = {'source_1m_terrain': str(SOURCE), 'output': str(target),
              'shape': SHAPE, 'transform': list(TRANSFORM)[:6], 'crs': CRS,
              'analysis_cell_size_m': CELL,
              'bands': [{'index': index, 'name': name,
                         'available': (CACHE/filename).exists()}
                        for index, (name, filename) in enumerate(bands, 1)],
              'imperviousness_available': all((CACHE/f).exists() for f in
                   ('imperviousness_2024.tif','upstream_sealed_area.tif','missing_upstream_imd.tif')),
              'flat_routing_method': FLAT_ROUTING_METHOD,
              'imperviousness_provenance': json.loads((CACHE/'imperviousness_provenance.json').read_text())
                  if (CACHE/'imperviousness_provenance.json').exists() else None,
              'missing_data_policy': 'Absent IMD is NoData; full index remains unavailable.',
              'boundary_policy': 'Flag downstream cells influenced by any terrain mask/extent edge.',
              'limitations': ['Depression depth is not water depth.',
                              'D8 routing does not model buildings, culverts, sewer hydraulics or timing.',
                              'Terrain grid spacing does not establish vertical accuracy.',
                              'No flood probability or calibrated rainfall return period is supplied.'],
              'output_bytes': target.stat().st_size,
              'elapsed_seconds': round(time.monotonic()-START, 1)}
    (OUT / ('preparation_manifest_%dm.json' % CELL)).write_text(json.dumps(report, indent=2))
    log('bundle_written', output=str(target), bytes=target.stat().st_size,
        imperviousness_available=report['imperviousness_available'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cell-size', type=int, choices=[5, 10], default=5)
    parser.add_argument('--bundle-only', action='store_true')
    parser.add_argument('--imperviousness', type=Path, nargs='+',
                        help='One or more unmodified native 10 m IMD 2024 density GeoTIFF tiles')
    parser.add_argument('--source-dtm', type=Path,
                        help='Optional path to the corrected horizontal-CRS-only 1 m GeoTIFF')
    args = parser.parse_args()
    configure(args.cell_size)
    if args.source_dtm:
        SOURCE = args.source_dtm.resolve()
    with rasterio.Env(GDAL_CACHEMAX=128000000, PROJ_NETWORK='OFF'):
        if not args.bundle_only:
            terrain()
        if args.imperviousness:
            imperviousness([path.resolve() for path in args.imperviousness])
        bundle()
