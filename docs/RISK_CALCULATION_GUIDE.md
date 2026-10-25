# DrainCheck risk calculation guide

Technical explanation of the Sofia map and hypothetical pipe-blockage scenario, version 1.9. Prepared for the user's time-compatible and fully absorbing green-area assumptions. The guide distinguishes source observations, unchanged terrain descriptors, review categories and editable scenario calculations.

## 1. What the map calculates

DrainCheck provides related analytical views. The terrain heatmap shows a relative ponding descriptor on a 5 m grid. The evidence-review map combines that descriptor with mapped historical flooding and potential building-footprint intersection. The blockage scenario compares potential locally unremoved runoff before and after an assumed drainage loss near selected existing sewer routes, then estimates local depression storage using genuine ground elevations. Mapped-river proximity separately distinguishes river-adjacent context from land away from the supplied river geometry.

These outputs have different units. Terrain P is a 0-100 relative indicator. Review codes are category identifiers. Scenario runoff is in millimetres, stored volumes in cubic metres, and estimated local ponding depth in metres. None is a calibrated annual flood probability, validated inundation forecast, property-damage estimate or diagnosis of current pipe clogging. The app retains separate legends rather than adding incompatible numbers together.

The calculation uses actual local datasets. No terrain is fabricated, the preview PNG is not elevation, source grids are not shifted, and original elevations are not normalized into replacement heights. Normalization is confined to relative indicators and display colours. Every original remains preserved separately from derived rasters and browser geometry.

## 2. Inputs and their roles

| Input | Verified content | Role in this app |
|---|---|---|
| Sofia municipal DTM | Native 1 m, 51,722 columns by 54,343 rows, Float32, EPSG:7801, NoData -9999; Baltic 1982 remains descriptive vertical metadata | Ground readout and underlying terrain factors |
| Prepared terrain factors and scores | Aligned 5 m grid, 10,345 columns by 10,869 rows; eight Float32 bands | Depression, slope, contributing-area, uncertainty and P/C/S descriptors |
| Existing open water | 537 source polygons; 1,519,688 mapped-water cells, 37.9922 km2 at 5 m | Excludes mapped existing water from terrestrial screening |
| Green areas | 64,962 original records, 64,956 nonempty polygons; original empties retained | Complete geometric route partition and the user's full-absorption scenario mask |
| Sewer routes | 717 source routes: 464 existing, 250 planned, three open-channel | Source inventory, area selection and assumed influence neighbourhood |
| Infrastructure points | 322,025 records with original categories | Inventory and local drainage context; no inferred network topology |
| AGKK cadastral buildings | 334,033 source records; 334,018 distinct non-null cadastral IDs in the study rectangle | Potential footprint intersection and neutral building context |
| Historical survey | 136 actual northern Sofia flood polygons from the 2021 survey | Prior observed inundation footprints; individual causes remain unknown |
| Official event register | 19 Sofia rows representing 15 event IDs, 2020-2024 | Reported causes and narratives; no invented incident coordinates |
| Official assessments | Six municipal high/medium/low polygons and 23 draft 2026 PFRA reach/identifier features | Independent prospective assessment context |
| Rainfall | Three genuine 27 June 2025 daily products and 55 stations, including 43 accepted and 12 rejected | Supplemental observed-product context, separately from editable scenario rainfall |

