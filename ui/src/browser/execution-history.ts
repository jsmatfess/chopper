import {lifecycleScopes} from './stages';
import {counter,averageRate,workSeconds,timelineSeconds,type TimelineSeconds} from './measurements';
import {configuredLabel,operationName,operationColor,statusLabel} from '../step-labels';
import {motionMarkup,stepMotion} from './execution-motion';
import {ExecutionDag,edgePath,DAG_NODE_WIDTH,DAG_NODE_HEIGHT,type DagFrame} from './execution-dag';
import {ExecutionEvents,MAX_EXECUTION_EVENTS,eventKinds,stepSlot,type ExecutionEvent} from './execution-events';
import {PHYSICAL_ID_BASE,MAX_PHYSICAL_STEPS,physicalTitles,type PhysicalSummary} from './physical-history';
import type {Job} from '../app';
import {ExecutionTiming,TimingGapLog,TimingGapWriter,MAX_TIMING_WINDOWS,validTiming,type TimingWindow} from './execution-timing';
import {ExecutionTimeline,type TimelineRow} from './execution-timeline';
import {captureExplanationSettings,explainStep,explanationLevels,fixedStepKinds} from './execution-explanations';
export type StepStatus='unknown'|'active'|'completed'|'interrupted'|'failed'|'handed_off';
export type Measurement={status:StepStatus;rows?:number;seconds?:number;files?:number};
export type Observation={completedStages?:number[];processingComplete?:boolean;events?:ExecutionEvent[];eventsOmitted?:number;timeline?:TimingWindow[];timeline_seconds?:number;physical?:PhysicalSummary[];read?:Measurement;write?:Measurement;export?:Measurement;marker?:Measurement;unavailable?:boolean;deliveryCoalesced?:boolean};
const keys=fixedStepKinds;
const titles=['Read input','Write CSV','Save destination files','Confirm completion marker'];
const statuses:StepStatus[]=['unknown','active','completed','interrupted','failed','handed_off'];
function validMeasurement(value:Measurement){return value&&typeof value==='object'&&statuses.includes(value.status)&&[value.rows,value.files].every(count=>count===undefined||Number.isSafeInteger(count)&&count>=0)&&(value.seconds===undefined||Number.isFinite(value.seconds)&&value.seconds>=0);}
export class ExecutionHistory {
  readonly flow:string;
  readonly configured:{id:number;label:string}[];
  readonly configurationOmitted:boolean;
  revision=0;
  readonly steps:(Measurement&{id:number;title:string;operation?:number}&Partial<PhysicalSummary>)[]=[];
  readonly events:ExecutionEvent[]=[];
  eventsOmitted=0;
  unavailable=false;
  readonly supported:boolean;
  readonly prepared:boolean;
  readonly allocationLabels:string[][];
  readonly explanationSettings:ReturnType<typeof captureExplanationSettings>;
  deliveryCoalesced=false;
  active=true;
  processingComplete=false;
  readonly completedStages=new Set<number>();
  readonly timeline=new Map<number,TimingWindow>();
  readonly timingGaps=new TimingGapLog();
  private timelineClock=0;
  private timelineReceived=0;
  private timelineStopped:number|null=null;
  timelineNow(now=performance.now()):TimelineSeconds{
    return timelineSeconds(this.timelineStopped??(this.timeline.size?this.timelineClock+(this.active&&!this.steps.some(step=>step.id===3&&step.status==='completed')?Math.max(0,(now-this.timelineReceived)/1000):0):0));
  }
  addTimingGapBlock(run:number,buffer:unknown){
    if(run!==this.run)return false;
    if(!this.timingGaps.add(buffer))this.unavailable=true;
    if(this.active)return false;
    if(!this.timingGaps.read(Infinity))this.unavailable=true;
    this.timelineStopped=Math.max(this.timelineNow(),this.timingGaps.last);
    this.revision++;return true;
  }
  interruptedAs:'interrupted'|'unknown'='unknown';
  constructor(readonly run:number,job:Job){
    this.explanationSettings=captureExplanationSettings(job);
    const settings:string[]=[];
    if(job.compression!=null)settings.push(`compression: ${String(job.compression).slice(0,64)}`);
    for(const key of ['encoding','headers','delimiter','quote','escape','line_ending','bom','skip_empty_lines'] as const){const value=job.output_csv[key];if(value!=null)settings.push(`${key}: ${String(value).slice(0,64)}`);}
    for(const key of ['rows','bytes','compressed_bytes'] as const)if(job.limits[key]!=null)settings.push(`${key}: ${job.limits[key]}`);
    this.configurationOmitted=job.operations.length>16||String(job.compression).length>64||Object.values(job.output_csv).some(value=>value!=null&&String(value).length>64)||job.operations.slice(0,16).some(op=>[op.columns,op.strata,op.groups].some(values=>(values?.length??0)>16)||(op.columns??[]).slice(0,16).some(column=>String(column).length>64)||(op.strata??[]).slice(0,16).some(column=>String(column).length>64)||(op.groups??[]).slice(0,16).some(group=>String(group.name).length>64||String(group.percent).length>32)||String(op.type).length>64||String(op.strategy??'').length>64||String(op.files??'').length>32);
    this.allocationLabels=job.operations.slice(0,16).map(op=>(op.groups??[]).slice(0,16).map(group=>String(group.name).slice(0,64)));
    const operations=job.operations.slice(0,16).map((op,index)=>`${index+1}. ${String(op.type).slice(0,64)}${op.files!=null?` (${String(op.files).slice(0,32)} parts)`:''}${op.strategy?` (${String(op.strategy).slice(0,64)})`:''}${op.columns?` (${op.columns.slice(0,16).map(column=>String(column).slice(0,64)).join(', ')})`:''}${op.groups?` (requested ${op.groups.slice(0,16).map(group=>`${String(group.name).slice(0,64)} ${String(group.percent).slice(0,32)}%`).join(', ')})`:''}${op.strata?.length?` (strata columns: ${op.strata.slice(0,16).map(column=>String(column).slice(0,64)).join(', ')})`:''}`);
    this.configured=operations.map((label,index)=>({id:index+1,label}));
    this.configured.push({id:job.operations.length+1,label:`${job.operations.length+1}. CSV output (${settings.join(', ')})`});
    this.flow=this.configured.map(item=>item.label).join(' → ')+(job.operations.length>16?' · Additional configured operations omitted':'');
    this.prepared=job.operations.length>0;
    this.supported=job.operations.length<=16&&job.operations.every(op=>['partition','shuffle','assign','assign_probabilistic','balanced','interleaved'].includes(op.type))&&['none','gzip','zip'].includes(job.compression);
    this.unavailable=!this.supported;
  }
  accept(run:number,observation:Observation){
    if(run!==this.run)return;
    this.revision++;
    if(observation.completedStages){
      if(observation.completedStages.length>18||observation.completedStages.some(stage=>!Number.isInteger(stage)||stage<0||stage>this.configured.length))this.unavailable=true;
      else for(const stage of observation.completedStages)this.completedStages.add(stage);
    }
    this.unavailable ||= !!observation.unavailable;
    this.deliveryCoalesced ||= !!observation.deliveryCoalesced;
    if(observation.events){
      if(observation.events.length>MAX_EXECUTION_EVENTS)this.unavailable=true;
      for(const event of observation.events.slice(this.events.length,MAX_EXECUTION_EVENTS)){
        if(event.index!==this.events.length||stepSlot(event.step)<0||!eventKinds.includes(event.kind)||!Number.isFinite(event.seconds)||event.seconds<0||event.seconds<(this.events.at(-1)?.seconds??0)){this.unavailable=true;break;}
        this.events.push({...event});
      }
    }
    if(observation.eventsOmitted!=null){if(Number.isSafeInteger(observation.eventsOmitted)&&observation.eventsOmitted>=0&&observation.eventsOmitted<=(MAX_PHYSICAL_STEPS+4)*eventKinds.length)this.eventsOmitted=Math.max(this.eventsOmitted,observation.eventsOmitted);else this.unavailable=true;}
    for(const value of observation.physical??[]){
      if(!Number.isInteger(value.id)||value.id<PHYSICAL_ID_BASE||value.id>=PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS){this.unavailable=true;continue;}
      let step=this.steps.find(s=>s.id===value.id);
      if(step&&((value.last_attempt??0)<(step.last_attempt??0)||(value.last_terminal??0)<(step.last_terminal??0)))continue;
      if(value.status==='active'&&stageFinished(this,{...value,title:physicalTitles[value.kind]})){this.unavailable=true;continue;}
      const motif=stepMotion(value,this.configured);
      const title=(value.role?'Strata · ':'')+(motif==='uniform_sort'?'Resident random-key sort':motif==='fused_sort'?'Fused resident random-key sort':physicalTitles[value.kind]);
      const status=!this.active&&value.status==='active'?(step&&step.status!=='active'?step.status:'unknown'):value.status;
      if(!step&&value.status==='unknown'&&!(value.last_attempt??value.attempts??0))continue;
      if(!step){if(this.steps.length>=MAX_PHYSICAL_STEPS+4){this.unavailable=true;break;}step={id:value.id,title,status:value.status};this.steps.push(step);}
      Object.assign(step,value,{title,status});
    }
    keys.forEach((key,id)=>{
      const incoming=observation[key];if(!incoming)return;
      if(!validMeasurement(incoming)){this.unavailable=true;const prior=this.steps.find(step=>step.id===id);if(prior?.status==='active')prior.status='unknown';return;}
      if(incoming.status==='unknown'){const prior=this.steps.find(s=>s.id===id);if(prior){if(prior.status!=='completed')prior.status='unknown';return;}if(!this.events.some(event=>event.step===id&&event.kind==='active'))return;}
      let step=this.steps.find(s=>s.id===id);
      if(!step){step={id,title:titles[id],status:'unknown',...(id===1?{operation:1}:{})};this.steps.push(step);}
      if(step.status!=='completed')Object.assign(step,incoming,{status:!this.active&&incoming.status==='active'?(step.status==='active'?'unknown':step.status):incoming.status});
      if(id===0){const codec=this.steps.find(s=>s.kind&&['gzip_input','zip_input'].includes(s.kind));if(codec)step.source=codec.id;}
      if(id===2&&!this.prepared){const codec=this.steps.find(s=>s.kind&&['gzip_output','zip_archive'].includes(s.kind));if(codec)step.source=codec.id;}
      if(id===2&&this.prepared){const materialized=this.steps.find(s=>s.kind==='materialize');step.source=materialized?.id;step.source_omitted=!materialized;}
    });
    this.processingComplete ||= observation.processingComplete===true&&!this.unavailable;
    if(observation.timeline){
      const clock=observation.timeline_seconds;
      if(!Number.isFinite(clock)||clock!<0||!Array.isArray(observation.timeline)||observation.timeline.length>MAX_TIMING_WINDOWS){this.unavailable=true;return;}
      if(clock!<this.timelineClock)return;
      if(!this.timingGaps.read(clock!))this.unavailable=true;
      const received=performance.now(),displayed=this.timelineNow(received);
      for(const value of observation.timeline){
        if(!validTiming(value,clock!)){this.unavailable=true;continue;}
        if(!this.steps.some(step=>step.id===value.step))continue;
        const prior=this.timeline.get(value.step);if(prior&&prior.last>value.last)continue;
        if(prior&&prior.start!==value.start){this.unavailable=true;continue;}
        const {step,start,last,status}=value;
        this.timeline.set(step,{step,start,last,status});
      }
      this.timelineClock=clock!;this.timelineReceived=received-Math.max(0,displayed-clock!)*1000;
      if(this.timelineStopped!==null)this.timelineStopped=Math.max(this.timelineStopped,clock!);
    }
  }
  interrupt(status:'interrupted'|'unknown'){
    if(!this.timingGaps.read(Infinity))this.unavailable=true;
    this.timelineStopped=Math.max(this.timelineNow(),this.timingGaps.last);
    this.revision++;this.interruptedAs=status;
    if(this.active&&status==='unknown'&&(!this.steps.length||this.steps.some(step=>step.status==='active')))this.unavailable=true;
    this.active=false;
    for(const step of this.steps)if(step.status==='active')step.status=status;
  }
}
// At most one queued message and one cumulative pending snapshot. Credit is
// released by the page even while the worker is synchronously inside WASI.
export class ObservationDelivery {
  private latest:Observation={};
  private readonly events=new ExecutionEvents();
  private readonly timing:ExecutionTiming;
  recordPhysical(fact:import('./physical-history').PhysicalFact){if(!this.disabled){this.events.physical(fact);if(fact.kind!=='omitted')this.timing.record(fact.id,fact.status,fact.attempt);}}
  private dirty=false;
  disabled=false;
  get unavailable(){return !!this.latest.unavailable;}
  constructor(private run:number,private credit:Int32Array,private send:(message:unknown)=>void){
    const gaps=new TimingGapWriter(buffer=>send({timingGapBlock:buffer,observationRun:run}));
    this.timing=new ExecutionTiming((step,end,resume)=>{
      try{gaps.record(step,end,resume);}catch{this.latest.unavailable=true;this.disabled=true;}
    });
  }
  update(observation:Observation){
    if(this.disabled)return;
    if(this.dirty)this.latest.deliveryCoalesced=true;
    keys.forEach((key,id)=>{const value=observation[key];if(value&&validMeasurement(value)&&(value.status!=='unknown'||key==='marker')){this.events.record(id,value.status);this.timing.record(id,value.status);}});
    Object.assign(this.latest,observation);this.dirty=true;this.flush();
  }
  flush(){
    if(this.disabled||!this.dirty||Atomics.compareExchange(this.credit,0,0,1)!==0)return;
    try{this.send({observation:structuredClone(this.snapshot()),observationRun:this.run});this.dirty=false;}
    catch{this.latest.unavailable=true;this.disabled=true;Atomics.store(this.credit,0,0);}
  }
  snapshot(){return {...this.latest,events:this.events.items,eventsOmitted:this.events.omitted,timeline:this.timing.snapshot(),timeline_seconds:this.timing.seconds()};}
}
export type ObservedStep=ExecutionHistory['steps'][number];
export function observedStrategy(history:ExecutionHistory,operation:number):string|null{
 const isShuffle=(id:number)=>history.configured.find(item=>item.id===id)?.label.startsWith(`${id}. shuffle`)??false;
 const steps=history.steps.filter(step=>operationsFor(step).includes(operation)),kinds=new Set(steps.map(step=>step.kind));
 const external=['spill','merge','hierarchical_merge','merge_traversal'].some(kind=>kinds.has(kind as PhysicalSummary['kind']));
 const resident=kinds.has('resident_sort');
 let strategy:string|null=null;
 if(kinds.has('fisher_yates'))strategy='Fisher–Yates · in memory';
 else if(external||resident){
  const randomKey=isShuffle(operation)||steps.some(step=>['spill','resident_sort','merge','hierarchical_merge','merge_traversal'].includes(step.kind??'')&&operationsFor(step).some(isShuffle));
  const fused=steps.some(step=>['spill','resident_sort'].includes(step.kind??'')&&operationsFor(step).length>1);
  strategy=`${kinds.has('fallback')?'Routing → ':kinds.has('routed_grouping')||kinds.has('reuse')?'Routing + ':''}${fused?'Fused ':''}${randomKey?'random-key':'comparison'} sort · ${external?resident?'memory + external':'external':'in memory'}`;
 }else if(kinds.has('fallback'))strategy='Routing → sorting';
 else if(kinds.has('routed_grouping'))strategy='Bounded routing';
 else if(kinds.has('reuse'))strategy='Reused ordered groups';
 else if(kinds.has('routing'))strategy='Bounded value grouping';
 else if(kinds.has('elided'))strategy='Elided by later shuffle';
 else if(isShuffle(operation)||history.configured.find(item=>item.id===operation)?.label.startsWith(`${operation}. partition`))strategy=history.active&&!history.unavailable?'Awaiting strategy':'Strategy not observed';
 if(strategy)strategy=strategy[0].toUpperCase()+strategy.slice(1);
 return strategy&&history.unavailable?`${strategy} · partial observation`:strategy;
}
function stageFinished(history:ExecutionHistory,step:ObservedStep){
 if(history.processingComplete)return true;
 const scope=step.kind?lifecycleScopes[step.kind]:undefined;
 if(scope==='publication')return false;
 const owners=operationsFor(step);
 const stages=scope==='serialization'?[history.configured.length]:scope==='input'?[0]:owners.length?owners:scope==='intermediate'?[0]:[];
 return stages.length>0&&stages.every(stage=>history.completedStages.has(stage));
}

