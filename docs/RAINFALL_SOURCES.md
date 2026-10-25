# Rainfall source and quality audit

Audited 25 October 2026 using the complete supplemental handoff preserved at `handoff/rainfall_supplement/`. The original rainfall script, source COGs, station features, full native arrays, masks, Earth Engine metadata and point checks remain unchanged. No fresh Earth Engine authentication or query was used for this audit.

## What these data represent

These are **daily accumulated precipitation in mm for 27 June 2025, Europe/Sofia**, not mm/hour, runoff, sewer loading or floodwater depth. The local-day label corresponds to `[2025-06-26T21:00:00Z, 2025-06-27T21:00:00Z)`; the unavailable upstream programs prevent independently verifying how the original accumulation window was implemented.

The supplied script describes OPERA radar and Weather Underground station merging, naming `radar_1km.py`, `radar_station_merge.py` and `upload_to_ee.py`. Those upstream programs, five-minute radar frames and individual station time series are absent. Accordingly, the stated radar cadence, correction method and approximately fourfold raw bias remain source claims, not independently verified results. The final/corrected products must not receive another guessed correction. No five-minute animation or rainfall return period can be reconstructed from a daily total.

All raster assets use the project prefix `projects/rivertracker-512606/assets/sofia_rain_20250627/`. The files reproduce their stored native pixels and masks, not original pre-upload TIFF file bytes. Asset IDs end in their corresponding filenames without `.tif`; the observed band is `rain_mm`. Station asset: `wu_stations`.

## Verified grids and coverage

| Product | Native dimensions | Valid / masked cells | Valid area | Range |
|---|---:|---:|---:|---:|
| Final merged | 104 × 71 | 7,384 / 0 | 461.237756634 km² | 0.06267655–27.14878273 mm |
| Bias-corrected radar | 104 × 71 | 7,384 / 0 | 461.237756634 km² | 2.41311765–20.15553093 mm |
| Raw radar | 98 × 69 | 5,041 / 1,721 | 4,961.043603466 km² | 2.86369705–109.69969940 mm |

All three are Float32 COGs, EPSG:4326, one `rain_mm` band, with `-9999` NoData. Exact affine transforms, in the order `[a,b,c,d,e,f]`, are:

```text
final/corrected:
[0.003054851458076265,0,23.18,0,-0.0022457779374775422,42.76]
raw:
[0.010398141544071897,0,22.831742360561023,0,-0.010398141544071897,43.05713699491116]
```

The fine product bounds are `[23.18,42.600549766439094,23.49770455163993,42.76]`; raw bounds are `[22.831742360561023,42.3396652283702,23.85076023188007,43.05713699491116]`. Bounds do not establish valid coverage inside the raw mask. None is a complete municipality-wide rainfall surface.

The nominal 250 m and 1 km names describe products, not independently observed square metric resolution. Around each grid centre, the fine cells are approximately **250.38 m east–west × 249.48 m north–south**; raw stored cells are approximately **852 m × 1,155.10 m**. A 5 m terrain analysis or smoothed display cannot manufacture 5 m rainfall observations.

## Masks, zeros and station quality

Every valid raster cell matches the corresponding native-array Float32 value exactly, and every COG mask matches its snapshot. The supplied 15 separate point checks also match: 13 numeric values and two masked raw-radar locations. These are handoff evidence of the earlier acquisition; this audit did not re-query live Earth Engine or independently validate meteorological accuracy.

There are no exact zero-valued valid raster cells in this particular snapshot, but the application must still distinguish zero from missing. Of **55 unique station IDs**, **43 have `qc='ok'`** and **12 are rejected**. All station coordinates, original properties and QC reasons are retained. Six stations report zero, including accepted **ISOFIA682** at longitude 23.43, latitude 42.65 (`rain_mm=0`, `rows=589`). That is a valid recorded zero. Rejected **ISOFIA667** records 441.7 mm with `qc='implausible'`; it remains inspectable as rejected data. No new QC or fitting rule has been invented.

Final rainfall defaults to a 0–30 mm continuous colour range; corrected uses the same range, raw uses 0–110 mm. The source's optional final display threshold is 0.5 mm. Display thresholds and optional bilinear smoothing must not modify native samples, summaries, exports or mask coverage. Nearest native-cell sampling is authoritative. Rain stations, archived sewer routes and water-supply infrastructure remain separate datasets.

## Independently reproduced summaries

Each complete native geographic cell uses WGS84 ellipsoidal polygon area from `pyproj.Geod`. Whole-product summaries include only cells marked valid. There is no viewport partial-cell rule because these are full-product summaries.

```text
area-weighted mean = sum(rain_mm × cell_area_m²) / sum(valid_cell_area_m²)
precipitation volume_m³ = sum(rain_mm / 1000 × valid_cell_area_m²)
```

| Product | Area-weighted mean | Precipitation volume |
|---|---:|---:|
| Final merged | 11.1552023452 mm | 5,145,200.50449 m³ |
| Bias-corrected radar | 11.3354628056 mm | 5,228,343.43487 m³ |
| Raw radar | 31.4676812890 mm | 156,112,538.97481 m³ |

Independent per-cell area calculations agree with the supplied per-row computation within 0.00002 m³. Products have different coverage: their whole-product means/volumes cannot establish a correction factor. A future comparison must first define a common valid spatial support. These volumes are precipitation falling on the valid cells, with no deduction for infiltration, storage, interception or drainage.

## Recovered terrain reference

The complete supplement restores the original saved `Script1.js`, `Script2.js`, `shared/elevation_scale.mjs` and `data/reference/elevation_quantiles_whole_area.json`. The `quantiles_m` field contains all 201 P0–P100 values in 0.5-percentile increments, for the same municipal terrain asset and study rectangle `[23,42.4,23.7,42.95]`, using 60 m display statistics. Its inverse-mapped legend is approximately **501.0, 574.3, 808.3, 1062.6, 2278.8 m**.

The earlier local approximation had the same scope and continuous 80% percentile / 20% linear-height formula; its largest quantile difference is 1.7365625 m. Restoring the full supplied curve affects whole-area colours and legend only. The previous generated curve is archived; native 1 m elevations, local-fit behaviour, 5 m P/C/S scores, water exclusions, exposures and other existing functions remain independent. Five rounded legend labels are never used to reconstruct a curve. The supplied JS module has different API names and flat-terrain representation, so its interfaces must not be copied blindly over the existing app API. Both normalizations are continuous, not 201 elevation classes.

## Verification and reproduction

The supplied checks ran first and passed: 52 manifest-listed files verified; handoff data invariants passed; all rainfall cell/mask checks and 15 supplied point checks passed; five supplied elevation-scale tests passed. The manifest verification passed again after this read-only audit. The 53rd file is the manifest itself. The installed rainfall files and preserved supplement files have identical SHA-256 values.

From the app directory, run the preserved original checks:

```text
python handoff/rainfall_supplement/scripts/verify_handoff.py
python handoff/rainfall_supplement/scripts/verify_rainfall.py
node --test handoff/rainfall_supplement/tests/elevation_scale.test.mjs
python scripts/prepare_rainfall_cache.py
python scripts/restore_reference_scale.py
```

The latter two prepare derived caches/reference display settings; they do not modify original rasters or station records. See `test-artifacts/rainfall_handoff_validation.json` for the full independent profile, exact transforms, QC breakdown, hashes, samples, summaries and the pre-restoration curve comparison. Public redistribution rights for upstream OPERA/Weather Underground products were not established by the supplied handoff; the audit does not invent a licence.
