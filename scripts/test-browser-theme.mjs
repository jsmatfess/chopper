// Real production bootstrap/CSP check, with app.js deliberately delayed.
import {withHostedBrowser} from './browser-acceptance.mjs';
import {mkdir,readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
await withHostedBrowser({port:8433,viewport:{width:1280,height:1000}},async({context,url})=>{
 await context.addInitScript(()=>localStorage.setItem('chopper-color-scheme','dark'));
 const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(String(error)));
 let release;const blocked=new Promise(resolve=>release=resolve);
 await page.route('**/app.js',async route=>{await blocked;await route.continue();});
 try{
  const response=await page.goto(url,{waitUntil:'commit'});
  assert.match(response.headers()['content-security-policy'],/sha256-/);
  assert.doesNotMatch(response.headers()['content-security-policy'],/unsafe-inline/);
  const notices=await readFile(new URL('../docs/releases/native-usage.txt',import.meta.url),'utf8');
  assert.ok((await response.text()).includes(`<!-- Chopper distribution notices\n${notices}\n-->`),'hosted HTML must retain the complete distribution notices');
  await page.waitForFunction(()=>document.body&&document.querySelector('meta[name="color-scheme"]').content==='dark'&&getComputedStyle(document.body).backgroundColor==='rgb(17, 24, 32)');
  assert.equal(await page.getByRole('button',{name:/Switch to .* theme/}).count(),0,'stored theme must apply before app.js runs');
 }finally{release();}
 await page.waitForFunction(()=>document.querySelector('#status').textContent==='IDLE');
 const theme=page.getByRole('button',{name:/Switch to .* theme/});assert.equal(await theme.getAttribute('data-choice'),'dark');
 const captures=process.argv.find(arg=>arg.startsWith('--screenshots='))?.slice(14);
 if(captures)await mkdir(captures,{recursive:true});
 for(const value of ['dark','light']){
  if(await theme.getAttribute('data-resolved')!==value)await theme.click();
  assert.equal(await page.evaluate(()=>document.querySelector('meta[name="color-scheme"]').content),value==='light'?'light dark':'dark');
  for(const id of ['source','pipeline','output-settings','review','output-plan']){
   const card=page.locator('#'+id);
   const surface=el=>{const style=getComputedStyle(el);return [style.backgroundColor,style.backgroundImage];};
   await page.mouse.move(0,0);
   const resting=await card.evaluate(surface);
   await card.locator('.section-title h2').hover();
   assert.equal(await card.evaluate(el=>el.matches(':hover')),true);
   assert.deepEqual(await card.evaluate(surface),resting,`${value} ${id} keeps its surface on hover`);
  }
  if(captures){await page.setViewportSize({width:1440,height:1050});await page.screenshot({path:`${captures}/theme-${value}-desktop.png`,fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:`${captures}/theme-${value}-mobile.png`,fullPage:true});}
 }
 assert.equal(await page.evaluate(()=>localStorage.getItem('chopper-color-scheme')),null);
 await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(17, 24, 32)');
 await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(244, 245, 247)');
 await page.emulateMedia({forcedColors:'active'});await theme.click();assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundImage),'none');
 assert.equal(await page.evaluate(()=>getComputedStyle(document.body,'::before').display),'none','forced colors suppress the decorative grid');
 assert.deepEqual(errors,[]);console.log('Production theme: early saved override under CSP, system changes, explicit modes, forced colors and mobile fit passed');
});
