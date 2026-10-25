// Display transform only. Input values and scientific raster remain unchanged.
export const PALETTE = ['0b4da2','27a7df','6ddcc7','83ca42','d7e865','fff2a3','f6bd60','e76f51','b53252'];

export function buildScale(quantiles) {
  if (!Array.isArray(quantiles) || quantiles.length !== 201 ||
      quantiles.some((v, i) => !Number.isFinite(v) || (i > 0 && v < quantiles[i-1]))) {
    throw new Error('Expected 201 finite nondecreasing quantiles for P0, P0.5, ... P100.');
  }
  const low = quantiles[0], high = quantiles[200], x = [], y = [];
  quantiles.forEach((value, i) => {
    if (!x.length || value > x[x.length-1]) {
      x.push(value);
      y.push(high > low ? 0.8*i/200 + 0.2*(value-low)/(high-low) : 0.5);
    }
  });
  if (x.length < 2) return {x:[low-0.5,low+0.5], y:[0,1], minimum:low, maximum:high, flat:true};
  y[0] = 0; y[y.length-1] = 1;
  return {x,y,minimum:low,maximum:high,flat:false};
}

function interpolate(value, from, to) {
  if (value <= from[0]) return to[0];
  if (value >= from[from.length-1]) return to[to.length-1];
  let lo=0, hi=from.length-1;
  while (hi-lo>1) {const mid=(lo+hi)>>1; if(from[mid]<=value)lo=mid;else hi=mid;}
  return to[lo]+(value-from[lo])/(from[hi]-from[lo])*(to[hi]-to[lo]);
}

export function normalizeElevation(height, scale, valid=true) {
  if (!valid || height === null || height === -9999 || !Number.isFinite(height)) return null;
  return interpolate(height,scale.x,scale.y);
}

export function elevationAtLevel(level, scale) {
  if (!Number.isFinite(level)) return null;
  return interpolate(level,scale.y,scale.x);
}

export function legendTicks(scale) {
  return [0,0.25,0.5,0.75,1].map(level=>({level,elevation_m:elevationAtLevel(level,scale)}));
}

export function rgbaForElevation(height, scale, valid=true) {
  const n=normalizeElevation(height,scale,valid);
  if(n===null)return [0,0,0,0];
  const index=n*(PALETTE.length-1), a=Math.min(Math.floor(index),PALETTE.length-2), weight=index-a;
  const rgb=hex=>[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16));
  const first=rgb(PALETTE[a]),second=rgb(PALETTE[a+1]);
  return first.map((v,i)=>Math.round(v+(second[i]-v)*weight)).concat(255);
}
