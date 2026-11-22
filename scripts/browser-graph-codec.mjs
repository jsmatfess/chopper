// Independent Graph fixture caller; protected SMALL tools come only from its packet.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync,realpathSync,lstatSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {isAbsolute,resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const helper=fileURLToPath(new URL('graph-codec-fixtures.py',import.meta.url));
export function validateGraphCodecPacket(packet){
 for(const path of [packet.python,helper]){
  assert(typeof path==='string'&&isAbsolute(path),'Absolute Graph Python/DLL/helper path required');
  assert.equal(resolve(path),path,'Canonical Graph tool path required');
  const inputs=packet.inputs.filter(input=>input.path===path);
  assert.equal(inputs.length,1,`Exactly one pinned Graph input required: ${path}`);
  assert(/^[a-f0-9]{64}$/.test(inputs[0].sha256),'Graph input hash required');
 }
}
export function verifyGraphCodecInputs(packet){
 validateGraphCodecPacket(packet);
 for(const path of [packet.python,helper]){
  assert.equal(realpathSync(path),path,'Canonical Graph tool path required');
  for(let part=path;;part=dirname(part)){
   assert(!lstatSync(part).isSymbolicLink(),'Graph input alias rejected');
   if(dirname(part)===part)break;
  }
  const info=lstatSync(path);assert(info.isFile()&&info.size>0,'Nonempty regular Graph input required');
  assert.equal(createHash('sha256').update(readFileSync(path)).digest('hex'),packet.inputs.find(input=>input.path===path).sha256,`Graph input drift: ${path}`);
 }
}
export function codecFixture(mode,payload,packet=null,spawn=spawnSync){
 if(packet)verifyGraphCodecInputs(packet);
 const args=[helper,mode];
 // Preserve the owning caller's inherited cwd/env/console and Python flags.
 const result=spawn(packet?packet.python:'python3',args,{input:payload,maxBuffer:64*1024*1024});
 if(result.error)throw result.error;
 assert.equal(result.status,0,result.stderr?.toString());return result.stdout;
}
