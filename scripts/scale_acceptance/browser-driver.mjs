// Tiny production client/worker integration. Launch ONLY through the guarded plan.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir, rename} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import http from 'node:http';
import {release, arch} from 'node:os';
import {extract} from './browser-export.mjs';
import {ownedPath, root, sha} from './browser-bundle.mjs';
import {assertProductionWasm, testAssets} from '../browser-artifacts.mjs';

const MiB = 1024 ** 2;
const json = async path => JSON.parse(await readFile(path, 'utf8'));
export function validateFixtures(fixtures) {
  assert.equal(fixtures.length, 2);
  let size = 0;
  for (const [index, fixture] of fixtures.entries()) {
    const width = index === 0 ? 100 : 1000;
    assert.equal(fixture.shape, index === 0 ? 'D' : 'G');
    assert(fixture.tiny === true && fixture.runtime === 'browser');
    assert(Number.isSafeInteger(fixture.rows) && fixture.rows >= 1 && fixture.rows <= 2000, 'Tiny rows required');
    assert(fixture.width === width && fixture.bytes === (fixture.rows + 1) * width, 'Fixed-width fixture size');
    size += fixture.bytes;
  }
  assert(size < 3 * MiB, 'Combined fixture ceiling');
}
export function validateQuota(sample) {
  assert(Number.isFinite(sample.sampled_unix) && Date.now() / 1000 - sample.sampled_unix >= -1 && Date.now() / 1000 - sample.sampled_unix <= 90,
    'Stale quota observation');
  // Match production startup's conservative usable quota floor; scale thresholds do not apply here.
  assert(Number.isFinite(sample.usable_bytes) && sample.usable_bytes >= 128 * MiB, 'Origin quota denied');
}
export function observe(sample, previous, now, lastProgress) {
  validateQuota(sample);
  assert(!sample.error && !['failed', 'cancelled'].includes(sample.status), sample.error || 'Run failed/cancelled');
  const checkpoint = JSON.stringify([sample.status, sample.progress]);
  const advanced = checkpoint !== previous;
  if (advanced) lastProgress = now;
  assert(now - lastProgress < 60_000, 'No progress for 60 seconds');
  return {checkpoint, lastProgress, advanced};
}
export async function deadline(promise, milliseconds, label) {
  let timer;
  try {return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(label + ' deadline')), milliseconds);
  })]);} finally {clearTimeout(timer);}
}
// One bounded in-flight sampler, including while Run/start/extraction awaits.
export function watchQuota(sample, write, interval = 1000) {
  let stopped = false, pending = null, inflight = null, previousStart = null, rejectFailure;
  const failure = new Promise((_, reject) => {rejectFailure = reject;});
  const timer = setInterval(() => {
    if (pending) return;
    pending = (async () => {
      const started = Date.now();
      assert(previousStart === null || started-previousStart <= 45000, 'Quota sampling cadence exceeded');
      previousStart = started;
      inflight = Promise.resolve().then(sample);
      const value = await deadline(inflight, 30000, 'Quota sampler');
      validateQuota(value);
      if (!stopped) await write(value);
    })().catch(error => {clearInterval(timer);if (!stopped) rejectFailure(error);}).finally(() => {pending = null;});
  }, interval);
  return {failure, async stop() {stopped = true; clearInterval(timer); await pending; await inflight?.catch(() => {});}};
}
export async function cleanup(page, context) {
  const errors = [];
  if (page && !page.isClosed()) {
    try {await deadline(page.evaluate(async () => {
      await window.scaleAcceptance?.cancel();
      const state = await window.scaleAcceptance?.sample(false);
      if (state?.error?.includes('cleanup failed')) throw new Error(state.error);
    }), 20_000, 'Public cancel');}
    catch (error) {errors.push(String(error));}
  }
  if (context) {
    try {await deadline(context.close(), 20_000, 'Owned browser close');}
    catch (error) {errors.push(String(error));}
  }
  assert.equal(errors.length, 0, 'Cleanup failed: ' + errors.join('; '));
}
export async function main(packetPath, directory) {
  directory = await ownedPath(directory);
  // Accidental standalone calls cannot launch outside the guard/owned process tree.
  const runnerPid = Number(await readFile(join(directory, 'batch/runner.lock'), 'utf8'));
  assert.equal(runnerPid, process.ppid, 'Use scale-acceptance.py run; live parent guard required');
  const policy = await json(join(directory, 'policy.json'));
  assert.equal(policy.owned_bytes, 64 * MiB);
  assert.equal(policy.deadline_seconds, 600);
  assert.equal(policy.browser_frozen.packet, resolve(packetPath));
  assert.equal(sha(await readFile(packetPath)), policy.browser_frozen.sha256, 'Packet drift');
  const packet = await json(packetPath);
  assert(packet.mode === 'tiny' && packet.runtime === 'browser' && packet.parent_scheduled === true);
  // Playwright detaches POSIX browser processes from the runner group. This driver
  // requires the existing Windows Job containment rather than claiming POSIX stop/reap.
  assert.equal(process.platform, 'win32', 'This owned-process integration driver launches on Windows only');
  assert.equal(sha(await readFile(process.execPath)), packet.node.sha256, 'Selected Node drift');
  assert.equal(sha(await readFile(packet.browser.path)), packet.browser.sha256, 'Selected browser drift');
  const fixtures = await Promise.all(['D', 'G'].map(shape => json(join(directory, shape, 'fixture.json'))));
  validateFixtures(fixtures);
  for (const [index, shape] of ['D', 'G'].entries()) {
    const bytes = await readFile(join(directory, shape, 'input.csv'));
    assert.equal(bytes.length, fixtures[index].bytes);
    assert.equal(sha(bytes), fixtures[index].sha256, 'Fixture hash changed');
  }
  // Refuse all resource test assets and the test WASM export without modifying production assets.
  assert(!Object.keys(packet.input_sha256).some(name => testAssets.includes(name.replace(/^ui\/dist\//, ''))),
    'Test assets in frozen production directory');
  const assets = new Map();
  for (const name of ['engine.wasm', 'engine-worker.js', 'storage-worker.js', 'index.html', 'style.css']) {
    const bytes = await readFile(resolve(root, 'ui/dist', name));
    assert.equal(sha(bytes), packet.input_sha256['ui/dist/' + name], 'Production asset drift');
    assets.set('/' + name, bytes);
  }
  assertProductionWasm(assets.get('/engine.wasm'));
  const bridge = await readFile(resolve(root, packet.bundle));
  assert.equal(sha(bridge), packet.input_sha256[packet.bundle], 'Bridge drift');
  assets.set('/bridge.js', bridge);
  const html = assets.get('/index.html').toString('utf8');
  assert.equal(html.split('src="/app.js"').length, 2, 'Expected production page script');
  assets.set('/', Buffer.from(html.replace('src="/app.js"', 'src="/bridge.js"')
    .replace('</body>', '<input id="fixture" type="file" hidden></body>')));
  const work = join(directory, 'work');
  await mkdir(work); // Exclusive profile/output/origin owner; never remove failures or reuse a profile.
  const atomic = async (name, value) => {
    await writeFile(join(work, name + '.tmp'), JSON.stringify(value) + '\n');
    await rename(join(work, name + '.tmp'), join(work, name));
  };
  let context, page, server, watcher, stopping = false;
  const receipt = {status: 'failed', channel: packet.channel, source: packet.source,
    packet_sha256: policy.browser_frozen.sha256, browser: packet.browser,
    platform: process.platform, os_release: release(), architecture: arch(),
    profile: join(work, 'profile'), origin: packet.origin, output_root: work,
    coverage: 'tiny public production browserApi/worker/WASM; injected File picker and OPFS destination; no actual dialog/external filesystem/scale acceptance',
    shapes: [], unrun: ['D', 'G']};
  let failure;
  try {
    server = http.createServer((request, response) => {
      const path = request.url;
      const bytes = request.method === 'GET' && assets.get(path);
      response.writeHead(bytes ? 200 : 404, {
        'Content-Type': path?.endsWith('.wasm') ? 'application/wasm' : path?.endsWith('.js') ? 'text/javascript' : path?.endsWith('.css') ? 'text/css' : 'text/html',
        'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"
      });
      response.end(bytes || 'Not found');
    });
    await new Promise((accept, reject) => {
      server.once('error', reject);
      server.listen(Number(new URL(packet.origin).port), '127.0.0.1', accept);
    });
    // Reuse the channel selector; explicit executablePath binds the actual installed binary.
    process.env.CHOPPER_BROWSER_CHANNEL = packet.channel;
    const {browserChannel, browserLaunchOptions} = await import('../browser-launch.mjs');
    assert.equal(browserChannel, packet.channel);
    const {chromium} = await import('../../ui/node_modules/playwright/index.mjs');
    context = await chromium.launchPersistentContext(receipt.profile, {
      ...browserLaunchOptions, executablePath: packet.browser.path, headless: true, serviceWorkers: 'block', timeout: 30_000
    });
    receipt.actual_browser_version = context.browser().version();
    assert.equal(receipt.actual_browser_version, packet.browser_version, 'Browser version drift');
    await context.route('**/*', route => route.request().url().startsWith(packet.origin + '/') ? route.continue() : route.abort());
    page = context.pages()[0] || await context.newPage();
    page.setDefaultTimeout(20_000);
    await page.goto(packet.origin + '/', {waitUntil: 'load'});
    await page.waitForFunction(() => !!window.scaleAcceptance && document.getElementById('status')?.textContent === 'IDLE');
    await deadline(page.evaluate(() => window.scaleAcceptance.capacity()), 30000, 'Initial capacity');
    watcher = watchQuota(() => page.evaluate(() => window.scaleAcceptance.capacity()),
      sample => atomic('quota.json', sample));
    const transport = {evaluate(...args) {
      assert(!stopping, 'Attempt stopping');
      return deadline(page.evaluate(...args), 10_000, 'Export transport');
    }};
    const runShapes = async () => {
      for (const shape of ['D', 'G']) {
        assert(!stopping, 'Attempt stopping');
        await page.locator('#fixture').setInputFiles(join(directory, shape, 'input.csv'));
        const job = await json(join(directory, shape, 'job.json'));
        // Public defaults starts real workers: establish quota before any Run.
        observe(await deadline(page.evaluate(() => window.scaleAcceptance.sample(false)), 10_000, 'Initial quota'),
          null, Date.now(), Date.now());
        assert(!stopping, 'Attempt stopping');
        await deadline(page.evaluate(job => window.scaleAcceptance.start(job), job), 30_000, 'Public Run start');
        let previous, lastProgress = Date.now(), sample;
        do {
          sample = await deadline(page.evaluate(() => window.scaleAcceptance.sample(false)), 10_000, 'Public sample');
          const observation = observe(sample, previous, Date.now(), lastProgress);
          previous = observation.checkpoint; lastProgress = observation.lastProgress;
          await atomic('latest-sample.json', {shape, ...sample});
          if (observation.advanced) await atomic('progress.json', {shape, checkpoint: previous});
          if (sample.status !== 'complete') await new Promise(accept => setTimeout(accept, 1000));
          assert(!stopping, 'Attempt stopping');
        } while (sample.status !== 'complete');
        await atomic(shape + '-public-state.json', sample);
        const files = await extract(transport, join(work, shape), async checkpoint => {
          await atomic('progress.json', {shape, extraction: checkpoint});
        }, {maxBytes: 16 * MiB});
        assert(!stopping, 'Attempt stopping');
        receipt.shapes.push({shape, files, public_state: shape + '-public-state.json'});
        receipt.unrun.shift();
      }
    };
    await Promise.race([runShapes(), watcher.failure]);
    receipt.status = 'extracted'; // Independent verifier steps are still required, never acceptance here.
  } catch (error) {failure = error; receipt.error = String(error);}
  finally {
    stopping = true;
    // Stop sampling before public cancellation changes state; deadline bounds in-flight sample.
    const samplerStop = watcher?.stop();
    try {await cleanup(page, context); receipt.cleanup = 'public cancel and owned context close completed';}
    catch (error) {failure ||= error; receipt.cleanup_error = String(error); receipt.status = 'failed';}
    await samplerStop;
    if (server) {server.closeAllConnections(); await new Promise(accept => server.close(accept));}
    await atomic('browser-receipt.json', receipt);
  }
  if (failure) throw failure;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main(process.argv[2], process.argv[3]);
}
