import assert from 'node:assert/strict';
import {lstat,realpath,readdir,readFile,statfs} from 'node:fs/promises';
import {isAbsolute,resolve,relative,dirname,join} from 'node:path';
import {createHash} from 'node:crypto';
const inside=(parent,child)=>{const r=relative(parent,child);return r===''||(!r.startsWith('..')&&!isAbsolute(r));};
export async function roots(config){
  const canonical=async p=>{assert(typeof p==='string'&&isAbsolute(p),'absolute root required');assert.equal(p,resolve(p),'noncanonical root');const actual=await realpath(p);assert.equal(resolve(p).toLowerCase(),actual.toLowerCase(),'noncanonical root');return actual;};
  const source=await canonical(config.sourceRoot),invocation=await canonical(config.invocationRoot);
  assert.notEqual(source.toLowerCase(),invocation.toLowerCase(),'distinct source/invocation roots required');
  assert(isAbsolute(config.outputRoot),'absolute output required');
  assert.equal(config.outputRoot,resolve(config.outputRoot),'noncanonical output');
  const output=join(await canonical(dirname(config.outputRoot)),config.outputRoot.split(/[\\/]/).at(-1));
  assert(inside(invocation,output)&&output!==invocation,'output ownership');
  await assert.rejects(lstat(output),{code:'ENOENT'},'existing output refused');
  const evidence=await Promise.all(config.evidenceRoots.map(canonical)),scratch=await Promise.all(config.scratchRoots.map(canonical));
  assert(evidence.includes(invocation),'invocation evidence root missing');
  for(const list of [evidence,scratch])for(let i=0;i<list.length;i++)for(let j=0;j<i;j++)assert(!inside(list[i],list[j])&&!inside(list[j],list[i]),'overlapping category roots');
  assert(scratch.length>0&&inside(invocation,scratch[0])&&scratch[0]!==invocation,'current scratch ownership');
  assert(scratch.every(p=>evidence.some(owner=>inside(owner,p)&&p!==owner)&&!inside(output,p)&&!inside(p,output)),'aggregate scratch ownership');
  // The concrete checkout's retained E1 roots cannot be omitted by a caller.
  const accounting=await canonical(config.accountingRoot);
  for(const name of await readdir(accounting))if(name.startsWith('e1-'))assert(evidence.includes(await canonical(join(accounting,name))),'retained E1 evidence root omitted: '+name);
  const requiredLedger=join(accounting,'e1-followup-20261027-r02','selftest-attempt-ledger.json');
  assert(config.priorAttemptLedgers?.includes(requiredLedger),'concrete retained tiny ledger omitted');
  await readFile(requiredLedger);
  for(const name of ['tiny-temp','tiny-profile'])await freshChild(scratch[0],join(scratch[0],name));
  return {source,invocation,output,evidence,scratch};
}
export async function freshChild(owner,p){
  assert(isAbsolute(p)&&resolve(p)===p,'canonical absolute child required');
  const actual=await realpath(owner);assert(inside(actual,p)&&actual!==p,'child ownership');
  const parent=await realpath(dirname(p));assert(inside(actual,parent),'child ancestor escape');
  assert.equal(parent.toLowerCase(),resolve(dirname(p)).toLowerCase(),'linked child ancestor');
  await assert.rejects(lstat(p),{code:'ENOENT'},'existing child refused');return p;
}
export async function mutableEnvironment(owner,env){
  const base=await realpath(owner);
  for(const key of ['CARGO_HOME','CARGO_TARGET_DIR','TEMP','TMP','TMPDIR','npm_config_cache','npm_config_logs_dir']){
    const p=env[key];assert(typeof p==='string'&&isAbsolute(p)&&resolve(p)===p,'canonical mutable '+key+' required');
    const actual=await realpath(p);assert.equal(actual.toLowerCase(),p.toLowerCase(),'linked mutable '+key);
    assert(inside(base,actual)&&base!==actual,'mutable '+key+' escaped invocation');
  }
  assert(env.CARGO_NET_OFFLINE==='true','offline Cargo required');
  return {owner:base,paths:Object.fromEntries(Object.entries(env).filter(([k])=>/^(CARGO_|TEMP$|TMP$|TMPDIR$|npm_)/.test(k)))};
}
export async function census(rootPaths,excluded=[]){
  let bytes=0;const links=[];
  async function walk(p){
    if(excluded.includes(p))return;
    const st=await lstat(p);
    if(st.isSymbolicLink()){
      const target=await realpath(p);
      links.push({path:p,target,external_to_roots:!rootPaths.some(r=>inside(r,target)),excluded_bytes:true});return;
    }
    if(st.isDirectory())for(const name of await readdir(p))await walk(join(p,name));
    else if(st.isFile())bytes+=st.size;
  }
  for(const p of rootPaths)await walk(p);
  return {bytes,links};
}
export async function budget(r,{evidenceExpansion=0,scratchExpansion=0,finalReserve=1024**3}={}){
  const evidence=await census(r.evidence,r.scratch),scratch=await census(r.scratch),disk=await statfs(r.invocation);
  assert(evidence.bytes+evidenceExpansion+finalReserve<=25*1024**3,'aggregate evidence/build budget exhausted');
  assert(scratch.bytes+scratchExpansion<=1024**3,'aggregate scratch/profile budget exhausted');
  assert(disk.bavail*disk.bsize>=evidenceExpansion+scratchExpansion+finalReserve,'disk headroom exhausted');
  return {utc:new Date().toISOString(),evidence,scratch,available_disk_bytes:disk.bavail*disk.bsize,final_reserve_bytes:finalReserve};
}
export async function priorAttempts(paths){
  assert(Array.isArray(paths)&&paths.length>0,'retained attempt ledgers required');
  let attempts=0;const identities=[];
  for(const path of paths){
    assert(isAbsolute(path),'absolute prior ledger required');const bytes=await readFile(path);
    const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
    if(path.endsWith('.jsonl')){const rows=text.trim()?text.trim().split('\n').map(JSON.parse):[];attempts+=rows.filter(x=>x.type==='attempt-start').length;}
    else {const ledger=JSON.parse(text);assert(Number.isSafeInteger(ledger.attempt_count)&&ledger.attempt_count>=0&&Array.isArray(ledger.attempts)&&ledger.attempts.length===ledger.attempt_count,'invalid retained attempt ledger');attempts+=ledger.attempt_count;}
    identities.push({path,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});
  }
  return {attempts,identities};
}
