"""Area-selected, explicit drainage-loss scenario on the genuine aligned 5 m grid.

This is an assumed local water balance, not a sewer hydraulic model, routed
inundation, predicted flood depth, measured clogging or calibrated probability.
All mapped green polygons absorb all rainfall in this user-requested scenario.
"""
import hashlib
import json
import math
import re
import sqlite3
import tempfile
import threading
from contextlib import closing, nullcontext
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.windows import Window
from rasterio.warp import reproject
from shapely import from_wkb, transform, union_all
from shapely.geometry import mapping, shape
from scipy.ndimage import binary_dilation, find_objects, label

from .terrain import RASTER_SLOTS, tile_bounds, png
from .tile_cache import file_signature, read_json_cached
from .cloud_state import MAX_SCENARIO_BYTES

TO_METRIC = Transformer.from_crs(4326, 7801, always_xy=True)
TO_GEO = Transformer.from_crs(7801, 4326, always_xy=True)
METHOD = 'area-drainage-loss-local-depression-storage-v2'
MAX_AREA_M2 = 25_000_000
MAX_CELLS = 1_000_000
NODATA = -9999.0
PARAMETERS = {'rainfall_mm': 30.0, 'duration_minutes': 60.0,
              'drainage_capacity_mm_h': 15.0, 'blockage_percent': 100.0,
              'influence_distance_m': 50.0, 'runoff_coefficient': 0.9,
              'river_proximity_m': 100.0}
LIMITS = {'rainfall_mm': (0, 1000), 'duration_minutes': (1, 1440),
          'drainage_capacity_mm_h': (0, 500), 'blockage_percent': (0, 100),
          'influence_distance_m': (5, 500), 'runoff_coefficient': (0, 1),
          'river_proximity_m': (5, 1000)}
MODES = {'baseline': 1, 'clogged': 2, 'change': 3,
         'depth_baseline': 4, 'depth_clogged': 5, 'depth_change': 6}
BUILD_LOCK = threading.Lock()
ASSUMPTIONS = [
    'All source dates are treated as compatible by the user scenario assumption; real source dates and spatial coverage remain unchanged.',
    'All mapped green polygons absorb all rainfall and are excluded from both baseline and clogged scenario values; this is an assumption, not measured infiltration.',
    'Drainage capacity is an assumed area-equivalent removal rate in mm/hour, not a measured capacity assigned to individual pipes.',
    'Only selected existing source routes create the assumed influence buffer. Planned and open-channel source routes are reported separately and do not imply functioning pipes.',
    'The influence distance is a user-defined neighbourhood, not a catchment or connected pipe service area. Water is not routed between cells.',
    'Excess runoff is potential locally unremoved runoff in mm; it is not predicted flood depth, water level, damage or calibrated flood probability.',
    'Mapped open water, mapped river channels, stadium footprints, uncertain terrain and cells outside the genuine terrain coverage are excluded. River/stadium exclusion is a user policy, not evidence of safety. Green and area membership use 5 m cell centres.',
    'The unchanged terrain ponding indicator supplies context. No arbitrary combined flood probability is fitted.'
    , 'Estimated ponding depth allocates only locally generated potential excess runoff within each 8-connected positive-depression component. Its actual mean terrain elevations and minimum recorded fill-surface elevation define a capped storage curve; this is not a routed inundation forecast.'
    , 'Runoff on zero-fill land is unallocated. Runoff exceeding a component storage capacity is reported as overflow, without inventing its downstream destination. Components near the selection or excluded-land boundary are potentially truncated.'
]


class ScenarioStale(ValueError):
    pass


def runoff_values(rainfall_mm, duration_minutes, drainage_capacity_mm_h,
                  blockage_percent, runoff_coefficient):
    effective = rainfall_mm * runoff_coefficient
    removal = drainage_capacity_mm_h * duration_minutes / 60
    return effective, max(0.0, effective-removal), max(0.0, effective-removal*(1-blockage_percent/100))


def scenario_rgba(values, scale_mm):
    values = np.asarray(values, dtype=np.float32)
    valid = np.isfinite(values) & (values >= 0)
    t = np.clip(np.where(valid, values, 0) / max(float(scale_mm), 1e-9), 0, 1)
    stops = [0, .25, .5, .75, 1]
    colors = np.array([[255, 240, 150, 0], [255, 197, 65, 95],
                       [250, 117, 38, 155], [228, 42, 83, 205], [135, 21, 145, 235]])
    result = np.rint(np.stack([np.interp(t, stops, colors[:, i]) for i in range(4)], axis=-1)).astype('uint8')
    result[~valid] = 0
    return result


