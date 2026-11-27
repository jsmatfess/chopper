// Mark up the web guide using Markdown tokens so fenced text cannot be mistaken
// for a section heading or language label.
export function renderLibraryGuide(markdown, tokens) {
  const lines = markdown.split('\n');
  const headings = tokens.flatMap((token, index) => (
    token.type === 'heading_open' && token.tag === 'h2' && token.level === 0
      ? [{ title: tokens[index + 1].content, line: token.map[0] }]
      : []
  ));
  const setup = headings.findIndex(heading => heading.title === 'Rust');
  if (setup === -1 || headings[setup + 1]?.title !== 'Python') {
    throw new Error('The library guide needs consecutive Rust and Python quickstart sections');
  }
  const rust = headings[setup].line;
  const python = headings[setup + 1].line;
  const end = headings[setup + 2]?.line ?? lines.length;
  const source = (start, stop) => lines.slice(start, stop).join('\n').trim();
  const panel = (language, body) => `<div data-library-example="${language}">\n\n${body}\n\n</div>\n\n`;

  const edits = [{
    start: rust,
    end,
    text: '## Run your first Job\n\n<span id="rust"></span><span id="python"></span>\n\n'
      + panel('rust', '**Rust**\n\n' + source(rust + 1, python))
      + panel('python', '**Python**\n\n' + source(python + 1, end)),
  }];
  for (const [index, token] of tokens.entries()) {
    if (token.type !== 'fence' || token.level !== 0) continue;
    const [start, stop] = token.map;
    if (start >= rust && start < end) continue;
    const language = token.info.trim().match(/^(rust|python)(?:$|[\s:{])/)?.[1];
    if (!language) continue;
    const label = language === 'rust' ? '**Rust**' : '**Python**';
    const paragraph = tokens[index - 3];
    const first = paragraph?.type === 'paragraph_open'
      && tokens[index - 2].content === label ? paragraph.map[0] : start;
    edits.push({ start: first, end: stop, text: panel(language, source(first, stop)) });
  }
  edits.push({ start: headings[0].line, end: headings[0].line, text: '<LibraryLanguage />\n\n' });
  for (const edit of edits.sort((a, b) => b.start - a.start || b.end - a.end)) {
    lines.splice(edit.start, edit.end - edit.start, edit.text);
  }
  return "<script setup>\nimport LibraryLanguage from './LibraryLanguage.vue';\n</script>\n\n" + lines.join('\n');
}
