// Benchmark-only candidates. Keep the rule fixed before viewing held-out timings.
const MIB=1024*1024;
const tiers=[256,512,1024,2048];
const tierFor=bytes=>tiers.find(tier=>tier*MIB/4>=bytes)??256;

export function previewCandidate(job,bytes,sample) {
  const ops=job.operations;
  const last=ops.at(-1);
  const partitioned=ops.length===2&&ops[0].type==='partition';
  const eligible=(ops.length===1||partitioned)&&last?.type==='shuffle'&&last.strategy!=='fisher_yates'
    &&job.compression==='none'&&job.resources.grouping==='auto'&&job.resources.memory_mb==='auto';
  if(!eligible)return {eligible:false,previewTier:null,sizeTier:null,baseCue:false,previewCue:false};
  const plain=job.input.endsWith('.csv')&&job.input_csv.encoding==='utf-8';
  const gzip=job.input.endsWith('.gz');
  const keyFactor=partitioned?1.125:1;
  const rough=plain&&bytes>=48*MIB?1.5*bytes*keyFactor:null;
  const sizeTier=rough===null?256:tierFor(rough);
  const compressedCue=gzip&&bytes>=256*1024;
  const nearBoundary=(estimate,tier)=>estimate!==null&&tier<2048&&estimate>=0.75*tier*MIB/4&&estimate<=tier*MIB/4;
  const baseCue=compressedCue||nearBoundary(rough,sizeTier);
  // The present preview returns decoded fields, not exact consumed source
  // bytes. Only use full, simple UTF-8 samples for the first candidate.
  const csv=job.input_csv;
  const usable=plain&&bytes>=32*MIB&&sample?.preview.length===8&&sample.columns>=1
    &&csv.delimiter===','&&csv.quote==='"'&&csv.escape===null&&!csv.skip_empty_lines
    &&sample.preview.every(row=>row.length===sample.columns&&row.every(field=>!/[,"\r\n]/.test(field)));
  let footprint=null,previewTier=sizeTier;
  if(usable){
    const utf8=new TextEncoder();
    const widths=sample.preview.map(row=>row.reduce((sum,field)=>sum+utf8.encode(field).length,0));
    const width=widths.reduce((sum,value)=>sum+value,0)/widths.length;
    const estimatedRows=bytes/(width+sample.columns);
    footprint=estimatedRows*(width+200+8*sample.columns)*keyFactor;
    previewTier=Math.max(sizeTier,tierFor(footprint));
  }
  return {
    eligible:true,usable,columns:sample?.columns??null,sampledRows:sample?.preview.length??0,
    estimatedSortBytes:footprint,previewTier,sizeTier,baseCue,
    previewCue:compressedCue||nearBoundary(footprint,previewTier),
  };
}

export function calibrationPayload(id){
  let state=(id+1)|0,value='';
  for(let index=0;index<52;index++){
    state^=state<<13;state^=state>>>17;state^=state<<5;
    value+='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'[state&63];
  }
  return value;
}

// Bounded probe for preliminary plain-CSV sort sizing. Complete-looking lines
// from the interior can still be inside a quoted CSV field.
export async function windowCandidate(job,input,sample,startingPlan) {
  const windowBytes=64*1024;
  const start=performance.now();
  const startingTier=startingPlan?.previewTier??256;
  const report=(target,records,bytes,footprint)=>({target,records,bytes,footprint,
    planning_seconds:(performance.now()-start)/1000});
  if(!startingPlan?.usable||startingTier!==1024||!job.input_csv.headers)
    return report(startingTier,0,0,null);
  const csv=new TextDecoder('utf-8',{fatal:true});
  let records=0,bytes=0;
  for(const fraction of [0.25,0.50,0.75,0.875]){
    const offset=Math.floor(input.size*fraction);
    const buffer=new Uint8Array(await input.slice(offset,offset+windowBytes).arrayBuffer());
    const first=buffer.indexOf(10),last=buffer.lastIndexOf(10);
    if(first<0||last<=first||buffer.includes(34)||buffer.includes(13))
      return report(startingTier,records,bytes,null);
    let lines;
    try{lines=csv.decode(buffer.subarray(first+1,last)).split('\n');}
    catch{return report(startingTier,records,bytes,null);}
    if(lines.length<8||lines.some(line=>line.split(',').length!==sample.columns))
      return report(startingTier,records,bytes,null);
    bytes+=last-first;
    records+=lines.length;
  }
  const keyFactor=job.operations.length===2?1.125:1;
  const footprint=input.size*(1+records*(200+7*sample.columns)/bytes)*keyFactor;
  return report(footprint>256*MIB&&footprint<=528*MIB?2048:startingTier,records,bytes,footprint);
}
