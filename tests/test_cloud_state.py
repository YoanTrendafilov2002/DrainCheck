"""Private restart durability and portable identity, using genuine local inputs."""
import hashlib
import io
import json
import math
import shutil
import urllib.error
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import FileResponse
from PIL import Image
from shapely import transform
from shapely.geometry import Polygon, box, mapping

from backend.cloud_state import (CloudStateUnavailable, DATA_SCHEMA, MAX_JSON_BYTES, MAX_OBJECT_BYTES,
                                 PrivateStateStore, VerifiedDataSnapshot, file_digest, json_bytes)
from backend.clogging import CloggingScenarios, TO_GEO, TO_METRIC
from backend.clogging_routes import create_clogging_router
from backend.pluvial import LocalPluvial
from backend.river_context import RiverContext
from backend.terrain import LocalTerrain

ROOT = Path(__file__).resolve().parents[1]


class MemoryObjects:
    def __init__(self):
        self.values = {}
        self.operations = []
        self.fail = None

    def __call__(self, method, key, data=None):
        self.operations.append((method, key))
        if self.fail and self.fail(method, key):
            raise OSError('private-response-secret-must-not-escape')
        if method == 'PUT':
            self.values[key] = data
            return b''
        return self.values.get(key)


def manifest(root, names):
    document = {'schema': DATA_SCHEMA, 'files': {
        name: {'size': (root/name).stat().st_size,
               'sha256': hashlib.sha256((root/name).read_bytes()).hexdigest()}
        for name in names}}
    path = root/'runtime-data-manifest.json'
    path.write_bytes(json_bytes(document))
    return path


def test_verified_snapshot_is_content_portable_and_local_changes_fail_closed(tmp_path):
    # Small genuine metadata copies test identity mechanics; they are never
    # installed as terrain or substituted for any scientific input.
    names = ['data/cache/revision.txt', 'data/cache/pluvial_meta.json']
    roots = [tmp_path/'container-a', tmp_path/'container-b']
    snapshots = []
    for root in roots:
        for name in names:
            (root/name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, root/name)
        snapshots.append(VerifiedDataSnapshot(root, manifest(root,names)))
    a,b = [snapshot.state([root/name for name in names]) for root,snapshot in zip(roots,snapshots)]
    assert a == b
    assert str(tmp_path) not in json.dumps(a)
    assert a['identity_method'] == 'verified-sha256-content-v1'
    (roots[1]/names[0]).write_text('changed', encoding='ascii')
    with pytest.raises(RuntimeError, match='changed'):
        snapshots[1].state([roots[1]/names[0]])


def test_manifest_rejects_bad_hash_escape_and_unlisted_sources(tmp_path):
    original = ROOT/'data/cache/revision.txt'
    (tmp_path/'revision.txt').write_bytes(original.read_bytes())
    path = manifest(tmp_path,['revision.txt'])
    document = json.loads(path.read_bytes())
    document['files']['revision.txt']['sha256'] = '0'*64
    path.write_bytes(json_bytes(document))
    with pytest.raises(ValueError,match='differs'):
        VerifiedDataSnapshot(tmp_path,path)
    document['files'] = {'../outside': {'size': 1,'sha256':'0'*64}}
    path.write_bytes(json_bytes(document))
    with pytest.raises(ValueError,match='Unsafe'):
        VerifiedDataSnapshot(tmp_path,path)
    snapshot = VerifiedDataSnapshot(tmp_path,manifest(tmp_path,['revision.txt']))
    (tmp_path/'not-listed').write_bytes(b'')
    with pytest.raises(RuntimeError,match='absent'):
        snapshot.state([tmp_path/'not-listed'])


def test_environment_opt_in_and_private_host_and_key_limits(monkeypatch):
    monkeypatch.delenv('DRAINCHECK_STATE_URL',raising=False)
    monkeypatch.delenv('DRAINCHECK_DATA_MANIFEST',raising=False)
    assert PrivateStateStore.from_env() is None
    assert VerifiedDataSnapshot.from_env(ROOT) is None
    with pytest.raises(ValueError,match='private'):
        PrivateStateStore('https://public.example')
    store = PrivateStateStore(transport=MemoryObjects())
    with pytest.raises(CloudStateUnavailable,match='Unsupported'):
        store.object('GET','../secrets')
    with pytest.raises(CloudStateUnavailable,match='size'):
        store.object('PUT','local-scales/local-'+'0'*16+'.json',b'x'*(MAX_OBJECT_BYTES+1))


