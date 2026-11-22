import {timelineSeconds,type TimelineSeconds} from './measurements';
import {MAX_PHYSICAL_STEPS,PHYSICAL_ID_BASE,type PhysicalFact} from './physical-history';
export type TimingGap=[end:TimelineSeconds,resume:TimelineSeconds];
export type TimingWindow={step:number;start:TimelineSeconds|null;last:TimelineSeconds;status:PhysicalFact['status']};
const statuses=['active','completed','interrupted','failed','handed_off','unknown'];
const validStep=(step:number)=>Number.isInteger(step)&&(step>=0&&step<4||step>=PHYSICAL_ID_BASE&&step<PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS);
export const MAX_TIMING_WINDOWS=MAX_PHYSICAL_STEPS+4;
export const TIMING_GAPS_PER_BLOCK=1024;
const headerBytes=Float64Array.BYTES_PER_ELEMENT;
const blockBytes=headerBytes+TIMING_GAPS_PER_BLOCK*3*Float64Array.BYTES_PER_ELEMENT;

export function validTiming(value:TimingWindow,clock:number){
 return value&&validStep(value.step)&&Number.isFinite(value.last)&&value.last>=0&&value.last<=clock&&(value.start===null||Number.isFinite(value.start)&&value.start>=0&&value.start<=value.last)&&statuses.includes(value.status);
}

// The worker keeps the current block. The page sees committed entries even if
// the worker is stopped before its next cumulative observation.
export class TimingGapWriter {
 private block?:{count:Int32Array;values:Float64Array};
 private size=TIMING_GAPS_PER_BLOCK;
 constructor(private send:(buffer:SharedArrayBuffer)=>void){}
 record(step:number,end:TimelineSeconds,resume:TimelineSeconds){
  let block=this.block,newBuffer:SharedArrayBuffer|undefined;
  if(!block||this.size===TIMING_GAPS_PER_BLOCK){
   newBuffer=new SharedArrayBuffer(blockBytes);
   block=this.block={count:new Int32Array(newBuffer,0,1),values:new Float64Array(newBuffer,headerBytes)};
   this.size=0;
  }
  block.values[this.size*3]=step;
  block.values[this.size*3+1]=end;
  block.values[this.size*3+2]=resume;
  Atomics.store(block.count,0,++this.size);
  if(newBuffer)this.send(newBuffer);
 }
}

export class TimingGapLog {
 private blocks:{count:Int32Array;values:Float64Array;offset:number}[]=[];
 readonly byStep=new Map<number,TimingGap[]>();
 last=0;
 add(buffer:unknown){
  if(!(buffer instanceof SharedArrayBuffer)||buffer.byteLength!==blockBytes)return false;
  this.blocks.push({count:new Int32Array(buffer,0,1),values:new Float64Array(buffer,headerBytes),offset:0});return true;
 }
 read(clock:number){
  let complete=0,valid=true;
  for(const block of this.blocks){
   const count=Atomics.load(block.count,0);
   if(count<block.offset||count>TIMING_GAPS_PER_BLOCK){complete++;valid=false;continue;}
   while(block.offset<count){
    const index=block.offset*3,step=block.values[index],end=block.values[index+1],resume=block.values[index+2];
    if(Number.isFinite(resume)&&resume>clock)break;
    block.offset++;
    let gaps=this.byStep.get(step);
    if(!validStep(step)||!Number.isFinite(end)||!Number.isFinite(resume)||end<(gaps?.at(-1)?.[1]??0)||resume<=end||resume<this.last){valid=false;continue;}
    if(!gaps){gaps=[];this.byStep.set(step,gaps);}
    gaps.push([timelineSeconds(end),timelineSeconds(resume)]);
    this.last=resume;
   }
   if(block.offset<TIMING_GAPS_PER_BLOCK)break;
   complete++;
  }
  this.blocks.splice(0,complete);
  return valid;
 }
}

// Windows stay in the cumulative snapshot. Gaps are recorded separately once.
export class ExecutionTiming {
 private started=performance.now();
 private windows=new Map<number,TimingWindow&{attempt:number}>();
 constructor(private onGap?:(step:number,end:TimelineSeconds,resume:TimelineSeconds)=>void){}
 seconds():TimelineSeconds{return timelineSeconds(Math.max(0,(performance.now()-this.started)/1000));}
 record(step:number,status:string,attempt=0){
  if(!statuses.includes(status)||!Number.isSafeInteger(attempt)||attempt<0)return;
  const now=this.seconds(),prior=this.windows.get(step);
  const value:TimingWindow={step,start:status==='active'?now:null,last:now,status:status as TimingWindow['status']};
  if(!validTiming(value,now))return;
  if(prior){
   if(attempt&&attempt<prior.attempt)return;
   if(attempt&&attempt===prior.attempt&&prior.status!=='active'&&prior.status!=='unknown')return;
   if(prior.status!=='active'&&status==='active'&&attempt&&attempt===prior.attempt)return;
   if(prior.status!=='active'&&(status===prior.status&&(!attempt||attempt===prior.attempt)||step<4&&status==='active'))return;
   if(status==='active'&&prior.status!=='active'&&prior.status!=='unknown'&&now>prior.last)this.onGap?.(step,prior.last,now);
   prior.last=now;prior.status=value.status;prior.attempt=Math.max(prior.attempt,attempt);
  }else if(this.windows.size<MAX_TIMING_WINDOWS)this.windows.set(step,{...value,attempt});
 }
 snapshot():TimingWindow[]{return [...this.windows.values()].map(({attempt,...window})=>window);}
}
