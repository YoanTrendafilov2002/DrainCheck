# Vasil Levski stadium: what actually drives the map colour

**The verified raster contains no depression-fill depth anywhere in the mapped pitch or whole Vasil Levski stadium footprint.** Its higher combined score comes entirely from the experimental concentration calculation: a very shallow slope and D8 contributing-area ranking. The raster does not support explaining this stadium as a filled topographic bowl.

The [actual-data four-panel check](../test-artifacts/vasil-levski-terrain-check.png) shows elevation, geometric fill depth, D8 contributing area and concentration score, with the actual OpenStreetMap stadium/pitch outlines. [The JSON receipt](../test-artifacts/stadium_screening_check.json) records geometry sources, exact coordinates, raster identity, native-pixel checks, percentile references and zonal distributions. No map values or stadium masks were changed.

## Identity and exact sample

Sofia's [municipal tourism listing](https://www.visitsofia.bg/en/cityinfrastructure/what-to-do/sports-halls-and-stadiums/vasil-levski-national-stadium) identifies the national stadium at 38 Evlogi and Hristo Georgievi Boulevard, also the address given by the [National Sport Base operator](https://www.nsb.bg/en/nsb/%D0%BD%D1%81-%D0%B2%D0%B0%D1%81%D0%B8%D0%BB-%D0%BB%D0%B5%D0%B2%D1%81%D0%BA%D0%B8-en/).

The pitch polygon is [OSM way 1304896487](https://www.openstreetmap.org/way/1304896487), version 3; the whole stadium polygon is [OSM way 341968882](https://www.openstreetmap.org/way/341968882), version 16. These are public map geometries, not engineering surveys or drainage designs. OSM attribution: © OpenStreetMap contributors, ODbL 1.0.

The tested pitch centroid is longitude **23.3352531692**, latitude **42.6875642953**. Its projected location is `[322624.0695, 4730282.4738]` in EPSG:7801. It falls in 5 m row **4665**, column **4646**, whose centre is `[322624.5, 4730283.5]` (longitude 23.3352581003, latitude 42.6875736301).

| Actual factor at that 5 m cell | Value |
|---|---:|
| Mean ground elevation, Baltic 1982 | 542.4961 m |
| Depression-fill depth | **0 m** |
| Ponding rank | **0 / 100** |
| Slope | 0.443846° |
| D8 contributing area | 625 m² |
| Concentration score | 75.7903 / 100 |
| Combined score, max of the two pathways | 75.7903 / 100 |

The contributing-area rank is **0.6925**, the slope rank **0.170518**, and the flatness fraction `1 − slope_rank` is **0.829482**. Consequently:

`100 × sqrt(0.6925 × 0.829482) = 75.79025`.

These ranks use the whole available municipal terrain distribution, including mountains, approximated by 201 quantiles of a fixed 20 m sample of the 5 m grid. A score of 75.8 is **not** a 75.8% flood probability. The 625 m² is algorithmic upstream surface area on this DEM, not a surveyed or validated stadium drainage catchment.

## Entire pitch and stadium, rather than one selected cell

Every 5 m cell centre inside each actual OSM polygon was checked. The read windows explicitly cover floor(minimum) through ceil(maximum), avoiding cropped polygon-edge cells.

| Zone | Checked 5 m cells | Cells with positive fill depth | Concentration median | 95th percentile | Maximum |
|---|---:|---:|---:|---:|---:|
| Pitch | 294 | **0** | 68.81 | 88.94 | 90.46 |
| Whole stadium envelope | 1,557 | **0** | 58.12 | 83.80 | 94.76 |

All checked pitch and stadium cells therefore have ponding rank zero, and combined equals concentration. On the pitch, the exploratory concentration classes are 9.52% lower signal, 43.88% raised, 37.41% higher signal and 9.18% strongest signal. This variation on a nearly uniform pitch is consistent with the documented sensitivity to D8 parallel flow paths and the municipal percentile reference; it is not evidence that those coloured strips are observed inundation zones.

The part of the stadium envelope outside the pitch includes stands, track and other surfaces. It is not a separately surveyed seating or roof polygon. Nearby land outside the stadium can contain positive fill depth; it should not be attributed to the stadium itself merely because it is close on the map.

## Native 1 m data check

The source 1 m pixel containing the pitch centroid is row **23328**, column **23232**, centred at `[322624.5, 4730282.5]`; its elevation is **542.5020 m**. The exact 5 × 5 native-pixel block underlying the sampled 5 m cell ranges from **542.4742 to 542.5179 m** and averages **542.49609375 m**, exactly the stored 5 m mean. This is a verified aligned aggregation, not artificial elevation data or a preview image.

The pitch contains 7,354 native 1 m cell centres versus 294 analysis-cell centres: approximately 25 native samples per 5 m cell. Their represented areas are 7,354 m² and 7,350 m²; the small difference arises at polygon boundaries. Neither spacing nor these internally consistent means establishes the source survey's vertical accuracy or current stadium microtopography.

## What this does and does not establish

The real evidence explains **why the current experimental formula colours the stadium**. It does not establish its actual pluvial flood risk. No field drainage, pumps, inlets, sewer capacity, turf infiltration, contemporary engineering survey, rainfall event or confirmed stadium flood observation enters this calculation. Surface type alone does not establish infiltration performance, and the dataset cannot determine whether drainage is sufficient or deficient.

The appropriate response is to label concentration/combined results as experimental and inspect their factors, as documented in [PLUVIAL_ROUTING_LIMITATIONS.md](PLUVIAL_ROUTING_LIMITATIONS.md). Arbitrarily removing the stadium or forcing its score lower would conceal a general model limitation. Conversely, zero mapped depression depth is not proof that the stadium cannot flood.
