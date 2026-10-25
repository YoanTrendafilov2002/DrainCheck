"""Private snapshot integrity tests. Small byte fixtures are never terrain inputs."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

import pytest

from scripts.prepare_cloudflare_data import (
    collect_files, create_manifest, manifest_bytes, NATIVE_NAME, NATIVE_SHA256,
    validate_native, write_snapshot,
)
from scripts.restore_cloudflare_data import (
    MANIFEST_NAME, parse_manifest, restore_archive,
)

ROOT = Path(__file__).resolve().parents[1]


def data_fixture(tmp_path):
    root = tmp_path / 'source'
    source = root / 'data/cache/test.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'real packaging fixture; not an elevation raster\x00\xff')
    os.utime(source, ns=(1750000000123456700, 1750000000123456700))
    files = collect_files(root)
    return root, source, files, create_manifest(files)


def archive_fixture(tmp_path, manifest, members):
    archive = tmp_path / 'test.tar'
    sidecar = tmp_path / MANIFEST_NAME
    sidecar.write_bytes(manifest_bytes(manifest))
    with tarfile.open(archive, 'w', format=tarfile.PAX_FORMAT) as stream:
        for name, content, kind in [(MANIFEST_NAME, manifest_bytes(manifest), tarfile.REGTYPE), *members]:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = '../outside'
            if kind == tarfile.REGTYPE:
                info.size = len(content)
                stream.addfile(info, io.BytesIO(content))
            else:
                stream.addfile(info)
    return archive, sidecar


def test_private_snapshot_roundtrip_preserves_bytes_ns_inventory_and_sources(tmp_path):
    root, source, files, manifest = data_fixture(tmp_path)
    before = source.stat()
    receipt = write_snapshot(files, manifest, tmp_path / 'private')
    restored = tmp_path / 'restored'
    result = restore_archive(tmp_path / 'private/runtime-data.tar', restored,
                             tmp_path / 'private/runtime-data-manifest.json')
    target = restored / 'data/cache/test.bin'
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.stat().st_size == before.st_size
    assert result['files'] == receipt['files'] == 1
    assert receipt['data_bytes'] == before.st_size
    assert json.loads((restored / MANIFEST_NAME).read_text()) == manifest
    assert {path.relative_to(restored).as_posix() for path in restored.rglob('*') if path.is_file()} == {MANIFEST_NAME, 'data/cache/test.bin'}


def test_snapshot_excludes_only_disposable_private_and_archival_backups(tmp_path):
    root, source, files, manifest = data_fixture(tmp_path)
    excluded = ['data/cache/rendered_tiles/a.tile', 'data/cache/clogging/id/runoff.tif',
                'data/cache/local-0123456789abcdef.json',
                'data/reference/source.receipt.private.json',
                'data/reference/previous_whole_scales/old.json', 'data/cache/job.pending.123']
    included = ['data/reference/agkk_buildings/batch_001.json.gz',
                'data/reference/historical_floods/report.pdf',
                'data/derived/full_cadastral.geojson', 'data/derived/screen.csv',
                'data/rainfall/real-cog.tif', 'data/reference/source_metadata_manifest.json']
    for name in excluded + included:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'preserve original fixture')
    result = collect_files(root)
    assert all(name not in result for name in excluded)
    assert all(name in result for name in included)
    assert all((root / name).is_file() for name in excluded + included)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'data/../escape',
                                  'C:/escape', 'data\\windows', 'data//repeat', 'data/./dot'])
def test_unsafe_archive_paths_fail_before_activation(tmp_path, name):
    _, _, _, manifest = data_fixture(tmp_path)
    archive, sidecar = archive_fixture(tmp_path, manifest, [(name, b'escape', tarfile.REGTYPE)])
    destination = tmp_path / 'destination'
    with pytest.raises(ValueError):
        restore_archive(archive, destination, sidecar)
    assert not (destination / 'data').exists()
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE,
                                 tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_links_and_special_archive_members_are_rejected(tmp_path, kind):
    _, _, _, manifest = data_fixture(tmp_path)
    archive, sidecar = archive_fixture(tmp_path, manifest, [('data/cache/test.bin', b'', kind)])
    destination = tmp_path / 'destination'
    with pytest.raises(ValueError, match='ordinary regular'):
        restore_archive(archive, destination, sidecar)
    assert not (destination / 'data').exists()


def test_corrupt_payload_of_same_size_is_not_activated(tmp_path):
    _, source, _, manifest = data_fixture(tmp_path)
    archive, sidecar = archive_fixture(tmp_path, manifest,
        [('data/cache/test.bin', b'x' * source.stat().st_size, tarfile.REGTYPE)])
    destination = tmp_path / 'destination'
    with pytest.raises(ValueError, match='checksum'):
        restore_archive(archive, destination, sidecar)
    assert not (destination / 'data').exists()
    assert not list(destination.glob('.draincheck-restore-*'))


def test_duplicate_files_and_missing_files_are_rejected(tmp_path):
    _, source, _, manifest = data_fixture(tmp_path)
    member = ('data/cache/test.bin', source.read_bytes(), tarfile.REGTYPE)
    archive, sidecar = archive_fixture(tmp_path, manifest, [member, member])
    with pytest.raises(ValueError, match='Duplicate'):
        restore_archive(archive, tmp_path / 'duplicate', sidecar)
    archive, sidecar = archive_fixture(tmp_path, manifest, [])
    with pytest.raises(ValueError, match='missing'):
        restore_archive(archive, tmp_path / 'missing', sidecar)


def test_trusted_manifest_cannot_be_replaced_by_archive(tmp_path):
    _, source, _, manifest = data_fixture(tmp_path)
    archive, sidecar = archive_fixture(tmp_path, manifest,
        [('data/cache/test.bin', source.read_bytes(), tarfile.REGTYPE)])
    changed = json.loads(sidecar.read_text())
    changed['files']['data/cache/test.bin']['sha256'] = '0' * 64
    sidecar.write_bytes(manifest_bytes(changed))
    with pytest.raises(ValueError, match='manifests differ'):
        restore_archive(archive, tmp_path / 'destination', sidecar)


def test_duplicate_manifest_keys_and_bad_size_are_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        parse_manifest(b'{"schema":"draincheck-runtime-data-v1","files":{},"files":{}}')
    with pytest.raises(ValueError, match='Invalid'):
        parse_manifest(json.dumps({'schema': 'draincheck-runtime-data-v1',
            'files': {'data/a': {'sha256': '0' * 64, 'size': True}}}).encode())


def test_existing_original_data_and_prior_snapshot_are_never_overwritten(tmp_path):
    root, source, files, manifest = data_fixture(tmp_path)
    output = tmp_path / 'private'
    write_snapshot(files, manifest, output)
    archive_before = (output / 'runtime-data.tar').read_bytes()
    with pytest.raises(FileExistsError):
        write_snapshot(files, manifest, output)
    assert (output / 'runtime-data.tar').read_bytes() == archive_before
    with pytest.raises(FileExistsError):
        restore_archive(output / 'runtime-data.tar', root, output / MANIFEST_NAME)
    assert source.read_bytes() == b'real packaging fixture; not an elevation raster\x00\xff'


def test_real_runtime_inventory_includes_full_data_and_native_grid():
    """Inspect real datasets, without copying or reconstructing any original."""
    native = ROOT.parent / 'sofia_dtm_2024_1m_gee.tif'
    if not native.is_file() or not (ROOT / 'data/cache/pluvial_5m.tif').is_file():
        pytest.skip('Requires the real locally restored Sofia data snapshot')
    files = collect_files(ROOT, native)
    required = {NATIVE_NAME, 'data/cache/spatial.sqlite', 'data/cache/cadastral_buildings.sqlite',
                'data/cache/pluvial_5m.tif', 'data/cache/green_absorption_5m.tif',
                'data/derived/cadastral_buildings.geojson', 'data/derived/pluvial_land_screening_5m.tif',
                'data/derived/infrastructure_terrain_screening.csv',
                'data/derived/sewer_route_terrain_screening.csv',
                'data/reference/flood_assessment/assessment_zones.geojson'}
    assert required <= files.keys()
    assert len([name for name in files if name.startswith('data/reference/agkk_buildings/batches/') and name.endswith('.geojson.gz')]) == 335
    assert len([name for name in files if name.startswith('data/reference/agkk_buildings/batches/') and name.endswith('.receipt.json')]) == 335
    assert any(name.startswith('data/reference/historical_floods/') and name.endswith('.pdf') for name in files)
    assert all(not name.endswith('.private.json') for name in files)
    assert not any(name.startswith(('data/cache/clogging/', 'data/cache/rendered_tiles/')) for name in files)
    validate_native(native)
    actual = create_manifest({name: files[name] for name in [
        'data/cache/revision.txt', 'data/cache/whole_scale.json', 'data/cache/pluvial_meta.json']})
    for name, entry in actual['files'].items():
        assert entry['sha256'] == hashlib.sha256(files[name].read_bytes()).hexdigest()