export function displayStepStatus(history:ExecutionHistory,step:ObservedStep):string{
 if(step.kind&&!stageFinished(history,step)&&['completed','handed_off'].includes(step.status))return history.active?'in_progress':history.interruptedAs;
 if(step.kind&&step.status==='interrupted'&&history.active&&!stageFinished(history,step))return 'in_progress';
 return step.status==='active'?'in_progress':step.status;
}

export function observedSources(history:ExecutionHistory,step:ObservedStep):number[]{
 if(step.kind==='elided')return [];
 const explicit=step.sources?.length?step.sources:step.source!=null?[step.source]:[];
 if(explicit.length)return [...new Set(explicit)].slice(0,4);
 if(step.source_omitted||step.kind)return [];
 // These are the fixed direct writer/export and completion-marker contracts.
 if(step.id===1)return [0];
 if(step.id===2&&!history.prepared)return [1];
 if(step.id===3)return [2];
 return [];
}

export function describeStep(history:ExecutionHistory,step:ObservedStep){
      const status=displayStepStatus(history,step);
      // Ending the page lifetime supplies no terminal measurement for the newest attempt.
      const unfinished=!!step.kind&&['interrupted','unknown'].includes(step.status)&&(step.last_attempt??0)>(step.last_terminal??0);
      const terminalOutcome=unfinished?undefined:step.status==='handed_off'?step.outcomes?.handed_off:step.status==='failed'?step.outcomes?.failed:step.status==='interrupted'?step.outcomes?.interrupted:undefined;
      const showingActive=unfinished||step.kind&&step.status==='active'&&(step.active_seconds??0)>0;
      const observed=showingActive?{bytes:step.active_bytes??0,rows:step.active_rows??0,seconds:step.active_seconds??0,runs:step.active_runs??0}:terminalOutcome??{bytes:step.bytes??0,rows:step.rows??0,seconds:step.seconds??0,runs:step.runs??0};
      const inputCodec=!!step.kind&&['gzip_input','zip_input'].includes(step.kind);
      const archive=step.kind==='zip_archive';
      const outputCodec=!!step.kind&&['gzip_output','zip_deflate'].includes(step.kind);
      const rowUnit=archive?'archive bytes':outputCodec?'encoded CSV bytes consumed':inputCodec?'decoded CSV bytes':step.kind&&['merge','hierarchical_merge','merge_traversal'].includes(step.kind)?'row visits':step.kind==='shared_ranges'?'frame lengths scanned':step.kind==='dataset_materialize'?'framed rows written':'rows';
      const count=inputCodec||outputCodec||archive?observed.bytes:observed.rows;
      const rate=observed.seconds>0&&Number.isFinite(count/observed.seconds)?` · average ${Math.round(count/observed.seconds).toLocaleString('en-US')} ${rowUnit}/s`:'';
      const metrics=archive?` · ${count.toLocaleString('en-US')} archive bytes · ${observed.runs} entries (manifest included) · ${observed.seconds.toFixed(2)} s${rate}`:step.kind==='spill'?` · ${observed.runs} sorted runs · ${observed.rows.toLocaleString('en-US')} sorted rows · ${observed.seconds.toFixed(2)} s${rate}`:step.kind==='reuse'||step.kind==='fallback'?` · ${observed.runs} already ordered file(s)${step.kind==='reuse'?' · no re-sort':''}`:step.kind==='materialize'?` · ${observed.seconds.toFixed(2)} s elapsed`:step.kind==='elided'?' · order replaced; no shuffle performed':step.rows!=null?step.kind&&step.status==='active'&&!observed.seconds?' · awaiting measurement':` · ${count.toLocaleString('en-US')} ${rowUnit} · ${observed.seconds.toFixed(2)} s${rate}`:step.files!=null?` · ${step.files} saved and closed files (manifest included)`:'';
      const sourceIds=observedSources(history,step);
      const sources=sourceIds.map(id=>history.steps.find(s=>s.id===id)).filter((s):s is typeof history.steps[number]=>!!s);
      const dependency=sources.length?` · ← receives data from ${sources.map(s=>s.title).join(", ")}`:'';
      const memberCounts=terminalOutcome?.memberships??step.memberships;
      const actualGroups=terminalOutcome?.groups??step.groups,emptyGroups=terminalOutcome?.empty_groups??step.empty_groups,omittedMemberships=terminalOutcome?.omitted_memberships??step.omitted_memberships;
      const membership=memberCounts?.length?` · observed memberships: ${memberCounts.map((rows,index)=>`${step.kind&&['shared_ranges','balanced_traversal','fused_balanced','interleaved_membership'].includes(step.kind)?`part ${index+1}`:history.allocationLabels[(step.operations?.[0]??1)-1]?.[index]??`group ${index+1}`}: ${rows.toLocaleString('en-US')}`).join(', ')}`:'';
      const groupMetrics=actualGroups!=null&&['exact_membership','probabilistic_membership','shared_ranges','balanced_traversal','fused_balanced','interleaved_membership','dataset_materialize'].includes(step.kind??'')?` · ${actualGroups} logical groups, ${emptyGroups} empty${membership}${omittedMemberships?` · ${omittedMemberships} parent/group membership entries omitted`:''}`:'';
      let completedWork='';
      if((unfinished||terminalOutcome)&&(step.completed_attempts??0)>0){
        const completedCount=inputCodec||outputCodec||archive?(step.bytes??0):(step.rows??0);
        const completedMetric=step.kind==='materialize'?`${(step.seconds??0).toFixed(2)} s elapsed`:step.kind==='reuse'||step.kind==='fallback'?`${step.runs??0} ordered file(s)`:step.kind==='elided'?'elision annotations':`${completedCount.toLocaleString('en-US')} ${rowUnit}`;
        completedWork=` · ${completedMetric} confirmed completed`;
      }
      const partialCount=inputCodec||outputCodec||archive?(step.outcomes?.interrupted.bytes??0):step.partial_rows;
      const failedCount=inputCodec||outputCodec||archive?(step.outcomes?.failed.bytes??0):(step.outcomes?.failed.rows??0);
      const marker=step.id===3?` · ${step.status==='completed'?'confirmed':step.status==='active'?'pending':'unconfirmed'}`:'';
  return `${step.title}${step.operations?.length?` [operations ${step.operations.join(', ')}]`:step.operation?' [operation 1]':''} · ${statusLabel(status)}${marker}${metrics}${step.kind&&step.status==='active'&&!(step.active_seconds??0)&&step.completed_attempts?' · completed work shown; current attempt awaiting measurement':''}${groupMetrics}${dependency}${completedWork}${step.attempts?` · ${step.completed_attempts??step.attempts} completed attempt(s)${step.interrupted_attempts?` · ${step.interrupted_attempts} interrupted attempt(s), ${partialCount?.toLocaleString('en-US')} partial ${rowUnit}, ${step.partial_seconds?.toFixed(2)} s last observed`:""}`:''}${step.outcomes?.handed_off.attempts?` · ${step.outcomes.handed_off.rows.toLocaleString('en-US')} rows handed off, ${step.outcomes.handed_off.runs} ordered file(s)`:''}${step.outcomes?.failed.attempts?` · ${step.outcomes.failed.attempts} failed attempt(s), ${failedCount.toLocaleString('en-US')} partial ${inputCodec||outputCodec||archive?rowUnit:'row visits'}`:''}${step.max_level!=null?` · merge levels ${step.min_level}..${step.max_level}`:''}${step.source_omitted||sources.length<sourceIds.length?' · upstream dependency detail omitted':''}${['interrupted','unknown'].includes(status)?' · last observed':''}`;
}

