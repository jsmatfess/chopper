import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createServer} from 'node:http';
import {execFileSync} from 'node:child_process';
import {cpus,release} from 'node:os';
import {resolve} from 'node:path';
import {gzipSync} from 'node:zlib';
import {calibrationPayload} from './browser-preview-calibration.mjs';
import {readFile} from 'node:fs/promises';
import {build} from '../ui/node_modules/esbuild/lib/main.js';
import {chromium} from '../ui/node_modules/playwright/index.mjs';

const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const mib=1024*1024,cap=4*mib;
const assetDirectory=process.argv[3]??'ui/dist';
const files=Object.fromEntries(await Promise.all(['engine.wasm','engine-worker.js','storage-worker.js'].map(async name=>[name,await readFile(assetDirectory+'/'+name)])));
// The historical swarm harness enumerates owners from its older evidence schema.
const swarm=await readFile('ui/tests/benchmark-swarm.ts','utf8');
const ownerCheck=/    const owners = \[[\s\S]+?'Retained workspace owner sum mismatch'\);\n/;
assert.match(swarm,ownerCheck);
const driverSource="import {previewCandidate,windowCandidate} from '../../scripts/browser-preview-calibration.mjs';\n"+swarm.replace(ownerCheck,'').replace("response.arrayBuffer()], 'input.csv')","response.arrayBuffer()], config.input || 'input.csv')")
  .replace('timeout: number) => {','timeout: number, profileFirst: boolean, inspectPreview: boolean, usePreview: boolean, keepPreview: boolean, useGzipTrailer: boolean, useWindows: boolean) => {')
  .replace('    const start = performance.now(),', '    await (window as any).swarmReady?.();\n    const start = performance.now(),')
  .replace('    Object.assign(window, {swarmSubmitted: submitted});',`    const previewStart=performance.now();
    const preview=inspectPreview?await api<{columns:number;preview:string[][]}>('preview',submitted):null;
    const previewSeconds=inspectPreview?(performance.now()-previewStart)/1000:0;
    const previewPlan=preview?previewCandidate(submitted,input.size,preview):null;
    if(inspectPreview && !keepPreview)await api('pick-path',{mode:'input'});
    if(usePreview && previewPlan?.previewTier>previewPlan?.sizeTier)submitted.resources.memory_mb=previewPlan.previewTier;
    Object.assign(window, {swarmSubmitted: submitted});`)
  .replace("    await api('run-direct', submitted);",`    let profileTarget;
    let windowPlan;
    if(useWindows){
      windowPlan=await windowCandidate(submitted,input,preview,previewPlan);
      if(windowPlan.target>previewPlan.previewTier)submitted.resources.memory_mb=windowPlan.target;
    }
    let gzipTrailer;
    if(useGzipTrailer){
      const hintStart=performance.now();
      const footer=await input.slice(-4).arrayBuffer();
      const isize=new DataView(footer).getUint32(0,true);
      const candidate={...submitted,input:'input.csv'};
      const plan=previewCandidate(candidate,isize,preview);
      gzipTrailer={isize,approximateSortBytes:plan.estimatedSortBytes,target:plan.previewTier,planning_seconds:(performance.now()-hintStart)/1000};
      if(plan.previewTier>256)submitted.resources.memory_mb=plan.previewTier;
    }
    if(profileFirst){
      await api('profile', submitted);
      const observation=await wait('profiled');
      profileTarget=observation.profile?.suggested_run_memory_mb;
    }
    const runStarted=performance.now();
    await api('run-direct', submitted);`)
  .replace('return {submitted, analysis: done.analysis,','return {submitted, previewPlan, previewSeconds, profileTarget, gzipTrailer, windowPlan, startWallMs:performance.timeOrigin+start, endWallMs:performance.timeOrigin+finished, analyzeSeconds:profileFirst?(runStarted-start)/1000:0, analysis: done.analysis,');
assert.match(driverSource,/config\.input \|\| 'input.csv'/);
const driver=await build({stdin:{contents:driverSource,resolveDir:resolve('ui/tests'),loader:'ts'},bundle:true,format:'iife',write:false});
files['driver.js']=driver.outputFiles[0].contents;
files['index.html']='<!doctype html><script src="/driver.js"></script>';
const metadata={commit:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),kernel:release(),
  cpu:cpus()[0]?.model,node:process.version,script_sha256:sha(await readFile(new URL(import.meta.url))),
  assets:Object.fromEntries(Object.entries(files).map(([name,bytes])=>[name,sha(bytes)])),
  destination:'disposable Chromium context, same-origin OPFS',clock:'complete Run through marker verification and workspace cleanup'};
