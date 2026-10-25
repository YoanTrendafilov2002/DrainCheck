# Validation record — 2026-10-24

- Original source hashes match the uploaded sewer and green-area files; duplicate sewer upload retained and byte-identical.
- Derived vectors rebuilt from originals with Shapely 2.2.0 / pyproj 3.8.0. Source properties retained.
- All/inside/outside source-route counts: 717 / 543 / 670.
- Lengths: 540163.0135031902 / 137858.69885054993 / 402304.31468007684 m.
- Aggregate partition difference: approximately 0.00002744 m. Largest per-route difference: approximately 0.00000285 m.
- Green mask: 64,956 nonempty geometries from 64,962 raw records; six empty IDs recorded; one derived geometry repaired. Display subset: 2,175 features.
- Source statuses: 464 existing / 250 planned / 3 open.
- Exact saved prototype snapshots: Script1 511,862 bytes; Script2 511,982 bytes. Both preserved.
- All packaged Python files compile; all Earth Engine JavaScript files pass Node syntax checks.
- Five Node normalization tests pass, including live whole-area legend reproduction.
- Live read-only Earth Engine query confirms EPSG:7801, nominal 1 m cells and 322,025 points; all 201 whole-area quantiles included.
- Batch export helper dry-run succeeds without starting a task. Actual authenticated Python export/download paths are not executed or claimed complete.
- Full DTM raster bytes and infrastructure-point coordinates are not bundled. No model-generated substitutes are included.
- Final manifest and package invariants are checked by scripts/verify_handoff.py before delivery. No live app has been built or deployed by this handoff preparation.

## Rainfall update — 2026-10-25

- New uploaded script is byte-identical to the attachment: 16,323 bytes, SHA-256 `81d5832798aa33ea3a857911a14d14d747fda64e2a108ca673356dba603d9765`.
- Three complete rainfall assets retrieved as native-grid arrays/masks via read-only Earth Engine queries; no cloud batch export jobs started.
- Final/corrected: 104 × 71, all 7,384 cells valid. Raw daily radar: 98 × 69, 5,041 valid and 1,721 masked cells.
- All three Float32 COGs match every valid source pixel and mask exactly, with the same EPSG:4326 transforms and -9999 NoData.
- Fifteen independently queried native-grid point samples match, including raw-radar NoData at corners.
- Rain stations: 55 unique station IDs, 43 accepted (`qc=ok`) and 12 rejected. Original source properties/rejection reasons retained.
- Rebuild and rainfall verification pass with rasterio 1.5.2, numpy 2.3.5, pyproj 3.8.0 and affine 3.0.1.
- Full-area final-product precipitation summary: valid area 461.2377566 km²; area-weighted mean 11.15520235 mm; max 27.14878273 mm; precipitation volume 5,145,200.5045 m³. These are native-cell computations, not runoff or flood-volume estimates; see `summary.json` for exact values/method.
- The metadata label says local day 2025-06-27, Europe/Sofia. The upstream five-minute/individual station observations and three named preprocessing scripts were not supplied, so their aggregation, correction and QC algorithms were not independently audited.
- The original Script1/Script2, raw source data and full normalization snapshot remain unchanged. The app prompt explicitly retains the newer granular stable elevation scale.
