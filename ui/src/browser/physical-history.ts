export const PHYSICAL_ID_BASE=1000,MAX_PHYSICAL_STEPS=1152;
import type {StepStatus} from './execution-history';
export const kinds=['read','resident_sort','fisher_yates','grouping','serialize','materialize','elided','routed_grouping','spill','merge','hierarchical_merge','merge_traversal','routing','fallback','reuse','exact_membership','probabilistic_membership','stratification','dataset_materialize','shared_ranges','interleaved_membership','balanced_traversal','fused_balanced','gzip_input','zstandard_input','zip_input','gzip_output','zstandard_output','zip_deflate','zip_archive'] as const;
export type Kind=typeof kinds[number];
export type Outcome='completed'|'interrupted'|'failed'|'handed_off';
export type Metrics={bytes:number;rows:number;seconds:number;runs:number;attempts:number;groups:number;empty_groups:number;memberships:number[];omitted_memberships:number};
export type PhysicalFact={id:number;bytes?:number;role?:number;groups?:number;empty_groups?:number;memberships?:number[];membership_len?:number;omitted_memberships?:number;kind:Kind|'omitted';operations:[number,number];rows:number;seconds:number;status:StepStatus;source_omitted:boolean;source?:number|null;sources?:(number|null)[];attempt?:number;runs?:number;level?:number|null};
export type StageFact=Omit<PhysicalFact,'kind'>&{kind:'stage_complete'};
export type PhysicalSummary={id:number;bytes:number;active_bytes:number;role:number;groups:number;empty_groups:number;memberships:number[];omitted_memberships:number;kind:Kind;operations:number[];rows:number;seconds:number;runs:number;status:StepStatus;attempts:number;completed_attempts:number;interrupted_attempts:number;partial_rows:number;partial_seconds:number;source_omitted:boolean;source?:number|null;sources:number[];outcomes:Record<Outcome,Metrics>;active_rows:number;active_seconds:number;active_runs:number;source_omissions:number;last_attempt:number;last_terminal:number;min_level:number|null;max_level:number|null};
export const physicalTitles:Record<Kind,string>={routed_grouping:'Read and materialize routed groups',read:'Read input',resident_sort:'Resident comparison sort',fisher_yates:'Resident Fisher–Yates shuffle',grouping:'Group and materialize rows',serialize:'Serialize CSV',materialize:'Write result files',elided:'Shuffle elided by later uniform shuffle',spill:'Sort and write spill runs',merge:'Materialize merge passes',hierarchical_merge:'Materialize hierarchical merge passes',merge_traversal:'Traverse final merge',routing:'Bounded value grouping',fallback:'Grouping handed off to sorting',reuse:'Reuse already ordered grouping files',exact_membership:'Exact allocation (inclusive)',probabilistic_membership:'Probabilistic allocation (inclusive)',stratification:'Group and materialize strata',dataset_materialize:'Stage intermediate rows and metadata',shared_ranges:'Share balanced row ranges',interleaved_membership:'Interleaved membership (inclusive)',balanced_traversal:'Emit consecutive balanced groups',fused_balanced:'Split balanced groups during sorted traversal',gzip_input:'Decode gzip input (inclusive)',zstandard_input:'Decode Zstandard input (inclusive)',zip_input:'Read selected ZIP member (inclusive)',gzip_output:'Compress gzip CSV (inclusive)',zstandard_output:'Compress Zstandard CSV (inclusive)',zip_deflate:'Deflate CSV members (inclusive)',zip_archive:'Build and finalize ZIP archive (inclusive)'};
const metrics=():Metrics=>({bytes:0,rows:0,seconds:0,runs:0,attempts:0,groups:0,empty_groups:0,memberships:[],omitted_memberships:0});
const outcomes=():Record<Outcome,Metrics>=>({completed:metrics(),interrupted:metrics(),failed:metrics(),handed_off:metrics()});
// Fixed operation/category summaries; no per-parent or per-file retained history.
export class PhysicalHistory {
 readonly summaries=new Map<number,PhysicalSummary>();unavailable=false;
 accept(fact:PhysicalFact){
  const bytes=fact.bytes??0,runs=fact.runs??0,attempt=fact.attempt??0,role=fact.role??0,groups=fact.groups??0,empty=fact.empty_groups??0,membershipLength=fact.membership_len??0,omittedMemberships=fact.omitted_memberships??0;
  if(!Number.isInteger(role)||role<0||role>1||![bytes,groups,empty,omittedMemberships].every(n=>Number.isSafeInteger(n)&&n>=0)||empty>groups||!Number.isInteger(membershipLength)||membershipLength<0||membershipLength>16||membershipLength>groups){this.unavailable=true;return;}
  if(!kinds.includes(fact.kind as Kind)||fact.operations.length!==2||fact.operations.some(n=>!Number.isInteger(n)||n<0||n>17)||!Number.isSafeInteger(fact.rows)||fact.rows<0||!Number.isSafeInteger(runs)||runs<0||!Number.isFinite(fact.seconds)||fact.seconds<0||!Number.isSafeInteger(attempt)||attempt<0){this.unavailable=true;return;}
  const id=fact.id;
  if(!Number.isInteger(id)||id<PHYSICAL_ID_BASE||id>=PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS){this.unavailable=true;return;}
  let summary=this.summaries.get(id);
  if(!summary){
   if(this.summaries.size===MAX_PHYSICAL_STEPS){this.unavailable=true;return;}
   summary={id,bytes:0,active_bytes:0,role,groups:0,empty_groups:0,memberships:[],omitted_memberships:0,kind:fact.kind as Kind,operations:fact.operations.filter(n=>n>0),rows:0,seconds:0,runs:0,status:fact.status,attempts:0,completed_attempts:0,interrupted_attempts:0,partial_rows:0,partial_seconds:0,source_omitted:fact.source_omitted,source:fact.source,sources:[],outcomes:outcomes(),active_rows:0,active_seconds:0,active_runs:0,source_omissions:0,last_attempt:0,last_terminal:0,min_level:null,max_level:null};this.summaries.set(id,summary);
  }
  if(summary.kind!==fact.kind||summary.role!==role){this.unavailable=true;return;}
  if(attempt&&attempt<summary.last_attempt)return;
  const terminal=['completed','interrupted','failed','handed_off'].includes(fact.status);
  if(attempt&&attempt<=summary.last_terminal)return;
  summary.last_attempt=Math.max(summary.last_attempt,attempt);
  summary.status=fact.status;if(fact.status==='active'){summary.active_bytes=bytes;summary.active_rows=fact.rows;summary.active_seconds=fact.seconds;summary.active_runs=runs;}
  if(terminal&&fact.source_omitted)summary.source_omissions++;
  summary.source_omitted=summary.source_omissions>0||fact.source_omitted;
  for(const source of [...(fact.sources??[]),fact.source]){
   if(source==null||summary.sources.includes(source))continue;
   if(source===id||!Number.isInteger(source)||source<0||source>=4&&source<PHYSICAL_ID_BASE||source>=PHYSICAL_ID_BASE+MAX_PHYSICAL_STEPS||summary.sources.length===4){this.unavailable=true;summary.source_omitted=true;summary.source_omissions++;continue;}
   summary.sources.push(source);
  }
  if(terminal){
   const target=summary.outcomes[fact.status as Outcome];
   if(!Number.isSafeInteger(target.bytes+bytes)||!Number.isSafeInteger(target.rows+fact.rows)||!Number.isSafeInteger(target.runs+runs)||!Number.isFinite(target.seconds+fact.seconds)||summary.attempts===Number.MAX_SAFE_INTEGER){this.unavailable=true;return;}
   const memberships=Array.from({length:Math.max(target.memberships.length,membershipLength)},(_,index)=>(target.memberships[index]??0)+(index<membershipLength?(fact.memberships?.[index]??0):0));
   if(memberships.some(n=>!Number.isSafeInteger(n)||n<0)||![target.groups+groups,target.empty_groups+empty,target.omitted_memberships+omittedMemberships].every(n=>Number.isSafeInteger(n))){this.unavailable=true;return;}
   target.groups+=groups;target.empty_groups+=empty;target.memberships=memberships;target.omitted_memberships+=omittedMemberships;
   target.bytes+=bytes;target.rows+=fact.rows;target.seconds+=fact.seconds;target.runs+=runs;target.attempts++;summary.attempts++;summary.last_terminal=Math.max(summary.last_terminal,attempt);
   summary.bytes=summary.outcomes.completed.bytes;summary.rows=summary.outcomes.completed.rows;summary.seconds=summary.outcomes.completed.seconds;summary.runs=summary.outcomes.completed.runs;summary.completed_attempts=summary.outcomes.completed.attempts;summary.groups=summary.outcomes.completed.groups;summary.empty_groups=summary.outcomes.completed.empty_groups;summary.memberships=[...summary.outcomes.completed.memberships];summary.omitted_memberships=summary.outcomes.completed.omitted_memberships;
   summary.interrupted_attempts=summary.outcomes.interrupted.attempts;summary.partial_rows=summary.outcomes.interrupted.rows;summary.partial_seconds=summary.outcomes.interrupted.seconds;
   if(fact.level!=null){if(!Number.isSafeInteger(fact.level)||fact.level<0||fact.level>64){this.unavailable=true;return;}summary.min_level=Math.min(summary.min_level??fact.level,fact.level);summary.max_level=Math.max(summary.max_level??fact.level,fact.level);}
  }
 }
 snapshot(){return [...this.summaries.values()].map(value=>({...value,operations:[...value.operations],memberships:[...value.memberships],sources:[...value.sources],outcomes:Object.fromEntries(Object.entries(value.outcomes).map(([key,metric])=>[key,{...metric,memberships:[...metric.memberships]}])) as Record<Outcome,Metrics>}));}
}
