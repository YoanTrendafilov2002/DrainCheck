"""Independent completeness, real geometry and fail-closed cadastre tests.

Large source batches are read one at a time. Tampering checks use a tiny
isolated project containing actual acquired buildings, never production files.
"""
from contextlib import closing
import copy
import gzip
import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import mapbox_vector_tile
import pytest
import shapely
from shapely.geometry import shape, mapping
from pyproj import Transformer

from backend.cadastre_routes import create_cadastre_router
from backend.context_layers import BuildingsContext, CadastralContext, sha256
from backend.tile_cache import ByteTileCache
from backend.vector import render_vector_tile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/reference/agkk_buildings'
EXPECTED = 334033
PROJECT = Transformer.from_crs(4326, 3857, always_xy=True)
HALF = 20037508.342789244


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def connect(path):
    return sqlite3.connect('file:' + Path(path).as_posix() + '?mode=ro', uri=True)


def at_tile(geometry, zoom=18):
    point = shape(geometry).representative_point()
    x, y = PROJECT.transform(point.x, point.y)
    return zoom, int((x + HALF) / (2 * HALF) * 2**zoom), int((HALF - y) / (2 * HALF) * 2**zoom)


def load_index_builder():
    spec = importlib.util.spec_from_file_location('test_cadastre_index_builder', ROOT / 'scripts/prepare_buildings_index.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def cadastral():
    context = CadastralContext(ROOT)
    metadata = context.meta()
    assert metadata.get('available'), 'Complete real AGKK metadata, display geometry and index must be prepared first'
    assert metadata['feature_count'] == EXPECTED
    return context


@pytest.fixture(scope='module')
def real_features(cadastral):
    with closing(connect(cadastral.database)) as db:
        # Prefer the separately recorded central-Sofia source example for the
        # browser-scale tile check, then exercise two additional real records.
        known = cadastral.meta().get('known_example', {}).get('source_id')
        identifiers = [str(known)] if known is not None else []
        for row in db.execute('SELECT source_id FROM features ORDER BY fid LIMIT 3'):
            if row[0] not in identifiers:
                identifiers.append(row[0])
        rows = [db.execute('SELECT source_id,properties,geometry FROM features WHERE source_id=?', (sid,)).fetchone()
                for sid in identifiers[:3]]
    assert len(rows) == 3
    return [{'type': 'Feature', 'id': row[0], 'properties': json.loads(row[1]),
             'geometry': mapping(shapely.from_wkb(row[2]))} for row in rows]


@pytest.fixture
def api(cadastral, tmp_path):
    cache = ByteTileCache(tmp_path / 'tiles')
    app = FastAPI()
    app.include_router(create_cadastre_router(cadastral, 'test-cadastral-renderer', cache))
    with TestClient(app) as client:
        yield client, cache


@pytest.fixture
def isolated(tmp_path, cadastral, real_features):
    """One genuine building and its original batch in an isolated test project."""
    feature = copy.deepcopy(real_features[0])
    root = tmp_path / 'project'
    (root / 'data/cache').mkdir(parents=True)
    (root / 'data/derived').mkdir(parents=True)
    path = root / feature['properties']['source_batch_file']
    path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / feature['properties']['source_batch_file'], path)
    geometry = root / 'data/derived/cadastral_buildings.geojson'
    geometry.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature]}), encoding='utf-8')
    metadata = copy.deepcopy(cadastral.meta())
    metadata.update(feature_count=1, revision='actual-source-test-subset')
    meta_path = root / 'data/cache/cadastral_buildings_meta.json'
    meta_path.write_text(json.dumps(metadata), encoding='utf-8')
    load_index_builder().prepare(geometry, meta_path, root / 'data/cache/cadastral_buildings.sqlite')
    context = CadastralContext(root)
    app = FastAPI()
    app.include_router(create_cadastre_router(context, 'test-renderer', ByteTileCache(root / 'tiles')))
    with TestClient(app) as client:
        yield context, client, feature, path


def change_properties(context, source_id, changes):
    with closing(sqlite3.connect(context.database)) as db, db:
        row = db.execute('SELECT properties FROM features WHERE source_id=?', (source_id,)).fetchone()
        properties = json.loads(row[0])
        properties.update(changes)
        db.execute('UPDATE features SET properties=? WHERE source_id=?', (json.dumps(properties), source_id))


