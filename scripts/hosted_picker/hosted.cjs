'use strict';
const assert=require('node:assert/strict');

async function failedGateDiagnostic(page,mode){
  return page.evaluate(mode=>{
    const read=id=>{const n=document.getElementById(id);return n?{
      id,disabled:!!n.disabled,hidden:!!n.hidden,ariaDisabled:n.getAttribute('aria-disabled'),
      value:typeof n.value==='string'?n.value.slice(0,256):null,text:(n.textContent||'').slice(0,id==='error'?2048:256)}:{id,missing:true};};
    return {kind:'hosted-browse-failed-gate-dom',mode,acceptance:false,runs:0,
      nodes:['input','output','error','status','phase','progress-detail','cancel','browse-input','browse-output','run-direct'].map(read)};
  },mode);
}

function cancellationObservation(value,which){
  assert(['processing-cancel','export-cancel'].includes(which));
  assert.equal(value.status,'RUNNING','completion before Cancel does not qualify');
  if(which==='export-cancel'){
    const match=/^Saving results \((\d+)\/(\d+)\)$/.exec(value.phase);
    assert(match&&Number.isSafeInteger(Number(match[1]))&&Number.isSafeInteger(Number(match[2]))&&Number(match[1])>0&&Number(match[1])<=Number(match[2]),'completed-file export progress required');
  }
  else{
    const preparation=/^Preparing operation ([2-9]|1[0-7]) of 17$/.test(value.phase);
    const positive=value.rows>0&&['Reading CSV','Reading and validating CSV','Serializing output'].includes(value.phase);
    assert(Number.isSafeInteger(value.rows)&&value.rows>=0&&(preparation||positive),'actual processing phase required');
  }
  return value;
}
function installCancelCapture(){
  if(globalThis.__chopper105CancelCapture)throw Error('existing cancellation observer');
  const button=document.querySelector('#cancel');if(!button)throw Error('public Cancel absent');
  const capture={installed:{unixMs:Date.now(),monotonicMs:performance.now()},events:[]};
  capture.listener=event=>{capture.events.push({status:document.querySelector('#status').textContent.trim(),
    phase:document.querySelector('#phase').textContent,
    rows:Number((document.querySelector('#progress-detail').textContent.match(/^([\d,]+) rows/)||[])[1]?.replaceAll(',','')||0),
    unixMs:Date.now(),monotonicMs:performance.now(),eventTimeStamp:event.timeStamp,trusted:event.isTrusted,type:event.type});};
  button.addEventListener('click',capture.listener,{capture:true,passive:true,once:true});
  globalThis.__chopper105CancelCapture=capture;return capture.installed;
}
function takeCancelCapture(){
  const capture=globalThis.__chopper105CancelCapture;if(!capture)return null;
  document.querySelector('#cancel').removeEventListener('click',capture.listener,true);
  delete globalThis.__chopper105CancelCapture;
  return {installed:capture.installed,events:capture.events,taken:{unixMs:Date.now(),monotonicMs:performance.now()}};
}
async function cancelCurrent(page,which,emit){
  const read=()=>({status:document.querySelector('#status').textContent.trim(),
    phase:document.querySelector('#phase').textContent,
    rows:Number((document.querySelector('#progress-detail').textContent.match(/^([\d,]+) rows/)||[])[1]?.replaceAll(',','')||0),
    unixMs:Date.now(),monotonicMs:performance.now()});
  await page.waitForFunction(which=>{
    const value={status:document.querySelector('#status').textContent.trim(),phase:document.querySelector('#phase').textContent,
      rows:Number((document.querySelector('#progress-detail').textContent.match(/^([\d,]+) rows/)||[])[1]?.replaceAll(',','')||0)};
    if(['COMPLETE','FAILED','CANCELLED'].includes(value.status))throw Error('terminal before cancellation phase');
    const preparation=/^Preparing operation ([2-9]|1[0-7]) of 17$/.test(value.phase);
    const positive=value.rows>0&&['Reading CSV','Reading and validating CSV','Serializing output'].includes(value.phase);
    const match=/^Saving results \((\d+)\/(\d+)\)$/.exec(value.phase);
    const exporting=match&&Number.isSafeInteger(Number(match[1]))&&Number.isSafeInteger(Number(match[2]))&&Number(match[1])>0&&Number(match[1])<=Number(match[2]);
    return value.status==='RUNNING'&&(which==='export-cancel'?!!exporting:Number.isSafeInteger(value.rows)&&value.rows>=0&&(preparation||positive));
  },which,{timeout:30000,polling:'raf'});
  const active=cancellationObservation(await page.evaluate(read),which);
  emit({kind:'cancel-active-observed',case:which,active});
  await page.evaluate(installCancelCapture);
  let taken=false;
  try{
    const beforeClick=cancellationObservation(await page.evaluate(read),which);
    await page.locator('#cancel').click({timeout:1500});
    const capture=await page.evaluate(takeCancelCapture);taken=true;
    emit({kind:'cancel-click-observed',case:which,active,beforeClick,capture});
    assert(capture&&capture.events.length===1,'one actual Cancel click required');
    const click=cancellationObservation(capture.events[0],which);
    assert.equal(click.trusted,true);assert.equal(click.type,'click');
    const stamps=[active,capture.installed,beforeClick,click,capture.taken].map(x=>x.monotonicMs);
    assert(stamps.every(Number.isFinite)&&stamps.every((x,i)=>!i||x>=stamps[i-1]));
    return {active,beforeClick,capture};
  }finally{if(!taken)await page.evaluate(takeCancelCapture);}
}

