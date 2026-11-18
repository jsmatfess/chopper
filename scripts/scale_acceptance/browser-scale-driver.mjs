// The full controller's explicit tiny qualification keeps its inventory and guards.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir, rename, appendFile, lstat} from 'node:fs/promises';
import {createReadStream, constants} from 'node:fs';
import {createHash} from 'node:crypto';
import {join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {release, version, arch, hostname} from 'node:os';
import http from 'node:http';
import {ownedPath, sha} from './browser-bundle.mjs';
import {deadline, watchQuota} from './browser-driver.mjs';
import {extract, validateMarker} from './browser-export.mjs';
import {assertProductionWasm, testAssets} from '../browser-artifacts.mjs';
import {observeStorageCapacity, installRecoveredExport} from './browser-page.mjs';
const GiB = 1024 ** 3;
const json = async path => JSON.parse(await readFile(path, 'utf8'));
export function observationPublisher(work) {
  const channels = new Map();
  let closed = false;
  const checked = async (path, previous) => {
    const current = await lstat(path, {bigint: true});
    assert(current.isFile() && current.nlink === 1n, 'Observation regular single-link file');
    if (previous) assert(current.dev === previous.dev && current.ino === previous.ino &&
      current.size >= previous.size, 'Observation identity/truncation drift');
    return current;
  };
  const publish = (name, value) => {
    assert(!closed, 'Observation publisher stopped');
    assert(['quota', 'progress'].includes(name), 'Explicit observation channel');
    const record = JSON.stringify(value) + '\n';
    if (name === 'quota') assert(Buffer.byteLength(record) <= 1024 ** 2, 'Quota JSON bound');
    const state = channels.get(name) || {pending: Promise.resolve(), identity: null};
    channels.set(name, state);
    state.pending = state.pending.then(async () => {
      const path = join(work, name + '.jsonl');
      if (!state.identity) {
        await lstat(path).then(() => {throw Error('Fresh observation required');},
          error => {if (error.code !== 'ENOENT') throw error;});
        // Publish the first complete record before any reader can see the file.
        await writeFile(path + '.tmp', record, {flag: 'wx'});
        await rename(path + '.tmp', path);
        state.identity = await checked(path);
      } else {
        const before = await checked(path, state.identity);
        await appendFile(path, record, {flag: constants.O_WRONLY | constants.O_APPEND});
        const after = await checked(path, before);
        assert(after.size === before.size + BigInt(Buffer.byteLength(record)), 'Observation append length');
        state.identity = after;
      }
    });
    return state.pending;
  };
  publish.stop = async () => {
    closed = true;
    const results = await Promise.allSettled([...channels.values()].map(state => state.pending));
    const errors = results.filter(value => value.status === 'rejected').map(value => value.reason);
    if (errors.length) throw new AggregateError(errors, 'Observation publication failed');
  };
  return publish;
}
export async function streamIdentity(path) {
  const hash = createHash('sha256');
  let bytes = 0, lines = 0;
  for await (const chunk of createReadStream(path, {highWaterMark: 64 * 1024})) {
    hash.update(chunk); bytes += chunk.length;
    for (const byte of chunk) if (byte === 10) lines++;
  }
  return {sha256: hash.digest('hex'), bytes, rows: lines - 1};
}
export function validateScaleFixture(fixture, packet) {
  const qualifying = packet.mode === 'qualify';
  const [width, scaleRows] = packet.shape === 'D' ? [100, 9_999_999] : [1000, 999_999];
  const rows = qualifying ? packet.fixture.rows : scaleRows;
  if (qualifying) assert(Number.isSafeInteger(rows) && rows >= 1 && rows <= 127);
  assert(['D', 'G'].includes(packet.shape));
  assert.equal(fixture.shape, packet.shape);
  assert.equal(fixture.generator, 'release-acceptance-v1');
  assert.equal(fixture.runtime, 'browser'); assert.equal(fixture.tiny, qualifying);
  assert.equal(fixture.width, width); assert.equal(fixture.rows, rows);
  assert.equal(fixture.bytes, qualifying ? (rows + 1) * width : 1_000_000_000);
  assert.deepEqual({width: fixture.width, rows: fixture.rows, bytes: fixture.bytes, sha256: fixture.sha256}, packet.fixture);
}
export function observedSpill(state, expectedRows) {
  assert(state?.status === 'complete' && state.error === null, 'Successful terminal Run required for spill proof');
  assert(Number.isSafeInteger(expectedRows) && expectedRows > 0, 'Bound expected fixture rows');
  const graph = state.graph;
  assert(graph && graph.unavailable === false && !graph.truncated &&
    Number.isSafeInteger(graph.eventsOmitted) && graph.eventsOmitted >= 0 &&
    Array.isArray(graph.steps) && graph.steps.length <= 1156, 'Complete public graph required for spill proof');
  const selected = graph.steps.filter(step => ['spill', 'merge', 'hierarchical_merge', 'merge_traversal'].includes(step.kind));
  const facts = selected.map(step => {
    const outcomes = {};
    for (const name of ['completed', 'interrupted', 'failed', 'handed_off']) {
      const value = step.outcomes?.[name];
      assert(value && ['rows', 'runs', 'attempts'].every(key => Number.isSafeInteger(value[key]) && value[key] >= 0),
        'Actual physical outcome metrics required');
      assert(value.attempts > 0 || value.rows === 0 && value.runs === 0, 'Rows/runs require an actual attempt');
      outcomes[name] = {rows: value.rows, runs: value.runs, attempts: value.attempts};
    }
    assert(outcomes.failed.rows === 0 && outcomes.failed.runs === 0 && outcomes.failed.attempts === 0 &&
      (step.status === 'completed' || step.kind === 'merge_traversal' && step.status === 'interrupted'),
      'Failed or nonterminal physical work cannot qualify');
    return {id: step.id, kind: step.kind, status: step.status, outcomes};
  });
  assert(facts.some(step => step.kind === 'spill' && step.outcomes.completed.rows > 0 &&
    step.outcomes.completed.runs > 0 && step.outcomes.completed.attempts > 0), 'Actual completed spill runs required');
  const completedMerge = facts.some(step => step.kind !== 'spill' && step.outcomes.completed.rows > 0 &&
    step.outcomes.completed.attempts > 0 && (step.kind === 'merge_traversal'
      ? step.outcomes.interrupted.attempts === 0 : step.outcomes.completed.runs > 0));
  // Exact assignment reads its quotas, then drops the exhausted cursor without
  // requesting another next(): MergeRows truthfully records Interrupted on Drop.
  const quotaTraversal = facts.some(step => step.kind === 'merge_traversal' &&
    step.outcomes.interrupted.attempts > 0 &&
    step.outcomes.completed.rows + step.outcomes.interrupted.rows === expectedRows);
  assert(completedMerge || quotaTraversal, 'Actual merge work must cover the successful Run');
  return {source: 'public-state.json graph; completed and interrupted outcomes remain separate', facts,
    event_details_omitted: graph.eventsOmitted,
    upstream_details_omitted: selected.filter(step => step.source_omitted).map(step => step.id)};
}
export async function qualifyFailure(page, job, sample, atomic) {
  // A one-byte cap cannot hold even the header. This is a real engine failure
  // through public Run, without worker routes, fake handles beyond this profile,
  // extra fixtures or workload expansion.
  await deadline(page.evaluate(job => window.scaleAcceptance.start(job),
    {...job, limits: {...job.limits, bytes: 1}}), 30_000, 'Controlled failure Run start');
  const end = Date.now() + 45_000;
  let current;
  do {
    current = await sample(); validateScaleQuota(current);
    assert(Date.now() < end, 'Controlled failure deadline');
    assert(!['complete', 'cancelled'].includes(current.status), 'Expected the controlled engine failure');
    if (current.status !== 'failed') await new Promise(accept => setTimeout(accept, 25));
  } while (current.status !== 'failed');
  assert(current.error?.includes('header/BOM exceeds output byte limit') && !current.error.includes('cleanup failed'), 'Expected failure with successful retirement');
  await atomic('controlled-failure.json', current);
  await deadline(page.evaluate(() => window.scaleAcceptance.cancel()), 20_000, 'Failure retirement');
  const cleanup = await deadline(page.evaluate(() => window.scaleAcceptance.incomplete()), 4000, 'Incomplete output census');
  assert.deepEqual(cleanup, {entries: [], workspaces: [], locks: []}, 'Incomplete output/marker/workspace/lock residue');
  await atomic('controlled-failure-cleanup.json', cleanup);
  return {public_run: true, expected_status: 'failed', cleanup};
}
export async function observeScaleCapacity(page, context, packet, profile) {
  const sampled_unix = Date.now() / 1000, end = Date.now() + 30000;
  const bounded = (work, label) => {
    const remaining = end - Date.now(); assert(remaining > 0, label + ' deadline');
    return deadline(Promise.resolve().then(work), remaining, label);
  };
  const web_estimate = await bounded(() => page.evaluate(observeStorageCapacity), 'Web quota estimate');
  assert.equal(web_estimate.origin, packet.origin, 'Capacity page origin binding');
  assert(web_estimate.secure_context && web_estimate.cross_origin_isolated, 'Capacity page isolation');
  let session, actual_quota;
  try {
    session = await bounded(() => context.newCDPSession(page), 'Capacity CDP attach');
    actual_quota = await bounded(() => session.send('Storage.getUsageAndQuota', {origin: packet.origin}), 'Actual origin quota');
  } finally {
    if (session) await deadline(session.detach(), Math.max(1, end - Date.now()), 'Capacity CDP detach');
  }
  const valid = Number.isSafeInteger(actual_quota?.quota) && Number.isSafeInteger(actual_quota?.usage) &&
    actual_quota.usage >= 0 && actual_quota.quota >= actual_quota.usage;
  return {sampled_unix, origin: web_estimate.origin, profile,
    secure_context: web_estimate.secure_context, cross_origin_isolated: web_estimate.cross_origin_isolated,
    capacity_source: 'CDP Storage.getUsageAndQuota', actual_quota, web_estimate,
    usable_bytes: valid ? Math.floor((actual_quota.quota - actual_quota.usage) * 0.8) : null};
}
export function validateScaleQuota(sample, start = false, now = Date.now() / 1000) {
  assert(Number.isFinite(sample.sampled_unix) && now - sample.sampled_unix >= -1 && now - sample.sampled_unix <= 90, 'Stale quota');
  if (sample.capacity_source === 'CDP Storage.getUsageAndQuota') {
    assert(sample.actual_quota?.overrideActive === false, 'Origin quota override denied');
    assert(Number.isSafeInteger(sample.actual_quota.quota) && Number.isSafeInteger(sample.actual_quota.usage) &&
      sample.actual_quota.usage >= 0 && sample.actual_quota.quota >= sample.actual_quota.usage, 'Invalid actual origin quota');
    assert.equal(sample.usable_bytes, Math.floor((sample.actual_quota.quota - sample.actual_quota.usage) * 0.8), 'Actual usable quota binding');
  }
  assert(Number.isSafeInteger(sample.usable_bytes) && sample.usable_bytes >= (start ? 16 : 2) * GiB, 'Origin quota denied');
}
export function admitInitialScaleQuota(initial, packet, receipt) {
  // Preserve the actual observation even when admission rejects it.
  receipt.initial_capacity = {...initial, profile: packet.profile, mode: packet.mode,
    required_usable_bytes: 16 * GiB, usable_formula: initial.capacity_source === 'CDP Storage.getUsageAndQuota'
      ? 'floor((actual_quota.quota-actual_quota.usage)*0.8)' : 'floor(max(0,(quota||0)-(usage||0))*0.8)'};
  assert.equal(initial.origin, packet.origin);
  assert(initial.secure_context && initial.cross_origin_isolated);
  validateScaleQuota(initial, true);
  return initial;
}
export function observeScale(sample, previous, now, lastProgress) {
  validateScaleQuota(sample);
  assert(!sample.error && !['failed', 'cancelled'].includes(sample.status), sample.error || 'Run failed/cancelled');
  const checkpoint = JSON.stringify([sample.status, sample.progress]);
  const advanced = checkpoint !== previous;
  if (advanced) lastProgress = now;
  assert(now - lastProgress < 600_000, 'No useful progress for 600 seconds');
  return {checkpoint, advanced, lastProgress};
}
// Every resource is attempted even if the preceding closer fails or times out.
// Keep primary, sampler, cancellation, browser and server failures independently.
export async function closeScale({watcher, page, context, browser, server}, failures = []) {
  const attempt = async (label, fn) => {
    try {await deadline(Promise.resolve().then(fn), 20_000, label);}
    catch (error) {failures.push({phase: label, error: String(error)});}
  };
  const samplerStop = watcher?.stop();
  if (page && !page.isClosed()) await attempt('Public cancel', () => page.evaluate(async () => {
    await window.scaleAcceptance.cancel();
    const state = await window.scaleAcceptance.sample(false);
    if (state?.error?.includes('cleanup failed')) throw Error(state.error);
  }));
  if (context) await attempt('Context close', () => context.close());
  if (browser) await attempt('Browser close', () => browser.close());
  if (watcher) await attempt('Sampler stop', () => samplerStop);
  if (server) await attempt('Server close', () => new Promise((accept, reject) => {
    server.closeAllConnections(); server.close(error => error ? reject(error) : accept());
  }));
  return failures;
}
async function scaleAssets(packet) {
  const assets = new Map();
  assert(!Object.keys(packet.assets.sha256).some(name => testAssets.includes(name)), 'Test assets denied');
  for (const name of ['engine.wasm', 'engine-worker.js', 'storage-worker.js', 'index.html', 'style.css']) {
    const bytes = await readFile(resolve(packet.assets.root, name));
    assert.equal(sha(bytes), packet.assets.sha256[name]); assets.set('/' + name, bytes);
  }
  assertProductionWasm(assets.get('/engine.wasm'));
  const bridge = await readFile(resolve(packet.harness.root, packet.bundle));
  assert.equal(sha(bridge), packet.harness.sha256[packet.bundle]); assets.set('/bridge.js', bridge);
  const html = assets.get('/index.html').toString('utf8');
  assert.equal(html.split('src="/app.js"').length, 2);
  assets.set('/', Buffer.from(html.replace('src="/app.js"', 'src="/bridge.js"')
    .replace('</body>', '<input id="fixture" type="file" hidden></body>')));
  return assets;
}

function createScaleServer(assets) {
  return http.createServer((request, response) => {
      const bytes = request.method === 'GET' && assets.get(request.url);
      response.writeHead(bytes ? 200 : 404, {'Content-Type': request.url?.endsWith('.wasm') ? 'application/wasm' :
        request.url?.endsWith('.js') ? 'text/javascript' : request.url?.endsWith('.css') ? 'text/css' : 'text/html',
        'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"});
      response.end(bytes || 'Not found');
    });
}

export async function capacityControl(definitionPath, expectedSha256) {
  const raw = await readFile(definitionPath);
  assert(raw.length <= 1024 ** 2 && sha(raw) === expectedSha256, 'Capacity definition binding');
  const definition = JSON.parse(raw), frozen = await readFile(definition.frozen_packet.path);
  assert(frozen.length <= 16 * 1024 ** 2 && sha(frozen) === definition.frozen_packet.sha256, 'Frozen selected packet');
  const packet = JSON.parse(frozen), directory = resolve(definition.root);
  assert.equal(definition.capacity_profile, join(directory, 'browser-profile'));
  assert.equal(definition.origin, packet.origin);
  assert.equal(process.version, packet.toolchains.node_version);
  assert.equal((await json(resolve(packet.harness.root, 'ui/node_modules/playwright/package.json'))).version,
    packet.toolchains.playwright_version, 'Actual Playwright dependency mismatch');
  assert.equal((await streamIdentity(process.execPath)).sha256, packet.node.sha256);
  assert.equal((await streamIdentity(packet.browser.path)).sha256, packet.browser.sha256);
  const assets = await scaleAssets(packet);
  let server, context, browser, page, stopping = false;
  const failures = [], receipt = {status: 'failed', qualification: false, scale_slots: 0,
    mode: 'capacity-only; no File selection, fixture generation or public Run',
    origin: packet.origin, profile: definition.capacity_profile, frozen_packet_sha256: definition.frozen_packet.sha256,
    launch_options: {headless: true, serviceWorkers: 'block', executablePath: packet.browser.path, timeout: 30_000}, failures};
  try {
    await lstat(definition.capacity_profile).then(() => {throw Error('Fresh capacity profile required');},
      error => {if (error.code !== 'ENOENT') throw error;});
    server = createScaleServer(assets);
    await deadline(new Promise((accept, reject) => {
      server.once('error', reject); server.listen(Number(new URL(packet.origin).port), '127.0.0.1', accept);
    }), 10000, 'Capacity origin start');
    const {chromium} = await import(pathToFileURL(resolve(packet.harness.root, 'ui/node_modules/playwright/index.mjs')).href);
    context = await chromium.launchPersistentContext(definition.capacity_profile, receipt.launch_options);
    browser = context.browser();
    browser.on('disconnected', () => {if (!stopping) failures.push({phase: 'disconnect', error: 'Browser disconnected'});});
    await context.route('**/*', route => route.request().url().startsWith(packet.origin + '/') ? route.continue() : route.abort());
    page = context.pages()[0] || await context.newPage(); page.setDefaultTimeout(20_000);
    receipt.actual_browser_version = browser.version();
    assert.equal(receipt.actual_browser_version, packet.browser_version);
    await page.goto(packet.origin + '/', {waitUntil: 'load'});
    await page.waitForFunction(() => !!window.scaleAcceptance && document.getElementById('status')?.textContent === 'IDLE');
    // Execute the current hash-pinned owning page observer in the real frozen
    // production page. The older bridge is not claimed to contain new fields.
    const initial = await observeScaleCapacity(page, context, packet, definition.capacity_profile);
    try {
      admitInitialScaleQuota(initial, {...packet, profile: definition.capacity_profile}, receipt);
      receipt.admission = 'passed';
    } catch (error) {
      if (error.code !== 'ERR_ASSERTION' || error.message !== 'Origin quota denied') throw error;
      receipt.admission = 'denied'; receipt.denial = String(error);
    }
    receipt.status = 'observed-capacity';
  } catch (error) {failures.push({phase: 'capacity-observation', error: String(error)});}
  finally {
    stopping = true;
    await closeScale({page, context, browser, server}, failures);
    receipt.cleanup_complete = failures.length === 0;
    if (failures.length) receipt.status = 'failed';
    await writeFile(join(directory, 'capacity-observation.json'), JSON.stringify(receipt) + '\n', {flag: 'wx'});
  }
  if (failures.length) throw new AggregateError(failures.map(value => Error(value.error)), 'Capacity control failed');
  return receipt;
}

export async function extractCompleted(definitionPath, expectedSha256) {
  const raw = await readFile(definitionPath);
  assert(raw.length <= 1024 ** 2 && sha(raw) === expectedSha256, 'Recovery definition pin');
  const definition = JSON.parse(raw);
  assert.equal(definition.schema, 'browser-scale-export-recovery-v1');
  const bound = async binding => {
    const bytes = await readFile(binding.path);
    assert(bytes.length <= 16 * 1024 ** 2 && sha(bytes) === binding.sha256, 'Original recovery evidence pin');
    return JSON.parse(bytes);
  };
  const packet = await bound(definition.frozen_packet), state = await bound(definition.public_state);
  const failed = await bound(definition.browser_receipt), independent = await bound(definition.independent);
  assert.equal(failed.status, 'failed');assert.equal(independent.status, 'passed-after-exit');
  assert.equal(independent.scale_cell_passed, false);assert.equal(state.status, 'complete');assert.equal(state.error, null);
  assert.equal(failed.profile, packet.profile);assert.equal(failed.origin, packet.origin);
  assert.equal(state.profile, packet.profile);assert.equal(state.origin, packet.origin);
  assert.equal(failed.plan_id, packet.plan_id);assert.equal(failed.actual_browser_version, packet.browser_version);
  assert.equal(failed.packet_sha256, definition.frozen_packet.sha256);
  assert.deepEqual(failed.source, packet.source);assert.deepEqual(failed.browser, packet.browser);
  const spill = observedSpill(state, packet.fixture.rows);
  const copied = await json(definition.profile_copy_receipt);
  assert(copied.status === 'passed' && copied.definition_sha256 === expectedSha256 &&
    copied.source === packet.profile && copied.destination === definition.profile && copied.source_unchanged === true,
    'Matching completed closed-profile copy required');
  assert.equal(process.platform, 'win32');assert.equal(packet.host.os, 'Windows');
  assert.equal(packet.host.node_os_release, release());assert.equal(packet.host.node_os_version, version());
  assert.equal(packet.host.node.toLowerCase(), hostname().toLowerCase());
  assert.equal(packet.host.machine.toLowerCase().replace('amd64', 'x64'), arch());
  assert.equal(sha(await readFile(process.execPath)), packet.node.sha256);
  assert.equal((await streamIdentity(packet.browser.path)).sha256, packet.browser.sha256);
  assert(definition.profile !== packet.profile && Date.now() / 1000 < definition.deadline_unix);
  const assets = await scaleAssets(packet), work = resolve(definition.root, 'work');await mkdir(work);
  const publish = observationPublisher(work), failures = [];
  let context, browser, page, server, watcher, stopping = false;
  const receipt = {status: 'failed', operation: 'read-only completed export extraction; no Run',
    definition_sha256: expectedSha256, packet_sha256: definition.frozen_packet.sha256,
    source: packet.source, channel: packet.channel, shape: packet.shape, browser: packet.browser,
    origin: packet.origin, scale_acceptance: false, original_public_state: definition.public_state,
    original_failed_receipt: definition.browser_receipt, original_independent: definition.independent,
    original_consumed_claim: definition.consumed_claim, product_run_count: 0, new_scale_claims: 0,
    original_profile: packet.profile, copied_profile: definition.profile, output: state.output,
    spill_coverage: spill, failures};
  try {
    server = createScaleServer(assets);
    await deadline(new Promise((accept, reject) => {server.once('error', reject);
      server.listen(Number(new URL(packet.origin).port), '127.0.0.1', accept);}), 10000, 'Recovery origin start');
    const {chromium} = await import(pathToFileURL(resolve(packet.harness.root, 'ui/node_modules/playwright/index.mjs')).href);
    context = await chromium.launchPersistentContext(definition.profile, {executablePath: packet.browser.path,
      headless: true, serviceWorkers: 'block', timeout: 30000});
    browser = context.browser();assert.equal(browser.version(), packet.browser_version);
    receipt.actual_browser_version = browser.version();
    browser.on('disconnected', () => {if (!stopping) failures.push({phase: 'disconnect', error: 'Browser disconnected'});});
    await context.route('**/*', route => route.request().url().startsWith(packet.origin + '/') ? route.continue() : route.abort());
    page = context.pages()[0] || await context.newPage();
    await deadline(page.goto(packet.origin + '/', {waitUntil: 'load'}), 30000, 'Recovery page load');
    await deadline(page.evaluate(installRecoveredExport, state.output), 10000, 'Read-only recorded OPFS binding');
    assert.equal(await page.evaluate(() => typeof window.scaleAcceptance.start), 'undefined', 'Recovery must not expose Run');
    const initial = await observeScaleCapacity(page, context, packet, definition.profile);
    receipt.recovery_initial_capacity=initial;validateScaleQuota(initial,true);await publish('quota', initial);
    watcher = watchQuota(async () => {const value=await observeScaleCapacity(page, context, packet, definition.profile);
      receipt.recovery_last_capacity=value;validateScaleQuota(value);return value;}, value => publish('quota', value), 1000);
    const transport = {async evaluate(...args) {
      assert(!stopping && failures.length === 0 && Date.now() / 1000 < definition.deadline_unix);
      const value = await deadline(page.evaluate(...args), 10000, 'Bounded recovered export read');
      assert(Buffer.byteLength(JSON.stringify(value)) < 1024 ** 2, 'Bounded recovered transfer');return value;
    }};
    const files = await transport.evaluate(() => window.scaleAcceptance.list());
    const marker = files.find(file => file.name === 'CHOPPER-COMPLETE.json');
    assert(marker && marker.size <= 256 && marker.size > 0);
    const encoded = await transport.evaluate(size => window.scaleAcceptance.slice('CHOPPER-COMPLETE.json', 0, size), marker.size);
    validateMarker(JSON.parse(Buffer.from(encoded, 'base64').toString('utf8')), files.length);
    receipt.files = await Promise.race([extract(transport, join(work, packet.shape),
      value => publish('progress', value), {maxBytes: 2 * GiB}), watcher.failure]);
    receipt.status = 'extracted; independent streaming verification pending';
  } catch (error) {failures.push({phase: 'completed-export recovery', error: String(error)});}
  finally {
    stopping = true;
    // This page has no Run; context close needs no public Cancel invocation.
    await closeScale({watcher, context, browser, server}, failures);
    try {await bound(definition.consumed_claim);receipt.original_consumed_claim_unchanged=true;}
    catch (error) {failures.push({phase: 'Original consumed claim pin', error: String(error)});}
    try {await deadline(publish.stop(), 30000, 'Recovery observation join');}
    catch (error) {failures.push({phase: 'observation join', error: String(error)});}
    if (failures.length) receipt.status = 'failed';
    await writeFile(join(work, 'extraction-receipt.json'), JSON.stringify(receipt) + '\n', {flag: 'wx'});
  }
  if (failures.length) throw new AggregateError(failures.map(value => Error(value.phase + ': ' + value.error)), 'Completed-export recovery failed');
}

export async function main(packetPath, directory) {
  directory = await ownedPath(directory);
  const authority = await json(join(directory, 'batch/scale-authority.json'));
  assert.equal(Number(await readFile(join(directory, 'batch/runner.lock'), 'utf8')), process.ppid, 'Live guarded parent required');
  assert.equal(authority.parent_pid, process.ppid);
  assert.equal(process.platform, 'win32', 'Actual Windows owned-process containment required');
  const packet = await json(packetPath), policy = await json(join(directory, 'policy.json'));
  const plan = await json(join(directory, 'plan.json'));
  assert.equal(sha(await readFile(packetPath)), authority.packet_sha256);
  assert.equal(sha(await readFile(join(directory, 'policy.json'))), authority.policy_sha256);
  assert.equal(sha(await readFile(join(directory, 'plan.json'))), authority.plan_sha256);
  assert(['scale', 'qualify'].includes(packet.mode)); assert.equal(packet.runtime, 'browser');
  const qualifying = packet.mode === 'qualify';
  assert.equal(plan.contract, qualifying ? 'browser-scale-tiny-v1' : 'browser-scale-v1');
  assert.equal(process.version, packet.toolchains.node_version, 'Actual Node version mismatch');
  assert.equal((await json(resolve(packet.harness.root, 'ui/node_modules/playwright/package.json'))).version,
    packet.toolchains.playwright_version, 'Actual Playwright dependency mismatch');
  assert.deepEqual(packet.features, []); assert.equal(packet.parent_scheduled, true);
  assert(['chrome', 'msedge'].includes(packet.channel), 'Installed channel required');
  assert.equal(packet.plan_id, authority.plan_id); assert.equal(plan.shape, packet.shape);
  assert.equal(policy.owned_bytes, 24 * GiB); assert.equal(policy.deadline_seconds, 21600);
  assert.equal(sha(await readFile(process.execPath)), packet.node.sha256);
  assert.equal((await streamIdentity(packet.browser.path)).sha256, packet.browser.sha256);
  assert.equal(packet.host.os, 'Windows'); assert.equal(packet.host.node_os_release, release());
  assert.equal(packet.host.node_os_version, version(), 'Actual Node Windows OS version mismatch');
  assert.equal(packet.host.machine.toLowerCase().replace('amd64', 'x64'), arch());
  assert.equal(packet.host.node.toLowerCase(), hostname().toLowerCase());
  const fixtureRoot = join(directory, packet.shape);
  const inputPath = packet.borrowed_input?.path || join(fixtureRoot, 'input.csv');
  const fixture = await json(join(fixtureRoot, 'fixture.json'));
  validateScaleFixture(fixture, packet);
  assert.deepEqual(await streamIdentity(inputPath),
    {sha256: fixture.sha256, bytes: fixture.bytes, rows: fixture.rows}, 'Actual input hash/count mismatch before Run');
  const job = await json(join(fixtureRoot, 'job.json'));
  assert.deepEqual(job, plan.job, 'Immutable exact recipe mismatch');
  assert.equal(packet.profile, join(directory, 'work/profile'));
  const assets = await scaleAssets(packet);
  const work = join(directory, 'work');
  await mkdir(work);
  const atomic = async (name, value) => {
    await writeFile(join(work, name + '.tmp'), JSON.stringify(value) + '\n');
    await rename(join(work, name + '.tmp'), join(work, name));
  };
  const publish = observationPublisher(work);
  let context, browser, page, server, watcher, stopping = false;
  const failures = [], receipt = {status: 'failed', packet_sha256: authority.packet_sha256,
    plan_id: packet.plan_id, shape: packet.shape, channel: packet.channel, source: packet.source,
    browser: packet.browser, profile: packet.profile, origin: packet.origin, os_release: release(), os_version: version(),
    node_version: process.version, failures, spill_coverage: 'unmet unless actual complete graph facts demonstrate spilling',
    peer_coverage: packet.peer ? 'pending independent same-input verifier comparison' : 'unmet: no same-size seeded peer supplied',
    coverage: 'injected File/OPFS client bridge; no real dialog/external filesystem or served app.js claim'};
  try {
    assert(Date.now() / 1000 < authority.channel_deadline_unix, 'Channel deadline');
    server = createScaleServer(assets);
    await deadline(new Promise((accept, reject) => {
      server.once('error', reject); server.listen(Number(new URL(packet.origin).port), '127.0.0.1', accept);
    }), 10_000, 'Server start');
    // Pin the installed executable directly. No dependency on parallel #121 changes.
    const {chromium} = await import('../../ui/node_modules/playwright/index.mjs');
    context = await chromium.launchPersistentContext(packet.profile, {executablePath: packet.browser.path,
      headless: true, serviceWorkers: 'block', timeout: 30_000});
    browser = context.browser();
    receipt.actual_browser_version = browser.version();
    assert.equal(receipt.actual_browser_version, packet.browser_version, 'Running browser version mismatch');
    browser.on('disconnected', () => {if (!stopping) failures.push({phase: 'disconnect', error: 'Browser disconnected'});});
    await context.route('**/*', route => route.request().url().startsWith(packet.origin + '/') ? route.continue() : route.abort());
    page = context.pages()[0] || await context.newPage(); page.setDefaultTimeout(20_000);
    await page.goto(packet.origin + '/', {waitUntil: 'load'});
    await page.waitForFunction(() => !!window.scaleAcceptance && document.getElementById('status')?.textContent === 'IDLE');
    await page.locator('#fixture').setInputFiles(inputPath);
    let completedCapacity;
    const sample = async () => {
      assert(!stopping && failures.length === 0, 'Stopped/disconnected');
      assert(Date.now() / 1000 < authority.channel_deadline_unix, 'Channel deadline');
      const state = await deadline(page.evaluate(() => window.scaleAcceptance.sample(false)), 4000, 'State sampler');
      return {...state, ...completedCapacity}; // Retain the actual capacity observation's oldest start.
    };
    const quota = async () => {
      const value = await observeScaleCapacity(page, context, packet, packet.profile);
      validateScaleQuota(value); completedCapacity = value; return value;
    };
    const initial = await observeScaleCapacity(page, context, packet, packet.profile);
    admitInitialScaleQuota(initial, packet, receipt); completedCapacity = initial;
    await publish('quota', initial);
    watcher = watchQuota(async () => {const value = await quota(); validateScaleQuota(value); return value;},
      value => publish('quota', value), 1000);
    const execute = async () => {
      // Exactly one public Run; a failure never selects another shape or retries.
      await deadline(page.evaluate(job => window.scaleAcceptance.start(job), job), 30_000, 'Public Run start');
      let previous, lastProgress = Date.now(), current;
      do {
        current = await sample();
        const observation = observeScale(current, previous, Date.now(), lastProgress);
        previous = observation.checkpoint; lastProgress = observation.lastProgress;
        await atomic('latest-sample.json', current);
        if (observation.advanced) await publish('progress', {checkpoint: previous});
        if (current.status !== 'complete') await new Promise(accept => setTimeout(accept, 1000));
      } while (current.status !== 'complete');
      await atomic('public-state.json', current); // Actual graph retained; absence is not a spill pass.
      if (!qualifying && packet.shape === 'G') {
        receipt.spill_coverage = observedSpill(current, fixture.rows);
      }
      const transport = {async evaluate(...args) {
        assert(!stopping);
        const value = await deadline(page.evaluate(...args), 10_000, 'Bounded export');
        assert(Buffer.byteLength(JSON.stringify(value)) < 1024 ** 2, 'Encoded transfer must be below 1 MiB');
        return value;
      }};
      receipt.files = await extract(transport, join(work, packet.shape), checkpoint => publish('progress', checkpoint),
        {maxBytes: 2 * GiB}); // Exact CSV caps/conservation checked by independent streaming verifier.
      if (qualifying) receipt.controlled_failure = await qualifyFailure(page, job, sample, atomic);
      if (qualifying) receipt.scale_acceptance = false;
      receipt.status = 'extracted; independent verification still required';
    };
    await Promise.race([deadline(execute(), 5400_000, 'Run/extraction'), watcher.failure]);
  } catch (error) {failures.push({phase: 'execution', error: String(error)});}
  finally {
    stopping = true;
    await closeScale({watcher, page, context, browser, server}, failures);
    try {await deadline(publish.stop(), 30_000, 'Observation publication join');}
    catch (error) {failures.push({phase: 'observation publication', error: String(error)});}
    if (failures.length) receipt.status = 'failed';
    await atomic('browser-receipt.json', receipt);
  }
  if (failures.length) throw new AggregateError(failures.map(f => Error(f.phase + ': ' + f.error)), 'Scale attempt failed');
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === '--extract-completed') await extractCompleted(process.argv[3], process.argv[4]);
  else if (process.argv[2] === '--capacity-control') await capacityControl(process.argv[3], process.argv[4]);
  else await main(process.argv[2], process.argv[3]);
}
