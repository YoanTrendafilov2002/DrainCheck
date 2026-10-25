# Evidence for the refined flood-review map

The useful refinement is a **separate map of review priorities**, retaining the existing terrain scores. Actual historical flood footprints and cadastral buildings identify places where inspection has supporting evidence or potential exposure. The available inputs do not support calibrated flood probability, flood depth, sewer capacity, blockage probability or expected damage.

At the user's request, the different source dates are treated as compatible for a combined review scenario. Dates and unknown currency remain visible. This scenario assumption does not show that June 2025 rainfall caused the mapped 2021 flooding, or that present cadastral records existed during that survey.

## What the actual datasets support

| Dataset | Evidence available | Appropriate role | Material limit |
|---|---|---|---|
| Municipal 1 m DTM and aligned 5 m terrain factors | Real ground elevations, depression-fill depth, slope, D8 contributing area and boundary flag | Ponding-terrain inspection and reliability flags | Fill depth is not flood depth; vertical accuracy/survey lineage not verified |
| Existing P/C/S scores | Unchanged 0–100 relative terrain scores | Preserve original map modes and explain terrain pathways | Scores and 50/70/85 thresholds are exploratory; concentration has routing artefacts |
| 136 Sofiaplan flood polygons | Actual 2021 mapped northern flood footprints | Historical-evidence category and overlap inspection | Partial survey; mixed river/rain/snowmelt context; no known-negative coverage |
| 19 official register rows / 15 event IDs | Reported 2020–2024 incidents, source classifications and narrative mechanisms | Incident evidence and drainage review | Text locations can include several addresses; no invented exact incident points |
| 334,033 AGKK cadastral records | Actual footprints, IDs and source attributes; 334,018 distinct nonnull cadastral IDs | Potential building exposure | Records are not necessarily unique physical buildings; height, thresholds and vulnerability unavailable |
| Three real 27 June 2025 rainfall products | Native daily precipitation totals and masks; 55 station records | Dated rainfall-event context | No subhourly hyetograph; fine products do not cover northern historical polygons |
| Open-water polygon mask | 1,519,688 qualifying mapped-water 5 m cells | Explicit exclusion of existing open-water interiors | Community/source gaps and intermittent channels remain; adjacent land is not excluded |
| 64,962 green source records | 64,956 nonempty mapped polygons | Geometric land-use context and sewer-overlap inspection | Green designation is not measured permeability, storage, soil condition or infiltration |
| 717 sewer routes and 322,025 infrastructure points | Actual source geometry, route status and point category | Context/exposure and a shortlist for drainage inspection | No verified pipe topology, diameter, invert, capacity, inlet condition or maintenance history |

## Historical-footprint comparison

The reproducible calculation uses actual polygons transformed to EPSG:7801 and the original 5 m scores. Polygon union prevents double-counting overlaps. It compares the historical union with surrounding 0–50 m, 50–250 m and 250–500 m rings. Surroundings are **comparison areas, not confirmed non-flooded controls**: no complete drone-survey coverage or negative-observation layer is available.

The 136 polygons sum to 1,914,939.24 m²; their union is 1,909,008.66 m². Unioning removes 5,930.58 m² of feature overlap. Membership uses 5 m pixel centres. Eligible cells have real terrain, no mapped-water exclusion, no upstream-boundary flag and valid original terrain scores.

| Metric | Historical union | 50–250 m surroundings | 250–500 m surroundings |
|---|---:|---:|---:|
| Eligible land cells | 76,020 | 210,724 | 268,958 |
| Eligible land area, km² | 1.9005 | 5.2681 | 6.7240 |
| Zero depression-fill depth | 56.08% | 76.47% | 82.60% |
| Mean depression-fill depth, m | 0.329 | 0.190 | 0.150 |
| Ponding P≥70 | 13.61% | 6.20% | 6.38% |
| Concentration C≥70 | 67.93% | 52.34% | 45.26% |
| Combined S≥70 | 69.13% | 53.20% | 46.24% |

Historical-union membership contains 76,343 cell centres:76,262 have terrain, 62 are mapped water, 180 have uncertain terrain factors, and 76,020 are eligible. The 81 centres outside terrain are not silently assigned zero risk. Exact vector area and pixel-centre cell area differ at polygon edges.

There is an aggregate association with ponding terrain, but it varies markedly among polygons.134 polygons have eligible land both inside and in their local comparison ring. The inside median P exceeds the ring median for 16, equals it for 114, and is lower for 4. The median paired difference is zero. For concentration the corresponding counts are 78/2/54, with median difference 2.05 points. Overlapping local rings are not independent samples. Larger polygons contribute more cells to the union result.

These findings support checking topographic depressions alongside known flooding. They do **not** establish accuracy, false-positive rate, return period or fitted predictor weights. Flooded-only sampling, mixed mechanisms, incomplete survey coverage and terrain artefacts prevent that interpretation. No machine-learning fit or significance claim was made.

