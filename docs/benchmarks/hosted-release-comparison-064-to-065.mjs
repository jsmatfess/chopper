// Matched complete hosted Run using the shipped workers and benchmark-swarm driver.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createReadStream, createWriteStream, readlinkSync, statSync} from 'node:fs';
import {appendFile, mkdir, open, readFile, rm, writeFile} from 'node:fs/promises';
import http from 'node:http';
import {availableParallelism, release, totalmem} from 'node:os';
import {join, resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {pipeline} from 'node:stream/promises';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath, pathToFileURL} from 'node:url';

const planPath = resolve(process.argv[2]);
const {baseline, candidate, out, cases, verifier} = JSON.parse(await readFile(planPath));
const root = process.cwd();
const {build, stop} = await import(pathToFileURL(join(root,'ui/node_modules/esbuild/lib/main.js')));
const {chromium} = await import(pathToFileURL(join(root,'ui/node_modules/playwright/index.mjs')));
const assetDirs = [resolve(baseline,'..'), resolve(candidate,'..')];
const evidence = join(out,'samples.jsonl');
const sha = async path => {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest('hex');
};
const note = async value => {
  const text = JSON.stringify(value);
  await appendFile(evidence, text+'\n');
  console.log(text.slice(0, 400));
};
await mkdir(out);
const driverPath = 'ui/tests/benchmark-swarm.ts';
let driver = await readFile(driverPath, 'utf8');
const inputLoader = "const input = new File([await response.arrayBuffer()], 'input.csv');";
assert.ok(driver.includes(inputLoader));
driver = driver.replace(inputLoader, `const inputHandle = await destination.getFileHandle('input.csv', {create:true});
    await response.body!.pipeTo(await inputHandle.createWritable());
    const input = await inputHandle.getFile();`);
const ownerCheck = 'diagnostics.workspace_reserved_bytes === owners.reduce';
assert.ok(driver.includes(ownerCheck));
driver = driver.replace(ownerCheck, "diagnostics.workspace_reserved_bytes === Number((done.analysis as any).auto_plan.physical_plan === 'private_terminal') * (8192 + '/results'.length) + owners.reduce");
await build({stdin:{contents:driver,resolveDir:resolve('ui/tests'),loader:'ts'},
  bundle:true,format:'iife',define:{__HOSTED__:'true'},outfile:join(out,'driver.js')});
