"""Real mapped channels must stay absent from every derived risk surface.

The fixed controls were independently selected from the preserved OSM network
where the previous polygon-only mask was zero and genuine terrain was valid.
They cover urban rivers, northern/eastern rivers, a stream and an open drain.
Native-DTM cross sections add off-line channel-bed and mixed-edge controls:
burning a centreline alone must not leave the real channel colored alongside it.
"""
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from pyproj import Transformer
from shapely import transform
from shapely.geometry import box, mapping

from backend import app as api
from backend.clogging import CloggingScenarios, NODATA, TO_GEO, TO_METRIC
from backend.river_context import RiverContext
from backend.terrain import tile_bounds

ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(api.app)
WEB = Transformer.from_crs(4326, 3857, always_xy=True)
CONTROLS = [
    ('Kakach', 23066184, 23.24881123137895, 42.73861242752225),
    ('Suhodolska', 23083806, 23.239940243791715, 42.70880881656388),
    ('Perlovska', 157682390, 23.367474675545715, 42.72379811029055),
    ('Domuz dere', 157755996, 23.25261816544155, 42.67184816819773),
    ('Iskar', 32823044, 23.390762561447815, 42.7434582347484),
    ('Katinska', 25116214, 23.354575211434277, 42.82267922334908),
    ('Lokorska', 24724984, 23.454546124030347, 42.82737681790222),
    ('Open drain', 89114654, 23.41579825, 42.69390094),
    # Near-horizontal source segment straddling a native row boundary. GDAL's
    # ordinary line burn omitted this intersected cell despite all_touched.
    ('Zhelyavska row crossing', 918002352, 23.6121578, 42.75966885),
]
# Independently inspected way256813270 cross sections: native bed554 m versus
# banks~557 m. These cells were still colored after the centreline-only fix.
PERLOVSKA_FOOTPRINT = [
    ('Perlovska upstream bed', 256813270, 23.314883117397095, 42.67996902985578),
    ('Perlovska middle bed', 256813270, 23.315021695213026, 42.68027208839755),
    ('Perlovska downstream bed', 256813270, 23.315423021307335, 42.68078236765922),
    ('Perlovska southeast mixed edge', 256813270, 23.315349352006923, 42.68055738433926),
    ('Perlovska northwest mixed edge', 256813270, 23.315262438694024, 42.6805901681666),
]
CONTROLS += PERLOVSKA_FOOTPRINT
# Actual transverse dry-bank points,10 m from their respective local line
# segments; both have fill0 and are nongreen, inside the20 m candidate search.
DRY_BANKS = [
    ('Upstream nongreen bank', 23.315069422311808, 42.67992599053382),
    ('Middle nongreen bank', 23.315201818162354, 42.68021653902312),
]
LAND = (23.33370350350254, 42.6866436907843)


def rgba_at(location, mode, zoom):
    lon, lat = location
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    west, south, east, north = tile_bounds(zoom, x, y)
    mx, my = WEB.transform(lon, lat)
    column = int((mx - west) / (east - west) * 256)
    row = int((north - my) / (north - south) * 256)
    base = 'refinement' if mode == 'review' else 'pluvial'
    meta = CLIENT.get(f'/api/{base}/meta').json()
    assert meta['available'], meta
    route = (f'/api/refinement/tiles/{zoom}/{x}/{y}.png' if mode == 'review'
             else f'/api/pluvial/{mode}/{zoom}/{x}/{y}.png')
    response = CLIENT.get(route, params={'v': meta['revision'], 'green_absorption': 0})
    assert response.status_code == 200, response.text
    return np.asarray(Image.open(BytesIO(response.content)).convert('RGBA'))[row, column]


@pytest.mark.parametrize('name,way_id,lon,lat', CONTROLS, ids=[c[0] for c in CONTROLS])
def test_channel_controls_have_no_scores_but_keep_real_ground(name, way_id, lon, lat):
    params = {'lon': lon, 'lat': lat}
    for green in (0, 1):
        terrain = CLIENT.get('/api/pluvial/sample', params={**params, 'green_absorption': green}).json()
        review = CLIENT.get('/api/refinement/sample', params={**params, 'green_absorption': green}).json()
        for result in (terrain, review):
            assert result['status'] == 'excluded_user_screening', (name, way_id, result)
            assert result['screening_excluded'] is True
            assert result['screening_exclusion_reason'] in ('river', 'river_and_stadium')
            if (name, way_id, lon, lat) in PERLOVSKA_FOOTPRINT:
                assert result['screening_exclusion_method'] == 'terrain_connected'
                assert result['screening_exclusion_flags'] & 4, 'Inferred footprint must remain distinct from mapped geometry'
        assert all(terrain[key] is None for key in ('score', 'ponding_score', 'concentration_score', 'class'))
        assert review['review_class'] is review['legacy_ponding_score'] is None
        assert terrain['factors']['mean_ground_elevation_m'] is not None
    native = CLIENT.get('/api/elevation', params=params)
    assert native.status_code == 200
    assert native.json() == api.terrain.sample(lon, lat)


