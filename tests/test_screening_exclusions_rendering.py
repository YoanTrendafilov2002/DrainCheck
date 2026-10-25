"""Native mapped-channel cells remain excluded at overview and inspection scales."""
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject, transform as transform_coordinates
from rasterio.windows import Window, bounds as window_bounds
from scipy.ndimage import binary_dilation
from shapely.geometry import Polygon, box

from backend.screening_exclusions import ScreeningExclusions, GRID
from backend.terrain import tile_bounds

ROOT = Path(__file__).resolve().parents[1]
PERLOVSKA = (23.335932930341258, 42.6895156)
LAND = (23.33370350350254, 42.6866436907843)
MIXED_EDGE = (23.315349352006923, 42.68055738433926)
DRY_BANKS = [(23.315069422311808, 42.67992599053382),
             (23.315201818162354, 42.68021653902312)]
TO_METRIC = Transformer.from_crs(4326, 7801, always_xy=True)
TO_WEB = Transformer.from_crs(4326, 3857, always_xy=True)


def tile_at(location, zoom):
    lon, lat = location
    scale = 2**zoom
    return (int((lon+180)/360*scale),
            int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*scale))


def native_channel_centres_in_tile(service, zoom, x, y):
    """Independently bin native channel-cell centres; no raster warp is used."""
    metric_x, metric_y = TO_METRIC.transform(*PERLOVSKA)
    col, row = int((metric_x-GRID.c)//5), int((GRID.f-metric_y)//5)
    window = Window(col-60, row-60, 120, 120)
    with rasterio.open(service.path, OVERVIEW_LEVEL='NONE') as source:
        values = source.read(1, window=window)
        native_rows, native_cols = np.where(values & 1)
        assert native_rows.size > 0, 'The actual mapped Perlovska channel is required'
        xs = GRID.c+(native_cols+window.col_off+.5)*5
        ys = GRID.f-(native_rows+window.row_off+.5)*5
        web_x, web_y = transform_coordinates(source.crs, 3857, xs.tolist(), ys.tolist())
    west, south, east, north = tile_bounds(zoom, x, y)
    spacing = (east-west)/256
    cols = np.floor((np.asarray(web_x)-west)/spacing).astype(int)
    rows = np.floor((north-np.asarray(web_y))/spacing).astype(int)
    inside = (cols >= 0) & (cols < 256) & (rows >= 0) & (rows < 256)
    expected = np.zeros((256, 256), dtype=bool)
    expected[rows[inside], cols[inside]] = True
    assert expected.any()
    return expected


def nearest_native_tile(service, zoom, x, y):
    west, south, east, north = tile_bounds(zoom, x, y)
    spacing = (east-west)/256
    destination = np.full((256, 256), 255, dtype='uint8')
    with rasterio.open(service.path, OVERVIEW_LEVEL='NONE') as source:
        reproject(rasterio.band(source, 1), destination,
                  src_transform=source.transform, src_crs=source.crs, src_nodata=None,
                  dst_transform=Affine(spacing, 0, west, 0, -spacing, north),
                  dst_crs='EPSG:3857', dst_nodata=255, resampling=Resampling.nearest)
    return (destination > 0) & (destination != 255)


@pytest.mark.parametrize('zoom', [10, 12, 14, 16, 18])
def test_actual_native_channel_cells_are_not_lost_between_overview_samples(zoom):
    service = ScreeningExclusions(ROOT/'data/cache')
    x, y = tile_at(PERLOVSKA, zoom)
    expected = native_channel_centres_in_tile(service, zoom, x, y)
    actual = service.tile_mask(zoom, x, y)
    assert actual.dtype == np.dtype(bool)
    assert actual[expected].all(), 'A native river cell must not reappear as risk when zooming out'
    if zoom == 10:
        nearest = nearest_native_tile(service, zoom, x, y)
        assert np.any(expected & ~nearest), 'This real source segment must exercise the former nearest-sampling loss'


@pytest.mark.parametrize('zoom', [16, 18])
def test_inspection_zoom_clips_only_boundary_pixels_and_keeps_nearby_land(zoom):
    service = ScreeningExclusions(ROOT/'data/cache')
    x, y = tile_at(PERLOVSKA, zoom)
    actual = service.tile_mask(zoom, x, y)
    nearest = nearest_native_tile(service, zoom, x, y)
    assert actual[nearest].all()
    boundary_pixels = actual & ~nearest
    assert boundary_pixels.any(), 'Real source boundaries must exercise partial-pixel clipping'
    assert not np.any(boundary_pixels & ~binary_dilation(nearest, structure=np.ones((3, 3), dtype=bool)))
    x, y = tile_at(LAND, zoom)
    west, south, east, north = tile_bounds(zoom, x, y)
    web_x, web_y = TO_WEB.transform(*LAND)
    col = int((web_x-west)/(east-west)*256)
    row = int((north-web_y)/(north-south)*256)
    assert not service.tile_mask(zoom, x, y)[row, col], 'Nearby eligible land remains visible at inspection zoom'


def test_real_mixed_channel_edge_is_clipped_when_web_pixel_centre_falls_on_dry_land():
    service = ScreeningExclusions(ROOT/'data/cache')
    zoom = 16
    x, y = tile_at(MIXED_EDGE, zoom)
    west, south, east, north = tile_bounds(zoom, x, y)
    spacing = (east-west)/256
    web_x, web_y = TO_WEB.transform(*MIXED_EDGE)
    col, row = int((web_x-west)/spacing), int((north-web_y)/spacing)
    assert not nearest_native_tile(service, zoom, x, y)[row, col], 'Control must exercise the former dry-centre leak'
    with rasterio.open(service.path, OVERVIEW_LEVEL='NONE') as source:
        native_row, native_col = source.index(*TO_METRIC.transform(*MIXED_EDGE))
        cell = Window(native_col, native_row, 1, 1)
        assert int(source.read(1, window=cell)[0, 0]) & 4
        native_footprint = box(*window_bounds(cell, source.transform))
    pixel_corners = [(west+col*spacing, north-row*spacing),
                     (west+(col+1)*spacing, north-row*spacing),
                     (west+(col+1)*spacing, north-(row+1)*spacing),
                     (west+col*spacing, north-(row+1)*spacing)]
    metric = Transformer.from_crs(3857, 7801, always_xy=True)
    footprint = Polygon([metric.transform(*point) for point in pixel_corners])
    assert footprint.intersection(native_footprint).area > 0, 'Actual screen pixel overlaps the excluded native cell'
    assert service.tile_mask(zoom, x, y)[row, col]


@pytest.mark.parametrize('zoom', [16, 18])
@pytest.mark.parametrize('location', DRY_BANKS)
def test_verified_dry_banks_remain_visible_after_conservative_edge_clipping(zoom, location):
    service = ScreeningExclusions(ROOT/'data/cache')
    x, y = tile_at(location, zoom)
    west, south, east, north = tile_bounds(zoom, x, y)
    web_x, web_y = TO_WEB.transform(*location)
    col = int((web_x-west)/(east-west)*256)
    row = int((north-web_y)/(north-south)*256)
    assert not service.tile_mask(zoom, x, y)[row, col]
