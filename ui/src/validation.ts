import type {Job} from './app';
import {columnIndex,type ColumnSchema} from './column-picker';
import {GROUP_TOTAL_ERROR,groupErrors,percentageUnits} from './plan';

type Field = HTMLInputElement | HTMLSelectElement;
type Issue = {field: HTMLElement; message: string; related?: HTMLElement[]};
const get = <T extends HTMLElement = HTMLInputElement>(id:string) => document.getElementById(id) as T;
const reveal = (field:HTMLElement) => {
  document.dispatchEvent(new Event('chopper-edit-configuration'));
  for(let parent=field.parentElement;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement)parent.open=true;
  const target=field instanceof HTMLInputElement&&field.readOnly&&['input','output'].includes(field.id)?get('browse-'+field.id):field;
  target.focus();target.scrollIntoView({block:'center'});
};

// Validate editable configuration only. Filesystem state and unseen rows still need the engine.
export function configureValidation(getJob:()=>Job, getSchema:()=>ColumnSchema|null, parseSize:(id:string)=>number|null,requestedMemory:()=>number|'auto',showNext?:(issue:{message:string;reveal:()=>void}|undefined)=>void) {
  const form=get<HTMLFormElement>('job-form'),panel=get('validation-panel'),list=get('validation-list');
  let touched=new WeakSet<HTMLElement>();
  const feedback=new WeakMap<HTMLElement,HTMLElement>();
  let submitted=false,serial=0,issues:Issue[]=[],announced:HTMLElement|null=null,announceTimer:ReturnType<typeof setTimeout>;
  const add=(field:HTMLElement|null,message:string,related?:HTMLElement[])=>{if(field)issues.push({field,message,related});};
  const issueFor=(field:HTMLElement)=>issues.find(issue=>issue.field===field||issue.related?.includes(field));
  const collect=()=>{
    issues=[];
    const job=getJob();if(!job)return;
    const controls=[...form.querySelectorAll<Field>('input:not([type=file]),select')];
    for(const field of controls)field.setCustomValidity('');
    if(!get('input').value.trim())add(get('input'),get('input').readOnly?'Choose an input file with Browse.':'Choose an input file with Browse or enter its path.');
    if(!get('output').value.trim())add(get('output'),get('output').readOnly?'Choose an output folder with Browse.':'Choose an output folder with Browse or enter a new directory path.');
    for(const field of controls){
      if(field.disabled||field.matches('[data-column-search]'))continue;
      const name=field.labels?.[0]?.childNodes[0]?.textContent?.trim()||'This setting';
      if(field instanceof HTMLSelectElement&&!field.value)add(field,`${name}: choose a supported option.`);
      if(field instanceof HTMLInputElement&&field.type==='number'&&!field.dataset.quantity){
        const n=Number(field.value);
        if(!field.value&&!field.required&&!field.validity.badInput)continue;
        if(!field.value||!Number.isSafeInteger(n)||n<Number(field.min||'-Infinity')||n>Number(field.max||'Infinity'))add(field,`${name}: enter a whole number${field.min?` from ${field.min}`:''}${field.max?` to ${field.max}`:''}.`);
      }
    }
    for(const id of ['max-bytes','compressed-bytes','temp-bytes','max-record','memory']){
      const field=get(id);if(field.disabled)continue;
      try{if(id==='memory')requestedMemory();else parseSize(id);}catch(e){add(field,`${field.labels?.[0]?.childNodes[0]?.textContent?.trim()}: ${e instanceof Error?e.message:String(e)}`);}
    }
    const automatic=get('memory-mode').disabled||get('memory-mode').value==='auto';
    let memory:number=NaN;try{const requested=requestedMemory();memory=requested==='auto'?256:requested;}catch{/* Reported by the size field above. */}
    if(Number.isSafeInteger(memory)&&memory>=32){
      let record=0;try{record=parseSize('max-record')??0;}catch{/* Reported above. */}
      if(record>memory*1024*1024/16)add(get('max-record'),`Maximum record working size must fit within 1/16 of the ${automatic?'256 MiB Auto baseline':'memory budget'} (${memory/16} MiB). Lower this limit or increase manual memory.`);
      if(!get('workers').disabled&&Number(get('workers').value)>Math.min(64,Math.floor(memory/8)))add(get('workers'),`Reduce workers to at most ${Math.min(64,Math.floor(memory/8))} for this memory budget, or increase manual memory. Zero selects automatic workers.`);
    }
    for(const prefix of ['input','output']){
      const field=(key:string)=>get(prefix+'-csv').querySelector<Field>(`[data-csv="${key}"]`)!;
      for(const key of ['delimiter','quote','escape']){
        const text=field(key).value;
        if(key==='escape'&&!text)continue;
        if(text.length!==1||!/^[\x01-\x7f]$/.test(text)||/[\r\n]/.test(text))add(field(key),`${prefix==='input'?'Input':'Output'} ${key}: enter one ASCII character other than a line break.`);
      }
      if(field('delimiter').value===field('quote').value)add(field('quote'),`${prefix==='input'?'Input':'Output'} quote must differ from its delimiter.`);
      if(field('escape').value&&[field('delimiter').value,field('quote').value].includes(field('escape').value))add(field('escape'),`${prefix==='input'?'Input':'Output'} escape must differ from delimiter and quote; leave it empty to double quotes.`);
    }
    const inputHeaders=get('input-csv').querySelector<HTMLInputElement>('[data-csv="headers"]')!;
    const outputHeaders=get('output-csv').querySelector<HTMLInputElement>('[data-csv="headers"]')!;
    if(!inputHeaders.checked&&outputHeaders.checked)add(outputHeaders,'Turn off output headers, or enable the input header row. A header cannot be copied from headerless input.');
    let outputEncoding='';
    for(const prefix of ['input','output']){
      const field=get(prefix+'-csv').querySelector<HTMLSelectElement>('[data-csv="encoding"]')!;
      try{
        const encoding=new TextDecoder(field.value).encoding;
        const supported=['utf-8','utf-16le','utf-16be','windows-1250','windows-1251','windows-1252','windows-1253','windows-1254','windows-1255','windows-1256','windows-1257','windows-1258','shift_jis','gbk','big5','euc-kr','iso-8859-2'];
        if(!supported.includes(encoding))throw new Error('Unsupported encoding');
        if(prefix==='output')outputEncoding=encoding;
      }catch{add(field,`${prefix==='input'?'Input':'Output'} encoding is unsupported. Choose a supported encoding from the list.`);}
    }
    const outputBom=get('output-csv').querySelector<HTMLInputElement>('[data-csv="bom"]')!;
    if(outputBom.checked&&!['utf-8','utf8','utf-16','utf-16le','utf-16be'].includes(outputEncoding))add(outputBom,'Turn off the output byte-order mark, or choose a UTF encoding.');
    const schema=getSchema();
    if(job.operations.length>64)add(get('operations').querySelector('[data-action="remove"]')||get('add-operation'),'Remove steps until the pipeline has at most 64 operations.');
    job.operations.forEach((op,index)=>{
      const step=form.querySelector<HTMLElement>(`[data-step="${index}"]`)!;
      if(op.type==='balanced'||op.type==='interleaved'){
        if((op.files||0)>Number(get('max-files').value))add(step.querySelector('[data-field="files"]'),`Step ${index+1}: reduce equal parts to the maximum output files / groups limit, or increase that limit.`);
      }
      if(op.type==='assign'||op.type==='assign_probabilistic'){
        const groups=op.groups||[],errors=groupErrors(groups);
        const note=get<HTMLElement>(`group-feedback-${index}`);
        const text=errors.length?errors.join(' '):(op.type==='assign_probabilistic'?'Total target: 100%. Actual counts may vary.':'Total: 100%. Exact percentages, rounded to whole rows.');
        if(note.textContent!==text)note.textContent=text;
        note.classList.toggle('invalid-groups',errors.length>0);
        for(const message of errors){
          if(message.startsWith(GROUP_TOTAL_ERROR)){
            const [first,...related]=step.querySelectorAll<HTMLElement>('[data-group-field="percent"]');
            add(first??step.querySelector('[data-action="add-group"]'),`Step ${index+1}: ${message}`,related);
            continue;
          }
          const field=message.includes('name')?'name':'percent';
          let group=field==='name'?groups.findIndex((g,i)=>!g.name.trim()||groups.slice(0,i).some(other=>other.name===g.name)):groups.findIndex(g=>percentageUnits(g.percent)===null);
          if(group<0)group=0;
          add(step.querySelector(`[data-group="${group}"] [data-group-field="${field}"]`)||step.querySelector('[data-action="add-group"]'),`Step ${index+1}: ${message}`);
        }
      }
      for(const key of ['columns','strata'] as const){
        const columns=op[key];if(!columns)continue;
        const picker=step.querySelector<HTMLElement>(`[data-column-field="${key}"]`)!;
        const target=picker.querySelector<HTMLElement>('[data-column-search]:not(:disabled)')||picker.querySelector<HTMLElement>('.chip-remove,[data-column-reload]')||picker;
        if(key==='columns'&&!columns.length)add(target,`Step ${index+1}: choose at least one column to partition by.`);
        else if(schema&&columns.some(column=>columnIndex(column,schema)===undefined))add(target,`Step ${index+1}: remove missing or ambiguous ${key==='strata'?'stratification':'partition'} columns and select them from the current input.`);
      }
    });
    const messages=new Map<HTMLElement,string>();
    for(const issue of issues)for(const field of [issue.field,...(issue.related??[])]){
      messages.set(field,[messages.get(field),issue.message].filter(Boolean).join(' '));
    }
    for(const field of controls){
      const message=messages.get(field)||'';
      field.setCustomValidity(message);
      // Allocation errors already have a shared message below the rows.
      const groupNote=field.hasAttribute('data-group-field')
        ?get<HTMLElement>(`group-feedback-${field.closest<HTMLElement>('[data-step]')?.dataset.step}`)
        :null;
      const shown=!!message&&(!!groupNote||submitted||touched.has(field));
      field.setAttribute('aria-invalid',String(shown));
      let note=groupNote??feedback.get(field);
      if(message&&!note){note=document.createElement('small');note.id=`field-error-${++serial}`;note.className='field-guidance';(field.closest('.quantity-field,label')||field.parentElement)!.append(note);feedback.set(field,note);}
      if(note){
        if(!groupNote){note.textContent=message;note.hidden=!message;note.classList.toggle('field-error',shown);}
        const ids=(field.getAttribute('aria-describedby')||'').split(/\s+/).filter(id=>id&&id!==note!.id);
        if(shown)ids.push(note.id);
        if(ids.length)field.setAttribute('aria-describedby',ids.join(' '));else field.removeAttribute('aria-describedby');
      }
    }
  };
  const update=()=>{
    const previous=issues;collect();panel.hidden=!issues.length;
    if(announced&&!issueFor(announced)){clearTimeout(announceTimer);get('validation-announcement').textContent='';announced=null;}
    if(issues.length===previous.length&&issues.every((issue,i)=>issue.field===previous[i].field&&issue.message===previous[i].message))return;
    const next=issues[0];
    showNext?.(next?{message:next.message,reveal:()=>reveal(next.field)}:undefined);
    list.replaceChildren();
    for(const {field,message} of issues){
      const item=document.createElement('li'),button=document.createElement('button');
      button.type='button';button.className='validation-link';button.textContent=message;button.onclick=()=>reveal(field);
      item.append(button);list.append(item);
    }
  };
  const announce=(field:HTMLElement)=>{
    clearTimeout(announceTimer);announced=field;
    const message=issueFor(field)?.message||'';
    announceTimer=setTimeout(()=>{get('validation-announcement').textContent=message;},500);
  };
  form.addEventListener('input',event=>{
    const field=event.target as HTMLElement;
    if(field.matches('[data-group-field]')&&issueFor(field))announce(field);
  });
  form.addEventListener('focusout',event=>{
    const field=event.target as HTMLElement;
    if(!field.matches('input,select'))return;
    touched.add(field);update();announce(field);
  });
  form.addEventListener('invalid',event=>{touched.add(event.target as HTMLElement);update();},true);
  return {update,reset(){submitted=false;touched=new WeakSet();clearTimeout(announceTimer);get('validation-announcement').textContent='';},check(outputRequired=true){
    submitted=true;update();const first=issues.find(issue=>outputRequired||issue.field.id!=='output');
    if(first){reveal(first.field);return false;}return true;
  }};
}
