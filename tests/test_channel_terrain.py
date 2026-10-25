"""Terrain policy expands only through evidence connected to mapped channels."""
import numpy as np
import pytest

from scripts.channel_terrain import expand_terrain_connected_channels


def test_only_connected_positive_fill_inside_search_area_is_added_and_bits_survive():
    mask = np.zeros((7, 8), dtype='uint8')
    mask[3, 1] = 1
    mask[6, 0] = 3
    mask[0, 0] = 2
    corridor = np.zeros(mask.shape, dtype=bool)
    positive = np.zeros(mask.shape, dtype=bool)
    connected = [(3, 2), (3, 3), (4, 4)]
    for cell in connected:
        corridor[cell] = positive[cell] = True
    corridor[3, 4] = True                    # Flat bank: no positive fill.
    corridor[0, 6] = positive[0, 6] = True   # Isolated positive-fill puddle.
    positive[3, 6] = True                   # Positive fill outside the corridor.
    corridor[0, 0] = positive[0, 0] = True   # Stadium cannot seed river propagation.
    before_corridor, before_positive = corridor.copy(), positive.copy()
    result, stats = expand_terrain_connected_channels(mask, corridor, positive)
    assert result is mask
    assert all(mask[cell] == 5 for cell in connected)
    assert mask[3, 4] == mask[0, 6] == mask[3, 6] == 0
    assert mask[0, 0] == 2 and mask[6, 0] == 3 and mask[3, 1] == 1
    assert stats == {'method': 'positive-fill-connected-within-bounded-channel-search',
                     'connectivity': 8, 'original_river_cells': 2,
                     'eligible_candidate_cells': 5, 'additional_river_cells': 3,
                     'terrain_candidate_cells': 3,
                     'unconnected_candidate_cells': 2, 'result_river_cells': 5}
    assert np.array_equal(corridor, before_corridor)
    assert np.array_equal(positive, before_positive)


def test_flat_or_invalid_terrain_breaks_a_positive_fill_connection():
    mask = np.zeros((3, 6), dtype='uint8')
    mask[1, 0] = 1
    corridor = np.ones(mask.shape, dtype=bool)
    positive = np.zeros(mask.shape, dtype=bool)
    positive[1, 1] = positive[1, 3] = positive[1, 4] = True
    result, stats = expand_terrain_connected_channels(mask, corridor, positive)
    assert result[1, 1] == 5
    assert not result[1, 2:].any(), 'Zero-fill/invalid cells must not bridge to a separate depression'
    assert stats['additional_river_cells'] == 1
    assert stats['unconnected_candidate_cells'] == 2


def test_eight_neighbour_diagonal_connection_is_explicit_and_preserves_stadium_bit():
    mask = np.zeros((4, 4), dtype='uint8')
    mask[0, 0] = 1
    mask[2, 2] = 2
    corridor = np.eye(4, dtype=bool)
    positive = corridor.copy()
    result, stats = expand_terrain_connected_channels(mask, corridor, positive)
    assert result[1, 1] == result[3, 3] == 5
    assert result[2, 2] == 7
    assert np.count_nonzero(result) == 4
    assert stats['additional_river_cells'] == 3
    assert stats['terrain_candidate_cells'] == 3
    assert set(np.unique(result)) == {0, 1, 5, 7}


def test_repeated_expansion_keeps_mapped_and_preexisting_inferred_flags_distinct():
    mask = np.array([[1, 3, 5, 7, 0]], dtype='uint8')
    corridor = np.ones(mask.shape, dtype=bool)
    result, stats = expand_terrain_connected_channels(mask, corridor, corridor)
    assert result.tolist() == [[1, 3, 5, 7, 5]]
    assert stats['additional_river_cells'] == 1
    assert stats['terrain_candidate_cells'] == 3
    assert not np.any(((result & 4) != 0) & ((result & 1) == 0)), 'Inference always includes the river exclusion bit'


def test_no_river_seeds_produces_no_expansion():
    mask = np.full((3, 3), 2, dtype='uint8')
    corridor = np.ones(mask.shape, dtype=bool)
    result, stats = expand_terrain_connected_channels(mask, corridor, corridor)
    assert np.all(result == 2)
    assert stats['additional_river_cells'] == stats['original_river_cells'] == 0
    assert stats['unconnected_candidate_cells'] == 9


@pytest.mark.parametrize('corridor,positive', [
    (np.ones((2, 2), dtype='uint8'), np.ones((2, 2), dtype=bool)),
    (np.ones((2, 3), dtype=bool), np.ones((2, 2), dtype=bool)),
    (np.ones((2, 2), dtype=bool), np.ones((2, 2), dtype='float32')),
])
def test_misaligned_or_nonboolean_evidence_is_rejected(corridor, positive):
    with pytest.raises(ValueError):
        expand_terrain_connected_channels(np.zeros((2, 2), dtype='uint8'), corridor, positive)
