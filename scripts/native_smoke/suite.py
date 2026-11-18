"""Bounded private smoke specification and file oracle. Import has no external effects."""
import hashlib,json,os,re,stat
from pathlib import Path,PureWindowsPath
from datetime import datetime
MIB=1024**2
NATIVE_ROOT=r'C:\native105-cancel-disk-r1'
FUTURE_BYTES=4*1024**3 # Conservative future growth; sampled, not a quota.
REUSED_INPUT=r'C:\native105-cancel-renewed-r1\cancel.csv'
INPUT_BYTES=220002
INPUT_SHA256='a1ebd4884d59708be9726030be67b918cf449f50b9e652cfb73f75c7d96387a7'
SOURCE='639d1fe97d985b1544df0932321c6a93cca2567b'
BUILD='feb9e099e5e0f22c4da8d0f5ba7269e221c91e9d'

def fixture_bytes():
    # No additional generated input or source copy fits the cumulative input cap.
    return {}

def verify_reused_input(path,binding):
    assert binding['path']==REUSED_INPUT and binding['bytes']==INPUT_BYTES and binding['sha256']==INPUT_SHA256
    expected=binding['nativeStat']
    assert isinstance(expected,dict) and set(expected)=={'dev','ino','bytes','mtime_ns'}, 'Root must bind exact native input stat'
    path=Path(path)
    before=path.lstat()
    assert path.is_file() and not path.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400
    identity=lambda s:dict(dev=s.st_dev,ino=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)
    assert identity(before)==expected and before.st_size==INPUT_BYTES, 'reused input stat drift'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==INPUT_SHA256, 'reused input byte drift'
    assert identity(path.lstat())==expected, 'reused input changed while reading'

def cases(root):
    root=Path(root);cfg=document('job.json')
    case=document('decision.json')['case']
    assert case in ('processing-cancel','export-cancel') and case==PLAN['case']
    assert cfg['resources']['memory_mb']==64 and cfg['resources']['workers']==1
    cfg['input']=REUSED_INPUT;cfg['output']=str(root/'attempt1'/'cancel-output')
    # Partition barriers preserve real stages; adjacent uniform shuffles alone are elided.
    cfg['operations']=([op for _ in range(8) for op in (dict(type='shuffle',strategy='uniform'),dict(type='partition',columns=['v']))]+[dict(type='shuffle',strategy='uniform')]) if case=='processing-cancel' else [dict(type='shuffle',strategy='uniform')]
    cfg['limits']=dict(rows=100 if case=='export-cancel' else None,bytes=262144,compressed_bytes=None)
    cfg['resources']['max_files']=1200 if case=='export-cancel' else 4
    cfg['resources']['temp_bytes']=64*MIB
    if os.name=='nt':validate_job_namespace(cfg)
    return [dict(name=case,job=cfg)]

def validate_job_namespace(cfg):
    root=PureWindowsPath(NATIVE_ROOT)
    assert PureWindowsPath(cfg['input'])==PureWindowsPath(REUSED_INPUT)
    assert PureWindowsPath(cfg['output'])==root/'attempt1'/'cancel-output'
    assert PureWindowsPath(cfg['resources']['temp_dir'])==root/'attempt1'/'temp'

def authorize_history(root,now):
    root=Path(root)
    decision=document('decision.json');assert decision['case'] in ('processing-cancel','export-cancel')
    assert decision['case']==PLAN['case']
    assert decision==dict(case=decision['case'],enabled=True,parentReviewed=True,sourceReviewed=True,phase='native-faults',renewedWindowAuthorized=True),'DISABLED: separate parent review and renewed window required'
    a=document('accounting.json')
    start=datetime.fromisoformat(a['window_start_utc'].replace('Z','+00:00')).timestamp()
    stop=datetime.fromisoformat(a['absolute_stop_utc'].replace('Z','+00:00')).timestamp()
    assert a['expired_window_seconds_charged']>=17100
    assert a['window_start_utc']!='2026-11-07T16:16:09Z'
    assert start<=now and now+180<=stop and stop-start<=5400
    custody=document('custody.json')
    assert isinstance(custody['reusedInput']['nativeStat'],dict), 'Root must bind exact native input stat'
    assert isinstance(custody['chromeVersion'], str) and re.fullmatch(r'\d+\.\d+\.\d+\.\d+', custody['chromeVersion']), 'fresh Chrome version binding required'
    assert custody['parentHostSchedulingApproved'] is True
    assert isinstance(custody['baselineCompletedManifestSha256'],str) and len(custody['baselineCompletedManifestSha256'])==64
    assert custody['retainedFixtureBytes'] is not None and custody['sampleUtc'] is not None
    assert type(custody['extraRetainedSourceFixtureBytes']) is int and custody['extraRetainedSourceFixtureBytes']>=159
    return custody

