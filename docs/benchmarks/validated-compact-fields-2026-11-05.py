import pathlib,json,hashlib,subprocess,time,sys,csv,statistics,os,re
p=pathlib.Path(sys.argv[1]);sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();read=lambda f:json.loads(f.read_text());write=lambda f,d:f.write_text(json.dumps(d,indent=2)+'\n')
if sys.argv[2]=='fixtures':
 meta={}
 for n in [1000000,200000]:
  f=p/f'input-{n}.csv'; assert not f.exists(); counters={'rows_including_header':n+1,'fields':(n+1)*3,'payload_bytes':0,'checksum':0}
  with f.open('w',encoding='utf8',newline='') as out:
   out.write('id,region,payload\n')
   for field in ['id','region','payload']:counters['payload_bytes']+=len(field);counters['checksum']+=len(field)+ord(field[0])
   for id in range(n):
    fields=[str(id),f'R{id%4}',f'note-{id}-'+('x'*(24+id%97))];out.write(','.join(fields)+'\n')
    for field in fields:counters['payload_bytes']+=len(field);counters['checksum']+=len(field)+ord(field[0])
  meta[str(n)]={'sha256':sha(f),'bytes':f.stat().st_size,'probe_expected':counters}
 write(p/'fixtures.json',meta); print('Two fixed probe-v1 fixtures generated',[(k,v['bytes']) for k,v in meta.items()]);sys.exit(0)
fixtures=read(p/'fixtures.json'); roots={c:p/(c+'-src') for c in ['baseline','candidate']};bins={c:p/(c+'-target')/'release/chopper.exe' for c in roots};probes={c:p/(c+'-target')/'release/examples/serial-parser-probe.exe' for c in roots}
for n,v in fixtures.items():assert sha(p/f'input-{n}.csv')==v['sha256']
assert not (p/'runs').exists();(p/'runs').mkdir();records=[];reference={}
logical=['algorithm_version','column_values','seed','rows','columns','header','preview','logical_digest','groups','output_files','output_csv_bytes','largest_record_bytes','memory_budget_bytes','workers','stages','warnings','accuracy']
def retain(record):
 with (p/'attempts.jsonl').open('a') as out:out.write(json.dumps(record)+'\n');out.flush();os.fsync(out.fileno())
def verify(output,job,n,analysis,recipe):
 rows=0;seen=bytearray(n);files={};outrecords=[]
 for line in (output/'manifest.jsonl').read_text().splitlines():
  r=json.loads(line)
  if r.get('type')=='output':outrecords.append(r)
 assert len(outrecords)==analysis['output_files']
 for record in outrecords:
  f=output/record['path'];assert f.is_file();length=f.stat().st_size;assert length<=job['limits']['bytes'] and length==record['csv_bytes'];count=0
  with f.open(encoding='utf8',newline='') as stream:
   reader=csv.reader(stream,strict=True);assert next(reader)==['id','region','payload']
   for fields in reader:
    assert len(fields)==3;id=int(fields[0]);assert 0<=id<n and not seen[id];seen[id]=1;assert fields==[str(id),f'R{id%4}',f'note-{id}-'+('x'*(24+id%97))]
    if recipe=='ordered':assert id==rows
    else:assert record['lineage'][0]['values']==[f'R{id%4}'] and record['lineage'][1]['allocation'] in ['treatment','control']
    rows+=1;count+=1
  assert count==record['rows'] and count<=job['limits']['rows'];files[f.name]=sha(f)
 assert rows==n==analysis['rows'] and all(seen)
 assert analysis['groups']==(1 if recipe=='ordered' else 12)
 assert set(f.name for f in output.iterdir())==set(files)|{'manifest.jsonl'}
 assert sum((output/name).stat().st_size for name in files)==analysis['output_csv_bytes']
 if recipe=='ordered':assert len(files)==1 and next(iter(files.values()))==fixtures[str(n)]['sha256']
 return {'files_sha256':files,'output_records':outrecords,'logical_analysis':{k:analysis[k] for k in logical}}
