#!/usr/bin/env python3
"""Verify immutable files, source identity, prototype payload and vector statistics."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def main():
    manifest=read_json(ROOT/'MANIFEST.json')
    for entry in manifest['files']:
        path=ROOT/entry['path']
        assert path.is_file(), ('missing',entry['path'])
        assert path.stat().st_size==entry['bytes'], ('size',entry['path'])
        assert digest(path)==entry['sha256'], ('hash',entry['path'])
    raw=ROOT/'data/raw'
    source=read_json(raw/'vik_kanal_26_sofpr_20090000.geojson')['features']
    assert digest(raw/'vik_kanal_26_sofpr_20090000.geojson')==digest(raw/'vik_kanal_26_sofpr_20090000(1).geojson')
    assert len(source)==717
    source_ids={f['properties']['id'] for f in source}
    assert len(source_ids)==717
    summary=read_json(ROOT/'data/derived/summary.json')
    lengths={}
    per_route=collections.defaultdict(dict)
    for zone, expected_count in [('all',717),('inside',543),('outside',670)]:
        fs=read_json(ROOT/'data/derived'/('sewer_routes_'+zone+'.geojson'))['features']
        assert len(fs)==expected_count
        ids=[f['properties']['source_id'] for f in fs]
        assert len(set(ids))==len(ids) and set(ids)<=source_ids
        if zone=='all': assert set(ids)==source_ids
        total=0
        for f in fs:
            p=f['properties']
            assert p['zone']==zone
            assert p['status'] in ['existing','planned','open']
            assert p['length_m']>0
            assert f['geometry']['type'] in ['LineString','MultiLineString']
            total+=p['length_m']; per_route[p['source_id']][zone]=p['length_m']
        lengths[zone]=total
        assert abs(total-summary['zone_length_m'][zone])<0.001
    assert abs(lengths['all']-lengths['inside']-lengths['outside'])<1
    assert max(abs(p['all']-p.get('inside',0)-p.get('outside',0)) for p in per_route.values())<0.001
    greens=read_json(next(raw.glob('green_areas*.geojson')))['features']
    assert len(greens)==64962
    displayed=read_json(ROOT/'data/derived/green_intersecting_routes.geojson')['features']
    assert len(displayed)==2175
    assert all(f['properties'].get('id') for f in displayed)
    assert len(summary['empty_green_source_ids'])==6
    assert len(summary['repaired_green_source_ids'])==1
    config=read_json(ROOT/'config/map_config.json')
    assert sum(c['count'] for c in config['infrastructure']['categories'])==322025
    scripts=[(ROOT/'earth_engine'/name).read_text(encoding='utf-8') for name in ['Script1.js','Script2.js']]
    packed=[]
    for script,name in zip(scripts,['PACKED_FIRST','PACKED_REST']):
        match=re.search(r'var '+name+r" = (\[.*?\])\.join\(''\);",script,re.S)
        assert match, name
        packed.append(''.join(json.loads(match.group(1))))
    data=json.loads(zlib.decompress(base64.b64decode(''.join(packed)),-15))
    assert list(map(len,data))==[717,1930,2175]
    for original,packed_source in zip(source,data[0]):
        p=original['properties']
        assert packed_source==[p['object_id'],p['id'],p['leg'],p['legso']]
    assert "require('users/yoantrendafilov2002/rivertracker:Script2')" in scripts[0]
    assert 'nativeElevation.interpolate(x,y' in scripts[0]
    assert 'min: 553, max: 598' not in scripts[0]
    for file,count in [('sofia_sewer_routes_green_split.zip',1930),('sofia_green_areas_2020.zip',64956)]:
        with zipfile.ZipFile(ROOT/'earth_engine/uploads'/file) as archive:
            assert archive.testzip() is None
            dbf=archive.read(next(n for n in archive.namelist() if n.endswith('.dbf')))
            shx=archive.read(next(n for n in archive.namelist() if n.endswith('.shx')))
            assert struct.unpack('<I',dbf[4:8])[0]==count
            assert (len(shx)-100)//8==count
    quantile_path=ROOT/'data/reference/elevation_quantiles_whole_area.json'
    if quantile_path.exists():
        q=read_json(quantile_path)['quantiles_m']
        assert len(q)==201 and all(isinstance(v,(int,float)) for v in q)
        assert all(a<=b for a,b in zip(q,q[1:]))
    print(json.dumps({'verified_manifest_files':len(manifest['files']),
        'prototype_payload_counts':list(map(len,data)),
        'route_counts':summary['zone_feature_counts'],'route_length_m':lengths,
        'raw_files_preserved':True,'duplicate_pipe_upload_kept':True,
        'native_DTM_bytes_bundled':False,'infrastructure_point_bytes_bundled':False},indent=2))

if __name__=='__main__':
    main()
