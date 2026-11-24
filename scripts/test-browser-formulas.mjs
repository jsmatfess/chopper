import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {readFile} from 'node:fs/promises';
import {withHostedBrowser, revealFormControl} from './browser-acceptance.mjs';

const adversarial = JSON.parse(await readFile(
  new URL('../crates/chopper-core/tests/fixtures/formula-adversarial.json', import.meta.url), 'utf8'
));
const cases = Object.entries(adversarial).flatMap(([name, trials]) =>
  trials.map(([args, kind, expected]) => ({expression:`${name}(${args})`, kind, expected})));
const formulaReference=await readFile(new URL('../docs/formula-functions.md',import.meta.url),'utf8');
const reference=new Map(
  [...formulaReference.matchAll(/^\| `([A-Z_][A-Z_0-9]*)\([^`]*\)` \| (.*?) \| (.*?) \|$/gm)]
    .map(([,name,behavior,cell])=>[name,{
      behavior:behavior.replaceAll('`',''),
      examples:[...cell.matchAll(/`([^`]+)` → `([^`]+)`/g)].map(([,expression,result])=>`${expression} → ${result}`),
    }])
);

const helpCases = [
  ['SUBSTRING("x, ""y""", ▮','SUBSTRING','start'],
  ['SUBSTRING([name]]),(with,comma], ▮','SUBSTRING','start'],
  ['SUBSTRING("fake REGEX_MATCH(, ▮','SUBSTRING','text'],
  ['SUBSTRING([fake REGEX_MATCH(, ▮','SUBSTRING','text'],
  ['SUBSTRING(TRIM("α, ▮🙂"), 1, 2)','TRIM','text'],
  ['SUBSTRING(TRIM("α, 🙂"), ▮1, 2)','SUBSTRING','start'],
  ['SUBSTRING(TRIM("α, 🙂"), 1, ▮2)','SUBSTRING','length?'],
  ['SUBSTRING(TRIM("α, 🙂"), 1, 2)▮','',null],
  ['SUBSTRING("α", ▮1) & RIGHT("x", 1)','SUBSTRING','start'],
  ['SUBSTRING("α", 1) & RIGHT("x", ▮1)','RIGHT','count'],
  ['"TRIM(, ▮)"','',null],
  ['[TRIM(, ▮)]','',null],
  ['SAFE .number(▮','SAFE.NUMBER','text'],
  ['SAFE(SAFE.NUMBER(▮"42"))','SAFE.NUMBER','text'],
  ['SAFE(SAFE.NUMBER("42")▮)','SAFE','expression'],
  ['IF((1 + 2) IN (3, ▮4), "yes", "no")','IF','condition'],
  ['IF((1 + 2) IN (3, 4), ▮','IF','when_true'],
  ['IF((1 + 2) IN (3, 4), "yes", ▮','IF','when_false'],
  ['(SUBSTRING("x", ▮','SUBSTRING','start'],
  ['IF(UNKNOWN("x", ▮','IF','condition'],
  ['UNKNOWN("x", ▮','',null],
  ['▮ SUBSTRING("x", 1)','',null],
  ['SUBSTRING▮("x", 1)','',null],
  [`${'('.repeat(40)}TRIM(▮"x")${')'.repeat(40)}`,'TRIM','text'],
  ['REGEX_EXTRACT("<img src=x>", ".*", ▮0)','REGEX_EXTRACT','group?'],
  ['SUBSTRING("é", 1, 1, ▮','SUBSTRING',null],
  ['SUBSTRING( \u2003 "é", ▮','SUBSTRING','start'],
  ['IFS(TRUE,1,▮0)','IFS','fallback'],
  ['IFS(FALSE,1,▮TRUE,2,0)','IFS','condition'],
  ['IFS(FALSE,1,TRUE,▮2,0)','IFS','value'],
  ['IFS(FALSE,1,TRUE,2,▮0)','IFS','fallback'],
  ['IFS(TRUE,1, ▮','IFS','...'],
  ['CONCAT_WS("|","a","b",▮TRUE,FALSE)','CONCAT_WS','ignore_null?'],
  ['CONCAT_WS("|","a","b",TRUE,▮FALSE)','CONCAT_WS','ignore_empty?'],
  ['CONCAT_WS("|","a",▮FALSE)','CONCAT_WS','ignore_null?'],
  ['CONCAT_WS("|","a",FALSE,▮','CONCAT_WS','ignore_empty?'],
  ['CONCAT_WS("|","a",▮"TRUE")','CONCAT_WS','...'],
  ['CONCAT_WS("|","a",▮(FALSE),TRUE)','CONCAT_WS','ignore_null?'],
  ['CONCAT_WS("|","a",REGEX_EXTRACT("x","(.+)",1),▮FALSE, TRUE)','CONCAT_WS','ignore_null?'],
  ['CONCAT_WS("|","a",▮TRUE,FALSE, "b")','CONCAT_WS','...'],
  ['CONCAT_WS("|","a",FALSE,▮FA','CONCAT_WS','ignore_empty?'],
  ['CONCAT_WS("|","a",TRUE,▮TEXT(FALSE))','CONCAT_WS','...'],
];


