"""Restore the supplied full Earth Engine display curve; native values stay unchanged."""
import argparse,hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.scale import knots,legend

def restore_reference_scale(root,native_hash):
    root=Path(root)
    source=root/'data/reference/elevation_quantiles_whole_area.json'
    if not source.is_file():return False
    snapshot=json.loads(source.read_text(encoding='utf-8'))
    if snapshot.get('source_asset')!='projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee':
        raise ValueError('Whole-area colour curve refers to a different terrain asset')
    if snapshot.get('bounds_wgs84')!=[23,42.4,23.7,42.95]:
        raise ValueError('Whole-area colour curve has an unexpected scope')
    q=snapshot['quantiles_m'];heights,levels=knots(q)
    snapshot_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    path=root/'data/cache/whole_scale.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
    if previous and previous.get('reference_snapshot_sha256')==snapshot_hash and previous.get('source_sha256')==native_hash:
        return False
    if previous:
        archive=root/'data/reference/previous_whole_scales'/('whole-'+hashlib.sha256(path.read_bytes()).hexdigest()[:16]+'.json')
        archive.parent.mkdir(parents=True,exist_ok=True)
        if not archive.exists():archive.write_bytes(path.read_bytes())
    definition={'id':'whole','scope':'whole-study-area','quantiles':q,'heights':heights,'levels':levels,
      'statistics_scale_m':snapshot['statistics_scale_m'],'native_sample_scale_m':1,
      'bbox':snapshot['bounds_wgs84'],'source_sha256':native_hash,
      'reference_snapshot_sha256':snapshot_hash,'reference_asset':snapshot['source_asset'],
      'provenance':'Supplied complete 201-point Earth Engine whole-study-area snapshot; 60 m display statistics. Native 1 m values and local fit are unchanged.',
      'method':'201 continuous percentiles, 80% empirical percentile + 20% linear height; no height quantization',
      'snapshot_date':snapshot.get('snapshot_date')}
    definition['legend']=legend(definition)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.reference.tmp')
    temporary.write_text(json.dumps(definition,indent=2),encoding='utf-8');temporary.replace(path)
    return True

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.parse_args()
    from dotenv import load_dotenv
    from backend.terrain import LocalTerrain
    load_dotenv(root/'.env')
    native=Path(os.environ.get('SOFIA_DTM_PATH',str(root.parent/'sofia_dtm_2024_1m_gee.tif')))
    if not native.is_absolute():native=root/native
    adapter=LocalTerrain(native,root/'data/cache')
    if not adapter.available:raise ValueError('A validated real native Sofia raster is required')
    with native.open('rb') as stream:native_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    print(json.dumps({'restored':restore_reference_scale(root,native_hash),'native_sha256':native_hash}))
