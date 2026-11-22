import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const bundle=await build({stdin:{contents:"export * from './src/browser/stages';export * from './src/browser/physical-history';export * from './src/browser/measurements';export * from './src/result-ownership';export * from './src/browser/publication';",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node'});
const c=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
test('stage finalization is bounded, monotone and separate from attempt completion',()=>{
 const stages=new c.StageCompletions();
 const event=operation=>({kind:'stage_complete',id:1030+operation*32,operations:[operation,0],rows:0,status:'completed',attempt:operation+1});
 for(const stage of [0,2,1,2])stages.accept(event(stage));assert.deepEqual(stages.snapshot(),[0,1,2]);assert.equal(stages.unavailable,false);
 stages.accept({...event(3),status:'active'});assert.equal(stages.unavailable,true);assert.deepEqual(stages.snapshot(),[0,1,2]);
});
test('measurement units and rate denominator are explicit',()=>{
 assert.deepEqual(c.counter('merge',100,0),{unit:'row visits',value:100});assert.deepEqual(c.counter('shared_ranges',100,0),{unit:'frame lengths',value:100});assert.deepEqual(c.counter('gzip_output',0,100),{unit:'bytes',value:100});
 assert.equal(c.averageRate(c.counter('read',100,0),c.workSeconds(2)),50);assert.equal(c.averageRate(c.counter('read',100,0),c.workSeconds(0)),null);
 assert.equal(c.activityDuration(c.timelineSeconds(2),c.timelineSeconds(5)),3);assert.throws(()=>c.workSeconds(NaN));
});
test('result ownership distinguishes input identity, draft revisions and retained values',()=>{
 const job={input:'same.csv',zip_member:null,input_csv:{headers:true},operations:[]};
 const source=c.sourceIdentity(1,job),origin=c.resultOrigin(source,job,4,7),owned=c.ownedResult(origin,{rows:3});
 assert(c.belongsToSource(origin,source));assert(!c.belongsToSource(origin,c.sourceIdentity(2,job)));
 assert(c.belongsToDraft(origin,source,4));assert(!c.belongsToDraft(origin,source,5));
 job.operations.push({type:'shuffle'});assert.equal(JSON.parse(owned.origin.configuration).operations.length,0);assert(Object.isFrozen(origin));
});
test('success requires a receipt for the exact destination',()=>{
 const result={output:'destination/result',publication:{kind:'browser-completion-marker',version:1,folder:'result',files:2,marker:'CHOPPER-COMPLETE.json'}};
 assert.equal(c.verifyPublication(result,'result','destination/result').output,result.output);
 for(const bad of [{output:result.output},{...result,output:'other/result'},{...result,publication:{...result.publication,files:-1}},{...result,publication:{...result.publication,folder:'old'}}])assert.throws(()=>c.verifyPublication(bad,'result','destination/result'),/receipt/);
});

test('measurement APIs reject mixed units at compile time',async()=>{
 const ts=await import('typescript'),{resolve}=await import('node:path');const file=resolve('.measurement-contract.ts').replaceAll('\\','/');
 const source=`import type {StageFact} from './src/browser/physical-history';
 import {ObservationDelivery} from './src/browser/execution-history';
 declare const delivery:ObservationDelivery;declare const stage:StageFact;
 // @ts-expect-error stage finalization is not a physical attempt
 delivery.recordPhysical(stage);
 import {ExecutionTimeline} from './src/browser/execution-timeline';
 declare const timeline:ExecutionTimeline;
 import {averageRate,workSeconds,timelineSeconds,type RowCount,type ByteCount} from './src/browser/measurements';
 timeline.update([],timelineSeconds(1),true);
 // @ts-expect-error work duration is not a timeline coordinate
 timeline.update([],workSeconds(1),true);
 const rows:RowCount={unit:'rows',value:1};averageRate(rows,workSeconds(1));
 // @ts-expect-error timeline coordinates are not inclusive work durations
 averageRate(rows,timelineSeconds(1));
 const bytes:ByteCount={unit:'bytes',value:1};
 // @ts-expect-error byte counts are not row counts
 const wrong:RowCount=bytes;`;
 const options={target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,moduleResolution:ts.ModuleResolutionKind.Bundler,strict:true,noEmit:true,skipLibCheck:true};
 const host=ts.createCompilerHost(options),original=host.getSourceFile.bind(host);
 host.getSourceFile=(path,...args)=>path===file?ts.createSourceFile(file,source,ts.ScriptTarget.ES2022,true):original(path,...args);
 const program=ts.createProgram([file],options,host);const errors=ts.getPreEmitDiagnostics(program);assert.deepEqual(errors.map(error=>ts.flattenDiagnosticMessageText(error.messageText,'\n')),[]);
});

test('engine and browser physical kind ordinals agree, including lifecycle metadata',async()=>{
 const {readFile}=await import('node:fs/promises');const source=await readFile('../crates/chopper/src/observation/physical.rs','utf8');
 const names=[...source.match(/pub enum Kind\s*\{([^}]+)\}/)[1].matchAll(/^\s*([A-Z]\w*)(?:\s*=\s*\d+)?\s*,?\s*$/gm)].map(match=>match[1]).map(name=>name.replace(/[A-Z]/g,(letter,index)=>(index?'_':'')+letter.toLowerCase()));
 assert.deepEqual(names,[...c.kinds,'stage_complete','omitted']);
});
