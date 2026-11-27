// Isolated DOM interaction coverage: bundled Chromium, mocked client responses.
// No engine, product Run, File System Access, OPFS, or server is started.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {build} from 'esbuild';
import {chromium} from 'playwright';

const csv={encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false};
const {job_values: jobValues}=JSON.parse(await readFile(new URL('../../docs/cli-reference-data.json',import.meta.url),'utf8'));
const defaults={version:1,input:'',output:'',zip_member:null,input_csv:csv,output_csv:csv,compression:'none',operations:[],limits:{rows:null,bytes:null,compressed_bytes:null},resources:{grouping:'auto',workers:0,memory_mb:256,max_files:100000,max_record_bytes:8388608,temp_dir:null,temp_bytes:null}};
const analysis={algorithm_version:'test-only',rows:4,columns:2,header:['country','note'],preview:[['US','sample']],groups:1,output_files:2,output_csv_bytes:32,temp_bytes:0,peak_temp_bytes:0,analysis_seconds:1,memory_budget_bytes:268435456,workers:1,seed:'fixture',accuracy:'Exact fixture response',warnings:['Fixture warning'],stages:[]};
const sampleCsv=await readFile(new URL('../../examples/customers.csv',import.meta.url));
const html=(await readFile('index.html','utf8')).replace('id="try-sample"',
  `id="try-sample" data-csv="${sampleCsv.toString('base64')}" data-rows="5"`);
const css=await readFile('style.css','utf8');
async function bundle(){
  const result=await build({entryPoints:['src/app.ts'],bundle:true,write:false,plugins:[{name:'mock-client',setup(build){
    build.onResolve({filter:/^\.\/browser\/client$/},args=>args.importer.endsWith('/app.ts')?{path:'mock-client',namespace:'fixture'}:undefined);
    build.onLoad({filter:/.*/,namespace:'fixture'},()=>({resolveDir:resolve('.'),loader:'ts',contents:`
      export {configureBrowserUI,invalidateBrowserDraft} from ${JSON.stringify(resolve('src/browser/client.ts'))};
      export function startFormulaScan(job,onBatch){
        queueMicrotask(()=>onBatch({rows:[],done:true}));
        return {more(){},stop(){}};
      }
      export async function browserApi(path,data){
        window.calls.push({path,data:structuredClone(data)});
        if(path==='defaults')return structuredClone(window.defaults);
        if(path==='state'){const snapshot=structuredClone(window.fixtureState);if(window.deferNextState){window.deferNextState=false;return await new Promise(resolve=>window.releaseState=()=>resolve(snapshot));}return snapshot;}
        if(path==='preview'){if(window.deferPreview)await new Promise(resolve=>window.releasePreview=resolve);const sample=window.previewFixture??{columns:2,header:['country','note'],preview:[[data.input==='old.csv'?'OLD':'US','sample']],input_is_zip:false};return {...sample,preview_row_numbers:sample.preview.map((_,index)=>index+1)};}
        if(path==='pick-path')return {path:data.mode==='sample'?'customers.csv':data.mode==='input'?(window.pickedInput??'source.csv'):'destination'};
        if(path==='sniff'){
          if(window.sniffWithoutMemberError&&!data.zip_member)throw new Error(window.sniffWithoutMemberError);
          const settings={...data.input_csv,...window.sniffSettings};
          if(window.deferSniff){window.deferSniff=false;await new Promise(resolve=>window.releaseSniff=resolve);}
          return {settings,note:'Fixture detection complete'};
        }
        if(path==='profile'){if(window.deferAnalysisAck)await new Promise(resolve=>window.releaseAnalysisAck=resolve);const finish=()=>window.fixtureState={...window.fixtureState,status:'profiled',profile:window.profileFixture??{rows:4,columns:2,header:['country','note'],seconds:1,accuracy:'Exact fixture input count',stages:[],column_values:[]}};if(window.deferProfile){window.fixtureState={...window.fixtureState,status:'profiling',profile:null};window.finishProfile=finish;}else finish();return {};}
        if(path==='run-direct'){
          if(window.runError)throw new Error(window.runError);
          if(window.failRunDispatch){
            window.fixtureState={...window.fixtureState,status:'failed',analysis:null,output:null,error:'Run dispatch failed'};
            return {dispatched:false};
          }
          window.fixtureState={...window.fixtureState,status:'running',error:null,progress:{phase:'Fixture processing',rows:1,temp_bytes:0}};
          return {dispatched:true};
        }
        if(path==='cancel'){window.fixtureState={...window.fixtureState,status:'cancelled',analysis:null};return {};}
        throw new Error('Unexpected mock client action '+path);
      }`}));
  }}]});return result.outputFiles[0].text;
}
const hostedScript=await bundle();
async function harness(browser,hosted=true,clock=false,scrollspy=true,transitions=false,isolated=false){
  const page=await browser.newPage();if(clock)await page.clock.install();page.setDefaultTimeout(5000); const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(({defaults,analysis})=>{
    window.defaults=defaults;window.analysis=analysis;window.calls=[];
    window.fixtureState={status:'idle',progress:{phase:'',rows:0,temp_bytes:0},analysis:null,error:null,output:null};
    window.Worker=class {constructor(){throw new Error('Worker forbidden in DOM controls');}};
    const create=URL.createObjectURL.bind(URL);URL.createObjectURL=blob=>{window.exported=blob;return create(blob);};
  },{defaults,analysis});
  const origin=isolated?'http://localhost':'http://ui.test';
  await page.route(origin+'/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/')return route.fulfill({contentType:'text/html',body:html,headers:isolated?{'Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'}:undefined});
    if(path==='/style.css')return route.fulfill({contentType:'text/css',body:css});
    if(path==='/app.js')return route.fulfill({contentType:'text/javascript',body:hostedScript});
    return route.abort();
  });
  if(!scrollspy)await page.addInitScript(()=>{const supports=CSS.supports.bind(CSS);CSS.supports=(...args)=>args[0]==='scroll-target-group: auto'?false:supports(...args);});
  if(!transitions)await page.addInitScript(()=>document.startViewTransition=undefined);
  await page.goto(origin+'/');
  await page.waitForFunction(()=>document.querySelector('#input-csv select'));
  return {page,errors};
}
async function choose(page){await page.locator('#browse-input').click();await page.locator('#browse-output').click();}

test('automatic CSV detection follows the latest file and preserves manual edits',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser);
  const browse=page.locator('#browse-input');
  const delimiter=page.locator('#input-csv [data-csv="delimiter"]');
  const encoding=page.locator('#input-csv [data-csv="encoding"]');
  await page.evaluate(()=>{window.sniffSettings={delimiter:';',encoding:'utf-16le',bom:true};});
  await browse.click();
  await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'&&call.data.input_csv.encoding==='utf-16le'));
  assert.equal(await encoding.inputValue(),'utf-16le');

  await page.evaluate(()=>{window.deferSniff=true;window.releaseSniff=null;});
  await browse.click();
  await page.waitForFunction(()=>window.releaseSniff);
  const request=await page.evaluate(()=>window.calls.findLast(call=>call.path==='sniff').data.input_csv);
  assert.equal(request.encoding,'utf-8');
  assert.equal(request.delimiter,',');
  assert.equal(await page.locator('#run-direct').isDisabled(),true);
  assert.equal(await page.locator('#profile').isDisabled(),true);

  await page.evaluate(()=>{window.sniffSettings={delimiter:'|'};});
  await browse.click();
  await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'&&call.data.input_csv.delimiter==='|'));
  await page.evaluate(()=>window.releaseSniff());
  assert.equal(await delimiter.inputValue(),'|');
  assert.equal(await encoding.inputValue(),'utf-8');

  await page.evaluate(()=>{window.sniffSettings={delimiter:';'};window.deferSniff=true;window.releaseSniff=null;});
  await browse.click();
  await page.waitForFunction(()=>window.releaseSniff);
  await page.locator('#source-settings > summary').click();
  await delimiter.fill('^');
  await page.evaluate(()=>window.releaseSniff());
  await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'&&call.data.input_csv.delimiter==='^'));
  assert.equal(await delimiter.inputValue(),'^');
  assert.equal(await page.locator('#run-direct').isEnabled(),true);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('automatic detection waits for processing and retries when a ZIP member is entered',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser,true,true);
  await page.evaluate(()=>{
    window.pickedInput='source.zip';
    window.fixtureState.status='profiling';
    window.sniffWithoutMemberError='ZIP has multiple CSV members; set zip_member';
    window.previewFixture={columns:2,header:['country','note'],preview:[['US','sample']],input_is_zip:true};
    window.sniffSettings={delimiter:';'};
  });
  await page.clock.runFor(1000);
  await page.locator('#browse-input').click();
  const note=page.locator('#sniff-note');
  await note.filter({hasText:'when processing finishes'}).waitFor();
  assert.equal(await page.evaluate(()=>window.calls.some(call=>call.path==='sniff')),false);

  await page.evaluate(()=>window.fixtureState.status='idle');
  await page.clock.runFor(1000);
  await note.filter({hasText:'ZIP has multiple CSV members'}).waitFor();
  await page.locator('#source-settings > summary').click();
  await page.locator('#zip-member').fill('data/chosen.csv');
  assert.equal(await page.locator('#run-direct').isDisabled(),true);
  await page.clock.runFor(400);
  await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'
    &&call.data.zip_member==='data/chosen.csv'&&call.data.input_csv.delimiter===';'));
  assert.equal(await page.locator('#run-direct').isEnabled(),true);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('results describe the published archive and copy its subfolder name',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser);await choose(page);
  await page.evaluate(()=>{
   Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedResult=text;}}});
   window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'selected folder/chopper-results-test',
    publication:{kind:'browser-completion-marker',version:1,compression:'zip',files:2,folder:'chopper-results-test',marker:'CHOPPER-COMPLETE.json'}};
  });
  await page.locator('#result-message').filter({hasText:'outputs.zip contains 2 CSV files'}).waitFor();
  assert.equal(await page.locator('#result-parent').textContent(),'selected folder');
  assert.equal(await page.locator('#result-folder').textContent(),'chopper-results-test');
  assert.match(await page.locator('#result-marker').textContent(),/verified.*CHOPPER-COMPLETE\.json/);
  await page.getByRole('button',{name:'Copy folder name'}).click();
  assert.equal(await page.evaluate(()=>window.copiedResult),'chopper-results-test');
  await page.locator('#result-copy-feedback').filter({hasText:'Folder name copied.'}).waitFor();
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('a same-name input replacement retains the previous export without its column values',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  await page.locator('#run-direct').click();
  await page.evaluate(()=>{
   window.fixtureState={...window.fixtureState,status:'complete',
    analysis:{...window.analysis,column_values:[{column:0,values:['from old input'],truncated:false}]},
    output:'destination/previous-results'};
  });
  await page.clock.runFor(1000);
  await page.locator('#result-message').filter({hasText:'Export complete.'}).waitFor();
  await page.locator('#input-values .column-values-row>summary').first().click();
  const oldValue=page.locator('#input-values .value-label').getByText('from old input',{exact:true});
  await oldValue.waitFor();

  await page.locator('#browse-input').click();
  assert.equal(await page.locator('#input').inputValue(),'source.csv');
  await page.clock.runFor(1000);
  await page.locator('#result-message').filter({hasText:'Previous export complete.'}).waitFor();
  assert.equal(await page.locator('#published-output').isVisible(),true);
  assert.equal(await page.locator('#result-parent').textContent(),'destination');
  assert.equal(await page.locator('#result-folder').textContent(),'previous-results');
  assert.equal(await oldValue.count(),0);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('failed Run dispatch clears the previous analysis and a retry can display identical metrics',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  const run=page.locator('#run-direct'),analysisPanel=page.locator('#analysis');
  const complete=async()=>{
   await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/results'});
   await page.clock.runFor(1000);
   await analysisPanel.waitFor();
  };
  await run.click();
  await complete();

  await page.evaluate(()=>window.failRunDispatch=true);
  await run.click();
  await page.locator('#status').filter({hasText:'FAILED'}).waitFor();
  assert.equal(await analysisPanel.isHidden(),true);
  assert.equal(await page.locator('#published-output').isHidden(),true);

  await page.evaluate(()=>window.failRunDispatch=false);
  await run.click();
  await complete();
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
test('targeted recovery opens the folder picker or focuses the CSV size limit',async()=>{
 const browser=await chromium.launch();
 try{
  const {page,errors}=await harness(browser);await choose(page);
  await page.evaluate(()=>window.runError='Output folder write permission was not granted.');
  await page.locator('#run-direct').click();
  await page.getByRole('button',{name:'Choose another folder',exact:true}).click();
  await page.waitForFunction(()=>window.calls.filter(call=>call.path==='pick-path'&&call.data.mode==='output').length===2);
  await page.evaluate(()=>{window.runError=null;window.fixtureState={...window.fixtureState,status:'failed',error:'Error: one row plus header exceeds output byte limit'};});
  await page.getByRole('button',{name:'Review maximum CSV size',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'max-bytes');
  await page.evaluate(()=>window.fixtureState.error='Unexpected failure');
  await page.locator('#error').filter({hasText:'Unexpected failure'}).waitFor();
  assert.equal(await page.locator('#error-recovery').isHidden(),true);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
test('sample loads the source and row cap without opening a picker or starting Run',async()=>{
  const browser=await chromium.launch();
  try{
    const {page,errors}=await harness(browser);
    await page.locator('#browse-output').click();
    await page.locator('#max-rows').fill('10');
    const sample=page.getByRole('button',{name:'Try a sample',exact:true});
    page.once('dialog',dialog=>dialog.dismiss());
    await sample.click();
    assert.equal(await page.locator('#input').inputValue(),'');
    assert.equal(await page.locator('#max-rows').inputValue(),'10');
    page.once('dialog',dialog=>dialog.accept());
    await sample.click();
    await page.locator('#sample-status').filter({hasText:'Loaded customers.csv with a 5-row cap'}).waitFor();
    assert.equal(await page.locator('#input').inputValue(),'customers.csv');
    assert.equal(await page.locator('#output').inputValue(),'destination');
    assert.equal(await page.locator('#max-rows').inputValue(),'5');
    assert.deepEqual(await page.evaluate(()=>window.calls.filter(call=>call.path==='pick-path'||call.path==='run-direct').map(call=>[call.path,call.data.mode])),[
      ['pick-path','output'],['pick-path','sample'],
    ]);
    assert.deepEqual(Buffer.from(await page.evaluate(()=>[...window.calls.find(call=>call.data?.mode==='sample').data.bytes])),sampleCsv);
    assert.deepEqual(errors,[]);
  }finally{await browser.close();}
});
async function exported(page){await page.locator('#export').click();return page.evaluate(async()=>JSON.parse(await window.exported.text()));}
async function tick(page){await page.waitForTimeout(1100);}

async function setTheme(page,mode){
 const button=page.locator('.theme-control button');
 if(await button.getAttribute('data-resolved')!==mode)await button.click();
}

test('hosted workspace preserves configuration and real app action wiring through disclosures',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);
    for(const [selector, expected] of [
      ['#compression',jobValues.compression],
      ['#grouping',jobValues.grouping],
      ['#input-csv [data-csv="encoding"]',jobValues.encoding],
      ['#output-csv [data-csv="line_ending"]',jobValues.line_ending],
    ]){
      const actual=await page.locator(selector+' option').evaluateAll(options=>options.map(option=>option.value.toLowerCase()));
      assert.deepEqual(actual,expected.map(value=>value.toLowerCase()),selector);
    }
    if(process.env.CHOPPER_UI_SCREENSHOTS){
      await mkdir(process.env.CHOPPER_UI_SCREENSHOTS,{recursive:true});
      for(const width of [1280,390]){
        await page.setViewportSize({width,height:900});
        await page.screenshot({path:resolve(process.env.CHOPPER_UI_SCREENSHOTS,`empty-${width}.png`),fullPage:true});
      }
      await page.setViewportSize({width:1280,height:900});
    }
    assert.equal(await page.locator('.workspace-utilities').isVisible(),true,'project utilities remain visible');
    assert.equal(await page.locator('.footer-cleanup').isHidden(),true,'no cleanup link without detected abandoned data');
    const help=page.getByRole('navigation',{name:'Chopper help'});
    const docs=help.getByRole('link',{name:'Docs (opens in a new tab)',exact:true});
    assert.equal(await docs.isVisible(),true);
    assert.equal(await docs.getAttribute('href'),'https://github.com/jsmatfess/chopper/blob/main/docs/user/README.md');
    await page.getByRole('link',{name:/^Buy me a coffee/}).focus();
    await page.keyboard.press('Tab');
    assert.equal(await docs.evaluate(link=>link===document.activeElement),true);
    await page.keyboard.press('Tab');
    const sample=help.getByRole('button',{name:'Try a sample',exact:true});
    assert.equal(await sample.evaluate(link=>link===document.activeElement),true);
    assert.equal(await page.getByRole('textbox',{name:'Input file',exact:true}).count(),1);
    assert.equal(await page.getByRole('button',{name:'Browse for input file',exact:true}).count(),1);
    assert.equal(await page.getByRole('button',{name:'Browse for output folder',exact:true}).count(),1);
    assert.equal(await page.getByRole('link',{name:'GitHub',exact:false}).last().getAttribute('href'),'https://github.com/jsmatfess/chopper');
    const support=page.getByRole('link',{name:'Buy me a coffee',exact:false});
    assert.equal(await support.getAttribute('href'),'https://buymeacoffee.com/tblflip');
    assert.equal(await support.getAttribute('rel'),'noopener noreferrer');
    assert.equal(await page.locator('#pipeline-editor > summary').count(),0);
    assert.equal(await page.locator('#add-operation').isVisible(),true);
    assert.equal(await page.locator('#memory').inputValue(),'');
    await choose(page);
    const imported={...defaults,input:'source.csv',output:'destination',zip_member:'nested/data.csv',compression:'zip',full_shuffle_rng:'blake3_counter_v1',full_shuffle_algorithm:'adaptive_v1',input_csv:{...csv,encoding:'utf-16le',delimiter:'\t',headers:false,skip_empty_lines:true},output_csv:{...csv,encoding:'windows-1252',headers:false,bom:false,line_ending:'crlf'},resources:{...defaults.resources,memory_mb:257,max_record_bytes:123456,temp_bytes:876543,max_files:1234},limits:{rows:12,bytes:12345,compressed_bytes:6789},operations:[{type:'partition',columns:[0]},{type:'assign',groups:[{name:'a',percent:'12.345678'},{name:'b',percent:'87.654322'}],strata:[1]},{type:'assign_probabilistic',groups:[{name:'x',percent:'100'}],strata:[]},{type:'interleaved',files:2},{type:'shuffle',strategy:'fisher_yates'},{type:'balanced',files:3}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(imported))});
    await page.waitForFunction(()=>document.querySelectorAll('[data-step]').length===6);
    assert.deepEqual(await exported(page),imported);
    assert.equal(await page.locator('#require-reproducible').count(),0);
    const seeded=imported;
    assert.deepEqual(await exported(page),seeded);
    await page.locator('[data-step="0"] [data-action="down"]').click();
    assert.equal(await page.evaluate(()=>document.activeElement?.getAttribute('aria-label')),'Move step 2 down');
    const reordered=await exported(page);assert.deepEqual(reordered.operations,[seeded.operations[1],seeded.operations[0],...seeded.operations.slice(2)]);
    assert.match(await page.locator('#plan-description').innerText(),/12.345678/);
    assert.equal(await page.locator('#preview-card').isVisible(),true);
    assert.match(await page.locator('#preview').innerText(),/US/);
    await page.locator('#review').scrollIntoViewIfNeeded();
    await page.locator('#profile').click();
    assert.equal(!(await page.locator('#run-direct').textContent()).includes('Confirm & split'),true);
    assert.match(await page.locator('#input-profile').innerText(),/Records · exact/);assert.equal(await page.locator('.profile-facts dd').first().innerText(),'4');
    assert.equal(await page.locator('#analyze').count(),0);
    const before=await page.evaluate(()=>window.calls.filter(c=>c.path==='profile').at(-1).data);
    assert.deepEqual(before.operations,reordered.operations);
    await page.locator('#max-rows').fill('13');await tick(page);
    assert.equal(await page.locator('#run-direct').textContent(),'Run →');
    await page.locator('#max-rows').fill('12');
    await page.locator('#run-direct').click();
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.path!=='state').at(-1).path),'run-direct');
    await page.locator('#cancel').click();
    assert.match(await page.locator('#status').innerText(),/CANCELLED/);
    await page.locator('#run-direct').click();
    assert.equal(await page.evaluate(()=>window.calls.some(c=>c.path==='run-direct')),true);
    assert.equal(await page.locator('#run-direct').isDisabled(),true);
    const frozen=await page.evaluate(()=>window.calls.findLast(c=>c.path==='run-direct').data);
    await page.locator('#max-rows').fill('99');
    assert.equal(frozen.limits.rows,12);
    await page.evaluate(()=>{window.fixtureState={...window.fixtureState,status:'failed',error:'Marker close failed. No valid CHOPPER-COMPLETE.json; retained folder needs cleanup.'};});
    await tick(page);assert.match(await page.locator('#error').innerText(),/Marker close failed/);
    assert.doesNotMatch(await page.locator('#result-path').innerText(),/✓ Complete/);
    assert.deepEqual(errors,[]);
    await page.close();
  }finally{await browser.close();}
});

