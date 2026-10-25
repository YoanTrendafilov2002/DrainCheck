# Mapped channels and stadiums: requested screening exclusions

The user requested that actual rivers and stadiums be removed from displayed
risk zones. The application therefore uses a **separate, explicit suppression
mask**. This is a presentation/analysis policy, not evidence that a river channel
or a stadium cannot flood. Original terrain values, source scores and original
flood observations are preserved.

## Source geometry

Mapped geometry comes from © OpenStreetMap contributors, licensed under
[ODbL 1.0](https://www.openstreetmap.org/copyright).

- Channel polygons reuse the unchanged, checksum-verified
  `data/reference/osm_open_water_20261025T073109Z.json` snapshot. It selects actual
  water polygons tagged `water=river`, `water=canal`, `water=stream`, or legacy
  `waterway=riverbank`. Intermittent `natural=water` polygons without a water
  subtype are also included, retaining their original tags. These are mapped
  water/channel footprints; an untyped footprint is not independently confirmed
  to be a river.
- The citywide waterway query also acquires `waterway=river`, `stream`, `canal`,
  `drain` and `ditch` centerlines. Its preserved response is
  `data/reference/screening_exclusions_waterways_20261025T151232Z.json`, with
  the matching `.overpass` query and acquisition receipt. The pointer is
  `data/reference/screening_exclusions_waterways_acquisition.json`.
  Lines tagged covered, tunnel, indoor, underground or inactive are omitted;
  a buried culvert does not automatically exclude the surface road above it.
- An unambiguous positive [OSM `width` tag](https://wiki.openstreetmap.org/wiki/Key:width) supplies a centered footprint of that
  width, projected in metres. Without a usable width, the mapped line itself
  selects intersecting 5 m cells. That is a grid policy, not a measured bank width.
- Stadium geometry was acquired with a citywide bounding-box Overpass query for
  polygon ways/relations tagged `leisure=stadium` or `building=stadium`, on
  **25 October 2026**. The exact query, unmodified response and checksummed
  acquisition receipt are preserved under
  `data/reference/screening_exclusions_stadium_20261025T124953596329Z*`.
  A pointer receipt is `screening_exclusions_stadium_acquisition.json`.
- Whole mapped stadium footprints are used, including
  [Vasil Levski way 341968882](https://www.openstreetmap.org/way/341968882),
  rather than excluding only its playing field.
- Both intermittent central Perlovska footprints are included:
  [way 1341771831](https://www.openstreetmap.org/way/1341771831) and
  [way 1234109017](https://www.openstreetmap.org/way/1234109017).
  Their intermittent tags excluded them from the earlier conservative standing
  open-water mask. The new channel-suppression policy deliberately includes them.

The accepted source geometry is recorded, with OSM object IDs, versions,
timestamps, complete original tags and source links, in
`data/reference/screening_exclusions.geojson`. Source line counts describe
features intersecting the rectangular analysis grid; they do not establish that
every feature intersects valid terrain. Stadium polygons are not a count of
unique venues because facility and building outlines can overlap. Current
counts, omitted records and checksums are in
`data/cache/screening_exclusions_meta.json`.

## Exact raster and edge policy

`data/cache/screening_exclusions_5m.tif` is a single-band UInt8 raster, with no
NoData value, in EPSG:7801. It matches the actual screening raster's dimensions
of **10,345 columns × 10,869 rows**, with affine transform
`[5, 0, 299392, 0, -5, 4753611]`.

| Value | Meaning |
|---|---|
| 0 | Not suppressed by this mask; not a safety classification |
| 1 | Mapped channel polygon, source-width footprint or intersected centerline cell |
| 2 | Stadium footprint |
| 3 | Mapped channel and stadium |
| 5 | Terrain-connected channel candidate (river bit 1 plus inference bit 4) |
| 7 | Terrain-connected channel candidate and stadium |

Rasterization uses **all_touched=True**: every 5 m cell intersecting accepted
geometry is suppressed, including partial boundary cells and line crossings.
Centerlines also use exact segment/grid traversal to retain nearly horizontal
crossings and cells touched at a grid edge or corner.
Cells outside actual valid terrain are zero. Grid-cell area includes partial
cells and must not be described as surveyed channel area.

### Connected terrain candidates

Mapped centerlines can miss part of an incised channel in the terrain raster.
The alignment input is the municipal DTM's existing 5 m ground-elevation and
depression-fill bands in `data/cache/pluvial_5m.tif`.
The separate screening policy searches within **20 m** of actual open
waterway lines, with flat end caps, using native 5 m cell centres. A candidate
must have finite valid ground elevation and finite, strictly positive terrain
depression fill depth. Mapped river seeds outside valid terrain are removed
before propagation. Only candidate components connected to the remaining seeds
through eight-neighbour cell adjacency are added. They receive
river bit 1 and inference bit 4, keeping terrain inference distinct from mapped
channel geometry in the raster and sample responses.

Zero-fill land, disconnected depressions and cells outside this search corridor
remain unchanged by this extension. The 20 m limit is a bounded screening
assumption; it is neither a measured bank width nor a floodplain boundary. Added
cells are terrain-derived exclusions, **not observed water**. Original terrain,
fill depth and screening values remain intact.

Native 1 m Perlovska cross-sections showed an incised trough beside the mapped
centerline cells, explaining why alignment was needed there. That local check
does not validate channel boundaries throughout the study area.

Tile masks read the **native 5 m raster**, bypass nearest-neighbour overviews
and use maximum reduction at every zoom: any overlapping excluded native cell
suppresses that display pixel. This also clips partial edge pixels whose centres
fall on neighbouring land. It prevents channel colours from returning at zoom
changes; adjacent land within the same display pixel may be hidden without
changing any analysis cell or source score.

## Reproduce and verify

Restore the verified `pluvial_5m.tif` and the preserved OSM source snapshots and
receipts, then run:

```powershell
python scripts/prepare_screening_exclusions.py
```

The default reuses the preserved snapshots and fails if their hashes change.
`--refresh` downloads new dated waterway and stadium snapshots without deleting
originals.
Changing the source snapshot creates a new derivative and revision.

The script checks the exact grid, data type, absence of NoData, and every saved
pixel against the prepared array. It requires the open-waterway network as well
as the actual whole-stadium and two central-channel source polygons, with real
pixel controls inside each mandatory polygon.
The confirmed Vasil Levski pitch centroid at longitude 23.3352531692, latitude
42.6875642953, row 4665/column 4646, must carry stadium bit 2.
`data/cache/screening_exclusions_meta.json` records source receipts, checksums,
cell counts, controls and verification results. The source score raster is
opened read-only and is not rewritten.

## Limits

Community mapping can be incomplete, stale or misclassified. Missing channels,
stadium tags and unknown bank widths remain limitations. Mapped geometry plus
connected terrain candidates does not establish complete physical bank coverage;
connected adjacent depressions can also enter the bounded policy exclusion.
The mask does not infer river flood
extent, simulate river levels, verify stadium drainage capacity, or establish
absence of flood hazard. Historical observations
remain an independent evidence source, rather than being erased from originals.

The earlier open-water mask remains a separate input. This new mask supplements
it, allowing explicit reporting of a channel or stadium suppression instead of
mislabeling a stadium as standing water.
