"""Acquire a bounded public AGKK cadastral-building snapshot, preserving originals.

Reads official public ArcGIS query services only. No account, fee, publication,
permission change, height inference, geometry simplification or hydrology edit.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
REF = APP / "data/reference/agkk_buildings"
SERVICE = "https://inspire.cadastre.bg/arcgis/rest/services/Building/MapServer/0"
BBOX = [23, 42.4, 23.7, 42.95]
HEADERS = {"User-Agent": "SofiaTerrainExplorer local cadastral context acquisition", "Accept-Encoding": "gzip"}
SELECT = ["objectid", "id_localid", "id_namespace", "id_versionid", "beginlifespanversion", "endlifespanversion", "numberoffloorsaboveground", "numberoffloorsaboveground_void", "numberofdwellings", "numberofdwellings_void", "conditionofconstr", "conditionofconstr_void", "currentuse_code1", "currentuse_label1", "currentuse_void", "hgeomref", "hgeomestimatedaccuracy_value", "hgeomestimatedaccuracy_void", "referencegeometry"]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def request(form, timeout=60):
    raw_form = urllib.parse.urlencode(form).encode("ascii")
    req = urllib.request.Request(SERVICE + "/query", data=raw_form, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        encoded = response.headers.get("Content-Encoding", "").lower()
    body = gzip.decompress(raw) if encoded == "gzip" else raw
    doc = json.loads(body)
    if doc.get("error"):
        raise ValueError(f"AGKK response error: {doc['error']}")
    return body, doc


def query_ids():
    # Reuse the already preserved initial count/ID snapshot without extra calls.
    names = ["count_study_bbox_original.json", "ids_study_bbox_original.json"]
    form = {"where": "1=1", "geometry": ",".join(map(str, BBOX)), "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "f": "json"}
    for name, flag in zip(names, ["returnCountOnly", "returnIdsOnly"]):
        path = REF / name
        if not path.exists():
            body, _ = request({**form, flag: "true"})
            path.write_bytes(body)
    count = json.loads((REF / names[0]).read_text())["count"]
    data = json.loads((REF / names[1]).read_text())
    ids = sorted(data["objectIds"])
    assert count == len(ids) == len(set(ids)) and data["objectIdFieldName"] == "objectid"
    return ids


def acquire_batch(job):
    index, ids = job
    name = f"batch_{index:05d}.geojson.gz"
    path = REF / "batches" / name
    receipt = path.with_suffix(path.suffix + ".receipt.json")
    if path.exists() and receipt.exists():
        entry = json.loads(receipt.read_text())
        packed = path.read_bytes()
        body = gzip.decompress(packed)
        if digest(packed) != entry["sha256"] or digest(body) != entry["content_sha256"]:
            raise ValueError(f"Preserved batch failed checksum: {name}")
        doc = json.loads(body)
    else:
        started = time.perf_counter()
        form = {"objectIds": ",".join(map(str, ids)), "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson"}
        for attempt in range(3):
            try:
                body, doc = request(form)
                break
            except urllib.error.HTTPError as error:
                if error.code in [401, 403, 429]:
                    raise  # Do not bypass access restrictions or rate limits.
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        assert doc.get("type") == "FeatureCollection"
        packed = gzip.compress(body, mtime=0)
        entry = {"file": "batches/" + name, "sha256": digest(packed), "content_sha256": digest(body), "bytes": len(packed), "content_bytes": len(body), "feature_count": len(doc.get("features", [])), "first_objectid": ids[0], "last_objectid": ids[-1], "request_method": "POST", "request_url": SERVICE + "/query", "request_form": form, "retrieved_utc": now(), "elapsed_seconds": time.perf_counter() - started, "encoding": "gzip lossless storage of the exact original response content"}
        path.write_bytes(packed)
        receipt.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    returned = [int(f["properties"]["objectid"]) for f in doc["features"]]
    if len(returned) != len(set(returned)) or set(returned) != set(ids):
        raise ValueError(f"Batch missing/duplicate/extra IDs: {name}; requested {len(ids)}, returned {len(returned)}")
    if doc.get("exceededTransferLimit"):
        raise ValueError(f"Unexpected transfer limit in {name}; preserve response and use smaller explicit batches")
    return index, entry


def prepare(manifest, do_index=True):
    import shapely
    from shapely.geometry import MultiPolygon, mapping, shape
    from shapely.validation import explain_validity

    def polygon_parts(g):
        if g.geom_type == "Polygon":
            return [g]
        return [p for part in getattr(g, "geoms", []) for p in polygon_parts(part)]

    ids = query_ids()
    seen = set()
    source_identifiers = set()
    invalid = []
    counts = Counter()
    extent = [math.inf, math.inf, -math.inf, -math.inf]
    feature_count = 0
    known_example = None
    target = APP / "data/derived/cadastral_buildings.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix(".pending.geojson")
    index_lines = APP.parents[1] / "work/agkk_index_features.jsonl"
    index_lines.parent.mkdir(parents=True, exist_ok=True)
    with pending.open("w", encoding="utf-8") as out, index_lines.open("w", encoding="utf-8") as lines:
        out.write('{"type":"FeatureCollection","features":[')
        for batch in manifest["batches"]:
            path = REF / batch["file"]
            raw = path.read_bytes()
            if digest(raw) != batch["sha256"]:
                raise ValueError("Batch changed since acquisition")
            doc = json.loads(gzip.decompress(raw))
            for f in doc["features"]:
                props = f["properties"]
                oid = int(props["objectid"])
                if oid in seen:
                    raise ValueError("Duplicate source objectid")
                seen.add(oid)
                if props.get("id_localid"):
                    source_identifiers.add(props["id_localid"])
                geometry = shapely.force_2d(shape(f["geometry"]))
                if not geometry.is_valid:
                    reason = explain_validity(geometry)
                    fixed = shapely.make_valid(geometry)
                    parts = polygon_parts(fixed)
                    if not parts:
                        raise ValueError(f"No real polygon area after repair: {oid}")
                    geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
                    invalid.append({"objectid": oid, "reason": reason, "operation": "make_valid in derived display copy only; retain polygon parts, omit non-area remnants"})
                if geometry.geom_type not in ["Polygon", "MultiPolygon"] or not geometry.is_valid or geometry.is_empty:
                    raise ValueError(f"Invalid/nonpolygon source building: {oid}")
                w, s, e, n = geometry.bounds
                if not (-180 <= w <= e <= 180 and -90 <= s <= n <= 90):
                    raise ValueError("Geometry is not longitude/latitude")
                extent = [min(extent[0], w), min(extent[1], s), max(extent[2], e), max(extent[3], n)]
                keep = {key: props.get(key) for key in SELECT}
                keep.update({"source_id": str(oid), "source_oid": oid, "cadastral_id": props.get("id_localid"), "source_batch_file": "data/reference/agkk_buildings/" + batch["file"], "source_batch_sha256": batch["sha256"], "context_kind": "cadastral_buildings"})
                floors = props.get("numberoffloorsaboveground")
                counts["floor_count_nonnull"] += floors is not None
                counts["floor_count_null"] += floors is None
                if feature_count:
                    out.write(",")
                encoded = json.dumps({"type": "Feature", "id": oid, "properties": keep, "geometry": mapping(geometry)}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                out.write(encoded)
                lines.write(encoded + "\n")
                if known_example is None or oid == 2716694:
                    point = geometry.representative_point()
                    known_example = {"source_id": str(oid), "source_oid": oid, "cadastral_id": props.get("id_localid"), "longitude": point.x, "latitude": point.y, "source_batch_file": keep["source_batch_file"], "source_batch_sha256": batch["sha256"]}
                feature_count += 1
        out.write("]}")
    if seen != set(ids) or feature_count != manifest["expected_feature_count"]:
        raise ValueError("Whole acquired source-ID coverage does not match the initial query")
    pending.replace(target)
    geo_hash = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
    manifest_hash = digest((REF / "manifest.json").read_bytes())
    revision = digest((geo_hash + manifest_hash + "agkk-building-context-v1").encode())[:16]
    meta = {
        "available": True, "title": "AGKK INSPIRE cadastral buildings", "provider": "Geodesy, Cartography and Cadastre Agency, Bulgaria (AGKK/GCCA)",
        "source_label": "AGKK/GCCA — INSPIRE cadastral building service",
        "source_url": SERVICE, "source_name": "BU.Building — Buildings from Cadastral map of Bulgaria", "source_kind": "AGKK INSPIRE cadastral building polygons",
        "description": "Official national cadastral-building snapshot intersecting the app study rectangle, with actual source geometry and identifiers. Survey date and synchronization with the operational KAIS register are not established.",
        "feature_count": feature_count, "count": feature_count,
        "coverage_bbox_wgs84": extent, "bbox": extent, "query_bbox_wgs84": BBOX,
        "coverage_label": "Buildings intersecting study rectangle [23,42.4,23.7,42.95]; this rectangle is not Sofia's administrative boundary. Full source polygons are retained at its edge.",
        "coverage_note": "Complete for the initial service object-ID list in the query rectangle; not an independently verified complete inventory of all existing buildings.",
        "crs": "EPSG:4326", "source_crs": "EPSG:4258", "geometry_type": "Polygon/MultiPolygon", "min_zoom": 13,
        "height": {"available": False, "semantics": None, "reason": "Source floor counts are not measured height in metres; no 3D height is inferred."},
        "source_fields": SELECT, "source_attributes": "Full original INSPIRE attributes retained in gzip batch responses and available for source feature inspection.",
        "raw_manifest_file": "data/reference/agkk_buildings/manifest.json", "raw_manifest_sha256": manifest_hash,
        "raw_batch_format": "GeoJSON FeatureCollection gzip; features/properties/objectid",
        "data_file": "data/derived/cadastral_buildings.geojson", "geojson_file": "data/derived/cadastral_buildings.geojson", "index_file": "data/cache/cadastral_buildings.sqlite",
        "sha256": geo_hash, "revision": revision, "retrieved_utc": manifest["started_utc"], "acquisition_completed_utc": manifest["completed_utc"],
        "retrieved_at": manifest["started_utc"],
        "feature_lines_sha256": hashlib.file_digest(index_lines.open("rb"), "sha256").hexdigest(),
        "source_date": None,
        "catalogue_date_note": "INSPIRE catalogue publication: 2021-11-03; metadata revision: 2024-04-29. Feature lifecycle dates vary; survey date is unknown.",
        "source_publication_date": "2021-11-03", "metadata_revision_date": "2024-04-29",
        "license": "Official INSPIRE metadata: no limitations to public access; use constraints reference Tariff14. No CC licence or unrestricted redistribution right has been inferred.",
        "attribution": "Geodesy, Cartography and Cadastre Agency, Bulgaria (AGKK/GCCA)",
        "known_example": known_example,
        "limitations": ["Acquired from a public INSPIRE service; currency relative to the operational KAIS register is not guaranteed.", "Study-bbox coverage is not an administrative-municipality selection, and source cadastral records do not prove complete current physical-building coverage.", "Floors and INSPIRE void codes are retained; floor counts are not converted into metres.", "Buildings are separate visual context and do not alter native terrain, rainfall, pluvial scores, water exclusions or exposure calculations.", "Some source fields may be absent/void. No owner information or proprietary account was requested."],
        "validation": {"source_ids_expected": len(ids), "source_ids_received_unique": len(seen), "cadastral_identifiers_distinct_nonnull": len(source_identifiers), "transfer_limited_batches": 0, "original_batch_count": len(manifest["batches"]), "geometry_simplification": False, "geometry_repairs": invalid, "floor_counts": dict(counts)},
    }
    meta_path = APP / "data/cache/cadastral_buildings_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if do_index:
        subprocess.run([sys.executable, str(APP / "scripts/prepare_buildings_index.py"), "--geojson", str(target), "--metadata", str(meta_path), "--output", str(APP / "data/cache/cadastral_buildings.sqlite"), "--feature-lines", str(index_lines)], check=True)
    (APP / "test-artifacts/agkk_buildings_validation.json").write_text(json.dumps({"verified_at": now(), "source_service": SERVICE, "source_ids_exact": True, "all_original_response_checksums_verified": True, "all_display_geometry_valid": True, "no_geometry_simplification": True, "no_height_inference": True, "metadata": meta}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"prepared": True, "feature_count": feature_count, "bbox": extent, "revision": revision, "repairs": len(invalid), "geojson_bytes": target.stat().st_size}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Use already preserved complete batches, with no network requests")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or not 1 <= args.workers <= 2:
        raise ValueError("Bounded batches1–1000 and workers1–2 are required")
    (REF / "batches").mkdir(parents=True, exist_ok=True)
    if args.prepare_only:
        manifest = json.loads((REF / "manifest.json").read_text(encoding="utf-8"))
        prepare(manifest, do_index=not args.skip_index)
        return
    ids = query_ids()
    started = now()
    entries = []
    jobs = [(i // args.batch_size + 1, ids[i:i + args.batch_size]) for i in range(0, len(ids), args.batch_size)]
    print(json.dumps({"expected_feature_count": len(ids), "batches": len(jobs), "workers": args.workers}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, entry in pool.map(acquire_batch, jobs):
            entries.append(entry)
            if index == 1 or index % 10 == 0 or index == len(jobs):
                print(json.dumps({"completed_batches": index, "total_batches": len(jobs), "feature_count": sum(e["feature_count"] for e in entries), "last_elapsed_seconds": entry.get("elapsed_seconds"), "compressed_bytes": sum(e["bytes"] for e in entries)}), flush=True)
    manifest = {"schema_version": 1, "source_url": SERVICE, "scope_bbox_wgs84": BBOX, "spatial_relation": "intersects", "expected_feature_count": len(ids), "objectid_field": "objectid", "started_utc": started, "completed_utc": now(), "batch_size": args.batch_size, "workers": args.workers, "batches": entries}
    manifest_path = REF / "manifest.json"
    if manifest_path.exists():
        previous_bytes = manifest_path.read_bytes()
        previous = json.loads(previous_bytes)
        identity = lambda m: [(b["file"], b["sha256"]) for b in m["batches"]]
        if previous.get("scope_bbox_wgs84") == BBOX and identity(previous) == identity(manifest):
            manifest = previous  # Reusing old responses is not a fresh observation.
        else:
            archive = REF / "manifest_snapshots" / (digest(previous_bytes) + ".json")
            archive.parent.mkdir(exist_ok=True)
            if not archive.exists():
                archive.write_bytes(previous_bytes)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    prepare(manifest, do_index=not args.skip_index)


if __name__ == "__main__":
    main()
