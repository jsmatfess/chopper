import {timelineSeconds,type TimelineSeconds} from './measurements';
import {MAX_PHYSICAL_STEPS,PHYSICAL_ID_BASE,type PhysicalFact} from './physical-history';
export type TimingWindow={step:number;start:TimelineSeconds|null;last:TimelineSeconds;status:PhysicalFact['status']};
const statuses=['active','completed','interrupted','failed','handed_off','unknown'];
export const MAX_TIMING_WINDOWS=MAX_PHYSICAL_STEPS+4;
export function validTiming(value:TimingWindow,clock:number){
 return value&&Number.isInteger(value.step)&&(value.step>=0&&value.step<4||value.step>=PHYSICAL_ID_BASE&&value.step<PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS)&&Number.isFinite(value.last)&&value.last>=0&&value.last<=clock&&(value.start===null||Number.isFinite(value.start)&&value.start>=0&&value.start<=value.last)&&statuses.includes(value.status);
}
// One envelope per physical identity, not an unbounded trace of parent attempts.
export class ExecutionTiming {
 private started=performance.now();
 private windows=new Map<number,TimingWindow&{attempt:number}>();
 seconds():TimelineSeconds{return timelineSeconds(Math.max(0,(performance.now()-this.started)/1000));}
 record(step:number,status:string,attempt=0){
  if(!statuses.includes(status)||!Number.isSafeInteger(attempt)||attempt<0)return;
  const now=this.seconds(),prior=this.windows.get(step);
  const value:TimingWindow={step,start:status==='active'?now:null,last:now,status:status as TimingWindow['status']};
  if(!validTiming(value,now))return;
  if(prior){
   if(attempt&&attempt<prior.attempt)return;
   if(prior.status!=='active'&&status==='active'&&attempt&&attempt===prior.attempt)return;
   if(prior.status!=='active'&&(status===prior.status&&(!attempt||attempt===prior.attempt)||step<4&&status==='active'))return;
   prior.last=now;prior.status=value.status;prior.attempt=Math.max(prior.attempt,attempt);
  }else if(this.windows.size<MAX_TIMING_WINDOWS)this.windows.set(step,{...value,attempt});
 }
 snapshot():TimingWindow[]{return [...this.windows.values()].map(({step,start,last,status})=>({step,start,last,status}));}
}
