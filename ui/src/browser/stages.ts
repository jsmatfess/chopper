import {PHYSICAL_ID_BASE,type StageFact} from './physical-history';
// Rust keeps the retired codec category slots reserved in the physical IDs.
const STAGE_COMPLETE_SLOT=30;
// One finalization per logical stage, never one entry per group or attempt.
export class StageCompletions {
 private stages=new Set<number>();
 unavailable=false;
 accept(fact:StageFact){
  const operation=fact.operations?.[0];
  if(fact.kind!=='stage_complete'||fact.status!=='completed'||fact.operations?.length!==2||(fact.role??0)!==0||!Number.isSafeInteger(fact.attempt)||fact.attempt!<1||!Number.isInteger(operation)||operation<0||operation>17||fact.operations[1]!==0||fact.id!==PHYSICAL_ID_BASE+operation*32+STAGE_COMPLETE_SLOT||fact.rows!==0){this.unavailable=true;return;}
  this.stages.add(operation);
 }
 snapshot(){return [...this.stages].sort((a,b)=>a-b);}
}

// Plan linkage is not lifecycle ownership: codecs use the output plan's number
// but run during publication, after the retained CSV snapshot has finalized.
export const lifecycleScopes:Record<import('./physical-history').Kind,'input'|'operation'|'serialization'|'publication'|'intermediate'>={
 read:'input',gzip_input:'input',zip_input:'input',
 serialize:'serialization',materialize:'publication',gzip_output:'publication',zip_deflate:'publication',zip_archive:'publication',
 dataset_materialize:'intermediate',
 resident_sort:'operation',fisher_yates:'operation',grouping:'operation',elided:'operation',routed_grouping:'operation',spill:'operation',merge:'operation',hierarchical_merge:'operation',merge_traversal:'operation',routing:'operation',fallback:'operation',reuse:'operation',exact_membership:'operation',probabilistic_membership:'operation',stratification:'operation',shared_ranges:'operation',interleaved_membership:'operation',balanced_traversal:'operation',fused_balanced:'operation',
};