// Keep a single cumulative scope across attempt boundaries; active counters join
// confirmed work instead of replacing it with a different per-attempt sentence.
function stepMetrics(step:ObservedStep){
 const unfinished=!!step.kind&&['interrupted','unknown'].includes(step.status)&&(step.last_attempt??0)>(step.last_terminal??0);
 const active=!!step.kind&&(step.status==='active'||unfinished);
 const partial=active?undefined:step.status==='failed'?step.outcomes?.failed:step.status==='interrupted'?step.outcomes?.interrupted:step.status==='handed_off'?step.outcomes?.handed_off:undefined;
 const rows=(step.rows??0)+(active?(step.active_rows??0):(partial?.rows??0)),bytes=(step.bytes??0)+(active?(step.active_bytes??0):(partial?.bytes??0));
 const seconds=(step.seconds??0)+(active?(step.active_seconds??0):(partial?.seconds??0)),runs=(step.runs??0)+(active?(step.active_runs??0):(partial?.runs??0));
 return {rows,bytes,seconds,runs};
}
export function summarizeStep(step:ObservedStep):string{
 const {rows,bytes,seconds,runs}=stepMetrics(step);
 const count=(value:number)=>value.toLocaleString('en-US');
 if(step.id===3)return step.status==='completed'?'Export verified':'Verifying export';
 if(step.files!=null)return `${count(step.files)} saved and closed files`;
 if(step.kind==='elided')return 'Replaced by a later shuffle';
 if(step.kind==='reuse'||step.kind==='fallback')return `${count(runs)} ordered files`;
 if(step.kind==='materialize')return `${seconds.toFixed(2)} s elapsed`;
 const measurement=counter(step.kind,rows,bytes);if(!measurement)return `${seconds.toFixed(2)} s elapsed`;
 const codec=measurement.unit==='bytes',unit=measurement.unit;
 const rate=averageRate(measurement,workSeconds(seconds));
 let throughput='';
 if(rate!==null){
  const scale=codec?Math.min(3,Math.max(0,Math.floor(Math.log2(rate)/10))):0;
  const rateUnit=codec?['B','KiB','MiB','GiB'][scale]:unit;
  const value=rate/1024**scale;
  throughput=` · avg ${value.toLocaleString('en-US',{maximumFractionDigits:codec?1:value<1?2:0})} ${rateUnit}/s`;
 }
 return `${count(codec?bytes:rows)} ${unit}${step.kind==='spill'?` · ${count(runs)} sorted runs`:''} · ${seconds.toFixed(2)} s${throughput}`;
}

