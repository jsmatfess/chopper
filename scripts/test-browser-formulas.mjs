import assert from 'node:assert/strict';
import {withHostedBrowser, revealFormControl} from './browser-acceptance.mjs';

await withHostedBrowser({port:8427}, async ({context,url}) => {
  const page=await context.newPage();
  await page.addInitScript(()=>{
    window.formulaSource='id,Sales Region,amount\n1, north ,120\n2,south,unknown\n';
    window.formulaOutput='formulas-'+crypto.randomUUID();
    window.showOpenFilePicker=async()=>[{getFile:async()=>new File([window.formulaSource],'formula-fixture.csv')}];
    window.showDirectoryPicker=async()=> (await navigator.storage.getDirectory()).getDirectoryHandle(window.formulaOutput,{create:true});
  });
  await page.goto(url+'/');
  await page.waitForFunction(()=>document.getElementById('status')?.textContent==='IDLE');
  await revealFormControl(page,'#browse-input');
  await page.locator('#browse-input').click();
  await page.locator('#browse-output').click();
  await revealFormControl(page,'#new-operation');
  await page.locator('#new-operation').selectOption('calculate');
  await page.locator('#add-operation').click();
  const first=page.locator('[data-step="0"]');
  const formula=first.getByRole('combobox',{name:'Formula'});
  await first.getByLabel('Column name').fill('normalized');
  await formula.fill('UPP');
  await first.getByText(/missing or ambiguous/).waitFor();
  await formula.press('Control+Space');
  await first.getByRole('option',{name:/UPPER/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER()');
  assert.equal(await formula.evaluate(el=>el.selectionStart),6);
  await formula.fill('UPPER(TRIM([Sales');
  await first.getByRole('option',{name:/Sales Region/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER(TRIM([Sales Region]');
  await formula.fill('UPPER(TRIM([Sales Region]))');
  await first.getByText('NORTH',{exact:true}).waitFor();
  await formula.press('Escape');
  await formula.press('Tab');
  assert.notEqual(await formula.evaluate(el=>document.activeElement===el),true);

  await page.locator('#add-operation').click();
  const second=page.locator('[data-step="1"]');
  await second.getByLabel('Column name').fill('total');
  const secondFormula=second.getByRole('combobox',{name:'Formula'});
  await secondFormula.fill('norm');
  await second.getByRole('option',{name:/normalized/}).waitFor();
  await secondFormula.press('Tab');
  assert.equal(await secondFormula.inputValue(),'normalized');
  await second.getByText('NORTH',{exact:true}).waitFor();
  await second.getByRole('button',{name:'Move step 2 up'}).click();
  await first.getByText(/missing or ambiguous/).waitFor();
  await first.getByRole('button',{name:'Move step 1 down'}).click();
  await secondFormula.fill('NUMBER(amount)');
  await second.getByText('invalid number',{exact:true}).waitFor();
  await secondFormula.fill('SAFE.NUMBER(amount)');
  await second.getByText('NULL',{exact:true}).waitFor();
  const original=await page.evaluate(()=>window.formulaSource);
  await page.evaluate(()=>{window.formulaSource=window.formulaSource.replace('Sales Region','Market');});
  await page.locator('#browse-input').click();
  await first.getByText(/missing or ambiguous/).waitFor();
  await second.getByText('NULL',{exact:true}).waitFor();
  await formula.fill('UPPER(TRIM($1');
  await first.getByRole('option',{name:/Market/}).waitFor();
  await formula.press('Tab');
  assert.equal(await formula.inputValue(),'UPPER(TRIM($1');
  await page.evaluate(source=>{window.formulaSource=source;},original);
  await page.locator('#browse-input').click();
  await formula.fill('UPPER(TRIM([Sales Region]))');
  await first.getByText('NORTH',{exact:true}).waitFor();

  await revealFormControl(page,'#run-direct');
  await page.locator('#run-direct').click();
  await page.waitForFunction(()=>['COMPLETE','FAILED'].includes(document.getElementById('status').textContent));
  assert.equal(await page.locator('#status').textContent(),'COMPLETE',await page.locator('#error').textContent());
  const csv=await page.evaluate(async()=>{
    const root=await (await navigator.storage.getDirectory()).getDirectoryHandle(window.formulaOutput);
    for await(const entry of root.values()){
      if(entry.kind!=='directory')continue;
      const directory=await root.getDirectoryHandle(entry.name);
      for await(const file of directory.values())if(file.kind==='file'&&file.name.endsWith('.csv'))return (await file.getFile()).text();
    }
    throw new Error('No formula output CSV found');
  });
  assert.match(csv,/id,Sales Region,amount,normalized,total\n1, north ,120,NORTH,120\n2,south,unknown,SOUTH,""\n/);
});
