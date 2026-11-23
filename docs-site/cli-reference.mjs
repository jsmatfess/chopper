// Tables use the executable's structured contract; raw help remains available verbatim.
function html(text) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function notes(text) {
  return text.split('\n').map(line => line.startsWith('Example: ')
    ? ['```sh', line.slice(9), '```'].join('\n')
    : line.replace(/--[\w=-]+/g, flag => `\`${flag}\``)
  ).join('\n\n');
}

function optionTable(title, entries) {
  const commands = title === 'Commands';
  const label = title === 'Arguments' ? 'Argument' : commands ? 'Command' : 'Flag';
  return [
    '<table class="cli-option-table">',
    `<thead><tr><th scope="col">${label}</th><th scope="col">Description</th>${commands ? '' : '<th scope="col">Accepted values</th>'}</tr></thead>`,
    '<tbody>',
    ...entries.map(({ syntax, description, accepted_values: values, defaults }) => {
      if (!description?.trim()) throw new Error(`Missing CLI description for ${syntax}`);
      const detail = defaults?.length ? ` <small>Default: ${html(defaults.join(', '))}</small>` : '';
      const choices = commands ? '' : `<td class="cli-choices">${values.length
        ? values.map(value => `<code>${html(value)}</code>`).join(' ')
        : '—'}</td>`;
      return `<tr><th scope="row"><code>${html(syntax)}</code></th><td>${html(description)}${detail}</td>${choices}</tr>`;
    }),
    '</tbody>',
    '</table>',
  ].join('\n');
}

export function renderCliReference(reference, contract, version) {
  const rawHelp = new Map([...reference.matchAll(/^## `([^`]+)`\n\n```text\n([\s\S]*?)\n```/gm)]
    .map(([, name, raw]) => [name, raw]));
  if (contract.version !== version || rawHelp.size !== contract.commands.length) {
    throw new Error('Structured CLI reference does not match the release help.');
  }
  const intro = reference.slice(0, reference.indexOf('\n## `')).trimEnd();
  return [intro, ...contract.commands.map(command => {
    const raw = rawHelp.get(command.name);
    if (!raw) throw new Error(`Missing terminal help for ${command.name}`);
    const grouped = new Map();
    if (command.subcommands.length) grouped.set('Commands', command.subcommands);
    grouped.set('Arguments', []);
    grouped.set('Options', []);
    for (const argument of command.arguments) {
      if (!grouped.has(argument.heading)) grouped.set(argument.heading, []);
      grouped.get(argument.heading).push(argument);
    }
    return [
      `## \`${command.name}\``,
      command.description,
      ['```text', command.usage.replace(/^Usage: /, ''), '```'].join('\n'),
      ...[...grouped].filter(([, entries]) => entries.length)
        .map(([title, entries]) => `### ${title}\n\n${optionTable(title, entries)}`),
      notes(command.notes),
      ['::: details Original terminal help', '', '```text', raw, '```', '', ':::'].join('\n'),
    ].filter(Boolean).join('\n\n');
  })].join('\n\n');
}
