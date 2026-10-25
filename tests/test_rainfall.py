"""Native-source and display-only rainfall regression tests with real snapshots."""
import hashlib
import io
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pyproj import Transformer
from rasterio.transform import Affine

from backend.rainfall import LocalRainfall, PRODUCTS, PALETTE, colour_rainfall, ellipsoidal_statistics
from backend.rainfall_routes import create_rainfall_router

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/rainfall'
MERCATOR = Transformer.from_crs(4326, 3857, always_xy=True)
HALF = 20037508.342789244


def hashed(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tile_at(lon, lat, zoom=14):
    x, y = MERCATOR.transform(lon, lat)
    return zoom, int((x + HALF) / (2 * HALF) * 2 ** zoom), int((HALF - y) / (2 * HALF) * 2 ** zoom)


def png_array(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'))


@pytest.fixture(scope='module', autouse=True)
def originals_unchanged():
    files = [p for p in SOURCE.rglob('*') if p.is_file()]
    assert files, 'The real supplied rainfall snapshot must be installed before testing'
    before = {str(p): hashed(p) for p in files}
    yield
    assert before == {str(p): hashed(p) for p in files}


@pytest.fixture
def rain(tmp_path):
    return LocalRainfall(SOURCE, tmp_path / 'cache')


@pytest.fixture
def client(rain):
    app = FastAPI()
    app.include_router(create_rainfall_router(rain))
    with TestClient(app) as client:
        yield client


def test_metadata_native_grids_scales_and_event_semantics(rain):
    meta = rain.meta()
    assert meta['available']
    assert meta['period']['local_date'] == '2025-06-27'
    assert meta['period']['timezone'] == 'Europe/Sofia'
    assert meta['period']['start_utc'] == '2025-06-26T21:00:00Z'
    assert meta['period']['end_utc'] == '2025-06-27T21:00:00Z'
    assert meta['units'] == 'mm'
    assert set(meta['products']) == set(PRODUCTS)
    for name, product in meta['products'].items():
        assert product['grid']['crs'] == 'EPSG:4326'
        assert product['grid']['tiff_band_description'] == 'rain_mm'
        assert product['palette'] == PALETTE
        assert product['range_mm'] == [0, 110 if name == 'radar_raw_1km' else 30]
        assert product['default_threshold_mm'] == (.5 if name == 'merged_250m' else None)
    # A caller's UI additions cannot change a shared cached source document.
    meta['products']['merged_250m']['range_mm'][1] = 999
    assert rain.meta()['products']['merged_250m']['range_mm'] == [0, 30]


@pytest.mark.parametrize('name', PRODUCTS)
def test_every_original_native_cell_and_mask_matches_snapshot(rain, name):
    snapshot = json.loads((SOURCE / 'native_arrays' / (name + '.json')).read_text())
    values, valid, affine = rain._load()['arrays'][name]
    expected = np.asarray(snapshot['values'], np.float32)
    expected_valid = np.asarray(snapshot['mask']) > 0
    assert np.array_equal(valid, expected_valid)
    assert np.array_equal(values, np.where(expected_valid, expected, np.float32(-9999)))
    assert list(affine)[:6] == snapshot['metadata']['bands'][0]['crs_transform']
    assert valid.sum() == (5041 if name == 'radar_raw_1km' else 7384)
    assert (~valid).sum() == (1721 if name == 'radar_raw_1km' else 0)
    assert not values.flags.writeable and not valid.flags.writeable


@pytest.mark.parametrize('name', PRODUCTS)
def test_fifteen_independent_earth_engine_point_checks(rain, name):
    checks = json.loads((SOURCE / 'native_point_checks.json').read_text())[name]
    _, _, affine = rain._load()['arrays'][name]
    for point in checks:
        lon, lat = affine @ (point['column'] + .5, point['row'] + .5)
        sampled = rain.sample(lon, lat)['products'][name]
        assert sampled['row'] == point['row'] and sampled['column'] == point['column']
        assert sampled['rain_mm'] == point['value']
        assert sampled['status'] == ('nodata' if point['value'] is None else 'ok')


@pytest.mark.parametrize('name', PRODUCTS)
def test_native_whole_product_geodesic_statistics(rain, name):
    supplied = json.loads((SOURCE / 'summary.json').read_text())[name]
    result = rain.statistics(name)
    assert result['valid_cell_count'] == supplied['valid_pixels']
    assert result['total_cell_count'] == supplied['width'] * supplied['height']
    assert result['masked_cell_count'] == supplied['masked_pixels']
    assert result['min_mm'] == supplied['min_mm']
    assert result['max_mm'] == supplied['max_mm']
    assert result['area_weighted_mean_mm'] == pytest.approx(supplied['mean_mm_area_weighted'], rel=1e-12)
    assert result['precipitation_volume_m3'] == pytest.approx(supplied['precipitation_volume_m3'], rel=1e-12)
    assert result['valid_coverage_area_m2'] == pytest.approx(supplied['valid_area_km2'] * 1e6, rel=1e-12)
    assert result['precipitation_volume_m3'] == pytest.approx(result['area_weighted_mean_mm'] / 1000 * result['valid_coverage_area_m2'])
    assert 'whole product' in result['scope'] and not result['display_threshold_affects_statistics']


def test_each_product_samples_its_own_grid_and_mask(rain):
    result = rain.sample(23.32, 42.7)
    native_indices = []
    for name in PRODUCTS:
        point = result['products'][name]
        with rasterio.open(SOURCE / (name + '.tif')) as src:
            row, column = src.index(23.32, 42.7)
            assert (point['row'], point['column']) == (row, column)
            assert point['rain_mm'] == float(src.read(1)[row, column])
            native_indices.append((row, column))
    assert native_indices[0] == native_indices[1] != native_indices[2]
    assert rain.sample(0, 0)['products']['merged_250m']['reason'] == 'outside_coverage'


def test_all_station_records_properties_and_real_valid_zero_preserved(rain):
    original = json.loads((SOURCE / 'wu_stations.geojson').read_text())
    stations = rain.stations()
    assert stations == original
    assert len(stations['features']) == 55
    assert sum(f['properties']['qc'] == 'ok' for f in stations['features']) == 43
    zero = next(f for f in stations['features'] if f['properties']['station_id'] == 'ISOFIA682')
    assert zero['properties'] == {'qc': 'ok', 'rain_mm': 0, 'rows': 589, 'station_id': 'ISOFIA682'}
    rejected = next(f for f in stations['features'] if f['properties']['station_id'] == 'ISOFIA667')
    assert rejected['properties']['rain_mm'] == 441.7 and rejected['properties']['qc'] == 'implausible'


def test_valid_zero_is_not_nodata_in_sample_colour_or_statistics(rain, monkeypatch):
    # Small explicit unit fixture tests zero semantics; no substitute data is
    # shipped or used in the application's real-source adapter.
    values = np.array([[0., 2.], [-9999., 4.]], np.float32)
    valid = np.array([[True, True], [False, True]])
    affine = Affine(.01, 0, 23, 0, -.01, 43)
    monkeypatch.setattr(rain, '_load', lambda: {'arrays': {'merged_250m': (values, valid, affine)}, 'meta': {'revision': 'unit-fixture'}})
    point = rain.sample(23.005, 42.995)['products']['merged_250m']
    assert point['status'] == 'ok' and point['rain_mm'] == 0
    assert colour_rainfall(values, valid, 30)[0, 0, 3] == 255
    assert colour_rainfall(values, valid, 30, .5)[0, 0, 3] == 0
    summary = ellipsoidal_statistics(values, valid, affine)
    assert summary['min_mm'] == 0 and summary['valid_cell_count'] == 3


def test_display_threshold_does_not_change_native_readouts_or_statistics(rain):
    values, _, affine = rain._load()['arrays']['merged_250m']
    row, column = np.unravel_index(values.argmin(), values.shape)
    lon, lat = affine @ (column + .5, row + .5)
    before = rain.statistics('merged_250m')
    plain = rain.sample(lon, lat)['products']['merged_250m']
    threshold = rain.sample(lon, lat, threshold=.5)['products']['merged_250m']
    assert plain['rain_mm'] == threshold['rain_mm'] > 0
    assert threshold['hidden_by_display_threshold'] and not plain['hidden_by_display_threshold']
    assert rain.statistics('merged_250m') == before
    visible = png_array(rain.tile('merged_250m', *tile_at(lon, lat, 18)))
    hidden = png_array(rain.tile('merged_250m', *tile_at(lon, lat, 18), threshold=.5))
    assert (visible[..., 3] > 0).any() and (hidden[..., 3] == 0).any()
    assert np.array_equal(visible[..., :3], hidden[..., :3])
    assert rain.statistics('merged_250m') == before


def test_palette_is_continuous_and_endpoints_explicitly_clipped():
    values = np.array([[0., 2.5, 5., 30., 100.]], np.float32)
    colours = colour_rainfall(values, np.ones(values.shape, bool), 30)
    assert colours[0, 0, :3].tolist() == [247, 251, 255]
    assert colours[0, 1, :3].tolist() not in [[int(c[i:i+2], 16) for i in (0, 2, 4)] for c in PALETTE]
    assert colours[0, 2, :3].tolist() == [198, 219, 239]
    assert np.array_equal(colours[0, 3], colours[0, 4])
    assert np.all(colours[..., 3] == 255)


@pytest.mark.parametrize('name', PRODUCTS)
def test_real_land_tiles_are_visible_at_high_zoom_and_nearest_values_are_native(rain, name):
    coordinates = tile_at(23.32, 42.7, 18)
    tile = png_array(rain.tile(name, *coordinates))
    values, valid = rain._warped_values(name, *coordinates)
    assert np.all(tile[..., 3] == 255) and valid.all()
    native, mask, _ = rain._load()['arrays'][name]
    assert set(np.unique(values)).issubset(set(native[mask].tolist()))
    expected = colour_rainfall(values, valid, PRODUCTS[name][1])
    assert np.array_equal(tile, expected)
    outside = png_array(rain.tile(name, *tile_at(0, 0, 18)))
    assert np.all(outside[..., 3] == 0)


@pytest.mark.parametrize('name', PRODUCTS)
def test_bilinear_keeps_exact_nearest_valid_coverage_and_holes(rain, name):
    _, source_valid, affine = rain._load()['arrays'][name]
    if name == 'radar_raw_1km':
        rows, columns = np.where(source_valid[:, 1:] != source_valid[:, :-1])
        lon, lat = affine @ (int(columns[len(columns)//2]) + 1, int(rows[len(rows)//2]) + .5)
    else:
        lon, lat = affine @ (0, 25)
    coordinates = tile_at(lon, lat, 12)
    nearest_values, nearest_mask = rain._warped_values(name, *coordinates, 'nearest')
    smooth_values, smooth_mask = rain._warped_values(name, *coordinates, 'bilinear')
    assert nearest_mask.any() and (~nearest_mask).any(), 'Regression must exercise both real coverage and an excluded region'
    assert np.array_equal(nearest_mask, smooth_mask)
    nearest = png_array(rain.tile(name, *coordinates, 'nearest'))
    smooth = png_array(rain.tile(name, *coordinates, 'bilinear'))
    assert np.array_equal(nearest[..., 3], smooth[..., 3])
    assert np.all(smooth[~nearest_mask, 3] == 0)
    assert np.all(smooth[nearest_mask, 3] == 255)


def test_cache_cannot_reuse_old_results_when_source_changes(tmp_path):
    copied = tmp_path / 'sources'
    shutil.copytree(SOURCE, copied)
    rainfall = LocalRainfall(copied, tmp_path / 'cache')
    old_revision = rainfall.meta()['revision']
    coordinates = tile_at(23.32, 42.7)
    rainfall.tile('merged_250m', *coordinates)
    renders = rainfall.tiles.stats['renders']
    rainfall.tile('merged_250m', *coordinates)
    assert rainfall.tiles.stats['renders'] == renders
    metadata = json.loads((copied / 'earth_engine_metadata.json').read_text())
    metadata['test_refresh_note'] = 'A source metadata revision only; numeric snapshots stay unchanged'
    (copied / 'earth_engine_metadata.json').write_text(json.dumps(metadata))
    assert rainfall.meta()['revision'] != old_revision
    rainfall.tile('merged_250m', *coordinates)
    assert rainfall.tiles.stats['renders'] == renders + 1
    # A modified numeric snapshot must fail rather than use a once-valid cache.
    path = copied / 'native_arrays/merged_250m.json'
    snapshot = json.loads(path.read_text())
    snapshot['values'][0][0] += 1
    path.write_text(json.dumps(snapshot))
    assert not rainfall.available and not rainfall.meta()['available']
    with pytest.raises(ValueError):
        rainfall.tile('merged_250m', *coordinates)


def test_router_meta_stations_statistics_gzip_conditional_and_native_download(client, rain):
    metadata = client.get('/api/rainfall/meta', headers={'Accept-Encoding': 'identity'})
    assert metadata.status_code == 200 and metadata.json()['available']
    revision = metadata.json()['revision']
    identity = client.get('/api/rainfall/stations?v=' + revision, headers={'Accept-Encoding': 'identity'})
    compressed = client.get('/api/rainfall/stations?v=' + revision, headers={'Accept-Encoding': 'gzip'})
    assert identity.json() == compressed.json() == rain.stations()
    assert len(compressed.json()['features']) == 55
    assert compressed.headers['content-encoding'] == 'gzip'
    assert identity.headers['etag'] != compressed.headers['etag']
    assert client.get('/api/rainfall/stations?v=' + revision, headers={'Accept-Encoding': 'gzip', 'If-None-Match': compressed.headers['etag']}).status_code == 304
    stats = client.get('/api/rainfall/statistics?product=radar_raw_1km').json()
    assert stats['masked_cell_count'] == 1721 and 'precipitation' in stats['quantity']
    download = client.get('/api/rainfall/download/merged_250m', headers={'Range': 'bytes=0-99'})
    assert download.status_code == 206 and download.content == (SOURCE / 'merged_250m.tif').read_bytes()[:100]
    point = client.get('/api/rainfall/sample?lon=23.32&lat=42.7').json()
    assert set(point['products']) == set(PRODUCTS) and all(p['status'] == 'ok' for p in point['products'].values())
    z, x, y = tile_at(23.32, 42.7, 18)
    tile = client.get(f'/api/rainfall/tiles/merged_250m/{z}/{x}/{y}.png?v={revision}')
    assert tile.status_code == 200 and (png_array(tile.content)[..., 3] > 0).any()
    assert client.get(f'/api/rainfall/tiles/merged_250m/{z}/{x}/{y}.png?v={revision}', headers={'If-None-Match': tile.headers['etag']}).status_code == 304


@pytest.mark.parametrize('url', ['/sample?lon=23.32&lat=42.7&v=old', '/stations?v=old', '/statistics?v=old', '/download/merged_250m?v=old', '/tiles/merged_250m/14/9250/6040.png?v=old'])
def test_stale_revision_rejected(client, url):
    assert client.get('/api/rainfall' + url).status_code == 409


@pytest.mark.parametrize('url', ['/sample?lon=nan&lat=42.7', '/sample?lon=23.3&lat=999', '/statistics?product=fake', '/tiles/merged_250m/23/1/1.png', '/tiles/radar_raw_1km/14/9250/6040.png?threshold=0.5', '/tiles/merged_250m/14/9250/6040.png?smoothing=cubic'])
def test_invalid_inputs_rejected(client, url):
    assert client.get('/api/rainfall' + url).status_code == 422


def test_missing_source_explicitly_unavailable(tmp_path):
    rainfall = LocalRainfall(tmp_path / 'absent', tmp_path / 'cache')
    app = FastAPI()
    app.include_router(create_rainfall_router(rainfall))
    with TestClient(app) as client:
        assert client.get('/api/rainfall/meta').json()['available'] is False
        assert client.get('/api/rainfall/statistics').status_code == 503
