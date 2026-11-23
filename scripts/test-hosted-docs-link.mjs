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
  const docs = page.getByRole('region', { name: 'Appearance and project links' })
    .getByRole('link', { name: 'Docs', exact: true });
  await docs.waitFor();
  assert.equal(await docs.getAttribute('href'), target);

  if (['localhost', '127.0.0.1'].includes(app.hostname)) {
    const files = await readdir(new URL('../ui/dist/', import.meta.url));
    assert.deepEqual(files.sort(), [
      '_headers', 'app.js', 'engine-worker.js', 'engine.wasm',
      'index.html', 'storage-worker.js', 'style.css',
    ]);
  } else if (docsOrigin) {
    await docs.click();
    await page.waitForURL(target);
    await page.locator('h1#user-guide').waitFor();
  }
  console.log(`Hosted app Docs link targets ${target}`);
} finally {
  await browser.close();
}
