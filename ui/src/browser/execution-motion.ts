import type {Kind} from './physical-history';

type MotionKind=Kind|'write'|'export'|'confirm'|'uniform_sort'|'fused_sort';
const path=(d:string,actor='')=>`<path d="${d}" class="${actor?`motion-actor ${actor}`:'motion-track'}"/>`;
const bar=(x:number,y:number,w:number,h:number,actor='motion-a')=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1" class="motion-actor ${actor}"/>`;
const dot=(x:number,y:number,actor='motion-a')=>`<circle cx="${x}" cy="${y}" r="2" class="motion-actor ${actor}"/>`;
const rows=path('M4 5h18M4 12h18M4 19h18');
const bins=path('M34 2h10v5H34zM34 10h10v5H34zM34 18h10v5H34z');
const sortBars=bar(37,10,6,12)+bar(5,18,6,4,'motion-b')+bar(21,14,6,8,'motion-c');
const mergeObjects=bar(3,2,4,4)+bar(3,18,4,4,'motion-b')+bar(23,9,6,6,'motion-c');
const sheet=path('M30 3h12v18H30zM33 7h6M33 11h6M33 15h6');

// Fixed, decorative diagrams: no per-row DOM, timing estimates or engine callbacks.
export const motionScenes={
 read:path('M4 5h36M4 12h36M4 19h36')+bar(3,3,2,4),
 resident_sort:path('M3 23h42')+sortBars,
 uniform_sort:path('M3 23h42M7 3h4M23 3h2M39 3h5')+sortBars,
 fused_sort:path('M3 23h12M19 23h12M35 23h10')+sortBars,
 fisher_yates:path('M10 12C16 0 30 0 36 12M36 12C30 24 16 24 10 12')+bar(7,9,6,6)+bar(33,9,6,6,'motion-b'),
 grouping:path('M32 2h12v8H32zM32 14h12v8H32z')+bar(5,3,12,3)+bar(5,10,12,3,'motion-b')+bar(5,17,12,3,'motion-c'),
 serialize:path('M14 4v16M28 4v16M42 4v16')+bar(3,9,7,4)+bar(17,9,7,4,'motion-b')+bar(31,9,7,4,'motion-c'),
 materialize:path('M27 5h17v16H27zM30 2h11M4 12h18')+bar(7,9,9,6),
 elided:path('M4 5l16 14M4 19 20 5M26 12h18')+path('M2 22 23 1','motion-a'),
 routed_grouping:path('M3 3h9v7H3zM3 15h9v7H3zM15 6h8l8 6-8 6h-8M34 12h10')+bar(6,5,4,3)+bar(6,17,4,3,'motion-b'),
 spill:path('M2 23h29M36 13v9h10v-9M36 10h10')+bar(23,10,5,12)+bar(3,18,5,4,'motion-b')+bar(13,14,5,8,'motion-c'),
 merge:path('M5 4h8l13 8h18M5 20h8l13-8')+mergeObjects,
 hierarchical_merge:path('M3 2h4l9 5h8l9 5h12M3 22h4l9-5h8l9-5M3 12h4l9-5')+bar(1,.5,4,3)+bar(1,20.5,4,3,'motion-b')+bar(30,9,6,6,'motion-c'),
 merge_traversal:path('M5 4h8l13 8h18M5 20h8l13-8M32 8v8M39 8v8')+mergeObjects,
 routing:bins+path('M3 12h18l10-8M21 12h10M21 12l10 8')+dot(5,12),
 fallback:path('M3 5h15l6 7M3 19h15l6-7M28 5h14M28 12h10M28 19h6')+path('M4 12h36','motion-a'),
 reuse:path('M4 5h18M4 12h18M4 19h18M28 7h15M28 17h15')+path('M26 12h18','motion-a'),
 exact_membership:bins+bar(3,4,5,3)+bar(11,4,5,3,'motion-b')+bar(19,4,5,3,'motion-c'),
 probabilistic_membership:bins+path('M4 12h15l12-8M19 12h12M19 12l12 8')+dot(7,12),
 stratification:path('M3 3h17v7H3zM3 14h17v7H3zM29 3h15v7H29zM29 14h15v7H29z')+bar(6,5,5,3)+bar(13,16,5,3,'motion-b'),
 dataset_materialize:path('M28 3v18h16V3M30 8h12M30 14h12')+bar(3,4,15,3)+bar(3,11,15,3,'motion-b')+bar(3,18,15,3,'motion-c'),
 shared_ranges:path('M3 5h42v14H3zM17 5v14M31 5v14')+path('M4 22h12','motion-a'),
 interleaved_membership:bins+dot(4,5)+dot(11,12,'motion-b')+dot(18,19,'motion-c'),
 balanced_traversal:path('M3 6h42M3 18h42M17 4v16M31 4v16')+bar(4,9,9,6),
 fused_balanced:path('M3 4h14M3 12h18M3 20h10M28 2v20M38 2v20')+bar(8,10,8,4),
 gzip_input:path('M4 5h9v14H4zM29 4h15M29 12h15M29 20h15')+bar(17,9,8,6),
 zip_input:path('M3 3h18v18H3zM6 7h11M6 12h11M6 17h11M29 6h14v15H29z')+bar(8,10,10,4),
 gzip_output:path('M3 4h16M3 12h16M3 20h16M34 5h10v14H34z')+bar(22,7,9,10),
 zip_deflate:path('M3 5h12M3 12h12M3 19h12M34 4v16M31 6h6M31 11h6M31 16h6')+bar(19,9,8,5),
 zip_archive:path('M27 4h17v17H27zM33 4v17M30 8h6M30 14h6')+bar(3,2,8,5)+bar(6,10,8,5,'motion-b')+bar(9,18,8,5,'motion-c'),
 write:sheet+bar(3,5,14,3)+bar(3,12,14,3,'motion-b')+bar(3,19,14,3,'motion-c'),
 export:path('M28 8h16v14H28zM28 8l3-5h10l3 5')+bar(3,4,9,13)+bar(9,7,9,13,'motion-b'),
 confirm:path('M13 3h22v18H13zM18 8h12M18 16h12')+path('M10 12h28','motion-a'),
} satisfies Record<MotionKind,string>;

export function stepMotion(step:{id:number;kind?:Kind;operations?:number[];operation?:number},configured:readonly {id:number;label:string}[]):MotionKind{
 if(step.kind==='resident_sort'&&(step.operations??[step.operation]).some(id=>configured.find(op=>op.id===id)?.label.startsWith(`${id}. shuffle`)))return (step.operations?.length??0)>1?'fused_sort':'uniform_sort';
 return step.kind??(['read','write','export','confirm'] as const)[step.id]??'read';
}
export function motionMarkup(kind:MotionKind):string{
 return `<svg class="execution-node-motion" data-motion="${kind}" viewBox="0 0 48 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round">${motionScenes[kind]}</svg>`;
}
