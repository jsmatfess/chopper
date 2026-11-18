// Shared by the follow-up page and fixture-free malformed-input checks.
export const assert=(condition,message)=>{if(!condition)throw new Error(message);};
export const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
export const equal=(a,b,message)=>assert(JSON.stringify(canonical(a))===JSON.stringify(canonical(b)),message);
export const header=['id','payload',...Array.from({length:31},(_,k)=>'c'+k)];
export function blockProof(analysis){
  assert(analysis&&typeof analysis==='object'&&analysis.diagnostics&&typeof analysis.diagnostics==='object','retained analysis missing');
  const d=analysis.diagnostics,keys=['compact_spill_files','compact_spill_blocks','compact_spill_rows','compact_spill_fallbacks','compact_spill_source_bytes','compact_spill_stored_bytes'];
  for(const key of keys)assert(Number.isSafeInteger(d[key])&&d[key]>=0,'invalid block proof '+key);
  assert(d.compact_spill_files>0&&d.compact_spill_blocks>0&&d.compact_spill_rows>0&&d.compact_spill_fallbacks===0,'actual blocks absent/fallback');
  return Object.fromEntries(keys.map(k=>[k,d[k]]));
}
export function retainedOwners(d){
  const keys=['temporary_path_reserved_bytes','directory_path_reserved_bytes','input_header_reserved_bytes','prepared_job_reserved_bytes','analysis_preview_reserved_bytes','column_values_reserved_bytes','stage_stats_reserved_bytes','analysis_text_reserved_bytes','analysis_warnings_reserved_bytes','analysis_timings_reserved_bytes','analysis_diagnostics_reserved_bytes'];
  for(const key of [...keys,'workspace_reserved_bytes'])assert(Number.isSafeInteger(d[key])&&d[key]>=0,'missing/invalid owner '+key);
  let audit=0;const a=d.shuffle_partition_decisions;
  if(a!==undefined){
    assert(a.version===1&&a.policy==='experiment_gate_v1'&&a.capacity===16&&a.selector===null&&a.calibration===null,'unsupported decision audit');
    assert(typeof a.initialized==='boolean'&&typeof a.collection_denied==='boolean'&&Number.isSafeInteger(a.reserved_bytes)&&a.reserved_bytes>=0,'invalid audit owner');
    assert(Array.isArray(a.records)&&a.records.length<=16&&Number.isSafeInteger(a.omitted_attempts)&&a.omitted_attempts>=0&&a.completed_attempts===a.records.length+a.omitted_attempts,'invalid audit counts');
    assert(a.initialized&&!a.collection_denied?a.reserved_bytes>0:a.reserved_bytes===0&&a.records.length===0,'audit state/owner mismatch');audit=a.reserved_bytes;
  }
  assert(d.workspace_reserved_bytes===keys.reduce((n,k)=>n+d[k],0)+audit,'retained ownership equation failed');
}
export function metadata(manifest,config,analysis,shape,rows){
  assert(typeof manifest==='string'&&manifest.endsWith('\n'),'manifest must end in LF');
  const entries=manifest.slice(0,-1).split('\n').map(line=>JSON.parse(line));
  assert(entries.every(e=>e&&typeof e==='object'),'invalid manifest entry');
  const jobs=entries.filter(e=>e.type==='job'),outputs=entries.filter(e=>e.type==='output');
  assert(jobs.length===1&&entries.length===outputs.length+1,'unexpected manifest records');
  const job=jobs[0];
  equal(Object.keys(job).sort(),['algorithm_version','analysis','application_version','config','schema_version','type'],'unexpected job schema');
  assert(job.schema_version===1&&job.algorithm_version==='chopper-v1-blake3-1'&&job.application_version==='0.1.0','job version mismatch');
  const expected=structuredClone(config);expected.input='/input.csv';expected.output='/results';expected.resources.temp_dir='/tmp';
  // The current Rust Serialize schema omits these exact default enum values.
  assert(expected.full_shuffle_policy==='seeded_v1'&&expected.full_shuffle_rng==='blake3_counter_v1'&&expected.full_shuffle_algorithm==='adaptive_v1','unexpected replay policy');
  delete expected.full_shuffle_policy;delete expected.full_shuffle_rng;delete expected.full_shuffle_algorithm;
  equal(job.config,expected,'full manifest config mismatch');
  equal(job.analysis.header,header,'manifest header mismatch');equal(analysis.header,header,'ready header mismatch');
  const logicalKeys=['accuracy','column_values','columns','groups','header','largest_record_bytes','logical_digest','memory_budget_bytes','output_csv_bytes','output_files','preview','rows','seed','stages','workers'];
  for(const key of logicalKeys){assert(key in job.analysis&&key in analysis,'missing analysis '+key);equal(job.analysis[key],analysis[key],'manifest analysis mismatch '+key);}
  assert(analysis.rows===rows&&analysis.workers===1&&analysis.columns===33&&analysis.seed==='external-comparison-v1'&&analysis.memory_budget_bytes===33554432,'analysis contract mismatch');
  assert(/^[0-9a-f]{64}$/.test(analysis.logical_digest),'invalid logical digest');
  const n=shape==='columns'?1:4;assert(outputs.length===n&&analysis.output_files===n,'output count mismatch');
  const names=new Set();let total=0;
  for(const entry of outputs){
    equal(Object.keys(entry).sort(),['compressed_target_exceeded','csv_bytes','lineage','path','rows','stored_bytes','type'],'unexpected output schema');
    const part=outputs.indexOf(entry)+1;
    const path=(shape==='rare_wide'?'split-'+part+'-':'')+'part-'+String(part).padStart(8,'0')+'.csv';
    assert(entry.path===path&&!names.has(entry.path),'invalid/duplicate output path');names.add(entry.path);
    assert(entry.rows===rows/n&&Number.isSafeInteger(entry.csv_bytes)&&entry.csv_bytes>0&&entry.stored_bytes===entry.csv_bytes&&entry.compressed_target_exceeded===false,'output quota/bytes mismatch');
    equal(entry.lineage,shape==='rare_wide'?[{operation:1,part}]:[],'lineage mismatch');total+=entry.csv_bytes;
  }
  assert(total===analysis.output_csv_bytes,'manifest byte total mismatch');retainedOwners(analysis.diagnostics);retainedOwners(job.analysis.diagnostics);
  return {job,outputs,logical:Object.fromEntries(logicalKeys.map(k=>[k,analysis[k]]))};
}
export function schedule(){
  const jobs=[];for(const shape of ['columns','rare_wide'])for(const mode of ['MINIMAL','FULL'])for(const variant of ['baseline','candidate'])jobs.push({phase:'parity',shape,mode,variant});
  for(const variant of ['baseline','candidate']){jobs.push({phase:'cap-rejection',shape:'rare_wide',mode:'MINIMAL',variant,cap:1000000});jobs.push({phase:'cap-retry',shape:'rare_wide',mode:'MINIMAL',variant});}
  for(let repetition=1;repetition<=4;repetition++)for(const shape of repetition%2?['rare_wide','columns']:['columns','rare_wide'])for(const mode of [1,4].includes(repetition)?['MINIMAL','FULL']:['FULL','MINIMAL'])for(const variant of repetition%2?['baseline','candidate']:['candidate','baseline'])jobs.push({phase:'measurement',repetition,shape,mode,variant});
  assert(jobs.length===44,'fixed schedule changed');return jobs;
}
