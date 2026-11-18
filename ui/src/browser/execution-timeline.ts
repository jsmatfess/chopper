import {activityDuration,timelineSeconds,type WorkSeconds,type TimelineSeconds} from './measurements';
import {statusLabel} from '../step-labels';
import type {TimingWindow} from './execution-timing';
export type TimelineRow={id:number;title:string;group:string;color?:string;status:string;seconds:WorkSeconds|null;window?:TimingWindow;selected:boolean;matching:boolean;targets:string};
export const timelineTime=(seconds:number)=>`${seconds.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1})} s`;
export class ExecutionTimeline {
 private rows=new Map<number,HTMLTableRowElement>();
 private body:HTMLTableSectionElement;
 private axis:HTMLElement;
 private elapsed:HTMLElement;
 constructor(private root:HTMLElement,select:(id:number)=>void){
  root.innerHTML='<p class="execution-timeline-note">Activity windows may include gaps between repeated groups. Overlap shows nested processing scopes, not parallel workers.</p><p class="execution-timeline-empty" hidden>Timing unavailable for this run. New runs capture a timeline.</p><div class="execution-timeline-scroll" role="region" aria-label="Execution timeline" tabindex="0"><table><caption class="sr-only">Observed execution timing, seconds since processing started</caption><thead><tr><th scope="col">Step</th><th scope="col"><span class="execution-timeline-axis" aria-hidden="true"></span><span class="sr-only">Observed activity window</span></th><th scope="col">Measured work</th></tr></thead><tbody></tbody></table></div><p class="execution-timeline-elapsed"></p>';
  this.body=root.querySelector('tbody')!;this.axis=root.querySelector('.execution-timeline-axis')!;this.elapsed=root.querySelector('.execution-timeline-elapsed')!;
  root.addEventListener('click',event=>{const row=(event.target as Element).closest<HTMLTableRowElement>('tr[data-timeline-row]');if(row){row.querySelector('button')!.focus({preventScroll:true});select(Number(row.dataset.timelineRow));}});
 }
 clear(){this.rows.clear();this.body.replaceChildren();}
 update(input:TimelineRow[],now:TimelineSeconds,active:boolean){
  const focused=this.root.contains(document.activeElement)?document.activeElement as HTMLElement:null;
  input=[...input].sort((a,b)=>(a.window?.start??a.window?.last??Infinity)-(b.window?.start??b.window?.last??Infinity));
  const maximum=Math.max(.1,now,...input.map(row=>row.window?.last??0));
  this.root.querySelector<HTMLElement>('.execution-timeline-empty')!.hidden=input.some(row=>row.window);
  this.axis.replaceChildren(...Array.from({length:5},(_,i)=>{const label=document.createElement('span');label.textContent=timelineTime(maximum*i/4);return label;}));
  this.elapsed.textContent=input.some(row=>row.window)?`${active?'Elapsed':'Captured timeline'} · ${timelineTime(Math.max(0,now,...input.map(row=>row.window?.last??0)))}`:'No captured timing';
  for(const item of input){
   let row=this.rows.get(item.id);
   if(!row){row=document.createElement('tr');row.innerHTML='<th scope="row"><button type="button"><span class="execution-timeline-group"></span><strong></strong></button></th><td><span class="execution-timeline-track" aria-hidden="true"><span class="execution-timeline-bar"></span></span><span class="execution-timeline-times"></span></td><td class="execution-timeline-work"></td>';row.querySelector('button')!.dataset.timelineStep=String(item.id);this.rows.set(item.id,row);this.body.append(row);}
   row.dataset.timelineRow=String(item.id);row.dataset.planTargets=item.targets;row.dataset.status=item.status;row.dataset.planColor=item.color??'slate';row.dataset.selected=String(item.selected);row.dataset.matching=String(item.matching);
   const button=row.querySelector('button')!,track=row.querySelector<HTMLElement>('.execution-timeline-track')!,bar=row.querySelector<HTMLElement>('.execution-timeline-bar')!,window=item.window;
   button.dataset.planTargets=item.targets;button.setAttribute('aria-pressed',String(item.selected));row.querySelector('strong')!.textContent=item.title;const group=row.querySelector<HTMLElement>('.execution-timeline-group')!;group.textContent=item.group;group.hidden=!item.group||item.group===item.title;
   row.querySelector('.execution-timeline-work')!.textContent=item.seconds===null?'—':timelineTime(item.seconds);
   track.hidden=!window;
   if(window){const unfinished=window.status==='active',end=unfinished&&window.start!==null?maximum:window.last,start=window.start??end;
    bar.style.left=`${start/maximum*100}%`;bar.style.width=`${activityDuration(timelineSeconds(start),timelineSeconds(end))/maximum*100}%`;bar.classList.toggle('is-point',window.start===null||end===start);
    const status=window.status==='active'&&active?'In Progress':statusLabel(item.status);
    row.querySelector('.execution-timeline-times')!.textContent=(window.start===null?`Start not observed · seen ${timelineTime(window.last)}`:`${timelineTime(start)} – ${unfinished&&!active?'end not observed':timelineTime(end)}`)+` · ${status}`;
   }else row.querySelector('.execution-timeline-times')!.textContent='Timing unavailable';
  }
  input.forEach((item,index)=>{const row=this.rows.get(item.id)!;if(this.body.children[index]!==row)this.body.insertBefore(row,this.body.children[index]??null);});
  if(focused&&document.activeElement!==focused&&focused.isConnected)focused.focus({preventScroll:true});
 }
}
