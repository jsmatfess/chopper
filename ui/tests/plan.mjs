import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {limits,partition,assign,balanced,shuffle,scenarios,simulations} from './plan-scenarios.mjs';

const bundle = await build({entryPoints:['src/plan.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {percentageUnits,groupErrors,describePlan} = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const describe = (operations, changes = {}) => describePlan(operations,changes.limits || limits,changes.compression || 'none');
const summary = (operations,changes) => describe(operations,changes).split('\n\n')[0];

test('opt-in algorithms explain changed guarantees without weakening exact defaults',()=>{
  const approximate={type:'assign_probabilistic',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:['country']};
  const text=describe([approximate]);
  assert.match(text,/approximately 80%/);
  assert.match(text,/targets, not exact quotas/);
  assert.match(text,/small strata may receive no rows/);
  assert.doesNotMatch(text,/rounded to whole rows/);
  const cyclic=describe([{type:'interleaved',files:3}],{limits:{...limits,rows:'10'}});
  assert.match(cyclic,/cyclically across 3 CSVs/);
  assert.match(cyclic,/concatenating files does not restore input order/);
  assert.match(cyclic,/file count stays fixed/);
  assert.match(describe([{type:'shuffle',strategy:'fisher_yates'}]),/Each group must fit in memory or the job fails/);
});

test('percentages use exact decimal units and reject unsupported values',()=>{
  assert.equal(percentageUnits('33.333333'),33_333_333);
  assert.equal(percentageUnits('0.000001'),1);
  assert.equal(percentageUnits('100.'),100_000_000);
  for(const value of ['-1','101','100.000001','0.0000001','1e2','NaN','']) assert.equal(percentageUnits(value),null,value);
  assert.deepEqual(groupErrors([{name:'a',percent:'33.333333'},{name:'b',percent:'33.333333'},{name:'c',percent:'33.333334'}]),[]);
  assert.match(groupErrors([{name:'a',percent:'99.999999'}]).join(' '),/exactly 100/);
});

test('group names can contain commas and equals signs; missing and duplicate names fail',()=>{
  assert.deepEqual(groupErrors([{name:'a,b=c',percent:'100'}]),[]);
  assert.match(groupErrors([{name:' ',percent:'100'}]).join(' '),/name/);
  assert.match(groupErrors([{name:'a',percent:'50'},{name:'a',percent:'50'}]).join(' '),/unique/);
});

test('simple plans lead with the actual output',()=>{
  assert.equal(describe([]),'Write the input to one CSV, keeping rows in their original order.');
  assert.equal(summary([shuffle]),'Shuffle the input rows into a random order, then write them to one CSV.');
  assert.equal(summary([partition]),'Create a CSV for each unique combination of “country” and “segment”.');
});

test('partition and assignment read as one output plan',()=>{
  assert.equal(summary([partition,assign]),'For each unique combination of “country” and “segment”, create a CSV for “treatment” with 80% of the matching rows and a CSV for “control” with 20%, choosing rows randomly.');
  const reversed = summary([assign,partition]);
  assert.match(reversed,/^Randomly assign 80% of the rows/);
  assert.match(reversed,/within each allocation\.$/);
  assert.notEqual(reversed,summary([partition,assign]));
});

test('shuffle position preserves the difference between random membership and random file order',()=>{
  assert.equal(summary([shuffle,balanced]),'Shuffle the input rows into a random order, then split them as evenly as possible into 3 CSVs.');
  assert.equal(summary([balanced,shuffle]),'Split the input as evenly as possible into 3 CSVs. Shuffle the rows in each CSV into a random order before writing.');
  assert.doesNotMatch(describe([shuffle,balanced]),/original order/);
});

test('balanced files are per parent group and remain nonempty',()=>{
  assert.equal(summary([partition,balanced]),'For each unique combination of “country” and “segment”, split the matching rows as evenly as possible into 3 CSVs.');
  assert.match(summary([balanced,partition]),/3 parts\. Create a CSV.*within each part/);
  assert.match(summary([assign,balanced]),/split each allocation as evenly as possible into 3 CSVs/i);
  assert.match(describe([balanced]),/nonempty parts whose row counts differ by at most one/);
  assert.equal(summary([{...balanced,files:1}]),'Keep the input together in one CSV.');
});

test('strata are pooled into named allocations instead of creating extra output files',()=>{
  const result = describe([{...assign,strata:['country','segment']}]);
  assert.match(result,/percentages separately for each unique combination of “country” and “segment”/);
  assert.match(result,/pooling the results into the corresponding “treatment” and “control” outputs/);
  assert.doesNotMatch(result,/CSV for each.*country/);
});

test('earlier partition keys avoid redundant stratification prose',()=>{
  assert.equal(describe([partition,{...assign,strata:['country','segment']}]),describe([partition,assign]));
  const result = describe([{...partition,columns:['country']},{...assign,strata:['country','segment']}]);
  assert.match(result,/percentages separately for each distinct value of “segment”/);
  assert.equal((result.match(/“country”/g) || []).length,1);
});

test('strata in intermediate assignments stay within their named allocations',()=>{
  assert.match(describe([{...assign,strata:['country']},balanced]),/corresponding “treatment” and “control” allocations/);
  assert.match(describe([balanced,{...assign,strata:['country']}]),/Within each part, create/);
});

test('one or zero percent allocations avoid false random-selection claims',()=>{
  assert.equal(summary([{...assign,groups:[{name:'all',percent:'100'}]}]),'Create a CSV for “all” containing all rows.');
  const result = describe([{...assign,groups:[{name:'all',percent:'100'},{name:'empty',percent:'0'}]}]);
  assert.match(result,/an empty CSV for “empty”/);
  assert.doesNotMatch(result,/random|rounded/);
  const emptyFirst = summary([{...assign,groups:[{name:'empty',percent:'0'},...assign.groups]}]);
  assert.match(emptyFirst,/an empty CSV.*“treatment” with 80% of the rows/);
});

test('lists and arbitrary names stay readable without guessing indefinite articles',()=>{
  assert.match(summary([{...partition,columns:['x','y','z']}]),/“x”, “y”, and “z”/);
  const result = summary([{...assign,groups:[{name:'A',percent:'80.000000'},{name:'control, holdout=1',percent:'20'}]}]);
  assert.match(result,/a CSV for “A” with 80%/);
  assert.match(result,/a CSV for “control, holdout=1” with 20%/);
  assert.doesNotMatch(result,/a “A”|80\.000000/);
});

test('fixed final balanced files reject hard caps instead of promising more files',()=>{
  const result = describe([balanced,shuffle],{limits:{...limits,rows:'10000',bytes:'64MiB'}});
  assert.match(result,/10,000 data rows and 64 MiB/);
  assert.match(result,/file count stays fixed; analysis will reject/);
  assert.match(result,/header and byte-order mark/);
});

test('partition or assignment after balancing allows further chunks',()=>{
  for(const last of [partition,assign]) {
    const result = describe([balanced,last],{limits:{...limits,rows:'1000'}});
    assert.match(result,/CSV files/);
    assert.doesNotMatch(result,/file count stays fixed|analysis will reject/);
  }
});

test('approximate targets guide splitting but do not subdivide final balanced files',()=>{
  const changes = {limits:{...limits,compressed:'10MB'},compression:'zip'};
  assert.match(describe([partition],changes),/Create CSV files/);
  assert.match(describe([partition],changes),/10 MB per compressed CSV inside the ZIP/);
  assert.match(describe([balanced],changes),/chosen file count even if.*larger/);
  assert.doesNotMatch(describe([balanced,assign],changes),/chosen file count/);
  assert.match(describe([],{limits:changes.limits}),/Choose an output compression format/);
  assert.match(summary([],{limits:changes.limits}),/one CSV/);
});

test('repeated shuffles remain explicit, ordered, and correctly scoped',()=>{
  const result = summary([shuffle,shuffle,shuffle,balanced]);
  assert.match(result,/Shuffle the input rows.*Shuffle them again.*Shuffle them again.*split them/);
  assert.equal((result.match(/shuffle/gi) || []).length,3);
});

test('numeric references are explained once without repeating index jargon',()=>{
  const result = describe([{...partition,columns:[0,2]}, {...assign,strata:[0,1]}]);
  assert.match(result,/column #0 and column #2/);
  assert.match(result,/percentages separately for each distinct value of column #1/);
  assert.equal((result.match(/Column numbers start at 0/g) || []).length,1);
});

test('incomplete forms explain the next choice rather than fabricating an output',()=>{
  for(const scenario of scenarios.filter(s => /Unfinished|Invalid allocation/.test(s.name))) {
    const result = describePlan(scenario.operations,scenario.limits,scenario.compression);
    assert.match(result,/Choose /);
    assert.doesNotMatch(result,/undefined|NaN|\?|\(add groups\)|\(choose columns\)|0 CSVs/);
  }
});

test('9,372 combinations preserve ordering, fixed counts, compression, and row order',()=>{
  let count = 0;
  for (const scenario of simulations()) {
    const {operations,limits,compression} = scenario;
    const result = describePlan(operations,limits,compression);
    const context = JSON.stringify(scenario);
    const lastGroup = operations.filter(op => op.type !== 'shuffle').at(-1);
    const shuffles = operations.filter(op => op.type === 'shuffle');
    assert.ok(result.length,context);
    assert.doesNotMatch(result,/undefined|NaN|current group|\?|\b1 parts\b|\b1 CSVs\b/,context);
    assert.equal(result.includes('original order'),shuffles.length === 0,context);
    assert.equal((result.split('\n\n')[0].match(/\bshuffle\b/gi) || []).length,shuffles.length,context);
    assert.equal(result.includes('file count stays fixed'),!!(limits.rows || limits.bytes) && lastGroup?.type === 'balanced',context);
    assert.equal(result.includes('chosen file count'),!!limits.compressed && compression !== 'none' && lastGroup?.type === 'balanced',context);
    assert.equal(result.includes('one ZIP archive'),compression === 'zip',context);
    assert.equal(result.includes('with gzip'),compression === 'gzip',context);
    assert.equal(result.includes('with Zstandard'),compression === 'zstd',context);
    count++;
  }
  assert.equal(count,9372);
});


test('linked prose maps each operation and limit to its own editor target',()=>{
  const links=[];
  describePlan([shuffle,partition,assign,balanced],{rows:'10',bytes:'1MB',compressed:'500KB'},'zip',(text,target)=>{links.push({text,target});return text;});
  for(const target of ['step-0','step-1','step-2','step-3','max-rows','max-bytes','compressed-bytes','compression'])assert(links.some(link=>link.target===target),target);
  assert.match(links.find(link=>link.target==='step-0').text,/Shuffle/);
  assert.match(links.find(link=>link.target==='step-1').text,/Group/);
  assert.match(links.find(link=>link.target==='max-rows').text,/10 data rows/);
  assert.match(links.find(link=>link.target==='max-bytes').text,/1 MB/);
  assert(links.every(link=>!link.text.includes(', then ')),'linked steps remain separate navigation targets');
});

test('linked simple plans retain row-order and flexible-policy explanations',()=>{
  const links=[];
  const text=describePlan([],limits,'none',(text,target)=>{links.push({text,target});return text;});
  assert.match(text,/Write the input to one CSV, keeping rows in their original order/);
});
