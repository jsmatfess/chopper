// Same Node process as the owning harness: validation-runner remains its parent.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {validatePacket,validateGuard,bounded} from './browser-small-observer.mjs';
export async function handshake(packet,{read=()=>readFile(packet.guard,'utf8'),pid=process.pid,parent=process.ppid,now=Date.now,pause=ms=>new Promise(r=>setTimeout(r,ms))}={}){
 const deadline=now()+5000;
 while(now()<deadline){
  let value;
  try{value=JSON.parse(await bounded(read(),Math.max(1,deadline-now())));}catch(error){if(error.code!=='ENOENT')throw error;}
  if(value){
   // A pre-spawn heartbeat may have no child. Never accept a different child,
   // denial, stale heartbeat, wrong runner, or fabricated census while waiting.
   assert.equal(value.runner_pid,parent);
   if(value.child_pid!==null){validateGuard(value,packet,{initial:true,pid,parent,now:now()});return;}
   assert.equal(value.allowed,true);assert(!value.error);
   assert.equal(value.reservation,packet.reservation);assert.equal(value.reservation_held,true);
   assert.equal(value.windows_job_kill_on_close,true);assert(value.owned_pids.includes(parent));
   assert.equal(value.batch_started_ms,packet.batch_started_ms);
   assert(now()-value.batch_started_ms>=0&&now()-value.batch_started_ms<7200000);
   assert(now()-value.last_progress_ms>=0&&now()-value.last_progress_ms<600000);
   assert(value.cumulative_owned_bytes>=0&&value.cumulative_owned_bytes<packet.limits.stop_owned_bytes);
   assert.deepEqual(value.volumes.map(v=>v.path).sort(),[...packet.volumes].sort());
   assert(value.volumes.every(v=>v.free_bytes>=packet.limits.start_free_bytes&&Number.isFinite(v.sampled_ms)&&now()-v.sampled_ms>=-1000&&now()-v.sampled_ms<=packet.limits.disk_stale_ms));
   assert(now()-value.sampled_ms<=5000&&now()-value.sampled_ms>=-1000);
  }
  await pause(25);
 }
 throw new Error('SMALL own-PID handshake exceeded five seconds');
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 assert.equal(process.argv.length,3,'Usage: node browser-small-bootstrap.mjs ABSOLUTE_PACKET');
 const packet=JSON.parse(await readFile(resolve(process.argv[2]),'utf8'));
 validatePacket(packet,packet.channel,packet.argv);
 await handshake(packet);
 await import(pathToFileURL(fileURLToPath(new URL('./browser-small-contract.mjs',import.meta.url))).href);
}