schedule=[('pipeline',False),('pipeline',True),('pipeline',True),('pipeline',False),('ordered',False),('ordered',True)]
for index,(recipe,candidate) in enumerate(schedule):
 cell='candidate' if candidate else 'baseline';n=1000000;run=p/'runs'/f'{index}-{recipe}-{cell}';run.mkdir();(run/'temp').mkdir();output=run/'output'
 operations=[] if recipe=='ordered' else [{'type':'partition','columns':[1]},{'type':'assign_probabilistic','groups':[{'name':'treatment','percent':'80'},{'name':'control','percent':'20'},{'name':'empty','percent':'0'}],'strata':[]},{'type':'shuffle','strategy':'uniform'}]
 job={'input':str(p/f'input-{n}.csv'),'output':str(output),'seed':'strict-csv-serial-v1','operations':operations,'limits':{'rows':1000000,'bytes':134217728},'resources':{'memory_mb':32,'workers':4,'temp_dir':str(run/'temp'),'temp_bytes':1073741824,'max_files':4096,'max_record_bytes':1048576,'grouping':'auto'}}
 write(run/'job.json',job);argv=[str(bins[cell]),'run','--config',str(run/'job.json'),'--yes'];retain({'index':index,'recipe':recipe,'candidate':candidate,'state':'launched','argv':argv,'time_unix':time.time()})
 started=time.perf_counter();run_env=os.environ.copy();run_env['CHOPPER_MEMORY_LIMIT_MB']='32';result=subprocess.run(argv,capture_output=True,env=run_env);seconds=time.perf_counter()-started;(run/'stdout.log').write_bytes(result.stdout);(run/'stderr.log').write_bytes(result.stderr);assert result.returncode==0, result.stderr.decode(errors='replace')
 assert b'PARALLEL_CSV' not in result.stderr
 analysis=json.loads(result.stdout);write(run/'analysis.json',analysis);checked=verify(output,job,n,analysis,recipe)
 if recipe in reference:assert checked==reference[recipe]
 else:reference[recipe]=checked
 write(run/'verified.json',checked);assert not any((run/'temp').iterdir()) and not any(f.name.startswith('.chopper-staging-') for f in run.iterdir());record={'type':'complete_job','index':index,'recipe':recipe,'candidate':candidate,'rows':n,'seconds':seconds,'binary_sha256':sha(bins[cell]),'input_sha256':fixtures[str(n)]['sha256'],'exact_verified_sha256':sha(run/'verified.json'),'cleanup':True,'output_files':analysis['output_files'],'output_csv_bytes':analysis['output_csv_bytes'],'reported_analysis_diagnostics':analysis.get('diagnostics'),'scope':'Native CLI process startup through complete Run/publication/AnalysisJSON/process exit; fixture generation, hash and independent verification excluded. Cache/background uncontrolled.'};records.append(record);retain({**record,'state':'complete'});print('Complete exact job',index,recipe,cell,seconds,flush=True)
summaries={}
for group,subset in [('pipeline',[r for r in records if r['recipe']=='pipeline'])]:
 med={}
 for candidate in [False,True]:
  values=[r['seconds'] for r in subset if r['candidate']==candidate];med[str(candidate)]={'n':len(values),'median':statistics.median(values),'min':min(values),'max':max(values),'samples':values}
 b=med['False']['median'];c=med['True']['median'];med['median_reduction_fraction']=(b-c)/b;summaries[group]=med
write(p/'records.json',{'type':'validated_compact_fields_complete_run_control','complete_jobs':records,'summaries':summaries,'verification':{'independent_fields_ids_groups_caps':True,'exact_files_output17Analysis_per_recipe':True,'ordered_csv_exact_input':True,'cleanup_all':True},'limits':['Two pipeline observations pervariant in ABBA order; no tails/threshold/universal speed claim.','Ordered owned-field negative control pair one observation pervariant, diagnostic only.','No component scans. Returned Analysis diagnostics precede final publication, not complete Run IO or RSS.','Uncontrolled cache/background; no RSS,physicalIO or device-specific throughput inference.']});print('Bounded panel complete')
