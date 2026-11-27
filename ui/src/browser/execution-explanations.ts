import type {Job} from '../app';
import type {ObservedStep} from './execution-history';
import {reasons, type Kind, type Reason} from './physical-history';

export const fixedStepKinds = ['read', 'write', 'export', 'marker'] as const;
export const explanationLevels = ['Brief', 'Standard', 'Detailed'] as const;

type ExplanationKind = Kind | typeof fixedStepKinds[number];
type Levels = readonly [string, string, string];
type Level = 0 | 1 | 2;

function clip(value: string | number | null | undefined, limit = 64): string | undefined {
  if (value == null) return undefined;
  const text = String(value);
  return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
}

function labelList(values: readonly (string | number)[] = []) {
  const labels = values.slice(0, 3).map(value =>
    typeof value === 'number' ? `column index ${value}` : `“${clip(value)}”`);
  if (values.length > labels.length) labels.push(`${values.length - labels.length} more`);
  return labels.join(', ');
}

function csvSettings(csv: Job['input_csv'] | undefined) {
  return {
    encoding: clip(csv?.encoding),
    delimiter: clip(csv?.delimiter, 2),
    quote: clip(csv?.quote, 2),
    escape: clip(csv?.escape, 2),
    headers: csv?.headers,
  };
}

export function captureExplanationSettings(job: Job) {
  return {
    operations: job.operations.slice(0, 16).map(op => ({
      type: clip(op.type),
      columns: labelList(op.columns),
      strata: labelList(op.strata),
      parts: clip(op.files, 32),
      targets: (op.groups ?? []).slice(0, 3).map(group => ({
        name: clip(group.name) ?? '',
        percent: clip(group.percent, 32) ?? '',
      })),
    })),
    input: csvSettings(job.input_csv),
    output: csvSettings(job.output_csv),
    rowsLimit: clip(job.limits.rows, 32),
    byteLimit: clip(job.limits.bytes, 32),
    zipMember: clip(job.zip_member, 128),
    calculations: (job.calculated_columns ?? []).slice(0, 3).map(column => ({
      name: clip(column.name),
      expression: clip(column.expression, 128),
    })),
    compression: clip(job.compression),
  };
}

type Settings = ReturnType<typeof captureExplanationSettings>;
type Context = {
  settings: Settings;
  step: ObservedStep;
  kind: ExplanationKind;
  groups: string;
  sortOrder: string;
  strata: string;
  parts: string;
  targets: string;
  sources: readonly ObservedStep[];
};
type Explanation = (context: Context) => Levels;

const number = (value: number) => value.toLocaleString();
const units = (value: number, unit: string, plural = unit + 's') => `${number(value)} ${value === 1 ? unit : plural}`;
const quoted = (value: string) => `“${value}”`;

function separator(delimiter: string | undefined) {
  if (delimiter === '\t') return 'tabs';
  if (delimiter === ',') return 'commas';
  return delimiter ? `${quoted(delimiter)} characters` : 'the configured separator';
}

function csvExample(csv: Settings['output']) {
  if (!csv.delimiter || !csv.quote) return '';
  const value = `Paris${csv.delimiter} France`;
  return ` For example, ${quoted(value)} is written as ${csv.quote}${value}${csv.quote} so it stays one field.`;
}

const writeCsv: Explanation = ({settings}) => {
  const {output, rowsLimit, byteLimit} = settings;
  const caps = [rowsLimit && `${number(Number(rowsLimit))} data rows`, byteLimit && `${number(Number(byteLimit))} encoded bytes`].filter(Boolean);
  const lastGroup = [...settings.operations].reverse().find(op => op.type !== 'shuffle');
  const exact = lastGroup?.type === 'balanced' || lastGroup?.type === 'interleaved';
  const cap = caps.length
    ? exact
      ? ` Each part must fit the limit of ${caps.join(' or ')} per CSV.`
      : ` Chopper starts a new chunk for the same group when the next whole row would exceed the limit of ${caps.join(' or ')} per CSV.`
    : '';
  const header = output.headers ? ' The output settings enable column headers.' : '';
  const encoding = output.encoding ? ` in ${output.encoding}` : '';
  const quotes = output.escape
    ? `Inside a quoted field, Chopper prefixes literal quote and escape characters with ${quoted(output.escape)}.`
    : 'Inside a quoted field, Chopper doubles each literal quote character.';
  return [
    `Chopper puts ${separator(output.delimiter)} between fields.${csvExample(output)}${cap}`,
    `Chopper turns each row into CSV${encoding}, quoting fields that contain separators, quotes, or line breaks.${csvExample(output)}${header}${cap}`,
    `Chopper surrounds empty fields and fields containing a separator, quote, or line break with ${output.quote ? quoted(output.quote) : 'the configured quote character'}. ${quotes} It encodes each complete record${encoding}.${cap} The row cap counts data records. The byte cap counts encoded bytes, including headers and a byte-order mark when present.`,
  ];
};

