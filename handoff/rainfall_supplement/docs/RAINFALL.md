# Rainfall and water-data addition — 2026-10-25

The attached `Поставен текст.txt` is preserved byte-for-byte as `earth_engine/Rainfall_20250627_original.js` (16,323 bytes; SHA-256 `81d5832798aa33ea3a857911a14d14d747fda64e2a108ca673356dba603d9765`). It supplies rainfall behavior to combine with the earlier sewer/green-area prototype. Do not replace or merge away Script1 or Script2. Do not revert to this attachment's older P2–P98 terrain stretch or default auto-fit; the granular normalization and stable default specified in CODEX_PROMPT take precedence.

## Actual data included

All four rainfall assets were read from the authorized Earth Engine project on 2026-10-25. Complete raster cell values and masks were retrieved with `sampleRectangle` in their stored projection, then written to numeric Float32 Cloud Optimized GeoTIFFs without resampling. These are native-pixel copies of the Earth Engine assets, not copies of the original pre-upload TIFF file bytes. Both numeric array snapshots and original Earth Engine asset metadata are retained for audit/reproduction.

| File under `data/rainfall/` | Meaning | Stored grid |
|---|---|---|
| `merged_250m.tif` | Final radar/station merged daily rainfall | 104 × 71, EPSG:4326 |
| `radar_bias_corrected_250m.tif` | Bias-corrected daily radar rainfall | 104 × 71, EPSG:4326 |
| `radar_raw_1km.tif` | Uncorrected daily radar aggregation as uploaded | 98 × 69, EPSG:4326 |
| `wu_stations.geojson` | All 55 stations, original coordinates/properties | WGS84 lon/lat; 43 `qc=ok`, 12 rejected |

Asset IDs start with `projects/rivertracker-512606/assets/sofia_rain_20250627/` and end in the matching filenames without extensions. All raster bands are `rain_mm`, unit **mm accumulated over the local day 2025-06-27**, not mm/hour. The asset metadata explicitly identifies Europe/Sofia. That local day corresponds to `[2025-06-26T21:00:00Z, 2025-06-27T21:00:00Z)`; this is a timezone interpretation of the label, not an independent audit of the upstream aggregation code.

The stored grids are geographic, not exactly square 250 m/1 km cells. Retain their exact affine transforms from `earth_engine_metadata.json` and the TIFFs. The final/corrected products cover a smaller area than the raw radar and the terrain study area. Outside each raster's coverage is unavailable, not zero rainfall. Preserve the 1,721 masked raw-radar cells. The two fine grids each have 7,384 valid cells; raw radar has 5,041 valid cells.

## Provenance and limits

The attachment describes OPERA 1 km/5-minute radar merged with Weather Underground observations from 43 accepted stations. The bundled assets contain **daily totals only**. Neither the original five-minute radar series nor the individual station observation time series are bundled. The named upstream programs `radar_1km.py`, `radar_station_merge.py`, and `upload_to_ee.py` were referenced by the attachment but not supplied. Do not invent those programs, their QC thresholds, correction algorithm, interpolation uncertainty, or a time animation. The 250 m label is an output-grid description, not independently observed 250 m rainfall resolution.

The attachment's “raw radar overestimates ~4x” label is an unverified source claim. Preserve it in provenance if useful, but do not apply another factor of four or present it as a verified calibration. Use the already corrected/final products as supplied. This package validates data transfer and geometry; it does not independently validate the meteorological model or public redistribution rights. Preserve OPERA/Weather Underground attribution and check applicable source terms if publishing.

“Water supply” infrastructure points remain the earlier `type=2` category (40,994 points) within the unbundled infrastructure asset; they are distinct from rain stations and sewer routes. Do not infer pipes or connectivity from either point layer.

## App integration

- Add a rainfall section with final merged as default, corrected/raw as alternatives. Prefer one selected raster at a time so overlapping colours are not misread; keep an overall visibility and opacity control. Preserve terrain/route/green-area settings independently. Save rainfall selection, opacity, station filters and any display threshold in URL state.
- Use the source rainfall palette `f7fbff,c6dbef,6baed6,2171b5,08306b,54278f,e7298a`. Interpolate colours continuously, not seven discrete classes. Stable default scales: 0–30 mm final/corrected and 0–110 mm raw, with accurate legends and explicit endpoint clipping if needed. Rainfall has its own scale; never reuse the elevation normalization.
- Source rainfall display opacity is 0.7. Allow optional bilinear display smoothing and a native-cell view. Smoothing is display-only; statistics, click sampling and downloads must use native values and valid masks. It must not imply finer measured resolution or extend coverage.
- The attached script hides final rainfall at or below 0.5 mm for display. Implement this as an explicit optional visibility threshold, preserving the source default of 0.5 mm for final merged. Label it in the control/legend. The threshold must never remove real values from native readouts, statistics or exports; “hidden by display threshold” is distinct from NoData.
- Stations: accepted `qc='ok'` visible by default, rejected initially off and styled distinctly (e.g. red crosses). Show `station_id`, `rain_mm`, `qc`, and `rows` on click. Preserve rejection reasons and all records; never silently include rejected stations in fitting. Any master control must correctly reflect mixed child visibility; do not copy the attachment's inconsistent initial master state.
- Show native rainfall alongside elevation on click, clearly naming the selected rainfall product. Optional comparison values must each use that product's own transform/mask. Guard against stale asynchronous responses and distinguish valid zero, NoData, and errors.
- Summaries: compute min/max and area-weighted mean over valid native cells; volume is `sum(rain_mm / 1000 * cell_area_m2)`. Use geodesic/ellipsoidal geographic-cell areas or another documented appropriate area method, and report the valid coverage area and summary scope. A viewport/selection summary must define partial-cell treatment. Display thresholds must not change totals. Never use the footprint area as if all footprint cells were valid.
- Label the result **precipitation volume**, not runoff, sewer load, floodwater or flood depth. Rainfall depth alone does not establish hydrological flow, infiltration, drainage capacity or flood risk.

## Reproduce and verify

```bash
python -m pip install -r requirements-data.txt
python scripts/prepare_rainfall.py --out-dir build/rainfall
python scripts/verify_rainfall.py
```

`native_arrays/*.json` contains every stored raster value/mask plus pixel-coordinate bounds; `native_point_checks.json` contains 15 independent Earth Engine point queries. `prepare_rainfall.py` checks dimensions/orientation, writes Float32 COGs with -9999 NoData, verifies pixel/mask equality and computes WGS84 ellipsoidal summary statistics. The original script and the two existing scripts remain untouched.

For a future authorized refresh, run `earth_engine/read_rainfall_metadata.js`, then `read_rainfall_pixels.js` and `check_rainfall_samples.js` in a new unsaved Earth Engine script, capturing each JSON console result. `read_rainfall_pixels.js` embeds the inspected grid metadata for this snapshot; refresh those descriptors before reading a changed asset revision. Alternatively use an authenticated server-side API or native-grid export. No cloud batch export jobs, permissions changes, asset writes or publication were needed for this snapshot.

Official array retrieval semantics: https://developers.google.com/earth-engine/apidocs/ee-image-samplerectangle . Each band is sampled in its input projection; the specified default value represents masked/outside cells.
