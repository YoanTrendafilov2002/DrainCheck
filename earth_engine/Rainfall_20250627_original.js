// SOFIA INFRASTRUCTURE + ORIGINAL 1 METRE MUNICIPAL DTM + RAINFALL 2025-06-27
// Source: SofiaPlan municipal DTM, listed valid at 2024-10-01.
// Uses the CRS-corrected copy of the original 1 m GeoTIFF, on its native grid.
// Heights remain Baltic 1982 (EPSG:5786); no vertical shift was applied.
// IMPORTANT: Upload sofia_dtm_2024_1m_gee.tif under DTM_ASSET before running.
// Horizontal CRS only: EPSG:7801. Original pixels/grid are unchanged.
// Infrastructure features remain original points. No NDWI is used.
// Rainfall: OPERA radar (1 km, 5-min) merged with 43 Weather Underground stations,
// 250 m grid, 2025-06-27 local day (radar_1km.py / radar_station_merge.py / upload_to_ee.py).
var POINT_ASSET = 'projects/rivertracker-512606/assets/sofia_infrastructure_pps';
var GRID_CRS = 'EPSG:7801'; // Native BGS2005 / CCS2005, metres.
var GRID_TRANSFORM = [1, 0, 299392, 0, -1, 4753611];
// Planned asset ID. Change this if you choose a different upload name.
var DTM_ASSET = 'projects/rivertracker-512606/assets/sofia_dtm_2024_1m_gee';
var RAIN_FOLDER = 'projects/rivertracker-512606/assets/sofia_rain_20250627/';
var points = ee.FeatureCollection(POINT_ASSET);
var area = ee.Geometry.Rectangle([23.0, 42.4, 23.7, 42.95], null, false);
var referenceURL = 'https://en-ca.topographic-map.com/map-lggrf3/Sofia/?center=42.75068%2C23.30135&zoom=14';
Map.setOptions('TERRAIN');
Map.setCenter(23.30135, 42.75068, 14);
// The DTM asset must finish uploading before this script can run.
// Preserve the original pixel values and native 1 m projection.
var sourceLabel = 'SofiaPlan municipal DTM | original 1 m grid';
// Coarser samples estimate display contrast only. Data and click readouts
// retain the native 1 m grid. No 10 m terrain asset is used.
var statisticsScale = 10;
var uploadedDtm = ee.Image(DTM_ASSET);
print('Actual uploaded DTM band names', uploadedDtm.bandNames());
print('Actual uploaded DTM projection', uploadedDtm.select([0]).projection());
print('Actual uploaded DTM transform', uploadedDtm.select([0]).projection().transform());
var dem = uploadedDtm.select([0], ['elevation']);
var nativeElevation = dem.updateMask(dem.neq(-9999)).toFloat().clip(area);
var elevation = nativeElevation;
var hillshade = ee.Terrain.hillshade(elevation, 315, 45).clip(area);
var palette = ['0b4da2', '27a7df', '6ddcc7', '83ca42', 'd7e865',
  'fff2a3', 'f6bd60', 'e76f51', 'b53252'];
var elevationLayer = ui.Map.Layer(elevation,
  {min: 0, max: 3000, palette: palette},
  'Elevation | native 1 m grid | ' + sourceLabel, true, 0.85);
var hillshadeLayer = ui.Map.Layer(hillshade, {min: 0, max: 255},
  'Hillshade | native 1 m DTM', true, 0.22);