async function repeatInput(page,stage,name,runs,emit,gate){
  assert(['malformed','retry'].includes(stage));
  emit({kind:'repeat-browse-start',stage,mode:'input',unixMs:Date.now()});
  await page.locator('#browse-input').click({timeout:5000});
  emit({kind:'repeat-browse-clicked',stage,mode:'input',unixMs:Date.now()});
  assert.deepEqual(await gate('repeat-input'),{selected:'input'});
  await page.waitForFunction(name=>document.querySelector('#input').value===name&&!document.querySelector('#browse-input').disabled,name,{timeout:5000});
  assert.equal(await page.locator('#input').inputValue(),name);
  assert.equal(await page.locator('#output').inputValue(),'output');
  emit({kind:'repeat-input-selected',stage,filename:name,output:'output',acceptance:false,byteConsumptionProven:false});
  assert.deepEqual(await gate('repeat-input-verified'),{inputVerified:true});
  emit({kind:'repeat-ready-to-run',stage,runs,output:'output'});
  assert.deepEqual(await gate('repeat-run'),{runApproved:true});
  await page.locator('#run-direct').click({timeout:5000});emit({kind:'repeat-run-clicked',stage,runs:runs+1});
  // Run acknowledgement can leave the previous terminal status visible.
  await page.waitForFunction(wanted=>document.querySelector('#status').textContent.trim()===wanted,stage==='malformed'?'FAILED':'COMPLETE',{timeout:45000});
}
function completedPath(text){
  const match=/^✓ Complete\. Results saved to (output\/chopper-results-[a-f0-9-]{36})$/.exec(text.trim());
  assert.ok(match,'public completed output path');return match[1];
}
async function retiredWorkspace(page){
  await page.waitForFunction(async()=>{
    const root=await navigator.storage.getDirectory();let folder;
    try{folder=await root.getDirectoryHandle('chopper-workspaces');}catch(error){if(error.name!=='NotFoundError')throw error;}
    if(folder)for await(const entry of folder.entries())return false;
    return !(await navigator.locks.query()).held.some(lock=>lock.name.startsWith('chopper-'));
  },null,{timeout:20000});
  return page.evaluate(async()=>{
    const root=await navigator.storage.getDirectory();let folder;const workspaces=[];
    try{folder=await root.getDirectoryHandle('chopper-workspaces');}catch(error){if(error.name!=='NotFoundError')throw error;}
    if(folder)for await(const [name] of folder.entries()){if(workspaces.length>=16)throw Error('workspace census bound');workspaces.push(name);}
    const locks=(await navigator.locks.query()).held.filter(lock=>lock.name.startsWith('chopper-')).map(lock=>lock.name);
    return {workspaces:workspaces.sort(),locks:locks.sort()};
  });
}

