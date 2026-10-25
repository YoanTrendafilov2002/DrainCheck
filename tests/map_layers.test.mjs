import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,realpathSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import {defaults} from '../shared/state.mjs';

const require=createRequire(import.meta.url);
const fromMapLibre=createRequire(realpathSync(require.resolve('maplibre-gl/package.json')));
const {validateStyleMin,featureFilter}=fromMapLibre('@maplibre/maplibre-gl-style-spec');
const source=ts.createSourceFile('MapView.tsx',readFileSync(new URL('../src/MapView.tsx',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function declaration(name){
  let found;
  function visit(node){if(ts.isFunctionDeclaration(node)&&node.name?.text===name)found=node;else ts.forEachChild(node,visit);}
  visit(source);assert.ok(found,'MapView function '+name+' exists');return found.getText(source);
}

// Exercise the real setup declarations without creating a browser/WebGL context.
// Validate the actual objects before JSON serialization can hide undefined keys.
function surveyLayers(settings={}){
  const state={...defaults,terrain:false,hillshade:false,buildings:false,cadastre:false,historySurvey:true,...settings};
  const latest={current:{state,meta:{revision:'test',terrain_available:false},historySurveyMeta:{available:true,revision:'test'}}};
  const layers=[],sources={};
  const map={getStyle:()=>({layers:[]}),getLayer:()=>undefined,getSource:name=>name==='history-survey'?sources[name]:{},addSource:(name,s)=>{sources[name]=s;},addLayer:layer=>layers.push(layer)};
  const code=ts.transpileModule(['revisionReady','historyFilter','screeningTileUrl','setup'].map(declaration).join('\n')+'\nreturn setup;',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
  const setup=new Function('latest','ready','historyDataUrl','window',code)(latest,{current:false},{current:''},{location:{origin:'https://example.test'}});
  setup(map);
  return {layers,style:{version:8,sources,layers}};
}

test('initial all/all historical layers validate without an undefined filter in both priority styles',()=>{
  for(const historyPriority of [false,true]){
    const {layers,style}=surveyLayers({historyPriority});
    assert.equal(layers.length,2);
    for(const layer of layers)assert.equal(Object.hasOwn(layer,'filter'),false);
    assert.deepEqual(validateStyleMin(style).map(error=>error.message),[]);
  }
});

test('historical map filters retain unknowns honestly and require both selected cause and certainty',()=>{
  for(const settings of [{historyMechanism:'unknown',historyConfidence:'unknown'},{historyMechanism:'pluvial',historyConfidence:'documented'}]){
    const {layers,style}=surveyLayers(settings);
    assert.deepEqual(validateStyleMin(style).map(error=>error.message),[]);
    for(const layer of layers){
      const accepts=properties=>featureFilter(layer.filter).filter({zoom:14},{type:'Polygon',properties});
      assert.equal(accepts({mechanism:settings.historyMechanism,mechanism_confidence:settings.historyConfidence}),true);
      assert.equal(accepts({mechanism:settings.historyMechanism,mechanism_confidence:'likely'}),false);
      assert.equal(accepts({}),settings.historyMechanism==='unknown');
    }
  }
});

function thematicLayers(riskMode='heatmap',scenario={}){
  const state={...defaults,risk:true,riskMode,historySurvey:true,assessmentOverlay:true,statuses:['planned']};
  const buildings={available:true,revision:'test',minzoom:13,coverage_bbox_wgs84:[23,42.4,23.7,42.95]};
  const config=JSON.parse(readFileSync(new URL('../config/map_config.json',import.meta.url),'utf8'));
  const latest={current:{state,meta:{revision:'test',renderer_revision:'renderer',terrain_available:true,config},
    pluvialMeta:{available:true,revision:'ponding-source'},refinementMeta:{available:true,revision:'review-source'},
    buildingsMeta:buildings,cadastreMeta:buildings,historySurveyMeta:buildings,assessmentMeta:buildings,scale:{id:'whole'},...scenario}};
  const layers=[],sources={};
  const noop=()=>{},canvas={style:{}};
  const map={getStyle:()=>({layers}),getZoom:()=>16,getLayer:id=>layers.find(l=>l.id===id),getSource:id=>sources[id],
    addSource:(id,s)=>{Object.defineProperties(s,{setTiles:{value:tiles=>{s.tiles=tiles;}},setData:{value:data=>{s.data=data;}}});sources[id]=s;},
    addLayer:(layer,before)=>{const i=layers.findIndex(l=>l.id===before);if(i<0)layers.push(layer);else layers.splice(i,0,layer);},
    setLayoutProperty:(id,key,value)=>{const layer=layers.find(l=>l.id===id);layer.layout={...layer.layout,[key]:value};},
    setPaintProperty:(id,key,value)=>{const layer=layers.find(l=>l.id===id);layer.paint={...layer.paint,[key]:value};},
    setFilter:(id,filter)=>{const layer=layers.find(l=>l.id===id);if(filter===null)delete layer.filter;else layer.filter=filter;},
    getCanvas:()=>canvas,dragPan:{enable:noop,disable:noop},boxZoom:{enable:noop,disable:noop},doubleClickZoom:{enable:noop,disable:noop}};
  const code=ts.transpileModule(['revisionReady','historyFilter','screeningTileUrl','areaFeature','setup','replaceTiles','apply'].map(declaration).join('\n')+'\nreturn {setup,apply};',
    {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
  const location={origin:'https://example.test'};
  const {setup,apply}=new Function('latest','ready','historyDataUrl','assessmentDataUrl','stationsDataUrl','window','location','m','drawingStart',code)
    (latest,{current:false},{current:''},{current:''},{current:''},{location},location,map,{current:null});
  setup(map);return {layers,sources,style:{version:8,sources,layers},latest,setup:()=>setup(map),apply};
}

test('complete thematic overlays validate and keep heatmap cells separate from categorical review',()=>{
  for(const mode of ['heatmap','review','ponding','combined','concentration']){
    const {style,sources,layers}=thematicLayers(mode);
    assert.deepEqual(validateStyleMin(style).map(error=>error.message),[]);
    assert.match(sources.pluvial.tiles[0],mode==='review'?/\/refinement\/tiles\//:new RegExp('/pluvial/'+mode+'/'));
    assert.equal(layers.find(l=>l.id==='pluvial').paint['raster-resampling'],'nearest');
    const order=id=>layers.findIndex(l=>l.id===id);
    assert.ok(order('green-fill')<order('pluvial'));
    assert.ok(order('pluvial')<order('green-outline'));
    assert.ok(order('pluvial')<order('history-survey-fill'));
    assert.ok(order('history-survey-outline')<order('cadastre-outline'));
  }
});

test('distinct sewer casings share status visibility and preserve coloured foreground lines',()=>{
  const {layers}=thematicLayers();
  for(const status of ['existing','planned','open']){
    const line=layers.find(l=>l.id==='route-'+status),casing=layers.find(l=>l.id==='route-casing-'+status);
    assert.deepEqual(line.filter,casing.filter);
    assert.equal(line.layout.visibility,status==='planned'?'visible':'none');
    assert.equal(casing.layout.visibility,line.layout.visibility);
    assert.notEqual(line.paint['line-color'],casing.paint['line-color']);
    assert.ok(layers.indexOf(casing)<layers.indexOf(line));
  }
});

test('selection boundary and grey buildings coexist above a separate depth scenario heatmap',()=>{
  const geometry={type:'Polygon',coordinates:[[[23.26,42.68],[23.27,42.68],[23.27,42.69],[23.26,42.69],[23.26,42.68]]]};
  const {layers,sources,style}=thematicLayers('heatmap',{selectionGeometry:geometry,selectedPipes:{type:'FeatureCollection',features:[]},cloggingVisible:true,cloggingMode:'depth_clogged',cloggingScenario:{scenario_id:'verified-example'},cloggingRiverFilter:'away',riverProximityM:250});
  assert.deepEqual(validateStyleMin(style).map(error=>error.message),[]);
  assert.equal(layers.find(l=>l.id==='pluvial').layout.visibility,'none');
  assert.match(sources['clogging-scenario'].tiles[0],/tiles\/depth_clogged\//);
  assert.match(sources['clogging-scenario'].tiles[0],/river_filter=away/);
  assert.match(sources['history-survey'].data,/river_proximity_m=250/);
  assert.ok(layers.findIndex(l=>l.id==='pipe-selection-outline')>layers.findIndex(l=>l.id==='cadastre-outline'));
  assert.equal(layers.find(l=>l.id==='cadastre-fill').paint['fill-color'],'#808990');
  assert.equal(layers.find(l=>l.id==='pipe-selection-fill').paint['fill-opacity'],.035);
  assert.deepEqual(sources['pipe-selection-area'].data.features[0].geometry,geometry);
});

test('source labels retain UTF8 units and punctuation',()=>{
  const ui=readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
  assert.match(ui,/m³/);assert.match(ui,/km²/);
  assert.equal(ui.includes('В·'),false);assert.equal(ui.includes('вЂ'),false);
});

test('available metadata without a revision never creates screening requests',()=>{
  for(const mode of ['heatmap','review','ponding','combined','concentration']){
    for(const revision of [undefined,null,'']){
      const result=thematicLayers(mode,{pluvialMeta:{available:true,revision},refinementMeta:{available:true,revision}});
      assert.equal(result.sources.pluvial,undefined);
      result.apply();
      assert.equal(result.sources.pluvial,undefined);
      assert.doesNotMatch(JSON.stringify(result.sources),/[?&]v=(?:undefined|null)(?:&|"|$)/);
    }
  }
});

test('a pre-registered style callback uses arriving metadata and preserves valid URLs during reload',()=>{
  for(const mode of ['heatmap','review']){
    // Keep this exact callback across asynchronous metadata changes: this is
    // the cold style.load ordering that previously replaced a valid source
    // created by setup with a stale closure's v=undefined URL.
    const result=thematicLayers(mode,{pluvialMeta:null,refinementMeta:null});
    const onStyleLoad=result.apply;
    assert.equal(result.sources.pluvial,undefined);
    result.latest.current.pluvialMeta={available:true,revision:'arrived-ponding'};
    result.latest.current.refinementMeta={available:true,revision:'arrived-review'};
    onStyleLoad();
    assert.match(result.sources.pluvial.tiles[0],mode==='review'?/v=arrived-review&/:/v=arrived-ponding&/);
    const validUrl=result.sources.pluvial.tiles[0];
    assert.equal(result.layers.find(l=>l.id==='pluvial').layout.visibility,'visible');
    result.latest.current.pluvialMeta=null;result.latest.current.refinementMeta={available:true};
    onStyleLoad();
    assert.equal(result.sources.pluvial.tiles[0],validUrl);
    assert.equal(result.layers.find(l=>l.id==='pluvial').layout.visibility,'none');
    assert.doesNotMatch(JSON.stringify(result.sources),/[?&]v=(?:undefined|null)(?:&|"|$)/);
  }
});
