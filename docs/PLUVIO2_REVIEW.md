# NASA Pluvio2 review and relevance to Sofia

Reviewed 25 October 2026. The supplied [NASA instrument URL](https://www.earthdata.nasa.gov/data/instruments/pluvio2) returned HTTP 403 to the research tool. NASA's accessible [CASEI Pluvio instrument record](https://impact.earthdata.nasa.gov/casei/instrument/Pluvio/) links to that exact page and identifies the instrument and its deployments. Official NASA dataset records, GHRC documentation and the manufacturer's manual support the findings below.

## What it measures

**Pluvio2 is an OTT ground-based weighing precipitation gauge, not a flood-mapping algorithm or a satellite rainfall grid.** A load cell measures the collection bucket's changing mass. Known collector area converts water mass to an equivalent precipitation depth; changes over time provide precipitation rate. Liquid, solid and mixed precipitation can be collected. NASA identifies typical one-minute sampling and **point** spatial support. A minute is temporal resolution, not a one-metre or five-metre map resolution. [NASA CASEI](https://impact.earthdata.nasa.gov/casei/instrument/Pluvio/)

For the current **Pluvio² L variant**, the manufacturer describes six-second internal weighing with 0.001 mm-equivalent raw resolution, processed output at 0.01 mm resolution, temperature compensation of the weighing mechanism, and filtering of disturbances such as wind. Its outputs distinguish real-time (RT) and more heavily filtered non-real-time (NRT) data. These are instrument-processing details, not terrain/runoff equations; specifications differ by instrument variant and firmware. [OTT L operating instructions, §§4–4.1, printed pages 8–12](https://cdn.hach.com/1XMCM0ZF/at/hqb367sgkf47xb77nhs85wrs/Operating_instructions_Pluvio2_L_V3.pdf)

NASA's [Albert Head OLYMPEX user guide](https://ghrc.nsstc.nasa.gov/pub/fieldCampaigns/gpmValidation/olympex/disdrometers_and_gauges/EC_AHD_met_station/doc/gpmahdmetolyx_dataset.pdf) also describes temperature and other measurement corrections in Pluvio2 processing. This does not establish a universal correction for all wind-induced catch losses or guarantee representativeness over a city. Siting, calibration records, exposure, maintenance and campaign quality flags still need review before using a particular time series.

## Rate and accumulation require different handling

The L manual's **Intensity RT** represents the preceding minute, with a 0.1 mm/min (6 mm/h) threshold and values below that threshold set to zero. It warns against summing these values into rainfall totals. Polling less frequently does not turn that last-minute rate into an interval average. **Accu NRT** provides interval amounts with a five-minute delay; the cumulative-total channel has different reset semantics. These distinctions must be checked for the actual model/data product rather than applied indiscriminately. [OTT L manual, §4.1](https://cdn.hach.com/1XMCM0ZF/at/hqb367sgkf47xb77nhs85wrs/Operating_instructions_Pluvio2_L_V3.pdf)

NASA's [Pluvio2 data-format specification](https://ghrc.nsstc.nasa.gov/pub/doc/gpmgv/pluvio/DataFormat_Pluvio2.pdf), last updated September 2011, lists one-minute ASCII records with RT intensity in **mm/h**, accumulation/bucket channels in **mm**, and temperature in °C. Its event tables contain event start/end and accumulated rainfall, or snow's liquid-water equivalent. These are different quantities; a generic numeric sum across columns would be wrong. Confirm each campaign's time zone, timestamp alignment, missing-value codes, channel definition, delayed output and any resets before deriving a hyetograph.

An interval rainfall depth `p_mm` over `dt_minutes` corresponds to mean intensity `60 × p_mm / dt_minutes` in mm/h. For a valid interval-mean rate, interval depth is `rate_mm_per_hour × dt_minutes / 60`. These dimensional conversions do not override thresholding, missing records, overlapping rolling intervals or the manufacturer's warning about RT totals. Use a quality-controlled amount channel for totals where appropriate.

## What NASA actually provides

The inspected NASA records are campaign observations with limited station/time coverage, rather than a global Pluvio2 rainfall surface:

| Product | Verified geography and archived temporal extent |
| --- | --- |
| [LPVEx, DOI 10.5067/GPMGV/LPVEX/PLUVIO/DATA301](https://www.earthdata.nasa.gov/data/catalog/ghrc-daac-gpmpllpvex-1) | Three sites in Finland; catalogue extent 15 September 2010–13 January 2011. |
| [GCPEx, DOI 10.5067/GPMGV/GCPEX/PLUVIO/DATA301](https://www.earthdata.nasa.gov/data/catalog/ghrc-daac-gpmplgcpex-1) | Five sites in Ontario, Canada; 8 December 2011–29 February 2012. |
| [OLYMPEX Pluvio, DOI 10.5067/GPMGV/OLYMPEX/PLUVIO/DATA301](https://www.earthdata.nasa.gov/data/catalog/ghrc-daac-gpmplolyx-1) | Three sites on Washington's Olympic Peninsula; 31 October 2015–31 January 2016, varying by site. |
| [Albert Head MET OLYMPEX](https://www.earthdata.nasa.gov/data/catalog/ghrc-daac-gpmahdmetolyx-1) | A multi-instrument station in British Columbia, Canada; 13 November 2015–17 January 2016. |
| [SBU Pluvio IMPACTS, DOI 10.5067/IMPACTS/PLUVIO/DATA101](https://www.earthdata.nasa.gov/data/catalog/ghrc-daac-sbuplimpacts-1) | New York sites; catalogue extent 7 January 2020–2 March 2023, with campaign-season gaps. |

The [CASEI instrument inventory](https://impact.earthdata.nasa.gov/casei/instrument/Pluvio/) additionally lists an ICE-POP deployment in South Korea in 2017–2018. No Sofia/Bulgaria Pluvio2 product was found in the inspected NASA instrument inventory and linked product records or the bounded official-domain search. This is a finding about the records reviewed, not proof that no Pluvio instrument exists in Bulgaria.

## How it could improve the Sofia workflow

**Inference for this app:** quality-controlled local gauge records of this kind could provide the rainfall forcing that the current terrain screen lacks. A useful input would include station coordinates, real observation timestamps, interval amounts/rates with units, instrument/channel identity, quality flags and coverage. Several gauges and/or checked radar observations would better represent spatially variable urban storms than a single point. A foreign campaign's event record must not be presented as Sofia observations.

These rainfall measurements could support event hyetographs and testing of a runoff/drainage/hydraulic model. They do not by themselves supply infiltration, imperviousness, sewer/inlet capacity, building/kerb/culvert geometry, flood footprints or vulnerability. They cannot validate a terrain-only index without independent flood observations, and they do not explain or confirm a stadium hotspot. The existing Sofia map remains an unvalidated terrain screen; this review adds no rainfall values and changes no scores.
