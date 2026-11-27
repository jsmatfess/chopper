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
  '.csv': 'text/csv; charset=utf-8',
};

async function checkLibraryLanguage(browser, origin, base) {
  const url = origin + base + 'libraries';
  const anchor = '#compose-inspect-and-replay';
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  try {
    const picker = page.getByRole('combobox', { name: 'Example language' });
    const examples = language => page.locator(`[data-library-example="${language}"]`);
    async function checkLanguage(language, other) {
      await picker.waitFor();
      assert.equal(await picker.inputValue(), language.toLowerCase());
      assert.ok(await examples(language.toLowerCase()).count() > 0);
      assert.equal(
        await examples(language.toLowerCase()).filter({ visible: true }).count(),
        await examples(language.toLowerCase()).count(),
      );
      assert.equal(await examples(other.toLowerCase()).filter({ visible: true }).count(), 0);
    }

    assert.equal((await page.goto(url + '?lang=python' + anchor))?.status(), 200);
    await checkLanguage('Python', 'Rust');
    await page.locator('h1#chopper-libraries').waitFor();
    await page.waitForFunction(id => {
      const heading = document.getElementById(id).getBoundingClientRect();
      return heading.top >= 0 && heading.bottom <= window.innerHeight;
    }, anchor.slice(1));
    await picker.press('ArrowUp');
    await page.waitForURL(url + '?lang=rust' + anchor);
    await checkLanguage('Rust', 'Python');
    await page.reload();
    await checkLanguage('Rust', 'Python');
    await page.goto(url + '#python');
    await checkLanguage('Python', 'Rust');
    await page.goto(url);
    await checkLanguage('Python', 'Rust');

    await page.getByRole('button', { name: 'Search' }).first().click();
    await page.getByRole('searchbox').fill('ExecutionControl');
    await page.locator(`#localsearch-list a[href^="${base}libraries"]`).first().click();
    await page.waitForURL(target => target.pathname === base + 'libraries' && target.hash.length > 1);
    await checkLanguage('Python', 'Rust');
  } finally {
    await page.close();
  }

  const fallback = await browser.newPage({ javaScriptEnabled: false });
  try {
    await fallback.goto(url);
    for (const language of ['rust', 'python']) {
      await fallback.locator(`[data-library-example="${language}"]`).first().waitFor();
    }
    assert.equal(await fallback.getByRole('combobox', { name: 'Example language' }).count(), 0);
  } finally {
    await fallback.close();
  }
}

