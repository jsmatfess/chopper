import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
const bundle=await build({entryPoints:['src/column-picker.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {columnChoices,columnIndex,pickerMarkup,matchingColumns}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);

test('preserves exact header text and distinguishes duplicate names by index',()=>{
  const schema={columns:4,header:['country, region','segment','segment','']};
  assert.deepEqual(columnChoices(schema).map(c=>c.value),['country, region',1,2,'']);
  assert.equal(columnIndex('country, region',schema),0);
  assert.equal(columnIndex('segment',schema),undefined);
  assert.equal(columnIndex(2,schema),2);
});
test('headerless columns use numeric references and reject invalid indices',()=>{
  const schema={columns:2,header:null};
  assert.deepEqual(columnChoices(schema).map(c=>c.value),[0,1]);
  for(const ref of [-1,2,0.5,'0'])assert.equal(columnIndex(ref,schema),undefined);
});
test('picker excludes name/index aliases and escapes imported chip names',()=>{
  const schema={columns:2,header:['country','segment']};
  const markup=pickerMarkup('columns',[0,'<script>'],0,schema,'');
  assert.deepEqual(matchingColumns(schema,[0],'').map(c=>c.index),[1]);
  assert.ok(markup.includes('role="combobox"'));
  assert.ok(!markup.includes('<select'));
  assert.ok(markup.includes('&lt;script&gt;'));
  assert.ok(pickerMarkup('strata',['country'],1,null,'Choose input').includes('Load columns'));
});

test('typeahead matches names or indices without offering selected columns',()=>{
  const schema={columns:4,header:['country, region','segment','segment','note']};
  assert.deepEqual(matchingColumns(schema,[], ' REGION ').map(c=>c.value),['country, region']);
  assert.deepEqual(matchingColumns(schema,[1], 'SEG').map(c=>c.value),[2]);
  assert.deepEqual(matchingColumns(schema,[], '#2').map(c=>c.value),[2]);
  assert.deepEqual(matchingColumns(schema,[], 'missing'),[]);
});
