"""Prepare a private, lossless runtime snapshot; never edit source datasets.

The snapshot is a Docker build input, not a public download or a Git artifact.
Use --check-only to validate and inventory inputs without writing the archive.
"""
import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SCHEMA = 'draincheck-runtime-data-v1'
MANIFEST_NAME = 'runtime-data-manifest.json'
NATIVE_NAME = 'data/native/sofia_dtm_2024_1m_gee.tif'
NATIVE_SHA256 = 'bc76434415d1ea6ee7dccb44d1dcaf35381914ff3129fb7398f38a9cc7e212a3'
EXCLUDED_DIRECTORIES = {
    ('data', 'cache', 'rendered_tiles'), ('data', 'cache', 'clogging'),
    ('data', 'reference', 'previous_whole_scales'),
}


def safe_name(name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(ord(character) < 32 for character in name)
            or path.is_absolute() or '..' in path.parts or str(path) != name
            or not path.parts or path.parts[0] != 'data'):
        raise ValueError('Unsafe runtime data path: ' + repr(name))
    return path


def excluded(name):
    relative = safe_name(name)
    return (any(relative.parts[:len(parts)] == parts for parts in EXCLUDED_DIRECTORIES)
            or any(part in ('__pycache__', '.pytest_cache', '.git') for part in relative.parts)
            or relative.name.endswith(('.private.json', '.pyc', '.pyo', '.part', '.tmp'))
            or '.pending.' in relative.name
            or (relative.parent.as_posix() == 'data/cache'
                and relative.name.startswith('local-') and relative.suffix == '.json'))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path):
    info = Path(path).stat()
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)


def collect_files(root, native_dtm=None):
    """Inventory regular files only; do not follow links, junctions or reparse points."""
    root = Path(root).resolve(strict=True)
    data = root / 'data'
    if not data.is_dir() or data.is_symlink():
        raise ValueError('A real restored data directory is required')
    result = {}
    for directory, dirs, files in os.walk(data, followlinks=False):
        parent = Path(directory)
        for name in list(dirs):
            child = parent / name
            relative = child.relative_to(root).as_posix()
            info = child.lstat()
            if child.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked data directories are not portable: ' + relative)
            if excluded(relative):
                dirs.remove(name)
        for name in files:
            child = parent / name
            relative = child.relative_to(root).as_posix()
            if excluded(relative):
                continue
            info = child.lstat()
            if (not stat.S_ISREG(info.st_mode) or child.is_symlink()
                    or getattr(info, 'st_file_attributes', 0) & 0x400):
                raise ValueError('Only regular data files may be packaged: ' + relative)
            result[relative] = child
    if native_dtm is not None:
        source = Path(native_dtm).resolve(strict=True)
        if not source.is_file() or source.is_symlink():
            raise ValueError('The corrected real native DTM is required')
        if NATIVE_NAME in result and result[NATIVE_NAME] != source:
            raise ValueError('Both an external and restored native DTM were supplied')
        result[NATIVE_NAME] = source
    if not result:
        raise ValueError('No real runtime data files were found')
    return dict(sorted(result.items()))


def create_manifest(files):
    entries = {}
    for name, path in sorted(files.items()):
        safe_name(name)
        before = file_identity(path)
        entries[name] = {'sha256': sha256_file(path), 'size': before[0]}
        if file_identity(path) != before:
            raise ValueError('Source changed while hashing: ' + name)
    return {'schema': SCHEMA, 'files': entries}


def manifest_bytes(manifest):
    return (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def validate_native(path, expected_sha256=None):
    import rasterio
    with rasterio.open(path) as source:
        if (source.crs is None or source.crs.to_epsg() != 7801
                or source.shape != (54343, 51722) or source.count != 1
                or source.dtypes != ('float32',) or source.nodata != -9999
                or list(source.transform)[:6] != [1, 0, 299392, 0, -1, 4753611]):
            raise ValueError('Native DTM is not the verified real 1 m Sofia raster')
    if expected_sha256 is not None and expected_sha256 != NATIVE_SHA256:
        raise ValueError('Native DTM checksum differs from the verified corrected original')


def write_snapshot(files, manifest, output_directory):
    """Install a new snapshot only after all bytes pass a second read verification."""
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / 'runtime-data.tar'
    manifest_path = output / MANIFEST_NAME
    receipt_path = output / 'runtime-data-info.json'
    if any(path.exists() for path in (archive_path, manifest_path, receipt_path)):
        raise FileExistsError('Snapshot already exists; use a new output directory to preserve it')
    encoded = manifest_bytes(manifest)
    descriptor, temporary_name = tempfile.mkstemp(prefix='runtime-data-', suffix='.pending.tar', dir=output)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, 'w', format=tarfile.PAX_FORMAT) as archive:
            header = tarfile.TarInfo(MANIFEST_NAME)
            header.size = len(encoded); header.mode = 0o444; header.mtime = 0
            archive.addfile(header, io.BytesIO(encoded))
            for name, path in sorted(files.items()):
                before = file_identity(path)
                expected = manifest['files'][name]
                if before[0] != expected['size'] or sha256_file(path) != expected['sha256']:
                    raise ValueError('Source changed before packaging: ' + name)
                info = archive.gettarinfo(str(path), arcname=name)
                if not info.isfile():
                    raise ValueError('Only regular files may be packaged: ' + name)
                # Decimal PAX time preserves ns when Linux restores Windows inputs.
                info.pax_headers['mtime'] = str(Path(path).stat().st_mtime_ns // 1_000_000_000) + '.' + str(Path(path).stat().st_mtime_ns % 1_000_000_000).zfill(9)
                info.uid = info.gid = 0; info.uname = info.gname = ''; info.mode = 0o444
                with Path(path).open('rb') as stream:
                    archive.addfile(info, stream)
                if file_identity(path) != before:
                    raise ValueError('Source changed while packaging: ' + name)
        # The restore path verifies every archived byte against the trusted manifest.
        if __package__:
            from .restore_cloudflare_data import inspect_archive
        else:
            from restore_cloudflare_data import inspect_archive
        inspect_archive(temporary, manifest, verify_payload=True)
        receipt = {'schema': 'draincheck-runtime-data-receipt-v1',
                   'files': len(files), 'data_bytes': sum(item['size'] for item in manifest['files'].values()),
                   'archive_bytes': temporary.stat().st_size,
                   'archive_sha256': sha256_file(temporary),
                   'manifest_sha256': hashlib.sha256(encoded).hexdigest()}
        # Preserve existing outputs: no replacement is permitted by this operation.
        temporary.rename(archive_path)
        with manifest_path.open('xb') as stream:
            stream.write(encoded)
        with receipt_path.open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2); stream.write('\n')
        return receipt
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--native-dtm', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    native = args.native_dtm or root.parent / 'sofia_dtm_2024_1m_gee.tif'
    files = collect_files(root, native)
    manifest = create_manifest(files)
    validate_native(native, manifest['files'][NATIVE_NAME]['sha256'])
    if args.check_only:
        result = {'check_only': True, 'files': len(files),
                  'data_bytes': sum(entry['size'] for entry in manifest['files'].values()),
                  'native_sha256': manifest['files'][NATIVE_NAME]['sha256']}
    else:
        result = write_snapshot(files, manifest, args.output or root / '.cloudflare-data')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
