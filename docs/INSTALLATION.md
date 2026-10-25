# Install and run DrainCheck

## Use the configured application

In the configured local package, double-click **Run_Sofia_App.cmd**. It opens
[DrainCheck at localhost:8040](http://127.0.0.1:8040). Keep its terminal open;
press **Ctrl+C** to stop. The launcher reopens an existing DrainCheck server
instead of starting a duplicate. Node is unnecessary when `dist/` is present.

For temporary sharing, use **Run_Cloudflare_Demo.cmd** and share its printed
HTTPS address. Keep this PC awake, online and the launcher running. Restarting
creates a different address. An official `cloudflared` executable must already
be available; see [the Tunnel instructions](CLOUDFLARE_TUNNEL_DEMO.md).

## Set up another computer

Run these PowerShell commands from the application directory. Install
**Python 3.12** first. Create `.env` only for a new installation; retain an
existing configuration.

```powershell
py -3.12 -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-lock.txt
Copy-Item -LiteralPath '.env.example' -Destination '.env'
```

If `dist/` is missing, as in a fresh Git checkout, install **Node 22 or newer**
and **pnpm**, then build the interface:

```powershell
pnpm install --frozen-lockfile
pnpm build
```

## Restore the real data

A Git checkout includes the permitted route/green/point inputs and small daily
rainfall files. It excludes the native DTM, large pluvial rasters, bulk cadastral
geometry and generated spatial indexes. Small metadata files do not restore
those datasets. Copy matching data and their provenance from an existing
installation or obtain them from the documented sources. Preserve originals
and keep each snapshot's metadata with its matching files.

For a fresh checkout, restore the bundled green source and prepare the vector
index and rainfall summaries:

```powershell
& '.venv/Scripts/python.exe' scripts/restore_source_bundles.py
& '.venv/Scripts/python.exe' scripts/prepare_data.py
& '.venv/Scripts/python.exe' scripts/prepare_rainfall_cache.py
```

For elevation, set `SOFIA_DTM_PATH` in `.env` to the real raster, or place it at
`data/external/sofia_dtm_2024_1m_gee.tif`. The configured local installation uses
the sibling `../sofia_dtm_2024_1m_gee.tif`. Required raster: **51,722 × 54,343**,
Float32, horizontal **EPSG:7801**, transform
`[1, 0, 299392, 0, -1, 4753611]`, NoData **-9999**, with Baltic 1982 heights.
A preview PNG or different DEM cannot replace it. After restoring it, rerun
`prepare_data.py`, then `scripts/restore_reference_scale.py` with the same
Python environment. Without it, vector/rainfall browsing can run, with elevation
reported unavailable. See [terrain acquisition](ACQUISITION.txt).

Flood screening and scenarios additionally need the matching 5 m terrain
factors/scores, water mask, river/stadium screening-exclusion mask, full vector
index and green-absorption mask. Restore both `screening_exclusions_5m.tif` and
`screening_exclusions_meta.json` together, or run
`scripts/prepare_screening_exclusions.py` using its preserved real source
geometry. See [the screening-exclusion sources](SCREENING_EXCLUSIONS.md).
Evidence review also needs the real historical polygons and full cadastral
source/index. Restore these before running their preparation scripts:
[pluvial inputs](PLUVIAL_EVIDENCE.md), [water mask](OPEN_WATER_SOURCES.md),
[cadastral buildings](AGKK_CADASTRAL_BUILDINGS_SOURCES.md),
[historical evidence](HISTORICAL_FLOODS_SOURCES.md), and
[calculation inputs](RISK_CALCULATION_GUIDE.md). A new live-source acquisition
can differ from an existing snapshot; do not pair it with old metadata.

After the matching terrain, water and vector inputs are restored, run
`scripts/prepare_green_absorption.py` with the app's Python environment;
regenerate this mask after rebuilding its vector index. With the complete
historical/cadastral prerequisites also present, use
`scripts/acquire_flood_assessment.py` and then
`scripts/prepare_review_priority.py` for evidence review.

## Start the app

Use the launcher, or run:

```powershell
& '.venv/Scripts/python.exe' scripts/serve.py
```

Add `--port 8041` if another application occupies port 8040. Local dataset use
does not require Google sign-in. Keep credentials in server configuration.
