import assert from 'node:assert/strict';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createMarkdownRenderer, disposeMdItInstance } from 'vitepress';
import {
  findLanguagePagesMarker, languagePagesMarker, renderLanguageGuide, renderLibraryGuide,
} from './library-guide.mjs';

const root = fileURLToPath(new URL('./', import.meta.url));
const renderer = await createMarkdownRenderer(root, { highlight: () => '' });
const parse = markdown => renderer.parse(markdown, { path: join(root, 'library-fixture.md') });
const guide = '# Library guide\n\n## Rust\n\nRust job.\n\n## Python\n\nPython job.\n\n## Recipes\n\n';
const scopedProse = '<!-- docs:python -->\n\nPython prose only.\n\n<!-- docs:end -->\n';
const fencedSample = `\`\`\`text\n${languagePagesMarker}\n<!-- docs:rust -->\n\`\`\`\n`;
const splitGuide = languagePagesMarker + '\n\n' + guide;

after(disposeMdItInstance);

test('scoped prose requires a real top-level layout marker', () => {
  for (const prefix of ['', fencedSample + '\n']) {
    const markdown = prefix + guide + scopedProse;
    const tokens = parse(markdown);
    assert.equal(findLanguagePagesMarker(tokens), undefined);
    assert.throws(() => renderLibraryGuide(markdown, tokens), /require the top-level.*layout marker/);
  }
  assert.match(renderLibraryGuide(guide + fencedSample, parse(guide + fencedSample)), /<!-- docs:rust -->/);
});

test('split guides filter scoped prose and preserve fenced text', () => {
  const markdown = splitGuide + fencedSample + '\n' + scopedProse;
  const tokens = parse(markdown);
  assert.ok(findLanguagePagesMarker(tokens));
  const rust = renderLanguageGuide(markdown, tokens, 'rust', '/versions/0.7.0/');
  const python = renderLanguageGuide(markdown, tokens, 'python', '/versions/0.7.0/');
  assert.doesNotMatch(rust, /Python prose only/);
  assert.match(python, /Python prose only/);
  assert.ok(rust.includes(fencedSample));
  assert.ok(python.includes(fencedSample));
});

test('split guides reject language markup inside lists', () => {
  const comment = splitGuide + '1. <!-- docs:python -->\n\n   Python prose only.\n\n   <!-- docs:end -->\n';
  const example = splitGuide + '1. Code\n\n   ```python\n   print(1)\n   ```\n';
  assert.throws(() => renderLanguageGuide(comment, parse(comment), 'rust', '/'), /markers must be top-level/);
  assert.throws(() => renderLanguageGuide(example, parse(example), 'rust', '/'), /fences must be top-level/);
});
