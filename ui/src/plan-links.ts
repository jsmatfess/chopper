import {operationColor} from './step-labels';
import {describePlan,type PlanTarget} from './plan';
import type {Job} from './app';

// Share border anchors and routing for editor and execution-graph connections.
function connectorGeometry(a:DOMRect,box:DOMRect,b:DOMRect,viewport:DOMRect,inset=0){
  const inside=(position:number,extent:number)=>inset?Math.max(inset,Math.min(extent-inset,position)):position;
  const y1=inside(a.top+a.height/2-viewport.top,viewport.height),y2=inside(b.top+b.height/2-viewport.top,viewport.height);
  let x1:number,x2:number,c1:number,c2:number;
  if(box.left>=b.right){x1=box.left-viewport.left;x2=b.right+5-viewport.left;const bend=Math.max(0,(x1-x2)/2);c1=x1-bend;c2=x2+bend;}
  else if(b.left>=box.right){x1=box.right-viewport.left;x2=b.left-5-viewport.left;const bend=Math.max(0,(x2-x1)/2);c1=x1+bend;c2=x2-bend;}
  else{x1=box.right-viewport.left;x2=b.right+4-viewport.left;c1=c2=Math.min(viewport.width-4,Math.max(x1,x2)+35);}
  x1=inside(x1,viewport.width);x2=inside(x2,viewport.width);
  c1=inside(c1,viewport.width);c2=inside(c2,viewport.width);
  return {x1,y1,x2,y2,path:`M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}`};
}

