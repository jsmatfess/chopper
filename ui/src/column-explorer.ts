import type {FormulaInsertion,FormulaInsertionTarget} from './formula-editor';

type SourceColumns = {columns:number; header:string[]|null};
type ColumnSummary = {
  column:number;
  values:string[];
  frequencies?:Record<string,number>;
  truncated:boolean;
  distinct?:number;
  distinct_exact?:boolean;
};
type Analysis = {columns:ColumnSummary[]; header:string[]|null; origin:string; rows:number};

const compactCount=new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1});

export function configureColumnExplorer(analyze:HTMLButtonElement,formula:FormulaInsertionTarget) {
  const panel=document.createElement('section');
  panel.id='input-values';
  panel.hidden=true;
  panel.setAttribute('aria-labelledby','input-values-heading');
  panel.innerHTML=`
    <div class="column-explorer-header">
      <div class="input-values-heading">
        <h3 id="input-values-heading" tabindex="-1">Column explorer</h3>
        <span id="input-values-count"></span>
      </div>
      <label class="input-values-filter">
        <span class="sr-only">Find a column</span>
        <input type="search" data-inspection-search placeholder="Find a column" autocomplete="off">
      </label>
    </div>
    <div class="column-explorer-list-heading" aria-hidden="true" hidden><span>Column</span><span data-explorer-count-heading></span></div>
    <div class="input-values-list" role="group" aria-label="Source columns"></div>
    <p class="hint input-values-empty" role="status" hidden>No matching columns.</p>
    <p class="column-explorer-insert-message hint" role="status" hidden></p>
    <div class="column-explorer-footer">
      <p class="hint" id="input-values-origin"></p>
      <button type="button" class="text-button" data-explorer-analyze>Analyze input</button>
    </div>`;
  const search=panel.querySelector<HTMLInputElement>('input')!;
  const list=panel.querySelector<HTMLElement>('.input-values-list')!;
  const empty=panel.querySelector<HTMLElement>('.input-values-empty')!;
  const insertMessage=panel.querySelector<HTMLElement>('.column-explorer-insert-message')!;
  const total=panel.querySelector<HTMLElement>('#input-values-count')!;
  const note=panel.querySelector<HTMLElement>('#input-values-origin')!;
  const countHeading=panel.querySelector<HTMLElement>('[data-explorer-count-heading]')!;
  const analyzeHere=panel.querySelector<HTMLButtonElement>('[data-explorer-analyze]')!;
  let schema:SourceColumns|null=null;
  let analysis:Analysis|null=null;
  let schemaKey='';
  let analysisKey='';
  let isAnalyzing=false;
  const expanded=new Set<string>();

  function filter(){
    const query=search.value.trim().toLocaleLowerCase();
    let matches=0;
    for(const row of list.querySelectorAll<HTMLElement>('[data-column]')){
      row.hidden=!row.dataset.search!.includes(query);
      if(!row.hidden)matches++;
    }
    empty.hidden=matches>0||!query;
  }
  search.addEventListener('input',filter);
  analyzeHere.addEventListener('click',()=>{if(analyzeHere.getAttribute('aria-disabled')!=='true')analyze.click();});

  function clickedInsertion(event:Event):FormulaInsertion|null {
    if(!panel.closest('.workspace-sidebar')||!formula.isFocused()||!(event.target instanceof Element))return null;
    const token=event.target.closest<HTMLElement>('[data-insert-column],[data-insert-value]');
    if(!token||!list.contains(token))return null;
    if(token.dataset.insertValue!==undefined)return {value:token.dataset.insertValue};
    return {column:Number(token.dataset.insertColumn)};
  }

  panel.addEventListener('pointerdown',event=>{
    if(event.button!==0||!panel.closest('.workspace-sidebar')||!formula.isFocused())return;
    if(clickedInsertion(event)||event.target instanceof Element&&event.target.closest('.column-disclosure')){
      event.preventDefault();
    }
  });
  panel.addEventListener('click',event=>{
    const insertion=clickedInsertion(event);
    if(!insertion)return;
    event.preventDefault();
    const error=formula.insert(insertion);
    insertMessage.hidden=!error;
    insertMessage.textContent=error??'';
  });

  function renderFooter(){
    const text=analysis?.columns.length?analysis.origin:isAnalyzing?'Scanning input…':'Analyze to see values and counts.';
    if(note.textContent!==text)note.textContent=text;
    const hideAction=!!analysis?.columns.length||!schema?.columns;
    if(hideAction&&document.activeElement===analyzeHere)panel.querySelector('h3')!.focus({preventScroll:true});
    analyzeHere.hidden=hideAction;
  }

  function columnContents(summary:ColumnSummary,name:string,rows:number){
    const values=document.createElement('ul');
    const description=document.createElement('small');
    values.className='value-chips';
    values.setAttribute('role','list');
    if(summary.values.length)values.tabIndex=0;
    values.setAttribute('aria-label',`Retained values for ${name}`);
    const frequencies=summary.frequencies;
    const ranked=summary.values.map(value=>({
      value, count:frequencies&&Object.hasOwn(frequencies,value)?frequencies[value]:NaN,
    }));
    const shares=!summary.truncated&&rows>0&&ranked.length>0&&
      ranked.every(entry=>Number.isSafeInteger(entry.count)&&entry.count>0)&&
      ranked.reduce((sum,entry)=>sum+entry.count,0)===rows;
    if(shares){
      ranked.sort((a,b)=>b.count-a.count);
      values.classList.add('value-distribution');
      values.setAttribute('aria-label',`Value distribution for ${name}, largest first`);
    }
    for(const {value,count} of ranked){
      const item=document.createElement('li');
      const label=document.createElement('span');
      label.className='value-label';
      const text=document.createElement('span');
      text.textContent=value||'(empty)';
      text.dataset.insertValue=value;
      label.append(text);
      if(value==='')item.dataset.empty='true';
      item.append(label);
      if(shares){
        const metrics=document.createElement('span');
        const frequency=document.createElement('span');
        const share=document.createElement('span');
        const track=document.createElement('span');
        const fill=document.createElement('span');
        const percent=100*count/rows;
        metrics.className='value-metrics';
        frequency.className='value-frequency';
        frequency.textContent=compactCount.format(count);
        frequency.setAttribute('aria-label',`${count.toLocaleString()} rows`);
        share.className='value-share';
        share.textContent=percent<0.1?'<0.1%':`${percent.toLocaleString(undefined,{maximumFractionDigits:1})}%`;
        item.title=`${count.toLocaleString()} of ${rows.toLocaleString()} input rows`;
        track.className='value-track';
        track.setAttribute('aria-hidden','true');
        fill.className='value-fill';
        fill.style.inlineSize=`${percent}%`;
        track.append(fill);
        metrics.append(frequency,share);
        item.append(metrics,track);
      }
      values.append(item);
    }
    description.textContent=shares?'Exact row counts and shares.':summary.truncated
      ?`Showing ${summary.values.length.toLocaleString()} retained values. Counts unavailable.`
      :summary.values.length?`All ${summary.values.length.toLocaleString()} values shown.`:'No values in the input.';
    return [values,description];
  }

  function columnName(index:number) {
    const header=schema?schema.header:analysis?.header;
    return header?.[index]||`Column #${index}`;
  }

  function render(){
    const summaries=new Map(analysis?.columns.map(column=>[column.column,column]));
    const columns=schema?Array.from({length:schema.columns},(_,index)=>index):[...summaries.keys()];
    panel.hidden=!columns.length;
    list.tabIndex=summaries.size?-1:0;
    countHeading.parentElement!.hidden=!summaries.size;
    countHeading.textContent=analysis?.columns.some(column=>column.distinct===undefined)?'Values':'Distinct';
    total.textContent=`${compactCount.format(columns.length)} ${columns.length===1?'column':'columns'}`;
    search.closest('label')!.hidden=columns.length<2;
    renderFooter();
    const focus=document.activeElement?.closest<HTMLElement>('[data-column]');
    const focusedColumn=focus&&list.contains(focus)?focus.dataset.column:undefined;
    const scrollTop=list.scrollTop;
    const content=document.createDocumentFragment();
    for(const index of columns){
      const summary=summaries.get(index);
      const name=columnName(index);
      const row=document.createElement(summary?'details':'div');
      row.className='column-values-row';
      row.dataset.column=String(index);
      row.dataset.search=`${name.toLocaleLowerCase()} #${index} $${index}`;
      const heading=document.createElement(summary?'summary':'div');
      heading.className='column-values-line';
      const indexLabel=document.createElement('span');
      const label=document.createElement('span');
      indexLabel.className='column-values-index';
      indexLabel.textContent=`$${index}`;

      label.className='column-values-name';
      const text=document.createElement('span');
      text.textContent=name;
      text.dataset.insertColumn=String(index);
      label.append(text);
      if(summary){
        const disclosure=document.createElement('span');
        disclosure.className='column-disclosure';
        disclosure.setAttribute('aria-hidden','true');
        heading.append(disclosure);
      }
      heading.append(indexLabel,label);
      row.append(heading);
      if(summary){
        const count=document.createElement('span');
        count.className='column-values-count';
        row.dataset.countKind=summary.distinct===undefined?'values':summary.distinct_exact?'exact':'estimated';
        const shortCount=document.createElement('span');
        shortCount.className='column-count-number';
        const qualifier=document.createElement('span');
        qualifier.className='column-count-qualifier';
        if(summary.distinct===undefined){
          shortCount.textContent=`${compactCount.format(summary.values.length)}${summary.truncated?'+':''}`;
          qualifier.textContent=' values shown';
        }else{
          shortCount.textContent=`${summary.distinct_exact?'':'~'}${compactCount.format(summary.distinct)}`;
          qualifier.textContent=` distinct · ${summary.distinct_exact?'exact':'estimated'}`;
        }
        count.append(shortCount,qualifier);
        const fullCount=summary.distinct??summary.values.length;
        count.title=`${summary.distinct!==undefined&&!summary.distinct_exact?'~':''}${fullCount.toLocaleString()}${qualifier.textContent}`;
        count.setAttribute('aria-label',count.title);
        heading.append(count);
        if(row instanceof HTMLDetailsElement){
          const column=row.dataset.column!;
          const analyzedRows=analysis!.rows;
          row.open=expanded.has(column);
          const populate=()=>{row.append(...columnContents(summary,name,analyzedRows));};
          let populated=row.open;
          if(populated)populate();
          row.addEventListener('toggle',()=>{
            if(!row.isConnected)return;
            if(!row.open){expanded.delete(column);return;}
            expanded.add(column);
            if(!populated){populate();populated=true;}
          });
        }
      }
      content.append(row);
    }
    list.replaceChildren(content);
    filter();
    list.scrollTop=scrollTop;
    if(focusedColumn!==undefined)list.querySelector<HTMLElement>(`[data-column="${focusedColumn}"] summary`)?.focus({preventScroll:true});
  }

  return {
    panel,
    reset(){
      if(!schema&&!analysis)return;
      schema=null;
      analysis=null;
      schemaKey=analysisKey='';
      expanded.clear();
      insertMessage.hidden=true;
      insertMessage.textContent='';
      search.value='';
      render();
    },
    source(next:SourceColumns){
      const key=JSON.stringify([next.columns,next.header]);
      if(key===schemaKey)return;
      schemaKey=key;
      schema=next;
      render();
    },
    values(columns:ColumnSummary[],header:string[]|null,origin:string,rows:number){
      if(!columns.length&&!analysis)return;
      const key=JSON.stringify([columns,header,origin,rows]);
      if(key===analysisKey)return;
      analysisKey=key;
      analysis=columns.length?{columns,header,origin,rows}:null;
      render();
    },
    processing(busy:boolean,profiling:boolean){
      isAnalyzing=profiling;
      analyzeHere.setAttribute('aria-disabled',String(busy));
      renderFooter();
    },
  };
}
