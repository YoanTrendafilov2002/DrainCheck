# Mapped open-water exclusion: source and method

The hidden exclusion mask removes qualifying mapped water interiors from the pluvial screening display and related exposure summaries. It does not remove native terrain or change upstream routing, the underlying eight-band terrain raster, source infrastructure or any original datasets. It is a water-context mask, not a river-flood risk or safety boundary.

This is a post-calculation exclusion. Existing percentile reference curves remain
fixed, including the terrain population originally used to calculate them; land
scores are not reranked after removing water.

## Real source and preserved snapshot

Source: **© OpenStreetMap contributors**, licensed under [ODbL 1.0](https://www.openstreetmap.org/copyright), acquired through the public [Overpass API](https://overpass-api.de/api/interpreter). Retrieved **25 October 2026 at 07:31:52 UTC**; the response reports an OSM database timestamp of **07:30:02 UTC**. This database timestamp is not a survey date or proof of current water levels.

The query covers the geographic envelope of the entire native municipal terrain grid, padded by 0.01°: west **23.0336018251**, south **42.3927406840**, east **23.7009712208**, north **42.9135684312**. It returned **586** objects: 563 ways and 23 relations.

Preserved files in `data/reference/`:

- `osm_open_water_20261025T073109Z.overpass`: exact query.
- `osm_open_water_20261025T073109Z.json`: original complete API response, unchanged.
- `osm_open_water_acquisition.json`: acquisition pointer and provenance.
- `open_water_polygons.geojson`: derived qualifying WGS84 polygons with original IDs, tags, versions and edit timestamps.
- `open_water_geometry_review.json`: every rejected object and reason.

The installed mask and source digests, full grid definition, counts and actual control coordinates are recorded in `data/cache/open_water_meta.json`. The mask's SHA256 is verified by the backend before use.

## Which footprints qualify

[OSM `natural=water`](https://wiki.openstreetmap.org/wiki/Tag:natural%3Dwater) describes inland water areas. [`water=river`](https://wiki.openstreetmap.org/wiki/Tag:water%3Driver) specifies the water-covered river area, distinct from its centreline. The query also accepts legacy `waterway=riverbank` polygons. It does not acquire or buffer all stream/river lines, use wetlands as permanent water, or assign an invented river width.

The processor rejects explicitly intermittent, seasonal, dry, disused, abandoned, removed, demolished, proposed or construction features, including lifecycle tags. It also rejects indoor, covered and tunnel water features and [splash pads](https://wiki.openstreetmap.org/wiki/Tag:fountain%3Dsplash_pad), which do not establish standing water. Seasonal values such as `summer` are rejected as well as `yes`; explicit `no` is allowed.

For [multipolygons](https://wiki.openstreetmap.org/wiki/Relation:multipolygon), complete outer and inner way linework is assembled independently. Inner rings remain land holes. Separately returned relation-member ways are not reintroduced as filled polygons. Missing/unclosed/unsupported geometry is rejected and logged rather than guessed. Invalid standalone geometry may be repaired only in the derived copy, with source IDs logged.

This snapshot produced **537 accepted source features** and **49 rejections**: 37 intermittent, five splash pads, four indoor features, one disused feature, one construction feature and one relation whose inner ring could not be assigned to an outer shell. No invalid accepted polygon required repair.

## Exact raster and verification

`data/cache/open_water_mask_5m.tif` is a single **UInt8** band in **EPSG:7801**, width **10,345**, height **10,869**, transform **[5, 0, 299392, 0, −5, 4753611]**. It has **no NoData value**. Rasterization uses polygon membership at pixel centres (`all_touched=False`), with no bank buffer. Water pixels outside the actual valid municipal terrain footprint are reset to zero.

- **1**: qualifying mapped water exclusion.
- **0**: no qualifying mapped water, or outside valid terrain. It does **not** mean verified dry land or low flood risk.

The initial mask contains **1,519,688 water cells**, nominally **37.9922 km²** at 25 m² per cell. This is mask footprint area where ground elevation is present, including cells whose screening score was previously uncertain. The summaries keep excluded water separate from eligible land and uncertain land. The source raster is opened read-only. Output CRS, transform, dimensions, type, missing-value semantics and every saved pixel are verified against the generated mask.

Actual source-based controls passed:

| Control | Longitude | Latitude | Mask |
| --- | ---: | ---: | ---: |
| River footprint, [OSM way 743562181](https://www.openstreetmap.org/way/743562181) | 23.3590736378 | 42.6676687374 | 1 |
| Ariana lake water, [relation 2905862](https://www.openstreetmap.org/relation/2905862) | 23.3372476422 | 42.6900426993 | 1 |
| Ariana island hole, same relation | 23.3368331507 | 42.6896746529 | 0 |
| Vasil Levski playing field | 23.3352531692 | 42.6875642953 | 0 |

## Important central-river limitation

The long central canal/Perlovska footprint beside Vasil Levski is [way 1341771831](https://www.openstreetmap.org/way/1341771831), tagged `natural=water`, `water=canal`, **`intermittent=yes`** in the preserved response. Nearby [way 1234109017](https://www.openstreetmap.org/way/1234109017) is also intermittent. They deliberately remain outside this permanent-water-style exclusion rule. Masking the entire partly dry channel would remove terrain where rainfall-driven ponding or flow may still matter. Removing those reaches requires a different explicitly justified water-state dataset or reviewed wet footprints, not a guessed width or ignored seasonality tag.

OSM coverage and water levels vary. Unmapped narrow rivers remain unmasked, unmarked seasonality can create false exclusions, and 5 m pixel-centre rasterization may omit narrow slivers. Bridge decks and adjacent banks are not independently resolved. This layer cannot establish that land near water is safe or distinguish all fluvial and pluvial events.

## Reproduce

From the app directory, using the environment in the main README:

```powershell
python scripts/prepare_open_water.py
```

This reuses and validates the preserved response by default. To acquire a new dated snapshot while preserving the previous raw files:

```powershell
python scripts/prepare_open_water.py --refresh
```

The script writes only derived polygon review/GeoJSON, mask and metadata files. Following a refresh, rebuild dependent masked exports and exposure summaries using the workflow in the README; their composite revisions must match the new mask.
