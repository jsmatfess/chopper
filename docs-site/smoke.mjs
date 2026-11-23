import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname } from 'node:path';
import { chromium } from 'playwright';

const [live, expectedCommit] = process.argv.slice(2);
const types = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css',
  '.js': 'text/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
};
let server;
let browser;
try {
  if (!live) {
    server = createServer(async (request, response) => {
      const path = new URL(request.url, 'http://localhost').pathname;
      if (path.includes('..')) return response.writeHead(400).end();
      const file = path.endsWith('/') ? path + 'index.html' : extname(path) ? path : path + '.html';
      try {
        const body = await readFile(new URL('./dist' + file, import.meta.url));
        response.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream' }).end(body);
      } catch {
        response.writeHead(404).end();
      }
    }).listen(0, '127.0.0.1');
    await new Promise((resolve, reject) => server.once('listening', resolve).once('error', reject));
  }
  const origin = live ? new URL(live).origin : `http://127.0.0.1:${server.address().port}`;
  const response = await fetch(origin + '/versions.json');
  assert.equal(response.status, 200);
  const { latest, versions } = await response.json();
  assert.ok(versions.length);
  assert.equal(latest, versions[0].version);
  if (expectedCommit) assert.equal(versions.find(({ version }) => version === '0.5.0')?.commit, expectedCommit);

  browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  assert.equal((await page.goto(origin))?.status(), 200);
  const support = page.getByRole('link', { name: 'Buy me a coffee', exact: true });
  assert.equal(await support.getAttribute('href'), 'https://buymeacoffee.com/tblflip');
  assert.equal(await page.getByRole('link', { name: /Latest stable release/ }).getAttribute('href'), `/versions/${latest}/`);
  await page.getByRole('link', { name: latest, exact: true }).waitFor();
  for (const { version, commit } of versions) {
    const base = `/versions/${version}/`;
    assert.match(commit, /^[0-9a-f]{40}$/);
    assert.equal((await page.goto(origin + base))?.status(), 200);
    await page.locator('h1#user-guide').waitFor();
    assert.equal(await support.getAttribute('href'), 'https://buymeacoffee.com/tblflip');
    await page.getByRole('link', { name: 'All versions' }).click();
    await page.waitForURL(origin + '/');
    assert.equal((await page.goto(origin + base + 'cli-reference#chopper-run'))?.status(), 200);
    await page.locator('h2#chopper-run').waitFor();
    await page.getByRole('rowheader', { name: '--analysis <analysis>', exact: true }).waitFor();
    const lineEnding = page.getByRole('rowheader', { name: '--output-line-ending <output-line-ending>', exact: true });
    assert.deepEqual(await lineEnding.locator('..').locator('.cli-choices code').allTextContents(), ['lf', 'crlf']);
    const runHelp = page.locator('details').filter({ hasText: 'Usage: chopper run [OPTIONS]' });
    await runHelp.locator('summary').press('Enter');
    assert.equal(await runHelp.getAttribute('open'), '');
    assert.equal((await page.goto(origin + base + 'browser#checking-a-hosted-export-after-interruption'))?.status(), 200);
    await page.locator('h2#checking-a-hosted-export-after-interruption').waitFor();
    const sidebar = page.locator('#VPSidebarNav');
    const picker = sidebar.getByRole('link', { name: 'Choosing an output folder', exact: true });
    const browserGuide = sidebar.getByRole('link', { name: 'Browser exports', exact: true });
    const quickstart = sidebar.getByRole('link', { name: 'Native quickstart', exact: true });
    const linux = sidebar.getByRole('link', { name: 'Linux shell', exact: true });
    const browserToggle = browserGuide.locator('..').getByRole('button', { name: 'toggle section' });
    const quickstartToggle = quickstart.locator('..').getByRole('button', { name: 'toggle section' });
    await picker.waitFor();
    await linux.waitFor({ state: 'hidden' });
    await browserToggle.press('Enter');
    await picker.waitFor({ state: 'hidden' });
    await browserToggle.press('Enter');
    await picker.waitFor();
    await quickstartToggle.click();
    await linux.waitFor();
    await quickstartToggle.click();
    await linux.waitFor({ state: 'hidden' });
    await picker.press('Enter');
    await page.waitForURL(origin + base + 'browser#choosing-an-output-folder');
    await quickstart.click();
    await page.waitForURL(origin + base + 'quickstart');
    await linux.waitFor();
    await picker.waitFor({ state: 'hidden' });
    await page.goBack();
    await picker.waitFor();
    await linux.waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Search' }).first().click();
    await page.getByRole('searchbox').fill('CHOPPER-COMPLETE');
    const result = page.locator(`#localsearch-list a[href^="${base}browser"]`).first();
    await result.waitFor();
    await result.click();
    await page.waitForURL(url => url.pathname === base + 'browser' && url.hash.length > 1);
    console.log(`Verified ${version} landing, version navigation, sidebar anchors, deep link and search at ${origin}`);
  }
  if (live) {
    const alias = await fetch(origin + '/latest', { redirect: 'manual' });
    assert.equal(alias.status, 302);
    assert.equal(new URL(alias.headers.get('location'), origin).pathname, `/versions/${latest}/`);
  }
} finally {
  await browser?.close();
  server?.close();
}