def storage_depths(elevation, fill_depth, eligible, baseline_mm, clogged_mm,
                   influence, cell_area=25.0):
    """Capped local storage, not hydrodynamic routing or an AOI-wide bathtub.

    Each 8-connected positive-fill component retains only runoff generated in
    that same component. The common cap is min(original elevation + fill).
    Mask-cut components are retained with an explicit truncation warning.
    Float32 depths round down so no numerical encoding creates water volume.
    """
    elevation = np.asarray(elevation, dtype='float64')
    fill_depth = np.asarray(fill_depth, dtype='float64')
    eligible = np.asarray(eligible, dtype=bool)
    baseline_mm = np.asarray(baseline_mm, dtype='float64')
    clogged_mm = np.asarray(clogged_mm, dtype='float64')
    influence = np.asarray(influence, dtype=bool)
    if (any(a.shape != eligible.shape for a in [elevation, fill_depth, baseline_mm, clogged_mm, influence])
        or eligible.ndim != 2 or not math.isfinite(cell_area) or cell_area <= 0
        or np.any(~np.isfinite(elevation[eligible])) or np.any(~np.isfinite(fill_depth[eligible]))
        or np.any(fill_depth[eligible] < 0) or np.any(~np.isfinite(baseline_mm[eligible]))
        or np.any(~np.isfinite(clogged_mm[eligible])) or np.any(baseline_mm[eligible] < 0)
        or np.any(clogged_mm[eligible] < baseline_mm[eligible])):
        raise ValueError('Storage calculation requires finite aligned terrain and nondecreasing nonnegative runoff')
    positive = eligible & (fill_depth > 0)
    labels, count = label(positive, structure=np.ones((3,3), dtype='uint8'))
    slices = find_objects(labels)
    boundary = positive & binary_dilation(~eligible, structure=np.ones((3,3), dtype=bool), border_value=1)
    boundary_ids = set(int(v) for v in np.unique(labels[boundary]) if v)
    partial = 0
    depth_outputs = [np.where(eligible, 0, NODATA).astype('float32') for _ in range(2)]
    overflow = [0.0, 0.0]
    numerical = [0.0, 0.0]
    capacity_total = 0.0
    summaries = []

    def allocate(beds, spill, volume, capacity):
        target = min(volume, capacity)
        if target <= 0 or capacity <= 0:
            return np.zeros(beds.shape, dtype='float32'), 0.0, target
        below = np.sort(beds[beds < spill])
        prefix = np.cumsum(below, dtype='float64')
        indices = np.arange(below.size, dtype='float64')
        required = (below*indices - np.r_[0.0,prefix[:-1]])*cell_area
        active = max(1, int(np.searchsorted(required,target,side='right')))
        level = min(spill,(target/cell_area + prefix[active-1])/active)
        exact = np.maximum(0.0,level-beds)
        encoded = exact.astype('float32')
        rounded_up = encoded.astype('float64') > exact
        encoded[rounded_up] = np.nextafter(encoded[rounded_up], np.float32(0))
        stored = float(np.sum(encoded,dtype='float64')*cell_area)
        return encoded,stored,max(0.0,target-stored)

    for identity, region in enumerate(slices,1):
        if region is None:
            continue
        members = labels[region] == identity
        beds = elevation[region][members]
        fills = fill_depth[region][members]
        spill = float(np.min(beds+fills))
        capacity = float(np.maximum(0.0,spill-beds).sum(dtype='float64')*cell_area)
        capacity_total += capacity
        flags = influence[region][members]
        partial += int(bool(flags.any()) and not bool(flags.all()))
        inputs = []
        stores = []
        for index, runoff in enumerate([baseline_mm,clogged_mm]):
            volume = float(np.sum(runoff[region][members],dtype='float64')*cell_area/1000)
            depths,stored,residual = allocate(beds,spill,volume,capacity)
            depth_outputs[index][region][members] = depths
            overflow[index] += max(0.0,volume-capacity)
            numerical[index] += residual
            inputs.append(volume)
            stores.append(stored)
        if len(summaries) < 100:
            summaries.append({'component_id':identity,'cell_count':int(members.sum()),
                              'spill_elevation_m':spill,'storage_capacity_m3':capacity,
                              'potentially_boundary_truncated':identity in boundary_ids,
                              'baseline_source_runoff_m3':inputs[0],'clogged_source_runoff_m3':inputs[1],
                              'baseline_stored_volume_m3':stores[0],'clogged_stored_volume_m3':stores[1]})

    summaries_by_mode = {}
    for index, (name, runoff) in enumerate([('baseline',baseline_mm),('clogged',clogged_mm)]):
        depths = depth_outputs[index]
        wet = eligible & (depths > 0)
        wet_values = depths[wet]
        stored = float(np.sum(depths[eligible],dtype='float64')*cell_area)
        source_volume = float(np.sum(runoff[eligible],dtype='float64')*cell_area/1000)
        unallocated = float(np.sum(runoff[eligible & ~positive],dtype='float64')*cell_area/1000)
        unallocated_total = unallocated+overflow[index]+numerical[index]
        summaries_by_mode[name] = {
            'max_depth_m':float(wet_values.max()) if wet_values.size else 0.0,
            'p95_depth_m':float(np.quantile(wet_values,.95)) if wet_values.size else 0.0,
            'p95_basis':'Positive estimated-depth cells only',
            'ponded_area_m2':float(wet.sum()*cell_area),
            **{key:float(np.count_nonzero(eligible & (depths>=threshold))*cell_area)
               for key,threshold in [('area_at_least_0_05m_m2',.05),('area_at_least_0_1m_m2',.1),('area_at_least_0_3m_m2',.3)]},
            'stored_volume_m3':stored,'overflow_volume_m3':overflow[index],
            'unallocated_nondepression_volume_m3':unallocated,
            'numerical_storage_residual_m3':numerical[index],
            'unallocated_total_volume_m3':unallocated_total,
            'source_runoff_volume_m3':source_volume,
            'volume_balance_error_m3':source_volume-stored-unallocated_total}
    change = np.where(eligible,depth_outputs[1]-depth_outputs[0],NODATA).astype('float32')
    summaries_by_mode['change'] = {
        'additional_stored_volume_m3':summaries_by_mode['clogged']['stored_volume_m3']-summaries_by_mode['baseline']['stored_volume_m3'],
        'max_additional_depth_m':float(change[eligible].max()) if eligible.any() else 0.0}
    summaries_by_mode['components'] = {
        'count':int(count),'boundary_truncated_count':len(boundary_ids),'partial_influence_count':partial,
        'positive_depression_area_m2':float(positive.sum()*cell_area),
        'storage_capacity_m3':capacity_total,
        'connectivity':8,
        'boundary_rule':'A component adjacent to an AOI edge or excluded cell is potentially truncated; partial influence means the assumed loss buffer crosses it, not a hydraulic basin boundary.',
        'details_first_100':summaries,'details_truncated':count>100}
    summaries_by_mode['interpretation'] = 'Estimated local depression-storage depth in metres, using actual terrain and original fill-depth components. No surface-flow routing, connected sewer hydraulics, downstream overflow destination or calibrated inundation forecast.'
    return depth_outputs[0],depth_outputs[1],change,summaries_by_mode