def test_authoritative_snapshot_scope_provenance_and_height_semantics(cadastral):
    metadata = cadastral.meta()
    assert metadata['available'] and metadata['feature_count'] == EXPECTED
    assert metadata['minzoom'] == 13
    assert 'AGKK' in json.dumps(metadata, ensure_ascii=False)
    assert 'inspire.cadastre.bg' in json.dumps(metadata)
    assert metadata['coverage_bbox_wgs84'][0] < 23.32 < metadata['coverage_bbox_wgs84'][2]
    assert metadata['coverage_bbox_wgs84'][1] < 42.7 < metadata['coverage_bbox_wgs84'][3]
    source_date = metadata.get('source_date')
    assert source_date is None or ('catalogue' in source_date.lower() and 'do not establish' in source_date.lower()), \
        'Catalogue and lifecycle dates must not masquerade as a universal current building survey date'
    assert metadata['height']['available'] is False, 'No floor-to-height inference or unverified extrusion'
    assert 'not' in metadata['interpretation'].lower() and 'context' in metadata['interpretation'].lower()
    assert 'archiv' not in metadata['title'].lower()


def test_complete_official_id_set_matches_every_batch_and_sqlite(cadastral):
    queried = read_json(SOURCE / 'ids_study_bbox_original.json')
    expected = set(map(str, queried['objectIds']))
    assert len(queried['objectIds']) == len(expected) == EXPECTED
    manifest = read_json(SOURCE / 'manifest.json')
    assert manifest['expected_feature_count'] == EXPECTED and manifest['completed_utc']
    actual, batch_total = set(), 0
    for batch in manifest['batches']:
        path = SOURCE / batch['file']
        assert sha256(path) == batch['sha256']
        raw = gzip.decompress(path.read_bytes())
        assert hashlib.sha256(raw).hexdigest() == batch['content_sha256']
        document = json.loads(raw)
        assert document['type'] == 'FeatureCollection' and not document.get('exceededTransferLimit')
        ids = [str(f['properties']['objectid']) for f in document['features']]
        assert len(ids) == len(set(ids)) == batch['feature_count']
        assert not actual.intersection(ids), 'Duplicate national OIDs across acquired pages'
        actual.update(ids)
        batch_total += len(ids)
    with closing(connect(cadastral.database)) as db:
        indexed = {row[0] for row in db.execute('SELECT source_id FROM features')}
        assert db.execute('SELECT COUNT(*) FROM features').fetchone()[0] == EXPECTED
        assert db.execute('SELECT COUNT(*) FROM feature_bounds').fetchone()[0] == EXPECTED
    assert batch_total == EXPECTED and indexed == actual == expected


def test_real_inspection_restores_all_original_attributes_and_full_precision(cadastral, real_features):
    for compact in real_features:
        properties = compact['properties']
        raw_path = ROOT / properties['source_batch_file']
        with gzip.open(raw_path, 'rt', encoding='utf-8') as stream:
            source = next(f for f in json.load(stream)['features']
                          if str(f['properties']['objectid']) == str(properties['source_oid']))
        inspected = cadastral.feature(compact['id'])
        assert len(source['properties']) >= 100, 'Test must exercise full national attributes, not just compact tile fields'
        for key, value in source['properties'].items():
            assert inspected['properties'][key] == value
        assert inspected['properties']['id_localid'] == source['properties']['id_localid']
        assert str(source['properties']['objectid']) == inspected['id']
        assert 'height_m' not in inspected['properties']
        # Source batches were explicitly requested as output EPSG:4326. Full
        # source coordinates survive the WKB index unchanged for valid inputs.
        original = shape(source['geometry'])
        assert original.is_valid
        assert shape(inspected['geometry']).equals_exact(original, tolerance=0)
        assert shape(inspected['geometry']).equals_exact(shape(compact['geometry']), tolerance=0)


