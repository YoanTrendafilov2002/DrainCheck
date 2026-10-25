// Standalone acquisition utility, not a replacement for Script1 or Script2.
// Run in a NEW unsaved Code Editor tab. Then start chosen tasks under Tasks.
// Creates tasks only. The full 1 m DTM can be several GB; choose storage first.
var DTM='projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee';
var POINTS='projects/rivertracker-512606/assets/sofia_infrastructure_pps';
var AREA=ee.Geometry.Rectangle([23,42.4,23.7,42.95],null,false);
var source=ee.Image(DTM).select([0],['elevation']);
var elevation=source.updateMask(source.neq(-9999)).toFloat().clip(AREA);
var folder='SofiaCodex';
Export.image.toDrive({
  image:elevation.unmask({value:-9999,sameFootprint:false}),
  description:'sofia_codex_dtm_1m',fileNamePrefix:'sofia_codex_dtm_1m',folder:folder,
  region:AREA,crs:'EPSG:7801',crsTransform:[1,0,299392,0,-1,4753611],
  maxPixels:5000000000,fileDimensions:8192,shardSize:256,fileFormat:'GeoTIFF',
  formatOptions:{cloudOptimized:true,noData:-9999}
});
Export.table.toDrive({collection:ee.FeatureCollection(POINTS),
  description:'sofia_codex_infrastructure',fileNamePrefix:'sofia_codex_infrastructure',
  folder:folder,fileFormat:'GeoJSON'});
var percentiles=[],names=[];
for(var i=0;i<=200;i++){percentiles.push(i/2);names.push('q'+i);}
var stats=elevation.reduceRegion({
  reducer:ee.Reducer.percentile(percentiles,names,65536,0.05,4096),
  geometry:AREA,scale:60,bestEffort:true,maxPixels:2000000,tileScale:4});
var rows=ee.FeatureCollection(ee.List.sequence(0,200).map(function(i){
  i=ee.Number(i);
  return ee.Feature(null,{percentile:i.divide(2),elevation_m:stats.get(ee.String('elevation_q').cat(i.format('%d')))});
}));
Export.table.toDrive({collection:rows,description:'sofia_codex_elevation_quantiles',
  fileNamePrefix:'sofia_codex_elevation_quantiles',folder:folder,
  fileFormat:'CSV',selectors:['percentile','elevation_m']});
print('Native projection to verify',source.projection());
print('Expected infrastructure count: 322025',ee.FeatureCollection(POINTS).size());
print('Tasks prepared. Start only the exports whose destination has sufficient capacity.');
