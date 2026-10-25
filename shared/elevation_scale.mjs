// Reimplemented from the recovered configuration; original module was not recoverable.
export function createScale(quantiles) {
  if (quantiles.length !== 201 || !quantiles.every(Number.isFinite) || quantiles.some((h,i)=>i>0&&h<quantiles[i-1])) throw Error('201 ordered finite quantiles required');
  const min=quantiles[0],max=quantiles.at(-1);
  if(min===max)return {heights:[min],levels:[.5]};
  const heights=[],levels=[];
  quantiles.forEach((height,i)=>{if(!heights.length||height>heights.at(-1)){heights.push(height);levels.push(.8*i/200+.2*(height-min)/(max-min));}});
  levels[0]=0;levels[levels.length-1]=1;return {heights,levels};
}
export function interpolate(value,x,y) {
  if(!Number.isFinite(value))return null;
  if(x.length===1)return y[0];
  if(value<=x[0])return y[0];if(value>=x.at(-1))return y.at(-1);
  let hi=x.findIndex(k=>k>=value),lo=hi-1;
  return y[lo]+(y[hi]-y[lo])*(value-x[lo])/(x[hi]-x[lo]);
}
export function normalize(height,scale){return scale.heights.length===1?(Number.isFinite(height)?.5:null):interpolate(height,scale.heights,scale.levels);}
export function inverse(level,scale){return interpolate(level,scale.levels,scale.heights);}
export function legend(scale){return [0,.25,.5,.75,1].map(level=>({level,elevation_m:inverse(level,scale)}));}
