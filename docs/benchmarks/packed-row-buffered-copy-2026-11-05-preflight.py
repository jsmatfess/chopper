import pathlib,sys,json,hashlib,subprocess,platform,os,shutil,datetime
p=pathlib.Path(sys.argv[1]);sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();read=lambda f:json.loads(f.read_text())
proof=read(p/'maintained-baseline-source-proof.json');gate=read(p/'gate-record.json')
lock=read(p/'host-lock-source.json');assert sha(pathlib.Path(lock['native_path']))==lock['sha256'];assert read(p/'native-host-lock.json')['module_sha256']==lock['sha256']
assert (gate['head'],gate['base'])==(proof['candidate'],proof['base'])
for cell in ['baseline','candidate']:
 actual={f.relative_to(p/(cell+'-src')).as_posix():sha(f) for f in (p/(cell+'-src')).rglob('*') if f.is_file()};assert actual==proof['source_sha256'][cell]
for receipt in gate['receipts']:
 path=pathlib.Path(receipt['native_receipt_path']);j=read(path);assert sha(path)==receipt['receipt_sha256'];assert (j['head'],j['base'])==(gate['head'],gate['base']);status=pathlib.Path(receipt['native_status_path']);assert sha(status)==j['status_sha256'];assert read(status)['summary']=={'passed':1,'incomplete':0};assert sha(pathlib.Path(receipt['native_plan_path']))==j['plan_sha256']
for key,fixture in read(p/'fixtures.json').items():assert sha(p/f'input-{key}.csv')==fixture['sha256']
old=p.parent/'reservation-entry-current-main-5de66079-205534';status=read(old/'batch/status.json');assert status['summary']=={'passed':7,'incomplete':0}
step=next(a for a in status['attempts'] if a['id']=='candidate-cli');assert step['status']=='passed' and step['exit_code']==0
files={name.replace('\\','/').split('/',1)[1]:identity['sha256'] for name,identity in step['inputs'].items() if not identity.get('directory')};assert files==proof['source_sha256']['baseline']
for name,identity in step['inputs'].items():
 f=pathlib.Path(identity.get('resolved',old/name))
 if identity.get('directory'):assert f.is_dir()
 else:assert sha(f)==identity['sha256']
artifact=next(iter(step['artifacts'].values()));assert sha(pathlib.Path(artifact['resolved']))==artifact['sha256']
env=hashlib.sha256(json.dumps(dict(os.environ),sort_keys=True).encode()).hexdigest();assert env==step['runtime']['environment_sha256']
oldpre=read(old/'preflight.json')
for tool in oldpre['resolved_tools'].values():assert sha(pathlib.Path(tool['path']))==tool['sha256']
assert subprocess.check_output([oldpre['resolved_tools']['actual_rustc']['path'],'-Vv'],text=True)==oldpre['rustc']
assert sha(pathlib.Path(step['runtime']['executable']))==step['runtime']['executable_sha256']
target=p/'baseline-target/release/chopper.exe';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists();shutil.copy2(pathlib.Path(artifact['resolved']),target);assert sha(target)==artifact['sha256']
assert oldpre['platform']==platform.platform() and oldpre['python']==sys.version
record={**oldpre,'source_sha256':proof['source_sha256'],'head':gate['head'],'base':gate['base'],'environment_sha256':env,'baseline_reuse':{'original_status_sha256':sha(old/'batch/status.json'),'original_build':step,'original_preflight_sha256':sha(old/'preflight.json'),'source335_environment_compilers_binary_rechecked':True},'baseline_binary_sha256':sha(target),'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
record['hardware']=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',"$ErrorActionPreference='Stop';[pscustomobject]@{CPU=(Get-CimInstance Win32_Processor|Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);Memory=(Get-CimInstance Win32_OperatingSystem|Select-Object TotalVisibleMemorySize,FreePhysicalMemory);Volume=(Get-Volume -DriveLetter C|Select-Object FileSystemType,Size,SizeRemaining)}|ConvertTo-Json -Depth 5 -Compress"],text=True))
(p/'preflight.json').write_text(json.dumps(record,indent=2)+'\n');print('Exact original baseline/source335/environment/compiler/binary eligibility and fresh paired gates verified')
