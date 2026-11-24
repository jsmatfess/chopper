export type Column = string | number;
export type ColumnSchema = {input_is_zip?: boolean; columns: number; header: string[] | null; unnamed?:number; calculatedStart?:number};
export function withCalculatedColumns(
  schema: ColumnSchema | null, calculated: {name: string}[],
): ColumnSchema | null {
  if (!schema) return null;
  const names = calculated.map(column=>column.name);
  if (!names.length) return schema;
  const header = schema.header ?? Array<string>(schema.columns).fill('');
  return {...schema, columns: schema.columns + names.length, header: [...header, ...names], unnamed:schema.header?0:schema.columns, calculatedStart:schema.columns};
}
type Choice = {value: Column; label: string; index: number};
const escape = (s: unknown) => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function columnChoices(schema: ColumnSchema | null): Choice[] {
  if(!schema)return [];
  const counts=new Map<string,number>();
  schema.header?.slice(schema.unnamed??0).forEach(name=>counts.set(name,(counts.get(name)||0)+1));
  return Array.from({length:schema.columns},(_,index)=>{
    const name=index<(schema.unnamed??0)?undefined:schema.header?.[index];
    const unique=name!==undefined&&counts.get(name)===1;
    return {index,value:unique?name:index,label:name===undefined?`Column #${index}`:name||`(empty header) · #${index}`};
  }).filter(choice=>choice.index<(schema.calculatedStart??schema.columns)||Boolean(schema.header?.[choice.index]));
}
export function columnIndex(column: Column, schema: ColumnSchema | null): number | undefined {
  if(!schema)return undefined;
  if(typeof column==='number')return Number.isSafeInteger(column)&&column>=0&&column<schema.columns?column:undefined;
  if(schema.header?.slice(schema.unnamed??0).filter(name=>name===column).length!==1)return undefined;
  const index=schema.header?.indexOf(column,schema.unnamed??0)??-1;
  return index<0?undefined:index;
}
export function matchingColumns(schema: ColumnSchema | null, selected: Column[], query: string): Choice[] {
  const needle=query.trim().toLocaleLowerCase();
  return columnChoices(schema).filter(choice=>!selected.some(c=>columnIndex(c,schema)===choice.index)
    && `${choice.label} #${choice.index}`.toLocaleLowerCase().includes(needle));
}
export function pickerMarkup(field: 'columns'|'strata', selected: Column[], step: number, schema: ColumnSchema | null, message: string) {
  const choices=columnChoices(schema);
  const available=matchingColumns(schema,selected,'');
  const label=field==='columns'?'Columns':'Stratify by';
  const id=`column-picker-${step}-${field}`;
  return `<div class="column-picker" data-column-field="${field}"><label for="${id}">${label}${field==='strata'?' <span class="optional">optional</span>':''}</label><div class="column-typeahead"><div class="column-input"><div class="column-chips" role="list" aria-label="${label} selected columns">${selected.map((column,index)=>{
    const resolved=columnIndex(column,schema),choice=choices.find(c=>c.index===resolved);
    const name=choice?.label??(typeof column==='number'?`Column #${column}`:column);
    return `<div class="column-chip" role="listitem" data-column-index="${index}"><button type="button" class="chip-grip" draggable="true" aria-label="Reorder ${escape(name)}" title="Drag to reorder, or use Left and Right arrow keys"><svg viewBox="0 0 16 24" width="10" height="16" aria-hidden="true" fill="currentColor"><circle cx="5" cy="5" r="1.5"/><circle cx="11" cy="5" r="1.5"/><circle cx="5" cy="12" r="1.5"/><circle cx="11" cy="12" r="1.5"/><circle cx="5" cy="19" r="1.5"/><circle cx="11" cy="19" r="1.5"/></svg></button><span>${escape(name)}</span><button type="button" class="chip-remove" data-column-remove aria-label="Remove ${escape(name)}">×</button></div>`;
  }).join('')}</div><input id="${id}" data-column-search role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-results" aria-label="Add ${label.toLowerCase()} column" autocomplete="off" placeholder="${!schema?'Load input columns to choose':available.length?(selected.length?'Add column?':'Type to find a column?'):'All columns selected'}" ${!available.length?'disabled':''}></div><div id="${id}-results" class="column-results" role="listbox" aria-label="Matching columns" hidden></div><span class="sr-only" data-column-feedback role="status"></span></div><small class="column-picker-hint">${escape(message||'Drag chips to reorder, or focus a grip and use ← / →.')}</small>${!schema?'<button type="button" class="text-button" data-column-reload>Load columns</button>':''}</div>`;
}

