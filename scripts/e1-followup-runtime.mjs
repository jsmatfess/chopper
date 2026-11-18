// Harness-only shutdown ownership. Keep handles until process exit is observed.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {deadline,shutdown} from './e1-followup-controller.mjs';
export function processIdentity(pid){
  assert(Number.isSafeInteger(pid)&&pid>0&&pid!==process.pid,'owned PID required');
  assert.equal(process.platform,'win32','E1 owned-process observer currently requires Windows');
  const r=spawnSync('powershell',['-NoProfile','-Command',`Get-CimInstance Win32_Process -Filter "ProcessId = ${pid}" | Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress`],{timeout:5000,encoding:'utf8'});
  assert(!r.error&&r.status===0,'owned process inspection failed: '+(r.error||r.stderr));
  return r.stdout.trim()?JSON.parse(r.stdout):null;
}
export async function captureRuntime(context,browser,profile){
  const session=await deadline(5000).run(()=>browser.newBrowserCDPSession());let pid;
  try{const result=await deadline(5000).run(()=>session.send('SystemInfo.getProcessInfo'));pid=result.processInfo.find(p=>p.type==='browser')?.id;}finally{await deadline(5000).run(()=>session.detach());}
  const identity=processIdentity(pid);assert(identity,'browser ownership unavailable');
  if(profile)assert(identity.CommandLine.includes(profile),'browser profile ownership mismatch');
  return {context,browser,pid,identity,profile,exit_observed:false};
}
export async function closeOwnedRuntime(owner,{inspect=processIdentity,kill=(pid)=>process.kill(pid,'SIGKILL'),milliseconds=10000,pause=()=>new Promise(r=>setTimeout(r,25))}={}){
  const errors=[];
  await shutdown([['context-close',()=>deadline(milliseconds).run(()=>owner.context?.close())],['browser-close',()=>deadline(milliseconds).run(()=>owner.browser?.isConnected()?owner.browser.close():undefined)]],errors);
  const same=actual=>actual&&JSON.stringify(actual)===JSON.stringify(owner.identity);
  let actual=inspect(owner.pid);
  if(actual){
    assert(same(actual),'owned PID identity changed; refusing stop');
    owner.fallback={pid:owner.pid,identity_rechecked:true,signal:'SIGKILL'};
    kill(owner.pid);
    const bound=deadline(milliseconds);
    do{await bound.run(pause);actual=inspect(owner.pid);if(actual)assert(same(actual),'PID reused while awaiting owned exit');}while(actual);
  }
  owner.exit_observed=true;owner.disconnected=!owner.browser?.isConnected();
  assert(owner.disconnected,'browser process exited but connection remains');
  owner.context=null;owner.browser=null;
  if(errors.length){const error=new Error('runtime shutdown failed');error.secondary=errors;error.ownership={pid:owner.pid,identity:owner.identity,exit_observed:owner.exit_observed,fallback:owner.fallback};throw error;}
  return {pid:owner.pid,identity:owner.identity,exit_observed:true,disconnected:owner.disconnected,fallback:owner.fallback??null};
}
export async function stopServer(server,{milliseconds=10000}={}){
  const result={pid:server.pid,exit_observed:server.exitCode!==null||server.signalCode!==null};
  if(!result.exit_observed){
    const exit=new Promise((ok,fail)=>{server.once('close',(code,signal)=>ok({code,signal}));server.once('error',fail);});
    result.stop_requested=server.kill();
    try{Object.assign(result,await deadline(milliseconds).run(()=>exit));}catch(primary){result.fallback_stop_requested=server.kill('SIGKILL');Object.assign(result,await deadline(milliseconds).run(()=>exit));result.primary=String(primary);result.exit_observed=true;const error=new Error(String(primary));error.shutdown=result;throw error;}
    result.exit_observed=true;
  }
  result.code=server.exitCode;result.signal=server.signalCode;return result;
}
