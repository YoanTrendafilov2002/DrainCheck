"""Extract source-backed Sofia historical records without manufacturing geometry.

Requires openpyxl. Run from any directory after the original public source files
listed in data/reference/historical_floods/*acquisition_receipt.json are present.
Original XLSX/CSV/PDF files are opened read-only and never modified.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path

import openpyxl

APP = Path(__file__).resolve().parents[1]
REF = APP / "data/reference/historical_floods"
CACHE = APP / "data/cache"
REGISTER = "bddr_pastFloods_2020_2025.xlsx"
MAP = "bddr_sofia_pfra_map.pdf"
SOURCE_URL = "https://www.bd-dunav.bg/content/upravlenie-na-vodite/plan-za-upravlenie-na-riska-ot-navodneniia-2028-2033/aktualizaciia-na-porn/"
REGISTER_URL = "https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN%202028-2033/aktual_PORN/04_PFRA_BG1_APP04_pastFloods_2020_2025.xlsx"
MAP_URL = "https://www.bd-dunav.bg/uploads/content/files/upravlenie-na-vodite/PURN-2022-2027/aktualizacia_PORN/BG1_APSFR_IS_041.pdf"
FIELDS = ["event_id", "location_id", "significant_event", "significant_location", "ekatte", "settlement", "municipality", "province", "start_date_original", "start_time_original", "duration_hours", "repeat_count", "frequency_years", "flood_source_original", "mechanism_original", "characteristic_original", "description_original", "affected_territory_original", "data_source_original"]


def serializable(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = {name: sha(REF / name) for name in [REGISTER, MAP]}
    book = openpyxl.load_workbook(REF / REGISTER, read_only=True, data_only=True)
    sheet = book["bg1_pastFloods"]
    records = []
    for row_number, row in enumerate(sheet.iter_rows(values_only=True), 1):
        # Municipality code is explicit. Do not search free text or source URLs.
        if str(row[6] or "").strip() != "SOF46":
            continue
        record = dict(zip(FIELDS, map(serializable, row[:19])))
        source = str(record["flood_source_original"] or "")
        rain = "Дъждовно" in source
        river = "Речно" in source
        infrastructure = "Инфраструктурно" in source
        kind = "Pluvial + river" if rain and river else "Pluvial + infrastructure" if rain and infrastructure else "Pluvial" if rain else "Other / unclassified"
        original_date = row[8]
        start = original_date.date().isoformat() if isinstance(original_date, datetime) else original_date.isoformat() if isinstance(original_date, date) else None
        event_date = str(record["event_id"])[4:12]
        notes = []
        if start and event_date.isdigit() and start.replace("-", "") != event_date:
            notes.append("Event-ID date differs from the row start date; both are preserved, without correction.")
        if river:
            notes.append("Mixed river/rain source; do not classify as a pure pluvial observation.")
        if infrastructure:
            notes.append("Mixed rain/infrastructure source; no measured drainage capacity is supplied.")
        record.update({
            "id": f"bddr-2020-2025-row-{row_number}",
            "source_file": REGISTER,
            "source_sheet": sheet.title,
            "source_row": row_number,
            "source_url": REGISTER_URL,
            "start_date": start,
            "end_date": None,
            "date_precision": "Source row calendar day; event ID may represent a wider grouped event.",
            "type": kind,
            "reported_rain_source": rain,
            "reported_river_source": river,
            "reported_infrastructure_source": infrastructure,
            "geometry": None,
            "spatial_precision": "Text description only; multiple addresses or broad areas can occur within one row.",
            "quality_notes": notes,
        })
        records.append(record)
    book.close()
    counts = dict(Counter(r["type"] for r in records))
    summary = {
        "schema_version": 1,
        "source": SOURCE_URL,
        "register_url": REGISTER_URL,
        "publication_date": "2026-08-14",
        "publication_status": "Draft PFRA 2028–2033, published for consultation; not a final adopted plan.",
        "register_period": "2020–2025",
        "selection": "bg1_pastFloods!G == SOF46 (Sofia municipality)",
        "record_count": len(records),
        "unique_source_event_ids": len({r["event_id"] for r in records}),
        "type_counts": counts,
        "geometry_count": 0,
        "cautions": [
            "Rows are source records, not a count of independent incidents or inundated buildings; event IDs repeat and rows can contain multiple places.",
            "All selected rows describe Sofia municipality but EKATTE 68134 does not establish an exact incident coordinate.",
            "No coordinates, mapped footprints, measured depths or surveyed non-flooded controls are provided.",
            "Absence of a record is not evidence that flooding did not occur; records are not used to calibrate terrain scores.",
        ],
        "records": records,
    }
    (REF / "sofia_past_flood_records.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_fields = ["id", "event_id", "location_id", "start_date", "end_date", "type", "settlement", "municipality", "source_file", "source_sheet", "source_row", "source_url", "spatial_precision"] + FIELDS[8:]
    with (REF / "sofia_past_flood_records.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    # HANZE's affected-region membership is retained as context, never converted
    # to a flooded-area polygon or treated as a point observation.
    hanze = []
    with (REF / "HANZE_events_v3_0_1b.csv").open(encoding="utf-8-sig", newline="") as handle:
        for event in csv.DictReader(handle):
            affected = str(event.get("Regions affected (NUTS 3)", ""))
            if "BG411" in affected or "BG412" in affected:
                event["spatial_support"] = "Affected NUTS3 region membership, not an inundation footprint."
                event["source_url"] = "https://zenodo.org/records/20478847"
                hanze.append(event)
    (REF / "hanze_sofia_region_records.json").write_text(json.dumps(hanze, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "available": True,
        "title": "Official Sofia historical flood evidence",
        "source_url": SOURCE_URL,
        "description": "Official past-flood register with Sofia rain/pluvial reports, plus an earlier official PFRA map containing historical-event symbols. Records are evidence for inspection, not flood footprints or model calibration.",
        "coverage_label": f"Sofia municipality: {len(records)} source rows / {summary['unique_source_event_ids']} event IDs, dated 2020–2024; parent register covers 2020–2025.",
        "spatial_support": "Official map/PFRA register; no machine-readable incident geometry",
        "register_status": summary["publication_status"],
        "register_publication_date": "2026-08-14",
        "register_period": "2020–2025",
        "register_file": "data/reference/historical_floods/" + REGISTER,
        "register_url": REGISTER_URL,
        "record_count": len(records),
        "unique_source_event_ids": summary["unique_source_event_ids"],
        "type_counts": counts,
        "map_title": "Official Sofia PFRA map with historical-event symbols (2022–2027 cycle)",
        "map_description": "1:150,000 PFRA context map. Orange/red count symbols represent past flood locations; blue hatching and blue river corridors identify types/areas selected for hazard and risk analysis, not observed inundation extents. This earlier map does not depict all records in the newer register.",
        "map_source_url": MAP_URL,
        "map_file": "data/reference/historical_floods/" + MAP,
        "download_file": "data/reference/historical_floods/sofia_past_flood_records.csv",
        "map_url": "/api/history/map",
        "download_url": "/api/history/download",
        "events": [{
            "id": r["id"], "source_event_id": r["event_id"],
            "start_date": r["start_date"], "end_date": None, "type": r["type"],
            "affected_region": "Sofia municipality (SOF46)",
            "source_url": REGISTER_URL,
            "source_row": r["source_row"],
            "description": str(r["affected_territory_original"] or r["description_original"] or "Source record; no detailed location supplied."),
            "spatial_precision": r["spatial_precision"],
            "quality_notes": r["quality_notes"],
        } for r in records],
        "limitations": summary["cautions"] + [
            "The newer source is a draft register published in 2026; observation dates and publication/plan dates differ.",
            "Mixed river/rain and rain/infrastructure records are labelled explicitly; they are not pure pluvial calibration samples.",
            "The earlier official PDF mixes historical symbols with analysis zones. Blue areas must not be presented as observed flood extent.",
            "No street geometry was reconstructed from broad district or address descriptions; no historic flood raster has been fabricated.",
        ],
        "license": "Danube Basin Directorate public documents; an explicit open reuse licence was not stated on the retrieved page. HANZE supplemental data: CC BY 4.0.",
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": before,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "historical_floods_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == {name: sha(REF / name) for name in before}, "Original source changed"
    print(json.dumps({k: summary[k] for k in ["record_count", "unique_source_event_ids", "type_counts", "geometry_count"]}, ensure_ascii=True))
    print(json.dumps({"hanze_sofia_city_records": sum("BG411" in e["Regions affected (NUTS 3)"] for e in hanze), "hanze_sofia_region_records": len(hanze)}))


if __name__ == "__main__":
    main()