export function measurementParts(text:string){
 const pattern=/\b\d[\d,.]* (?:encoded CSV bytes consumed|decoded CSV bytes|framed rows written|frame lengths scanned|saved and closed files|already ordered file\(s\)|completed attempt\(s\)|interrupted attempt\(s\)|failed attempt\(s\)|sorted runs|sorted rows|ordered files|KiB|MiB|GiB|B|bytes|logical groups|row visits|archive bytes|rows|files|entries|empty|s)(?:\/s)?(?![A-Za-z])/g;
 const parts:{text:string;measurement:boolean}[]=[];let offset=0;
 for(const match of text.matchAll(pattern)){if(match.index!>offset)parts.push({text:text.slice(offset,match.index),measurement:false});parts.push({text:match[0],measurement:true});offset=match.index!+match[0].length;}
 if(offset<text.length)parts.push({text:text.slice(offset),measurement:false});return parts;
}

let panel:HTMLDetailsElement|null=null,renderedRun=-1,renderedRevision=-1;
let selectedStep:number|null=null,selectedOperation:number|null=null,listView=false,autoFit=true,timelineView=false;
let timeline:ExecutionTimeline|null=null,timelineRows:TimelineRow[]=[],timelineTimer:ReturnType<typeof setInterval>|undefined;
function refreshTimeline(){if(shownHistory&&timeline)timeline.update(timelineRows,shownHistory.timelineNow(),shownHistory.active&&!shownHistory.steps.some(step=>step.id===3&&step.status==='completed'));}
function updateTimelineTimer(){
 const running=timelineView&&panel?.open&&shownHistory?.active&&shownHistory.timeline.size>0&&!shownHistory.steps.some(step=>step.id===3&&step.status==='completed')&&!document.hidden;
 if(running&&!timelineTimer)timelineTimer=setInterval(()=>{if(!timelineView||!shownHistory?.active||!panel?.open||document.hidden){updateTimelineTimer();return;}refreshTimeline();},250);
 else if(!running&&timelineTimer){clearInterval(timelineTimer);timelineTimer=undefined;}
}
const cards=new Map<number,HTMLLIElement>();
let motionObserver:IntersectionObserver|undefined;
let dag=new ExecutionDag(),drawnRevision=-1,drawnSelection='',zoom=1,shownHistory:ExecutionHistory|null=null;
function dagInput(history:ExecutionHistory){
 const output=history.configured.at(-1)!.id;
 const scale=listView?1:Number(panel!.querySelector<HTMLElement>('.execution-stage')!.style.getPropertyValue('--dag-zoom')||1);
 return history.steps.map(step=>{
 const card=cards.get(step.id);
 // Remove transform rounding noise before retaining whole CSS pixels.
 const height=card?Math.ceil(Math.round(card.getBoundingClientRect().height/scale*100)/100):undefined;
 return {id:step.id,height,sources:observedSources(history,step),stage:
  step.id===0||['read','gzip_input','zip_input'].includes(step.kind||'')?0:
  step.id===1||['materialize','serialize','gzip_output','zip_deflate','zip_archive'].includes(step.kind||'')?output:step.id===2?output+1:step.id===3?output+2:
  operationsFor(step).length?Math.min(...operationsFor(step)):undefined};});
}
const edges=new Map<string,SVGPathElement>();
const activityLabels=new Map<number,HTMLButtonElement>();
const svgNamespace='http://www.w3.org/2000/svg';
function category(step:ObservedStep){
 if(step.id===3)return 'confirm';if(step.id===2)return 'export';
 if(step.id===0||['read','gzip_input','zip_input'].includes(step.kind||''))return 'input';
 if(step.id===1||['serialize','gzip_output','zip_deflate','zip_archive'].includes(step.kind||''))return 'output';
 if(['materialize','dataset_materialize','spill','merge','hierarchical_merge'].includes(step.kind||''))return 'storage';
 return step.kind==='elided'?'annotation':'transform';
}
function syncGraphZoom(){
 const slider=panel!.querySelector<HTMLInputElement>('[data-graph-zoom]')!;
 const percent=Math.round(zoom*100);
 slider.value=String(percent);
 slider.setAttribute('aria-valuetext',zoom<.01?'Less than 1%':`${percent}%`);
 panel!.querySelector<HTMLInputElement>('[data-auto-fit]')!.checked=autoFit;
 panel!.querySelector<HTMLElement>('.execution-stage')!.style.setProperty('--dag-zoom',String(zoom));
}
function renderDag(history:ExecutionHistory,frame:DagFrame){
 const stage=panel!.querySelector<HTMLElement>('.execution-stage')!,canvas=panel!.querySelector<HTMLElement>('.execution-canvas')!;
 stage.classList.toggle('is-list',listView);
 const viewport=panel!.querySelector<HTMLElement>('.execution-viewport')!;
 if(autoFit&&!listView&&viewport.clientWidth)zoom=Math.min(1,Math.max(1,viewport.clientWidth-20)/frame.width);
 stage.style.setProperty('--dag-width',`${frame.width}px`);stage.style.setProperty('--dag-height',`${frame.height}px`);
 syncGraphZoom();

 const svg=canvas.querySelector<SVGSVGElement>('.execution-dag-edges')!;
 if(drawnRevision!==frame.revision){
 for(const [id,position] of frame.positions){const card=cards.get(id);if(card){card.style.setProperty('--dag-x',`${position.x}px`);card.style.setProperty('--dag-y',`${position.y}px`);card.style.setProperty('--dag-card-height',`${position.height}px`);}}
  const activities=new Map<number,number[]>();
  for(const step of history.steps){const position=frame.positions.get(step.id);if(!position)continue;const ids=activities.get(position.column)||[];ids.push(step.id);activities.set(position.column,ids);}
  for(const [column,ids] of activities){
   let label=activityLabels.get(column);if(!label){label=document.createElement('button');label.type='button';label.className='execution-activity';activityLabels.set(column,label);canvas.append(label);}
   const output=history.configured.at(-1)!.id;
   label.textContent=column===0?'Read input':column===output?'Create CSV output':column===output+1?'Save destination files':column===output+2?'Confirm completion':[...new Set(ids.flatMap(id=>operationsFor(history.steps.find(step=>step.id===id)!)))].map(id=>history.configured.find(item=>item.id===id)?.label).filter(Boolean).map(label=>configuredLabel(label!).split(' (')[0]).join(' · ')||'Supporting work';
   label.style.top=`${frame.positions.get(ids[0])!.y-24}px`;
   for(const id of ids)cards.get(id)?.querySelector('.execution-node-context')?.replaceChildren(document.createTextNode(label.textContent||''));
   label.dataset.planTargets=column===0?'input':column>=output?'output':[...new Set(ids.flatMap(id=>operationsFor(history.steps.find(step=>step.id===id)!)))].map(id=>`step-${id-1}`).join(' ');
  }
  drawnRevision=frame.revision;drawnSelection='';svg.setAttribute('width',String(frame.width));svg.setAttribute('height',String(frame.height));
  const present=new Set<string>();
  for(const edge of frame.edges){
   const key=`${edge.source}:${edge.target}`;present.add(key);let path=edges.get(key);
   if(!path){path=document.createElementNS(svgNamespace,'path');path.classList.add('execution-edge');path.dataset.source=String(edge.source);path.dataset.target=String(edge.target);path.setAttribute('marker-end','url(#execution-arrow)');edges.set(key,path);svg.append(path);}
   path.setAttribute('d',edgePath(frame.positions.get(edge.source)!,frame.positions.get(edge.target)!));
  }
  for(const [key,path] of edges)if(!present.has(key)){path.remove();edges.delete(key);}
 }
 const selection=`${selectedStep}:${selectedOperation}`;
 if(drawnSelection!==selection){
  drawnSelection=selection;const matching=new Set(history.steps.filter(step=>step.id===selectedStep||selectedOperation!==null&&operationsFor(step).includes(selectedOperation)).map(step=>step.id));
  for(const path of edges.values())path.classList.toggle('is-related',matching.has(Number(path.dataset.source))||matching.has(Number(path.dataset.target)));
 }
 panel!.querySelector<HTMLElement>('.execution-zoom-controls')!.hidden=listView||timelineView;
 if(listView){
  const list=panel!.querySelector('.execution-list')!,focused=document.activeElement as HTMLElement;
  const ordered=[...cards].sort(([a],[b])=>{const x=frame.positions.get(a)!,y=frame.positions.get(b)!;return x.column-y.column||x.row-y.row;}).map(([,card])=>card);
  ordered.forEach((card,index)=>{if(list.children[index]!==card)list.insertBefore(card,list.children[index]??null);});
  if(focused&&document.activeElement!==focused&&list.contains(focused))focused.focus({preventScroll:true});
 }
}

