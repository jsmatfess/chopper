import {columnChoices, type ColumnSchema} from './column-picker';

import {formulaExamples,type Calculation,type FormulaSample,type Preview} from './formula-examples';

export type FormulaInsertion = {column:number}|{value:string};
export type FormulaInsertionTarget = {
  isFocused:()=>boolean;
  insert:(insertion:FormulaInsertion)=>string|undefined;
};

type Suggestion = {label:string; detail:string; insertion:string; call?:boolean};

declare const __CHOPPER_FORMULA_USAGE__: Record<string,{behavior:string;examples:[string,string][]}>;
const usage = typeof __CHOPPER_FORMULA_USAGE__==='undefined' ? {} : __CHOPPER_FORMULA_USAGE__;

const bareName = /^[\p{L}_][\p{L}\p{N}_]*$/u;
const reserved = /^(TRUE|FALSE|NULL|NOT|AND|OR|IN)$/i;
const alphabetical=new Intl.Collator('en',{sensitivity:'base',numeric:true});
type RankedSuggestion = {option:Suggestion;score:number};
function compareSuggestions(a:RankedSuggestion,b:RankedSuggestion) {
  return a.score-b.score||alphabetical.compare(a.option.label,b.option.label);
}


function token(input:HTMLTextAreaElement) {
  const at = input.selectionStart ?? input.value.length;
  const before = input.value.slice(0, at);
  if ((before.match(/"/g)?.length ?? 0) % 2) return null;
  const prefix = before.match(/(?:\[[^\]]*|\$[0-9]*|[\p{L}\p{N}_.]+)$/u)?.[0] ?? '';
  return {start:at-prefix.length, end:input.selectionEnd??at, prefix};
}

function rank(value:string,query:string,prefixOnly=false) {
  const name=value.toUpperCase();
  if(name===query)return 0;
  if(name.startsWith(query))return 1;
  return !prefixOnly&&name.includes(query)?2:Infinity;
}

function ranked(options:Suggestion[],prefix:string){
  const safe=prefix.startsWith('SAFE.');
  const query=safe?prefix.slice(5):prefix.replace(/^\[/,'');
  const index=prefix.startsWith('$');
  return options.map(option=>{
    const insertion=rank(option.insertion.slice(safe?5:0),query,index);
    const label=index?Infinity:rank(option.label.slice(safe?5:0),query);
    return {option,score:Math.min(insertion,label)};
  }).filter(({score})=>Number.isFinite(score))
    .sort(compareSuggestions).slice(0,16);
}

function formulaTokens(source:string,functions:Map<string,string>,names:Set<string>) {
  const content=document.createDocumentFragment();
  const tokens=/"(?:[^"]|"")*(?:"|$)|\[(?:[^\]]|\]\])*(?:\]|$)|\$[0-9]+|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|(?:SAFE\s*\.)?[\p{L}_][\p{L}\p{M}\p{N}_]*/giu;
  let end=0;
  for(const {0:token,index} of source.matchAll(tokens)){
    if(token.startsWith('"'))continue;
    const after=index+token.length;
    const functionName=token.toUpperCase().replace(/^SAFE\s*\./,'');
    const reference=token.startsWith('[')&&token.endsWith(']')
      ?token.slice(1,-1).replaceAll(']]',']'):token;
    const kind=functions.has(functionName)&&/^\s*\(/.test(source.slice(after))?'function':
      token.startsWith('$')||(!reserved.test(token)&&names.has(reference))?'column':null;
    if(!kind)continue;
    content.append(source.slice(end,index));
    const chip=document.createElement('span');
    chip.className='formula-chip';
    chip.dataset.formulaKind=kind;
    chip.textContent=token;
    content.append(chip);
    end=after;
  }
  content.append(source.slice(end)+(source.endsWith('\n')?'\n':''));
  return content;
}

type Call = {name:string; safe:boolean; commas:number[]; close?:number};

function activeCall(value:string,caret:number,catalog:Map<string,string>) {
  const stack:(Call|null)[]=[];
  const innermost=()=>{
    for(let index=stack.length-1;index>=0;index--){
      const call=stack[index];
      if(call&&catalog.has(call.name))return call;
    }
  };
  let active:Call|undefined;
  // Skip strings and bracketed column names, including unfinished tokens.
  const tokens=/"(?:[^"]|"")*(?:"|$)|\[(?:[^\]]|\]\])*(?:\]|$)|(?:SAFE\s*\.)?[\p{L}_][\p{L}\p{N}_]*(?:\s*\()?|[(),]/giu;
  for(const {0:token,index} of value.matchAll(tokens)){
    const quoted=token.startsWith('"')||token.startsWith('[');
    const opens=!quoted&&token.endsWith('(');
    const at=opens?index+token.length-1:index;
    if(!active&&at>=caret){
      active=innermost();
      if(active?.name!=='IFS'&&active?.name!=='CONCAT_WS')return active;
    }
    if(quoted)continue;
    if(token===')'){
      const closed=stack.pop();
      if(active&&closed===active){
        active.close=at;
        return active;
      }
    }else if(token===',')stack.at(-1)?.commas.push(at);
    else if(token==='(')stack.push(null);
    else if(opens){
      const name=token.slice(0,-1).trimEnd().toUpperCase().replace(/^SAFE\s*\./,'SAFE.');
      const safe=name.startsWith('SAFE.');
      stack.push({name:safe?name.slice(5):name,safe,commas:[]});
    }
  }
  return active??innermost();
}

function literalBoolean(text:string) {
  let part=text.trim();
  while(part.startsWith('(')&&part.endsWith(')'))part=part.slice(1,-1).trim();
  return /^(TRUE|FALSE)$/i.test(part);
}

function activeParameter(call:Call,value:string,caret:number,parameters:string[]) {
  const argument=call.commas.filter(at=>at<caret).length;
  const repeated=parameters.indexOf('...');
  if(repeated<0||argument<repeated)return argument;

  const last=call.commas.length;
  if(call.name==='IFS'){
    if(call.close!==undefined&&last%2===0&&argument===last)return repeated+1;
    if(argument<last||argument%2===1)return argument%2;
  }
  if(call.name==='CONCAT_WS'&&last>=2){
    const tail=value.slice(call.commas[last-1]+1,call.close??value.length).trim();
    const previousIsFlag=last>=3&&literalBoolean(value.slice(call.commas[last-2]+1,call.commas[last-1]));
    const tailIsFlag=literalBoolean(tail)||(call.close===undefined&&previousIsFlag&&
      ['TRUE','FALSE'].some(flag=>flag.startsWith(tail.toUpperCase())));
    if(tailIsFlag){
      const firstFlag=previousIsFlag?last-1:last;
      if(argument>=firstFlag)return repeated+1+argument-firstFlag;
    }
  }
  return repeated;
}

function columnReference(value:string|number,index:number,byIndex:boolean) {
  if(byIndex||typeof value==='number'||/[\r\n]/.test(value))return '$'+index;
  return bareName.test(value)&&!reserved.test(value)?value:'['+value.replaceAll(']',']]')+']';
}

function columnSuggestions(schema:ColumnSchema|null, indexReference:boolean, definition:number):Suggestion[] {
  const current = (schema?.calculatedStart ?? 0) + definition;
  return columnChoices(schema).filter(choice=>schema?.calculatedStart===undefined||choice.index!==current).map(choice=>{
    const {value,label,index}=choice;
    const insertion=columnReference(value,index,indexReference);
    return {label,detail:'Column #'+index,insertion};
  });
}

export function configureFormulaEditor(
  root:HTMLElement,
  calculations:()=>Calculation[],
  sample:()=>FormulaSample|null,
  schema:()=>ColumnSchema|null,
  request:(data:unknown)=>Promise<Preview>,
) {
  let catalog=new Map<string,string>();
  let timer:ReturnType<typeof setTimeout>;
  let revision=0;
  let input:HTMLTextAreaElement|null=null;
  let options:Suggestion[]=[];
  let active=0;
  let offeredAt:number|null=null;

  const field=(target:EventTarget|null) => target instanceof HTMLTextAreaElement &&
    target.matches('[data-field="expression"]') ? target : null;
  let colorRevision=0;
  let colorHeader='';
  let colorNames=new Set<string>();
  const painted=new WeakMap<HTMLTextAreaElement,{value:string;revision:number}>();
  const tokenLayer=(target:HTMLTextAreaElement)=>target.parentElement?.querySelector<HTMLElement>('.formula-token-layer');
  function syncTokenScroll(target:HTMLTextAreaElement,layer=tokenLayer(target)){
    if(!layer)return;
    layer.scrollTop=target.scrollTop;
    layer.scrollLeft=target.scrollLeft;
  }
  function paintFormulas(){
    const header=schema()?.header??[];
    const key=JSON.stringify(header);
    if(colorHeader!==key){
      colorHeader=key;
      colorNames=new Set(header);
      colorRevision++;
    }
    for(const target of root.querySelectorAll<HTMLTextAreaElement>('[data-field="expression"]')){
      const previous=painted.get(target);
      if(previous?.value===target.value&&previous.revision===colorRevision)continue;
      const layer=tokenLayer(target);
      if(!layer)continue;
      layer.replaceChildren(formulaTokens(target.value,catalog,colorNames));
      painted.set(target,{value:target.value,revision:colorRevision});
      syncTokenScroll(target,layer);
    }
  }
  root.addEventListener('scroll',event=>{
    const target=field(event.target);
    if(target)syncTokenScroll(target);
  },true);

  const focusedFormula=()=>{
    const target=field(document.activeElement);
    return target&&root.contains(target)?target:null;
  };
  const insertionTarget:FormulaInsertionTarget={
    isFocused:()=>focusedFormula()!==null,
    insert(insertion){
      const target=focusedFormula();
      if(!target)return;
      let text:string;
      if('value' in insertion){
        if(insertion.value.includes('\r'))return 'This value contains a carriage return that the formula field cannot preserve.';
        text='"'+insertion.value.replaceAll('"','""')+'"';
      }else{
        const choice=columnChoices(schema()).find(column=>column.index===insertion.column);
        if(!choice)return;
        text=columnReference(choice.value,choice.index,false);
      }
      target.setRangeText(text,target.selectionStart,target.selectionEnd,'end');
      target.dispatchEvent(new Event('input',{bubbles:true}));
      close();
    },
  };
  const list=()=>input?.closest('.column-typeahead')?.querySelector<HTMLElement>('[data-formula-suggestions]');
  function showHelp(target:HTMLTextAreaElement, visible=true){
    const help=target.closest('.column-typeahead')?.querySelector<HTMLElement>('[data-formula-help]');
    if(!help)return;
    const signature=help.querySelector('code')!;
    const detail=help.querySelector('small')!;
    const examples=help.querySelector<HTMLElement>('[data-formula-examples]')!;
    const call=visible&&catalog.size
      ?activeCall(target.value,target.selectionStart??target.value.length,catalog):null;
    if(!call){
      if(!help.hidden){
        help.hidden=true;
        signature.replaceChildren();
        detail.textContent='';
        examples.replaceChildren();
        examples.hidden=true;
        delete help.dataset.signature;
      }
      return;
    }
    const syntax=catalog.get(call.name)!;
    const start=syntax.indexOf('(');
    const parameters=syntax.slice(start+1,-1).split(', ');
    const active=activeParameter(call,target.value,target.selectionStart??target.value.length,parameters);
    const key=syntax+':'+call.safe+':'+active;
    if(help.dataset.signature===key)return;
    help.dataset.signature=key;
    signature.replaceChildren((call.safe?'SAFE.':'')+syntax.slice(0,start+1));
    for(const [index,parameter] of parameters.entries()){
      if(index)signature.append(', ');
      if(index===active){
        const current=document.createElement('strong');
        current.textContent=parameter;
        signature.append(current);
      }else signature.append(parameter);
    }
    signature.append(')');
    const reference=usage[call.name];
    detail.textContent=reference?.behavior??'';
    const entries=(reference?.examples??[]).map(([formula,output])=>{
      const entry=document.createElement('li');
      const expression=document.createElement('code');
      expression.textContent=formula;
      const result=document.createElement('code');
      result.textContent=output;
      entry.append(expression,' → ',result);
      return entry;
    });
    examples.replaceChildren(...entries);
    examples.hidden=!entries.length;
    help.hidden=false;
  }

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
  function suggest(target:HTMLTextAreaElement, forced=false){
    const match=token(target);
    if(!match||(!forced&&!match.prefix)){close();return;}
    if(input!==target){close();input=target;}
    const menu=list();
    if(!menu)return;
    const step=Number(target.closest<HTMLElement>('[data-calculation]')?.dataset.calculation);
    const prefix=match.prefix.toUpperCase();
    const safe=prefix.startsWith('SAFE.');
    const functions=Array.from(catalog,([name,detail])=>({
      label:safe?'SAFE.'+name:name,detail,insertion:safe?'SAFE.'+name:name,call:true,
    }));
    options=[
      ...(prefix.startsWith('[')||prefix.startsWith('$')?[]:ranked(functions,prefix)),
      ...(safe?[]:ranked(columnSuggestions(schema(),prefix.startsWith('$'),step),prefix)),
    ].sort(compareSuggestions).map(({option})=>option);
    if(!options.length){close();return;}
    menu.replaceChildren(...options.map((option,index)=>{
      const row=document.createElement('div');
      row.id=menu.id+'-'+index;
      row.dataset.formulaOption=String(index);
      row.setAttribute('role','option');
      const label=document.createElement('span');
      label.className='formula-chip';
      label.dataset.formulaKind=option.call?'function':'column';
      label.textContent=option.label;
      const detail=document.createElement('small');
      detail.textContent=option.detail;
      row.append(label,detail);
      return row;
    }));
    menu.hidden=false;
    offeredAt=target.selectionStart;
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
    if(!target)return;
    showHelp(target);
    suggest(target);
  });
  root.addEventListener('focusin',event=>{
    const target=field(event.target);
    if(target)showHelp(target);
  });
  root.addEventListener('focusout',event=>{
    const target=field(event.target);
    if(target)showHelp(target,false);
    if(target===input)close();
  });
  document.addEventListener('selectionchange',()=>{
    const target=field(document.activeElement);
    if(target&&root.contains(target)){
      showHelp(target);
      if(target===input&&target.selectionStart!==offeredAt)close();
    }
  });
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

  const examples=formulaExamples(root,request);

  return {
    insertionTarget,
    resetSample:()=>examples.reset(),
    startScan:examples.startScan,
    update(){
      const current=++revision;
      paintFormulas();
      examples.invalidate();
      clearTimeout(timer);
      const steps=calculations();
      if(!steps.length){examples.render(undefined,sample(),steps);return;}
      timer=setTimeout(async()=>{
        const source=sample();
        try{
          const result=await request({
            header:source?.header??null, columns:source?.columns??0,
            rows:source?.preview.length?source.preview:[Array<string>(source?.columns??0).fill('')],
            calculations:steps,include_references:true,
          });
          if(current!==revision)return;
          const first=!catalog.size;
          catalog=new Map(result.functions);
          if(first){
            colorRevision++;
            paintFormulas();
            const focused=field(document.activeElement);
            if(focused&&root.contains(focused)){
              showHelp(focused);
              if(token(focused)?.prefix)suggest(focused);
            }
          }
          examples.render(result,source,steps);
        }catch(error){
          if(current===revision)examples.render(undefined,source,steps,error instanceof Error?error.message:String(error));
        }
      },160);
    },
  };
}
