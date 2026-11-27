import { execFileSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, createMarkdownRenderer, disposeMdItInstance } from 'vitepress';
import { checkSite } from './check.mjs';
import { renderCliReference } from './cli-reference.mjs';
import { languagePagesMarker, renderLanguageGuide, renderLibraryGuide, renderLibraryIndex } from './library-guide.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const out = fileURLToPath(new URL('./dist', import.meta.url));
const repo = 'https://github.com/jsmatfess/chopper';
const versions = process.argv.slice(2);
const stable = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
if (!versions.length || versions.some(arg => !stable.test(arg.split('=')[0]))) {
  throw new Error('Usage: npm run build -- VERSION[=GIT_REF] [VERSION[=GIT_REF] ...]');
}

// Only these operator pages and assets can enter the publication.
const pages = [
  ['docs/user/README.md', 'index', 'User guide'],
  ['README.md', 'quickstart', 'Native quickstart'],
  ['docs/browser.md', 'browser', 'Browser exports'],
  ['docs/cli-reference.md', 'cli-reference', 'CLI reference'],
  ['docs/job-json.md', 'job-json', 'Job JSON'],
  ['docs/job-recipes.md', 'job-recipes', 'Job recipes'],
  ['docs/validate-cli.md', 'validate-cli', 'Validate'],
  ['docs/run-cli.md', 'run-cli', 'Run and automation'],
  ['docs/native-manifest.md', 'native-manifest', 'Native manifest'],
  ['docs/operator-support.md', 'operator-support', 'Operator support'],
  ['docs/compatibility.md', 'compatibility', 'Compatibility and migration'],
];
const formulaPage = ['docs/formula-functions.md', 'formula-functions', 'Formula functions'];
const libraryPage = ['docs/user/libraries.md', 'libraries', 'Libraries'];
const languagePages = [
  [libraryPage[0], 'libraries-rust', 'Rust'],
  [libraryPage[0], 'libraries-python', 'Python'],
];
const imagePath = 'docs/images/workbench.png';
const samplePath = 'examples/customers.csv';
const supportUrl = 'https://buymeacoffee.com/tblflip';
const stylesheet = fileURLToPath(new URL('./chopper.css', import.meta.url));
const git = (...args) => execFileSync('git', args, { cwd: root, maxBuffer: 5 * 1024 * 1024 });

function section(markdown, heading) {
  const start = markdown.indexOf(`\n## ${heading}\n`);
  if (start < 0) throw new Error(`Missing operator section: ${heading}`);
  const end = markdown.indexOf('\n## ', start + 1);
  return markdown.slice(start + 1, end < 0 ? undefined : end).trimEnd();
}

