type Group = {name: string; percent: string};
type Step = {type: string; files?: number; columns?: (string | number)[]; groups?: Group[]; strata?: (string | number)[]; strategy?: string};

// Match the engine's exact, millionths-of-a-percent arithmetic.
export function percentageUnits(text: string): number | null {
  if (!/^\d+(\.\d{0,6})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  const units = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, '0'));
  return Number.isSafeInteger(units) && units <= 100_000_000 ? units : null;
}

export const GROUP_TOTAL_ERROR = 'Percentages must total exactly 100%.';
export function groupErrors(groups: Group[]): string[] {
  const names = groups.map(g => g.name);
  const units = groups.map(g => percentageUnits(g.percent));
  const errors: string[] = [];
  if (!groups.length || groups.length > 1024) errors.push('Add between 1 and 1,024 groups.');
  if (names.some(n => !n.trim())) errors.push('Give every group a name.');
  if (new Set(names).size !== names.length) errors.push('Group names must be unique.');
  if (units.some(n => n === null)) errors.push('Use percentages from 0 to 100 with at most 6 decimal places.');
  else {
    const total = units.reduce<number>((sum, n) => sum + n!, 0);
    if (total !== 100_000_000) errors.push(`${GROUP_TOTAL_ERROR} Current total: ${total / 1_000_000}%.`);
  }
  return errors;
}

const quote = (text: string) => `“${text}”`;
const list = (items: string[]) => items.length < 3
  ? items.join(' and ')
  : `${items.slice(0, -1).join(', ')}, and ${items.at(-1)}`;
const number = (value: number) => value.toLocaleString('en-US');
const fileSize = (text: string) => text.trim().replace(/^(\d+)\s*([a-z]+)$/i, '$1 $2');
const positiveInteger = (value: number | undefined): value is number => Number.isSafeInteger(value) && value! > 0;
const field = (column: string | number) => typeof column === 'number' ? `column #${column}` : quote(column);
const fieldKey = (column: string | number) => `${typeof column}:${column}`;
const distinctValues = (columns: (string | number)[]) => columns.length === 1
  ? `each distinct value of ${field(columns[0])}`
  : `each unique combination of ${list(columns.map(field))}`;
const capitalize = (text: string) => text[0].toUpperCase() + text.slice(1);
const sentence = (text: string) => `${capitalize(text)}.`;

type Scope = 'input' | 'group' | 'part' | 'allocation';
const within = (scope: Scope) => scope === 'input' ? '' : `within each ${scope}, `;
const rows = (scope: Scope) => scope === 'input' ? 'the input rows' : `the rows in each ${scope}`;
const source = (scope: Scope) => scope === 'input' ? 'the input' : `each ${scope}`;

export type PlanTarget = `step-${number}` | `section-${number}` | 'input' | 'output' | 'pipeline' | 'resources' | 'max-rows' | 'max-bytes' | 'compressed-bytes' | 'compression';