def test_actual_mvt_gzip_etag_revision_cache_and_range_download(api, cadastral, real_features):
    client, cache = api
    selected = real_features[0]
    zoom, x, y = at_tile(selected['geometry'])
    revision = cadastral.meta()['revision']
    url = f'/api/cadastre/tiles/{zoom}/{x}/{y}.pbf?v={revision}'
    identity = client.get(url, headers={'Accept-Encoding': 'identity'})
    assert identity.status_code == 200
    decoded = mapbox_vector_tile.decode(identity.content)['buildings']
    matches = [f for f in decoded['features'] if f['properties']['source_id'] == selected['id']]
    assert matches and decoded['extent'] == 4096
    assert matches[0]['geometry']['type'] in ['Polygon', 'MultiPolygon']
    assert 'height_m' not in matches[0]['properties']
    renders = cache.stats['renders']
    assert client.get(url, headers={'Accept-Encoding': 'identity'}).content == identity.content
    assert cache.stats['renders'] == renders
    compressed = client.get(url, headers={'Accept-Encoding': 'gzip'})
    assert compressed.content == identity.content and compressed.headers['content-encoding'] == 'gzip'
    assert compressed.headers['etag'] != identity.headers['etag']
    assert compressed.headers['vary'] == 'Accept-Encoding'
    assert client.get(url, headers={'Accept-Encoding': 'gzip', 'If-None-Match': compressed.headers['etag']}).status_code == 304
    assert client.get(f'/api/cadastre/tiles/{zoom}/{x}/{y}.pbf?v=stale').status_code == 409
    assert client.get(f'/api/cadastre/tiles/23/1/1.pbf?v={revision}').status_code == 422
    assert client.get('/api/cadastre/feature?source_id=not-a-real-oid').status_code == 404
    download = client.get('/api/cadastre/download', headers={'Range': 'bytes=0-255'})
    assert download.status_code == 206
    with cadastral.geojson.open('rb') as stream:
        assert download.content == stream.read(256)


def test_changed_original_batch_checksum_fails_after_a_successful_warm_read(isolated):
    context, client, feature, path = isolated
    url = '/api/cadastre/feature?source_id=' + feature['id']
    assert client.get(url).status_code == 200
    with path.open('ab') as stream:
        stream.write(b'test-only-source-tamper')
    response = client.get(url)
    assert response.status_code == 503 and 'checksum' in response.json()['detail'].lower()
    # The whole index is not reclassified as empty or replaced by archival data.
    assert context.meta()['feature_count'] == 1


def test_original_batch_path_is_confined_to_preserved_source_directory(isolated):
    context, client, feature, path = isolated
    for bad in ['../outside.geojson.gz', 'data/reference/agkk_buildings/elsewhere.geojson.gz',
                'data/reference/agkk_buildings/batches/not-a-source.txt']:
        change_properties(context, feature['id'], {'source_batch_file': bad})
        response = client.get('/api/cadastre/feature?source_id=' + feature['id'])
        assert response.status_code == 503
        assert 'preserved source directory' in response.json()['detail']


def test_oid_and_cadastral_identifier_must_join_the_preserved_record(isolated):
    context, client, feature, path = isolated
    original = feature['properties']
    change_properties(context, feature['id'], {'source_oid': -999999999})
    response = client.get('/api/cadastre/feature?source_id=' + feature['id'])
    assert response.status_code == 503 and 'missing' in response.json()['detail'].lower()
    change_properties(context, feature['id'], {'source_oid': original['source_oid'], 'id_localid': 'unmatched-test-id'})
    response = client.get('/api/cadastre/feature?source_id=' + feature['id'])
    assert response.status_code == 503 and 'identifier differs' in response.json()['detail'].lower()


def test_incomplete_source_batch_rejected_even_with_matching_checksum(isolated):
    context, client, feature, path = isolated
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        document = json.load(stream)
    document['exceededTransferLimit'] = True
    path.write_bytes(gzip.compress(json.dumps(document).encode(), mtime=0))
    change_properties(context, feature['id'], {'source_batch_sha256': sha256(path)})
    response = client.get('/api/cadastre/feature?source_id=' + feature['id'])
    assert response.status_code == 503 and 'incomplete' in response.json()['detail'].lower()


def test_missing_main_source_does_not_silently_use_archive_or_twin(tmp_path):
    root = tmp_path / 'unprepared'
    (root / 'data/cache').mkdir(parents=True)
    # A real archival metadata file exists in the test root, but it is a
    # different source and cannot satisfy the national cadastre adapter.
    shutil.copyfile(ROOT / 'data/cache/cadastral_archive_buildings_meta.json', root / 'data/cache/cadastral_archive_buildings_meta.json')
    context = CadastralContext(root)
    app = FastAPI()
    app.include_router(create_cadastre_router(context, 'test', ByteTileCache(root / 'tiles')))
    with TestClient(app) as client:
        assert client.get('/api/cadastre/meta').json()['available'] is False
        assert client.get('/api/cadastre/feature?source_id=3701').status_code == 503
        assert client.get('/api/cadastre/download').status_code == 503


