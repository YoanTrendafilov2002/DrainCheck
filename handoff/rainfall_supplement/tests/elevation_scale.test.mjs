import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildScale,normalizeElevation,elevationAtLevel,rgbaForElevation,legendTicks} from '../shared/elevation_scale.mjs';

test('uniform distribution gives an invertible linear stretch',()=>{
  const scale=buildScale(Array.from({length:201},(_,i)=>500+i));
  for(const h of [500,501.25,550,600,650,699.5,700]){
    assert.ok(Math.abs(normalizeElevation(h,scale)-(h-500)/200)<1e-12);
    assert.ok(Math.abs(elevationAtLevel(normalizeElevation(h,scale),scale)-h)<1e-9);
  }
});
test('repeated quantiles and flat terrain never divide by zero',()=>{
  for(const q of [Array(201).fill(550),Array.from({length:201},(_,i)=>500+Math.floor(i/5))]){
    const s=buildScale(q);
    assert.ok(s.x.every((v,i)=>i===0||v>s.x[i-1]));
    assert.ok(s.y.every((v,i)=>i===0||v>s.y[i-1]));
    assert.ok(Number.isFinite(normalizeElevation(q[100],s)));
  }
  assert.equal(normalizeElevation(550,buildScale(Array(201).fill(550))),0.5);
});
test('small relief remains distinguishable; data are not quantized',()=>{
  const q=Array.from({length:201},(_,i)=>550+i/100), before=[...q],s=buildScale(q);
  assert.ok(normalizeElevation(550.01,s)>normalizeElevation(550,s));
  assert.deepEqual(q,before);
  assert.deepEqual(rgbaForElevation(550,s),[11,77,162,255]);
  assert.deepEqual(rgbaForElevation(552,s),[181,50,82,255]);
});
test('missing pixels remain transparent and invalid quantiles fail clearly',()=>{
  const s=buildScale(Array.from({length:201},(_,i)=>500+i));
  for(const h of [null,NaN,Infinity,-9999])assert.deepEqual(rgbaForElevation(h,s),[0,0,0,0]);
  assert.equal(normalizeElevation(550,s,false),null);
  assert.throws(()=>buildScale([500,600]));
  const bad=Array(201).fill(500);bad[100]=499;assert.throws(()=>buildScale(bad));
});
test('live whole-area quantiles reproduce the observed Earth Engine legend',()=>{
  const data=JSON.parse(readFileSync(new URL('../data/reference/elevation_quantiles_whole_area.json',import.meta.url),'utf8'));
  const scale=buildScale(data.quantiles_m);
  assert.deepEqual(legendTicks(scale).map(t=>t.elevation_m.toFixed(1)),['501.0','574.3','808.3','1062.6','2278.8']);
  assert.ok(scale.x.every((x,i)=>!i||x>scale.x[i-1]));
  assert.ok(scale.y.every((y,i)=>!i||y>scale.y[i-1]));
});
