import {sourceIdentity,resultOrigin,belongsToSource,type ResultOrigin} from './result-ownership';
import {operationName} from './step-labels';
import {browserApi,configureBrowserUI,invalidateBrowserDraft} from './browser/client';
import {groupErrors,percentageUnits} from './plan';
import {bindColumnPickers,pickerMarkup,type ColumnSchema} from './column-picker';
import {populateMemory,updateMemory,readMemory} from './memory';
import {createSizeControl,populateSize,readSize,type SizeUnit} from './size-units';
import {configurePlanLinks} from './plan-links';
import {configureValidation} from './validation';
import {configureHostedWorkspace} from './hosted-workspace';

export {};
type Csv = { encoding: string; headers: boolean; delimiter: string; quote: string; escape: string | null; line_ending: string; bom: boolean; skip_empty_lines: boolean };
type Operation = { type: string; files?: number; columns?: (string | number)[]; groups?: {name: string; percent: string}[]; strata?: (string | number)[]; strategy?: string };
export type Job = {version: number; input: string; output: string; zip_member: string | null; input_csv: Csv; output_csv: Csv; compression: string; operations: Operation[]; limits: {rows: number | null; bytes: number | null; compressed_bytes: number | null}; resources: {grouping?: 'auto' | 'sort'; workers: number; memory_mb: number | 'auto'; max_files: number; max_record_bytes: number; temp_dir: string | null; temp_bytes: number | null}; full_shuffle_rng?: 'blake3_counter_v1'; full_shuffle_algorithm?: 'adaptive_v1'};
export type Analysis = {algorithm_version?: string; execution?: {replay_guarantee: string; plan_version: number; records: number; rng_version: string; plan_digest_blake3: number[]}; diagnostics?: {routing_reused_runs?: number; resident_sorts: number; routed_groupings: number; routing_fallbacks: number; sort_runs: number; merge_operations: number; peak_workspace_reserved_bytes: number}; column_values?: {column: number; values: string[]; frequencies?:Record<string,number>; truncated: boolean}[]; analysis_seconds: number; peak_temp_bytes: number; memory_budget_bytes: number; workers: number; rows: number; columns: number; header: string[] | null; preview: string[][]; groups: number; output_files: number; output_csv_bytes: number; temp_bytes: number; seed: string; accuracy: string; warnings: string[]; stages: {operation: number; input_groups: number; output_groups: number}[]};
export type InputProfile = {rows:number;columns:number;cache_hit:boolean;seconds:number;accuracy:string;header:string[]|null;column_values:{column:number;values:string[];frequencies?:Record<string,number>;truncated:boolean;distinct:number;distinct_exact:boolean}[];stages:{operation:number;strategy:string;input_distinct_keys:number|null;distinct_exact:boolean}[]};
export type State = {origins?:{profile?:ResultOrigin;analysis?:ResultOrigin};profile?:InputProfile|null;status: string; progress: {phase: string; rows: number; temp_bytes: number}; analysis: Analysis | null; error: string | null; output: string | null};
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const value = (id: string) => $<HTMLInputElement>(id).value;
const setValue = (id: string, v: unknown) => { $<HTMLInputElement>(id).value = v == null ? '' : String(v); };
const escape = (s: unknown) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const format = (n: number) => n.toLocaleString();
const size = (n: number) => n >= 1073741824 ? `${(n/1073741824).toFixed(2)} GiB` : n >= 1048576 ? `${(n/1048576).toFixed(1)} MiB` : n >= 1024 ? `${(n/1024).toFixed(1)} KiB` : `${n} B`;
let inputSelectionRevision=0;
let job: Job; let status = 'idle'; let dirty = true; let editRevision = 0; let lastAnalysis = '';
let requestEpoch=0,activeCommands=0,pollSerial=0,lastAppliedPoll=0;
async function api<T = unknown>(path: string, data?: unknown): Promise<T> {
  const mutation=['profile','run-direct','cancel'].includes(path);
  if(mutation){requestEpoch++;activeCommands++;}
  try {
  return await browserApi<T>(path,data);
  } finally {if(mutation){activeCommands--;requestEpoch++;}}
}
function error(e: unknown) { $('error').textContent = e instanceof Error ? e.message : String(e); $('error').hidden = false; }
let columnSchema: ColumnSchema | null = null;
let columnMessage = 'Choose an input file to load its columns.';
let columnSource = '', columnRequest = 0;
function sourceKey() { return sourceIdentity(inputSelectionRevision,{input:value('input'),zip_member:value('zip-member')||null,input_csv:readCsv('input')}); }
function renderPickers() {
  $('operations').querySelectorAll<HTMLElement>('[data-column-field]').forEach(picker=>{
    const step=Number(picker.closest<HTMLElement>('[data-step]')!.dataset.step);
    const field=picker.dataset.columnField as 'columns'|'strata';
    picker.innerHTML=new DOMParser().parseFromString(pickerMarkup(field,job.operations[step][field]||[],step,columnSchema,columnMessage),'text/html').body.firstElementChild!.innerHTML;
  });
}
async function loadColumns() {
  const request=++columnRequest;
  columnSource=sourceKey();columnSchema=null;$('preview-card').hidden=true;hostedWorkspace?.preview(null);
  columnMessage=value('input')?'Loading input columns?':'Choose an input file to load its columns.';
  renderPickers();
  if(!value('input'))return;
  try {
    const schema=await api<ColumnSchema & {preview:string[][]}>('preview',{...job,input:value('input'),zip_member:value('zip-member')||null,input_csv:readCsv('input')});
    if(request!==columnRequest||columnSource!==sourceKey())return;
    renderPreview(schema);hostedWorkspace?.preview(schema);columnSchema=schema;columnMessage=schema.columns?'':'The input file has no columns.';
  } catch(e) {if(request!==columnRequest||columnSource!==sourceKey())return;columnMessage=e instanceof Error?e.message:String(e);$('preview').textContent=`Input preview unavailable: ${columnMessage}`;$('preview-card').hidden=false;hostedWorkspace?.preview(null,true);}
  renderPickers();updateFields();validation.update();
}
function csvForm(prefix: string, settings: Csv) {
  const encodings = ['utf-8','utf-16le','utf-16be','windows-1252','windows-1250','windows-1251','windows-1253','windows-1254','windows-1255','windows-1256','windows-1257','windows-1258','Shift_JIS','GBK','Big5','EUC-KR','ISO-8859-2'];
  if (!encodings.some(e=>e.toLowerCase()===settings.encoding.toLowerCase())) encodings.push(settings.encoding);
  $(prefix+'-csv').innerHTML = `<label>Encoding<select data-csv="encoding">${encodings.map(e=>`<option value="${escape(e)}" ${e.toLowerCase()===settings.encoding.toLowerCase()?'selected':''}>${escape(e)}</option>`).join('')}</select></label><div class="grid2"><label>Delimiter<input data-csv="delimiter" maxlength="1" value="${escape(settings.delimiter)}"></label><label>Quote<input data-csv="quote" maxlength="1" value="${escape(settings.quote)}"></label><label>Escape<input data-csv="escape" maxlength="1" placeholder="Double quotes" value="${escape(settings.escape||'')}"></label><label>Line ending<select data-csv="line_ending"><option value="lf" ${settings.line_ending==='lf'?'selected':''}>LF</option><option value="crlf" ${settings.line_ending==='crlf'?'selected':''}>CRLF</option></select></label></div>${[['headers','Header row'],['bom','Byte-order mark'],['skip_empty_lines','Skip bare empty lines']].map(([key,label])=>`<label class="check-label"><input type="checkbox" data-csv="${key}" ${(settings as unknown as Record<string,boolean>)[key]?'checked':''}>${label}</label>`).join('')}`;
  for(const key of prefix==='input'?['line_ending','bom']:['skip_empty_lines']){
    const field=$(prefix+'-csv').querySelector<HTMLInputElement>('[data-csv="'+key+'"]')!;
    field.disabled=true;
    const note=document.createElement('small');note.textContent=prefix==='input'?'Detected automatically while reading.':'This setting applies to input parsing only.';
    field.closest('label')!.append(note);
    field.closest('label')!.hidden=true;
  }

  if(prefix==='input'){const note=document.createElement('small');note.className='csv-auto-note';note.textContent='Line endings and byte-order marks are detected automatically.';$(prefix+'-csv').append(note);}
}
function readCsv(prefix: string): Csv {
  const record: Record<string, unknown> = {};
  $(prefix+'-csv').querySelectorAll<HTMLInputElement>('[data-csv]').forEach(el=>{record[el.dataset.csv!] = el.type==='checkbox'?el.checked:el.value;});
  record.escape ||= null; return record as unknown as Csv;
}
const operationIds = new WeakMap<Operation,number>();
let nextOperationId = 0;
function operationId(op: Operation) {
  if(!operationIds.has(op))operationIds.set(op,++nextOperationId);
  return operationIds.get(op)!;
}
function operationNote(title:string,text:string){
  return `<details class="step-help"><summary>${title}</summary><small>${text}</small></details>`;
}
function renderOps() {
  finishStepDrag();
  const active=document.activeElement as HTMLElement|null;
  const activeOperation=active?.closest<HTMLElement>('[data-operation-id]')?.dataset.operationId;
  const activeField=active?.dataset.field;
  $('operations').innerHTML = job.operations.length ? job.operations.map((op,i)=>{
    let fields = '';
    if(op.type==='balanced'||op.type==='interleaved') fields = `<label>Number of equal parts<input data-field="files" type="number" min="1" value="${op.files}"></label><small>Counts differ by at most one. Fewer rows than parts is an error. ${op.type==='interleaved'?'Rows alternate between parts; concatenating files will not restore input order.':'Each part contains a consecutive range of rows.'}</small>`;
    if(op.type==='partition') fields = pickerMarkup('columns',op.columns||[],i,columnSchema,columnMessage);
    if(op.type==='assign'||op.type==='assign_probabilistic') fields = `<fieldset class="group-builder"><legend>Named percentages</legend>${(op.groups||[]).map((g,j)=>`<div class="group-row" data-group="${j}"><label>Group name<input data-group-field="name" required value="${escape(g.name)}" placeholder="e.g. treatment"></label><label>Percent<input data-group-field="percent" required inputmode="decimal" value="${escape(g.percent)}" placeholder="80"></label><button type="button" class="text-button" data-action="remainder" aria-label="Fill remaining percentage for group ${j+1}">Fill remainder</button><button type="button" class="icon-button" data-action="remove-group" aria-label="Remove group ${j+1}" ${(op.groups?.length||0)<=1?'disabled':''}>×</button></div>`).join('')}<button type="button" class="secondary" data-action="add-group" ${(op.groups?.length||0)>=1024?'disabled':''}>+ Add group</button><small data-group-feedback></small></fieldset>${pickerMarkup('strata',op.strata||[],i,columnSchema,columnMessage)}${operationNote('Allocation & stratification',op.type==='assign_probabilistic'?'Each row is assigned independently using the target percentages. Counts are approximate, including within strata; small strata may have no rows in a destination. Membership is random and row order is preserved.':'Stratification applies these percentages separately within every combination of the selected column values. For example, stratifying by country keeps an 80% / 20% allocation within each country, rounded to whole rows. Membership is random; row order is preserved.')}`;
    if(op.type==='shuffle') fields = `<div><label>Strategy<select data-field="strategy">${[['auto','Automatic (full shuffle; recommended)'],['uniform','Uniform (random-key sort)'],['fisher_yates','Uniform in memory (Fisher–Yates v1)']].map(([v,l])=>`<option value="${v}" ${op.strategy===v?'selected':''}>${l}</option>`).join('')}</select></label></div>${operationNote('How shuffle strategies work','Automatic uses a full external-capable shuffle and combines compatible steps. Output order may vary with resources and execution plan. Explicit Fisher–Yates requires each group to fit in memory; oversized groups fail.')}`;
    const split=op.type==='balanced'||op.type==='interleaved';
    const assignment=op.type==='assign'||op.type==='assign_probabilistic';
    const name=split?'Split into equal parts':assignment?'Assign groups by percentage':operationName(op.type);
    if(split||assignment){
      const modes=split?[['balanced','Consecutive rows'],['interleaved','Alternating rows']]:[['assign','Exact counts'],['assign_probabilistic','Approximate counts']];
      fields=`<fieldset class="group-builder mode-choices"><legend>${split?'Row distribution':'Group counts'}</legend>${modes.map(([type,label])=>`<label class="check-label"><input type="radio" name="operation-mode-${operationId(op)}" data-field="type" value="${type}" ${op.type===type?'checked':''}><span>${label}</span></label>`).join('')}</fieldset>${fields}`;
    }
    const actionIcon=(action:string)=>`<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${action==='up'?'m6 14 6-6 6 6':action==='down'?'m6 10 6 6 6-6':'m6 6 12 12M18 6 6 18'}"/></svg>`;

    const descriptions:Record<string,string>={partition:'Create groups from matching column values',balanced:'Divide each group into consecutive parts',interleaved:'Distribute rows cyclically across parts',assign:'Allocate rows using exact percentage quotas',assign_probabilistic:'Allocate each row independently by probability',shuffle:'Randomize row order within each group'};
    const paths:Record<string,string>={partition:'M4 4h16v5H4zM4 15h6v5H4zM14 15h6v5h-6zM7 9v6m10-6v6',balanced:'M4 5h16M4 12h16M4 19h16',interleaved:'M4 5h16M4 12h16M4 19h16',assign:'M4 6h6v12H4zM14 6h6v5h-6zM14 15h6v3h-6z',assign_probabilistic:'M4 6h6v12H4zM14 6h6v5h-6zM14 15h6v3h-6z',shuffle:'M3 5h3c5 0 7 14 12 14h3m-4-4 4 4-4 3M3 19h3c5 0 7-14 12-14h3m-4-3 4 3-4 4'};
    const identity=`<span class="operation-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[op.type]||paths.partition}"/></svg></span><span class="step-identity"><span class="step-title">${name}</span><span class="step-description">${descriptions[op.type]||''}</span></span>`;
    return `<div class="step" data-step="${i}" data-operation-id="${operationId(op)}"><div class="step-head"><button type="button" class="step-grip" data-step-grip draggable="true" aria-label="Reorder step ${i+1}: ${name}" aria-describedby="pipeline-reorder-help" title="Drag to reorder, or use Up and Down arrow keys"><svg viewBox="0 0 16 24" aria-hidden="true" fill="currentColor"><circle cx="5" cy="5" r="1.4"/><circle cx="11" cy="5" r="1.4"/><circle cx="5" cy="12" r="1.4"/><circle cx="11" cy="12" r="1.4"/><circle cx="5" cy="19" r="1.4"/><circle cx="11" cy="19" r="1.4"/></svg></button><span class="step-index">${String(i+1).padStart(2,'0')}</span>${identity}<button type="button" class="icon-button" data-action="up" title="Move earlier" aria-label="Move step ${i+1} up" ${i===0?'disabled':''}>${actionIcon('up')}</button><button type="button" class="icon-button" data-action="down" title="Move later" aria-label="Move step ${i+1} down" ${i===job.operations.length-1?'disabled':''}>${actionIcon('down')}</button><button type="button" class="icon-button" data-action="remove" title="Remove step" aria-label="Remove step ${i+1}">${actionIcon('remove')}</button></div><div class="step-fields">${fields}</div></div>`;
  }).join('') : '<div class="empty-steps">Add a step to group, split, assign or shuffle rows. File limits also work on their own.</div>';
  updateGroupValidation();
  if(activeOperation&&activeField)$('operations').querySelector<HTMLElement>(`[data-operation-id="${activeOperation}"] [data-field="${activeField}"]${activeField==='type'?':checked':''}`)?.focus();
}
function updateGroupValidation() {
  $('operations').querySelectorAll<HTMLElement>('[data-step]').forEach(step=>{
    const op=job.operations[Number(step.dataset.step)];if(op.type!=='assign'&&op.type!=='assign_probabilistic')return;
    const errors=groupErrors(op.groups||[]);
    step.querySelectorAll<HTMLInputElement>('[data-group-field]').forEach(el=>el.setCustomValidity(''));
    step.querySelector<HTMLInputElement>('[data-group-field="percent"]')?.setCustomValidity(errors.join(' '));
    const feedback=step.querySelector<HTMLElement>('[data-group-feedback]')!;
    feedback.textContent=errors.length?errors.join(' '):(op.type==='assign_probabilistic'?'Total target: 100%. Actual counts may vary.':'Total: 100%. Exact percentages, rounded to whole rows.');
    feedback.classList.toggle('invalid-groups',!!errors.length);
  });
}
const unitFields=new Map(['max-bytes','compressed-bytes','temp-bytes','max-record','memory'].map(id=>[id,createSizeControl($<HTMLInputElement>(id),id==='memory'?['MiB','GiB']:['B','KB','MB','GB','TB','KiB','MiB','GiB','TiB'] as SizeUnit[])]));
const memoryControls={mode:$<HTMLSelectElement>('memory-mode'),manual:$<HTMLInputElement>('memory'),unit:unitFields.get('memory')!.unit};
const readSizeField=(id:string)=>readSize(unitFields.get(id)!);
const sizeText=(id:string)=>value(id)?`${value(id)} ${unitFields.get(id)!.unit.value}`:'';
function populate() {
  validation.reset();
  setValue('input',job.input);setValue('output',job.output);setValue('zip-member',job.zip_member);setValue('compression',job.compression);
  setValue('max-rows',job.limits.rows);populateSize(unitFields.get('max-bytes')!,job.limits.bytes);populateSize(unitFields.get('compressed-bytes')!,job.limits.compressed_bytes);
  setValue('grouping',job.resources.grouping || 'auto');setValue('workers',job.resources.workers);populateMemory(memoryControls,job.resources.memory_mb);setValue('max-files',job.resources.max_files);populateSize(unitFields.get('max-record')!,job.resources.max_record_bytes);setValue('temp-dir',job.resources.temp_dir);populateSize(unitFields.get('temp-bytes')!,job.resources.temp_bytes);
  csvForm('input',job.input_csv);csvForm('output',job.output_csv);renderOps();markDirty();void loadColumns();
}
function readJob(): Job {
  return {...job,input:value('input'),output:value('output'),zip_member:value('zip-member')||null,compression:value('compression'),
    input_csv:readCsv('input'),output_csv:readCsv('output'),limits:{rows:value('max-rows')?Number(value('max-rows')):null,bytes:readSizeField('max-bytes'),compressed_bytes:value('compression')==='none'?null:readSizeField('compressed-bytes')},
    resources:{...job.resources,grouping:value('grouping') as 'auto' | 'sort',workers:Number(value('workers')),memory_mb:readMemory(memoryControls),max_files:Number(value('max-files')),max_record_bytes:readSizeField('max-record')!,temp_dir:value('temp-dir')||null,temp_bytes:readSizeField('temp-bytes')}};
}
function updateFields() {
  updateMemory(memoryControls);
  const zip = columnSchema?.input_is_zip ?? (/\.zip$/i.test(value('input')) || !!value('zip-member'));
  $('zip-member').closest('label')!.hidden = !zip;
  $<HTMLInputElement>('zip-member').disabled=!zip;
  const uncompressed=value('compression')==='none';
  $('compressed-bytes').closest<HTMLElement>('.quantity-field')!.hidden=uncompressed;
  unitFields.get('compressed-bytes')!.unit.disabled=uncompressed;
  $<HTMLInputElement>('compressed-bytes').disabled=uncompressed;
  const automaticMemory=value('memory-mode')==='auto';
  $('manual-memory-help').hidden=!automaticMemory;
  $('memory').setAttribute('aria-describedby',automaticMemory?'memory-help manual-memory-help':'memory-help');
  $<HTMLButtonElement>('add-operation').disabled=(job?.operations.length||0)>=64;
}
function markDirty() {
  profileDirty=!belongsToSource(profileOrigin,sourceKey());if(profileDirty)$('input-profile').hidden=true;
  if(inspectionSource!==sourceKey())hostedWorkspace?.values([],null,'');
  if(lastProfileData&&!profileDirty&&status==='profiled')renderProfile(lastProfileData);
  updateFields();
  editRevision++;invalidateBrowserDraft(sourceKey()); dirty = true; updateRunControl();
  if(job) planLinks.render(job.operations,{rows:value('max-rows'),bytes:sizeText('max-bytes'),compressed:sizeText('compressed-bytes')},value('compression'));
  const finalGrouping = job?.operations.filter(op=>op.type!=='shuffle').at(-1);
  const conflict = ['balanced','interleaved'].includes(finalGrouping?.type||'') && !!(value('max-rows')||value('max-bytes'));
  $('conflict').hidden = !conflict; $('conflict').textContent = 'Equal parts and hard limits can conflict. Processing will reject balanced groups that cannot fit without extra files.';
  updateDraft();validation.update();
}
function updateDraft() {
  if(!job)return;
  let draft: Job | null = null;
  try { draft=readJob(); } catch { /* Keep invalid intermediate input editable. */ }
  hostedWorkspace?.draft(draft,job.operations.length);
  planLinks.summary(job.operations);
}
function renderProfile(p:InputProfile,showValues=true){
  $('input-profile').hidden=false;$('empty-plan').hidden=true;
  let changed=true;try{changed=profileOrigin?.configuration!==JSON.stringify(readJob());}catch{/* Keep incomplete edits editable. */}
  if(showValues){inspectionSource=profileOrigin?.source??null;hostedWorkspace?.values(p.column_values,p.header,'Full-file input analysis',p.rows);}
  const key=JSON.stringify([p,changed]);if(key===lastProfile)return;lastProfile=key;
  $('input-profile').innerHTML=`<h3>Input analysis</h3><dl class="profile-facts"><div><dt>Records · exact</dt><dd>${format(p.rows)}</dd></div><div><dt>Columns</dt><dd>${format(p.columns)}</dd></div></dl><p class="profile-duration">Scanned in ${p.seconds.toFixed(2)} s${p.cache_hit?' · reused profile':''}</p>${changed?'<p class="profile-context">Input unchanged. Pipeline estimates reflect the earlier configuration.</p>':''}${p.stages.length?`<details><summary>Pipeline estimates${changed?' · previous settings':''}</summary><ul class="profile-stages">${p.stages.map(stage=>`<li>Step ${stage.operation}: ${escape(stage.strategy)}${stage.input_distinct_keys===null?'':` · ${stage.distinct_exact?'':'~'}${format(stage.input_distinct_keys)} distinct keys (${stage.distinct_exact?'exact':'estimated'})`}</li>`).join('')}</ul></details>`:''}<details><summary>Coverage & methodology</summary><p>${escape(p.accuracy)}</p><p>Statistics cover up to 64 selected columns. Value lists show at most 100 values per column and 256 KiB in total. Run reports the final exact group counts and file sizes. Analyzing input does not create output files.</p></details>`;
}
function renderAnalysis(a: Analysis) {
  if(belongsToSource(analysisOrigin,sourceKey())){inspectionSource=analysisOrigin?.source??null;hostedWorkspace?.values(a.column_values||[],a.header,'Completed output analysis',a.rows);}
  const key = JSON.stringify(a); if(key===lastAnalysis) return; lastAnalysis=key;
  $('empty-plan').hidden=true; $('analysis').hidden=false;
  const facts=(items:[string,string][])=>`<dl class="analysis-facts">${items.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>`;
  const metrics=[[format(a.rows),'Input rows'],[format(a.output_files),'Output CSVs'],[format(a.groups),'Logical groups'],[size(a.output_csv_bytes),'CSV bytes · exact'],[`${a.analysis_seconds.toFixed(1)} s`,'Processing time'],[format(Math.round(a.rows/Math.max(a.analysis_seconds,0.001))),'Avg rows/s']];
  const d=a.diagnostics;
  $('analysis').innerHTML=`<div class="stat-grid">${metrics.map(([value,label])=>`<div class="stat"><strong>${value}</strong><span>${label}</span></div>`).join('')}</div><p class="analysis-note">${escape(a.accuracy)}</p>
    ${a.warnings.length?`<section class="analysis-warnings" aria-label="Warnings"><h3>Warnings <span>${format(a.warnings.length)}</span></h3><ul>${a.warnings.map(w=>`<li>${escape(w)}</li>`).join('')}</ul></section>`:''}
    <details class="analysis-section analysis-details"><summary>Processing details</summary>${facts([['Temporary storage retained',size(a.temp_bytes)],['Peak temporary storage',size(a.peak_temp_bytes)],['Working memory budget',size(a.memory_budget_bytes)],['Workers',format(a.workers)],['Algorithm version',a.algorithm_version??'See manifest']])}
    ${a.stages.length?`<h3>Group counts by step</h3><ul class="analysis-stages">${a.stages.map(stage=>`<li><span>Step ${stage.operation}</span><span>${format(stage.input_groups)} → ${format(stage.output_groups)} groups</span></li>`).join('')}</ul>`:''}</details>
    ${d?`<details class="analysis-section"><summary>Execution strategies</summary>${facts([['In-memory sorts',format(d.resident_sorts)],['Bounded groupings',format(d.routed_groupings)],['Spilled sort runs',format(d.sort_runs)],['Merges',format(d.merge_operations)],['Grouping fallbacks to sorting',format(d.routing_fallbacks)],['Sorted group files reused',format(d.routing_reused_runs??0)],['Peak reserved workspace',size(d.peak_workspace_reserved_bytes)]])}<p class="analysis-explanation">Automatic grouping routes low-cardinality, ordered groups and falls back to sorting if their shape changes. Reserved workspace includes intermediate dataset buffers; it excludes parser, final output, codec and runtime overhead and is not process memory.</p></details>`:''}
    `;

}
function renderPreview(a: {header:string[]|null;columns:number;preview:string[][]}) {
  $('preview').tabIndex=0;$('preview').setAttribute('role','region');$('preview').setAttribute('aria-label','Input preview rows');
  $('preview-card').hidden=!a.preview.length;
  $('preview').innerHTML=`<table aria-label="Input preview sample"><thead><tr>${(a.header||Array.from({length:a.columns},(_,i)=>`Column ${i}`)).map(c=>`<th>${escape(c)}</th>`).join('')}</tr></thead><tbody>${a.preview.map(row=>`<tr>${row.map(c=>`<td>${escape(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
let lastProfile='';let profileDirty=true;let profileOrigin:ResultOrigin|null=null,analysisOrigin:ResultOrigin|null=null,inspectionSource:string|null=null;let resultSerial=0;let lastProfileData:InputProfile|null=null;
let progressPhase='', progressStatus='', progressStarted=0, progressRows=0, progressStopped:number|null=0;
async function poll() {
  try {
    const ticket=++pollSerial,epoch=requestEpoch;if(activeCommands)return;
    const s = await api<State>('state');if(ticket<=lastAppliedPoll||epoch!==requestEpoch||activeCommands)return;lastAppliedPoll=ticket;
    if(s.origins?.profile)profileOrigin=s.origins.profile;if(s.origins?.analysis)analysisOrigin=s.origins.analysis;
    profileDirty=!belongsToSource(profileOrigin,sourceKey());
    status=s.status;
    $('connection').hidden=true;
    const busy = ['profiling','running'].includes(status);
    $('status').textContent=status.replace('_',' ').toUpperCase();
    const now=performance.now();
    if(busy&&(progressPhase!==s.progress.phase||progressStatus!==status||s.progress.rows<progressRows)){progressPhase=s.progress.phase;progressStarted=now;progressRows=s.progress.rows;progressStopped=null;}
    if(!busy&&progressStopped===null)progressStopped=now;
    progressStatus=status;
    const seconds=((progressStopped??now)-progressStarted)/1000, rate=(s.progress.rows-progressRows)/Math.max(seconds,0.001);
    $('progress').hidden=!busy&&!['failed','cancelled'].includes(status);$('phase').textContent=s.progress.phase;
    $('progress-detail').textContent=`${format(s.progress.rows)} rows · ${size(s.progress.temp_bytes)} temporary · ${Math.floor(seconds)} s in phase${seconds>=1&&rate>0?` · ${format(Math.round(rate))} rows/s`:''}`;
    updateRunControl();$<HTMLButtonElement>('profile').disabled=busy;
    $('cancel').hidden=!['profiling','running'].includes(status);
    if(s.profile){lastProfileData=s.profile;if(!profileDirty)renderProfile(s.profile,!s.analysis||!belongsToSource(analysisOrigin,sourceKey()));else if(status==='profiled'){lastProfile='';$('input-profile').hidden=false;$('input-profile').textContent='Analysis finished for a different input or parsing configuration. Analyze input again for the current source.';}}

    if(s.analysis) renderAnalysis(s.analysis);
    if(s.error) error(s.error);
    $('result-path').className=status==='complete'?'hint complete':'hint';
    $('result-path').textContent=status==='complete'?`✓ Complete. Results saved to ${s.output}`:status==='cancelled'?(s.error?'Cancelled. See cleanup and destination details.':'Cancelled. Job-owned temporary files cleaned up.'):'';
    hostedWorkspace?.state(s,dirty);
  } catch(e) { $('connection').hidden=false;$('connection').textContent=e instanceof Error?e.message:String(e); }
}
bindColumnPickers($('operations'),picker=>{
  const step=Number(picker.closest<HTMLElement>('[data-step]')!.dataset.step);
  return job.operations[step][picker.dataset.columnField as 'columns'|'strata']||[];
},()=>columnSchema,(picker,columns)=>{
  const step=Number(picker.closest<HTMLElement>('[data-step]')!.dataset.step);
  job.operations[step][picker.dataset.columnField as 'columns'|'strata']=columns;
  renderPickers();markDirty();
},()=>void loadColumns());
let columnTimer: ReturnType<typeof setTimeout>;
$('job-form').addEventListener('input',event=>{
  const target=event.target as HTMLElement;
  if(target.matches('[data-column-search],[data-inspection-search]'))return;
  if(target.matches('[data-size-unit]')){
    updateFields();
    if(job)planLinks.render(job.operations,{rows:value('max-rows'),bytes:sizeText('max-bytes'),compressed:sizeText('compressed-bytes')},value('compression'));
    updateDraft();validation.update();return;
  }
  markDirty();
  if(target.id==='input'||target.id==='zip-member'||target.closest('#input-csv')){
    clearTimeout(columnTimer);columnRequest++;columnSchema=null;columnMessage='Loading input columns?';renderPickers();
    $('preview-card').hidden=true;validation.update();columnTimer=setTimeout(()=>void loadColumns(),400);
  }
});
$('operations').addEventListener('input',e=>{
  const el=e.target as HTMLInputElement;const step=el.closest<HTMLElement>('[data-step]');if(!step)return;
  const op=job.operations[Number(step.dataset.step)],field=el.dataset.field;
  if(el.dataset.groupField){const group=op.groups![Number(el.closest<HTMLElement>('[data-group]')!.dataset.group)];group[el.dataset.groupField as 'name'|'percent']=el.value;updateGroupValidation();return;}
  if(!field)return;
  if(field==='files') op[field]=Number(el.value);
  else if(field==='strategy'){op.strategy=el.value;renderOps();}
  else if(field==='type'){op.type=el.value;renderOps();}
});
const reorderHelp=document.createElement('p');reorderHelp.id='pipeline-reorder-help';reorderHelp.className='sr-only';reorderHelp.textContent='Drag a handle to a highlighted gap. On a handle, use Up or Down arrow keys. The movement arrow buttons are also available.';
const reorderStatus=document.createElement('p');reorderStatus.className='sr-only';reorderStatus.setAttribute('role','status');$('operations').after(reorderHelp,reorderStatus);
function moveOperation(from:number,to:number){
  if(from<0||to<0||from>=job.operations.length||to>=job.operations.length||from===to)return;
  const [operation]=job.operations.splice(from,1);job.operations.splice(to,0,operation);renderOps();markDirty();
  const step=$('operations').querySelector<HTMLElement>(`[data-operation-id="${operationId(operation)}"]`)!;
  step.scrollIntoView({block:'nearest'});step.querySelector<HTMLButtonElement>('[data-step-grip]')!.focus({preventScroll:true});
  reorderStatus.textContent=`Moved ${step.querySelector('.step-title')!.textContent} to step ${to+1} of ${job.operations.length}.`;
}
let stepDrag:{operation:Operation;target:HTMLElement|null;position:'before'|'after'}|null=null;
function clearStepDrop(){for(const step of $('operations').querySelectorAll<HTMLElement>('[data-drop]'))delete step.dataset.drop;}
function finishStepDrag(){clearStepDrop();for(const step of $('operations').querySelectorAll('.is-dragging'))step.classList.remove('is-dragging');stepDrag=null;}
$('operations').addEventListener('dragstart',event=>{
  const handle=(event.target as Element).closest('[data-step-grip]');if(!handle)return;
  const step=handle.closest<HTMLElement>('[data-step]')!,operation=job.operations[Number(step.dataset.step)];
  stepDrag={operation,target:null,position:'before'};step.classList.add('is-dragging');
  if(event.dataTransfer){event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('application/x-chopper-step',String(operationId(operation)));event.dataTransfer.setDragImage(step.querySelector('.step-head')!,20,20);}
});
$('operations').addEventListener('dragover',event=>{
  if(!stepDrag)return;
  const steps=[...$('operations').querySelectorAll<HTMLElement>(':scope>.step')];
  const target=steps.find(step=>event.clientY<step.getBoundingClientRect().bottom)??steps.at(-1);if(!target)return;
  const box=target.getBoundingClientRect(),position=event.clientY<box.top+box.height/2?'before':'after';
  clearStepDrop();stepDrag.target=target;stepDrag.position=position;
  const from=job.operations.indexOf(stepDrag.operation),slot=Number(target.dataset.step)+(position==='after'?1:0),to=slot>from?slot-1:slot;
  if(from<0)return;event.preventDefault();if(event.dataTransfer)event.dataTransfer.dropEffect='move';
  if(to!==from)target.dataset.drop=position;
});
$('operations').addEventListener('dragleave',event=>{if(!(event.relatedTarget instanceof Node&&$('operations').contains(event.relatedTarget))){clearStepDrop();if(stepDrag)stepDrag.target=null;}});
$('operations').addEventListener('drop',event=>{
  if(!stepDrag)return;event.preventDefault();const drag=stepDrag;
  const from=job.operations.indexOf(drag.operation),slot=drag.target?Number(drag.target.dataset.step)+(drag.position==='after'?1:0):-1;
  finishStepDrag();if(from>=0&&slot>=0)moveOperation(from,slot>from?slot-1:slot);
});
$('operations').addEventListener('dragend',finishStepDrag);
$('operations').addEventListener('keydown',event=>{
  if(event.key==='Escape'&&stepDrag){finishStepDrag();reorderStatus.textContent='Step reorder cancelled.';return;}
  if(stepDrag)return;
  const handle=(event.target as Element).closest('[data-step-grip]');if(!handle||!['ArrowUp','ArrowDown'].includes(event.key))return;
  event.preventDefault();const from=Number(handle.closest<HTMLElement>('[data-step]')!.dataset.step);moveOperation(from,from+(event.key==='ArrowUp'?-1:1));
});
$('operations').addEventListener('click',e=>{
  const button=(e.target as HTMLElement).closest<HTMLButtonElement>('[data-action]');if(!button)return;
  const index=Number(button.closest<HTMLElement>('[data-step]')!.dataset.step);const action=button.dataset.action;
  if(action==='add-group'||action==='remove-group'||action==='remainder'){
    const op=job.operations[index];const groups=op.groups||[];const groupIndex=Number(button.closest<HTMLElement>('[data-group]')?.dataset.group);
    if(action==='add-group'&&groups.length<1024)groups.push({name:'',percent:'0'});
    if(action==='remove-group'&&groups.length>1)groups.splice(groupIndex,1);
    if(action==='remainder'){
      const other=groups.filter((_,i)=>i!==groupIndex).map(g=>percentageUnits(g.percent));
      const total=other.reduce<number>((sum,n)=>sum+(n||0),0);
      if(other.some(n=>n===null)||total>100_000_000){error(new Error('Enter valid percentages totaling at most 100% in the other groups first.'));return;}
      groups[groupIndex].percent=String((100_000_000-total)/1_000_000);
    }
    op.groups=groups;renderOps();markDirty();

      const step=$('operations').querySelector<HTMLElement>(`[data-step="${index}"]`)!;
      const next=action==='remove-group'?step.querySelector<HTMLElement>('[data-action="add-group"]'):step.querySelector<HTMLElement>(`[data-group="${groupIndex}"] [data-action="${action}"]`);
      (next||step.querySelector<HTMLElement>('[data-action="add-group"]'))?.focus();

    return;
  }
  if(action==='remove')job.operations.splice(index,1);else{const next=index+(action==='up'?-1:1);[job.operations[index],job.operations[next]]=[job.operations[next],job.operations[index]];}
  renderOps();markDirty();

    const nextIndex=Math.min(action==='remove'?index:index+(action==='up'?-1:1),job.operations.length-1);
    const next=$('operations').querySelector<HTMLButtonElement>(`[data-step="${nextIndex}"] [data-action="${action}"]:not(:disabled)`)
      || $('operations').querySelector<HTMLButtonElement>(`[data-step="${nextIndex}"] [data-action="remove"]`)
      || $<HTMLButtonElement>('add-operation');
    next.focus();

});
$('add-operation').onclick=()=>{const type=value('new-operation');job.operations.push((type==='balanced'||type==='interleaved')?{type,files:2}:type==='partition'?{type,columns:[]}:(type==='assign'||type==='assign_probabilistic')?{type,groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:[]}:{type,strategy:'auto'});renderOps();markDirty();};
$('sniff-csv').onclick=async()=>{
  const button=$<HTMLButtonElement>('sniff-csv');button.disabled=true;
  const source=sourceKey();
  try{const result=await api<{settings:Csv;note:string}>('sniff',{...job,input:value('input'),zip_member:value('zip-member')||null,input_csv:readCsv('input')});
    if(source!==sourceKey())return;
    csvForm('input',result.settings);$('sniff-note').textContent=result.note;markDirty();void loadColumns();
  }catch(e){error(e);}finally{button.disabled=false;}
};
$('copy-csv').onclick=()=>{csvForm('output',readCsv('input'));markDirty();};
$('profile').onclick=async()=>{
  if(!validation.check(false))return;
  try{job=readJob();$('error').hidden=true;profileOrigin=resultOrigin(sourceKey(),job,editRevision,++resultSerial);profileDirty=false;lastProfileData=null;await api('profile',job);lastProfile='';lastAnalysis='';$('input-profile').hidden=true;$('analysis').hidden=true;await poll();}catch(e){error(e);}
};
async function startJob(){
  if(!validation.check())return;
  try{
    job=readJob();updateDraft();$('error').hidden=true;
    const submittedRevision=editRevision;analysisOrigin=resultOrigin(sourceKey(),job,editRevision,++resultSerial);
    await api('run-direct',job);
    // Acknowledgement validates only the draft revision that was submitted.
    if(submittedRevision===editRevision)dirty=false;
    lastAnalysis='';$('input-profile').hidden=true;$('analysis').hidden=true;
    $('empty-plan').hidden=true;await poll();
  }catch(e){error(e);}
}
function updateRunControl() {
  const button=$<HTMLButtonElement>('run-direct');
  button.disabled=['profiling','running'].includes(status);
  button.textContent='Run →';
}
$('job-form').onsubmit=async e=>{
  e.preventDefault();
  if(!validation.check())return;
  await startJob();
};
$('cancel').onclick=async()=>{try{await api('cancel',{});await poll();}catch(e){error(e);}};
$('export').onclick=()=>{try{const blob=new Blob([JSON.stringify(readJob(),null,2)+'\n'],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='chopper-job.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e);}};
$('import').onclick=()=>$<HTMLInputElement>('import-file').click();
$<HTMLInputElement>('import-file').onchange=async e=>{try{const file=(e.target as HTMLInputElement).files?.[0];if(!file)return;if(file.size>1048576)throw new Error('Job JSON exceeds 1 MiB.');const config=JSON.parse(await file.text());if(Object.hasOwn(config,"seed")||Object.hasOwn(config,"random_seed"))throw new Error("Seed settings are no longer supported. Remove the seed field from the job JSON.");const defaults=await api<Job>('defaults');job={...defaults,...config,input_csv:{...defaults.input_csv,...config.input_csv},output_csv:{...defaults.output_csv,...config.output_csv},limits:{...defaults.limits,...config.limits},resources:{...defaults.resources,...config.resources}};populate();}catch(e){error(e);}};
for(const mode of ['input','output']) $('browse-'+mode).onclick=async()=>{
  const buttons=['input','output'].map(m=>$<HTMLButtonElement>('browse-'+m));
  buttons.forEach(b=>b.disabled=true);
  const button=$<HTMLButtonElement>('browse-'+mode);button.textContent='Picker open?';
  try {
    const result=await api<{path:string|null}>('pick-path',{mode,path:value(mode)});
    if(result.path!==null){if(mode==='input')inputSelectionRevision++;setValue(mode,result.path);markDirty();if(mode==='input')void loadColumns();}
  } catch(e){error(e);} finally {buttons.forEach(b=>b.disabled=false);button.textContent='Browse';}
};
async function start(){try{job=await api<Job>('defaults');populate();await poll();setInterval(()=>void poll(),1000);}catch(e){$('connection').hidden=false;$('connection').textContent=`${e instanceof Error?e.message:e}. Open the browser app in desktop Chrome or Edge.`;}}
const planLinks=configurePlanLinks();
const validation=configureValidation(()=>job,()=>columnSchema,readSizeField,()=>readMemory(memoryControls));
const hostedWorkspace=configureHostedWorkspace();
configureBrowserUI();
void start();
