import {readdir,readFile,writeFile} from 'node:fs/promises';
import {join,extname} from 'node:path';
import {gzipSync} from 'node:zlib';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../dist/',import.meta.url));let files=0,before=0,after=0;
async function visit(path){for(const entry of await readdir(path,{withFileTypes:true})){
  const file=join(path,entry.name);
  if(entry.isDirectory()){await visit(file);continue;}
  if(!['.js','.mjs','.css','.html','.svg','.json'].includes(extname(file)))continue;
  const original=await readFile(file);if(original.length<512)continue;
  const compressed=gzipSync(original,{level:6});if(compressed.length>=original.length)continue;
  await writeFile(file+'.gz',compressed);files++;before+=original.length;after+=compressed.length;
}}
await visit(root);console.log(JSON.stringify({compressed_static_files:files,original_bytes:before,gzip_bytes:after}));
