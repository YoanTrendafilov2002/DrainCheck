import json,pathlib
base=pathlib.Path('work');p=json.load(open('upload/vik_kanal_26_sofpr_20090000.geojson')); routes=json.load(open(base/'routes_inline.json'));green=json.load(open(base/'green_intersecting_inline.json'))
props={f['properties']['id']:i for i,f in enumerate(p['features'])}
def enc(coords):
 out=[];last=[23000000000,42000000000]
 for xy in coords:
  for k in range(2):
   v=round(xy[k]*1e9);d=v-last[k];last[k]=v;n=2*d if d>=0 else -2*d-1
   while n>=32:out.append(chr((n&31)|32|64 if False else ((n&31)|32)+63));n>>=5
   out.append(chr(n+63))
 return ''.join(out)
pdata=[[f['properties']['object_id'],f['properties']['id'],f['properties']['leg'],f['properties']['legso']] for f in p['features']]
rdata=[]
for f in routes['features']:
 a=f['properties']; geom=f['geometry'];coords=geom['coordinates'];coords=[coords] if geom['type']=='LineString' else coords
 rdata.append([props[a['source_id']],{'all':0,'inside':1,'outside':2}[a['zone']],round(a['length_m'],3),[enc(c) for c in coords]])
gdata=[[[enc(ring) for ring in poly] for poly in f['geometry']['coordinates']] for f in green['features']]
parts=['// Compact lossless original coordinates; clip endpoints rounded to 1e-9 degree (<0.1 mm).\n']
for name,data in [('ROUTE_SOURCE',pdata),('ROUTE_GEOMETRIES',rdata),('GREEN_GEOMETRIES',gdata)]:
 parts.append('var '+name+' = [\n'+',\n'.join(json.dumps(row,ensure_ascii=False,separators=(',',':')) for row in data)+'\n];\n')
parts.append('''function decodePath(encoded) {
  var pos = 0, last = [23000000000, 42000000000], path = [];
  while (pos < encoded.length) {
    var xy = [];
    for (var axis = 0; axis < 2; axis++) {
      var value = 0, factor = 1, digit;
      do {
        digit = encoded.charCodeAt(pos++) - 63;
        value += (digit & 31) * factor;
        factor *= 32;
      } while (digit >= 32);
      var delta = value % 2 ? -(value + 1) / 2 : value / 2;
      last[axis] += delta;
      xy.push(last[axis] / 1e9);
    }
    path.push(xy);
  }
  return path;
}
var routeParts = ee.FeatureCollection(ROUTE_GEOMETRIES.map(function(row) {
  var source = ROUTE_SOURCE[row[0]];
  var status = source[3].indexOf('проект') >= 0 ? 'planned' :
    (source[3].indexOf('Открит') >= 0 ? 'open' : 'existing');
  return ee.Feature(ee.Geometry.MultiLineString(row[3].map(decodePath), 'EPSG:4326', false), {
    object_id: source[0], source_id: source[1], leg: source[2], legso: source[3],
    status: status, zone: ['all', 'inside', 'outside'][row[1]], length_m: row[2]
  });
}));
var greenAreas = ee.FeatureCollection(GREEN_GEOMETRIES.map(function(polygons) {
  return ee.Feature(ee.Geometry.MultiPolygon(polygons.map(function(rings) {
    return rings.map(decodePath);
  }), 'EPSG:4326', false));
}));
''')
output=''.join(parts);(base/'inline_data.js').write_text(output);print('Inline JS bytes',len(output.encode()))
# Check every encoded coordinate decodes, including negative offsets and rings.
def dec(s):
 pos=0;last=[23000000000,42000000000];out=[]
 while pos<len(s):
  pt=[]
  for k in range(2):
   n=0;fac=1
   while True:
    digit=ord(s[pos])-63;pos+=1;n+=(digit&31)*fac;fac*=32
    if digit<32:break
   last[k]+=-(n+1)//2 if n%2 else n//2;pt.append(last[k]/1e9)
  out.append(pt)
 return out
for f,row in zip(routes['features'],rdata):
 coords=f['geometry']['coordinates'];coords=[coords] if f['geometry']['type']=='LineString' else coords
 for c,e in zip(coords,row[3]):
  assert all(abs(a-b)<=5.1e-10 for xy,uv in zip(c,dec(e)) for a,b in zip(xy,uv))
print('All route coordinates verified')
