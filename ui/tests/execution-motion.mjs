import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const bundle=await build({stdin:{contents:"export * from './src/browser/execution-motion';export * from './src/step-labels';export {kinds} from './src/browser/physical-history';",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node'});
const {motionScenes,stepMotion,motionMarkup,kinds,operationName,operationColor,configuredLabel,statusLabel}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
test('every observed kind has a distinct bounded decorative diagram',()=>{
 for(const kind of [...kinds,'write','export','confirm']){
  assert(motionScenes[kind]);const svg=motionMarkup(kind);assert.match(svg,/aria-hidden="true"/);assert.match(svg,/focusable="false"/);assert(!svg.includes('<text'));assert(!svg.includes(' id='));assert((svg.match(/class="motion-actor/g)||[]).length<=3);
 }
 assert.equal(new Set(Object.values(motionScenes)).size,Object.keys(motionScenes).length);
});
test('shuffle motion follows observed algorithms instead of guessing from requested auto',()=>{
 const configured=[{id:1,label:'1. shuffle (auto)'},{id:2,label:'2. partition (key)'}];
 assert.equal(stepMotion({id:1040,kind:'fisher_yates',operations:[1]},configured),'fisher_yates');
 assert.equal(stepMotion({id:1040,kind:'resident_sort',operations:[1]},configured),'uniform_sort');
 assert.equal(stepMotion({id:1040,kind:'resident_sort',operations:[1,2]},configured),'fused_sort');
 assert.equal(stepMotion({id:1040,kind:'resident_sort',operations:[2]},configured),'resident_sort');
 assert.equal(stepMotion({id:1040,kind:'spill',operations:[1]},configured),'spill');
 for(const [id,kind] of ['read','write','export','confirm'].entries())assert.equal(stepMotion({id},configured),kind);
});

test('execution labels share readable names and never render unknown identifiers as markup',()=>{
 assert.equal(configuredLabel('3. assign_probabilistic (requested a 100%)'),'3. Assign approximate groups (requested a 100%)');
 assert.equal(operationColor('partition'),'blue');assert.equal(operationColor('constructor'),'slate');
 assert.equal(operationName('<img src=x onerror=alert(1)>'),'Pipeline step');
 assert.equal(statusLabel('in_progress'),'In Progress');assert.equal(statusLabel('handed_off'),'Handed Off');
});
