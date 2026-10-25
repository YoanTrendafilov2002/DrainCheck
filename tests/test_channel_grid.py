"""Independent geometric checks of zero-width channel/grid intersections."""
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import LineString, MultiLineString, Polygon

from scripts.channel_grid import burn_centerline_cells


def geometric_reference(shape, grid, geometry):
    expected = np.zeros(shape, dtype=bool)
    for row in range(shape[0]):
        for col in range(shape[1]):
            cell = Polygon([grid@(col, row), grid@(col+1, row),
                            grid@(col+1, row+1), grid@(col, row+1)])
            expected[row, col] = geometry.intersects(cell)
    return expected


def test_actual_nearly_horizontal_zhelyavska_segment_retains_both_crossed_rows():
    original_grid = Affine(5, 0, 299392, 0, -5, 4753611)
    grid = original_grid@Affine.translation(9217, 3171)
    line = LineString([(345492.48719785, 4737746.02104076),
                       (345483.49681107, 4737745.98851211)])
    result = np.zeros((4, 6), dtype='uint8')
    burn_centerline_cells(result, [line], grid)
    assert result[3172-3171, 9219-9217] == 1
    assert np.array_equal(result != 0, geometric_reference(result.shape, grid, line))
    assert np.count_nonzero(result.any(axis=1)) == 2


@pytest.mark.parametrize('coordinates', [
    [(2, 10), (18, 10)],                    # Horizontal shared cell edge.
    [(10, 2), (10, 18)],                    # Vertical shared cell edge.
    [(1, 19), (19, 1)],                     # Exact grid-corner crossings.
    [(-100, 10), (100, 10)],                # Both endpoints outside, crosses grid.
    [(-10, 30), (0, 20)],                   # Only touches the outer corner.
    [(-100, 30), (100, 30)],                # Entirely outside.
    [(1, 19), (4, 16)],                     # Entirely inside one cell.
    [(2, 18), (2, 18)],                     # Repeated source coordinate.
])
def test_every_closed_cell_intersection_matches_independent_geometry(coordinates):
    grid = Affine(5, 0, 0, 0, -5, 20)
    line = LineString(coordinates)
    result = np.zeros((4, 4), dtype='uint8')
    burn_centerline_cells(result, [line], grid)
    assert np.array_equal(result != 0, geometric_reference(result.shape, grid, line))
    reversed_result = np.zeros_like(result)
    burn_centerline_cells(reversed_result, [LineString(coordinates[::-1])], grid)
    assert np.array_equal(result, reversed_result)


def test_separate_parts_do_not_create_a_connection_and_existing_flags_are_preserved():
    grid = Affine(5, 0, 0, 0, -5, 20)
    lines = MultiLineString([[(1, 19), (4, 16)], [(16, 4), (19, 1)]])
    result = np.full((4, 4), 2, dtype='uint8')
    assert burn_centerline_cells(result, [lines], grid) is result
    expected = geometric_reference(result.shape, grid, lines)
    assert np.array_equal(result, np.where(expected, 3, 2))
    assert result[1, 1] == result[2, 2] == 2


def test_rotated_grid_uses_its_actual_cell_footprints():
    grid = Affine.translation(300000, 4700000)@Affine.rotation(15)@Affine.scale(5, -5)
    line = LineString([grid@(.2, .3), grid@(3.8, 3.4)])
    result = np.zeros((4, 4), dtype='uint8')
    burn_centerline_cells(result, [line], grid)
    assert np.array_equal(result != 0, geometric_reference(result.shape, grid, line))