function content(source, name) {
  if (name === 'quickstart') {
    return section(source, 'Native quickstart')
      .replace(/^## (Native quickstart)$/m, '# $1');
  }
  if (name === 'browser') {
    const quickstart = source.includes('\n## Try a sample export\n')
      ? section(source, 'Try a sample export')
      : 'Open the [hosted app](https://chopper-1rx.pages.dev/) in desktop Chrome or Edge.';
    const requirements = section(source, 'Browser requirements and storage');
    const picker = section(source, 'Choosing an output folder').split('\n\nFor a desktop picker check,')[0];
    const recovery = section(source, 'Checking a hosted export after interruption');
    return `# Browser exports\n\n${quickstart}\n\n${requirements}\n\n${picker}\n\n${recovery}`;
  }
  return source;
}

function rewriteLinks(md, tag, releasePages) {
  // The shared Markdown points to the library index. Each language guide
  // still resolves its relative links from that same source file.
  const pageMap = new Map();
  for (const [source, name] of releasePages) {
    if (!pageMap.has(source)) pageMap.set(source, name);
  }
  for (const [rule, attribute] of [['link_open', 'href'], ['image', 'src']]) {
    const render = md.renderer.rules[rule] ?? ((tokens, i, options, _env, self) => self.renderToken(tokens, i, options));
    md.renderer.rules[rule] = (tokens, i, options, env, self) => {
      const token = tokens[i];
      const target = token.attrGet(attribute);
      if (target && !/^(?:[\w+.-]+:|\/|#)/.test(target)) {
        const source = releasePages.find(([, name]) => `${name}.md` === env.relativePath)?.[0];
        if (!source) throw new Error(`Unknown link source: ${env.relativePath}`);
        const [path, hash] = target.split('#', 2);
        const suffix = hash ? `#${hash}` : '';
        const resolved = posix.normalize(posix.join(posix.dirname(source), path));
        const local = pageMap.get(resolved);
        if (resolved === imagePath) {
          token.attrSet(attribute, './workbench.png');
        } else if (resolved === samplePath && rule === 'link_open') {
          token.attrSet(attribute, './customers.csv');
          token.attrSet('download', 'customers.csv');
        } else if (local && !(local === 'browser' && hash === 'result-ownership-and-publication-contracts')) {
          token.attrSet(attribute, `./${local}.md${suffix}`);
        } else {
          // Non-site material stays in the repository at this documentation version.
          token.attrSet(attribute, `${repo}/blob/${tag}/${resolved}${suffix}`);
        }
      }
      return render(tokens, i, options, env, self);
    };
  }
}

async function preparePages(source, documents, base, splitLibraries) {
  const renderer = await createMarkdownRenderer(source, {
    headers: { level: [2, 3] },
    highlight: () => '',
  });
  try {
    const generated = new Map();
    const library = documents.find(({ name }) => name === libraryPage[1]);
    if (library) {
      const env = { path: join(source, `${library.name}.md`) };
      const tokens = renderer.parse(library.markdown, env);
      if (splitLibraries) {
        const anchorsByLanguage = [];
        for (const [, name] of languagePages) {
          const language = name.slice('libraries-'.length);
          const page = renderLanguageGuide(library.markdown, tokens, language, base);
          const guideEnv = { path: join(source, `${name}.md`) };
          renderer.render(page, guideEnv);
          anchorsByLanguage.push(guideEnv.headers.map(heading => heading.link));
          generated.set(name, page);
        }
        const [rust, python] = anchorsByLanguage;
        if (JSON.stringify(rust) !== JSON.stringify(python)) {
          throw new Error('Rust and Python library guides must share section anchors');
        }
        generated.set(library.name, renderLibraryIndex(base, rust));
      } else {
        generated.set(library.name, renderLibraryGuide(library.markdown, tokens));
      }
    }
    const navigation = [];
    for (const { name, text, markdown } of documents) {
      const link = name === 'index' ? '/' : `/${name}`;
      const env = { path: join(source, `${name}.md`) };
      const page = generated.get(name) ?? markdown;
      await writeFile(env.path, page);
      renderer.render(page, env);
      const items = env.headers.map(heading => ({
        text: renderer.utils.escapeHtml(heading.title),
        link: link + heading.link,
      }));
      navigation.push({ name, text, link, items });
    }
    // VitePress selects a sidebar by source path on each route change.
    return Object.fromEntries(navigation.map(current => {
      const item = ({ name, text, link, items }) => (
        items.length ? { text, link, items, collapsed: name !== current.name } : { text, link }
      );
      const items = navigation.flatMap(page => {
        if (!splitLibraries) return [item(page)];
        if (page.name.startsWith('libraries-')) return [];
        if (page.name !== libraryPage[1]) return [item(page)];
        const guides = navigation.filter(entry => entry.name.startsWith('libraries-')).map(item);
        const active = current.name === page.name || current.name.startsWith('libraries-');
        return [{ ...item(page), items: guides, collapsed: !active }];
      });
      return [`/${current.name}.md`, [{ items }]];
    }));
  } finally {
    disposeMdItInstance();
  }
}

const releases = versions.map(arg => {
  const [version, ref = `v${version}`, extra] = arg.split('=');
  if (!ref || extra !== undefined) throw new Error(`Invalid source revision for ${version}`);
  const commit = git('rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  const read = path => git('show', `${commit}:${path}`);
  if (JSON.parse(read('ui/package.json')).version !== version) {
    throw new Error(`App version does not match docs version ${version} at ${commit}`);
  }
  const hasFormulas = git('ls-tree', '--name-only', commit, '--', formulaPage[0]).length > 0;
  const hasLibraries = git('ls-tree', '--name-only', commit, '--', libraryPage[0]).length > 0;
  const splitLibraries = hasLibraries && read(libraryPage[0]).toString().split('\n').includes(languagePagesMarker);
  return { version, commit, read, hasFormulas, hasLibraries, splitLibraries };
}).sort((a, b) => b.version.localeCompare(a.version, 'en', { numeric: true }));
if (new Set(releases.map(r => r.version)).size !== releases.length) throw new Error('Duplicate documentation version');

const staging = await mkdtemp(fileURLToPath(new URL('./.build-', import.meta.url)));
try {
  const site = join(staging, 'dist');
  for (const { version, read, hasFormulas, hasLibraries, splitLibraries } of releases) {
    const source = join(staging, version);
    const base = `/versions/${version}/`;
    await mkdir(join(source, 'public'), { recursive: true });
    await cp(stylesheet, join(source, 'public/chopper.css'));
    const releasePages = pages.flatMap(page => {
      if (hasLibraries && page[1] === 'index') return [page, libraryPage, ...(splitLibraries ? languagePages : [])];
      if (hasFormulas && page[1] === 'job-json') return [page, formulaPage];
      return [page];
    });
    const documents = releasePages.map(([path, name, text]) => ({
      name, text, markdown: name === 'cli-reference'
        ? renderCliReference(read(path).toString(), JSON.parse(read('docs/cli-reference-data.json')), version)
        : content(read(path).toString(), name),
    }));
    if (hasLibraries) {
      const component = splitLibraries ? 'LibraryGuideNav.vue' : 'LibraryLanguage.vue';
      await cp(new URL(`./${component}`, import.meta.url), join(source, component));
    }
    await writeFile(join(source, 'workbench.png'), read(imagePath));
    await writeFile(join(source, 'public/customers.csv'), read(samplePath));
    const sidebar = await preparePages(source, documents, base, splitLibraries);

    await build(source, {
      onAfterConfigResolve(config) {
        config.site.base = base;
        config.site.cleanUrls = config.cleanUrls = true;
        config.outDir = join(site, base);
        config.site.title = `Chopper ${version}`;
        config.site.description = `Operator documentation for Chopper ${version}`;
        config.site.head.push(['link', { rel: 'stylesheet', href: base + 'chopper.css' }]);
        config.markdown = { config: md => rewriteLinks(md, `v${version}`, releasePages) };
        config.site.themeConfig = {
          nav: [
            { text: 'Release notes', link: `${repo}/releases/tag/v${version}` },
            { text: 'All versions', link: '../../' },
            { text: 'Buy me a coffee', link: supportUrl },
          ],
          sidebar,
          search: { provider: 'local' },
        };
      },
    });
    // The next version must create its sidebar with a fresh Markdown renderer.
    disposeMdItInstance();
  }

  const [latest] = releases;
  await cp(stylesheet, join(site, 'chopper.css'));
  await writeFile(join(site, 'index.html'), `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chopper documentation</title>
<link rel="stylesheet" href="/chopper.css">
<body class="version-index">
<header><a class="version-brand" href="/">Chopper</a><a href="${supportUrl}">Buy me a coffee</a></header>
<main>
<h1>Chopper documentation</h1>
<p><a href="/versions/${latest.version}/">Latest stable release (${latest.version})</a></p>
<h2>All versions</h2>
<ul>${releases.map(({ version }) => `<li><a href="/versions/${version}/">${version}</a></li>`).join('')}</ul>
</main>
</body>
</html>
`);
  await writeFile(join(site, '404.html'), '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page not found</title><main><h1>Page not found</h1><a href="/">Browse Chopper documentation versions</a></main></html>\n');
  await writeFile(join(site, '_redirects'), `/latest /versions/${latest.version}/ 302\n/latest/* /versions/${latest.version}/:splat 302\n`);
  await writeFile(join(site, 'versions.json'), JSON.stringify({
    latest: latest.version,
    versions: releases.map(({ version, commit, hasFormulas, hasLibraries, splitLibraries }) => {
      const additionalPages = [hasFormulas && formulaPage[1], hasLibraries && libraryPage[1],
        ...(splitLibraries ? languagePages.map(([, name]) => name) : [])].filter(Boolean);
      return { version, commit, ...(additionalPages.length ? { additionalPages } : {}) };
    }),
    pages: pages.map(([, name]) => name),
  }, null, 2) + '\n');
  await checkSite(site);
  await rm(out, { recursive: true, force: true });
  await cp(site, out, { recursive: true });
} finally {
  await rm(staging, { recursive: true, force: true });
}
