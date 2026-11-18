// Fake-only controls: compile test JavaScript, never instantiate WASM or launch a browser.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, mkdtemp, mkdir, writeFile, copyFile, symlink, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import vm from 'node:vm';
import {spawnSync} from 'node:child_process';
import {transform} from '../ui/node_modules/esbuild/lib/main.js';
import {browserEngineAsset, testAssets, assertProductionWasm} from './browser-artifacts.mjs';
const base='engine-resource-tests.wasm', partition='engine-resource-tests-shuffle-partition.wasm';
const feature='experimental-shuffle-partition';

test('Cargo feature forms select distinct resource assets without changing production selection',()=>{
  for(const flags of [['--features',feature],['--features',`other,${feature}`],['--features',`other ${feature}`],
    ['--features','other',feature],['--features=other,'+feature],['--features','other','--features='+feature],
    ['--features','chopper-browser/'+feature],['--features','chopper/'+feature],['--features=chopper/'+feature],['-Fchopper/'+feature],['-F',feature],['-F'+feature],['--all-features']]){
    assert.equal(browserEngineAsset(['--resource-contracts',...flags]),partition,JSON.stringify(flags));
    assert.equal(browserEngineAsset(flags),'engine.wasm');
  }
  for(const flags of [[],['--features','experimental-spill-blocks'],['--features',feature+'-extra'],['--features','unrelated/'+feature],
    ['--target-dir',feature],['--features','other','--target-dir',feature]]){
    assert.equal(browserEngineAsset(['--resource-contracts',...flags]),base);
  }
});

