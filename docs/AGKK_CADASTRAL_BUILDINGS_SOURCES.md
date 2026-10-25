# AGKK INSPIRE cadastral buildings

This is a separate authoritative cadastral source, acquired from the Bulgarian Geodesy, Cartography and Cadastre Agency's public [BU.Building service](https://inspire.cadastre.bg/arcgis/rest/services/Building/MapServer/0). It is not the unavailable GATE Digital Twin model or the separate municipal pre-KKKR archive. All building context remains independent of elevation, rainfall, terrain screening, water exclusions and exposure calculations.

## Source, scope and date

The [official national INSPIRE catalogue record](https://inspireportal.egov.bg/geonetwork/srv/eng/catalog.search#/metadata/602ad10f-cdd5-49cc-b919-50dc45825bb3) describes buildings from Bulgaria's cadastral map. Its [machine-readable original metadata](https://inspireportal.egov.bg/geonetwork/srv/api/records/602ad10f-cdd5-49cc-b919-50dc45825bb3/formatters/xml) records publication on 3 November 2021, maintenance as needed, and a metadata revision on 29 April 2024. These dates and per-feature lifecycle versions do not establish a 2026 survey or synchronization with the operational KAIS register. The title therefore identifies an **AGKK INSPIRE cadastral-building snapshot retrieved on 25 October 2026**.

The exact acquisition scope is the existing app study rectangle **[23,42.4,23.7,42.95] in longitude/latitude**, using intersection rather than centroid or clipping. The service returned **334,033 object IDs**, matching its independent count response. This rectangle is **not Sofia municipality's administrative boundary**. Complete source footprints intersecting its edges are retained, including parts extending beyond the rectangle. This is complete acquisition of the listed service features, not proof that all current physical buildings are recorded.

Native service geometry is EPSG:4258. The source service supplied GeoJSON coordinates in EPSG:4326 through its documented `outSR` query parameter. No geometry simplification, invented footprint or cartographic buffering is applied. The service's sample geometry reference is “lower floor above ground”; source estimated-accuracy fields can be void. This is cadastral geometry, not a measured hydraulic obstruction model.

## Access and original preservation

Official INSPIRE metadata explicitly states no limitations to public access. Its separate use constraints reference Tariff 14; no CC licence or unrestricted redistribution right has been inferred. Acquisition used public read-only requests, without registration, credentials, paid orders, permissions changes or publication. Provider attribution remains visible.

The service advertises a maximum of 1,000 records per query and supports JSON, GeoJSON and pagination. Acquisition first saves one count response and one complete object-ID response for the study rectangle, then requests explicit groups of at most 1,000 IDs with at most two workers. Requests stop on authentication, permission or rate-limit errors. Every returned batch must contain exactly its requested unique IDs and no transfer-limit flag. Across batches, all initial IDs must be received once.

Original responses are preserved under `data/reference/agkk_buildings/`. Each `batches/batch_XXXXX.geojson.gz` is a lossless gzip copy of the complete original response content, including all original INSPIRE attributes. The manifest records the original query, retrieval time, compressed-file SHA-256 and uncompressed-content SHA-256. Gzip reduces storage; it does not change geometry or properties. Original service/catalogue/WMS metadata and the initial count/ID responses remain separately preserved.

## Display, attributes and heights

`data/derived/cadastral_buildings.geojson` is a full-precision, two-dimensional display copy. It retains useful scalar cadastral, lifecycle, floor-count, condition/use and geometry-reference fields, plus `source_oid`, `source_id`, `cadastral_id` and a checksum-linked original batch reference. The inspector can retrieve every original attribute from that batch; compact map tiles do not have to transfer approximately 130 mostly-null INSPIRE fields for each footprint.

The stable context `source_id` is the source `objectid` represented as text. The cadastral identifier remains separately available as `id_localid` / `cadastral_id`. This snapshot has 334,033 unique source object IDs but 334,018 distinct nonempty cadastral identifiers; the feature count must not be relabelled a count of unique physical buildings. Source IDs are snapshot identities; they must not be confused with a timeless feature key across future service revisions.

Source `numberoffloorsaboveground` and its void flag are retained. A floor count is not a measured height in metres and is never multiplied by an assumed storey height. The source has no confirmed metre-height contract for this integration, so 3D extrusion remains unavailable. Geographic `st_area(shape)` / `st_perimeter(shape)` values follow the service coordinate units; they must not be labelled square metres/metres without an appropriate calculation.

Invalid source rings, if found, are repaired with GEOS `make_valid` only in derived processing, retaining polygon components and recording affected source IDs. The raw responses remain unchanged. No source feature may disappear silently. The independent SQLite index retains source IDs, full-precision derived geometry, coverage bounds and a source-file checksum; it is separate from all hydrological and infrastructure data.

## Reproduce and verify

```text
python scripts/acquire_agkk_buildings.py
```

The acquisition script preserves and verifies completed batches when resumed, then prepares the source-backed display copy and independent building index through `prepare_buildings_index.py`. It does not clear or overwrite the older municipal archive. The resulting metadata is `data/cache/cadastral_buildings_meta.json`; its recorded source revision controls the independent index and map tiles. Full validation results are saved in `test-artifacts/agkk_buildings_validation.json`.

The final snapshot revision is **568d80b32ddb42f2**. Independent verification matches every display feature's full coordinate arrays and selected attributes against the original response, covers exactly all 334,033 initially listed IDs, verifies all 335 compressed and original-content checksums, and finds no transfer-limited batch. There are 334,032 Polygon and one MultiPolygon features, all valid without repair. The independent SQLite index and R-tree both contain 334,033 records and pass integrity checks. Full original response content occupies 60,315,844 gzip bytes.

Index preparation uses a checksum-verified, one-feature-per-line intermediate under `work/` and SQLite disk staging, avoiding whole-dataset JSON materialization. This intermediate is temporary preparation data, outside the user-facing source package. Native cadastral geometry and source properties are retained; streaming changes memory use, not data precision.

Keep the older municipal cadastral-plan source separate; see [its source guide](CADASTRAL_BUILDINGS_SOURCES.md). Neither source establishes building vulnerability, flood damage, impermeability or drainage capacity. Adding these outlines does not recalibrate the pluvial screening map.