const mergePass: Explanation = ({kind, sortOrder}) => [
  `Chopper takes the next row in order from a batch of sorted chunks and writes it to a new temporary chunk. This leaves fewer chunks for a later merge.`,
  `Chopper combines sorted chunks in batches to limit how many it reads at once. It picks the next row ${sortOrder} and writes that row to a new sorted chunk, which a later merge can read in place of the batch.`,
  `Each active chunk needs a reader and a next-row candidate. Chopper merges batches into temporary chunks to bound how many readers are open. ${kind === 'hierarchical_merge' ? 'A higher-level pass can combine chunks from earlier merges. ' : ''}The row visits count describes work in these passes, including a row each time a pass reads it.`,
];

const balanced: Explanation = ({kind, parts, step}) => {
  if (kind === 'balanced_traversal' && step.operations?.length === 2) {
    return [
      'Chopper splits the incoming rows into consecutive groups, then splits each group again.',
      'Chopper visits the retained rows once and fills the final parts in the order set by both Balanced operations.',
      'Each split gives the first few children of its parent one extra row when needed. The traversal preserves both sets of boundaries and counts the final groups it emits.',
    ];
  }
  const stream = kind === 'fused_balanced' ? 'the shuffled stream' : 'the incoming rows';
  return [
    `Chopper splits ${stream} into ${parts}. It fills one part before starting the next, keeping their sizes as close as possible.`,
    `Chopper divides the row count by the requested number of parts and gives the first few parts one extra row when needed. It takes each part's rows consecutively from ${stream}.`,
    `For each current group, Chopper divides the row count by the number of parts to get a base size. The remainder determines how many of the first parts receive one extra row. Chopper consumes exactly that many rows per part from ${stream}, preserving the sequence set by the preceding steps.`,
  ];
};

const outputCompression: Explanation = ({kind}) => {
  const target = kind === 'gzip_output' ? 'a separate gzip file' : 'a compressed entry in the ZIP archive';
  return [
    `Chopper compresses each CSV into ${target}. Decompressing it gives you the same CSV back.`,
    `Chopper reads each CSV's encoded bytes and compresses them into ${target}. The compressor represents repeated patterns more compactly, with the headers and quoting recoverable when the file is decompressed.`,
    `The DEFLATE compressor receives the already encoded CSV, including any header and line endings. ${kind === 'gzip_output' ? 'Gzip wraps the compressed stream with metadata and an integrity check.' : 'ZIP records each DEFLATE stream as a separate member.'} The step measures the uncompressed bytes accepted by the compressor.`,
  ];
};

