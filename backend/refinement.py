"""Categorical review priority with explicit evidence and drainage limitations."""
import math, sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import Window
from shapely import from_wkb, transform
from shapely.geometry import Point, box, shape
from .terrain import XY, RASTER_SLOTS, tile_bounds, png
from .context_layers import sha256
from .tile_cache import file_signature, read_json_cached
from .screening_exclusions import REASONS

TO_GEO = Transformer.from_crs(7801, 4326, always_xy=True)
TO_METRIC = Transformer.from_crs(4326, 7801, always_xy=True)
LABELS = ('Lower ponding terrain signal', 'Raised ponding terrain signal',
          'Higher ponding terrain signal', 'Higher ponding + potential building footprint',
          'Historical flood footprint', 'Historical footprint + potential building footprint')

def rgba(values, classes):
    palette = np.zeros((256, 4), dtype=np.uint8)
    for item in classes:
        code = int(item.get('code', item.get('value', 255)))
        if 0 <= code <= 5:
            palette[code] = item.get('color_rgba', item.get('color', [128, 135, 140, 160]))
    palette[254] = [128, 135, 140, 155]
    return palette[np.asarray(values, dtype=np.uint8)]

class LocalReviewPriority:
    def __init__(self, root, pluvial, cadastre, history, assessment):
        self.root = Path(root); self.cache = self.root/'data/cache'
        self.path = self.root/'data/derived/review_priority_5m.tif'
        self.receipt = self.cache/'review_priority_meta.json'
        self.pluvial = pluvial; self.cadastre = cadastre; self.history = history; self.assessment = assessment
        self.tiles = pluvial.tiles
        self.green = None

    @staticmethod
    @lru_cache(maxsize=4)
    def validate(signature, expected):
        if sha256(signature[0]) != expected:
            raise ValueError('Review raster checksum differs from its receipt')
        with rasterio.open(signature[0]) as src:
            if (src.crs is None or src.crs.to_epsg() != 7801 or src.shape != (10869, 10345) or src.count != 1
                or src.dtypes != ('uint8',) or src.nodata != 255
                or list(src.transform)[:6] != [5, 0, 299392, 0, -5, 4753611]
                or src.descriptions != ('evidence_based_review_priority',)):
                raise ValueError('Review raster is not the verified categorical 5 m grid')

    def meta(self):
        try:
            data = read_json_cached(self.receipt)
            self.validate(file_signature(self.path), data['output_sha256'])
            sources = data['source_revisions']
            current = {'pluvial': self.pluvial.meta().get('revision'),
                       'water': self.pluvial.water.meta().get('revision'),
                       'screening_exclusions': self.pluvial.exclusions.meta().get('revision'),
                       'cadastre': self.cadastre.meta().get('revision'),
                       'history': self.history.meta().get('revision')}
            if any(sources.get(key) != value or value is None for key, value in current.items()):
                raise ValueError('Review source revisions changed; rebuild the separate derivative')
            classes = []
            for item in data['classes']:
                code = item.get('code', item.get('value'))
                if code not in range(6):
                    continue
                color = list(item['color_rgba'])
                color[3] = (45, 100, 155, 195, 170, 215)[code]
                classes.append({**item, 'value': code, 'color': color, 'color_rgba': color})
            details = data.get('formula')
            formula = '; '.join(details.get('ordered_rules', [])) if isinstance(details, dict) else details
            return {**data, 'available': True, 'classes': classes,
                    'formula': formula, 'formula_details': details,
                    'logic_links': self.logic_links(), 'clogging_analysis': {
                        'available': False, 'status': 'Not assessed',
                        'reason': 'Historical reports describe restricted conveyance in some events, but no current, asset-located blockage inspections, pipe connectivity, diameters, inverts or maintenance history are supplied. Proximity flags identify field-review candidates, not measured clogging.'}}
        except (OSError, ValueError, KeyError, TypeError, rasterio.errors.RasterioError) as error:
            return {'available': False, 'title': 'Evidence-based review priority', 'message': str(error)}

    @staticmethod
    def logic_links():
        return [
            {'data': '5 m terrain', 'use': 'Ponding signal at existing P=50/70 display cutoffs; C remains an experimental diagnostic.'},
            {'data': 'Mapped river channels and stadiums', 'use': 'User-requested exclusion from screening and scenario outputs; not evidence that these places cannot flood.'},
            {'data': 'Mapped historical flooding', 'use': 'Prior-observation review category at cell centres, regardless of overlay visibility; unknown flood mechanism remains unknown.'},
            {'data': 'Cadastral buildings', 'use': 'Potential 5 m cell–footprint intersection; exposure context, no measured vulnerability or whole-cell imperviousness.'},
            {'data': 'Rainfall', 'use': 'Time-compatible scenario context by user assumption; native daily totals and coverage retained. No storm intensity or drainage load is invented.'},
            {'data': 'Sewer routes and points', 'use': 'Actual mapped proximity/exposure only. Planned routes do not imply functioning drainage. No capacity, flow or clogging calculation.'},
            {'data': 'All mapped green areas', 'use': 'All 64,956 nonempty polygons partition routes. Display choice is independent; polygons do not measure permeability.'},
            {'data': 'Official assessment geometry', 'use': 'Independent supplier-level overlay and full-precision containment; not an invented pixel flood probability.'},
        ]

    def sample(self, lon, lat, green_absorption=False):
        meta = self.meta()
        if not meta.get('available'):
            raise ValueError(meta['message'])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError('Finite coordinates required')
        x, y = XY.transform(lon, lat)
        with rasterio.open(self.path) as src:
            row, col = src.index(x, y)
            code = int(src.read(1, window=Window(col, row, 1, 1))[0, 0]) if 0 <= row < src.height and 0 <= col < src.width else 255
            centre = src.xy(row, col)
        status = 'excluded_user_screening' if code == 252 else 'excluded_open_water' if code == 253 else 'uncertain' if code == 254 else 'nodata' if code == 255 else 'ok'
        legacy = self.pluvial.sample(lon, lat)
        if legacy['status']=='excluded_user_screening':status='excluded_user_screening'
        if status == 'ok' and (code not in range(6) or legacy['status'] != 'ok'):
            raise ValueError('Review and original terrain eligibility disagree')
        history_ids = self.history_ids(*TO_GEO.transform(*centre)) if code != 255 else []
        context = self.local_context(lon, lat, centre, legacy.get('ponding_score')) if code != 255 else {'available': False, 'clogging_status': 'not_assessed', 'reason': 'Outside terrain coverage'}
        result = {'longitude': lon, 'latitude': lat, 'status': status, 'revision': meta['revision'],
                'analysis_resolution_m': 5, 'row': row, 'column': col,
                'review_class': code if status == 'ok' else None,
                'review_label': LABELS[code] if status == 'ok' else {'excluded_user_screening': 'Excluded mapped river channel / stadium', 'uncertain': 'Uncertain terrain', 'excluded_open_water': 'Excluded mapped open water', 'nodata': 'Outside terrain'}[status],
                'legacy_ponding_score': legacy.get('ponding_score'),
                'history_intersection': bool(history_ids) if code != 255 else None,
                'historical_polygon_ids': history_ids, 'history_location_basis': '5 m analysis cell centre',
                'potential_building_intersection': context.get('potential_building_intersection'),
                'drainage_context': context, 'official_assessment': self.assessment.intersections(lon, lat),
                'source_dates': meta.get('source_dates'), 'scenario_assumption': meta.get('scenario_assumption'),
                'interpretation': 'Rule-based review category. Class numbers are identifiers, not probabilities, flood depths or damage scores.'}
        if status=='excluded_user_screening':
            result.update(screening_excluded=True,screening_exclusion_reason=legacy.get('screening_exclusion_reason'),
                          exclusion_reason=legacy.get('exclusion_reason'),legacy_ponding_score=None,
                          original_terrain=legacy.get('unmasked_scores'),
                          interpretation='Mapped river channel or stadium is omitted at the user’s request; historical observations remain separately available and exclusion is not a safety finding.')
        if green_absorption:
            if self.green is None or not self.green.available:
                raise ValueError('Full-green absorption mask unavailable')
            if status not in ('excluded_user_screening','excluded_open_water','nodata') and self.green.sample_cell(row,col):
                result.update(original_terrain={'review_class':result['review_class'],'review_label':result['review_label'],'ponding_score':result['legacy_ponding_score']},
                              status='excluded_green_absorption',review_class=None,review_label='Assumed absorbing green area',
                              legacy_ponding_score=None,green_absorption_assumption=True,
                              interpretation='Mapped green area is excluded under the user-defined full absorption assumption; observed historical evidence remains available independently.')
        return result

    def history_ids(self, lon, lat):
        meta = self.history.meta()
        if not meta.get('available'):
            return []
        doc = read_json_cached(self.history.data_path(meta)); point = Point(lon, lat)
        return [f['properties']['source_id'] for f in doc['features'] if shape(f['geometry']).covers(point)]

    def local_context(self, lon, lat, centre, ponding_score=None):
        spatial = self.cache/'spatial.sqlite'
        if not spatial.is_file():
            return {'available': False, 'clogging_status': 'not_assessed', 'reason': 'Original vector index unavailable'}
        x, y = XY.transform(lon, lat); point = Point(x, y); radius = 100
        region = point.buffer(radius)
        w, s, e, n = TO_GEO.transform_bounds(x-radius, y-radius, x+radius, y+radius, densify_pts=8)
        predicate = 'b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?'
        counts = {status: 0 for status in ['existing', 'planned', 'open']}
        lengths = {status: 0.0 for status in counts}; points = {'sewerage': 0, 'collectors': 0}
        green = False
        with closing(sqlite3.connect('file:'+spatial.as_posix()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT f.kind,f.zone,f.status,f.geometry FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE '+predicate+" AND ((f.kind='routes' AND f.zone='all') OR (f.kind='points' AND f.status IN ('2','3')) OR f.kind='green')", (e,w,n,s))
            for item in rows:
                geom = from_wkb(item['geometry'])
                if item['kind'] == 'green':
                    green = green or geom.covers(Point(lon, lat)); continue
                metric = transform(geom, TO_METRIC.transform, interleaved=False)
                if not metric.intersects(region):
                    continue
                if item['kind'] == 'routes':
                    status = item['status']
                    if status in counts:
                        counts[status] += 1; lengths[status] += metric.intersection(region).length
                else:
                    points['sewerage' if item['status'] == '2' else 'collectors'] += 1
        footprint_ids = None
        if self.cadastre.meta().get('available'):
            cx, cy = centre; cell = box(cx-2.5, cy-2.5, cx+2.5, cy+2.5)
            cw, cs, ce, cn = TO_GEO.transform_bounds(*cell.bounds, densify_pts=8)
            footprint_ids = []
            with closing(sqlite3.connect('file:'+self.cadastre.database.as_posix()+'?mode=ro', uri=True)) as db:
                for identity, blob in db.execute('SELECT f.source_id,f.geometry FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE '+predicate, (ce,cw,cn,cs)):
                    if transform(from_wkb(blob), TO_METRIC.transform, interleaved=False).intersects(cell):
                        footprint_ids.append(identity)
        return {'available': True, 'search_radius_m': radius, 'route_counts': counts,
                'route_length_m_in_radius': lengths, 'point_counts': points,
                'mapped_green_cover_at_point': bool(green),
                'potential_building_intersection': bool(footprint_ids) if footprint_ids is not None else None,
                'cadastral_source_ids_in_cell': footprint_ids,
                'clogging_status': 'not_assessed',
                'review_flags': ['Higher ponding signal near an existing mapped sewer route: inspect drainage and inlet condition on site'] if counts['existing'] and ponding_score is not None and ponding_score >= 70 else [],
                'summary': f"Within 100 m: {counts['existing']} existing, {counts['planned']} planned and {counts['open']} open-channel source routes; {points['sewerage']} sewerage and {points['collectors']} collector points. Capacity and clogging are not assessed.",
                'interpretation': 'Counts and lengths are source geometry within 100 m, not connected pipe capacity or blockage. Planned routes remain separate. Green cover is a mapped polygon, not infiltration.'}

    def tile(self, z, x, y, renderer, green_absorption=False):
        meta = self.meta()
        if not meta.get('available'):
            raise ValueError(meta['message'])
        tile_bounds(z, x, y)
        if green_absorption and (self.green is None or not self.green.available):
            raise ValueError('Full-green absorption mask unavailable')
        key = ['review-categorical-v2-policy-exclusions', meta['revision'], renderer, z,x,y, file_signature(self.path), file_signature(self.receipt), file_signature(__file__),file_signature(self.pluvial.exclusions.path),file_signature(self.pluvial.exclusions.receipt)]
        key.extend([green_absorption,*( [file_signature(self.green.path),file_signature(self.green.receipt)] if green_absorption else [])])
        def render():
            west, south, east, north = tile_bounds(z,x,y); spacing = (east-west)/256
            dest = np.full((256,256), 255, dtype=np.uint8)
            with RASTER_SLOTS, rasterio.Env(PROJ_NETWORK='OFF', GDAL_CACHEMAX=64000000), rasterio.open(self.path) as src:
                reproject(rasterio.band(src,1), dest, src_transform=src.transform, src_crs=src.crs,
                          src_nodata=255, dst_transform=Affine(spacing,0,west,0,-spacing,north),
                          dst_crs='EPSG:3857', dst_nodata=255, resampling=Resampling.nearest, num_threads=1, warp_mem_limit=64)
            colours=rgba(dest, meta['classes'])
            colours[self.pluvial.exclusions.tile_mask(z,x,y),3]=0
            if green_absorption:colours[self.green.tile_mask(z,x,y),3]=0
            return png(colours)
        return self.tiles.get_or_render(key, render)

