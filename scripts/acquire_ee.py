"""Optional user-run Earth Engine acquisition. Never executed automatically.

The installed local app already has real native data. This utility is for a
future machine that needs authorized exports; no credentials enter the client.
"""
import argparse,json
from pathlib import Path

DTM='projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee'
POINTS='projects/rivertracker-512606/assets/sofia_infrastructure_pps'
GRID=[1,0,299392,0,-1,4753611]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['inspect','export-dem','export-points','export-statistics'])
    parser.add_argument('--project',default='rivertracker-512606')
    parser.add_argument('--bucket',help='Existing user-controlled Cloud Storage bucket; no bucket is created')
    parser.add_argument('--prefix',default='sofia-explorer')
    parser.add_argument('--out',type=Path,default=Path('data/reference/ee_whole_area_quantiles.json'))
    args=parser.parse_args()
    try:import ee
    except ImportError:raise SystemExit('Install the optional SDK: python -m pip install earthengine-api')
    ee.Initialize(project=args.project)
    image=ee.Image(DTM).select([0],['elevation'])
    points=ee.FeatureCollection(POINTS)
    projection=image.projection().getInfo()
    if projection.get('crs')!='EPSG:7801' or projection.get('transform')!=GRID:
        raise SystemExit('Unexpected asset grid; export stopped: '+json.dumps(projection))
    if args.action=='inspect':
        print(json.dumps({'dtm_asset':DTM,'bands':ee.Image(DTM).bandNames().getInfo(),
          'projection':projection,'point_count':points.size().getInfo()},indent=2));return
    if args.action=='export-statistics':
        reducer=ee.Reducer.percentile(percentiles=[i*.5 for i in range(201)],
          outputNames=['q%03d'%i for i in range(201)],maxBuckets=65536,minBucketWidth=.05,maxRaw=4096)
        values=image.reduceRegion(reducer=reducer,geometry=ee.Geometry.Rectangle([23,42.4,23.7,42.95]),
          scale=60,bestEffort=True,maxPixels=2000000,tileScale=4).getInfo()
        q=[values['elevation_q%03d'%i] for i in range(201)]
        if len(q)!=201 or any(value is None for value in q):raise SystemExit('Incomplete quantile response; nothing written')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        if args.out.exists():raise SystemExit('Output exists; choose another --out to preserve the original')
        args.out.write_text(json.dumps({'source_asset':DTM,'quantiles':q,'statistics_scale_m':60,
          'provenance':'Read-only Earth Engine whole-study-area percentile query'},indent=2),encoding='utf-8')
        print('Saved real quantiles:',args.out);return
    if not args.bucket:raise SystemExit('Export needs --bucket naming your existing Cloud Storage bucket; no cloud job started')
    if args.action=='export-dem':
        task=ee.batch.Export.image.toCloudStorage(image=image.toFloat().unmask(-9999),
          description='Sofia_native_DTM_1m',bucket=args.bucket,fileNamePrefix=args.prefix+'/sofia_dtm_1m',
          region=ee.Geometry.Rectangle([299392,4699268,351114,4753611],ee.Projection('EPSG:7801'),False),
          crs='EPSG:7801',crsTransform=GRID,maxPixels=4000000000,fileFormat='GeoTIFF',
          formatOptions={'cloudOptimized':True,'noData':-9999})
    else:
        task=ee.batch.Export.table.toCloudStorage(collection=points,description='Sofia_infrastructure_all_points',
          bucket=args.bucket,fileNamePrefix=args.prefix+'/sofia_infrastructure_points',fileFormat='GeoJSON')
    task.start();print(json.dumps({'task_id':task.id,'status':task.status(),'source':DTM if args.action=='export-dem' else POINTS},indent=2))

if __name__=='__main__':main()
