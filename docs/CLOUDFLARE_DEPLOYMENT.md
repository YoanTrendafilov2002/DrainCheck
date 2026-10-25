# DrainCheck on Cloudflare

The prepared deployment keeps the existing React map and the complete Python
analysis API. Cloudflare serves the frontend as static assets and forwards
`/api/*` to one Container running FastAPI, Rasterio/GDAL, NumPy and SciPy. It
uses the actual municipal 1 m DTM, prepared 5 m products, full cadastral and
infrastructure data, rainfall, historical sources, and existing downloads.
It does not replace the backend with screenshots, fabricated elevations, or a
static map.

## What has been verified

Preparation and safe restoration are covered by `tests/test_cloudflare_data.py`:
exact file inventory, SHA256 and size checks, original-file preservation,
nanosecond modification times, malicious paths, duplicate entries, links,
special files, missing files, altered manifests and corrupted payloads. A real
data inventory check confirms the corrected native DTM grid, both SQLite
indexes, the full cadastral geometry, 335 cadastral source batches and their
receipts, the terrain-screening downloads and historical reports.

All 36 locked Python dependencies have downloadable binary wheels for
CPython 3.12 on Linux x86-64, including Rasterio, pyproj, NumPy, SciPy and
Shapely. This verifies wheel availability; it does not execute those wheels on
Linux. Worker tests, TypeScript checking and Wrangler's no-deploy dry run are
separate checks. A dry run with `--containers-rollout=none` does not build or
test the Container.

Docker is not installed on the preparation computer. A private remote builder
with a Docker-compatible engine is an alternative to installing it locally;
it must receive the verified private snapshot and protect that input. No local
or remote Linux image build has been executed. Container startup and the public
full-stack smoke test remain unverified until a builder runs the steps below. Check the
deployment receipt for the current account-access and publication state.

## Required services and resources

