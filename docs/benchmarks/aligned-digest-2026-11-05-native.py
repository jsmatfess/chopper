import pathlib,json,hashlib,subprocess,sys,csv,statistics,os,time,importlib.util
p=pathlib.Path(sys.argv[1])
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
read=lambda f:json.loads(f.read_text())
def write(f,d):f.write_text(json.dumps(d,indent=2)+'\n')
def payload(row,shape):
    ordinary='x'*(24+row%97)
    return f'note-{row},界 {ordinary} says "hi"\r\nnext-{row%7}' if shape=='rich' else f'note-{row}-{ordinary}'
if sys.argv[2]=='fixtures':
    meta=read(p/'fixtures.json');assert set(meta)=={'plain-1000000'}
    for key,item in meta.items():
        f=p/f'input-{key}.csv';assert sha(f)==item['sha256'] and f.stat().st_size==item['bytes']
    print('One exact existing fixture verified; no new generator or old timing reuse');sys.exit(0)
spec=importlib.util.spec_from_file_location('study_cpu',pathlib.Path(__file__).with_name('quoted-serialization-2026-11-05-cpu.py'))
measurement=importlib.util.module_from_spec(spec);spec.loader.exec_module(measurement)
fixtures=read(p/'fixtures.json')
for key,meta in fixtures.items():assert sha(p/f'input-{key}.csv')==meta['sha256']
bins={c:p/(c+'-target')/'release/chopper.exe' for c in ['baseline','candidate']}
assert not (p/'runs').exists();(p/'runs').mkdir()
records=[];reference={}
logical=['algorithm_version','column_values','seed','rows','columns','header','preview','logical_digest','groups','output_files','output_csv_bytes','largest_record_bytes','memory_budget_bytes','workers','stages','warnings','accuracy']
def retain(d):
    with (p/'attempts.jsonl').open('a') as out:out.write(json.dumps(d)+'\n');out.flush();os.fsync(out.fileno())
def verify(output,job,n,analysis,recipe,shape):
    rows=0;seen=bytearray(n);files={}
    outputs=[r for line in (output/'manifest.jsonl').read_text().splitlines() if (r:=json.loads(line)).get('type')=='output']
    assert len(outputs)==analysis['output_files']
    for item in outputs:
        f=output/item['path'];length=f.stat().st_size
        assert length==item['csv_bytes'] and length<=job['limits']['bytes'];count=0
        with f.open(encoding='utf8',newline='') as stream:
            reader=csv.reader(stream,strict=True);assert next(reader)==['id','region','payload']
            for fields in reader:
                assert len(fields)==3
                row=int(fields[0]);assert 0<=row<n and not seen[row];seen[row]=1
                assert fields==[str(row),f'R{row%4}',payload(row,shape)]
                if recipe=='ordered':assert row==rows
                else:assert item['lineage'][0]['values']==[f'R{row%4}'] and item['lineage'][1]['allocation'] in ['treatment','control']
                rows+=1;count+=1
        assert count==item['rows'] and count<=job['limits']['rows'];files[f.name]=sha(f)
    assert rows==n==analysis['rows'] and all(seen)
    assert analysis['groups']==(1 if recipe=='ordered' else 12)
    assert {f.name for f in output.iterdir()}==set(files)|{'manifest.jsonl'}
    assert sum((output/name).stat().st_size for name in files)==analysis['output_csv_bytes']
    if recipe=='ordered':assert len(files)==1 and next(iter(files.values()))==fixtures[f'{shape}-{n}']['sha256']
    return {'files_sha256':files,'output_records':outputs,'logical_analysis':{k:analysis[k] for k in logical}}
