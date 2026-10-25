import { test } from 'node:test';
import assert from 'node:assert/strict';
import { routeRequest, STATE_HOST, INSTANCE_NAME, readinessGate } from '../src/routing.mjs';

test('concurrent requests share cold-start verification and can retry a failed start', async () => {
  let starts = 0;
  let release;
  const start = readinessGate(async () => {
    starts++;
    await new Promise(resolve => { release = resolve; });
    if (starts === 1) throw new Error('not ready');
  });
  const first = start();
  const second = start();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(starts, 1);
  release();
  await assert.rejects(first, /not ready/);
  const retry = start();
  await Promise.resolve();
  assert.equal(starts, 2);
  release();
  await retry;
});

test('API passes POST body, query and headers through the same Request', async () => {
  const request = new Request('https://draincheck.example/api/clogging/scenarios?test=1', {
    method: 'POST', body: '{"rainfall_mm":75}', headers: { 'Content-Type': 'application/json', 'If-Match': 'source-v1' },
  });
  let calls = 0;
  const response = await routeRequest(request, { fetch() { assert.fail('API reached assets'); } }, () => ({
    async fetch(actual) {
      calls++;
      assert.equal(actual, request);
      assert.equal(actual.headers.get('If-Match'), 'source-v1');
      assert.equal(await actual.text(), '{"rainfall_mm":75}');
      return Response.json({ scenario_id: 'real-result' }, { status: 201 });
    },
  }));
  assert.equal(calls, 1);
  assert.equal(response.status, 201);
  assert.equal((await response.json()).scenario_id, 'real-result');
});

test('ranged downloads and conditional responses preserve response streams and headers', async () => {
  const request = new Request('https://draincheck.example/api/refinement/download', {
    headers: { Range: 'bytes=1-3', 'If-Range': '"source"' },
  });
  const download = new Response(new Uint8Array([2, 3, 4]), {
    status: 206, headers: { 'Content-Range': 'bytes 1-3/10', ETag: '"source"', 'Content-Type': 'image/tiff' },
  });
  const actual = await routeRequest(request, {}, () => ({ fetch(forwarded) {
    assert.equal(forwarded.headers.get('Range'), 'bytes=1-3');
    assert.equal(forwarded.headers.get('If-Range'), '"source"');
    return download;
  } }));
  assert.equal(actual, download);
  assert.deepEqual([...new Uint8Array(await actual.arrayBuffer())], [2, 3, 4]);
  assert.equal(actual.headers.get('Content-Range'), 'bytes 1-3/10');
  const cached = new Response(null, { status: 304, headers: { ETag: '"source"' } });
  assert.equal(await routeRequest(request, {}, () => ({ fetch: () => cached })), cached);
});

test('SPA, assets and API lookalikes never create a container or expose storage', async () => {
  for (const path of ['/', '/assets/app.js', '/api-lookalike', '/objects/manifest.json', '/list']) {
    const request = new Request('https://draincheck.example' + path);
    assert.equal(await (await routeRequest(request, { fetch(actual) {
      assert.equal(actual, request);
      return new Response('static');
    } }, () => assert.fail('Static route started container'))).text(), 'static');
  }
  assert.equal(INSTANCE_NAME, 'draincheck-main');
  const denied = await routeRequest(new Request(`http://${STATE_HOST}/objects/manifest.json`), {
    fetch() { assert.fail('Private host reached assets'); },
  }, () => assert.fail('Private host reached API'));
  assert.equal(denied.status, 404);
});

test('container startup errors are retryable without exposing exception details', async () => {
  const response = await routeRequest(new Request('https://draincheck.example/api/health'), {}, () => {
    throw new Error('secret internal state');
  });
  assert.equal(response.status, 503);
  assert.equal(response.headers.get('Retry-After'), '5');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.doesNotMatch(await response.text(), /secret/);
});