await withHostedBrowser({port:8427}, async ({context,url}) => {
  const page=await context.newPage();
  page.setDefaultTimeout(15_000);
  await page.addInitScript(()=>{
    const BrowserWorker=window.Worker;
    window.Worker=class extends BrowserWorker{
      postMessage(message, ...options){
        if(message.type==='init'&&message.port&&message.available)window.formulaEngine=this;
        if(message.type==='formula-scan'&&window.holdScan){
          window.resumeScan=()=>super.postMessage(message,...options);
          return;
        }
        if(message.type==='formula-preview'&&window.holdFormulaRequests){
          window.heldFormulaRequests.push(message);
          return;
        }
        return super.postMessage(message,...options);
      }
    };
    window.heldFormulaRequests=[];
    window.formulaSource='id,Sales Region,amount\n1, north ,120\n2,south,unknown\n';
    window.formulaOutput='formulas-'+crypto.randomUUID();
    window.showOpenFilePicker=async()=>[{getFile:async()=>window.compressedFormulaSource
      ?new File([new Uint8Array(window.compressedFormulaSource)],'formula-fixture.csv.gz')
      :new File([window.formulaSource],'formula-fixture.csv')}];
    window.showDirectoryPicker=async()=> (await navigator.storage.getDirectory()).getDirectoryHandle(window.formulaOutput,{create:true});
  });
  await page.goto(url+'/');
  await page.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
  let catalog;
  for(let offset=0;offset<cases.length;offset+=48){
    const batch=cases.slice(offset,offset+48);
    const preview=await page.evaluate(({offset, expressions})=>new Promise((resolve,reject)=>{
      const worker=window.formulaEngine;
      const id=`formula-cases-${offset}`;
      const timeout=setTimeout(()=>{
        worker.removeEventListener('message',receive);
        reject(new Error(`Formula preview batch timed out at ${offset}`));
      },10_000);
      function receive({data}){
        if(data.id!==id)return;
        clearTimeout(timeout);
        worker.removeEventListener('message',receive);
        if(data.error)reject(new Error(data.error));
        else resolve(data.result);
      }
      worker.addEventListener('message',receive);
      worker.postMessage({id,type:'formula-preview',preview:{
        header:null,columns:0,rows:[[]],
        calculations:expressions.map((expression,operation)=>({operation,name:`case_${operation}`,expression})),
      }});
    }),{offset,expressions:batch.map(({expression})=>expression)});
    catalog=preview.functions;
    assert.deepEqual(preview.functions.map(([name])=>name).sort(),Object.keys(adversarial).sort());
    assert.equal(preview.steps.length,batch.length);
    for(const {operation,error,rows} of preview.steps){
      const {expression,kind,expected}=batch[operation];
      if(kind==='parse'){
        assert.ok(error?.includes(expected),`${expression} returned ${error}`);
        continue;
      }
      assert.equal(error,null,expression);
      assert.equal(rows.length,1,expression);
      const [row]=rows;
      if(kind==='row'){
        assert.ok(row.error?.includes(expected),`${expression} returned ${row.error}`);
      }else{
        assert.deepEqual(row,{value:expected,error:null,is_null:kind==='n'},expression);
      }
    }
  }

  const wideHeader=Array.from({length:80},(_,index)=>'source_'+index);
  const wideValues=wideHeader.map((_,index)=>'value_'+index).join(',');
  const formulaFixture=await page.evaluate(input=>{
    const previous=window.formulaSource;
    window.formulaSource=input;
    return previous;
  },wideHeader.join(',')+'\n'+wideValues+'\n'+wideValues+'\n');
  await revealFormControl(page,'#browse-input');
  await page.locator('#browse-input').click();
  await page.locator('#profile').click();
  const lastSourceColumn=page.locator('#input-values [data-column="79"]');
  await lastSourceColumn.getByText('source_79',{exact:true}).waitFor();
  await lastSourceColumn.locator('summary').click();
  await lastSourceColumn.getByText('value_79',{exact:true}).waitFor();
  await lastSourceColumn.getByText('100%',{exact:true}).waitFor();
  assert.equal(await page.locator('#input-values .column-values-row').count(),80);
  await page.evaluate(input=>{window.formulaSource=input;},formulaFixture);

  await revealFormControl(page,'#browse-input');
  await page.locator('#browse-input').click();
  await page.locator('#browse-output').click();
  await revealFormControl(page,'#add-calculated-column');
  await page.evaluate(()=>{window.holdFormulaRequests=true;});
  await page.locator('#add-calculated-column').click();
  const first=page.locator('[data-calculation="0"]');
  assert.equal(await page.locator('#operations [data-step]').count(),0);
  const formula=first.getByRole('combobox',{name:'Formula'});
  await first.getByLabel('Column name').fill('normalized');
  const help=first.locator('[data-formula-help]');
  const oldDraft='RIGHT("old", ';
  const currentDraft='SUBSTRING("é,)", ';
  await formula.fill(oldDraft);
  await page.waitForFunction(expression=>window.heldFormulaRequests.some(request=>
    request.preview.calculations[0].expression===expression),oldDraft);
  await formula.fill(currentDraft);
  await page.waitForFunction(expression=>window.heldFormulaRequests.some(request=>
    request.preview.calculations[0].expression===expression),currentDraft);
  assert.equal(await help.isHidden(),true);
  await page.evaluate(async()=>{
    window.holdFormulaRequests=false;
    const worker=window.formulaEngine;
    const held=window.heldFormulaRequests.splice(0).reverse();
    const pending=new Set(held.map(({id})=>id));
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{
        worker.removeEventListener('message',receive);
        reject(new Error('Delayed preview responses did not arrive'));
      },10_000);
      function receive({data}){
        if(!pending.delete(data.id)||pending.size)return;
        clearTimeout(timeout);
        worker.removeEventListener('message',receive);
        resolve();
      }
      worker.addEventListener('message',receive);
      for(const message of held)worker.postMessage(message);
    });
  });
  await help.locator('code').getByText('SUBSTRING(text, start, length?)',{exact:true}).waitFor();
  await help.locator('strong').getByText('start',{exact:true}).waitFor();

  const uniformCases = catalog.flatMap(([name, signature]) =>
    signature.slice(name.length+1,-1).split(', ').flatMap((arg,index)=>{
      if(arg==='...'||arg==='fallback'||arg==='ignore_null?'||arg==='ignore_empty?')return [];
      return ['', 'SAFE.'].map(prefix=>[
        `${prefix}${name}(${'"bad, ( )", '.repeat(index)}▮`,prefix+name,arg,
      ]);
    }));
  assert.deepEqual([...reference.keys()].sort(),catalog.map(([name])=>name).sort());
  const signatures=new Map(catalog);
  const trials=[...uniformCases,...helpCases].map(([marked,name,argument])=>{
    const base=name.replace(/^SAFE\./,'');
    const signature=name?(name.startsWith('SAFE.')?'SAFE.':'')+signatures.get(base):'';
    return {marked,signature,argument,description:reference.get(base)?.behavior??'',examples:reference.get(base)?.examples??[]};
  });
  const failures = await formula.evaluate((field, trials)=>{
    const help=field.closest('.column-typeahead').querySelector('[data-formula-help]');
    const issues=[];
    for(const {marked,signature,argument,description,examples} of trials){
      const caret=marked.indexOf('▮');
      field.value=marked.replace('▮','');
      field.setSelectionRange(caret,caret);
      field.dispatchEvent(new Event('input',{bubbles:true}));
      const actual=help.querySelector('code').textContent;
      const usage=help.querySelector('small').textContent;
      const selected=help.querySelector('strong')?.textContent??null;
      const exampleList=help.querySelector('[data-formula-examples]');
      const actualExamples=[...exampleList.children].map(entry=>entry.textContent);
      if(exampleList.hidden!==!examples.length||actualExamples.join('\n')!==examples.join('\n')||help.hidden!==!signature||actual!==signature||selected!==argument||usage!==description||
        !field.getAttribute('aria-describedby').split(/\s+/).includes(help.id)){
        issues.push({marked,signature,actual,argument,selected,description,usage,examples,actualExamples,hidden:help.hidden});
      }
    }
    return issues;
  },trials);
  assert.deepEqual(failures,[],'Function help for catalog arguments and difficult caret positions');
  console.log(`Verified ${trials.length} function-help caret cases in Chromium.`);

  await formula.fill('UPP');
  await first.getByText(/missing or ambiguous/).waitFor();
  await formula.press('Control+Space');
  await first.getByRole('option',{name:/UPPER/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER()');
  assert.equal(await formula.evaluate(el=>el.selectionStart),6);
  await formula.fill('TEXT');
  assert.deepEqual(await first.getByRole('option').evaluateAll(options=>options.slice(0,3).map(option=>option.firstElementChild.textContent)),[
    'TEXT','TEXT_AFTER','TEXT_BEFORE',
  ]);
  await formula.fill('UPPER(TRIM([les R');
  await first.getByRole('option',{name:/Sales Region/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER(TRIM([Sales Region]');
  await formula.fill('UPPER(TRIM([Sales Region]))');
  await first.getByText('NORTH',{exact:true}).waitFor();
  await formula.press('Escape');
  await formula.press('Tab');
  assert.notEqual(await formula.evaluate(el=>document.activeElement===el),true);

  await page.locator('#add-calculated-column').click();
  const second=page.locator('[data-calculation="1"]');
  await second.getByLabel('Column name').fill('total');
  const secondFormula=second.getByRole('combobox',{name:'Formula'});
  await secondFormula.fill('norm');
  await second.getByRole('option',{name:/normalized/}).waitFor();
  await secondFormula.press('Tab');
  assert.equal(await secondFormula.inputValue(),'normalized');
  await second.getByText('NORTH',{exact:true}).waitFor();
  await formula.fill('tot');
  await first.getByRole('option',{name:/total/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'total');
  await first.getByText(/cyclic calculated column dependency/i).waitFor();
  await second.getByText(/cyclic calculated column dependency/i).waitFor();
  await formula.fill('UPPER(TRIM([Sales Region]))');
  await first.getByText('NORTH',{exact:true}).waitFor();
  await secondFormula.fill('NUMBER(amount)');
  await second.getByText('120',{exact:true}).waitFor();
  await second.getByRole('button',{name:'Next distinct row'}).click();
  await second.getByText(/invalid number.*Use TRIM/).waitFor();
  await secondFormula.fill('IS_ERR');
  await second.getByRole('option', {name:/IS_ERROR/}).waitFor();
  await secondFormula.press('Tab');
  assert.equal(await secondFormula.inputValue(), 'IS_ERROR()');
  await secondFormula.fill('IS_ERROR(NUMBER(amount))');
  await second.getByText('true', {exact:true}).waitFor();
  await secondFormula.fill('SAFE.NUMBER(amount)');
  await second.getByText('NULL',{exact:true}).waitFor();
  const original=await page.evaluate(()=>window.formulaSource);
  await page.evaluate(()=>{window.formulaSource=window.formulaSource.replace('Sales Region','Market');});
  await page.locator('#browse-input').click();
  await first.getByText(/missing or ambiguous/).waitFor();
  await second.getByText('120',{exact:true}).waitFor();
  await formula.fill('UPPER(TRIM($1');
  await first.getByRole('option',{name:/Market/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER(TRIM($1');
  await page.evaluate(source=>{window.formulaSource=source;},original);
  await page.locator('#browse-input').click();
  await formula.fill('UPPER(TRIM([Sales Region]))');
  await first.getByText('NORTH',{exact:true}).waitFor();

  await formula.fill('SUBSTRING("x", 1, 2)');
  await help.waitFor({state:'hidden'});
  await formula.press('ArrowLeft');
  await help.locator('strong').getByText('length?',{exact:true}).waitFor();
  await formula.press('Home');
  await help.waitFor({state:'hidden'});
  await formula.press('End');
  await formula.press('ArrowLeft');
  await help.locator('strong').getByText('length?',{exact:true}).waitFor();
  await secondFormula.fill('POWER(2, ');
  const otherHelp=second.locator('[data-formula-help]');
  await help.waitFor({state:'hidden'});
  await otherHelp.locator('strong').getByText('exponent',{exact:true}).waitFor();
  await formula.focus();
  await otherHelp.waitFor({state:'hidden'});
  await help.locator('strong').getByText('length?',{exact:true}).waitFor();

  const originalViewport=page.viewportSize();
  for(const width of [320,390,1280]){
    await page.setViewportSize({width,height:900});
    await formula.fill('SUBSTRING(TRI');
    await first.getByRole('option',{name:/TRIM/}).first().waitFor();
    const [inputBox,helpBox,popupBox]=await Promise.all([
      formula.boundingBox(),help.boundingBox(),first.locator('[data-formula-suggestions]').boundingBox(),
    ]);
    assert.ok(inputBox&&helpBox&&popupBox,`Formula assistance should be visible at ${width}px`);
    assert.ok(inputBox.y+inputBox.height<=helpBox.y,`Help appears below the input at ${width}px`);
    assert.ok(helpBox.y+helpBox.height<=popupBox.y,`Suggestions leave help visible at ${width}px`);
    assert.ok(helpBox.x>=0&&helpBox.x+helpBox.width<=width,`Help fits at ${width}px`);
  }
  await page.setViewportSize(originalViewport);

  const nested='SUBSTRING(TRIM("x, ""y"""), ';
  await formula.fill(nested);
  await help.locator('strong').getByText('start',{exact:true}).waitFor();
  await help.getByText('Take text at a zero-based position start in text.',{exact:false}).waitFor();
  assert.equal(await formula.getAttribute('aria-describedby'),await help.getAttribute('id'));
  await formula.evaluate((input,caret)=>input.setSelectionRange(caret,caret),nested.indexOf('x,')+2);
  await help.locator('code').getByText('TRIM(text)',{exact:true}).waitFor();
  await formula.press('End');
  await help.locator('strong').getByText('start',{exact:true}).waitFor();
  await formula.fill('SUBSTRING([a,b], ');
  await help.locator('strong').getByText('start',{exact:true}).waitFor();
  await formula.fill('SUBSTRING([a,b], 1)');
  await help.waitFor({state:'hidden'});

  await formula.fill('RGEEX_EXT');
  assert.equal(await first.locator('[data-formula-suggestions]').isHidden(),true);
  await formula.fill('Ex_Ex');
  await first.getByRole('option',{name:/REGEX_EXTRACT/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'REGEX_EXTRACT()');
  await formula.fill('CONCAT_W');
  await first.getByRole('option',{name:/CONCAT_WS.*ignore_null.*ignore_empty/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'CONCAT_WS()');
  await formula.fill('CONCAT_WS("-", "", REGEX_EXTRACT(UPPER([Sales Region]), "([A-Z]+)", 1), TRUE, TRUE) & "!"');
  await first.getByText('NORTH!',{exact:true}).waitFor();
  await secondFormula.fill('IF(normalized IN ("NORTH!", "WEST!"), BUCKET(SAFE.NUMBER(amount), 10), NULL)');
  await second.getByText('120',{exact:true}).waitFor();
  await second.getByRole('button',{name:'Next distinct row'}).click();
  await second.getByText('NULL',{exact:true}).waitFor();

  await page.locator('#add-calculated-column').click();
  const third=page.locator('[data-calculation="2"]');
  await third.getByLabel('Column name').fill('leap_day');
  await third.getByRole('combobox',{name:'Formula'}).fill('IF(IS_NULL(total) OR total >= 100, DATE_ADD_DAYS(DATE_FROM_PARTS(2024, 2, 28), POWER(1, 2)), NULL)');
  await third.getByText('2024-02-29',{exact:true}).first().waitFor();

  const previewInput=first.getByRole('textbox',{name:'Sales Region',exact:true});
  await previewInput.fill(' custom ');
  await first.getByText('CUSTOM!',{exact:true}).waitFor();
  await first.getByRole('button',{name:'Next distinct row'}).click();
  await first.getByText('Source row 2',{exact:true}).waitFor();
  await first.getByText('SOUTH!',{exact:true}).waitFor();
  assert.equal(await previewInput.inputValue(),'south');
  await previewInput.fill(' another ');
  await first.getByText('ANOTHER!',{exact:true}).waitFor();

  await page.locator('#new-operation').selectOption('partition');
  await page.locator('#add-operation').click();
  const partition=page.locator('#operations [data-step="0"]');
  await partition.locator('[data-column-search]').fill('normalized');
  await partition.getByRole('option',{name:/normalized/}).click();

  await revealFormControl(page,'#run-direct');
  await page.locator('#run-direct').click();
  await page.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status').textContent));
  assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());
  const csv=await page.evaluate(async()=>{
    const root=await (await navigator.storage.getDirectory()).getDirectoryHandle(window.formulaOutput);
    const results=[];
    for await(const entry of root.values()){
      if(entry.kind!=='directory')continue;
      const directory=await root.getDirectoryHandle(entry.name);
      for await(const file of directory.values())if(file.kind==='file'&&file.name.endsWith('.csv'))results.push(await (await file.getFile()).text());
    }
    return results.sort();
  });
  assert.deepEqual(csv,[
    'id,Sales Region,amount,normalized,total,leap_day\n1, north ,120,NORTH!,120,2024-02-29\n',
    'id,Sales Region,amount,normalized,total,leap_day\n2,south,unknown,SOUTH!,"",2024-02-29\n',
  ]);

  const sparseCsv='id,Sales Region,amount\n'+
    Array.from({length:512},(_,index)=>`${index+1}, north ,120\n`).join('')+
    '513, north ,235\n514, west ,120\n515, north ,42\n516, south ,120\n';
  await page.evaluate(bytes=>{
    window.holdScan=true;
    window.resumeScan=null;
    window.compressedFormulaSource=bytes;
  },[...gzipSync(sparseCsv)]);
  await revealFormControl(page,'#browse-input');
  await page.locator('#browse-input').click();
  await page.waitForFunction(()=>typeof window.resumeScan==='function');
  await revealFormControl(page,'#add-calculated-column');
  await first.getByText('NORTH!',{exact:true}).waitFor();
  assert.equal(await first.getByRole('textbox',{name:'id',exact:true}).count(),0);
  assert.equal(await first.getByRole('textbox',{name:'amount',exact:true}).count(),0);
  await previewInput.fill(' online ');
  await first.getByText('ONLINE!',{exact:true}).waitFor();
  assert.equal(await previewInput.evaluate(input=>document.activeElement===input),true);
  await formula.fill('TRIM([Sales Region])');
  await first.getByText('online',{exact:true}).waitFor();
  await page.evaluate(()=>{window.holdScan=false;window.resumeScan();});
  const scanMore=first.getByRole('button',{name:'Scan more rows'});
  await scanMore.waitFor();
  await scanMore.click();
  const nextDistinct=first.getByRole('button',{name:'Next distinct row'});
  await nextDistinct.click();
  await first.getByText('Source row 514',{exact:true}).waitFor();
  await first.getByText('west',{exact:true}).waitFor();
  await nextDistinct.click();
  await first.getByText('Source row 516',{exact:true}).waitFor();
  await first.getByText('south',{exact:true}).waitFor();
  assert.equal(await nextDistinct.isEnabled(),false);
  assert.equal(await scanMore.isHidden(),true);

  // The second formula exposes both source inputs, including the one used by normalized.
  const secondInputs=second.locator('[data-formula-preview]');
  const region=secondInputs.getByRole('textbox',{name:'Sales Region',exact:true});
  const amount=secondInputs.getByRole('textbox',{name:'amount',exact:true});
  await secondFormula.fill('IF(normalized = "north", NUMBER(amount), 0)');
  await second.getByText('120',{exact:true}).waitFor();
  await amount.fill('225');
  await second.getByText('225',{exact:true}).waitFor();
  await region.fill(' east ');
  await second.getByText('0',{exact:true}).waitFor();
  await first.getByText('south',{exact:true}).waitFor();

  await page.setViewportSize({width:1680,height:900});
  await page.evaluate(()=>{
    window.compressedFormulaSource=null;
    window.formulaSource='id,Sales Region],duplicate,duplicate,TRUE,trimZ,trimA,atrim,ztrim\n1,"a""b",100,200,yes,x,x,x,x\n2,"line\nnext",300,400,no,y,y,y,y\n';
  });
  await revealFormControl(page,'#browse-input');
  await page.locator('#browse-input').click();
  const explorer=page.locator('.workspace-sidebar > #input-values');
  const sidebarRegion=explorer.locator('[data-column="1"]');
  const sidebarDuplicate=explorer.locator('[data-column="3"]');
  await sidebarRegion.getByText('Sales Region]',{exact:true}).waitFor();
  await revealFormControl(page,'#add-calculated-column');
  await formula.fill('TRIM(x)');
  await formula.evaluate(field=>field.setSelectionRange(5,6));
  await sidebarRegion.getByText('Sales Region]',{exact:true}).click();
  assert.equal(await formula.inputValue(),'TRIM([Sales Region]]])');
  assert.equal(await formula.evaluate(field=>field===document.activeElement),true);
  await formula.fill('');
  await sidebarDuplicate.getByText('duplicate',{exact:true}).click();
  assert.equal(await formula.inputValue(),'$3','a duplicate name inserts its unambiguous index');
  await formula.fill('');
  await sidebarRegion.getByText('$1',{exact:true}).click();
  assert.equal(await formula.inputValue(),'','the displayed index is not an insertion target');
  await formula.fill('$1');
  await secondFormula.fill('1');
  await explorer.getByRole('button',{name:'Analyze input'}).click();
  await sidebarRegion.locator('summary').waitFor();

  await formula.fill('LENGTH()');
  await formula.evaluate(field=>field.setSelectionRange(7,7));
  await sidebarRegion.locator('.column-disclosure').click();
  assert.equal(await formula.evaluate(field=>field===document.activeElement),true,'expanding a column keeps the formula focused');
  await sidebarRegion.locator('.value-metrics').first().click();
  assert.equal(await formula.inputValue(),'LENGTH()','counts and percentages are not insertion targets');
  await formula.focus();
  await formula.evaluate(field=>field.setSelectionRange(7,7));
  await sidebarRegion.getByText('a"b',{exact:true}).click();
  assert.equal(await formula.inputValue(),'LENGTH("a""b")');
  await first.getByText('3',{exact:true}).waitFor();
  await formula.fill('LENGTH()');
  await formula.evaluate(field=>field.setSelectionRange(7,7));
  await sidebarRegion.locator('[data-insert-value]').filter({hasText:'line'}).click();
  assert.equal(await formula.inputValue(),'LENGTH("line\nnext")');
  await first.getByText('9',{exact:true}).waitFor();
  await formula.fill('TRIM');
  const suggestionChips=first.locator('[data-formula-suggestions] .formula-chip');
  assert.deepEqual(await suggestionChips.allTextContents(),['TRIM','trimA','trimZ','atrim','LTRIM','RTRIM','ztrim']);
  const colors=await suggestionChips.evaluateAll(chips=>chips.slice(0,2).map(chip=>getComputedStyle(chip).backgroundColor));
  assert.notEqual(colors[0],colors[1],'functions and columns have different chips in suggestions');

  await formula.fill('IF($0 = "TRIM duplicate", SAFE.NUMBER([Sales Region]]]), trimA)');
  const fieldChips=first.locator('.formula-token-layer .formula-chip');
  assert.deepEqual(await fieldChips.evaluateAll(chips=>chips.map(chip=>[chip.textContent,chip.dataset.formulaKind])),[
    ['IF','function'],['$0','column'],['SAFE.NUMBER','function'],['[Sales Region]]]','column'],['trimA','column'],
  ]);
  assert.deepEqual(await fieldChips.evaluateAll(chips=>chips.slice(0,2).map(chip=>getComputedStyle(chip).backgroundColor)),colors);
  await first.getByText('Preview result',{exact:true}).waitFor();
  const nav=first.locator('.formula-example-head');
  assert.equal(await nav.locator('[data-example-row] + [data-example-next].secondary').count(),1);
  assert.equal(await first.locator('button.secondary[data-remove-calculation]').count(),1);
  await formula.fill('id < 1000000');
  await first.getByText(/Cannot compare text with a number.*Use NUMBER/).waitFor();
  await formula.fill('NUMBER(id) < 1000000');
  await first.locator('[data-formula-preview] output').filter({hasText:/^true$/}).waitFor();
  console.log('Verified text-only sidebar insertion, alphabetical suggestions, formula chips, and labeled preview controls.');

});
console.log(`Verified ${cases.length} adversarial cases across ${Object.keys(adversarial).length} formulas in WASI.`);
