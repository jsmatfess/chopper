import {columnChoices, type ColumnSchema} from './column-picker';

type Calculation = {operation:number; name:string; expression:string};
type Sample = ColumnSchema & {preview:string[][]};
type Cell = {value:string|null; error:string|null; is_null:boolean};
type Preview = {functions:[string,string][]; steps:{operation:number; error:string|null; rows:Cell[]}[]};
type Suggestion = {label:string; detail:string; insertion:string; call?:boolean};

const bareName = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const reserved = /^(TRUE|FALSE|NULL|NOT|AND|OR)$/i;

function token(input:HTMLInputElement) {
  const at = input.selectionStart ?? input.value.length;
  const before = input.value.slice(0, at);
  if ((before.match(/"/g)?.length ?? 0) % 2) return null;
  const prefix = before.match(/(?:\[[^\]]*|\$[0-9]*|[\p{L}\p{N}_.]+)$/u)?.[0] ?? '';
  return {start:at-prefix.length, end:input.selectionEnd??at, prefix};
}

function columnSuggestions(schema:ColumnSchema|null):Suggestion[] {
  return columnChoices(schema).map(choice=>{
    const {value,label,index}=choice;
    const insertion = typeof value==='number' ? '$'+value
      : bareName.test(value)&&!reserved.test(value) ? value : '['+value.replaceAll(']',']]')+']';
    return {label,detail:'Column #'+index,insertion};
  });
}

export function configureFormulaEditor(
  root:HTMLElement,
  calculations:()=>Calculation[],
  sample:()=>Sample|null,
  schema:(step:number)=>ColumnSchema|null,
  request:(data:unknown)=>Promise<Preview>,
) {
  let catalog:Preview['functions']=[];
  let timer:ReturnType<typeof setTimeout>;
  let revision=0;
  let input:HTMLInputElement|null=null;
  let options:Suggestion[]=[];
  let active=0;

  const field=(target:EventTarget|null) => target instanceof HTMLInputElement &&
    target.matches('[data-field="expression"]') ? target : null;
  const list=()=>input?.closest('.column-typeahead')?.querySelector<HTMLElement>('[data-formula-suggestions]');
  function close(){
    const menu=list();
    if(menu)menu.hidden=true;
    input?.setAttribute('aria-expanded','false');
    input?.removeAttribute('aria-activedescendant');
    input=null;
    options=[];
  }
  function highlight(index:number){
    const menu=list();
    if(!menu||!input||!options.length)return;
    active=(index+options.length)%options.length;
    for(const [i,element] of [...menu.children].entries()){
      element.setAttribute('aria-selected',String(i===active));
      if(i===active){
        input.setAttribute('aria-activedescendant',element.id);
        element.scrollIntoView({block:'nearest'});
      }
    }
  }
  function suggest(target:HTMLInputElement, forced=false){
    const match=token(target);
    if(!match||(!forced&&!match.prefix)){close();return;}
    if(input!==target){close();input=target;}
    const menu=list();
    if(!menu)return;
    const step=Number(target.closest<HTMLElement>('[data-step]')?.dataset.step);
    const prefix=match.prefix.toUpperCase();
    const safe=prefix.startsWith('SAFE.');
    const functions=catalog.map(([name,detail])=>({
      label:safe?'SAFE.'+name:name,detail,insertion:safe?'SAFE.'+name:name,call:true,
    }));
    options=[...functions,...(safe?[]:columnSuggestions(schema(step)))]
      .filter(option=>option.insertion.toUpperCase().startsWith(prefix)
        ||option.label.toUpperCase().startsWith(prefix))
      .slice(0,24);
    if(!options.length){close();return;}
    menu.replaceChildren(...options.map((option,index)=>{
      const row=document.createElement('div');
      row.id=menu.id+'-'+index;
      row.dataset.formulaOption=String(index);
      row.setAttribute('role','option');
      const label=document.createElement('span');
      label.textContent=option.label;
      const detail=document.createElement('small');
      detail.textContent=option.detail;
      row.append(label,detail);
      return row;
    }));
    menu.hidden=false;
    target.setAttribute('aria-expanded','true');
    highlight(0);
  }
  function accept(index:number){
    if(!input)return;
    const selected=options[index];
    const match=token(input);
    if(!selected||!match)return;
    const target=input;
    const call=selected.call&&!target.value.slice(match.end).trimStart().startsWith('(');
    target.setRangeText(selected.insertion+(call?'()':''),match.start,match.end,'end');
    if(call){
      const caret=(target.selectionEnd??target.value.length)-1;
      target.setSelectionRange(caret,caret);
    }
    close();
    target.dispatchEvent(new Event('input',{bubbles:true}));
    close();
  }

  root.addEventListener('input',event=>{
    const target=field(event.target);
    if(target)suggest(target);
  });
  root.addEventListener('focusout',event=>{if(event.target===input)close();});
  root.addEventListener('keydown',event=>{
    const target=field(event.target);
    if(!target)return;
    if(event.ctrlKey&&event.code==='Space'){
      event.preventDefault();suggest(target,true);return;
    }
    if(input!==target||!options.length)return;
    if(event.key==='Escape'){event.preventDefault();close();}
    else if(!event.shiftKey&&(event.key==='Tab'||event.key==='Enter')){
      event.preventDefault();accept(active);
    }else if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      event.preventDefault();highlight(active+(event.key==='ArrowDown'?1:-1));
    }
  });
  root.addEventListener('pointerdown',event=>{
    if(event.target instanceof Element&&event.target.closest('[data-formula-option]'))event.preventDefault();
  });
  root.addEventListener('click',event=>{
    const option=event.target instanceof Element&&event.target.closest<HTMLElement>('[data-formula-option]');
    if(option)accept(Number(option.dataset.formulaOption));
  });

  function render(preview?:Preview, fallback?:string) {
    for(const output of root.querySelectorAll<HTMLElement>('[data-formula-preview]')){
      const operation=Number(output.closest<HTMLElement>('[data-step]')?.dataset.step);
      const step=preview?.steps.find(step=>step.operation===operation);
      const error=step?.error??fallback;
      output.replaceChildren();
      if(error&&sample()){
        const message=document.createElement('p');
        message.className='field-error';
        message.textContent=error;
        output.append(message);
      }else if(step?.rows.length){
        const values=document.createElement('ol');
        values.setAttribute('aria-label','Calculated values on input sample');
        for(const row of step.rows){
          const value=document.createElement('li');
          value.textContent=row.error??(row.is_null?'NULL':row.value===''?'(empty text)':row.value);
          if(row.error)value.className='field-error';
          values.append(value);
        }
        output.append(values);
      }
      output.hidden=output.childElementCount===0;
    }
  }

  return {
    update(){
      const current=++revision;
      clearTimeout(timer);
      const steps=calculations();
      if(!steps.length){render();return;}
      timer=setTimeout(async()=>{
        const source=sample();
        try{
          const result=await request({
            header:source?.header??null, columns:source?.columns??0,
            rows:source?.preview??[], calculations:steps,
          });
          if(current!==revision)return;
          const first=!catalog.length;
          catalog=result.functions;
          if(first&&input===document.activeElement&&input)suggest(input,true);
          render(result);
        }catch(error){
          if(current===revision)render(undefined,error instanceof Error?error.message:String(error));
        }
      },160);
    },
  };
}
