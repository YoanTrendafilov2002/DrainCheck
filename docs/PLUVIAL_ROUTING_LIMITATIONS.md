# Why the concentration and combined layers are experimental

The first real-map visual check revealed dense parallel and diagonal stripes across central Sofia. The same structure is present in the **raw D8 contributing-area raster**, before percentile ranking and map colouring. The concentration index amplifies it; it is not a browser rendering error. These patterns cannot be presented as verified street-level flood hotspots.

The ponding layer is the default topographic inspection layer. Concentration and combined layers remain experimental diagnostics for investigating terrain routing. This choice does **not** validate ponding as a flood model: depression-fill depth is not water depth, and zero fill depth does not establish safety.

## Actual-data diagnosis

The machine-readable receipt is [pluvial_routing_diagnostic.json](../test-artifacts/pluvial_routing_diagnostic.json). Its six-panel visual is [pluvial-routing-diagnostic.png](../test-artifacts/pluvial-routing-diagnostic.png).

The analysis used every base-resolution cell in a 512 × 512 window of the actual 5 m derived raster, centred near longitude 23.3219, latitude 42.6977. It covers a 2.56 km square: EPSG:7801 bounds `[320277, 4730161, 322837, 4732721]`. The receipt records geographic bounds, raster SHA256, exact window offsets, valid-cell rules, quantiles, and diagnostic parameters. No terrain was invented, smoothed, shifted or changed.

Of 261,627 eligible cells in that window:

- 260,470 (99.56%) have a concentration score at least as large as the depression score.
- 259,152 (99.05%) have zero depression-fill depth.
- 20,215 have a combined score of at least 85. Of those, 19,737 (97.64%) have zero depression-fill depth, and 20,031 already meet that cutoff through concentration alone.

The municipal reference distribution ranks a contributing area of just 1,000 m² at the 80th percentile. On a 0.3° slope, the concentration score is about 83 for 1,000 m² and 88 for 2,000 m². Thus the ranking can strongly emphasise narrow parallel D8 flow paths even where no topographic depression is present. The percentile is a position in this DEM's distribution, not an observed flood frequency.

A diagnostic subset of 8,919 cells has a 7 × 7 local slope standard deviation below 0.01°, with slope between 0.1° and 2°. Their combined scores still span approximately 17–92. Immediate east/north neighbours differ by about 10 score points on average; about one fifth of those neighbour pairs differ by at least 20 points. This subset is a descriptive test of visually uniform facets, not a validated mask for erroneous terrain.

The diagnostic picture stretches each actual-data panel separately between its 2nd and 98th percentiles for visibility. Contributing area is shown on a logarithmic scale. This display stretch does not modify any source or analysis values.

## Interpretation and next methodological checks

D8 assigns each cell to one of eight neighbours, constraining flow directions to the grid. Grid alignment can create parallel flow-path structure on planar, divergent or interpolated terrain. The observed elevation/slope panels also contain conspicuous facets and flat plateaus. A specific TIN or contour lineage cannot be established from appearance alone; the exact survey method, date and vertical accuracy remain unverified.

[Tarboton (1997)](https://digitalcommons.usu.edu/cee_facpub/2507/) describes this directional bias and a D-infinity approach that divides flow between two neighbours. The [official GRASS `r.watershed` manual](https://grass.osgeo.org/grass85/manuals/r.watershed.html) describes multiple-flow routing, its convergence parameter, and uncertainty from incomplete upstream terrain. Such alternatives introduce their own flow-dispersion and parameter choices; switching algorithms alone would not establish flood accuracy.

A principled next comparison would rerun accumulation using a documented D-infinity or multiple-flow implementation, preserve the same real elevation grid, and map disagreement between routing methods. It should then be evaluated against independently surveyed drainage and flood-event evidence. This demo does not claim that comparison or validation has occurred.

Blurring the coloured map would conceal the numerical pattern without establishing physical drainage paths. Arbitrary minimum contributing-area or depth cutoffs would also require a defensible measurement/validation basis. Neither was applied as a purported correction.

## Exposure totals follow the selected mode

Point and route overlap totals are calculated separately for ponding, concentration and combined layers. All three use all 322,025 supplied point records and all 717 full source routes. They retain boundary uncertainty and NoData, preserve source geodesic route length, and do not estimate drainage capacity, damage, buildings, residents or economic loss.

The concentration/combined overlaps inherit the routing sensitivity documented here. Low ponding overlap should not be interpreted as low flood risk: rainfall intensity, inlet/sewer capacity, infiltration, barriers, surface changes and observed inundation remain unmodelled.
