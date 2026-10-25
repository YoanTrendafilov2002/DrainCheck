# Evidence and interpretation for the Sofia pluvial screen

Reviewed 24 October 2026. The machine-readable evidence register is [pluvial_evidence.json](pluvial_evidence.json). Source findings and implementation choices are deliberately distinguished below.

## What the evidence supports

| Evidence | Relevant conclusion |
| --- | --- |
| [Sofia Municipality, Strategic Security Vision 2024–2030](https://www.sofia.bg/documents/d/guest/strategiceska-vizia-za-sigurnost-na-stolicna-obsina-2024-2030), §3.16, page 11 | Intense-rainfall urban flooding is an identified local concern. The document supplies no street-level labels to validate this map. |
| [Huang et al., Water 2019, DOI 10.3390/w11102115](https://www.mdpi.com/2073-4441/11/10/2115) | Depression/catchment analysis is useful, but terrain indices remain incomplete risk measures. Small depressions and coarser grids need care. |
| [Environment Agency, surface-water map method, updated 2025](https://www.gov.uk/government/publications/flood-risk-maps-for-surface-water-how-to-use-the-map/risk-of-flooding-from-surface-water-understanding-and-using-the-map), §§3.2–3.5 | Operational hazard estimates also need rainfall, runoff and drainage, hydraulic modelling and independent local review. Its England parameters are not Sofia parameters. |
| [Poppenga et al., USGS 2010–5059](https://pubs.usgs.gov/sir/2010/5059/) | Elevation obstructions and depression filling can misroute water where drainage through structures is missing. |
| [UNDRR: Disaster risk](https://www.undrr.org/terminology/disaster-risk) and [Exposure](https://www.undrr.org/terminology/exposure) | Asset overlap is exposure context; quantitative risk also requires hazard, vulnerability and capacity. |

## The scientific meaning of the available inputs

The 1 m municipal elevation grid is real terrain data. The existing 5 m derivatives can support inspection of depressions, slopes and simplified surface-flow convergence. Grid spacing does not establish survey accuracy, and averaging to 5 m can remove small kerbs, road crowns and shallow storage. Preserve the 1 m click inspection and retain the original raster unchanged.

Depression fill depth is the vertical difference between the unfilled terrain and its filled spill surface. It describes geometric storage or a possible obstruction. It is not a simulated storm-water depth. A deeper bowl can also take more runoff to fill. Upstream contributing area describes the chosen terrain routing; it supplies neither runoff volume nor discharge without rainfall and losses. A large value may follow a river valley. Neither factor proves that a flood has occurred or will occur.

The 2009 sewer lines show archived infrastructure geometry and recorded status. They lack current topology, inverts, diameter, inlet locations, hydraulic capacity and condition. The infrastructure CSV contains survey records, not a verified inventory of independent assets or storm inlets. The green polygons date to 2020 and do not measure permeability, infiltration, saturation or storage. Retain these as context or exposure overlays; do not infer drainage protection from line/point density or green-area membership. Imperviousness is excluded from the active map under the user's previous instruction.

## Analyst choices and checks

The application may use an explicit, reproducible rule to prioritize terrain for inspection. Percentile ranks, composite weights, slope cutoffs, depression filters and colour classes in such a rule are analyst choices. Their physical motivation comes from the evidence above; their numerical values have not been validated for Sofia. A percentile of 90 means a value ranks above roughly 90% of the reference cells; it does not mean a 90% chance of flooding. A cell composite is not the published depression-catchment TCI.

Keep the raw factor layers available and show the formula and reference mask. Compare a balanced rule with depth-focused and flow-focused variants. Report both disagreement and stable priority overlap. Agreement between variants is a sensitivity result, not an accuracy estimate. Preserve NoData as unknown and distinguish the downstream footprint of boundary/missing-upstream terrain. A non-highlighted cell has not been demonstrated safe.

Report infrastructure records and archived route length overlapping each priority class separately from the terrain rank. Do not multiply survey-record density into a supposed damage or risk probability. Source dates, planned status, the treatment of duplicate records and spatial coverage belong with those counts.

## Implemented exploratory rule

The application implements `terrain-relative-screen-v1` on the actual aligned 5 m raster. For valid cells, with depression fill depth `d` in metres, contributing area `a` in square metres, and local ground slope `s` in degrees:

```text
P = 0                              if d = 0
P = 100 × R_positive_depth(d)       if d > 0
C = 100 × sqrt(R_area(a) × (1 − R_slope(s)))
S = max(P, C)
```

Each `R` returns a fraction from 0 to 1 using a fixed reference: every fourth row and every fourth column of the 5 m grid, aligned at global row/column zero. This is a systematic sample at 20 m spacing of actual 5 m cells, not a 20 m averaged terrain model. References cover eligible cells throughout the available municipal DTM footprint, including mountainous terrain; they are not urban-only or recomputed when the map moves. The depth reference includes positive depths only. Each distribution uses 201 quantiles, with linear interpolation and a mean percentile position for repeated quantile values. Thus this is an approximate reference rank, not an exact empirical percentile of all 5 m pixels. The combined `S` is not itself a percentile.

Only cells with finite valid depth, slope and contributing area and an unflagged boundary-input indicator are assigned scores. Depth must be nonnegative, slope between 0 and 90 degrees, and contributing area at least one 25 m² analysis cell. Boundary influence and missing factors remain unscored. Native elevation sampling remains at 1 m.

Mapped existing open water is excluded separately from this land screening. The
mask uses real OpenStreetMap water polygons and a pixel-centre rule on the aligned
5 m grid; it does not buffer water lines or extend an exclusion across nearby
banks. The source query, acquisition snapshot, selected tags, limitations and
preparation command are documented in [OPEN_WATER_SOURCES.md](OPEN_WATER_SOURCES.md).
Polygon coverage and shoreline positions may be incomplete or outdated.

Masked cells are transparent in the screening overlay, return no relative score
in the location inspector and remain in inventories as **Excluded open water**.
They are omitted from ranked land classes and threshold exposure counts, rather
than being assigned a zero or safe score. Native elevation and original terrain
factors remain available. This distinguishes existing mapped water from potential
new ponding on land; it does not establish that a water body, bank or neighbouring
property is safe from pluvial or river flooding. No additional visible water
overlay or user switch is needed.

The display classes are **Lower signal** `[0, 50)`, **Raised** `[50, 70)`, **Higher signal** `[70, 85)` and **Strongest signal** `[85, 100]`. These boundaries and the choice of maximum/geometric-mean combination are analyst decisions, with no fitted Sofia flood thresholds. In particular, `P` ranks geometric depth-to-spill; deeper storage receives a stronger geometric signal without establishing that it floods more frequently. `C` highlights large contributing area and relatively low local slope, without predicting flow velocity or isolating river flooding.

Current sensitivity reporting changes the combined-score inspection threshold to 70, 80 and 90 and reports terrain area, point-record counts and approximate archived route lengths above each. This is threshold sensitivity only: it does not establish calibration, test alternate factor combinations, quantify DTM uncertainty or measure predictive accuracy. The separate `P` and `C` layers allow inspection of which terrain pathway drives the combined result.

## What is still needed for a flood-risk prediction

A rainfall event or local intensity-duration-frequency relationship is needed to evaluate forcing. Current drainage and culvert hydraulics, infiltration and antecedent wetness, and a checked urban surface are needed to predict routing and ponding reliably. Independently dated, geolocated pluvial observations and known coverage/negative cases are needed to test performance; river flooding must be separated. Exposure inventories and vulnerability or damage relationships are needed to estimate consequences. Until those are available and validated, describe the result as a relative terrain screening map with infrastructure exposure context, not a flood-depth forecast, annual probability, return period, safe/unsafe boundary or expected loss.

## Dated local evidence for follow-up

The [municipal situation report of 16 June 2023](https://www.sofia.bg/w/%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F-%D0%B7%D0%B0-%D0%BE%D0%B1%D1%81%D1%82%D0%B0%D0%BD%D0%BE%D0%B2%D0%BA%D0%B0%D1%82%D0%B0-%D0%BA%D1%8A%D0%BC-7-00-%D1%87%D0%B0%D1%81%D0%B0) identifies ponding closures on the southern ring road and at Lion's Bridge tunnels overnight, and storm incidents in several named districts. It is useful for obtaining precise incident records; the broad locations are not mapped validation labels.

The [NIMH October 2025 bulletin](https://bulletins.cfd.meteo.bg/bull/Buletin_NIMH_202510.pdf), page 11, reports a flooded Sofia intersection and tram disruption on 27 October, with 42.9 mm in 24 hours. The intersection is unnamed in the text. These two reports confirm local relevance but provide neither sufficient coordinates/footprints nor non-event coverage to calibrate or score this screen. They are retained in the JSON as historical evidence leads, explicitly with `calibration_used: false`.
