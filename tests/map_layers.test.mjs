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
  const code=ts.transpileModule(declaration('historyFilter')+'\n'+declaration('setup')+'\nreturn setup;',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
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

function thematicLayers(riskMode='heatmap'){
  const state={...defaults,risk:true,riskMode,historySurvey:true,assessmentOverlay:true,statuses:['planned']};
  const buildings={available:true,revision:'test',minzoom:13,coverage_bbox_wgs84:[23,42.4,23.7,42.95]};
  const config=JSON.parse(readFileSync(new URL('../config/map_config.json',import.meta.url),'utf8'));
  const latest={current:{state,meta:{revision:'test',renderer_revision:'renderer',terrain_available:true,config},
    pluvialMeta:{available:true,revision:'ponding-source'},refinementMeta:{available:true,revision:'review-source'},
    buildingsMeta:buildings,cadastreMeta:buildings,historySurveyMeta:buildings,assessmentMeta:buildings,scale:{id:'whole'}}};
  const layers=[],sources={};
  const map={getStyle:()=>({layers}),getZoom:()=>16,getLayer:id=>layers.find(l=>l.id===id),getSource:id=>sources[id],
    addSource:(id,s)=>{sources[id]=s;},addLayer:(layer,before)=>{const i=layers.findIndex(l=>l.id===before);if(i<0)layers.push(layer);else layers.splice(i,0,layer);}};
  const code=ts.transpileModule(['historyFilter','screeningTileUrl','setup'].map(declaration).join('\n')+'\nreturn setup;',
    {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
  const location={origin:'https://example.test'};
  const setup=new Function('latest','ready','historyDataUrl','assessmentDataUrl','window','location',code)
    (latest,{current:false},{current:''},{current:''},{location},location);
  setup(map);return {layers,sources,style:{version:8,sources,layers}};
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
