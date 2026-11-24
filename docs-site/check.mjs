import { readFile, readdir, stat } from 'node:fs/promises';
import { join, relative, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parse } from 'parse5';

export function* elements(node) {
  if (node.tagName) yield node;
  for (const child of node.childNodes ?? []) yield* elements(child);
}

export function attr(element, name) {
  return element.attrs.find(attribute => attribute.name === name)?.value;
}

export async function checkSite(root) {
  const manifest = JSON.parse(await readFile(join(root, 'versions.json')));
  const files = await readdir(root, { recursive: true });
  const html = new Map();
  for (const path of files.filter(path => path.endsWith('.html'))) {
    html.set(path, [...elements(parse(await readFile(join(root, path), 'utf8')))]);
  }

  const expected = new Set(['index.html']);
  for (const { version, additionalPages = [] } of manifest.versions) {
    const base = `versions/${version}/`;
    for (const page of [...manifest.pages, ...additionalPages]) expected.add(`${base}${page}.html`);
    const assets = files.filter(path => path.startsWith(`${base}assets/`));
    if (!assets.some(path => path.includes('@localSearchIndex') && path.endsWith('.js'))) {
      throw new Error(`Missing local search index for ${version}`);
    }
  }
  expected.forEach(path => {
    if (!html.has(path)) throw new Error(`Missing docs page: ${path}`);
  });

  const origin = 'https://docs.invalid';
  const failures = [];
  for (const [path, nodes] of html) {
    if (!expected.has(path) && !/(^|\/)404\.html$/.test(path)) throw new Error(`Unexpected docs page: ${path}`);
    for (const node of nodes) {
      for (const name of ['href', 'src']) {
        const value = attr(node, name);
        if (!value) continue;
        const url = new URL(value, `${origin}/${path}`);
        if (url.origin !== origin) continue;

        const pathname = decodeURIComponent(url.pathname.slice(1));
        const target = pathname.endsWith('/') || !pathname ? pathname + 'index.html' : pathname;
        const page = html.get(target) ?? html.get(target + '.html');
        const anchor = decodeURIComponent(url.hash.slice(1));
        if (page && (!anchor || page.some(element => attr(element, 'id') === anchor))) continue;
        if (!page && !anchor && files.includes(target) && (await stat(join(root, target))).isFile()) continue;
        failures.push(`${path}: ${value}`);
      }
    }
  }
  if (failures.length) throw new Error(`Broken documentation links:\n${failures.join('\n')}`);
  console.log(`Checked ${expected.size} operator pages and ${manifest.versions.length} local search indexes in ${relative(process.cwd(), root)}`);
}

if (import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await checkSite(resolve(process.argv[2]));
}
