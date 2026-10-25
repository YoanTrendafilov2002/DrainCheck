#!/usr/bin/env python3
"""Acquire missing authorized Earth Engine inputs; never embeds credentials."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/map_config.json').read_text())

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(path)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'stats', 'export-dem', 'export-points'])
    parser.add_argument('--project', default=CONFIG['project'])
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/incoming')
    parser.add_argument('--destination', choices=['drive','gcs'], default='drive')
    parser.add_argument('--bucket', help='Existing GCS bucket; this tool never creates a bucket.')
    parser.add_argument('--folder', default='SofiaCodex')
    parser.add_argument('--prefix', default='sofia_codex')
    parser.add_argument('--start', action='store_true', help='Actually submit the selected batch export.')
    parser.add_argument('--bounds', type=float, nargs=4, metavar=('WEST','SOUTH','EAST','NORTH'))
    args = parser.parse_args()
    if args.destination == 'gcs' and not args.bucket:
        parser.error('--bucket is required for GCS exports')
    if args.action.startswith('export-') and not args.start:
        print('Dry run: no export started. Add --start after checking destination storage and quota.')
        print(json.dumps({'action':args.action,'project':args.project,'destination':args.destination,
            'bucket':args.bucket,'folder':args.folder,'prefix':args.prefix},indent=2))
        return
    try:
        import ee
    except ImportError as error:
        raise SystemExit('Install earthengine-api, then authenticate with earthengine authenticate.') from error
    try:
        ee.Initialize(project=args.project)
    except Exception as error:
        raise SystemExit('Earth Engine initialization failed. Authenticate or configure authorized server credentials and asset permissions. No data were exported.') from error
    dem_id = CONFIG['elevation']['asset']
    point_id = CONFIG['infrastructure']['asset']
    area = ee.Geometry.Rectangle(CONFIG['study_area_wgs84'], None, False)
    dem = ee.Image(dem_id).select([0], ['elevation'])
    native = dem.updateMask(dem.neq(-9999)).toFloat().clip(area)
    points = ee.FeatureCollection(point_id)
    if args.action == 'inspect':
        save(args.output_dir / 'earth_engine_metadata.json',{
            'dem_asset':ee.data.getAsset(dem_id),
            'dem_projection':dem.projection().getInfo(),
            'points_asset':ee.data.getAsset(point_id),
            'points_count':points.size().getInfo(),
            'points_type_histogram':points.aggregate_histogram('type').getInfo()})
        return
    if args.action == 'stats':
        region = ee.Geometry.Rectangle(args.bounds,None,False) if args.bounds else area
        values = native.reduceRegion(
            reducer=ee.Reducer.percentile([i/2 for i in range(201)],['q'+str(i) for i in range(201)],65536,0.05,4096),
            geometry=region.intersection(area,30),scale=10 if args.bounds else 60,
            bestEffort=True,maxPixels=2000000,tileScale=4).getInfo()
        quantiles = [values.get('elevation_q'+str(i)) for i in range(201)]
        if any(v is None for v in quantiles):
            raise SystemExit('No valid elevation distribution was returned. No scale file written.')
        save(args.output_dir / 'elevation_quantiles.json',{'scope':'current-view' if args.bounds else 'whole-study-area',
            'bounds_wgs84':args.bounds or CONFIG['study_area_wgs84'],
            'percentiles':[i/2 for i in range(201)],'quantiles_m':quantiles,
            'statistics_scale_m':10 if args.bounds else 60,'best_effort':True,
            'source_asset':dem_id,'display_only':True})
        return
    common = {'description':args.prefix + '_' + args.action.replace('-','_'),
              'fileNamePrefix':args.prefix + ('_dtm_1m' if args.action=='export-dem' else '_infrastructure')}
    if args.action == 'export-dem':
        # Explicit NoData preserves valid heights, but filled empty areas can add storage.
        params = {**common,'image':native.unmask(value=-9999,sameFootprint=False),
            'region':area,'crs':CONFIG['elevation']['crs'],
            'crsTransform':CONFIG['elevation']['transform'],'maxPixels':5000000000,
            'fileDimensions':8192,'shardSize':256,'fileFormat':'GeoTIFF',
            'formatOptions':{'cloudOptimized':True,'noData':-9999}}
        factory = ee.batch.Export.image
    else:
        params = {**common,'collection':points,'fileFormat':'GeoJSON'}
        factory = ee.batch.Export.table
    task = factory.toCloudStorage(bucket=args.bucket,**params) if args.destination=='gcs' else factory.toDrive(folder=args.folder,**params)
    task.start()
    save(args.output_dir / (args.action + '_task.json'),{'task_id':task.id,
        'action':args.action,'destination':args.destination,'bucket':args.bucket,'folder':args.folder,
        'file_prefix':common['fileNamePrefix'],'status':task.status(),
        'note':'Task submission is not completion. Download the completed outputs and verify them before using the data.'})

if __name__ == '__main__':
    main()
