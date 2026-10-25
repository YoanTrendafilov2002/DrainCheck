import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stateRequest, STATE_PREFIX, MAX_OBJECT_BYTES } from '../src/state-store.mjs';

const origin = 'http://draincheck-state.internal';
const id = 'a'.repeat(32);

function memoryBucket() {
  const objects = new Map();
  const access = [];
  function object(key, body = true) {
    const stored = objects.get(key);
    if (!stored) return null;
    return {
      size: stored.bytes.length, etag: 'test-etag', httpEtag: '"test-etag"',
      writeHttpMetadata(headers) { headers.set('Content-Type', stored.contentType); },
      ...(body ? { body: new Response(stored.bytes).body } : {}),
    };
  }
  return {
    objects, access,
    async put(key, body, options) {
      access.push(['put', key]);
      objects.set(key, { bytes: new Uint8Array(await new Response(body).arrayBuffer()), contentType: options.httpMetadata.contentType });
      return object(key, false);
    },
    async get(key) { access.push(['get', key]); return object(key); },
    async head(key) { access.push(['head', key]); return object(key, false); },
    async delete(key) { access.push(['delete', key]); objects.delete(key); },
  };
}

test('private scenario and scale objects roundtrip with exact bytes and scoped keys', async () => {
  const bucket = memoryBucket();
  for (const key of [`scenarios/${id}/manifest.json`, `scenarios/${id}/result.json`, `scenarios/${id}/runoff.tif`, `scenarios/${id}/river_classes.tif`, 'local-scales/local-0123456789abcdef.json', 'manifest.json']) {
    const bytes = new Uint8Array([0, 123, 255, 10, 99]);
    const write = await stateRequest(new Request(`${origin}/objects/${key}`, {
      method: 'PUT', body: bytes, headers: { 'Content-Length': String(bytes.length), 'Content-Type': 'application/octet-stream' },
    }), bucket);
    assert.equal(write.status, 201);
    assert.equal(write.headers.get('ETag'), '"test-etag"');
    assert.ok(bucket.objects.has(STATE_PREFIX + key));
    const read = await stateRequest(new Request(`${origin}/objects/${key}`), bucket);
    assert.deepEqual([...new Uint8Array(await read.arrayBuffer())], [...bytes]);
    assert.equal(read.headers.get('Content-Length'), '5');
    assert.equal(read.headers.get('Cache-Control'), 'private, no-store');
    const head = await stateRequest(new Request(`${origin}/objects/${key}`, { method: 'HEAD' }), bucket);
    assert.equal(head.status, 200);
    assert.equal(await head.text(), '');
    assert.equal(head.headers.get('Content-Length'), '5');
    const conditional = await stateRequest(new Request(`${origin}/objects/${key}`, { headers: { 'If-None-Match': '"test-etag"' } }), bucket);
    assert.equal(conditional.status, 304);
    assert.equal(conditional.headers.has('Content-Length'), false);
    assert.equal((await stateRequest(new Request(`${origin}/objects/${key}`, { method: 'DELETE' }), bucket)).status, 204);
    assert.equal((await stateRequest(new Request(`${origin}/objects/${key}`), bucket)).status, 404);
  }
});

test('untrusted host, paths, traversal, source datasets, listing and methods cannot access R2', async () => {
  const bucket = memoryBucket();
  for (const url of [
    `https://draincheck.example/objects/scenarios/${id}/result.json`,
    `${origin}/objects/scenarios/${id}/secrets.json`,
    `${origin}/objects/scenarios/${id}/../../data/cache/spatial.sqlite`,
    `${origin}/objects/scenarios/${id}/%2e%2e%2fsecret`,
    `${origin}/objects/local-scales/local-123.json`,
    `${origin}/objects/data/external/dtm.tif`,
    `${origin}/objects/manifest.json?arbitrary=1`,
    `${origin}/list?prefix=scenarios/`,
  ]) assert.equal((await stateRequest(new Request(url), bucket)).status, 404, url);
  const denied = await stateRequest(new Request(`${origin}/objects/manifest.json`, { method: 'POST' }), bucket);
  assert.equal(denied.status, 405);
  assert.equal(denied.headers.get('Allow'), 'GET, HEAD, PUT, DELETE');
  assert.deepEqual(bucket.access, []);
});

test('uploads fail before bucket writes when Content-Length is missing, invalid or over 32 MiB', async () => {
  const bucket = memoryBucket();
  const path = `${origin}/objects/scenarios/${id}/runoff.tif`;
  assert.equal((await stateRequest(new Request(path, { method: 'PUT', body: 'a' }), bucket)).status, 411);
  for (const length of ['-1', 'abc', '1.5']) {
    const request = { url: path, method: 'PUT', headers: new Headers({ 'Content-Length': length }), body: null };
    assert.equal((await stateRequest(request, bucket)).status, 400);
  }
  assert.equal((await stateRequest(new Request(path, { method: 'PUT', headers: { 'Content-Length': String(MAX_OBJECT_BYTES + 1) } }), bucket)).status, 413);
  assert.deepEqual(bucket.access, []);
});
