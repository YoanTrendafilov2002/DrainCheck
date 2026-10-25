# Map performance

The optimizations avoid unnecessary requests, reuse rendered tiles and reduce
transfer size. They preserve native 1 m elevation samples, the 5 m terrain
analysis, the original datasets and calculated screening values. The terrain
rendering algorithm and its existing display-resolution choices are unchanged.
Version 1.5 restores the newly recovered original whole-area colour curve, so
colour PNGs using that curve can intentionally differ from the earlier local
approximation. Scientific heights, hillshade inputs and P/C/S scores do not
change with that display-reference restoration.

## What changed

- Terrain and hillshade load independently when first enabled. Hidden layers
  use layout visibility rather than opacity alone, so panning does not request
  their tiles. Zero-opacity terrain and screening layers are also hidden. Their
  sources remain available for reuse when enabled again.
- Layer controls apply as soon as the style is ready, including while tiles
  are loading. They no longer wait for every outstanding tile to finish.
- Infrastructure tiles are filtered on the server to the selected categories.
  Every selected source record is retained; unselected categories need not be
  transferred and decoded. Original inventories and exposure totals are intact.
- A shared rendered-byte cache serves PNG and vector tiles from memory or disk.
  Its default limits are **32 MiB memory**, **256 MiB disk** and **4,096 disk
  files**. Concurrent requests for the same missing tile share one render.
  Disk entries survive an API restart. An unusable or corrupt cache causes the
  real tile to be regenerated rather than substituted.
- Cache keys account for source-file identity, data and renderer revisions,
  layer, tile coordinates and relevant filters. Tile URLs include revisions so
  browsers do not reuse an earlier rendering after a change. Old disk entries
  are bounded by the shared cache limits.
- The build produces gzip versions of static assets; vector responses negotiate
  gzip too. Hashed static assets and revisioned tiles allow browser caching with
  `immutable`. The HTML entry point uses `no-cache` so an updated build is found.
- The Pluvial panel reuses pending and completed exposure requests by data
  revision and mode, with at most three mode entries. Failed requests can retry.

## Historical measurements — 25 October 2026

The transfer and timing figures below belong to the earlier performance and
water-exclusion builds. They are retained with their original receipts and are
not new benchmarks of the later building and historical-source integration.

Real browser checks used the running production app and the cumulative handler
counts from `/api/performance`. They verified request behavior, not a universal
page-load timing claim:

| Browser action | Observed local tile/exposure requests |
|---|---|
| Start with all data layers off | No counted requests: `{}` |
| Enable hillshade alone | 40 hillshade requests; 0 elevation-raster requests |
| Disable hillshade, enable sewerage points and navigate | Hillshade stayed at 40; vector requests reached 12 |
| Open Pluvial, leave it and return to the same mode | Exposure requests stayed at 1 |

The performance-update static assets totalled **1,870,800 bytes uncompressed** and
**513,622 bytes with gzip**, a **72.5% reduction in transfer bytes**. The later
water-exclusion build totals 1,874,469 and 514,524 bytes respectively. This is not
a measured 72.5% reduction in loading time.

The 24 paired raster cases cover terrain, hillshade, ponding and concentration
at city and uncovered locations, at zooms 11, 14 and 16. Before water exclusion,
all 24 PNG hashes matched the pre-optimization baseline. Current checks retain
exact native elevation/hillshade tiles and terrain-factor samples; pluvial land
pixels remain identical and only mapped-water pixels become transparent. The
historical cache run retrieved all 24 tiles from disk without rendering.
Measured city zoom-11 disk hits were approximately **1–23 ms**, compared with
approximately **0.28–0.76 seconds** for first renders in that run. Filesystem
caches may already have been warm; initialization was excluded and other work
could contend for the machine.

See [the raster receipt](../test-artifacts/raster_performance_after.json) for
individual measurements and limitations. Vector verification compares decoded
feature IDs, properties and geometry with the earlier renderer; encoded feature
ordering may differ. Its measurements are recorded in
[the vector receipt](../test-artifacts/vector_performance_after.json).

