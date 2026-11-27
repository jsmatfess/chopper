export const formulaTablesMarker = '<!-- chopper-docs:formula-tables -->';

function markCells(token, column, syntax) {
  for (const [index, code] of token.children.entries()) {
    if (code.type !== 'code_inline') continue;
    // In an example cell the expression precedes the result arrow.
    if (column !== 0 && !token.children[index + 1]?.content.trimStart().startsWith('→')) continue;
    const entry = Object.hasOwn(syntax, code.content) && syntax[code.content];
    if (typeof entry?.rust !== 'string' || typeof entry?.python !== 'string') {
      throw new Error(`Missing SDK syntax for ${code.content}`);
    }
    code.attrSet('data-formula-rust', entry.rust);
    code.attrSet('data-formula-python', entry.python);
  }
}

export function renderFormulaTables(md, syntax) {
  md.core.ruler.after('inline', 'chopper_formula_tables', state => {
    if (state.env.relativePath !== 'formula-functions.md') return;
    let heading = 'Formula reference';
    let table;
    let column;
    for (const [index, token] of state.tokens.entries()) {
      if (token.type === 'heading_open' && (token.tag === 'h2' || token.tag === 'h3')) {
        heading = state.tokens[index + 1].content;
      }
      if (token.type === 'table_open') table = token;
      if (!table) continue;
      if (token.type === 'tr_open') column = -1;
      if (token.type === 'th_open' || token.type === 'td_open') column++;
      if (token.type === 'table_close') {
        token.meta = table.meta;
        table = undefined;
      }
      if (token.type !== 'inline') continue;
      const cell = state.tokens[index - 1].type;
      if (cell === 'th_open' && column === 0 && ['Function', 'Operator'].includes(token.content)) {
        table.meta = { formulaTableHeading: heading };
      }
      if (!table?.meta?.formulaTableHeading) continue;
      if (cell === 'th_open') state.tokens[index - 1].attrSet('scope', 'col');
      if (cell === 'td_open' && (column === 0 || column === 2)) markCells(token, column, syntax);
    }
  });

  for (const type of ['table_open', 'table_close']) {
    const render = md.renderer.rules[type] ?? ((tokens, i, options, _env, self) => self.renderToken(tokens, i, options));
    md.renderer.rules[type] = (tokens, i, options, env, self) => {
      const label = tokens[i].meta?.formulaTableHeading;
      const html = render(tokens, i, options, env, self);
      if (!label) return html;
      if (type === 'table_open') {
        return `<div class="formula-table-scroll" role="region" aria-label="${md.utils.escapeHtml(label)}" tabindex="0">\n${html}`;
      }
      return html + '</div>\n';
    };
  }
}