export function describePlan(operations: Step[], limits: {rows: string; bytes: string; compressed: string}, compression: string, decorate?: (text:string,target:PlanTarget)=>string): string {
  const narrative: string[] = [];
  const details: string[] = [];
  const delivery: string[] = [];
  let target:PlanTarget='output', shuffleTarget:PlanTarget='output';
  const link=(text:string,to:PlanTarget)=>decorate?decorate(text,to):text;
  const detail=(text:string,to:PlanTarget=target)=>details.push(link(text,to));
  const deliver=(text:string,to:PlanTarget='output')=>delivery.push(link(text,to));
  const lastGrouping = operations.reduce((last, op, i) => op.type === 'shuffle' ? last : i, -1);
  // Shuffling preserves fixed counts; partitioning and assignment create new,
  // subdividable groups even when a balanced split came earlier.
  const fixedFiles = ['balanced', 'interleaved'].includes(operations[lastGrouping]?.type);
  const hardLimits = !!(limits.rows.trim() || limits.bytes.trim());
  const softLimit = !!limits.compressed.trim() && compression !== 'none';
  const multipleFiles = !fixedFiles && (hardLimits || softLimit);
  const csv = multipleFiles ? 'CSV files' : 'a CSV';
  const fixedColumns = new Set<string>();
  let scope: Scope = 'input';
  let hasAssignment = false;
  let hasBalanced = false;
  let pendingShuffle = '';

  // Merge a shuffle with the next action, rather than narrating two disconnected
  // commands. Keep every shuffle in place: its position changes the result.
  const action = (text: string) => {
    // Linked prose keeps each step separate so every sentence has one editor target.
    if(decorate&&pendingShuffle){narrative.push(link(sentence(pendingShuffle),shuffleTarget));pendingShuffle='';}
    narrative.push(link(sentence(pendingShuffle ? `${pendingShuffle}, then ${text}` : text),target));
    pendingShuffle = '';
  };

  const assignment = (op: Step, prefix: string, final: boolean) => {
    const approximate = op.type === 'assign_probabilistic';
    const groups = op.groups || [];
    if (groupErrors(groups).length) {
      action(`${prefix}choose unique allocation names and percentages totaling 100%`);
      scope = 'allocation';
      return;
    }
    const randomMembership = groups.filter(g => percentageUnits(g.percent)! > 0).length > 1;
    hasAssignment ||= !approximate && groups.some(g => ![0, 100_000_000].includes(percentageUnits(g.percent)!));
    if (final) {
      const matching = prefix.startsWith('for ') ? 'matching ' : '';
      let describedRows = false;
      const outputs = groups.map(g => {
        const units = percentageUnits(g.percent)!;
        if (!units) return `an empty CSV for ${quote(g.name)}`;
        const output = `${multipleFiles ? 'a set of CSV files' : 'a CSV'} for ${quote(g.name)}`;
        if (units === 100_000_000) return `${output} containing all ${matching}rows`;
        const share = `${output} with ${approximate ? 'approximately ' : ''}${units / 1_000_000}%${describedRows ? '' : ` of the ${matching}rows`}`;
        describedRows = true;
        return share;
      });
      action(`${prefix}create ${list(outputs)}${randomMembership ? ', choosing rows randomly' : ''}`);
    } else {
      action(`${prefix}${randomMembership ? 'randomly ' : ''}assign ${list(groups.map((g, i) => `${approximate ? 'approximately ' : ''}${percentageUnits(g.percent)! / 1_000_000}%${i === 0 ? ' of the rows' : ''} to ${quote(g.name)}`))}`);
    }
    // Columns fixed by earlier partitions already have separate quotas. Only
    // describe additional strata; stratification does not add output groups.
    const strata = (op.strata || []).filter(c => !fixedColumns.has(fieldKey(c)));
    if (strata.length) {
      narrative.push(link(sentence(`apply those percentages separately for ${distinctValues(strata)}, pooling the results into the corresponding ${list(groups.map(g => quote(g.name)))} ${final ? 'outputs' : 'allocations'}`),target));
    }
    if (approximate) detail('Each row is assigned independently. Percentages are targets, not exact quotas; small strata may receive no rows in a destination.');
    scope = 'allocation';
  };

  for (let i = 0; i < operations.length; i++) {
    const op = operations[i];
    target=`step-${i}`;
    const final = i === lastGrouping;
    if (op.type === 'shuffle') {
      if (pendingShuffle) { narrative.push(link(sentence(pendingShuffle),shuffleTarget)); pendingShuffle = ''; }
      shuffleTarget=target;
      const subject = scope === 'input' && operations[i - 1]?.type === 'shuffle' ? 'them'
          : i > lastGrouping && lastGrouping >= 0 && !multipleFiles ? 'the rows in each CSV' : rows(scope);
      pendingShuffle = `shuffle ${subject}${operations[i - 1]?.type === 'shuffle' ? ' again' : ''} into a random order`;
      continue;
    }
    if (op.type === 'partition') {
      const columns = op.columns || [];
      if (!columns.length) {
        action(`choose the columns ${final ? 'that should have separate CSV files' : 'to group rows by'}`);
        scope = 'group';
        continue;
      }
      columns.forEach(c => fixedColumns.add(fieldKey(c)));
      // Common partition → allocation/split pairs read as one output plan.
      const next = operations[i + 1];
      const prefix = `for ${distinctValues(columns)}${scope === 'input' ? '' : ` within each ${scope}`}, `;
      if (!decorate && (next?.type === 'assign' || next?.type === 'assign_probabilistic') && !groupErrors(next.groups || []).length) {
        assignment(next, prefix, i + 1 === lastGrouping);
        i++;
      } else if (!decorate && next?.type === 'balanced' && i + 1 === lastGrouping && positiveInteger(next.files)) {
        action(`${prefix}${next.files === 1 ? 'keep the matching rows together in one CSV' : `split the matching rows as evenly as possible into ${number(next.files)} CSVs`}`);
        hasBalanced = true;
        scope = 'part';
        i++;
      } else {
        action(final
          ? `create ${csv} for ${distinctValues(columns)}${scope === 'input' ? '' : ` within each ${scope}`}`
          : `group ${rows(scope)} by ${list(columns.map(field))}`);
        scope = 'group';
      }
    } else if (op.type === 'assign' || op.type === 'assign_probabilistic') {
      assignment(op, within(scope), final);
    } else if (op.type === 'interleaved') {
      if (!positiveInteger(op.files)) action(`choose a positive whole number of parts for ${source(scope)}`);
      else {
        action(`${within(scope)}distribute consecutive rows cyclically across ${number(op.files)} ${final ? 'CSVs' : 'parts'}`);
        detail('Parts are interleaved; concatenating files does not restore input order.');
        hasBalanced = true;
      }
      scope = 'part';
    } else if (op.type === 'balanced') {
      if (!positiveInteger(op.files)) action(`choose a positive whole number of ${final ? 'CSV files' : 'parts'} for ${source(scope)}`);
      else {
        const unit = final ? 'CSV' : 'part';
        action(op.files === 1
          ? `keep ${source(scope)} together in one ${unit}`
          : `split ${scope === 'input' && pendingShuffle ? 'them' : source(scope)} as evenly as possible into ${number(op.files)} ${unit}s`);
        hasBalanced = true;
      }
      scope = 'part';
    }
  }

  target='output';
  if (lastGrouping === -1) action(multipleFiles ? `split ${pendingShuffle ? 'them' : 'the input'} into CSV files` : `write ${pendingShuffle ? 'them' : 'the input'} to one CSV`);
  else if (pendingShuffle) narrative.push(link(sentence(`${pendingShuffle} before writing`),shuffleTarget));
  if (!operations.some(op => op.type === 'shuffle')) {
    // Fold the simple case into a single sentence.
    if (!operations.length) narrative[0] = decorate ? link(`${multipleFiles?'Split the input into CSV files':'Write the input to one CSV'}, keeping rows in their original order.`,'output') : narrative[0].slice(0, -1) + ', keeping rows in their original order.';
    else detail('Rows keep their original order within each output.','pipeline');
  }
  if (operations.some(op => op.type === 'shuffle' && op.strategy === 'fisher_yates')) detail('Fisher–Yates keeps uniform randomness. Each group must fit in memory or the job fails.',`step-${operations.findIndex(op=>op.type==='shuffle'&&op.strategy==='fisher_yates')}`);
  if (hasAssignment) detail('Allocations are rounded to whole rows.',`step-${operations.findIndex(op=>op.type==='assign')}`);
  if (hasBalanced) detail('Each split produces nonempty parts whose row counts differ by at most one.',`step-${operations.findIndex(op=>op.type==='balanced'||op.type==='interleaved')}`);
  if (hardLimits) {
    const caps = [
      limits.rows.trim() ? `${/^\d+$/.test(limits.rows.trim()) ? number(Number(limits.rows)) : limits.rows.trim()} data rows` : '',
      limits.bytes.trim() ? `${fileSize(limits.bytes)} of uncompressed CSV data` : '',
    ].filter(Boolean);
    if(decorate){
      if(limits.rows.trim())deliver(`Each CSV contains at most ${caps[0]}.`,'max-rows');
      if(limits.bytes.trim())deliver(`Each CSV contains at most ${caps.at(-1)}.`,'max-bytes');
    }else deliver(`Each CSV contains at most ${list(caps)}.`);
    if (limits.bytes.trim()) deliver('The byte limit includes any header and byte-order mark.','max-bytes');
    if (fixedFiles) deliver('The file count stays fixed; analysis will reject the plan if a part cannot fit within those limits.',limits.bytes.trim()?'max-bytes':'max-rows');
  }
  if (limits.compressed.trim()) {
    if (!softLimit) deliver('Choose an output compression format to use the compressed size target.','compression');
    else {
      deliver(`Aim for ${fileSize(limits.compressed)} per ${compression === 'zip' ? 'compressed CSV inside the ZIP' : 'compressed file'}; this is an approximate target and may be exceeded.`,'compressed-bytes');
      if (fixedFiles) deliver('Keep the chosen file count even if the compressed files are larger than the target.','compressed-bytes');
    }
  }
  if (operations.some(op => [...(op.columns || []), ...(op.strata || [])].some(c => typeof c === 'number'))) detail('Column numbers start at 0.','pipeline');
  if (compression === 'zip') deliver('Package all CSVs and the manifest together in one ZIP archive.','compression');
  else if (compression === 'gzip') deliver(`Compress each CSV separately with gzip.`,'compression');
  return [narrative.join(' '), details.join(' '), delivery.join(' ')].filter(Boolean).join('\n\n');
}
