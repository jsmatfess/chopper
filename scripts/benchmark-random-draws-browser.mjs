// Complete WASI prepare/confirmation/export comparisons using the existing bounded driver.
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {readFile,writeFile,mkdir,copyFile,rm} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import http from 'node:http';
import assert from 'node:assert/strict';
const [baseline,candidate,output,nativeFixtures]=process.argv.slice(2).map(p=>resolve(p));
assert(output&&nativeFixtures,'BASELINE.wasm CANDIDATE.wasm OUTPUT NATIVE_FIXTURES required');
await mkdir(output);const assets=join(output,'assets');await mkdir(assets);
await build({entryPoints:['ui/tests/benchmark-swarm.ts'],bundle:true,format:'iife',define:{__HOSTED__:'true'},outfile:join(assets,'driver.js')});
await build({entryPoints:['ui/src/browser/engine-worker.ts','ui/src/browser/storage-worker.ts'],bundle:true,format:'esm',outdir:assets});
await copyFile(baseline,join(assets,'baseline.wasm'));await copyFile(candidate,join(assets,'candidate.wasm'));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const save=async(path,value)=>writeFile(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});
let active='baseline',fixture;const types={js:'application/javascript',wasm:'application/wasm',csv:'text/csv'};
const server=http.createServer(async(req,res)=>{
 res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cache-Control','no-store');
 try{const name=new URL(req.url,'http://localhost').pathname.slice(1);
  if(!name){res.setHeader('Content-Type','text/html');res.end('<!doctype html><script src="/driver.js"></script>');return;}
  assert(['engine.wasm','engine-worker.js','storage-worker.js','driver.js','input.csv'].includes(name));
  const path=name==='engine.wasm'?join(assets,active+'.wasm'):name==='input.csv'?fixture:join(assets,name);
  res.setHeader('Content-Type',types[name.split('.').at(-1)]);res.end(await readFile(path));
 }catch(e){res.statusCode=404;res.end(String(e));}
});
let browser;const reports=[];
try{
 await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
 browser=await chromium.launchPersistentContext(join(output,'profile'),{headless:true});
 const page=await browser.newPage();page.on('pageerror',e=>console.error(e));
 await save(join(output,'environment.json'),{browser:browser.browser().version(),context:'persistent disposable bundled Chromium, warm uncontrolled OPFS',clock:'prepare through confirmation, export, completion marker and worker retirement; collection/verification outside clock',harness_sha256:sha(await readFile(new URL(import.meta.url))),assets:Object.fromEntries(await Promise.all(['driver.js','engine-worker.js','storage-worker.js','baseline.wasm','candidate.wasm'].map(async n=>[n,sha(await readFile(join(assets,n)))])))});
 const selected=(process.argv[6]??'fy-fit,exact-draws,uniform-spill').split(',');
 assert(selected.every(name=>['fy-fit','exact-draws','uniform-spill','probability-control'].includes(name)));
 for(const name of selected){
  const cell=join(output,name);await mkdir(cell);fixture=join(nativeFixtures,name,'input.csv');
  const {recipe}=JSON.parse(await readFile(join(nativeFixtures,name,'fixture.json'),'utf8'));
  const config={operations:recipe.operations,resources:{memory_mb:recipe.memory_mb,workers:1,max_record_bytes:1048576},limits:{rows:10000,bytes:4194304,compressed_bytes:null}};
  const samples={baseline:[],candidate:[]};
  for(let repeat=-1;repeat<3;repeat++)for(const variant of repeat%2===0?['baseline','candidate']:['candidate','baseline']){
   active=variant;const attempt=join(cell,`${repeat+1}-${variant}`);await mkdir(attempt);
   await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForFunction(()=>typeof window.swarmRun==='function');
   try{
    const result=await page.evaluate(config=>window.swarmRun(config,120),config);await save(join(attempt,'result.json'),result);
    const destination=join(attempt,'results');await mkdir(destination);
    for(const file of result.files){assert(/^[a-zA-Z0-9_.-]+$/.test(file.name));if(file.name==='CHOPPER-COMPLETE.json')continue;
     const chunks=[];for(let offset=0;offset<file.size;offset+=1048576)chunks.push(Buffer.from(await page.evaluate(({name,offset})=>window.swarmCollect(name,offset),{name:file.name,offset}),'base64'));
     await writeFile(join(destination,file.name),Buffer.concat(chunks),{flag:'wx'});
    }
    await save(join(attempt,'recipe.json'),recipe);
    execFileSync('python3',['-c',`import importlib.util,json,pathlib; s=importlib.util.spec_from_file_location('v','scripts/verify-shuffle-swarm.py'); v=importlib.util.module_from_spec(s);s.loader.exec_module(v); p=pathlib.Path(${JSON.stringify(attempt)});r=json.load(open(p/'result.json')); m=json.loads((p/'results/manifest.jsonl').read_text().splitlines()[0]); a=dict(r['analysis']); assert a['warnings']==m['analysis']['warnings']+['Browser export is not atomic. A valid CHOPPER-COMPLETE.json record marks successful completion. Keep this tab open until saving finishes.']; a['warnings']=m['analysis']['warnings']; j=dict(r['submitted']); j.pop('seed',None) if j.get('seed') is None else None; assert j['input']=='input.csv' and j['output']=='results' and j['resources']['temp_dir'] is None; j['input']='/input.csv'; j['output']='/results'; j['resources']={**j['resources'],'temp_dir':'/tmp'}; n=importlib.util.spec_from_file_location('n','scripts/benchmark-random-draws.py'); native=importlib.util.module_from_spec(n); n.loader.exec_module(native); x=native.check(json.load(open(p/'recipe.json')),p/'results',a,j);json.dump(x,open(p/'verification.json','x'))`],{cwd:process.cwd(),stdio:'pipe'});
    const cleanup=await page.evaluate(()=>window.swarmCleanup());await save(join(attempt,'cleanup.json'),cleanup);await rm(destination,{recursive:true});
    if(repeat>=0)samples[variant].push({seconds:result.elapsed_seconds,attempt});
    console.log(JSON.stringify({name,variant,repeat,seconds:result.elapsed_seconds}));
   }catch(error){await save(join(attempt,'failure.json'),{error:String(error),stack:error.stack});throw error;}
  }
  const stats=Object.fromEntries(Object.entries(samples).map(([variant,values])=>{const times=values.map(s=>s.seconds).sort((a,b)=>a-b);return [variant,{median:times[1],minimum:times[0],maximum:times.at(-1)}];}));
  reports.push({name,recipe,samples,stats,reduction_percent:100*(1-stats.candidate.median/stats.baseline.median)});
 }
 await save(join(output,'summary.json'),reports);
}finally{if(browser)await browser.close();server.closeAllConnections();await new Promise(ok=>server.close(ok));}