schedule=[('ordered','plain',1000000,False),('ordered','plain',1000000,True),('ordered','plain',1000000,True),('ordered','plain',1000000,False),('pipeline','plain',1000000,False),('pipeline','plain',1000000,True)]
for index,(recipe,shape,n,candidate) in enumerate(schedule):
    cell='candidate' if candidate else 'baseline';run=p/'runs'/f'{index}-{recipe}-{shape}-{cell}';run.mkdir();(run/'temp').mkdir();output=run/'output'
    operations=[] if recipe=='ordered' else [{'type':'partition','columns':[1]},{'type':'assign_probabilistic','groups':[{'name':'treatment','percent':'80'},{'name':'control','percent':'20'},{'name':'empty','percent':'0'}],'strata':[]},{'type':'shuffle','strategy':'uniform'}]
    job={'input':str(p/f'input-{shape}-{n}.csv'),'output':str(output),'seed':'strict-csv-serial-v1','operations':operations,'limits':{'rows':1000000,'bytes':134217728},'resources':{'memory_mb':32,'workers':4,'temp_dir':str(run/'temp'),'temp_bytes':1073741824,'max_files':4096,'max_record_bytes':1048576,'grouping':'auto'}}
    write(run/'job.json',job);argv=[str(bins[cell]),'run','--config',str(run/'job.json'),'--yes'];retain({'index':index,'state':'launched','argv':argv,'time_unix':time.time()})
    env=os.environ.copy();env['CHOPPER_MEMORY_LIMIT_MB']='32'
    result,seconds,cpu=measurement.completed_run(argv,env)
    (run/'stdout.log').write_bytes(result.stdout);(run/'stderr.log').write_bytes(result.stderr);write(run/'cpu.json',cpu)
    assert result.returncode==0,result.stderr.decode(errors='replace');assert cpu['ok'] and cpu['total_seconds']>0,cpu
    analysis=json.loads(result.stdout);write(run/'analysis.json',analysis);checked=verify(output,job,n,analysis,recipe,shape)
    key=f'{recipe}-{shape}-{n}'
    if key in reference:assert checked==reference[key]
    else:reference[key]=checked
    write(run/'verified.json',checked)
    assert not any((run/'temp').iterdir()) and not any(f.name.startswith('.chopper-staging-') for f in run.iterdir())
    record={'type':'complete_job','index':index,'recipe':recipe,'shape':shape,'candidate':candidate,'rows':n,'seconds':seconds,'cpu':cpu,'binary_sha256':sha(bins[cell]),'input_sha256':fixtures[f'{shape}-{n}']['sha256'],'exact_verified_sha256':sha(run/'verified.json'),'cleanup':True,'output_files':analysis['output_files'],'output_csv_bytes':analysis['output_csv_bytes'],'reported_analysis_diagnostics':analysis['diagnostics'],'scope':'Native CLI startup through complete Run/publication/AnalysisJSON/process exit; fixture/hash/independent verification and post-exit CPU query excluded. CPU is all child threads, not function attribution.'}
    records.append(record);retain({**record,'state':'complete'});print('Exact complete job',index,recipe,shape,cell,seconds,cpu,flush=True)
summary={}
for field in ['seconds','cpu.total_seconds','cpu.user_seconds']:
    cells={}
    for candidate in [False,True]:
        selected=[r for r in records if r['recipe']=='ordered' and r['shape']=='plain' and r['candidate']==candidate]
        values=[r['seconds'] if field=='seconds' else r['cpu'][field.split('.',1)[1]] for r in selected]
        cells[str(candidate)]={'n':len(values),'samples':values,'median':statistics.median(values),'min':min(values),'max':max(values)}
    cells['median_reduction_fraction']=(cells['False']['median']-cells['True']['median'])/cells['False']['median'];summary[field]=cells
write(p/'records.json',{'type':'aligned_digest_complete_run_control','complete_jobs':records,'summaries':summary,'verification':{'independent_fields_ids_groups_caps':True,'exact_csv_output17Analysis_per_cohort':True,'ordered_csv_exact_input':True,'cleanup_all':True},'limits':['Plain ordered n2/variant ABBA primary; plain pipeline n1/variant separate transfer control.','Uncontrolled warm cache/background, no own Linux builds during timings.','CPU sums all process threads, excludes verification, not function-specific attribution. No RSS/physical IO claim.','Returned Analysis diagnostics precede final publication, not full Run IO.','Six-job/one-experimental-candidate-build cap; no automatic tuning/repeats/expansion.']})
print('Bounded six-job aligned digest panel complete')
