# Flood mechanisms and evidence-led refinement

Reviewed 25 October 2026. The auditable classifications and source IDs are in [mechanism_review.json](../data/reference/historical_floods/mechanism_review.json). This review changes the interpretation and attention rules supported by the evidence; it does not establish flood probability, water depth or damage.

## What the Sofia records actually show

The official [past-flood register](https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN%202028-2033/aktual_PORN/04_PFRA_BG1_APP04_pastFloods_2020_2025.xlsx) contains 19 selected Sofia municipality rows representing 15 distinct event IDs. Its source labels are rain/pluvial for 14 rows, rain plus river for two, and rain plus infrastructure for three. These are questionnaire-derived reports, not 19 independently surveyed flood footprints. Several rows combine addresses, dates or very different kinds of damage. Original row dates, event IDs and source descriptions remain preserved.

The [Bulgarian reporting instructions](https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN%202028-2033/aktual_PORN/02_PFRA_BG1_APP02_Instruction_pastFloods_blanka_PURN.pdf), sections 1.2.1–1.2.3, separate **source**, **mechanism** and **characteristic**. Rain, rivers and infrastructure can coexist. A restriction code can mean either river or sewer conveyance, and a flash-flood characteristic does not identify a pluvial source. Nine selected rows contain the broad restriction code, including one with additional defence mechanisms; ten have no coded mechanism. It would be incorrect to count nine proven clogged sewers. This separation also follows the [EU reporting guidance](https://circabc.europa.eu/sd/a/acbcd98a-9540-480e-a876-420b7de64eba/Floods%20Reporting%20guidance%20-%20final_with%20revised%20paragraph%204.2.3.pdf), tables 10.1-1 to 10.1-3.

The most informative causal descriptions are:

| Register row | Supported reading | What remains unresolved |
|---|---|---|
| 34; January 2021 | River overflow, damaged defences/check valves, channel and bridge restrictions; one subarea separately reports groundwater waterlogging without local river overtopping. | Which mechanism produced each of the 136 drone polygons; measured flow/capacity; exact footprint of every described problem. |
| 84; June 2022 | Flooded road underpass, underground floors and ramp; source coded rain plus infrastructure. | A particular clog, pipe defect or quantitative capacity. Row date and event-ID date differ. |
| 103; 4 November 2022 | River water interacting with street drainage/outfall, backing up into a low rail underpass. | A surveyed inundation boundary, flood depth, and whether debris or another constriction contributed. Backwater is not automatically clogging. |
| 141; June 2023 | Mixed river/channel damage, road runoff/drainage problems and sediment; also roof leaks in the same damage inventory. | Ground inundation at every affected building. Roof damage cannot be converted into a surface-flood footprint. |
| 219; 22 May 2024 | Reported street-sewer surcharge, backflow through a building sewer connection, garage-ramp inflow, and a stated contribution from additional development/paving. | Measured capacity, an identified clog, or an independently disambiguated cadastral building. A block number alone does not justify an automatic building match. |

Other reports include pumping basements, elevator shafts, roads and tunnels. They establish reported impacts at textual locations, but pumping alone does not distinguish inlet blockage, pipe capacity, groundwater entry or overland runoff. No incident geometry has been invented. Each reviewed row links back to the exact source sheet and row, with narrative interpretation stored separately from its coded classification.

## The previous map and its GIS counterparts

The municipal [drone-survey catalogue](https://urbandata.sofia.bg/dataset/flooded-areas-identified-by-drone-survey-february-2021) supplies 136 real mapped zones. The [associated study](https://sofiaplan.bg/wp-content/uploads/2021/03/I.10.3_%D0%91%D0%B5%D0%B4%D1%81%D1%82%D0%B2%D0%B8%D1%8F.pdf), printed pages 264–265, describes January 2021 northern flooding after heavy rain in river corridors. Catalogue month and study month differ. Every polygon lacks its own event date, source and mechanism. All 136 therefore retain **mechanism unknown**; study-level river association is additional context, not a per-polygon pure-pluvial or fluvial label.

The preserved [municipal comparison-map PDF](https://sofiaplan.bg/wp-content/uploads/2021/03/I.10.3_%D0%91%D0%B5%D0%B4%D1%81%D1%82%D0%B2%D0%B8%D1%8F_%D0%BA%D0%B0%D1%80%D1%82%D0%B8-1.pdf) was visually reviewed again. Page 5 distinguishes blue 2021 surveyed flooding from red/orange/yellow assessment zones. It prints a flooded-area feature sum of **1,914,939.27 m²**, matching the GIS feature sum of approximately **1,914,939.24 m²**; its outside-assessment figure is **1,230,573.15 m²**. The prose's 19,150 ha total conflicts with the actual map and geometry. Overlapping survey polygons have a smaller union, approximately 1,909,008.66 m²; use union area for a combined footprint.

Neither the earlier basin PFRA PDF nor the eight-page municipal map PDF contains the inspected PDF geospatial keys (`/VP`, `/LGIDict`, `/Measure`, `/Viewport`). A PDF trace would add unnecessary uncertainty because actual source GIS is available:

- Survey: municipal API dataset 549 / atlas layer 310, already preserved in the application.
- Assessment: [layer 306](https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer/306), [307](https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer/307), [308](https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer/308): two source features each, labelled high, medium and low likelihood by the supplier. Their fields supply no numerical return period, per-polygon flood mechanism or model/reference date. Keep these ordinal labels without inventing a probability or calling them current pluvial inundation.
- The [2026 draft PFRA publication](https://www.bd-dunav.bg/content/upravlenie-na-vodite/plan-za-upravlenie-na-riska-ot-navodneniia-2028-2033/aktualizaciia-na-porn/) supplies real [assessment GIS](https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN%202028-2033/aktual_PORN/12_PFRA_BG1_APP12_APSFR_kmz.zip). Sofia code `BG1_APSFR_IS_041` has **23 placemarks: 19 river-assessment lines and four schematic area/reservoir points**. Explicit source types support river, urban-rain, infrastructure or mixed scenario labels. These are assessment reaches/identifiers, not observed incidents or inundation polygons. No widths or buffers are assigned. Its separate critical-point workbook has no applicable Sofia point description; this does not demonstrate that Sofia has no critical drainage locations.

Full source responses, native EPSG:7801 geometry, WGS84 responses and SHA-256 receipts are under `data/reference/flood_assessment/originals/`. The six source polygons contain ring self-intersections. `assessment_zones.geojson` preserves them; `assessment_zones_display.geojson` is a separately validated `make_valid` copy for predicates/masks. Repair retained every unique source vertex, added none, and produced no non-area remnants. The greatest projected feature-area change was below 0.000002 m². No smoothing, buffer or manual extent correction was applied. `geometry_repair_receipt.json` records each feature.

`assessment_zones_browser.geojson` is a separate map-display derivative simplified at 1 m in EPSG:7801 with topology preservation, then returned to WGS84. It retains feature IDs, properties, polygon-component counts and holes. Browser geometry is never the analysis or hit-test source. Per-feature size/area/bounds checks are in metadata; no global Hausdorff error was measured. Source originals and full validated geometry remain recoverable.

Reproduce acquisition/validation in the existing data environment:

```powershell
python scripts/acquire_flood_assessment.py
```

Preserved downloads are hash-verified and reused. Source response bodies are unchanged. Full HTTP receipts containing server-issued cookie headers are local private records; public receipts remove cookie/authorization values. The inspected sources do not state a specific reuse licence; source attribution and this limitation are retained.

## What an override should mean

For this scenario the user explicitly treats the available input dates as compatible. Retain the source dates and unknown dates, record that assumption, and proceed with the combined screening. Compatibility does not create a missing hyetograph, sewer capacity, observed non-flooded control survey or measured building threshold.

Use two distinct attention flags at actual polygon intersections:

1. **Documented previous flooding** inside a real surveyed footprint. This flag can take display precedence over a weak or missing terrain signal. It keeps the occurrence visible while preserving the underlying terrain factors and scores.
2. **Official assessment zone** inside a supplier polygon, with its high/medium/low ordinal label. Where zones overlap, the highest supplier label can be shown, with all matching source IDs available.

These are categorical attention overrides. Do not silently replace P/C/S with 100, add an arbitrary numerical boost or describe a missed historic footprint as a newly validated probability. Keep observation, official assessment, terrain signal and uncertainty individually inspectable. A history flag can remain visible over open water or outside scored terrain; that must not create a land score where the terrain is excluded or unknown. Text reports remain searchable evidence until their locations are verified; broad districts, an underpass description or a schematic city point do not justify a pixel override or an invented buffer.

The canonical API fields are `evidence_id`, `source_id`, `evidence_kind`, `geometry_role`, `reported_source_types`, `mechanism`, `mechanism_confidence`, `mechanism_basis`, source URL/record locator, original date/precision, `assessment_level` and the scenario assumption. Mechanism values are `pluvial`, `river`, `infrastructure`, `mixed`, `unknown`. **Documented** means an explicit applicable source classification; it is not a numerical confidence estimate or independent causal validation. All source interpretations and 136 survey IDs are listed in the JSON review.

## What the new data can add to the index

| Input | Defensible contribution | Missing information |
|---|---|---|
| Real 1 m DTM and aligned 5 m factors | Geometric storage, slope, routing diagnostics and boundary uncertainty; inspect source terrain at fine scale. | Verified vertical accuracy, current kerbs/culverts/inlets, building openings and corrected hydraulic connectivity. |
| 136 survey footprints | Documented flood-history attention and model-mismatch diagnostics over the measured footprint. | Surveyed non-flooded coverage, per-polygon mechanism, depth, recurrence and event forcing. |
| Six official assessment polygons / 23 source placemarks | Supplier assessment attention and documented river/rain/infrastructure scenario context. | Numerical probabilities, an observed flood extent, or a river hazard width from the line alone. |
| 334,033 AGKK building source records | Actual footprint intersection, building planform and exposure context, with source IDs. | Finished-floor/sill levels, basement use, openings, measured heights, occupants, asset values and damage functions. Floors are not height. |
| Archived 2009 sewer routes | Known archived network position and recorded attributes; locations for further inspection. | Current connectivity, pipe/inlet levels and sizes, outfall states, clogging, pumps and operating capacity. |
| 2020 green polygons | Land-cover context and actual overlap. | Measured infiltration, soil/saturation and storage; a green polygon is not a drainage-capacity measurement. |
| Real daily rainfall and station QC | Compatible scenario rainfall amount at the product's native footprint/resolution, with uncertainty/QC visible. | Short-duration intensity, storm timing and routing; daily totals cannot determine flash-flood peaks. |

The existing maximum/percentile score can overemphasise D8 flow strips and shallow slopes. The stadium check demonstrates this with real values: its pitch has zero geometric fill depth, while concentration varies substantially. Retain ponding as a geometric signal and keep concentration/combined experimental until routing sensitivity and local pathways are evaluated. Buildings or historical labels do not remove this numerical issue.

A stronger next physical analysis would delineate real depression spill units and their contributing catchments, calculate geometric storage volume in m³ and compare it with compatible scenario runoff volume in m³, while routing fill-and-spill transfers. Rainfall amount, infiltration and drainage would need explicit documented scenarios rather than guessed coefficients. A ratio based on catchment runoff and available storage could describe a filling scenario; it would still require hydraulic connectivity, uncertainty and event review and would not be flood probability. This has not been calculated by this source review.

For sewer surcharge or river-outfall backwater, surface terrain alone is insufficient: network and river boundary conditions matter. The [Scottish validation guidance](https://www.gov.scot/publications/flood-risk-management-scotland-act-2009-surface-water-management-planning/pages/14/) supports using history to investigate omitted pathways, drainage and interacting sources; it also states that no past observation does not establish safety. The [Environment Agency method](https://www.gov.uk/government/publications/flood-risk-maps-for-surface-water-how-to-use-the-map/risk-of-flooding-from-surface-water-understanding-and-using-the-map) uses rainfall/runoff, drainage, terrain and local review. Its UK drainage/building assumptions are not measured Sofia values and are not imported here.

Do not fit new weights or train against this selectively mapped, mixed-source positive-only inventory. Compare mismatches and route-method sensitivity, then seek independent observations and known survey coverage before calibration. Building/route overlap remains exposure, and quantitative loss/risk additionally needs vulnerability and capacity, consistent with [UNDRR terminology](https://www.undrr.org/terminology/disaster-risk).