def test_private_http_transport_sets_length_and_does_not_expose_server_error(monkeypatch):
    seen=[]
    class Response:
        headers={'Content-Length':'0'}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,limit):return b''
    class Opener:
        def open(self,request,timeout):
            seen.append(request)
            if request.method == 'GET':
                raise urllib.error.HTTPError(request.full_url,404,'private error',{},None)
            return Response()
    monkeypatch.setattr('backend.cloud_state.urllib.request.build_opener',lambda *handlers:Opener())
    store=PrivateStateStore()
    key='local-scales/local-'+'0'*16+'.json'
    store.object('PUT',key,b'abc')
    assert seen[0].get_header('Content-length')=='3'
    assert seen[0].full_url == 'http://draincheck-state.internal/objects/'+key
    assert store.object('GET',key) is None
    class FailedOpener:
        def open(self,request,timeout):
            raise urllib.error.HTTPError(request.full_url,403,'sensitive private response',{},None)
    monkeypatch.setattr('backend.cloud_state.urllib.request.build_opener',lambda *handlers:FailedOpener())
    with pytest.raises(CloudStateUnavailable) as error:
        store.object('PUT',key,b'abc')
    assert 'sensitive' not in str(error.value) and '403' not in str(error.value)


@pytest.fixture(scope='module')
def actual_case(tmp_path_factory):
    memory = MemoryObjects()
    store = PrivateStateStore(transport=memory)
    pluvial = LocalPluvial(ROOT/'data/cache')
    assert pluvial.available, 'The genuine restored analysis terrain is required'
    service = CloggingScenarios(ROOT,pluvial,RiverContext(ROOT),cloud_state=store)
    service.directory = tmp_path_factory.mktemp('cloud-source')
    x,y = TO_METRIC.transform(23.267111,42.684845)
    geometry = mapping(transform(box(x-200,y-200,x+200,y+200),TO_GEO.transform,interleaved=False))
    result = service.create(geometry)
    return service,result,memory,store


def test_actual_scenario_manifest_is_commit_marker_and_restart_restores_exact_bytes(actual_case,tmp_path):
    service,result,memory,store = actual_case
    assert 'identity_method' not in result['source_revisions']
    assert Path(result['source_revisions']['files'][0][0]).resolve() == service.database.resolve()
    identity = result['scenario_id']
    assert memory.operations[-1] == ('PUT',f'scenarios/{identity}/manifest.json')
    restarted = CloggingScenarios(ROOT,service.pluvial,RiverContext(ROOT),
                                  cloud_state=PrivateStateStore(transport=memory))
    restarted.directory = tmp_path/'after-container-restart'
    restored = restarted.result(identity)
    assert restored == json.loads(json.dumps(result))
    for name in ['result.json','runoff.tif','river_classes.tif']:
        assert (restarted.path(identity)/name).read_bytes() == (service.path(identity)/name).read_bytes()
    with rasterio.open(restarted.path(identity)/'runoff.tif') as src:
        assert src.count == 6 and src.crs.to_epsg() == 7801 and src.res == (5,5)
        assert src.nodata == -9999
        assert src.descriptions == tuple(result['bands'])
    # The normal APIs, including PNG and byte-range download, consume restored
    # real raster data without requiring a new scenario calculation.
    app = FastAPI();app.include_router(create_clogging_router(restarted))
    with TestClient(app) as client:
        assert client.get(f'/api/clogging/scenarios/{identity}').status_code == 200
        response = client.get(f'/api/clogging/scenarios/{identity}/download',headers={'Range':'bytes=0-255'})
        assert response.status_code == 206 and len(response.content) == 256
        z=15;lon,lat=23.267111,42.684845
        x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
        response = client.get(f'/api/clogging/scenarios/{identity}/tiles/depth_clogged/{z}/{x}/{y}.png')
        assert response.status_code == 200
        assert Image.open(io.BytesIO(response.content)).size == (256,256)
    assert not list(restarted.directory.glob('restore-*'))