const server=createServer((req,res)=>{
  const name=req.url==='/'?'index.html':req.url.slice(1),body=files[name];
  if(!body){res.writeHead(404).end();return;}
  const contentType=name.endsWith('.wasm')?'application/wasm':name.endsWith('.js')?'text/javascript':name.endsWith('.csv')?'text/csv':'text/html';
  res.writeHead(200,{'Content-Type':contentType,'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp','Cache-Control':'no-store'}).end(body);
});
const shuffle=[{type:'shuffle',strategy:'uniform'}],partition=[{type:'partition',columns:[1]}];
const memory=[{memory_mb:'auto'},{memory_mb:512},{memory_mb:1024},{memory_mb:2048}];
const partitionShuffle=[...partition,...shuffle];
const previewVariants=[{memory_mb:'auto'},{memory_mb:'auto',usePreview:true},{memory_mb:'auto',profile:true}];
const policyVariants=[{memory_mb:256},{memory_mb:'auto'},{memory_mb:'auto',profile:true}];
const grouping=[{grouping:'auto'},{grouping:'sort'}];
const panel=process.argv[2]??'primary';
assert(['primary','holdout','pipeline','policy','preview','preview-codec-control','preview-large','preview-large-shuffle-control','preview-production','preview-gzip-trailer','preview-gzip-production','preview-pair','preview-windows','preview-windows-integrated','preview-windows-composed'].includes(panel),'Unknown browser resource benchmark panel');
const jobs=panel==='preview-windows-composed'?[
  {name:'windows-narrow-composed',rows:680000,groups:8,payloadRepeats:7,widePrefix:true,middleBand:true,
    skewed:true,operations:partitionShuffle,
    variants:[{memory_mb:'auto'},{memory_mb:'auto',keepPreview:true},{memory_mb:'auto',keepPreview:true,profile:true}]},
]:panel.startsWith('preview-windows')?[
  {name:'windows-stable-wide',rows:260000,groups:8,payloadRepeats:52,operations:shuffle},
  {name:'windows-narrow-tail',rows:1744000,groups:8,payloadRepeats:7,widePrefix:true,operations:shuffle},
  {name:'windows-narrow-middle',rows:754000,groups:8,payloadRepeats:7,widePrefix:true,middleBand:true,operations:shuffle},
  {name:'windows-interior-quoted-lines',rows:257000,groups:8,payloadRepeats:52,probeQuoted:true,operations:shuffle},
  ...(panel==='preview-windows-integrated'?[
    {name:'windows-beyond-range',rows:2000000,groups:8,payloadRepeats:6,widePrefix:true,operations:shuffle},
  ]:[]),
].map(job=>({...job,variants:panel==='preview-windows-integrated'
  ?[{memory_mb:'auto'},{memory_mb:'auto',keepPreview:true},{memory_mb:'auto',keepPreview:true,profile:true}]
  :[{memory_mb:'auto',keepPreview:true},{memory_mb:'auto',keepPreview:true,useWindows:true},{memory_mb:'auto',keepPreview:true,profile:true}]})):panel==='preview-pair'?[
  {name:'paired-column-rich',rows:325000,groups:8,columns:42,operations:shuffle,
    variants:[{memory_mb:'auto'},{memory_mb:'auto',keepPreview:true}]},
]:panel==='primary'?[
  {name:'streaming-control',rows:100000,groups:8,operations:[],variants:memory},
  {name:'shuffle-medium',rows:400000,groups:8,operations:shuffle,variants:memory},
  {name:'shuffle-large',rows:800000,groups:8,operations:shuffle,variants:memory},
  {name:'partition-8',rows:400000,groups:8,operations:partition,variants:grouping},
  {name:'partition-256',rows:400000,groups:256,operations:partition,variants:grouping},
]:panel==='holdout'?[
  {name:'shuffle-held-out-wide',rows:100000,groups:8,payloadRepeats:50,operations:shuffle,variants:memory.slice(0,3)},
  {name:'shuffle-held-out-narrow',rows:550000,groups:8,payloadRepeats:8,operations:shuffle,variants:memory.slice(0,3)},
  {name:'shuffle-held-out-gzip',rows:100000,groups:8,payloadRepeats:50,gzip:true,operations:shuffle,variants:memory.slice(0,3)},
]:panel==='pipeline'?[
  {name:'partition-shuffle-even',rows:400000,groups:8,operations:partitionShuffle,variants:[memory[0],memory[2]]},
  {name:'partition-shuffle-skew',rows:400000,groups:8,skewed:true,operations:partitionShuffle,variants:[memory[0],memory[2]]},
]:panel==='policy'?[
  {name:'policy-large',rows:780000,groups:8,operations:shuffle,choices:[2048,2048]},
  {name:'policy-wider',rows:97000,groups:8,payloadRepeats:52,operations:shuffle,choices:[512,512]},
  {name:'policy-narrower',rows:520000,groups:8,payloadRepeats:9,operations:shuffle,choices:[512,1024]},
  {name:'policy-gzip',rows:97000,groups:8,payloadRepeats:52,gzip:true,operations:[{type:'shuffle',strategy:'auto'}],choices:[256,512]},
  {name:'policy-late-wide',rows:110000,groups:8,payloadRepeats:2,lateWide:true,operations:shuffle,choices:[512,512]},
  {name:'policy-many-columns',rows:150000,groups:8,columns:42,operations:shuffle,choices:[512,1024]},
  {name:'policy-composed',rows:360000,groups:8,skewed:true,operations:partitionShuffle,choices:[1024,1024]},
  {name:'policy-streaming',rows:260000,groups:8,operations:[],choices:[256,256]},
  {name:'policy-unsupported',rows:90000,groups:8,operations:[...partitionShuffle,...shuffle],choices:[256,256]},
].map(job=>({...job,variants:policyVariants})):panel==='preview'?[
  {name:'preview-column-rich',rows:145000,groups:8,columns:42,operations:shuffle},
  {name:'preview-column-rich-composed',rows:143000,groups:8,columns:42,skewed:true,operations:partitionShuffle},
  {name:'preview-uniform-wide',rows:100000,groups:8,payloadRepeats:52,operations:shuffle},
  {name:'preview-same-head-narrow-tail',rows:675000,groups:8,payloadRepeats:7,widePrefix:true,operations:shuffle},
  {name:'preview-late-wide',rows:112000,groups:8,payloadRepeats:2,lateWide:true,operations:shuffle},
  {name:'preview-censored-head',rows:92000,groups:8,payloadRepeats:54,hugePrefix:true,operations:shuffle},
  {name:'preview-gzip-expand',rows:100000,groups:8,payloadRepeats:52,gzip:true,operations:shuffle},
  {name:'preview-gzip-small',rows:11500,groups:8,noisy:true,gzip:true,operations:shuffle},
  {name:'preview-streaming',rows:138000,groups:8,columns:42,operations:[]},
].map(job=>({...job,variants:previewVariants})):panel==='preview-codec-control'?[
  {name:'preview-gzip-matched-head',rows:11500,groups:8,noisy:true,gzip:true,widePrefix:true,operations:shuffle,variants:previewVariants},
]:panel.startsWith('preview-gzip-')?[
  {name:'trailer-single-member-large',rows:260000,groups:8,payloadRepeats:52,gzip:true,operations:shuffle},
  {name:'trailer-held-out-parallel-keys',rows:235000,groups:16,payloadRepeats:37,skewed:true,gzip:true,operations:partitionShuffle},
  {name:'trailer-single-member-small',rows:30000,groups:8,noisy:true,gzip:true,widePrefix:true,operations:shuffle},
  {name:'trailer-concatenated-small-last-member',rows:260000,groups:8,payloadRepeats:52,gzip:true,multiMember:true,operations:shuffle},
  {name:'trailer-concatenated-large-last-member',rows:260000,groups:8,payloadRepeats:52,gzip:true,multiMember:true,shortFirstMember:true,operations:shuffle},
  {name:'trailer-single-member-prefix-trap',rows:1744000,groups:8,payloadRepeats:7,widePrefix:true,gzip:true,operations:shuffle},
].filter(job=>panel==='preview-gzip-trailer'||[
  'trailer-single-member-large','trailer-held-out-parallel-keys','trailer-concatenated-small-last-member'
].includes(job.name)).map(job=>({...job,variants:panel==='preview-gzip-trailer'
  ?[{memory_mb:'auto'},{memory_mb:'auto',useGzipTrailer:true},{memory_mb:'auto',profile:true}]
  :[{memory_mb:'auto'},{memory_mb:'auto',keepPreview:true}]})):panel==='preview-large'?[
  {name:'large-preview-column-rich',rows:325000,groups:8,columns:42,operations:partitionShuffle},
  {name:'large-preview-stable-wide',rows:260000,groups:8,payloadRepeats:52,operations:shuffle},
  {name:'large-preview-narrow-tail',rows:1744000,groups:8,payloadRepeats:7,widePrefix:true,operations:shuffle},
  {name:'large-preview-gzip-expand',rows:260000,groups:8,payloadRepeats:52,gzip:true,operations:shuffle},
  {name:'large-preview-gzip-matched-head',rows:30000,groups:8,noisy:true,gzip:true,widePrefix:true,operations:shuffle},
  {name:'large-preview-streaming',rows:585000,groups:8,columns:42,operations:[]},
].map(job=>({...job,variants:previewVariants})):panel==='preview-production'?[
  {name:'production-column-rich',rows:325000,groups:8,columns:42,operations:shuffle},
  {name:'production-narrow-tail',rows:1744000,groups:8,payloadRepeats:7,widePrefix:true,operations:shuffle},
].map(job=>({...job,variants:[{memory_mb:'auto'},{memory_mb:'auto',keepPreview:true},{memory_mb:'auto',keepPreview:true,profile:true}]})):[
  {name:'large-preview-column-rich-standalone',rows:325000,groups:8,columns:42,operations:shuffle,variants:previewVariants},
  {name:'large-preview-narrow-tail-2048',rows:1744000,groups:8,payloadRepeats:7,widePrefix:true,operations:shuffle,variants:[memory.at(-1)]},
];
let browser,failed=false;
try{
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  browser=await chromium.launch();console.log(JSON.stringify({type:'environment',browser:browser.version(),panel,...metadata}));
  for(const {name,rows,groups,operations,variants,payloadRepeats=20,gzip=false,skewed=false,lateWide=false,columns=3,widePrefix=false,hugePrefix=false,noisy=false,multiMember=false,shortFirstMember=false,middleBand=false,probeQuoted=false,choices} of jobs){
    const payload=columns===3?'Chopper01234'.repeat(payloadRepeats):Array(columns-2).fill('Chopper01234').join(',');
    const latePayload=lateWide?'Chopper01234'.repeat(360):payload;
    const prefix=hugePrefix?'h'.repeat(40*1024):widePrefix?'Chopper01234'.repeat(52):null;
    const header=columns===3?'id,key,payload':['id','key',...Array.from({length:columns-2},(_,i)=>'data'+i)].join(',');
    const keyFor=id=>skewed?id%16===0?1+(Math.floor(id/16)%(groups-1)):0:id%groups;
    const csv=Buffer.from(header+'\n'+Array.from({length:rows},(_,id)=>{
      let field=prefix&&id<8?prefix:noisy?calibrationPayload(id):id>=rows*7/8?latePayload:payload;
      if(middleBand&&(id<rows/8||id>=rows*7/8))field=prefix;
      if(probeQuoted&&id>8&&id%32===0)field=`"${field}\n0,0,quoted"`;
      return `${id},${keyFor(id)},${field}\n`;
    }).join(''));
    const boundary=csv.lastIndexOf(10,shortFirstMember?4*mib:csv.length-4*mib)+1;
    files['input.csv']=multiMember?Buffer.concat([gzipSync(csv.subarray(0,boundary)),gzipSync(csv.subarray(boundary))])
      :gzip?gzipSync(csv):csv;
    console.log(JSON.stringify({type:'fixture',name,rows,groups,operations,gzip,multiMember,shortFirstMember,middleBand,probeQuoted,skewed,lateWide,widePrefix,hugePrefix,noisy,columns,payload_bytes:payload.length,decoded_csv_bytes:csv.length,bytes:files['input.csv'].length,sha256:sha(files['input.csv'])}));
    for(let round=0;round<(['policy','preview','preview-codec-control','preview-large','preview-large-shuffle-control','preview-production','preview-gzip-trailer','preview-gzip-production','preview-pair','preview-windows','preview-windows-integrated','preview-windows-composed'].includes(panel)?2:3);round++)for(let slot=0;slot<variants.length;slot++){
      const variant=variants[(round+slot)%variants.length];
      const {profile=false,usePreview=false,keepPreview=false,useGzipTrailer=false,useWindows=false,...resources}=variant;
      const config={input:gzip?'input.csv.gz':'input.csv',operations,resources:{memory_mb:'auto',workers:0,grouping:'auto',...resources},limits:{rows:null,bytes:cap,compressed_bytes:null}};
      const context=await browser.newContext();
      const parallel=panel==='preview-pair'?2:1;
      let arrivals=0,releasePair;
      const ready=new Promise(resolve=>{releasePair=resolve;});
      const trials=Array.from({length:parallel},async (_,jobIndex)=>{
        const record={type:'run',name,round,variant,config,job_index:jobIndex};
        let page;
        try{
          page=await context.newPage();
          if(parallel>1)await page.exposeFunction('swarmReady',()=>{
            if(++arrivals===parallel)releasePair();
            return ready;
          });
          await page.goto('http://127.0.0.1:'+server.address().port);
          await page.waitForFunction(()=>typeof window.swarmRun==='function');
          const result=await page.evaluate(({config,profile,inspectPreview,usePreview,keepPreview,useGzipTrailer,useWindows})=>window.swarmRun(config,180,profile,inspectPreview,usePreview,keepPreview,useGzipTrailer,useWindows),{config,profile,inspectPreview:panel.startsWith('preview'),usePreview,keepPreview,useGzipTrailer,useWindows});
          if(panel==='preview-windows-integrated'||panel==='preview-windows-composed'){
            const plan=result.analysis.auto_plan?.memory_plan;
            assert(plan,'Missing product width-sample plan');
            const raised=keepPreview&&name.startsWith('windows-narrow');
            assert.equal(typeof plan.interior_sort_bytes==='number',raised);
            assert.equal(result.analysis.memory_budget_bytes/mib,raised?2048:1024);
          }
          if(panel==='preview-gzip-production'){
            const plan=result.analysis.auto_plan?.memory_plan;
            assert(plan,'Missing product gzip memory plan');
            const raised=keepPreview&&name!=='trailer-concatenated-small-last-member';
            assert.equal(result.analysis.memory_budget_bytes/mib,raised?1024:256);
            assert.equal(plan.preview_tier_mb??null,raised?1024:null);
            assert.equal(typeof plan.gzip_member_bytes==='number',raised);
          }
          if(panel==='preview-production'||panel==='preview-pair'){
            const plan=result.analysis.auto_plan?.memory_plan;
            assert(plan,'Missing product memory plan');
            assert.equal(result.analysis.memory_budget_bytes/mib,!keepPreview||name==='production-narrow-tail'&&!profile?1024:2048);
            assert.equal(plan.from_analyze,profile);
            assert.equal(plan.preview_tier_mb??null,keepPreview&&name!=='production-narrow-tail'?2048:null);
          }
          if(choices){
            const expected=variant.memory_mb===256?256:choices[Number(profile)];
            assert.equal(result.analysis.memory_budget_bytes/mib,expected,'Effective Run memory');
            if(profile){
              assert.equal(result.analysis.auto_plan?.analysis_status,'matched','Analyze observations were reused');
              if(operations.length===1&&operations[0].type==='shuffle'||operations===partitionShuffle){
                assert.equal(result.profileTarget,expected,'Analyze memory target');
                assert.equal(result.analysis.auto_plan?.memory_plan?.from_analyze,true);
              }
            }
          }
          await page.evaluate(async({owned,output,count,rows,groups,payload,latePayload,prefix,noisy,header,cap,ordered,partitioned,skewed,middleBand,probeQuoted})=>{
            const root=await navigator.storage.getDirectory(),parent=await root.getDirectoryHandle(owned);
            const folder=await parent.getDirectoryHandle(output.split('/').at(-1));
            const file=async name=>(await folder.getFileHandle(name)).getFile();
            const marker=JSON.parse(await(await file('CHOPPER-COMPLETE.json')).text());
            const manifest=(await(await file('manifest.jsonl')).text()).trim().split('\n').map(line=>JSON.parse(line));
            const seen=new Uint8Array(rows),last=new Map();let observed=0;
            for(const item of manifest.filter(item=>item.type==='output')){
              const csv=await file(item.path),body=(await csv.text()).trimEnd();
              const lines=probeQuoted?body.match(/^\d+,\d+,(?:"[^"]*"|[^"\n]*)$/gm)??[]:body.split('\n');
              if(probeQuoted){
                lines.unshift(header);
                if(body!==lines.join('\n'))throw Error('Quoted output framing mismatch');
              }
              if(csv.size>cap||csv.size!==item.csv_bytes||lines.shift()!==header||lines.length!==item.rows)throw Error('Output cap, header or manifest mismatch');
              let fileGroup;
              for(const line of lines){
                const first=line.indexOf(','),second=line.indexOf(',',first+1);
                const id=Number(line.slice(0,first)),key=Number(line.slice(first+1,second));
                const expected=skewed?id%16===0?1+(Math.floor(id/16)%(groups-1)):0:id%groups;
                let expectedPayload=prefix&&id<8?prefix:id>=rows*7/8?latePayload:payload;
                if(middleBand&&(id<rows/8||id>=rows*7/8))expectedPayload=prefix;
                if(probeQuoted&&id>8&&id%32===0)expectedPayload=`"${expectedPayload}\n0,0,quoted"`;
                if(noisy&&!(prefix&&id<8)){
                  let state=(id+1)|0;
                  expectedPayload='';
                  for(let index=0;index<52;index++){
                    state^=state<<13;state^=state>>>17;state^=state<<5;
                    expectedPayload+='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'[state&63];
                  }
                }
                if(!Number.isInteger(id)||id<0||id>=rows||seen[id]||expected!==key||line.slice(second+1)!==expectedPayload)throw Error('Output fields or conservation mismatch');
                if(partitioned){fileGroup??=key;if(fileGroup!==key)throw Error('Partition membership mismatch');}
                if(ordered){const group=partitioned?key:0;if((last.get(group)??-1)>=id)throw Error('Stable order mismatch');last.set(group,id);}
                seen[id]=1;observed++;
              }
            }
            if(observed!==rows||marker.complete!==true||marker.engine!=='chopper-browser'||marker.version!==1||marker.files!==count-1)throw Error('Incomplete result or marker');
          },{owned:result.owned_destination,output:result.output,count:result.files.length,rows,groups,payload,latePayload,prefix,noisy,header,cap,ordered:!operations.some(op=>op.type==='shuffle'),partitioned:operations.some(op=>op.type==='partition'),skewed,middleBand,probeQuoted});
          await page.evaluate(()=>window.swarmCleanup());
          const {analysis,diagnostics}=result;
          Object.assign(record,{elapsed_seconds:result.elapsed_seconds,start_wall_ms:result.startWallMs,end_wall_ms:result.endWallMs,preview_plan:result.previewPlan,preview_wall_seconds:result.previewSeconds,gzip_trailer_candidate:result.gzipTrailer,window_candidate:result.windowPlan,analysis_seconds:analysis.analysis_seconds,analyze_wall_seconds:result.analyzeSeconds,profile_target_mb:result.profileTarget,memory_budget_bytes:analysis.memory_budget_bytes,workers:analysis.workers,
            resource_diagnostics:analysis.diagnostics,auto_plan:analysis.auto_plan,storage:diagnostics.storage,storage_calls:{execute:diagnostics.execute,export:diagnostics.export},
            output_files:analysis.output_files,output_csv_bytes:analysis.output_csv_bytes,verified:true});
        }catch(error){failed=true;releasePair();record.error=String(error);record.failure=await page?.evaluate(()=>window.swarmFailure()).catch(()=>null);}
        finally{await page?.close();}
        return record;
      });
      const records=await Promise.all(trials);
      await context.close();
      for(const record of records)console.log(JSON.stringify(record));
      if(parallel>1&&records.every(record=>record.verified)){
        const starts=records.map(record=>record.start_wall_ms),ends=records.map(record=>record.end_wall_ms);
        assert(Math.max(...starts)<Math.min(...ends),'The jobs did not overlap');
        console.log(JSON.stringify({type:'pair',name,round,variant,
          start_skew_ms:Math.max(...starts)-Math.min(...starts),
          makespan_seconds:(Math.max(...ends)-Math.min(...starts))/1000}));
      }
    }
  }
}finally{try{await browser?.close();}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}}
if(failed)process.exitCode=1;
