import { STATE_HOST } from './routing.mjs';

export const MAX_OBJECT_BYTES = 32 * 1024 * 1024;
export const STATE_PREFIX = 'appstate/v1/';
const KEY = /^(?:manifest\.json|local-scales\/local-[a-f0-9]{16}\.json|scenarios\/[a-f0-9]{32}\/(?:manifest\.json|result\.json|runoff\.tif|river_classes\.tif))$/;
const METHODS = 'GET, HEAD, PUT, DELETE';

function result(body, status, headers = {}) {
  return new Response(body, { status, headers: { 'Cache-Control': 'private, no-store', ...headers } });
}

function objectHeaders(object) {
  const headers = new Headers({ 'Cache-Control': 'private, no-store' });
  object.writeHttpMetadata?.(headers);
  headers.set('Cache-Control', 'private, no-store');
  headers.set('Content-Length', String(object.size));
  headers.set('ETag', object.httpEtag ?? `"${object.etag}"`);
  return headers;
}

/** Invoked only by ContainerProxy's explicit outboundByHost binding. */
export async function stateRequest(request, bucket) {
  const url = new URL(request.url);
  if (url.hostname !== STATE_HOST || url.search || !url.pathname.startsWith('/objects/')) {
    return result('Not found', 404);
  }
  let key;
  try {
    key = decodeURIComponent(url.pathname.slice('/objects/'.length));
  } catch {
    return result('Invalid object key', 400);
  }
  if (!KEY.test(key)) return result('Not found', 404);
  const scopedKey = STATE_PREFIX + key;
  if (!['GET', 'HEAD', 'PUT', 'DELETE'].includes(request.method)) {
    return result('Method not allowed', 405, { Allow: METHODS });
  }

  if (request.method === 'PUT') {
    const length = request.headers.get('Content-Length');
    if (length === null) return result('Content-Length is required', 411);
    if (!/^\d+$/.test(length)) return result('Invalid Content-Length', 400);
    if (Number(length) > MAX_OBJECT_BYTES) return result('Object exceeds the 32 MiB state limit', 413);
    const object = await bucket.put(scopedKey, request.body ?? new Uint8Array(0), {
      httpMetadata: { contentType: request.headers.get('Content-Type') ?? 'application/octet-stream' },
    });
    return result(null, 201, { ETag: object.httpEtag ?? `"${object.etag}"` });
  }
  if (request.method === 'DELETE') {
    await bucket.delete(scopedKey);
    return result(null, 204);
  }
  const object = request.method === 'HEAD' ? await bucket.head(scopedKey) : await bucket.get(scopedKey);
  if (!object) return result(null, 404);
  const headers = objectHeaders(object);
  const ifNoneMatch = request.headers.get('If-None-Match');
  if (ifNoneMatch && (ifNoneMatch === '*' || ifNoneMatch.split(',').map(value => value.trim()).includes(headers.get('ETag')))) {
    await object.body?.cancel();
    headers.delete('Content-Length');
    return new Response(null, { status: 304, headers });
  }
  return new Response(request.method === 'HEAD' ? null : object.body, { headers });
}
