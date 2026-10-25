"""Acquire and prepare the separately labelled municipal ARCHIVAL building set.

The original ZIP is retained unchanged. This script never writes the main
cadastral_buildings products, which are reserved for the AGKK national source.
Only use --index when an independent archival display index is wanted.
"""
import argparse
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

import shapely
from shapely.geometry import shape, mapping, MultiPolygon

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = 'https://urbandata.sofia.bg/en/dataset/cad_plan_sgr-zip'
PACKAGE = '24283798-c042-44de-9bd0-8cec77f2200b'
RESOURCE = '5e7418f8-4a75-4b75-b247-e8d0d74354de'
METADATA = 'https://urbandata.sofia.bg/api/3/action/package_show?id=' + PACKAGE


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def acquire(root=ROOT):
    source = Path(root) / 'data/reference/cadastral_buildings'
    source.mkdir(parents=True, exist_ok=True)
    catalogue = source / 'catalogue_metadata.json'
    if not catalogue.exists():
        with urllib.request.urlopen(METADATA, timeout=30) as response:
            raw = response.read()
        with catalogue.open('xb') as stream:
            stream.write(raw)
    catalog = json.loads(catalogue.read_text(encoding='utf-8'))
    if not catalog.get('success') or catalog['result']['id'] != PACKAGE:
        raise ValueError('Unexpected official catalogue response')
    resource = next(r for r in catalog['result']['resources'] if r['id'] == RESOURCE)
    url = resource['url']
    if not url.startswith('https://urbandata.sofia.bg/'):
        raise ValueError('Official resource no longer points to the inspected municipal host')
    archive = source / 'cad_plan_sgr.zip'
    receipt = source / 'download_manifest.json'
    if archive.exists():
        if not receipt.exists():
            raise ValueError('Existing original ZIP has no receipt; inspect it without overwriting')
        recorded = json.loads(receipt.read_text(encoding='utf-8'))
        if recorded['sha256'] != digest(archive):
            raise ValueError('Existing original ZIP does not match its acquisition hash')
    else:
        start = time.monotonic()
        pending = source / 'cad_plan_sgr.zip.part'
        with urllib.request.urlopen(url, timeout=30) as response, pending.open('xb') as out:
            count = 0
            for block in iter(lambda: response.read(1024 * 1024), b''):
                out.write(block)
                count += len(block)
                if count % (8 * 1024 * 1024) == 0:
                    print(json.dumps({'stage': 'download', 'mib': count / 1024**2,
                                      'elapsed_seconds': round(time.monotonic() - start, 1)}), flush=True)
        if count != int(resource['size']):
            raise ValueError('Download size differs from the official resource size; original not installed')
        pending.replace(archive)
        recorded = {'source_url': url, 'catalogue_url': CATALOGUE, 'resource_id': RESOURCE,
                    'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'filename': archive.name, 'bytes': archive.stat().st_size, 'sha256': digest(archive)}
        write_json(receipt, recorded)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('Original ZIP failed its internal CRC checks')
        names = [item.filename for item in z.infolist() if not item.is_dir()]
        if names != ['cad_plan_sgr.geojson']:
            raise ValueError('Unexpected source archive contents; inspect before extracting')
    return archive, catalog['result'], json.loads(receipt.read_text(encoding='utf-8'))


def polygonal_parts(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry] if not geometry.is_empty and geometry.area > 0 else []
    if geometry.geom_type in ['MultiPolygon', 'GeometryCollection']:
        return [p for child in geometry.geoms for p in polygonal_parts(child)]
    return []


def prepare(root=ROOT, make_index=False):
    root = Path(root)
    archive, catalogue, acquisition = acquire(root)
    original_hash = digest(archive)
    with zipfile.ZipFile(archive) as z, z.open('cad_plan_sgr.geojson') as stream:
        document = json.load(stream)
    if document.get('type') != 'FeatureCollection' or document.get('crs') is not None:
        raise ValueError('Expected the inspected geographic GeoJSON with no alternative declared CRS')
    features = document['features']
    if document.get('numberMatched') != len(features):
        raise ValueError('The downloaded feature count differs from its numberMatched declaration')
    output = root / 'data/derived/cadastral_archive_buildings.geojson'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.pending.geojson')
    seen_ids, geometry_hashes = set(), set()
    repairs, skipped, duplicates = [], [], 0
    regions, floors, functions, fields = Counter(), Counter(), Counter(), Counter()
    bounds = [float('inf'), float('inf'), -float('inf'), -float('inf')]
    valid_original = 0
    count = 0
    source_holes = output_holes = 0
    first = True
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write('{"type":"FeatureCollection","name":"Sofia archival cadastral building outlines","features":[\n')
        for index, feature in enumerate(features):
            properties = dict(feature.get('properties') or {})
            rn = str(properties.get('rn', ''))
            if not rn or rn in seen_ids:
                raise ValueError('Source rn identifiers are absent or duplicated; do not invent silently merged IDs')
            seen_ids.add(rn)
            fields.update(properties.keys())
            regions[str(properties.get('region'))] += 1
            floors[str(properties.get('numer_of_floors'))] += 1
            functions[str(properties.get('functional_type'))] += 1
            source_id = 'sofia-archival-building-' + rn
            if not feature.get('geometry'):
                skipped.append({'source_id': source_id, 'reason': 'No source geometry'})
                continue
            geometry = shape(feature['geometry'])
            if geometry.has_z:
                raise ValueError('Unexpected source Z coordinates require separate height-semantics inspection')
            if geometry.geom_type not in ['Polygon', 'MultiPolygon']:
                raise ValueError('Unexpected non-polygon source feature')
            source_holes += sum(len(p.interiors) for p in polygonal_parts(geometry))
            if geometry.is_valid and not geometry.is_empty:
                valid_original += 1
            else:
                reason = shapely.is_valid_reason(geometry)
                fixed = shapely.make_valid(geometry)
                pieces = polygonal_parts(fixed)
                if not pieces:
                    skipped.append({'source_id': source_id, 'reason': str(reason),
                                    'source_geometry_sha256': hashlib.sha256(geometry.wkb).hexdigest()})
                    continue
                geometry = pieces[0] if len(pieces) == 1 else MultiPolygon(pieces)
                repairs.append({'source_id': source_id, 'source_invalid_reason': str(reason),
                                'derived_geometry_type': geometry.geom_type,
                                'repair': 'GEOS make_valid; polygonal components only; source retained in original ZIP'})
                # Preserve a clear per-feature disclosure for inspection/export.
                properties['derived_geometry_repair'] = 'make_valid_polygonal_components'
            if geometry.is_empty or not geometry.is_valid or geometry.area <= 0:
                raise ValueError('Derived footprint remains invalid after documented repair: ' + source_id)
            west, south, east, north = geometry.bounds
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError('Coordinates are inconsistent with geographic GeoJSON')
            bounds = [min(bounds[0], west), min(bounds[1], south), max(bounds[2], east), max(bounds[3], north)]
            geometry_hash = hashlib.sha256(shapely.normalize(geometry).wkb).digest()
            if geometry_hash in geometry_hashes:
                duplicates += 1
            geometry_hashes.add(geometry_hash)
            output_holes += sum(len(p.interiors) for p in polygonal_parts(geometry))
            properties['source_id'] = source_id
            converted = {'type': 'Feature', 'id': source_id, 'properties': properties,
                         'geometry': feature['geometry'] if geometry.is_valid and not properties.get('derived_geometry_repair') else mapping(geometry)}
            if not first:
                stream.write(',\n')
            stream.write(json.dumps(converted, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
            first = False
            count += 1
            if (index + 1) % 50000 == 0:
                print(json.dumps({'stage': 'validate_archive', 'source_records': index + 1,
                                  'written': count, 'repairs': len(repairs), 'skipped': len(skipped)}), flush=True)
        stream.write('\n]}\n')
    temporary.replace(output)
    output_hash = digest(output)
    revision = hashlib.sha256((original_hash + output_hash + 'archival-footprints-v1').encode()).hexdigest()[:16]
    meta = {
        'available': True, 'revision': revision, 'title': 'Archival cadastral building outlines',
        'source_label': 'GIS Sofia / Sofia Municipality — archival cadastral plan buildings',
        'source_url': CATALOGUE, 'download_url': acquisition['source_url'],
        'license': 'Creative Commons Attribution (cc-by), as listed by the municipal catalogue; version not specified there',
        'license_url': catalogue.get('license_url'),
        'coverage_label': 'Actual extent of the municipal archival cadastral plan snapshot; not a guarantee of current cadastral completeness',
        'coverage_bbox_wgs84': bounds, 'feature_count': count, 'original_feature_count': len(features),
        'source_date': None, 'catalogue_valid_at': '2026-09-08',
        'catalogue_created_at': catalogue.get('metadata_created'),
        'catalogue_modified_at': catalogue.get('metadata_modified'), 'retrieved_at': acquisition['retrieved_at'],
        'minzoom': 13, 'height': {'available': False, 'field': None, 'semantics': 'unavailable', 'count': 0},
        'source_crs': 'Geographic GeoJSON without crs member; interpreted as WGS84 longitude/latitude',
        'output_crs': 'EPSG:4326', 'original_archive_sha256': original_hash, 'geojson_sha256': output_hash,
        'geometry_repair_count': len(repairs), 'nonpolygon_or_empty_omitted_count': len(skipped),
        'exact_normalized_duplicate_geometry_count': duplicates,
        'promoted_to_main_cadastre': False,
        'limitations': [
            'The provider explicitly calls these archival building boundaries from before the current cadastral map and registers took effect.',
            'The catalogue valid-at label 8 September 2026 is not a verified survey or construction date for individual archived buildings.',
            'The original rn field is a snapshot row identifier; it is not a verified national cadastral building identifier.',
            'numer_of_floors is preserved verbatim. Floor counts are not converted to heights and no extrusions are inferred.',
            'Unknown functional_type and ownership strings remain as supplied; archived outlines do not prove current ownership or legal boundaries.',
            'Geometry repairs, if any, are limited to documented validity repair in the display derivative. The downloaded ZIP remains unchanged.',
            'This separate archival reference does not replace AGKK national building data or the unavailable Digital Twin model, and does not alter terrain, drainage routing, water masks or pluvial scores.'
        ]}
    write_json(root / 'data/cache/cadastral_archive_buildings_meta.json', meta)
    receipt = {
        'available': True, 'revision': revision, 'source_archive_sha256_before': original_hash,
        'source_archive_sha256_after': digest(archive), 'source_archive_bytes': archive.stat().st_size,
        'original_feature_count': len(features), 'source_number_matched': document.get('numberMatched'),
        'derived_feature_count': count, 'valid_original_features': valid_original, 'unique_source_rn': len(seen_ids),
        'source_fields': dict(fields), 'source_geometry': '2D polygons in geographic GeoJSON',
        'region_counts': dict(regions), 'source_floor_value_counts': dict(floors),
        'source_function_value_counts': dict(functions), 'coverage_bbox_wgs84': bounds,
        'source_holes': source_holes, 'derived_holes': output_holes,
        'documented_repairs': repairs, 'omitted_source_records': skipped,
        'normalized_duplicate_geometries': duplicates, 'derived_geojson_sha256': output_hash,
        'height_inferred': False, 'promoted_to_main_cadastre': False,
        'original_source_description': catalogue['notes'], 'catalogue_metadata_url': METADATA,
        'archive_integrity': 'Full ZIP member CRC test passed',
    }
    if receipt['source_archive_sha256_after'] != original_hash:
        raise AssertionError('Original archive changed during preparation')
    write_json(root / 'test-artifacts/cadastral_archive_validation.json', receipt)
    if make_index:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from prepare_buildings_index import prepare as index_buildings
        index_buildings(output, root / 'data/cache/cadastral_archive_buildings_meta.json',
                        root / 'data/cache/cadastral_archive_buildings.sqlite')
    print(json.dumps({'stage': 'complete', 'revision': revision, 'features': count,
                      'original_features': len(features), 'bbox': bounds, 'repairs': len(repairs),
                      'omitted': len(skipped), 'index_built': make_index, 'promoted_to_main_cadastre': False}), flush=True)
    return receipt


def verify(root=ROOT):
    """Independent source-to-derivative comparison of every original record."""
    root = Path(root)
    source = root / 'data/reference/cadastral_buildings'
    archive = source / 'cad_plan_sgr.zip'
    output = root / 'data/derived/cadastral_archive_buildings.geojson'
    receipt_path = root / 'test-artifacts/cadastral_archive_validation.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    meta = json.loads((root / 'data/cache/cadastral_archive_buildings_meta.json').read_text(encoding='utf-8'))
    assert digest(archive) == receipt['source_archive_sha256_before'] == meta['original_archive_sha256']
    assert digest(output) == receipt['derived_geojson_sha256'] == meta['geojson_sha256']
    with zipfile.ZipFile(archive) as z, z.open('cad_plan_sgr.geojson') as stream:
        original = json.load(stream)
    omitted = {item['source_id'] for item in receipt['omitted_source_records']}
    repaired = {item['source_id'] for item in receipt['documented_repairs']}
    compared = unchanged_geometries = 0
    with output.open(encoding='utf-8') as stream:
        def records():
            for line in stream:
                if line.startswith('{"type":"Feature",'):
                    yield json.loads(line.rstrip().removesuffix(','))
        derived = iter(records())
        for feature in original['features']:
            source_id = 'sofia-archival-building-' + str(feature['properties']['rn'])
            if source_id in omitted:
                continue
            check = next(derived)
            assert check['id'] == check['properties']['source_id'] == source_id
            for key, value in feature['properties'].items():
                assert check['properties'][key] == value
            assert 'height_m' not in check['properties']
            if source_id not in repaired:
                assert check['geometry'] == feature['geometry']
                unchanged_geometries += 1
            compared += 1
        assert next(derived, None) is None
    assert compared == meta['feature_count'] == receipt['derived_feature_count']
    assert not meta['height']['available'] and not meta['promoted_to_main_cadastre']
    assert digest(archive) == receipt['source_archive_sha256_after']
    receipt['independent_source_to_derivative_verification'] = {
        'all_original_properties_compared': compared,
        'unchanged_original_geometry_coordinates_compared': unchanged_geometries,
        'no_height_inference': True, 'original_zip_unchanged': True,
        'main_cadastre_not_replaced': True,
        'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write_json(receipt_path, receipt)
    print(json.dumps({'stage': 'verify_complete', 'compared_records': compared,
                      'unchanged_geometry_records': unchanged_geometries,
                      'original_zip_unchanged': True, 'main_cadastre_not_replaced': True}), flush=True)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, default=ROOT)
    parser.add_argument('--index', action='store_true', help='Build a separate archival index; never the main AGKK index')
    parser.add_argument('--verify', action='store_true', help='Verify every prepared record against the original ZIP without rebuilding')
    args = parser.parse_args()
    if args.verify:
        verify(args.app_root)
    else:
        prepare(args.app_root, args.index)
