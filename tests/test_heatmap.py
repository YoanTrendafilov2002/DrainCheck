"""Display-only heatmap checks against the unchanged, real 5 m ponding raster."""
import hashlib
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from pyproj import Transformer
from rasterio.windows import Window

from backend import app as api
from backend.pluvial import LocalPluvial, NODATA, heatmap_rgba
from backend.terrain import tile_bounds

ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(api.app)
XY = Transformer.from_crs(4326, 3857, always_xy=True)
ISLAND = (23.336833150705026, 42.68967465294718)
STADIUM = (23.3352531692, 42.6875642953)
POSITIVE_P = (23.33370350350254, 42.6866436907843)
LAKE = (23.337247642167377, 42.690042699335194)
RIVER = (23.359073637791244, 42.66766873740193)
UNCERTAIN = (23.261843334262714, 42.87771146033699)


def tile_at(lon, lat, zoom=18):
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    west, south, east, north = tile_bounds(zoom, x, y)
    mx, my = XY.transform(lon, lat)
    column = int((mx - west) / (east - west) * 256)
    row = int((north - my) / (north - south) * 256)
    response = CLIENT.get(f'/api/pluvial/heatmap/{zoom}/{x}/{y}.png',
                          params={'v': api.pluvial.meta()['revision']})
    assert response.status_code == 200, response.text
    image = np.asarray(Image.open(BytesIO(response.content)).convert('RGBA'))
    assert image.shape == (256, 256, 4)
    return image, row, column, response


def test_continuous_colours_preserve_numeric_domain_and_missing_states():
    values = np.array([[NODATA, np.nan, np.inf, -1, 101, 0, 12.5, 100]], dtype=np.float32)
    rgba = heatmap_rgba(values)
    assert rgba.dtype == np.uint8 and rgba.shape == (1, 8, 4)
    assert not np.any(rgba[0, :5, 3])
    # Zero is a valid, deliberately transparent signal, distinct from NoData.
    np.testing.assert_array_equal(rgba[0, 5], [255, 246, 180, 0])
    np.testing.assert_array_equal(rgba[0, 6], [255, 236, 152, 12])
    np.testing.assert_array_equal(rgba[0, 7], [130, 24, 144, 245])
    ramp = heatmap_rgba(np.linspace(0, 100, 401))
    assert len(np.unique(ramp, axis=0)) > 250, 'Heatmap must not collapse back to four classes'
    assert np.all(np.diff(ramp[:, 3].astype(int)) >= 0)


def test_real_land_pixels_use_native_ponding_not_combined_or_interpolated_scores():
    with rasterio.open(api.pluvial.path, OVERVIEW_LEVEL='NONE') as source:
        for location in (ISLAND, STADIUM, POSITIVE_P):
            sample = api.pluvial.sample(*location)
            assert sample['status'] == 'ok' and not sample['water_excluded']
            native = source.read([6, 8], window=Window(sample['column'], sample['row'], 1, 1))[:, 0, 0]
            assert sample['ponding_score'] == float(native[0])
            image, row, column, _ = tile_at(*location)
            np.testing.assert_array_equal(image[row, column], heatmap_rgba(np.array([native[0]]))[0])
            if location in (ISLAND, STADIUM):
                assert native[0] == 0 and native[1] > 70
                assert image[row, column, 3] == 0, 'Combined-score hotspots must not leak into P heatmap'
            else:
                assert native[0] > 90 and image[row, column, 3] > 0


def test_mapped_water_outside_coverage_and_uncertainty_keep_their_exclusions():
    for location in (LAKE, RIVER):
        sample = api.pluvial.sample(*location)
        assert sample['status'] == 'excluded_open_water' and sample['ponding_score'] is None
        image, row, column, _ = tile_at(*location)
        assert image[row, column, 3] == 0
    outside, _, _, _ = tile_at(22.4, 42.7)
    assert not np.any(outside[:, :, 3])
    sample = api.pluvial.sample(*UNCERTAIN)
    assert sample['status'] == 'uncertain' and sample['ponding_score'] is None
    assert sample['factors']['mean_ground_elevation_m'] is not None
    image, row, column, _ = tile_at(*UNCERTAIN)
    np.testing.assert_array_equal(image[row, column], [120, 127, 136, 155])


def test_heatmap_public_cache_contract_and_invalid_requests():
    image, _, _, response = tile_at(*POSITIVE_P)
    assert 'immutable' in response.headers['cache-control']
    assert response.headers['content-type'] == 'image/png'
    url = str(response.request.url)
    again = CLIENT.get(url)
    assert again.content == response.content
    cached = CLIENT.get(url, headers={'If-None-Match': response.headers['etag']})
    assert cached.status_code == 304 and not cached.content
    revision = api.pluvial.meta()['revision']
    assert CLIENT.get('/api/pluvial/heatmap/12/2313/1509.png?v=stale').status_code == 409
    assert CLIENT.get('/api/pluvial/heatmap/12/-1/0.png', params={'v': revision}).status_code == 422
    assert CLIENT.get('/api/pluvial/fabricated/12/2313/1509.png', params={'v': revision}).status_code == 422
    assert image[:, :, 3].max() > 0


def test_missing_water_mask_cannot_reuse_a_cached_or_unmasked_heatmap(tmp_path, monkeypatch):
    missing = LocalPluvial(tmp_path)
    missing.path = api.pluvial.path
    missing.receipt = api.pluvial.receipt
    assert missing.source_available and not missing.available
    before = dict(missing.tiles.stats)
    with pytest.raises(ValueError, match='unavailable'):
        missing.tile('heatmap', 18, 148068, 96634, 'old')
    assert missing.tiles.stats == before
    monkeypatch.setattr(api, 'pluvial', missing)
    assert CLIENT.get('/api/pluvial/heatmap/12/2313/1509.png?v=old').status_code == 503


def test_rendering_is_read_only_and_retains_native_values_and_source_revision():
    paths = [api.pluvial.path, api.pluvial.receipt, api.pluvial.water.path,
             api.pluvial.water.receipt, ROOT.parent / 'sofia_dtm_2024_1m_gee.tif']
    assert all(path.is_file() for path in paths)
    signatures = {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}
    receipt_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in (api.pluvial.receipt, api.pluvial.water.receipt)}
    before = api.pluvial.meta()
    native_before = api.pluvial.sample(*POSITIVE_P)
    tile_at(*POSITIVE_P)
    tile_at(*STADIUM)
    assert signatures == {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths}
    assert receipt_hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (api.pluvial.receipt, api.pluvial.water.receipt)}
    assert api.pluvial.meta()['revision'] == before['revision']
    assert api.pluvial.meta()['terrain_revision'] == before['terrain_revision']
    assert api.pluvial.sample(*POSITIVE_P) == native_before
