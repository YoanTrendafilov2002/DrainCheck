"""Install a real 201-point EE snapshot without modifying the supplied snapshot."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.scale import knots,legend

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);args=p.parse_args()
    raw=json.loads(args.input.read_text(encoding='utf-8'))
    if isinstance(raw,dict) and raw.get('source_asset','projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee')!='projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee':
        raise SystemExit('Snapshot source_asset does not match the Sofia municipal DTM')
    q=raw if isinstance(raw,list) else raw.get('quantiles')
    heights,levels=knots(q)
    cache=ROOT/'data/cache'
    previous=json.loads((cache/'whole_scale.json').read_text(encoding='utf-8')) if (cache/'whole_scale.json').exists() else {}
    definition={**previous,'id':'whole','scope':'whole-study-area','quantiles':q,'heights':heights,'levels':levels,
      'statistics_scale_m':60,'native_sample_scale_m':1,'bbox':[23,42.4,23.7,42.95],
      'input_quantile_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),
      'provenance':'Imported complete 201-point snapshot: '+args.input.name+'; source snapshot unchanged'}
    definition['legend']=legend(definition)
    target=cache/'whole_scale.json'
    if target.exists():
        backup=cache/('whole_scale_before_import_'+hashlib.sha256(target.read_bytes()).hexdigest()[:12]+'.json')
        if not backup.exists():backup.write_bytes(target.read_bytes())
    target.write_text(json.dumps(definition,indent=2),encoding='utf-8')
    print('Imported real curve. Run python scripts/prepare_data.py, then restart the API to update the data revision.')
