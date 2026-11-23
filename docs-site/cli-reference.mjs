// Reuse the checked release help, including descriptions, defaults and examples.
function parseHelp(reference) {
  const commands = [...reference.matchAll(/^## `([^`]+)`\n\n```text\n([\s\S]*?)\n```/gm)];
  if (!commands.length) throw new Error('No commands found in the generated CLI reference.');
  return commands.map(([, name, raw]) => {
    const [description, help] = raw.split('\n\nUsage: ');
    if (!help) throw new Error(`Missing usage for ${name}`);
    const [usage, ...lines] = help.split('\n');
    const groups = [];
    const notes = [];
    let group;
    for (const line of lines) {
      if (!line.trim()) continue;
      if (/^[A-Z][^:]+:$/.test(line)) {
        group = { title: line.slice(0, -1), entries: [] };
        groups.push(group);
      } else if (/^ {10}/.test(line) && group?.entries.length) {
        group.entries.at(-1).description.push(line.trim());
      } else if (/^ {2,6}\S/.test(line) && group) {
        const [, syntax, description] = line.trim().match(/^(.+?)(?: {2,}(.+))?$/);
        group.entries.push({ syntax, description: description ? [description] : [] });
      } else {
        notes.push(line);
      }
    }
    return { name, description, usage, groups, notes, raw };
  });
}

function html(text) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function synopsis(command) {
  return [command.description, '', '```text', command.usage, '```', ''].join('\n');
}

function rawHelp(command) {
  return ['::: details Original terminal help', '', '```text', command.raw, '```', '', ':::', ''].join('\n');
}

function commandNotes(notes) {
  if (!notes.length) return '';
  return notes.map(line => line.startsWith('Example: ')
    ? '```sh\n' + line.slice(9) + '\n```'
    : line.replace(/--[\w=-]+/g, flag => `\`${flag}\``)
  ).join('\n\n') + '\n\n';
}

function optionTable(title, entries) {
  const label = title === 'Arguments' ? 'Argument' : title === 'Commands' ? 'Command' : 'Flag';
  return [
    '<table class="cli-option-table">',
    `<thead><tr><th scope="col">${label}</th><th scope="col">Description</th></tr></thead>`,
    '<tbody>',
    ...entries.map(entry => (
      `<tr><th scope="row"><code>${html(entry.syntax)}</code></th><td>${html(entry.description.join(' ')) || '—'}</td></tr>`
    )),
    '</tbody>',
    '</table>',
  ].join('\n');
}

export function renderCliReference(reference) {
  const commands = parseHelp(reference);
  const intro = reference.slice(0, reference.indexOf('\n## `')).trimEnd();
  return [intro, ...commands.map(command => [
    `## \`${command.name}\``,
    synopsis(command),
    ...command.groups.map(({ title, entries }) => `### ${title}\n\n${optionTable(title, entries)}`),
    commandNotes(command.notes),
    rawHelp(command),
  ].filter(Boolean).join('\n\n'))].join('\n\n');
}
