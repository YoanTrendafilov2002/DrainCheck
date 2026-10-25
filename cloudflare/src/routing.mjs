export const STATE_HOST = 'draincheck-state.internal';
export const INSTANCE_NAME = 'draincheck-main';

/** Coalesce cold-start checks, retrying after a failed or completed check. */
export function readinessGate(start) {
  let pending;
  return () => pending ??= Promise.resolve().then(start).finally(() => { pending = undefined; });
}

/** Keep the original Request and Response streams, headers and status intact. */
export async function routeRequest(request, assets, backend) {
  const url = new URL(request.url);
  // The private outbound handler is never reachable through the public router.
  if (url.hostname === STATE_HOST) {
    return new Response('Not found', { status: 404 });
  }
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
    try {
      return await backend().fetch(request);
    } catch {
      return Response.json({ detail: 'The analysis service is starting or temporarily unavailable. Retry shortly.' }, {
        status: 503,
        headers: { 'Cache-Control': 'no-store', 'Retry-After': '5' },
      });
    }
  }
  return assets.fetch(request);
}
