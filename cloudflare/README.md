# Cloudflare edge and container routing

This directory is an isolated Node package for Cloudflare deployment. The
React application and its existing dependencies remain in the parent project.
It targets account `abeef81bb3a4248c72956a9246527d8b` and a new Worker named
`draincheck`; it does not alter unrelated Workers.

## Architecture

- Workers Static Assets serves the existing `../dist` application with SPA
  routing. `/api` and `/api/*` go to the API before asset routing.
- The API uses one named `DrainCheckContainer` (`draincheck-main`), instance
  `standard-2`, maximum one instance, with a ten-minute idle sleep timeout.
  Concurrent requests share a readiness check allowing up to four minutes for
  actual startup verification of the multi-gigabyte source snapshot.
- The parent `Dockerfile` builds the existing Linux Python API and the verified
  data snapshot. Its build context is the parent application directory.
- Native terrain values, scientific rasters, source geometry, original
  attributes and existing API downloads continue to come from the real data.
  Static-only deployment cannot provide those backend functions.
- Local colour scales and generated scenario files persist through the private
  `DRAINCHECK_STATE` R2 binding. Rendered map tiles are disposable cache entries.
  The bucket must remain private; do not enable a public development URL.

Incoming API requests and their responses pass through without buffering or
rewriting bodies, response status, `Range`, `ETag`, conditional headers or
download headers. A container-start failure returns a retryable 503 response.

## Private state protocol

The API alone can reach `http://draincheck-state.internal` through the
Container SDK's `outboundByHost` interception. Public Worker requests cannot
invoke the object-storage handler. Internet access from the container is
disabled; the one virtual storage hostname is explicitly allowed. Browser
basemap requests remain independent requests from the browser.

The internal protocol is `GET`, `HEAD`, `PUT` or `DELETE` on `/objects/<key>`.
Permitted keys are:

- `local-scales/local-<16 lowercase hexadecimal characters>.json`
- `scenarios/<32 lowercase hexadecimal characters>/manifest.json`
- The same scenario path followed by `result.json`, `runoff.tif` or
  `river_classes.tif`
- `manifest.json`, reserved for a future application state index

Physical R2 keys start with `appstate/v1/`. No arbitrary key, dataset path,
listing endpoint, query parameter or public-host request is accepted. `PUT`
requires an accurate `Content-Length` no greater than 32 MiB. Bodies stream to
R2, and responses include private/no-store cache headers. The Python adapter
writes scenario data first and its checksum manifest last; it restores saved
objects lazily by the known scale/scenario ID.

## Install and verify

Use Node 22 or newer. Run these commands **inside this directory**:

```text
pnpm install --ignore-workspace --frozen-lockfile --ignore-scripts
pnpm --ignore-workspace check
pnpm --ignore-workspace test
pnpm --ignore-workspace dry-run
```

The isolated lockfile pins Wrangler 4.152.0, `@cloudflare/containers` 0.3.7,
and Workers types 5.20261025.1. Versions were read from the official npm
registry. The local workspace exception permits the same-day Workers types;
it does not change the parent project's dependencies.

Dry-run bundles the Worker and validates its configuration. It deliberately
uses `--containers-rollout=none` and does not validate a Linux image build,
upload datasets, create an R2 bucket or deploy a live Worker. Build the actual
frontend first, and keep the parent Dockerfile available for configuration
validation.

## Deploy

Follow the parent deployment guide for data snapshot preparation and image
building. A full deployment requires authenticated access to the specified
Cloudflare account, Workers Paid with Containers enabled, the private
`draincheck-state` R2 bucket and a Docker-compatible build engine (or a private
remote image build). Then run:

```text
pnpm --ignore-workspace exec wrangler deploy
```

This command makes the Worker live. Cloudflare can activate Worker code before
container provisioning finishes. Verify the live `/api/health`, source
availability, real map layers, scenario calculation, downloads and state
restoration before reporting deployment success. A static asset upload or a
successful Worker dry-run is not a successful full application deployment.

## Platform references

- [Container SDK and singleton routing](https://developers.cloudflare.com/containers/api/container-class/)
- [Static assets and a container backend](https://developers.cloudflare.com/containers/examples/container-backend/)
- [Private outbound binding handlers](https://developers.cloudflare.com/containers/configuration/workers-connections/)
- [Outbound hostname restrictions](https://developers.cloudflare.com/containers/configuration/outbound-traffic/)
- [Container deployment and build requirements](https://developers.cloudflare.com/containers/guides/deploy/)
- [Ephemeral container filesystem](https://developers.cloudflare.com/containers/concepts/architecture/)
