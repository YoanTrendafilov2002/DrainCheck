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
