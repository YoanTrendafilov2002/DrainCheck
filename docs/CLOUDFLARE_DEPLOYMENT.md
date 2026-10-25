# Cloudflare hosting

For temporary sharing from your PC, use the [Tunnel launcher](CLOUDFLARE_TUNNEL_DEMO.md).
The steps below host the frontend and Python API on Cloudflare.

## Requirements

- Python 3.12 with `requirements-lock.txt` installed; Node 22+, pnpm and a Docker engine supporting Linux amd64.
- Workers Paid with Containers enabled, authenticated Wrangler, and a private R2 bucket named `draincheck-state`.
- The matching real datasets restored as described in [Installation](INSTALLATION.md), including the native DTM, 5 m screening, vector indexes, green mask and provenance.
- Both water-mask files and both river/stadium exclusion files in `data/cache/`: `open_water_mask_5m.tif`, `open_water_meta.json`, `screening_exclusions_5m.tif`, `screening_exclusions_meta.json`.

The configuration runs one `standard-2` Container and sleeps after ten idle minutes. Usage is metered; see [Cloudflare pricing](https://developers.cloudflare.com/containers/platform/pricing/).

## Prepare and check

Run from the app root in its activated Python environment. Replace the DTM path with the actual corrected original:

```sh
python scripts/prepare_cloudflare_data.py --native-dtm /path/to/sofia_dtm_2024_1m_gee.tif --check-only
python scripts/prepare_cloudflare_data.py --native-dtm /path/to/sofia_dtm_2024_1m_gee.tif
python -m pytest tests -q
pnpm install --frozen-lockfile
pnpm test
pnpm build
docker info
docker build --platform linux/amd64 -t draincheck:verified .
docker image inspect draincheck:verified --format '{{.Size}}'
```

Preparation creates the private `.cloudflare-data/` build input and verifies its file hashes. Keep it out of Git. Preserve any previous snapshot elsewhere before preparing a replacement; existing outputs are never overwritten. The snapshot must include the current exclusion masks, not an older data package.

## Deploy

Check `cloudflare/wrangler.jsonc` targets your intended account. Run:

```sh
cd cloudflare
pnpm install --ignore-workspace --frozen-lockfile --ignore-scripts
pnpm --ignore-workspace check
pnpm --ignore-workspace test
pnpm --ignore-workspace dry-run
pnpm --ignore-workspace exec wrangler login
pnpm --ignore-workspace exec wrangler whoami
pnpm --ignore-workspace exec wrangler r2 bucket list
```

Create the bucket only if it is absent, then deploy:

```sh
pnpm --ignore-workspace exec wrangler r2 bucket create draincheck-state
pnpm --ignore-workspace exec wrangler deploy
```

Keep R2 public access disabled. The dry run checks Worker configuration; it does not test a Container build or deploy the app.

## Verify and update

At the resulting URL, check `/api/health` reports `terrain_available` and `spatial_ready` true. Check `/api/pluvial/meta`, `/api/pluvial/water-mask/meta` and `/api/pluvial/screening-exclusions/meta` report available data. Test map layers, downloads and a rainfall/blockage scenario; confirm saved scenarios and local colour scales restore after a Container restart.

For source-only updates, reuse the snapshot only while its inputs are unchanged. For data changes, prepare a new snapshot and rebuild. Retain the previous image and manifest for rollback.
