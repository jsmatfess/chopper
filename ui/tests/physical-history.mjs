import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const result=await build({entryPoints:['src/browser/physical-history.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {PhysicalHistory}=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const fact=(overrides={})=>({id:1033,kind:'resident_sort',operations:[1,2],rows:3,seconds:0.5,status:'completed',source_omitted:true,...overrides});
test('repeated fused resident work has one summary with attributable totals',()=>{
 const history=new PhysicalHistory();for(let i=0;i<10000;i++)history.accept(fact());
 assert.equal(history.snapshot().length,1);assert.equal(history.snapshot()[0].rows,30000);assert.equal(history.snapshot()[0].seconds,5000);assert.deepEqual(history.snapshot()[0].operations,[1,2]);
 history.accept(fact({id:1098,kind:'fisher_yates',operations:[3,0]}));assert.equal(history.snapshot().length,2);
});
test('producer omission and invalid categories stay bounded and explicit',()=>{
 const history=new PhysicalHistory();history.accept(fact());for(let i=0;i<10000;i++)history.accept(fact({operations:[i+18,0]}));
 assert.equal(history.snapshot().length,1);assert.equal(history.unavailable,true);
});
test('interrupted child work preserves completed outcomes and their measurements',()=>{
 const history=new PhysicalHistory();history.accept(fact());history.accept(fact({status:'active',rows:0,seconds:0}));history.accept(fact({status:'interrupted',rows:1,seconds:0.2}));
 const summary=history.snapshot()[0];assert.equal(summary.completed_attempts,1);assert.equal(summary.interrupted_attempts,1);assert.equal(summary.rows,3);assert.equal(summary.partial_rows,1);assert.equal(summary.seconds,0.5);assert.equal(summary.partial_seconds,0.2);
});
test('unsafe partial counters degrade rather than lose integer precision',()=>{
 const history=new PhysicalHistory();history.accept(fact({status:'interrupted',rows:Number.MAX_SAFE_INTEGER}));history.accept(fact({status:'interrupted',rows:1}));assert.equal(history.unavailable,true);assert.equal(history.snapshot()[0].partial_rows,Number.MAX_SAFE_INTEGER);
});
test('the complete identity envelope saturates at 1152 categories',()=>{
 const history=new PhysicalHistory();const kinds=['read','resident_sort','fisher_yates','grouping','serialize','materialize','elided','routed_grouping'];
 for(let operation=0;operation<36;operation++)for(let kind=0;kind<32;kind++)history.accept(fact({id:1000+operation*32+kind,operations:[operation%18,0],role:Math.floor(operation/18),kind:kinds[kind%kinds.length]}));
 assert.equal(history.snapshot().length,1152);assert.equal(history.unavailable,false);
 history.accept(fact({id:2152,operations:[18,0]}));assert.equal(history.snapshot().length,1152);assert.equal(history.unavailable,true);
});
test('handed-off routing and failed merge attempts retain distinct measured outcomes',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1044,kind:'routing',attempt:1,status:'active',rows:0,seconds:0,operations:[1,0],source:1000}));history.accept(fact({id:1044,kind:'routing',attempt:1,status:'handed_off',rows:32061,runs:64,seconds:1,operations:[1,0],source:1000}));
 const handed=history.snapshot()[0];assert.equal(handed.outcomes.handed_off.rows,32061);assert.equal(handed.outcomes.handed_off.runs,64);assert.equal(handed.outcomes.completed.rows,0);
 history.accept(fact({id:1041,kind:'merge',attempt:2,status:'failed',rows:2,runs:2,operations:[1,0],sources:[1040,1046]}));
 const merge=history.snapshot().find(s=>s.kind==='merge');assert.equal(merge.outcomes.failed.rows,2);assert.equal(merge.outcomes.completed.rows,0);assert.deepEqual(merge.sources,[1040,1046]);
});
test('duplicate terminal attempts do not double commit counters',()=>{
 const history=new PhysicalHistory();const completed=fact({attempt:7});history.accept(completed);history.accept(completed);assert.equal(history.snapshot()[0].rows,3);assert.equal(history.snapshot()[0].attempts,1);
});
test('strata and pipeline sorts retain distinct identities and original mappings',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1609,role:1,operations:[1,0]}));history.accept(fact({id:1033,role:0,operations:[1,2]}));
 assert.equal(history.snapshot().length,2);assert.deepEqual(history.snapshot().find(s=>s.role===1).operations,[1]);assert.deepEqual(history.snapshot().find(s=>s.role===0).operations,[1,2]);
});
test('actual memberships include zero groups without substituting target percentages',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1047,kind:'exact_membership',operations:[1,0],rows:6,groups:3,empty_groups:1,membership_len:3,memberships:[4,2,0],omitted_memberships:0}));
 const summary=history.snapshot()[0];assert.deepEqual(summary.memberships,[4,2,0]);assert.equal(summary.groups,3);assert.equal(summary.empty_groups,1);
});
test('membership snapshot arrays do not alias retained state',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1047,kind:'exact_membership',operations:[1,0],rows:6,groups:3,empty_groups:1,membership_len:3,memberships:[4,2,0]}));const snapshot=history.snapshot();snapshot[0].memberships[0]=99;snapshot[0].outcomes.completed.memberships[0]=88;assert.deepEqual(history.snapshot()[0].memberships,[4,2,0]);assert.deepEqual(history.snapshot()[0].outcomes.completed.memberships,[4,2,0]);
});
test('codec summaries retain decoded bytes separately from row counts',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1023,kind:'gzip_input',operations:[0,0],rows:0,bytes:1024,attempt:1}));
 const summary=history.snapshot()[0];assert.equal(summary.bytes,1024);assert.equal(summary.rows,0);assert.equal(summary.outcomes.completed.bytes,1024);
});
test('codec byte overflow degrades safely and direct writer sources remain inspectable',()=>{
 const history=new PhysicalHistory();history.accept(fact({id:1026,kind:'gzip_output',operations:[1,0],source:1,source_omitted:false,bytes:Number.MAX_SAFE_INTEGER,attempt:1}));
 history.accept(fact({id:1026,kind:'gzip_output',operations:[1,0],source:1,source_omitted:false,bytes:1,attempt:2}));assert.equal(history.unavailable,true);assert.equal(history.snapshot()[0].bytes,Number.MAX_SAFE_INTEGER);assert.deepEqual(history.snapshot()[0].sources,[1]);
});
test('delayed active updates cannot reopen a confirmed terminal attempt',()=>{
 const history=new PhysicalHistory();history.accept(fact({attempt:7,status:'completed'}));history.accept(fact({attempt:7,status:'active',rows:1}));history.accept(fact({attempt:6,status:'completed',rows:99}));
 const summary=history.snapshot()[0];assert.equal(summary.status,'completed');assert.equal(summary.rows,3);assert.equal(summary.attempts,1);
 history.accept(fact({attempt:8,status:'active',rows:1}));assert.equal(history.snapshot()[0].status,'active');assert.equal(history.snapshot()[0].rows,3);
});
test('source overflow stays at four dependencies and labels omitted detail',()=>{
 const h=new PhysicalHistory();h.accept(fact({sources:[1000,1001,1002,1003,1004],source_omitted:false}));assert.deepEqual(h.snapshot()[0].sources,[1000,1001,1002,1003]);assert.equal(h.snapshot()[0].source_omitted,true);assert.equal(h.unavailable,true);
});
test('repeated high-fanout parents retain only the bounded membership prefix',()=>{
 const h=new PhysicalHistory();for(let i=0;i<10000;i++)h.accept(fact({id:1047,kind:'exact_membership',operations:[1,0],rows:32,groups:32,membership_len:16,memberships:Array(16).fill(1),omitted_memberships:16}));const s=h.snapshot()[0];assert.equal(h.snapshot().length,1);assert.equal(s.groups,320000);assert.equal(s.memberships.length,16);assert.equal(s.omitted_memberships,160000);assert.ok(s.memberships.every(count=>count===10000));
});