test('keyboard validation, column picker, seed-free submission and mobile reachability',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);await choose(page);
    await page.locator('.workspace-nav a[href="#review"]').focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'review');
    await page.locator('#add-operation').click();
    const search=page.locator('[data-column-search]');await search.fill('country');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
    assert.deepEqual((await exported(page)).operations,[{type:'partition',columns:['country']}]);
    await page.locator('[data-action="remove"]').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'add-operation');
    await page.locator('#max-files').fill('0');
    await page.locator('#run-direct').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'max-files');
    await page.locator('#max-files').fill('100000');await page.locator('#run-direct').click();
    assert.equal(await page.locator('#seed').count(),0);
    assert.equal(Object.hasOwn(await exported(page),'seed'),false);
    await page.locator('#cancel').click();await page.locator('#run-direct').click();assert.equal(Object.hasOwn(await exported(page),'seed'),false);
    await page.evaluate(()=>{window.fixtureState={...window.fixtureState,status:'complete',output:'destination/result',analysis:window.analysis};});await tick(page);
    assert.match(await page.locator('#result-message').innerText(),/Export complete. 2 CSV files saved/);
    await page.locator('#max-rows').fill('7');await tick(page);
    assert.match(await page.locator('#result-path').innerText(),/Draft changed/);
    assert.equal(await page.locator('#result-parent').textContent(),'destination');
    assert.equal(await page.locator('#result-folder').textContent(),'result','draft edits retain the completed result location');
    for(const width of [390,760,1280]){
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow at ${width}`);
      assert.equal(await page.locator('.results .plan #draft-resources').isVisible(),true);
      for(const id of ['source','output-settings','pipeline','review']){
        await page.locator(`.workspace-nav a[href="#${id}"]`).click();
        assert.equal(await page.evaluate(()=>document.activeElement.id),id);
      }
    }
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

test('source detection, independent serialization and operation edits remain reachable',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);
    await page.evaluate(()=>{window.sniffSettings={delimiter:';'};});
    await choose(page);
    await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'&&call.data.input_csv.delimiter===';'));
    assert.equal(await page.locator('#input-csv [data-csv="delimiter"]').inputValue(),';');
    await page.locator('#source-settings > summary').click();
    await page.locator('#sniff-csv').click();
    await page.waitForFunction(()=>window.calls.filter(call=>call.path==='sniff').length===2);
    assert.equal(await page.locator('#input-csv [data-csv="delimiter"]').inputValue(),';');
    await page.locator('#output-settings details > summary').click();
    assert.equal(await page.locator('#output-csv [data-csv="delimiter"]').inputValue(),',');
    await page.locator('#copy-csv').click();
    assert.equal(await page.locator('#output-csv [data-csv="delimiter"]').inputValue(),';');
    await page.locator('#new-operation').selectOption('assign');await page.locator('#add-operation').click();
    await page.locator('[data-group="0"] [data-group-field="percent"]').fill('30');
    await page.locator('[data-group="1"] [data-action="remainder"]').click();
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.action),'remainder');
    assert.deepEqual((await exported(page)).operations[0].groups,[{name:'treatment',percent:'30'},{name:'control',percent:'70'}]);
    await page.locator('[data-action="add-group"]').click();
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.action),'add-group');
    await page.locator('[data-group="2"] [data-action="remove-group"]').click();
    await page.locator('#new-operation').selectOption('shuffle');await page.locator('#add-operation').click();
    await page.locator('#execution-mode').check();
    await page.locator('[data-field="strategy"]').focus();
    await page.locator('[data-field="strategy"]').selectOption('fisher_yates');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.field),'strategy');
    const identity=await page.locator('[data-step="1"]').getAttribute('data-operation-id');
    await page.locator('[data-step="1"] [data-action="up"]').click();
    assert.equal(await page.locator('[data-step="0"]').getAttribute('data-operation-id'),identity);
    await page.locator('#profile').click();
    await page.locator('#input-csv [data-csv="headers"]').uncheck();
    assert.equal(await page.locator('#input-profile').isHidden(),true);
    assert.equal(!(await page.locator('#run-direct').textContent()).includes('Confirm & split'),true);
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>['profile','analyze','run','run-direct'].includes(c.path)).length),1,'editing never starts a full scan or Run');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} encoding aliases survive import, edit, export and both submission paths`,async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser,hosted);
    for(const [input,output] of [['cp1252','sjis'],['sjis','cp1252'],['utf-8','Shift_JIS'],['  cp1252  ','sjis']]){
      const imported={...defaults,input:'source.csv',output:'destination',input_csv:{...csv,encoding:input},output_csv:{...csv,encoding:output}};
      await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(imported))});
      await page.waitForFunction(expected=>document.querySelector('#input-csv [data-csv=encoding]').value===expected,imported.input_csv.encoding);
      assert.equal(await page.locator('#input-csv [data-csv=encoding]').inputValue(),input);
      assert.equal(await page.locator('#output-csv [data-csv=encoding]').inputValue(),output);
      await page.locator('#max-rows').evaluate(el=>{el.value='2';el.dispatchEvent(new Event('input',{bubbles:true}));});
      const expected={...imported,limits:{...imported.limits,rows:2}};
      assert.deepEqual(await exported(page),expected);
      await page.locator('#job-form').evaluate(form=>form.requestSubmit());
      await page.waitForFunction(()=>window.calls.some(c=>c.path==='run-direct'));
      assert.deepEqual(await page.evaluate(()=>window.calls.findLast(c=>c.path==='run-direct').data),expected);
      await page.waitForFunction(()=>document.getElementById('status').textContent==='RUNNING');
      await page.locator('#cancel').click();
      await page.waitForFunction(()=>document.getElementById('status').textContent==='CANCELLED');
      await page.locator('#profile').evaluate(el=>el.click());
      await page.waitForFunction(()=>document.getElementById('input-profile').hidden===false);
      assert.deepEqual(await page.evaluate(()=>window.calls.findLast(c=>c.path==='profile').data),expected);
      await page.locator('#run-direct').click();
      assert.deepEqual(await page.evaluate(()=>window.calls.findLast(c=>c.path==='run-direct').data),expected);
      assert.deepEqual(await exported(page),expected);
      await page.waitForFunction(()=>document.getElementById('status').textContent==='RUNNING');
      await page.locator('#cancel').click();
      await page.waitForFunction(()=>document.getElementById('status').textContent==='CANCELLED');
      await page.locator('#copy-csv').evaluate(el=>el.click());
      assert.equal((await exported(page)).output_csv.encoding,input);
      await page.evaluate(()=>window.calls=[]);
    }
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} sample loads on import and Run stays in the action bar`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    await page.waitForFunction(()=>document.querySelector('#run-next-step').textContent==='Choose an input file.');
    await page.locator('#run-next-step').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-input');
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...defaults,input:'source.csv',output:'destination'}))});
    await page.waitForFunction(()=>!document.getElementById('preview-card').hidden);
    assert.match(await page.locator('#preview').innerText(),/US/);
    assert.equal(await page.locator('.results .plan :is(#profile,#run-direct,#cancel)').count(),0);
    assert.equal(await page.locator('#run-dock #cancel').count(),1);
    assert.equal(await page.locator('#profile').innerText(),'Analyze input');
    assert.equal(await page.locator('#execute').count(),0);
    assert.equal(await page.locator('#run-dock #run-direct, #source #profile').count(),2);
    await page.waitForFunction(()=>document.querySelector('#run-readiness').textContent==='Ready to run');
    for(const width of [1280,390]){
      await page.setViewportSize({width,height:720});
      const run=await page.locator('#run-direct').boundingBox();
      assert.ok(run.y>=0&&run.y+run.height<=720,'Run is in view on desktop and mobile');
    }
    assert.equal(await page.locator('#plan-description').evaluate(el=>el.firstElementChild.id),'draft-output');
    assert.match(await page.locator('#draft-output').innerText(),/Write uncompressed CSVs to a new folder in destination/);
    for(const [selector,edge,width] of [
      ['#draft-output','borderBottomWidth','1px'],
      ['.plan-summary-section[data-config-section="source"]','borderTopWidth','0px'],
      ['#plan-description > details','borderTopWidth','1px'],
      ['#plan-description','borderBottomWidth','0px'],
      ['.cli-handoff','borderTopWidth','1px'],
    ])assert.equal(await page.locator(selector).evaluate((el,edge)=>getComputedStyle(el)[edge],edge),width,selector);
    assert.equal(await page.locator('#run-direct').evaluate(button=>button.form?.id),'job-form');
    if(hosted){
      assert.equal(await page.locator('.results > .card').count(),2);
      assert.equal(await page.locator('.recipe').count(),0);
      for(const id of ['draft-source','draft-output','draft-resources','plan-description'])assert.equal(await page.locator(`.results .plan #${id}`).count(),1);
      assert.equal(await page.locator('#output-plan h2').innerText(),'Output plan');
    }
    assert.equal(await page.evaluate(()=>window.calls.some(c=>['profile','analyze','run','run-direct'].includes(c.path))),false);
    await page.locator('#profile').click();
    await page.waitForFunction(()=>document.getElementById('status').textContent==='PROFILED');
    await page.locator('#max-rows').fill('7');
    assert.equal(await page.locator('#run-direct').textContent(),'Run →');
    await page.locator('#run-direct').click();
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.path!=='state').at(-1).path),'run-direct');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

test('late source samples cannot replace a newly imported source',async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser);
    const importSource=async input=>{
      await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...defaults,input,output:'destination'}))});
    };
    await page.evaluate(()=>window.deferPreview=true);
    await importSource('old.csv');await page.waitForFunction(()=>window.releasePreview);
    await page.evaluate(()=>window.deferPreview=false);
    await importSource('new.csv');
    await page.waitForFunction(()=>document.getElementById('preview').textContent.includes('US'));
    await page.evaluate(()=>window.releasePreview());await tick(page);
    assert.doesNotMatch(await page.locator('#preview').innerText(),/OLD/);
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} paired operations share menu entries and retain settings across mode changes`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...defaults,input:'source.csv',output:'destination'}))});
    await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
    assert.deepEqual(await page.locator('#new-operation option').evaluateAll(options=>options.map(option=>option.value)),['partition','balanced','assign','shuffle']);
    await page.locator('#new-operation').selectOption('balanced');await page.locator('#add-operation').click();
    assert.equal(await page.locator('[data-step="0"] input[value="balanced"]').isChecked(),true);
    await page.locator('[data-step="0"] [data-field="files"]').fill('5');
    await page.locator('#new-operation').selectOption('assign');await page.locator('#add-operation').click();
    assert.equal(await page.locator('[data-step="1"] input[value="assign"]').isChecked(),true);
    const search=page.locator('[data-step="1"] [data-column-field="strata"] [data-column-search]');
    await search.fill('country');await search.press('ArrowDown');await search.press('Enter');
    const original=await exported(page);
    await page.locator('[data-step="0"] input[value="interleaved"]').check();
    assert.equal(await page.evaluate(()=>document.activeElement.value),'interleaved');
    await page.locator('[data-step="1"] input[value="assign_probabilistic"]').check();
    assert.equal(await page.evaluate(()=>document.activeElement.value),'assign_probabilistic');
    assert.deepEqual((await exported(page)).operations,original.operations.map((op,i)=>({...op,type:i===0?'interleaved':'assign_probabilistic'})));
    assert.match(await page.locator('[data-step="1"] [data-group-feedback]').innerText(),/Actual counts may vary/);
    assert.match(await page.locator('#plan-description').innerText(),/approximately/);
    await page.locator('[data-step="0"] input[value="interleaved"]').focus();await page.keyboard.press('ArrowLeft');
    await page.locator('[data-step="1"] input[value="assign"]').check();
    assert.deepEqual((await exported(page)).operations,original.operations);
    const imported={...original,operations:[{type:'interleaved',files:7},{...original.operations[1],type:'assign_probabilistic'}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(imported))});
    await page.waitForFunction(()=>document.querySelector('[data-field="files"]').value==='7');
    assert.equal(await page.locator('[data-step="0"] input[value="interleaved"]').isChecked(),true);
    assert.equal(await page.locator('[data-step="1"] input[value="assign_probabilistic"]').isChecked(),true);
    assert.deepEqual(await exported(page),imported);
    await page.locator('[data-step="0"] [data-action="down"]').click();
    assert.equal(await page.locator('[data-step="0"] input[value="assign_probabilistic"]').isChecked(),true);
    assert.equal(await page.locator('[data-step="1"] input[value="interleaved"]').isChecked(),true);
    assert.equal(await page.locator('.step-title').nth(0).innerText(),'Assign groups by percentage');
    assert.equal(await page.locator('.step-title').nth(1).innerText(),'Split into equal parts');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} live guidance blocks incomplete jobs and links to fields without starting work`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    assert.match(await page.locator('#validation-panel').innerText(),/Choose an input file/);
    assert.match(await page.locator('#validation-panel').innerText(),/Choose an output folder/);
    assert.equal(await page.locator('#output').getAttribute('aria-invalid'),'false');
    await page.locator('#validation-list button').filter({hasText:'Choose an output folder'}).click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),hosted?'browse-output':'output');
    const config={...defaults,input:'source.csv',output:'',operations:[{type:'assign',groups:[{name:'a',percent:'70'},{name:'b',percent:'20'}],strata:[]}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
    assert.match(await page.locator('#validation-panel').innerText(),/Percentages must total exactly 100/);
    await page.locator('#run-direct').click();
    assert.equal(await page.evaluate(()=>window.calls.some(c=>['run','run-direct','analyze'].includes(c.path))),false);
    const second=page.locator('[data-group="1"] [data-group-field="percent"]');
    await second.fill('30');
    assert.doesNotMatch(await page.locator('#validation-panel').innerText(),/Percentages must total/);
    await page.locator('[data-group="1"] [data-group-field="name"]').fill('a');
    assert.match(await page.locator('#validation-panel').innerText(),/Group names must be unique/);
    await page.locator('[data-group="1"] [data-group-field="name"]').fill('b');
    await page.locator('#profile').click();
    assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.path!=='state').at(-1).path),'profile','input analysis does not need an output folder');
    if(hosted)await page.locator('#browse-output').click();else await page.locator('#output').fill('destination');
    assert.equal(await page.locator('#validation-panel').isVisible(),false);
    assert.equal(await page.locator('[data-group="0"] [data-group-field="percent"]').getAttribute('aria-invalid'),'false');
    await page.locator('#run-direct').click();
    await page.waitForFunction(()=>window.calls.some(c=>c.path==='run-direct'));
    const submitted=await page.evaluate(()=>window.calls.findLast(c=>c.path==='run-direct').data);
    assert.deepEqual(submitted.operations[0].groups,[{name:'a',percent:'70'},{name:'b',percent:'30'}]);
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

