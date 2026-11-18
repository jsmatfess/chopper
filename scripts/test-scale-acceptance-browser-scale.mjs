// No Playwright import, browser launch or product Run. Synthetic controls only.
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, readFile, mkdir, unlink, link, rename} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {streamIdentity, validateScaleFixture, validateScaleQuota, observeScale, closeScale, main, observationPublisher, admitInitialScaleQuota, observeScaleCapacity, observedSpill} from './scale_acceptance/browser-scale-driver.mjs';
import {validateFixtures, watchQuota} from './scale_acceptance/browser-driver.mjs';
import {installPageAdapter, observeStorageCapacity, installRecoveredExport} from './scale_acceptance/browser-page.mjs';
import {extract, SLICE_BYTES} from './scale_acceptance/browser-export.mjs';
// Always retain failed controls and partial transfers in the caller-owned scratch.
assert(process.argv[2], 'Supply a fresh retained evidence directory below scratch');
const root = resolve(process.argv[2]); await mkdir(root);
let controls = 0;
const outcomes = [];
async function control(name, fn) {
  try {await fn(); outcomes.push({name, status: 'passed'}); controls++;}
  catch (error) {outcomes.push({name, status: 'failed', error: String(error)}); throw error;}
  finally {await writeFile(join(root, 'controls.json'), JSON.stringify({scope: 'synthetic only; acceptance UNRUN', outcomes}, null, 2));}
}
await control('Large G keeps actual completed spill and interrupted quota traversal separate', async () => {
  const step = (kind, id) => ({id, kind, status: 'completed', source_omitted: false,
    outcomes: Object.fromEntries(['completed', 'interrupted', 'failed', 'handed_off'].map(name =>
      [name, {rows: name === 'completed' ? 101 : 0, runs: name === 'completed' ? 2 : 0, attempts: name === 'completed' ? 1 : 0}]))});
  const traversal = step('merge_traversal', 1001);traversal.outcomes.completed.runs = 0;
  const graph = {unavailable: false, eventsOmitted: 0, steps: [step('spill', 1000), traversal]};
  const state = {status: 'complete', error: null, graph};
  assert.equal(observedSpill(state, 101).facts.length, 2);
  const bounded = observedSpill({...state, graph: {...graph, eventsOmitted: 1,
    steps: [{...graph.steps[0], source_omitted: true}, graph.steps[1]]}}, 101);
  assert.equal(bounded.event_details_omitted, 1);assert.deepEqual(bounded.upstream_details_omitted, [1000]);
  for (const bad of [null, {...graph, unavailable: true}, {...graph, truncated: true},
    {...graph, eventsOmitted: -1}, {...graph, steps: [graph.steps[0]]}])
    assert.throws(() => observedSpill({...state, graph: bad}, 101));
  for (const status of ['running', 'failed', 'cancelled']) assert.throws(() => observedSpill({...state, status}, 101));
  assert.throws(() => observedSpill({...state, error: 'engine failed'}, 101));
  for (const change of [{status: 'failed'},
    {outcomes: {...graph.steps[0].outcomes, completed: {rows: 0, runs: 0, attempts: 0}, failed: {rows: 101, runs: 2, attempts: 1}}}])
    assert.throws(() => observedSpill({...state, graph: {...graph, steps: [{...graph.steps[0], ...change}, traversal]}}, 101));
});
await control('actual Chrome G graph retains successful Run and interrupted traversal as recorded', async () => {
  const state = JSON.parse(await readFile(new URL('./fixtures/browser-scale-quota-traversal.json', import.meta.url), 'utf8'));
  const proof = observedSpill(state, 999999);
  const spill = proof.facts.find(step => step.kind === 'spill');
  const traversal = proof.facts.find(step => step.kind === 'merge_traversal');
  assert.deepEqual(spill.outcomes.completed, {rows: 999999, runs: 72, attempts: 72});
  assert.equal(traversal.status, 'interrupted');
  assert.deepEqual(traversal.outcomes.completed, {rows: 0, runs: 0, attempts: 0});
  assert.deepEqual(traversal.outcomes.interrupted, {rows: 999999, runs: 0, attempts: 8});
  const mixed=structuredClone(state), member=mixed.graph.steps.find(step => step.kind === 'merge_traversal');
  member.status='completed';member.outcomes.completed={rows:1,runs:0,attempts:1};member.outcomes.interrupted.rows--;
  observedSpill(mixed,999999);
  member.outcomes.interrupted.rows--;assert.throws(() => observedSpill(mixed,999999));
  member.outcomes.interrupted.attempts=0;assert.throws(() => observedSpill(mixed,999999));
  for (const mutate of [
    x => {x.graph.steps.find(step => step.kind === 'merge_traversal').outcomes.interrupted.rows--;},
    x => {x.graph.steps.find(step => step.kind === 'merge_traversal').outcomes.failed.attempts = 1;},
    x => {delete x.graph.steps.find(step => step.kind === 'merge_traversal').outcomes.interrupted;},
    x => {x.status = 'running';}, x => {x.error = 'failed';},
  ]) {const bad=structuredClone(state);mutate(bad);assert.throws(() => observedSpill(bad, 999999));}
});
await control('completed export reopening is read-only exact-path binding and uses bounded extractor', async () => {
  const output='scale-acceptance-cfe00474-8fb4-479f-8ac8-9e96fcda9652/chopper-results-b7b9f23c-b048-425c-9b5a-6dc1215ed3ea';
  const bytes=new Map([['part-00000001.csv',Buffer.from('id\n1\n')],['manifest.jsonl',Buffer.from('{}\n')],
    ['CHOPPER-COMPLETE.json',Buffer.from(JSON.stringify({complete:true,files:2,engine:'chopper-browser',version:1}))]]);
  const accesses=[];
  const folder={async *entries(){for(const [name,value] of bytes)yield [name,{kind:'file',getFile:async()=>new Blob([value])}];},
    async getFileHandle(name,options){assert.equal(options.create,false);assert(bytes.has(name));return {getFile:async()=>new Blob([bytes.get(name)])};}};
  const parent={async getDirectoryHandle(name,options){assert.equal(options.create,false);assert.equal(name,output.split('/')[1]);accesses.push(name);return folder;}};
  const opfsRoot={async getDirectoryHandle(name,options){assert.equal(options.create,false);assert.equal(name,output.split('/')[0]);accesses.push(name);return parent;}};
  const browser=vm.createContext({window:{scaleAcceptance:{start(){throw Error('Run forbidden');}}},
    navigator:{storage:{getDirectory:async()=>opfsRoot}},TextEncoder,Uint8Array,btoa,Blob});
  const install=async value=>{browser.argument=value;return vm.runInContext('('+installRecoveredExport.toString()+')(argument)',browser);};
  for(const bad of ['../escape',output+'/extra',output.replace('scale-acceptance','other')])await assert.rejects(install(bad));
  assert.equal(accesses.length,0);
  await install(output);assert.equal(browser.window.scaleAcceptance.start,undefined);
  assert.equal(browser.window.scaleAcceptance.cancel,undefined);assert.equal(accesses.length,2);
  const transport={async evaluate(fn,arg){browser.argument=arg;return vm.runInContext('('+fn.toString()+')(argument)',browser);}};
  const exported=await extract(transport,join(root,'recovered-export'),()=>{}, {maxBytes:1024});
  assert.equal(exported.length,3);assert.deepEqual(await readFile(join(root,'recovered-export/part-00000001.csv')),bytes.get('part-00000001.csv'));
  await assert.rejects(browser.window.scaleAcceptance.slice('../foreign',0,1));
  await assert.rejects(browser.window.scaleAcceptance.slice('manifest.jsonl',0,512*1024+1));
});
await control('append observations are bounded, ordered and fail closed on namespace drift', async () => {
  const work=join(root,'observations');await mkdir(work);
  const publish=observationPublisher(work);
  await Promise.all([publish('quota',{epoch:0}),publish('quota',{epoch:1})]);
  assert.deepEqual((await readFile(join(work,'quota.jsonl'),'utf8')).trimEnd().split('\n').map(JSON.parse),[{epoch:0},{epoch:1}]);
  assert.throws(()=>publish('quota',{large:'x'.repeat(1024**2)}),/Quota JSON bound/);
  assert.throws(()=>publish('foreign',{}),/Explicit observation/);
  await publish.stop();assert.throws(()=>publish('quota',{}),/stopped/);
  for (const mode of ['missing','replacement','hardlink','truncation']) {
    const directory=join(root,mode);await mkdir(directory);const write=observationPublisher(directory);
    await write('quota',{epoch:1});const path=join(directory,'quota.jsonl');
    if(mode==='missing')await unlink(path);
    if(mode==='replacement'){await rename(path,path+'.old');await writeFile(path,'{}\n');}
    if(mode==='hardlink')await link(path,path+'.alias');
    if(mode==='truncation')await writeFile(path,'');
    await assert.rejects(write('quota',{epoch:2}));
    await assert.rejects(write.stop());
  }
});
await control('scale counts and tiny ceilings stay separate', async () => {
  for (const [shape, width, rows] of [['D', 100, 9_999_999], ['G', 1000, 999_999]]) {
    const p = {shape, fixture: {width, rows, bytes: 1_000_000_000, sha256: 'synthetic'}};
    const f = {shape, ...p.fixture, tiny: false, runtime: 'browser', generator: 'release-acceptance-v1'};
    validateScaleFixture(f, p);
    for (const mutate of [v => v.rows--, v => v.bytes++, v => v.width++, v => v.tiny = true,
      v => v.runtime = 'native', v => v.shape = shape === 'D' ? 'G' : 'D']) {
      const value = structuredClone(f); mutate(value); assert.throws(() => validateScaleFixture(value, p));
    }
    assert.throws(() => validateFixtures([f, f]));
  }
});
await control('actual streamed hash/count on tiny fixture', async () => {
  const bytes = Buffer.from('id\n1\n2\n'); const path = join(root, 'tiny.csv'); await writeFile(path, bytes);
  assert.deepEqual(await streamIdentity(path), {sha256: createHash('sha256').update(bytes).digest('hex'), rows: 2, bytes: bytes.length});
});
const sample = {sampled_unix: Date.now() / 1000, usable_bytes: 16 * 1024 ** 3, status: 'running', progress: {rows: 1, phase: 'read', temp_bytes: 0}};
await control('quota stale denial no-progress and failure controls', async () => {
  validateScaleQuota(sample, true);
  for (const patch of [{usable_bytes: 0}, {usable_bytes: 2 * 1024 ** 3}, {sampled_unix: 0}, {sampled_unix: Date.now() / 1000 + 11}, {usable_bytes: NaN}])
    assert.throws(() => validateScaleQuota({...sample, ...patch}, true));
  const first = observeScale(sample, null, 0, 0);
  assert(!observeScale({...sample, sampled_unix: Date.now() / 1000}, first.checkpoint, 100, 0).advanced);
  assert.throws(() => observeScale(sample, first.checkpoint, 600000, 0));
  for (const patch of [{error: 'storage denied'}, {status: 'cancelled'}, {status: 'failed'}])
    assert.throws(() => observeScale({...sample, ...patch}, null, 0, 0));
});
await control('initial quota denial retains measured, absent and invalid facts before validation', async () => {
  const names=['navigator','location','isSecureContext','crossOriginIsolated'];
  const saved=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  try {
    for (const estimate of [{quota:1024,usage:24},{usage:0},{quota:NaN,usage:0}]) {
      let requests=0;
      for(const [name,value] of Object.entries({navigator:{storage:{estimate:async()=>estimate,
        persisted:async()=>false,persist:async()=>{requests++;return true;}},
        permissions:{query:async()=>({state:'prompt'})}},location:{origin:'http://127.0.0.1:8431'},
        isSecureContext:true,crossOriginIsolated:true}))
        Object.defineProperty(globalThis,name,{value,configurable:true});
      const observed=await observeStorageCapacity(),receipt={};
      assert.throws(()=>admitInitialScaleQuota(observed,{profile:'fresh-profile',mode:'qualify',origin:location.origin},receipt),/Origin quota denied/);
      assert.deepEqual(receipt.initial_capacity.quota,observed.quota);
      assert.deepEqual(receipt.initial_capacity.usage,observed.usage);
      assert.equal(receipt.initial_capacity.required_usable_bytes,16*1024**3);
      assert.equal(receipt.initial_capacity.profile,'fresh-profile');
      assert.equal(observed.persisted,false);assert.equal(observed.persistence_permission,'prompt');assert.equal(requests,0);
      if(Number.isFinite(estimate.quota)){assert.equal(observed.quota.state,'measured');assert.equal(observed.usable_bytes,800);}
      else {assert.equal(observed.quota.state,estimate.quota===undefined?'absent':'invalid');assert.equal(observed.usable_bytes,0);}
    }
    // Diagnostics must not change the legacy absent-usage fallback contract.
    navigator.storage.estimate=async()=>({quota:40*1024**3});
    const observed=await observeStorageCapacity(),receipt={};
    admitInitialScaleQuota(observed,{profile:'fresh-profile',mode:'qualify',origin:location.origin},receipt);
    assert.equal(observed.usage.state,'absent');assert.equal(observed.usable_bytes,32*1024**3);
  } finally {for(const name of names){const old=saved.get(name);if(old)Object.defineProperty(globalThis,name,old);else delete globalThis[name];}}
});
await control('actual quota uses exact read-only CDP origin and keeps web estimate separate', async () => {
  const packet={origin:'http://127.0.0.1:8431',profile:'fresh-profile',mode:'qualify'};
  const web={sampled_unix:Date.now()/1000,origin:packet.origin,secure_context:true,cross_origin_isolated:true,
    usable_bytes:8*1024**3,quota:{state:'measured',value:10*1024**3},usage:{state:'measured',value:0}};
  const calls=[];let detached=0;
  const raw={quota:40*1024**3,usage:400,overrideActive:false,usageBreakdown:[]};
  const page={evaluate:async fn=>{assert.equal(fn,observeStorageCapacity);return web;}};
  const context={newCDPSession:async selected=>{assert.equal(selected,page);return {
    send:async(method,args)=>{calls.push([method,args]);return raw;},detach:async()=>{detached++;}};}};
  const started=Date.now()/1000;
  const value=await observeScaleCapacity(page,context,packet,packet.profile),receipt={};
  admitInitialScaleQuota(value,packet,receipt);
  assert.deepEqual(calls,[['Storage.getUsageAndQuota',{origin:packet.origin}]]);
  assert.equal(value.web_estimate,web);assert.equal(value.actual_quota,raw);
  assert.equal(value.usable_bytes,Math.floor((raw.quota-400)*.8));
  assert(value.sampled_unix>=started && value.sampled_unix<=Date.now()/1000);assert.equal(detached,1);
  for(const patch of [{quota:NaN},{usage:-1},{quota:0,usage:1},{overrideActive:true},{overrideActive:undefined}]) {
    Object.assign(raw,{quota:40*1024**3,usage:400,overrideActive:false},patch);
    const observed=await observeScaleCapacity(page,context,packet,packet.profile),denied={};
    assert.throws(()=>admitInitialScaleQuota(observed,packet,denied));
    assert.equal(denied.initial_capacity.actual_quota,raw,'Retain denied raw actual quota');
  }
  assert.equal(detached,6);
  let attached=0;
  await assert.rejects(observeScaleCapacity({evaluate:async()=>({...web,origin:'http://foreign'})},
    {newCDPSession:async()=>{attached++;}},packet,packet.profile),/origin binding/);
  assert.equal(attached,0);
});
await control('CDP query and detach failures deny; every created session is detached', async () => {
  const packet={origin:'http://127.0.0.1:8431'},page={evaluate:async()=>({origin:packet.origin,secure_context:true,cross_origin_isolated:true})};
  let detached=0;
  await assert.rejects(observeScaleCapacity(page,{newCDPSession:async()=>({
    send:async()=>{throw Error('query failed');},detach:async()=>{detached++;}})},packet,'profile'),/query failed/);
  assert.equal(detached,1);
  await assert.rejects(observeScaleCapacity(page,{newCDPSession:async()=>({
    send:async()=>({quota:40*1024**3,usage:0,overrideActive:false}),
    detach:async()=>{detached++;throw Error('detach failed');}})},packet,'profile'),/detach failed/);
  assert.equal(detached,2);
  const realNow=Date.now;let clock=0,attached=0;
  try {
    Date.now=()=>clock;
    await assert.rejects(observeScaleCapacity({evaluate:async()=>{clock=30001;return {
      origin:packet.origin,secure_context:true,cross_origin_isolated:true};}},
      {newCDPSession:async()=>{attached++;}},packet,'profile'),/attach deadline/);
    assert.equal(attached,0,'No new query after original deadline');
  } finally {Date.now=realNow;}
});
await control('pending capacity never blocks hot state or restamps completed capacity', async () => {
  const names = ['window','navigator','isSecureContext','crossOriginIsolated','location'];
  const saved = new Map(names.map(name => [name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  let release, calls=0;
  const pending = new Promise(resolve => {release=resolve;});
  try {
    for (const [name,value] of Object.entries({window:{},isSecureContext:true,crossOriginIsolated:true,
      location:{origin:'http://127.0.0.1:8422'},navigator:{storage:{estimate:async()=>{
        calls++;if(calls>1)await pending;return {quota:40*1024**3,usage:0};
      },persisted:async()=>false}}})) Object.defineProperty(globalThis,name,{value,configurable:true});
    installPageAdapter(async()=>({status:'running',progress:{rows:7}}),()=>null);
    const adapter=window.scaleAcceptance;
    const first=await adapter.capacity();
    const second=adapter.capacity();
    assert.equal(adapter.capacity(),second,'Only one origin estimate may be in flight');
    const hot=await adapter.sample(false);
    assert.equal(hot.progress.rows,7);
    assert.equal(hot.sampled_unix,first.sampled_unix,'Hot publication must retain original disk start');
    const began=Date.now()/1000;
    await new Promise(resolve=>setTimeout(resolve,5));
    release();const completed=await second;
    assert(completed.sampled_unix<=began,'Quota timestamp is observation start, not completion');
  }finally{
    release();
    for(const name of names){const value=saved.get(name);if(value)Object.defineProperty(globalThis,name,value);else delete globalThis[name];}
  }
});
await control('sampler stop waits for actual pending capacity completion',async()=>{
  let release,entered;
  const waiting=new Promise(resolve=>{release=resolve;});
  const started=new Promise(resolve=>{entered=resolve;});
  const watcher=watchQuota(async()=>{entered();await waiting;return sample;},async()=>{},1);
  await started;let stopped=false;const completion=watcher.stop().then(()=>{stopped=true;});
  await new Promise(resolve=>setTimeout(resolve,5));assert.equal(stopped,false);
  release();await completion;assert.equal(stopped,true);
});
await control('cleanup independently retains all failures', async () => {
  const calls = [];
  const fail = label => async () => {calls.push(label); throw Error(label + ' denied');};
  const errors = [{phase: 'execution', error: 'primary'}];
  await closeScale({watcher: {stop: fail('sampler')}, page: {isClosed: () => false, evaluate: fail('cancel')},
    context: {close: fail('context')}, browser: {close: fail('browser')}, server: {
      closeAllConnections() {calls.push('server');}, close(fn) {fn(Error('server denied'));}}}, errors);
  assert.deepEqual(calls, ['sampler', 'cancel', 'context', 'browser', 'server']); assert.equal(errors.length, 6);
  await writeFile(join(root, 'cleanup-errors.json'), JSON.stringify(errors, null, 2));
});
await control('standalone launch denied without authority', async () => {
  await assert.rejects(main('/absent', join(root, 'unapproved')), /ENOENT/);
});
await control('bounded streaming export and partial retention', async () => {
  // Synthetic bytes, not a product CSV fixture. Only one 512 KiB slice is produced
  // at a time; neither transport nor writer accumulates the output body.
  const size = SLICE_BYTES * 3 + 7;
  const marker = Buffer.from(JSON.stringify({complete: true, files: 2, engine: 'chopper-browser', version: 1}));
  let pending = 0, maximumPending = 0, slices = 0;
  const transport = mutation => ({async evaluate(fn, args) {
    if (!args) return [{name: 'part-00000001.csv', size}, {name: 'manifest.jsonl', size: 3}, {name: 'CHOPPER-COMPLETE.json', size: marker.length}];
    pending++; maximumPending = Math.max(maximumPending, pending);
    try {
      assert(args.length <= SLICE_BYTES); slices++;
      const bytes = args.name.endsWith('.csv') ? Buffer.alloc(args.length, 120) :
        (args.name === 'manifest.jsonl' ? Buffer.from('{}\n') : marker).subarray(args.offset, args.offset + args.length);
      if (mutation === 'short') return bytes.subarray(1).toString('base64');
      if (mutation === 'extra') return Buffer.concat([bytes, Buffer.from('x')]).toString('base64');
      if (mutation === 'invalid') return '*';
      if (mutation === 'marker' && args.name === 'CHOPPER-COMPLETE.json') return Buffer.alloc(args.length, 120).toString('base64');
      return bytes.toString('base64');
    } finally {pending--;}
  }});
  await extract(transport(), join(root, 'streamed'));
  assert.equal(maximumPending, 1); assert(slices >= 6);
  for (const mutation of ['short', 'extra', 'invalid', 'marker']) {
    await assert.rejects(extract(transport(mutation), join(root, mutation)));
    await readFile(join(root, mutation, 'part-00000001.csv')); // retained even on failure
  }
});
console.log(JSON.stringify({status: 'passed', controls, root, coverage: 'fake/unit only; no browser acceptance'}));
