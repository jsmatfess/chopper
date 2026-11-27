import {job_values as jobValues} from '../../docs/cli-reference-data.json';
import type {Job} from './app';

// Literal selectors avoid comma splitting and preserve names versus indices.
export function runArguments(job:Job):string[]{
 const args=['run'];
 const add=(flag:string,value:unknown)=>{if(value!==null&&value!==undefined)args.push(`--${flag}=${String(value)}`);};
 add('input',job.input);add('output',job.output);
 if(job.version!==jobValues.version)add('job-version',job.version);
 add('zip-member',job.zip_member);
 add('compression',job.compression);
 for(const [field,flag] of [['rows','rows'],['bytes','bytes'],['compressed_bytes','compressed-bytes']] as const)add(flag,job.limits[field]);
 for(const [field,flag] of [['memory_mb','memory-mb'],['workers','workers'],['grouping','grouping'],['max_files','max-files'],['max_record_bytes','max-record-bytes'],['temp_dir','temp-dir'],['temp_bytes','temp-bytes']] as const)add(flag,job.resources[field]);
 add('full-shuffle-rng',job.full_shuffle_rng);add('full-shuffle-algorithm',job.full_shuffle_algorithm);
 const csvDefaults={encoding:'utf-8',headers:true,delimiter:',',quote:'"',escape:null,line_ending:'lf',bom:false,skip_empty_lines:false};
 for(const prefix of ['input','output'] as const){
  const settings=job[`${prefix}_csv`];
  for(const field of Object.keys(csvDefaults) as (keyof typeof csvDefaults)[]){if(settings[field]!==csvDefaults[field])add(`${prefix}-${field.replaceAll('_','-')}`,settings[field]);}
 }
 for(const [field,defaultValue] of Object.entries({trim:'none',comment_prefix:null,skip_rows:0,skip_columns:0,skip_blank_rows:false})){
  const value=job.input_dialect?.[field as keyof NonNullable<Job['input_dialect']>];
  if(value!==defaultValue)add(`input-${field.replaceAll('_','-')}`,value);
 }
 for(const column of job.calculated_columns??[])add('calculated-column',`${column.name}=${column.expression}`);
 for(const op of job.operations){
  add('step',op.type);
  switch(op.type){
   case 'partition':for(const column of op.columns??[])add(typeof column==='number'?'column-index':'column',column);break;
   case 'assign':case 'assign_probabilistic':
    for(const group of op.groups??[])add('group',`${group.name}=${group.percent}`);
    for(const column of op.strata??[])add(typeof column==='number'?'stratum-index':'stratum',column);break;
   case 'shuffle':add('strategy',op.strategy??'uniform');break;
   case 'balanced':case 'interleaved':add('files',op.files);break;
   default:throw new Error(`Unsupported CLI step: ${op.type}`);
  }
 }
 args.push('--yes');return args;
}
export type CommandPlatform='windows'|'linux'|'macos';
export function defaultCommandPlatform(platform:string):CommandPlatform{
 const name=platform.toLowerCase();return name.includes('win')?'windows':name.includes('mac')?'macos':'linux';
}
// PowerShell 7.3+ in Standard/Windows mode preserves embedded native-argument quotes.
const powershellLiteral=(value:string)=>`'${value.replaceAll("'","''")}'`;
const posixLiteral=(value:string)=>`'${value.replaceAll("'",`'"'"'`)}'`;
export function runCommand(job:Job,platform:CommandPlatform='windows'){
 const windows=platform==='windows',args=runArguments(job);
 const executable=windows?'.\\chopper.exe':'./chopper';
 const safe=windows?/^[a-zA-Z0-9_=./:\\-]+$/:/^[a-zA-Z0-9_=./:-]+$/;
 const quote=windows?powershellLiteral:posixLiteral;
 const command=executable+' '+args.map(arg=>safe.test(arg)?arg:quote(arg)).join(' ');
 // A conservative portable threshold leaves headroom for native argument limits.
 const usesJson=command.length>24000||args.some(arg=>arg.includes('\0'))||job.calculated_columns?.some(column=>column.name.includes('='))===true;
 return {command:usesJson?`${executable} run --config ${windows?'.\\chopper-job.json':'./chopper-job.json'} --yes`:command,usesJson};
}