test('allocation feedback stays below the rows without moving percentage controls',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);
    const config={...defaults,input:'source.csv',output:'destination',operations:[{type:'assign',groups:[{name:'a',percent:'80'},{name:'b',percent:'20'}],strata:[]}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    const groups=page.locator('fieldset:has([data-group-feedback])');
    const hint=groups.locator('[data-group-feedback]');
    const first=groups.locator('[data-group-field="percent"]').first(),second=groups.locator('[data-group-field="percent"]').last();
    const summary=page.locator('#validation-panel').getByRole('button',{name:/Percentages must total/});
    const positions=()=>groups.evaluate(group=>{
      const top=group.getBoundingClientRect().top;
      return [...group.querySelectorAll('.group-row input,.group-row button')].map(control=>Math.round((control.getBoundingClientRect().top-top)*10)/10);
    });
    for(const [width,mode] of [[1280,'Exact counts'],[390,'Approximate counts']]){
      await page.setViewportSize({width,height:900});
      await page.getByRole('radio',{name:mode,exact:true}).check();
      const before=await positions();
      const neutral=await hint.evaluate(el=>getComputedStyle(el).color);
      await second.fill('2');
      assert.equal(await hint.isVisible(),true);
      assert.match(await hint.innerText(),/Percentages must total exactly 100/);
      assert.equal(await second.getAttribute('aria-invalid'),'true','show the error while the edited field still has focus');
      assert.equal(await second.getAttribute('aria-describedby'),await hint.getAttribute('id'));
      assert.notEqual(await hint.evaluate(el=>getComputedStyle(el).color),neutral,'the shared error is distinguishable from help text');
      assert.deepEqual(await positions(),before);
      await second.fill('40');
      assert.match(await hint.innerText(),/Current total: 120%/);
      assert.equal(await summary.count(),1,'a group total has one summary entry');
      await page.waitForFunction(()=>document.getElementById('validation-announcement').textContent.includes('Current total: 120%'));
      assert.deepEqual(await positions(),before);
      await first.focus();await first.press('Tab');
      assert.equal(await first.getAttribute('aria-invalid'),'true');
      assert.equal(await first.getAttribute('aria-describedby'),await hint.getAttribute('id'));
      await second.fill('');
      assert.match(await hint.innerText(),/Use percentages from 0 to 100/);
      assert.deepEqual(await positions(),before);
      await second.fill('20');
      assert.match(await hint.innerText(),/Total(?: target)?: 100%/);
      assert.deepEqual(await positions(),before);
      assert.equal(await first.getAttribute('aria-invalid'),'false');
      assert.equal(await first.getAttribute('aria-describedby'),null);
      assert.equal(await second.getAttribute('aria-invalid'),'false');
      assert.equal(await second.getAttribute('aria-describedby'),null);
      assert.equal(await summary.count(),0);
      assert.equal(await page.locator('#validation-announcement').textContent(),'');
    }
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} cross-field checks and inactive settings update without discarding user values`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    const config={...defaults,input:'source.csv',output:'destination',resources:{...defaults.resources,memory_mb:32},operations:[{type:'balanced',files:5}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
    assert.match(await page.locator('#validation-panel').innerText(),/1\/16 of the memory budget/);
    await page.locator('#validation-list button').filter({hasText:'1/16'}).click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'max-record');
    await page.locator('#memory-mode').selectOption('auto');
    assert.equal(await page.locator('#memory').isDisabled(),true);
    assert.equal(await page.locator('#manual-memory-help').isVisible(),true);
    assert.equal((await exported(page)).resources.memory_mb,'auto');
    assert.equal(await page.locator('#workers').isEnabled(),true,'automatic memory does not override an explicit worker choice');
    const workers=page.getByRole('spinbutton',{name:/Compression workers/});
    await workers.fill('2');
    assert.equal((await exported(page)).resources.workers,2);
    await page.locator('#memory-mode').selectOption('manual');
    assert.equal(await page.locator('#memory').inputValue(),'32');
    await page.locator('#max-record').fill('1');
    await page.locator('#max-files').fill('3');
    assert.match(await page.locator('#validation-panel').innerText(),/reduce equal parts/);
    await page.locator('#max-files').fill('10');
    await page.locator('#max-bytes').fill('0');
    assert.match(await page.locator('#validation-panel').innerText(),/Size must be positive/);
    await page.locator('#max-bytes-unit').selectOption('MB');await page.locator('#max-bytes').fill('100');
    if(hosted)await page.locator('#output-settings details > summary').click();
    await page.locator('#compression').selectOption('gzip');
    await page.locator('#compressed-bytes').fill('0');
    assert.match(await page.locator('#validation-panel').innerText(),/Compressed size target/);
    await page.locator('#compression').selectOption('none');
    assert.equal(await page.locator('#compressed-bytes').isDisabled(),true);
    assert.doesNotMatch(await page.locator('#validation-panel').innerText(),/Compressed size target/);
    assert.equal((await exported(page)).limits.compressed_bytes,null);
    await page.locator('#compression').selectOption('gzip');
    assert.equal(await page.locator('#compressed-bytes').inputValue(),'0');
    await page.locator('#compressed-bytes-unit').selectOption('MB');await page.locator('#compressed-bytes').fill('1');
    if(hosted)await page.locator('#source-settings > summary').click();else await page.locator('#input-csv').evaluate(el=>el.closest('details').open=true);
    await page.locator('#input-csv [data-csv="headers"]').uncheck();
    assert.match(await page.locator('#validation-panel').innerText(),/Turn off output headers/);
    await page.locator('#output-csv [data-csv="headers"]').uncheck();
    await page.locator('#output-csv [data-csv="quote"]').fill(',');
    assert.match(await page.locator('#validation-panel').innerText(),/quote must differ/);
    await page.locator('#output-csv [data-csv="quote"]').fill('"');
    await page.locator('#output-csv [data-csv="encoding"]').selectOption('windows-1252');
    await page.locator('#output-csv [data-csv="bom"]').check();
    assert.match(await page.locator('#validation-panel').innerText(),/Turn off the output byte-order mark/);
    await page.locator('#output-csv [data-csv="bom"]').uncheck();
    assert.equal(await page.locator('#validation-panel').isVisible(),false);
    assert.equal(await page.locator('#input-csv [data-csv="line_ending"]').isDisabled(),true);
    assert.equal(await page.locator('#input-csv [data-csv="bom"]').isDisabled(),true);
    assert.equal(await page.locator('#output-csv [data-csv="skip_empty_lines"]').isDisabled(),true);
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} imports surface unsupported encodings and missing columns before execution`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    const config={...defaults,input:'source.csv',output:'destination',input_csv:{...csv,encoding:'unknown<&encoding'},operations:[{type:'partition',columns:['missing-column']}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    await page.waitForFunction(()=>document.getElementById('validation-list').textContent.includes('missing or ambiguous'));
    assert.match(await page.locator('#validation-panel').innerText(),/encoding is unsupported/);
    await page.locator('#profile').click();
    assert.equal(await page.evaluate(()=>window.calls.some(c=>c.path==='profile')),false);
    assert.equal(await page.locator('#input-csv [data-csv="encoding"]').getAttribute('aria-invalid'),'true');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} linked plan text highlights and focuses its current configuration`,async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const {page,errors}=await harness(browser,hosted);
    const config={...defaults,input:'source.csv',output:'destination',limits:{rows:10,bytes:1000000,compressed_bytes:500000},compression:'gzip',operations:[{type:'shuffle',strategy:'uniform'},{type:'partition',columns:['country']},{type:'assign',groups:[{name:'<img src=x onerror=alert(1)>',percent:'80'},{name:'control',percent:'20'}],strata:[]}]};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    await page.waitForFunction(()=>!document.getElementById('preview-card').hidden);
    const partition=page.locator('#plan-description [data-plan-target="step-1"]').first();
    await partition.hover();
    assert.equal(await page.locator('[data-step="1"]').evaluate(el=>el.classList.contains('plan-config-highlight')),true);
    if(hosted)for(const theme of ['light','dark']){
      await setTheme(page,theme);
      await page.mouse.move(0,0);
      const styles=await page.evaluate(()=>{
        const steps=[1,2].map(index=>document.querySelector(`#operations [data-step="${index}"]`));
        return steps.map((step,i)=>({
          icon:getComputedStyle(step.querySelector('.operation-icon')).color,
          number:getComputedStyle(step.querySelector('.step-index')).color,
          marker:getComputedStyle(document.querySelector(`.plan-steps li[value="${i+2}"]`),'::marker').color,
          label:getComputedStyle(step.querySelector('.step-title')).color,
          planLabel:getComputedStyle(document.querySelector(`.plan-steps>li>button[data-plan-target="step-${i+1}"]`)).color,
        }));
      });
      assert.equal(styles[0].icon,styles[1].icon,`${theme} icons use the same neutral color`);
      assert.notEqual(styles[0].number,styles[1].number,`${theme} numbers identify the operation`);
      for(const style of styles)assert.equal(style.number,style.marker);
      assert.equal(styles[0].label,styles[1].label);
      assert.equal(styles[0].planLabel,styles[1].planLabel);
      const accents=[];
      for(const index of [2,1]){
        await page.locator(`.plan-steps>li>button[data-plan-target="step-${index}"]`).hover();
        await page.waitForFunction(index=>document.querySelector('.plan-connector.is-visible')?.dataset.target===`step-${index}`,index);
        accents.push(await page.evaluate(()=>{
          const outline=document.querySelector('#operations .plan-config-highlight');
          const connector=document.querySelector('.plan-connector.is-visible .plan-connector-line');
          return [getComputedStyle(outline).outlineColor,getComputedStyle(connector).stroke];
        }));
      }
      assert.deepEqual(accents,[styles[1],styles[0]].map(({number})=>[number,number]),`${theme} each line and outline matches its step number`);
      const color=await page.locator('[data-step="1"]').evaluate(el=>getComputedStyle(el).backgroundColor.match(/\d+/g).slice(0,3).map(Number));
      assert(color[2]>=color[1]&&color[1]>=color[0],`${theme} linked steps retain their neutral surface`);
    }
    await partition.click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'column-picker-1-columns');
    const row=page.locator('#plan-description [data-plan-target="max-rows"]').first();
    await partition.focus();await row.hover();
    assert.equal(await page.locator('#max-rows').evaluate(el=>el.closest('label').classList.contains('plan-config-highlight')),true,'pointer hover follows the hovered link even while another has keyboard focus');
    await row.focus();
    assert.equal(await page.locator('#max-rows').evaluate(el=>el.closest('label').classList.contains('plan-config-highlight')),true,'keyboard focus highlights configuration too');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.id),'max-rows');
    const compressed=page.locator('#plan-description [data-plan-target="compressed-bytes"]').first();
    await compressed.click();assert.equal(await page.evaluate(()=>document.activeElement.id),'compressed-bytes');
    assert.equal(await page.locator('#plan-description img').count(),0);
    assert.match(await page.locator('#plan-description').innerText(),/<img src=x onerror=alert\(1\)>/);
    await page.locator('[data-step="0"] [data-action="down"]').click();
    await page.locator('#plan-description [data-plan-target="step-1"]').first().click();
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.field),'strategy','reordering keeps links mapped to the current step');
    if(hosted){
      await page.locator('#draft-source .plan-link').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-input');
      await page.locator('#draft-output .plan-link').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-output');
      await page.locator('#draft-resources .plan-link').hover();
      assert.equal(await page.locator('#resource-settings').evaluate(el=>el.classList.contains('plan-config-highlight')),true);
      await page.locator('#draft-resources .plan-link').click();assert.equal(await page.evaluate(()=>document.activeElement.id),'memory-mode');
    }
    for(const width of [390,760,1280]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
    assert.equal(await page.evaluate(()=>window.calls.some(c=>['profile','analyze','run','run-direct'].includes(c.path))),false,'plan navigation never starts processing');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} plan keeps its own section order and curved connectors track configuration`,async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,hosted);
  const config={...defaults,input:'source.csv',output:'destination',operations:[{type:'balanced',files:3},{type:'assign',groups:[{name:'a',percent:'50'},{name:'b',percent:'50'}],strata:[]}]};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
  await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
  const configOrder=['source','output-settings','calculated-columns','pipeline','review'];
  const planOrder=['source','pipeline','output-settings','review'];
  assert.deepEqual(await page.locator('#job-form > section').evaluateAll(cards=>cards.map(card=>card.id)),configOrder);
  assert.deepEqual(await page.locator('.plan-summary-section').evaluateAll(cards=>cards.map(card=>card.dataset.configSection)),planOrder);
  assert.deepEqual(await page.locator('.workspace-nav a').evaluateAll(links=>links.map(link=>link.hash.slice(1))),configOrder);
  const numbers=['01','02','03','04'];
  assert.deepEqual(await page.locator('#job-form > section .number').allTextContents(),numbers);
  assert.deepEqual(await page.locator('.plan-section-index').allTextContents(),numbers);
  await page.locator('.plan-section-heading [data-plan-target="section-3"]').click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-output','the plan Output heading still opens Output in Configure');
  assert.deepEqual(await page.locator('.plan-steps > li').evaluateAll(items=>items.map(item=>item.value)),[1,2]);
  assert.equal(await page.locator('.plan-steps').filter({has:page.locator('[data-plan-target="step-0"]')}).evaluate(el=>getComputedStyle(el).listStyleType),'decimal-leading-zero');
  const link=page.locator('.plan-steps [data-plan-target="step-0"]').first();
  assert.equal(await link.evaluate(el=>getComputedStyle(el).textDecorationLine),'none');
  await link.hover();
  await page.waitForFunction(()=>document.querySelector('.plan-connector:not(.execution-plan-connector).is-visible')?.dataset.target==='step-0'&&document.querySelector('.plan-connector-line').getAttribute('d')?.includes('C'));
  const attachment=await link.evaluate(el=>{
   const text=el.getBoundingClientRect(),box=el.closest('.plan').getBoundingClientRect();
   const dot=document.querySelector('.plan-connector:not(.execution-plan-connector) circle');
   return {x:Number(dot.getAttribute('cx')),y:Number(dot.getAttribute('cy')),boxLeft:box.left,textY:text.top+text.height/2};
  });
  assert(Math.abs(attachment.x-attachment.boxLeft)<1,'connector starts at the output-card edge');
  assert(Math.abs(attachment.y-attachment.textY)<1,'connector stays aligned with the linked text');
  assert.equal(await page.locator('.plan-connector:not(.execution-plan-connector)').getAttribute('aria-hidden'),'true');
  assert.equal(await page.locator('.plan-connector:not(.execution-plan-connector)').evaluate(el=>getComputedStyle(el).pointerEvents),'none');
  await link.focus();
  const before=await page.locator('.plan-connector-line').getAttribute('d');
  await page.evaluate(()=>scrollBy(0,scrollY>40?-40:40));
  await page.waitForFunction(before=>document.querySelector('.plan-connector-line').getAttribute('d')!==before,before);
  await link.click();await page.mouse.move(2,2);
  await page.waitForFunction(()=>document.querySelector('.plan-connector:not(.execution-plan-connector).is-visible')?.dataset.target==='step-0');
  assert.equal(await page.evaluate(()=>document.activeElement.value),'balanced');
  await page.locator('[data-step="0"] [data-field="files"]').fill('4');
  await page.waitForFunction(()=>document.querySelector('.plan-connector:not(.execution-plan-connector).is-visible')?.dataset.target==='step-0');
  assert.doesNotMatch(await page.locator('.plan-connector-line').getAttribute('d'),/NaN/);
  await page.locator('#compression').focus();
  assert.equal(await page.locator('.plan-connector:not(.execution-plan-connector)').evaluate(el=>el.classList.contains('is-visible')),false);
  const pipelineSection=2;
  await page.locator(`.plan-section-heading [data-plan-target="section-${pipelineSection}"]`).click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'new-operation');
  for(const width of [390,760,1280]){
   await page.setViewportSize({width,height:900});await link.focus();
   await page.waitForFunction(()=>document.querySelector('.plan-connector:not(.execution-plan-connector).is-visible'));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`connector overflow at ${width}`);
  }
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});


test('hovering a pipeline step reveals its matching plan entry',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);
    const config={...defaults,operations:Array.from({length:16},()=>({type:'shuffle'}))};
    await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
    const step=page.locator('#operations [data-step="15"] .step-title');
    const link=page.locator('.plan-steps>li>button[data-plan-target="step-15"]');
    const visible=el=>{
      const box=el.getBoundingClientRect(),panel=el.closest('.results').getBoundingClientRect();
      const rail=document.querySelector('.rail').getBoundingClientRect();
      return box.top>=Math.max(panel.top,rail.bottom)&&box.bottom<=Math.min(panel.bottom,innerHeight);
    };
    for(const width of [1280,1920,390]){
      await page.setViewportSize({width,height:720});
      await page.mouse.move(0,0);
      await step.scrollIntoViewIfNeeded();
      await page.locator('.results').evaluate(panel=>panel.scrollTop=0);
      assert.equal(await link.evaluate(visible),false);
      const before=await page.evaluate(()=>scrollY);
      await step.hover();
      await page.waitForFunction(visible,await link.elementHandle());
      if(width>760){
        assert.equal(await page.evaluate(()=>scrollY),before,'only the plan scrolls in side-by-side layouts');
        assert.equal(await page.locator('.plan-connector:not(.execution-plan-connector)').getAttribute('data-target'),'step-15');
      }
    }
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});

test('execution view opens beside the plan once per Run and preserves inspection state',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,errors}=await harness(browser);await choose(page);
    await page.locator('#run-direct').click();await tick(page);
    const graph=await build({stdin:{contents:"export {ExecutionHistory,renderExecutionHistory} from './src/browser/execution-history';",resolveDir:resolve('.')},bundle:true,write:false,format:'iife',globalName:'GraphFixture'});
    await page.addScriptTag({content:graph.outputFiles[0].text});
    await page.evaluate(()=>{
      window.graphHistory=new GraphFixture.ExecutionHistory(1,window.defaults);
      GraphFixture.renderExecutionHistory(window.graphHistory);
    });
    const panel=page.locator('#execution-history');
    assert.equal(await panel.getAttribute('open'),'');
    assert.equal(await panel.evaluate(el=>el.parentElement.matches('.execution-pane')),true,'graph lives in the execution pane');
    assert.equal(await page.locator('body').getAttribute('data-workspace-view'),'execution');
    const graphBox=await panel.boundingBox(),planBox=await page.locator('#output-plan').boundingBox();
    assert(planBox.x>=graphBox.x+graphBox.width,'output plan sits beside the graph');
    assert.equal(await panel.locator('.execution-viewport').isVisible(),true);
    assert.equal(await page.locator('#cancel').isVisible(),true);
    assert.ok((await page.locator('#cancel').boundingBox()).y<900,'sticky cancellation stays reachable above the wide graph');
    for(const width of [1280,390]){
      await page.setViewportSize({width,height:900});
      await page.evaluate(()=>{
        window.graphHistory.accept(1,{read:{status:'active',rows:1,bytes:20,seconds:0.1}});
        GraphFixture.renderExecutionHistory(window.graphHistory);
      });
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      if(process.env.CHOPPER_UI_SCREENSHOTS)await page.screenshot({path:resolve(process.env.CHOPPER_UI_SCREENSHOTS,`processing-${width}.png`),fullPage:true});
    }
    await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/result'});
    await page.waitForFunction(()=>document.getElementById('execution-phase').textContent.includes('2 CSV files saved'));
    assert.match(await page.locator('#execution-counters').innerText(),/destination\/result · 1 warning/);
    await page.locator('#execution-results-link').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'run-results');
    await panel.locator(':scope > summary').click();
    await page.evaluate(()=>{
      window.graphHistory.accept(1,{read:{status:'completed',rows:4,bytes:80,seconds:1}});
      GraphFixture.renderExecutionHistory(window.graphHistory);
    });
    assert.equal(await panel.getAttribute('open'),null,'updates respect a manually collapsed graph');
    await page.evaluate(()=>GraphFixture.renderExecutionHistory(new GraphFixture.ExecutionHistory(2,window.defaults)));
    assert.equal(await panel.getAttribute('open'),'','a new Run reveals the graph again');
    assert.deepEqual(errors,[]);await page.close();
  }finally{await browser.close();}
});


test('seeded saved jobs are rejected and resource controls are visible inline',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  assert.equal(await page.locator('#seed').count(),0);
  assert.equal(await page.locator('#review details').count(),0);
  assert.equal(await page.locator('#max-files').isVisible(),true);
  for(const field of ['seed','random_seed']){
   await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...defaults,[field]:'obsolete'}))});
   await page.waitForFunction(()=>document.getElementById('error').textContent.includes('no longer supported'));
   assert.equal(Object.hasOwn(await exported(page),field),false);
  }
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('execution cards retain peak height per Run and connectors attach to plan borders',async()=>{
 const renderer=await build({stdin:{contents:"export * from './src/browser/execution-history';",resolveDir:process.cwd()},bundle:true,write:false,format:'iife',globalName:'GraphFixture'});
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);
  const config={...defaults,input:'source.csv',output:'destination',operations:[{type:'assign',groups:[{name:'a',percent:'50'},{name:'b',percent:'50'}],strata:[]}]};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
  await page.addScriptTag({content:renderer.outputFiles[0].text});
  const sizes=await page.evaluate(config=>{
   const {ExecutionHistory,renderExecutionHistory}=GraphFixture;
   const job={...config,operations:[{...config.operations[0],groups:Array.from({length:16},(_,i)=>({name:'long allocation group '+i+' x'.repeat(15),percent:'6.25'}))}]};
   const h=new ExecutionHistory(700,job);h.accept(700,{physical:[{id:1040,kind:'exact_membership',operations:[1],status:'completed',rows:10000,groups:1,empty_groups:0,memberships:[10000],seconds:1}]});
   const measure=()=>document.querySelector('.execution-list li>button').offsetHeight;
   renderExecutionHistory(h);const short=measure();
   Object.assign(h.steps[0],{title:'Allocation scope '.repeat(16)});h.revision++;renderExecutionHistory(h);const tall=measure();
   Object.assign(h.steps[0],{title:'Allocation'});h.revision++;renderExecutionHistory(h);const shorter=measure();
   const fit=document.querySelector('[data-auto-fit]');fit.click();fit.click();const fitted=document.querySelector('.execution-list li>button').offsetHeight;
   const fresh=new ExecutionHistory(701,job);fresh.accept(701,{physical:[{...h.steps[0]}]});renderExecutionHistory(fresh);const reset=measure();
   return {short,tall,shorter,fitted,reset};
  },config);
  assert(sizes.tall>sizes.short,'longer live counters grow the card');assert.equal(sizes.shorter,sizes.tall,'shorter counters never shrink the card');assert.equal(sizes.fitted,Math.round(sizes.tall),'Fit preserves retained card height');assert(sizes.reset<=sizes.short,'a new Run starts with fresh card heights, independent of prior zoom');
  const source=page.locator('#execution-history .execution-list li>button');
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:width===390?1900:900});await source.hover();await page.waitForFunction(()=>document.querySelectorAll('.execution-plan-connector.is-visible circle').length===2&&document.querySelector('.execution-plan-connector').viewBox.baseVal.width===innerWidth);
   const geometry=await page.evaluate(()=>{
    const svg=document.querySelector('.execution-plan-connector'),dots=svg.querySelectorAll('circle'),source=document.querySelector('#execution-history .execution-list li>button').getBoundingClientRect(),plan=document.querySelector('.plan').getBoundingClientRect();
    return {start:Number(dots[0].getAttribute('cx')),end:Number(dots[1].getAttribute('cx')),source:source.toJSON(),plan:plan.toJSON(),paths:svg.querySelectorAll('path').length,radii:[...dots].map(dot=>dot.getAttribute('r'))};
   });
   assert(Math.abs(geometry.start-geometry.source.right)<1,'line starts at card border');
   assert(Math.abs(geometry.end-(width===1280?geometry.plan.left-5:geometry.plan.right+4))<1,'line ends at plan border for side-by-side and stacked layouts');
   assert.deepEqual(geometry.radii,['3.5','4']);assert.equal(geometry.paths,2);
  }
  const longConfig={...config,operations:[...config.operations,...Array.from({length:15},()=>({type:'shuffle'}))]};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(longConfig))});
  const target=page.locator('.plan-steps>li>button[data-plan-target="step-15"]');
  await target.waitFor({state:'attached'});
  await page.evaluate(job=>{
   const h=new GraphFixture.ExecutionHistory(702,job);
   h.accept(702,{physical:[{id:1040,kind:'resident_sort',operations:[16],status:'completed',rows:4,groups:1,seconds:1}]});
   GraphFixture.renderExecutionHistory(h);
  },longConfig);
  const state=()=>target.evaluate(el=>{
   const panel=el.closest('.results'),box=panel.getBoundingClientRect(),entry=el.getBoundingClientRect();
   const svg=document.querySelector('.execution-plan-connector.is-visible');
   return {scrollY,scrollTop:panel.scrollTop,visible:entry.top>=Math.max(box.top,0)&&entry.bottom<=Math.min(box.bottom,innerHeight),
     dots:svg?.querySelectorAll('circle').length??0,path:svg?.querySelector('.plan-connector-line')?.getAttribute('d')??''};
  });
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:720});await page.mouse.move(0,0);
   await source.scrollIntoViewIfNeeded();
   await target.evaluate(el=>el.closest('.results').scrollTop=0);
   const before=await state();assert.equal(before.visible,false);
   await source.hover();
   await page.waitForFunction(()=>document.querySelector('.execution-plan-connector.is-visible path'));
   const after=await state();
   assert.equal(after.scrollY,before.scrollY,'graph hover keeps the page in place');
   if(width===1280){
    assert.ok(after.visible&&after.scrollTop>before.scrollTop,'graph hover reveals the linked plan entry inside its panel');
    assert.equal(after.dots,2,'a visible entry gets its normal endpoint');
   }else{
    assert.equal(after.visible,false);
    assert.equal(after.dots,1,'an offscreen entry gets a continuation arrow');
    assert.match(after.path,/ M [\d.]+ [\d.]+ L [\d.]+ [\d.]+ L [\d.]+ [\d.]+$/);
    const coordinates=after.path.match(/-?[\d.]+/g).map(Number);
    assert.ok(coordinates.every((value,i)=>value>0&&value<(i%2?720:width)),'continuation stays within the screen');
   }
  }
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('terminal phase timing freezes and results are separate from the draft plan',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true);
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'running',progress:{phase:'Writing CSV',rows:100,temp_bytes:200}});
  await page.clock.runFor(1100);await page.waitForFunction(()=>document.getElementById('status').textContent==='RUNNING');
  const initial=await page.locator('#progress-detail').textContent();await page.clock.runFor(5000);assert.notEqual(await page.locator('#progress-detail').textContent(),initial,'busy phase time advances');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/result'});
  await page.clock.runFor(1100);await page.waitForFunction(()=>document.getElementById('status').textContent==='COMPLETE');
  assert.deepEqual(await page.locator('#result-path').evaluate(el=>[getComputedStyle(el).borderTopWidth,getComputedStyle(el).borderBottomWidth]),['0px','1px']);
  const stopped=await page.locator('#progress-detail').textContent();await page.clock.runFor(9000);assert.equal(await page.locator('#progress-detail').textContent(),stopped,'terminal polls cannot advance phase time');
  assert.equal(await page.locator('#progress').isHidden(),true);assert.equal(await page.locator('#output-plan #analysis').count(),0);assert.equal(await page.locator('#run-results #analysis').isVisible(),true);assert.equal(await page.locator('#run-results #result-path').isVisible(),true);assert.equal(await page.locator('#run-dock #run-direct').count(),1);
  for(const width of [390,1280,1920]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  const boxes=await page.locator('#output-plan,#run-results').evaluateAll(nodes=>nodes.map(node=>({box:node.getBoundingClientRect().toJSON(),divider:node.querySelector('.section-title').getBoundingClientRect().bottom})));assert(Math.abs(boxes[0].box.top-boxes[1].box.top)<1,'plan and results sit alongside each other on a wide screen');assert(Math.abs(boxes[0].box.height-boxes[1].box.height)<1,'paired cards have equal total heights');assert(Math.abs(boxes[0].divider-boxes[1].divider)<1,'paired title/body dividers align');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'cancelled',analysis:null});
  await page.clock.runFor(1100);await page.waitForFunction(()=>document.getElementById('status').textContent==='CANCELLED');
  assert.equal(await page.locator('#progress').isVisible(),true);
  assert.equal(await page.locator('#progress').evaluate(el=>getComputedStyle(el).borderBottomWidth),'0px');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('execution controls keep compact flow, full settings and keyboard navigation without card percentages',async()=>{
 const renderer=await build({stdin:{contents:"export * from './src/browser/execution-history';",resolveDir:process.cwd()},bundle:true,write:false,format:'iife',globalName:'GraphFixture'});
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(config=>{
   const h=new GraphFixture.ExecutionHistory(900,{...config,operations:[{type:'partition',columns:['country']},{type:'shuffle',strategy:'uniform'}],limits:{rows:100000,bytes:null,compressed_bytes:null}});h.accept(900,{read:{status:'active',rows:10,seconds:1}});GraphFixture.renderExecutionHistory(h);
  },defaults);
  const bar=page.getByRole('toolbar',{name:'Execution view controls'});
  const graph=bar.getByRole('button',{name:'Graph view',exact:true}),list=bar.getByRole('button',{name:'List view',exact:true});await graph.focus();await graph.press('ArrowRight');assert.equal(await list.evaluate(button=>button===document.activeElement),true);
  await list.press('Enter');assert.equal(await list.getAttribute('aria-pressed'),'true');await list.press('Home');assert.equal(await graph.evaluate(button=>button===document.activeElement),true);await graph.press('Enter');
  const flow=page.locator('.execution-flow');assert.equal(await flow.locator('button').count(),3);assert.doesNotMatch(await flow.textContent(),/rows:|compression:/);assert.match(await flow.locator('button').last().getAttribute('aria-label'),/rows: 100000/);await flow.locator('button').last().click();assert.match(await page.locator('.execution-inspector').textContent(),/rows: 100000/);
  assert.equal(await page.locator('.execution-node-percentage').count(),0);assert.doesNotMatch(await page.locator('.execution-list button').first().getAttribute('aria-label'),/% complete/);
  for(const width of [320,390,1280]){await page.setViewportSize({width,height:900});assert.equal(await bar.evaluate(el=>el.scrollWidth<=el.clientWidth),true);}
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('hosted visible text is readable and technical result metadata is disclosed on demand',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);
  const job={...defaults,input:'source.csv',output:'destination',operations:[{type:'partition',columns:['country']},{type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:[]},{type:'shuffle',strategy:'uniform'}]};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(()=>document.getElementById('input').value==='source.csv');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/result'});await page.waitForFunction(()=>document.getElementById('status').textContent==='COMPLETE');
  assert.equal(await page.locator('.analysis-details').getAttribute('open'),null);assert.equal(await page.locator('.analysis-details dd').last().isVisible(),false);await page.getByText('Processing details',{exact:true}).click();assert.equal(await page.locator('.analysis-details dd').last().isVisible(),true);
  await page.evaluate(()=>document.querySelectorAll('details').forEach(node=>node.open=true));
  const tiny=await page.evaluate(()=>{const found=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);for(let text;text=walker.nextNode();){if(!text.textContent.trim())continue;const el=text.parentElement;if(!el||el.closest('script,style,[aria-hidden=true],.sr-only'))continue;const range=document.createRange();range.selectNodeContents(text);if(!range.getBoundingClientRect().width||!range.getBoundingClientRect().height)continue;const px=parseFloat(getComputedStyle(el).fontSize);if(px<13)found.push({text:text.textContent.slice(0,70),px,tag:el.tagName,class:el.className});}return found;});assert.deepEqual(tiny,[],'visible text must be at least 13px at the default text preference');
  assert.equal(await page.locator('#input').evaluate(el=>getComputedStyle(el).fontSize),'14px');
  assert.equal(await page.locator('#input').evaluate(el=>getComputedStyle(el).fontWeight),'400');
  assert.equal(await page.locator('#input').evaluate(el=>getComputedStyle(el.labels[0]).fontWeight),'500');
  assert.equal(await page.locator('#source h2').evaluate(el=>getComputedStyle(el).fontWeight),'600');
  await page.evaluate(()=>document.documentElement.style.fontSize='20px');assert.equal(await page.locator('#input').evaluate(el=>getComputedStyle(el).fontSize),'17.5px');
  const touch=await browser.newContext({hasTouch:true,isMobile:true,viewport:{width:390,height:844}});
  try{const {page:touchPage}=await harness(touch);assert.equal(await touchPage.locator('#input').evaluate(el=>getComputedStyle(el).fontSize),'16px');}finally{await touch.close();}
  for(const width of [320,390]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'larger preferred text reflows on a narrow screen');}
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

for(const hosted of [true])test(`${hosted?'hosted':'native'} friendly units preserve defaults, exact imports and canonical submissions`,async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,hosted);await choose(page);
  assert.equal(await page.locator('#memory').inputValue(),'');assert.equal(await page.locator('#memory').getAttribute('placeholder'),'At Run');assert.equal(await page.locator('#memory-unit').inputValue(),'MiB');assert.equal(await page.locator('#max-record').inputValue(),'8');assert.equal(await page.locator('#max-record-unit').inputValue(),'MiB');
  assert.equal((await exported(page)).resources.memory_mb,'auto');
  for(const id of ['memory-mode','memory','memory-unit','workers','grouping']){
    assert.equal(await page.locator('#'+id).isVisible(),true);
    assert.equal(await page.locator('#'+id).isDisabled(),true);
  }
  assert.equal(await page.locator('#memory-mode').inputValue(),'auto');
  assert.equal(await page.locator('#grouping').inputValue(),'auto');
  assert.equal(await page.locator('#workers').inputValue(),'0');
  assert.equal(await page.locator('#max-files').isEnabled(),true);
  const mode=page.getByRole('switch',{name:'Advanced execution mode'});
  assert.equal(await mode.isChecked(),false);
  await mode.focus();await page.keyboard.press('Space');
  assert.equal(await mode.isChecked(),true);
  assert.equal(await page.locator('#memory').isEnabled(),true);
  assert.deepEqual((await exported(page)).resources,defaults.resources);
  await page.locator('#memory-unit').selectOption('GiB');assert.equal(await page.locator('#memory').inputValue(),'0.25');assert.equal((await exported(page)).resources.memory_mb,256);assert.match(await page.locator('#draft-resources').textContent(),/0.25 GiB/);
  assert.equal(await page.locator('#memory').getAttribute('max'),hosted?'2':'1024');
  await page.locator('#workers').fill('2');
  await page.locator('#grouping').selectOption('sort');
  await page.locator('#execution-mode').uncheck();
  assert.equal(await page.locator('#memory-unit').isDisabled(),true);
  assert.equal(await page.locator('#memory').inputValue(),'');
  assert.equal(await page.locator('#workers').inputValue(),'0');
  assert.equal(await page.locator('#grouping').inputValue(),'auto');
  assert.equal((await exported(page)).resources.memory_mb,'auto');
  await page.locator('#execution-mode').check();
  assert.equal(await page.locator('#memory').inputValue(),'0.25');
  assert.equal(await page.locator('#workers').inputValue(),'2');
  assert.equal(await page.locator('#grouping').inputValue(),'sort');
  assert.equal((await exported(page)).resources.memory_mb,256);

  if(hosted){await page.locator('#memory').fill('2');assert.equal((await exported(page)).resources.memory_mb,2048);await page.locator('#memory').fill('0.25');}
  await page.locator('#memory-mode').selectOption('auto');assert.equal(await page.locator('#memory-unit').isDisabled(),true);assert.equal((await exported(page)).resources.memory_mb,'auto');await page.locator('#memory-mode').selectOption('manual');assert.equal(await page.locator('#memory').inputValue(),'0.25');
  await page.locator('#max-bytes-unit').selectOption('MB');await page.locator('#max-bytes').fill('1.5');assert.equal((await exported(page)).limits.bytes,1500000);
  await page.locator('#max-bytes-unit').selectOption('MiB');assert.equal((await exported(page)).limits.bytes,1500000);
  const config={...defaults,input:'source.csv',output:'destination',limits:{...defaults.limits,bytes:Number.MAX_SAFE_INTEGER},resources:{...defaults.resources,max_record_bytes:8388609,temp_bytes:1099511627776}};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});await page.waitForFunction(()=>document.getElementById('max-bytes').value==='9007199254740991');
  await page.locator('#max-bytes-unit').selectOption('GiB');await page.locator('#max-record-unit').selectOption('MiB');assert.deepEqual((await exported(page)).limits,config.limits);assert.deepEqual((await exported(page)).resources,config.resources);
  await page.locator('#profile').click();await page.waitForFunction(()=>window.calls.some(call=>call.path==='profile'));const submitted=await page.evaluate(()=>window.calls.find(call=>call.path==='profile').data);assert.deepEqual(submitted.limits,config.limits);assert.deepEqual(submitted.resources,config.resources);
  await page.waitForFunction(()=>document.getElementById('status').textContent==='PROFILED');await page.locator('#memory-unit').selectOption('GiB');assert.equal(await page.locator('#run-direct').textContent(),'Run →','display-only unit changes keep Run available');await page.locator('#memory').fill('0.5');assert.match(await page.locator('#run-direct').textContent(),/Run/,'editing the amount changes the prepared draft');
  for(const width of [320,390,1280]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});


test('execution auto-fit follows width and new graph lanes until manual zoom disables it',async()=>{
 const renderer=await build({stdin:{contents:"export * from './src/browser/execution-history';",resolveDir:process.cwd()},bundle:true,write:false,format:'iife',globalName:'GraphFixture'});
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(config=>{window.liveGraph=new GraphFixture.ExecutionHistory(950,{...config,operations:[{type:'shuffle',strategy:'uniform'}]});liveGraph.accept(950,{read:{status:'active',rows:1,seconds:.1}});GraphFixture.renderExecutionHistory(liveGraph);},defaults);
  const panel=page.locator('#execution-history'),auto=panel.getByRole('checkbox',{name:'Auto-fit'});
  assert.match(await panel.locator('.execution-node-detail').first().innerText(),/avg 10 rows\/s/);
  assert.equal(await auto.isChecked(),true);assert.equal(await panel.getByRole('button',{name:'Advanced details'}).count(),0);assert.equal(await panel.locator('.execution-events,.execution-map-key,.execution-map-summary').count(),0);
  const scale=()=>panel.locator('.execution-stage').evaluate(el=>Number(el.style.getPropertyValue('--dag-zoom')));
  await page.evaluate(()=>{liveGraph.accept(950,{physical:[0,1,2,3].map(i=>({id:1040+i,kind:'resident_sort',operations:[1],sources:i?[1039+i]:[0],status:'active',rows:1,seconds:.1}))});GraphFixture.renderExecutionHistory(liveGraph);});
  await page.waitForFunction(()=>Number(document.querySelector('.execution-stage').style.getPropertyValue('--dag-zoom'))<1);const wide=await scale();
  assert.match(await panel.locator('.execution-flow-strategy').first().textContent(),/Random-key sort · in memory/);
  await page.setViewportSize({width:390,height:900});await page.waitForFunction(wide=>Number(document.querySelector('.execution-stage').style.getPropertyValue('--dag-zoom'))<wide,wide);const narrow=await scale();
  await panel.getByRole('slider',{name:'Zoom',exact:true}).press('ArrowRight');assert.equal(await auto.isChecked(),false);const manual=await scale();assert(manual>narrow);
  await page.setViewportSize({width:1280,height:900});await page.waitForTimeout(50);assert.equal(await scale(),manual,'manual zoom survives resize');
  await auto.check();await page.waitForFunction(manual=>Number(document.querySelector('.execution-stage').style.getPropertyValue('--dag-zoom'))!==manual,manual);
  await panel.getByRole('button',{name:'List view',exact:true}).click();assert.equal(await panel.locator('.execution-node-context').first().isVisible(),true);
  await page.evaluate(()=>{liveGraph.accept(950,{physical:[{id:1045,kind:'spill',operations:[1],status:'active',rows:0,seconds:0}]});GraphFixture.renderExecutionHistory(liveGraph);});
  assert.match(await panel.locator('.execution-flow-strategy').first().textContent(),/memory \+ external/);
  await panel.locator('[data-operation="1"]').click();assert.match(await panel.locator('.execution-inspector').textContent(),/Observed strategy: Random-key sort · memory \+ external/);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('timeline shows overlapping observed windows, supports selection and freezes on stop',async()=>{
 const renderer=await build({stdin:{contents:"export * from './src/browser/execution-history';export {TimingGapWriter} from './src/browser/execution-timing';",resolveDir:process.cwd()},bundle:true,write:false,format:'iife',globalName:'GraphFixture'});
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,false,true,false,true);await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(config=>{
   window.timelineHistory=new GraphFixture.ExecutionHistory(970,{...config,operations:[{type:'shuffle',strategy:'auto'}]});
   window.gapWriter=new GraphFixture.TimingGapWriter(buffer=>timelineHistory.addTimingGapBlock(970,buffer));
   timelineHistory.accept(970,{read:{status:'active',rows:1000,seconds:2},physical:[{id:1040,kind:'resident_sort',operations:[1],status:'active',rows:500,seconds:1}],timeline:[{step:0,start:0,last:4,status:'active'},{step:1040,start:2,last:4,status:'active'}],timeline_seconds:4});GraphFixture.renderExecutionHistory(timelineHistory);
  },defaults);
  const panel=page.locator('#execution-history');await panel.getByRole('button',{name:'Timeline view',exact:true}).click();
  assert.equal(await panel.locator('.execution-viewport').isVisible(),false);assert.equal(await panel.locator('.execution-zoom-controls').isVisible(),false);assert.equal(await panel.locator('.execution-timeline tr').count(),3);
  assert.match(await panel.locator('.execution-timeline-note').textContent(),/Gaps.*not parallel/);
  const lefts=await panel.locator('.execution-timeline-bar').evaluateAll(nodes=>nodes.map(n=>parseFloat(n.style.left)));assert.equal(lefts[0],0);assert(lefts[1]>0&&lefts[1]<100);
  const readBar=panel.locator('tr[data-timeline-row="0"] .execution-timeline-bar');
  const width=()=>readBar.evaluate(bar=>parseFloat(bar.style.width));
  const initialWidth=await width();
  const elapsed=await panel.locator('.execution-timeline-elapsed').textContent();await page.waitForFunction(before=>document.querySelector('.execution-timeline-elapsed').textContent!==before,elapsed);
  assert((await width())>initialWidth&&initialWidth<100,'a live bar that starts at zero visibly grows');
  const sort=panel.locator('tr[data-timeline-row="1040"]');
  const sortTimes=sort.locator('.execution-timeline-times');
  await page.evaluate(()=>{
   timelineHistory.accept(970,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'interrupted',rows:500,seconds:1}],timeline:[{step:1040,start:2,last:4.5,status:'interrupted'}],timeline_seconds:4.5});
   GraphFixture.renderExecutionHistory(timelineHistory);
  });
  assert.equal(await sort.getAttribute('data-status'),'in_progress');
  assert.equal(await sortTimes.textContent(),'2.0 s – 4.5 s · In Progress');
  const pausedClock=await panel.locator('.execution-timeline-elapsed').textContent();
  await page.waitForFunction(before=>document.querySelector('.execution-timeline-elapsed').textContent!==before,pausedClock);
  assert.equal(await sortTimes.textContent(),'2.0 s – 4.5 s · In Progress','the attempt window stops growing in the gap');
  await page.evaluate(()=>{
   gapWriter.record(1040,4.5,5);
   timelineHistory.accept(970,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'active',rows:0,seconds:0}],timeline:[{step:1040,start:2,last:5,status:'active'}],timeline_seconds:5});
   GraphFixture.renderExecutionHistory(timelineHistory);
  });
  assert.equal(await sort.getAttribute('data-status'),'in_progress');
  assert.notEqual(await sortTimes.textContent(),'2.0 s – 4.5 s · In Progress');
  assert.match(await sortTimes.textContent(),/1 pause \(0.5 s\)/);
  const segments=await sort.locator('.execution-timeline-bar').evaluateAll(bars=>bars.map(bar=>[parseFloat(bar.style.left),parseFloat(bar.style.width)]));
  assert.equal(segments.length,2);
  assert(segments[0][0]+segments[0][1]<segments[1][0],'observed work before and after the pause renders as separate segments');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await readBar.evaluate(bar=>getComputedStyle(bar).transitionDuration),'0s');
  const visibleClock=await panel.locator('.execution-timeline-elapsed').textContent();
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));timelineHistory.accept(970,{read:{status:'active',rows:2000,seconds:3},timeline:[{step:0,start:0,last:10,status:'active'}],timeline_seconds:10});GraphFixture.renderExecutionHistory(timelineHistory);});
  await page.waitForTimeout(350);assert.equal(await panel.locator('.execution-timeline-elapsed').textContent(),visibleClock,'hidden tabs retain data without redrawing the timeline');
  await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});assert.notEqual(await panel.locator('.execution-timeline-elapsed').textContent(),visibleClock);
  await panel.locator('tr[data-timeline-row="0"] .execution-timeline-track').click();assert.match(await panel.locator('.execution-inspector').textContent(),/Read input/);
  const button=panel.locator('button[data-timeline-step="1040"]');await button.focus();await page.keyboard.press('Enter');assert.equal(await button.getAttribute('aria-pressed'),'true');assert.match(await panel.locator('.execution-inspector').textContent(),/Resident random-key sort/);assert.equal(await button.evaluate(n=>n===document.activeElement),true);
  await page.evaluate(()=>{timelineHistory.interrupt('interrupted');GraphFixture.renderExecutionHistory(timelineHistory);});
  assert.match(await panel.locator('.execution-timeline-times').first().textContent(),/end not observed/);
  assert.match(await sortTimes.textContent(),/1 pause \(0.5 s\)/,'stopping leaves the earlier gap visible');
  const fill=await sort.locator('.execution-timeline-bar').evaluateAll(bars=>bars.map(bar=>{
   const style=getComputedStyle(bar);return {color:style.backgroundColor,border:style.borderTopStyle};
  }));
  assert.ok(fill.every(bar=>bar.color!=='rgba(0, 0, 0, 0)'),'interrupted work stays filled');
  assert.deepEqual(fill.map(bar=>bar.border),['solid','dashed'],'only the final attempt has an unobserved end');
  const stopped=await panel.locator('.execution-timeline-elapsed').textContent(),bars=await panel.locator('.execution-timeline-bar').evaluateAll(nodes=>nodes.map(n=>n.style.width));await page.waitForTimeout(350);assert.equal(await panel.locator('.execution-timeline-elapsed').textContent(),stopped);assert.deepEqual(await panel.locator('.execution-timeline-bar').evaluateAll(nodes=>nodes.map(n=>n.style.width)),bars);
  for(const width of [320,390,1280]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  await page.evaluate(()=>{
   for(let i=0;i<40;i++)gapWriter.record(1040,7+i,7.5+i);
   timelineHistory.accept(970,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'completed',rows:500,seconds:7}],processingComplete:true,timeline:[{step:1040,start:2,last:48,status:'completed'}],timeline_seconds:48});
   GraphFixture.renderExecutionHistory(timelineHistory);
  });
  assert.match(await sortTimes.textContent(),/41 pauses \(20.5 s\)/);
  assert.equal(await sort.locator('.execution-timeline-bar').count(),1,'dense traces keep a bounded number of elements');
  const pixels=await sort.locator('canvas').evaluate(canvas=>{
   const alpha=canvas.getContext('2d').getImageData(0,4,canvas.width,1).data.filter((_,i)=>i%4===3);
   return {filled:alpha.some(value=>value>0),gap:alpha.some(value=>value===0)};
  });
  assert.deepEqual(pixels,{filled:true,gap:true});
  await panel.getByRole('button',{name:'Graph view',exact:true}).click();assert.equal(await panel.locator('.execution-timeline').isVisible(),false);
  await page.evaluate(config=>{const next=new GraphFixture.ExecutionHistory(971,config);next.accept(971,{read:{status:'completed',rows:2,seconds:1}});GraphFixture.renderExecutionHistory(next);},defaults);
  await panel.getByRole('button',{name:'Timeline view',exact:true}).click();assert.equal(await panel.locator('.execution-timeline-empty').isVisible(),true);assert.equal(await panel.locator('button[data-timeline-step]').count(),1);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});


test('CLI handoff exports the current draft and copies a shell-safe command with visible failure feedback',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  const cli=page.locator('.cli-handoff');assert.equal(await cli.getAttribute('open'),null);
  await cli.locator('summary').click();
  await cli.getByRole('radio',{name:'Windows PowerShell'}).check();
  await page.locator('#max-rows').fill('1234');
  await page.locator('#input-csv').evaluate(element=>element.closest('details').open=true);
  await page.locator('#input-dialect-options > summary').click();
  await page.getByLabel('Trim field whitespace').selectOption('both');
  await page.getByLabel('Comment prefix').fill('# ');
  await page.getByLabel('Leading columns to drop').fill('1');
  await page.getByLabel('Skip rows with only empty fields').check();
  await page.waitForFunction(()=>window.calls.some(call=>call.path==='preview'&&call.data.input_dialect?.skip_columns===1));
  await cli.getByRole('button',{name:'Export job JSON'}).click();
  const job=await page.evaluate(async()=>JSON.parse(await window.exported.text()));
  assert.equal(job.input,'source.csv');assert.equal(job.output,'destination');assert.equal(job.limits.rows,1234);
  assert.deepEqual(job.input_dialect,{trim:'both',comment_prefix:'# ',skip_rows:0,skip_columns:1,skip_blank_rows:true});
  assert.match(await cli.innerText(),/full local paths/);
  assert.match(await cli.locator('#cli-command').textContent(),/--rows=1234/);
  assert.match(await cli.locator('#cli-command').textContent(),/--input-trim=both.*--input-comment-prefix=# .*--input-skip-columns=1.*--input-skip-blank-rows=true/);
  for(const type of ['shuffle','partition']){await page.locator('#new-operation').selectOption(type);await page.locator('#add-operation').click();}
  let command=await cli.locator('#cli-command').textContent();assert.ok(command.indexOf('--step=shuffle')<command.indexOf('--step=partition'));
  await page.locator('#operations [data-step="1"] [data-action="up"]').click();
  command=await cli.locator('#cli-command').textContent();assert.ok(command.indexOf('--step=partition')<command.indexOf('--step=shuffle'));
  await page.locator('#execution-mode').check();
  await page.locator('#memory').fill('0');
  assert.equal(await cli.getByRole('button',{name:'Copy command'}).isDisabled(),true);
  await page.locator('#memory').fill('256');assert.equal(await cli.getByRole('button',{name:'Copy command'}).isEnabled(),true);
  const {version}=JSON.parse(await readFile('package.json','utf8'));
  assert.ok((await cli.innerText()).includes(`Use Chopper ${version.split('.').slice(0,2).join('.')} with PowerShell`));
  assert.equal(await cli.getByRole('link').getAttribute('href'),'https://github.com/jsmatfess/chopper/releases');
  const checkCopy=async()=>{
   await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{if(window.denyClipboard)throw Error('Denied');window.copiedCommand=text;}}}));
   const button=cli.getByRole('button',{name:'Copy command'});await button.click();
   assert.equal(await page.evaluate(()=>window.copiedCommand),await cli.locator('#cli-command').textContent());
   assert.match(await cli.locator('#cli-command').textContent(),await cli.locator('[name=cli-platform]:checked').inputValue()==='windows'?/chopper.exe run/:/^\.\/chopper run/);
   await page.waitForFunction(()=>document.querySelector('.cli-copy-status').textContent.trim()==='Copied');
   assert.equal(await button.evaluate(el=>el===document.activeElement),true);
   await page.evaluate(()=>window.denyClipboard=true);await button.click();
   await page.waitForFunction(()=>document.querySelector('.cli-copy-status').textContent.includes('Copy failed'));
   assert.equal(await button.isEnabled(),true);
   await page.evaluate(()=>window.denyClipboard=false);
  };
  await checkCopy();
  for(const platform of ['linux','macos']){
   await cli.locator(`[name=cli-platform][value=${platform}]`).check();
   assert.equal(await cli.locator('.cli-copy-status').textContent(),'');
   assert.equal(await cli.getByRole('link').getAttribute('href'),platform==='linux'
    ? 'https://github.com/jsmatfess/chopper/releases'
    : 'https://github.com/jsmatfess/chopper#build-the-cli-from-source');
   assert.doesNotMatch(await cli.innerText(),/Run beside chopper.exe|Use PowerShell/);
   await checkCopy();
  }
  const windowsRadio=cli.getByRole('radio',{name:'Windows PowerShell'});await windowsRadio.focus();await windowsRadio.press('Space');await windowsRadio.press('ArrowRight');
  assert.equal(await cli.getByRole('radio',{name:'Linux Bash'}).isChecked(),true);
  assert.equal(await cli.getByRole('radio',{name:'Linux Bash'}).evaluate(el=>el===document.activeElement),true);
  await cli.getByRole('radio',{name:'Linux Bash'}).press('ArrowRight');assert.equal(await cli.getByRole('radio',{name:'macOS zsh / Bash'}).isChecked(),true);
  await page.locator('#max-rows').fill('1235');assert.equal(await cli.locator('[name=cli-platform]:checked').inputValue(),'macos');
  assert.match(await cli.locator('#cli-command').textContent(),/--rows=1235/);
  for(const width of [320,390,1280]){
   await page.setViewportSize({width,height:900});
   assert.equal(await cli.evaluate(el=>el.scrollWidth<=el.clientWidth),true,`CLI handoff fits at ${width}`);
   if(process.env.CHOPPER_UI_SCREENSHOTS){await mkdir(process.env.CHOPPER_UI_SCREENSHOTS,{recursive:true});await cli.screenshot({path:resolve(process.env.CHOPPER_UI_SCREENSHOTS,`cli-${width}.png`)});}
  }
  await page.addInitScript(()=>{delete window.CommandEvent;});await page.reload();await page.waitForFunction(()=>document.querySelector('#input-csv select'));
  await cli.locator('summary').click();await checkCopy();
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('hosted theme follows system, persists explicit choices, syncs tabs and keeps input analysis available',async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({colorScheme:'dark'});
 try{
  const {page,errors}=await harness(context);const theme=page.getByRole('button',{name:/Switch to .* theme/});
  const background=()=>page.evaluate(()=>getComputedStyle(document.body).backgroundColor);
  assert.equal(await theme.getAttribute('data-choice'),'system');assert.equal(await background(),'rgb(17, 24, 32)');
  await choose(page);await page.locator('#profile').click();await page.waitForFunction(()=>document.querySelector('#status').textContent==='PROFILED');
  await setTheme(page,'light');assert.equal(await background(),'rgb(244, 245, 247)');
  assert.equal(await page.locator('#browse-input').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)','control colors switch immediately with their text');
  assert.equal(await page.evaluate(()=>localStorage.getItem('chopper-color-scheme')),'light');
  assert.equal(await page.locator('#run-direct').textContent(),'Run →');
  await page.emulateMedia({colorScheme:'light'});await page.emulateMedia({colorScheme:'dark'});assert.equal(await background(),'rgb(244, 245, 247)');
  const {page:second,errors:secondErrors}=await harness(context);
  assert.equal(await second.getByRole('button',{name:/Switch to .* theme/}).getAttribute('data-choice'),'light');
  await setTheme(page,'dark');await second.waitForFunction(()=>document.querySelector('meta[name="color-scheme"]').content==='light dark');
  assert.equal(await second.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(17, 24, 32)');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#input-csv select'));assert.equal(await theme.getAttribute('data-choice'),'system');
  await theme.press('Enter');await theme.press('Enter');assert.equal(await page.evaluate(()=>localStorage.getItem('chopper-color-scheme')),null);
  await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(244, 245, 247)');
  await page.emulateMedia({colorScheme:'dark'});await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor==='rgb(17, 24, 32)');
  await page.waitForFunction(()=>document.querySelector('.theme-control button').title.includes('dark (system)'));
  assert.match(await theme.getAttribute('title'),/dark \(system\)/);
  assert.equal(await theme.getAttribute('aria-label'),'Switch to light theme');
  await page.evaluate(()=>localStorage.setItem('chopper-color-scheme','invalid'));await page.reload();await page.waitForFunction(()=>document.querySelector('#input-csv select'));assert.equal(await theme.getAttribute('data-choice'),'system');
  for(const width of [320,390,1280]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  assert.deepEqual(errors,[]);assert.deepEqual(secondErrors,[]);
 }finally{await context.close();await browser.close();}
});

test('theme works with blocked storage',async()=>{
 const browser=await chromium.launch({headless:true});const context=await browser.newContext({colorScheme:'dark'});
 try{
  await context.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Blocked','SecurityError');}}));
  const {page,errors}=await harness(context);const theme=page.getByRole('button',{name:/Switch to .* theme/});
  await setTheme(page,'light');assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(244, 245, 247)');
  await setTheme(page,'dark');assert.equal(await page.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgb(17, 24, 32)');
  assert.deepEqual(errors,[]);
 }finally{await context.close();await browser.close();}
});

test('config controls keep theme contrast, keyboard choices and resource defaults',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  const original=await exported(page);
  assert.deepEqual(await page.locator('#resource-settings .config-group legend').allTextContents(),['Processing','Safety limits · independent of Auto']);
  assert.equal(await page.locator('#temp-dir').isVisible(),false);
  assert.deepEqual((await exported(page)).resources,original.resources,'presentation preserves resource defaults');
  await page.locator('#new-operation').selectOption('balanced');await page.locator('#add-operation').click();
  const consecutive=page.getByRole('radio',{name:'Consecutive rows'});await consecutive.focus();await consecutive.press('ArrowRight');
  assert.equal(await page.getByRole('radio',{name:'Alternating rows'}).isChecked(),true);
  assert.equal((await exported(page)).operations[0].type,'interleaved');
  await page.locator('#new-operation').selectOption('assign');await page.locator('#add-operation').click();
  await page.locator('#source-settings>summary').click();await page.locator('#output-settings details>summary').click();
  await page.locator('.cli-handoff>summary').click();
  const captures=process.env.CHOPPER_CONFIG_SCREENSHOTS;if(captures)await mkdir(captures,{recursive:true});
  for(const theme of ['light','dark']){
   await setTheme(page,theme);
   const sections=await page.evaluate(()=>['source','output-settings','pipeline','review'].map(id=>{
    const header=document.querySelector(`#${id}>.section-title`),badge=document.querySelector(`[data-config-section="${id}"] .plan-section-index`);
    return {id,header:getComputedStyle(header).backgroundColor,badge:getComputedStyle(badge).backgroundColor,heading:getComputedStyle(header.querySelector('h2')).color,number:getComputedStyle(badge).color};
   }));
   for(const key of ['header','badge','heading','number'])assert.equal(new Set(sections.map(section=>section[key])).size,1,`${theme} section colors use a consistent palette`);
   assert.equal(await page.evaluate(()=>getComputedStyle(document.querySelector('main>header')).backgroundImage),'none');
   assert.equal(await page.evaluate(()=>getComputedStyle(document.body,'::before').backgroundImage.startsWith('linear-gradient')),true);
   const colors=await page.evaluate(()=>{
    const rgb=selector=>getComputedStyle(document.querySelector(selector)).backgroundColor.match(/\d+/g).slice(0,3).map(Number);
    const lum=rgb=>rgb.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
    return {run:lum(rgb('#run-direct')),browse:lum(rgb('#browse-input')),theme:lum(rgb('.rail')),cli:lum(rgb('.cli-platform-tabs input:checked+span'))};
   });
   assert(colors.run<.2,`${theme} Run should use a subdued dark green`);
   if(theme==='light')for(const key of ['browse','theme','cli'])assert(colors[key]>.75,`${key} should use a light surface`);
   for(const width of [320,390,760,1440,1920,2560]){
    await page.setViewportSize({width,height:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`${theme} config overflow at ${width}`);
    const alignment=await page.evaluate(()=>({title:document.querySelector('main>header').getBoundingClientRect().x,shell:document.querySelector('.configuration-shell').getBoundingClientRect().x}));
    assert(Math.abs(alignment.title-alignment.shell)<1,'idle title aligns with the configuration shell');
    if(captures&&[390,1440,2560].includes(width)){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`${captures}/config-${theme}-${width}.png`,fullPage:true});}
   }
  }
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