## Exposure and surrounding context

The read-only cadastral RTree selects local candidates; exact source geometry is reprojected and intersected.60 cadastral source records have a positive-area intersection with historical footprints; all 60 have distinct cadastral IDs. Their total and union overlap areas are both 1,941.29 m², or 0.102% of historical-union area. These are **potential footprint overlaps**, not confirmed damaged buildings or evidence that they existed in 2021. Northern mapped flooding is predominantly outside the cadastral footprints in this snapshot.

The 50–250 m comparison ring intersects 2,655 cadastral records and contains 148,853.70 m²of union footprint, 2.669% of ring area. This contrast illustrates land-use selection: treating the historical survey as a city-centre building-risk validation set would be misleading. Footprint coverage can be a documented building-cover proxy; it cannot stand in for all sealed surfaces, roof drainage connectivity or a calibrated runoff coefficient.

In the historical union, the supplied geometry contains:

- 40,738.09 m²of union green polygons, 2.134% of area;
- 586.88 mof 2 full sewer-route records;
- 8 infrastructure point records (source codes 2:2,3:5,5:1).

The 50–250 mring contains 85,327.93 m²of green area, 3,407.55 mof 8 routes and 439 infrastructure points. These are geometric overlaps and contextual inventory, not explanations of capacity or failure. One source route can cross several rings. Route lengths here use EPSG:7801 metric geometry; the existing global route partition below uses its established ellipsoidal geodesic definition.

## What “sewer overlapping green areas” actually calculates

The existing partition uses the union of **all 64,956 nonempty green-source polygons**, including a separate repaired analysis copy of the one invalid source feature. It does not use only the former 2,175 display subset. Six empty source records remain preserved and have no area to intersect.

All 717 full routes partition into 137,858.69885 m inside green polygons and 402,304.31468 m outside, against 540,163.01350 m total. The absolute length-conservation difference is 0.00002744 m. Thus 25.52% of total route length is geometrically inside mapped green areas. Counts are nonadditive:543 routes have inside portions and 670 have outside portions; 496 routes occur in both groups. The source statuses comprise 464 existing, 3 open and 250 planned routes. A planned route is not evidence of functioning drainage.

The partition answers **where supplied sewer lines overlap supplied green geometry**. It does not mean all green areas drain into these lines, that sewers are blocked by vegetation, or that green geometry reduces runoff by a known amount. Original P/C/S preparation reads none of these green, sewer, building or rainfall inputs; existing exposure totals sample/overlay the scores without feeding those assets back into them.

## Rainfall coverage and interpretation

Both fine products end at latitude 42.760000; the southernmost historical polygon starts at 42.774055. Their vector overlap with the historical union is exactly zero, regardless of the compatible-time scenario assumption. The wider raw-radar grid covers the historical union, but only 3 native cell centres fall within its irregular footprints. Those 3 June 2025 values average 20.99 mm; this is a sparse cell-centre description, not an area-weighted historical-event rainfall estimate.

The native whole-product rainfall statistics remain the rainfall API's geodesic summaries. Daily accumulation cannot resolve the short rainfall peaks that overwhelm an inlet or sewer, and the corrected/merged products are alternatives derived from related inputs, not independent storm observations to sum together. All 55 station records, including rejected observations and valid zero readings, remain available with their original QC.

## Native terrain and routing checks

Two bounded 640×640 native 1 m windows were compared with their aligned 128×128 five-metre windows: central Sofia near the stadium and an actual northern historical-polygon interior. Every one of 16,384 five-metre mean values in each window exactly equals the corresponding 25 native-pixel mean after Float32 encoding; maximum absolute difference is 0 m. This checks alignment/value preservation, not accuracy of elevations against surveyed ground.

In the northern window, 8,050 cells meet a descriptive near-uniform-slope criterion (7×7 local slope SD<0.01°, centre slope 0.1–2°). Their concentration score median is 90.09, maximum 94.28. This is consistent with the existing routing concern; it does not prove a particular contour or TIN lineage. The central diagnostic previously found D8 stripes in raw contributing area before colour rendering. See[PLUVIAL_ROUTING_LIMITATIONS.md](PLUVIAL_ROUTING_LIMITATIONS.md) and [index_refinement_native_checks.json](../test-artifacts/index_refinement_native_checks.json).

The refined review map therefore uses the P pathway and preserves C/S as separately selectable experimental diagnostics. It does not blur terrain, shift cells, invent barriers, alter elevations or resample the native source to suggest new accuracy.

## Separate review-map rules

The derivative is`data/derived/review_priority_5m.tif`, on the unchanged 5 mgrid. Historical polygons and cadastral footprints affect **this new categorical review layer only**. The original P/C/S raster remains unchanged.

