"""Verified portable data identity and private Cloudflare user-state storage.

Original datasets are never uploaded here. Only user-created colour scales and
bounded scenario derivatives cross the container's private outbound binding.
An object-store failure is an API failure, not a silently ephemeral success.
"""
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from .tile_cache import file_signature

DATA_SCHEMA = 'draincheck-runtime-data-v1'
STATE_SCHEMA = 'draincheck-private-scenario-v1'
SCALE_SCHEMA = 'draincheck-private-scale-v1'
PRIVATE_ORIGIN = 'http://draincheck-state.internal'
MAX_OBJECT_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SCENARIO_BYTES = 3 * MAX_OBJECT_BYTES
DEFAULT_CACHE_BYTES = 512 * 1024 * 1024
SCENARIO_FILES = ('result.json', 'runoff.tif', 'river_classes.tif')
SCENARIO_ID = re.compile(r'[a-f0-9]{32}')
SCALE_ID = re.compile(r'local-[a-f0-9]{16}')
SHA256 = re.compile(r'[a-f0-9]{64}')
OBJECT_KEY = re.compile(r'(?:local-scales/local-[a-f0-9]{16}\.json|scenarios/[a-f0-9]{32}/(?:manifest\.json|result\.json|runoff\.tif|river_classes\.tif))')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def json_bytes(document):
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class CloudStateUnavailable(RuntimeError):
    """Safe public message; never include private HTTP responses or credentials."""


