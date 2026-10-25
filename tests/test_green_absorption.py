"""Real complete-green scenario, reversible exclusions and integrity checks."""
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
import shapely
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.green_absorption import GreenAbsorption, BAND, GRID, SHAPE
from backend.terrain import tile_bounds


def cell(lon, lat):
    x, y = Transformer.from_crs(4326, 7801, always_xy=True).transform(lon, lat)
    c, r = (~GRID) @ (x, y)
    return int(r), int(c)


def tile_pixel(lon, lat, z=18):
    x = int((lon+180)/360*2**z)
    y = int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    west, south, east, north = tile_bounds(z, x, y)
    mx, my = Transformer.from_crs(4326, 3857, always_xy=True).transform(lon, lat)
    return z, x, y, int((north-my)/(north-south)*256), int((mx-west)/(east-west)*256)


def test_full_real_green_mask_grid_counts_and_original_provenance():
    mask = GreenAbsorption(ROOT)
    meta = mask.meta()
    assert meta['available'] and meta['enabled_by_default']
    assert meta['source_counts']['nonempty_green_polygons'] == 64956
    assert meta['source_counts']['distinct_candidates_in_grid'] == 64956
    assert meta['source_counts']['route_intersecting_display_subset'] == 2175
    assert meta['counts']['green_cells'] == 4756433
    assert meta['area_km2'] == 118.910825
    assert meta['verification']['all_sources_unchanged']
    assert meta['source_revision'] == 'af34c6d53d5b26fd'
    with rasterio.open(mask.path) as src:
        assert src.shape == SHAPE and src.transform == GRID and src.crs.to_epsg() == 7801
        assert src.nodata is None and src.dtypes == ('uint8',) and src.descriptions == (BAND,)
        counts = np.zeros(2, dtype=np.int64)
        for _, window in src.block_windows(1):
            a = src.read(1, window=window)
            assert np.all((a == 0) | (a == 1))
            counts += np.bincount(a.ravel(), minlength=2)
    assert counts.tolist() == [107683372, 4756433]


def test_real_polygon_hole_stays_non_green_and_nearby_green_stays_excluded():
    mask = GreenAbsorption(ROOT)
    # Actual source polygon fid 65394 contains this empty hole. It is not filled
    # by another mapped polygon, so the binary union must preserve the opening.
    hole = (23.23852165762764, 42.6722862215039)
    assert cell(*hole) == (4963, 3052)
    assert not mask.sample_cell(*cell(*hole))
    with sqlite3.connect('file:'+str(ROOT/'data/cache/spatial.sqlite')+'?mode=ro', uri=True) as db:
        geometry = shapely.from_wkb(db.execute('SELECT geometry FROM features WHERE fid=65394').fetchone()[0])
        assert not geometry.covers(Point(*hole))
        interior = geometry.representative_point()
        assert mask.sample_cell(*cell(interior.x, interior.y))
    # This is a real green area at the current map camera, independent of the
    # route-intersecting display filter or whether green rendering is enabled.
    assert mask.sample_cell(*cell(23.267111, 42.684845))


def test_independent_exact_cell_centre_union_cross_check():
    mask = GreenAbsorption(ROOT)
    xy = Transformer.from_crs(7801, 4326, always_xy=True)
    rng = np.random.default_rng(9365)
    seen = set()
    with sqlite3.connect('file:'+str(ROOT/'data/cache/spatial.sqlite')+'?mode=ro', uri=True) as db:
        # Random actual cells in the central urban extent, not modelled/fabricated
        # terrain. Check source geometry at each exact 5 m centre independently.
        for row, col in zip(rng.integers(4100, 5200, 80), rng.integers(3000, 5200, 80)):
            lon, lat = xy.transform(*(GRID @ (int(col)+.5, int(row)+.5)))
            candidates = db.execute("SELECT f.geometry FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=? AND f.kind='green'", (lon, lon, lat, lat)).fetchall()
            expected = any(shapely.from_wkb(record[0]).covers(Point(lon, lat)) for record in candidates)
            actual = mask.sample_cell(int(row), int(col))
            assert actual == expected
            seen.add(actual)
    assert seen == {False, True}


