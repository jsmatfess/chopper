import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('actual markup exposes Analyze and Run without preparation or confirmation',async()=>{
  const html=await readFile('index.html','utf8');
  const form=html.match(/<form id="job-form">([\s\S]*?)<\/form>/)[1];
  assert.match(html,/<button type="submit" id="run-direct" form="job-form"[^>]*>Run /);
  assert.match(html,/<button type="button" id="profile"[^>]*>Analyze<\/button>/);
  assert.doesNotMatch(html,/id="analyze"|Prepare exact outputs|Confirm & split/);
  assert.doesNotMatch(form,/require-reproducible|id="seed"|randomization-help/);
});
