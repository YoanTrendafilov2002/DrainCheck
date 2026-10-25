"""Preserve and validate the published GATE-coauthored Lozenets roof subset.

This is NOT an importer for the current Sofia Digital Twin.  The separately
named products must not replace digital_twin_buildings.geojson.  Inputs are
the original, publicly linked author dataset (paper DOI10.3390/rs16081386).
Run with the preprocessing environment containing pyshp==3.1.6.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import shapefile
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
STEM = "Outlines_Roof_Planes_1800"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False,
                               indent=2) + "\n", encoding="utf-8")


def prepare(root=ROOT):
    root = Path(root)
    source = root / "data/reference/digital_twin_buildings"
    manifest = json.loads((source / "download_manifest.json").read_text(encoding="utf-8"))
    before = {}
    for entry in manifest["files"]:
        path = source / entry["file"]
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError(f"Original does not match acquisition receipt: {path.name}")
        before[path.name] = digest(path)
    crs = CRS.from_wkt((source / f"{STEM}.prj").read_text(encoding="utf-8"))
    if crs.to_epsg() != 7801:
        raise ValueError("Unexpected source CRS; do not guess projected coordinates")
    forward = Transformer.from_crs(crs, 4326, always_xy=True)
    inverse = Transformer.from_crs(4326, crs, always_xy=True)
    features, projected, geographical, roundtrip_errors = [], [], [], []
    source_types, properties_schema = set(), set()
    with shapefile.Reader(str(source / STEM)) as reader:
        if reader.shapeType != shapefile.POLYGON or len(reader) != 1800:
            raise ValueError("Expected the published 1,800 two-dimensional roof outlines")
        for index, record in enumerate(reader.iterShapeRecords()):
            original = shape(record.shape.__geo_interface__)
            props = record.record.as_dict()
            source_types.add(original.geom_type)
            properties_schema.update(props)
            if original.is_empty or not original.is_valid:
                raise ValueError(f"Source polygon {index} is not valid; no silent geometry repair")
            converted = shapely.transform(original, forward.transform, interleaved=False)
            restored = shapely.transform(converted, inverse.transform, interleaved=False)
            error = original.hausdorff_distance(restored)
            if not converted.is_valid or error > 0.001:
                raise ValueError(f"CRS roundtrip failed for source record {index}")
            source_id = f"gate-lozenets-research-roof-{index:04d}"
            props.update({"source_id": source_id, "source_record_index": index,
                          "source_dataset": STEM, "geometry_semantics": "2d_roof_outline",
                          "source_publication_doi": "10.3390/rs16081386"})
            features.append({"type": "Feature", "id": source_id,
                             "properties": props, "geometry": mapping(converted)})
            projected.append(original)
            geographical.append(converted)
            roundtrip_errors.append(error)
    if len(set(g.wkb for g in projected)) != len(projected):
        raise ValueError("Exact duplicate source outlines require source review")
    bounds = [min(g.bounds[0] for g in geographical), min(g.bounds[1] for g in geographical),
              max(g.bounds[2] for g in geographical), max(g.bounds[3] for g in geographical)]
    output = root / "data/derived/gate_lozenets_research_roof_outlines.geojson"
    collection = {"type": "FeatureCollection", "name": "GATE-coauthored Lozenets research roof outlines",
                  "bbox": bounds, "features": features}
    write_json(output, collection)
    output_hash = digest(output)
    revision = hashlib.sha256((output_hash + "research-roof-outlines-v1").encode()).hexdigest()[:16]
    meta = {
        "available": True, "revision": revision,
        "title": "Lozenets research roof outlines (1,800; 2D)",
        "source_label": "Campoverde et al. (2024), author-published GATE/RMSI research dataset",
        "source_url": "https://www.mdpi.com/2072-4292/16/8/1386",
        "download_url": "https://drive.google.com/drive/folders/1CMWM6KCaSC2fqyw7sDZ_ZFRZiqtD5MmN",
        "license": "No explicit dataset reuse licence found in downloaded files or linked author repository; paper licence is separate",
        "coverage_label": "Partial Lozenets research subset; not the requested current full-city Sofia Digital Twin",
        "coverage_bbox_wgs84": bounds, "feature_count": len(features),
        "source_date": None, "source_file_modified_at": "2023-04-26T13:17:04Z",
        "retrieved_at": manifest["retrieved_at"], "publication_date": "2024-04-14", "minzoom": 13,
        "height": {"available": False, "field": None, "semantics": "unavailable", "count": 0},
        "geometry_semantics": "2d_roof_outlines", "source_crs": "EPSG:7801", "output_crs": "EPSG:4326",
        "lod": "2D roof outlines; no CityGML LoD or above-ground height supplied",
        "requested_full_city_twin": False, "promoted_to_main_building_layer": False,
        "limitations": [
            "The source is a finite research subset and does not establish coverage or geometry of the current full-city twin.",
            "Roof outlines were manually adjusted in the published research; they are not guaranteed cadastral ground footprints.",
            "The only original attribute is Area. No building name, cadastral ID, Z coordinate, height or roof mesh is provided.",
            "Record-order IDs are stable for the preserved source hash; no original feature-ID field exists.",
            "The 2023 file modification time is not a verified survey date; source acquisition date is unknown.",
            "These display-only outlines do not change the DTM, water mask, drainage routing or flood scores."
        ],
        "source_files": manifest["files"], "geojson_sha256": output_hash,
        "preprocessing": {"method": "Exact polygon coordinates transformed from declared EPSG:7801 to WGS84; no buffer, simplification, repair, height inference or extrusion", "script": "scripts/prepare_gate_research_buildings.py"}
    }
    write_json(root / "data/cache/gate_lozenets_research_meta.json", meta)
    holes = sum(len(g.interiors) for g in projected)
    receipt = {"available": True, "revision": revision, "feature_count": len(features),
               "source_shape_type": "POLYGON (2D)", "source_epsg": crs.to_epsg(),
               "source_property_fields": sorted(properties_schema), "source_geometry_types": sorted(source_types),
               "valid_features": sum(g.is_valid for g in projected), "empty_features": 0,
               "exact_duplicate_features": 0, "source_holes": holes,
               "output_holes": sum(len(g.interiors) for g in geographical),
               "coverage_bbox_wgs84": bounds, "maximum_crs_roundtrip_error_m": max(roundtrip_errors),
               "source_polygon_area_percentiles_m2": np.percentile([g.area for g in projected], [0, 50, 95, 100]).tolist(),
               "original_sha256_before": before,
               "original_sha256_after": {name: digest(source / name) for name in before},
               "geojson_sha256": output_hash, "height_available": False,
               "promoted_to_requested_full_city_layer": False}
    if receipt["original_sha256_before"] != receipt["original_sha256_after"]:
        raise AssertionError("Source file was modified")
    write_json(root / "test-artifacts/gate_lozenets_research_validation.json", receipt)
    print(json.dumps({"revision": revision, "features": len(features), "output": str(output),
                      "promoted_to_main_layer": False, "height_available": False}))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=ROOT)
    prepare(parser.parse_args().app_root)