def authorize(root,now,*,observation=None):
    custody=authorize_history(root,now)
    if observation is None:
        assert 0<=now-datetime.fromisoformat(custody['sampleUtc'].replace('Z','+00:00')).timestamp()<=60
        return
    assert observation['schema']=='native-ui-live-custody-v1' and observation['configSha256']==CONFIG_SHA and observation['preflight']==PREPARATION
    assert observation['started_unix']<=observation['finished_unix']<=now and 0<=now-observation['started_unix']<=60
    assert observation['input']==custody['reusedInput']
    assert observation['accounting_baseline']==dict(sampledOwnedBytes=custody['sampledOwnedBytes'],retainedFixtureBytes=custody['retainedFixtureBytes'],extraRetainedSourceFixtureBytes=custody['extraRetainedSourceFixtureBytes'])
    assert observation['baseline']==baseline_completed(root)
    from native_smoke import config
    assert observation['originalCustodySha256']==config.digest(PLAN['documents']['custody.json'])
    assert observation['retained_inputs']==input_inventory(custody,[Path(p) for p in PLAN['owned_roots']])

def input_gate(new_bytes,retained):
    assert type(new_bytes) is int and new_bytes>=0
    assert type(retained) is int and retained>=0
    assert new_bytes+retained<=MIB,'combined retained and new synthetic input cap'

def storage_gate(current):
    assert type(current) is int and current>=0
    assert current+FUTURE_BYTES<24*1024**3,'combined projected owned bytes cannot fit sampled stop/headroom'
    return current+FUTURE_BYTES