| Code | Review category | Rule on eligible nonwater terrain |
|---:|---|---|
| 0 | Lower ponding terrain signal | P<50; does not mean low flood risk |
| 1 | Raised ponding terrain signal | 50≤P<70; regardless of building presence |
| 2 | Higher ponding terrain signal | P≥70, no potential footprint intersection |
| 3 | Higher ponding + potential building footprint | P≥70 and potential cadastral footprint intersection |
| 4 | Historical flood footprint | Actual historical polygon, no potential footprint intersection |
| 5 | Historical footprint + potential building footprint | Both actual historical polygon and potential cadastral footprint intersection |
| 253 | Excluded mapped open water | Source water exclusion takes precedence |
| 254 | Uncertain terrain | Known terrain but boundary influence or missing required original factors |
| 255 | Outside terrain | No known native terrain; GeoTIFF NoData |

Historical categories 4/5 override the lower display categories without changing P. This prioritizes places with documented evidence for review; it does not rank a river-associated historical site against a street's forecast pluvial probability. Existing 50 and 70 thresholds are retained analytical display choices. No invented weighted average or fitted probability is introduced.

Historical membership uses pixel centres. Building membership uses` all_touched=True`: any footprint intersection may flag the 5 mcell, including a narrow sliver. Therefore coloured cell area is **not** actual exposed building area, and buildings are not assumed to make the entire cell impervious. Exact footprint-overlap areas above use actual polygon intersections instead.

## Drainage and clogging questions

The sewer system is present as mapped inventory and exposure, but it has not been hydraulically simulated. A blockage analysis needs pipe/inlet topology, dimensions, invert levels, verified connection/outfall conditions, maintenance/inspection evidence and a rainfall time series. These are not supplied. Sparse points, absent routes, proximity to trees, or a high terrain score cannot establish clogging.

Official incident narratives can support **reported drainage issues**, with their source wording and uncertainty preserved. The source review distinguishes sewer surcharge/ramp inflow, river water backing through drainage/outfalls, and generic obstruction fields whose definition includes either sewer or river systems. A generic field is not silently recoded as a clogged sewer. Such reports can guide field inspections; they cannot supply missing pipe capacity or current blockage probability.

A defensible next step is a transparent drainage-review flag showing the reason: actual reported mechanism, nearby supplied route/inlet context, and ponding/historical evidence. Distance must remain a distance, and a source report must remain a report. Channel adjacency can be contextual evidence; there is no arbitrary river buffer that removes adjacent land from flood review.

## Reproduction and verification

- Run `python scripts/analyze_index_refinement.py` from the app directory. It streams all 64,962 green records and uses the bounded historical region and read-only cadastral RTree; output: [index_refinement_analysis.json](../data/reference/index_refinement_analysis.json). Set `SOFIA_DTM_PATH` for the preserved native DTM when it is outside the default sibling location; relative paths resolve from the app directory.
- ` work/check_native_refinement.py`performs the two native grid checks; output: [index_refinement_native_checks.json](../test-artifacts/index_refinement_native_checks.json).
- ` python scripts/prepare_review_priority.py`builds the separate compressed categorical derivative and [review_priority_meta.json](../data/cache/review_priority_meta.json), including source hashes, dates, classification policy and counts.
- Source statistics and SHA256 are checked before/after the analysis/build. No source file is overwritten. New raster values represent only categorical review rules, with explicit water/uncertain/outside codes.

Primary methodological context: [Environment Agency surface-water modelling guidance](https://www.gov.uk/government/publications/flood-risk-maps-for-surface-water-how-to-use-the-map/risk-of-flooding-from-surface-water-understanding-and-using-the-map) describes rainfall, terrain, losses/drainage and local/historical evidence as separate modelling ingredients. [EPA SWMM](https://www.epa.gov/water-research/storm-water-management-model-swmm) provides a hydrology/hydraulics model rather than a density-based sewer proxy. These sources explain missing mechanisms; their modelling parameters are not transplanted to Sofia.

Local primary sources: [Sofiaplan flood-survey catalogue](https://urbandata.sofia.bg/dataset/flooded-areas-identified-by-drone-survey-february-2021),[associated municipal study](https://sofiaplan.bg/wp-content/uploads/2021/03/I.10.3_%D0%91%D0%B5%D0%B4%D1%81%D1%82%D0%B2%D0%B8%D1%8F.pdf),[official PFRA register source](https://www.bd-dunav.bg/content/upravlenie-na-vodite/plan-za-upravlenie-na-riska-ot-navodneniia-2028-2033/aktualizaciia-na-porn/),[AGKK cadastral service](https://inspire.cadastre.bg/arcgis/rest/services/Building/MapServer/0). Source dates/licence/currency limits remain in the existing metadata and source receipts.
