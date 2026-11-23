import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { chromium } from '../ui/node_modules/playwright/index.mjs';

const [appOrigin, docsOrigin] = process.argv.slice(2);
if (!appOrigin) throw new Error('Usage: node scripts/test-hosted-docs-link.mjs APP_ORIGIN [DOCS_ORIGIN]');
const version = JSON.parse(await readFile(new URL('../ui/package.json', import.meta.url))).version;
const target = docsOrigin
  ? new URL(`/versions/${version}/`, docsOrigin).href
  : 'https://github.com/jsmatfess/chopper/blob/main/docs/user/README.md';

const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  const app = new URL(appOrigin);
  assert.equal((await page.goto(app.href))?.status(), 200);
  const help = page.getByRole('navigation', { name: 'Chopper help' });
  const docs = help.getByRole('link', { name: 'Docs (opens in a new tab)', exact: true });
  const sample = help.getByRole('link', { name: 'Try a sample (opens in a new tab)', exact: true });
  await docs.waitFor();
  assert.equal(await docs.getAttribute('href'), target);
  assert.equal(await sample.getAttribute('href'), docsOrigin
    ? new URL('browser#try-a-sample-export', target).href
    : 'https://github.com/jsmatfess/chopper/blob/main/docs/browser.md#try-a-sample-export');

  if (['localhost', '127.0.0.1'].includes(app.hostname)) {
    const files = await readdir(new URL('../ui/dist/', import.meta.url));
    assert.deepEqual(files.sort(), [
      '_headers', 'app.js', 'engine-worker.js', 'engine.wasm',
      'index.html', 'storage-worker.js', 'style.css',
    ]);
  } else if (docsOrigin) {
    for (const [link, heading] of [[docs, 'h1#user-guide'], [sample, 'h2#try-a-sample-export']]) {
      const popup = page.waitForEvent('popup');
      await link.click();
      const opened = await popup;
      await opened.waitForURL(await link.getAttribute('href'));
      await opened.locator(heading).waitFor();
      await opened.close();
    }
    assert.equal(page.url(), app.href);
  }
  console.log(`Hosted app Docs link targets ${target}`);
} finally {
  await browser.close();
}
