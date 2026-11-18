import {MAX_PHYSICAL_STEPS,PHYSICAL_ID_BASE} from './physical-history';
import type {PhysicalFact} from './physical-history';
export const MAX_EXECUTION_EVENTS=128;
export const eventKinds=['active','completed','interrupted','failed','handed_off','unknown','fusion','fallback','reuse','elided'] as const;
export type ExecutionEvent={index:number;step:number;seconds:number;kind:typeof eventKinds[number]};
export function stepSlot(id:number){return Number.isInteger(id)&&id>=0&&id<4?id:Number.isInteger(id)&&id>=PHYSICAL_ID_BASE&&id<PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS?id-PHYSICAL_ID_BASE+4:-1;}
// Deduplicate significant changes, never retain individual attempts or rows.
export class ExecutionEvents {
 readonly items:ExecutionEvent[]=[];
 omitted=0;
 private readonly seen=new Uint16Array(MAX_PHYSICAL_STEPS+4);
 private readonly started=performance.now();
 record(step:number,kind:ExecutionEvent['kind']){
  const slot=stepSlot(step),bit=eventKinds.indexOf(kind);if(slot<0||bit<0)return;
  const mask=1<<bit;if(this.seen[slot]&mask)return;this.seen[slot]|=mask;
  if(this.items.length===MAX_EXECUTION_EVENTS){this.omitted++;return;}
  this.items.push({index:this.items.length,step,kind,seconds:Math.max(0,(performance.now()-this.started)/1000)});
 }
 physical(fact:PhysicalFact){
  if(fact.kind==='omitted')return;
  this.record(fact.id,fact.status);
  if(fact.operations[0]&&fact.operations[1])this.record(fact.id,'fusion');
  if(fact.kind==='fallback'||fact.kind==='reuse'||fact.kind==='elided')this.record(fact.id,fact.kind);
 }
}
