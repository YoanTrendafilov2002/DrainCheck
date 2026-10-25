"""Bound channel screening exclusions by real, connected terrain-fill evidence.

The supplied corridor limits the search; it is not itself an exclusion. Only
valid positive-fill cells connected to an existing river seed can be added.
This display policy does not identify physical water width or a floodplain.
"""
import numpy as np
from scipy.ndimage import binary_propagation


def expand_terrain_connected_channels(mask, search_corridor, positive_fill_valid):
    """Add terrain-candidate flag 5 through eligible eight-connected cells.

    ``mask`` is the uint8 policy raster: bit 1 is the river-screening exclusion,
    bit 2 is a mapped stadium, and bit 4 records terrain inference rather than
    mapped channel geometry. Newly reached cells receive bits 1+4 (value 5,
    or 7 over a stadium). Existing source river cells retain their original
    flags; bit 4 is never added to them or produced without river bit 1.
    ``search_corridor`` is the bounded boolean search area made by the caller.
    ``positive_fill_valid`` must mark only finite, valid real terrain whose fill
    depth is strictly positive; the helper never invents or modifies elevations.
    Returns the same mask plus auditable native-cell counts.
    """
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.uint8:
        raise ValueError('Terrain-connected channel mask must be a 2D uint8 array')
    for name, values in (('search_corridor', search_corridor),
                         ('positive_fill_valid', positive_fill_valid)):
        if (not isinstance(values, np.ndarray) or values.dtype != np.bool_
                or values.shape != mask.shape):
            raise ValueError(name+' must be a boolean array aligned with the policy mask')

    seeds = (mask & np.uint8(1)) != 0
    seed_count = int(np.count_nonzero(seeds))
    allowed = np.logical_and(search_corridor, positive_fill_valid)
    np.logical_or(allowed, seeds, out=allowed)
    candidate_count = int(np.count_nonzero(allowed))-seed_count
    propagated = binary_propagation(seeds, structure=np.ones((3, 3), dtype=bool), mask=allowed)
    propagated[seeds] = False
    added_count = int(np.count_nonzero(propagated))
    mask[propagated] |= np.uint8(5)
    return mask, {'method': 'positive-fill-connected-within-bounded-channel-search',
                  'connectivity': 8,
                  'original_river_cells': seed_count,
                  'eligible_candidate_cells': candidate_count,
                  'additional_river_cells': added_count,
                  'terrain_candidate_cells': int(np.count_nonzero(mask & np.uint8(4))),
                  'unconnected_candidate_cells': candidate_count-added_count,
                  'result_river_cells': seed_count+added_count}