@pytest.mark.parametrize('zoom', [12, 14, 16, 18])
@pytest.mark.parametrize('mode', ['heatmap', 'ponding', 'combined', 'concentration', 'review'])
def test_channel_footprints_are_clear_across_risk_views_and_map_scales(zoom, mode):
    for name, way_id, lon, lat in CONTROLS:
        assert rgba_at((lon, lat), mode, zoom)[3] == 0, (name, way_id, mode, zoom)


def test_preserved_open_network_is_covered_beyond_a_few_handpicked_controls():
    pointer = ROOT / 'data/reference/screening_exclusions_waterways_acquisition.json'
    receipt = json.loads(pointer.read_text(encoding='utf-8'))
    source = pointer.parent / receipt['raw_file']
    raw_bytes = source.read_bytes()
    assert hashlib.sha256(raw_bytes).hexdigest() == receipt['raw_sha256']
    raw = json.loads(raw_bytes)
    assert not raw.get('remark'), 'Incomplete Overpass response must not be used'
    candidates = []
    for way in raw['elements']:
        tags = way.get('tags', {})
        if way['type'] != 'way' or tags.get('waterway') not in ('river', 'stream', 'canal', 'drain', 'ditch'):
            continue
        # A negative layer alone does not imply burial: incised open streams are
        # frequently below adjoining roads. Explicit covered/underground tags do.
        if (tags.get('tunnel', 'no') not in ('no', 'false', '0', '')
                or tags.get('covered', 'no') not in ('no', 'false', '0', '')
                or tags.get('indoor', 'no') not in ('no', 'false', '0', '')
                or tags.get('location') in ('underground', 'indoor')
                or any(tags.get(key, 'no') not in ('no', 'false', '0', '') for key in
                       ('disused', 'abandoned', 'demolished', 'removed', 'razed', 'construction', 'proposed'))):
            continue
        geometry = way.get('geometry', [])
        # Vertices and segment midpoints independently audit actual source
        # geometry, including bends, rather than trusting generated controls.
        for a, b in zip(geometry[:-1], geometry[1:]):
            for lon, lat in ((a['lon'], a['lat']),
                             ((a['lon'] + b['lon']) / 2, (a['lat'] + b['lat']) / 2)):
                candidates.append((way['id'], *TO_METRIC.transform(lon, lat)))
        if geometry:
            point = geometry[-1]
            candidates.append((way['id'], *TO_METRIC.transform(point['lon'], point['lat'])))
    assert len(candidates) > 10_000
    coordinates = [(x, y) for _, x, y in candidates]
    with rasterio.open(api.pluvial.path, OVERVIEW_LEVEL='NONE') as terrain:
        z = np.array(list(terrain.sample(coordinates, indexes=1)))[:, 0]
        valid = np.isfinite(z) & (z != terrain.nodata)
    with rasterio.open(api.pluvial.exclusions.path, OVERVIEW_LEVEL='NONE') as mask:
        flags = np.array(list(mask.sample(coordinates, indexes=1)))[:, 0]
    valid_ways = {way for (way, _, _), good in zip(candidates, valid) if good}
    assert len(valid_ways) > 1_000, 'Coverage audit must span the municipality'
    missing = [candidates[index] for index in np.flatnonzero(valid & ((flags & 1) == 0))]
    assert not missing, f'{len(missing)} real open-channel source points remain unmasked: {missing[:10]}'


def test_new_channel_cells_are_nodata_in_all_six_storm_bands_and_land_is_preserved(tmp_path):
    service = CloggingScenarios(ROOT, api.pluvial, RiverContext(ROOT))
    service.directory = tmp_path
    # Kakach was absent from the polygon-only mask. Nearby eligible terrain
    # must remain calculated, rather than blanking the whole selection.
    _, _, lon, lat = CONTROLS[0]
    x, y = TO_METRIC.transform(lon, lat)
    selection = mapping(transform(box(x - 250, y - 250, x + 250, y + 250),
                                  TO_GEO.transform, interleaved=False))
    result = service.create(selection, rainfall_mm=100, blockage_percent=100)
    assert result['statistics']['screening_policy_excluded_area_m2'] > 0
    with rasterio.open(service.path(result['scenario_id']) / 'runoff.tif') as output:
        assert output.count == 6
        assert np.all(next(output.sample([(x, y)])) == NODATA)
        assert np.any(output.read(1) != NODATA)
    sample = CLIENT.get('/api/pluvial/sample', params=dict(zip(('lon', 'lat'), LAND))).json()
    assert sample['status'] == 'ok'
    with rasterio.open(api.pluvial.path, OVERVIEW_LEVEL='NONE') as original:
        values = original.read([6, 7, 8], window=rasterio.windows.Window(sample['column'], sample['row'], 1, 1))[:, 0, 0]
    assert [sample['ponding_score'], sample['concentration_score'], sample['score']] == values.tolist()
    assert rgba_at(LAND, 'heatmap', 18)[3] > 0
    assert result['source_revisions']['screening_exclusions_revision'] == api.pluvial.exclusions.meta()['revision']