def test_partial_private_bundle_is_never_restored(actual_case,tmp_path):
    service,result,memory,_ = actual_case
    broken = MemoryObjects();broken.values = dict(memory.values)
    identity = result['scenario_id']
    broken.values[f'scenarios/{identity}/runoff.tif'] = b'corrupt'
    store = PrivateStateStore(transport=broken)
    target = tmp_path/identity
    with pytest.raises(CloudStateUnavailable,match='checksum'):
        store.restore_scenario(target,identity)
    assert not target.exists() and not list(tmp_path.glob('restore-*'))
    del broken.values[f'scenarios/{identity}/manifest.json']
    assert store.restore_scenario(target,identity) is False
    assert not target.exists()


def test_valid_complex_real_selection_receipt_over_2mib_persists_and_restores(actual_case,tmp_path):
    service,_,_,_ = actual_case
    x,y=TO_METRIC.transform(23.32,42.70)
    x0,x1,y0,y1=x-2475,x+2475,y-2475,y+2475
    teeth=250;step=(x1-x0)/(2*teeth)
    coordinates=[(x0,y0),(x1,y0),(x1,y1)]
    for i in range(teeth):
        a=x1-(2*i+1)*step;b=x1-(2*i+2)*step
        coordinates.extend([(a,y1),(a,y0+5),(b,y0+5)])
        if i < teeth-1:
            coordinates.append((b,y1))
    coordinates.append((x0,y0))
    geometry=mapping(transform(Polygon(coordinates),TO_GEO.transform,interleaved=False))
    # This genuine-source AOI has 1003 permitted vertices, 12.26 km2 and
    # fewer than 1M grid cells. Its clipped real route/buffer geometry makes
    # the ordinary result receipt exceed the smaller manifest/scale budget.
    memory=MemoryObjects()
    complex_service=CloggingScenarios(ROOT,service.pluvial,
                                      cloud_state=PrivateStateStore(transport=memory))
    complex_service.directory=tmp_path/'calculated'
    result=complex_service.create(geometry,influence_distance_m=5)
    identity=result['scenario_id']
    receipt=(complex_service.path(identity)/'result.json').read_bytes()
    assert MAX_JSON_BYTES < len(receipt) <= MAX_OBJECT_BYTES
    restarted=CloggingScenarios(ROOT,service.pluvial,
                                cloud_state=PrivateStateStore(transport=memory))
    restarted.directory=tmp_path/'restored'
    restored=restarted.result(identity)
    assert (restarted.path(identity)/'result.json').read_bytes() == receipt
    assert restored['statistics'] == result['statistics']
    assert restored['depth_statistics'] == result['depth_statistics']
    assert restored['grid']['width']*restored['grid']['height'] <= 1_000_000
    # Manifest and local-scale parsing retain the tighter 2 MiB ceiling.
    with pytest.raises(CloudStateUnavailable,match='receipt'):
        PrivateStateStore._document(receipt)


def test_real_scenario_portable_id_survives_changed_container_root(tmp_path):
    names = ['data/cache/spatial.sqlite', 'data/cache/pluvial_5m.tif',
             'data/cache/pluvial_provenance.json', 'data/cache/open_water_mask_5m.tif',
             'data/cache/open_water_meta.json', 'data/cache/revision.txt',
             'data/cache/screening_exclusions_5m.tif', 'data/cache/screening_exclusions_meta.json']
    # Hard links preserve genuine immutable bytes without making another 2 GB
    # copy. The source is never modified; each container has distinct paths.
    entries = {name:{'size':(ROOT/name).stat().st_size,
                    'sha256':file_digest(ROOT/name)}
               for name in names}
    memory = MemoryObjects()
    results = []
    source_states = []
    x,y = TO_METRIC.transform(23.267111,42.684845)
    geometry = mapping(transform(box(x-200,y-200,x+200,y+200),TO_GEO.transform,interleaved=False))
    for suffix in ['container-one','container-two']:
        root = tmp_path/suffix
        for name in names:
            target = root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.hardlink_to(ROOT/name)
        path=root/'runtime-data-manifest.json'
        path.write_bytes(json_bytes({'schema':DATA_SCHEMA,'files':entries}))
        snapshot=VerifiedDataSnapshot(root,path)
        service=CloggingScenarios(root,LocalPluvial(root/'data/cache'),
                                  cloud_state=PrivateStateStore(transport=memory),snapshot=snapshot)
        source_states.append(service.source_state())
        results.append(json.loads(json.dumps(service.create(geometry))))
    assert results[0] == results[1]
    assert source_states[0] == source_states[1]
    assert 'dataset_snapshot_sha256' in source_states[0]
    assert str(tmp_path) not in json.dumps(source_states[0])


