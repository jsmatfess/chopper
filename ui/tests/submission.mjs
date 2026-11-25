import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';

test('actual markup exposes Analyze and Run without preparation or confirmation',async()=>{
  const html=await readFile('index.html','utf8');
  const form=html.match(/<form id="job-form">([\s\S]*?)<\/form>/)[1];
  assert.match(html,/<button type="submit" id="run-direct" form="job-form"[^>]*>Run /);
  assert.match(html,/<button type="button" id="profile"[^>]*>Analyze<\/button>/);
  assert.doesNotMatch(html,/id="analyze"|Prepare exact outputs|Confirm & split/);
  assert.doesNotMatch(form,/require-reproducible|id="seed"|randomization-help/);
});

const ownershipBundle=await build({entryPoints:['src/result-ownership.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {HostedResultOwnership,resultOrigin}=await import(`data:text/javascript;base64,${Buffer.from(ownershipBundle.outputFiles[0].text).toString('base64')}`);
const draft={input:'data.csv',zip_member:null,input_csv:{delimiter:','},limits:{rows:null}};

test('state polls can apply while newer polls are pending and cannot apply out of order or across commands',async()=>{
  const results=new HostedResultOwnership();
  const source=results.sourceKey(draft);
  const first=results.beginPoll();
  const second=results.beginPoll();
  assert.ok(results.acceptPoll(first,{},source));
  const third=results.beginPoll();
  assert.ok(results.acceptPoll(third,{},source));
  assert.equal(results.acceptPoll(second,{},source),null);

  const beforeCommand=results.beginPoll();
  const command=results.cancel(async()=>{});
  assert.equal(results.beginPoll(),null);
  assert.equal(results.acceptPoll(beforeCommand,{},source),null);
  await command;
  assert.equal(results.acceptPoll(beforeCommand,{},source),null);
  assert.ok(results.acceptPoll(results.beginPoll(),{},source));
});

test('Run acknowledgement clears only its submitted draft revision',async()=>{
  const results=new HostedResultOwnership();
  const source=results.sourceKey(draft);
  let acknowledge;
  const submitted=results.run(draft,source,()=>new Promise(resolve=>{acknowledge=resolve;}));
  results.editDraft(source);
  acknowledge();
  await submitted;
  assert.equal(results.dirty,true,'even an edit that reverts to the submitted values advances the revision');
  await assert.rejects(results.run(draft,source,async()=>{throw new Error('denied');}),/denied/);
  assert.equal(results.dirty,true);
  assert.equal(results.commandPending,false);
  await results.run(draft,source,async()=>{});
  assert.equal(results.dirty,false);
});

test('profiles follow the source and prior Run results cannot populate a replacement source',async()=>{
  const results=new HostedResultOwnership();
  const source=results.sourceKey(draft);
  const profile={rows:5};
  const origins={profile:resultOrigin(source,draft,0,1),analysis:resultOrigin(source,draft,0,2)};
  await results.analyze(draft,source,async()=>{});
  assert.deepEqual(results.acceptPoll(results.beginPoll(),{profile,origins},source),{profile,analysisSource:null});
  assert.equal(results.editDraft(source).profile,profile);
  assert.equal(results.profileMatchesJob({...draft,limits:{rows:1}}),false);
  assert.equal(results.profileMatchesJob(draft),true);

  results.selectInput();
  const replacement=results.sourceKey(draft);
  assert.notEqual(replacement,source);
  assert.deepEqual(results.editDraft(replacement),{profileCurrent:false,profile:null});
  assert.deepEqual(results.acceptPoll(results.beginPoll(),{profile,origins},replacement),{profile:null,analysisSource:null});
  await results.run(draft,replacement,async()=>{});
  assert.equal(results.acceptPoll(results.beginPoll(),{},replacement).analysisSource,replacement);
});
