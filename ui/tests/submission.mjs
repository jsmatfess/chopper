import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('actual markup retains Run submission and separate explicit preparation controls',async()=>{
  const html=await readFile('index.html','utf8');
  const form=html.match(/<form id="job-form">([\s\S]*?)<\/form>/)[1];
  assert.match(html,/<button type="submit" id="run-direct" form="job-form"[^>]*>Run /);
  assert.match(html,/<button type="button" id="analyze"[^>]*>Prepare exact outputs<\/button>/);
  assert.doesNotMatch(form,/require-reproducible|id="seed"|randomization-help/);
});