async function exercise(page,cfg,emit,gate){
  assert.equal(cfg.phase,'hosted-tiny-qualification');
  assert.equal(cfg.layoutReviewComplete,true);
  let unexpected=false;
  page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))unexpected=true;});
  assert.equal(await page.locator('#input').inputValue(),'');
  assert.equal(await page.locator('#output').inputValue(),'');
  const cancelling=['processing-cancel','export-cancel'].includes(cfg.case);
  const selected=cfg.runJob||cfg.job;
  const imported={...selected,input:'',output:''};
  if(!cancelling){assert.equal(imported.limits.bytes,40);assert.deepEqual(imported.operations,[]);}
  await page.locator('#import-file').setInputFiles({name:'tiny-job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(imported))});
  await page.waitForFunction(wanted=>document.querySelector('#seed').value===wanted.seed && document.querySelector('#max-bytes').value===String(wanted.bytes),{seed:selected.seed,bytes:selected.limits.bytes},{timeout:5000});
  for(const [id,wanted] of Object.entries({'max-bytes':String(selected.limits.bytes),'seed':selected.seed,'memory':String(selected.resources?.memory_mb||32),'workers':'1','compression':'none'}))assert.equal(await page.locator('#'+id).inputValue(),wanted);
  let mode='input';
  try{
    emit({kind:'browse-start',mode,unixMs:Date.now()});
    await page.locator('#browse-input').click({timeout:5000});
    emit({kind:'browse-clicked',mode,unixMs:Date.now()});
    const inputGate=await gate(mode);
    if(cfg.case==='observe-input'){assert.deepEqual(inputGate,{inputObserved:true});return {kind:'picker-observation-complete',case:cfg.case,runs:0,acceptance:false};}
    assert.deepEqual(inputGate,{selected:'input'});
    const inputName=cfg.inputName||'tiny.csv';
    await page.waitForFunction(name=>document.querySelector('#input').value===name &&
      !document.querySelector('#browse-input').disabled,inputName,{timeout:5000});
    assert.equal(await page.locator('#input').inputValue(),inputName);
    assert.equal(await page.locator('#output').inputValue(),'');
    assert.equal(await page.locator('#error').isVisible(),false);
    const dom=await failedGateDiagnostic(page,mode);
    emit({kind:'input-selected',filename:inputName,output:'',dom,acceptance:false,byteConsumptionProven:false});
    assert.deepEqual(await gate('input-verified'),{inputVerified:true});
    mode='output';
    emit({kind:'browse-start',mode,unixMs:Date.now()});
    await page.locator('#browse-output').click({timeout:5000});
    emit({kind:'browse-clicked',mode,unixMs:Date.now()});
    const outputGate=await gate(mode);
    if(cfg.case==='observe-output'){assert.deepEqual(outputGate,{outputObserved:true});return {kind:'picker-observation-complete',case:cfg.case,runs:0,acceptance:false};}
    assert.deepEqual(outputGate,{postClickObserved:true});
    let postDom;
    try{postDom=await failedGateDiagnostic(page,'post-output-click');}
    catch(error){postDom={kind:'hosted-browse-dom-unavailable',error:String(error).slice(0,512)};}
    emit({kind:'post-click-dom',dom:postDom,acceptance:false,runs:0,outputConfirmationRequired:false});
    const permissionGate=await gate('post-click-dom');
    if(cfg.case==='observe-permission'){assert.deepEqual(permissionGate,{permissionObserved:true});return {kind:'picker-observation-complete',case:cfg.case,runs:0,acceptance:false};}
    assert.deepEqual(permissionGate,{permissionInvoked:true});
    await page.waitForFunction(()=>document.querySelector('#output').value==='output' && !document.querySelector('#browse-output').disabled,null,{timeout:5000});
    assert.equal(await page.locator('#output').inputValue(),'output');
    assert.equal(await page.locator('#error').isVisible(),false);
    assert.equal(unexpected,false);
    if(cancelling){
      for(const [id,wanted] of Object.entries({'max-rows':selected.limits.rows===null?'':String(selected.limits.rows),'max-files':String(selected.resources.max_files),'max-record':String(selected.resources.max_record_bytes)}))assert.equal(await page.locator('#'+id).inputValue(),wanted);
      assert.equal(await page.locator('#operations [data-step]').count(),selected.operations.length);
    }
    if(cfg.case==='failure')await page.locator('#max-bytes').fill('1');
    emit({kind:'ready-to-run',runs:0,output:'output',permissionConfirmed:true});
    assert.deepEqual(await gate('run'),{runApproved:true});
    await page.locator('#run-direct').click({timeout:5000});emit({kind:'run-clicked',runs:1});
    const active=cancelling?await cancelCurrent(page,cfg.case,emit):null;
    await page.waitForFunction(()=>['COMPLETE','FAILED','CANCELLED'].includes(document.querySelector('#status').textContent.trim()) || !document.querySelector('#error').hidden,null,{timeout:45000});
    if(cancelling||cfg.case==='failure'){
      assert.equal((await page.locator('#status').textContent()).trim(),cancelling?'CANCELLED':'FAILED');
      if(!cancelling)assert.equal(await page.locator('#error').isVisible(),true);
      const error=await page.locator('#error').textContent();
      if(cancelling){assert(!error||!error.toLowerCase().includes('cleanup failed'));if(cfg.case==='export-cancel')assert(error&&error.includes('Export cancelled.'));}
      else assert(error && error.includes('header/BOM exceeds output byte limit') && !error.toLowerCase().includes('cleanup failed'),'failure must retire storage successfully');
      const cleanup=await retiredWorkspace(page);
      assert.deepEqual(cleanup,{workspaces:[],locks:[]});
      if(cancelling)return {kind:'cancellation-complete',case:cfg.case,...active,terminal:await page.evaluate(()=>({status:document.querySelector('#status').textContent.trim(),unixMs:Date.now(),monotonicMs:performance.now()})),cancelClicked:true,acceptance:false,runs:1,status:'CANCELLED',error,cleanup};
      return {kind:'controlled-failure-complete',acceptance:false,runs:1,status:'FAILED',error,cleanup};
    }
    assert.equal((await page.locator('#status').textContent()).trim(),'COMPLETE');
    assert.equal(await page.locator('#error').isVisible(),false);
    const output=completedPath(await page.locator('#result-path').textContent());
    if(cfg.case==='malformed-retry'){
      emit({kind:'baseline-export-complete',acceptance:false,runs:1,status:'COMPLETE',output});
      assert.deepEqual(await gate('baseline'),{baselineVerified:true});
      await repeatInput(page,'malformed',cfg.malformedName,1,emit,gate);
      assert.equal((await page.locator('#status').textContent()).trim(),'FAILED');
      const error=await page.locator('#error').textContent();
      assert(error&&error.includes('CSV record 4 has 2 fields, expected 3')&&!error.toLowerCase().includes('cleanup failed'));
      const cleanup=await retiredWorkspace(page);assert.deepEqual(cleanup,{workspaces:[],locks:[]});
      emit({kind:'malformed-failure-complete',acceptance:false,runs:2,status:'FAILED',error,cleanup});
      assert.deepEqual(await gate('malformed'),{malformedVerified:true});
      await repeatInput(page,'retry',cfg.inputName,2,emit,gate);
      assert.equal((await page.locator('#status').textContent()).trim(),'COMPLETE');
      assert.equal(await page.locator('#error').isVisible(),false);
      return {kind:'retry-export-complete',acceptance:false,runs:3,status:'COMPLETE',output:completedPath(await page.locator('#result-path').textContent())};
    }
    return {kind:'tiny-export-complete',acceptance:false,runs:1,status:'COMPLETE',output};
  }catch(error){
    try{console.error(JSON.stringify(await failedGateDiagnostic(page,mode)));}
    catch(diagnosticError){console.error(JSON.stringify({kind:'hosted-browse-dom-unavailable',mode,error:String(diagnosticError).slice(0,512)}));}
    throw error;
  }
}

async function run(chromium,cfg,emit,receive){
  assert(['chrome','msedge'].includes(cfg.channel));
  assert(['success','failure','observe-input','observe-output','observe-permission','processing-cancel','export-cancel','malformed-retry'].includes(cfg.case));
  const images={chrome:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',msedge:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'};
  assert.equal(cfg.browser,images[cfg.channel]);
  assert.equal(cfg.freshProfile,!cfg.continuedIssue105Profile);assert.equal(cfg.freshOrigin,true);
  assert.equal(cfg.profileChannel,cfg.channel,'profiles cannot cross channels');
  assert.equal(cfg.parentReviewed,true,'parent runtime review absent');
  assert.ok(cfg.expectedVersion&&cfg.profile&&cfg.url);
  let context;
  try{
    context=await chromium.launchPersistentContext(cfg.profile,{executablePath:cfg.browser,headless:false,
      timeout:20000,acceptDownloads:false,
      args:['--no-first-run','--no-default-browser-check','--disable-background-networking',
      '--disable-component-update','--disk-cache-size=1048576','--media-cache-size=1048576']});
    assert.equal(context.browser().version(),cfg.expectedVersion);
    emit({kind:'browser-launched',version:context.browser().version()});
    assert.deepEqual(await receive(),{ownedBrowserBound:true});
    const page=context.pages()[0];assert.ok(page);
    await page.goto(cfg.url,{waitUntil:'domcontentloaded',timeout:15000});
    await page.waitForFunction(()=>document.querySelector('#input').readOnly&&
      document.querySelector('#temp-dir').disabled&&!document.querySelector('#browse-input').disabled,null,{timeout:15000});
    const capabilities=await page.evaluate(async()=>({origin:location.origin,secure:isSecureContext,
      isolated:crossOriginIsolated,shared:typeof SharedArrayBuffer==='function',
      open:typeof showOpenFilePicker==='function',directory:typeof showDirectoryPicker==='function',
      locks:!!navigator.locks,storage:!!navigator.storage?.getDirectory,
      estimate:await navigator.storage.estimate(),persisted:await navigator.storage.persisted()}));
    assert.equal(capabilities.origin,cfg.url.replace(/\/$/,''));
    for(const k of ['secure','isolated','shared','open','directory','locks','storage'])assert.equal(capabilities[k],true,k);
    emit({kind:'capabilities',...capabilities});
    emit(await exercise(page,cfg,emit,async mode=>{const value=await receive();return value;}));
  }finally{if(context)await context.close();emit({kind:'browser-closed'});}
}
module.exports={exercise,run,failedGateDiagnostic,cancellationObservation,cancelCurrent,installCancelCapture,takeCancelCapture,repeatInput};
// Deliberately no CLI: the separately reviewed parent owns Job, pipes, deadline and reservation.