Map.layers().add(elevationLayer);
Map.layers().add(hillshadeLayer);
// Rainfall layers sit above the terrain and below the infrastructure points.
var rainMerged = ee.Image(RAIN_FOLDER + 'merged_250m');
var rainCorrected = ee.Image(RAIN_FOLDER + 'radar_bias_corrected_250m');
var rainRadarRaw = ee.Image(RAIN_FOLDER + 'radar_raw_1km');
var rainStations = ee.FeatureCollection(RAIN_FOLDER + 'wu_stations');
var rainPalette = ['f7fbff', 'c6dbef', '6baed6', '2171b5', '08306b', '54278f', 'e7298a'];
var rainVis = {min: 0, max: 30, palette: rainPalette};
var stationsUsed = rainStations.filter(ee.Filter.eq('qc', 'ok'));
var stationsRejected = rainStations.filter(ee.Filter.neq('qc', 'ok'));
var stationsUsedStyled = stationsUsed.map(function(f) {
  var i = ee.Number(f.get('rain_mm')).divide(rainVis.max).clamp(0, 1)
    .multiply(rainPalette.length - 1).round();
  return f.set('style', {color: '000000', fillColor: ee.List(rainPalette).get(i),
    pointSize: 6, width: 1});
});
// Display only: bilinear resampling draws a continuous surface between cell centres instead of
// blocky cells. Asset values, statistics and click readouts use the original grids.
var smooth = function(image) {return image.resample('bilinear');};
var rainLayers = [
  {label: 'Radar + stations, 250 m (final)', color: '2171b5', shown: true, layer: ui.Map.Layer(
    smooth(rainMerged).updateMask(smooth(rainMerged).gt(0.5)), rainVis,
    'Rain | merged radar + stations 250 m', true, 0.7)},
  {label: 'Radar bias-corrected, 250 m', color: '6baed6', shown: false, layer: ui.Map.Layer(
    smooth(rainCorrected), rainVis, 'Rain | radar bias-corrected 250 m', false, 0.7)},
  {label: 'Radar raw, 1 km (overestimates ~4x)', color: '54278f', shown: false, layer: ui.Map.Layer(
    smooth(rainRadarRaw), {min: 0, max: 110, palette: rainPalette}, 'Rain | radar raw 1 km', false, 0.7)},
  {label: 'Rain stations used (43)', color: '000000', shown: true, layer: ui.Map.Layer(
    stationsUsedStyled.style({styleProperty: 'style'}), {}, 'Rain | stations used', true)},
  {label: 'Rain stations rejected by QC (12)', color: 'ff0000', shown: false, layer: ui.Map.Layer(
    stationsRejected.style({color: 'red', pointSize: 4, pointShape: 'x'}), {},
    'Rain | stations rejected', false)}
];
// Rasters go in now; station points are added after the infrastructure so they stay on top.
rainLayers.slice(0, 3).forEach(function(item) {Map.layers().add(item.layer);});
// Separate infrastructure layers. These are vector points, not raster cells.
var categories = [
  {code: 1, label: 'Unknown', color: 'bdbdbd', count: 0, shown: false},
  {code: 2, label: 'Water supply', color: '00c8ff', count: 40994, shown: true},
  {code: 3, label: 'Sewerage', color: 'ff9f1c', count: 70790, shown: true},
  {code: 4, label: 'Collectors', color: 'e76f51', count: 1050, shown: true},
  {code: 5, label: 'Power network', color: 'ffeb3b', count: 116844, shown: false},
  {code: 6, label: 'Low-current network', color: 'c77dff', count: 81336, shown: false},
  {code: 7, label: 'District heating / steam', color: 'ff4d6d', count: 10928, shown: false}
];
// All layer toggles live in one panel: rainfall, topography, infrastructure.
var layersPanel = ui.Panel({
  style: {position: 'bottom-left', width: '330px', padding: '10px', maxHeight: '560px'}
});
layersPanel.add(ui.Label('Layers', {fontSize: '18px', fontWeight: 'bold'}));
function addSectionTitle(title, note) {
  layersPanel.add(ui.Label(title, {fontSize: '14px', fontWeight: 'bold', margin: '10px 8px 2px 8px'}));
  if (note) layersPanel.add(ui.Label(note, {fontSize: '11px', color: '666666', margin: '0 8px 2px 8px'}));
}
function addToggleRow(layer, label, color, shown) {
  var row = ui.Panel({layout: ui.Panel.Layout.flow('horizontal')});
  row.add(ui.Label('', {backgroundColor: '#' + color,
    padding: '7px', margin: '5px 5px 0 8px'}));
  var checkbox = ui.Checkbox({label: label, value: shown,
    onChange: function(value) {layer.setShown(value);}});
  row.add(checkbox);
  layersPanel.add(row);
  return checkbox;
}
addSectionTitle('Rainfall 27.06.2025', 'Colour scale in the legend panel (bottom right).');
var rainCheckboxes = rainLayers.map(function(item) {
  return addToggleRow(item.layer, item.label, item.color, item.shown);
});
// Master switch for both station layers; it drives their own checkboxes so all stay in sync.
var stationsMaster = ui.Checkbox({label: 'All rain stations (used + rejected)', value: true,
  style: {fontWeight: 'bold', margin: '4px 8px 0 30px'},
  onChange: function(value) {
    rainCheckboxes.slice(3).forEach(function(checkbox) {checkbox.setValue(value);});
  }});
