// Synthetic contract controls; never import Playwright or launch a browser.
import assert from 'node:assert/strict';
import {validateFixtures, observe, deadline, cleanup, main, watchQuota} from './browser-driver.mjs';
import {ownedPath} from './browser-bundle.mjs';
const fixtures = ['D', 'G'].map((shape, i) => ({shape, width: i ? 1000 : 100,
  runtime: 'browser', tiny: true, rows: 2000, bytes: 2001 * (i ? 1000 : 100)}));
validateFixtures(fixtures);
for (const mutate of [f => f[0].rows = 2001, f => f[1].tiny = false,
  f => f[1].bytes++, f => f[0].runtime = 'native', f => f.reverse(), f => f.pop()]) {
  const changed = structuredClone(fixtures); mutate(changed);
  assert.throws(() => validateFixtures(changed));
}
const sample = {sampled_unix: Date.now() / 1000, usable_bytes: 128 * 1024**2,
  status: 'running', progress: {phase: 'read', rows: 4, temp_bytes: 0}};
const first = observe(sample, null, 0, 0);
assert.equal(first.advanced, true);
assert.equal(observe(sample, first.checkpoint, 1000, 0).advanced, false);
assert.throws(() => observe(sample, first.checkpoint, 60000, 0), /No progress/);
for (const patch of [{usable_bytes: 0}, {usable_bytes: NaN}, {sampled_unix: 0},
  {sampled_unix: Date.now() / 1000 + 60}, {error: 'storage denial'}, {status: 'failed'}, {status: 'cancelled'}]) {
  assert.throws(() => observe({...sample, ...patch}, null, 0, 0));
}
assert.equal(await deadline(Promise.resolve(7), 100, 'control'), 7);
await assert.rejects(deadline(new Promise(() => {}), 1, 'control'), /deadline/);
const calls = [];
await cleanup({isClosed: () => false, evaluate: async () => calls.push('cancel')}, {close: async () => calls.push('close')});
assert.deepEqual(calls, ['cancel', 'close']);
await assert.rejects(cleanup({isClosed: () => false, evaluate: async () => {throw Error('cancel denied');}},
  {close: async () => calls.push('close-after-denial')}), /Cleanup failed/);
assert.equal(calls.at(-1), 'close-after-denial');
await assert.rejects(cleanup(null, {close: async () => {throw Error('close denied');}}), /Cleanup failed/);
await assert.rejects(ownedPath('scratch/../escape'), /traversal/);
await assert.rejects(ownedPath('/tmp/unowned'), /scratch/);
await assert.rejects(main('/missing-packet', 'scratch/absent-standalone-control'), /ENOENT/);


let quotaSamples = 0;
const watcher = watchQuota(async () => {quotaSamples++; return {...sample, usable_bytes: 0};}, async () => {}, 1);
await assert.rejects(watcher.failure, /quota denied/);
await watcher.stop();
assert.equal(quotaSamples, 1);
const writerDenial = watchQuota(async () => sample, async () => {throw Error('sample write denied');}, 1);
await assert.rejects(writerDenial.failure, /sample write denied/);
await writerDenial.stop();

const originalAdapter = window.scaleAcceptance;
window.scaleAcceptance = {cancel: async () => {}, sample: async () => ({error: 'Temporary storage cleanup failed: denied'})};
await assert.rejects(cleanup({isClosed: () => false, evaluate: async fn => fn()}, {close: async () => {}}), /Cleanup failed/);
window.scaleAcceptance = originalAdapter;
console.log('Browser tiny/lifecycle/prelaunch/quota negative controls passed; production integration UNRUN');
