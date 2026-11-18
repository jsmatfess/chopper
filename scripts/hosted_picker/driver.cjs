'use strict';
const assert=require('node:assert/strict');
const readline=require('node:readline');
const {run}=require('./hosted.cjs');
function validateConfig(cfg){
  assert.equal(cfg.phase,'hosted-tiny-qualification');assert(['chrome','msedge'].includes(cfg.channel));assert(['success','failure','observe-input','observe-output','observe-permission','processing-cancel','export-cancel','malformed-retry'].includes(cfg.case));
  assert.equal(cfg.parentReviewed,true);assert.equal(cfg.layoutReviewComplete,true);
}
module.exports={validateConfig};
async function main(){
  assert.equal(process.platform,'win32');
  const lines=readline.createInterface({input:process.stdin});
  const iterator=lines[Symbol.asyncIterator]();
  const receive=async()=>{const r=await iterator.next();assert.equal(r.done,false,'parent EOF');return JSON.parse(r.value);};
  try{
    const cfg=await receive();
    validateConfig(cfg);
    assert.equal(process.version,cfg.nodeVersion,'selected Node runtime version changed');
    const {chromium}=require(cfg.playwrightRoot);
    await run(chromium,cfg,v=>process.stdout.write(JSON.stringify(v)+'\n'),receive);
  }finally{lines.close();}
}
if(require.main===module)main().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
