"""Analytical rule tests use labelled tiny arrays, never substituted map data."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
import rasterio
from backend.pluvial import (BAND_NAMES, NODATA, LocalPluvial, class_indices,
                            colour_rgba, percentile_definition, rank, score_arrays)


def references():
    # Explicit artificial mathematical references, not observations of Sofia.
    return {'depth_positive': {'values': [1, 3], 'ranks': [0, 1]},
            'area': {'values': [25, 100], 'ranks': [0, 1]},
            'slope': {'values': [0, 20], 'ranks': [0, 1]}}


def test_equal_reference_values_have_no_fabricated_variation():
    definition = percentile_definition(np.ones(500))
    assert definition['values'] == [1]
    assert definition['ranks'] == pytest.approx([0.5])
    assert rank(np.array([1, 1]), definition) == pytest.approx([0.5, 0.5])


def test_scalar_and_missing_ranks_are_defined():
    definition = {'values': [0, 20], 'ranks': [0, 1]}
    assert float(rank(10, definition)) == pytest.approx(0.5)
    assert np.isnan(rank(np.nan, definition))


def test_pathways_and_maximum_have_explicit_arithmetic():
    depression, concentration, combined, valid = score_arrays(
        np.array([0, 2, 3]), np.array([0, 10, 20]), np.array([25, 62.5, 100]),
        np.zeros(3), references())
    np.testing.assert_allclose(depression, [0, 50, 100])
    np.testing.assert_allclose(concentration, [0, 50, 0])
    np.testing.assert_allclose(combined, [0, 50, 100])
    assert valid.all()


def test_boundary_and_missing_factors_never_become_low_scores():
    d, c, combined, valid = score_arrays(np.array([2, 2, 2, NODATA]),
        np.array([5, NODATA, 5, 5]), np.array([100, 100, 100, 100]), np.array([1, 0, 0, 0]), references())
    np.testing.assert_array_equal(valid, [False, False, True, False])
    assert combined[0] == combined[1] == combined[3] == NODATA
    assert d[0] == c[0] == NODATA


def test_no_positive_depression_reference_does_not_create_scores():
    refs = references(); refs['depth_positive'] = None
    d, c, score, valid = score_arrays(np.array([0, 1]), np.zeros(2), np.full(2, 25), np.zeros(2), refs)
    assert valid.tolist() == [True, False]
    assert d[0] == 0 and score[1] == NODATA


def test_display_cutoffs_use_documented_upper_class_at_exact_cutoff():
    np.testing.assert_array_equal(class_indices(np.array([0, 49.99, 50, 69.99, 70, 84.99, 85, 100])),
                                  [0, 0, 1, 1, 2, 2, 3, 3])


def test_missing_transparent_and_boundary_explicit():
    rgba = colour_rgba(np.array([[NODATA, np.nan, 0, 90]]))
    assert rgba[0, 0, 3] == rgba[0, 1, 3] == 0
    assert rgba[0, 2, 3] > 0 and rgba[0, 3, 3] > 0
    boundary = colour_rgba(np.array([[0, 1, NODATA]]), 'boundary')
    assert boundary[0, 0, 3] == boundary[0, 2, 3] == 0
    assert boundary[0, 1, 3] > 0


def test_invalid_percentile_definition_rejected():
    with pytest.raises(ValueError):
        rank([2], {'values': [1, 1], 'ranks': [0, 1]})
    with pytest.raises(ValueError):
        rank([2], {'values': [1, 2], 'ranks': [1, 0]})


def test_missing_prepared_data_never_falls_back(tmp_path):
    local = LocalPluvial(tmp_path)
    assert not local.available
    assert local.meta()['available'] is False
    with pytest.raises(ValueError, match='unavailable'):
        local.sample(23.3, 42.7)


def test_real_prepared_raster_grid_and_accounting():
    cache = Path(__file__).resolve().parents[1]/'data/cache'
    if not (cache/'pluvial_provenance.json').exists():
        pytest.skip('Real terrain preprocessing has not completed')
    local = LocalPluvial(cache)
    assert local.available
    meta = local.meta()
    assert meta['grid']['transform'] == [5, 0, 299392, 0, -5, 4753611]
    assert meta['verification']['all_first5bands_pixel_equal_to_source']
    assert meta['verification']['native_hash_unchanged_before_after']
    assert meta['counts']['eligible_cells'] == sum(c['cells'] for c in meta['classes'])
    counts = meta['counts']
    assert counts['terrain_cells'] == counts['eligible_cells'] + counts['boundary_excluded_cells'] + counts['other_invalid_factor_cells']
    assert [s['cells'] for s in meta['sensitivity']] == sorted([s['cells'] for s in meta['sensitivity']], reverse=True)
    assert meta['source']['missing_imperviousness_bands_confirmed'] == [6, 7, 8]
    outside = local.sample(0, 0)
    assert outside['status'] == 'nodata' and outside['score'] is None
    sofia = local.sample(23.3219, 42.6977)
    assert sofia['status'] == 'ok'
    assert 0 <= sofia['score'] <= 100
    assert sofia['analysis_resolution_m'] == 5
    with rasterio.open(local.path) as src:
        assert tuple(src.descriptions) == BAND_NAMES