const page=await transform(await readFile(new URL('../ui/tests/resource-contract-tests.ts',import.meta.url),'utf8'),{loader:'ts'});
const workerSource=await readFile(new URL('../ui/tests/resource-contract-worker.ts',import.meta.url),'utf8');
const worker=await transform(workerSource.replace(/^import .*;\n/gm,''),{loader:'ts'});
async function pageWorker(search){
  const urls=[];
  class Worker {
    constructor(url){this.url=url;urls.push(url);}
    postMessage(){if(this.url==='/storage-worker.js')queueMicrotask(()=>this.onmessage({data:{ready:true}}));}
    terminate(){}
  }
  const directory={getDirectoryHandle:async()=>directory};
  vm.runInNewContext(page.code,{window:{},document:{body:{}},location:{search},URLSearchParams,Worker,
    performance,crypto,SharedArrayBuffer,MessageChannel:class {port1={};port2={};},setTimeout:()=>1,clearTimeout(){},
    navigator:{locks:{request:async(_name,callback)=>callback()},storage:{getDirectory:async()=>directory}}});
  await new Promise(resolve=>setImmediate(resolve));
  return urls.find(url=>url.startsWith('/resource-contract-worker.js'));
}
async function workerFetch(search,available){
  let fetched;
  const messages=[];
  const context={location:{search},URLSearchParams,DiskBridge:class {},DiskDirectory:class {contents=new Map();},
    WASI:class {wasiImport={};},MemoryFile:class {path_open(){return {fd_obj:{}};}},ConsoleStdout:{lineBuffered(){}},RootFd:class {},
    fetch(url){fetched=url;return {url};},WebAssembly:{async instantiateStreaming(response){
      throw new Error(available.has(response.url)?'stopped before WASM execution':'missing reactor');
    }},postMessage:value=>messages.push(value)};
  vm.runInNewContext(worker.code,context);
  await context.onmessage({data:{available:1}});
  return {fetched,error:messages.at(-1).error};
}
test('page query reaches worker and selects each immutable reactor',async()=>{
  for(const [search,expected] of [['',base],['?shuffle-partition=1',partition],['?spill-blocks=1',base],['?not-shuffle-partition=1',base]]){
    const url=await pageWorker(search);
    assert.equal(url,'/resource-contract-worker.js'+(expected===partition?'?shuffle-partition=1':''));
    const result=await workerFetch(new URL(url,'http://fixture').search,new Set(['/'+base,'/'+partition]));
    assert.equal(result.fetched,'/'+expected);
    assert.match(result.error,/stopped before WASM execution/);
  }
});
test('missing selected reactor fails without falling back to the other variant',async()=>{
  for(const [search,missing,other] of [['',base,partition],['?shuffle-partition=1',partition,base]]){
    const result=await workerFetch(search,new Set(['/'+other]));
    assert.equal(result.fetched,'/'+missing);
    assert.match(result.error,/missing reactor/);
  }
});
test('unchanged owning assertion rejects wrong or absent candidate reports',async()=>{
  const source=await readFile(new URL('../ui/tests/resource-contract-tests.ts',import.meta.url),'utf8');
  const assertion=source.split('\n').find(line=>line.includes("'Unexpected resource reactor variant'"));
  assert.ok(assertion);
  for(const [candidate,result,passes] of [[false,{},true],[true,{shuffle_partition:{}},true],
    [true,{},false],[true,{shuffle_partition:null},false],[false,{shuffle_partition:{}},false]]){
    const check=()=>vm.runInNewContext(assertion,{candidate,result,assert:(ok,message)=>assert.ok(ok,message)});
    if(passes)check();else assert.throws(check,/Unexpected resource reactor variant/);
  }
});
test('production restore removes both reactors and export guard still rejects a test engine',async()=>{
  assert.ok(testAssets.includes(base)&&testAssets.includes(partition));
  const root=await mkdtemp(join(tmpdir(),'chopper-resource-routing-'));
  try{
    for(const folder of ['scripts','ui/dist','ui/src/browser','docs/releases'])await mkdir(join(root,folder),{recursive:true});
    const noticePath=join(root,'docs/releases/native-usage.txt'),notices='Synthetic dependency notice\n';
    await writeFile(noticePath,notices);
    for(const name of ['build-hosted.mjs','browser-artifacts.mjs','hosted-theme.mjs'])await copyFile(new URL(name,import.meta.url),join(root,'scripts',name));
    await symlink(resolve('ui/node_modules'),join(root,'ui/node_modules'),'dir');
    for(const name of ['app.ts','browser/engine-worker.ts','browser/storage-worker.ts'])await writeFile(join(root,'ui/src',name),'export {};');
    for(const name of ['index.html','style.css'])await writeFile(join(root,'ui',name),'fixture');
    const wasm=Buffer.from([0,97,115,109,1,0,0,0]);
    assertProductionWasm(wasm);
    await writeFile(join(root,'ui/dist/engine.wasm'),wasm);
    for(const name of testAssets)await writeFile(join(root,'ui/dist',name),'fixture');
    const run=spawnSync(process.execPath,[join(root,'scripts/build-hosted.mjs')],{encoding:'utf8'});
    assert.equal(run.status,0,run.stderr);
    assert.deepEqual((await readdir(join(root,'ui/dist'))).sort(),['_headers','app.js','engine-worker.js','engine.wasm','index.html','storage-worker.js','style.css']);
    assert.ok((await readFile(join(root,'ui/dist/index.html'),'utf8')).includes(`<!-- Chopper distribution notices\n${notices}\n-->`));
    await writeFile(noticePath,'Invalid --> notice');
    const invalidNotice=spawnSync(process.execPath,[join(root,'scripts/build-hosted.mjs')],{encoding:'utf8'});
    assert.notEqual(invalidNotice.status,0);assert.match(invalidNotice.stderr,/HTML comment delimiters/);
    await writeFile(noticePath,notices);
    const name=Buffer.from('chopper_resource_contracts');
    const exports=Buffer.concat([Buffer.from([1,name.length]),name,Buffer.from([2,0])]);
    const forbidden=Buffer.concat([wasm,Buffer.from([5,3,1,0,1,7,exports.length]),exports]);
    assert.throws(()=>assertProductionWasm(forbidden),/cannot be shipped/);
    await writeFile(join(root,'ui/dist/engine.wasm'),forbidden);
    const denied=spawnSync(process.execPath,[join(root,'scripts/build-hosted.mjs')],{encoding:'utf8'});
    assert.notEqual(denied.status,0);assert.match(denied.stderr,/cannot be shipped/);
  }finally{await rm(root,{recursive:true,force:true});}
});
