// Metadata-only bundled Chromium component check; no CSV, WASI or product Run.
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {chromium} from '../ui/node_modules/playwright/index.mjs';
import {contractBrowserLaunchOptions} from './browser-launch.mjs';
import {bounded} from './browser-small-observer.mjs';

const executable=chromium.executablePath(),results=[];
const modes=process.argv.includes('--negative-control')?['without-automation','ordinary','persistent']:['ordinary','persistent'];
for(const mode of modes){
 let browser,context,session,profile;const errors=[];
 try{
  const options=mode==='without-automation'?{executablePath:executable}:contractBrowserLaunchOptions({executable},{});
  if(mode==='persistent'){
   profile=await mkdtemp(join(tmpdir(),'chopper-launch-cdp-'));
   context=await chromium.launchPersistentContext(profile,options);browser=context.browser();
  }else browser=await chromium.launch(options);
  session=await bounded(browser.newBrowserCDPSession());
  if(mode==='without-automation'){
   await assert.rejects(bounded(session.send('Browser.getBrowserCommandLine')),/enable-automation/);
   results.push({mode,expected_identity_query_denial:true,version:browser.version()});
  }else{
   const {arguments:args}=await bounded(session.send('Browser.getBrowserCommandLine'));
   assert(args.includes('--enable-automation'),'Identity query flag missing from running browser');
   assert(args.includes(executable),'Running command line does not select the approved executable');
   const profiles=args.filter(arg=>arg.startsWith('--user-data-dir='));assert.equal(profiles.length,1);
   if(profile)assert.equal(profiles[0],`--user-data-dir=${profile}`);
   const {processInfo}=await bounded(session.send('SystemInfo.getProcessInfo'));
   const owned=processInfo.filter(value=>value.type==='browser');assert.equal(owned.length,1);
   assert(Number.isSafeInteger(Number(owned[0].id))&&Number(owned[0].id)>0);
   if(mode==='ordinary'){
    // browser.newPage() owns an implicit single-page context. A quota observer
    // must be able to create another page in the contract's actual context.
    if(process.argv.includes('--negative-control')){
     const implicit=await browser.newPage();
     await assert.rejects(implicit.context().newPage(),/Please use browser.newContext\(\)/);
     await implicit.close();
    }
    context=await browser.newContext();
   }
   const pages=[];
   for(let index=0;index<3;index++)pages.push(await context.newPage());
   assert(pages.every(page=>page.context()===context),'Contract, observer and app pages must share the explicit context');
   assert(pages.every(page=>context.pages().includes(page)));
   results.push({mode,command_line_available:true,browser_pid:Number(owned[0].id),version:browser.version(),shared_context_pages:pages.length});
  }
 }catch(error){errors.push(error);}
 finally{
  for(const cleanup of [()=>session?.detach(),()=>context?.close(),()=>browser?.close(),()=>profile&&rm(profile,{recursive:true,force:true})]){
   try{await cleanup();}catch(error){errors.push(error);}
  }
 }
 if(errors.length)throw new AggregateError(errors,`Browser command-line check failed: ${mode}`);
}
console.log(JSON.stringify({scope:'bundled Chromium launch metadata only',results},null,2));