function bindGraphNavigation(viewport:HTMLElement){
 viewport.tabIndex=0;viewport.setAttribute('role','region');viewport.setAttribute('aria-label','Execution graph. Drag the background or use left and right arrow keys to pan.');
 let drag:{id:number;x:number;y:number;left:number}|null=null;
 let dragged=false;
 viewport.addEventListener('pointerdown',event=>{
  if(!event.isPrimary||event.button!==0)return;
  dragged=false;
  if(listView||timelineView||event.pointerType!=='mouse'||(event.target as Element).closest('button,a,input,select'))return;
  drag={id:event.pointerId,x:event.clientX,y:event.clientY,left:viewport.scrollLeft};viewport.setPointerCapture(event.pointerId);
 });
 viewport.addEventListener('pointermove',event=>{
  if(!drag||event.pointerId!==drag.id)return;
  if(!viewport.classList.contains('is-panning')&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<4)return;
  if(!viewport.classList.contains('is-panning')){dragged=true;viewport.classList.add('is-panning');}
  viewport.scrollLeft=drag.left+drag.x-event.clientX;
 });
 viewport.addEventListener('pointerup',event=>{if(viewport.hasPointerCapture(event.pointerId))viewport.releasePointerCapture(event.pointerId);});
 viewport.addEventListener('lostpointercapture',()=>{drag=null;viewport.classList.remove('is-panning');});
 viewport.addEventListener('click',event=>{
  // A pan can produce a click after pointer capture has already been released.
  if(dragged){dragged=false;return;}
  if(listView||timelineView||(event.target as Element).closest('button,a,input,select'))return;
  if(selectedStep===null&&selectedOperation===null)return;
  selectedStep=null;selectedOperation=null;renderedRevision=-1;
  if(shownHistory)renderExecutionHistory(shownHistory);
 });
}

