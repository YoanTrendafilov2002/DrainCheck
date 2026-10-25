import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createScale,normalize,inverse,legend} from '../shared/elevation_scale.mjs';
import {buildScale,normalizeElevation,elevationAtLevel,legendTicks} from '../handoff/rainfall_supplement/shared/elevation_scale.mjs';
const supplied=JSON.parse(fs.readFileSync(new URL('../data/reference/elevation_quantiles_whole_area.json',import.meta.url)));

test('whole-area colour scale uses all 201 recovered source quantiles and original inverse metre ticks',()=>{
  const active=JSON.parse(fs.readFileSync(new URL('../data/cache/whole_scale.json',import.meta.url)));
  assert.deepEqual(active.quantiles,supplied.quantiles_m);
  const expected=legendTicks(buildScale(supplied.quantiles_m));
  const actual=legend(createScale(active.quantiles));
  actual.forEach((tick,i)=>assert.ok(Math.abs(tick.elevation_m-expected[i].elevation_m)<1e-10));
  assert.equal(active.scope,'whole-study-area');assert.equal(active.native_sample_scale_m,1);
});

test('retained scale API matches the recovered continuous transform between knots without height banding',()=>{
  const current=createScale(supplied.quantiles_m),reference=buildScale(supplied.quantiles_m);
  for(let i=0;i<=2000;i++){
    const height=490+i*.91;
    assert.ok(Math.abs(normalize(height,current)-normalizeElevation(height,reference))<1e-12);
    const level=i/2000;
    assert.ok(Math.abs(inverse(level,current)-elevationAtLevel(level,reference))<1e-10);
  }
  const h=supplied.quantiles_m[55],next=supplied.quantiles_m[56];
  assert.notEqual(normalize(h,current),normalize((h+next)/2,current));
  assert.notEqual(normalize((h+next)/2,current),normalize(next,current));
});
