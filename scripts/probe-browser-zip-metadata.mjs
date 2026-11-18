// Public browser profiling compatibility for the exact native ZIP probe bytes.
// No allocation census, throughput or cross-instance memory-bound claim.
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {mkdir,readFile,rm} from 'node:fs/promises';
import {resolve,join,sep,basename} from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import assert from 'node:assert/strict';

const root=process.cwd(),scratchRoot=resolve(root,'scratch'),fixtures=join(scratchRoot,'zip-browser-'+randomUUID());
let browser,server,report;
try{
await mkdir(fixtures,{recursive:true});
const generation=spawnSync(process.env.PYTHON||(process.platform==='win32'?'python':'python3'),['-B','-c',`
import hashlib,importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('probe','scripts/probe-zip-metadata.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=pathlib.Path(sys.argv[1]);manifest=[]
for name,data,description in m.fixtures():
 (root/(name+'.data')).write_bytes(data)
 manifest.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),**description})
(root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
`,fixtures],{encoding:'utf-8'});
if(generation.status!==0)throw new Error(generation.stderr);
const manifest=JSON.parse(await readFile(join(fixtures,'manifest.json'),'utf-8'));
const contents=`import {browserApi as api} from './ui/src/browser/client';
  window.zipMetadataProfile=async(name)=>{
    const bytes=await(await fetch('/zip-probe-'+name+'.data')).arrayBuffer();
    const file=new File([bytes],name+'.data');
    window.showOpenFilePicker=async()=>[{getFile:async()=>file}];window.showDirectoryPicker=async()=>{throw new Error('Profile requested an output directory');};
    const defaults=await api('defaults');
    await api('pick-path',{mode:'input'});
    const job={...defaults,input:file.name,output:'not-published',seed:'zip-metadata-probe-v1',operations:[],resources:{...defaults.resources,memory_mb:32,workers:1,max_record_bytes:1048576,temp_dir:''}};
    await api('profile',job);
    let state;
    const deadline=performance.now()+90000;
    while(performance.now()<deadline){state=await api('state');if(state.status==='profiled'||state.status==='failed')break;await new Promise(resolve=>setTimeout(resolve,10));}
    if(state.status!=='profiled'&&state.status!=='failed')throw new Error('ZIP metadata profile timed out');
    await api('cancel');
    while(performance.now()<deadline){
      const root=await navigator.storage.getDirectory(),workspaces=await root.getDirectoryHandle('chopper-workspaces',{create:true});
      let count=0;for await(const _ of workspaces.entries())count++;
      if(count===0)return {status:state.status,error:state.error,profile:state.profile,workspace_removed:true};
      await new Promise(resolve=>setTimeout(resolve,10));
    }
    throw new Error('ZIP metadata workspace cleanup timed out');
  };`;
const bundle=await build({stdin:{contents,resolveDir:root,loader:'ts'},bundle:true,write:false});
server=spawn(process.execPath,[fileURLToPath(new URL('serve-hosted.mjs',import.meta.url))],{env:{...process.env,PORT:'8424'},stdio:['ignore','pipe','inherit']});
  await new Promise((accept,reject)=>{server.stdout.once('data',accept);server.once('error',reject);server.once('exit',code=>reject(new Error('Server exited '+code)));});
  browser=await chromium.launch();const context=await browser.newContext(),page=await context.newPage();
  await context.route('**/zip-probe-page.html',route=>route.fulfill({contentType:'text/html',headers:{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Content-Security-Policy':"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'"},body:'<!doctype html><title>ZIP metadata compatibility probe</title>'}));
  await context.route('**/zip-probe-helper.js',route=>route.fulfill({contentType:'application/javascript',headers:{'Cross-Origin-Embedder-Policy':'require-corp'},body:bundle.outputFiles[0].text}));
  for(const fixture of manifest){
    const bytes=await readFile(join(fixtures,fixture.name+'.data'));
    assert.equal(createHash('sha256').update(bytes).digest('hex'),fixture.sha256);
    await context.route('**/zip-probe-'+fixture.name+'.data',route=>route.fulfill({contentType:'application/octet-stream',body:bytes}));
  }
  await page.goto('http://127.0.0.1:8424/zip-probe-page.html');
  await page.addScriptTag({url:'http://127.0.0.1:8424/zip-probe-helper.js'});
  const observations=[];
  for(const fixture of manifest){
    const result=await page.evaluate(name=>window.zipMetadataProfile(name),fixture.name);
    if(result.status==='profiled'){
      assert.equal(result.profile.rows,1);assert.equal(result.profile.columns,2);assert.deepEqual(result.profile.header,['id','payload']);
    }
    observations.push({fixture:fixture.name,fixture_sha256:fixture.sha256,...result});
  }
  report={type:'compatibility_diagnostic',scope:'public browser profiling of deterministic ZIP fixtures; not allocation or timing evidence',browserVersion:browser.version(),context:'fresh temporary Chromium context; actual engine worker and OPFS',fixture_generator_sha256:createHash('sha256').update(await readFile('scripts/probe-zip-metadata.py')).digest('hex'),harness_sha256:createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex'),production_wasm_sha256:createHash('sha256').update(await readFile('ui/dist/engine.wasm')).digest('hex'),fixtures:manifest,observations};
}finally{
  server?.kill();
  const target=resolve(fixtures);assert(target.startsWith(scratchRoot+sep)&&basename(target).startsWith('zip-browser-'));
  const cleanup=await Promise.allSettled([browser?.close(),rm(target,{recursive:true,force:true})]);
  for(const result of cleanup)if(result.status==='rejected')throw result.reason;
}
console.log(JSON.stringify({...report,fixture_directory_removed:true},null,2));
