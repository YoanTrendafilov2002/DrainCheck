# Obtain the remaining data

The source route and green polygons, live metadata, full 201-point whole-area normalization snapshot, and all four rainfall assets are bundled. Rainfall needs no further cloud acquisition; see `docs/RAINFALL.md`. The native DTM raster and infrastructure point coordinates are **not**. They are present in the existing authorized Earth Engine project and were successfully used in the prototype. Their presence in that project does not imply a fresh Codex environment already has access.

No export job was started during preparation of this package. A read-only Earth Engine query retrieved the included metadata and quantiles. The acquisition helpers have been syntax checked, but their authenticated batch-export paths have not been executed as part of this handoff.

## Preferred first check

Look for a user-provided native `sofia_dtm_2024_1m_gee.tif` or its completed export shards. Validate the projection, affine transform, mask, pixel size, band and native values against `config/map_config.json`. Use the corrected EPSG:7801 asset/file, not an older incorrectly labelled upload. Preserve an untouched copy. Do not download the colour-reference PNG and treat it as a DEM.

If authorized Earth Engine credentials are available, a server adapter can access both assets directly while the standalone app is developed. Do not place credentials or private keys in frontend code, source control, URLs, logs, or this package. A durable production app should use an appropriate authorized server identity or exported data; do not assume a developer's interactive browser sign-in transfers to the backend.

## Python workflow

Install the official client and authenticate using the account with asset access, if not already configured:

```bash
python -m pip install earthengine-api
earthengine authenticate
python scripts/export_ee_assets.py inspect
python scripts/export_ee_assets.py stats
```

`inspect` writes small metadata and category-count outputs to `data/incoming/`. `stats` refreshes all **201** quantiles in `data/incoming/elevation_quantiles.json`. It does not download the full raster. The default statistics use 60 m display samples, best-effort reduction and the same reducer settings as the prototype. This sampling only estimates the colour transform; native scientific pixels remain 1 m. A local statistics request accepts `--bounds WEST SOUTH EAST NORTH` and uses a requested 10 m statistics scale.

To plan an export, omit `--start`. These commands authenticate and submit jobs only when `--start` is present:

```bash
# Dry-run plans; no jobs start:
python scripts/export_ee_assets.py export-points
python scripts/export_ee_assets.py export-dem

# After checking destination storage, submit to Google Drive:
python scripts/export_ee_assets.py export-points --start
python scripts/export_ee_assets.py export-dem --start

# Or use an EXISTING, authorized Google Cloud Storage bucket:
python scripts/export_ee_assets.py export-dem --destination gcs --bucket YOUR_BUCKET --start
```

The helper never creates a bucket, changes permissions, or publishes data. Batch task IDs/status at submission are saved under `data/incoming/`; submission is not completion. Monitor the tasks, download completed files, and validate them before treating the inputs as available. Avoid repeatedly submitting duplicate export jobs.

## Code Editor alternative

Open a **new unsaved script/tab** in Earth Engine and paste `earth_engine/export_for_codex.js`. Do not overwrite the existing Script1 or Script2. Running it prepares three tasks under **Tasks**:

1. Native numeric DTM as Cloud Optimized GeoTIFF shards.
2. Complete infrastructure point FeatureCollection as GeoJSON.
3. The 201 elevation quantiles as CSV.

Start only the chosen tasks after checking destination storage. For a web app, neither Script1 nor Script2 must be merged or deleted to perform these exports. The utility is an acquisition helper, not a third required prototype module.

## Large raster handling

A municipality-wide 1 m float raster can require several GB; compression, footprint and NoData influence actual size. The export uses the original native transform and 8192-pixel file dimensions. It explicitly writes -9999 as NoData without changing valid heights. Filling the export rectangle with a NoData sentinel can create extra empty-area storage, so do not assume every shard contains useful terrain. Check destination quota first. Prefer storage appropriate for geospatial data rather than placing the full raster in a frontend bundle or ordinary Git history.

After acquisition, keep the native EPSG:7801 COG/shards as the authoritative elevation source. Build any Web Mercator display tiles and overviews as separate derivatives. Native point sampling must transform incoming WGS84 click coordinates into the native raster grid. A styled RGB export cannot replace the numeric DTM. A terrain-RGB/DEM display encoding also has its own quantization and must not silently become the scientific source.

## Required validation after import

- DTM band values are heights, not RGB; native transform `[1,0,299392,0,-1,4753611]`, horizontal EPSG:7801, vertical Baltic 1982, 1 m cells.
- NoData is masked and does not appear as zero elevation or ocean-sized flat terrain.
- Raster shards tile without shifts or duplicate edge pixels. Inspect their actual extents and transforms.
- Point count is 322,025; category totals match `DATA_CONTRACT.md`; preserve properties and geometry.
- Quantile file has 201 finite nondecreasing entries, P0 through P100 in 0.5% increments.
- Recomputed whole-area statistics should be broadly consistent with the observed 501.0–2278.8 m range, but approximate sampling and dataset revision can change last digits. Do not force exact equality to rounded observations.
- Do not claim full raster acquisition, a working terrain endpoint, or point-layer availability until the relevant retrieval is completed and tested.

## Official API references

- Image export and native grid control: https://developers.google.com/earth-engine/apidocs/export-image-todrive
- Table export formats: https://developers.google.com/earth-engine/apidocs/export-table-todrive
- Percentile reducer: https://developers.google.com/earth-engine/apidocs/ee-reducer-percentile
- Server identity/access: https://developers.google.com/earth-engine/guides/service_account
- Image interpolation: https://developers.google.com/earth-engine/apidocs/ee-image-interpolate

The helper uses the documented APIs above; validate current authentication and export behavior in the target environment. No credentials are provided in this handoff.
