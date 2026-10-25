# Prototype behavior and app implementation notes

## Existing scripts

`Script1.js` is the map/UI entry point. It requires `users/yoantrendafilov2002/rivertracker:Script2`. Script2 supplies the remainder of a compressed data payload plus a DEFLATE decoder. The packed payload contains original route identifiers/labels, three route-zone representations, and the 2,175-polygon green display subset. Both files were saved and run successfully in the existing Code Editor session. The snapshots are 511,862 and 511,982 UTF-8 bytes respectively.

Embedding and decoding this vector payload made initial startup take several minutes in the Code Editor. This was a workaround for data ingestion constraints, not a target architecture. The app should read prepared files/tiles or query indexed data. The two prototype files remain a lossless behavior reference; they are not ordinary React/Node modules. `Map`, `ui`, `ee`, and `Export` are Earth Engine facilities and require replacement/adaptation outside that environment.

The `archive/` scripts are historical helpers with their original working-directory assumptions (`upload/`, `work/`). Keep them for provenance. For a portable rebuild use `scripts/prepare_vectors.py`. The table-asset upload ZIPs are legacy transfer outputs with shapefile field/type limitations; the raw and newly derived GeoJSON are the preferred app data.

## Elevation display math

Let `q_i` be the sampled elevation percentile at `p_i = i / 2` percent, for `i=0..200`. Let `low=q_0` and `high=q_200`. For non-flat data, form the normalized knots:

```
x_i = q_i
y_i = 0.8 * (i / 200) + 0.2 * ((q_i - low) / (high - low))
```

Keep only strictly increasing `x_i` values (first occurrence of repeated heights), then force the first and last retained y values to 0 and 1. Apply continuous piecewise linear interpolation from native height x to normalized display y, clamped at both ends. For a completely flat sample set, use x `[low-0.5,low+0.5]` and y `[0,1]`, so the actual flat height maps to the middle. This fallback is a display interval, not evidence that the terrain varies by 1 m.

Map y continuously along the nine palette anchors in `map_config.json`. These are **201 percentile control points**, not 201 discrete elevation bins and not a claim of 0.5 m resolution. Do not quantize raw heights. The whole-area reducer requests 60 m statistics samples; local fit requests 10 m samples, with best effort and max 2,000,000 pixels. Approximate histograms use maxBuckets 65,536, minimum bucket width 0.05 and maxRaw 4,096. These settings affect contrast estimation only.

Use `shared/elevation_scale.mjs` for the portable transformation and inverse legend mapping. Its independent tests cover uniform and repeated quantiles, flat terrain, small relief, invalid values, source-array preservation and transparent NoData. A display approximation is allowed only if explicitly identified and visually validated; do not quietly replace the method with simple min/max stretching.

The default whole-area stretch covers valid pixels in the study rectangle, not every possible region. The observed five inverse legend ticks were 501.0, 574.3, 808.3, 1062.6, 2278.8 m at normalized levels 0, 0.25, 0.5, 0.75, 1. The full 201-point statistics have now been retrieved by a live read-only Earth Engine query and are bundled in `data/reference/elevation_quantiles_whole_area.json`; use that file for the actual default curve. Local sample ranges observed in two close-up views included 508–576 m and 512–601 m. Those are viewport-specific examples, not global constants.

## Stable versus local scale

- Default: cache whole-study-area statistics and keep colours stable when the user pans/zooms.
- Local fit: compute statistics for the visible bounds intersected with the study rectangle; preserve that scale until another explicit change.
- Reset: restore the cached whole-area scale immediately.
- Auto-fit: explicitly opt in; debounce viewport changes and ignore stale asynchronous results.
- If a user pans beyond a manually fitted local scale's useful range, show its locked scope and an obvious fit/reset action. Do not silently alter colours when auto-fit is off. Endpoint clipping of values outside a declared local range is mathematically expected; do not disguise it as missing source data.
- Use a scope or revision identifier in tile cache keys. Legend and tile colours must refer to the same statistics revision. A request failure must keep the last valid map and show a meaningful status instead of substituting invented heights.

## Spatial layers and UI

Routes: existing cyan `#00e5ff`, planned dashed magenta `#ff4dce`, open channels yellow `#ffeb3b`. Prototype width is 3 px. Initial zone is inside green areas with all statuses enabled. Green outlines are `#246b35`, width 1 px, fill `#52c468` with alpha 80/255. Point-layer colours/counts are in the configuration. Terrain opacity is 0.95, and the separate grayscale hillshade layer has opacity 0.22.

Prefer a responsive sidebar/drawer over the prototype's three large floating panels. Retain full source properties for inspection and selected-feature export. Avoid competing legend meanings: green polygons are categorical land-cover features, while the green part of the elevation ramp is a height colour. Label each separately.

The available data support actual geometry filtering and geographic inspection. They do not support deducing flow direction from terrain slope or interpolating pipe connections between utility points. Route date labels and source limitations belong in the provenance panel.

## Suggested app boundaries

- Frontend: map view, layer controls, route filters, inspection, accessible legend, URL state and selected-data download.
- API/data layer: viewport feature queries, native elevation sample, whole/local normalization statistics and tile delivery with request cancellation and caching.
- Preparation: source-preserving geometry repair/clipping, statistics, vector tiling/indexing and raster display derivatives.
- Inputs: immutable originals and authoritative numeric raster; never put the municipal 1 m raster into the browser JavaScript bundle.

MapLibre supports raster tile sources alongside vector sources. Its tile size must match the actual source output. Reference: https://maplibre.org/maplibre-gl-js/docs/API/classes/RasterTileSource/ . Keep tile provider configuration/attribution explicit. A basemap is optional for tests and should not determine access to the real supplied vectors.

## Definition of ready

The app can start from documented local commands; real bundled vectors render and filter correctly; required missing cloud inputs have explicit states; native elevation and tile endpoints work when authorized data are available; geometry/count/length checks pass; nonlinear legend agrees with the renderer; data remain unchanged; and regional plus close-up screenshots have been inspected. Record any remaining credential/data/deployment blockers. A UI-only mockup or placeholder DEM is not completion.

## Rainfall reference precedence

`earth_engine/Rainfall_20250627_original.js` is the newly attached source, preserved exactly. Add its rainfall functionality following `docs/RAINFALL.md`; retain the existing two prototype scripts, full green-mask/route behavior, and the newer stable granular elevation normalization above. Its older default terrain auto-fit and P2–P98 stretch must not override the user's subsequent colour requirements. The actual daily rainfall assets are now bundled as native-grid COGs plus full numeric snapshots, so rainfall is available independently of the unbundled DTM/infrastructure points.
