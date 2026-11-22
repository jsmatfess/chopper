import {browserApi} from '../src/browser/client';
import type {Job,State} from '../src/app';
const results:{name:string;seconds:number;error?:string}[]=[];
Object.assign(window,{testResults:results,testDone:false});
const assert=(condition:unknown,message:string)=>{if(!condition)throw new Error(message);};
let selected:File;
let destination:FileSystemDirectoryHandle;
let defaults:Job;
const api=browserApi;
const pause=()=>new Promise(r=>setTimeout(r,25));
async function wait(status:string){const deadline=Date.now()+300000;while(Date.now()<deadline){const s=await api<State>('state');if(s.status===status)return s;if(s.status==='failed')throw new Error(s.error!);await pause();}throw new Error('Timed out waiting for '+status);}
async function verifyPlainRows(files:File[], source:File) {
  const expected=(await source.text()).trimEnd().split('\n');
  const output=await texts(files),actual:string[]=[];
  for(const text of output){const lines=text.trimEnd().split('\n');assert(lines.shift()===expected[0],'output header changed');actual.push(...lines);}
  assert(JSON.stringify(actual.sort())===JSON.stringify(expected.slice(1).sort()),'randomized output lost, duplicated or changed fields');
}
async function select(file:File){selected=file;await api('pick-path',{mode:'input'});await api('pick-path',{mode:'output'});}
function job(change:Partial<Job>={}):Job{return {...structuredClone(defaults),input:'fixture.csv',output:'results',...change};}
async function run(file:File,config:Job,direct=false){
  await select(file);
  if(!direct){await api('profile',config);await wait('profiled');}
  await api('run-direct',config);
  const done=await wait('complete');const plan=done;
  const folder=await destination.getDirectoryHandle(done.output!.split('/').at(-1)!);
  const files:File[]=[];for await(const [,h] of (folder as any).entries())files.push(await h.getFile());
  const markerFile=files.find(f=>f.name==='CHOPPER-COMPLETE.json');
  assert(markerFile,'missing completion marker');
  const marker=JSON.parse(await markerFile!.text());
  assert(marker.complete===true&&marker.engine==='chopper-browser'&&marker.version===1&&marker.files===files.length-1,'invalid completion marker record');
  return {plan:plan.analysis!,files,folder};
}
const csv=(s:string)=>new File([s],'fixture.csv');
function outputIndex(file:File){const match=file.name.match(/part-(\d+)\.csv$/);assert(match,'missing numeric output suffix');return Number(match![1]);}
// Descriptive prefixes can sort differently from the engine's logical output order.
async function texts(files:File[]){return await Promise.all(files.filter(f=>f.name.endsWith('.csv')).sort((a,b)=>outputIndex(a)-outputIndex(b)).map(f=>f.text()));}
async function test(name:string,fn:()=>Promise<void>){const start=performance.now();try{await fn();results.push({name,seconds:(performance.now()-start)/1000});}catch(e){results.push({name,seconds:(performance.now()-start)/1000,error:String(e)});throw e;}finally{document.body.textContent=JSON.stringify(results,null,2);}}
// The opt-in retained-parent audit is an admitted live owner, including at idle.
function decisionAuditBytes(diagnostics:any):number {
  const audit=diagnostics?.shuffle_partition_decisions;
  if(audit===undefined)return 0;
  assert(audit.version===1&&audit.policy==='experiment_gate_v1'&&audit.capacity===16,'unsupported decision audit');
  assert(audit.selector===null&&audit.calibration===null,'unsupported decision selector');
  assert(typeof audit.initialized==='boolean'&&typeof audit.collection_denied==='boolean','invalid audit state');
  assert(Number.isSafeInteger(audit.reserved_bytes)&&audit.reserved_bytes>=0,'invalid audit reservation');
  assert(Array.isArray(audit.records)&&audit.records.length<=audit.capacity,'invalid bounded audit records');
  assert(Number.isSafeInteger(audit.omitted_attempts)&&audit.omitted_attempts>=0&&audit.completed_attempts===audit.records.length+audit.omitted_attempts,'invalid audit counts');
  assert(audit.initialized&&!audit.collection_denied?audit.reserved_bytes>0:audit.reserved_bytes===0&&audit.records.length===0,'audit owner/state mismatch');
  return audit.reserved_bytes;
}
async function main(){
  const root=await navigator.storage.getDirectory();destination=await root.getDirectoryHandle('chopper-browser-tests-'+crypto.randomUUID(),{create:true});
  Object.assign(window,{showOpenFilePicker:async()=>[{getFile:async()=>selected}],showDirectoryPicker:async()=>destination});
  defaults=await api<Job>('defaults');
  await test('removed bucket and XOF requests fail through WASI without publication',async()=>{
    for(const action of ['profile','run-direct']) {
      for(const change of [
        {full_shuffle_algorithm:'independent_buckets_v1'},
        {full_shuffle_rng:'blake3_xof_v1'},
        {resources:{...defaults.resources,shuffle_rng_buffer_bytes:64}}
      ]) {
        await select(csv('id\n1\n2\n'));
        const before=[];for await(const [name] of (destination as any).entries())before.push(name);
        await api(action,job(change as Partial<Job>));
        let state=await api<State>('state');
        while(state.status==='running'||state.status==='profiling'){await pause();state=await api<State>('state');}
        assert(state.status==='failed','removed experiment was accepted');
        assert(/unknown variant `(independent_buckets_v1|blake3_xof_v1)`|unknown field `shuffle_rng_buffer_bytes`/.test(state.error||''),'missing schema error: '+state.error);
        let refused=false;try{await api('run',{});}catch{refused=true;}assert(refused,'invalid job authorized publication');
        const after=[];for await(const [name] of (destination as any).entries())after.push(name);
        assert(JSON.stringify(before.sort())===JSON.stringify(after.sort()),'invalid job published output');
      }
    }
  });
  await test('removed shuffle requests fail through WASI without publication',async()=>{
    for(const action of ['profile','run-direct']) {
      for(const operation of [
        {type:'shuffle',strategy:'buffer'},
        {type:'shuffle',strategy:'buffer',buffer_rows:7},
        {type:'shuffle',strategy:'radix'},
        {type:'shuffle',strategy:'prefix_distribution'},
        {type:'shuffle',buffer_rows:7},
        ...['uniform','auto','fisher_yates'].map(strategy=>({type:'shuffle',strategy,buffer_rows:7}))
      ]) {
        await select(csv('id\n1\n2\n'));
        const before=[];for await(const [name] of (destination as any).entries())before.push(name);
        await api(action,job({operations:[operation]}));
        let state=await api<State>('state');
        while(state.status==='running'||state.status==='profiling'){await pause();state=await api<State>('state');}
        assert(state.status==='failed','obsolete request was accepted');
        assert(/unknown variant `(buffer|radix|prefix_distribution)`|unknown field `buffer_rows`/.test(state.error||''),'missing schema error: '+state.error);
        let refused=false;try{await api('run',{});}catch{refused=true;}
        assert(refused,'rejected request authorized execution');
        const after=[];for await(const [name] of (destination as any).entries())after.push(name);
        assert(JSON.stringify(before.sort())===JSON.stringify(after.sort()),'rejection published results');
      }
    }
  });
  await test('optional CSV sniffing shares the native engine',async()=>{
    await select(csv('country;value\r\nUS;1\r\nGB;2\r\n'));
    const result=await api<{settings:Job['input_csv']}>('sniff',job());
    assert(result.settings.delimiter===';'&&result.settings.line_ending==='crlf','wrong sniffed dialect');
    const r=await run(csv('country,value\nUS,1\nGB,2\nUS,3\n'),job({operations:[{type:'partition',columns:['country']}]}));
    assert(JSON.stringify(r.plan.column_values?.[0].values)===JSON.stringify(['GB','US']),'missing unique values');
  });
  await test('bounded input samples use the worker without preparing outputs',async()=>{
    await select(csv('id,note\n'+'1,hello\n'.repeat(8)+'"unterminated'));
    const before=(await api<State>('state')).status;
    const result=await api<{header:string[];preview:string[][]}>('preview',job());
    assert(JSON.stringify(result.header)===JSON.stringify(['id','note']),'sample header changed');
    assert(result.preview.length===8&&result.preview[0][1]==='hello','sample rows changed');
    assert((await api<State>('state')).status===before,'sample changed processing state');
    await select(csv('id,note\n1,hello\n'));
    const headerless=await api<{header:null;preview:string[][]}>('preview',job({input_csv:{...defaults.input_csv,headers:false}}));
    assert(headerless.header===null&&headerless.preview[0][0]==='id','headerless first row lost');
  });
  await test('full input profiling sees late keys and caches across config edits',async()=>{
    await select(csv('id,key\n'+Array.from({length:20000},(_,i)=>`${i},${i<15000?'a':'z'}`).join('\n')+'\n'));
    await api('profile',job());const first=(await wait('profiled')).profile!;
    assert(first.rows===20000&&!first.cache_hit,'incorrect full profile');
    assert(first.column_values[1].distinct===2&&first.column_values[1].distinct_exact,'late key was missed');
    await api('profile',job({operations:[{type:'partition',columns:['key']}]}));const second=(await wait('profiled')).profile!;
    assert(second.cache_hit&&second.stages[0].input_distinct_keys===2,'profile was not reused');
    assert((await api<State>('state')).status!=='ready','profile authorized execution');
    await select(csv('id,key\n4,c\n'));
    await api('profile',job());const replaced=(await wait('profiled')).profile!;
    assert(!replaced.cache_hit&&replaced.rows===1,'replacement reused stale profile');
  });
  await test('input profiling cancellation cannot leave a publishable job',async()=>{
    await select(csv('id\n'+'x\n'.repeat(1000000)));
    await api('profile',job());
    let refused=false;try{await api('run-direct',job());}catch{refused=true;}
    assert(refused,'preparation overlapped active profiling');
    await api('cancel',{});
    assert((await api<State>('state')).status==='cancelled','profile did not cancel');
    refused=false;try{await api('run',{});}catch{refused=true;}
    assert(refused,'cancelled profile authorized execution');
  });
  await test('automatic memory Run-only and Analyze-then-Run flows preserve requested and effective manifest resources',async()=>{
    assert(defaults.resources.memory_mb===256,'default memory changed');
    for(const direct of [true,false]){
      const config=job({resources:{...defaults.resources,memory_mb:'auto',workers:0,max_record_bytes:1048576}});
      const original=JSON.stringify(config);
      const result=await run(csv('id\n1\n2\n'),config,direct);
      assert(JSON.stringify(config)===original,'requested job mutated');
      assert(result.plan.memory_budget_bytes>0&&result.plan.memory_budget_bytes<=256*1048576,'invalid automatic budget');
      assert(result.plan.workers===1,'WASI worker count changed');
      const manifest=result.files.find(file=>file.name==='manifest.jsonl');
      assert(manifest,'missing manifest');
      const record=JSON.parse((await manifest!.text()).trim().split('\n')[0]);
      assert(record.config.resources.memory_mb==='auto','manifest lost requested auto');
      assert(record.config.resources.workers===0&&record.config.resources.max_record_bytes===1048576,'manifest changed explicit limits');
      assert(record.analysis.memory_budget_bytes===result.plan.memory_budget_bytes&&record.analysis.workers===1,'manifest lost effective resources');
    }
  });
  await test('hosted memory accepts 2 GiB and rejects larger budgets before publication',async()=>{
    for(const action of ['profile','run-direct']){
      await select(csv('id\n1\n2\n'));
      const before=[];for await(const [name] of (destination as any).entries())before.push(name);
      await api(action,job({resources:{...defaults.resources,memory_mb:2049}}));
      let failed=await api<State>('state');
      while(['profiling','analyzing','running'].includes(failed.status)){await pause();failed=await api<State>('state');}
      assert(failed.status==='failed'&&/2048 MiB/.test(failed.error||''),'missing hosted ceiling denial: '+failed.error);
      const after=[];for await(const [name] of (destination as any).entries())after.push(name);
      assert(JSON.stringify(before.sort())===JSON.stringify(after.sort()),'oversized budget published output');
    }
    for(const direct of [false,true]){
      const result=await run(csv('id\n1\n2\n'),job({resources:{...defaults.resources,memory_mb:2048},operations:[{type:'shuffle',strategy:'uniform'}]}),direct);
      assert(result.plan.memory_budget_bytes===2*1024**3,'2 GiB budget truncated');
      assert((result.plan.diagnostics as any).process_memory.limit_bytes===1024**3,'incorrect WASI allocation ledger');
      await verifyPlainRows(result.files,csv('id\n1\n2\n'));
    }
  });
  await test('automatic memory refuses an oversized explicit record limit and permits retry',async()=>{
    for(const action of ['run-direct','profile']){
      await select(csv('id\n1\n2\n'));
      const before=[];for await(const [name] of (destination as any).entries())before.push(name);
      await api(action,job({resources:{...defaults.resources,memory_mb:'auto',max_record_bytes:512*1048576}}));
      const failed=await wait('failed');
      assert(!!failed.error,'missing explicit limit denial');
      let refused=false;try{await api('run',{});}catch{refused=true;}
      assert(refused,'failed auto job authorized publication');
      const after=[];for await(const [name] of (destination as any).entries())after.push(name);
      assert(JSON.stringify(before.sort())===JSON.stringify(after.sort()),'denied auto job published output');
      const retry=await run(csv('id\n1\n2\n'),job({resources:{...defaults.resources,memory_mb:'auto',max_record_bytes:1048576}}),action==='run-direct');
      assert(retry.plan.rows===2,'auto denial corrupted retry');
    }
  });
  await test('direct Run returns final analysis and enforces serialized byte and row caps',async()=>{
    const source=csv('id,value\n1,abc\n2,def\n3,ghi\n');
    const config=job({limits:{rows:2,bytes:21,compressed_bytes:null}});
    const direct=await run(source,config,true);
    const prepared=await run(source,config);
    assert(direct.plan.rows===3&&direct.plan.output_files===2,'direct exact-fit byte boundary or final counts changed');
    assert(JSON.stringify(await texts(direct.files))===JSON.stringify(await texts(prepared.files)),'Run-only/Analyze-then-Run output differs');
    assert(direct.files.filter(f=>f.name.endsWith('.csv')).every(f=>f.size<=21),'direct byte cap exceeded');
    let refused=false;try{await api('run',{});}catch{refused=true;}assert(refused,'completed direct run retained preparation');
  });
  await test('direct Run supports pipelines requiring internal preparation',async()=>{
    const source=csv('id,key\n1,a\n2,b\n3,a\n4,b\n');
    const config=job({operations:[{type:'partition',columns:['key']},{type:'shuffle',strategy:'uniform'}]});
    const direct=await run(source,config,true),prepared=await run(source,config);
    await verifyPlainRows(direct.files,source);await verifyPlainRows(prepared.files,source);
    assert(direct.plan.rows===4&&direct.plan.output_files===2,'direct fallback final analysis missing');
  });
  await test('direct Run codec outputs roundtrip through admitted input adapters',async()=>{
    const source=csv('id,key\n1,a\n2,界\n3,"a,b"\n');
    for(const compression of ['gzip','zstd','zip'] as const){
      const encoded=await run(source,job({compression}),true);
      const file=encoded.files.find(f=>f.name.endsWith(compression==='gzip'?'.gz':compression==='zstd'?'.zst':'.zip'));
      assert(file,'missing direct compressed output');
      const decoded=await run(file!,job(),true);
      assert(JSON.stringify(await texts(decoded.files))===JSON.stringify([await source.text()]),'direct '+compression+' roundtrip changed fields/order');
      assert(decoded.plan.rows===3,'direct '+compression+' row count changed');
    }
  });
  await test('direct Run cancellation cleans workspace and cannot publish prepared output',async()=>{
    const workspaces=await root.getDirectoryHandle('chopper-workspaces',{create:true});
    const before=new Set<string>();for await(const [name] of (workspaces as any).entries())before.add(name);
    await select(csv('id\n'+'x\n'.repeat(1000000)));
    await api('run-direct',job());await api('cancel',{});
    assert((await api<State>('state')).status==='cancelled','direct cancellation failed');
    let refused=false;try{await api('run',{});}catch{refused=true;}assert(refused,'cancelled direct run authorized execution');
    for await(const [name] of (workspaces as any).entries())assert(before.has(name),'direct cancellation leaked workspace');
  });
  await test('direct Run rejects late malformed input before destination export and retries cleanly',async()=>{
    const before=new Set<string>();for await(const [name] of (destination as any).entries())before.add(name);
    await select(csv('id,key\n1,a\n2,b,c\n'));
    await api('run-direct',job({limits:{rows:1,bytes:null,compressed_bytes:null}}));
    const failed=await wait('failed');assert(failed.error?.includes('expected 2'),'late direct width error missing');
    for await(const [name] of (destination as any).entries())assert(before.has(name),'failed direct input exported partial output');
    const retried=await run(csv('id,key\n1,a\n2,b\n'),job({limits:{rows:1,bytes:null,compressed_bytes:null}}),true);
    assert(retried.plan.rows===2&&retried.plan.output_files===2,'direct failure corrupted retry');
  });
  await test('row limits preserve order and exact bytes',async()=>{
    const r=await run(csv('id,country\n1,US\n2,GB\n3,US\n4,GB\n5,US\n'),job({limits:{rows:2,bytes:null,compressed_bytes:null}}));
    assert(JSON.stringify(await texts(r.files))===JSON.stringify(['id,country\n1,US\n2,GB\n','id,country\n3,US\n4,GB\n','id,country\n5,US\n']),'incorrect chunks');
    assert(r.plan.output_csv_bytes===58,'incorrect byte accounting');
  });
  await test('balanced split rejects fewer records than files',async()=>{
    await select(csv('id\n1\n'));await api('run-direct',job({operations:[{type:'balanced',files:2}]}));
    while((await api<State>('state')).status==='running')await pause();assert((await api<State>('state')).status==='failed','expected rejection');
  });
  await test('strict malformed CSV rejection',async()=>{
    await select(csv('id\n"unterminated'));await api('run-direct',job());while((await api<State>('state')).status==='running')await pause();
    assert((await api<State>('state')).status==='failed','malformed CSV accepted');
  });
  const input=csv('id,country,segment\n'+Array.from({length:120},(_,i)=>`${i},${i%2?'US':'GB'},${i%3}`).join('\n')+'\n');
  for(const [operation,expected] of [
    [{type:'shuffle',strategy:'fisher_yates'},'ff2da2d0220d169b924e4b40ef542527ae8518520e1476f17fe186efa49d1854'],
    [{type:'interleaved',files:3},'bfb6feea1164999a2a7d6eba076f4bbb915008fb24984faa1a58874c2e1a1296'],
    [{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['segment']},'ffa9262af6a4525d413e134458c8eefac8aeec9b32e8649ce83dad39c68f4857']
  ] as [Job['operations'][number],string][])await test(`${operation.type} ${operation.strategy||''} conserves exact input records`,async()=>{
    const r=await run(input,job({operations:[operation]}));
    const contents=await texts(r.files);
    await verifyPlainRows(r.files,input);
    assert(r.plan.rows===120,'wrong input count');
    assert(r.plan.stages.length===1,'missing fused stage metadata');
  });
  await test('compact streaming ingestion preserves records and admitted owners',async()=>{
    for(const [membership,expected] of [
      [{type:'interleaved',files:3},'45009d15f783adef9778fd2f13a6dfb0671d8fc07f899e19ef72c2553c071683'],
      [{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['segment','country']},'a97ce78461e85cca70315001c5468e1283f7d5192f14497c3bf78d242b30b9eb']
    ] as [Job['operations'][number],string][]){
      const r=await run(input,job({operations:[{type:'balanced',files:2},membership,{type:'shuffle',strategy:'uniform'}]}));
      const contents=await texts(r.files);
        await verifyPlainRows(r.files,input);
      assert(r.plan.rows===120&&r.plan.stages.length===3,'pipeline metadata changed');
      assert(r.plan.diagnostics?.workspace_reserved_bytes===(r.plan.diagnostics?.temporary_path_reserved_bytes??0)+(r.plan.diagnostics?.directory_path_reserved_bytes??0)+(r.plan.diagnostics?.input_header_reserved_bytes??0)+(r.plan.diagnostics?.prepared_job_reserved_bytes??0)+(r.plan.diagnostics?.analysis_preview_reserved_bytes??0)+(r.plan.diagnostics?.column_values_reserved_bytes??0)+(r.plan.diagnostics?.stage_stats_reserved_bytes??0)+(r.plan.diagnostics?.analysis_text_reserved_bytes??0)+(r.plan.diagnostics?.analysis_warnings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_timings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_diagnostics_reserved_bytes??0)+decisionAuditBytes(r.plan.diagnostics),'streaming workspace retained');
    }
  });
  await test('retained-parent shuffle then partition preserves records and groups',async()=>{
    const r=await run(input,job({resources:{...defaults.resources,memory_mb:32,max_record_bytes:1048576},operations:[{type:'balanced',files:2},{type:'shuffle',strategy:'uniform'},{type:'partition',columns:['country']}]}));
    const contents=await texts(r.files);
    await verifyPlainRows(r.files,input);
    assert(r.plan.rows===120&&r.plan.stages.length===3&&contents.length===4,'retained-parent counts or stages changed');
    assert(r.plan.diagnostics?.workspace_reserved_bytes===(r.plan.diagnostics?.temporary_path_reserved_bytes??0)+(r.plan.diagnostics?.directory_path_reserved_bytes??0)+(r.plan.diagnostics?.input_header_reserved_bytes??0)+(r.plan.diagnostics?.prepared_job_reserved_bytes??0)+(r.plan.diagnostics?.analysis_preview_reserved_bytes??0)+(r.plan.diagnostics?.column_values_reserved_bytes??0)+(r.plan.diagnostics?.stage_stats_reserved_bytes??0)+(r.plan.diagnostics?.analysis_text_reserved_bytes??0)+(r.plan.diagnostics?.analysis_warnings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_timings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_diagnostics_reserved_bytes??0)+decisionAuditBytes(r.plan.diagnostics),'retained-parent preparation leaked workspace');
  });
  await test('interleaved splitting retains nonempty and exact file-count caps',async()=>{
    for(const config of [job({operations:[{type:'interleaved',files:121}]}),job({operations:[{type:'interleaved',files:2}],limits:{rows:59,bytes:null,compressed_bytes:null}})]){
      await select(input);await api('run-direct',config);
      while((await api<State>('state')).status==='running')await pause();
      assert((await api<State>('state')).status==='failed','expected interleaved rejection');
    }
  });
  const pipeline:Job['operations']=[{type:'partition',columns:['country','segment']},{type:'shuffle',strategy:'uniform'},{type:'assign',groups:[{name:'treatment',percent:'75'},{name:'control',percent:'25'}],strata:[]},{type:'balanced',files:2}];
  await test('partition then stratified assignment then shuffle',async()=>{
    const source=csv('id,country,segment,payload\n'+Array.from({length:60000},(_,i)=>`${i},${i%2?'US':'GB'},${i%3},${'x'.repeat(128)}`).join('\n')+'\n');
    const r=await run(source,job({resources:{...defaults.resources,memory_mb:32,max_record_bytes:1024*1024},limits:{rows:10000,bytes:null,compressed_bytes:null},operations:[
      {type:'partition',columns:['country','segment']},
      {type:'assign',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['country','segment']},
      {type:'shuffle',strategy:'uniform'}
    ]}));
    assert(r.plan.rows===60000&&r.plan.output_files===12,'wrong stratified output counts');
    const seen=new Set<number>();for(const text of await texts(r.files))for(const line of text.trimEnd().split('\n').slice(1)){const id=Number(line.split(',')[0]);assert(id>=0&&id<60000&&!seen.has(id),'lost or duplicate stratified row');seen.add(id);}
    assert(seen.size===60000,'missing stratified rows');
  });
  await test('combined partition/shuffle/allocation/balanced preserves counts and records',async()=>{
    const a=await run(input,job({operations:pipeline})),b=await run(input,job({operations:pipeline}));
    assert(a.plan.rows===120&&a.plan.output_files===24,'wrong allocation/count');
    await verifyPlainRows(a.files,input);await verifyPlainRows(b.files,input);
    const automatic=await run(input,job({operations:pipeline,resources:{...defaults.resources,memory_mb:'auto'}}));
    await verifyPlainRows(automatic.files,input);
  });
  await test('automatic memory preserves probabilistic allocation records',async()=>{
    const operations:Job['operations']=[{type:'assign_probabilistic',groups:[{name:'treatment',percent:'37.5'},{name:'control',percent:'62.5'}],strata:['country']}];
    const numeric=await run(input,job({operations}));
    const automatic=await run(input,job({operations,resources:{...defaults.resources,memory_mb:'auto'}}));
    await verifyPlainRows(automatic.files,input);await verifyPlainRows(numeric.files,input);
  });
  for(const compression of ['gzip','zstd','zip'])await test(compression+' output and input roundtrip',async()=>{
    const a=await run(input,job({compression}));const compressed=a.files.find(f=>/\.(gz|zst|zip)$/.test(f.name))!;
    const b=await run(compressed,job());assert((await texts(b.files))[0]===await input.text(),'roundtrip failed');
  });
  await test('UTF-16 serialization and byte cap',async()=>{
    const settings={...defaults.output_csv,encoding:'utf-16le',bom:true,line_ending:'crlf'};
    const r=await run(csv('id,label\n1,café\n2,世界\n'),job({output_csv:settings,limits:{rows:null,bytes:40,compressed_bytes:null}}));
    for(const f of r.files.filter(f=>f.name.endsWith('.csv')))assert(f.size<=40,'byte cap exceeded');
    assert(r.plan.output_files===2,'expected two chunks');
  });
  await test('intermediate scans preserve wide UTF-8 fields across reader boundaries',async()=>{
    const encode=(fields:string[])=>fields.map(s=>/[",\r\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s).join(',')+'\n';
    const rows=Array.from({length:64},(_,id)=>[String(id),String(id%2),
      id===0||id===31?'a'+'界🙂'.repeat(12000)+'\r\n"end"':`é${id}`]);
    const header='id,key,payload\n',cap=85050;
    const r=await run(csv(header+rows.map(encode).join('')),job({
      resources:{...defaults.resources,memory_mb:32,max_record_bytes:1024*1024},
      operations:[{type:'balanced',files:4},{type:'partition',columns:['key']}],
      limits:{rows:null,bytes:cap,compressed_bytes:null}
    }));
    const expected=[];
    for(let part=0;part<4;part++)for(let key=0;key<2;key++)
      expected.push(header+rows.slice(part*16,(part+1)*16).filter(row=>Number(row[1])===key).map(encode).join(''));
    const actual=await texts(r.files);
    assert(r.plan.rows===64&&r.plan.output_files===8,'wide UTF-8 group counts changed');
    assert(JSON.stringify(actual)===JSON.stringify(expected),'wide UTF-8 fields or group order changed');
    const sizes=actual.map(text=>new TextEncoder().encode(text).byteLength);
    assert(sizes.every(size=>size<=cap),'wide UTF-8 byte cap exceeded');
    assert(r.plan.output_csv_bytes===sizes.reduce((a,b)=>a+b,0),'wide UTF-8 byte accounting changed');
  });
  await test('temporary budget fails without export',async()=>{
    await select(input);await api('run-direct',job({resources:{...defaults.resources,temp_bytes:1}}));while((await api<State>('state')).status==='running')await pause();assert((await api<State>('state')).status==='failed','budget ignored');
  });
  await test('disk-backed shuffle larger than working budget',async()=>{
    const source=await destination.getFileHandle('large-source.csv',{create:true});const writer=await source.createWritable();await writer.write('id,country,payload\n');
    const payload='x'.repeat(128);for(let start=0;start<300000;start+=1000)await writer.write(Array.from({length:1000},(_,n)=>`${start+n},${n%2?'US':'GB'},${payload}\n`).join(''));await writer.close();
    const file=await source.getFile();assert(file.size>32*1024*1024,'fixture must exceed memory budget');
    const r=await run(file,job({resources:{...defaults.resources,memory_mb:32,max_record_bytes:1024*1024},operations:[{type:'shuffle',strategy:'uniform'},{type:'balanced',files:3}]}));
    assert(r.plan.rows===300000&&r.plan.output_files===3,'large split mismatch');
    let count=0,sum=0;const seen=new Uint8Array(300000);for(const f of r.files.filter(f=>f.name.endsWith('.csv'))){let tail='',header=true;const reader=f.stream().pipeThrough(new TextDecoderStream()).getReader();for(;;){const {done,value}=await reader.read();if(done)break;const lines=(tail+value).split('\n');tail=lines.pop()!;for(const line of lines){if(header){header=false;continue;}const id=Number(line.split(',')[0]);assert(id>=0&&id<300000&&!seen[id],'lost or duplicate row');seen[id]=1;count++;sum+=id;}}}
    assert(count===300000&&sum===300000*299999/2,'large output conservation failed');
  });
  await test('adaptive grouping and forced sorting preserve identical output',async()=>{
    for(const late of [false,true]){
      // Keep new keys beyond the first spill with capacity-based WASI rows.
      const source=csv('id,key,payload\n'+Array.from({length:40000},(_,i)=>`${i},${late&&i>=32000?i%96:i%3},${'x'.repeat(256)}\n`).join(''));
      const resources={...defaults.resources,memory_mb:32,max_record_bytes:1024*1024};
      const operations=[{type:'partition',columns:['key']}];
      const a=await run(source,job({resources:{...resources,grouping:'auto'},operations}));
      if(late){
        assert((a.plan.diagnostics?.routing_reused_runs??0)>0,'expected reused sorted buckets');
        assert(a.plan.diagnostics?.routing_fallbacks===1,'expected a single late-key fallback');
      }else assert((a.plan.diagnostics?.routed_groupings??0)>0,'expected bounded grouping');
      const b=await run(source,job({resources:{...resources,grouping:'sort'},operations}));
      assert(b.plan.diagnostics?.routed_groupings===0,'sort override ignored');
      assert(JSON.stringify(await texts(a.files))===JSON.stringify(await texts(b.files)),'strategy output mismatch');
      assert(JSON.stringify(a.plan.stages)===JSON.stringify(b.plan.stages),'stage statistics mismatch');
    }
  });
  await test('per-group shuffle selection preserves records across resident and external budgets',async()=>{
    const count=18024;
    const source=csv('id,key,payload\n'+Array.from({length:count},(_,i)=>`${i},${i<24?'small'+Math.floor(i/3):'large'},${'x'.repeat(600)}\n`).join(''));
    const operations=[{type:'partition',columns:['key']},{type:'interleaved',files:1},{type:'shuffle',strategy:'uniform'},{type:'balanced',files:2}];
    const results=[];
    for(const memory_mb of [128,32]){
      const r=await run(source,job({resources:{...defaults.resources,memory_mb,max_record_bytes:1024*1024},operations}));
      assert(r.plan.output_files===18,'mixed group count');
      assert((r.plan.diagnostics?.resident_sorts??0)>=8,'small groups should stay resident');
      assert(((r.plan.diagnostics?.sort_runs??0)>0)===(memory_mb===32),'large group selection');
      assert(r.plan.diagnostics?.workspace_reserved_bytes===(r.plan.diagnostics?.temporary_path_reserved_bytes??0)+(r.plan.diagnostics?.directory_path_reserved_bytes??0)+(r.plan.diagnostics?.input_header_reserved_bytes??0)+(r.plan.diagnostics?.prepared_job_reserved_bytes??0)+(r.plan.diagnostics?.analysis_preview_reserved_bytes??0)+(r.plan.diagnostics?.column_values_reserved_bytes??0)+(r.plan.diagnostics?.stage_stats_reserved_bytes??0)+(r.plan.diagnostics?.analysis_text_reserved_bytes??0)+(r.plan.diagnostics?.analysis_warnings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_timings_reserved_bytes??0)+(r.plan.diagnostics?.analysis_diagnostics_reserved_bytes??0)+decisionAuditBytes(r.plan.diagnostics),'workspace retained after preparation');
      await verifyPlainRows(r.files,source);
      results.push({plan:r.plan,text:await texts(r.files)});
    }
    assert(JSON.stringify(results[0].plan.stages)===JSON.stringify(results[1].plan.stages),'budget changed stages');
  });
  await test('cancellation cleans active workspace',async()=>{
    const workspaces=await root.getDirectoryHandle('chopper-workspaces');
    const before=new Set<string>();for await(const [name] of (workspaces as any).entries())before.add(name);
    await select(await(await destination.getFileHandle('large-source.csv')).getFile());await api('run-direct',job());await api('cancel',{});assert((await api<State>('state')).status==='cancelled','cancel failed');
    for await(const [name] of (workspaces as any).entries())assert(before.has(name),'cancellation leaked temporary workspace');
  });
  await api('cancel',{});
  await root.removeEntry(destination.name,{recursive:true});
}
void main().then(()=>Object.assign(window,{testDone:true})).catch(error=>{Object.assign(window,{testDone:true,testError:String(error)});console.error(error);});
