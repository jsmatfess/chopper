import assert from 'node:assert/strict';
import {mkdir,writeFile,symlink,readFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {roots,mutableEnvironment,freshChild} from './e1-followup-roots.mjs';
import {sourceIdentity,ownedFile} from './e1-followup-inputs.mjs';
const base=process.argv[2];assert(base&&resolve(base)===base,'fresh absolute fixture root required');await mkdir(base);
let passed=0;async function test(name,fn){await fn();passed++;console.log(JSON.stringify({passed:name}));}
const source=join(base,'source'),accounting=join(base,'accounting'),invocation=join(accounting,'e1-current'),scratch=join(invocation,'scratch'),old=join(accounting,'e1-followup-20261027-r02');
for(const p of [source,scratch,old])await mkdir(p,{recursive:true});
const ledger=join(old,'selftest-attempt-ledger.json');await writeFile(ledger,'{"attempt_count":0,"attempts":[]}');
const config={sourceRoot:source,invocationRoot:invocation,outputRoot:join(invocation,'output'),evidenceRoots:[invocation,old],scratchRoots:[scratch],accountingRoot:accounting,priorAttemptLedgers:[ledger]};
await test('complete concrete fixture config admitted',()=>roots(config));
for(const [name,change] of [['relative',{sourceRoot:'relative'}],['noncanonical',{outputRoot:invocation+'/a/../output'}],['overlap',{evidenceRoots:[invocation,old,scratch]}],['missing retained root',{evidenceRoots:[invocation]}],['missing ledger',{priorAttemptLedgers:[]}],['missing scratch',{scratchRoots:[]}],['escaped output',{outputRoot:join(base,'escaped')}]] )await test(name+' rejected',()=>assert.rejects(roots({...config,...change})));
await mkdir(join(invocation,'existing'));await test('existing output rejected',()=>assert.rejects(roots({...config,outputRoot:join(invocation,'existing')})));
await mkdir(join(scratch,'existing-profile'));await test('existing profile rejected',()=>assert.rejects(freshChild(scratch,join(scratch,'existing-profile'))));
const env={CARGO_NET_OFFLINE:'true'};for(const key of ['CARGO_HOME','CARGO_TARGET_DIR','TEMP','TMP','TMPDIR','npm_config_cache','npm_config_logs_dir']){env[key]=join(invocation,key);await mkdir(env[key]);}
await test('fresh task-owned mutable environment admitted before spawn',()=>mutableEnvironment(invocation,env));
await test('old Cargo home rejected before spawn',()=>assert.rejects(mutableEnvironment(invocation,{...env,CARGO_HOME:old})));
await symlink(old,join(invocation,'escape'),'junction');await test('linked Cargo home rejected before spawn',()=>assert.rejects(mutableEnvironment(invocation,{...env,CARGO_HOME:join(invocation,'escape')})));
await writeFile(join(old,'old.wasm'),'old');await test('artifact junction escape rejected',()=>assert.rejects(ownedFile(invocation,join(invocation,'escape','old.wasm'))));
await writeFile(join(invocation,'fresh.wasm'),'fresh');await test('fresh artifact admitted',()=>ownedFile(invocation,join(invocation,'fresh.wasm')));
// An ignored mirror deliberately has no Git metadata. Pin application, harness,
// locks and the entire vendor tree instead of accepting Git's empty listing.
const names=['Cargo.toml','Cargo.lock','ui/package.json','ui/package-lock.json','ui/tsconfig.json','crates/test/src/lib.rs','scripts/benchmark-e1-followup.mjs','ui/src/app.ts','ui/tests/e1-followup.ts','vendor/zip-2.4.2/src/lib.rs'];
for(const name of names){await mkdir(resolve(source,name,'..'),{recursive:true});await writeFile(join(source,name),'fixture');}
await test('ignored staged mirror pins complete bounded inputs and rejects drift',async()=>{const before=await sourceIdentity(source);assert.equal(before.length,names.length);await writeFile(join(source,'ui/src/app.ts'),'drift');assert.notDeepEqual(await sourceIdentity(source),before);});
await test('empty/incomplete manifest rejected',()=>assert.rejects(sourceIdentity(old)));
console.log(JSON.stringify({passed,browser_jobs:0,cargo_spawns:0}));