layersPanel.add(stationsMaster);
addSectionTitle('Topography', sourceLabel);
addToggleRow(elevationLayer, 'Elevation colours', palette[3], true);
addToggleRow(hillshadeLayer, 'Hillshade', '9e9e9e', true);
addSectionTitle('Sofia infrastructure', '322,025 source points.');
function addCategoryLayer(subset, label, color, count, shown) {
  var layer = ui.Map.Layer(subset, {color: color},
    'Infrastructure | ' + label, shown);
  Map.layers().add(layer);
  addToggleRow(layer, label + ' (' + count.toLocaleString('en-US') + ')', color, shown);
}
categories.forEach(function(category) {
  var subset = points.filter(ee.Filter.inList('type',
    [category.code, String(category.code)]));
  addCategoryLayer(subset, category.label, category.color,
    category.count, category.shown);
});
var unspecified = points.filter(ee.Filter.notNull(['type']).not());
addCategoryLayer(unspecified, 'Unspecified in source', 'ffffff', 83, false);
rainLayers.slice(3).forEach(function(item) {Map.layers().add(item.layer);});
layersPanel.add(ui.Label('Points do not define pipe routes or connections.',
  {fontSize: '11px', color: '666666', margin: '2px 8px'}));
Map.add(layersPanel);
// Legend panel (bottom right): topography first, rainfall below.
// Local percentile stretch changes colours only; elevations stay in metres.
var terrainPanel = ui.Panel({
  style: {position: 'bottom-right', width: '310px', padding: '10px', maxHeight: '560px'}
});
terrainPanel.add(ui.Label('Topography', {fontWeight: 'bold', fontSize: '17px'}));
terrainPanel.add(ui.Label(sourceLabel, {fontSize: '11px', color: '666666'}));
terrainPanel.add(ui.Label('1 x 1 m native grid | BGS2005 / CCS2005', {fontSize: '12px'}));
terrainPanel.add(ui.Label('Ground heights in metres | Baltic 1982',
  {fontSize: '11px', color: '666666'}));
var lastLegend = 'Elevation colours: 0-3000 m';
var legend = ui.Label('Reading local elevation range...', {fontSize: '12px'});
terrainPanel.add(legend);
var swatches = ui.Panel({layout: ui.Panel.Layout.flow('horizontal')});
palette.forEach(function(color) {
  swatches.add(ui.Label('', {backgroundColor: '#' + color,
    padding: '6px', width: '18px', margin: '0'}));
});
terrainPanel.add(swatches);
var fitRequest = 0;
var autoFit = true;
function fitColours(region) {
  var request = ++fitRequest;
  fitButton.setDisabled(true);
  legend.setValue('Reading local elevation range...');
  // Approximate statistics are sufficient for display contrast.
  // Colour statistics may use a coarser scale; source pixels are unchanged.
  nativeElevation.reduceRegion({
    reducer: ee.Reducer.percentile([2, 98]),
    geometry: region.intersection(area, 30),
    scale: statisticsScale, bestEffort: true,
    maxPixels: 1000000, tileScale: 2
  }).evaluate(function(values, error) {
    if (request !== fitRequest) return;
    fitButton.setDisabled(false);
    if (error || !values || typeof values.elevation_p2 !== 'number' ||
        typeof values.elevation_p98 !== 'number' ||
        !isFinite(values.elevation_p2) || !isFinite(values.elevation_p98)) {
      legend.setValue('No local range available. ' + lastLegend);
      return;
    }
    var low = Math.floor(values.elevation_p2);
    var high = Math.max(low + 1, Math.ceil(values.elevation_p98));
    elevationLayer.setVisParams({min: low, max: high, palette: palette});
    lastLegend = 'Elevation colours: ' + low + '-' + high + ' m (P2-P98)';
    legend.setValue(lastLegend);
  });
}
var fitButton = ui.Button({label: 'Fit colours to current view',
  onClick: function() {fitColours(ee.Geometry(Map.getBounds(true)));},
  style: {stretch: 'horizontal'}});
terrainPanel.add(fitButton);
terrainPanel.add(ui.Checkbox({label: 'Auto-fit when panning / zooming', value: true,
  onChange: function(value) {
    autoFit = value;
    if (value) {
      fitColours(ee.Geometry(Map.getBounds(true)));
    } else {
      ++fitRequest;
      fitButton.setDisabled(false);
      legend.setValue(lastLegend);
    }
  }}));
Map.onChangeBounds(ui.util.debounce(function() {
  if (autoFit) fitColours(ee.Geometry(Map.getBounds(true)));
}, 600));
var clickLabel = ui.Label('Click the map to read elevation.', {fontSize: '12px'});
terrainPanel.add(clickLabel);
terrainPanel.add(ui.Label({value: 'Original topographic map reference',
  targetUrl: referenceURL, style: {fontSize: '11px', color: '1565c0'}}));
terrainPanel.add(ui.Label('Rainfall 27.06.2025', {fontWeight: 'bold', fontSize: '17px', margin: '14px 8px 4px 8px'}));
terrainPanel.add(ui.Label('OPERA radar 1 km + 43 Weather Underground stations, ' +
  '250 m grid, local day (Europe/Sofia)', {fontSize: '11px', color: '666666'}));
