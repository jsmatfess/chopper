#!/usr/bin/env python3
"""Bounded complete-job comparison; verifies outputs outside the timed interval."""
import argparse,csv,hashlib,json,os,platform,resource,statistics,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--pipeline',choices=['reverse','forward','auto'],default='reverse');p.add_argument('--rows',type=int,default=50000);p.add_argument('--shapes',nargs='+',choices=['balanced','skewed','single'],default=['balanced','skewed','single']);a=p.parse_args()
a.work.mkdir(parents=True,exist_ok=True);a.output.parent.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source={str(p):sha(p) for base in ['crates','vendor','ui/public'] for p in sorted(Path(base).rglob('*')) if p.is_file() and 'target' not in p.parts}
source.update({str(p):sha(p) for p in [Path('Cargo.toml'),Path('Cargo.lock'),Path('ui/index.html'),Path('ui/style.css'),Path(__file__)]})
with a.output.open('w') as raw:
 def record(value):raw.write(json.dumps(value,sort_keys=True)+'\n');raw.flush()
 record({'kind':'context','platform':platform.platform(),'kernel':platform.release(),'python':platform.python_version(),'cache':'warm, no cache flush; fixtures on Linux filesystem; not native Windows','features':'default release builds','baseline_binary_sha256':sha(a.baseline),'candidate_binary_sha256':sha(a.candidate),'candidate_sources':source,'timing':'process start through CLI exit, complete job including publication; verification excluded','commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'memory_mb':32,'workers':1,'rows':a.rows,'pipeline':a.pipeline,'payload_bytes':192,'repetitions':3,'warmups':1})
 for shape in a.shapes:
  fixture=a.work/(shape+'.csv')
  with fixture.open('w',newline='') as f:
   w=csv.writer(f,lineterminator='\n');w.writerow(['id','key','payload'])
   for i in range(a.rows):w.writerow([i, i%32 if shape=='balanced' else (0 if shape=='single' or i%100 else i%31+1),'x'*192])
  expected={}
  with fixture.open(newline='') as f:
   for row in list(csv.reader(f))[1:]:expected[row[1]]=expected.get(row[1],0)+1
  record({'kind':'fixture','shape':shape,'sha256':sha(fixture),'bytes':fixture.stat().st_size,'group_counts':expected})
  elapsed={'baseline':[],'candidate':[]}
  for repetition in range(-1,3):
   for variant in (['baseline','candidate'] if repetition%2==0 else ['candidate','baseline']):
    destination=a.work/f'{shape}-{variant}-{repetition}';job={'input':str(fixture.resolve()),'output':str(destination.resolve()),'seed':'policy-removal-experiment','resources':{'memory_mb':32,'workers':1,'max_record_bytes':1048576},'operations':([{'type':'shuffle','strategy':'auto'},{'type':'partition','columns':['key']}] if a.pipeline=='reverse' else [{'type':'partition','columns':['key']},{'type':'shuffle','strategy':'auto'}] if a.pipeline=='forward' else [{'type':'shuffle','strategy':'auto'}]),'limits':{'rows':10000,'bytes':4194304}}
    config=a.work/'job.json';config.write_text(json.dumps(job));usage=resource.getrusage(resource.RUSAGE_CHILDREN);started=time.perf_counter()
    result=subprocess.run([str(getattr(a,variant).resolve()),'run','--config',str(config),'--yes'],capture_output=True,text=True,timeout=120)
    seconds=time.perf_counter()-started;after=resource.getrusage(resource.RUSAGE_CHILDREN);(a.work/f'{shape}-{variant}-{repetition}.stderr').write_text(result.stderr)
    value={'kind':'measurement','shape':shape,'variant':variant,'repetition':repetition,'warmup':repetition<0,'wall_seconds':seconds,'user_seconds':after.ru_utime-usage.ru_utime,'system_seconds':after.ru_stime-usage.ru_stime,'exit_code':result.returncode}
    if result.returncode:record({**value,'error':result.stderr});raise RuntimeError(result.stderr)
    analysis=json.loads(result.stdout);seen=set();counts={}
    for output in destination.glob('*.csv'):
     assert output.stat().st_size<=4194304
     with output.open(newline='') as f:
      reader=csv.reader(f);assert next(reader)==['id','key','payload'];key=None;rows=0
      for row in reader:
       rows+=1;identity=int(row[0]);assert identity not in seen;seen.add(identity);assert row[2]=='x'*192;assert a.pipeline=='auto' or key is None or row[1]==key;key=row[1];counts[key]=counts.get(key,0)+1
      assert rows<=10000
    assert seen==set(range(a.rows));assert counts==expected
    value.update({'verified':True,'input_rows':analysis['rows'],'output_files':analysis['output_files'],'temp_bytes':analysis['temp_bytes'],'peak_temp_bytes':analysis['peak_temp_bytes'],'diagnostics':analysis['diagnostics']});record(value)
    if repetition>=0:elapsed[variant].append(seconds)
    import shutil;shutil.rmtree(destination)
  record({'kind':'summary','shape':shape,'wall_seconds':{variant:{'median':statistics.median(values),'min':min(values),'max':max(values)} for variant,values in elapsed.items()}})