def test_nearest_mask_tiles_keep_valid_zero_and_polygon_holes():
    mask = GreenAbsorption(ROOT)
    z, x, y, row, col = tile_pixel(23.23852165762764, 42.6722862215039)
    a = mask.tile_mask(z, x, y)
    assert a.shape == (256, 256) and a.dtype == bool and not a.flags.writeable
    assert not a[row, col]
    assert np.any(a) and np.any(~a), 'Do not expand absorbing green into valid zero holes'
    z, x, y, row, col = tile_pixel(23.267111, 42.684845)
    assert mask.tile_mask(z, x, y)[row, col]
    z, x, y, _, _ = tile_pixel(22.4, 42.7)
    assert not np.any(mask.tile_mask(z, x, y)), 'Outside the analysis rectangle is not absorbing green'
    assert not mask.sample_cell(-1, 0) and not mask.sample_cell(SHAPE[0], 0)


def test_missing_green_derivative_fails_closed(tmp_path):
    mask = GreenAbsorption(tmp_path)
    assert not mask.meta()['available']
    with pytest.raises(ValueError, match='unavailable'):
        mask.tile_mask(14, 9254, 6039)
    with pytest.raises(ValueError, match='unavailable'):
        mask.sample_cell(0, 0)


def test_stale_green_source_signature_is_rejected(tmp_path):
    mask = GreenAbsorption(ROOT)
    meta = json.loads(mask.receipt.read_text(encoding='utf-8'))
    meta['source_files']['spatial_index']['size_bytes'] += 1
    receipt = tmp_path/'changed_source.json'
    receipt.write_text(json.dumps(meta), encoding='utf-8')
    mask.receipt = receipt
    assert not mask.available and 'source signature changed' in mask.error
    with pytest.raises(ValueError, match='source signature changed'):
        mask.sample_cell(4697, 3528)


def test_modified_green_mask_without_updated_receipt_is_rejected(tmp_path):
    mask = GreenAbsorption(ROOT)
    target = tmp_path/'modified_green_absorption.tif'
    shutil.copyfile(mask.path, target)
    with target.open('r+b') as stream:
        stream.seek(-1, 2)
        byte = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([byte[0] ^ 1]))
    mask.path = target
    assert not mask.available and 'checksum differs' in mask.error


def test_refreshed_metadata_timestamp_is_accepted_only_when_source_bytes_match(tmp_path):
    mask = GreenAbsorption(ROOT)
    meta = json.loads(mask.receipt.read_text(encoding='utf-8'))
    # Copy only a small actual metadata source under the app root, so no native
    # input, live revision pointer or source raster is modified by this test.
    with tempfile.TemporaryDirectory(prefix='green-source-integrity-', dir=ROOT/'data/cache') as directory:
        copied = Path(directory)/'spatial_revision_inputs.json'
        original = ROOT/meta['source_files']['spatial_revision']['file']
        shutil.copyfile(original, copied)
        record = meta['source_files']['spatial_revision']
        record['file'] = copied.relative_to(ROOT).as_posix()
        record['mtime_ns'] = copied.stat().st_mtime_ns-1_000_000_000
        os.utime(copied, ns=(copied.stat().st_atime_ns, record['mtime_ns']+2_000_000_000))
        receipt = tmp_path/'refreshed_metadata_receipt.json'
        receipt.write_text(json.dumps(meta), encoding='utf-8')
        mask.receipt = receipt
        assert mask.available, mask.error
        # Cached verification is keyed by the actual file signature. A same-size
        # content edit gets a new signature and must not reuse the successful
        # identical-content result, even though the recorded revision is intact.
        data = copied.read_bytes()
        changed = data.replace(b'fingerprint', b'fingerpriny', 1)
        assert len(changed) == len(data) and changed != data
        copied.write_bytes(changed)
        assert not mask.available and 'checksum differs' in mask.error
