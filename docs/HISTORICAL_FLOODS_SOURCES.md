# Sofia historical flood evidence

Reviewed 25 October 2026. Original responses and documents are preserved under `data/reference/historical_floods/`, with URL, retrieval time and SHA-256 receipts. Historical context layers do not modify the terrain screening index, water mask or exposure calculations.

To verify preserved downloads or recover any missing original from its recorded public URL, run `python scripts/acquire_public_historical_sources.py`. It checks each saved SHA-256, preserves existing files, and refuses a replacement whose contents have changed since this snapshot. Research/acquisition findings are recorded in `source_review.json`.

## Actual mapped flood zones: Sofiaplan drone survey, 2021

The strongest public spatial source found is [municipal dataset 549](https://api.sofiaplan.bg/datasets/549), described by the [Sofia municipal catalogue](https://urbandata.sofia.bg/dataset/flooded-areas-identified-by-drone-survey-february-2021) as 136 flood-zone polygons identified by drone survey. The same survey is available as [Sofiaplan atlas layer 310](https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer/310), under the aerial flood-study group. These are actual mapped zones, unlike nearby layers 306–308, which show modelled flood likelihood areas.

The footprints cover parts of northern Sofia municipality: longitude 23.242826–23.370874, latitude 42.774055–42.816893. They are incomplete survey coverage, not an all-city inventory. The catalogue says February 2021, current as 1 February; the [associated study](https://sofiaplan.bg/wp-content/uploads/2021/03/I.10.3_%D0%91%D0%B5%D0%B4%D1%81%D1%82%D0%B2%D0%B8%D1%8F.pdf), printed pages 264–265, discusses January flooding along the Iskar, Blato and Kriva rivers and captions imagery 18 January. Keep the year and this date discrepancy visible. Individual polygons have no event date, mechanism, water depth or return period. They cannot be relabelled pure pluvial observations.

The municipal licence field is explicitly unspecified. Attribution is retained; public download availability has not been represented as a CC licence.

### Processing and quality checks

- `sofiaplan_dataset549_original.geojson`: byte-identical original; the initially acquired `sofiaplan_dataset549_metadata.json` also contains that original GeoJSON, despite its early working filename.
- `sofiaplan_flood_zones_2021_display.geojson`: 136 features, all source properties retained, plus stable source IDs, provenance and date/type caveats. No buffer, smoothing, invented footprint or geocoding.
- Two self-intersecting rings, source IDs 41 and 72, were repaired with GEOS `make_valid` in the display copy. Polygon components were retained; area change was below 0.00000001 m². Originals remain intact.
- Geometry is served in longitude/latitude from the source API; the parallel ArcGIS layer declares EPSG:7801. Count queries confirm 136 features. Geometry comparison finds the same 136 shapes within 0.00021 m after projection, although some object IDs differ between services; do not join these sources by matching their object IDs.
- Projected feature-area sum is approximately 1.91494 km²; union area is 1.90901 km² because some features overlap. The study's printed 19,150 ha total conflicts with these geometries and its own land-use totals; that printed total is not used.

Reproduce validation/display preparation with Python containing Shapely and pyproj:

```powershell
python scripts/prepare_historical_flood_zones.py
```

Output metadata: `data/cache/historical_flood_zones_meta.json`. Final display revision: `7fbfbcee6ee933f4`. This is observation context, not calibration: no surveyed non-flooded control area or source accuracy assessment was supplied.

## Actual pluvial reports: official Danube Basin register

The [PFRA 2028–2033 consultation publication](https://www.bd-dunav.bg/content/upravlenie-na-vodite/plan-za-upravlenie-na-riska-ot-navodneniia-2028-2033/aktualizaciia-na-porn/) was published on 14 August 2026. Its [Appendix 4 past-flood register](https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN%202028-2033/aktual_PORN/04_PFRA_BG1_APP04_pastFloods_2020_2025.xlsx) covers 2020–2025. It is a draft publication; its observation dates are separate from plan/publication dates.

Selecting municipality code `SOF46` in sheet `bg1_pastFloods` gives **19 source rows / 15 distinct event IDs**: 14 rain/pluvial rows, two river/rain rows and three rain/infrastructure rows. These Sofia rows have 2020–2024 start dates. Repeated event IDs and multiple addresses within rows prevent interpreting 19 as the number of distinct incidents or buildings. Row descriptions include underpasses, roads and basements. The source labels the data origin as questionnaire information.

There are no incident coordinates or inundation polygons in this workbook. `sofia_past_flood_records.json` and the UTF-8 CSV preserve original fields, sheet/row locators, classifications and differing row/event-ID dates. Geometry remains null. No broad district report has been turned into a precise point. The earlier 2011–2019 register was also downloaded and inspected; a strict Sofia city/municipality selection returned no rows, demonstrating why catalogue absence must not be treated as absence of flooding.

```powershell
python scripts/prepare_historical_floods.py
```

This extraction needs `openpyxl`. It writes `data/cache/historical_floods_meta.json` for the incident list, official map and CSV links; originals are opened read-only and verified unchanged.

## Official historical map and other evidence

The [official Sofia PFRA PDF, 2022–2027 cycle](https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN-2022-2027/aktualizacia_PORN/BG1_APSFR_IS_041.pdf) is preserved as `bddr_sofia_pfra_map.pdf` and visually reviewed. At 1:150,000 its legend separates orange/red past-flood location/count symbols and red event line/area symbols from analysis zones. **Blue hatching over Sofia and blue river corridors are selected flood-analysis areas, not observed inundation extents.** It is an earlier contextual map, not a rendering of the newer 2020–2025 register. The government pages do not state a specific open reuse licence.

[HANZE v3.0.1 beta](https://zenodo.org/records/20478847), published 31 May 2026, provides downloadable historical events through 2025 under CC BY 4.0. The downloaded CSV contains one event including Sofia city `BG411`: 4–11 August 2005, classified river/fluvial, also affecting several other regions. Four events include Sofia province `BG412`. Their geometry is affected NUTS3 administrative-region membership, not surveyed flooded area; multi-region damage totals cannot be assigned to Sofia. No Sofia-city pure-pluvial entry was found in this version. The subset is saved as `hanze_sofia_region_records.json`; no region was shaded as a flood footprint.

The [municipality's 16 June 2023 situation report](https://www.sofia.bg/w/%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F-%D0%B7%D0%B0-%D0%BE%D0%B1%D1%81%D1%82%D0%B0%D0%BD%D0%BE%D0%B2%D0%BA%D0%B0%D1%82%D0%B0-%D0%BA%D1%8A%D0%BC-7-00-%D1%87%D0%B0%D1%81%D0%B0) documents road ponding and basement response. It gives broad locations rather than mapped footprints; direct automated archival returned 403, although the public page was readable through search/open. The saved [NIMH October 2025 bulletin](https://bulletins.cfd.meteo.bg/bull/Buletin_NIMH_202510.pdf), printed page 11, reports an unnamed flooded Sofia intersection. Neither report supports invented coordinates.

The official basin web-GIS is linked from its home page, but the attempted public WFS capabilities request timed out. No service-derived historical geometry was claimed. EFAS warnings are forecasts, official likelihood maps are modelled scenarios, and Copernicus results for the Sofia region of Madagascar are unrelated to Sofia, Bulgaria; none were substituted for observed local floods.

## Supported integration

Display the real 136 survey polygons as a separate historical context layer, labelled with 2021 and incomplete northern coverage. Show the official pluvial register as a dated source list with original CSV download, plus the PFRA map PDF with its legend caveat. Keep flood source/type, spatial precision and publication status visible. Do not train or change terrain weights from these mixed and selectively reported records, derive flood probability from overlap, or treat unrecorded locations as safe.
