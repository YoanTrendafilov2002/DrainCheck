# Cadastral building sources

The municipal **archival** building dataset and the national **AGKK INSPIRE** building service are distinct sources. The main `cadastral_buildings.*` products are reserved for the separately acquired AGKK national snapshot. The archive below is preserved as a separate reference and has not been substituted for that national source or for the Sofia Digital Twin.

## Municipal archival plan

Provider: GIS Sofia, owned by Sofia Municipality. The [official dataset page](https://urbandata.sofia.bg/en/dataset/cad_plan_sgr-zip) explicitly identifies these as building boundaries from the archival cadastral plan before the current cadastral map and registers took effect. Its [resource page](https://urbandata.sofia.bg/en/dataset/cad_plan_sgr-zip/resource/5e7418f8-4a75-4b75-b247-e8d0d74354de) supplies a [30,104,876-byte ZIP](https://urbandata.sofia.bg/dataset/24283798-c042-44de-9bd0-8cec77f2200b/resource/5e7418f8-4a75-4b75-b247-e8d0d74354de/download/cad_plan_sgr.zip).

The catalogue lists Creative Commons Attribution (`cc-by`) and links the generic [CC Attribution definition](https://opendefinition.org/licenses/cc-by/). A licence version is not specified by that catalogue entry. The preserved machine-readable catalogue response records its exact licence fields. Attribution for this source is **GIS Sofia / Sofia Municipality, archival cadastral plan — buildings**.

The catalogue's “valid at” date is **8 September 2026**, with publication on 9 September. Those catalogue dates do not establish survey dates or current existence of individual archived buildings.

## Actual acquired contents

The ZIP contains one 159,602,027-byte `cad_plan_sgr.geojson`, declaring and containing **265,216** building records. All are valid 2D Polygons, their `rn` values are unique, and there are no exact normalized duplicate geometries. All **308 interior holes** are retained. One record has a blank region field; its original blank value is preserved.

The actual geometry envelope is:

| Coordinate | Value |
|---|---:|
| West longitude | 23.07737749032376 |
| South latitude | 42.42408986496466 |
| East longitude | 23.638263837193204 |
| North latitude | 42.856842995001124 |

This is an observed dataset extent, not a guarantee that every currently existing building is represented. Original fields are `rn`, `region`, `functional_type`, `ownership`, and the source-spelled `numer_of_floors`. `rn` is a snapshot row identifier, not a verified national cadastral identifier. Descriptions and ownership strings are historical source attributes, not a current legal determination.

The GeoJSON has no alternative `crs` member. Its longitude/latitude coordinates are retained unchanged and interpreted as WGS84 under the [GeoJSON specification](https://www.rfc-editor.org/info/rfc7946/). There is no reprojection, coordinate rounding, buffering or simplification in the saved derivative.

There are no Z coordinates or verified above-ground height attributes. Floor values include blanks, negative numbers and mixed strings such as `1 1/2` and `2/3`; they are retained verbatim. No height is inferred and no extrusion is manufactured from them.

## Preserved files and reproduction

Original ZIP, official catalogue response and download receipt:

```text
data/reference/cadastral_buildings/cad_plan_sgr.zip
data/reference/cadastral_buildings/catalogue_metadata.json
data/reference/cadastral_buildings/download_manifest.json
```

Original ZIP SHA256:

```text
1e81de4fff53d2c78957a0847b3afef51210cb8d89253212018103ab4684fbe0
```

Separate archival derivative, metadata and validation receipt:

```text
data/derived/cadastral_archive_buildings.geojson
data/cache/cadastral_archive_buildings_meta.json
test-artifacts/cadastral_archive_validation.json
```

The derivative adds stable snapshot-bound `source_id` values based on original `rn`. All original properties and all original geometry coordinates are retained. No source geometry required repair or omission. The derivative SHA256 is `5601797499e815cd2908e2c773904dd04425e3e0de5c390381aed0492c7de71a`; its separate revision is `2976469c28e5ac01`.

From the application directory:

```powershell
# Reuse the verified original ZIP, or download its official resource if absent.
& '../../work/hydro_env/Scripts/python.exe' scripts/acquire_cadastral_buildings.py

# Independently compare every derived record against its original properties
# and geometry, check full counts and hashes, and confirm no inferred heights.
& '../../work/hydro_env/Scripts/python.exe' scripts/acquire_cadastral_buildings.py --verify

# Optional separate archival display index; this never writes the AGKK index.
& '../../work/hydro_env/Scripts/python.exe' scripts/acquire_cadastral_buildings.py --index
```

The optional archival SQLite index has not been built by default because this dataset is being retained as an off-map reference. The main application can use the separately verified national AGKK snapshot when ready. Adding building context does not change native terrain, rainfall, open-water exclusions, drainage routing or pluvial scores.
