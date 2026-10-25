# Sofia terrain, sewer & rainfall explorer

A working local React + TypeScript + MapLibre application with a Python spatial
API. It uses real supplied geometries, the real municipal 1 m DTM, and all
322,025 infrastructure point records. Version 1.9 adds area selection for
hypothetical pipe-blockage comparisons, a rainfall slider with terrain-based
local ponding estimates, river-proximity filters, the requested fully absorbing
green-area scenario, and neutral grey filled buildings. The continuous ponding heatmap and
grouped layer switchboard remain independently available. It retains the categorical evidence-review map, historical
mechanism/certainty filters, official assessment context, AGKK cadastral
buildings and every legacy P/C/S mode. It retains the supplied 27 June 2025 daily
rainfall products and stations and the complete original Earth Engine whole-area
colour reference. Imperviousness is absent from the map.

The requested source repository is
[YoanTrendafilov2002/DrainCheck](https://github.com/YoanTrendafilov2002/DrainCheck).
For Git checkout setup, the included-data policy and future tested updates, see
[the GitHub workflow](docs/GITHUB_WORKFLOW.md). Large local originals and caches
remain preserved outside Git; a source checkout needs `pnpm build` and data
preparation rather than an already generated `dist/` directory.

## Run on this computer

Double-click **Run_Sofia_App.cmd**. It uses the existing Python environment,
starts the server at **http://127.0.0.1:8040**, and opens the app when ready.
Keep the terminal open. Press Ctrl+C in it to stop.
If this app is already running, the launcher reopens it instead of starting a
second server on the same port.

The production frontend is already built in `dist/`; Node is not needed just
to run it. If port 8040 is occupied, run the command below with `--port 8041`.

```powershell
Set-Location -LiteralPath 'C:\Users\Yoan\Documents\Codex\2026-10-24\hp\outputs\sofia_explorer_app'
& '..\..\work\hydro_env\Scripts\python.exe' 'scripts/serve.py'
```

The native raster is read from the existing sibling file:
`../sofia_dtm_2024_1m_gee.tif`. It is not copied into the source ZIP or modified.
The archives, original raw vectors, duplicate sewer file, original point CSV and
complete rainfall supplement are preserved. Existing terrain, sewer, green,
point, P/C/S screening, hidden water exclusion, exposure, historical-evidence
and building-source availability functions remain available. Real screenshots
and verification records are in `test-artifacts/`.

## Fresh installation / another computer

Use Python 3.12 and a current Node release (22 or newer) if rebuilding the UI.
For the prebuilt application, only Python is required.

```powershell
python -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-lock.txt
Copy-Item -LiteralPath '.env.example' -Destination '.env'
```

Put the real native DTM at `data/external/sofia_dtm_2024_1m_gee.tif`, or change
`SOFIA_DTM_PATH` in `.env` to its actual path. It must be the full horizontal-CRS
1 m municipal raster: 51,722 columns × 54,343 rows, Float32, EPSG:7801, affine
`[1,0,299392,0,-1,4753611]`, NoData `-9999`. The adapter supports local GeoTIFFs
and COGs. The already verified local input is a tiled GeoTIFF. A preview PNG,
another DEM, or a raster with a different grid is rejected.

```powershell
& '.venv/Scripts/python.exe' 'scripts/restore_source_bundles.py'
& '.venv/Scripts/python.exe' 'scripts/prepare_data.py'
& '.venv/Scripts/python.exe' 'scripts/prepare_rainfall_cache.py'
& '.venv/Scripts/python.exe' 'scripts/restore_reference_scale.py'
& '.venv/Scripts/python.exe' 'scripts/serve.py'
```

The full local source package includes real raw vectors/points, prepared geometries, native
rainfall COGs/stations, and the spatial index/display/statistics cache. It excludes the 1.39 GB native DTM,
dependencies and credentials. Without a native DTM, the real vector map still
runs and elevation is explicitly unavailable; there is no substitute surface.
The Git repository keeps permitted source inputs and small metadata but excludes
generated indexes, native terrain, bulk cadastral geometry and archives. See the
GitHub workflow for its separate checkout/bootstrap steps. Run the curve restorer
only after the actual native DTM is present.

The original 53.16 MB green-area GeoJSON is stored in Git as a **14.1 MB lossless
gzip bundle**. `restore_source_bundles.py` verifies compressed and decoded hashes
and sizes, then restores its exact original bytes before data preparation. It
leaves an existing matching original untouched and refuses to overwrite a
different file. The local original and all geometry remain unchanged; only the
Git storage representation is compressed.

## Development

```text
pnpm install --frozen-lockfile
pnpm build
```

For development, run the API on port 8040 and `pnpm dev` in another terminal;
Vite proxies `/api` locally. `pnpm-workspace.yaml` permits the required esbuild
installation script. The exact frontend dependency graph is in `pnpm-lock.yaml`;
the Python dependency closure is in `requirements-lock.txt`.

```text
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8040
pnpm dev
```

## Using the map

- Open **Explore**. Routes start in **Inside green**, with existing, planned
  and open statuses enabled. Switch exactly one zone at a time. Statistics
  cover the full selected dataset, not just visible tiles.
- Existing routes are cyan, planned routes dashed magenta, open channels yellow.
  Click a route to inspect its original properties and computed section length.
  **Export selected sections** returns full-precision geometry and source IDs.
- **Whole study area** colours remain fixed while panning. **Fit this view**
  measures local terrain statistics; **Reset** restores the whole-area curve.
  Auto-fit is explicitly opt-in. A compact warning with Fit/Reset remains visible
  when a locked local view moves outside its fitted area.
- The continuous nine-colour legend uses inverse-mapped metre ticks. A 201-point
  curve defines a continuous transform, not 201 elevation bands. Real height
  values remain unchanged. Native readouts are 1 m; whole-area colour statistics
  are 60 m, local statistics normally 10 m (coarser if the pixel cap requires it).
- **Layers** provides a grouped switchboard with independent controls and
  source-specific symbols for flood screening/evidence, terrain, mapped assets
  and supplemental weather. Detailed opacity, filter, green-display,
  infrastructure-category and basemap controls remain available. Green display
  starts at **All green areas**, showing the complete indexed source without
  changing the computed route partition. Attribution remains on the map.
- **Flood focus** enables the ponding heatmap, hides elevation colours, enables
  hillshade and selects all green polygons. **Terrain focus** hides screening
  and enables elevation colours and hillshade. Both preserve camera, rainfall,
  historical/assessment visibility, route statuses and asset filters; they do
  not reset analysis values or change source data.
- Point data loads only when enabled, through viewport vector tiles. No route
  connectivity or capacity is inferred from those points.
- **Share view** copies the URL with map position, zone, statuses, layers,
  opacity, colour-scale ID, auto-fit, basemap and rainfall controls. Local scales persist on the
  same server; a link to an unavailable or old-revision scale reports that state.
- On smaller screens the controls start collapsed. Native NoData, loading and
  request failures are distinct. Retry a failed map request explicitly; errors
  are not silently presented as valid terrain.

## Area-selected blockage scenarios and green absorption

Open **Scenario** and use **Draw pipe selection area** in the blockage scenario controls. Draw a
rectangle on the map, then inspect the actual source routes intersecting it.
Existing routes are selected initially; toggle individual existing source IDs
before calculating. Planned and open-channel routes are reported as context and
do not contribute functioning pipe capacity. Selection is independent of the
inside/outside-green display partition and uses each original route once.

Enter event rainfall (default 30 mm), duration (60 minutes), assumed drainage
removal (15 mm/hour), blockage (100%), influence distance (50 m) and runoff
coefficient (0.9). River proximity starts at 100 m as a separate contextual
threshold. The removal rate is an **area-equivalent assumption**, not a
measured or estimated capacity for each pipe. The calculation uses genuine
aligned 5 m terrain, the full mapped green union and actual selected route
geometry. It does not route water or solve pipe-network hydraulics.

Effective runoff is rainfall multiplied by the entered coefficient. Baseline
potential excess is the positive remainder after assumed removal over the event
duration. Blockage reduces removal only within the chosen buffer of selected
existing route sections. Outside that influence, the clogged view equals the
baseline. Buffer overlaps are unioned, never counted twice. The 0-100 terrain
score is not mixed numerically with millimetres of scenario runoff.

Adjust the rainfall slider to recalculate the same area and pipe choices.
Compare estimated **Baseline**, **Clogged** and **Additional** local ponding
depths in metres, or the retained excess-runoff views in millimetres. Each view
family uses a common colour scale.
When visible, the scenario replaces the base terrain-risk raster as the active
warm heatmap; area, selected pipes, buildings, green areas and evidence can still
appear together. Buildings have grey filled shapes, the area uses a cool blue
fill and boundary, and warm colours retain their single active risk meaning.
Downloads contain six original-grid bands in a separate GeoTIFF: the three
runoff fields followed by three estimated local storage-depth fields. A separate
JSON record retains parameters, source IDs, assumptions and statistics.

The depth estimate fills independent connected positive-depression components
using actual ground elevations, capped by the minimum recorded fill surface.
It uses only runoff generated within each component. Overflow and runoff on
zero-fill land are explicitly unallocated; water is not routed from the whole
rectangle into one depression. Potential boundary truncation is flagged. The
river filter distinguishes river-adjacent possible mixed influences from land
away from the supplied river geometry. Distance does not establish flood cause;
filtering leaves full-area statistics and downloads unchanged.

The user-requested **green absorption** assumption starts enabled. All 64,956
nonempty green polygons absorb all rainfall and are excluded from scenario risk
areas, even if their display layer is hidden. This is a scenario assumption,
not measured permeability or unlimited real-world infiltration. The original
unmasked P/C/S values remain preserved and inspectable. Water, uncertain terrain
and outside coverage remain explicit exclusions.

Scenario outputs report eligible area, green exclusion, affected area,
additional potential unremoved volume and affected area with P at least 70.
They are **not validated flood forecasts, flood probabilities or current clogging diagnoses**.
No selected existing route means zero additional effect. All parameters,
assumptions, source IDs and revisions are retained in the result record. The
scenario is limited to 25 km2 and 1,000,000 cropped grid cells; draw a smaller
or more compact area if either bound is exceeded.

Read [the full risk calculation guide](docs/RISK_CALCULATION_GUIDE.md), also available as a [12-page PDF](docs/DrainCheck_Risk_Calculation_Guide.pdf), for input
provenance, every equation and unit, a hand-worked example, a genuine local
example, sensitivity, masking rules and reproduction. The guide distinguishes
the scenario's entered event rain from the independent daily rainfall overlay.

## Performance

Hidden layers stop requesting tiles, point tiles contain the selected categories,
and a bounded persistent tile cache reuses completed rendering across visits and
API restarts. Static assets and vector tiles support gzip. Native 1 m readouts,
5 m terrain analysis and original data are unchanged. See
[performance changes and measured limits](docs/PERFORMANCE.md), including real
browser request checks and byte-for-byte raster verification. New uncached areas
still incur their first-render cost.

## Inputs actually used

| Input | Loaded source | Coverage / provenance |
|---|---|---|
| Sewer routes | Real recovered GeoJSON; original local sewer file matched the truncated entry's CRC | 717 original routes; source 2009 |
| Green mask | CRC-verified raw handoff GeoJSON | 64,956 nonempty polygons; 6 empty originals retained; 1 invalid geometry repaired only in processing copy; source 2020 |
| Green display subset | Prepared handoff GeoJSON | 2,175 polygons intersecting routes |
| Native terrain | Existing verified `sofia_dtm_2024_1m_gee.tif` | 1 m grid; Baltic 1982 heights; catalogue valid at 2024-10-01 |
| Infrastructure | Existing original local CSV, copied unchanged | All 322,025 rows; 83 without type |
| Whole-area colour curve | Complete supplied Earth Engine snapshot | All 201 quantiles; same study rectangle and 60 m display-statistics scope; previous local approximation archived |
| Daily rainfall | Three supplied numeric native COGs | 27 June 2025 local day; final/corrected nominal 250 m products and nominal 1 km raw radar; distinct EPSG:4326 grids/masks |
| Rain stations | Complete supplied station GeoJSON | 55 original station records; 43 accepted / 12 rejected; original QC retained |
| Cadastral building context | National AGKK INSPIRE source snapshot | 334,033 source records / 334,018 distinct non-null cadastral IDs intersecting the study rectangle; source geometry and attributes preserved; no inferred heights |
| Historical observations | Sofiaplan 2021 drone survey | 136 actual mapped northern flood-zone polygons; individual flood mechanisms unknown; incomplete survey coverage |
| Official assessment context | Municipal atlas and draft PFRA sources | Six supplier high/medium/low assessment polygons, plus 23 draft 2026 reach/identifier features; separate from observed inundation |
| Evidence review | Separate aligned 5 m categorical derivative | Existing ponding signal, actual historical footprints and potential cadastral footprint intersections; original P/C/S and native heights unchanged |

The first handoff ZIP was truncated; its original extraction receipt remains in
`test-artifacts/verification.json`. The later complete supplement resolves the
missing source tail. All **53 files** are preserved unchanged under
`handoff/rainfall_supplement/`, including both saved EE scripts, the portable
scale module, all 201 original quantiles, acquisition/data documentation,
rainfall data and original verification scripts. Its 52 manifest-listed entries
pass their original size/SHA-256 checks; the manifest itself is the 53rd file.
The original archive is retained alongside this preserved directory.

The default whole-area curve now uses the genuine supplied snapshot. It is a
continuous 80% percentile / 20% linear-height display transform; native heights
are unchanged. The previous locally estimated curve is retained in
`data/reference/previous_whole_scales/`. Reapply the reference from the preserved
source without changing the scientific raster or local-fit implementation:

```text
python scripts/restore_reference_scale.py
```

The restorer validates the exact source asset, scope and all 201 finite ordered
values, preserves the original snapshot and backs up the previous generated
curve. Five rounded legend labels are never accepted as a substitute. The two
saved EE scripts and the rainfall attachment remain reference originals; the
rainfall script's older elevation stretch is not reinstated. This computer
already has the verified terrain, points and rainfall data; no new installation,
Earth Engine login or cloud export is required to run the app.

## Daily rainfall

Use the independent rainfall controls to show the final merged radar/station
product, bias-corrected radar or raw radar for **27 June 2025, Europe/Sofia**.
Values and legends are accumulated **mm per local day**, not mm/hour. Final
merged is the default product; its optional 0.5 mm visibility threshold affects
display only. Fine-product legends span 0–30 mm and raw radar spans 0–110 mm.
Rainfall is supplemental: the raster and station groups start off. When enabled,
its default opacity is 30%, with hillshade, screening and vector layers above it.
Rainfall inspection details are collapsed while the overlay is off; selecting a
rain station exposes its full readout. Explicit saved display choices still apply.
Visibility, opacity, native-cell/bilinear display preference, threshold and station
filters are independent of terrain and routes and are retained in shared URLs.

All 55 station records remain available: 43 accepted by the supplied QC and 12
rejected, including their reasons and original values. Accepted stations start
visible and rejected stations hidden. A real accepted station reports exactly
0 mm; that remains a valid reading. Native rainfall sampling uses the selected
product's original grid and mask. Smoothing cannot create additional measured
resolution, alter statistics or extend valid coverage.

Summary cards use full valid native-cell coverage and WGS84 ellipsoidal cell
areas. They report area-weighted mean and **precipitation volume**, not runoff,
floodwater or sewer load. Final/corrected products cover approximately 461.24 km²;
raw radar has approximately 4,961.04 km² of valid cells and 1,721 masked cells.
Their different coverage prevents interpreting whole-product totals as a bias
correction factor. Neither the upstream five-minute series nor processing/QC
programs are supplied, so no time animation, guessed correction or event flood
simulation is made. See [rainfall sources and audit](docs/RAINFALL_SOURCES.md).

Rebuild the derived rainfall summaries, or rerun the original complete-handoff
checks, from this directory:

```text
python scripts/prepare_rainfall_cache.py
python handoff/rainfall_supplement/scripts/verify_handoff.py
python handoff/rainfall_supplement/scripts/verify_rainfall.py
node --test handoff/rainfall_supplement/tests/elevation_scale.test.mjs
```

## Validation

```text
python -m pytest tests -q --junitxml=test-results.xml
pnpm test
pnpm build
```

The v1.7 baseline passed **214 Python tests and 28 frontend tests
(242 total)**. Later updates run the complete commands above and record their
actual counts and production-build result in the current verification receipt;
older results retain their original scope. The three supplied validation flows also pass,
including all rainfall pixels/masks, the 15 supplied point checks and five
original elevation-scale tests; these are separate checks, not added again to
the application-suite total. Current integration results are recorded in
`test-results.xml`, the frontend test output and
`test-artifacts/rainfall_handoff_validation.json`. Older performance
timing receipts retain their original measurement scope; see
[current checks and historical performance measurements](docs/PERFORMANCE.md).

The integration tests check actual geometry partitioning against the full mask,
traversal lengths, all filter combinations, exports, polygon holes/multipart
geometry, point totals, native sampling, source NoData, rejected preview images,
transparent uncovered tiles, nonlinear legend inversion, revision handling and
local-fit caching. Frontend tests cover URL state and stale/cancelled requests.
Browser checks cover actual rendering, route inspection, filters, local colour
fit, scale locking/reset, optional points, and responsive controls.

Baseline route checks:

| Zone | Source routes represented | Length |
|---|---:|---:|
| All | 717 | 540.1630135 km |
| Inside green | 543 | 137.8586989 km |
| Outside green | 670 | 402.3043147 km |

Counts overlap across zones; lengths partition within numerical tolerance.
This partition uses the union of all 64,956 nonempty green-source polygons;
**25.52%** of total source-route length lies geometrically inside them. It is
not a measure of green-area drainage, infiltration, sewer capacity or clogging.
The former 2,175-polygon display subset is not the partition mask.
The Pluvial tab offers a continuous ponding heatmap, categorical evidence review
and the original analyst-defined terrain screening and infrastructure overlap. Daily rainfall is
a separate observed-product context layer; it does not calibrate or alter P/C/S
scores. There is no validated event
flood model, measured pipe capacity, invert or connectivity. The separate v1.9
blockage tool uses editable, explicit assumptions; it does not supply those
missing measurements.
The source dates do not establish current field conditions. Native 1 m spacing
does not establish centimetre vertical accuracy.

## Architecture and deployment

See `docs/ARCHITECTURE.txt` and `docs/DEPLOYMENT.txt`. The app runs locally;
publishing its source to GitHub does not deploy the API or upload ignored native
data. No paid infrastructure was provisioned. The app server uses local
loopback; the optional public basemap/font
assets are fetched by the browser. Choose **No external basemap** for a map
without that external tile dependency.

## Flood susceptibility heatmap and distinctive layers

Open **Layers** and choose **Flood focus**, or open **Pluvial**, select
**Flood susceptibility heatmap** and enable **Show flood susceptibility heatmap**.
Heatmap is the selected mode for a fresh or unspecified map link; the overlay
still starts off. Explicit saved categorical and legacy mode choices remain
unchanged.

The heatmap continuously colours the existing **ponding P** descriptor
(`depression_percentile`, source band 6) on its original 5 m grid. Colours run
from faint amber through orange/red to deep purple as P increases from 0 to 100.
This is a colour interpolation, with no kernel-density estimate, averaging of
neighbouring scores, new model weights or change to the stored raster. Display
tiles and final heatmap rendering use nearest source cells, preserving the
water mask and uncertainty boundaries. Grey denotes known terrain with an
unassigned score; mapped water and outside coverage stay transparent. A valid
P of zero is also deliberately transparent in this view, so the inspector
distinguishes a low signal from excluded/missing data. Neither means safety.

Clicking the heatmap reads the original P value, not a colour-derived estimate
or the combined S score. Infrastructure exposure uses the original ponding
classes. The existing raster download retains its original P/C/S bands and
explicit water flag; the heatmap creates no replacement numerical risk product.
Elevation Fit/Reset affects elevation colours only. The heatmap describes
relative terrain susceptibility, without calibrated flood probability, event
water depth or expected damage.

Layer styles distinguish their source meanings: warm heat colours for ponding,
blue survey boundaries for observed flooding, separate ordinal assessment
outlines/reaches/identifiers, grey filled cadastral buildings and green land-cover
boundaries. A selected scenario area uses cool blue styling alongside the warm
active risk field. Existing, planned and open sewer routes retain cyan, dashed magenta
and yellow status colours, with dark casings for contrast. When screening is
visible, green fill becomes lighter while its boundaries remain visible;
this styling does not remove green polygons or change their route partition.
Rainfall keeps its independent scale and controls. These layers can be compared
without treating their colours as one shared numerical index.

## Evidence review and legacy pluvial screening

Open **Pluvial**, choose **Refined evidence review · categorical** and enable
**Show evidence review**. This categorical view remains selectable separately
from the continuous heatmap. The separate 5 m review raster combines the existing ponding P
categories with actual historical footprints and potential cadastral footprint
intersections. On eligible land, historical evidence takes category priority;
building intersections distinguish potential exposure. Water, uncertain terrain
and outside-coverage states remain explicit. These are inspection categories,
not a numerical flood-risk scale, predicted damage or calibrated probability.
The original P/C/S raster, native 1 m heights, terrain colours and exports remain
unchanged. **Legacy depression storage potential**, **Legacy combined terrain**
and **Legacy runoff concentration** remain independently selectable.

**Past flooding** shows the 136 observed 2021 survey polygons, with mechanism and
certainty filters and **Prioritise historical evidence visually**. Observation
is documented; all individual polygon mechanisms currently remain unknown.
Filtering does not invent a classification, and stronger historical styling does
not add points to P/C/S or change the stored review raster. Saved filters that
have no matching classification report that state rather than substituting data.
The separate **Official assessment areas / reaches** overlay contains six
municipal high/medium/low polygons and 23 draft PFRA context features published
in 2026: 19 river-assessment lines and four schematic city/reservoir identifiers.
Supplier levels remain ordinal labels. These prospective assessment features
are not the 136 observed flood footprints, event locations or buffered flood
extents, and do not silently become numeric scores.

At the user's request, input dates are treated as compatible for this combined
review scenario. Source dates, unknown currency and spatial gaps remain visible.
This assumption does not expand rainfall coverage: final/corrected fine products
end at latitude 42.760000, south of the 2021 survey polygons, while the wider raw
radar has its own valid footprint and coarser grid. Rainfall remains supplemental,
off by default and at 30% opacity when enabled. A daily total does not provide
short-duration intensity or prove that the 2025 rain caused 2021 flooding.

Sewer proximity, line overlap and point density identify mapped inventory to
inspect; they establish neither operating capacity nor current clogging. The
official register separately reports sewer surcharge/garage entry and
river-outfall backwater at textual locations. Generic restriction codes can
refer to rivers or sewers; no precise incident geometry or blockage probability
is inferred. Green polygons supply geometric context, without an assumed
infiltration benefit. See [actual-data refinement findings](docs/INDEX_REFINEMENT_ANALYSIS.md)
and [mechanism/source review](docs/FLOOD_MECHANISMS_AND_REFINEMENT.md).

After restoring the verified terrain-score raster, water mask, complete AGKK
index and the 136 validated historical polygons with matching metadata, run:

```text
python scripts/acquire_flood_assessment.py
python scripts/prepare_review_priority.py
```

Both commands use application-relative paths and take no command-line flags.
The first verifies/reuses preserved public-source downloads or restores the
matching assessment snapshot, retaining raw/native geometry, a validated
full-precision copy and a separate 1 m simplified browser copy. It refuses a
changed download when a preserved checksum receipt exists. The second reads the
real terrain/water/history/cadastral prerequisites and creates only the separate
categorical derivative and provenance. A fresh Git checkout needs these excluded
local data restored first; metadata alone does not supply them. Source licensing
and publication limits remain in the source guides.

## Legacy terrain screening

Open **Pluvial**, select **Legacy depression storage potential** and enable
**Show terrain screening**. Compare the experimental combined and
runoff-concentration layers. Click a location for its real native
1 m height, 5 m factor values and relative scores. The index stays fixed when
elevation colours are fitted to a view. Grey means uncertain terrain; transparent
means outside coverage or an automatically excluded mapped-water cell. These
states are not low scores. No score establishes safety.

Mapped open-water polygon interiors are excluded automatically from pluvial
screening, without a visible water overlay or another layer switch. The panel
reports mask area/cells, the Sources tab records provenance, and water clicks
explicitly report **Existing mapped water — excluded from pluvial screening**.
The underlying elevation/basemap can remain visible through the transparent
screening layer. Water bodies and nearby banks can still flood; land beside
mapped water remains eligible for screening. See
[open-water sources and preparation](docs/OPEN_WATER_SOURCES.md).

This is an **unvalidated terrain-susceptibility screen**, not annual flood
probability, event water depth, a forecast or expected damage. The primary
evidence is linked in the app and documented in `docs/PLUVIAL_EVIDENCE.md` and
`docs/pluvial_evidence.json`. Official Sofia and NIMH reports establish local
rainfall-related flooding, but their incomplete incident locations and coverage
were not used to calibrate or validate the map.

The fixed analyst rule is:

* P = 100 × percentile rank of positive geometric depression-fill depth; zero where
  depth is zero.
* C = 100 × sqrt(rank(contributing area) × [1 − rank(slope)]).
* S = max(P, C).

Ranks are fractions from 201 quantiles of every fourth row/column on the real
5 m grid (a deterministic 20 m reference sample). The reference covers the
available municipal DTM, including mountains, not only the urban footprint.
Classes at 50/70/85 are analyst display cutoffs. The app also compares exposure
at 70/80/90. These choices are transparent hypotheses, not published validated
weights or calibrated flood thresholds. A deep depression is potential storage,
not a prediction of water depth or a proof of higher flood likelihood.
Contributing area can identify river corridors as well as rainfall flow paths.

All 322,025 point **records**, including 83 with missing category, and all 717
archived full routes are joined separately to each terrain pathway. The selected
map mode controls the displayed exposure counts and class areas. Counts are not
unique damaged assets. Route lengths use original WGS84 geodesic segment lengths,
assigned by midpoint samples at <=2.5 projected metres; their class assignment is
approximate at 5 m cell boundaries. Historical planned lines are not assumed
operational. Exposures are independent of display/route filters. Green polygons
provide context, without an assumed infiltration benefit. Imperviousness remains
excluded as requested; absent input bands are not treated as zero imperviousness.

Reproduce from the previously verified real terrain derivatives:

```text
python scripts/prepare_pluvial.py --source ../sofia_pluvial_demo/sofia_pluvial_inputs_5m.tif --native ../sofia_dtm_2024_1m_gee.tif
python scripts/prepare_open_water.py
python scripts/prepare_pluvial_exposure.py
pnpm build
python -m pytest tests -q --junitxml=test-results.xml
pnpm test
```

The first command verifies the source hash, grid and missing optional bands,
copies the first five terrain factor bands unchanged, calculates scores in new
bands, checks all copied factor pixels, score ranges and original source hashes,
and writes `data/cache/pluvial_provenance.json`. The app downloads a separate
land-screening GeoTIFF containing masked P/C/S scores and an open-water flag,
alongside point/route overlap CSVs and the evidence register. The original
terrain-factor/screening raster remains unchanged. Excluded water has no score;
it is not assigned zero. Inventories retain its point records and route lengths
in the separate **Excluded open water** bucket, outside ranked land classes and
threshold counts.
The verified earlier derivation script and routing receipt are preserved under
`data/provenance/`; they describe priority filling, strict-downhill D8 and
equal-height BFS routing, including conservation and boundary checks. No terrain
preview image is used in any calculation. The packaged screening raster contains
the actual five input factors and three derived scores; runtime needs no
authenticated Earth Engine access or new downloads. To reproduce the separate
real mapped-water exclusion, use `python scripts/prepare_open_water.py` and the
remaining preparation steps in [the source guide](docs/OPEN_WATER_SOURCES.md).
Acquired originals are preserved; refreshing the source is explicit.

To upgrade this screen into a calibrated hazard/risk model, obtain local storm
hyetographs or IDF rainfall, drainage/inlet/culvert geometry and capacity, terrain
accuracy and current urban barriers, spatial flood observations and coverage,
then calibrate and validate on separate events. Asset vulnerability and value are
also required for damage/loss risk.

### Routing structure found during real-data verification

The real city-window contributing-area raster contains pronounced diagonal and
parallel bands. The experimental concentration rule amplifies those D8/faceted
terrain patterns; in the inspected window, over 97% of combined scores >=85
occur at cells with zero depression depth. These are not verified physical
pluvial flood hotspots. The categorical review uses the ponding pathway as its
terrain ingredient; both legacy flow-based modes remain experimental, with a
visible warning.
See `docs/PLUVIAL_ROUTING_LIMITATIONS.md` and its reproducible diagnostic receipt.
The original raster has not been blurred or altered to hide the patterns.
Alternative flow-routing methods and independent survey/event observations are
needed to assess them. Even depression storage is not an event likelihood model.

The requested Water Hackathon repository could not be cloned: public Git access
returned HTTP 401 and the normal credential helper also failed to load a local
.NET dependency. No repository contents were incorporated. Exact attempts and
the remaining review scope are in `docs/WATER_HACKATHON_REVIEW.md`.

## Cadastral building context

**Layers → Cadastral buildings** independently displays the national AGKK
INSPIRE cadastral snapshot acquired on 25 October 2026. It contains **334,033
source records**, representing **334,018 distinct non-null cadastral IDs**.
Record count is not a count of independently verified unique physical buildings.
The query selects polygons intersecting `[23,42.4,23.7,42.95]`; this study rectangle
is not Sofia's administrative boundary. Whole source polygons at its edge are
retained. Tiles load only when enabled, from **zoom 13**.

Click an outline to inspect its cadastral identifier and source properties.
Compact display tiles retain a provenance link to the original source batch;
inspection restores all original attributes and verifies the batch checksum and
identifier join. Downloads retain full-precision geometry. There are no measured
above-ground heights in the app contract, so floor counts are preserved without
invented extrusion heights. These outlines leave terrain, rainfall, water
exclusions, legacy P/C/S and legacy exposure calculations unchanged. Their actual
footprints also identify potential cell overlap in the new review categories;
this does not establish building damage, thresholds or hydraulic barriers.

The service's survey date and synchronization with operational KAIS are not
established. Complete retrieval of its queried object IDs does not prove current
physical-building completeness. AGKK's public-access statement and Tariff 14
usage constraints remain explicit; no unrestricted reuse licence is invented.
See [national source and verification](docs/AGKK_CADASTRAL_BUILDINGS_SOURCES.md).
The separate 265,216-record municipal archival plan remains preserved as an
off-map reference, with [its own source notes](docs/CADASTRAL_BUILDINGS_SOURCES.md).
The original Digital Twin availability, historical survey, rainfall, routes,
infrastructure and terrain controls remain independent and available.

## Building context

The requested target is the **current whole-Sofia Digital Twin service**. At this
verification, requests to the official GATE CityLab viewer and related service,
including browser navigation, timed out before an HTTP response. No full-city
geometry was acquired, so the main building layer remains unavailable. The
failure was a **network timeout**, with no sign-in or permission-denial response;
it is not evidence of a permission block. The separately preserved 1,800 Lozenets
research roof outlines are not substituted for the requested whole-city model.
See [source scope and connection evidence](docs/DIGITAL_TWIN_BUILDINGS_SOURCES.md).

**Layers → Buildings context** independently controls the prepared source building
outlines. The layer is enabled by default when available and only
requests tiles from zoom 13 within its supplied coverage. **View coverage** moves
to that verified extent while retaining the selected layers, filters and map
orientation. The source name, date, licence, feature count and coverage limits
are listed in **Sources**; the supplied extent must not be mistaken for a
citywide building inventory. The exact publication is identified in Sources:
GATE research building/roof outlines must not be described as the current live
Digital Twin model or assumed to be surveyed ground-level footprints.

Source building shapes are shown with a neutral grey 2D fill and outline. The optional **3D using source heights** control is
offered only when the source confirms heights in metres above ground. Features
without a valid source height remain 2D outlines; no height is guessed. Clicking
a building shows its source properties separately from the native 1 m ground
elevation. Building visibility and 3D preference are included in shared URLs.

Buildings provide spatial context only. They do not modify the DTM, the 5 m
hydrology or the pluvial scores, and are not assumed to be impermeable flow
barriers, blocked drains, vulnerable assets or predicted damage.

Reproducing the separately preserved research subset is optional preprocessing,
not an app runtime requirement or a full-city acquisition. Use an environment
with the app's geospatial dependencies plus the pinned Shapefile reader:

```text
python -m pip install pyshp==3.1.6
python scripts/prepare_gate_research_buildings.py
```

The script validates the preserved original files and rebuilds only the
separately named 2D research outputs. It does not promote them into the requested
Digital Twin layer or invent building heights.

## Official historical flood map and reports

Open **Sources → Historical flood evidence → View official flood map (PDF)**.
The preserved Danube Basin Directorate map is an official Sofia PFRA context
map at 1:150,000 from the **2022–2027 cycle**. Its orange/red historical-event
symbols identify past-flood locations/counts. Blue hatching and river corridors
identify areas/types selected for hazard and risk analysis; they are not mapped
observed inundation extents.

The separate, newer **draft PFRA 2028–2033** register was published for
consultation on 14 August 2026. The app retains 19 Sofia source rows representing
15 event IDs, dated 2020–2024 within a parent register for 2020–2025. Source
mechanisms are preserved: 14 pluvial rows, two mixed pluvial/river rows and three
mixed pluvial/infrastructure rows. Inspect original descriptions, date-quality
notes and source IDs in the panel, or download the Sofia rows as CSV.

The earlier PDF does not depict every row in the newer register. The register
does not supply machine-readable incident geometry, so the app does not invent
event points or flood polygons. These sources remain separate evidence for
inspection, without calibration or validation claims for the terrain screen.

Separately, **Layers → Sofia flood survey · 2021** provides 136 real mapped
flood-zone polygons from Sofiaplan's drone-survey dataset 549 / Atlas layer 310.
Enable the optional overlay and use **View survey coverage** to visit the
northern municipality near Novi Iskar, Trebich, Mirovyane and Zhiten. Blue dashed
outlines and a very light fill distinguish these archived observations from the
terrain index. The layer is off by default and its choice is saved in the URL.

The catalogue refers to February 2021 while the associated study describes
January and captions imagery from 18 January; no exact date has been invented.
The source does not classify flood mechanism per polygon, and the associated
report discusses river-associated rainfall flooding. These are not verified
purely pluvial footprints or complete citywide coverage. Clicking a polygon shows
its source ID and archive context alongside the unchanged native elevation and
terrain scores. Displaying or filtering the survey does not recalibrate the
model or change terrain, open-water exclusions or legacy exposure calculations.
Its actual footprint also contributes to the separately prepared categorical
review layer described above.


