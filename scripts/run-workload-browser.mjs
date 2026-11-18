// Small persistent-browser baseline. Never mutates ui/dist or uses Prepare.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile,writeFile,mkdir,stat} from 'node:fs/promises';
import http from 'node:http';
import {resolve,join,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {browserChannel,browserLaunchOptions} from './browser-launch.mjs';

assert(process.argv.length===7,'Usage: node scripts/run-workload-browser.mjs JOB OUTPUT RECORD PROFILE BUILD_STATUS');
const [jobPath,output,record,profile,buildStatus]=process.argv.slice(2).map(value=>resolve(value));
const root=fileURLToPath(new URL('../',import.meta.url));
const job=JSON.parse(await readFile(jobPath,'utf8'));
assert((await stat(job.input)).size<=16*1024*1024,'Small baseline fixture exceeds 16 MiB');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
// Dependency/build errors remain explicit prerequisites, not silent substitutions.
const {build}=await import('../ui/node_modules/esbuild/lib/main.js');
const {chromium}=await import('../ui/node_modules/playwright/index.mjs');
const assets=new Map();
for(const name of ['engine.wasm','engine-worker.js','storage-worker.js'])
  assets.set('/'+name,await readFile(join(root,'ui/dist',name)));
const statusBytes=await readFile(buildStatus),status=JSON.parse(statusBytes);
const manifestPath=resolve(buildStatus,'../manifest.json');
const buildManifest=await readFile(manifestPath),buildPlan=JSON.parse(buildManifest);
assert(status.summary.incomplete===0,'Build record is incomplete');
const latest=new Map(status.attempts.map(attempt=>[attempt.id,attempt]));
for(const name of ['engine.wasm','engine-worker.js','storage-worker.js']){
  const matching=[...latest.values()].filter(attempt=>attempt.status==='passed')
    .flatMap(attempt=>Object.entries(attempt.artifacts))
    .filter(([path,identity])=>resolve(buildPlan.root,path)===join(root,'ui/dist',name)&&identity.sha256);
  assert(matching.length&&matching.every(([,identity])=>identity.sha256===sha(assets.get('/'+name))),
    'Hosted asset does not match completed build provenance: '+name);
}
const bundle=await build({entryPoints:[join(root,'ui/tests/workload-baseline.ts')],
  bundle:true,format:'esm',write:false,platform:'browser'});
assets.set('/baseline.js',bundle.outputFiles[0].contents);
assets.set('/',Buffer.from('<!doctype html><input id="fixture" type="file"><script type="module" src="/baseline.js"></script>'));
await mkdir(output); // Require a fresh host output directory; preserve attempts.
await mkdir(profile); // Require a fresh, task-owned persistent profile.
const result={runtime:'browser',status:'running',job_sha256:sha(await readFile(jobPath)),
  input_sha256:sha(await readFile(job.input)),wasm_sha256:sha(assets.get('/engine.wasm')),
  assets_sha256:Object.fromEntries([...assets].map(([name,bytes])=>[name,sha(bytes)])),
  script_sha256:sha(await readFile(fileURLToPath(import.meta.url))),
  driver_sha256:sha(await readFile(join(root,'ui/tests/workload-baseline.ts'))),
  channel:browserChannel,context:'fresh persistent disk-backed profile',cache:'uncontrolled',
  platform:process.platform,node:process.version,profile,job_source:jobPath};
result.build_provenance={status:buildStatus,status_sha256:sha(statusBytes),manifest_sha256:sha(buildManifest)};
await writeFile(record,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
const server=http.createServer((request,response)=>{
  response.setHeader('Cross-Origin-Opener-Policy','same-origin');
  response.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  response.setHeader('Cache-Control','no-store');
  const name=new URL(request.url,'http://localhost').pathname;
  const bytes=assets.get(name);
  if(request.method!=='GET'||!bytes){response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',name.endsWith('.wasm')?'application/wasm':
    name.endsWith('.js')?'application/javascript':'text/html; charset=utf-8');
  response.end(bytes);
});
let browser;
try{
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  browser=await chromium.launchPersistentContext(profile,browserLaunchOptions);
  result.browser_version=browser.browser()?.version();
  const page=await browser.newPage();
  page.setDefaultTimeout(130000);
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(()=>typeof window.workloadBaseline==='function');
  await page.locator('#fixture').setInputFiles(job.input);
  const {files,...measurement}=await page.evaluate(job=>window.workloadBaseline(job),job);
  for(const file of files){
    assert(file.name===basename(file.name)&&!file.name.includes('\\'),'Unsafe result path');
    await writeFile(join(output,file.name),Buffer.from(file.base64,'base64'),{flag:'wx'});
  }
  Object.assign(result,measurement,{status:'complete'});
}catch(error){
  result.status='failed';result.error=String(error);process.exitCode=1;
}finally{
  if(browser)try{await browser.close();}catch(error){
    result.status='failed';result.cleanup_error=String(error);process.exitCode=1;
  }
  await new Promise(ok=>server.close(ok));
  await writeFile(record,JSON.stringify(result,null,2)+'\n');
}
console.log(JSON.stringify(result));
