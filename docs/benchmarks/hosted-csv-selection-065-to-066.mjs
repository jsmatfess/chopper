// Replay input selection using both complete production app bundles.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {appendFile, readFile} from 'node:fs/promises';
import {readlinkSync} from 'node:fs';
import http from 'node:http';
import {release} from 'node:os';
import {extname, join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const [before, after, out] = process.argv.slice(2);
const arms = {baseline: resolve(before), candidate: resolve(after)};
const {chromium} = await import(pathToFileURL(resolve('ui/node_modules/playwright/index.mjs')));
const names = ['_headers', 'app.js', 'engine-worker.js', 'engine.wasm', 'index.html', 'storage-worker.js', 'style.css'];
const types = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.wasm': 'application/wasm'};
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const note = async record => appendFile(out, JSON.stringify(record)+'\n');
const assets = {};
for (const [arm, directory] of Object.entries(arms)) {
  assets[arm] = Object.fromEntries(await Promise.all(names.map(async name => [name, await readFile(join(directory, name))])));
}

let selected;
const server = http.createServer((request, response) => {
  const name = request.url === '/' ? 'index.html' : request.url.slice(1);
  if (request.method !== 'GET' || !types[extname(name)] || !Object.hasOwn(assets[selected], name)) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    'Content-Type': types[extname(name)],
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Embedder-Policy': 'require-corp',
    'Cache-Control': 'no-store',
  }).end(assets[selected][name]);
});

let browser;
try {
  await new Promise((ok, fail) => { server.once('error', fail); server.listen(0, '127.0.0.1', ok); });
  browser = await chromium.launch();
  const cdp = await browser.newBrowserCDPSession();
  const {id} = (await cdp.send('SystemInfo.getProcessInfo')).processInfo.find(process => process.type === 'browser');
  const executable = readlinkSync('/proc/'+id+'/exe');
  await cdp.detach();
  await note({
    kind: 'environment', kernel: release(), chromium: browser.version(), node: process.version,
    executable_sha256: sha(await readFile(executable)),
    asset_sha256: Object.fromEntries(Object.entries(assets).map(([arm, files]) =>
      [arm, Object.fromEntries(names.map(name => [name, sha(files[name])]))])),
    timing_boundary: 'Browse click through preview DOM update, after worker initialization',
    scope: 'Synthetic File handle, fresh page and browser context per trial',
  });

  for (const rows of [64, 12000]) {
    const text = 'id,note\n'+Array.from({length: rows}, (_, i) => `${i},${'x'.repeat(40)}\n`).join('');
    const expected = Array.from({length: 8}, (_, i) => [String(i), 'x'.repeat(40)]);
    await note({kind: 'fixture', rows, bytes: Buffer.byteLength(text), sha256: sha(text)});
    for (let pair = -1; pair < 8; pair++) {
      for (const arm of (pair % 2 === 0 ? ['baseline', 'candidate'] : ['candidate', 'baseline'])) {
        selected = arm;
        const page = await browser.newPage();
        try {
          await page.addInitScript(source => {
            const file = new File([source], 'fixture.csv', {type: 'text/csv'});
            window.showOpenFilePicker = async () => [{getFile: async () => file}];
          }, text);
          await page.goto('http://127.0.0.1:'+server.address().port);
          await page.waitForFunction(() => document.querySelector('#status')?.textContent === 'IDLE');
          const result = await page.evaluate(() => new Promise((resolve, reject) => {
            const preview = document.querySelector('#preview');
            const started = performance.now();
            const observer = new MutationObserver(() => {
              const rows = [...preview.querySelectorAll('tbody tr')].map(row => [...row.cells].map(cell => cell.textContent));
              if (rows.length !== 8) return;
              clearTimeout(timeout);
              observer.disconnect();
              resolve({seconds: (performance.now()-started)/1000, rows,
                header: [...preview.querySelectorAll('th')].map(cell => cell.textContent)});
            });
            const timeout = setTimeout(() => { observer.disconnect(); reject(new Error('Preview timed out')); }, 10000);
            observer.observe(preview, {childList: true, subtree: true});
            document.querySelector('#browse-input').click();
          }));
          assert.deepEqual(result.header, ['id', 'note']);
          assert.deepEqual(result.rows, expected);
          await note({kind: 'measurement', rows, pair, variant: arm, seconds: result.seconds, preview_verified: true});
        } catch (error) {
          await note({kind: 'failure', rows, pair, variant: arm, message: String(error)});
          throw error;
        } finally {
          await page.context().close();
        }
      }
    }
  }
} finally {
  await browser?.close();
  server.closeAllConnections();
  if (server.listening) await new Promise(ok => server.close(ok));
}
