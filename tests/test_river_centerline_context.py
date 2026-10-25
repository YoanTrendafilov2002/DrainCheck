"""Verified source centerlines fix context without promoting inferred corridors."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from backend.river_context import RiverContext, river_features

ROOT = Path(__file__).resolve().parents[1]


def document(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_line(river):
    return next(feature for feature in document(river.channel_path)['features']
                if feature['properties'].get('osm_id') == 256813270)


def test_actual_perlovska_source_vertex_is_near_a_river_without_assigning_flood_cause():
    river = RiverContext(ROOT)
    feature = source_line(river)
    location = feature['geometry']['coordinates'][3]
    result = river.sample(*location, threshold_m=0, reported_mechanism='unknown')
    assert result['nearest_distance_m'] == 0
    assert result['category'] == 'river_adjacent_possible_mixed'
    assert result['nearest_source']['source_id'] == 'way/256813270'
    assert result['nearest_source']['source_kind'] == 'osm_open_river_centerline'
    assert result['nearest_source']['source_url'] == 'https://www.openstreetmap.org/way/256813270'
    assert result['reported_mechanism'] == 'unknown' and result['causation'] == 'not_determined'


def test_real_off_line_channel_bed_uses_distance_to_original_line_not_inferred_corridor():
    river = RiverContext(ROOT)
    result = river.sample(23.315021695213026, 42.68027208839755)
    assert 0 < result['nearest_distance_m'] < 20
    assert result['category'] == 'river_adjacent_possible_mixed'
    assert result['nearest_source']['source_id'] == 'way/256813270'
    assert result['causation'] == 'not_determined'


def test_supplement_identity_is_verified_and_metadata_urls_remain_compact():
    river = RiverContext(ROOT)
    meta = river.meta()
    assert meta['available']
    counts = meta['source_counts']
    assert counts['osm_river_centerlines'] == 1887
    assert counts['included_river_geometries'] == 1924
    assert meta['source_hashes']['open_centerline_geometry'] == hashlib.sha256(river.channel_path.read_bytes()).hexdigest()
    assert len(meta['source_urls']) < 10, 'OSM record URLs belong in individual nearest-source records'
    assert 'https://www.openstreetmap.org/copyright' in meta['source_urls']


@pytest.mark.parametrize('change', [
    {'waterway': 'drain'}, {'waterway': 'ditch'}, {'tunnel': 'culvert'},
    {'covered': 'yes'}, {'location': 'underground'}, {'abandoned:waterway': 'river'},
])
def test_nonriver_covered_or_inactive_source_lines_are_not_river_distance_inputs(change):
    feature = copy.deepcopy(source_line(RiverContext(ROOT)))
    feature['properties']['tags'].update(change)
    selected, counts = river_features({'features': []}, {'features': []}, {'features': [feature]})
    assert not selected and counts['osm_river_centerlines'] == 0


def test_inferred_geometry_roles_are_never_promoted_to_observed_river_geometry():
    feature = copy.deepcopy(source_line(RiverContext(ROOT)))
    feature['properties']['geometry_role'] = 'terrain_connected_candidate'
    selected, counts = river_features({'features': []}, {'features': []}, {'features': [feature]})
    assert not selected and counts['osm_river_centerlines'] == 0


@pytest.mark.parametrize('problem', ['changed_geometry', 'missing_receipt', 'missing_geometry'])
def test_changed_or_incomplete_supplement_fails_closed_instead_of_using_polygon_only_context(tmp_path, problem):
    original, restored = RiverContext(ROOT), RiverContext(tmp_path)
    for name in ('water_path', 'water_meta', 'context_path', 'assessment_meta', 'channel_path', 'channel_meta'):
        target = getattr(restored, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(getattr(original, name), target)
    if problem == 'changed_geometry':
        with restored.channel_path.open('a', encoding='utf-8') as output:
            output.write('\n')
    elif problem == 'missing_receipt':
        restored.channel_meta.unlink()
    else:
        restored.channel_path.unlink()
    assert not restored.meta()['available']
    result = restored.sample(*source_line(original)['geometry']['coordinates'][3], reported_mechanism='unknown')
    assert result['category'] == 'unknown'
    assert result['nearest_distance_m'] is None
    assert result['reported_mechanism'] == 'unknown' and result['causation'] == 'not_determined'