const templates = {
  read: ({settings}) => [
    `Chopper reads the CSV a bit at a time and separates fields using ${separator(settings.input.delimiter)}.${csvExample(settings.input)}`,
    `Chopper reads complete CSV records${settings.input.encoding ? ` using ${settings.input.encoding}` : ''}. It uses ${separator(settings.input.delimiter)} between fields${settings.input.headers ? ' and reads the first record as column names' : ''}. A line break inside quotes can belong to the same field.`,
    `Chopper decodes the input bytes and applies the configured delimiter, quote, and escape rules. ${settings.input.headers ? 'It reads the header to establish the column names and expected width. ' : ''}It checks the number of fields in subsequent records. The row count measures data records, including those that span several lines of text.`,
  ],
  resident_sort: ({sortOrder}) => [
    `Chopper sorts the rows in memory ${sortOrder}, then passes them along in that order.`,
    `The rows for this sort fit in its working buffer. Chopper puts them in order ${sortOrder} and passes them straight to the next step.`,
    `Chopper uses sort keys to order the rows ${sortOrder} in memory. When a sort includes both group values and random keys, the group values bring matching rows together and the random key decides their order within each group.`,
  ],
  fisher_yates: () => [
    'Chopper keeps the rows in memory. Starting at the last position, it picks a random row from the positions still being shuffled and swaps it into place.',
    'Chopper works backward from the last position. For each swap, it chooses uniformly from that position and the rows before it. Each swap settles one position.',
    'At position i, Chopper chooses an index uniformly from 0 through i, swaps those rows, then decreases i. This gives each possible permutation the same probability under uniform draws. The rows for the group must fit in the working memory for this shuffle.',
  ],
  grouping: ({groups}) => [
    `Chopper reads the ordered rows and starts a new group when ${groups} changes. It passes the rows along in the order they arrive.`,
    `The upstream order brings matching ${groups} values together. Chopper checks each row against the current group and starts a new one when the value changes. Rows keep their order within the group.`,
    `Chopper uses ${groups} as the group boundary. The sorted stream makes each group consecutive, so Chopper can keep track of one active group and hand rows on one at a time. The next step receives each group with its existing row order.`,
  ],
  write: writeCsv,
  serialize: writeCsv,
  materialize: ({settings}) => [
    `Chopper copies the prepared CSV text from the temporary file ${settings.compression === 'none' ? 'into individual CSV files' : 'into the output writer'}. It also writes a list of the files it creates.`,
    'Chopper recorded where each CSV starts in the prepared data and how many bytes belong to it. It jumps to each starting point and copies exactly that part. The manifest records each CSV’s name, group, and row count.',
    'For each CSV, Chopper seeks to a recorded byte offset and sends exactly the recorded length to its output writer. It copies in bounded blocks. The copied bytes preserve the headers, quoting, and file boundaries set during serialization.',
  ],
  elided: () => [
    'Chopper skips an earlier shuffle when the later full shuffle can put those same rows in a fresh random order on its own.',
    'The two shuffles act on the same groups. A later full shuffle can give each group a fresh random order directly, saving the work of shuffling the same rows twice.',
    'An eligible full shuffle of the same group produces the same distribution of orders as doing both shuffles. Chopper skips the earlier Auto or uniform shuffle and leaves the later shuffle at its original pipeline position.',
  ],
  routed_grouping: ({groups}) => [
    `Chopper reads the temporary files already grouped by ${groups}. It passes one group's rows along before moving to the next file.`,
    `Each temporary file already holds one ${groups} group. Chopper reads the files in group-key order, finishing the current group before going on to the next.`,
    `Chopper reads the routed files sequentially with a single read buffer. The routes have already put matching ${groups} values together. This traversal emits the groups in key order and preserves row order within each group.`,
  ],
  spill: ({sortOrder}) => [
    `Chopper sorts batches ${sortOrder} and saves the sorted batches to temporary files for a merge.`,
    `Chopper sorts each batch ${sortOrder} and writes it to temporary storage. The merge can then read the batches a little at a time, keeping only part of the data in memory.`,
    `Chopper puts each batch in order ${sortOrder}, then writes it as a sorted chunk. A merge can pull the next row from those chunks in the same sort order. The tradeoff is extra temporary reads and writes in exchange for a smaller working set.`,
  ],
  merge: mergePass,
  hierarchical_merge: mergePass,
  merge_traversal: ({sortOrder}) => [
    'Chopper looks at the next row in each sorted chunk and picks the one that belongs next. It passes that row along and moves one row forward in the chunk it picked from.',
    `Chopper looks at the next row in each chunk, picks the one that comes first ${sortOrder}, and advances the chunk it picked from. It passes rows straight to the next step as it goes, saving the work of writing another temporary file.`,
    `Chopper keeps a read buffer for each active chunk and uses a priority queue to find the next row ${sortOrder}. After taking that row, it advances only the chunk it came from. The following step receives an ordered stream and can start as soon as rows arrive.`,
  ],
  routing: ({groups}) => [
    `Chopper looks at each row's ${groups} and sends it to a temporary file for that group.`,
    `Chopper keeps a small set of temporary writers, one for each ${groups} group it encounters. It looks up the writer for each incoming row and appends the row there.`,
    `Chopper maps each ${groups} key to its writer, appending rows in encounter order within the group. It bounds the number of writers and their memory. When the routing conditions change, it can hand the existing files to the sorter.`,
  ],
  fallback: ({step, sources}) => {
    const prepared = step.reasons?.prepared_shuffle_admission;
    const routed = sources.some(source => source.kind === 'routing') || step.reasons?.routing_order || step.reasons?.routing_writers || step.reasons?.routing_memory;
    if (prepared && !routed) return [
      'Chopper uses the separate allocation and shuffle steps when the combined path cannot reserve enough working memory.',
      'Preparing the combined allocation and shuffle required additional working memory. Chopper switches to separate steps on the retained rows when that reservation is denied.',
      'A memory admission check rejected the prepared path before it emitted rows. Chopper can use the retained group to run allocation and shuffle separately.',
    ];
    return routed && !prepared ? [
      'Chopper finishes the files it was grouping directly and hands the remaining rows to the sorter.',
      'Chopper closes its temporary grouping writers and switches the remaining rows to sorting. A merge can use the files that were already ordered alongside the new sorted chunks.',
      'Chopper hands its completed grouping files to the sorter as an ordered input. Newly encountered rows go through the normal sort buffer. This keeps the work already written available to later merges.',
    ] : [
      'Chopper switches to another execution path for this operation.',
      'Chopper hands the operation to its fallback path. The following observed steps show the work that path does.',
      'A fallback records a strategy transition. The linked steps show whether the new path uses sorting, existing files, or another execution step.',
    ];
  },
  reuse: ({groups}) => [
    `The temporary files already hold one ${groups} group each. Chopper reuses them as ordered input to a merge.`,
    `Rows in each routed file are already in the order the sorter needs. Chopper reads these files in ${groups} key order as one input to a later merge, saving another sort of those rows.`,
    'Each routed file has one key and rows in encounter order. The files are listed by key, so together they form one sorted run that needs only one file reader at a time.',
  ],
  exact_membership: ({targets, strata, sources}) => {
    const shuffled = sources.some(source =>
      (source.kind === 'fisher_yates' || source.kind === 'resident_sort' || source.kind === 'merge_traversal') &&
      (source.operations?.length ?? 0) > 1);
    const scope = strata ? ` separately for each combination of ${strata}` : '';
    const assignment = shuffled
      ? 'It fills the groups by taking consecutive ranges from the shuffled stream.'
      : 'It chooses randomly from the remaining slots and uses up one slot for each assigned row.';
    return [
      `Chopper works out the whole-row totals for ${targets}${scope}. ${assignment}`,
      `Chopper rounds down each requested share and gives the leftover slots to the groups with the largest fractions. It does this${scope || ' within each current group'}. ${assignment}`,
      `Chopper uses largest-remainder rounding for ${targets}${scope}. Configured group order breaks ties. ${assignment} Each group's final count follows the resulting quota.`,
    ];
  },
  probabilistic_membership: ({targets, strata}) => [
    `Chopper draws a random number for each row and uses your requested chances, ${targets}, to choose its group.`,
    `Chopper gives each group a range of numbers that reflects its requested share, ${targets}. It assigns each row according to where its draw lands. The actual totals can vary from the requested percentages.`,
    `Chopper derives a pseudorandom draw from the row's original ID and this allocation's random context${strata ? `, using ${strata} as stratum fields` : ''}. It maps the draw through cumulative weights for ${targets}. The draw determines membership while preserving encounter order inside each allocation.`,
  ],
  stratification: ({strata}) => [
    `Chopper puts matching ${strata || 'stratum'} values together so it can calculate whole-row allocation targets for each set.`,
    `Chopper gathers and counts rows that match on ${strata || 'the stratum columns'}. The exact allocation uses those counts to work out its quotas separately for each stratum.`,
    `Within each current parent group, Chopper groups by ${strata || 'the stratum columns'} and records each stratum's row count. The allocator uses each count for its own largest-remainder calculation. The named allocations then receive rows from across the strata.`,
  ],
  dataset_materialize: ({sources}) => sources.some(source => source.kind === 'shared_ranges') ? [
    'Chopper saves the starting positions and row counts for the groups so the next step can read from the existing temporary file.',
    'Chopper records where each group starts and how many rows it contains. The next step can use this catalog to read just the relevant range of the shared row file.',
    'The catalog gives each group a byte offset, row count, and pipeline lineage. The next stage uses those records to read groups from the existing temporary data.',
  ] : [
    'Chopper saves grouped rows in a temporary file and keeps a list of where each group starts and how many rows it contains.',
    'Chopper writes the rows in its working format, then records each group’s position and row count. The next step can open one group at a time and read just the rows it needs.',
    'Chopper writes length-framed records into a shared temporary data file. A separate catalog records each group’s starting byte offset, row count, and pipeline lineage so later operations can seek to that group and read its rows in order.',
  ],
  shared_ranges: ({parts}) => [
    `Chopper reads the stored row lengths to find where ${parts} begin. The next step can read those parts from the same file.`,
    `To split the rows into ${parts}, Chopper calculates each part's size and uses the stored row lengths to work out where it starts. It saves those positions and shares the earlier temporary row file.`,
    'Chopper calculates balanced row counts, then adds stored record lengths to find each child group’s byte offset. Each child records an offset and a row count while sharing the original row data.',
  ],
  interleaved_membership: ({parts}) => [
    `Chopper gives each row to the next of ${parts}, then starts the cycle again.`,
    `Chopper assigns rows in a repeating cycle across ${parts}. When it reaches the last part, it starts again at part 1. The rows assigned to each part keep the order they arrived in.`,
    `Within each current group, Chopper takes the zero-based position modulo the number of parts to select a destination. It emits ${parts} in numeric order and preserves encounter order within each part.`,
  ],
  balanced_traversal: balanced,
  fused_balanced: balanced,
  gzip_input: () => [
    'Chopper unpacks the gzip file a little at a time and passes the bytes along so it can read the rows.',
    'Chopper recognizes gzip from the file signature. It reads compressed data as needed, expands it, and passes the resulting CSV bytes to the reader.',
    'The gzip decoder returns decompressed bytes to the CSV reader. The CSV reader then decodes the characters and parses records. The bytes for this step measure decompression output before character decoding.',
  ],
  zip_input: ({settings}) => {
    const entry = settings.zipMember ? quoted(settings.zipMember) : 'the selected CSV entry';
    return [
      `Chopper opens ${entry} inside the ZIP and reads its contents a little at a time.`,
      `Chopper finds ${entry} in the archive and reads it directly, decompressing the bytes if the entry is compressed.`,
      `Chopper uses the archive index to locate ${entry}. A Deflate entry goes through a decompressor and a Stored entry supplies the CSV bytes directly. The step counts the returned bytes before CSV character decoding.`,
    ];
  },
  calculation: ({settings}) => {
    const names = settings.calculations.map(value => value.name).filter(Boolean).join(', ');
    const formula = settings.calculations[0]?.expression;
    return [
      `Chopper runs ${names ? `the formulas for ${names}` : 'your formulas'} and adds the results to each row.`,
      `Chopper finds the referenced fields in each row and evaluates your calculated columns.${formula ? ` For example, it evaluates ${quoted(formula)} for ${quoted(settings.calculations[0].name ?? 'a calculated column')}.` : ''} The remaining steps can use the results.`,
      'Chopper resolves formula references against the input schema and evaluates columns in dependency order, so formulas can use earlier results. The values travel with the rows. The CSV writer uses the order in which you defined the columns.',
    ];
  },
  gzip_output: outputCompression,
  zip_deflate: outputCompression,
  zip_archive: () => [
    'Chopper puts the compressed CSVs and their file list into outputs.zip, then writes an index so ZIP readers can find the entries.',
    'Chopper gives each compressed CSV its own named ZIP entry. It adds manifest.jsonl and writes an index a ZIP reader uses to locate each entry.',
    'Chopper assembles the CSV members and the manifest, then writes the ZIP central directory. The archive byte count includes the compressed entries and the ZIP structure. The entry count includes the manifest.',
  ],
  export: ({settings}) => {
    const files = settings.compression === 'zip' ? 'outputs.zip and the separate manifest' : 'the result files and the manifest';
    return [
      `Chopper saves ${files} in your results folder. It counts each file once the browser closes it.`,
      `The browser writes ${files} into your results folder. Chopper counts a file as saved when its writer closes successfully. Once all files close, Chopper can confirm the export.`,
      `The browser writes ${files} in blocks and waits for each writer's close() to succeed before counting that file. The resulting count is stored in CHOPPER-COMPLETE.json in the next step.`,
    ];
  },
  marker: () => [
    'After the files close, Chopper writes a small file saying the export is complete. It opens that file again to check what was saved.',
    'After all the destination files close, Chopper writes CHOPPER-COMPLETE.json with the number of saved files. It reads the marker back to verify that it matches the expected record.',
    'Chopper compares the count of closed destination files with the expected count, then writes and closes the versioned completion record. It reads the marker back and checks both its size and content before confirming the export.',
  ],
} satisfies Record<ExplanationKind, Explanation>;

