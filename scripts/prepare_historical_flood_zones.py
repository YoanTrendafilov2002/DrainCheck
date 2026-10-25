"""Validate actual Sofiaplan 2021 flood polygons and make a display copy.

No geocoding, buffering, inference of flood depth or pluvial classification.
Requires shapely and pyproj. Raw source downloads are never modified.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.validation import explain_validity

APP = Path(__file__).resolve().parents[1]
REF = APP / "data/reference/historical_floods"
SOURCE = REF / "sofiaplan_dataset549_metadata.json"  # Original response is GeoJSON.
OUTPUT = REF / "sofiaplan_flood_zones_2021_display.geojson"
META = APP / "data/cache/historical_flood_zones_meta.json"
CATALOGUE = "https://urbandata.sofia.bg/dataset/flooded-areas-identified-by-drone-survey-february-2021"
SERVICE = "https://gis.sofiaplan.bg/server/rest/services/programa_za_sofia/programa_sofia_atlas_na_analizite/MapServer/310"


def polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for child in getattr(geometry, "geoms", []) for p in polygons(child)]


def main():
    raw = SOURCE.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    source = json.loads(raw)
    source_count = json.loads((REF / "sofiaplan_floods_2021_layer310_count.json").read_text())["count"]
    assert len(source["features"]) == source_count == 136
    projector = Transformer.from_crs(4326, 7801, always_xy=True).transform
    reverse = Transformer.from_crs(7801, 4326, always_xy=True).transform
    result, repairs = [], []
    for item in source["features"]:
        props = dict(item["properties"])
        geometry = shape(item["geometry"])
        repaired = not geometry.is_valid
        if repaired:
            original = geometry
            fixed = make_valid(geometry)
            parts = polygons(fixed)
            assert parts, f"No polygon remains for {props}"
            geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
            repairs.append({
                "object_id": props["object_id"],
                "source_validity": explain_validity(original),
                "operation": "GEOS make_valid; polygon parts retained; non-area remnants omitted from display copy only",
                "original_area_m2": transform(projector, original).area,
                "display_area_m2": transform(projector, geometry).area,
            })
        assert geometry.is_valid and not geometry.is_empty
        props.update({
            "source_id": str(props["object_id"]),
            "context_kind": "historical_flood_survey",
            "history_source": "Sofiaplan drone survey 2021, dataset549",
            "survey_year": 2021,
            "survey_date_label": "Catalogue: February 2021; exact observation date unresolved",
            "flood_type": "Not classified per polygon; river-associated event context in the 2021 study",
            "source_url": CATALOGUE,
            "geometry_repaired": repaired,
        })
        result.append({"type": "Feature", "id": int(props["object_id"]), "properties": props, "geometry": mapping(geometry)})
    document = {"type": "FeatureCollection", "features": result}
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    geometries = [shape(f["geometry"]) for f in result]
    projected = [transform(projector, g) for g in geometries]
    merged = unary_union(projected)
    point = transform(reverse, merged.representative_point())
    display_sha = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    revision = hashlib.sha256((raw_sha + display_sha + "historical-source-v1").encode()).hexdigest()[:16]
    metadata = {
        "available": True,
        "title": "Mapped 2021 flood zones — Sofiaplan drone survey",
        "source_title": "Зони с наводнения от облитането с дрон през февруари 2021 г.",
        "source_url": CATALOGUE,
        "source_api_url": "https://api.sofiaplan.bg/datasets/549",
        "service_url": SERVICE,
        "provider": "Sofiaplan / Sofia Municipality",
        "description": "Actual mapped flood-zone polygons from a municipal drone survey; northern Sofia municipality. Historical observation context, not modelled future hazard or a citywide pluvial validation set.",
        "coverage_label": "Northern municipality near Novi Iskar, Trebich, Mirovyane and Zhiten; survey footprints are incomplete citywide coverage.",
        "geometry_type": "Polygon/MultiPolygon",
        "feature_count": len(result),
        "count": len(result),
        "bbox": list(unary_union(geometries).bounds),
        "coverage_bbox_wgs84": list(unary_union(geometries).bounds),
        "crs": "EPSG:4326",
        "native_service_crs": "EPSG:7801",
        "data_file": "data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson",
        "geojson_file": "data/reference/historical_floods/sofiaplan_flood_zones_2021_display.geojson",
        "source_file": "data/reference/historical_floods/sofiaplan_dataset549_metadata.json",
        "original_geojson_file": "data/reference/historical_floods/sofiaplan_dataset549_original.geojson",
        "source_fields": sorted(source["features"][0]["properties"]),
        "source_area_field": "area_kv_m",
        "sum_feature_area_m2": sum(g.area for g in projected),
        "union_area_m2": merged.area,
        "area_note": "Computed from actual validated geometry inEPSG7801; feature-sum overlaps are not counted twice in the union area. The study's printed19,150ha total conflicts with these geometries and its own land-use totals, so that number is not used.",
        "year": 2021,
        "survey_date_label": "2021; catalogue says February, associated study describes January",
        "catalogue_current_as_of": "2021-02-01",
        "date_precision": "Year; catalogue says February 2021, while associated study describes January 2021 and captions 18 Jan 2021 imagery. No per-feature observation timestamps.",
        "flood_type": "Unclassified per polygon; river-associated rainfall flooding in the associated study, not confirmed pure pluvial",
        "license": "Not specified in municipal CKAN catalogue; source attribution retained. No CC/open licence has been invented.",
        "attribution": "Sofiaplan / Sofia Municipality, dataset549 and Atlas of Analyses layer310",
        "revision": revision,
        "sha256": display_sha,
        "source_sha256": raw_sha,
        "geometry_repairs": repairs,
        "known_example": {"longitude": point.x, "latitude": point.y, "meaning": "Interior of a real mapped polygon; not an observed flood gauge or exact event location."},
        "limitations": [
            "Surveyed footprints do not provide citywide survey coverage; no polygon does not mean no flooding.",
            "The source does not separate pluvial from fluvial flooding per polygon, and no precise event date, depth, return period or rainfall hyetograph is attached.",
            "The associated 2021 study describes rainfall-related flooding along the Iskar, Blato and Kriva rivers; do not call the polygons pure pluvial.",
            "No terrain scores, open-water exclusions or asset-exposure calculations are changed by this context layer.",
            "Two invalid source geometries were repaired only in the derived display copy; all originals and source properties remain preserved.",
            "No reported non-flooded control coverage or observation-error assessment is available; no model calibration has been performed.",
        ],
        "retrieved_utc": "2026-10-25T07:56:16Z",
        "processed_utc": datetime.now(timezone.utc).isoformat(),
    }
    # A correctly named, byte-identical copy clarifies the endpoint's real type.
    original_copy = REF / "sofiaplan_dataset549_original.geojson"
    if not original_copy.exists():
        original_copy.write_bytes(raw)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == raw_sha
    assert hashlib.sha256(original_copy.read_bytes()).hexdigest() == raw_sha
    META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (REF / "historical_flood_zones_validation.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: metadata[k] for k in ["feature_count", "bbox", "revision", "sum_feature_area_m2", "union_area_m2", "geometry_repairs", "known_example"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