def test_private_upload_failure_is_503_and_retry_finishes_durable_commit(actual_case,tmp_path):
    service,result,_,_ = actual_case
    memory = MemoryObjects()
    memory.fail = lambda method,key: method == 'PUT' and key.endswith('/manifest.json')
    store = PrivateStateStore(transport=memory)
    failing = CloggingScenarios(ROOT,service.pluvial,RiverContext(ROOT),cloud_state=store)
    failing.directory = tmp_path/'scenario'
    app = FastAPI();app.include_router(create_clogging_router(failing))
    with TestClient(app) as client:
        response = client.post('/api/clogging/scenarios',json={'geometry':result['geometry']})
        assert response.status_code == 503
        assert 'secret' not in response.text and 'private-response' not in response.text
        assert not any(key.endswith('/manifest.json') for key in memory.values)
        memory.fail = None
        response = client.post('/api/clogging/scenarios',json={'geometry':result['geometry']})
        assert response.status_code == 200
        identity=response.json()['scenario_id']
        assert f'scenarios/{identity}/manifest.json' in memory.values


def test_actual_local_colour_scale_restores_after_restart_and_validates_revision(tmp_path):
    source = next((ROOT/'data/cache').glob('local-*.json'))
    identity = source.stem
    cache = tmp_path/'cache';cache.mkdir()
    shutil.copyfile(ROOT/'data/cache/revision.txt',cache/'revision.txt')
    shutil.copyfile(source,cache/source.name)
    native = ROOT.parent/'sofia_dtm_2024_1m_gee.tif'
    terrain = LocalTerrain(native,cache)
    assert terrain.available, 'The genuine native municipal terrain is required'
    memory=MemoryObjects();store=PrivateStateStore(transport=memory)
    store.install_terrain(terrain)
    actual = json.loads(source.read_bytes())
    result=terrain.local_scale(actual['bbox'],actual['dataset_revision'])
    assert result['id'] == identity
    payload=(cache/source.name).read_bytes()
    (cache/source.name).unlink()
    assert terrain.scale(identity) == result
    assert (cache/source.name).read_bytes() == payload
    # Wrong dataset revision still receives the existing local adapter's
    # rejection; the state layer cannot make stale colours appear current.
    (cache/'revision.txt').write_text('different',encoding='ascii')
    with pytest.raises(KeyError,match='different data revision'):
        terrain.scale(identity)


def test_local_colour_scale_corruption_is_atomic_and_network_failure_not_silent(tmp_path):
    source = next((ROOT/'data/cache').glob('local-*.json'))
    memory=MemoryObjects();store=PrivateStateStore(transport=memory)
    store.persist_scale(source,source.stem)
    key=f'local-scales/{source.name}'
    envelope=json.loads(memory.values[key]);envelope['payload']+=' '
    memory.values[key]=json_bytes(envelope)
    target=tmp_path/source.name
    with pytest.raises(CloudStateUnavailable,match='checksum'):
        store.restore_scale(target,source.stem)
    assert not target.exists()
    memory.fail=lambda method,key:True
    with pytest.raises(CloudStateUnavailable,match='unavailable'):
        store.persist_scale(source,source.stem)