const reasonText = {
  sort_buffer_limit: 'the next row would have exceeded the sort buffer limit',
  sort_reservation: 'the sorter could not reserve enough working memory for the next row',
  input_reservation: 'preparing more input for the sort needed more working memory',
  final_batch: 'the sorter was finishing an external sort',
  routing_order: 'rows arrived out of order for their group',
  routing_writers: 'a new group would have exceeded the writer limit',
  routing_memory: 'a new group would have exceeded the routing memory limit',
  prepared_shuffle_admission: 'the combined allocation and shuffle could not reserve enough working memory',
} satisfies Record<Reason, string>;

export function explainStep(
  settings: Settings,
  step: ObservedStep,
  level: Level,
  status: string,
  sources: readonly ObservedStep[],
): string[] {
  const kind = step.kind ?? fixedStepKinds[step.id];
  if (!kind) return [];
  const operations = (step.operations ?? (step.operation ? [step.operation] : []))
    .map(id => settings.operations[id - 1]);
  const partition = operations.find(op => op?.type === 'partition')?.columns ?? '';
  const allocation = operations.find(op => op?.type === 'assign' || op?.type === 'assign_probabilistic');
  const strata = allocation?.strata ?? '';
  const grouping = step.role ? strata : partition;
  const groups = grouping || 'the grouping key';
  const shuffled = !step.role && operations.some(op => op?.type === 'shuffle');
  const sortOrder = shuffled
    ? partition ? `by ${partition} and then by a random value within each group` :
      operations[0]?.type?.startsWith('assign') ? 'by allocation and then by a random value within each allocation' : 'by a random value for each row'
    : grouping ? `by ${grouping}` : 'in the selected sort order';
  const count = operations.find(op => op?.parts)?.parts;
  const parts = count ? `${number(Number(count))} parts` : 'the requested parts';
  const targets = allocation?.targets.map(group => `${quoted(group.name)} at ${group.percent}%`).join(', ') || 'the requested shares';
  const copy = templates[kind]({settings, step, kind, groups, sortOrder, strata, parts, targets, sources})[level];
  const text = [copy];
  const confirmed = status === 'completed' || (step.completed_attempts ?? 0) > 0;
  const prefix = status === 'completed' ? 'In this run' : 'In confirmed attempts so far';
  const countText = kind === 'spill' && step.runs ? units(step.runs, 'sorted chunk')
    : kind === 'export' && step.files ? units(step.files, 'closed result file')
    : kind === 'zip_archive' && step.runs ? units(step.runs, 'archive entry', 'archive entries')
    : kind === 'shared_ranges' && step.rows ? units(step.rows, 'row length')
    : ['read', 'resident_sort', 'fisher_yates', 'calculation', 'serialize', 'write', 'grouping'].includes(kind) && step.rows ? units(step.rows, 'data row')
    : '';
  if (confirmed && countText) text.push(`${prefix} Chopper counted ${countText} at this step.`);
  if (confirmed && (kind === 'exact_membership' || kind === 'probabilistic_membership') && allocation?.targets.length) {
    const membership = allocation.targets.flatMap((group, i) =>
      step.memberships?.[i] === undefined ? [] : [`${quoted(group.name)} received ${units(step.memberships[i], 'row')}`]);
    if (membership.length) text.push(`${prefix} ${membership.join(', ')}.`);
  }
  for (const reason of reasons) {
    const attempts = step.reasons?.[reason];
    if (attempts && kind === 'spill') {
      text.push(`Chopper wrote ${units(attempts, 'sorted chunk')} because ${reasonText[reason]}.`);
    } else if (attempts && kind === 'fallback') {
      text.push(`Chopper switched paths ${units(attempts, 'time')} because ${reasonText[reason]}.`);
    }
  }
  return text;
}