def preflight(root,current,now,*,observation=None,require_fresh=True):
    (authorize(root,now,observation=observation) if require_fresh else authorize_history(root,now));root=Path(root)
    custody=document('custody.json')
    verify_reused_input(Path(REUSED_INPUT),custody['reusedInput'])
    assert REUSED_INPUT in custody['retainedInputPaths'], 'reused input must already be debited'
    input_gate(0,custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes'])
    storage_gate(current)
    assert current>=custody['sampledOwnedBytes'],'parent sample/current inventory inconsistent'

def input_inventory(custody,roots):
    paths=custody['retainedInputPaths']
    assert paths and len(paths)==len(set(paths))
    assert REUSED_INPUT in paths, 'retained inventory omits reused input'
    values=[]
    for value in paths:
        p=Path(value)
        assert p.is_absolute() and any(p.is_relative_to(r) for r in roots)
        assert p.is_file() and not p.is_symlink()
        values.append(dict(path=str(p),bytes=p.stat().st_size))
    assert sum(v['bytes'] for v in values)==custody['retainedFixtureBytes']
    assert custody['inputInventoryComplete'] is True
    return values


def inventory(root):return helpers.inventory(root)


def diagnose_destination(root):
    # A failed case may leave many committed files; this is bounded evidence, not an export oracle.
    root=Path(root);before=helpers.dir_identity(root);entries=[];more=False
    with os.scandir(root) as names:
        for index,entry in enumerate(names):
            if index==8:
                more=True;break
            # Windows DirEntry.stat omits link count/device/file identity.
            value=Path(entry.path).lstat()
            assert stat.S_ISREG(value.st_mode) and value.st_nlink==1 and not getattr(value,'st_file_attributes',0)&0x400
            entries.append(dict(name=entry.name,bytes=value.st_size,dev=value.st_dev,ino=value.st_ino,mtime_ns=value.st_mtime_ns))
    assert helpers.dir_identity(root)==before, 'diagnostic destination identity changed'
    return dict(scope='first-eight-named-metadata-only-not-verified-export',entries=entries,moreEntriesPresent=more,directoryIdentity=before)

def clean(out,destinations,allow_completed=False):
    out=Path(out)
    assert not any(p.name.startswith('.chopper-') for p in out.iterdir()),'native staging remains'
    assert (out/'temp').is_dir() and not list((out/'temp').iterdir()),'owned temp remains'
    if not allow_completed:
        assert all(not Path(d).exists() and not Path(d).is_symlink() for d in destinations),'failed native output must remain absent'

def clean_browser_helpers(root,report,expected):
    return helpers.cleanup_helper(root,report,expected)


def verify_case(case,value,out,completed):
    state=value['state']
    assert value['submitted']==case['job'] and value['runs']==1 and value['cancels']==1 and value['picks']==0
    assert type(value.get('headerReads')) is int and 0<=value['headerReads']<=2
    if case['name']=='processing-cancel':assert value['headerReads']>=1
    active=value.get('activeBeforeCancel',{})
    assert active.get('status')=='running' and active.get('output')==case['job']['output']
    assert active.get('progress',{}).get('rows',0)>0 
    assert (active['progress'].get('phase')=='Writing output') == (case['name']=='export-cancel'), 'actual selected cancellation phase required'
    assert value['activeOrder'] < value['cancelOrder'] < value['terminalOrder']
    click=value['cancelClick']
    assert click['trusted'] is True and value['captureInstalledUnixMs']<=value['preClickUnixMs']<=click['unixMs']<=value['terminalUnixMs']
    assert all(isinstance(click[name],(int,float)) and not isinstance(click[name],bool) and click[name]>=0 for name in ('monotonicMs','eventTimestamp'))
    assert value.get('cancelRequested') is True and value.get('cancelHTTP')==200
    assert state['status']=='cancelled' and isinstance(state.get('error'),str) and 'cancelled' in state['error'].lower() and 'cleanup' not in state['error'].lower()
    # Each preparation event resets rows; finish retains that stage-local progress.
    progress=state.get('progress') or {};rows=progress.get('rows');phase=progress.get('phase')
    assert type(rows) is int and rows>=0, 'cancelled terminal progress rows missing/invalid'
    assert isinstance(phase,str) and phase, 'cancelled terminal phase missing/invalid'
    if case['name']=='export-cancel':assert rows>0, 'completed-file export progress required'
    assert (phase=='Writing output')==(case['name']=='export-cancel'), 'selected phase changed before cancellation completed'
    clean(out,[Path(case['job']['output'])])


def setup_release_gate(*, launch_attempted, capture_created, inner, outer, owner, watchdog_joined, acceptance):
    # No workload can exist before the first Popen attempt; uncertain spawn stays fenced.
    assert launch_attempted is False and capture_created is False and inner is None
    assert outer == [owner] and watchdog_joined is True and acceptance is False


def private_release_gate(report,parent_eof,inner,outer,owner,watch_alive):
    # Pure mirror used by controller before explicit close. Never substitutes fake receipts for runtime ones.
    c=report.get('privateCleanup',{});names=report.get('captureNames')
    assert c.get('complete') is True and isinstance(names,list) and len(names)==len(set(names))
    assert set(c.get('eof',{}))==set(names) and all(v=={'stdout':True,'stderr':True} for v in c['eof'].values())
    assert c.get('reaped')==len(names)==len(report.get('childExitCodes',[]))
    assert all(type(v) is int for v in report['childExitCodes'])
    assert c.get('owner')==owner and c.get('jobPids')==[owner]
    assert parent_eof=={'stdout':True,'stderr':True} and inner==[] and outer==[os.getpid()] and not watch_alive

def observe_case(case,out):
    dest=Path(case['job']['output'])
    return dict(destinationExists=dest.exists(),staging=[p.name for p in Path(out).iterdir() if p.name.startswith('.chopper-')],tempEntries=[p.name for p in (Path(out)/'temp').iterdir()],committedResultMeansUnaccepted=dest.exists())

def baseline_completed(root):return helpers.baseline_completed(root)
