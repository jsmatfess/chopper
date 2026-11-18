'use strict';
const assert=require('node:assert/strict');
const readline=require('node:readline');
class Counter {
  constructor(){this.runs=0;this.cancels=0;this.picks=0;this.headerReads=0;this.submitted=null;this.expected=null;}
  request(path,body){
    if(path==='/api/columns'){assert.ok(this.headerReads<2);this.headerReads++;assert.equal(body.input,this.expected.input);assert.deepEqual(body.input_csv,this.expected.input_csv);}
    if(path==='/api/pick-path'){this.picks++;throw Error('happy actual pickers already reused; no new picker');}
    if(['/api/run','/api/run-direct','/api/analyze','/api/profile'].includes(path)){
      assert.equal(path,'/api/run-direct');assert.ok(this.expected);assert.ok(this.runs<1);
      assert.deepEqual(body,this.expected);this.submitted=body;this.runs++;
    }
    if(path==='/api/cancel'){assert.equal(this.runs,1);assert.equal(this.cancels,0);this.cancels++;}
  }
}
function qualifies(state,requested,http,caseName){return requested===true&&http===200&&state.status==='cancelled'&&typeof state.error==='string'&&state.error.toLowerCase().includes('cancelled')&&!state.error.toLowerCase().includes('cleanup')&&Number.isSafeInteger(state.progress?.rows)&&state.progress.rows>=0&&typeof state.progress.phase==='string'&&state.progress.phase.length>0&&(caseName!=='export-cancel'||state.progress.rows>0)&&(state.progress.phase==='Writing output')===(caseName==='export-cancel');}
async function configureProcessing(page){
  for(let index=0;index<17;index++){
    const partition=index%2===1;
    await page.locator('#new-operation').selectOption(partition?'partition':'shuffle');
    await page.locator('#add-operation').click();
    const step=page.locator('#operations [data-step]').nth(index);
    if(!partition)await step.locator('[data-field="strategy"]').selectOption('uniform');
    else{
      // Input settings already triggered the native UI's ordinary read-only /api/columns.
      await step.locator('[data-column-search]').fill('v');
      const option=step.locator('[data-column-option="0"]');
      assert.equal(await option.locator('span').textContent(),'v');
      await option.click();
      assert.equal(await step.locator('.column-chip span').textContent(),'v');
    }
  }
  assert.equal(await page.locator('#operations [data-step]').count(),17);
}
async function configureExport(page){
  // A real operation selects prepared export; the empty seeded pipeline streams Reading and writing CSV.
  await page.locator('#new-operation').selectOption('shuffle');
  await page.locator('#add-operation').click();
  await page.locator('#operations [data-step]').nth(0).locator('[data-field="strategy"]').selectOption('uniform');
  assert.equal(await page.locator('#operations [data-step]').count(),1);
}
async function exercise(page,cfg,emit,gate){
  const count=new Counter();let violation=null;
  page.on('request',r=>{try{count.request(new URL(r.url()).pathname,r.method()==='POST'?r.postDataJSON():null);}catch(e){violation=e;}});
  for(const summary of await page.locator('details > summary').all())await summary.click();
  assert.equal(await page.locator('#operations [data-step]').count(),0);
  await page.locator('#memory-mode').selectOption('manual');
  await page.locator('#compression').selectOption('none');await page.locator('#grouping').selectOption('auto');
  for(const prefix of ['input','output'])await page.locator('#'+prefix+'-csv [data-csv="line_ending"]').selectOption('lf');
  for(const c of cfg.cases){
    count.expected=c.job;
    const fields={input:c.job.input,output:c.job.output,'max-rows':c.job.limits.rows===null?'':String(c.job.limits.rows),'max-bytes':String(c.job.limits.bytes),seed:c.job.seed,workers:'1',memory:'64','max-files':String(c.job.resources.max_files),'max-record':'64','temp-dir':c.job.resources.temp_dir,'temp-bytes':String(c.job.resources.temp_bytes)};
    for(const [id,v] of Object.entries(fields))await page.locator('#'+id).fill(v);
    if(c.name==='processing-cancel')await configureProcessing(page);else await configureExport(page);
    assert.equal(await page.locator('#operations [data-step]').count(),c.name==='processing-cancel'?17:1);
    if(violation)throw violation;
    let order=0, activeBeforeCancel=null,activeOrder=0,cancelOrder=0,terminalOrder=0;
    // Inspect only responses caused by the real UI's ordinary polling.
    const terminal=page.waitForResponse(async r=>{
      if(new URL(r.url()).pathname!=='/api/state'||r.status()!==200)return false;
      const s=await r.json();const done=s.output===c.job.output&&['complete','failed','cancelled'].includes(s.status);if(done)terminalOrder=++order;return done;
    },{timeout:30000});terminal.catch(()=>{});
    let cancelRequested=false,cancelHTTP=null,cancelClick=null,captureInstalledUnixMs=null,preClickUnixMs=null;
    // Read-only public status observation at25ms avoids waiting for the UI's slower display poll.
    // A state can still finish before the click; terminal qualification rejects that race.
    const ack=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/run-direct',{timeout:15000});
    const token=new URLSearchParams(new URL(cfg.url).hash.slice(1)).get('token');assert.ok(token);
    let polling=false,lastObservedState=null,lastPhase=null;
    const selectionObservation={startedUnixMs:Date.now(),deadlineUnixMs:null,polls:0,errors:0,lastError:null,phaseHistory:[],omittedTransitions:0};
    const timer=setInterval(()=>{
      if(polling)return;polling=true;const startedUnixMs=Date.now();
      page.request.get(new URL('/api/state',page.url()).href,{headers:{'X-Chopper-Token':token},timeout:1000})
        .then(async r=>{
          const s=await r.json();await r.dispose();lastObservedState=s;selectionObservation.polls++;
          const phase=JSON.stringify([s.status,s.progress?.phase]);
          if(phase!==lastPhase){
            lastPhase=phase;
            if(selectionObservation.phaseHistory.length<8)selectionObservation.phaseHistory.push({startedUnixMs,finishedUnixMs:Date.now(),status:s.status,phase:s.progress?.phase,rows:s.progress?.rows});
            else selectionObservation.omittedTransitions++;
          }
          if(!activeBeforeCancel&&s.output===c.job.output&&s.status==='running'&&s.progress?.rows>0&&(s.progress.phase==='Writing output')===(c.name==='export-cancel')){activeBeforeCancel=s;activeOrder=++order;}
        }).catch(error=>{selectionObservation.errors++;selectionObservation.lastError=String(error).slice(0,512);}).finally(()=>{polling=false;});
    },25);
    let state;
    try{
      await page.locator('#run-direct').click({timeout:5000});
      const reply=await ack;assert.equal(reply.status(),200);await reply.finished();
      // The request context does not emit page response events; wait on the shared observation too.
      const end=Date.now()+30000;selectionObservation.deadlineUnixMs=end;
      while(!activeBeforeCancel&&Date.now()<end&&!(lastObservedState?.output===c.job.output&&['complete','failed','cancelled'].includes(lastObservedState.status)))await new Promise(resolve=>setTimeout(resolve,5));
      assert.ok(activeBeforeCancel,'no active selected phase observed; one attempt stops unaccepted');
      const cancel=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/cancel',{timeout:2000});cancel.catch(()=>{});
      captureInstalledUnixMs=await page.evaluate(()=>{
        window.__nativeSmokeCancelClick=null;
        document.querySelector('#cancel').addEventListener('click',event=>{
          window.__nativeSmokeCancelClick={trusted:event.isTrusted,unixMs:Date.now(),monotonicMs:performance.now(),eventTimestamp:event.timeStamp,status:document.querySelector('#status').textContent,phase:document.querySelector('#phase').textContent};
        },{capture:true,passive:true,once:true});
        return Date.now();
      });
      preClickUnixMs=Date.now();cancelOrder=++order;
      await page.locator('#cancel').click({timeout:1500});cancelRequested=true;
      cancelClick=await page.evaluate(()=>window.__nativeSmokeCancelClick);
      assert.ok(cancelClick?.trusted&&captureInstalledUnixMs<=preClickUnixMs&&preClickUnixMs<=cancelClick.unixMs,'actual trusted public Cancel click required');
      const r=await cancel;cancelHTTP=r.status();await r.finished();
      state=await (await terminal).json();
    }catch(e){emit({kind:'cancel-race',detail:String(e),selectionObservation,activeBeforeCancel,lastObservedState,cancelRequested,cancelHTTP,cancelClick,captureInstalledUnixMs,preClickUnixMs,activeOrder,cancelOrder,terminalOrder});throw e;}finally{clearInterval(timer);}
    if(violation)throw violation;
    const result={kind:'case-result',case:c.name,selectionObservation,state,submitted:count.submitted,runs:count.runs,cancels:count.cancels,picks:count.picks,headerReads:count.headerReads,cancelRequested,cancelHTTP,cancelClick,captureInstalledUnixMs,preClickUnixMs,terminalUnixMs:Date.now(),activeBeforeCancel,activeOrder,cancelOrder,terminalOrder,qualifies:qualifies(state,cancelRequested,cancelHTTP,c.name)};
    emit(result);await gate(c.name);
  }
  assert.equal(count.runs,1);assert.equal(count.cancels,1);assert.equal(count.picks,0);
  return {kind:'suite-result',runs:count.runs,cancels:count.cancels,picks:count.picks,headerReads:count.headerReads};
}
module.exports={Counter,qualifies,configureProcessing,configureExport,exercise};
if(require.main===module)(async()=>{
  assert.equal(process.platform,'win32');
  const input=readline.createInterface({input:process.stdin});const lines=input[Symbol.asyncIterator]();
  const receive=async()=>{const v=await lines.next();assert.equal(v.done,false);return JSON.parse(v.value);};
  const emit=v=>process.stdout.write(JSON.stringify(v)+'\n');let context;
  try{
    const cfg=await receive();assert.equal(cfg.phase,'native-ui-smoke');assert.equal(process.version,cfg.nodeVersion);
    const {chromium}=require(cfg.playwrightRoot);
    context=await chromium.launchPersistentContext(cfg.profile,{executablePath:cfg.browser,headless:false,timeout:20000,acceptDownloads:false,args:['--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disk-cache-size=1048576','--media-cache-size=1048576']});
    assert.match(cfg.browserVersion,/^\d+\.\d+\.\d+\.\d+$/);assert.equal(context.browser().version(),cfg.browserVersion);emit({kind:'browser-version',version:context.browser().version()});
    const page=context.pages()[0];assert.ok(page);
    const initial=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/state',{timeout:15000});
    await page.goto(cfg.url,{waitUntil:'domcontentloaded',timeout:15000});await initial;
    emit(await exercise(page,cfg,emit,async name=>assert.deepEqual(await receive(),{verified:name})));
  }finally{try{if(context)await context.close();emit({kind:'browser-closed'});}finally{input.close();}}
})().catch(e=>{process.stderr.write(String(e.stack)+'\n');process.exitCode=1;});