function operationsFor(step:ObservedStep){return step.operations??(step.operation?[step.operation]:[]);}
export function renderExecutionHistory(history:ExecutionHistory|null){
 if(!history){shownHistory=null;updateTimelineTimer();return;}shownHistory=history;
 if(!panel){
  panel=document.createElement('details');panel.id='execution-history';panel.className='card';panel.style.setProperty('--dag-node-width',`${DAG_NODE_WIDTH}px`);panel.style.setProperty('--dag-node-height',`${DAG_NODE_HEIGHT}px`);
  panel.innerHTML='<summary></summary><div class="execution-flow" aria-label="Configured Run operations"></div><p class="execution-note"></p><div class="execution-controls" role="toolbar" aria-label="Execution view controls"><span class="execution-view-switch" role="group" aria-label="View" focusgroup="toolbar wrap"><button type="button" data-view="graph">Graph view</button><button type="button" data-view="list">List view</button><button type="button" data-view="timeline">Timeline view</button></span><span class="execution-control-divider" role="separator" aria-orientation="vertical"></span><span class="execution-zoom-controls" role="group" aria-label="Graph controls"><label class="execution-auto-fit"><input type="checkbox" data-auto-fit checked>Auto-fit</label><label class="execution-zoom">Zoom<input type="range" data-graph-zoom min="1" max="150" step="1" value="100"></label></span></div><span class="sr-only" id="execution-operation-match">Matches the selected configured operation.</span><div class="execution-map-heading"><span>Observed execution</span><span class="execution-navigation-hint">Drag sideways to pan</span></div><div class="execution-viewport"><div class="execution-stage"><div class="execution-canvas"><svg class="execution-dag-edges" aria-hidden="true"><defs><marker id="execution-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8ba69d"></path></marker></defs></svg><ol class="execution-list execution-graph" aria-label="Observed execution steps"></ol></div></div></div><div class="execution-timeline" hidden></div><section class="execution-inspector" aria-label="Selected execution step"><p>Select a step or configured operation.</p><details class="execution-explanation" hidden><summary>Explain this step</summary><div class="execution-explanation-control"><label for="execution-detail-level">Level of detail</label><div class="execution-detail-slider"><div class="execution-detail-track" aria-hidden="true"><span></span><span></span><span></span></div><input id="execution-detail-level" type="range" min="0" max="2" step="1" value="1" aria-valuetext="Standard"></div><div class="execution-explanation-labels" aria-hidden="true"><span>Brief</span><span class="is-selected">Standard</span><span>Detailed</span></div></div><div class="execution-explanation-copy"></div></details></section>';
  const explanation=panel.querySelector<HTMLDetailsElement>('.execution-explanation')!;
  const updateExplanation=()=>{
   if(shownHistory)renderExplanation(shownHistory,shownHistory.steps.find(step=>step.id===selectedStep));
  };
  explanation.addEventListener('toggle',updateExplanation);
  explanation.querySelector('input')!.addEventListener('input',updateExplanation);
  panel.querySelector<HTMLElement>('.execution-map-heading')!.title='Arrows show observed data dependencies, not parallel workers.';
  if(document.body.classList.contains('hosted-workspace'))(document.querySelector('.execution-pane')??document.querySelector('.editor'))!.append(panel);
  else document.querySelector('.editor')!.prepend(panel);
  bindGraphNavigation(panel.querySelector<HTMLElement>('.execution-viewport')!);
  panel.querySelector<HTMLInputElement>('[data-graph-zoom]')!.oninput=event=>{
   autoFit=false;zoom=(event.target as HTMLInputElement).valueAsNumber/100;syncGraphZoom();
  };
  motionObserver=new IntersectionObserver(entries=>{for(const entry of entries)(entry.target as HTMLElement).dataset.motionVisible=String(entry.isIntersecting);},{threshold:.1});
  const motionButton=document.createElement('button');motionButton.type='button';motionButton.className='execution-motion-toggle';
  let motionPaused=false;const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  const syncMotion=()=>{panel!.dataset.motionEnabled=String(!motionPaused&&!reducedMotion.matches&&!document.hidden);motionButton.disabled=reducedMotion.matches;motionButton.textContent=reducedMotion.matches?'Reduced motion':motionPaused?'Resume motion':'Pause motion';};
  motionButton.onclick=()=>{motionPaused=!motionPaused;syncMotion();};reducedMotion.addEventListener('change',syncMotion);document.addEventListener('visibilitychange',syncMotion);syncMotion();
  const toolbar=panel.querySelector<HTMLElement>('[role="toolbar"]')!;
  const viewSwitch=toolbar.querySelector<HTMLElement>('.execution-view-switch')!;
  toolbar.querySelector('.execution-zoom-controls')!.append(motionButton);
  const icons:Record<string,string>={graph:'<rect x="3" y="3" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M6 8v10h9"/>',list:'<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>',timeline:'<path d="M4 3v18M4 7h9M9 12h11M14 17h7"/>'};
  for(const button of toolbar.querySelectorAll<HTMLButtonElement>('[data-view]')){const icon=document.createElementNS(svgNamespace,'svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.innerHTML=icons[button.dataset.view!];button.prepend(icon);}
  // Native focusgroup owns keyboard navigation where supported.
  if(!('focusGroup' in HTMLElement.prototype)){
   const buttons=[...viewSwitch.querySelectorAll('button')];
   buttons.forEach((button,index)=>button.tabIndex=index?-1:0);
   viewSwitch.addEventListener('focusin',event=>{for(const button of buttons)button.tabIndex=button===event.target?0:-1;});
   viewSwitch.addEventListener('keydown',event=>{if(event.altKey||event.ctrlKey||event.metaKey)return;const index=buttons.indexOf(event.target as HTMLButtonElement),direction=getComputedStyle(viewSwitch).direction==='rtl'?-1:1;
    const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:event.key==='ArrowRight'?(index+direction+buttons.length)%buttons.length:event.key==='ArrowLeft'?(index-direction+buttons.length)%buttons.length:-1;
    if(index>=0&&next>=0){event.preventDefault();buttons[next].focus();}
   });
  }
  let observedWidth=0;
  new ResizeObserver(entries=>{const width=entries[0].contentRect.width;if(width===observedWidth)return;observedWidth=width;if(panel?.open&&shownHistory)requestAnimationFrame(()=>{if(shownHistory)renderDag(shownHistory,dag.update(dagInput(shownHistory)));});}).observe(panel.querySelector('.execution-viewport')!);
  timeline=new ExecutionTimeline(panel.querySelector('.execution-timeline')!,id=>{selectedStep=id;selectedOperation=null;renderedRevision=-1;if(shownHistory)renderExecutionHistory(shownHistory);});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&timelineView&&panel?.open)refreshTimeline();updateTimelineTimer();});
  panel.addEventListener('toggle',()=>{if(panel?.open&&shownHistory){dag=new ExecutionDag();drawnRevision=-1;renderedRevision=-1;renderExecutionHistory(shownHistory);}updateTimelineTimer();});
 }
 if(renderedRun===history.run&&renderedRevision===history.revision)return;
 const redraw=()=>{renderedRevision=-1;renderExecutionHistory(history);};
 if(renderedRun!==history.run){
  panel.open=true;
  panel.querySelector<HTMLDetailsElement>('.execution-explanation')!.open=false;
  if(document.body.classList.contains('hosted-workspace'))document.dispatchEvent(new Event('chopper-execution-start'));
  else panel.scrollIntoView({block:'start'});
  renderedRun=history.run;selectedStep=null;selectedOperation=null;motionObserver?.disconnect();cards.clear();for(const label of activityLabels.values())label.remove();activityLabels.clear();dag=new ExecutionDag();drawnRevision=-1;drawnSelection='';zoom=1;for(const edge of edges.values())edge.remove();edges.clear();
  panel.querySelector('.execution-list')!.replaceChildren();
  timeline?.clear();timelineRows=[];
  const flow=panel.querySelector('.execution-flow')!;flow.replaceChildren();
  for(const item of history.configured){
   const button=document.createElement('button'),index=document.createElement('span'),label=document.createElement('span'),text=document.createElement('span'),strategy=document.createElement('span');button.type='button';button.dataset.operation=String(item.id);button.title=configuredLabel(item.label);button.setAttribute('aria-label',configuredLabel(item.label));
   index.className='execution-flow-index';index.textContent=String(item.id).padStart(2,'0');label.className='execution-flow-label';
   const kind=item.label.replace(/^\d+\. /,'').split(/[ (]/)[0];label.textContent=kind==='CSV'?'CSV output':operationName(kind);
   if(kind!=='CSV')index.dataset.planColor=operationColor(kind);
   strategy.className='execution-flow-strategy';strategy.id=`execution-strategy-${item.id}`;text.className='execution-flow-text';text.append(label,strategy);
   button.append(index,text);button.onclick=()=>{selectedOperation=item.id;selectedStep=null;redraw();};flow.append(button);
  }
 }
 const phase=history.steps.slice().reverse().find(s=>s.status==='active')?.title;
 const terminal=history.steps.find(s=>s.id===3)?.status==='completed'?'Export confirmed':'History retained · export unconfirmed';
 panel.querySelector('summary')!.textContent=`Run execution · ${phase??(history.active?'Awaiting observations':terminal)}`;
 panel.querySelector('.execution-note')!.textContent=(history.unavailable?'Observation unavailable for some work. ':'')+(history.configurationOmitted?'Some configured details omitted by display limits.':'');
 const selected=history.steps.find(s=>s.id===selectedStep);
 for(const button of panel.querySelectorAll<HTMLButtonElement>('[data-operation]')){
  const operation=Number(button.dataset.operation),strategy=observedStrategy(history,operation),label=button.querySelector<HTMLElement>('.execution-flow-strategy')!;
  label.textContent=strategy??'';label.hidden=!strategy;
  if(strategy)button.setAttribute('aria-describedby',label.id);else button.removeAttribute('aria-describedby');
  button.setAttribute('aria-pressed',String(selected?operationsFor(selected).includes(operation):selectedOperation===operation));
 }
 for(const button of panel.querySelectorAll<HTMLButtonElement>('[data-view]')){button.setAttribute('aria-pressed',String(button.dataset.view===(timelineView?'timeline':listView?'list':'graph')));button.onclick=()=>{listView=button.dataset.view==='list';timelineView=button.dataset.view==='timeline';redraw();};}
 panel.querySelector<HTMLElement>('.execution-note')!.hidden=!history.unavailable&&!history.configurationOmitted;
 panel.querySelector<HTMLInputElement>('[data-auto-fit]')!.onchange=event=>{
  autoFit=(event.target as HTMLInputElement).checked;
  if(autoFit){dag=new ExecutionDag();drawnRevision=-1;panel!.querySelector('.execution-viewport')!.scrollLeft=0;}
  redraw();
 };
 panel.querySelector<HTMLButtonElement>('.execution-motion-toggle')!.hidden=listView||timelineView;panel.querySelector<HTMLElement>('.execution-navigation-hint')!.hidden=listView||timelineView;
 const list=panel.querySelector('.execution-list')!;list.classList.toggle('execution-graph',!listView);list.classList.toggle('execution-list-view',listView);
 for(const step of history.steps){
  let card=cards.get(step.id);
  if(!card){card=document.createElement('li');card.dataset.step=String(step.id);const button=document.createElement('button');button.type='button';button.innerHTML='<span class="execution-node-context"></span><strong class="execution-node-title"></strong><span class="execution-node-detail"></span><span class="execution-node-meta"><span class="execution-node-status"></span></span>';button.onclick=()=>{selectedStep=!listView&&selectedStep===step.id?null:step.id;selectedOperation=null;redraw();};card.append(button);cards.set(step.id,card);list.append(card);motionObserver?.observe(card);}
  const button=card.firstElementChild as HTMLButtonElement,text=describeStep(history,step)+(operationsFor(step).length?'':' · Supporting work');
  const attempts=step.attempts??0,hasOpenAttempt=(step.last_attempt??0)>(step.last_terminal??0);
  const repeated=attempts+Number(hasOpenAttempt)>1;
  card.toggleAttribute('data-repeated',repeated);
  button.setAttribute('aria-label',text+(repeated?' · Repeated work':''));
  button.dataset.planTargets=operationsFor(step).length?operationsFor(step).map(id=>id===history.configured.at(-1)!.id?'output':`step-${id-1}`).join(' '):category(step)==='input'?'input':['output','export','confirm'].includes(category(step))?'output':'resources';
  const title=button.querySelector('.execution-node-title')!,detail=button.querySelector('.execution-node-detail')!;
  if(title.textContent!==step.title)title.textContent=step.title;
  const description=summarizeStep(step);if(detail.textContent!==description){detail.replaceChildren(...measurementParts(description).map(part=>{if(!part.measurement)return document.createTextNode(part.text);const span=document.createElement('span');span.className='execution-measurement';span.textContent=part.text;return span;}));}
  button.title=step.kind?'In Progress covers all groups; the animation pauses between attempts. Completed means its stage has finished across all groups. Select to inspect measurements.':'Select to inspect measurements';
  button.querySelector('.execution-node-status')!.textContent=statusLabel(displayStepStatus(history,step));
  card.dataset.status=displayStepStatus(history,step);card.dataset.category=category(step);
  if(step.status==='active')card.dataset.motionStarted='true';
  card.dataset.motionActive=String(history.active&&displayStepStatus(history,step)==='in_progress'&&card.dataset.motionStarted==='true');
  card.dataset.motionRunning=String(step.status==='active');
  const motif=stepMotion(step,history.configured);
  if(card.dataset.motion!==motif){card.dataset.motion=motif;button.querySelector('.execution-node-motion')?.remove();button.querySelector('.execution-node-meta')!.insertAdjacentHTML('afterbegin',motionMarkup(motif));}

  const matching=selectedOperation!==null&&operationsFor(step).includes(selectedOperation);
  if(matching)button.setAttribute('aria-describedby','execution-operation-match');else button.removeAttribute('aria-describedby');
  card.dataset.matching=String(matching);card.dataset.selected=String(selectedStep===step.id);button.setAttribute('aria-pressed',String(selectedStep===step.id));
 }
 panel.querySelector('.execution-stage')!.classList.toggle('is-list',listView);
 renderDag(history,dag.update(dagInput(history)));
 panel.querySelector<HTMLElement>('.execution-viewport')!.hidden=timelineView;
 panel.querySelector<HTMLElement>('.execution-timeline')!.hidden=!timelineView;
 panel.querySelector('.execution-map-heading span')!.textContent=timelineView?'Observed timeline':'Observed execution';
 if(timelineView){
  timelineRows=history.steps.map(step=>({id:step.id,title:step.title,color:operationColor(history.configured.find(op=>op.id===operationsFor(step)[0])?.label.replace(/^\d+\. /,'').split(/[ (]/)[0]??''),group:cards.get(step.id)?.querySelector('.execution-node-context')?.textContent??'',status:displayStepStatus(history,step),seconds:step.seconds==null?null:workSeconds(stepMetrics(step).seconds),window:history.timeline.get(step.id),gaps:history.timingGaps.byStep.get(step.id),selected:step.id===selectedStep,matching:selectedOperation!==null&&operationsFor(step).includes(selectedOperation),targets:(cards.get(step.id)?.firstElementChild as HTMLElement)?.dataset.planTargets??''}));
  if(panel.open&&!document.hidden)refreshTimeline();
 }
 updateTimelineTimer();
 const inspector=panel.querySelector('.execution-inspector p')!;
 const strategy=selectedOperation!==null?observedStrategy(history,selectedOperation):null;
 const details=selected?describeStep(history,selected)+(operationsFor(selected).length?'':' · Supporting work; no configured operation mapping.'):selectedOperation!==null?`${configuredLabel(history.configured.find(item=>item.id===selectedOperation)?.label??`Operation ${selectedOperation}`)}${strategy?` · Observed strategy: ${strategy}.`:''} · Matching physical steps are outlined.`:'Select a step or configured operation.';
 if(inspector.textContent!==details)inspector.textContent=details;
 renderExplanation(history,selected);
 renderedRevision=history.revision;
}

function renderExplanation(history:ExecutionHistory,step:ObservedStep|undefined){
 const details=panel!.querySelector<HTMLDetailsElement>('.execution-explanation')!;
 details.hidden=!step;
 const copy=details.querySelector('.execution-explanation-copy')!;
 if(!step){copy.replaceChildren();return;}
 if(!details.open)return;
 const slider=details.querySelector<HTMLInputElement>('input')!;
 const level=slider.valueAsNumber as 0|1|2;
 slider.setAttribute('aria-valuetext',explanationLevels[level]);
 for(const [index,label] of Array.from(details.querySelectorAll('.execution-explanation-labels > *')).entries()){
  label.classList.toggle('is-selected',index===level);
 }
 const sourceIds=observedSources(history,step);
 const sources=sourceIds.length?history.steps.filter(source=>sourceIds.includes(source.id)):[];
 const paragraphs=explainStep(history.explanationSettings,step,level,displayStepStatus(history,step),sources);
 if(copy.childElementCount===paragraphs.length&&paragraphs.every((text,index)=>copy.children[index].textContent===text))return;
 copy.replaceChildren(...paragraphs.map(text=>{
  const paragraph=document.createElement('p');
  paragraph.textContent=text;
  return paragraph;
 }));
}
