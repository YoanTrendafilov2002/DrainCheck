"""Source-backed river context remains separate from reported flood mechanisms."""
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import Affine
import shapely
from shapely.geometry import Point

from backend.river_context import RiverContext, TO_METRIC, river_features

ROOT = Path(__file__).resolve().parents[1]


def document(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def test_real_sources_include_only_actual_rivers_and_reaches_and_preserve_inputs():
    river = RiverContext(ROOT)
    water, official = document(river.water_path), document(river.context_path)
    before_water, before_official = copy.deepcopy(water), copy.deepcopy(official)
    selected, counts = river_features(water, official)
    assert counts == {'open_water_source_polygons': 537, 'osm_river_polygons': 18,
                      'nonriver_water_polygons_excluded': 519, 'official_context_source_features': 23,
                      'official_river_reaches': 19, 'schematic_or_nonreach_features_excluded': 4,
                      'included_river_geometries': 37}
    assert all(f['geometry']['type'] != 'Point' for f, _ in selected)
    assert all(f['properties']['tags']['water'] == 'river' for f, r in selected if r['source_kind'] == 'osm_river_polygon')
    assert all(f['properties']['geometry_role'] == 'assessment_reach' for f, r in selected if r['source_kind'] == 'official_assessment_reach')
    assert before_water == water and before_official == official
    meta = river.meta()
    assert meta['available'] and meta['source_counts'] == counts
    assert meta['source_hashes']['open_water_polygons'] == hashlib.sha256(river.water_path.read_bytes()).hexdigest()
    assert meta['source_hashes']['official_context'] == hashlib.sha256(river.context_path.read_bytes()).hexdigest()


def test_exact_real_distances_and_adjustable_threshold_do_not_infer_causation():
    river = RiverContext(ROOT)
    # Actual mapped river polygon point has exact zero distance, as a polygon
    # footprint rather than an invented centreline or widened buffer.
    inside = river.sample(23.359073637791244, 42.66766873740193, 0, 'pluvial')
    assert inside['nearest_distance_m'] == 0
    assert inside['nearest_source']['source_id'] == 'way/743562181'
    assert inside['category'] == 'river_adjacent_possible_mixed'
    assert inside['reported_mechanism'] == 'pluvial' and inside['causation'] == 'not_determined'
    # Ariana is a real lake; its interior must not be counted as river distance0.
    lon, lat = 23.337247642167377, 42.690042699335194
    result = river.sample(lon, lat)
    assert 30 < result['nearest_distance_m'] < 40
    geometries = river._sources()[0]
    point = Point(*TO_METRIC.transform(lon, lat))
    expected = min(point.distance(g) for g in geometries)
    assert math.isclose(result['nearest_distance_m'], expected, abs_tol=1e-8)
    assert river.sample(lon, lat, expected-1)['category'] == 'away_from_mapped_river'
    assert river.sample(lon, lat, expected+1)['category'] == 'river_adjacent_possible_mixed'
    assert 'does not determine flood cause' in result['interpretation']


def test_actual_historical_polygon_keeps_its_reported_mechanism_and_uses_minimum_distance():
    river = RiverContext(ROOT)
    historical = document(ROOT/'data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson')['features'][0]
    feature = copy.deepcopy(historical)
    feature['properties']['mechanism'] = 'unknown'
    before = copy.deepcopy(feature)
    result = river.classify_geometry(feature)
    assert result['available'] and result['reported_mechanism'] == 'unknown'
    assert result['causation'] == 'not_determined'
    metric = shapely.transform(shapely.geometry.shape(feature['geometry']), TO_METRIC.transform, interleaved=False)
    expected = min(metric.distance(g) for g in river._sources()[0])
    assert math.isclose(result['nearest_distance_m'], expected, abs_tol=1e-8)
    assert 'large polygon may contain both' in result['distance_basis']
    assert feature == before


def test_grid_exact_centre_distances_partition_actual_river_neighbourhood():
    river = RiverContext(ROOT)
    x, y = TO_METRIC.transform(23.359073637791244, 42.66766873740193)
    # Real aligned 5 m neighbourhood and explicit eligibility subset. No terrain
    # values are invented; this tests only source-geometry distance calculation.
    west = 299392+math.floor((x-299392)/5)*5-150
    north = 4753611-math.floor((4753611-y)/5)*5+150
    grid = Affine(5, 0, west, 0, -5, north)
    eligible = np.ones((60, 60), dtype=bool)
    eligible[:5, :7] = False
    result = river.classify_grid(grid, eligible, threshold_m=50)
    distance, near, summary = result['distance_m'], result['near_river'], result['summary']
    assert np.all(np.isnan(distance[~eligible])) and not np.any(near[~eligible])
    assert np.isfinite(distance[eligible]).all() and near.any() and np.any(eligible & ~near)
    assert summary['unknown_area_m2'] == 0
    assert sum(summary['class_area_m2'].values()) == np.count_nonzero(eligible)*25
    geometries = river._sources()[0]
    for row, col in [(6, 6), (15, 15), (30, 30), (45, 45), (59, 59)]:
        cx, cy = grid @ (col+.5, row+.5)
        expected = min(Point(cx, cy).distance(g) for g in geometries)
        assert math.isclose(float(distance[row, col]), expected, rel_tol=1e-6, abs_tol=1e-5)
        assert near[row, col] == (expected <= 50)


def test_zero_sources_and_missing_or_changed_sources_are_unknown_not_away(tmp_path):
    river = RiverContext(tmp_path)
    empty = {'type': 'FeatureCollection', 'features': []}
    for path in [river.water_path, river.context_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(empty), encoding='utf-8')
    river.water_meta.parent.mkdir(parents=True, exist_ok=True)
    river.water_meta.write_text(json.dumps({'source': {'geojson_sha256': hashlib.sha256(river.water_path.read_bytes()).hexdigest()}}), encoding='utf-8')
    river.assessment_meta.write_text(json.dumps({'context_sha256': hashlib.sha256(river.context_path.read_bytes()).hexdigest()}), encoding='utf-8')
    assert not river.meta()['available']
    assert river.sample(23.3, 42.7, reported_mechanism='river')['category'] == 'unknown'
    assert river.sample(23.3, 42.7, reported_mechanism='river')['reported_mechanism'] == 'river'
    eligible = np.array([[True, False], [True, True]])
    result = river.classify_grid(Affine(5, 0, 320000, 0, -5, 4734000), eligible)
    assert np.isnan(result['distance_m']).all() and not result['near_river'].any()
    assert result['summary']['unknown_area_m2'] == 75
    assert result['summary']['away_from_mapped_river_area_m2'] == 0
    # A modified source without an updated authentic receipt also remains unknown.
    river.context_path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [], 'changed': True}), encoding='utf-8')
    assert 'checksum differs' in river.meta()['message']
    assert river.sample(23.3, 42.7)['category'] == 'unknown'
    river.context_path.unlink()
    assert river.sample(23.3, 42.7)['category'] == 'unknown'


def test_finite_distance_parameters_and_grid_limits():
    river = RiverContext(ROOT)
    for value in [-1, float('inf'), float('nan'), 5001, True]:
        with pytest.raises(ValueError, match='threshold'):
            river.sample(23.3, 42.7, value)
    with pytest.raises(ValueError, match='longitude'):
        river.sample(float('nan'), 42.7)
    with pytest.raises(ValueError, match='grid'):
        river.classify_grid(Affine(5, 0, 320000, 0, -5, 4734000), np.ones((1001, 1000), bool))