The municipal terrain catalogue and source receipts identify the local DTM. The [AGKK building service](https://inspire.cadastre.bg/arcgis/rest/services/Building/MapServer/0), [Sofiaplan survey catalogue](https://urbandata.sofia.bg/dataset/flooded-areas-identified-by-drone-survey-february-2021) and [Danube Basin Directorate PFRA publication](https://www.bd-dunav.bg/content/upravlenie-na-vodite/plan-za-upravlenie-na-riska-ot-navodneniia-2028-2033/aktualizaciia-na-porn/) supply the relevant building and flood evidence. Detailed acquisition snapshots, rights notes and checksums remain in the individual source guides and metadata.

The whole-Sofia Digital Twin target remains a separate source-availability item. An older 1,800-roof research subset is not substituted for that service. Cadastre records are not automatically unique physical buildings, and floor counts do not become invented heights. The requested imperviousness product has not been acquired as a usable analytical input; the app does not fill its absence with fabricated sealed-surface data.

## 3. Resolution, dates and spatial coverage

The 1 m DTM affine is `[1, 0, 299392, 0, -1, 4753611]`. The analytical 5 m affine is `[5, 0, 299392, 0, -5, 4753611]`, both EPSG:7801. Each analysis cell represents 25 m2. Native inspection remains 1 m; analysis does not claim that all ancillary data have 1 m information content. Two bounded native-window checks found the aligned 5 m mean elevations equal to their corresponding 25 native-pixel means after Float32 encoding. This verifies alignment and values, not surveyed vertical accuracy.

At the user's request, dates are treated as compatible for the combined scenario. Actual years, date conflicts and coverage boundaries remain recorded. This lets the user explore the data together; it does not establish that a June 2025 storm caused a 2021 flood or that all buildings existed at the time of that flood.

The fine rainfall products end at latitude 42.760000. The southernmost historical survey polygon starts at 42.774055. Their spatial overlap is zero even under the compatible-time assumption. Daily rainfall accumulation cannot supply an unobserved one-hour storm shape. The scenario's entered rainfall and duration are therefore explicit assumptions, not an automatic reinterpretation of the daily raster as hourly intensity.

## 4. The original terrain descriptors

The existing preparation reads genuine elevation, depression-fill depth, slope, upstream contributing area and the missing-upstream-terrain flag. It samples valid cells at globally aligned row/column intervals of four analysis cells: a deterministic 20 m sample. Each reference distribution is represented by 201 quantiles. Repeated quantile values receive their mean percentile position; interpolation produces a compact approximate percentile reference, not an exact empirical distribution of every 5 m cell.

Let `rank(x)` denote the applicable 0-1 percentile reference, `d` depression-fill depth, `a` upstream contributing area, and `s` slope:

```text
P = 0                                  if d = 0
P = 100 * rank_positive_depth(d)         if d > 0
C = 100 * sqrt(rank_area(a) * (1 - rank_slope(s)))
S = max(P, C)
```

P describes relative topographic depression. C combines contributing-area rank with low-slope rank. S retains the stronger pathway. The reference scope includes the available municipal terrain, including mountains; a percentile is not a rainfall return period. The 50/70/85 cutoffs are analyst-selected display classes, not validated flood thresholds.

Cells require finite, valid terrain factors, slope between 0 and 90 degrees, contributing area at least 25 m2, and no upstream-boundary flag. Mapped open water is separately excluded. A mandatory, separate user-requested mask also excludes mapped river channels (including mapped intermittent channels) and stadium footprints from every displayed risk mode, review category and blockage scenario. These locations are unscored, not assigned zero risk. Known terrain lacking an eligible score is distinguishable from outside-coverage NoData. The source raster, scores and rank reference remain unchanged by these exclusions, building visibility, rainfall overlays, area selection or scenario calculations. See [the exclusion sources and grid policy](SCREENING_EXCLUSIONS.md).

Depression-fill depth is the difference against a filled topographic surface; it is not forecast floodwater depth. D8 routing in the source contributing area shows facet/stripe artefacts, including high C on some near-uniform slopes. P is therefore the normal heatmap pathway; C and S remain accessible experimental diagnostics. Buildings, kerbs, culverts, inlets and underground pipes are not inserted as verified hydraulic barriers or connections.

## 5. Historical evidence and the categorical review map

The separate review raster uses these rules on eligible land, in descending priority:

| Code | Rule |
|---:|---|
| 5 | Actual historical footprint and potential cadastral-footprint intersection |
| 4 | Actual historical footprint without that building flag |
| 3 | P at least 70 and potential cadastral-footprint intersection |
| 2 | P at least 70 without that building flag |
| 1 | P at least 50 and below 70 |
| 0 | P below 50; no claim of safety |
| 253 / 254 / 255 | Mapped water / uncertain terrain / outside terrain |

Historical membership uses cell centres. Building membership in the prepared review raster uses any cell-footprint intersection, including narrow slivers. A coloured 25 m2 cell is consequently not a measurement of exposed building area or whole-cell imperviousness. Historical categories override lower review categories; they do not change P or prove a future event probability. The current absorbing-green scenario can mask these displayed review cells while the actual historical observation overlay remains independently available.

The actual comparison found P at least 70 in 13.61% of eligible historical-union cells versus 6.20% in surrounding 50-250 m rings. These surroundings are not confirmed non-flooded controls. Of 134 polygons with eligible local comparisons, the inside median P was higher in 16, equal in 114 and lower in four. This supports terrain inspection alongside known flooding, not a fitted predictive model or an accuracy statistic. Sixty actual cadastral records intersect historical polygons by positive area; their exact overlap totals 1,941.29 m2, not the area of all flagged 5 m cells.

The survey's January/February 2021 discrepancy remains explicit, and all 136 per-polygon mechanisms remain unknown. Register rows preserve the authority's pluvial, river and infrastructure classifications and narrative evidence. Nine rows containing a generic restricted-conveyance code do not establish nine clogged sewers: that reporting field can concern sewer or river systems. The six ordinal assessment polygons and 23 draft reach/schematic identifiers are prospective context, not observed flood extents. Lines are not expanded into invented corridors, and schematic points are not presented as precisely located incidents.

## 6. Heatmap and absorbing green areas

The terrain heatmap interpolates colours across unchanged P values: faint amber, orange, red and purple. It does not perform kernel-density estimation, spatial smoothing or a new numerical risk calculation. Nearest source-cell rendering preserves analytical boundaries. Valid P=0 is deliberately transparent and remains distinguishable in inspection from missing or excluded cells.

The user-requested assumption is that all mapped green areas absorb water completely and do not form part of scenario risk areas. This is enabled by default in the app's scenario display; the legacy unmasked descriptors remain inspectable. Hiding green polygon drawing does not disable the analytical mask. The complete set of 64,956 nonempty polygons is used, never just the former 2,175 route-intersecting display subset. Grid membership uses cell centres.

The full aligned green-mask rectangle contains 118.910825 km2 of green cells. That is not the amount removed from an individual AOI or from eligible terrain: some green cells can overlap missing terrain, water or areas outside a given selection. Scenario statistics separate total mapped green within the selection from green excluded on otherwise eligible nonwater land. The disjoint exclusion totals can therefore be reconciled without double counting.

Complete absorption is an intentionally favourable user assumption. The source designation does not measure soil infiltration, compaction, saturation, groundwater, storage capacity or impermeable paths within a park. The calculation does not route neighbouring street runoff into a green polygon or model its overflow. Those processes would require additional data and a different model.

The pre-existing sewer partition remains geometric: 137.858699 km of routes inside the full green union plus 402.304315 km outside equals 540.163014 km overall, within numerical tolerance. Thus 25.52% of mapped route length overlaps green areas. Counts cannot be added: 543 routes have inside sections and 670 outside sections; 496 occur in both groups. This overlap neither proves drainage connectivity nor diagnoses vegetation-related blockage.

## 7. Selecting an area and pipes

The blockage tool accepts a drawn rectangle, represented as a WGS84 GeoJSON Polygon. The backend also accepts a valid closed polygon. It transforms that actual geometry to EPSG:7801 for area, buffering and raster work. It queries the real full-route RTree with `zone='all'`, avoiding duplicate inside/outside copies, then performs exact intersections.

Candidate records contain stable source IDs, status and actual clipped length in metres. Geometry displayed and measured for this selection is the part inside the AOI; the preserved full source geometry is not overwritten. Initially all intersecting existing routes are selected. The user can change the selected existing IDs. Planned and open-channel routes remain visible as separate inventory context and do not silently act as functioning pipes.

Only selected existing route sections generate the influence geometry: their union buffered by the entered distance and clipped to the AOI. Overlapping buffers are unioned, so selecting two nearby routes does not multiply the capacity loss for the same cell. This neighbourhood is not a delineated catchment, pipe service area, connected network or predicted plume of floodwater.

Guards require finite coordinates and parameters, a valid nonempty closed polygon with at most 5,000 vertices, at most 25 km2 of geometric area, and at most 1,000,000 cells in its cropped grid rectangle. A long thin polygon can exceed the bounding-grid guard despite having a smaller polygon area. Unknown IDs, IDs outside the drawn area, invalid geometry and absent real inputs fail explicitly. The original grid is cropped by whole cells without resampling or shifting.

## 8. Blockage parameters and equations

| Editable parameter | Default | Unit and allowed range | Meaning |
|---|---:|---|---|
| Rainfall | 30 | mm; 0-1,000 | Assumed event accumulation |
| Duration | 60 | minutes; 1-1,440 | Assumed event duration |
| Drainage removal capacity | 15 | mm/hour; 0-500 | Assumed area-equivalent removal, not measured pipe capacity |
| Blockage | 100 | percent; 0-100 | Fraction of assumed capacity lost in the selected influence |
| Influence distance | 50 | metres; 5-500 | Assumed buffer around selected existing sections |
| Runoff coefficient | 0.9 | dimensionless; 0-1 | Fraction of entered rainfall counted as effective runoff on eligible nongreen land |
| River proximity | 100 | metres; 5-1,000 | Context threshold, not a hydraulic floodplain boundary |

The default 15 mm/hour is a transparent app assumption, not a verified Sofia drainage rate. The [Environment Agency methodology](https://www.gov.uk/government/publications/flood-risk-maps-for-surface-water-how-to-use-the-map/risk-of-flooding-from-surface-water-understanding-and-using-the-map) provides context for representing drainage as an ongoing loss and combining terrain, rainfall and local evidence. Its national modelling parameters are not adopted as Sofia calibration.

Let `R` be rainfall in mm, `c` runoff coefficient, `T` duration in hours, `D` assumed drainage rate in mm/hour, and `b` blockage as a fraction. On eligible nongreen land:

```text
effective rainfall Q = R * c
baseline excess E0 = max(0, Q - D * T)
clogged excess E1  = max(0, Q - D * T * (1 - b))  inside influence
clogged excess E1  = E0                           outside influence
additional excess = E1 - E0
```

Eligible cells lie inside the AOI, have genuine valid terrain scores and no upstream-boundary flag, and are neither mapped water, mapped river-channel/stadium exclusions nor mapped green. Scenario statistics report the disjoint exclusions and their precedence so that these areas plus eligible nongreen land reconcile with the rasterized AOI. Exact vector area can differ slightly from the cell-based area at boundaries.

Every eligible cell receives the baseline calculation. Only eligible cells within the selected existing-route influence receive the clogged calculation. Green cells, water, user-excluded river/stadium cells and uncertain/outside cells are NoData in runoff and depth scenario bands, rather than zero-valued evidence of safety. The original P/C/S values are not recalculated. The additional statistic for affected area with P at least 70 is a terrain-overlap measure, not a fused probability or a routing weight.

## 9. Estimating local ponding depth from terrain

The rainfall slider changes entered storm accumulation. After a short debounce, the current area and selected pipes are recalculated; the numeric control also supports values beyond the slider's ordinary range. A default depth view displays estimated clogged local depression-storage depth. The original millimetre runoff views remain selectable. The interface hides stale results when assumptions change, rather than relabelling an old calculation with new inputs.

The depth calculation uses the actual 5 m mean ground elevation `z` and original depression-fill depth `d`. It identifies 8-connected components where `d > 0` within eligible nongreen land. Each component is processed independently. No runoff is borrowed from another component, a whole-area reservoir, or an unmodelled upstream catchment. Zero-fill land does not become a fabricated depression.

For component `j`, its conservative common spill level is the minimum recorded filled-surface elevation among its cells:

```text
spill_j = min(z_i + d_i)
capacity_j = sum(max(0, spill_j - z_i) * 25)          cubic metres
input_j = sum(excess_runoff_mm_i * 25 / 1000)        cubic metres
retained_target_j = min(input_j, capacity_j)
```

The calculation sorts actual bed elevations to build the component's elevation-volume curve. It solves for the water level `h_j` satisfying `sum(max(0, h_j - z_i) * 25) = retained_target_j`, with `h_j <= spill_j`. Estimated cell depth is `max(0, h_j - z_i)`. Cells whose beds are above the common spill remain dry. Using the minimum spill also keeps every estimated depth at or below its original recorded fill depth. The baseline and clogged runoff fields are allocated separately to the same components; their difference gives additional estimated depth.

This is a local storage approximation. Connectivity of positive-fill cells is not a surveyed basin or a hydrodynamic solution. Water is levelled within each component without a travel-time or flow-path calculation. Component adjacency to the AOI edge or excluded green/water/uncertain land is flagged as potentially truncated. A component crossing the pipe influence boundary is separately flagged as partially influenced; the influence buffer does not become a hydraulic basin boundary. An AOI can cut a real basin, so a larger selection can change component storage and estimated depths.

Runoff exceeding component storage is reported as overflow without assigning a downstream destination. Runoff generated on eligible zero-fill land is reported as unallocated, rather than silently poured into the nearest depression. Consequently the app can show little stored water despite a large runoff total. It has not shown that the remaining water disappears or that zero-depth cells are safe.

For each baseline/clogged view, statistics include maximum estimated depth, the 95th percentile among positive-depth cells, wet area, areas at least 0.05/0.1/0.3 m, stored volume, overflow, zero-fill unallocated volume and a numerical residual. Float32 depths round down so raster encoding does not create water volume. The audit equation is:

```text
source runoff volume = stored volume + overflow
                     + nondepression unallocated volume + numerical residual
```

Boundary flags and these balances accompany every result. They make the estimate inspectable without claiming that it predicts actual street flooding. The model does not represent dynamic routing, green-area overflow, river levels, backwater or pipe pressure.

## 10. Area, volume and sensitivity

For a 5 m cell, area is 25 m2. One mm equals 0.001 m, so volume is `runoff_mm * 25 / 1000` m3 per eligible cell. The app sums baseline potential unremoved volume over eligible land, then adds the extra volume only from affected cells. The clogged total equals baseline plus additional volume.

For a hand-worked example, assume exactly one hectare of eligible nongreen land, all inside the selected influence. At 30 mm rain, coefficient 0.9, one hour, 15 mm/hour capacity and 100% blockage: effective rainfall is 27 mm, baseline excess is 12 mm, clogged excess is 27 mm and additional excess is 15 mm. Volumes are 120 m3 baseline, 270 m3 clogged and 150 m3 additional. If only half the eligible hectare is influenced, additional volume is 75 m3. Green or excluded cells never contribute to that affected hectare.

| Blockage with the same one-hectare inputs | Clogged excess, mm | Additional volume, m3 |
|---:|---:|---:|
| 0% | 12 | 0 |
| 25% | 15.75 | 37.5 |
| 50% | 19.5 | 75 |
| 100% | 27 | 150 |

The relationship has thresholds when baseline drainage can remove all effective rainfall. For example, 10 mm effective rainfall and two hours at 20 mm/hour still leave zero excess with 50% blockage. Zero rainfall produces zero runoff. No selected existing route produces no additional effect, even if planned lines intersect the AOI. A positive baseline can remain outside selected influence, because baseline removal is assumed across eligible land.

These are locally unremoved runoff volumes. They are not volumes demonstrated to remain as standing water at those coordinates: surface flow could move them, storage could retain them, and real drainage could differ. Duration enters only the accumulated removal term; the calculation has no time-step storm dynamics.

## 11. A reproducible actual-data example

A 400 m by 400 m EPSG:7801 box centred on longitude 23.267111, latitude 42.684845 was evaluated with the defaults. It intersects one existing source route, ID `7275f97d-8520-46ce-9e5e-37c5e39eb169`, with 448.6345 m of clipped geometry. The example uses real spatial-index records, full green polygons and native aligned terrain cells.

| Quantity | Calculated result |
|---|---:|
| Selection area | 160,000 m2 |
| Green excluded on otherwise eligible land | 47,475 m2 |
| Eligible nongreen land | 112,525 m2, 4,501 cells |
| Affected eligible land | 33,125 m2, 1,325 cells |
| Affected area with P at least 70 | 0 m2 |
| Baseline potential unremoved volume | 1,350.3 m3 |
| Clogged potential unremoved volume | 1,847.175 m3 |
| Additional potential unremoved volume | 496.875 m3 |

No mapped-water or uncertain-terrain cells occurred in this example. Its additional volume is exactly `33,125 * 15 / 1000`. It demonstrates source selection and arithmetic, not an observed flood or validation of the default capacity. Different AOI boundaries, parameters or selected routes legitimately change the output.

The terrain-storage calculation finds one positive-fill component with 21 eligible cells, conservatively flagged as potentially boundary-truncated and partially influenced. Baseline estimated maximum depth is about 0.0881 m; clogged maximum is about 0.0931 m. Stored volume increases from about 6.300 to 6.675 m3. The large remaining runoff totals occur mostly on zero-fill land and are explicitly unallocated: 1,344 m3 baseline and 1,840.5 m3 clogged. These values illustrate why runoff volume and ponded depth are different outputs.

## 12. Distinguishing mapped-river context

River proximity uses only 18 source polygons explicitly tagged as river and 19 actual official river-reach geometries. Lakes, ponds, reservoirs and four schematic assessment identifiers are excluded from this distance calculation. Distances are measured in metres in EPSG:7801 from each eligible cell centre to the genuine mapped geometry. A point within an actual river polygon has distance zero; existing mapped water remains excluded from terrestrial scenario cells.

The default 100 m threshold creates contextual categories: river-adjacent, possible mixed influences; away from mapped rivers; and unknown if the source context is unavailable. This is not an invented river inundation buffer or floodplain. Near-river land can flood from rainfall, river overflow, outfall backwater or several interacting processes. Distance cannot determine which occurred. Away from mapped rivers does not prove a purely pluvial cause or exclude an unmapped covered channel. Source-reported event mechanisms remain unchanged.

The display filter can show all cells, only river-adjacent cells, or only cells away from the mapped rivers. It uses the actual same-grid classification mask without resampling scores. Filtering does not change rainfall, storage allocation, full-AOI statistics or the six-band download. Category areas partition eligible nongreen land, and depth/volume summaries are available within each category. Compare those areas with the eligible denominator, not the full rectangle including green and excluded terrain. A threshold change recalculates context with the entered value; it does not create a fluvial hydraulic simulation.

## 13. Reading simultaneous map layers

Buildings are neutral grey filled shapes. The selected AOI uses a cool blue fill/boundary and selected pipes have their own line highlight. Warm colours are reserved for the active terrain susceptibility or scenario runoff field. This lets area and risk information appear together without giving a building fill the meaning of a hazard class.

When a blockage scenario is visible, its selected depth or runoff heatmap replaces the terrain risk raster as the active warm field. Independent terrain inspection, historical/assessment overlays, routes, green areas and building context remain available. The three runoff views share a 0-to-effective-rainfall mm scale. The three depth views share a metre scale extending to the clogged maximum, with a minimum displayed range of 0.05 m. This preserves valid comparisons: a smaller change is not independently stretched to look as severe as the clogged total. Zero is transparent; excluded cells are also transparent but separately identified by statistics and context.

Rainfall remains supplemental and independently controlled. Its daily observations are not summed with the entered event rain. Historical visibility and visual priority affect presentation, while the categorical review's historical input remains the documented source geometry. Displaying buildings does not convert them into hydraulic barriers or alter source heights.

## 14. Reproduction, audit and next improvements

Open the **Scenario** tab, choose **Draw pipe selection area**, drag a rectangle, inspect intersecting existing route IDs, set the assumptions, and calculate. Adjust the rainfall slider, compare baseline, clogged and additional depth or runoff views, and use the river-context filter when useful. Check eligible, green and affected areas before interpreting volume. Download the six-band scenario GeoTIFF and separate JSON result record, retaining exact parameters and source revisions. Bands 1-3 preserve baseline/clogged/additional runoff in mm; bands 4-6 contain estimated baseline/clogged/additional local ponding depth in m. The normal Share view link stores map-layer settings, not the current drawn geometry or scenario inputs.

Several terms in the result deliberately answer different questions. Selection area is the exact vector area of the drawn polygon. Rasterized selection area is the count of included cell centres multiplied by 25 m2. Eligible area is the part where this scenario can be calculated after exclusions. Affected area is eligible area within the unioned selected-route influence, irrespective of whether the entered blockage actually increases excess runoff. Additional volume is the arithmetic change under the assumptions; it can be zero even when affected area is positive. The scalar formula for excess inside influence remains a conditional parameter-derived value when there are no influenced eligible cells; it does not create runoff where that domain is empty.

Likewise, grey building shapes identify a source footprint, not a validated flood barrier, safe building or damaged asset. A historical polygon is an observation footprint, while an official assessment polygon is a supplier's prospective classification. A route marked existing is a source status rather than evidence that it is open, maintained or correctly connected today. Keeping these meanings separate makes the result auditable without turning missing operational measurements into false precision.

The API entry point is `POST /api/clogging/scenarios`; the result can be reread at `/api/clogging/scenarios/{id}`. It includes actual AOI and clipped-route geometry, assumptions, equations, units, selection counts, grid offsets, depth/volume balances, river context and download/tile links. A deterministic ID binds geometry, selected IDs, parameters, source signatures/revisions and implementation hash. The local cache is a separate derivative. Source changes invalidate reuse rather than silently mixing snapshots; the GeoTIFF and aligned river-mask checksums are verified before serving cached results.

Implementation is in `backend/clogging.py` and `backend/clogging_routes.py`; real-data tests are in `tests/test_clogging.py`. Original descriptor construction is in `scripts/prepare_pluvial.py` and `backend/pluvial.py`; review preparation is in `scripts/prepare_review_priority.py`. Full application validation uses:

```text
python -m pytest tests -q
pnpm test
pnpm build
```

Targeted tests verify the real selected route, full-green exclusion, unchanged grid alignment, volume closure, planned-route nonfunction, zero blockage, empty selection, finite/area guards, source staleness, PNG rendering, HTTP validators and raster downloads. Current test/build counts belong in the final verification receipt, not inferred from older baselines.

A more predictive model would need surveyed pipe connectivity, diameters and inverts, inlet capture, outfall levels, condition/maintenance observations, subdaily design or observed storms, soil/storage information and verified surface-flow barriers. [EPA SWMM](https://www.epa.gov/water-research/storm-water-management-model-swmm) is an example of a model with explicit runoff and drainage-network hydraulics. Coupling a verified network with surface routing and independent event observations would address mechanisms this app intentionally leaves unresolved. Until those inputs exist, the implemented calculation supports transparent comparative scenarios and inspection priorities.
