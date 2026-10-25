# DrainCheck source repository and future updates

The user requested publication of this app and future tested updates to
[YoanTrendafilov2002/DrainCheck](https://github.com/YoanTrendafilov2002/DrainCheck).
The configured SSH remote is `git@github.com:YoanTrendafilov2002/DrainCheck.git`
and the shared branch is `main`. `AGENTS.md` records this continuing instruction.
Publishing source code does not deploy the local API or publish ignored data.
Initial publication uses the connected GitHub tools, whose repository write
access has been verified; the SSH origin is recorded even though this computer
has no configured SSH key. Future tested updates may publish through that
authorized GitHub connection and verify the resulting remote commit without
requiring local SSH setup.

## What belongs in Git

Track the application, scripts, tests, dependency lockfiles, configuration
template, source documentation and small verification receipts/screenshots.
Retain the complete 201-value Earth Engine quantile snapshot, current canonical
metadata, and actual small rainfall COGs, numeric snapshots and all 55 stations.
These rainfall files total approximately **0.501 MiB** and use original native
values/masks. OPERA and Weather Underground attribution and the upstream
verification/reuse limitations remain in the rainfall source documentation.

The real decoded legacy route/green/point inputs total **58.16 MiB**, with small
prepared route/green partitions adding **4.97 MiB**. The repository stores the
unchanged green-area original as a lossless **14.1 MB (13.44 MiB) gzip bundle**
under `data/source_bundles/`, plus the other small raw inputs and partitions.
The 53,164,382-byte original GeoJSON remains intact locally and is ignored by
Git. The first API upload of that raw file was rejected for input size; gzip
changes its storage representation, not its geometry, attributes or bytes after
decoding. A fresh checkout restores it before building the vector index.
GitHub [warns about files above 50 MiB and blocks files above 100 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
Do not add any file at that limit or above it.

`scripts/restore_source_bundles.py` uses only Python's standard library, with no
login or network access. It verifies compressed size/SHA256, gzip decoding/CRC,
and the original decoded size/SHA256 from `data/source_bundles/manifest.json`.
An existing matching original is left untouched; a conflicting original causes
a failure without overwrite. A missing original is installed atomically only
after its complete temporary copy passes validation. The destination is a fixed
path within this application, rather than an archive-controlled output path.

Keep the following files local and ignored. Ignoring them never deletes them:

| Local material | Why it is separate |
|---|---|
| Native municipal 1 m DTM and other large rasters | Large immutable scientific input, restored from a verified source |
| Raw 5 m terrain factors, score/land-screening rasters | Large verified scientific inputs/derivatives; no substitute terrain |
| SQLite spatial/cadastral indexes, rendered tiles and local colour fits | Rebuildable local caches |
| AGKK original gzip batches, full cadastral GeoJSON and archival GeoJSON | Bulk acquired source/derivative data; retain exact provenance and rights limitations |
| Full official assessment source/native/WGS84 geometry and validated analysis geometry | Preserved local inputs; restore with the source script and verified receipts, separately from the smaller browser derivative |
| `*.private.json` acquisition receipts | Preserve original HTTP records locally; cookie/authorization values must not enter Git or public receipts |
| Original handoff ZIPs, duplicate upload ZIPs and large source reports | Preserved local originals; referenced by receipts and source guides |
| Decoded 53.16 MB green-area GeoJSON | Restored byte-for-byte from the permitted lossless source bundle |
| Unlicensed research geometry | A public download alone does not establish publication rights |
| `.env`, keys, tokens, credentials, virtual environments and `node_modules` | Local configuration, secrets or reproducible dependencies |
| `dist/`, coverage files, test runner caches and logs | Generated build/verification output |

Canonical small metadata under `data/cache/` is selectively tracked for audit;
it is not proof that the ignored binary files are present on a new computer.
The API verifies actual local sources and reports unavailable data explicitly.
Do not overwrite originals or add an ignored file forcibly to bypass this policy.

## Fresh checkout

Use the lockfiles rather than copying the current machine's dependency tree:

```powershell
git clone git@github.com:YoanTrendafilov2002/DrainCheck.git
Set-Location -LiteralPath DrainCheck
python -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-lock.txt
Copy-Item -LiteralPath '.env.example' -Destination '.env'
pnpm install --frozen-lockfile
pnpm build
& '.venv/Scripts/python.exe' scripts/restore_source_bundles.py
& '.venv/Scripts/python.exe' scripts/prepare_data.py
& '.venv/Scripts/python.exe' scripts/prepare_rainfall_cache.py
& '.venv/Scripts/python.exe' scripts/serve.py
```

The included vectors and rainfall are real data. Elevation and 5 m pluvial
screening require the separately restored native datasets; their absence must
remain visible. The generated `dist/` is rebuilt by `pnpm build`, so it is not
expected to exist immediately after cloning.

Restore the verified DTM to `data/external/sofia_dtm_2024_1m_gee.tif`, or point
`SOFIA_DTM_PATH` in the local `.env` to its existing location. The exact grid,
NoData, source identity and preserved vertical datum are specified in the README
and provenance. A screenshot, resampled terrain or unrelated DEM is rejected.
For the existing pluvial result, restore the matching verified local raster and
its source receipts; see the pluvial preparation script and source guides.
After restoring the native DTM, run `scripts/prepare_data.py` again and then
`scripts/restore_reference_scale.py` with the same Python environment. The curve
restorer deliberately requires the verified actual DTM; it is not a prerequisite
for running the vector/rainfall app without terrain.

The source-bundle verification is recorded separately in
`test-artifacts/source_bundle_verification.json`; those restoration checks are
not added to application-suite totals.

Restore AGKK buildings by copying the matching preserved source directory and
metadata from the existing installation, then rebuild its independent index,
or acquire a new public-service snapshot explicitly:

```powershell
& '.venv/Scripts/python.exe' scripts/acquire_agkk_buildings.py
```

The live national service can change. A new acquisition is a new audited
snapshot, not a promise of byte-identical reproduction of the October 2026
snapshot. The initial count/ID list, all responses, checksums, scope and final
count must be verified again. Do not mix old metadata with new batches. Preserve
the AGKK access/usage terms in [the source notes](AGKK_CADASTRAL_BUILDINGS_SOURCES.md);
public query access is not a claim of unrestricted redistribution rights.

The municipal archival alternative is independently reproducible with
`scripts/acquire_cadastral_buildings.py`; it is not promoted into the national
layer. Full handoff verification scripts require restoring all 53 original
supplement files locally, including the large copies excluded from Git. Existing
original archives remain intact on this machine. Other source guides identify
the historical PDF/report downloads and mapped survey geometry.

## Restore the v1.7 evidence review

Version 1.7 adds an independently prepared categorical review layer while
retaining all native terrain, rainfall, route/point/green, building, historical,
water-exclusion and legacy P/C/S functions. The review layer uses the existing
ponding categories, real historical footprints and potential AGKK footprint
intersections; it does not alter the legacy scores or introduce fitted weights.
Historic observation categories take display priority only on eligible land.
Explicit mapped-water exclusions, uncertain terrain and outside coverage remain.

Restore these real prerequisites before preparing the review raster:

- The matching verified `data/cache/pluvial_5m.tif`, open-water mask and their
  source metadata/receipts; the native municipal DTM remains a separate input.
- The complete matching AGKK cadastral source/index and metadata, restored or
  acquired as described above; 334,033 source records are not assumed to be
  334,033 unique physical buildings.
- The 136 validated historical survey polygons and matching metadata. Restore
  the preserved source and, if needed, run `scripts/prepare_historical_flood_zones.py`.

Then run the actual application-relative preparation entry points:

```powershell
& '.venv/Scripts/python.exe' scripts/acquire_flood_assessment.py
& '.venv/Scripts/python.exe' scripts/prepare_review_priority.py
```

Neither script takes command-line flags. The assessment script verifies cached
originals and restores missing public-source bodies only when they match an
existing checksum receipt; a changed source is refused without overwriting the
snapshot. It preserves native/WGS84 originals and creates validated analysis
geometry plus a separate 1 m topology-preserving browser copy. Public receipts
omit cookie/authorization values; full private receipts remain local. The review
script reads the real prerequisites and writes a separate aligned 5 m category
raster and provenance. It does not fabricate absent inputs. Small tracked
metadata or browser geometry does not stand in for excluded analysis datasets.

The map keeps **136 observed 2021 survey footprints** separate from **six
official supplier-level assessment polygons** and **23 draft 2026 PFRA
reach/identifier features**. The latter are prospective assessment context,
including river lines and schematic city/reservoir points, not observed flood
locations, inundation polygons or invented buffered corridors. Municipal
high/medium/low labels remain ordinal; no numerical return period is inferred.
The mechanism and certainty filters preserve unknown classifications, and the
historical visual-priority switch changes styling without adding score points.

Input dates are treated as compatible at the user's request for this scenario;
source dates and spatial gaps remain visible. This does not expand rainfall
coverage or recreate an event hyetograph. Rain stays supplemental, off by default
and at 30% initial opacity when enabled. Sewer proximity/density does not measure
capacity or clogging. All 64,956 nonempty green polygons form the route partition
and are the default green display: 25.52% of supplied route length is inside
their union, a geometric overlap rather than an infiltration or drainage metric.

Source rights and limitations remain explicit in
[the mechanism review](FLOOD_MECHANISMS_AND_REFINEMENT.md),
[the actual-data analysis](INDEX_REFINEMENT_ANALYSIS.md), and the existing
historical, water, rainfall and cadastral source guides. Public query/download
availability has not been relabelled as an unrestricted reuse licence.

## Version 1.8 heatmap and layer presentation

Version 1.8 adds a display-only continuous heatmap of the existing 5 m ponding
descriptor P, source band 6. It changes colour interpolation, not the analytical
grid, source values, P/C/S formula or review categories. It uses neither point
kernel density nor spatial averaging. Nearest source-cell rendering retains
the mapped-water exclusion, grey uncertainty and outside-coverage states.
Valid P = 0 is deliberately transparent in this view; the inspector distinguishes
it from water and missing data, without interpreting it as safety.

Heatmap is the fresh-link selected mode, with screening still off until enabled.
Explicit old mode URLs keep their original choices. Its inspector and exposure
inventory use P; the original P/C/S raster download remains unchanged. All
categorical review, legacy terrain, historical, assessment, drainage, green,
cadastral and rainfall functions remain available. No extra scientific input
or preprocessing step is needed beyond the matching terrain-score raster and
water-mask prerequisites already documented above.

The Layers switchboard groups independent visibility controls with distinctive
source swatches. Warm heat colours, blue observed-flood boundaries, ordinal
official-assessment outlines, amber cadastre, green boundaries and cased sewer
status lines remain visually distinct. Lighter green fill over screening is
presentation only; no polygons or route-overlap results are removed.
**Flood focus** enables heatmap, hides elevation colours, enables hillshade and
selects all green polygons. **Terrain focus** disables screening and enables
elevation colours and hillshade. These presets preserve camera, rainfall,
evidence visibility, route statuses and asset filters. They do not write data
or recompute scores.

The heatmap tests exercise the continuous palette and real-source pixels,
including Ariana water/island, Vasil Levski stadium, positive ponding and
uncertain terrain. They also check cache validation, missing-mask rejection
and preservation of source signatures, receipts and sampled values. Record
the complete suite/build outcome in the current verification receipt after
running it; previous receipts retain their original scope and test counts.

## Version 1.9 selection and blockage scenarios

Version 1.9 adds a hypothetical area-equivalent drainage-loss comparison. It
reads real routes once from the full spatial index, selects existing source
sections intersecting the drawn area, and compares assumed removal before and
after blockage within their unioned influence buffers. Planned and open-channel
routes remain separate inventory context. The model is not a connected sewer
simulation or a measurement of capacity, clogging, flood depth or probability.
Its equations, defaults, masks, units and actual-data example are documented in
[the risk calculation guide](RISK_CALCULATION_GUIDE.md).

The rainfall slider also drives a bounded local depression-storage estimate from
actual mean ground elevations and original fill depths. Components retain only
their own generated runoff and cap storage at their minimum recorded fill level;
overflow and nondepression runoff remain explicit unallocated volumes. The
separate six-band derivative preserves the three millimetre runoff fields and
adds three estimated metre-depth fields. SciPy 1.18.1 is pinned with the other
runtime dependencies for connected-component processing. Source terrain is not
changed. Estimated local storage is not validated hydrodynamic flood depth.

River-context filters use verified river polygons and actual assessment reaches;
lake/pond/reservoir geometry and schematic points are excluded. The adjustable
proximity threshold is not a floodplain or proof of fluvial causation. Its
separate same-grid class mask and full-AOI strata remain local scenario outputs.
Changing a tile's river display filter does not recalculate storage or alter the
full-area statistics and download.

Restore the genuine full vector index and matching 5 m terrain prerequisites
before building the separate full-green grid mask:

```powershell
& '.venv/Scripts/python.exe' scripts/prepare_green_absorption.py
```

This writes `data/cache/green_absorption_5m.tif` and
`data/cache/green_absorption_meta.json` without altering the full green source,
spatial index, terrain or legacy scores. The binary mask uses centres on the
unchanged 5 m EPSG:7801 grid. Matching source signatures, revision, output hash
and header are checked. Rebuild the derivative after regenerating its source
index; copying small metadata without the matching mask does not restore data.
The full 64,956 nonempty polygons are used, including those absent from the old
display subset. The 118.910825 km2 grid-wide mask area must not be relabelled as
eligible terrain or the amount excluded from every user selection.

Full absorption is a user-requested scenario assumption, enabled initially in
the frontend. The original unmasked P/C/S scores and earlier API behaviour remain
available. Hiding polygon display does not change analytical absorption. Existing
water/uncertainty exclusions remain. Grey building fills and cool selected-area
styling distinguish geometry from the warm active risk field. A visible blockage
scenario substitutes its own common-scale runoff heatmap for the base terrain
risk raster; all source functions remain available independently.

Generated immutable scenario directories live under `data/cache/clogging/`.
Keep those user selections/results and their rasters local and ignored, along
with the green mask and other generated caches. Track the implementation,
preparation script, tests, guide and permitted small provenance. Do not force-add
scenario rasters or copy source originals into Git. Every result binds its actual
parameters, AOI, selected IDs, implementation hash and source snapshot; changed
sources require a new calculation rather than reuse of a stale result.

Run the full restored-data Python suite, frontend tests and production build
before publishing. Focused checks are `python -m pytest tests/test_clogging.py -q`
and `python -m pytest tests/test_green_absorption.py -q`; they verify the genuine
local inputs rather than fabricating replacement terrain. Record the actual
current counts in the new verification receipt. Preserve older receipts as
historical evidence with their original scope.

## Publishing a tested update

1. Implement the requested work while preserving unrelated changes and originals.
2. Run meaningful targeted checks and the required build. With the full matching
   local data restored, run `python -m pytest tests -q`, `pnpm test` and
   `pnpm build`, then record their actual results in the current verification
   receipt. The v1.7 evidence-review baseline passed **214 Python tests + 28
   frontend tests (242 total)**; it is a historical baseline, not a substitute
   for checking later updates. Data-dependent checks on an incomplete clone
   are not equivalent to a complete restored-data run.
3. Review `git status --short`, `git diff`, staged paths, file sizes and the
   intended commit diff. Check that no credentials, native rasters, caches or
   unintended original datasets are staged.
4. Commit the intended files, then push the normal update to the configured
   remote. Keep this user's future-update instruction in force unless changed.

```text
git diff --check
git diff --cached --stat
git commit -m "Describe the verified application change"
git push origin main
```

Never use a force push, destructive history rewrite, branch deletion or original
file deletion as a shortcut. If authentication, an access rejection or a remote
change prevents publication, preserve the complete local work, state the actual
blocking result, and resolve it without bypassing security or claiming success.