await stop();
let activeEngine, fixture, collection;
const html = `<!doctype html><script>
window.finalObservation = null;
const NativeWorker = Worker;
window.Worker = class extends NativeWorker {
 constructor(...args){
  super(...args);
  this.addEventListener('message',({data})=>{
   if(data.observationFinal)window.finalObservation=data.observationFinal;
  });
 }
}
</script><main class="editor"></main><script src="/driver.js"></script>`;
const server = http.createServer(async (req,res) => {
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('Cache-Control','no-store');
  try {
    if (req.url === '/') {res.setHeader('Content-Type','text/html');res.end(html);return;}
    if (req.method === 'POST') {
      const match = /^\/out\/([a-zA-Z0-9_.-]+)$/.exec(req.url);
      assert.ok(collection && match && !['.','..'].includes(match[1]));
      await pipeline(req,createWriteStream(join(collection,match[1]),{flags:'wx'}));
      res.end('collected');return;
    }
    const paths = {
      '/engine.wasm':['application/wasm',activeEngine],'/input.csv':['text/csv',fixture],
      '/driver.js':['application/javascript',join(out,'driver.js')],
      '/engine-worker.js':['application/javascript',join(resolve(activeEngine,'..'),'engine-worker.js')],
      '/storage-worker.js':['application/javascript',join(resolve(activeEngine,'..'),'storage-worker.js')],
    };
    assert.ok(Object.hasOwn(paths,req.url));
    const [type,path] = paths[req.url];
    res.setHeader('Content-Length',statSync(path).size);
    res.setHeader('Content-Type',type);
    await pipeline(createReadStream(path),res);
  } catch (error) {
    if (!res.headersSent) {res.statusCode=500;res.end(String(error));}
    else res.destroy(error);
  }
});
const generate = async (path, recipe) => {
  const file = await open(path,'wx');
  const payloads = recipe.widths.map(width => Array.from({length:26}, (_,i) => String.fromCharCode(97+i).repeat(width)));
  let chunk = 'id,key,payload\n';
  try {
    for (let id=0; id<recipe.rows; id++) {
      const key = recipe.skewEvery ? (id % recipe.skewEvery ? 0 : 1 + Math.floor(id / recipe.skewEvery) % (recipe.keys - 1)) : id % recipe.keys;
      chunk += `${id},g${String(key).padStart(4,'0')},${payloads[id % payloads.length][id % 26]}\n`;
      if (chunk.length >= 1048576) {await file.write(chunk);chunk='';}
    }
    if (chunk) await file.write(chunk);
    await file.sync();
  } finally {await file.close();}
};
let context;
let executable;
try {
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  const addr = 'http://127.0.0.1:'+server.address().port;
  for (const recipe of cases) {
    const cell = join(out,recipe.id);
    await mkdir(cell);
    fixture=join(cell,'input.csv');
    await generate(fixture,recipe);
    const recipePath=join(cell,'recipe.json');
    await writeFile(recipePath,JSON.stringify(recipe));
    await note({kind:'fixture',recipe,sha256:await sha(fixture),bytes:statSync(fixture).size});
    context=await chromium.launchPersistentContext(join(cell,'profile'),{headless:true,args:['--no-zygote','--disable-breakpad','--disable-crash-reporter']});
    const browser=context.browser();
    const page=context.pages()[0]??await context.newPage();
    if(!executable){
      const cdp=await browser.newBrowserCDPSession();
      const pid=(await cdp.send('SystemInfo.getProcessInfo')).processInfo.find(p=>p.type==='browser').id;
      const path=readlinkSync('/proc/'+pid+'/exe');
      executable={path,sha256:await sha(path),version:browser.version()};
      await cdp.detach();
      const inputs=[baseline,candidate,planPath,fileURLToPath(import.meta.url),driverPath,join(out,'driver.js'),
        ...assetDirs.flatMap(dir=>['engine-worker.js','storage-worker.js'].map(name=>join(dir,name))),verifier];
      await note({kind:'context',executable,os:release(),cpus:availableParallelism(),memory_bytes:totalmem(),
        node:process.version,time_scope:'Run request through completion marker and worker retirement, excludes independent export copy/verification',
        storage:'persistent disposable bundled Chromium profile per cell; input copied to OPFS outside Run timer; warm uncontrolled WSL2 caches',
        inputs:Object.fromEntries(await Promise.all(inputs.map(async p=>[p,await sha(p)])))});
    }
    page.on('pageerror',error=>console.error(error));
    for(let pair=-1; pair<recipe.pairs; pair++){
      for(const variant of pair%2===0 ? ['baseline','candidate'] : ['candidate','baseline']){
        activeEngine = variant==='baseline'?baseline:candidate;
        const attempt=join(cell,`${pair+1}-${variant}`);
        await mkdir(attempt);
        await page.goto(addr);
        await page.waitForFunction(()=>typeof window.swarmRun==='function');
        const config={
          operations:recipe.operations,calculated_columns:[],
          compression:'none',limits:{rows:null,bytes:recipe.byteCap,compressed_bytes:null},
          resources:{memory_mb:recipe.memory,workers:1,max_record_bytes:1048576,grouping:recipe.grouping??'auto'},
        };
        try {
          const result=await page.evaluate(config=>window.swarmRun(config,150),config);
          const observation=await page.evaluate(()=>window.finalObservation);
          assert.equal(observation?.marker?.status,'completed');
          assert.equal(observation.export.status,'completed');
          assert.equal(observation.unavailable,false);
          assert.deepEqual(observation.completedStages,Array.from({length:config.operations.length+2},(_,i)=>i));
          const {physical_plan,measurements,effective_memory_bytes,memory_plan}=result.analysis.auto_plan;
          assert.equal(physical_plan,recipe.route?.[variant]??'snapshot');
          assert.equal(Boolean(result.diagnostics.execute.source_prefetch_request?.calls), variant==='candidate' && Boolean(recipe.prefetch));
          if (recipe.id.startsWith('nested-balanced')) {
            const traversal=observation.physical.filter(step=>step.kind==='balanced_traversal');
            assert.equal(traversal.length,1);
            const fused=variant==='candidate' && recipe.fused;
            assert.deepEqual(traversal[0].operations,fused?[1,2]:[2]);
            assert.equal(traversal[0].rows,recipe.rows);
            assert.equal(observation.physical.some(step=>step.kind==='shared_ranges'),!fused);
          }
          const resultPath=join(attempt,'result.json');
          await writeFile(resultPath,JSON.stringify({ ...result, observation },null,2));
          collection=join(attempt,'export');
          await mkdir(collection);
          for (const file of result.files) {
            await page.evaluate(async ({owned,folder,name})=>{
              const parent=await(await navigator.storage.getDirectory()).getDirectoryHandle(owned);
              const dir=await parent.getDirectoryHandle(folder);
              const file=await(await dir.getFileHandle(name)).getFile();
              const response=await fetch('/out/'+name,{method:'POST',body:file});
              if (!response.ok) throw Error('Collection failed: '+await response.text());
            },{owned:result.owned_destination,folder:result.output.split('/').at(-1),name:file.name});
          }
          const verify=spawnSync('python3',[verifier,recipePath,resultPath,collection],{encoding:'utf8'});
          if (verify.status!==0) throw Error(String(verify.error??verify.stderr));
          const verification=JSON.parse(verify.stdout);
          const cleanup=await page.evaluate(()=>window.swarmCleanup());
          await note({kind:'measurement',cell:recipe.id,pair,variant,seconds:result.elapsed_seconds,verification,cleanup,
            resources:result.analysis.diagnostics,peak_temp_bytes:result.analysis.peak_temp_bytes,storage:result.diagnostics.storage,
            physical_plan,measurements,effective_memory_bytes,memory_plan,bridge:result.diagnostics.execute,
            stages:result.analysis.stages,physical:observation.physical,marker:observation.marker});
          await rm(collection,{recursive:true});
        } catch(error) {
          const details=await page.evaluate(async()=>({...await window.swarmFailure(), observation:window.finalObservation})).catch(()=>null);
          await note({kind:'failure',cell:recipe.id,pair,variant,error:String(error),stack:error.stack,details});
          throw error;
        }
        await delay(100);
      }
    }
    await context.close();
    context=null;
  }
} finally {
  if (context) await context.close();
  server.closeAllConnections();
  await new Promise(ok=>server.close(ok));
}
