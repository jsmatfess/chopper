import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['src/memory.ts'],bundle:true,write:false,format:'esm',platform:'node',outdir:'unused'});
const modules=await Promise.all(bundle.outputFiles.map(file=>import(`data:text/javascript;base64,${Buffer.from(file.text).toString('base64')}`)));
const {populateMemory,updateMemory,readMemory}=modules.find(module=>module.readMemory);
const controls=()=>({mode:{value:'manual'},manual:{value:'256',disabled:false,min:'32',max:'1048576',dataset:{},required:true},unit:{value:'MiB',disabled:false,dataset:{},options:[{value:'MiB'},{value:'GiB'}]}});

test('import, selected controls, read and export preserve auto and exact numeric requests',()=>{
  for(const requested of ['auto',32,257,4096]){
    const imported=JSON.parse(JSON.stringify({resources:{memory_mb:requested,workers:7,max_record_bytes:123456789,temp_bytes:999,temp_dir:'custom'}}));
    const fields=controls();
    populateMemory(fields,imported.resources.memory_mb);
    assert.equal(fields.mode.value,requested==='auto'?'auto':'manual');
    assert.equal(fields.manual.disabled,requested==='auto');
    const current={...imported,resources:{...imported.resources,memory_mb:readMemory(fields)}};
    const exported=JSON.parse(JSON.stringify(current));
    assert.deepEqual(exported.resources,imported.resources);
    assert.equal(Object.hasOwn(exported,'seed'),false);
    assert.equal(exported.resources.memory_mb,requested);
  }
});

test('omitted memory defaults to automatic and explicit selections retain the manual value',()=>{
  const fields=controls();
  populateMemory(fields,JSON.parse('{}').memory_mb);
  assert.equal(fields.mode.value,'auto');
  assert.equal(readMemory(fields),'auto');
  fields.manual.value='513';
  fields.mode.value='auto';updateMemory(fields);
  assert.equal(readMemory(fields),'auto');
  assert.equal(fields.manual.disabled,true);
  fields.mode.value='manual';updateMemory(fields);
  assert.equal(readMemory(fields),513);
  assert.equal(fields.manual.disabled,false);
  populateMemory(fields,'auto');
  assert.equal(readMemory(fields),'auto');
});

test('memory markup defaults to automatic and exposes both choices without changing other limits',async()=>{
  const html=await readFile('index.html','utf8');
  assert.match(html,/<select id="memory-mode"[^>]*><option value="auto" selected>Automatic<\/option><option value="manual">Manual<\/option>/);
  assert.match(html,/<input id="memory" required type="number" min="32" max="1048576" value="256"/);
  const app=await readFile('src/app.ts','utf8');
  assert.match(app,/populateMemory\(memoryControls,job.resources.memory_mb\)/);
  assert.match(app,/memory_mb:advanced\?readMemory\(memoryControls\)/);
  assert.match(app,/resources:\{\.\.\.defaults.resources,\.\.\.config.resources\}/);
});

test('hosted ceiling remains exact when switching between MiB and GiB',()=>{
  const fields=controls();fields.manual.max='2048';
  populateMemory(fields,2048);
  assert.equal(fields.unit.value,'GiB');assert.equal(fields.manual.max,'2');
  assert.equal(readMemory(fields),2048);
  fields.manual.value='2.0009765625';assert.throws(()=>readMemory(fields),/between/);
  fields.unit.value='MiB';fields.manual.value='2048';updateMemory(fields);
  assert.equal(fields.manual.max,'2048');assert.equal(readMemory(fields),2048);
});
