import { execFileSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'vitepress';
import { checkSite } from './check.mjs';

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
const imagePath = 'docs/images/workbench.png';
const pageMap = new Map(pages.map(([source, name]) => [source, name]));
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
    const requirements = section(source, 'Browser requirements and storage');
    const picker = section(source, 'Choosing an output folder').split('\n\nFor a desktop picker check,')[0];
    const recovery = section(source, 'Checking a hosted export after interruption');
    return `# Browser exports\n\nOpen the [hosted app](https://chopper-1rx.pages.dev/) in desktop Chrome or Edge.\n\n${requirements}\n\n${picker}\n\n${recovery}`;
  }
  return source;
}

function rewriteLinks(md, tag) {
  for (const [rule, attribute] of [['link_open', 'href'], ['image', 'src']]) {
    const render = md.renderer.rules[rule] ?? ((tokens, i, options, _env, self) => self.renderToken(tokens, i, options));
    md.renderer.rules[rule] = (tokens, i, options, env, self) => {
      const token = tokens[i];
      const target = token.attrGet(attribute);
      if (target && !/^(?:[\w+.-]+:|\/|#)/.test(target)) {
        const source = pages.find(([, name]) => `${name}.md` === env.relativePath)?.[0];
        if (!source) throw new Error(`Unknown link source: ${env.relativePath}`);
        const [path, hash] = target.split('#', 2);
        const suffix = hash ? `#${hash}` : '';
        const resolved = posix.normalize(posix.join(posix.dirname(source), path));
        const local = pageMap.get(resolved);
        if (resolved === imagePath) {
          token.attrSet(attribute, './workbench.png');
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

const releases = versions.map(arg => {
  const [version, ref = `v${version}`, extra] = arg.split('=');
  if (!ref || extra !== undefined) throw new Error(`Invalid source revision for ${version}`);
  const commit = git('rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  const read = path => git('show', `${commit}:${path}`);
  if (JSON.parse(read('ui/package.json')).version !== version) {
    throw new Error(`App version does not match docs version ${version} at ${commit}`);
  }
  return { version, commit, read };
}).sort((a, b) => b.version.localeCompare(a.version, 'en', { numeric: true }));
if (new Set(releases.map(r => r.version)).size !== releases.length) throw new Error('Duplicate documentation version');

const staging = await mkdtemp(fileURLToPath(new URL('./.build-', import.meta.url)));
try {
  const site = join(staging, 'dist');
  for (const { version, read } of releases) {
    const source = join(staging, version);
    const base = `/versions/${version}/`;
    await mkdir(source, { recursive: true });
    for (const [path, name] of pages) {
      await writeFile(join(source, `${name}.md`), content(read(path).toString(), name));
    }
    await writeFile(join(source, 'workbench.png'), read(imagePath));

    await build(source, {
      onAfterConfigResolve(config) {
        config.site.base = base;
        config.site.cleanUrls = config.cleanUrls = true;
        config.outDir = join(site, base);
        config.site.title = `Chopper ${version}`;
        config.site.description = `Operator documentation for Chopper ${version}`;
        config.markdown = { config: md => rewriteLinks(md, `v${version}`) };
        config.site.themeConfig = {
          nav: [{ text: 'Release notes', link: `${repo}/releases/tag/v${version}` }, { text: 'All versions', link: '../../' }],
          sidebar: pages.map(([, name, text]) => ({ text, link: name === 'index' ? '/' : `/${name}` })),
          search: { provider: 'local' },
        };
      },
    });
  }

  const [latest] = releases;
  await writeFile(join(site, 'index.html'), `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chopper documentation</title>
<main>
<h1>Chopper documentation</h1>
<p><a href="/versions/${latest.version}/">Latest stable release (${latest.version})</a></p>
<h2>All versions</h2>
<ul>${releases.map(({ version }) => `<li><a href="/versions/${version}/">${version}</a></li>`).join('')}</ul>
</main>
</html>
`);
  await writeFile(join(site, '404.html'), '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page not found</title><main><h1>Page not found</h1><a href="/">Browse Chopper documentation versions</a></main></html>\n');
  await writeFile(join(site, '_redirects'), `/latest /versions/${latest.version}/ 302\n/latest/* /versions/${latest.version}/:splat 302\n`);
  await writeFile(join(site, 'versions.json'), JSON.stringify({
    latest: latest.version,
    versions: releases.map(({ version, commit }) => ({ version, commit })),
    pages: pages.map(([, name]) => name),
  }, null, 2) + '\n');
  await checkSite(site);
  await rm(out, { recursive: true, force: true });
  await cp(site, out, { recursive: true });
} finally {
  await rm(staging, { recursive: true, force: true });
}
