import pathlib,json,zlib,base64
s=pathlib.Path('work/inline_data.js').read_text(); names=['ROUTE_SOURCE','ROUTE_GEOMETRIES','GREEN_GEOMETRIES'];data=[]
for i,n in enumerate(names):
 a=s.index('var '+n+' = ')+len('var '+n+' = ');b=s.index('\n];',a)+2;data.append(json.loads(s[a:b]))
raw=json.dumps(data,ensure_ascii=True,separators=(',',':')).encode();compress=zlib.compressobj(9,zlib.DEFLATED,-15);packed=compress.compress(raw)+compress.flush();enc=base64.b64encode(packed).decode();pathlib.Path('work/vector_payload.b64').write_text(enc);pathlib.Path('work/vector_payload.json').write_bytes(raw);print('raw',len(raw),'base64',len(enc))
