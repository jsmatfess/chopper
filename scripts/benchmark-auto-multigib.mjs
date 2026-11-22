import {sourcePrefetchBridge,sourcePrefetchStorage} from './browser-source-prefetch-fixture.mjs';
import {asyncDestinationStorage,batchDestinationStorage,compileDestinationWorker,compileAsyncDestinationEngine,compileSynchronousDestinationEngine,disableStreamingOverlap} from './browser-async-destination.mjs';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {cpus, release} from 'node:os';
import {mkdtemp, open, readFile, rm, statfs} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';

const [panel='screen',assetDir='ui/dist',rootArg='scratch/chopper-auto-multigib',baselineDir]=process.argv.slice(2);
const root=resolve(rootArg), gib=2**30, mib=2**20;
const size=await statfs(root,{bigint:true});
assert(size.bavail*size.bsize>=40n*2n**30n,'At least 40 GiB free is required on the fixture volume');
const assets=new Map();
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
for(const name of ['engine.wasm','engine-worker.js','storage-worker.js'])assets.set('/'+name,await readFile(join(assetDir,name)));
if(panel==='streaming-io-production'||panel==='partition-io-production'){
  assert(baselineDir,'A pinned baseline asset directory is required');
  assert.deepEqual(await readFile(join(baselineDir,'engine.wasm')),assets.get('/engine.wasm'));
  for(const name of ['engine-worker.js','storage-worker.js'])assets.set('/baseline/'+name,await readFile(join(baselineDir,name)));
}
const driver=await build({entryPoints:['ui/tests/auto-scale.ts'],bundle:true,format:'esm',write:false});
assets.set('/driver.js',driver.outputFiles[0].contents);
assets.set('/',Buffer.from('<!doctype html><input type="file" id="fixture"><script type="module" src="/driver.js"></script>'));
const partition={type:'partition',columns:[1]};
const shuffle={type:'shuffle',strategy:'uniform'};
const fixtures=new Map();
async function fixture(rows,skewed){
  const name=`fixture-${rows}-${skewed?'skewed':'even'}.csv`;
  if(fixtures.has(name))return fixtures.get(name);
  const input=join(root,panel+'-'+name);
  const file=await open(input,'wx');
  const hash=createHash('sha256');
  const write=async data=>{await file.writeFile(data);hash.update(data);};
  try{
    await write(Buffer.from('id,key,payload\n'));
    const chunk=Buffer.alloc(2048*1024,120);
    for(let base=0;base<rows;base+=2048){
      const count=Math.min(2048,rows-base);
      for(let offset=0;offset<count;offset++){
        const id=base+offset,pos=offset*1024;
        const key=skewed?(id%16===0?1+Math.floor(id/16)%7:0):id%8;
        chunk.write(String(id).padStart(8,'0'),pos,8,'ascii');
        chunk[pos+8]=44;chunk[pos+9]=48+key;chunk[pos+10]=44;chunk[pos+1023]=10;
      }
      await write(chunk.subarray(0,count*1024));
    }
  }finally{await file.close();}
  const result={input,sha256:hash.digest('hex'),bytes:rows*1024+15,rows,skewed};
  fixtures.set(name,result);
  console.log(JSON.stringify({type:'fixture',...result}));
  return result;
}

// WSL/Linux browser-process CPU counters and sampled RSS from this profile.
async function observeResources(context,page) {
  const session=await context.browser().newBrowserCDPSession();
  let previous=new Map(),cpu=0,peakRss=0,samples=0,pending=Promise.resolve(),timer;
  async function sample(initial=false) {
    const {processInfo}=await session.send('SystemInfo.getProcessInfo');
    let rss=0;
    for(const {id,cpuTime} of processInfo){
      if(!initial)cpu+=Math.max(0,cpuTime-(previous.get(id)??0));
      previous.set(id,cpuTime);
      const status=await readFile('/proc/'+id+'/status','utf8').catch(()=>null);
      rss+=Number(status?.match(/^VmRSS:\s+(\d+) kB$/m)?.[1]??0)*1024;
    }
    peakRss=Math.max(peakRss,rss);samples++;
  }
  await page.exposeFunction('scaleObservation',async active=>{
    if(active){
      await sample(true);
      timer=setInterval(()=>{pending=pending.then(()=>sample());pending.catch(()=>{});},500);
      return null;
    }
    clearInterval(timer);
    await pending;
    await sample();
    return {observed_cpu_seconds:cpu,sampled_sum_process_rss_bytes:peakRss,samples};
  });
  return async()=>{clearInterval(timer);await pending.catch(()=>{});await session.detach().catch(()=>{});};
}

