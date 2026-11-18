"""Run the declared experiment cycle under the accepted native local-CI host lock."""
from pathlib import Path
import hashlib,importlib.util,json,os,subprocess,sys,datetime
root=Path.cwd();plan=Path(sys.argv[1]);batch=Path(sys.argv[2]);expected=sys.argv[3];module_file=root/'scripts/local-ci.py';actual=hashlib.sha256(module_file.read_bytes()).hexdigest();assert actual==expected,'Local CI lock implementation changed; review before execution'
spec=importlib.util.spec_from_file_location('chopper_experiment_host_lock',module_file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with module.host_lock():
 record={'pid':os.getpid(),'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'lock_path':str(module.host_lock_path()),'module_sha256':actual,'scope':'Native host CI exclusivity held through the declared experiment cycle; no CI command, check bypass, or extra engine Run.'}
 (plan.parent/'native-host-lock.json').write_text(json.dumps(record,indent=2)+'\n')
 result=subprocess.run([sys.executable,str(root/'scripts/experiment-cycle.py'),'run',str(plan),str(batch)])
 (plan.parent/'native-host-lock-completed.json').write_text(json.dumps({'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'returncode':result.returncode,'lock_release':'Context exit closes descriptor; never remove durable lock file.'},indent=2)+'\n')
raise SystemExit(result.returncode)