def test_cloud_quota_pins_active_reads_verifies_remote_commit_and_restores_evicted_case(actual_case,tmp_path):
    original,example,_,_=actual_case
    memory=MemoryObjects();store=PrivateStateStore(transport=memory)
    service=CloggingScenarios(ROOT,original.pluvial,RiverContext(ROOT),cloud_state=store)
    service.directory=tmp_path/'bounded-cache'
    first=service.create(example['geometry'])
    second=service.create(example['geometry'],rainfall_mm=45)
    first_id,second_id=first['scenario_id'],second['scenario_id']
    originals={identity:{name:(service.path(identity)/name).read_bytes()
                        for name in ['result.json','runoff.tif','river_classes.tif']}
               for identity in [first_id,second_id]}
    sizes={identity:sum(len(value) for value in files.values()) for identity,files in originals.items()}
    limit=max(sizes.values())+1
    # Neither a running raster read nor a download may lose its files.
    with service.cache_lease(first_id):
        with service.cache_lease(second_id):
            store.cache_limit_bytes=limit
            with pytest.raises(CloudStateUnavailable,match='full or busy'):
                store.enforce_cache(service.directory)
            assert service.path(first_id).is_dir() and service.path(second_id).is_dir()
        # Only the now-unleased, remotely committed second cache may go.
        store.enforce_cache(service.directory)
        assert service.path(first_id).is_dir() and not service.path(second_id).exists()
    marker=f'scenarios/{first_id}/manifest.json'
    saved_marker=memory.values.pop(marker)
    with pytest.raises(CloudStateUnavailable,match='full or busy'):
        service.result(second_id)
    assert service.path(first_id).is_dir(), 'An unverified remote copy cannot justify deleting local files'
    memory.values[marker]=saved_marker
    # A fresh service has no in-memory durability/LRU knowledge. It checks R2,
    # evicts only verified disposable bytes and restores the requested case.
    restarted_store=PrivateStateStore(transport=memory,cache_limit_bytes=limit)
    restarted=CloggingScenarios(ROOT,original.pluvial,RiverContext(ROOT),cloud_state=restarted_store)
    restarted.directory=service.directory
    assert restarted.result(second_id)['statistics'] == second['statistics']
    assert not restarted.path(first_id).exists()
    assert restarted_store._directory_size(service.directory) <= limit
    assert restarted.result(first_id)['depth_statistics'] == first['depth_statistics']
    for name,data in originals[first_id].items():
        assert (restarted.path(first_id)/name).read_bytes() == data
    assert restarted_store._directory_size(service.directory) <= limit
    assert all(method in ('GET','PUT') for method,_ in memory.operations)
    assert not restarted_store.leases and not restarted_store.reservations


def test_cloud_download_holds_lease_through_range_send_and_releases_on_error(actual_case,tmp_path,monkeypatch):
    original,example,_,_=actual_case
    store=PrivateStateStore(transport=MemoryObjects())
    service=CloggingScenarios(ROOT,original.pluvial,RiverContext(ROOT),cloud_state=store)
    service.directory=tmp_path/'download-cache'
    result=service.create(example['geometry'])
    identity=result['scenario_id'];directory=service.path(identity)
    key=store._cache_key(directory)
    original_call=FileResponse.__call__
    async def inspected(response,scope,receive,send):
        assert store.leases.get(key,0)>0
        limit=store.cache_limit_bytes
        try:
            store.cache_limit_bytes=1
            with pytest.raises(CloudStateUnavailable,match='full or busy'):
                store.enforce_cache(service.directory)
            assert (directory/'runoff.tif').is_file()
        finally:
            store.cache_limit_bytes=limit
        return await original_call(response,scope,receive,send)
    monkeypatch.setattr(FileResponse,'__call__',inspected)
    app=FastAPI();app.include_router(create_clogging_router(service))
    with TestClient(app) as client:
        response=client.get(f'/api/clogging/scenarios/{identity}/download',headers={'Range':'bytes=0-255'})
        assert response.status_code==206 and len(response.content)==256
        assert not store.leases and not store.reservations
        async def interrupted(response,scope,receive,send):
            assert store.leases.get(key,0)>0
            raise OSError('simulated interrupted file send')
        monkeypatch.setattr(FileResponse,'__call__',interrupted)
        with pytest.raises(OSError,match='interrupted'):
            client.get(f'/api/clogging/scenarios/{identity}/download')
        assert not store.leases and not store.reservations