const two=2_100_000,four=4_200_000;
const normal={memory_mb:'auto'},analyzed={memory_mb:'auto',profile:true},fixed={memory_mb:2048};
const writeModes=['direct','async','batched','async-batched','async-batched','batched','async','direct'];
const sourceModes=['sync','prefetch','prefetch','sync'].map(source_mode=>({...normal,source_mode}));
const productionModes=['baseline','candidate','candidate','baseline'].map(streaming_io=>({...normal,streaming_io}));
const panels={
  'streaming-io-production':[
    {name:'streaming-io-391-mib',rows:400_000,operations:[],variants:productionModes},
    {name:'streaming-io-977-mib',rows:1_000_000,operations:[],variants:productionModes},
  ],
  'partition-io-production':[
    {name:'partition-io-391-mib',rows:400_000,operations:[partition],variants:productionModes},
    {name:'partition-io-977-mib',rows:1_000_000,operations:[partition],skewed:true,variants:productionModes},
  ],
  'source-prefetch':[
    {name:'streaming-read-holdout',rows:400_000,operations:[],variants:sourceModes},
  ],
  'source-prefetch-controls':[
    {name:'partition-read-holdout',rows:400_000,operations:[partition],variants:sourceModes},
    {name:'larger-streaming-read-holdout',rows:1_000_000,operations:[],variants:sourceModes},
    {name:'prefetch-rejection-fallback',rows:100_000,operations:[],variants:[{...normal,source_mode:'prefetch-error'}]},
  ],
  'destination-overlap':[
    {name:'streaming-write-holdout',rows:400_000,operations:[],
      variants:writeModes.map(write_mode=>({...normal,write_mode}))},
  ],
  'merge-pass':[
    {name:'shuffle-2gib',rows:two,operations:[shuffle],
      variants:[{memory_mb:128},{memory_mb:256},{memory_mb:256},{memory_mb:128}]},
  ],
  repeat:[
    {name:'shuffle-2gib',rows:two,operations:[shuffle],variants:[fixed,normal]},
    {name:'skewed-partition-shuffle-2gib',rows:two,operations:[partition,shuffle],skewed:true,variants:[normal,fixed]},
  ],
  screen:[
    {name:'stream-4gib',rows:four,operations:[],variants:[normal,analyzed]},
    {name:'shuffle-2gib',rows:two,operations:[shuffle],variants:[normal,fixed,analyzed]},
    {name:'skewed-partition-shuffle-2gib',rows:two,operations:[partition,shuffle],skewed:true,variants:[fixed,normal,analyzed]},
  ],
};
assert(panels[panel],'Unknown benchmark panel');
if(panel.startsWith('source-prefetch')||panel==='destination-overlap')
  assets.set('/engine-worker.js',await compileSynchronousDestinationEngine());
if(panel.startsWith('source-prefetch')){
  assets.set('/engine-prefetch.js',await compileDestinationWorker('engine-worker',
    source=>disableStreamingOverlap(source).replace("from './fs'", "from './fs-async-fixture'"),sourcePrefetchBridge));
  assets.set('/storage-prefetch.js',await compileDestinationWorker('storage-worker',sourcePrefetchStorage));
  assets.set('/storage-prefetch-error.js',await compileDestinationWorker('storage-worker',source=>
    'let injectedFailure=false;\n'+sourcePrefetchStorage(source).replace('const data=new Uint8Array(await m.blob.arrayBuffer());',
      'if(!injectedFailure){injectedFailure=true;throw new Error("Injected prefetch read error");}\n'
      +'              const data=new Uint8Array(await m.blob.arrayBuffer());')));
}
if(panel==='destination-overlap'){
  assets.set('/engine-overlap.js',await compileAsyncDestinationEngine());
  assets.set('/storage-overlap.js',await compileDestinationWorker('storage-worker',asyncDestinationStorage));
  assets.set('/storage-batched.js',await compileDestinationWorker('storage-worker',batchDestinationStorage));
  assets.set('/storage-overlap-batched.js',await compileDestinationWorker(
    'storage-worker',source=>asyncDestinationStorage(batchDestinationStorage(source))));
}
const workerHeaders={'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp',
  'Cross-Origin-Resource-Policy':'same-origin'};
