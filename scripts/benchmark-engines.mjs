// Build hosted engine first. This harness is temporary and must never ship in production.
// Optional --interleave-cases after [BASELINE.wasm] alternates selected cases and
// reverses them each repetition; use it for explicit resident algorithm comparisons.
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {mkdtemp,writeFile,readFile,readdir,rm} from 'node:fs/promises';
import {tmpdir,cpus,totalmem} from 'node:os';
import {join,resolve} from 'node:path';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
const exec=promisify(execFile),binary=resolve(process.argv[2]||'.tools/linux/target/release/chopper');
const rows=Number(process.argv[3]||100000),repeats=Number(process.argv[4]||3);
const selectedCases=process.argv[5]?.split(',');
if(selectedCases?.some(name=>name.startsWith('flex_reverse_')))throw new Error('Removed partition-first experiment cases; use the preserved historical harness and pinned build for historical replay');
const payload=Number(process.argv[6]??128);
// Optional baseline WASM adds alternating browser A/B runs of the same fixture.
const interleaveCases=process.argv.slice(7).includes('--interleave-cases');
const beforePath=process.argv[7]?.startsWith('--')?null:process.argv[7];
const outputEncoding=process.argv.find(value=>value.startsWith('--output-encoding='))?.slice('--output-encoding='.length)||'utf-8';
const outputBom=process.argv.includes('--output-bom');
const extraColumns=Number(process.argv.find(value=>value.startsWith('--extra-columns='))?.slice('--extra-columns='.length)||0);
const reloadBrowser=process.argv.includes('--reload-browser');
const persistentBrowser=process.argv.includes('--persistent-browser');
const fixturePath=process.argv.find(value=>value.startsWith('--fixture='))?.slice('--fixture='.length);
const partitionColumn=process.argv.find(value=>value.startsWith('--partition-column='))?.slice('--partition-column='.length)||'country';
const seed=process.argv.find(value=>value.startsWith('--seed='))?.slice('--seed='.length)||'benchmark-1';
const maxRecordBytes=Number(process.argv.find(value=>value.startsWith('--max-record-bytes='))?.slice('--max-record-bytes='.length)||1048576);
if(process.argv.includes('--require-bucket-fallback'))throw new Error('Removed independent bucket experiment');
const outputCsv={encoding:outputEncoding,headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:outputBom,skip_empty_lines:false};
const nativeBeforePath=process.argv.find(value=>value.startsWith('--native-before='))?.slice('--native-before='.length);
const beforeWasm=beforePath?await readFile(beforePath):null;
const afterWasm=beforeWasm?await readFile('ui/dist/engine.wasm'):null;
if(!Number.isSafeInteger(payload)||payload<0||payload>8192||rows*(payload+32+2*extraColumns)>160*1024*1024)throw new Error('Payload must be 0–8192 bytes and fixture estimate at most 160 MiB');
if(!Number.isSafeInteger(extraColumns)||extraColumns<0||extraColumns>128)throw new Error('Use 0–128 extra columns');
if(!Number.isSafeInteger(rows)||rows<100||rows>2000000||!Number.isSafeInteger(repeats)||repeats<1)throw new Error('Use 100–2000000 rows and positive repeats');
const root=await mkdtemp(join(tmpdir(),'chopper-engine-bench-'));
let browser,server;
const files=['benchmark.csv','benchmark.js','benchmark.html'];
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])):value;
const outputMetadata=manifest=>manifest.trim().split('\n').map(JSON.parse).filter(e=>e.type==='output').map(({path,rows,csv_bytes,lineage})=>({path,rows,csv_bytes,lineage}));
try{
  if(fixturePath)await writeFile(join(root,'input.csv'),await readFile(resolve(fixturePath)));
  else await exec(resolve('.tools/linux/target/release/examples/generate'),[join(root,'input.csv'),String(rows),String(payload),String(extraColumns)]);
  const sourceBytes=await readFile(join(root,'input.csv'));
  const sourceRecords=sourceBytes.toString('utf8').trimEnd().split('\n');
  assert(sourceBytes.length<=160*1024*1024&&sourceRecords.length===rows+1,'fixture size/row bounds');
  assert(Number.isSafeInteger(maxRecordBytes)&&maxRecordBytes>0);
  await writeFile('ui/dist/benchmark.csv',sourceBytes);
  await build({entryPoints:['ui/tests/benchmark.ts'],bundle:true,format:'esm',outfile:'ui/dist/benchmark.js'});
  await writeFile('ui/dist/benchmark.html','<!doctype html><script type="module" src="/benchmark.js"></script>');
  server=spawn(process.execPath,['scripts/serve-hosted.mjs'],{env:{...process.env,PORT:'8423'},stdio:['ignore','pipe','inherit']});
  await new Promise((ok,fail)=>{server.stdout.once('data',ok);server.once('error',fail);server.once('exit',code=>fail(new Error(`Benchmark server exited: ${code}`)));});
  browser=persistentBrowser?await chromium.launchPersistentContext(join(root,'browser-profile')):await chromium.launch();const page=await browser.newPage();
  await page.goto('http://127.0.0.1:8423/benchmark.html');await page.waitForFunction(()=>typeof window.benchmark==='function');
  console.log(JSON.stringify({event:'environment',rows,payload_bytes:payload,extra_columns:extraColumns,input_sha256:createHash('sha256').update(sourceBytes).digest('hex'),custom_fixture:!!fixturePath,partition_column:partitionColumn,seed,max_record_bytes:maxRecordBytes,reload_browser:reloadBrowser,engine_worker_sha256:createHash('sha256').update(await readFile('ui/dist/engine-worker.js')).digest('hex'),storage_worker_sha256:createHash('sha256').update(await readFile('ui/dist/storage-worker.js')).digest('hex'),benchmark_bundle_sha256:createHash('sha256').update(await readFile('ui/dist/benchmark.js')).digest('hex'),generator_sha256:createHash('sha256').update(await readFile(resolve('.tools/linux/target/release/examples/generate'))).digest('hex'),browser_session:persistentBrowser?'temporary persistent disk profile':'private',repeats,case_order:interleaveCases?'interleaved, reversed each repetition':'case-by-case',output_encoding:outputEncoding,output_bom:outputBom,binary_sha256:createHash('sha256').update(await readFile(binary)).digest('hex'),native_before_sha256:nativeBeforePath?createHash('sha256').update(await readFile(nativeBeforePath)).digest('hex'):null,script_sha256:createHash('sha256').update(await readFile(new URL(import.meta.url))).digest('hex'),browser:browser.version?await browser.version():browser.browser().version(),platform:process.platform,architecture:process.arch,cpu:cpus()[0]?.model,logical_cpus:cpus().length,memory_bytes:totalmem(),wasm_sha256:beforeWasm?{before:createHash('sha256').update(beforeWasm).digest('hex'),after:createHash('sha256').update(afterWasm).digest('hex')}:createHash('sha256').update(await readFile('ui/dist/engine.wasm')).digest('hex'),note:'Warm cache; browser export to OPFS test destination; native export to local filesystem. Browser clock spans analyze (including WASM restart) through complete/publication; fixture preparation, initial defaults startup, verification and benchmark-owned output removal excluded. Native clock includes CLI startup/exit.'}));
  const residentCases=['uniform256','fisher256','grouped_uniform256','grouped_fisher256'];
  const allocationGroups=[{name:'small',percent:'17'},{name:'named zero',percent:'0'},{name:'middle',percent:'33'},{name:'large',percent:'50'}];
  const allocation={type:'assign',groups:allocationGroups,strata:[]};
  const cases=[
    ['flex_auto_downstream',[{type:'shuffle',strategy:'auto'},{type:'balanced',files:4}],32,'none'],
    ['flex_allocate_auto',[{type:'shuffle',strategy:'auto'},allocation],32,'none'],
    ['flex_allocate_uniform',[{type:'shuffle',strategy:'uniform'},allocation],32,'none'],
    ['flex_allocate_fisher',[{type:'shuffle',strategy:'fisher_yates'},allocation],256,'none'],
    ['flex_allocate_parents',[{type:'partition',columns:['country']},{type:'shuffle',strategy:'auto'},allocation],32,'none'],
    ['flex_allocate_downstream',[{type:'shuffle',strategy:'auto'},allocation,{type:'assign',groups:[{name:'left',percent:'50'},{name:'right',percent:'50'}],strata:[]}],32,'none'],
    ['flex_allocate_stratified',[{type:'shuffle',strategy:'auto'},{...allocation,strata:['country']}],32,'none'],
    ['flex_allocate_barrier',[{type:'shuffle',strategy:'auto'},{type:'balanced',files:2},allocation],32,'none'],
    ['flex_uniform256',[{type:'shuffle',strategy:'uniform'}],256,'none'],
    ['flex_auto256',[{type:'shuffle',strategy:'auto'}],256,'none'],
    ['flex_uniform32',[{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['flex_auto32',[{type:'shuffle',strategy:'auto'}],32,'none'],
    ['flex_partition_uniform',[{type:'partition',columns:['country']},{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['flex_partition_auto',[{type:'partition',columns:['country']},{type:'shuffle',strategy:'auto'}],32,'none'],
    ['rows',[],32,'none'],['uniform32',[{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['uniform256',[{type:'shuffle',strategy:'uniform'}],256,'none'],
    ['fisher256',[{type:'shuffle',strategy:'fisher_yates'}],256,'none'],
    ['grouped_uniform256',[{type:'balanced',files:4},{type:'shuffle',strategy:'uniform'}],256,'none'],
    ['grouped_fisher256',[{type:'balanced',files:4},{type:'shuffle',strategy:'fisher_yates'}],256,'none'],
    ['balanced_partition',[{type:'balanced',files:4},{type:'partition',columns:['country']}],32,'none'],
    ['balanced_probabilistic_shuffle',[{type:'balanced',files:2},{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['country']},{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['balanced_probabilistic_sort',[{type:'balanced',files:2},{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['country']},{type:'shuffle',strategy:'uniform'}],32,'none','sort'],
    ['balanced_interleaved_shuffle',[{type:'balanced',files:2},{type:'interleaved',files:3},{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['partition',[{type:'partition',columns:['country']}],256,'none'],
    ['partition_shuffle',[{type:'partition',columns:['country']},{type:'shuffle',strategy:'uniform'}],256,'none'],
    ['assign_shuffle',[{type:'assign',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}]},{type:'shuffle',strategy:'uniform'}],256,'none'],
    ['stratified_assign_shuffle',[{type:'assign',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['country']},{type:'shuffle',strategy:'uniform'}],32,'none'],
    ['gzip',[{type:'shuffle',strategy:'uniform'}],32,'gzip']].filter(([name])=>
      selectedCases?selectedCases.includes(name):!residentCases.slice(1).includes(name));
  // Optional resident comparisons alternate algorithms as well as engines.
  // Historical runs keep their case-by-case order unless explicitly requested.
  const work=[];
  if(interleaveCases){
    for(let repeat=0;repeat<repeats;repeat++)for(const entry of repeat%2?[...cases].reverse():cases)work.push([entry,repeat]);
  }else{
    for(const entry of cases)for(let repeat=0;repeat<repeats;repeat++)work.push([entry,repeat]);
  }
  const references=new Map();
  for(const [[name,operations,memory,compression,grouping='auto'],repeat] of work){
    const config={seed,operations,compression,output_csv:outputCsv,resources:{memory_mb:memory,workers:1,max_record_bytes:maxRecordBytes,grouping},limits:{rows:100000}};
    if(name.startsWith('flex_'))config.full_shuffle_policy='flexible_v1';
    const baselineEligible=beforeWasm;
    const engines=baselineEligible?(nativeBeforePath?['native-before','native','browser-before','browser']:['native','browser-before','browser']):['native','browser'];
    for(const engine of repeat%2?[...engines].reverse():engines){
      console.error(`${name} / ${engine} / repetition ${repeat+1}`);
      let result;
      if(engine.startsWith('browser')){
        if(beforeWasm){
          await writeFile('ui/dist/engine.wasm',engine==='browser-before'?beforeWasm:afterWasm);
        }
        if(beforeWasm||reloadBrowser){
          await page.reload();await page.waitForFunction(()=>typeof window.benchmark==='function');
        }
        result=await page.evaluate(({config,verify})=>window.benchmark(config,verify),{config,verify:name==='uniform32'||name.startsWith('flex_allocate')});
      }
      else{
        const output=join(root,'output'),path=join(root,'job.json');
        await writeFile(path,JSON.stringify({...config,input:join(root,'input.csv'),output}));
        const start=performance.now();
        const {stdout}=await exec(engine==='native-before'?resolve(nativeBeforePath):binary,['run','--config',path,'--yes'],{maxBuffer:8*1024*1024,timeout:300000});
        const elapsed=(performance.now()-start)/1000,analysis=JSON.parse(stdout),hashes={};
        const manifest=await readFile(join(output,'manifest.jsonl'),'utf8');
        const metadata=outputMetadata(manifest),seen=(name==='uniform32'||residentCases.includes(name)||name.startsWith('flex_'))?new Uint8Array(rows):null;
        for(const filename of await readdir(output))if(filename!=='manifest.jsonl'){
          const bytes=await readFile(join(output,filename)),decoded=filename.endsWith('.gz')?gunzipSync(bytes):bytes;
          hashes[filename]=createHash('sha256').update(decoded).digest('hex');
          if(seen){
            // The generator emits unquoted ASCII data; this check deliberately
            // applies only to that fixture, not to arbitrary input CSV.
            const entry=metadata.find(e=>e.path===filename);
            assert(entry);assert.equal(decoded.length,entry.csv_bytes);
            const records=new TextDecoder(outputEncoding).decode(decoded).trimEnd().split('\n').slice(1);
            assert.equal(records.length,entry.rows);
            const parentCount=4;
            const group=name.startsWith('grouped_')?entry.lineage.find(v=>v.part)?.part-1:null;
            if(group!==null)assert(Number.isInteger(group)&&group>=0&&group<parentCount);
            for(const record of records){
              const id=Number(record.split(',')[0]);
              assert(Number.isInteger(id)&&id>=0&&id<rows&&!seen[id]);
              if(group!==null){
                const start=group*Math.floor(rows/parentCount)+Math.min(group,rows%parentCount);
                assert(id>=start&&id<start+Math.floor(rows/parentCount)+Number(group<rows%parentCount));
              }
              if(name.startsWith('flex_partition_'))assert.equal(record.split(',')[1],entry.lineage.at(-1).values[0]);
              if((name==='uniform32'||name.startsWith('flex_allocate'))&&record!==sourceRecords[id+1])assert.deepEqual(record.split(',').map(v=>v==='""'?'':v),sourceRecords[id+1].split(',').map(v=>v==='""'?'':v));
              seen[id]=1;
            }
          }
        }
        if(seen)assert(seen.every(Boolean));
        result={analysis,manifest,elapsed_seconds:elapsed,analysis_wall_seconds:analysis.analysis_seconds,execution_seconds:elapsed-analysis.analysis_seconds,conservation_verified:!!seen,hashes};
        await rm(output,{recursive:true});
      }
      if((name.startsWith('flex_allocate'))&&!name.endsWith('stratified')){
        const groups=new Map();
        for(const entry of outputMetadata(result.manifest)){
          const position=entry.lineage.findIndex(v=>v.allocation&&allocationGroups.some(g=>g.name===v.allocation));
          assert(position>=0);
          const parent=JSON.stringify(entry.lineage.slice(0,position));
          const counts=groups.get(parent)??[0,0,0,0];groups.set(parent,counts);
          counts[allocationGroups.findIndex(g=>g.name===entry.lineage[position].allocation)]+=entry.rows;
        }
        for(const counts of groups.values()){
          const total=counts.reduce((a,b)=>a+b,0),weights=[17,0,33,50];
          const expected=weights.map(w=>Math.floor(total*w/100));
          const order=weights.map((_,i)=>i).sort((a,b)=>(total*weights[b]%100)-(total*weights[a]%100)||a-b);
          const remainder=total-expected.reduce((a,b)=>a+b,0);
          for(const index of order.slice(0,remainder))expected[index]++;
          assert.deepEqual(counts,expected);
        }
      }
      if(name.startsWith('flex_')){
        const audit=result.manifest.trim().split('\n').map(JSON.parse);
        const header=audit.find(r=>r.type==='execution_plan');
        assert.equal(header.replay_guarantee,'prepared_snapshot_only');
        assert.equal(header.source_logical_digest,result.analysis.logical_digest);
        const choices=audit.filter(r=>r.type==='execution_group');
        assert(choices.length>0&&choices.every(r=>r.uniform_full_permutation&&r.algorithm&&r.rng));
        result.resolved_algorithms=choices.map(r=>({algorithm:r.algorithm,implementation:r.implementation,decision:r.decision}));
      }
      // Hash decompressed outputs: codec byte streams can differ across targets.
      const logical=JSON.stringify(canonical([result.analysis.logical_digest,result.analysis.rows,result.analysis.output_csv_bytes,result.analysis.stages,outputMetadata(result.manifest),Object.entries(result.hashes).sort()]));
      const pinnedName=name;
      const referenceKey=pinnedName+(name.includes('entropy')?'/'+result.analysis.seed:name.startsWith('flex_allocate')&&result.manifest.includes('execution_rewrite')?'/rewritten':'/logical');
      const reference=references.get(referenceKey)??logical;references.set(referenceKey,reference);
      if(reference!==logical)throw new Error('Engine parity mismatch: '+name);
      result.output_hashes=result.hashes;delete result.hashes;delete result.analysis.preview;delete result.analysis.header;
      console.log(JSON.stringify({case:name,engine,repeat,rows,memory_mb:memory,verified:true,...result}));
    }
  }
}finally{await browser?.close();server?.kill();if(afterWasm)await writeFile('ui/dist/engine.wasm',afterWasm);await rm(root,{recursive:true,force:true});for(const file of files)await rm('ui/dist/'+file,{force:true});}