export function bindColumnPickers(container: HTMLElement, getSelection: (picker: HTMLElement)=>Column[], getSchema: (picker: HTMLElement)=>ColumnSchema|null, changed: (picker: HTMLElement, columns: Column[])=>void, reload: ()=>void) {
  let drag:{picker:HTMLElement;column:Column;target:HTMLElement|null;position:'before'|'after'}|null=null;
  const clearDrop=()=>{for(const chip of container.querySelectorAll<HTMLElement>('[data-column-drop]'))delete chip.dataset.columnDrop;};
  const finishDrag=()=>{clearDrop();for(const chip of container.querySelectorAll('.column-chip.is-dragging'))chip.classList.remove('is-dragging');drag=null;};
  const move=(picker: HTMLElement,from: number,to: number)=>{
    const columns=[...getSelection(picker)];
    if(to<0||to>=columns.length||from===to)return;
    columns.splice(to,0,...columns.splice(from,1));changed(picker,columns);
    const handle=picker.querySelectorAll<HTMLButtonElement>('.chip-grip')[to];handle?.closest('.column-chip')?.scrollIntoView({block:'nearest',inline:'nearest'});handle?.focus({preventScroll:true});
    picker.querySelector<HTMLElement>('[data-column-feedback]')!.textContent=`Moved column to position ${to+1} of ${columns.length}.`;
  };
  const close=(picker: HTMLElement)=>{
    const input=picker.querySelector<HTMLInputElement>('[data-column-search]')!;
    input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
    picker.querySelector<HTMLElement>('.column-results')!.hidden=true;
  };
  const activate=(picker: HTMLElement,index: number)=>{
    const options=[...picker.querySelectorAll<HTMLElement>('[data-column-option]')];
    options.forEach((option,i)=>option.setAttribute('aria-selected',String(i===index)));
    const input=picker.querySelector<HTMLInputElement>('[data-column-search]')!;
    if(options[index]){input.setAttribute('aria-activedescendant',options[index].id);options[index].scrollIntoView({block:'nearest'});}
    else input.removeAttribute('aria-activedescendant');
  };
  const suggest=(picker: HTMLElement)=>{
    const input=picker.querySelector<HTMLInputElement>('[data-column-search]')!;
    if(input.disabled)return;
    const choices=matchingColumns(getSchema(picker),getSelection(picker),input.value);
    const list=picker.querySelector<HTMLElement>('.column-results')!;
    list.innerHTML=choices.length?choices.map(choice=>`<div id="${input.id}-option-${choice.index}" role="option" aria-selected="false" data-column-option="${choice.index}"><span>${escape(choice.label)}</span><small>#${choice.index}</small></div>`).join(''):'<div class="column-no-results">No matching columns</div>';
    list.hidden=false;input.setAttribute('aria-expanded','true');activate(picker,0);
    picker.querySelector<HTMLElement>('[data-column-feedback]')!.textContent=choices.length?`${choices.length} matching columns.`:'No matching columns.';
  };
  const add=(picker: HTMLElement,index: number)=>{
    const choice=matchingColumns(getSchema(picker),getSelection(picker),'').find(c=>c.index===index);
    if(!choice)return;
    changed(picker,[...getSelection(picker),choice.value]);
    const input=picker.querySelector<HTMLInputElement>('[data-column-search]')!;
    if(input.disabled)picker.querySelector<HTMLButtonElement>('.chip-grip')?.focus();
    else input.focus();
  };
  container.addEventListener('input',event=>{
    const target=event.target as HTMLElement;
    if(target.matches('[data-column-search]'))suggest(target.closest<HTMLElement>('[data-column-field]')!);
  });
  container.addEventListener('focusin',event=>{
    const target=event.target as HTMLElement;
    if(target.matches('[data-column-search]'))suggest(target.closest<HTMLElement>('[data-column-field]')!);
  });
  container.addEventListener('focusout',event=>{
    const picker=(event.target as HTMLElement).closest<HTMLElement>('[data-column-field]');
    if(picker&&!picker.contains(event.relatedTarget as Node|null))close(picker);
  });
  container.addEventListener('pointerdown',event=>{
    if((event.target as HTMLElement).closest('[data-column-option]'))event.preventDefault();
  });
  container.addEventListener('click',event=>{
    const target=event.target as HTMLElement;
    if(target.closest('[data-column-reload]')){reload();return;}
    const option=target.closest<HTMLElement>('[data-column-option]');
    if(option){add(option.closest<HTMLElement>('[data-column-field]')!,Number(option.dataset.columnOption));return;}
    if(target.matches('.column-input,.column-chips')){target.closest<HTMLElement>('[data-column-field]')!.querySelector<HTMLInputElement>('[data-column-search]')?.focus();return;}
    if(target.matches('[data-column-search]')){suggest(target.closest<HTMLElement>('[data-column-field]')!);return;}
    if(!target.closest('[data-column-remove]'))return;
    const picker=target.closest<HTMLElement>('[data-column-field]')!;
    const index=Number(target.closest<HTMLElement>('[data-column-index]')!.dataset.columnIndex);
    changed(picker,getSelection(picker).filter((_,i)=>i!==index));picker.querySelector<HTMLInputElement>('[data-column-search]')?.focus();
  });
  container.addEventListener('keydown',event=>{
    if(drag)return;
    const target=event.target as HTMLElement;
    if(target.matches('[data-column-search]')){
      const input=target as HTMLInputElement,picker=input.closest<HTMLElement>('[data-column-field]')!;
      if(event.key==='Escape'){event.preventDefault();close(picker);return;}
      if(event.key==='Tab'){
        if(event.shiftKey||input.getAttribute('aria-expanded')!=='true')return;
        const option=picker.querySelector<HTMLElement>('[data-column-option][aria-selected="true"]');
        if(option){event.preventDefault();add(picker,Number(option.dataset.columnOption));close(picker);}
        return;
      }
      if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return;
      event.preventDefault();
      if(input.getAttribute('aria-expanded')!=='true'){suggest(picker);return;}
      const options=[...picker.querySelectorAll<HTMLElement>('[data-column-option]')];
      const active=options.findIndex(option=>option.getAttribute('aria-selected')==='true');
      if(event.key==='Enter'){if(options[active])add(picker,Number(options[active].dataset.columnOption));return;}
      if(options.length)activate(picker,(active+(event.key==='ArrowDown'?1:-1)+options.length)%options.length);
      return;
    }
    if(!target.matches('.chip-grip')||!['ArrowLeft','ArrowRight'].includes(event.key))return;
    event.preventDefault();
    const index=Number(target.closest<HTMLElement>('[data-column-index]')!.dataset.columnIndex);
    move(target.closest<HTMLElement>('[data-column-field]')!,index,index+(event.key==='ArrowLeft'?-1:1));
  });
  container.addEventListener('dragstart',event=>{
    const handle=(event.target as Element).closest('.chip-grip');if(!handle)return;
    const picker=handle.closest<HTMLElement>('[data-column-field]')!,chip=handle.closest<HTMLElement>('[data-column-index]')!;
    drag={picker,column:getSelection(picker)[Number(chip.dataset.columnIndex)],target:null,position:'before'};chip.classList.add('is-dragging');
    if(event.dataTransfer){event.dataTransfer.setData('application/x-chopper-column',JSON.stringify(drag.column));event.dataTransfer.effectAllowed='move';event.dataTransfer.setDragImage(chip,10,10);}
  });
  container.addEventListener('dragover',event=>{
    if(!drag)return;clearDrop();
    if(!drag.picker.isConnected||(event.target as Element).closest('[data-column-field]')!==drag.picker){drag.target=null;return;}
    const chips=[...drag.picker.querySelectorAll<HTMLElement>('[data-column-index]')];
    // Wrapped chips use the pointer's row first, then the inline midpoint.
    const rtl=getComputedStyle(drag.picker).direction==='rtl';
    const target=chips.find(chip=>{const box=chip.getBoundingClientRect();return event.clientY<box.top||(event.clientY<=box.bottom&&(rtl?event.clientX>box.left+box.width/2:event.clientX<box.left+box.width/2));})??chips.at(-1);
    if(!target)return;const box=target.getBoundingClientRect(),position=event.clientY>box.bottom||(event.clientY>=box.top&&(rtl?event.clientX<box.left+box.width/2:event.clientX>=box.left+box.width/2))?'after':'before';
    drag.target=target;drag.position=position;
    const from=getSelection(drag.picker).indexOf(drag.column),slot=Number(target.dataset.columnIndex)+(position==='after'?1:0),to=slot>from?slot-1:slot;
    if(from<0)return;event.preventDefault();if(event.dataTransfer)event.dataTransfer.dropEffect='move';
    if(to!==from)target.dataset.columnDrop=position;
  });
  container.addEventListener('dragleave',event=>{if(drag&&!(event.relatedTarget instanceof Node&&drag.picker.contains(event.relatedTarget))){clearDrop();drag.target=null;}});
  container.addEventListener('drop',event=>{
    if(!drag)return;
    const source=drag,valid=(event.target as Element).closest('[data-column-field]')===source.picker;
    const from=valid&&source.picker.isConnected?getSelection(source.picker).indexOf(source.column):-1,slot=source.target?.isConnected?Number(source.target.dataset.columnIndex)+(source.position==='after'?1:0):-1;
    finishDrag();if(valid&&from>=0&&slot>=0){event.preventDefault();move(source.picker,from,slot>from?slot-1:slot);}
  });
  container.addEventListener('dragend',finishDrag);
  container.addEventListener('keydown',event=>{if(event.key==='Escape'&&drag){finishDrag();}});

}