const server=createServer((req,res)=>{
  const asset=assets.get(req.url);
  if(!asset){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':req.url.endsWith('.wasm')?'application/wasm':req.url.endsWith('.js')?'text/javascript':'text/html',
    'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cache-Control':'no-store'}).end(asset);
});
let context;
try{
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const hashes=Object.fromEntries([...assets].map(([name,value])=>[name,sha(value)]));
  console.log(JSON.stringify({type:'environment',panel,kernel:release(),cpu:cpus()[0]?.model,hashes,
    driver_sha256:sha(await readFile('ui/tests/auto-scale.ts')),script_sha256:sha(await readFile(new URL(import.meta.url))),
    input:'Playwright disk-backed File',destination:'same-origin OPFS with fresh persistent profiles',clock:'complete job through marker verification and workspace cleanup'}));
  for(const job of panels[panel]){
    const source=await fixture(job.rows,!!job.skewed);
    for(const variant of job.variants){
      const record={type:'run',name:job.name,variant,source_sha256:source.sha256,operations:job.operations};
      const profile=await mkdtemp(join(root,'chromium-'));
      let stopObserving;
      try{
        context=await chromium.launchPersistentContext(profile,{headless:true});
        record.browser=context.browser()?.version();
        const page=context.pages()[0];
        stopObserving=await observeResources(context,page);
        if(variant.streaming_io==='baseline'){
          for(const name of ['engine-worker.js','storage-worker.js'])
            await context.route('**/'+name,route=>route.fulfill({headers:workerHeaders,
              contentType:'text/javascript',body:assets.get('/baseline/'+name)}));
        }
        if(variant.source_mode?.startsWith('prefetch')){
          await context.route('**/engine-worker.js',route=>route.fulfill({headers:workerHeaders,
            contentType:'text/javascript',body:assets.get('/engine-prefetch.js')}));
          await context.route('**/storage-worker.js',route=>route.fulfill({headers:workerHeaders,
            contentType:'text/javascript',body:assets.get(variant.source_mode==='prefetch-error'?'/storage-prefetch-error.js':'/storage-prefetch.js')}));
        }
        if(variant.write_mode&&variant.write_mode!=='direct'){
          const asyncWrite=variant.write_mode.startsWith('async');
          const path=variant.write_mode==='async-batched'?'/storage-overlap-batched.js'
            :asyncWrite?'/storage-overlap.js':'/storage-batched.js';
          if(asyncWrite)await context.route('**/engine-worker.js',route=>route.fulfill({headers:workerHeaders,
            contentType:'text/javascript',body:assets.get('/engine-overlap.js')}));
          await context.route('**/storage-worker.js',route=>route.fulfill({headers:workerHeaders,
            contentType:'text/javascript',body:assets.get(path)}));
        }
        await page.goto('http://127.0.0.1:'+server.address().port);
        await page.waitForFunction(()=>typeof window.scaleRun==='function');
        await page.locator('#fixture').setInputFiles(source.input);
        const quota=await page.evaluate(async()=>navigator.storage.estimate());
        record.initial_quota=quota;
        assert((quota.quota??0)-(quota.usage??0)>=8*gib,'OPFS capacity below the 8 GiB research start floor');
        console.error('Starting',job.name,JSON.stringify(variant));
        const parameters={job:{operations:job.operations,resources:{memory_mb:variant.memory_mb,workers:0},
          limits:{rows:null,bytes:8*mib,compressed_bytes:null}},rows:job.rows,profile:!!variant.profile,skewed:!!job.skewed};
        Object.assign(record,await page.evaluate(parameters=>window.scaleRun(parameters),parameters));
      }catch(error){record.error=String(error);}
      finally{await stopObserving?.();await context?.close();context=undefined;await rm(profile,{recursive:true,force:true});console.log(JSON.stringify(record));}
      if(record.error)throw new Error('Abort after failed run: '+record.error);
    }
  }
}finally{try{await context?.close();}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}}
