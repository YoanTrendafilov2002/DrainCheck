"""Safely restore a private runtime snapshot against its trusted manifest.

No existing data directory or manifest is ever overwritten. All archive entries
are validated before extraction; all extracted payloads are hashed before activation.
"""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

SCHEMA = 'draincheck-runtime-data-v1'
MANIFEST_NAME = 'runtime-data-manifest.json'
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_FILES = 50000
MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
SHA256 = re.compile(r'[a-f0-9]{64}')


def safe_name(name, allow_manifest=False):
    if not isinstance(name, str):
        raise ValueError('Archive path must be a string')
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name
            or any(ord(character) < 32 for character in name)
            or path.is_absolute() or '..' in path.parts or str(path) != name
            or not path.parts
            or (path.parts[0] != 'data' and not (allow_manifest and name == MANIFEST_NAME))):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return path


def reject_duplicate_json(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate JSON manifest key')
        result[name] = value
    return result


def parse_manifest(encoded):
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError('Runtime manifest is too large')
    manifest = json.loads(encoded, object_pairs_hook=reject_duplicate_json)
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA:
        raise ValueError('Unsupported runtime manifest schema')
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('Runtime manifest file inventory is empty or too large')
    total = 0
    for name, entry in files.items():
        safe_name(name)
        if (not isinstance(entry, dict) or type(entry.get('size')) is not int
                or entry['size'] < 0 or not SHA256.fullmatch(str(entry.get('sha256', '')))):
            raise ValueError('Invalid runtime manifest entry')
        total += entry['size']
    if total > MAX_TOTAL_BYTES:
        raise ValueError('Runtime snapshot exceeds the configured maximum size')
    return manifest


def payload_sha256(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
        value.update(block)
    return value.hexdigest()


def inspect_archive(path, manifest, verify_payload=True):
    """Reject links, duplicates, unlisted entries, bad sizes and altered payloads."""
    expected = manifest['files']
    seen = set()
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            safe_name(member.name, allow_manifest=True)
            if not member.isfile() or member.issparse():
                raise ValueError('Only ordinary regular archive files are supported')
            if member.name in seen:
                raise ValueError('Duplicate archive entry: ' + member.name)
            seen.add(member.name)
            if len(seen) > len(expected) + 1:
                raise ValueError('Archive contains more files than the trusted manifest')
            if member.name == MANIFEST_NAME:
                if member.size > MAX_MANIFEST_BYTES:
                    raise ValueError('Archived manifest is too large')
                if parse_manifest(archive.extractfile(member).read()) != manifest:
                    raise ValueError('Archived and trusted manifests differ')
                continue
            entry = expected.get(member.name)
            if entry is None or member.size != entry['size']:
                raise ValueError('Unexpected archive file or size: ' + member.name)
            if verify_payload and payload_sha256(archive.extractfile(member)) != entry['sha256']:
                raise ValueError('Archived file checksum differs: ' + member.name)
    if seen != set(expected) | {MANIFEST_NAME}:
        raise ValueError('Archive is missing declared runtime files')


def restore_archive(archive_path, destination, manifest_path):
    archive_path = Path(archive_path).resolve(strict=True)
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = parse_manifest(manifest_path.read_bytes())
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target_data = destination / 'data'
    target_manifest = destination / MANIFEST_NAME
    if target_data.exists() or target_data.is_symlink() or target_manifest.exists() or target_manifest.is_symlink():
        raise FileExistsError('Refusing to overwrite existing runtime data or its manifest')
    archive_before = archive_path.stat()
    # Validate the complete name/type/size inventory before creating any payload.
    inspect_archive(archive_path, manifest, verify_payload=False)
    staging = Path(tempfile.mkdtemp(prefix='.draincheck-restore-', dir=destination))
    try:
        with tarfile.open(archive_path, 'r:') as archive:
            for member in archive:
                relative = safe_name(member.name, allow_manifest=True)
                target = staging.joinpath(*relative.parts)
                if not target.is_relative_to(staging):
                    raise ValueError('Archive target escapes its private staging directory')
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.extractfile(member) as source, target.open('xb') as output:
                    for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
                        output.write(block); digest.update(block)
                if member.name != MANIFEST_NAME:
                    entry = manifest['files'][member.name]
                    if target.stat().st_size != entry['size'] or digest.hexdigest() != entry['sha256']:
                        raise ValueError('Extracted runtime checksum differs: ' + member.name)
                try:
                    time_ns = int(Decimal(member.pax_headers.get('mtime', str(member.mtime))) * 1_000_000_000)
                    if not 0 <= time_ns <= 9_223_372_036_854_775_807:
                        raise ValueError('Runtime timestamp is outside the supported range')
                except (InvalidOperation, OverflowError):
                    raise ValueError('Invalid runtime timestamp') from None
                os.utime(target, ns=(time_ns, time_ns))
        actual = {path.relative_to(staging).as_posix() for path in staging.rglob('*') if path.is_file()}
        if actual != set(manifest['files']) | {MANIFEST_NAME}:
            raise ValueError('Extracted runtime file inventory differs')
        archive_after = archive_path.stat()
        if (archive_before.st_size, archive_before.st_mtime_ns, archive_before.st_ctime_ns) != (archive_after.st_size, archive_after.st_mtime_ns, archive_after.st_ctime_ns):
            raise ValueError('Archive changed during restoration')
        # Activation occurs only after the complete private staging tree is verified.
        (staging / 'data').rename(target_data)
        (staging / MANIFEST_NAME).rename(target_manifest)
        return {'schema': SCHEMA, 'files': len(manifest['files']),
                'data_bytes': sum(entry['size'] for entry in manifest['files'].values())}
    finally:
        shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='Trusted sidecar from snapshot preparation, not an unverified external archive')
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(restore_archive(args.archive, args.destination, args.manifest), sort_keys=True))


if __name__ == '__main__':
    main()