def test_existing_context_endpoints_and_data_revisions_remain_independent(cadastral):
    from backend import app as production
    paths = set(production.app.openapi()['paths'])
    assert {'/api/buildings/meta', '/api/history/zones/meta', '/api/pluvial/meta',
            '/api/rainfall/meta', '/api/cadastre/meta'} <= paths
    legacy_revision = (ROOT / 'data/cache/revision.txt').read_text().strip()
    assert production.revision() == legacy_revision
    assert cadastral.meta()['revision'] != legacy_revision
    twin = BuildingsContext(ROOT).meta()
    assert twin['title'] == 'Sofia Digital Twin buildings'
    assert twin.get('feature_count', 0) != EXPECTED
    with TestClient(production.app) as client:
        assert client.get('/api/buildings/meta').json()['title'] == 'Sofia Digital Twin buildings'
        assert client.get('/api/rainfall/meta').json()['available'] is True
    assert production.revision() == legacy_revision


def test_archival_source_retained_separately_with_all_originals_verified():
    metadata = read_json(ROOT / 'data/cache/cadastral_archive_buildings_meta.json')
    receipt = read_json(ROOT / 'test-artifacts/cadastral_archive_validation.json')
    assert metadata['original_feature_count'] == metadata['feature_count'] == 265216
    assert metadata['promoted_to_main_cadastre'] is False and metadata['height']['available'] is False
    assert metadata['source_date'] is None and metadata['catalogue_valid_at'] == '2026-09-08'
    check = receipt['independent_source_to_derivative_verification']
    assert check['all_original_properties_compared'] == check['unchanged_original_geometry_coordinates_compared'] == 265216
    assert check['original_zip_unchanged'] and check['main_cadastre_not_replaced']
    assert sha256(ROOT / 'data/reference/cadastral_buildings/cad_plan_sgr.zip') == receipt['source_archive_sha256_before'] == receipt['source_archive_sha256_after']
    assert receipt['source_holes'] == receipt['derived_holes'] == 308


def test_streaming_index_matches_small_builder_for_real_buildings(tmp_path, real_features):
    features = copy.deepcopy(real_features[:2])
    source = tmp_path / 'actual-source-subset.geojson'
    source.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
    lines = tmp_path / 'actual-source-subset.ndjson'
    lines.write_text('\n'.join(json.dumps(f) for f in features) + '\n', encoding='utf-8')
    meta = tmp_path / 'meta.json'
    meta.write_text(json.dumps({'available': True, 'revision': 'test-real-subset', 'feature_count': 2,
                                'feature_lines_sha256': sha256(lines),
                                'height': {'available': False}}), encoding='utf-8')
    before = sha256(source)
    original, streamed = tmp_path / 'small.sqlite', tmp_path / 'stream.sqlite'
    builder = load_index_builder()
    builder.prepare(source, meta, original)
    builder.prepare_stream(source, meta, streamed, lines)
    with closing(connect(original)) as a, closing(connect(streamed)) as b:
        rows_a = a.execute('SELECT fid,source_id,kind,properties,geometry FROM features ORDER BY fid').fetchall()
        rows_b = b.execute('SELECT fid,source_id,kind,properties,geometry FROM features ORDER BY fid').fetchall()
        assert rows_a == rows_b
        assert a.execute('SELECT * FROM feature_bounds ORDER BY fid').fetchall() == b.execute('SELECT * FROM feature_bounds ORDER BY fid').fetchall()
    coordinates = at_tile(features[0]['geometry'])
    assert render_vector_tile(original, 'buildings', *coordinates, zone='all', display='all') == render_vector_tile(streamed, 'buildings', *coordinates, zone='all', display='all')
    assert sha256(source) == before
    valid_index_hash = sha256(streamed)
    with lines.open('a', encoding='utf-8') as stream:
        stream.write('\n')
    with pytest.raises(ValueError, match='acquisition receipt'):
        builder.prepare_stream(source, meta, streamed, lines)
    assert sha256(streamed) == valid_index_hash, 'Unverified intermediate must not overwrite an already valid index'