Use Cloudflare Workers Paid with Containers enabled and a private R2 bucket
called `draincheck-state`. The deployment configuration selects one
`standard-2` Container, with 1 vCPU, 6 GiB RAM and 12 GB disk, and a maximum of
one simultaneous instance. This leaves room for the real data, Python native
libraries and bounded derived caches. Cloudflare's image limit depends on the
selected instance's disk allocation; inspect the actual built image size.
[Cloudflare instance limits](https://developers.cloudflare.com/containers/platform/limits/).

Containers require the Workers Paid plan, currently starting at $5 USD/month.
Active CPU, provisioned memory and disk have separate metered charges, with
included allowances; Workers, Durable Objects and logs can add usage charges.
The Container sleeps after ten minutes without requests. One-instance and
sleep settings constrain activity but do not impose a billing cap. Confirm
the current rates and configure account usage notifications before a public
launch. [Cloudflare Container pricing](https://developers.cloudflare.com/containers/platform/pricing/).

For scale, the configured 6 GiB / 12 GB instance active for 730 hours would cost
about $46.35 for the plan, memory and disk after their included allowances,
before CPU and other services. This is an illustrative calculation from the
published rates, not a quote or measured app cost. Idle sleep can reduce it;
frequent public traffic can keep the instance active. The $5 plan fee is not
the total hosting price.

R2 stores only user-generated scenario derivatives and local colour scales;
the immutable municipal snapshot is part of the private image. Keep R2 public
access disabled. Standard R2 storage has a separate free allowance and usage
pricing; storage and operations can still grow with generated scenarios.
[R2 pricing](https://developers.cloudflare.com/r2/pricing/).

Cloud mode limits its local scenario cache to 512 MiB. Before removing a local
derivative, it verifies the saved manifest and all three remote payload hashes.
Active results, tiles and downloads hold leases; a full or busy cache returns
a retryable 503 instead of deleting active or uncommitted files. Evicted
scenarios restore by their existing IDs. Local desktop mode and original data
are unaffected. Each state object is limited to 32 MiB; small manifest and
colour-scale receipts retain a 2 MiB parsing limit.

The Container has Internet access disabled. Its permitted outbound binding is
`http://draincheck-state.internal`, handled by the Worker and its R2 binding.
It does not contain Cloudflare API keys or S3 credentials. The map browser
still fetches the configured public basemap. These controls preserve the
existing calculations and downloads without exposing a public R2 bucket.

## Private runtime-data snapshot

Run from the app root using the existing environment that contains Rasterio:

```powershell
../../work/hydro_env/Scripts/python.exe scripts/prepare_cloudflare_data.py --check-only
```

The command hashes the real inputs and checks the native source's known SHA256,
EPSG:7801, Float32 band, 51,722 columns by 54,343 rows, 1 m transform and
`-9999` NoData. It does not write an archive or modify any input.

To prepare the private build input:

```powershell
../../work/hydro_env/Scripts/python.exe scripts/prepare_cloudflare_data.py
```

The default input is the existing corrected DTM next to this app directory.
Use `--native-dtm PATH` if that same verified file is elsewhere. The output is:

```text
.cloudflare-data/runtime-data.tar
.cloudflare-data/runtime-data-manifest.json
.cloudflare-data/runtime-data-info.json
```

All originals remain in place. The native DTM is mapped into the snapshot as
`data/native/sofia_dtm_2024_1m_gee.tif`; this changes its packaged path, not its
CRS, grid, elevations, compression or file bytes. The snapshot includes all
runtime files under `data/`, including full source geometry, national cadastral
batches, source reports, analysis downloads and metadata. It excludes rendered
tiles, existing user scenarios, generated local colour scales, private HTTP
receipts, temporary files, Python caches and archived previous colour scales.
Those exclusions do not delete their local originals.

The manifest schema is intentionally portable:

```json
{
  "schema": "draincheck-runtime-data-v1",
  "files": {
    "data/cache/revision.txt": {
      "sha256": "<64 lowercase hexadecimal characters>",
      "size": 16
    }
  }
}
```

Every actual manifest entry has the file's exact byte size and SHA256. The
example size above illustrates the schema; the generated manifest supplies
the actual value. PAX TAR modification times preserve original nanoseconds.
The receipt records archive and manifest hashes, exact bytes and file count.
Preparing an already-existing output refuses to overwrite it; provide a new
`--output DIRECTORY` and inspect the result before changing build inputs.

The snapshot directory is ignored by Git. Never add it or credentials with
`git add -f`. It is approximately 4.2 GB uncompressed, so confirm local free
space before preparation. A build transfers these private data to the chosen
Cloudflare account's image registry; source Git stays free of bulk datasets.

## Safe restoration and image construction

Restoration uses a separately supplied trusted manifest, not only a manifest
inside an arbitrary archive:

```sh
python scripts/restore_cloudflare_data.py \
  --archive .cloudflare-data/runtime-data.tar \
  --manifest .cloudflare-data/runtime-data-manifest.json \
  --destination /path/to/new-runtime
```

The script refuses existing destination data or a destination manifest. It
validates the entire archive inventory before extracting anything, rejects
absolute/traversal paths, duplicate files, symlinks, hardlinks, sparse files
and special devices, then writes a private staging tree. It verifies every
size and SHA256 before activating that tree. It never extracts an unchecked
archive with `extractall` and never writes over a source dataset.

`Dockerfile` builds the frontend using Node 22 and frozen pnpm dependencies,
then installs the locked Python 3.12 binary dependencies. BuildKit reads the
private TAR through a bind mount, so the final image contains the extracted
data once rather than retaining both a TAR layer and extracted copies.
`.dockerignore` uses an allow-list that excludes the working data tree,
credentials, account state and dependency directories.

Inputs and manifest are root-owned and read-only in the image. The service
runs as UID/GID 10001. The cache parent has a sticky directory mode, preventing
that user from removing root-owned source cache files while allowing new local
scales; generated tile/scenario directories are writable. The app listens on
port 8080 with one Uvicorn process. Startup re-verifies the declared data hashes;
source relocation does not change scenario identity or authorize changed data.

On a Linux-amd64-capable Docker host:

```sh
docker info
docker build --platform linux/amd64 -t draincheck:verified .
docker image inspect draincheck:verified --format '{{.Size}}'
```

A standalone Docker run also needs the private state service for requests that
create or restore scenarios and local scales. Simply exposing port 8080 does
not provide Cloudflare's outbound R2 binding. For a full local platform test,
use the Wrangler Container development environment after configuring its local
R2 binding. Do not replace a failed persistence call with an apparent success.

Cloudflare's normal Container deployment builds and uploads the image with
Docker, so a functioning Docker daemon is required on that builder.
[Cloudflare deployment prerequisites](https://developers.cloudflare.com/containers/get-started/).

## Deploy the complete app

Run the existing app checks first; they require the matching real data snapshot:

```sh
python -m pytest tests -q
pnpm test
pnpm build
cd cloudflare
pnpm install --ignore-workspace --frozen-lockfile --ignore-scripts
pnpm --ignore-workspace check
pnpm --ignore-workspace test
pnpm --ignore-workspace dry-run
```

The Cloudflare package is isolated from the parent pnpm workspace. Keep the
`--ignore-workspace` switches above; its install deliberately disables package
lifecycle scripts. Authenticate Wrangler on the deployment machine, verify the
intended account, and create the private bucket only if it does not already
exist. Run the following commands inside `cloudflare/`:

```sh
pnpm --ignore-workspace exec wrangler login
pnpm --ignore-workspace exec wrangler whoami
pnpm --ignore-workspace exec wrangler r2 bucket list
pnpm --ignore-workspace exec wrangler r2 bucket create draincheck-state
pnpm --ignore-workspace exec wrangler deploy
```

Use the account ID already set in `cloudflare/wrangler.jsonc` only when it is
the intended signed-in account. The final command deploys the frontend,
Worker, Durable Object binding and real Container image together. Deployment
can take several minutes to provision its first instance. Record the resulting
Worker URL, version and image digest; a successful frontend-only upload is
insufficient to call this app deployed.

The Worker always handles API routes before static assets, so backend failures
stay explicit API errors. It does not substitute the HTML app shell for failed
analysis requests. Data identity comes from the exact runtime manifest; source
adapters retain their independent raster-header, provenance and revision checks.

## Verify the public app before sharing it

Check `/api/health` reports both `spatial_ready` and `terrain_available` true.
Check metadata endpoints for native terrain, pluvial screening, green absorption,
cadastre, historical sources, river context and rainfall. At a known real point,
compare elevation, original screening values and green/water treatment against
the local app. Render real vector and raster tiles and confirm expected PNG/MVT
responses instead of HTML errors. Confirm large downloads support byte ranges.

In the browser, test layer controls, terrain colours, grey cadastral buildings,
historic evidence, green exclusion, rainfall's supplemental overlay, pipe-area
selection, rain slider, blockage controls, depth legends and report downloads.
Save a scenario and a fitted local scale, let the Container restart, and confirm
their original URLs restore through private R2. User state is shared by its
unguessable identifier; this app does not add a per-user login system.

The public deployment retains the app's scientific distinctions: original
terrain susceptibility is a relative screening score; rain/blockage depth is a
bounded terrain-storage scenario, not validated hydraulic inundation; river
distance identifies proximity context, not observed flood cause. Cloud hosting
does not improve the underlying source resolution or model validation.

## Updating and rollback

Source-only updates can reuse the verified private snapshot when its data are
unchanged. If input data change, prepare a new snapshot in a new directory and
retain the previous archive and manifest. Test before deploying, record the new
image digest and preserve the previous known-working image for rollback.
Never delete old originals, force-push Git or replace a failed image with a
frontend-only release. The Container's renderer and portable source identities
invalidate stale derivatives when the implementation or true data change.
