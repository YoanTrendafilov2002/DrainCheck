"""Restore byte-identical original vector input from a verified local gzip.

Standard library only; no login, network request or inferred geometry. Existing
source files are never overwritten. The target is a fixed application-relative
path, not an arbitrary destination supplied by archive or manifest content.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {
    'legacy_green_areas': (
        'data/source_bundles/green_areas_original.geojson.gz',
        'data/raw/green_areas_26_sofp_20200518_a00bddf3-4189-4e65-8216-a8575de25e8c.geojson'),
}


def checksum(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def matches(path, size, expected):
    return path.is_file() and path.stat().st_size == size and checksum(path) == expected


def restore(root=ROOT):
    root = Path(root).resolve()
    manifest_path = root / 'data/source_bundles/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('bundles'), list):
        raise ValueError('Unsupported source-bundle manifest')
    results, seen = [], set()
    for entry in manifest['bundles']:
        identity = entry.get('id')
        if identity not in SUPPORTED or identity in seen:
            raise ValueError('Unknown or duplicate source bundle')
        seen.add(identity)
        bundle_relative, target_relative = SUPPORTED[identity]
        if (entry.get('bundle_file') != bundle_relative or entry.get('source_file') != target_relative or
                entry.get('compression') != 'gzip' or entry.get('gzip_mtime') != 0):
            raise ValueError('Source-bundle paths or encoding differ from the fixed supported source')
        for key in ['bundle_sha256', 'source_sha256']:
            if not isinstance(entry.get(key), str) or not re.fullmatch('[0-9a-f]{64}', entry[key]):
                raise ValueError('Source-bundle SHA256 is missing or malformed')
        for key in ['bundle_size_bytes', 'source_size_bytes']:
            if type(entry.get(key)) is not int or entry[key] <= 0:
                raise ValueError('Source-bundle size is missing or invalid')
        bundle = (root / bundle_relative).resolve()
        target = (root / target_relative).resolve()
        raw_directory = (root / 'data/raw').resolve()
        bundle_directory = (root / 'data/source_bundles').resolve()
        if (not raw_directory.is_relative_to(root) or not bundle_directory.is_relative_to(root) or
                not bundle.is_relative_to(bundle_directory) or target.parent != raw_directory or
                not target.is_relative_to(root)):
            raise ValueError('Source restoration must remain within this application data directory')
        if not matches(bundle, entry['bundle_size_bytes'], entry['bundle_sha256']):
            raise ValueError('Compressed source bundle size or SHA256 differs from its receipt')
        with bundle.open('rb') as source:
            header = source.read(10)
        if header[:3] != b'\x1f\x8b\x08' or header[4:8] != b'\0\0\0\0':
            raise ValueError('Source bundle is not the inspected deterministic gzip')
        if target.exists():
            if not matches(target, entry['source_size_bytes'], entry['source_sha256']):
                raise ValueError('Existing original differs from its receipt; it was not overwritten: ' + target_relative)
            results.append({'id': identity, 'status': 'already-present', 'file': target_relative,
                            'source_sha256': entry['source_sha256'], 'original_untouched': True})
            continue
        raw_directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='wb', prefix='.restore-green-', suffix='.tmp',
                                             dir=raw_directory, delete=False) as out:
                temporary = Path(out.name)
                h, count = hashlib.sha256(), 0
                with gzip.open(bundle, 'rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        count += len(block)
                        if count > entry['source_size_bytes']:
                            raise ValueError('Decoded bundle exceeds the expected original size')
                        h.update(block)
                        out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if count != entry['source_size_bytes'] or h.hexdigest() != entry['source_sha256']:
                raise ValueError('Decoded original size or SHA256 differs from its receipt; nothing installed')
            # A validated temporary and the final file are on the same volume.
            # link() installs atomically and refuses an already existing name;
            # unlike replace()/POSIX rename(), it cannot overwrite an original.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if not matches(target, entry['source_size_bytes'], entry['source_sha256']):
                    raise ValueError('An existing original appeared during restoration; it was not overwritten')
                status = 'already-present'
            else:
                status = 'restored'
            results.append({'id': identity, 'status': status, 'file': target_relative,
                            'source_size_bytes': count, 'source_sha256': h.hexdigest(),
                            'compressed_sha256': entry['bundle_sha256'], 'gzip_crc_checked': True,
                            'atomic_no_overwrite_install': True})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    if seen != set(SUPPORTED):
        raise ValueError('Source-bundle manifest is missing a required original input')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps({'results': restore(args.app_root)}, indent=2))