def test_prior_polygon_and_centreline_only_risk_tiles_cannot_be_reused():
    meta = CLIENT.get('/api/pluvial/meta').json()
    assert meta['revision'] not in ('0a7a8ca315510679', '85dd677d28609485')
    assert meta['screening_exclusions']['revision'] not in ('bfdf087d674d5c81', '95c920ca693324c7')
    for stale in ('0a7a8ca315510679', '85dd677d28609485'):
        assert CLIENT.get('/api/pluvial/heatmap/14/9253/6038.png', params={'v': stale}).status_code == 409
    for stale in ('973703f7b5f64d0b', '32df6ae7bc681769'):
        assert CLIENT.get('/api/refinement/tiles/14/9253/6038.png', params={'v': stale}).status_code == 409


def test_a_buried_river_segment_does_not_blank_the_surface_above_it():
    # OSM Katinska way25116220 is explicitly tunnel=yes. Its midpoint is
    # genuine eligible surface terrain, outside separate water/stadium masks.
    location = (23.36355712426426, 42.82173405117443)
    pointer = ROOT / 'data/reference/screening_exclusions_waterways_acquisition.json'
    receipt = json.loads(pointer.read_text(encoding='utf-8'))
    source = json.loads((pointer.parent / receipt['raw_file']).read_text(encoding='utf-8'))
    way = next(item for item in source['elements'] if item['type'] == 'way' and item['id'] == 25116220)
    assert way['tags']['tunnel'] == 'yes'
    result = CLIENT.get('/api/pluvial/sample', params=dict(zip(('lon', 'lat'), location))).json()
    assert result['status'] == 'ok' and not result.get('screening_excluded', False)
    with rasterio.open(api.pluvial.path, OVERVIEW_LEVEL='NONE') as original:
        values = original.read([6, 7, 8], window=rasterio.windows.Window(result['column'], result['row'], 1, 1))[:, 0, 0]
    assert [result['ponding_score'], result['concentration_score'], result['score']] == values.tolist()
    assert rgba_at(location, 'combined', 18)[3] > 0


@pytest.mark.parametrize('name,lon,lat', DRY_BANKS, ids=[c[0] for c in DRY_BANKS])
def test_actual_nongreen_dry_banks_inside_search_corridor_keep_land_values(name, lon, lat):
    for green in (0, 1):
        sample = CLIENT.get('/api/pluvial/sample', params={'lon': lon, 'lat': lat, 'green_absorption': green}).json()
        assert sample['status'] == 'ok', (name, sample)
        assert not sample.get('screening_excluded', False)
        assert sample['factors']['depression_fill_depth_m'] == 0
        with rasterio.open(api.pluvial.path, OVERVIEW_LEVEL='NONE') as source:
            original = source.read([6, 7, 8], window=rasterio.windows.Window(sample['column'], sample['row'], 1, 1))[:, 0, 0]
        assert [sample['ponding_score'], sample['concentration_score'], sample['score']] == original.tolist()
    assert rgba_at((lon, lat), 'combined', 18)[3] > 0
    assert CLIENT.get('/api/refinement/sample', params={'lon': lon, 'lat': lat}).json()['status'] == 'ok'


def test_storm_excludes_off_line_channel_beds_but_keeps_nearby_dry_nongreen_banks(tmp_path):
    service = CloggingScenarios(ROOT, api.pluvial, RiverContext(ROOT))
    service.directory = tmp_path
    x, y = TO_METRIC.transform(23.3153, 42.680576)
    selection = mapping(transform(box(x - 200, y - 200, x + 200, y + 200),
                                  TO_GEO.transform, interleaved=False))
    result = service.create(selection, rainfall_mm=100, blockage_percent=100)
    newly_excluded_nongreen_beds = 0
    with rasterio.open(service.path(result['scenario_id']) / 'runoff.tif') as output:
        for name, way_id, lon, lat in PERLOVSKA_FOOTPRINT:
            assert np.all(next(output.sample([TO_METRIC.transform(lon, lat)])) == NODATA), name
            sample = api.pluvial.sample(lon, lat)
            row, col = sample['row'], sample['column']
            assert sample['screening_excluded'] is True
            if not api.green_absorption.sample_cell(row, col) and not api.pluvial.water.sample_cell(row, col):
                newly_excluded_nongreen_beds += 1
        for name, lon, lat in DRY_BANKS:
            values = next(output.sample([TO_METRIC.transform(lon, lat)]))
            assert np.all(values != NODATA), (name, values)
            assert np.all(np.isfinite(values)) and np.all(values >= 0)
            assert np.all(values[3:] == 0), 'Zero-fill bank must not acquire ponding depth'
    assert newly_excluded_nongreen_beds > 0, 'Scenario must exercise a channel cell not already excluded by green/water masks'