export function configurePlanLinks() {
  const get=(id:string)=>document.getElementById(id);
  const root=document.querySelector<HTMLElement>('.results')!;
  let highlighted:HTMLElement|null=null, hovered:HTMLButtonElement|null=null,pinned:PlanTarget|null=null;
  let connection:HTMLButtonElement|null=null,frame=0;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('plan-connector');svg.setAttribute('aria-hidden','true');
  svg.innerHTML='<path class="plan-connector-halo"/><path class="plan-connector-line"/><circle r="3.5"/><circle r="4"/>';
  document.body.append(svg);
  const graphSvg=document.createElementNS('http://www.w3.org/2000/svg','svg');graphSvg.classList.add('plan-connector','execution-plan-connector');graphSvg.setAttribute('aria-hidden','true');document.body.append(graphSvg);
  let graphSource:HTMLElement|null=null;
  const graphTargets:HTMLElement[]=[];
  const clearGraph=()=>{graphSource=null;for(const target of graphTargets)target.classList.remove('plan-config-highlight');graphTargets.length=0;graphSvg.classList.remove('is-visible');};
  const rail=document.querySelector('.rail');
  const visiblePage=()=>{
    const strip=get('run-dock');
    return {top:Math.max(0,rail?.getBoundingClientRect().bottom??0),bottom:strip&&!strip.hidden?Math.min(innerHeight,strip.getBoundingClientRect().top):innerHeight};
  };
  const visiblePlan=()=>{
    const page=visiblePage(),panel=root.getBoundingClientRect();
    const top=Math.max(page.top,panel.top+root.clientTop),bottom=Math.min(page.bottom,panel.top+root.clientTop+root.clientHeight);
    return top<bottom?{top,bottom}:null;
  };
  const revealGraphTargets=()=>{
    // A stacked plan shares the page scroll with the graph. Keep the source in place.
    if(!['auto','scroll'].includes(getComputedStyle(root).overflowY)||root.scrollHeight<=root.clientHeight)return;
    const bounds=visiblePlan(),inset=8;
    if(!bounds)return;
    const {top,bottom}=bounds;
    const rows=graphTargets.map(target=>target.getBoundingClientRect());
    const first=rows[0];if(!first||bottom-top<=2*inset)return;
    let start=Math.min(...rows.map(row=>row.top)),end=Math.max(...rows.map(row=>row.bottom));
    if(end-start>bottom-top-2*inset){start=first.top;end=first.bottom;}
    const offset=start<top+inset?start-top-inset:Math.max(0,end-bottom+inset);
    if(offset)root.scrollBy({top:offset,behavior:'instant'});
  };
  const drawGraph=()=>{
    if(!graphSource?.isConnected||!graphTargets.length){graphSvg.classList.remove('is-visible');return;}
    const source=graphSource.getBoundingClientRect(),page=visiblePage();
    const graph=graphSource.closest('.execution-viewport')?.getBoundingClientRect();
    const top=Math.max(source.top,page.top,graph?.top??0),bottom=Math.min(source.bottom,page.bottom,graph?.bottom??page.bottom);
    const left=Math.max(source.left,0,graph?.left??0),right=Math.min(source.right,innerWidth,graph?.right??innerWidth);
    if(top>=bottom||left>=right){graphSvg.classList.remove('is-visible');return;}
    graphSvg.classList.add('is-visible');
    const viewport=graphSvg.getBoundingClientRect(),bounds=visiblePlan()??page;
    const a=new DOMRect(left,top,right-left,bottom-top);
    const box=graphSource.matches('.execution-activity')&&graph?graph:a;
    const inset=Math.min(8,(bounds.bottom-bounds.top)/2);
    graphSvg.setAttribute('viewBox',`0 0 ${viewport.width} ${viewport.height}`);graphSvg.replaceChildren();
    for(const target of graphTargets){
      if(!target.getClientRects().length)continue;
      const targetBox=target.closest('.plan')!.getBoundingClientRect(),link=target.getBoundingClientRect();
      const center=link.top+link.height/2;
      const edge=center<bounds.top?'above':center>bounds.bottom?'below':null;
      const y=edge==='above'?bounds.top+inset:edge==='below'?bounds.bottom-inset:center;
      const b=new DOMRect(targetBox.x,y,targetBox.width,0);
      const {x1,y1,x2,y2,path}=connectorGeometry(a,box,b,viewport,9);
      const group=document.createElementNS(graphSvg.namespaceURI,'g') as SVGGElement;
      const color=stepColor(target);
      if(color)group.dataset.planColor=color;
      graphSvg.append(group);
      const arrowY=y2+(edge==='above'?6:-6);
      const linePath=edge?`${path} M ${x2-5} ${arrowY} L ${x2} ${y2} L ${x2+5} ${arrowY}`:path;
      for(const name of ['plan-connector-halo','plan-connector-line']){const line=document.createElementNS(svg.namespaceURI,'path');line.setAttribute('class',name);line.setAttribute('d',linePath);group.append(line);}
      const dots=edge?[[x1,y1,3.5]]:[[x1,y1,3.5],[x2,y2,4]];
      for(const [x,y,r] of dots){const dot=document.createElementNS(svg.namespaceURI,'circle');dot.setAttribute('cx',String(x));dot.setAttribute('cy',String(y));dot.setAttribute('r',String(r));group.append(dot);}
    }
  };
  const graphFrom=(node:EventTarget|null)=>node instanceof Element?node.closest<HTMLElement>('#execution-history [data-plan-targets]'):null;
  const showGraph=(source:HTMLElement|null)=>{
    clearGraph();if(!source)return;graphSource=source;
    for(const target of (source.dataset.planTargets||'').split(' ')){
      const link=root.querySelector<HTMLElement>(`button[data-plan-target="${target}"]`);
      if(link&&!graphTargets.includes(link)){graphTargets.push(link);link.classList.add('plan-config-highlight');}
    }
    revealGraphTargets();schedule();
  };
  document.addEventListener('pointerover',event=>{const source=graphFrom(event.target);if(event.pointerType!=='touch'&&source&&source!==graphSource)showGraph(source);});
  document.addEventListener('pointerout',event=>{const source=graphFrom(event.target);if(source===graphSource&&source&&!(event.relatedTarget instanceof Node&&source.contains(event.relatedTarget)))showGraph(graphFrom(document.activeElement));});
  document.addEventListener('focusin',event=>{const source=graphFrom(event.target);if(source)showGraph(source);else clearGraph();});
  document.addEventListener('focusout',event=>{if(graphFrom(event.target))clearGraph();});
  const groups=new Map<HTMLElement,{section:HTMLElement;prose:HTMLElement;steps:HTMLOListElement}>();
  const initialize=()=>{
    if(groups.size)return;
    const original=get('plan-description')!,container=document.createElement('div');container.id='plan-description';container.className='plan-description draft-summary';
    const configs=document.body.classList.contains('hosted-workspace')
      ?['source','pipeline','output-settings','review'].map(id=>get(id)!)
      :[...document.querySelectorAll<HTMLElement>('#job-form > section')];
    for(const [offset,config] of configs.entries()){
      const section=document.createElement('section'),heading=document.createElement('h3'),index=document.createElement('span');
      section.className='plan-summary-section';section.dataset.configSection=config.id;heading.className='plan-section-heading';index.className='plan-section-index';
      index.textContent=String(offset+1).padStart(2,'0');
      const sectionLink=button(' '+config.querySelector('h2')!.textContent!,`section-${offset+1}`);sectionLink.classList.add('plan-section-link');sectionLink.prepend(index);heading.append(sectionLink);
      const steps=document.createElement('ol'),prose=document.createElement('div');steps.className='plan-steps';prose.className='plan-notes';
      section.append(heading,steps,prose);container.append(section);groups.set(config,{section,prose,steps});
    }
    for(const [id,field] of [['draft-source','input'],['draft-output','output'],['draft-resources','memory-mode']]){
      const group=groups.get(get(field)!.closest('section')!)!,paragraph=document.createElement('p');paragraph.id=id;group.section.insertBefore(paragraph,group.steps);
    }
    if(document.body.classList.contains('hosted-workspace')){
      const outcome=container.querySelector('#draft-output')!;
      outcome.classList.add('plan-outcome');
      container.prepend(outcome);
    }
    const hint=document.createElement('p');hint.className='hint';hint.textContent='Counts and CSV bytes are unknown until processing. Working memory is an allocation budget, not an RSS cap.';const help=document.createElement('details'),summary=document.createElement('summary');summary.textContent='About these estimates';help.append(summary,hint);container.append(help);
    original.replaceWith(container);
  };
  const clear=()=>{highlighted?.classList.remove('plan-config-highlight');highlighted=null;connection=null;svg.classList.remove('is-visible');if(frame)cancelAnimationFrame(frame);frame=0;};
  const resolve=(target:PlanTarget)=>{
    const section=target.match(/^section-(\d+)$/);
    if(section){
      const region=[...groups.keys()][Number(section[1])-1];
      if(!region)return null;
      const field=region.contains(get('operations'))?get('new-operation')!:region.querySelector<HTMLElement>('input:not(:disabled),select:not(:disabled)')||region;
      const control=field instanceof HTMLInputElement&&field.readOnly&&['input','output'].includes(field.id)?get('browse-'+field.id)!:field;
      return {region,control};
    }
    const step=target.match(/^step-(\d+)$/);
    if(step){
      const region=get('operations')!.querySelector<HTMLElement>(`[data-step="${step[1]}"]`);
      if(!region)return null;
      const fields=region.querySelector('.step-fields')!;
      const control=fields.querySelector<HTMLElement>('input[type="radio"]:checked')||fields.querySelector<HTMLElement>('input:not(:disabled),select:not(:disabled)')||fields.querySelector<HTMLElement>('button:not(:disabled)')||region;
      return {region,control};
    }
    if(target==='pipeline'){
      const region=get('operations')!.closest<HTMLElement>('section')!;
      return {region,control:get('add-operation')!};
    }
    if(target==='resources'){
      const memory=get('memory-mode') as HTMLSelectElement,region=memory.closest('details')!;
      return {region,control:memory.disabled?get('execution-mode')!:memory};
    }
    const field=get(target);
    if(!field)return null;
    const control=field instanceof HTMLInputElement&&field.readOnly&&['input','output'].includes(target)?get('browse-'+target)!:field;
    return {region:field.closest<HTMLElement>('.quantity-field,label')||field,control};
  };
  const stepColor=(link:HTMLElement)=>link.closest<HTMLElement>('.plan-steps li')?.dataset.planColor;
  const draw=()=>{
    frame=0;if(!connection?.isConnected||!highlighted?.isConnected){svg.classList.remove('is-visible');return;}
    svg.classList.add('is-visible');svg.dataset.target=connection.dataset.planTarget;
    const color=stepColor(connection);
    if(color)svg.dataset.planColor=color;
    else svg.removeAttribute('data-plan-color');
    const anchor=highlighted.matches('.step')?highlighted.querySelector('.step-head'):highlighted instanceof HTMLDetailsElement&&!highlighted.open?highlighted.querySelector('summary'):highlighted.matches('section')?highlighted.querySelector('.section-title'):highlighted;
    const a=connection.getBoundingClientRect(),box=connection.closest('.plan')!.getBoundingClientRect(),b=(anchor||highlighted).getBoundingClientRect(),viewport=svg.getBoundingClientRect();
    const {x1,y1,x2,y2,path}=connectorGeometry(a,box,b,viewport);
    svg.setAttribute('viewBox',`0 0 ${viewport.width} ${viewport.height}`);
    for(const line of svg.querySelectorAll('path'))line.setAttribute('d',path);
    const dots=svg.querySelectorAll('circle');dots[0].setAttribute('cx',String(x1));dots[0].setAttribute('cy',String(y1));dots[1].setAttribute('cx',String(x2));dots[1].setAttribute('cy',String(y2));
  };
  const schedule=()=>{if((connection||graphSource)&&!frame)frame=requestAnimationFrame(()=>{draw();drawGraph();});};
  window.addEventListener('scroll',schedule,{capture:true,passive:true});window.addEventListener('resize',schedule);
  const observer=new ResizeObserver(schedule);observer.observe(root);observer.observe(get('job-form')!);
  const linkFrom=(node:EventTarget|null)=>node instanceof Element?node.closest<HTMLButtonElement>('button[data-plan-target]'):null;
  const show=(button:HTMLButtonElement|null)=>{
    clear();if(!button)return;
    const target=resolve(button.dataset.planTarget as PlanTarget);if(!target)return;
    let visible=target.region;
    // Hover identifies the visible disclosure; opening it requires an explicit click.
    for(let parent:HTMLElement|null=visible;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement&&!parent.open)visible=parent;
    highlighted=visible;
    highlighted.classList.add('plan-config-highlight');connection=button;schedule();
  };
  const operations=get('operations')!;
  const stackedPlan=matchMedia('(max-width:760px)');
  let editorStep:HTMLElement|null=null, revealTimer=0;
  const cancelReveal=()=>window.clearTimeout(revealTimer);
  operations.addEventListener('pointermove',event=>{
    if(event.pointerType==='touch'||event.buttons)return;
    const step=(event.target as Element).closest<HTMLElement>('.step[data-step]');
    if(step===editorStep)return;
    editorStep=step;cancelReveal();
    if(!step)return;
    const link=root.querySelector<HTMLButtonElement>(`.plan-steps>li>button[data-plan-target="step-${step.dataset.step}"]`);
    if(!link)return;
    if(stackedPlan.matches){
      // Give clicks priority over hover when revealing the plan scrolls the page.
      revealTimer=window.setTimeout(()=>{
        if(link.isConnected&&step.matches(':hover'))link.scrollIntoView({block:'nearest',inline:'nearest'});
      },200);
    }else{
      const linkBox=link.getBoundingClientRect(),panel=root.getBoundingClientRect(),inset=8;
      const top=Math.min(0,linkBox.top-panel.top-inset),bottom=Math.max(0,linkBox.bottom-panel.bottom+inset);
      if(top||bottom)root.scrollBy({top:top||bottom});
    }
    show(link);
  });
  operations.addEventListener('pointerdown',cancelReveal);
  operations.addEventListener('pointerleave',()=>{editorStep=null;cancelReveal();sync();});
  const pinnedLink=()=>{
    if(!pinned)return null;
    const target=resolve(pinned);
    return target?.region.contains(document.activeElement)?root.querySelector<HTMLButtonElement>(`button[data-plan-target="${pinned}"]`):null;
  };
  const sync=()=>show(linkFrom(document.activeElement)||hovered||pinnedLink());
  document.addEventListener('focusin',event=>{if(!root.contains(event.target as Node)){if(!pinnedLink())pinned=null;sync();}});
  root.addEventListener('pointerover',event=>{const link=linkFrom(event.target);if(link){hovered=link;show(link);}});
  root.addEventListener('pointerout',event=>{const link=linkFrom(event.target);if(link&&!(event.relatedTarget instanceof Node&&link.contains(event.relatedTarget))){hovered=null;sync();}});
  root.addEventListener('focusin',sync);
  root.addEventListener('focusout',()=>{if(!hovered)clear();});
  root.addEventListener('click',event=>{
    const link=linkFrom(event.target);if(!link)return;
    const target=resolve(link.dataset.planTarget as PlanTarget);if(!target)return;
    pinned=link.dataset.planTarget as PlanTarget;
    for(let parent:HTMLElement|null=target.control;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement)parent.open=true;
    if(!target.control.matches('input,select,button,summary'))target.control.tabIndex=-1;
    target.control.focus({preventScroll:true});target.region.scrollIntoView({block:'center'});show(link);
  });
  const button=(text:string,target:PlanTarget)=>{
    const link=document.createElement('button');link.type='button';link.className='plan-link';
    link.dataset.planTarget=target;link.textContent=text;
    link.title='Show the matching configuration';return link;
  };
  return {
    render(operations:Job['operations'],limits:{rows:string;bytes:string;compressed:string},compression:string){
      clear();hovered=null;
      initialize();
      // Only generated buttons enter the template; imported names use textContent.
      const template=document.createElement('template');template.innerHTML=describePlan(operations,limits,compression,(text,target)=>button(text,target).outerHTML);
      const expanded=new Set([...root.querySelectorAll<HTMLDetailsElement>('.plan-step-details[open]')].map(details=>details.dataset.target));
      for(const group of groups.values()){group.prose.replaceChildren();group.steps.replaceChildren();}
      const numbered=new Map<string,HTMLLIElement>();
      for(const link of template.content.querySelectorAll<HTMLButtonElement>('button[data-plan-target]')){
        const target=link.dataset.planTarget as PlanTarget,region=resolve(target)?.region,group=region?groups.get(region.closest('section')!):null;
        if(!group)continue;
        if(target.startsWith('step-')){
          let item=numbered.get(target);
          if(!item){item=document.createElement('li');item.value=Number(target.slice(5))+1;item.dataset.planColor=operationColor(operations[item.value-1]?.type);group.steps.append(item);numbered.set(target,item);}
          item.append(link,document.createTextNode(' '));
        }else group.prose.append(link,document.createTextNode(' '));
      }
      if(document.body.classList.contains('hosted-workspace'))for(const [target,item] of numbered){
        const op=operations[Number(target.slice(5))];
        const columns=(op.columns||[]).map(column=>typeof column==='number'?`#${column}`:column);
        const selected=columns.slice(0,2).join(', ')+(columns.length>2?` +${columns.length-2} more`:'');
        const shares=(op.groups||[]).slice(0,2).map(group=>`${group.percent}% ${group.name}`).join(' · ')+((op.groups?.length||0)>2?` +${op.groups!.length-2} more`:'');
        const summary=op.type==='partition'?`Partition by ${selected||'selected columns'}`:['balanced','interleaved'].includes(op.type)?`${op.files} ${op.type==='interleaved'?'alternating':'consecutive'} parts per group`:op.type==='shuffle'?'Shuffle rows within each group':`Assign ${op.type==='assign_probabilistic'?'approximately ':''}${shares||'named percentages'}`;
        const details=document.createElement('details');details.className='plan-step-details';details.dataset.target=target;details.open=expanded.has(target);
        const label=document.createElement('summary');label.textContent='Rules & details';details.append(label,...item.childNodes);
        item.replaceChildren(button(summary,target as PlanTarget),details);
      }
      for(const group of groups.values())group.steps.hidden=!group.steps.children.length;
      sync();
    },
    summary(){
      clear();hovered=null;
      if(!document.body.classList.contains('hosted-workspace')){
        get('draft-source')!.textContent=(get('input') as HTMLInputElement).value?`Read ${(get('input') as HTMLInputElement).value}.`:'Choose a source file to begin.';
        get('draft-output')!.textContent=(get('output') as HTMLInputElement).value?`Save results to ${(get('output') as HTMLInputElement).value}.`:'Choose an output folder.';
        get('draft-resources')!.textContent=(get('memory-mode') as HTMLSelectElement).value==='auto'?'Automatic working memory.':`${(get('memory') as HTMLInputElement).value} ${(get('memory-unit') as HTMLSelectElement).value} working memory.`;
      }
      for(const [id,target] of [['draft-source','input'],['draft-output','output'],['draft-resources','resources']] as const){
        const paragraph=get(id);if(paragraph?.textContent)paragraph.replaceChildren(button(paragraph.textContent,target));
      }
      sync();
    },
  };
}