var rainSwatches = ui.Panel({layout: ui.Panel.Layout.flow('horizontal')});
rainPalette.forEach(function(color) {
  rainSwatches.add(ui.Label('', {backgroundColor: '#' + color,
    padding: '6px', width: '26px', margin: '0'}));
});
terrainPanel.add(rainSwatches);
terrainPanel.add(ui.Label('0 to 30+ mm (raw radar: 0 to 110 mm)', {fontSize: '12px'}));
var rainSummary = ui.Label('Computing rain totals...', {fontSize: '12px', whiteSpace: 'pre'});
terrainPanel.add(rainSummary);
var rainArea = rainMerged.geometry();
rainMerged.divide(1000).multiply(ee.Image.pixelArea()).rename('m3')
  .reduceRegion({reducer: ee.Reducer.sum(), geometry: rainArea, scale: 250, maxPixels: 1e8})
  .combine(rainMerged.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.max(), '', true),
    geometry: rainArea, scale: 250, maxPixels: 1e8}))
  .set('area_km2', rainArea.area(1).divide(1e6))
  .evaluate(function(s, error) {
    if (error || !s) {
      rainSummary.setValue('Rain totals unavailable.');
      return;
    }
    rainSummary.setValue('Mean ' + s.rain_mm_mean.toFixed(1) + ' mm, max ' +
      s.rain_mm_max.toFixed(1) + ' mm\nWater volume: ' + (s.m3 / 1e6).toFixed(2) +
      ' million m3 over ' + s.area_km2.toFixed(0) + ' km2');
  });
var rainClickLabel = ui.Label('Click the map to read rainfall.', {fontSize: '12px', whiteSpace: 'pre'});
terrainPanel.add(rainClickLabel);
Map.add(terrainPanel);
fitColours(ee.Geometry.Point([23.30135, 42.75068]).buffer(8000).bounds(30));
var clickRequest = 0;
Map.onClick(function(coords) {
  var request = ++clickRequest;
  var location = ee.Geometry.Point([coords.lon, coords.lat]);
  clickLabel.setValue('Reading elevation...');
  rainClickLabel.setValue('Reading rainfall...');
  elevation.reduceRegion({reducer: ee.Reducer.first(), geometry: location,
    crs: GRID_CRS, crsTransform: GRID_TRANSFORM, maxPixels: 1000
  }).evaluate(function(values, error) {
    if (request !== clickRequest) return;
    clickLabel.setValue(!error && values && typeof values.elevation === 'number' ?
      'Elevation: ' + values.elevation.toFixed(1) + ' m' : 'No elevation here.');
  });
  ee.Dictionary({
    merged: rainMerged.reduceRegion(ee.Reducer.first(), location, 250).get('rain_mm'),
    corrected: rainCorrected.reduceRegion(ee.Reducer.first(), location, 250).get('rain_mm'),
    raw: rainRadarRaw.reduceRegion(ee.Reducer.first(), location, 1000).get('rain_mm')
  }).evaluate(function(values, error) {
    if (request !== clickRequest) return;
    if (error || !values) {
      rainClickLabel.setValue('No rainfall here.');
      return;
    }
    var mm = function(v) {return typeof v === 'number' ? v.toFixed(1) + ' mm' : '-';};
    rainClickLabel.setValue('Rain (final): ' + mm(values.merged) +
      '\nRadar corrected: ' + mm(values.corrected) + ' | raw: ' + mm(values.raw));
  });
  print('Up to 10 infrastructure points within 25 m',
    points.filterBounds(location.buffer(25)).limit(10));
  print('Rain stations within 500 m (qc = reason if rejected)',
    rainStations.filterBounds(location.buffer(500)));
});
print('Infrastructure points (expected 322025)', points.size());
print('Points without a category (expected 83)', unspecified.size());
print('Category counts', points.aggregate_histogram('type'));
print('Elevation source', sourceLabel);
print('Output grid', elevation.projection());
print('Output cell size in metres', elevation.projection().nominalScale());
print('Rain stations used / rejected', stationsUsed.size(), stationsRejected.size());
// Optional tiled export of the native 1 m values. Enable only if needed.
// When enabled, this creates a task; start it from Tasks > Run.
var CREATE_EXPORT_TASK = false;
if (CREATE_EXPORT_TASK) {
Export.image.toDrive({
  image: elevation,
  description: 'SofiaPlan_DTM_2024_1m',
  folder: 'GEE_Sofia',
  region: area,
  crs: GRID_CRS,
  crsTransform: GRID_TRANSFORM,
  maxPixels: 5000000000,
  fileDimensions: 8192,
  shardSize: 256,
  skipEmptyTiles: true,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true}
});
}
// Source and publishing conditions:
// https://sofiaplan.bg/api/
// https://api.sofiaplan.bg/datasets/656