async function checkSplitLibraryGuides(browser, origin, base) {
  const index = origin + base + 'libraries';
  const languages = ['Rust', 'Python'];
  const url = language => index + '-' + language.toLowerCase();
  const compose = '#compose-inspect-and-replay';
  const detect = '#detect-a-dialect-and-list-columns';
  const firstJob = '#run-your-first-job';
  const calculatedColumns = '#add-calculated-columns';
  const nav = page => page.getByRole('navigation', { name: 'Library guides', exact: true });
  const link = (page, language) => nav(page).getByRole('link', { name: new RegExp(`\\b${language}\\b`) });
  const guide = page => page.locator('.vp-doc');
  const heading = (page, language) => guide(page).getByRole('heading', {
    level: 1, name: new RegExp(`^Chopper for ${language}\\b`),
  });
  const install = {
    Rust: /chopper-csv\s*=|cargo add chopper-csv/,
    Python: /pip install chopper-csv/,
  };
  const sections = {
    'inspect-an-input': { Rust: /\bInputReport\b/, Python: /\biter_columns\b/ },
    'add-calculated-columns': { Rust: /\.alias\(/, Python: /\bcalculated_columns\s+mapping\b/ },
    'stream-published-output-metadata': { Rust: /\breport\.outputs\(/, Python: /\bopen_manifest\b/ },
    'observe-and-cancel-a-run': { Rust: /\bcloned control\b/, Python: /\bcontrol object\b/ },
  };

  async function checkNav(page, current) {
    await nav(page).waitFor();
    for (const language of languages) {
      const item = link(page, language);
      const href = await item.getAttribute('href');
      assert.equal(new URL(href, page.url()).pathname, new URL(url(language)).pathname);
      assert.equal(await item.getAttribute('aria-current') === 'page', language === current);
    }
  }

  async function checkFragment(page, destination) {
    await page.waitForURL(destination);
    await page.waitForFunction(id => {
      const box = document.getElementById(id)?.getBoundingClientRect();
      return box && box.top >= 0 && box.bottom <= window.innerHeight;
    }, new URL(destination).hash.slice(1));
  }

  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(10_000);
  try {
    assert.equal((await page.goto(index))?.status(), 200);
    await checkNav(page);
    await link(page, 'Python').click();
    await page.waitForURL(url('Python'));
    await heading(page, 'Python').waitFor();
    await page.goBack();
    await page.waitForURL(index);
    await checkNav(page);

    for (const language of languages) {
      const other = language === 'Rust' ? 'Python' : 'Rust';
      const destination = url(language);
      assert.equal((await page.goto(destination + compose))?.status(), 200);
      await checkFragment(page, destination + compose);
      await heading(page, language).waitFor();
      await checkNav(page, language);
      const body = guide(page);
      const text = await body.innerText();
      assert.match(text, install[language]);
      assert.doesNotMatch(text, install[other]);
      const guideText = await body.evaluate(article => {
        const content = article.cloneNode(true);
        content.querySelectorAll('nav, pre').forEach(node => node.remove());
        return content.textContent;
      });
      assert.doesNotMatch(guideText, new RegExp(`\\b${other}\\b`, 'i'));
      await body.locator(`.language-${language.toLowerCase()} pre`).first().waitFor();
      assert.equal(await body.locator(`.language-${other.toLowerCase()} pre`).count(), 0);

      for (const [id, terminology] of Object.entries(sections)) {
        const prose = await body.locator(`#${id}`).evaluate(section => {
          const paragraphs = [];
          for (let node = section.nextElementSibling; node; node = node.nextElementSibling) {
            if (/^H[1-6]$/.test(node.tagName) && node.tagName <= section.tagName) break;
            if (node.tagName === 'P') paragraphs.push(node.textContent);
          }
          return paragraphs.join('\n');
        });
        assert.match(prose, terminology[language], `${language} prose at #${id}`);
        assert.doesNotMatch(prose, terminology[other], `${other} prose leaked into ${language} #${id}`);
      }

      await page.getByRole('button', { name: 'Search' }).first().click();
      await page.getByRole('searchbox').fill(language === 'Rust' ? 'InputReport' : 'open_manifest');
      const route = new URL(destination).pathname;
      await page.locator(`#localsearch-list a[href^="${route}#"]`).first().click();
      await page.waitForURL(target => target.pathname === route && target.hash.length > 1);
    }

    for (const fragment of [compose, detect]) {
      await page.goto(url('Rust') + fragment);
      const sectionLink = link(page, 'Python').and(page.locator(`a[href$="${fragment}"]`));
      await sectionLink.waitFor();
      await sectionLink.click();
      await checkFragment(page, url('Python') + fragment);
      await page.goBack();
      await page.waitForURL(url('Rust') + fragment);
      await heading(page, 'Rust').waitFor();
    }

    await page.goto(url('Rust') + compose);
    await checkFragment(page, url('Rust') + compose);
    await page.getByRole('button', { name: 'Search' }).first().click();
    const search = page.getByRole('searchbox');
    await search.fill('InputReport');
    const result = `${base}libraries-rust${detect}`;
    await page.locator(`#localsearch-list [aria-selected="true"] a[href="${result}"]`).waitFor();
    await search.press('Enter');
    await checkFragment(page, url('Rust') + detect);
    const pythonGuide = link(page, 'Python');
    await pythonGuide.focus();
    await pythonGuide.and(page.locator(`a[href$="${detect}"]`)).click();
    await checkFragment(page, url('Python') + detect);

    for (const language of languages) {
      const slug = language.toLowerCase();
      for (const [legacy, anchor] of [[`?lang=${slug}${compose}`, compose], [`#${slug}`, firstJob]]) {
        await page.goto(index + legacy, { waitUntil: 'commit' });
        await checkFragment(page, url(language) + anchor);
      }
    }
    await page.goto(index + '?lang=python#compose%2Dinspect%2Dand%2Dreplay', { waitUntil: 'commit' });
    await checkFragment(page, url('Python') + compose);
    await page.goto(index + '#py%74hon', { waitUntil: 'commit' });
    await checkFragment(page, url('Python') + firstJob);

    await page.goto(index);
    await page.getByRole('button', { name: 'Search' }).first().click();
    await search.waitFor();
    await search.press('Escape');
    await search.waitFor({ state: 'hidden' });
    await page.evaluate(() => { window.location.hash = '#python'; });
    await checkFragment(page, url('Python') + firstJob);
  } finally {
    await page.close();
  }

  const fallback = await browser.newPage({ javaScriptEnabled: false });
  fallback.setDefaultTimeout(10_000);
  try {
    await fallback.goto(index);
    for (const language of languages) {
      await link(fallback, language).click();
      await fallback.waitForURL(url(language));
      await heading(fallback, language).waitFor();
      await checkNav(fallback, language);
      await guide(fallback).locator(`.language-${language.toLowerCase()} pre`).first().waitFor();
    }
    for (const language of languages) {
      assert.equal((await fallback.goto(origin + base + 'formula-functions'))?.status(), 200);
      const examples = guide(fallback).getByRole('link', { name: `${language} examples`, exact: true });
      const destination = url(language) + calculatedColumns;
      await examples.first().waitFor();
      for (const href of await examples.evaluateAll(anchors => anchors.map(anchor => anchor.href))) {
        assert.equal(href, destination);
      }
      await examples.first().click();
      await fallback.waitForURL(destination);
      await heading(fallback, language).waitFor();
      await guide(fallback).locator(calculatedColumns).waitFor();
    }
  } finally {
    await fallback.close();
  }
}

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
  if (expectedCommit) assert.equal(versions[0].commit, expectedCommit);

  browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(10_000);
  assert.equal((await page.goto(origin))?.status(), 200);
  const support = page.getByRole('link', { name: 'Buy me a coffee', exact: true });
  assert.equal(await support.getAttribute('href'), 'https://buymeacoffee.com/tblflip');
  assert.equal(await page.getByRole('link', { name: /Latest stable release/ }).getAttribute('href'), `/versions/${latest}/`);
  await page.getByRole('link', { name: latest, exact: true }).waitFor();
  for (const { version, commit, additionalPages = [] } of versions) {
    const base = `/versions/${version}/`;
    assert.match(commit, /^[0-9a-f]{40}$/);
    assert.equal((await page.goto(origin + base))?.status(), 200);
    await page.locator('h1#user-guide').waitFor();
    assert.equal(await support.getAttribute('href'), 'https://buymeacoffee.com/tblflip');
    const guide = page.locator('.vp-doc');
    for (const [name, anchor] of [
      ['Keep each upload under a limit', 'make-upload-sized-chunks'],
      ['Make exactly N files', 'make-exactly-n-files'],
      ['Make one set per country', 'partition-by-a-business-column'],
    ]) {
      assert.equal(await guide.getByRole('link', { name }).evaluate(link => link.href),
        origin + base + 'job-recipes#' + anchor);
    }
    await guide.getByRole('link', { name: 'Try a sample export' }).click();
    await page.waitForURL(origin + base + 'browser#try-a-sample-export');
    const sample = guide.getByRole('link', { name: 'Download the sample customers.csv' });
    assert.equal(await sample.evaluate(link => link.href), origin + base + 'customers.csv');
    const pendingDownload = page.waitForEvent('download');
    await sample.press('Enter');
    const download = await pendingDownload;
    assert.equal(download.suggestedFilename(), 'customers.csv');
    assert.equal(await download.failure(), null);
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
    if (additionalPages.includes('formula-functions')) {
      await sidebar.getByRole('link', { name: 'Formula functions', exact: true }).click();
      await page.waitForURL(origin + base + 'formula-functions');
      await page.locator('h1#formula-functions').waitFor();
      await guide.getByText('CONCAT_WS(separator, text, ..., ignore_null?, ignore_empty?)', { exact: true }).waitFor();
      await sidebar.getByRole('link', { name: 'CLI reference', exact: true }).click();
      await page.waitForURL(origin + base + 'cli-reference');
      assert.equal(await guide.getByRole('link', { name: 'formula functions', exact: true })
        .evaluate(link => link.href), origin + base + 'formula-functions');
      await page.getByRole('button', { name: 'Search' }).first().click();
      await page.getByRole('searchbox').fill('REGEX_EXTRACT');
      const formulaResult = page.locator(`#localsearch-list a[href^="${base}formula-functions"]`).first();
      await formulaResult.click();
      await page.waitForURL(url => url.pathname === base + 'formula-functions' && url.hash.length > 1);
    }
    const splitGuides = ['libraries-rust', 'libraries-python'];
    if (splitGuides.some(guide => additionalPages.includes(guide))) {
      for (const route of ['libraries', ...splitGuides]) {
        assert.ok(additionalPages.includes(route), `Missing ${route} in ${version} additionalPages`);
      }
      await checkSplitLibraryGuides(browser, origin, base);
      console.log(`Verified ${version} Rust and Python guides, navigation, deep links, and search`);
    } else if (additionalPages.includes('libraries')) {
      await checkLibraryLanguage(browser, origin, base);
      console.log(`Verified ${version} library language choice, deep links, keyboard use, and search`);
    }
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
