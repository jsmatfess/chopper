import {activityDuration,timelineSeconds,type WorkSeconds,type TimelineSeconds} from './measurements';
import {statusLabel} from '../step-labels';
import type {TimingGap,TimingWindow} from './execution-timing';
export type TimelineRow={id:number;title:string;group:string;color?:string;status:string;seconds:WorkSeconds|null;window?:TimingWindow;gaps?:TimingGap[];selected:boolean;matching:boolean;targets:string};
export const timelineTime=(seconds:number)=>`${seconds.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})} s`;
// Dense tracks use a single bitmap for completed attempts to bound DOM cost.
function renderTimingBars(track:HTMLElement,window:TimingWindow,gaps:TimingGap[],end:number,maximum:number,endUnknown:boolean){
 const dense=gaps.length>32;
 let start=window.start??gaps[0]?.[0]??end;
 const existing=track.firstElementChild;
 if(dense){
  const canvas=existing instanceof HTMLCanvasElement?existing:document.createElement('canvas');
  if(canvas!==existing){canvas.className='execution-timeline-dense';track.replaceChildren(canvas);}
  const width=Math.max(1,track.clientWidth),scale=width/maximum;
  if(canvas.width!==width||canvas.height!==16){canvas.width=width;canvas.height=16;}
  const context=canvas.getContext('2d');
  if(context){
   context.clearRect(0,0,canvas.width,canvas.height);
   context.fillStyle=getComputedStyle(canvas).color;
   for(const [stop,resume] of gaps){
    const left=Math.round(start*scale),right=Math.round(stop*scale);
    if(right>left)context.fillRect(left,1,right-left,14);
    start=resume;
   }
  }
  start=gaps.at(-1)![1];
 }else if(existing instanceof HTMLCanvasElement)existing.remove();
 const count=dense?2:gaps.length+1;
 while(track.children.length>count)track.lastElementChild!.remove();
 for(let i=dense?1:0;i<count;i++){
  let bar=track.children[i] as HTMLElement|undefined;
  if(!bar){bar=document.createElement('span');bar.className='execution-timeline-bar';track.append(bar);}
  const stop=dense?end:gaps[i]?.[0]??end;
  bar.style.left=`${start/maximum*100}%`;
  bar.style.width=`${activityDuration(timelineSeconds(start),timelineSeconds(stop))/maximum*100}%`;
  bar.classList.toggle('is-point',start===stop);
  bar.classList.toggle('is-open',i===count-1&&endUnknown);
  start=gaps[i]?.[1]??end;
 }
}
export class ExecutionTimeline {
 private rows=new Map<number,HTMLTableRowElement>();
 private body:HTMLTableSectionElement;
 private axis:HTMLElement;
 private elapsed:HTMLElement;
 constructor(private root:HTMLElement,select:(id:number)=>void){
  root.innerHTML='<p class="execution-timeline-note">Gaps show observed pauses between attempts for the same step. Overlap shows nested processing scopes, not parallel workers.</p><p class="execution-timeline-empty" hidden>Timing unavailable for this run. New runs capture a timeline.</p><div class="execution-timeline-scroll" role="region" aria-label="Execution timeline" tabindex="0"><table><caption class="sr-only">Observed execution timing, seconds since processing started</caption><thead><tr><th scope="col">Step</th><th scope="col"><span class="execution-timeline-axis" aria-hidden="true"></span><span class="sr-only">Observed activity window</span></th><th scope="col">Measured work</th></tr></thead><tbody></tbody></table></div><p class="execution-timeline-elapsed"></p>';
  this.body=root.querySelector('tbody')!;this.axis=root.querySelector('.execution-timeline-axis')!;this.elapsed=root.querySelector('.execution-timeline-elapsed')!;
  root.addEventListener('click',event=>{const row=(event.target as Element).closest<HTMLTableRowElement>('tr[data-timeline-row]');if(row){row.querySelector('button')!.focus({preventScroll:true});select(Number(row.dataset.timelineRow));}});
 }
 clear(){this.rows.clear();this.body.replaceChildren();}
 update(input:TimelineRow[],now:TimelineSeconds,active:boolean){
  const focused=this.root.contains(document.activeElement)?document.activeElement as HTMLElement:null;
  input=[...input].sort((a,b)=>(a.window?.start??a.window?.last??Infinity)-(b.window?.start??b.window?.last??Infinity));
  const elapsed=Math.max(now,...input.map(row=>Math.max(row.window?.last??0,row.gaps?.at(-1)?.[1]??0)));
  // Leave room for the live edge to grow without setting the chart's scale to that edge.
  const maximum=active?Math.max(10,elapsed+4):Math.max(.1,elapsed);
  this.root.dataset.live=String(active);
  this.root.querySelector<HTMLElement>('.execution-timeline-empty')!.hidden=input.some(row=>row.window);
  this.axis.replaceChildren(...Array.from({length:5},(_,i)=>{const label=document.createElement('span');label.textContent=timelineTime(maximum*i/4);return label;}));
  this.elapsed.textContent=input.some(row=>row.window)?`${active?'Elapsed':'Captured timeline'} · ${timelineTime(elapsed)}`:'No captured timing';
  for(const item of input){
   let row=this.rows.get(item.id);
   if(!row){row=document.createElement('tr');row.innerHTML='<th scope="row"><button type="button"><span class="execution-timeline-group"></span><strong></strong></button></th><td><span class="execution-timeline-track" aria-hidden="true"></span><span class="execution-timeline-times"></span></td><td class="execution-timeline-work"></td>';row.querySelector('button')!.dataset.timelineStep=String(item.id);this.rows.set(item.id,row);this.body.append(row);}
   row.dataset.timelineRow=String(item.id);row.dataset.planTargets=item.targets;row.dataset.status=item.status;row.dataset.planColor=item.color??'slate';row.dataset.selected=String(item.selected);row.dataset.matching=String(item.matching);
   const button=row.querySelector('button')!,track=row.querySelector<HTMLElement>('.execution-timeline-track')!,window=item.window;
   button.dataset.planTargets=item.targets;button.setAttribute('aria-pressed',String(item.selected));row.querySelector('strong')!.textContent=item.title;const group=row.querySelector<HTMLElement>('.execution-timeline-group')!;group.textContent=item.group;group.hidden=!item.group||item.group===item.title;
   row.querySelector('.execution-timeline-work')!.textContent=item.seconds===null?'—':timelineTime(item.seconds);
   track.hidden=!window;
   if(window){
    const gaps=item.gaps??[],latestResume=gaps.at(-1)?.[1]??0,last=Math.max(window.last,latestResume);
    const unfinished=window.status==='active'||latestResume>window.last;
    const advancing=unfinished&&active&&item.status==='in_progress',endUnknown=unfinished&&!advancing||window.status==='unknown';
    const hasObservedStart=window.start!==null||gaps.length>0;
    const end=unfinished&&hasObservedStart&&(advancing||!active)?elapsed:last;
    renderTimingBars(track,window,gaps,end,maximum,endUnknown);
    let status=(window.start===null?`Start not observed · seen ${timelineTime(last)}`:`${timelineTime(window.start)} – ${endUnknown?'end not observed':timelineTime(end)}`)+` · ${statusLabel(item.status)}`;
    if(gaps.length){
     const duration=gaps.reduce((sum,[stop,resume])=>sum+(resume-stop),0);
     status+=` · ${gaps.length.toLocaleString()} ${gaps.length===1?'pause':'pauses'} (${duration<.1?'<0.1 s':timelineTime(duration)})`;
    }
    row.querySelector('.execution-timeline-times')!.textContent=status;
   }else row.querySelector('.execution-timeline-times')!.textContent='Timing unavailable';
  }
  input.forEach((item,index)=>{const row=this.rows.get(item.id)!;if(this.body.children[index]!==row)this.body.insertBefore(row,this.body.children[index]??null);});
  if(focused&&document.activeElement!==focused&&focused.isConnected)focused.focus({preventScroll:true});
 }
}
