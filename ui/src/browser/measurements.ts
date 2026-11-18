import type {Kind} from './physical-history';
// Values cross the worker as numbers; constructors establish their meaning at
// the boundary. Work time and timeline time deliberately cannot be interchanged.
declare const unit:unique symbol;
export type WorkSeconds=number&{readonly [unit]:'inclusive-work-seconds'};
export type TimelineSeconds=number&{readonly [unit]:'timeline-seconds'};
export type WindowSeconds=number&{readonly [unit]:'activity-window-seconds'};
function seconds(value:number){if(!Number.isFinite(value)||value<0)throw new Error('Invalid duration');return value;}
export const workSeconds=(value:number)=>seconds(value) as WorkSeconds;
export const timelineSeconds=(value:number)=>seconds(value) as TimelineSeconds;
export const activityDuration=(start:TimelineSeconds,end:TimelineSeconds)=>seconds(end-start) as WindowSeconds;
export type RowCount=Readonly<{unit:'rows';value:number}>;
export type RowVisits=Readonly<{unit:'row visits';value:number}>;
export type FrameLengths=Readonly<{unit:'frame lengths';value:number}>;
export type ByteCount=Readonly<{unit:'bytes';value:number}>;
export type Counter=RowCount|RowVisits|FrameLengths|ByteCount;
// Exhaustive: a new engine/card kind also needs an explicit display unit.
function counterUnit(kind:Kind|undefined):Counter['unit']|null {
 switch(kind){
 case 'gzip_input':case 'zstandard_input':case 'zip_input':case 'gzip_output':case 'zstandard_output':case 'zip_deflate':case 'zip_archive':return 'bytes';
 case 'shared_ranges':return 'frame lengths';
 case 'merge':case 'hierarchical_merge':case 'merge_traversal':return 'row visits';
 case 'materialize':case 'elided':case 'fallback':case 'reuse':return null;
 case undefined:case 'read':case 'resident_sort':case 'fisher_yates':case 'grouping':case 'serialize':case 'routed_grouping':case 'spill':case 'routing':case 'exact_membership':case 'probabilistic_membership':case 'stratification':case 'dataset_materialize':case 'interleaved_membership':case 'balanced_traversal':case 'fused_balanced':return 'rows';
 default:{const exhaustive:never=kind;throw new Error(`Unsupported measurement kind: ${exhaustive}`);}
 }
}
export function counter(kind:Kind|undefined,rows:number,bytes:number):Counter|null {
 const unit=counterUnit(kind),value=unit==='bytes'?bytes:rows;return unit===null||!Number.isSafeInteger(value)||value<0?null:{unit,value} as Counter;
}
export function averageRate(count:Counter,work:WorkSeconds):number|null {
 if(!Number.isSafeInteger(count.value)||count.value<0||work<=0)return null;
 const rate=count.value/work;return rate>0&&Number.isFinite(rate)?rate:null;
}
