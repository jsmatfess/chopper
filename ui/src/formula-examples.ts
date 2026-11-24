import type {FormulaSampleBatch} from './browser/session';
import type {ColumnSchema} from './column-picker';

export type Calculation = {operation:number; name:string; expression:string};
export type FormulaSample = ColumnSchema & {preview:string[][]; preview_row_numbers:number[]};
type Cell = {value:string|null; error:string|null; is_null:boolean};
type Step = {operation:number; error:string|null; rows:Cell[]; references?:number[]};
export type Preview = {functions:[string,string][]; steps:Step[]};
type SampleRow = FormulaSampleBatch['rows'][number];
type Scan = {more:()=>void; stop:()=>void};
type Example = {
  name:string;
  fields:number[];
  row:SampleRow|null;
  visited:Set<string>;
  edits:Map<number,string>;
  result:Cell|null;
  error:string|null;
  version:number;
  next?:{generation:number;row:SampleRow|null};
  examinedThrough:number;
};

export function formulaExamples(
  root:HTMLElement,
  request:(data:unknown)=>Promise<Preview>,
) {
  let source:FormulaSample|null=null;
  let calculations:Calculation[]=[];
  let draft=0;
  let scan:Scan|null=null;
  let scanning=false;
  let scanError='';
  let samplePages:SampleRow[][]=[];
  let sampleGeneration=0;
  let navigationVersion=0;
  const examples=new Map<number,Example>();
  const pending=new Map<number,number>();
  let busy=false;
  let timer:ReturnType<typeof setTimeout>;
  function invalidate(){
    draft++;
    pending.clear();
    clearTimeout(timer);
  }
  const panels=()=>root.querySelectorAll<HTMLElement>('[data-formula-preview]');
  const operation=(panel:HTMLElement)=>Number(panel.closest<HTMLElement>('[data-calculation]')!.dataset.calculation);
  const values=(example:Example,row:SampleRow)=>JSON.stringify(example.fields.map(index=>row[1][index]));
  const initialRows=()=>{
    const sample=source;
    return sample?.preview.map((row,index):SampleRow=>[sample.preview_row_numbers[index],row])??[];
  };

  function nextRow(example:Example) {
    if(!example.fields.length)return null;
    if(example.next&&(example.next.row||example.next.generation===sampleGeneration))return example.next.row;
    let next:SampleRow|null=null;
    find: for(const page of [initialRows(),...samplePages]){
      for(const row of page){
        if(row[0]<=example.examinedThrough)continue;
        example.examinedThrough=row[0];
        if(!example.visited.has(values(example,row))){
          next=row;
          break find;
        }
      }
    }
    example.next={generation:sampleGeneration,row:next};
    return next;
  }

  function select(example:Example,row:SampleRow){
    example.row=row;
    example.examinedThrough=Math.max(row[0],example.examinedThrough);
    example.visited.add(values(example,row));
    example.next=undefined;
    example.edits.clear();
  }

  function show(panel:HTMLElement, example:Example, navigation=true) {
    if(example.error){
      panel.replaceChildren();
      const error=document.createElement('p');
      error.className='field-error';
      error.textContent=example.error;
      panel.append(error);
      panel.hidden=false;
      return;
    }
    const fieldKey=JSON.stringify([example.name,example.fields]);
    if(panel.dataset.fields!==fieldKey||!panel.querySelector('output')){
      panel.dataset.fields=fieldKey;
      // All markup is static. Field labels, input values and results are assigned as text.
      const resultLabel=`formula-result-label-${operation(panel)}`;
      panel.innerHTML=`<div class="formula-example-head"><span data-example-row></span><button type="button" class="secondary" data-example-next hidden>Next distinct row</button><small data-example-edited hidden>Edited values</small></div><div class="formula-example-fields"></div><div class="formula-example-result"><span id="${resultLabel}">Preview result</span><output aria-labelledby="${resultLabel}"></output></div><div class="formula-example-actions"><button type="button" class="text-button" data-example-more hidden>Scan more rows</button><small data-example-status role="status"></small></div>`;
      const fields=panel.querySelector('.formula-example-fields')!;
      for(const index of example.fields){
        const name=source?.header?.[index];
        const label=document.createElement('label');
        label.textContent=name ? (source!.header!.indexOf(name)===source!.header!.lastIndexOf(name)?name:`${name} ($${index})`) : '$'+index;
        const input=document.createElement('textarea');
        input.id=`formula-preview-${operation(panel)}-${index}`;
        label.htmlFor=input.id;
        input.rows=1;
        input.autocomplete='off';
        input.spellcheck=false;
        input.dataset.exampleField=String(index);
        label.append(input);
        fields.append(label);
      }
    }
    const row=panel.querySelector<HTMLElement>('[data-example-row]')!;
    row.textContent=example.row?`Source row ${example.row[0]}`:'Custom example';
    panel.querySelector<HTMLElement>('[data-example-edited]')!.hidden=!example.edits.size;
    for(const input of panel.querySelectorAll<HTMLTextAreaElement>('[data-example-field]')){
      const index=Number(input.dataset.exampleField);
      const text=example.edits.get(index)??example.row?.[1][index]??'';
      // Textareas normalize line breaks. Keep exact source text until the field is edited.
      if(input.value!==text.replace(/\r\n?/g,'\n'))input.value=text;
    }
    const result=panel.querySelector('output')!;
    const cell=example.result;
    const text=cell ? cell.error??(cell.is_null?'NULL':cell.value===''?'(empty text)':cell.value??'') : 'Calculating…';
    if(result.textContent!==text)result.textContent=text;
    result.classList.toggle('field-error',!!cell?.error);
    if(navigation)showNavigation(panel,example);
    panel.hidden=false;
  }

  function showNavigation(panel:HTMLElement,example:Example){
    const next=panel.querySelector<HTMLButtonElement>('[data-example-next]');
    if(!next)return;
    const available=!!nextRow(example);
    next.disabled=!available;
    next.hidden=!example.fields.length;
    const more=panel.querySelector<HTMLButtonElement>('[data-example-more]')!;
    more.hidden=!example.fields.length||available||!scan;
    more.disabled=scanning;
    const status=panel.querySelector('[data-example-status]')!;
    const message=!example.fields.length||available?'':scanning?'Scanning for more examples…':
      scanError?`Scan stopped: ${scanError}`:scan?'No distinct rows in the current sample.':'No source rows with a new combination.';
    if(status.textContent!==message)status.textContent=message;
  }
  async function refreshNavigation(){
    const version=++navigationVersion;
    const scheduler=(globalThis as typeof globalThis & {scheduler?:{yield?():Promise<void>}}).scheduler;
    let deadline=performance.now()+12;
    for(const panel of panels()){
      const example=examples.get(operation(panel));
      if(example)showNavigation(panel,example);
      if(performance.now()>=deadline){
        await (scheduler?.yield?.()??new Promise(resolve=>setTimeout(resolve,0)));
        if(version!==navigationVersion)return;
        deadline=performance.now()+12;
      }
    }
  }

  // One override evaluation in flight. Rapid typing replaces pending work.
  function queue(index:number,example:Example){
    pending.set(index,++example.version);
    clearTimeout(timer);
    timer=setTimeout(()=>void evaluate(),100);
  }
  async function evaluate(){
    if(busy)return;
    busy=true;
    try{
      while(pending.size){
        const [index,version]=pending.entries().next().value!;
        pending.delete(index);
        const example=examples.get(index);
        if(!example||example.version!==version)continue;
        const current=draft;
        const row=Array<string>(source?.columns??0).fill('');
        for(const field of example.fields)row[field]=example.edits.get(field)??example.row?.[1][field]??'';
        let result:Cell|null;
        try{
          const preview=await request({header:source?.header??null,columns:source?.columns??0,
            rows:[row],calculations,target:index});
          const step=preview.steps.find(step=>step.operation===index);
          result=step?.rows[0]??{error:step?.error??'Preview unavailable',value:null,is_null:false};
        }catch(error){
          result={error:error instanceof Error?error.message:String(error),value:null,is_null:false};
        }
        if(current!==draft||example.version!==version||examples.get(index)!==example)continue;
        example.result=result;
        const panel=[...panels()].find(panel=>operation(panel)===index);
        if(panel)show(panel,example);
      }
    }finally{busy=false;}
  }

  root.addEventListener('input',event=>{
    if(!(event.target instanceof HTMLTextAreaElement)||event.target.dataset.exampleField===undefined)return;
    // Preview edits never enter the job draft, validation or execution path.
    event.stopPropagation();
    const input=event.target;
    const panel=input.closest<HTMLElement>('[data-formula-preview]')!;
    const index=operation(panel);
    const example=examples.get(index);
    if(!example)return;
    const field=Number(input.dataset.exampleField);
    if(input.value===(example.row?.[1][field]??'').replace(/\r\n?/g,'\n'))example.edits.delete(field);
    else example.edits.set(field,input.value);
    panel.querySelector<HTMLElement>('[data-example-edited]')!.hidden=!example.edits.size;
    queue(index,example);
  });
  root.addEventListener('click',event=>{
    if(!(event.target instanceof HTMLButtonElement))return;
    const button=event.target;
    const panel=button.closest<HTMLElement>('[data-formula-preview]');
    if(!panel)return;
    if(button.hasAttribute('data-example-more')&&scan&&!scanning){
      scanning=true;
      scan.more();
      void refreshNavigation();
    }
    if(button.hasAttribute('data-example-next')){
      const index=operation(panel);
      const example=examples.get(index);
      const row=example&&nextRow(example);
      if(!example||!row)return;
      select(example,row);
      example.result=null;
      show(panel,example);
      queue(index,example);
    }
  });

  return {
    invalidate,
    reset(){
      invalidate();
      scan?.stop();
      scan=null;
      scanning=false;
      scanError='';
      samplePages=[];
      navigationVersion++;
      source=null;
      examples.clear();
      for(const panel of panels()){panel.replaceChildren();panel.hidden=true;}
    },
    startScan(start:(batch:(batch:FormulaSampleBatch)=>void,error:(error:string)=>void)=>Scan){
      scanning=true;
      try{
        scan=start(batch=>{
          if(batch.rows.length){
            sampleGeneration++;
            samplePages.push(batch.rows);
            // Keep the initial sample and seven recent batches within a fixed payload budget.
            if(samplePages.length>8)samplePages.splice(1,1);
          }
          scanning=false;
          if(batch.done)scan=null;
          void refreshNavigation();
        },error=>{
          scanError=error;
          scanning=false;
          scan=null;
          void refreshNavigation();
        });
      }catch(error){scanError=String(error);scanning=false;}
    },
    render(preview:Preview|undefined,sample:FormulaSample|null,steps:Calculation[],error?:string){
      if(source!==sample)sampleGeneration++;
      source=sample;
      calculations=steps;
      if(!steps.length){examples.clear();return;}
      const rows=initialRows();
      for(const panel of panels()){
        const index=operation(panel);
        const step=preview?.steps.find(step=>step.operation===index);
        const name=steps[index]?.name;
        if(name===undefined||!step&&!error||!sample&&(step?.error||error)){
          panel.replaceChildren();panel.hidden=true;
          if(name===undefined)examples.delete(index);
          continue;
        }
        const fields=step?.references??[];
        let example=examples.get(index);
        const message=step?.error??error??null;
        if(!example||example.name!==name||(!message&&JSON.stringify(example.fields)!==JSON.stringify(fields))){
          example={name,fields,row:null,visited:new Set(),edits:new Map(),result:null,error:null,version:0,examinedThrough:0};
          examples.set(index,example);
        }
        example.error=message;
        if(!example.row&&!example.edits.size){
          const first=rows[0]??samplePages.find(page=>page.length)?.[0];
          if(first)select(example,first);
        }
        const rowIndex=rows.findIndex(row=>row[0]===example.row?.[0]);
        const base=step?.rows[rowIndex>=0?rowIndex:0];
        if(!example.edits.size&&(rowIndex>=0||!example.row)&&base)example.result=base;
        else if(!message)queue(index,example);
        show(panel,example,false);
      }
      void refreshNavigation();
    },
  };
}
