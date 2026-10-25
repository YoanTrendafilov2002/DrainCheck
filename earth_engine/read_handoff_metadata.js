var dem=ee.Image('projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee').select([0],['elevation']);
var area=ee.Geometry.Rectangle([23,42.4,23.7,42.95],null,false);
var native=dem.updateMask(dem.neq(-9999)).toFloat().clip(area);
var p=[],n=[];for(var i=0;i<=200;i++){p.push(i/2);n.push('q'+i);}
var points=ee.FeatureCollection('projects/rivertracker-512606/assets/sofia_infrastructure_pps');
var values=ee.Dictionary({
 projection_crs:dem.projection().crs(),
 projection_transform:dem.projection().transform(),
 nominal_scale_m:dem.projection().nominalScale(),
 point_count:points.size(),
 point_types:points.aggregate_histogram('type'),
 quantiles:native.reduceRegion({reducer:ee.Reducer.percentile(p,n,65536,0.05,4096),geometry:area.intersection(area,30),scale:60,bestEffort:true,maxPixels:2000000,tileScale:4})
});
values.evaluate(function(value,error){
 print('SOFIA_HANDOFF_SNAPSHOT:'+JSON.stringify(error?{error:error}:value));
});
