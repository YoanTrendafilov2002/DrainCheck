// Read-only rainfall handoff inventory; creates no export jobs or assets.
var folder = 'projects/rivertracker-512606/assets/sofia_rain_20250627/';
['merged_250m','radar_bias_corrected_250m','radar_raw_1km'].forEach(function(name) {
  ee.Image(folder+name).evaluate(function(value,error) {
    print('RAIN_ASSET_'+name+':'+JSON.stringify(error?{error:error}:value));
  });
});
ee.FeatureCollection(folder+'wu_stations').evaluate(function(value,error) {
  print('RAIN_STATIONS:'+JSON.stringify(error?{error:error}:value));
});