In the same-process, uncached vector comparison, a city tile containing all
**98,511 points** took **13.148 seconds** with the earlier renderer and
**3.332 seconds** with batch rendering (**3.95×** for that case). Both returned
the same decoded IDs, geometry and properties. A street tile with 4,301 points
had median times of 0.580 and 0.119 seconds across two runs per renderer. These
are direct rendering measurements, excluding HTTP, and filesystem caches were
not cleared; the city case has one earlier-then-batch pair. Filtering the city
tile to selected categories returns a smaller requested payload and is not a
like-for-like renderer speed comparison. The reproducible comparison is in
[benchmark_vectors.py](../scripts/benchmark_vectors.py).

## Current validation

The historical pre-rainfall production build passed **141 Python tests and 18
frontend tests: 159 tests total**. Coverage included cache
persistence and limits, coalesced requests, invalidation, corruption recovery,
selected-category preservation, compression, unchanged real-data results and the
independent building/history context contracts. Those receipts and timing
measurements remain preserved with their original scope; they are not new
rainfall-integration benchmarks.

The recovered complete supplement passes its own original checks: 52
manifest-listed files, all three native rainfall COGs against complete arrays
and masks, 15 supplied native point checks, 55 unique station records with the
43/12 accepted/rejected split, and five original elevation-scale tests. The
independent audit reproduces ellipsoidal rainfall areas/means/volumes and checks
source hashes without changing originals. Its receipt is
[rainfall_handoff_validation.json](../test-artifacts/rainfall_handoff_validation.json).
The current app passes **184 Python tests and 23 frontend tests (207 total)**,
and its production frontend build passes. The supplied validation flows and five
original elevation-scale tests are separate checks, not counted again in that
total. Results are recorded in `test-results.xml` and the frontend test output.
The current static assets total **1,913,968 bytes uncompressed** and **523,580
bytes with gzip**, a 72.6% transfer-byte reduction; this is not a page-load-time
measurement.

The old terrain colour golden images remain preserved. Tests reproduce their
hashes using the archived previous curve, verify unchanged coverage alpha, and
check the restored reference against the original Node normalization. Changed
colour hashes under the restored whole-area curve are expected display changes,
not altered native elevation values.

## Rainfall addition and restored reference

The three supplied native rasters are small numeric products: final/corrected
are each 104 × 71 cells and raw radar is 98 × 69. Their complete arrays and masks
are checked once during data preparation/startup; ordinary requests use the
validated data and cached summaries. Rainfall has its own source/rendering
identity and cache keys. Adding it does not require recomputing the spatial
index, native terrain, water mask or full infrastructure exposures.

The scientific rainfall samples and summaries use native cells; display
reprojection or bilinear smoothing is a separate rendering operation. Optional
visibility thresholds do not reduce the data used for statistics or exports.
Native validity governs alpha, including the 1,721 missing raw-radar cells.
Station filters retain all 55 original records and do not rerun a guessed QC or
interpolation procedure. These are correctness constraints, not benchmarked
claims about loading speed.

The complete handoff also supplies the genuine 201-point whole-study-area Earth
Engine normalization snapshot. The previous local approximation is archived;
the full reference replaces only the default whole-area colour definition.
Restoring it invalidates affected display tiles through their scale/source
fingerprints while retaining the scientific dataset identity and existing
local-fit scopes. No height quantization, lower-resolution scientific terrain or
new native-raster processing is introduced. The independent comparison found
at most 1.7365625 m difference between corresponding old/new display quantiles.
That is a statistics-reference difference, not a change to terrain elevations.

See [the source audit](RAINFALL_SOURCES.md) for exact grids, coverage and limits.
No fresh wall-clock performance improvement is claimed for the rainfall build;
the historical measurements above remain the measurements of their own builds.

## Remaining costs

The first visit to an uncached area still requires spatial queries, raster
reads/reprojection or vector construction. Large visible datasets and remote
basemap/font requests can still take time. Cache reuse helps repeat visits and
does not make every first render faster. The browser counters are process-wide,
so compare snapshots while avoiding other tabs requesting the same API.

Keep only useful layers enabled when exploring a wide area. No resolution or
analysis change is needed to benefit from the request and cache improvements.
