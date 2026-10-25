# Data contract and provenance

## Original sources

| File or asset | Meaning | Evidence/status |
|---|---|---|
| `data/raw/vik_kanal_26_sofpr_20090000.geojson` | Supplied sewer route lines | 717 MultiLineString features; filename indicates 2009 source |
| Same filename with `(1)` suffix | Duplicate user upload | Byte-identical; kept, never add its features a second time |
| `data/raw/green_areas_26_sofp_20200518_a00bddf3-4189-4e65-8216-a8575de25e8c.geojson` | Supplied green areas | 64,962 MultiPolygon records; filename indicates 2020-05-18 source |
| Municipal DTM Earth Engine asset | Ground elevation | Source label SofiaPlan, listed valid at 2024-10-01; source survey/capture date not established here |
| Infrastructure point Earth Engine asset | Classified utility points | 322,025 records observed in Earth Engine; source temporal coverage not established here |

GeoJSON uses WGS84 longitude, latitude coordinate order (EPSG:4326); no explicit `crs` member was supplied. Do not reverse coordinates. Raw data remain byte-preserved. Keep Bulgarian text in UTF-8.

SofiaPlan references retained in the prototype: https://sofiaplan.bg/api/ and https://api.sofiaplan.bg/datasets/656 . Dataset redistribution/licensing text was not supplied in this handoff; do not invent a dataset licence or infer unrestricted redistribution merely from possession of files.

## Sewer attributes

Original properties include `object_id`, `id` (source UUID), `leg`, `legso` and source-reported `length_m`. Preserve all original attributes. Derivatives add:

| Field | Meaning |
|---|---|
| `source_id` | Original UUID; common across all/inside/outside representations |
| `source_length_m` | Unmodified original `length_m` value |
| `length_m` | Recomputed WGS84 ellipsoidal length of the selected geometry |
| `status` | `existing`, `planned`, or `open` |
| `zone` | `all`, `inside`, or `outside` |
| `source_year`, `mask_year` | Source labels 2009 and 2020 |
| Feature `id` | `<source_uuid>:<zone>` |

Status classification reproduces the prototype: `legso` containing Bulgarian `проект` is planned; otherwise containing `Открит` is open; otherwise existing. This is a classification of the supplied source, not a current condition assessment. Preserve `leg` separately, and do not silently overwrite this rule with a guessed field interpretation.

### Geometry and statistics

| Zone | Represented source routes | Total length (km) |
|---|---:|---:|
| All | 717 | 540.163013503 |
| Inside green areas | 543 | 137.858698851 |
| Outside green areas | 670 | 402.304314680 |

The sum of inside and outside lengths matches all-route length within 0.001 m in this build. Counts are not additive: a source route may cross both zones. Each zone feature may contain multiple disconnected line pieces. Do not call the feature count the number of individual pipe segments. Status totals: 464 existing, 250 planned, 3 open. Per-zone/status counts and lengths are in `data/derived/summary.json`.

For clipping, repaired nonempty green polygons form the mask; candidate polygons are unioned per route so overlapping green polygons do not duplicate route length. GEOS planar intersections are performed in WGS84 longitude/latitude to reproduce the prototype. Lengths use the WGS84 ellipsoid. Non-simple route geometries are split into their original constituent traversal segments before intersection, preserving multiplicity at overlapping/self-crossing paths. Do not dissolve route lines indiscriminately. A later switch to projected clipping should be documented and compared against this baseline with a justified tolerance.

Derived coordinates are regenerated at double precision. The packed Earth Engine prototype rounded clip coordinates to 1e-9 degree and lengths to 0.001 m; small last-digit differences are expected. Original raw coordinates are never changed.

## Green areas

All 64,956 nonempty source polygons participate in the mask. Six empty source records remain in the raw file and are listed in `summary.json`. One invalid polygon, source ID `866e1e3f-da40-4151-a219-81c6f66c942c`, is repaired with Shapely `make_valid` only in derived processing. Polygon holes and multipart features remain meaningful.

`green_intersecting_routes.geojson` has 2,175 polygons, with their original properties plus `geometry_repaired`. It is a display subset, not the complete green-area dataset. The old embedded prototype stored only geometry for this subset; this handoff restores source properties from the complete original file. Boundary-only intersections can include a polygon in the display subset even if it contributes zero positive pipe length.

Original properties include `object_id`, `source_`, `area_m`, `id`, `area_kv_m`. Their names/values are preserved. Do not infer a new meaning or unit for ambiguous fields beyond what the source establishes.

## Elevation

- Asset: `projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee`.
- Observed band: `b1`; renamed `elevation` by the prototype.
- Horizontal CRS: EPSG:7801, BGS2005 / CCS2005.
- Affine transform: `[1, 0, 299392, 0, -1, 4753611]`.
- Native cells: 1 x 1 m; vertical datum: Baltic 1982, EPSG:5786; elevations in metres.
- Mask source NoData, including -9999. No vertical datum shift was applied in the prototype.
- Current study rectangle: `[23.0, 42.4, 23.7, 42.95]` (WGS84). Default normalization is over valid DTM pixels in this rectangle.
- A browser click samples the native grid, not a coloured tile. Keep the scientific raster separate from RGB display products.

The supplied preview PNG states a **10 m working grid averaged from 1 m cells**, and its axes use **UTM 34N**. It is only a palette/relief reference. Do not use its plotting CRS, lower resolution, labels, or colours to reconstruct native elevation. Grid cell size does not establish vertical RMSE or survey accuracy.

## Infrastructure points

Asset: `projects/rivertracker-512606/assets/sofia_infrastructure_pps`. Point coordinates are not bundled. Expected category counts:

| `type` | Category | Count |
|---|---|---:|
| 1 | Unknown | 0 |
| 2 | Water supply | 40,994 |
| 3 | Sewerage | 70,790 |
| 4 | Collectors | 1,050 |
| 5 | Power network | 116,844 |
| 6 | Low-current network | 81,336 |
| 7 | District heating / steam | 10,928 |
| Missing/null | Unspecified in source | 83 |

Match numeric and string forms of type codes, as the prototype does. These points do not define pipe routes or physical network connectivity. Do not conflate the 717 route features with the 70,790 sewerage point records.

## Not established by these datasets

Pipe diameter, invert level, capacity, connectivity, operational condition, actual current pipe status, inlet/manhole hydraulics, time-resolved rainfall/runoff forcing suitable for a hydraulic simulation, soil infiltration, downstream boundary conditions, and hydraulic model validation are not established here. Green overlap alone does not demonstrate infiltration effectiveness or flood safety. Keep any future hydraulic analysis separate and explicitly sourced.

## Rainfall addition — 2026-10-25

The complete daily rainfall data and station properties are now included. `docs/RAINFALL.md`, `config/map_config.json` and `data/rainfall/summary.json` define the contract. All three rasters retain native EPSG:4326 transforms, Float32 rain_mm, and valid masks. Stations retain all 55 records, original IDs/properties, and QC reasons. Rainfall totals do not constitute hydrological runoff or a validated flood model. The original five-minute radar and station observation series are not included.
