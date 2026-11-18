// Alternating native/WASI profiling and complete jobs. Warm uncontrolled WSL/OPFS.
// Usage: node scripts/benchmark-profiling-budget.mjs BEFORE BEFORE.wasm [rows=100000] [repeats=3] [--shapes=narrow,many,late_wide] [--workers=1]
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {mkdtemp,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir,cpus,platform,release} from 'node:os';
import {join,resolve} from 'node:path';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const exec=promisify(execFile),before=resolve(process.argv[2]),beforeWasm=await readFile(process.argv[3]);
const rows=Number(process.argv[4]??100000),repeats=Number(process.argv[5]??3);
const workers=Number(process.argv.find(value=>value.startsWith('--workers='))?.slice('--workers='.length)??1);
assert(Number.isSafeInteger(workers)&&workers>=1&&workers<=32);
const shapes=process.argv.find(value=>value.startsWith('--shapes='))?.slice('--shapes='.length).split(',')??['narrow','many','late_wide'];
assert(shapes.length&&shapes.every(value=>['narrow','many','late_wide'].includes(value)));
assert(Number.isSafeInteger(rows)&&rows>=100&&rows<=300000);
assert(Number.isSafeInteger(repeats)&&repeats>0);
const after=resolve('.tools/linux/target/release/chopper'),afterWasm=await readFile('ui/dist/engine.wasm');
const sha=value=>createHash('sha256').update(value).digest('hex');
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
const profileKey=({seconds,cache_hit,...profile})=>canonical(profile);
const outputKey=result=>canonical([result.analysis.rows,result.analysis.logical_digest,result.analysis.stages,result.analysis.output_csv_bytes,result.manifest.trim().split('\n').map(JSON.parse).filter(e=>e.type==='output').map(({path,rows,csv_bytes,lineage})=>({path,rows,csv_bytes,lineage})),result.hashes]);
const root=await mkdtemp(join(tmpdir(),'chopper-profiling-budget-'));
let browser,server;
try{
  await build({entryPoints:['ui/tests/benchmark.ts'],bundle:true,format:'esm',outfile:'ui/dist/benchmark.js'});
  await writeFile('ui/dist/benchmark.html','<!doctype html><script type="module" src="/benchmark.js"></script>');
  server=spawn(process.execPath,['scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8423'},stdio:['ignore','pipe','inherit']});
  await new Promise((ok,fail)=>{server.stdout.once('data',ok);server.once('error',fail);server.once('exit',code=>fail(new Error(`Server exited: ${code}`)));});
  browser=await chromium.launch();const page=await browser.newPage();
  console.log(JSON.stringify({type:'environment',rows,repeats,cpu:cpus()[0]?.model,platform:platform(),release:release(),browser:await browser.version(),cache:'warm, uncontrolled WSL filesystem and browser OPFS; physical SSD I/O unmeasured',workers,browser_workers:1,memory_mb:32,sha256:{before:sha(await readFile(before)),after:sha(await readFile(after)),before_wasm:sha(beforeWasm),after_wasm:sha(afterWasm),script:sha(await readFile(new URL(import.meta.url)))}}));
  for(const shape of shapes){
    const columns=shape==='many'?32:3;
    const records=[['id',...Array.from({length:columns},(_,i)=>`c${i}`)].join(',')];
    for(let i=0;i<rows;i++){
      const fields=[String(i),...Array.from({length:columns},(_,c)=>String((i+c)%10))];
      if(shape==='late_wide'&&i===rows-2)fields[2]='界'.repeat(600000);
      records.push(fields.join(','));
    }
    const csv=records.join('\n')+'\n';
    await writeFile(join(root,'input.csv'),csv);await writeFile('ui/dist/benchmark.csv',csv);
    const config={seed:'profiling-budget-v1',operations:[{type:'balanced',files:2},{type:'partition',columns:['c0']},{type:'shuffle',strategy:'uniform'}],resources:{memory_mb:32,workers,max_record_bytes:2097152},limits:{rows:10000}};
    const browserConfig={...config,resources:{...config.resources,workers:1}};
    const path=join(root,'job.json'),output=join(root,'output');
    await writeFile(path,JSON.stringify({...config,input:join(root,'input.csv'),output,resources:{...config.resources,temp_dir:root}}));
    let referenceProfile,referenceOutput;
    for(let repeat=0;repeat<repeats;repeat++){
      const engines=['native-before','browser-before','native-after','browser-after'];
      for(const engine of repeat%2?engines.reverse():engines){
        console.error(`${shape}/${engine}/${repeat+1}`);
        let fresh,cached,result,cpu,rss;
        if(engine.startsWith('native')){
          const binary=engine.endsWith('before')?before:after;
          const started=performance.now();
          const {stdout}=await exec('/usr/bin/time',['-f','%U %S %M','-o',join(root,'time.txt'),binary,'profile','--config',path],{maxBuffer:8*1024*1024,timeout:300000});
          fresh={profile:JSON.parse(stdout),elapsed_seconds:(performance.now()-started)/1000};
          const [user,system,peak]=(await readFile(join(root,'time.txt'),'utf8')).trim().split(' ').map(Number);cpu=user+system;rss=peak;
          const runStart=performance.now();
          const run=await exec(binary,['run','--config',path,'--yes'],{maxBuffer:8*1024*1024,timeout:300000});
          const elapsed_seconds=(performance.now()-runStart)/1000;
          const hashes={};for(const file of await readdir(output))if(file!=='manifest.jsonl')hashes[file]=sha(await readFile(join(output,file)));
          result={analysis:JSON.parse(run.stdout),manifest:await readFile(join(output,'manifest.jsonl'),'utf8'),hashes,elapsed_seconds};
          await rm(output,{recursive:true});
        }else{
          await writeFile('ui/dist/engine.wasm',engine.endsWith('before')?beforeWasm:afterWasm);
          await page.goto('http://127.0.0.1:8423/benchmark.html');
          await page.waitForFunction(()=>typeof window.benchmarkProfile==='function');
          ({fresh,cached}=await page.evaluate(config=>window.benchmarkProfile(config),browserConfig));
          assert(cached.profile.cache_hit);assert.deepEqual(profileKey(fresh.profile),profileKey(cached.profile));
          result=await page.evaluate(config=>window.benchmark(config),browserConfig);
        }
        assert(!fresh.profile.cache_hit);assert.equal(fresh.profile.rows,rows);
        const actualProfile=profileKey(fresh.profile),actualOutput=outputKey(result);
        referenceProfile??=actualProfile;referenceOutput??=actualOutput;
        assert.deepEqual(actualProfile,referenceProfile);assert.deepEqual(actualOutput,referenceOutput);
        console.log(JSON.stringify({type:'measurement',shape,engine,repeat:repeat+1,verified:true,profile_seconds:fresh.elapsed_seconds,scan_seconds:fresh.profile.seconds,cache_seconds:cached?.elapsed_seconds,profile_cpu_seconds:cpu,profile_peak_rss_kib:rss,job_seconds:result.elapsed_seconds,profile_sha256:sha(JSON.stringify(actualProfile)),output_sha256:sha(JSON.stringify(actualOutput)),diagnostics:result.analysis.diagnostics}));
      }
    }
  }
}finally{
  await browser?.close();server?.kill();await writeFile('ui/dist/engine.wasm',afterWasm);
  await rm(root,{recursive:true,force:true});
  for(const file of ['benchmark.csv','benchmark.js','benchmark.html'])await rm('ui/dist/'+file,{force:true});
}
