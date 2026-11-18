// Fixture-free verifier checks. Historical records test serialized schema only.
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {metadata,retainedOwners,schedule} from '../ui/tests/e1-followup-verifier.mjs';
const decode=b=>new TextDecoder('utf-8',{fatal:true}).decode(b);
const bundle=JSON.parse(decode(await readFile(new URL('../docs/benchmarks/spill-blocks-persistent-e1-2026-10-24.json',import.meta.url))));
let rejected=0,accepted=0;
for(const shape of ['columns','rare_wide']){
  const record=Object.values(bundle.raw_attempts).find(x=>x.data?.shape===shape&&x.data.manifest)?.data;
  assert(record,'missing retained schema record');
  metadata(record.manifest,record.config,record.analysis,shape,100000);accepted++;
  const mutations=[
    es=>{es.shift();},
    es=>{es[0].schema_version=2;},
    es=>{es[0].algorithm_version='unversioned';},
    es=>{es[0].config.seed='changed';},
    es=>{es[0].analysis.logical_digest='0'.repeat(64);},
    es=>{es[1].rows--;},
    es=>{es[1].lineage=[{operation:99,part:2}];},
    es=>{delete es[0].analysis.diagnostics.temporary_path_reserved_bytes;},
    es=>{es[0].analysis.diagnostics.workspace_reserved_bytes++;},
    es=>{es[1].path='../escape.csv';},
    es=>{es.push({...es[1]});},
  ];
  for(const mutate of mutations){const entries=record.manifest.trim().split('\n').map(JSON.parse);mutate(entries);assert.throws(()=>metadata(entries.map(x=>JSON.stringify(x)).join('\n')+'\n',record.config,record.analysis,shape,100000));rejected++;}
}
assert.throws(()=>decode(Uint8Array.of(0xff)));rejected++;
assert.throws(()=>retainedOwners({workspace_reserved_bytes:0}));rejected++;
const jobs=schedule();assert.equal(jobs.filter(x=>x.phase==='measurement').length,32);assert.equal(jobs.filter(x=>x.phase!=='measurement').length,12);
assert.deepEqual(jobs.slice(8,12).map(x=>[x.phase,x.variant]),[['cap-rejection','baseline'],['cap-retry','baseline'],['cap-rejection','candidate'],['cap-retry','candidate']]);
console.log(JSON.stringify({contract:'e1-followup-verifier-schema-v1',historical_schema_acceptances:accepted,expected_malformed_rejections:rejected,fixed_plan_attempts:jobs.length,executed_browser_jobs:0},null,2));
