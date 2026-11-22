export const limits = {rows:'',bytes:'',compressed:''};
export const partition = {type:'partition',columns:['country','segment']};
export const assign = {type:'assign',groups:[{name:'treatment',percent:'80'},{name:'control',percent:'20'}],strata:[]};
export const balanced = {type:'balanced',files:3};
export const shuffle = {type:'shuffle',strategy:'auto'};
const scenario = (name, operations, changes = {}) => ({name,operations,limits,compression:'none',...changes});
export const scenarios = [
  scenario('One plain CSV',[]),
  scenario('Row chunks',[],{limits:{...limits,rows:'100000'}}),
  scenario('Byte chunks in one ZIP',[],{limits:{...limits,bytes:'64MiB'},compression:'zip'}),
  scenario('Full shuffle',[shuffle]),
  scenario('Fisher-Yates shuffle into chunks',[{...shuffle,strategy:'fisher_yates'}],{limits:{...limits,rows:'1000'}}),
  scenario('One partition column',[{...partition,columns:['country']}]),
  scenario('Two partition columns',[partition]),
  scenario('Three partition columns',[{...partition,columns:['country','segment','channel']}]),
  scenario('Numeric column references',[{...partition,columns:[0,2]}]),
  scenario('Treatment and control',[assign]),
  scenario('Three allocations',[{...assign,groups:[{name:'A',percent:'50'},{name:'B',percent:'30'},{name:'C',percent:'20'}]}]),
  scenario('Allocation names with punctuation',[{...assign,groups:[{name:'control, holdout=1',percent:'80'},{name:'test <new>',percent:'20'}]}]),
  scenario('Single allocation',[{...assign,groups:[{name:'all',percent:'100'}]}]),
  scenario('Zero-percent allocation',[{...assign,groups:[{name:'all',percent:'100'},{name:'empty',percent:'0'}]}]),
  scenario('Empty allocation listed first',[{...assign,groups:[{name:'empty',percent:'0'},...assign.groups]}]),
  scenario('Country strata pooled into allocation files',[{...assign,strata:['country']}]),
  scenario('Partition then allocation',[partition,assign]),
  scenario('Allocation then partition',[assign,partition]),
  scenario('Redundant strata',[partition,{...assign,strata:['country','segment']}]),
  scenario('Additional strata',[{...partition,columns:['country']},{...assign,strata:['country','segment']}]),
  scenario('Partition, allocation, shuffle, balanced parts',[partition,assign,shuffle,balanced]),
  scenario('Stratified allocation, shuffle, limits and ZIP',[{...assign,strata:['country','segment']},shuffle],{limits:{rows:'100000',bytes:'64MiB',compressed:'10MB'},compression:'zip'}),
  scenario('Shuffle before balanced splitting',[shuffle,balanced]),
  scenario('Shuffle after balanced splitting',[balanced,shuffle]),
  scenario('Partition then balanced splitting',[partition,balanced]),
  scenario('Balanced splitting then partition',[balanced,partition]),
  scenario('Balanced splitting then allocation',[balanced,assign]),
  scenario('Allocation then balanced splitting',[assign,balanced]),
  scenario('Fixed balanced files with hard limits',[balanced,shuffle],{limits:{rows:'10000',bytes:'64MiB',compressed:''}}),
  scenario('Balanced splitting followed by subdividable partitions',[balanced,partition],{limits:{...limits,rows:'1000'}}),
  scenario('Balanced splitting followed by subdividable allocations',[balanced,assign],{limits:{...limits,rows:'1000'}}),
  scenario('Repeated partitions',[partition,{...partition,columns:['channel']}]),
  scenario('Repeated allocations',[assign,{...assign,groups:[{name:'A',percent:'50'},{name:'B',percent:'50'}]}]),
  scenario('Repeated balanced splits',[balanced,{...balanced,files:2}]),
  scenario('Repeated shuffles',[shuffle,shuffle,shuffle,balanced]),
  scenario('One balanced file',[{...balanced,files:1}]),
  scenario('Compressed target without hard limits',[partition],{limits:{...limits,compressed:'10MB'},compression:'gzip'}),
  scenario('Balanced files with compressed target',[balanced],{limits:{...limits,compressed:'10MB'},compression:'gzip'}),
  scenario('Compressed target without compression',[],{limits:{...limits,compressed:'10MB'}}),
  scenario('Unfinished partition',[{type:'partition',columns:[]}]),
  scenario('Unfinished allocation',[{type:'assign',groups:[]}]),
  scenario('Invalid allocation total',[{...assign,groups:[{name:'A',percent:'60'},{name:'B',percent:'30'}]}]),
  scenario('Unfinished balanced split',[{type:'balanced',files:0}]),
];

// Every ordering and repetition of five step variants, through four steps.
export function* combinations(depth = 4, prefix = []) {
  yield prefix;
  if (prefix.length === depth) return;
  for (const step of [partition,assign,balanced,shuffle,{...shuffle,strategy:'fisher_yates'}]) yield* combinations(depth,[...prefix,step]);
}

export function* simulations() {
  for (const operations of combinations()) {
    for (const compression of ['none','gzip','zip']) {
      for (const configuration of [limits,{...limits,rows:'1000',bytes:'64MiB'},{...limits,compressed:'10MB'}]) {
        yield {operations,compression,limits:configuration};
      }
    }
  }
}
