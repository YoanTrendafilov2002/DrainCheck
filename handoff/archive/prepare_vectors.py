import json,pathlib,shapefile,zipfile,collections
from shapely.geometry import shape,mapping,MultiPolygon,MultiLineString,LineString
from shapely.geometry.polygon import orient
from shapely import make_valid,STRtree,union_all
from pyproj import CRS,Geod
base=pathlib.Path('upload'); out=pathlib.Path('work')
g=json.load(open(next(base.glob('green*')))); p=json.load(open(base/'vik_kanal_26_sofpr_20090000.geojson'))
def polygons(x):
 if x.geom_type=='Polygon': return [x]
 if hasattr(x,'geoms'): return [a for t in x.geoms for a in polygons(t)]
 return []
def lines(x):
 if x.geom_type=='LineString': return [x] if x.length else []
 if hasattr(x,'geoms'): return [a for t in x.geoms for a in lines(t)]
 return []
def finish(w,name):
 w.close(); (out/(name+'.prj')).write_text(CRS('EPSG:4326').to_wkt(version='WKT1_ESRI')); (out/(name+'.cpg')).write_text('UTF-8')
 with zipfile.ZipFile(out/(name+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
  for ext in ['shp','shx','dbf','prj','cpg']:z.write(out/(name+'.'+ext),name+'.'+ext)
 print(name,(out/(name+'.zip')).stat().st_size)
geoms=[]; invalid=0
w=shapefile.Writer(str(out/'sofia_green_areas_2020'),shapeType=shapefile.POLYGON,encoding='utf-8'); w.field('object_id','N',12,0);w.field('source_id','C',40);w.field('area_m2','F',20,3)
for f in g['features']:
 x=shape(f['geometry'])
 if not x.is_valid: invalid+=1;x=make_valid(x)
 ps=[a for a in polygons(x) if not a.is_empty]
 if not ps:continue
 x=MultiPolygon(ps);geoms.append(x)
 parts=[]
 for poly in ps:
  poly=orient(poly,sign=-1);parts.append(list(poly.exterior.coords));parts.extend(list(r.coords) for r in poly.interiors)
 w.poly(parts);a=f['properties'];w.record(a.get('object_id'),a.get('id'),a.get('area_kv_m'))
finish(w,'sofia_green_areas_2020')
tree=STRtree(geoms);geod=Geod(ellps='WGS84');totals=collections.defaultdict(float);counts=collections.Counter();w=shapefile.Writer(str(out/'sofia_sewer_routes_green_split'),shapeType=shapefile.POLYLINE,encoding='utf-8')
for n,t,size,dec in [('object_id','N',12,0),('source_id','C',40,0),('leg','C',150,0),('legso','C',150,0),('status','C',12,0),('zone','C',8,0),('length_m','F',20,3)]:w.field(n,t,size,dec)
for f in p['features']:
 x=shape(f['geometry']);a=f['properties'];cand=tree.query(x,predicate='intersects'); mask=union_all([geoms[i] for i in cand]); status='planned' if 'проект' in (a['legso'] or '') else ('open' if 'Открит' in (a['legso'] or '') else 'existing')
 parts = [x] if x.is_simple else [LineString([a,b]) for l in lines(x) for a,b in zip(list(l.coords)[:-1],list(l.coords)[1:])]
 for zone,geom in [('all',x),('inside',MultiLineString([l for part in parts for l in lines(part.intersection(mask))])),('outside',MultiLineString([l for part in parts for l in lines(part.difference(mask))]))]:
  ls=lines(geom)
  if not ls:continue
  length=sum(abs(geod.geometry_length(l)) for l in ls);w.line([list(l.coords) for l in ls]);w.record(a['object_id'],a['id'],a['leg'],a['legso'],status,zone,length);totals[zone]+=length;counts[zone]+=1
finish(w,'sofia_sewer_routes_green_split')
print(json.dumps({'repaired_green_features':invalid,'counts':dict(counts),'length_m':dict(totals),'status_counts':dict(collections.Counter('planned' if 'проект' in (f['properties']['legso'] or '') else ('open' if 'Открит' in (f['properties']['legso'] or '') else 'existing') for f in p['features']))},ensure_ascii=False))
assert abs(totals['all']-totals['inside']-totals['outside'])<1