class VerifiedDataSnapshot:
    """Hash every declared source at startup; never identify it by inode/mtime.

    Header and provenance checks in the actual raster adapters still apply.
    Container relocation changes neither this identity nor scenario IDs. Local
    mode, with no manifest environment variable, retains its strict stat keys.
    """
    def __init__(self, root, manifest_path):
        self.root = Path(root).resolve(strict=True)
        self.path = Path(manifest_path)
        if not self.path.is_absolute():
            self.path = self.root / self.path
        self.path = self.path.resolve(strict=True)
        if not self.path.is_relative_to(self.root):
            raise ValueError('Runtime data manifest must be inside the application root')
        self.manifest_signature = file_signature(self.path)
        manifest = json.loads(self.path.read_text(encoding='utf-8'))
        files = manifest.get('files')
        if manifest.get('schema') != DATA_SCHEMA or not isinstance(files, dict) or not files:
            raise ValueError('Invalid runtime data manifest')
        self.files = {}
        self.signatures = {}
        for name, entry in sorted(files.items()):
            relative = PurePosixPath(name)
            if (not isinstance(name, str) or '\\' in name or relative.is_absolute()
                    or '..' in relative.parts or str(relative) != name or not relative.parts
                    or not isinstance(entry, dict) or not SHA256.fullmatch(str(entry.get('sha256', '')))
                    or type(entry.get('size')) is not int or entry['size'] < 0):
                raise ValueError('Unsafe or incomplete runtime data manifest entry')
            path = (self.root / name).resolve(strict=True)
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('Runtime data file escapes the application root')
            before = file_signature(path)
            if before[1] != entry['size'] or file_digest(path) != entry['sha256']:
                raise ValueError('Runtime data differs from the verified manifest: ' + name)
            if file_signature(path) != before:
                raise ValueError('Runtime data changed while verifying: ' + name)
            self.files[name] = {'size': entry['size'], 'sha256': entry['sha256']}
            self.signatures[name] = before
        if file_signature(self.path) != self.manifest_signature:
            raise ValueError('Runtime data manifest changed while verifying')
        self.identity = digest(json_bytes({'schema': DATA_SCHEMA, 'files': self.files}))

    @classmethod
    def from_env(cls, root):
        path = os.environ.get('DRAINCHECK_DATA_MANIFEST')
        return cls(root, path) if path else None

    def state(self, paths):
        if file_signature(self.path) != self.manifest_signature:
            raise RuntimeError('Verified runtime data manifest changed; restart against a verified snapshot')
        entries = []
        for value in paths:
            path = Path(value).resolve(strict=True)
            if not path.is_relative_to(self.root):
                raise RuntimeError('Scenario source is outside the verified runtime snapshot')
            name = path.relative_to(self.root).as_posix()
            if name not in self.files or file_signature(path) != self.signatures[name]:
                raise RuntimeError('Scenario source changed or is absent from the verified runtime snapshot')
            entries.append({'path': name, **self.files[name]})
        return {'identity_method': 'verified-sha256-content-v1',
                'dataset_snapshot_sha256': self.identity, 'files': entries}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class PrivateStateStore:
    """Raw-object protocol implemented only by the private Worker binding."""
    def __init__(self, origin=PRIVATE_ORIGIN, transport=None, cache_limit_bytes=DEFAULT_CACHE_BYTES):
        if origin.rstrip('/') != PRIVATE_ORIGIN:
            raise ValueError('User state requires the configured private Cloudflare binding')
        self.origin = PRIVATE_ORIGIN
        self.transport = transport or self._http
        self.lock = threading.RLock()
        self.persisted = {}
        if type(cache_limit_bytes) is not int or cache_limit_bytes <= 0:
            raise ValueError('Private scenario cache quota must be positive')
        self.cache_limit_bytes = cache_limit_bytes
        self.leases = {}
        self.reservations = {}
        self.last_used = {}

    @staticmethod
    def _cache_key(directory):
        directory = Path(directory)
        if not SCENARIO_ID.fullmatch(directory.name):
            raise CloudStateUnavailable('Invalid private scenario cache directory')
        root = directory.parent.resolve()
        if directory.is_symlink() or directory.resolve().parent != root:
            raise CloudStateUnavailable('Private scenario cache path is unsafe')
        return root, directory.name

    @staticmethod
    def _directory_size(directory):
        total = 0
        if not directory.exists():
            return 0
        if directory.is_symlink():
            raise CloudStateUnavailable('Private scenario cache contains an unsafe link')
        for current, directories, files in os.walk(directory, followlinks=False):
            for name in directories + files:
                path = Path(current)/name
                if path.is_symlink():
                    raise CloudStateUnavailable('Private scenario cache contains an unsafe link')
            for name in files:
                total += (Path(current)/name).stat().st_size
        return total

    def _cache_usage(self, root):
        actual = self._directory_size(root)
        # Pending creations reserve a worst-case bundle before any disk write.
        # Committed bytes replace their reservation, rather than double count.
        reserved = sum(max(0, size-self._directory_size(root/identity))
                       for (folder,identity),size in self.reservations.items() if folder == root)
        return actual+reserved

    def _verified_private_copy(self, directory, identity):
        """Check the commit marker AND all remote bytes before deleting a copy."""
        if (not directory.is_dir() or directory.is_symlink()
                or {path.name for path in directory.iterdir()} != set(SCENARIO_FILES)
                or any(not (directory/name).is_file() or (directory/name).is_symlink() for name in SCENARIO_FILES)):
            return False
        marker = self.object('GET', f'scenarios/{identity}/manifest.json')
        if marker is None:
            return False
        manifest = self._document(marker)
        files = manifest.get('files')
        if (manifest.get('schema') != STATE_SCHEMA or manifest.get('scenario_id') != identity
                or not isinstance(files, dict) or set(files) != set(SCENARIO_FILES)):
            return False
        for name in SCENARIO_FILES:
            path = directory/name
            entry = files[name]
            if (not isinstance(entry, dict) or type(entry.get('size')) is not int
                    or not 0 <= entry['size'] <= MAX_OBJECT_BYTES
                    or not SHA256.fullmatch(str(entry.get('sha256', '')))
                    or path.stat().st_size != entry['size'] or file_digest(path) != entry['sha256']):
                return False
            remote = self.object('GET', f'scenarios/{identity}/{name}')
            if remote is None or len(remote) != entry['size'] or digest(remote) != entry['sha256']:
                return False
        return True

    def _make_room(self, root, protected=()):
        if self._cache_usage(root) <= self.cache_limit_bytes:
            return
        candidates = []
        for directory in root.iterdir() if root.exists() else []:
            identity = directory.name
            key = (root,identity)
            if (SCENARIO_ID.fullmatch(identity) and directory.is_dir()
                    and identity not in protected and not self.leases.get(key)
                    and not self.reservations.get(key)):
                candidates.append((self.last_used.get(key,directory.stat().st_mtime),directory))
        for _,directory in sorted(candidates,key=lambda item:item[0]):
            identity = directory.name
            key = self._cache_key(directory)
            if not self._verified_private_copy(directory,identity):
                continue
            # Only three explicitly named derivative files may be removed.
            # No recursive delete, unknown files, sources or private R2 objects.
            for name in SCENARIO_FILES:
                (directory/name).unlink()
            directory.rmdir()
            self.persisted.pop(identity,None)
            self.last_used.pop(key,None)
            if self._cache_usage(root) <= self.cache_limit_bytes:
                return
        raise CloudStateUnavailable('Private scenario cache is full or busy; wait for active requests and retry')

    def enforce_cache(self, root):
        with self.lock:
            self._make_room(Path(root).resolve())

    @contextmanager
    def scenario_lease(self, directory, reserve_bytes=0):
        """Pin files through reads/downloads; admit writes within a fixed quota."""
        directory = Path(directory)
        key = self._cache_key(directory)
        root,identity = key
        with self.lock:
            self.leases[key] = self.leases.get(key,0)+1
            previous = self.reservations.get(key,0)
            if reserve_bytes and not (directory/'result.json').is_file():
                self.reservations[key] = max(previous,reserve_bytes)
            try:
                self._make_room(root,protected=(identity,))
                self.last_used[key] = time.time()
            except BaseException:
                self.leases[key] -= 1
                if not self.leases[key]:
                    self.leases.pop(key,None)
                if previous:
                    self.reservations[key] = previous
                else:
                    self.reservations.pop(key,None)
                raise
        try:
            yield
        finally:
            with self.lock:
                self.leases[key] -= 1
                if not self.leases[key]:
                    self.leases.pop(key,None)
                    self.reservations.pop(key,None)
                if (directory/'result.json').is_file():
                    self.last_used[key] = time.time()
                else:
                    self.last_used.pop(key,None)

    def _cache_committed(self, directory, identity):
        key = self._cache_key(directory)
        self.reservations.pop(key,None)
        self.last_used[key] = time.time()
        self._make_room(key[0],protected=(identity,))

    @classmethod
    def from_env(cls):
        origin = os.environ.get('DRAINCHECK_STATE_URL')
        return cls(origin) if origin else None

    def _http(self, method, key, data=None):
        headers = {'Accept': 'application/octet-stream'}
        if data is not None:
            headers.update({'Content-Type': 'application/octet-stream', 'Content-Length': str(len(data))})
        request = urllib.request.Request(self.origin + '/objects/' + key,
                                         data=data, headers=headers, method=method)
        try:
            with urllib.request.build_opener(_NoRedirect).open(request, timeout=45) as response:
                length = response.headers.get('Content-Length')
                if length is not None and int(length) > MAX_OBJECT_BYTES:
                    raise CloudStateUnavailable('Private saved state exceeds its supported size')
                body = response.read(MAX_OBJECT_BYTES + 1)
                if len(body) > MAX_OBJECT_BYTES:
                    raise CloudStateUnavailable('Private saved state exceeds its supported size')
                return body
        except urllib.error.HTTPError as error:
            if method == 'GET' and error.code == 404:
                return None
            raise CloudStateUnavailable('Private state storage is unavailable; retry the request') from None
        except (OSError, ValueError, urllib.error.URLError):
            raise CloudStateUnavailable('Private state storage is unavailable; retry the request') from None

    def object(self, method, key, data=None):
        if method not in ('GET', 'PUT') or not OBJECT_KEY.fullmatch(key):
            raise CloudStateUnavailable('Unsupported private state object')
        if data is not None and (not isinstance(data, bytes) or len(data) > MAX_OBJECT_BYTES):
            raise CloudStateUnavailable('Private saved state exceeds its supported size')
        try:
            result = self.transport(method, key, data)
            if result is not None and (not isinstance(result, bytes) or len(result) > MAX_OBJECT_BYTES):
                raise CloudStateUnavailable('Private saved state is invalid or oversized')
            return result
        except CloudStateUnavailable:
            raise
        except Exception:
            raise CloudStateUnavailable('Private state storage is unavailable; retry the request') from None

    @staticmethod
    def _scenario_id(identity):
        if not isinstance(identity, str) or not SCENARIO_ID.fullmatch(identity):
            raise KeyError('Unknown scenario ID')

    @staticmethod
    def _document(data, limit=MAX_JSON_BYTES):
        if not isinstance(data, bytes) or len(data) > limit:
            raise CloudStateUnavailable('Private saved state receipt is invalid')
        try:
            result = json.loads(data.decode('utf-8'))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (UnicodeError, ValueError):
            raise CloudStateUnavailable('Private saved state receipt is invalid') from None

    def persist_scenario(self, directory, identity):
        self._scenario_id(identity)
        directory = Path(directory)
        with self.lock:
            signatures = tuple(file_signature(directory / name) for name in SCENARIO_FILES)
            if self.persisted.get(identity) == signatures:
                self._cache_committed(directory,identity)
                return
            files = {}
            payloads = {}
            for name in SCENARIO_FILES:
                path = directory / name
                if path.stat().st_size > MAX_OBJECT_BYTES:
                    raise CloudStateUnavailable('Scenario is too large for durable private storage')
                data = path.read_bytes()
                files[name] = {'size': len(data), 'sha256': digest(data)}
                payloads[name] = data
            result = self._document(payloads['result.json'], limit=MAX_OBJECT_BYTES)
            if (result.get('scenario_id') != identity or result.get('raster_sha256') != files['runoff.tif']['sha256']
                    or result.get('river_mask_sha256') != files['river_classes.tif']['sha256']):
                raise CloudStateUnavailable('Scenario files disagree with their immutable receipt')
            for name, data in payloads.items():
                self.object('PUT', f'scenarios/{identity}/{name}', data)
            manifest = {'schema': STATE_SCHEMA, 'scenario_id': identity, 'files': files}
            # The manifest is the commit marker. Partial uploads are never read.
            self.object('PUT', f'scenarios/{identity}/manifest.json', json_bytes(manifest))
            if signatures != tuple(file_signature(directory / name) for name in SCENARIO_FILES):
                raise CloudStateUnavailable('Scenario changed during private persistence')
            if len(self.persisted) >= 256:
                self.persisted.pop(next(iter(self.persisted)))
            self.persisted[identity] = signatures
            self._cache_committed(directory,identity)

    def restore_scenario(self, directory, identity):
        self._scenario_id(identity)
        directory = Path(directory)
        with self.lock:
            if (directory / 'result.json').is_file():
                return True
            marker = self.object('GET', f'scenarios/{identity}/manifest.json')
            if marker is None:
                return False
            manifest = self._document(marker)
            entries = manifest.get('files')
            if (manifest.get('schema') != STATE_SCHEMA or manifest.get('scenario_id') != identity
                    or not isinstance(entries, dict) or set(entries) != set(SCENARIO_FILES)):
                raise CloudStateUnavailable('Private scenario manifest is invalid')
            for entry in entries.values():
                if (not isinstance(entry, dict) or type(entry.get('size')) is not int
                        or not 0 <= entry['size'] <= MAX_OBJECT_BYTES
                        or not SHA256.fullmatch(str(entry.get('sha256', '')))):
                    raise CloudStateUnavailable('Private scenario manifest contains an invalid file')
            key=self._cache_key(directory)
            previous=self.reservations.get(key,0)
            self.reservations[key]=max(previous,sum(entry['size'] for entry in entries.values()))
            try:
                self._make_room(key[0],protected=(identity,))
                directory.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='restore-', dir=directory.parent) as scratch:
                    temporary = Path(scratch) / identity
                    temporary.mkdir()
                    for name in SCENARIO_FILES:
                        entry = entries[name]
                        data = self.object('GET', f'scenarios/{identity}/{name}')
                        if data is None or len(data) != entry['size'] or digest(data) != entry['sha256']:
                            raise CloudStateUnavailable('Private saved scenario is incomplete or fails checksum verification')
                        (temporary / name).write_bytes(data)
                    result = self._document((temporary / 'result.json').read_bytes(), limit=MAX_OBJECT_BYTES)
                    if (result.get('scenario_id') != identity
                            or result.get('raster_sha256') != entries['runoff.tif']['sha256']
                            or result.get('river_mask_sha256') != entries['river_classes.tif']['sha256']):
                        raise CloudStateUnavailable('Private scenario receipt does not match its raster files')
                    if directory.exists():
                        raise CloudStateUnavailable('Local scenario cache is incomplete; refusing a partial overwrite')
                    temporary.rename(directory)
                self.persisted[identity] = tuple(file_signature(directory / name) for name in SCENARIO_FILES)
                self._cache_committed(directory,identity)
                return True
            except BaseException:
                if previous:
                    self.reservations[key]=previous
                else:
                    self.reservations.pop(key,None)
                raise

    @staticmethod
    def _validate_scale(data, identity):
        document = PrivateStateStore._document(data)
        try:
            bounds = document['bbox']
            quantiles = document['quantiles']
            heights, levels = document['heights'], document['levels']
            key = digest(json.dumps({'bbox': [round(v, 6) for v in bounds],
                                     'revision': document['dataset_revision'],
                                     'scale': 10, 'method': 'hybrid-continuous-v2'}).encode())[:16]
            if (document['id'] != identity or identity != 'local-' + key
                    or document['status'] != 'ok' or document['scope'] != 'locked-local-view'
                    or len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
                    or not (-180 <= bounds[0] < bounds[2] <= 180 and -85 <= bounds[1] < bounds[3] <= 85)
                    or len(quantiles) != 201 or not all(math.isfinite(v) for v in quantiles)
                    or any(a > b for a,b in zip(quantiles, quantiles[1:]))
                    or len(heights) < 2 or len(heights) != len(levels)
                    or not all(math.isfinite(v) for v in heights + levels)
                    or any(a >= b for a,b in zip(heights, heights[1:]))
                    or any(a > b for a,b in zip(levels, levels[1:]))
                    or levels[0] != 0 or levels[-1] != 1):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            raise CloudStateUnavailable('Private saved local colour scale is invalid') from None
        return document

    def persist_scale(self, path, identity):
        if not SCALE_ID.fullmatch(identity):
            raise CloudStateUnavailable('Invalid local colour scale ID')
        data = Path(path).read_bytes()
        self._validate_scale(data, identity)
        envelope = json_bytes({'schema': SCALE_SCHEMA, 'sha256': digest(data), 'payload': data.decode('utf-8')})
        self.object('PUT', f'local-scales/{identity}.json', envelope)

    def restore_scale(self, path, identity):
        if not SCALE_ID.fullmatch(identity):
            return False
        with self.lock:
            path = Path(path)
            if path.is_file():
                return True
            data = self.object('GET', f'local-scales/{identity}.json')
            if data is None:
                return False
            envelope = self._document(data)
            payload = envelope.get('payload')
            if envelope.get('schema') != SCALE_SCHEMA or not isinstance(payload, str):
                raise CloudStateUnavailable('Private saved colour scale envelope is invalid')
            payload = payload.encode('utf-8')
            if digest(payload) != envelope.get('sha256'):
                raise CloudStateUnavailable('Private saved colour scale fails checksum verification')
            self._validate_scale(payload, identity)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_bytes(payload)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            return True

    def install_terrain(self, terrain):
        """Keep the native terrain adapter intact; wrap only saved user scales."""
        original_scale, original_local = terrain.scale, terrain.local_scale
        def scale(identity):
            if isinstance(identity, str) and SCALE_ID.fullmatch(identity):
                self.restore_scale(terrain.cache / (identity + '.json'), identity)
            return original_scale(identity)
        def local_scale(bounds, revision):
            result = original_local(bounds, revision)
            if result.get('status') == 'ok':
                self.persist_scale(terrain.cache / (result['id'] + '.json'), result['id'])
            return result
        terrain.scale, terrain.local_scale = scale, local_scale
        return terrain