class CloggingScenarios:
    def __init__(self, root, pluvial, river_context=None, cloud_state=None, snapshot=None):
        self.root = Path(root)
        self.pluvial = pluvial
        self.database = self.root/'data/cache/spatial.sqlite'
        self.directory = self.root/'data/cache/clogging'
        self.tiles = pluvial.tiles
        self.river_context = river_context
        self.cloud_state = cloud_state
        self.snapshot = snapshot
        # Rainfall edits do not alter geometry, eligibility or river distances.
        # Keep at most four bounded grids so slider updates reuse exact distances.
        self.river_grids = OrderedDict()

    def river_grid(self, grid, eligible, proximity):
        revision = self.river_context.meta().get('revision')
        key = (tuple(grid)[:6],eligible.shape,hashlib.sha256(eligible.tobytes()).hexdigest(),float(proximity),revision)
        if key in self.river_grids:
            self.river_grids.move_to_end(key)
            return self.river_grids[key]
        data = self.river_context.classify_grid(grid,eligible,proximity)
        self.river_grids[key] = data
        while len(self.river_grids) > 4:
            self.river_grids.popitem(last=False)
        return data

    def source_state(self):
        meta = self.pluvial.meta()
        if not meta.get('available') or not self.database.is_file():
            raise RuntimeError('Real terrain, verified water/river/stadium exclusions and full vector index are required for a blockage scenario')
        paths = [self.database, self.pluvial.path, self.pluvial.receipt,
                 self.pluvial.water.path, self.pluvial.water.receipt,
                 self.pluvial.exclusions.path, self.pluvial.exclusions.receipt]
        revision_path = self.root/'data/cache/revision.txt'
        if revision_path.is_file():
            paths.append(revision_path)
        river_meta = self.river_context.meta() if self.river_context is not None else {}
        state = {'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'screening_exclusion_implementation_sha256': hashlib.sha256(Path(__file__).with_name('screening_exclusions.py').read_bytes()).hexdigest(),
                'river_implementation_sha256': hashlib.sha256(Path(__file__).with_name('river_context.py').read_bytes()).hexdigest() if self.river_context is not None else None,
                'pluvial_revision': meta['revision'],
                'river_revision': river_meta.get('revision') if river_meta.get('available') else None,
                'water_revision': meta['water_exclusion']['revision'],
                'screening_exclusions_revision': meta['screening_exclusions']['revision'],
                'spatial_revision': revision_path.read_text(encoding='ascii').strip() if revision_path.is_file() else None,
                'files': [list(file_signature(path)) for path in paths]}
        if self.snapshot is not None:
            # The manifest was SHA-verified at startup. Portable source identity
            # excludes host paths, inode numbers and filesystem timestamps.
            state.update(self.snapshot.state(paths))
        return state

    def meta(self):
        try:
            state = self.source_state()
            return {'available': True, 'method': METHOD, 'defaults': PARAMETERS,
                    'parameter_limits': {k: list(v) for k, v in LIMITS.items()},
                    'max_area_km2': MAX_AREA_M2/1e6, 'max_grid_cells': MAX_CELLS,
                    'analysis_resolution_m': 5, 'source_revisions': state,
                    'assumptions': ASSUMPTIONS, 'modes': list(MODES),
                    'value_unit': 'mm potential locally unremoved runoff; m estimated local depression-storage depth',
                    'interpretation': 'Hypothetical area-equivalent drainage loss and capped local depression storage; no pipe-network hydraulics or measured clogging.'}
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            return {'available': False, 'message': str(error)}

    @staticmethod
    def region(geometry):
        if not isinstance(geometry, dict) or geometry.get('type') != 'Polygon':
            raise ValueError('Selection must be a GeoJSON Polygon in longitude/latitude')
        coordinates = geometry.get('coordinates')
        if not isinstance(coordinates, (list, tuple)) or not coordinates:
            raise ValueError('Polygon rings are required')
        count = 0
        for ring in coordinates:
            if not isinstance(ring, (list, tuple)) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError('Polygon rings must be closed with at least four coordinates')
            count += len(ring)
            for coordinate in ring:
                if (not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2
                    or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in coordinate)
                    or not -180 <= coordinate[0] <= 180 or not -85 <= coordinate[1] <= 85):
                    raise ValueError('Finite longitude/latitude coordinate pairs are required')
        if count > 5000:
            raise ValueError('Selection has too many vertices; maximum 5000')
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError('Selection polygon must be nonempty and valid; it is not silently repaired')
        metric = transform(polygon, TO_METRIC.transform, interleaved=False)
        if not math.isfinite(metric.area) or metric.area <= 0 or metric.area > MAX_AREA_M2:
            raise ValueError('Select a positive area of at most 25 square kilometres')
        return polygon, metric

    @staticmethod
    def parameters(values):
        if set(values) - set(PARAMETERS):
            raise ValueError('Unknown scenario parameter')
        params = {**PARAMETERS, **values}
        for key, value in params.items():
            low, high = LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key} must be finite and between {low} and {high}')
            params[key] = float(value)
        return params

    def candidates_and_green(self, polygon, metric):
        w, s, e, n = polygon.bounds
        rows = []
        greens = []
        with closing(sqlite3.connect('file:'+self.database.as_posix()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            records = db.execute("SELECT f.source_id,f.status,f.kind,f.geometry FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=? AND ((f.kind='routes' AND f.zone='all') OR f.kind='green')", (e,w,n,s))
            for row in records:
                geom = from_wkb(row['geometry'])
                if not geom.intersects(polygon):
                    continue
                projected = transform(geom, TO_METRIC.transform, interleaved=False)
                clipped = projected.intersection(metric)
                if row['kind'] == 'green':
                    if not clipped.is_empty and clipped.area > 0:
                        greens.append(clipped)
                elif clipped.length > 0:
                    rows.append({'source_id': str(row['source_id']), 'status': row['status'],
                                 'clipped_length_m': float(clipped.length), '_geometry': clipped})
        rows.sort(key=lambda row: row['source_id'])
        return rows, greens

    def create(self, geometry, selected_route_ids=None, **values):
        polygon, metric = self.region(geometry)
        params = self.parameters(values)
        source = self.source_state()
        if selected_route_ids is not None and (not isinstance(selected_route_ids, list)
                or len(selected_route_ids) > 2000 or any(not isinstance(v, str) or len(v) > 200 for v in selected_route_ids)):
            raise ValueError('selected_route_ids must be a list of at most 2000 source IDs')
        with rasterio.open(self.pluvial.path) as src:
            west, south, east, north = metric.bounds
            col0 = max(0, math.floor((west-src.transform.c)/src.transform.a))
            col1 = min(src.width, math.ceil((east-src.transform.c)/src.transform.a))
            row0 = max(0, math.floor((src.transform.f-north)/(-src.transform.e)))
            row1 = min(src.height, math.ceil((src.transform.f-south)/(-src.transform.e)))
            if row1 <= row0 or col1 <= col0:
                raise ValueError('Selection does not intersect the actual terrain grid')
            height, width = row1-row0, col1-col0
            if height*width > MAX_CELLS:
                raise ValueError('Selection bounding grid exceeds 1,000,000 cells; draw a more compact or smaller area')
            window = Window(col0, row0, width, height)
            grid = src.window_transform(window)
        candidates, greens = self.candidates_and_green(polygon, metric)
        known_ids = {r['source_id'] for r in candidates}
        if selected_route_ids is not None and set(selected_route_ids)-known_ids:
            raise ValueError('Selected route IDs must intersect the drawn area')
        selected = set(selected_route_ids) if selected_route_ids is not None else {r['source_id'] for r in candidates if r['status'] == 'existing'}
        key = {'method': METHOD, 'geometry': geometry, 'selected_route_ids': sorted(selected), 'parameters': params, 'source': source}
        identity = hashlib.sha256(json.dumps(key, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()[:32]
        target = self.directory/identity
        with BUILD_LOCK, self.cache_lease(identity,reserve_bytes=MAX_SCENARIO_BYTES):
            if self.cloud_state is not None and not (target/'result.json').is_file():
                self.cloud_state.restore_scenario(target,identity)
            if (target/'result.json').is_file():
                result = self.result(identity)
                if self.cloud_state is not None:
                    self.cloud_state.persist_scenario(target,identity)
                return result
            self.directory.mkdir(parents=True, exist_ok=True)
            active = [r['_geometry'] for r in candidates if r['source_id'] in selected and r['status'] == 'existing']
            shape_hw = (height, width)
            def burn(geoms):
                return rasterize([(geom, 1) for geom in geoms], out_shape=shape_hw, transform=grid, fill=0,
                                 dtype='uint8', all_touched=False).astype(bool) if geoms else np.zeros(shape_hw, dtype=bool)
            area = burn([metric])
            green = burn(greens) & area
            influence_geometry = union_all(active).buffer(params['influence_distance_m']).intersection(metric) if active else None
            influence = burn([influence_geometry] if influence_geometry is not None and not influence_geometry.is_empty else []) & area
            with rasterio.open(self.pluvial.path) as src, rasterio.open(self.pluvial.water.path) as water_src, rasterio.open(self.pluvial.exclusions.path) as exclusion_src:
                terrain = src.read([1,2,5,6,8], window=window)
                water = water_src.read(1, window=window) == 1
                policy_flags = exclusion_src.read(1, window=window)
                policy_excluded = policy_flags > 0
            finite_terrain = np.all(np.isfinite(terrain) & (terrain != NODATA), axis=0)
            valid = finite_terrain & (terrain[1] >= 0) & (terrain[2] == 0) & (terrain[3] >= 0) & (terrain[3] <= 100) & (terrain[4] >= 0) & (terrain[4] <= 100)
            eligible = area & valid & ~water & ~green & ~policy_excluded
            impacted = eligible & influence
            effective, baseline_mm, clogged_mm = runoff_values(**{k: v for k,v in params.items() if k not in ['influence_distance_m','river_proximity_m']})
            baseline = np.full(shape_hw, NODATA, dtype='float32')
            baseline[eligible] = baseline_mm
            clogged = baseline.copy()
            clogged[impacted] = clogged_mm
            change = np.full(shape_hw, NODATA, dtype='float32')
            change[eligible] = 0
            change[impacted] = clogged_mm-baseline_mm
            cell_area = abs(grid.a*grid.e)
            depth_baseline,depth_clogged,depth_change,depth_statistics = storage_depths(
                terrain[0],terrain[1],eligible,baseline,clogged,influence,cell_area)
            depth_legend = {'unit':'m estimated local depression-storage depth',
                            'minimum_m':0,'maximum_m':max(.05,depth_statistics['clogged']['max_depth_m']),
                            'same_scale_for_all_modes':True,'zero_transparent':True,
                            'minimum_display_range_m':.05}
            river_classes = np.where(eligible,0,255).astype('uint8')
            river_summary = {'available':False,'revision':None,'threshold_m':params['river_proximity_m'],
                             'eligible_area_m2':float(eligible.sum()*cell_area),
                             'near_river_area_m2':0.0,'away_from_mapped_river_area_m2':0.0,
                             'unknown_area_m2':float(eligible.sum()*cell_area),
                             'class_area_m2':{'river_adjacent_possible_mixed':0.0,'away_from_mapped_river':0.0,'unknown':float(eligible.sum()*cell_area)},
                             'interpretation':'Mapped-river context is unavailable; mechanism remains unknown, not assumed pluvial.'}
            if self.river_context is not None:
                river_grid = self.river_grid(grid,eligible,params['river_proximity_m'])
                river_summary = river_grid['summary']
                if river_summary.get('available'):
                    known = eligible & np.isfinite(river_grid['distance_m'])
                    river_classes[known & river_grid['near_river']] = 1
                    river_classes[known & ~river_grid['near_river']] = 2
            river_summary = {**river_summary,'depth_by_proximity':{},
                             'filter_changes':'Display only; full-AOI statistics and six-band download are unchanged.',
                             'class_codes':{'unknown':0,'river_adjacent_possible_mixed':1,'away_from_mapped_river':2,'outside_or_excluded':255}}
            for name,depths in [('baseline',depth_baseline),('clogged',depth_clogged)]:
                river_summary['depth_by_proximity'][name] = {
                    category:{'ponded_area_m2':float(np.count_nonzero((river_classes==code) & (depths>0))*cell_area),
                              'stored_volume_m3':float(np.sum(depths[river_classes==code],dtype='float64')*cell_area),
                              'max_depth_m':float(depths[river_classes==code].max()) if np.any(river_classes==code) else 0.0}
                    for category,code in [('unknown',0),('river_adjacent_possible_mixed',1),('away_from_mapped_river',2)]}
            count = lambda mask: int(np.count_nonzero(mask))
            area_m2 = lambda mask: count(mask)*cell_area
            baseline_volume = count(eligible)*cell_area*baseline_mm/1000
            change_volume = count(impacted)*cell_area*(clogged_mm-baseline_mm)/1000
            status_counts = {status: sum(r['status'] == status for r in candidates) for status in ['existing','planned','open']}
            selected_counts = {status: sum(r['status'] == status and r['source_id'] in selected for r in candidates) for status in status_counts}
            public_routes = [{k:v for k,v in r.items() if not k.startswith('_')} | {'selected': r['source_id'] in selected, 'contributes_blockage': r['source_id'] in selected and r['status']=='existing'} for r in candidates]
            features = [{'type':'Feature', 'geometry':mapping(transform(r['_geometry'], TO_GEO.transform, interleaved=False)), 'properties':p} for r,p in zip(candidates,public_routes)]
            result = {'available': True, 'scenario_id': identity, 'revision': identity, 'method': METHOD,
                      'parameters': params, 'assumptions': ASSUMPTIONS, 'source_revisions': source,
                      'geometry': geometry, 'candidate_routes': public_routes,
                      'selected_route_ids': sorted(selected), 'route_counts': status_counts, 'selected_route_counts': selected_counts,
                      'selected_routes': {'type':'FeatureCollection','features':[f for f in features if f['properties']['selected']]},
                      'candidate_route_geometry': {'type':'FeatureCollection','features':features},
                      'influence_geometry': mapping(transform(influence_geometry, TO_GEO.transform, interleaved=False)) if influence_geometry is not None and not influence_geometry.is_empty else None,
                      'grid': {'crs':'EPSG:7801','transform':list(grid)[:6], 'width':width,'height':height,'resolution_m':5,'cell_area_m2':cell_area,'row_offset':row0,'column_offset':col0},
                      'statistics': {'selection_area_m2':float(metric.area),'rasterized_selection_area_m2':area_m2(area),
                                     'eligible_nongreen_land_area_m2':area_m2(eligible), 'green_excluded_area_m2':area_m2(area & green & valid & ~water & ~policy_excluded),
                                     'mapped_green_area_in_selection_m2':area_m2(green),
                                     'green_within_selected_influence_area_m2':area_m2(green & influence),
                                     'screening_policy_excluded_area_m2':area_m2(area & policy_excluded),
                                     'river_channel_excluded_area_m2':area_m2(area & ((policy_flags & 1)>0)),
                                     'stadium_excluded_area_m2':area_m2(area & ((policy_flags & 2)>0)),
                                     'mapped_water_excluded_area_m2':area_m2(area & water & ~policy_excluded), 'uncertain_or_missing_terrain_area_m2':area_m2(area & ~valid & ~water & ~policy_excluded),
                                     'exclusion_partition':'River/stadium policy first (river and stadium subcounts may overlap), then other mapped water, then uncertain/missing terrain, then mapped green; policy total plus other exclusions and eligible land partition the rasterized selection.',
                                     'affected_eligible_area_m2':area_m2(impacted), 'higher_ponding_affected_area_m2':area_m2(impacted & (terrain[3]>=70)),
                                     'eligible_cell_count':count(eligible),'affected_cell_count':count(impacted),
                                     'effective_rainfall_mm':effective,'baseline_excess_runoff_mm':baseline_mm,
                                     'clogged_excess_runoff_in_influence_mm':clogged_mm,
                                     'additional_excess_runoff_in_influence_mm':clogged_mm-baseline_mm,
                                     'baseline_potential_unremoved_volume_m3':baseline_volume,
                                     'clogged_potential_unremoved_volume_m3':baseline_volume+change_volume,
                                     'additional_potential_unremoved_volume_m3':change_volume},
                      'formula': {'effective_rainfall_mm':'rainfall_mm * runoff_coefficient',
                                  'baseline_excess_mm':'max(0, effective_rainfall_mm - drainage_capacity_mm_h * duration_minutes / 60)',
                                  'clogged_excess_mm':'max(0, effective_rainfall_mm - drainage_capacity_mm_h * duration_minutes / 60 * (1 - blockage_percent / 100)) inside selected existing-route influence; baseline elsewhere',
                                  'additional_volume_m3':'sum((clogged_excess_mm - baseline_excess_mm) * eligible cell area_m2 / 1000)'},
                      'legend': {'unit':'mm potential locally unremoved runoff','minimum_mm':0,'maximum_mm':effective,
                                 'zero_transparent':True,'same_scale_for_all_modes':True},
                      'depth_legend':depth_legend,'depth_statistics':depth_statistics,
                      'river_context':river_summary,
                      'bands': ['baseline_excess_runoff_mm','clogged_excess_runoff_mm','additional_excess_runoff_mm',
                                'estimated_baseline_local_ponding_depth_m','estimated_clogged_local_ponding_depth_m','estimated_additional_local_ponding_depth_m'],
                      'raster_nodata':NODATA,
                      'screening_exclusions':self.pluvial.exclusions.meta(),
                      'interpretation':'Hypothetical drainage loss and estimated local depression storage on eligible non-green land, excluding mapped river channels and stadiums by user policy. Values are not predicted flood depths, probabilities or measured pipe clogging.',
                      'tiles_url':{mode:f'/api/clogging/scenarios/{identity}/tiles/{mode}/{{z}}/{{x}}/{{y}}.png' for mode in MODES},
                      'download_url':f'/api/clogging/scenarios/{identity}/download'}
            with tempfile.TemporaryDirectory(prefix='scenario-',dir=self.directory) as scratch:
                scratch_path = Path(scratch)
                raster_path = scratch_path/'runoff.tif'
                with rasterio.open(raster_path,'w',driver='GTiff',width=width,height=height,count=6,dtype='float32',
                                   crs='EPSG:7801',transform=grid,nodata=NODATA,tiled=True,compress='DEFLATE',predictor=3) as dst:
                    dst.write(np.stack([baseline,clogged,change,depth_baseline,depth_clogged,depth_change]))
                    for band,name in enumerate(result['bands'],1): dst.set_band_description(band,name)
                    dst.update_tags(method=METHOD,scenario_id=identity,green_assumption='All mapped green absorbs rainfall; excluded',value_unit='Bands1-3:mm potential locally unremoved runoff; bands4-6:m estimated local depression-storage depth',interpretation=result['interpretation'])
                result['raster_sha256'] = hashlib.sha256(raster_path.read_bytes()).hexdigest()
                river_path = scratch_path/'river_classes.tif'
                with rasterio.open(river_path,'w',driver='GTiff',width=width,height=height,count=1,dtype='uint8',
                                   crs='EPSG:7801',transform=grid,nodata=255,tiled=True,compress='DEFLATE') as dst:
                    dst.write(river_classes,1)
                    dst.set_band_description(1,'mapped_river_proximity_context_class')
                    dst.update_tags(interpretation='Distance context only; river adjacency does not establish flood causation',threshold_m=params['river_proximity_m'])
                result['river_mask_sha256'] = hashlib.sha256(river_path.read_bytes()).hexdigest()
                # A source change during calculation invalidates rather than mixing snapshots.
                if source != self.source_state():
                    raise ScenarioStale('Sources changed during scenario calculation; retry against the new snapshot')
                (scratch_path/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
                with self.cloud_state.lock if self.cloud_state is not None else nullcontext():
                    scratch_path.rename(target)
            if self.cloud_state is not None:
                self.cloud_state.persist_scenario(target,identity)
            return result

    def path(self, identity):
        if not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise KeyError('Unknown scenario ID')
        return self.directory/identity

    def cache_lease(self, identity, reserve_bytes=0):
        if self.cloud_state is None:
            return nullcontext()
        return self.cloud_state.scenario_lease(self.path(identity),reserve_bytes)

    @staticmethod
    @lru_cache(maxsize=16)
    def validate_raster(signature, expected):
        if hashlib.sha256(Path(signature[0]).read_bytes()).hexdigest() != expected:
            raise ScenarioStale('Cached scenario raster differs from its immutable result receipt')
        with rasterio.open(signature[0]) as src:
            if src.count != 6 or src.crs.to_epsg() != 7801 or src.nodata != NODATA or src.dtypes != ('float32',)*6:
                raise ScenarioStale('Cached scenario raster header is invalid')

    @staticmethod
    @lru_cache(maxsize=16)
    def validate_river_mask(signature, expected, transform_values, dimensions):
        if hashlib.sha256(Path(signature[0]).read_bytes()).hexdigest() != expected:
            raise ScenarioStale('Cached river-context mask differs from its immutable result receipt')
        with rasterio.open(signature[0]) as src:
            if (src.count != 1 or src.crs.to_epsg() != 7801 or src.nodata != 255 or src.dtypes != ('uint8',)
                or tuple(src.transform)[:6] != transform_values or (src.width,src.height) != dimensions):
                raise ScenarioStale('Cached river-context mask is not aligned with the scenario raster')

    def result(self, identity):
        with self.cache_lease(identity):
            return self._result(identity)

    def _result(self, identity):
        directory = self.path(identity)
        if self.cloud_state is not None and not (directory/'result.json').is_file():
            self.cloud_state.restore_scenario(directory,identity)
        if not (directory/'result.json').is_file():
            raise KeyError('Scenario not found; calculate it first')
        result = read_json_cached(directory/'result.json')
        if result['source_revisions'] != self.source_state():
            raise ScenarioStale('Source snapshot changed; calculate a new scenario')
        self.validate_raster(file_signature(directory/'runoff.tif'),result['raster_sha256'])
        self.validate_river_mask(file_signature(directory/'river_classes.tif'),result['river_mask_sha256'],
                                 tuple(result['grid']['transform']),(result['grid']['width'],result['grid']['height']))
        return result

    def tile(self, identity, mode, z, x, y, renderer='', river_filter='all'):
        with self.cache_lease(identity):
            return self._tile(identity,mode,z,x,y,renderer,river_filter)

    def _tile(self, identity, mode, z, x, y, renderer='', river_filter='all'):
        if mode not in MODES: raise ValueError('Unknown scenario display mode')
        aliases = {'river_adjacent_possible_mixed':'river_adjacent','away_from_mapped_river':'away'}
        river_filter = aliases.get(river_filter,river_filter)
        if river_filter not in ['all','river_adjacent','away']:
            raise ValueError('Unknown mapped-river display filter')
        tile_bounds(z,x,y)
        result = self.result(identity)
        if river_filter != 'all' and not result['river_context'].get('available'):
            raise RuntimeError('Mapped-river context is unavailable; a proximity filter cannot be applied')
        source = self.path(identity)/'runoff.tif'
        river_source = self.path(identity)/'river_classes.tif'
        key = ['clogging-local-storage-v2',identity,mode,river_filter,z,x,y,renderer,file_signature(source),file_signature(river_source),file_signature(__file__)]
        def render():
            west,south,east,north = tile_bounds(z,x,y)
            spacing = (east-west)/256
            dest = np.full((256,256),NODATA,dtype='float32')
            with RASTER_SLOTS, rasterio.Env(PROJ_NETWORK='OFF',GDAL_CACHEMAX=64000000), rasterio.open(source) as src:
                reproject(rasterio.band(src,MODES[mode]),dest,src_transform=src.transform,src_crs=src.crs,src_nodata=NODATA,
                          dst_transform=Affine(spacing,0,west,0,-spacing,north),dst_crs='EPSG:3857',dst_nodata=NODATA,
                          resampling=Resampling.nearest,num_threads=1,warp_mem_limit=64)
                if river_filter != 'all':
                    river = np.full((256,256),255,dtype='uint8')
                    with rasterio.open(river_source) as mask:
                        reproject(rasterio.band(mask,1),river,src_transform=mask.transform,src_crs=mask.crs,src_nodata=255,
                                  dst_transform=Affine(spacing,0,west,0,-spacing,north),dst_crs='EPSG:3857',dst_nodata=255,
                                  resampling=Resampling.nearest,num_threads=1,warp_mem_limit=64)
                    dest[river != (1 if river_filter == 'river_adjacent' else 2)] = NODATA
            scale = result['depth_legend']['maximum_m'] if mode.startswith('depth_') else result['legend']['maximum_mm']
            colours=scenario_rgba(dest,scale)
            colours[self.pluvial.exclusions.tile_mask(z,x,y),3]=0
            return png(colours)
        return self.tiles.get_or_render(key,render)
