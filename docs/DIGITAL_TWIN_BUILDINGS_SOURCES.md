# Building-source acquisition record

Checked 25 October 2026. The requested source is the **current Sofia Digital Twin with full-city coverage**. The older Lozenets pilot and a separately published research dataset must not be presented as the current full-city dataset.

## Current official platform

The [GATE CityLab directory](https://citylab.gate-ai.eu/) advertises a [3D City Model of Sofia](https://citylab.gate-ai.eu/3d-city-model/) and a [3D World Builder](https://citylab.gate-ai.eu/3d-world-builder/). Its current descriptions mention Cesium building tiles, terrain, orthophotography, cadastral layers and building information. Those descriptions establish relevant public applications; they do not expose the downloadable building geometry, authoritative coverage extent, licence or height schema.

The official viewer and GATE project host failed direct connection attempts from this workspace on 25 October 2026. The browser and independent web retrieval also timed out. The failure was a connection timeout, with no authentication or permission response. No access token, guessed asset identifier or private endpoint was used. A failed connection does **not** establish that the current platform has only pilot coverage or that the full-city model does not exist.

The current [municipal digital-twin description](https://www.sofia.bg/en/city-digital-twin) says the project covers Sofia territory and uses CityGML/Cesium. The older [GATE project site](https://city.gate-ai.eu/) and the [2021 paper](https://doi.org/10.5194/isprs-archives-XLIII-B4-2021-23-2021) describe an earlier Lozenets pilot; those historical descriptions do not limit the current service.

The [Sofiaplan ArcGIS atlas catalogue](https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer?f=pjson) was inspected. Its building-labelled layers concern aggregated indicators, accessibility and renovation; no current Digital Twin geometry source was identified there. The root REST catalogue, basic-data service and southern-Lozenets planning service were also checked without finding a linked 3D-twin export. These checks are bounded discovery results, not proof that no other export exists.

The [municipal buildings dataset](https://urbandata.sofia.bg/dataset/buildings-800-m-unweighted) and [archival cadastral building outlines](https://urbandata.sofia.bg/en/dataset/cad_plan_sgr-zip) are possible separately attributed 2D alternatives. They have not been substituted for the requested twin. The “800 m” name refers to pedestrian-access analysis rather than a claim that its coverage is only an 800 m area.

## Separately preserved research subset

[Campoverde et al. (2024)](https://www.mdpi.com/2072-4292/16/8/1386), DOI **10.3390/rs16081386**, links an [author repository](https://github.com/carecamp93/Automatic_Roof_Plane_Extraction) and [original Stage 1 data folder](https://drive.google.com/drive/folders/1ZDmQDv58faQrKPdYRurABFxSAF1o398h). Its Lozenets input folder includes an unbuffered `roof_planes_1800/Outlines_Roof_Planes_1800` shapefile. The study credits GATE and RMSI for the Sofia inputs. These research roof outlines are distinct from both the current Cesium service and a complete 3D CityGML building model.

The four original shapefile components were downloaded and retained in `data/reference/digital_twin_buildings/`. `download_manifest.json` records their canonical Drive links, sizes, modification timestamps and SHA256 hashes. The separate `Outlines_Buildings_Buffer2m` source was not used; no buffer was reversed or treated as an original footprint.

Direct inspection found exactly **1,800 unique valid Polygon features**, with **one interior hole**. The source is **2D**, its declared CRS resolves to **EPSG:7801**, and its sole attribute is **Area**. There are no original IDs, names, Z coordinates or above-ground heights. The file modification date is 26 April 2023; a survey/acquisition date was not established. No explicit dataset reuse licence was found in the downloaded components or linked author repository. The paper's open-access licence must not automatically be assigned to its input datasets.

The derived subset is deliberately named `data/derived/gate_lozenets_research_roof_outlines.geojson`, with separate metadata `data/cache/gate_lozenets_research_meta.json`. It is **not promoted to `digital_twin_buildings.geojson` or the main application layer**. Heights remain unavailable. Roof edges are not guaranteed cadastral ground footprints. Its actual WGS84 geometry envelope is approximately **23.310369–23.338904 E, 42.633391–42.685702 N**.

## Reproduce and verify the subset

The preprocessing environment needs `pyshp==3.1.6`, alongside existing Shapely, NumPy and pyproj dependencies. From the app directory:

```powershell
& '../../work/hydro_env/Scripts/python.exe' scripts/prepare_gate_research_buildings.py
```

The script verifies every acquired component against its download hash, rejects an unexpected CRS/count/type, retains source record order in stable hash-bound IDs, transforms coordinates to WGS84, and checks inverse-transformation error below 1 mm. It applies no buffer, simplification, repair, height inference or extrusion. `test-artifacts/gate_lozenets_research_validation.json` records geometry validity, holes, duplicate counts, actual bounds and unchanged original hashes. The observed maximum roundtrip error was approximately **4.7×10⁻⁹ m**.

The native 1 m terrain, raw 5 m terrain factors, water mask and pluvial scores were not modified by this acquisition or preprocessing.

## What remains necessary for the requested full-city layer

A reachable current official application or download link is needed to identify the actual building asset and establish its licence, spatial extent, feature count and height semantics. An actual export must be checked before claiming a complete city-wide layer or enabling height-based extrusion. A map view spanning Sofia by itself does not establish that the same semantic building dataset covers every part of that view.
