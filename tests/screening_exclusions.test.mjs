import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const source=ts.createSourceFile('main.tsx',readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
function declaration(name){
  let found;
  function visit(node){if(ts.isFunctionDeclaration(node)&&node.name?.text===name)found=node;else ts.forEachChild(node,visit);}
  visit(source);assert.ok(found,'Inspector component '+name+' exists');return found.getText(source);
}
const componentNames=['UserScreeningExcludedReadout','PluvialReadout','RefinementReadout'];
const code=ts.transpileModule(componentNames.map(declaration).join('\n')+'\nreturn {PluvialReadout,RefinementReadout};',
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None,jsx:ts.JsxEmit.React}}).outputText;
const empty=()=>null;
const {PluvialReadout,RefinementReadout}=new Function('React','Droplets','RiverContextReadout','AssessmentIntersections','reading','reviewColor',code)
  (React,empty,empty,empty,value=>String(value),'#888');

test('river and stadium exclusions are shown as user policy, without a numeric risk label',()=>{
  for(const [reason,label] of [['river','Mapped river footprint'],['stadium','Mapped stadium footprint'],['river_and_stadium','Mapped river / stadium footprint']]){
    for(const Component of [PluvialReadout,RefinementReadout]){
      const sample={status:'excluded_user_screening',screening_excluded:true,screening_exclusion_reason:reason,
        score:null,ponding_score:null,concentration_score:null,review_class:null,legacy_ponding_score:null};
      const html=renderToStaticMarkup(React.createElement(Component,{sample,error:null,mode:'heatmap',meta:{}}));
      assert.ok(html.includes(label));
      assert.match(html,/excluded from screening by user choice/);
      assert.match(html,/does not establish flood safety/);
      assert.match(html,/pipe-blockage scenarios/);
      assert.doesNotMatch(html,/class="screening-value|data-testid="review-category"|\/ 100/);
    }
  }
});
