#!/usr/bin/env python3
"""Rebuild native rainfall COGs from the complete Earth Engine numeric snapshots."""
import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
import rasterio
from rasterio.shutil import copy as raster_copy
from affine import Affine
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['merged_250m', 'radar_bias_corrected_250m', 'radar_raw_1km']

def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    geod = Geod(ellps='WGS84')
    for name in NAMES:
        source = ROOT / 'data/rainfall/native_arrays' / (name + '.json')
        record = json.loads(source.read_text())
        band = record['metadata']['bands'][0]
        width, height = band['dimensions']
        data = np.asarray(record['values'], dtype='float32')
        valid = np.asarray(record['mask']) > 0
        assert data.shape == valid.shape == (height, width)
        assert np.isfinite(data[valid]).all() and (data[valid] >= 0).all()
        assert record['pixel_x_first'] == record['pixel_y_first'] == 0.5
        assert record['pixel_x_last'] == width - 0.5
        assert record['pixel_y_last'] == height - 0.5
        transform = Affine(*band['crs_transform'])
        assert band['crs'] == 'EPSG:4326' and transform.b == transform.d == 0
        assert transform.a > 0 and transform.e < 0
        data = data.copy()
        data[~valid] = -9999
        target = out / (name + '.tif')
        with tempfile.TemporaryDirectory() as temp:
            tif = Path(temp) / 'numeric.tif'
            with rasterio.open(tif, 'w', driver='GTiff', width=width, height=height,
                               count=1, dtype='float32', crs=band['crs'],
                               transform=transform, nodata=-9999) as dst:
                dst.write(data, 1)
                dst.set_band_description(1, 'rain_mm')
                dst.update_tags(source_asset=record['source_asset'], units='mm',
                                period='2025-06-27 local day (Europe/Sofia)',
                                provenance='Complete native asset pixels, no resampling')
            raster_copy(tif, target, driver='COG', compress='DEFLATE', blocksize=256)
        with rasterio.open(target) as check:
            assert check.transform == transform and check.crs.to_string() == band['crs']
            assert np.array_equal(check.read(1), data)
            assert np.array_equal(check.read_masks(1) > 0, valid)
        # Geographic cells have latitude-dependent ellipsoidal areas.
        areas = np.empty((height, width), dtype='float64')
        for row in range(height):
            west, north = transform * (0, row)
            east, south = transform * (1, row + 1)
            a, _ = geod.polygon_area_perimeter([west,east,east,west], [north,north,south,south])
            areas[row, :] = abs(a)
        covered_area = float(areas[valid].sum())
        volume = float((data[valid].astype('float64') / 1000 * areas[valid]).sum())
        result[name] = {
            'file': str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
            'asset_id': record['source_asset'], 'crs': band['crs'],
            'transform': list(band['crs_transform']), 'width': width, 'height': height,
            'valid_pixels': int(valid.sum()), 'masked_pixels': int((~valid).sum()),
            'min_mm': float(data[valid].min()), 'max_mm': float(data[valid].max()),
            'mean_mm_unweighted': float(data[valid].astype('float64').mean()),
            'mean_mm_area_weighted': volume * 1000 / covered_area,
            'valid_area_km2': covered_area / 1e6,
            'precipitation_volume_m3': volume,
            'volume_scope': 'valid native cells only; rainfall volume, not runoff or floodwater',
            'area_method': 'WGS84 ellipsoidal polygon area per geographic cell; pyproj.Geod',
        }
    stations = json.loads((ROOT / 'data/rainfall/wu_stations.geojson').read_text())['features']
    result['stations'] = {
        'total': len(stations), 'used': sum(f['properties'].get('qc') == 'ok' for f in stations),
        'rejected': sum(f['properties'].get('qc') != 'ok' for f in stations),
    }
    result['period'] = {'local_date':'2025-06-27','timezone':'Europe/Sofia',
                        'utc_start_inclusive':'2025-06-26T21:00:00Z',
                        'utc_end_exclusive':'2025-06-27T21:00:00Z',
                        'aggregation_window_verified_from_upstream_code':False}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'data/rainfall')
    prepare(parser.parse_args().out_dir.resolve())
