# Mapped channels and stadiums: requested screening exclusions

The user requested that actual rivers and stadiums be removed from displayed
risk zones. The application therefore uses a **separate, explicit suppression
mask**. This is a presentation/analysis policy, not evidence that a river channel
or a stadium cannot flood. Original terrain values, source scores and original
flood observations are preserved.

## Actual source footprints

The source is © OpenStreetMap contributors, licensed under
[ODbL 1.0](https://www.openstreetmap.org/copyright).

- Channel geometry reuses the unchanged, checksum-verified
  `data/reference/osm_open_water_20261025T073109Z.json` snapshot. It selects actual
  water polygons tagged `water=river`, `water=canal`, `water=stream`, or legacy
  `waterway=riverbank`. Intermittent `natural=water` polygons without a water
  subtype are also included, retaining their original tags. These are mapped
  water/channel footprints; an untyped footprint is not independently confirmed
  to be a river.
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
`data/reference/screening_exclusions.geojson`. This snapshot has **52 channel/
water polygons and 40 stadium polygons**; stadium polygons are not a count of
unique venues because a venue can have both a facility and a building outline.
No source geometry was rejected during this acquisition.

## Exact raster and edge policy

`data/cache/screening_exclusions_5m.tif` is a single-band UInt8 raster, with no
NoData value, in EPSG:7801. It matches the actual screening raster's dimensions
of **10,345 columns × 10,869 rows**, with affine transform
`[5, 0, 299392, 0, -5, 4753611]`.

| Value | Meaning |
|---|---|
| 0 | Not suppressed by this mask; not a safety classification |
| 1 | Mapped channel/water footprint |
| 2 | Stadium footprint |
| 3 | Both |

Rasterization uses **all_touched=True**: every 5 m cell intersecting an actual
source footprint is suppressed, including partial boundary cells. This prevents
thin mapped channels from disappearing under pixel-centre rasterization. It
does not add an arbitrary river buffer or remove a surrounding floodplain.
Cells outside actual valid terrain are zero. Nearest-neighbour overviews retain
the categorical flags.

The prepared snapshot contains **55,770 channel cells**, **20,291 stadium
cells**, and **76,061 union cells**, with no overlap. The represented union
grid-cell area is 1.901525 km²; this includes partial edge cells and is not the
surveyed footprint area. Current SHA-256 is
`bfdf087d674d5c81f80107d1c2ecf5d6c83ae7312756e1e5bbe8528a70a8a9fd`.
The installed metadata file is authoritative for the full checksum; verify it
against the binary rather than relying on this explanatory text.

## Reproduce and verify

Restore the verified `pluvial_5m.tif` and the preserved OSM source snapshots and
receipts, then run:

```powershell
python scripts/prepare_screening_exclusions.py
```

The default reuses the preserved snapshots and fails if their hashes change.
`--refresh` downloads a new dated stadium snapshot without deleting originals.
Changing the source snapshot creates a new derivative and revision.

The script checks the exact grid, data type, absence of NoData, and every saved
pixel against the prepared array. It also requires the actual whole-stadium and
two central-channel source polygons and verifies real pixel centres inside each.
The confirmed Vasil Levski pitch centroid at longitude 23.3352531692, latitude
42.6875642953, row 4665/column 4646, must carry stadium bit 2.
`data/cache/screening_exclusions_meta.json` records source receipts, checksums,
cell counts, controls and verification results. The source score raster is
opened read-only and is not rewritten.

## Limits

Community mapping can be incomplete, stale or misclassified. A missing stadium
tag, an unmapped channel polygon or a river represented only as a line remains
a gap. No invented line width or fabricated footprint is substituted. The mask
does not infer river flood extent, simulate river levels, verify stadium
drainage capacity, or establish absence of flood hazard. Historical observations
remain an independent evidence source, rather than being erased from originals.

The earlier open-water mask remains a separate input. This new mask supplements
it, allowing explicit reporting of a channel or stadium suppression instead of
mislabeling a stadium as standing water.
