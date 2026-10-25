# Sofia app handoff

Prepared 2026-10-24; updated 2026-10-25 with the rainfall script and complete rainfall assets for turning the existing Earth Engine prototype into a standalone app.

**Give Codex this entire folder/ZIP and `CODEX_PROMPT.md`.** This is a development handoff, not an already-built application.

## What is ready

- Exact UTF-8 snapshots of the saved `Script1.js` and companion `Script2.js`, kept as two files.
- Original sewer and green-area GeoJSON files, including the duplicate sewer upload, byte-preserved.
- Recomputed ready-to-use all/inside/outside sewer geometries, with original source properties and computed lengths.
- The 2,175 green polygons intersecting routes, with original IDs/properties restored for the new app.
- Original user-supplied terrain colour reference PNG.
- Reusable browser/server-independent elevation normalization module, the actual 201 whole-area quantiles retrieved from Earth Engine, and passing tests.
- Configuration, schemas, provenance, validation checks, and asset acquisition tools.
- The previously prepared Earth Engine shapefile upload ZIPs, plus archived preprocessing code.

## Rainfall addition included in full

- The newly attached rainfall script, byte-preserved as `earth_engine/Rainfall_20250627_original.js`.
- Three complete numeric rainfall COGs for the 2025-06-27 local day: merged, bias-corrected and raw radar.
- All 55 Weather Underground station records, including 43 accepted and 12 rejected with QC reasons.
- Complete native-array/mask snapshots, asset metadata, independent point checks, a reproducible COG builder and validation.
- Integration instructions in `docs/RAINFALL.md`. Keep the newer granular terrain colours; do not restore the rainfall attachment's older elevation styling.

The full rainfall products can be used locally without Earth Engine access. Upstream five-minute radar observations, station time series and their preprocessing scripts are not included; these outputs are daily totals.

## Two inputs are referenced, not bundled

| Input | Current location | Status |
|---|---|---|
| Native 1 m municipal DTM | `projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee` | Ran successfully in the authorized Earth Engine session. Full raster bytes are not in this handoff. |
| 322,025 infrastructure points | `projects/rivertracker-512606/assets/sofia_infrastructure_pps` | Count/category totals checked in Earth Engine. Point coordinates/properties are not in this handoff. |

The actual 201 whole-area elevation quantiles are included in `data/reference/elevation_quantiles_whole_area.json`, obtained by a live read-only Earth Engine calculation. `earth_engine_live_metadata.json` independently confirms EPSG:7801, 1 m nominal scale and 322,025 points. The five rounded legend ticks in the configuration remain UI reference values, not a substitute for the full curve.

See `docs/ACQUISITION.md` for obtaining the two assets and normalization statistics. Codex can implement a working map from the included real vectors and rainfall immediately, while connecting terrain/point data through an authorized backend or downloaded exports. The preview PNG is a visual reference and cannot supply elevation values.

## Package layout

| Path | Purpose |
|---|---|
| `CODEX_PROMPT.md` | Complete build instructions to paste/send to Codex |
| `config/map_config.json` | Native grid, palette, normalization, layers and categories |
| `docs/DATA_CONTRACT.md` | Geometry/attributes/counts and scientific limitations |
| `docs/ACQUISITION.md` | Missing asset export, storage and authorization workflow |
| `docs/IMPLEMENTATION_NOTES.md` | Prototype behavior, performance lessons and app acceptance |
| `data/raw/` | Immutable original user GeoJSON files |
| `data/derived/` | Ready-to-use route zones, green display subset and statistics |
| `data/reference/` | Uploaded colour-reference PNG, live metadata and 201-point normalization snapshot |
| `docs/RAINFALL.md` | Rainfall provenance, integration rules, grids, QC and limits |
| `data/rainfall/` | Three numeric COGs, 55 stations, full snapshots and checks |
| `earth_engine/Rainfall_20250627_original.js` | Exact newly attached source script |
| `scripts/prepare_rainfall.py`, `scripts/verify_rainfall.py` | Rebuild and verify rainfall files |
| `data/asset_dependencies.json` | Explicit inventory of unbundled inputs |
| `shared/elevation_scale.mjs` | Portable continuous nonlinear display transform |
| `scripts/prepare_vectors.py` | Reproducible source-to-derived vector processing |
| `scripts/export_ee_assets.py` | Optional authorized metadata/statistics retrieval and batch exports |
| `scripts/verify_handoff.py` | File integrity and data invariants |
| `earth_engine/Script1.js`, `Script2.js` | Saved prototype snapshots; archive/reference, not frontend bundles |
| `earth_engine/export_for_codex.js` | Standalone export utility; does not replace either prototype script |
| `earth_engine/uploads/` | Previously prepared table-asset upload ZIPs |
| `archive/` | Historical preprocessing helpers; see notes before running |
| `MANIFEST.json` | SHA-256 and size inventory for all included files except itself |

## Verify and reproduce

From this folder:

```bash
python -m venv .venv
# Activate .venv for your operating system, then:
python -m pip install -r requirements-data.txt
python scripts/verify_handoff.py
python scripts/verify_rainfall.py
node --test tests/elevation_scale.test.mjs
```

To rebuild derived data without overwriting the packaged baseline:

```bash
python scripts/prepare_vectors.py --out-dir build/derived
```

The original files remain untouched. The regenerated output retains full precision at clip intersections; the old browser prototype rounded packed clip coordinates to 1e-9 degree and lengths to 0.001 m. Those display encoding choices are unnecessary in the new app.

## Current behavior to preserve

The default map uses whole-study-area elevation normalization, fixed during panning. A user can fit colours to the current view, restore the whole-area scale, or explicitly enable auto-fit. Both transforms use the same reference palette and preserve native height values. Routes initially show only sections inside green areas, with all three statuses enabled. Infrastructure point layers start off. Imperviousness was removed from the active map at the user's request.

The package contains no credentials, no full DTM raster, no full infrastructure-point export, and no validated flood model. It includes no invented substitutes for them. No cloud export jobs or publication actions were started while preparing this handoff.
