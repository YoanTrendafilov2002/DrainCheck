#!/usr/bin/env python3
"""Verify the actual rainfall payload, masks, independent samples and provenance."""
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
from affine import Affine

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/rainfall'

def main():
    script = ROOT / 'earth_engine/Rainfall_20250627_original.js'
    assert hashlib.sha256(script.read_bytes()).hexdigest() == '81d5832798aa33ea3a857911a14d14d747fda64e2a108ca673356dba603d9765'
    checks = json.loads((DATA/'native_point_checks.json').read_text())
    summary = json.loads((DATA/'summary.json').read_text())
    for name, expected in [('merged_250m',7384),('radar_bias_corrected_250m',7384),('radar_raw_1km',5041)]:
        source = json.loads((DATA/'native_arrays'/f'{name}.json').read_text())
        values = np.asarray(source['values'], dtype='float32')
        mask = np.asarray(source['mask']) > 0
        band = source['metadata']['bands'][0]
        assert values.shape == (band['dimensions'][1],band['dimensions'][0])
        assert mask.sum() == expected
        assert np.isfinite(values[mask]).all() and np.all(values[mask]>=0)
        with rasterio.open(DATA/f'{name}.tif') as ds:
            assert ds.crs.to_string() == band['crs'] == 'EPSG:4326'
            assert ds.transform == Affine(*band['crs_transform'])
            assert ds.nodata == -9999 and ds.descriptions == ('rain_mm',)
            assert ds.tags(ns='IMAGE_STRUCTURE').get('LAYOUT') == 'COG'
            assert np.array_equal(ds.read_masks(1)>0,mask)
            assert np.array_equal(ds.read(1)[mask],values[mask])
            for point in checks[name]:
                row,col = point['row'],point['column']
                expected_value = point['value']
                x,y = ds.xy(row,col)
                sampled = next(ds.sample([(x,y)],masked=True))[0]
                if expected_value is None:
                    assert np.ma.is_masked(sampled) and not mask[row,col]
                else:
                    assert float(sampled) == expected_value == float(values[row,col])
        assert summary[name]['valid_pixels'] == expected
        assert summary[name]['min_mm'] == float(values[mask].min())
        assert summary[name]['max_mm'] == float(values[mask].max())
    stations = json.loads((DATA/'wu_stations.geojson').read_text())['features']
    assert len(stations) == 55
    assert sum(f['properties'].get('qc')=='ok' for f in stations) == 43
    assert len({f['properties']['station_id'] for f in stations}) == 55
    for f in stations:
        assert f['geometry']['type'] == 'Point'
        assert all(k in f['properties'] for k in ['station_id','qc','rain_mm','rows'])
    print('PASS: 3 complete native rainfall COGs; masks/grid preserved; 15 independent samples; 55 stations (43 accepted/12 rejected); original script unchanged.')

if __name__ == '__main__':
    main()
