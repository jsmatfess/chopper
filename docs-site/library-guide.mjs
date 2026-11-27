export const languagePagesMarker = '<!-- chopper-docs:language-pages -->';
const languages = ['rust', 'python'];

export function findLanguagePagesMarker(tokens) {
  return tokens.find(token => (
    token.type === 'html_block' && token.level === 0 && token.content.trim() === languagePagesMarker
  ));
}

function proseMarker(token) {
  if (token.type !== 'html_block' && token.type !== 'html_inline') return;
  return token.content.trim().match(/^<!-- docs:(rust|python|end) -->$/)?.[1];
}

function fenceLanguage(token) {
  if (token.type !== 'fence') return;
  return token.info.trim().match(/^(rust|python)(?:$|[\s:{])/)?.[1];
}

// Markdown tokens keep fenced text out of the heading and label detection.
function structure(tokens, lineCount) {
  const headings = tokens.flatMap((token, index) => (
    token.type === 'heading_open' && token.tag === 'h2' && token.level === 0
      ? [{ title: tokens[index + 1].content, line: token.map[0] }]
      : []
  ));
  const setup = headings.findIndex(heading => heading.title === 'Rust');
  const title = tokens.find(token => token.type === 'heading_open' && token.tag === 'h1' && token.level === 0);
  if (!title || setup === -1 || headings[setup + 1]?.title !== 'Python') {
    throw new Error('The library guide needs consecutive Rust and Python quickstart sections');
  }
  const rust = headings[setup].line;
  const python = headings[setup + 1].line;
  return { title, rust, python, end: headings[setup + 2]?.line ?? lineCount, firstHeading: headings[0].line };
}

function examples(tokens, rust, end) {
  return tokens.flatMap((token, index) => {
    const language = fenceLanguage(token);
    if (!language || token.level !== 0) return [];
    const [fence, stop] = token.map;
    if (fence >= rust && fence < end) return [];
    const label = language === 'rust' ? '**Rust**' : '**Python**';
    const paragraph = tokens[index - 3];
    const start = paragraph?.type === 'paragraph_open'
      && tokens[index - 2].content === label ? paragraph.map[0] : fence;
    return [{ start, fence, stop, language }];
  });
}

function editLines(lines, edits) {
  let previous = lines.length;
  for (const edit of edits.sort((a, b) => b.start - a.start || b.end - a.end)) {
    if (edit.end > previous) throw new Error('Library guide edits overlap a language prose block');
    lines.splice(edit.start, edit.end - edit.start, edit.text);
    previous = edit.start;
  }
  return lines.join('\n');
}

export function renderLibraryGuide(markdown, tokens) {
  if (tokens.some(token => proseMarker(token) || token.children?.some(proseMarker))) {
    throw new Error('Library prose language markers require the top-level chopper-docs:language-pages layout marker');
  }
  const lines = markdown.split('\n');
  const { title, rust, python, end, firstHeading } = structure(tokens, lines.length);
  const source = (start, stop) => lines.slice(start, stop).join('\n').trim();
  const panel = (language, body) => `<div data-library-example="${language}">\n\n${body}\n\n</div>\n\n`;

  const edits = [{
    start: title.map[0],
    end: title.map[1],
    text: '# Chopper libraries\n\n<span id="rust-and-python-libraries" class="library-section-alias"></span>\n',
  }, {
    start: rust,
    end,
    text: '## Run your first Job\n\n<span id="rust" class="library-section-alias"></span>'
      + '<span id="python" class="library-section-alias"></span>\n\n'
      + panel('rust', '**Rust**\n\n' + source(rust + 1, python))
      + panel('python', '**Python**\n\n' + source(python + 1, end)),
  }];
  for (const { start, stop, language } of examples(tokens, rust, end)) {
    edits.push({ start, end: stop, text: panel(language, source(start, stop)) });
  }
  edits.push({ start: firstHeading, end: firstHeading, text: '<LibraryLanguage />\n\n' });
  return "<script setup>\nimport LibraryLanguage from './LibraryLanguage.vue';\n</script>\n\n" + editLines(lines, edits);
}

function proseBlocks(tokens) {
  const blocks = [];
  let open;
  for (const token of tokens) {
    const language = proseMarker(token);
    if ((language && token.level !== 0) || token.children?.some(proseMarker)) {
      throw new Error('Library prose language markers must be top-level comment blocks');
    }
    if (!language) continue;
    if (language === 'end') {
      if (!open) throw new Error('Library prose has a closing language marker with no opening marker');
      blocks.push({ ...open, close: token.map });
      open = undefined;
    } else {
      if (open) throw new Error('Library prose language blocks cannot be nested');
      open = { language, start: token.map };
    }
  }
  if (open) throw new Error('Library prose has an unclosed language block');
  return blocks;
}

const navImport = "import LibraryGuideNav from './LibraryGuideNav.vue';\n";

export function renderLanguageGuide(markdown, tokens, language, base) {
  if (tokens.some(token => token.level !== 0 && fenceLanguage(token))) {
    throw new Error('Rust and Python example fences must be top-level blocks in the library source');
  }
  const blocks = proseBlocks(tokens);
  const lines = markdown.split('\n');
  const { title, rust, python, end } = structure(tokens, lines.length);
  const label = language === 'rust' ? 'Rust' : 'Python';
  const [start, stop] = language === 'rust' ? [rust + 1, python] : [python + 1, end];
  const edits = [{
    start: title.map[0], end: title.map[1],
    text: `# Chopper for ${label}\n\n<LibraryGuideNav base="${base}" current="${language}" />\n`,
  }, {
    start: rust, end,
    text: '## Run your first Job\n\n' + lines.slice(start, stop).join('\n'),
  }];
  const marker = findLanguagePagesMarker(tokens);
  if (marker) edits.push({ start: marker.map[0], end: marker.map[1], text: '' });
  for (const example of examples(tokens, rust, end)) {
    edits.push({
      start: example.start,
      end: example.language === language ? example.fence : example.stop,
      text: '',
    });
  }
  for (const block of blocks) {
    if (block.language === language) {
      edits.push({ start: block.start[0], end: block.start[1], text: '' });
      edits.push({ start: block.close[0], end: block.close[1], text: '' });
    } else {
      edits.push({ start: block.start[0], end: block.close[1], text: '' });
    }
  }
  return `<script setup>\n${navImport}</script>\n\n` + editLines(lines, edits);
}

export function renderLibraryIndex(base, anchors) {
  return `<script setup>
${navImport}import { onMounted, onUnmounted } from 'vue';

const base = ${JSON.stringify(base)};
const sections = ${JSON.stringify(anchors)};
const languages = ${JSON.stringify(languages)};

function redirectLibraryLink() {
  const url = new URL(window.location.href);
  let hash = '';
  try {
    hash = decodeURIComponent(url.hash);
  } catch {
    // Malformed fragments cannot match a section or a legacy language.
  }
  const requested = url.searchParams.get('lang');
  const legacy = languages.find(language => hash === '#' + language);
  const section = sections.includes(hash) ? hash : '';
  const language = languages.includes(requested) ? requested : legacy ?? (section ? 'rust' : '');
  if (!language) return;
  url.pathname = base + 'libraries-' + language;
  url.searchParams.delete('lang');
  url.hash = legacy ? '#run-your-first-job' : section;
  window.location.replace(url);
}

onMounted(() => {
  window.addEventListener('hashchange', redirectLibraryLink);
  redirectLibraryLink();
});
onUnmounted(() => window.removeEventListener('hashchange', redirectLibraryLink));
</script>

# Chopper libraries

Build, validate, and run file-to-file Jobs from your application.

<LibraryGuideNav base="${base}" />

${anchors.map(anchor => `<span id="${anchor.slice(1)}"></span>`).join('\n')}
<span id="rust-and-python-libraries"></span><span id="rust"></span><span id="python"></span>
`;
}