for(const scrollspy of [true,false])test(`hosted navigation (${scrollspy?'native':'fallback'}), nearby file context, compact plan and processing strip work together`,async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true,scrollspy);
  await page.evaluate(()=>{const input=document.getElementById('input');input.dataset.fileName='source.csv';input.dataset.fileBytes=String(2*1024**2);});
  await choose(page);await page.waitForFunction(()=>document.getElementById('source-facts').textContent.includes('2 columns'));
  assert.match(await page.locator('#source-facts').textContent(),/2 MiB · 2 columns/);
  assert.equal(await page.locator('#source #preview-card').isVisible(),true);
  assert.equal(await page.getByRole('table',{name:'Input preview sample'}).count(),1);
  for(const type of ['shuffle','balanced','assign']){await page.locator('#new-operation').selectOption(type);await page.locator('#add-operation').click();}
  assert.equal(await page.locator('.step-description').count(),3);assert.equal(await page.locator('.operation-icon svg').count(),3);
  const rules=page.locator('.plan-step-details[data-target="step-0"]');assert.equal(await rules.evaluate(el=>el.open),false);
  assert.match(await page.locator('.plan-steps>li').first().innerText(),/Shuffle rows within each group/);
  await rules.locator('summary').click();await page.locator('#max-rows').fill('20');assert.equal(await rules.evaluate(el=>el.open),true,'draft refresh retains the open explanation');
  for(const id of ['output-settings','calculated-columns','pipeline','review','source']){
   await page.locator(`.workspace-nav a[href="#${id}"]`).click();
   await page.clock.runFor(100);
   assert.equal(await page.evaluate(()=>document.activeElement.id),id);
   await page.waitForFunction(id=>document.querySelector(`.workspace-nav a[href="#${id}"]`).hasAttribute('aria-current'),id);
   assert.equal(await page.locator('.workspace-nav [aria-current]').count(),1);
  }
  await page.setViewportSize({width:1920,height:900});
  await page.evaluate(()=>scrollTo(0,document.getElementById('output-settings').getBoundingClientRect().top+scrollY-350));await page.clock.runFor(100);
  const beforeCardClick=await page.evaluate(()=>({y:scrollY,history:history.length}));
  await page.locator('#output-settings h2').click();await page.clock.runFor(100);
  assert.equal(await page.evaluate(()=>scrollY),beforeCardClick.y,'card selection preserves scroll position');
  assert.equal(await page.evaluate(()=>history.length),beforeCardClick.history,'card selection replaces the current history entry');
  assert.equal(await page.evaluate(()=>location.hash),'#output-settings');
  assert.equal(await page.locator('.workspace-nav [aria-current]').getAttribute('href'),'#output-settings');
  assert.equal(await page.locator('.workspace-nav a').evaluateAll(links=>links.filter(link=>getComputedStyle(link).borderBottomColor!== 'rgba(0, 0, 0, 0)').length),1,'clicked section is the only visually active link');
  await page.evaluate(()=>{scrollBy(0,40);document.dispatchEvent(new Event('scroll'));});await page.clock.runFor(100);
  assert.equal(await page.locator('.workspace-nav').getAttribute('data-selected'),null,'scrolling resumes visible-section tracking');
  const compact=await page.locator('.workspace-toolbar').boundingBox(),workspace=await page.locator('.workspace').boundingBox();
  assert(compact.x+compact.width<workspace.x,'rail sits beside the configuration');
  assert.equal(await page.locator('.workspace-nav').evaluate(nav=>getComputedStyle(nav).flexDirection),'column','wide navigation uses vertical links');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'running',progress:{phase:'Sorting rows',rows:100,temp_bytes:200}});await tick(page);
  assert.equal(await page.locator('#processing-strip').isVisible(),true);
  const elapsedBefore=parseInt(await page.locator('#processing-elapsed').textContent(),10);await page.clock.runFor(4100);
  assert(parseInt(await page.locator('#processing-elapsed').textContent(),10)>elapsedBefore,'elapsed time advances across processing polls');
  await page.evaluate(()=>{const graph=document.createElement('details');graph.id='execution-history';graph.innerHTML='<summary>Execution</summary><p>Fixture graph</p>';document.querySelector('.execution-pane').append(graph);});
  await page.locator('#processing-view').click();assert.equal(await page.locator('#execution-history').evaluate(el=>el.open),true);assert.equal(await page.evaluate(()=>document.activeElement.id),'execution-history');
  await page.locator('.workspace-view-controls [data-workspace-view=configuration]').click();
  for(const width of [320,390,760,1440,1920,2560]){
   await page.setViewportSize({width,height:900});await page.locator('.workspace-nav a[href="#review"]').click();await page.clock.runFor(100);
   const rail=await page.locator('.rail').boundingBox(),bar=await page.locator('.workspace-toolbar').boundingBox();
   const railOffset=width<=640?0:rail.height;
   if(width<1600){assert(Math.abs(bar.y-railOffset)<1,'top navigation stays flush with the sticky stack');assert(bar.height<60,'top navigation stays compact');}
   else{
    assert(Math.abs(bar.y-railOffset-16)<1,'wide section navigation stays within reach');
    const sidebar=await page.locator('.workspace-sidebar').boundingBox();
    assert.equal(bar.width,sidebar.width,'nav fills the desktop sidebar');
   }
   const bottom=await page.locator('#run-dock').boundingBox();assert(Math.abs(bottom.y+bottom.height-900)<1,'processing bar sits at the viewport bottom');assert(bottom.height<110,'processing bar stays compact');
   await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));await page.clock.runFor(100);const last=await page.locator('#review').evaluate(el=>el.getBoundingClientRect().bottom);assert(last<=bottom.y,'bottom padding keeps the final content above processing controls');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`busy overflow at ${width}`);
   if(process.env.CHOPPER_CONFIG_SCREENSHOTS&&[390,1920].includes(width)){const dir=process.env.CHOPPER_CONFIG_SCREENSHOTS;await mkdir(dir,{recursive:true});await page.screenshot({path:`${dir}/processing-${scrollspy?'native':'fallback'}-${width}.png`});}
  }
  if(process.env.CHOPPER_CONFIG_SCREENSHOTS){const dir=process.env.CHOPPER_CONFIG_SCREENSHOTS;await mkdir(dir,{recursive:true});await page.screenshot({path:`${dir}/processing-${scrollspy?'native':'fallback'}.png`});}
  await page.locator('#cancel').click();await tick(page);
  assert.equal(await page.locator('#processing-strip').isHidden(),true);assert.equal(await page.evaluate(()=>window.calls.filter(c=>c.path!=='state').at(-1).path),'cancel');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('input analysis finishes visibly after unrelated configuration edits',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  await page.evaluate(()=>window.deferProfile=true);await page.locator('#profile').click();
  assert.equal(await page.locator('#status').textContent(),'PROFILING');
  await page.locator('#max-rows').fill('12');
  await page.evaluate(()=>window.finishProfile());await tick(page);
  assert.equal(await page.locator('#status').textContent(),'PROFILED');
  assert.equal(await page.locator('#input-profile').isVisible(),true,'completed input analysis stays visible after output settings change');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'max-rows','completion preserves editor focus');
  assert.match(await page.locator('#input-profile').innerText(),/4/);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('column inspection lives by the preview, survives config edits, and retires on source changes',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);
  await page.evaluate(()=>{
   const header=['country','note','segment','label','status','bucket'];
   window.previewFixture={columns:6,header,preview:[['US','sample','a','first','active','1']],input_is_zip:false};
   window.profileFixture={suggested_run_memory_mb:512,rows:4000,columns:6,header,seconds:1.25,cache_hit:false,accuracy:'Full-file fixture count; selected-column distinct values may use estimates.',stages:[{operation:1,strategy:'automatic grouping',input_distinct_keys:12,distinct_exact:false}],column_values:header.map((name,column)=>({column,values:column===0?['US','CA','<img src=x onerror=alert(1)>','']:['sample','second'],frequencies:column===0?{'US':3000,'CA':500,'<img src=x onerror=alert(1)>':499,'':1}:column===1?{}:{sample:3000,second:1000},truncated:column===1,distinct:column===1?1000:column===0?4:2,distinct_exact:column!==1}))};
  });
  await choose(page);await page.locator('#profile').click();
  assert.match(await page.locator('#input-profile').innerText(),/4,000/);
  assert.match(await page.locator('#input-profile').innerText(),/Run memory target · estimated\s+512.0 MiB/);
  assert.equal(await page.locator('#source #input-values').isVisible(),true);
  assert.equal(await page.locator('.column-values-row[open]').count(),0,'column values start collapsed');
  await page.locator('.column-values-row>summary').first().click();
  await page.locator('.column-values-row .value-label').first().waitFor();
  assert.equal(await page.locator('#run-results .value-chips').count(),0);
  assert.match(await page.locator('#input-values').innerText(),/<img src=x onerror=alert\(1\)>/);assert.equal(await page.locator('#input-values img').count(),0);
  assert.match(await page.locator('.column-values-count').nth(1).textContent(),/~1K distinct · estimated/);
  assert.deepEqual(await page.locator('.column-values-row').first().locator('.value-label').allTextContents(),['US','CA','<img src=x onerror=alert(1)>','(empty)']);
  assert.deepEqual(await page.locator('.column-values-row').first().locator('.value-share').allTextContents(),['75%','12.5%','12.5%','<0.1%']);
  assert.equal(await page.locator('.column-values-row').nth(1).locator('.value-distribution').count(),0,'truncated columns do not present partial counts as shares');
  assert.equal(await page.locator('.column-values-row').first().locator('.value-fill').first().evaluate(el=>el.style.inlineSize),'75%');

  const before=await exported(page);await page.locator('[data-inspection-search]').fill('country');
  assert.equal(await page.locator('.column-values-row:visible').count(),1);assert.deepEqual(await exported(page),before,'column search is not a job edit');
  await page.locator('[data-inspection-search]').fill('missing');assert.equal(await page.locator('.input-values-empty').isVisible(),true);await page.locator('[data-inspection-search]').fill('');
  await page.locator('#max-rows').fill('20');await tick(page);
  assert.equal(await page.locator('#input-profile').isVisible(),true);assert.equal(await page.locator('#input-values').isVisible(),true);assert.match(await page.locator('.profile-context').innerText(),/Input unchanged/);
  assert.doesNotMatch(await page.locator('#input-profile').innerText(),/Run memory target|Pipeline estimates/);
  assert.equal(await page.locator('.column-values-row').count(),6);
  await page.locator('#run-direct').click();
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:{...window.analysis,column_values:[{column:0,values:['different'],truncated:false}]},output:'destination/results'});
  await tick(page);
  assert.match(await page.locator('#input-values-origin').textContent(),/Full-file input analysis/);
  assert.equal(await page.locator('.column-values-row').count(),6);

  for(const mode of ['light','dark']){
   await setTheme(page,mode);
   await page.locator('.column-values-row').first().evaluate(el=>el.open=true);
   assert.equal(await page.locator('.column-values-name').first().isVisible(),true,'column names stay visible on narrow screens');assert.equal(await page.locator('.column-values-count').first().isVisible(),true,'column counts stay visible on narrow screens');
   const insets=await page.locator('.column-values-row>summary').first().evaluate(el=>{
    const box=el.getBoundingClientRect(),badge=el.querySelector('.column-values-count').getBoundingClientRect();
    return {start:parseFloat(getComputedStyle(el).paddingInlineStart),end:box.right-badge.right};
   });
   assert(insets.start>=10,`${mode} expanded chevron has room to rotate inside the summary`);
   assert(insets.end>=10,`${mode} count badge is inset from the summary edge`);
   const contrasts=await page.evaluate(()=>{
    const rgb=text=>text.match(/[\d.]+/g).slice(0,3).map(Number),lum=color=>rgb(color).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((sum,x,i)=>sum+x*[.2126,.7152,.0722][i],0);
    return [...document.querySelectorAll('#run-direct,#input-values h3,#input-values-origin,.column-values-name,.column-values-count,#input-values input,.value-chips li')].map(node=>{let surface=node;while(getComputedStyle(surface).backgroundColor==='rgba(0, 0, 0, 0)')surface=surface.parentElement;const a=lum(getComputedStyle(node).color),b=lum(getComputedStyle(surface).backgroundColor);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);});
   });
   assert(contrasts.every(ratio=>ratio>=4.5),`${mode} inspector text contrast: ${contrasts}`);
  }
  if(process.env.CHOPPER_PROFILE_SCREENSHOTS){const dir=process.env.CHOPPER_PROFILE_SCREENSHOTS;await mkdir(dir,{recursive:true});for(const theme of ['light','dark']){await setTheme(page,theme);await page.setViewportSize({width:1440,height:1000});await page.locator('#input-values').evaluate(el=>el.scrollIntoView({block:'start'}));await page.locator('#input-values').screenshot({path:`${dir}/column-values-${theme}.png`});await page.locator('#run-results').screenshot({path:`${dir}/analysis-${theme}.png`});}}
  for(const width of [320,390,760,1920]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  await page.locator('#source-settings>summary').click();await page.locator('#input-csv [data-csv=delimiter]').fill(';');await tick(page);
  assert.equal(await page.locator('#input-values .column-values-count').count(),0,'parser changes retire the old column counts');
  assert.equal(await page.locator('#input-profile').isHidden(),true,'parser changes retire the source profile after Run');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('column explorer starts from the preview and keeps search and distributions across layouts',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);
  await page.setViewportSize({width:1600,height:800});
  await page.evaluate(()=>{
   const header=['country','note','segment','label','status','bucket',...Array.from({length:34},(_,index)=>'extra '+index)];
   window.previewFixture={columns:header.length,header,preview:[header.map(()=> 'A')]};
   window.profileFixture={rows:2_000_000,columns:header.length,header,seconds:1,cache_hit:false,accuracy:'Fixture',stages:[],
    column_values:header.map((_,column)=>({column,values:['A','B'],frequencies:{A:1_000_000,B:1_000_000},distinct:2,distinct_exact:true,truncated:false}))};
  });
  await choose(page);
  const search=page.getByRole('searchbox',{name:'Find a column'});
  const panel=page.getByRole('region',{name:'Column explorer'});
  const country=panel.locator('[data-column="0"]');
  await page.locator('.workspace-sidebar > #input-values').waitFor();
  assert.equal(await panel.locator('.column-values-name').count(),40);
  assert.equal(await panel.locator('.column-values-count').count(),0);
  assert.equal(await panel.locator('.input-values-list').evaluate(list=>list.scrollHeight>list.clientHeight),true);
  await search.fill('country');
  await panel.getByRole('button',{name:'Analyze input'}).click();
  const countryDisclosure=country.locator('summary');
  await countryDisclosure.click();
  await country.getByText('50%',{exact:true}).first().waitFor();
  assert.equal(await search.inputValue(),'country');
  assert.deepEqual(await country.locator('.value-frequency').allTextContents(),['1M','1M']);
  assert.equal(await country.locator('.column-values-index').textContent(),'$0');
  await search.fill('');
  const second=panel.locator('[data-column="1"]');
  await second.locator('summary').click();
  await second.getByText('50%',{exact:true}).first().waitFor();
  assert.equal(await panel.locator('details[open]').count(),2,'columns expand independently');
  await search.fill('country');
  for(const theme of ['light','dark']){
   await setTheme(page,theme);
   const chrome=await page.evaluate(()=>['.workspace-toolbar','#input-values'].map(selector=>{
    const rules=getComputedStyle(document.querySelector(selector));
    return [rules.backgroundColor,rules.borderTopColor];
   }));
   assert.deepEqual(chrome[0],chrome[1],`${theme} explorer uses the navigation palette`);
  }
  await search.focus();
  for(const width of [1600,1920]){
   await page.setViewportSize({width,height:800});
   assert.equal(await search.evaluate(input=>input===document.activeElement),true);
   assert.equal(await countryDisclosure.evaluate(summary=>summary.parentElement.open),true);
   assert.deepEqual(await country.locator('.value-share').allTextContents(),['50%','50%']);
   const [nav,values,editor,dock]=await Promise.all([
    page.locator('.workspace-toolbar').boundingBox(),panel.boundingBox(),page.locator('#source').boundingBox(),page.locator('#run-dock').boundingBox(),
   ]);
   assert(nav.y+nav.height<values.y&&values.x+values.width<=editor.x,'the explorer is a separate card below the nav');
   assert.equal(nav.x,values.x,'sidebar cards share their left edge');
   assert.equal(nav.width,values.width,'navigation matches the explorer width');
   assert(values.y+values.height<=dock.y,'sidebar clears the bottom Run controls');
  }
  await page.setViewportSize({width:1599,height:800});
  await page.locator('#source #input-values').waitFor();
  assert.equal(await search.inputValue(),'country');
  assert.equal(await search.evaluate(input=>input===document.activeElement),true);
  assert.equal(await country.locator('summary').evaluate(summary=>summary.parentElement.open),true);
  const editorBackgrounds=await page.evaluate(()=>['#source .section-title','#input-values'].map(selector=>
   getComputedStyle(document.querySelector(selector)).backgroundColor));
  assert.equal(editorBackgrounds[0],editorBackgrounds[1],'Source explorer uses the editor palette');

  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('a profile finishing after another selection of the same filename is not applied to that file',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);await page.evaluate(()=>window.deferProfile=true);await page.locator('#profile').click();
  await page.locator('#browse-input').click();await page.evaluate(()=>window.finishProfile());await tick(page);
  assert.match(await page.locator('#input-profile').innerText(),/different input/);assert.equal(await page.locator('#input-values .column-values-count').count(),0);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('filtering completed column values keeps the analysis source and fresh Run action',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  await page.evaluate(()=>window.analysis={...window.analysis,column_values:Array.from({length:2},(_,column)=>({column,values:['a','b'],truncated:false}))});
  await page.locator('#run-direct').click();await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/result'});await tick(page);assert.equal(await page.locator('#run-direct').innerText(),'Run →');
  assert.match(await page.locator('#input-values-origin').innerText(),/Completed output analysis/);
  assert.equal(await page.locator('.column-values-row[open]').count(),0,'completed values also start collapsed');
  await page.locator('[data-inspection-search]').fill('country');await tick(page);
  assert.equal(await page.locator('.column-values-row:visible').count(),1);assert.equal(await page.locator('#run-direct').innerText(),'Run →');
  await page.locator('#run-direct').click();assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.path!=='state').at(-1).path),'run-direct');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('Analyze shows an updating row count in the bottom bar',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  await page.setViewportSize({width:320,height:800});
  for(const count of [0,1,12345678]){
   await page.evaluate(rows=>window.fixtureState={...window.fixtureState,status:'profiling',progress:{phase:'Profiling all input records',rows,temp_bytes:0}},count);
   await tick(page);
   assert.equal(await page.locator('#processing-rows').innerText(),`${count.toLocaleString('en-US')} ${count===1?'row':'rows'} scanned`);
   const [rows,actions]=await Promise.all([page.locator('#processing-rows').boundingBox(),page.locator('.processing-actions').boundingBox()]);
   assert(rows.x+rows.width<=actions.x,'row total stays clear of the processing actions');
  }
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'running'});await tick(page);
  assert.equal(await page.locator('#processing-rows').isHidden(),true);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('bottom action bar returns to Run and focuses results or the error',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  for(const terminal of ['complete','failed']){
   await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'running',error:null,progress:{phase:'Writing CSV',rows:10,temp_bytes:0}});await tick(page);
   await page.locator('#processing-view').focus();
   await page.evaluate(status=>window.fixtureState={...window.fixtureState,status,error:status==='failed'?'Fixture write failed':null,analysis:window.analysis,output:'destination/result'},terminal);await tick(page);
   assert.equal(await page.locator('#processing-strip').isHidden(),true);
   assert.equal(await page.evaluate(()=>document.activeElement.id),terminal==='failed'?'error':'run-results');
   const dock=await page.locator('#run-dock').boundingBox();
   assert.ok(Math.abs(await page.locator('main').evaluate(el=>parseFloat(getComputedStyle(el).paddingBottom))-dock.height-24)<1,'completed jobs reserve the idle Run bar height');
  }
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('pipeline handles preview insertion gaps, retain settings, and keep arrow controls',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  for(const type of ['partition','balanced','shuffle']){await page.locator('#new-operation').selectOption(type);await page.locator('#add-operation').click();}
  await page.locator('#execution-mode').check();
  await page.locator('[data-step="1"] [data-field=files]').fill('7');await page.locator('[data-field=strategy]').selectOption('uniform');
  await page.locator('[data-step="0"] [data-column-search]').fill('country');await page.keyboard.press('Enter');
  const original=(await exported(page)).operations;
  await page.locator('#execution-mode').uncheck();
  assert.match(await page.locator('.auto-shuffle-strategy').innerText(),/Shuffle strategy set by Auto · Full shuffle/);
  assert.equal((await exported(page)).operations[2].strategy,'auto');
  await page.locator('#execution-mode').check();
  assert.equal(await page.locator('[data-field=strategy]').inputValue(),'uniform');
  await page.locator('#profile').click();assert.equal(await page.locator('#run-direct').innerText(),'Run →');
  const drag=await page.evaluateHandle(()=>new DataTransfer());
  await page.locator('[data-step="1"] [data-step-grip]').dispatchEvent('dragstart',{dataTransfer:drag});
  const first=page.locator('[data-step="0"]'),box=await first.boundingBox();
  await first.dispatchEvent('dragover',{dataTransfer:drag,clientY:box.y+2,clientX:box.x+10});
  assert.equal(await first.getAttribute('data-drop'),'before');
  if(process.env.CHOPPER_REORDER_SCREENSHOTS){const dir=process.env.CHOPPER_REORDER_SCREENSHOTS;await mkdir(dir,{recursive:true});await page.setViewportSize({width:1440,height:1600});await page.locator('#pipeline').screenshot({path:`${dir}/pipeline-drop.png`});}
  assert.deepEqual((await exported(page)).operations,original,'preview does not mutate the job');
  await first.dispatchEvent('drop',{dataTransfer:drag});
  assert.equal(await page.locator('[data-drop],.step.is-dragging').count(),0);assert.match(await page.evaluate(()=>document.activeElement.getAttribute('aria-label')),/Reorder step 1/);
  assert.deepEqual((await exported(page)).operations,[original[1],original[0],original[2]]);assert.doesNotMatch(await page.locator('#run-direct').innerText(),/Confirm/);
  await page.locator('[data-step="0"] [data-step-grip]').focus();await page.keyboard.press('ArrowDown');assert.deepEqual((await exported(page)).operations,original,'handle keyboard movement preserves the complete operation');
  await page.locator('[data-step="1"] [data-action=down]').click();assert.deepEqual((await exported(page)).operations,[original[0],original[2],original[1]],'existing arrows still work');
  await page.locator('#profile').click();
  await page.locator('[data-step="0"] [data-step-grip]').dispatchEvent('dragstart',{dataTransfer:drag});
  const own=await page.locator('[data-step="0"]').boundingBox();await page.locator('[data-step="0"]').dispatchEvent('dragover',{dataTransfer:drag,clientY:own.y+2});
  assert.equal(await page.locator('[data-drop]').count(),0);await page.locator('[data-step="0"]').dispatchEvent('drop',{dataTransfer:drag});assert.equal(await page.locator('#run-direct').innerText(),'Run →','dropping in place leaves Run available');
  const before=(await exported(page)).operations;
  await page.locator('[data-step="0"] [data-step-grip]').dispatchEvent('dragstart',{dataTransfer:drag});
  const end=page.locator('[data-step="2"]'),endBox=await end.boundingBox();await end.dispatchEvent('dragover',{dataTransfer:drag,clientY:endBox.y+endBox.height-2});assert.equal(await end.getAttribute('data-drop'),'after');
  await page.locator('[data-step="0"] [data-step-grip]').press('Escape');assert.equal(await page.locator('[data-drop]').count(),0);assert.deepEqual((await exported(page)).operations,before);
  for(const width of [320,390,1440]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('partition column drops show before/after targets including wrapped rows and the end',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  const job={...defaults,input:'source.csv',output:'destination',operations:[{type:'partition',columns:['country','note',0,1]},{type:'partition',columns:['country','note']}]};
  await page.locator('#import-file').setInputFiles({name:'job.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(job))});await page.waitForFunction(()=>document.querySelectorAll('.column-chip').length===6);
  await page.setViewportSize({width:390,height:1000});
  const picker=page.locator('[data-step="0"] [data-column-field=columns]'),chips=picker.locator('.column-chip'),drag=await page.evaluateHandle(()=>new DataTransfer());
  await chips.first().locator('.chip-grip').dispatchEvent('dragstart',{dataTransfer:drag});
  const last=await chips.last().boundingBox();await picker.locator('.column-input').dispatchEvent('dragover',{dataTransfer:drag,clientX:last.x+last.width+3,clientY:last.y+last.height/2});
  assert.equal(await chips.last().getAttribute('data-column-drop'),'after');
  if(process.env.CHOPPER_REORDER_SCREENSHOTS){const dir=process.env.CHOPPER_REORDER_SCREENSHOTS;await mkdir(dir,{recursive:true});await picker.screenshot({path:`${dir}/column-drop.png`});}
  assert.deepEqual((await exported(page)).operations[0].columns,job.operations[0].columns);
  await picker.locator('.column-input').dispatchEvent('drop',{dataTransfer:drag});assert.deepEqual((await exported(page)).operations[0].columns,['note',0,1,'country']);assert.equal(await page.locator('[data-column-drop]').count(),0);
  await chips.last().locator('.chip-grip').dispatchEvent('dragstart',{dataTransfer:drag});const first=await chips.first().boundingBox();await chips.first().dispatchEvent('dragover',{dataTransfer:drag,clientX:first.x+1,clientY:first.y+first.height/2});assert.equal(await chips.first().getAttribute('data-column-drop'),'before');
  await chips.first().dispatchEvent('drop',{dataTransfer:drag});assert.deepEqual((await exported(page)).operations[0].columns,job.operations[0].columns);
  await chips.first().locator('.chip-grip').focus();await page.keyboard.press('ArrowRight');assert.deepEqual((await exported(page)).operations[0].columns,['note','country',0,1],'column grip keyboard reorder remains available');
  await chips.first().locator('.chip-grip').dispatchEvent('dragstart',{dataTransfer:drag});const other=page.locator('[data-step="1"] .column-input');await other.dispatchEvent('dragover',{dataTransfer:drag});assert.equal(await page.locator('[data-column-drop]').count(),0);await other.dispatchEvent('drop',{dataTransfer:drag});assert.deepEqual((await exported(page)).operations[1].columns,['country','note'],'cross-picker drops are rejected');
  const selected=(await exported(page)).operations[0].columns;await chips.first().locator('.chip-grip').dispatchEvent('dragstart',{dataTransfer:drag});await page.locator('#add-operation').click();await page.locator('[data-step="0"] .column-input').dispatchEvent('drop',{dataTransfer:drag});assert.deepEqual((await exported(page)).operations[0].columns,selected,'a rerendered picker rejects stale drags');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('native browser drag gestures reorder steps and selected partition columns',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await choose(page);
  for(const type of ['shuffle','balanced']){await page.locator('#new-operation').selectOption(type);await page.locator('#add-operation').click();}
  const firstStep=page.locator('[data-step="0"] .step-head');
  await firstStep.evaluate(el=>el.scrollIntoView({block:'center'}));
  await page.locator('[data-step="1"] [data-step-grip]').dragTo(firstStep,{targetPosition:{x:50,y:2}});
  assert.deepEqual((await exported(page)).operations.map(op=>op.type),['balanced','shuffle']);
  await page.locator('#new-operation').selectOption('partition');await page.locator('#add-operation').click();
  const search=page.locator('[data-step="2"] [data-column-search]');for(const name of ['country','note']){await search.fill(name);await search.press('Enter');}
  const chips=page.locator('[data-step="2"] .column-chip'),last=await chips.last().boundingBox();
  await chips.first().locator('.chip-grip').dragTo(chips.last(),{targetPosition:{x:last.width-2,y:last.height/2}});
  assert.deepEqual((await exported(page)).operations[2].columns,['note','country']);
  assert.equal(await page.locator('[data-drop],[data-column-drop],.is-dragging').count(),0);assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

for(const transitions of [false,true])test(`workspace views preserve controls and graph state (${transitions?'view transition':'fallback'})`,async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,false,true,transitions);
  const toggle=view=>page.locator(`.workspace-view-controls [data-workspace-view="${view}"]`);
  const wait=view=>page.waitForFunction(view=>document.body.dataset.workspaceView===view,view);
  await toggle('execution').click();await wait('execution');
  assert.equal(await page.locator('.execution-empty').isVisible(),true);assert.equal(await page.locator('#job-form').isVisible(),false);assert.equal(await page.locator('#output-plan').isVisible(),true);assert.equal(await page.evaluate(()=>document.activeElement.tagName),'H1');
  await page.locator('#run-direct').click();await wait('configuration');assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-input','validation reveals the editor before focusing an invalid setting');await choose(page);await page.locator('#max-rows').fill('17');
  const renderer=await build({stdin:{contents:"export {ExecutionHistory,renderExecutionHistory} from './src/browser/execution-history';",resolveDir:resolve('.')},bundle:true,write:false,format:'iife',globalName:'ViewFixture'});await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(()=>{window.viewHistory=new ViewFixture.ExecutionHistory(1,window.defaults);viewHistory.accept(1,{read:{status:'active',rows:10,seconds:1}});ViewFixture.renderExecutionHistory(viewHistory);});await wait('execution');
  assert.equal(await page.locator('.execution-empty').isVisible(),false);
  const panel=page.locator('#execution-history');await panel.getByRole('button',{name:'List view',exact:true}).click();
  for(const width of [390,1440,2560]){await page.setViewportSize({width,height:1000});const graph=await panel.boundingBox(),plan=await page.locator('#output-plan').boundingBox();if(width>=1100)assert(plan.x>=graph.x+graph.width,'plan beside graph');else assert(plan.y>=graph.y+graph.height,'plan stacks below graph');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);}
  await toggle('configuration').click();await wait('configuration');assert.equal(await page.locator('#max-rows').inputValue(),'17');assert.equal(await panel.isVisible(),false);
  await page.evaluate(()=>{viewHistory.accept(1,{read:{status:'active',rows:20,seconds:2}});ViewFixture.renderExecutionHistory(viewHistory);});assert.equal(await page.locator('body').getAttribute('data-workspace-view'),'configuration','live updates do not steal the editor back');
  await toggle('execution').click();await wait('execution');assert.equal(await panel.getByRole('button',{name:'List view',exact:true}).getAttribute('aria-pressed'),'true','same graph retains selection');
  await panel.getByRole('button',{name:'Graph view',exact:true}).click();await panel.getByRole('slider',{name:'Zoom',exact:true}).press('End');
  const manualZoom=await panel.locator('.execution-stage').evaluate(el=>el.style.getPropertyValue('--dag-zoom'));
  await toggle('configuration').click();await wait('configuration');
  await page.evaluate(()=>{viewHistory.accept(1,{read:{status:'active',rows:Number.MAX_SAFE_INTEGER,seconds:2}});ViewFixture.renderExecutionHistory(viewHistory);});
  await toggle('execution').click();await wait('execution');
  await page.waitForFunction(()=>{const stage=document.querySelector('.execution-stage'),card=document.querySelector('.execution-graph li'),zoom=Number(stage.style.getPropertyValue('--dag-zoom'));return parseFloat(card.style.getPropertyValue('--dag-card-height'))>=card.getBoundingClientRect().height/zoom-1;});
  assert.equal(await panel.locator('.execution-stage').evaluate(el=>el.style.getPropertyValue('--dag-zoom')),manualZoom,'returning remeasures cards without resetting manual zoom');
  await page.locator('#draft-source .plan-link').click();await wait('configuration');assert.equal(await page.evaluate(()=>document.activeElement.id),'browse-input');
  await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>{window.transitionCalls=0;const start=document.startViewTransition?.bind(document);if(start)document.startViewTransition=(...args)=>{window.transitionCalls++;return start(...args);};});await toggle('execution').click();await wait('execution');assert.equal(await page.evaluate(()=>window.transitionCalls),0,'reduced motion switches immediately');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('step motion follows actual attempts and pauses without touching processing',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.emulateMedia({reducedMotion:'no-preference'});
  const renderer=await build({stdin:{contents:"export {ExecutionHistory,renderExecutionHistory} from './src/browser/execution-history';",resolveDir:resolve('.')},bundle:true,write:false,format:'iife',globalName:'MotionFixture'});await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(()=>{window.motionHistory=new MotionFixture.ExecutionHistory(1,{...window.defaults,operations:[{type:'shuffle',strategy:'auto'},{type:'partition',columns:['key']}]});motionHistory.accept(1,{physical:[{id:1040,kind:'fisher_yates',operations:[1],status:'active',rows:10,seconds:1},{id:1041,kind:'resident_sort',operations:[1],status:'active',rows:10,seconds:1},{id:1042,kind:'spill',operations:[1],status:'completed',rows:10,seconds:1},{id:1043,kind:'resident_sort',operations:[2],status:'active',rows:10,seconds:1}]});MotionFixture.renderExecutionHistory(motionHistory);});
  const fisher=page.locator('.execution-list li[data-step="1040"]'),sort=page.locator('.execution-list li[data-step="1041"]'),waiting=page.locator('.execution-list li[data-step="1042"]');
  await page.waitForFunction(()=>document.querySelector('[data-step="1040"]').dataset.motionVisible==='true');
  const actor=card=>card.locator('.motion-actor').first();const style=(card,prop)=>actor(card).evaluate((el,prop)=>getComputedStyle(el)[prop],prop);
  assert.equal(await fisher.getAttribute('data-motion'),'fisher_yates');assert.equal(await sort.getAttribute('data-motion'),'uniform_sort');assert.equal(await sort.locator('.execution-node-title').textContent(),'Resident random-key sort');assert.notEqual(await style(fisher,'animationName'),await style(sort,'animationName'));assert.equal(await style(fisher,'animationPlayState'),'running');
  for(const kind of ['fisher_yates','uniform_sort','resident_sort'])assert.deepEqual(await page.locator(`li[data-motion="${kind}"] .motion-actor`).evaluateAll(nodes=>nodes.map(el=>getComputedStyle(el).animationDelay)),['0s','0s',...(kind!=='fisher_yates'?['0s']:[])],'paired actors stay synchronized');
  for(const kind of ['resident_sort','uniform_sort']){const heights=await page.locator(`li[data-motion="${kind}"] svg`).evaluate(svg=>{const bars=[...svg.querySelectorAll('.motion-actor')];for(const el of bars)for(const animation of el.getAnimations()){animation.pause();animation.currentTime=1690;}return bars.sort((a,b)=>a.getBoundingClientRect().left-b.getBoundingClientRect().left).map(el=>el.getBBox().height);});assert.deepEqual(heights,[4,8,12],'sort organizes distinct bar heights into ascending order');}

  assert.equal(await waiting.getAttribute('data-status'),'in_progress');assert.equal(await style(waiting,'animationName'),'none','a completed attempt awaiting more parents does not pretend to be working');
  const before=await page.evaluate(()=>window.calls.filter(call=>call.path!=='state').length);await page.getByRole('button',{name:'Pause motion',exact:true}).click();assert.equal(await style(fisher,'animationPlayState'),'paused');assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.path!=='state').length),before);
  await page.getByRole('button',{name:'Resume motion',exact:true}).click();assert.equal(await style(fisher,'animationPlayState'),'running');
  const retained=await actor(fisher).elementHandle();await page.evaluate(()=>{motionHistory.accept(1,{physical:[{id:1040,kind:'fisher_yates',operations:[1],status:'active',rows:20,seconds:2}]});MotionFixture.renderExecutionHistory(motionHistory);});assert.equal(await retained.evaluate(el=>el===document.querySelector('[data-step="1040"] .motion-actor')),true,'polls preserve the animated element');
  await page.locator('.workspace-view-controls [data-workspace-view=configuration]').click();await page.waitForFunction(()=>document.querySelector('[data-step="1040"]').dataset.motionVisible==='false');assert.equal(await style(fisher,'animationPlayState'),'paused');
  await page.locator('.workspace-view-controls [data-workspace-view=execution]').click();await page.waitForFunction(()=>document.querySelector('[data-step="1040"]').dataset.motionVisible==='true');
  await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});assert.equal(await style(fisher,'animationPlayState'),'paused');await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
  await page.emulateMedia({reducedMotion:'reduce'});await page.getByRole('button',{name:'Reduced motion',exact:true}).waitFor();assert.equal(await style(fisher,'animationName'),'none');await page.getByRole('slider',{name:'Zoom',exact:true}).focus();await page.keyboard.press('Tab');assert.equal(await page.locator('.execution-viewport').evaluate(el=>el===document.activeElement),true,'keyboard navigation skips disabled reduced-motion control');
  await page.evaluate(()=>{motionHistory.accept(1,{processingComplete:true,physical:motionHistory.steps.map(step=>({id:step.id,kind:step.kind,operations:step.operations,status:'completed',rows:20,seconds:2}))});MotionFixture.renderExecutionHistory(motionHistory);});assert.equal(await waiting.locator('.execution-node-status').textContent(),'Completed');
  await page.emulateMedia({reducedMotion:'no-preference'});await page.evaluate(()=>{motionHistory.interrupt('unknown');MotionFixture.renderExecutionHistory(motionHistory);});assert.equal(await style(fisher,'animationName'),'none','terminal work stops animating');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('execution graph shows finished attempts, friendly labels, pan/zoom and plan-colored timelines',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.setViewportSize({width:1440,height:1000});
  const renderer=await build({stdin:{contents:"export {ExecutionHistory,renderExecutionHistory} from './src/browser/execution-history';",resolveDir:resolve('.')},bundle:true,write:false,format:'iife',globalName:'GraphPolish'});await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(()=>{window.polishHistory=new GraphPolish.ExecutionHistory(903,{...window.defaults,operations:[{type:'partition',columns:['key']},{type:'assign_probabilistic',groups:[{name:'a',percent:'100'}]}]});polishHistory.accept(903,{physical:[{id:1040,kind:'resident_sort',operations:[1],status:'completed',rows:100,seconds:1},{id:1041,kind:'probabilistic_membership',operations:[2],status:'active',rows:50,seconds:.5}],timeline:[{step:1040,start:0,last:1,status:'completed'},{step:1041,start:1,last:2,status:'active'}],timeline_seconds:2});for(let i=2;i<10;i++)polishHistory.accept(903,{physical:[{id:1040+i,kind:'grouping',operations:[1],source:1039+i,status:'completed',rows:100,seconds:1}]});GraphPolish.renderExecutionHistory(polishHistory);});
  const panel=page.locator('#execution-history'),viewport=panel.locator('.execution-viewport');await viewport.scrollIntoViewIfNeeded();
  assert.equal(await panel.locator('[data-step="1040"] .execution-node-status').textContent(),'In Progress');assert.equal(await panel.locator('[data-step="1041"] .execution-node-status').textContent(),'In Progress');assert.match(await panel.locator('[data-step="1041"] .execution-node-context').textContent(),/Assign approximate groups/);assert.doesNotMatch(await panel.textContent(),/assign_probabilistic/);
  const card=panel.locator('[data-step="1040"] > button'),inspector=panel.locator('.execution-inspector');
  await card.click();assert.equal(await card.getAttribute('aria-pressed'),'true');
  await card.click();assert.equal(await card.getAttribute('aria-pressed'),'false');
  assert.match(await inspector.textContent(),/Select a step or configured operation/);
  await card.press('Enter');assert.equal(await card.getAttribute('aria-pressed'),'true');
  await page.setViewportSize({width:1440,height:620});
  await card.scrollIntoViewIfNeeded();
  const slider=panel.getByRole('slider',{name:'Zoom',exact:true}),before=await slider.inputValue();
  const point=await card.boundingBox(),pageTop=await page.evaluate(()=>scrollY);
  await page.mouse.move(point.x+point.width/2,point.y+point.height/2);
  await page.mouse.wheel(0,300);
  await page.waitForFunction(top=>scrollY>top,pageTop);
  assert.equal(await slider.inputValue(),before,'wheel over the graph scrolls the page at the same zoom');
  assert.equal(await viewport.evaluate(el=>el.scrollTop),0);
  assert.equal(await viewport.evaluate(el=>el.dispatchEvent(new WheelEvent('wheel',{altKey:true,deltaY:-300,bubbles:true,cancelable:true}))),true);
  assert.equal(await slider.inputValue(),before,'Alt plus wheel no longer changes zoom');
  await slider.scrollIntoViewIfNeeded();
  const track=await slider.boundingBox(),center=track.y+track.height/2;
  await page.mouse.move(track.x+track.width*.4,center);await page.mouse.down();
  await page.mouse.move(track.x+track.width-1,center,{steps:5});await page.mouse.up();
  assert.equal(await slider.inputValue(),'150','dragging the slider changes graph zoom');
  assert.equal(await slider.getAttribute('aria-valuetext'),'150%');
  await slider.press('ArrowLeft');
  assert.equal(await slider.inputValue(),'149','arrow keys adjust the slider directly');
  assert.equal(await slider.evaluate(el=>el===document.activeElement),true);
  await slider.press('End');
  assert.equal(await panel.locator('.execution-stage').evaluate(el=>el.style.getPropertyValue('--dag-zoom')),'1.5');
  assert.equal(await panel.locator('[data-auto-fit]').isChecked(),false);
  assert.equal(await viewport.evaluate(el=>el.scrollHeight<=el.clientHeight+1),true,'manual zoom keeps the full graph height in the page');
  await page.setViewportSize({width:1440,height:1000});
  await viewport.evaluate(el=>el.scrollLeft=80);const previous=await viewport.evaluate(el=>el.scrollLeft);const bounds=await viewport.boundingBox();await page.mouse.move(bounds.x+Math.min(bounds.width-20,400),bounds.y+12);await page.mouse.down();await page.mouse.move(bounds.x+Math.min(bounds.width-20,400)-60,bounds.y+12,{steps:6});await page.mouse.up();assert((await viewport.evaluate(el=>el.scrollLeft))>previous,'background dragging pans');assert.equal(await viewport.evaluate(el=>el.classList.contains('is-panning')),false);
  assert.equal(await card.getAttribute('aria-pressed'),'true','dragging preserves the selection');
  await page.mouse.click(bounds.x+Math.min(bounds.width-20,400)-60,bounds.y+12);
  assert.equal(await card.getAttribute('aria-pressed'),'false','clicking the background clears the selection');
  assert.match(await inspector.textContent(),/Select a step or configured operation/);
  const panned=await viewport.evaluate(el=>el.scrollLeft);
  await viewport.press('ArrowRight');
  await page.waitForFunction(left=>document.querySelector('.execution-viewport').scrollLeft>left,panned);
  assert.equal(await slider.inputValue(),'150','arrowing across the graph pans at the current scale');
  await panel.getByRole('checkbox',{name:'Auto-fit'}).check();await panel.getByRole('button',{name:'Timeline view',exact:true}).click();assert.equal(await panel.locator('[data-timeline-row="1040"]').getAttribute('data-plan-color'),'blue');assert.equal(await panel.locator('[data-timeline-row="1041"]').getAttribute('data-plan-color'),'purple');assert.match(await panel.locator('[data-timeline-row="1041"] .execution-timeline-group').textContent(),/Assign approximate groups/);
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('results promote processing time and separate warnings from disclosures',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.evaluate(()=>{window.fixtureState={...window.fixtureState,status:'complete',output:'destination/result',analysis:{...window.analysis,analysis_seconds:12.5,warnings:['A representative warning.'],diagnostics:{resident_sorts:1,routed_groupings:2,sort_runs:3,merge_operations:4,routing_fallbacks:0,peak_workspace_reserved_bytes:1024}}};});await tick(page);
  const result=page.locator('#analysis');assert.match(await result.locator('.stat-grid').textContent(),/12.5 sProcessing time/);assert.equal(await result.locator('.analysis-warnings').count(),1);assert.equal(await result.locator('.analysis-warnings').evaluate(el=>el.closest('details')),null);assert.match(await result.locator('.analysis-warnings h3').textContent(),/Warnings/);assert.doesNotMatch(await result.locator('.analysis-details').textContent(),/12.5 s/);
  for(const summary of ['Processing details','Execution strategies']){await result.getByText(summary,{exact:true}).click();assert.equal(await result.locator('.analysis-warnings').isVisible(),true);}
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('rail utilities stay sticky and clear the navigation and processing strip',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);const utilities=page.locator('.workspace-utilities');
  assert.equal(await page.locator('.rail .workspace-utilities').count(),1);assert.equal(await page.locator('.rail-note').count(),0);
  assert.equal(await utilities.getByRole('button',{name:/Switch to .* theme/}).count(),1);assert.equal(await page.locator('.rail .theme-control').count(),1);
  assert.equal(await utilities.getByRole('link',{name:'GitHub',exact:false}).count(),1);assert.equal(await utilities.getByRole('link',{name:'Buy me a coffee',exact:false}).count(),1);assert.equal(await utilities.locator('.footer-cleanup').count(),1);
  for(const width of [1280,390,320]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>scrollTo(0,0));const before=await utilities.boundingBox();
   await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));const after=await utilities.boundingBox();
   assert(width>640?Math.abs(after.y-before.y)<1:after.y<0,'compact viewports let the top bar scroll away');
   assert(after.x>=0&&after.x+after.width<=width,'utilities fit the viewport');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   const rail=await page.locator('.rail').boundingBox(),nav=await page.locator('.workspace-toolbar').boundingBox();
   assert(nav.y>=Math.max(0,rail.y+rail.height)-1,'sticky section navigation clears the rail');
   const help=await page.getByRole('navigation',{name:'Chopper help'}).boundingBox();
   assert(help.x>=0&&Math.abs(help.x+help.width-after.x-after.width)<1&&help.y+help.height<=rail.y+rail.height,'top-bar help is right-aligned inside the rail');
  }
  await setTheme(page,'dark');assert.equal(await page.locator('meta[name="color-scheme"]').getAttribute('content'),'dark');
  assert.equal(await utilities.locator('select').count(),0,'theme is a button rather than a dropdown');
  await utilities.locator('.footer-cleanup').evaluate(el=>{el.hidden=false;const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent='Clear temporary data';el.append(button);const status=document.createElement('small');status.setAttribute('role','status');status.textContent='1 unused workspace remains.';el.after(status);});
  for(const mode of ['light','dark'])for(const width of [320,390,1280]){
   await setTheme(page,mode);await page.setViewportSize({width,height:900});
   const box=await utilities.boundingBox();assert(box.x>=0&&box.x+box.width<=width,'cleanup and theme share a dock that fits the viewport');
   assert.equal(await utilities.getByRole('button',{name:'Clear temporary data'}).isVisible(),true);
   assert.equal(await utilities.evaluate(el=>el.scrollWidth<=el.clientWidth),true,'cleanup status wraps inside the dock');
   if(process.env.CHOPPER_UTILITY_SCREENSHOTS){const dir=process.env.CHOPPER_UTILITY_SCREENSHOTS;await mkdir(dir,{recursive:true});await page.locator('.rail').screenshot({path:`${dir}/rail-${mode}-${width}.png`});}
  }
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'running',progress:{phase:'Sorting rows',rows:10,temp_bytes:0}});await tick(page);await page.waitForFunction(()=>parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--processing-strip-height'))>0);
  const dock=await utilities.boundingBox(),strip=await page.locator('#processing-strip').boundingBox();assert(dock.y+dock.height<strip.y,'utilities clear the running status controls');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'complete',analysis:window.analysis,output:'destination/result'});await tick(page);await page.waitForFunction(()=>parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--processing-strip-height'))===document.querySelector('#run-dock').offsetHeight);assert.equal((await utilities.boundingBox()).y,dock.y,'utilities remain in the rail after processing');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('repeated comparison sorts keep their badge and pause the same animation between groups',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser);await page.emulateMedia({reducedMotion:'no-preference'});
  const renderer=await build({stdin:{contents:"export {ExecutionHistory,renderExecutionHistory} from './src/browser/execution-history';export {PhysicalHistory} from './src/browser/physical-history';",resolveDir:resolve('.')},bundle:true,write:false,format:'iife',globalName:'StableFixture'});await page.addScriptTag({content:renderer.outputFiles[0].text});
  await page.evaluate(()=>{
   window.stableHistory=new StableFixture.ExecutionHistory(904,{...window.defaults,operations:[{type:'partition',columns:['key']}]});
   const physical=new StableFixture.PhysicalHistory();
   window.feedStable=(status,attempt)=>{
    physical.accept({id:1040,kind:'resident_sort',operations:[1,0],status,attempt:attempt*100,rows:10,seconds:.2});
    stableHistory.accept(904,{physical:physical.snapshot()});StableFixture.renderExecutionHistory(stableHistory);
   };
   feedStable('active',1);
  });
  const card=page.locator('[data-step="1040"]'),actor=card.locator('.motion-actor').first(),badge=card.locator('.execution-node-status');await page.waitForFunction(()=>document.querySelector('[data-step="1040"]').dataset.motionVisible==='true');
  const stack=()=>card.evaluate(el=>getComputedStyle(el,'::after').content);
  assert.equal(await stack(),'none','a single attempt does not get a stack, regardless of its attempt ID');
  await actor.evaluate(el=>{window.retainedAnimation=el.getAnimations()[0];retainedAnimation.currentTime=900;});
  await page.evaluate(()=>feedStable('completed',1));assert.equal(await badge.textContent(),'In Progress');assert.equal(await actor.evaluate(el=>getComputedStyle(el).animationPlayState),'paused');assert.equal(await actor.evaluate(el=>el.getAnimations()[0]===window.retainedAnimation),true,'attempt completion retains the animation');assert.equal(await stack(),'none','one completed attempt is still a single card');
  const paused=await page.evaluate(()=>retainedAnimation.currentTime);await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>retainedAnimation.currentTime),paused,'no motion is invented between groups');
  await page.evaluate(()=>feedStable('active',2));assert.equal(await badge.textContent(),'In Progress');assert.equal(await actor.evaluate(el=>el.getAnimations()[0]===window.retainedAnimation),true,'next group resumes the same animation');assert.equal(await actor.evaluate(el=>getComputedStyle(el).animationPlayState),'running');assert((await page.evaluate(()=>retainedAnimation.currentTime))>=paused,'animation does not restart at zero');
  assert.equal(await stack(),'""','the stack appears as soon as the second attempt starts');
  assert.match(await card.locator('button').getAttribute('aria-label'),/Repeated work/);
  await page.evaluate(()=>{feedStable('completed',2);stableHistory.accept(904,{processingComplete:true});StableFixture.renderExecutionHistory(stableHistory);});assert.equal(await badge.textContent(),'Completed');assert.equal(await actor.evaluate(el=>getComputedStyle(el).animationName),'none');
  assert.equal(await stack(),'""','a completed repeat retains its stack');
  await page.getByRole('button',{name:'List view',exact:true}).click();
  assert.equal(await card.evaluate(el=>getComputedStyle(el,'::after').pointerEvents),'auto','list rows keep their own styling');
  assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('late state responses cannot overwrite newer state or cross a Run acknowledgement',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  await page.evaluate(()=>{window.fixtureState={...window.fixtureState,status:'failed',error:'stale response'};window.deferNextState=true;});
  await page.clock.runFor(1000);assert.equal(await page.evaluate(()=>typeof window.releaseState),'function');
  await page.evaluate(()=>window.fixtureState={...window.fixtureState,status:'idle',error:null});await page.clock.runFor(1000);assert.equal(await page.locator('#status').textContent(),'IDLE');
  await page.evaluate(()=>window.releaseState());await page.clock.runFor(20);assert.equal(await page.locator('#status').textContent(),'IDLE');assert.equal(await page.locator('#error').isHidden(),true);
  await page.evaluate(()=>{window.fixtureState={...window.fixtureState,status:'failed',error:'before Run'};window.deferNextState=true;});await page.clock.runFor(1000);
  await page.locator('#run-direct').click();assert.equal(await page.locator('#status').textContent(),'RUNNING');await page.evaluate(()=>window.releaseState());await page.clock.runFor(20);
  assert.equal(await page.locator('#status').textContent(),'RUNNING');assert.equal(await page.locator('#error').isHidden(),true);assert.deepEqual(errors,[]);await page.close();
 }finally{await browser.close();}
});

test('pending commands suppress state polls until their acknowledgement settles',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const {page,errors}=await harness(browser,true,true);await choose(page);
  await page.locator('#max-rows').fill('2');
  await page.evaluate(()=>window.deferAnalysisAck=true);
  await page.locator('#profile').click();await page.waitForFunction(()=>window.releaseAnalysisAck);
  const before=await page.evaluate(()=>window.calls.filter(call=>call.path==='state').length);
  await page.clock.runFor(3000);
  assert.equal(await page.evaluate(()=>window.calls.filter(call=>call.path==='state').length),before);
  await page.evaluate(()=>{window.deferAnalysisAck=false;window.releaseAnalysisAck();});
  await page.waitForFunction(()=>document.getElementById('status').textContent==='PROFILED');
  assert.equal(await page.locator('#run-direct').textContent(),'Run →');assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
