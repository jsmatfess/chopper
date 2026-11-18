"""Bounded private smoke specification and file oracle. Import has no external effects."""
import hashlib,json,os
from pathlib import Path
from datetime import datetime
MIB=1024**2
NATIVE_ROOT=None
PROFILE=None
STOP_BYTES=248*MIB
FUTURE_BYTES=10*MIB # aggregate new growth including continued profile, captures and helper temp
REUSED_INPUT=None
INPUT_BYTES=53
INPUT_SHA256='ecbed63ad30d497bcbaf3ad45ec86b0ab6651215e6d086bf87afe157fb3e610b'

def cancellation_job(job,case):
    """Only the two reviewed public-UI cancellation workloads; no input creation."""
    assert case in ('processing-cancel','export-cancel')
    value=json.loads(json.dumps(job))
    assert value['operations']==[] and value['limits']==dict(rows=None,bytes=40,compressed_bytes=None)
    value['input_csv']['line_ending']=value['output_csv']['line_ending']='lf'
    value['limits']=dict(rows=100 if case=='export-cancel' else None,bytes=262144,compressed_bytes=None)
    # Intervening value partitions retain parent lineage; adjacent uniform
    # shuffles alone are elided. This is real bounded work, not a delay hook.
    value['operations']=[] if case=='export-cancel' else [operation for _ in range(8) for operation in (dict(type='shuffle',strategy='uniform'),dict(type='partition',columns=['v']))]+[dict(type='shuffle',strategy='uniform')]
    value['resources'].update(memory_mb=64,workers=1,temp_bytes=2097152 if case=='export-cancel' else 64*1024**2,
        max_files=1200 if case=='export-cancel' else 4,max_record_bytes=64 if case=='export-cancel' else 1024)
    return value


def processing_observation(value):
    import re
    rows=value.get('rows');phase=value.get('phase')
    if value.get('status')!='RUNNING' or type(rows) is not int or not 0<=rows<=2**53-1 or not isinstance(phase,str):return False
    # Preparation is real work after ingestion; its stage-local counter starts at zero.
    return bool(re.fullmatch(r'Preparing operation ([2-9]|1[0-7]) of 17',phase)) or (rows>0 and phase in ('Reading CSV','Reading and validating CSV','Serializing output'))


def cancellation_click(value,case):
    import math,re
    assert value['case']==case and case in ('processing-cancel','export-cancel')
    capture=value['capture'];assert len(capture['events'])==1
    click=capture['events'][0]
    assert click['trusted'] is True and click['type']=='click' and click['status']=='RUNNING'
    for observed in (value['active'],value['beforeClick'],click):
        assert observed['status']=='RUNNING', 'terminal before actual Cancel does not qualify'
        if case=='export-cancel':
            match=re.fullmatch(r'Saving results \(([0-9]+)/([0-9]+)\)',observed['phase'])
            assert match and 0<int(match[1])<=int(match[2]), 'actual completed-file export progress at click required'
        else:
            assert processing_observation(observed), 'actual processing phase at click required'
    events=[value['active'],capture['installed'],value['beforeClick'],click,capture['taken']]
    if 'terminal' in value:
        assert value['terminal']['status']=='CANCELLED';events.append(value['terminal'])
    stamps=[row['monotonicMs'] for row in events]
    assert all(type(n) in (int,float) and math.isfinite(n) for n in stamps) and stamps==sorted(stamps), 'actual observation/click/terminal ordering'
    return click


def verify_cancelled_output(output,birth,case):
    """Cancelled exports may leave incomplete files or an invalid marker, never a valid committed marker."""
    import stat
    output=Path(output);verify_output(output,birth,empty=False)
    assert case in ('processing-cancel','export-cancel')
    folders=list(output.iterdir());assert len(folders)==(1 if case=='export-cancel' else 0)
    files={};total=0;marker=dict(status='absent')
    for folder in folders:
        import re
        assert re.fullmatch(r'chopper-results-[0-9a-f-]{36}',folder.name)
        identity=dir_identity(folder);names=[]
        for item in folder.iterdir():
            assert len(files)<1202 and dir_identity(folder)==identity
            before=item.lstat()
            assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not item.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400
            assert re.fullmatch(r'(part-[0-9]{8}\.csv|manifest\.jsonl|CHOPPER-COMPLETE\.json)',item.name), 'unknown incomplete export entry'
            if item.name=='CHOPPER-COMPLETE.json':assert before.st_size<=256, 'marker read bound'
            total+=before.st_size;assert total<=2*1024**2
            raw=item.read_bytes();after=item.lstat()
            stamp=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns)
            assert stamp(before)==stamp(after) and len(raw)==before.st_size
            files[item.name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());names.append(item.name)
            if item.name=='CHOPPER-COMPLETE.json':
                marker=dict(status='invalid',**files[item.name])
                try:
                    def unique(pairs):
                        result={}
                        for key,value in pairs:
                            if key in result:raise ValueError('duplicate marker key')
                            result[key]=value
                        return result
                    value=json.loads(raw,object_pairs_hook=unique)
                except (ValueError,UnicodeError):value=None
                valid=isinstance(value,dict) and value.get('complete') is True and type(value.get('files')) is int and value['files']>0 and value.get('engine')=='chopper-browser' and type(value.get('version')) is int and value['version']==1
                assert not valid, 'valid committed marker cannot qualify as incomplete cancellation'
        assert sorted(p.name for p in folder.iterdir())==sorted(names), 'cancelled export membership changed'
        assert dir_identity(folder)==identity
    assert sorted(p.name for p in output.iterdir())==sorted(p.name for p in folders), 'cancelled output membership changed'
    assert dir_identity(output)==birth
    return dict(complete=False,markerAbsent=marker['status']=='absent',marker=marker,incompleteFolders=[p.name for p in folders],files=files,bytes=total)


def verify_reused_input(path,binding):
    return verify_bound_input(path,binding,(REUSED_INPUT,INPUT_BYTES,INPUT_SHA256))

def verify_malformed_input(binding):
    return verify_bound_input(Path(binding['path']),binding,(r'C:\desktop105-native-faults-r1\malformed.csv',63,'9161b910f538d8611ec4e6324f893af7cf35d199cac516c4fe59696e9f1da45e'))

def verify_bound_input(path,binding,expected_binding):
    expected_path,expected_bytes,expected_sha256=expected_binding
    assert (binding['path'],binding['bytes'],binding['sha256'])==expected_binding
    expected=binding['nativeStat']
    assert isinstance(expected,dict) and set(expected)=={'dev','ino','bytes','mtime_ns'}, 'Root must bind exact native input stat'
    path=Path(path)
    import stat
    for q in (path,*path.parents):
        qs=q.lstat()
        assert not q.is_symlink() and not getattr(qs,'st_file_attributes',0)&0x400,'reused input ancestry reparse'
    before=path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
    assert path.is_file() and not path.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400
    identity=lambda s:dict(dev=s.st_dev,ino=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)
    assert identity(before)==expected and before.st_size==expected_bytes, 'reused input stat drift'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==expected_sha256, 'reused input byte drift'
    assert identity(path.lstat())==expected, 'reused input changed while reading'

def validate_history(plan,a):
    """Authoritative complete ledger closure, independent of live custody age."""
    assert a['prior_attempts'] and len({r['native_path'] for r in a['prior_attempts']})==len(a['prior_attempts'])
    assert abs(a['prior_elapsed_seconds']-sum(r['elapsed'] for r in a['prior_attempts']))<1e-8
    assert sum(r['charged_seconds'] for r in a['expired_windows'])==a['expired_window_seconds_charged']
    binding=plan['historical_anchor'];anchor_path=Path(binding['path'])
    assert anchor_path.stat().st_size<=1024**2
    raw=anchor_path.read_bytes();assert hashlib.sha256(raw).hexdigest()==binding['sha256']
    anchor=json.loads(raw);prior=anchor['issueAccounting']
    required=[*prior['prior_attempts'],dict(native_path=binding['path'],sha256=binding['sha256'],elapsed=anchor['elapsed'])]
    by_path={row['native_path']:row for row in a['prior_attempts']}
    assert all(row['native_path'] in by_path and all(by_path[row['native_path']][key]==row[key] for key in ('sha256','elapsed')) for row in required), 'original history/elapsed charges cannot be omitted'
    assert all(row in a['expired_windows'] for row in prior['expired_windows']), 'expired windows cannot be refunded'
    assert a['expired_window_seconds_charged']>=prior['expired_window_seconds_charged']
    declared={e['path']:e['sha256'] for e in plan['inputs']}
    assert all(declared.get(r['native_path'])==r['sha256'] for r in a['prior_attempts']), 'history cannot be omitted or refunded'

def authorize_history(root,now):
    assert PLAN['parent_reviewed'] is True
    a=document('accounting.json')
    start=datetime.fromisoformat(a['window_start_utc'].replace('Z','+00:00')).timestamp()
    stop=datetime.fromisoformat(a['absolute_stop_utc'].replace('Z','+00:00')).timestamp()
    assert start<=now and now+180<=stop and stop-start<=5400, 'explicit unreset window required'
    validate_history(PLAN,a)
    custody=document('custody.json')
    assert custody['extraRetainedSourceFixtureBytes']>=1444
    assert custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes']>=1009704, 'original synthetic/source-fixture charges cannot be refunded'
    assert custody['parentHostSchedulingApproved'] is True and custody['freshNativeCustodyReviewed'] is True
    assert custody['packageOSBrowserHashesReviewed'] is True
    assert isinstance(custody['baselineCompletedManifestSha256'],str) and len(custody['baselineCompletedManifestSha256'])==64
    return custody


def authorize(root,now,*,observation=None,context=None):
    custody=authorize_history(root,now)
    if observation is None:
        assert context is None
        assert 0<=now-datetime.fromisoformat(custody['sampleUtc'].replace('Z','+00:00')).timestamp()<=60, 'fresh custody required'
        return
    import config
    assert context is not None, 'live custody context required'
    assert Path(observation['path']).lstat().st_nlink==1, 'ordinary owned live custody receipt required'
    live=config.read(observation['path'],expected_sha256=observation['sha256'])
    assert Path(observation['path'])==Path(root)/'attempt1'/(context['phase']+'-live-custody.json'), 'owned live custody receipt required'
    assert live['context']==context, 'live custody binding mismatch'
    assert live['schema']=='hosted-picker-live-custody-v1' and context['phase'] in ('parent','worker')
    assert context['config']==CONFIG_BINDING and context['preflight']==PREFLIGHT_BINDING, 'live custody config/preflight mismatch'
    config.read(CONFIG_BINDING['path'],expected_sha256=CONFIG_BINDING['sha256'])
    expected={row['path']:row for row in PLAN['inputs']}
    original=PLAN['documents']['custody.json']
    assert config.read(original,expected_sha256=expected[original]['sha256'])==custody, 'original custody changed'
    assert context['original_custody']==dict(path=original,sha256=expected[original]['sha256']), 'live custody original binding mismatch'
    assert context['observer']['pid']==os.getpid() and context['observer']['created']>0, 'live custody observer mismatch'
    assert live['started_unix']<=live['finished_unix']<=now and 0<=now-live['started_unix']<=60, 'fresh live custody required'
    assert live['accounting_baseline']==dict(sampledOwnedBytes=custody['sampledOwnedBytes'],growthBytes=PLAN['growth_bytes'],retainedFixtureBytes=custody['retainedFixtureBytes'],extraRetainedSourceFixtureBytes=custody['extraRetainedSourceFixtureBytes']), 'live custody cannot reset accounting'
    assert live['input']==custody['reusedInput'] and live['selectedZIP']==custody['selectedZIP'], 'live custody input/package drift'
    assert live['original_lock']==PLAN['original_lock'], 'live custody lock drift'
    assert live['executables']==[expected[PLAN[key]['path']] for key in ('python','node','browser')], 'live custody executable drift'
    runtime=document('uia-binding.json')
    assert live['uia']==[runtime['powershell'],*runtime['assemblies'].values(),*runtime['nativeImages'].values()] and live['windows_version']==runtime['windowsVersion'], 'live custody runtime drift'
    assert live['volume']==custody['capacityObservation']['volume'], 'live custody volume drift'
    inventory=live['retained_inputs']
    assert [row['path'] for row in inventory]==custody['retainedInputPaths'] and sum(row['bytes'] for row in inventory)==custody['retainedFixtureBytes'], 'live retained inventory drift'
    validate_completed(live['baseline_completed'])
    assert live['started_unix']<=live['disk']['started_unix']<=live['disk']['finished_unix']<=live['finished_unix'] and live['disk']['finished_unix']-live['disk']['started_unix']<=30, 'live disk observation outside epoch/bound'
    storage_gate(live['disk']['value']['owned'],custody['sampledOwnedBytes'])
    if PLAN['owned_cap_bytes']==32*1024**3:
        assert min(live['physical_free_bytes'],live['disk']['value']['free'])-PLAN['growth_bytes']>=128*1024**3, 'live physical headroom'



def input_gate(new_bytes,retained):
    assert type(new_bytes) is int and new_bytes>=0
    assert type(retained) is int and retained>=0
    assert new_bytes+retained<=MIB,'combined retained and new synthetic input cap'

def storage_gate(current,baseline=None):
    assert type(current) is int and current>=0
    if baseline is None:baseline=current
    assert type(baseline) is int and 0<=baseline<=current
    assert current-baseline<FUTURE_BYTES,'staging and runtime share the aggregate growth envelope'
    assert baseline+FUTURE_BYTES<STOP_BYTES,'combined projected owned bytes cannot fit sampled stop/headroom'
    return baseline+FUTURE_BYTES

def preflight(root,current,now,**freshness):
    authorize(root,now,**freshness)
    check_inputs_storage(root,current)


def check_inputs_storage(root,current):
    root=Path(root)
    custody=document('custody.json')
    verify_reused_input(Path(REUSED_INPUT),custody['reusedInput'])
    if PLAN['profile']['reuse']:verify_profile(Path(PROFILE),PLAN['profile'])
    assert REUSED_INPUT in custody['retainedInputPaths'], 'reused input must already be debited'
    input_gate(0,custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes'])
    storage_gate(current,custody['sampledOwnedBytes'])
    assert current>=custody['sampledOwnedBytes'],'parent sample/current inventory inconsistent'

def input_inventory(custody,roots,reused_input):
    paths=custody['retainedInputPaths']
    assert paths and len(paths)==len(set(paths))
    assert reused_input in paths, 'retained inventory omits reused input'
    values=[]
    for value in paths:
        p=Path(value)
        assert p.is_absolute() and any(p.is_relative_to(r) for r in roots)
        assert p.is_file() and not p.is_symlink()
        values.append(dict(path=str(p),bytes=p.stat().st_size))
    assert sum(v['bytes'] for v in values)==custody['retainedFixtureBytes']
    assert custody['inputInventoryComplete'] is True
    return values


def _inventory_stamp(value, *, held=False):
    # Python Windows path ctime is creation-time; descriptor ctime is change-time.
    # Keep descriptor change-time in its own before/after stability comparison.
    creation = value.st_ctime_ns
    if held and os.name == 'nt':
        creation = getattr(value, 'st_birthtime_ns', None)
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,creation,
            value.st_nlink,getattr(value,'st_file_attributes',0))


def _inventory_match(path, boundary, before, after, *, held=False):
    fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_file_attributes','st_birthtime_ns')
    def raw(value):return {name:dict(present=hasattr(value,name),value=getattr(value,name,None)) for name in fields}
    matched=_inventory_stamp(before)==_inventory_stamp(after)
    if not matched and held and os.name=='nt':
        matched=_inventory_stamp(before)==_inventory_stamp(after,held=True)
    assert matched, \
        'retained export metadata mismatch: '+json.dumps(dict(path=str(path),boundary=boundary,before=raw(before),after=raw(after)),sort_keys=True)


def inventory(root):
    import stat
    root=Path(root);identity=dir_identity(root);result={}
    for p in root.iterdir():
        assert len(result)<5, 'retained export entry bound'
        before=p.lstat()
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not p.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400
        assert before.st_size<=MIB
        with p.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            _inventory_match(p,'named-to-held-open',before,opened,held=True)
            raw=stream.read(MIB+1)
            held_after=os.fstat(stream.fileno())
            _inventory_match(p,'held-before-to-after',opened,held_after)
            assert len(raw)==before.st_size, 'retained export read size changed: '+str(p)
            _inventory_match(p,'named-to-held-after-read',before,held_after,held=True)
        _inventory_match(p,'named-before-to-after-close',before,p.lstat())
        assert dir_identity(root)==identity, 'retained export directory identity changed during read: '+str(root)
        result[p.name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=before.st_size,dev=before.st_dev,ino=before.st_ino,mtime_ns=before.st_mtime_ns)
    assert sum(row['bytes'] for row in result.values())<MIB
    assert sorted(p.name for p in root.iterdir())==sorted(result) and dir_identity(root)==identity, 'retained export membership changed'
    return result


def private_release_gate(report,parent_eof,inner,outer,owner,watch_alive):
    # Pure mirror used by controller before explicit close. Never substitutes fake receipts for runtime ones.
    c=report.get('privateCleanup',{});names=report.get('captureNames')
    assert c.get('complete') is True and isinstance(names,list) and len(names)==len(set(names))
    assert set(c.get('eof',{}))==set(names) and all(v=={'stdout':True,'stderr':True} for v in c['eof'].values())
    assert c.get('reaped')==len(names)==len(report.get('childExitCodes',[]))
    assert all(type(v) is int for v in report['childExitCodes'])
    assert c.get('owner')==owner and c.get('jobPids')==[owner]
    assert parent_eof=={'stdout':True,'stderr':True} and inner==[] and outer==[os.getpid()] and not watch_alive

def baseline_completed(root, *, expected_manifest=None):
    root=Path(root);dest=Path(r'C:\desktop105-native-export-control-r5\attempt1\export')
    return validate_completed(inventory(dest),expected_manifest=expected_manifest)

def validate_completed(observed, *, expected_manifest=None):
    assert set(observed)=={'part-00000001.csv','part-00000002.csv','manifest.jsonl'}
    header=b'id,text,tag\r\n'
    rows=[b'3,"say ""hi""",\xe6\xbc\xa2\r\n',b'4,"line\nfeed",\xf0\x9f\x99\x82\r\n']
    for i,row in enumerate(rows,1):
        entry=observed[f'part-{i:08d}.csv']
        assert entry['bytes']==33 and entry['sha256']==hashlib.sha256(header+row).hexdigest()
    assert observed['manifest.jsonl']['sha256']==(document('custody.json')['baselineCompletedManifestSha256'] if expected_manifest is None else expected_manifest)
    return observed


def dir_identity(path):
    import stat
    path=Path(path)
    for q in (path,*path.parents):
        s=q.lstat()
        assert stat.S_ISDIR(s.st_mode) and not q.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400,'directory reparse/alias'
    s=path.lstat()
    return dict(dev=s.st_dev,ino=s.st_ino)

def verify_profile(path,binding):
    assert binding['path']==PROFILE and binding['channel']==PLAN['channel']
    assert binding['reuse'] is PLAN['profile']['reuse']
    assert binding['nativeIdentity']==dir_identity(path),'continued profile identity changed/unbound'
    # Mutable profile contents are charged by full owned inventory, never frozen as export evidence.

def cleanup_helper(path,report,expected,*,retain_cache=None):
    # Remove only empty directories. A proven Edge diagnostic log is retained,
    # never unlinked or counted as empty-directory/deletion cleanup.
    import re,stat,time
    import config
    path=Path(path)
    assert path==Path(NATIVE_ROOT)/'attempt1'/'helper-temp','cleanup namespace'
    c=report['privateCleanup'];names=report['captureNames']
    assert c['complete'] is True and c['jobPids']==[c['owner']]
    assert c['reaped']==len(names)==len(report['childExitCodes'])
    assert set(c['eof'])==set(names) and all(v=={'stdout':True,'stderr':True} for v in c['eof'].values())
    assert all(type(v) is int for v in report['childExitCodes'])
    end=time.monotonic()+1;root_id=dir_identity(path);rows=[];retained=[]
    assert root_id==expected,'fresh helper identity changed'
    stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink,getattr(s,'st_file_attributes',0))
    def visit(q,depth):
        assert time.monotonic()<end and depth<=8 and len(rows)+len(retained)<64,'helper cleanup bound'
        identity=dir_identity(q);rows.append(dict(path=str(q),identity=identity))
        for child in q.iterdir():
            if child.is_dir():
                visit(child,depth+1)
                continue
            plan=globals().get('PLAN',{})
            assert child.parent==path and child.name=='cv_debug.log' and plan.get('channel')=='msedge','helper contains unknown file: retain untouched'
            assert names==['browser'] and report['childExitCodes']==[0] and c['owner']==os.getpid()
            assert report.get('browserClosed') is True and report.get('serverStopped') is True and report.get('nodeExit')==0
            node_path=path.parent/'browser.birth.json';node_stat=node_path.lstat()
            assert stat.S_ISREG(node_stat.st_mode) and node_stat.st_nlink==1 and not node_path.is_symlink() and not getattr(node_stat,'st_file_attributes',0)&0x400
            node=config.read(node_path,maximum=4096);browser=report['browserIdentity']
            assert node['parent']==c['owner'] and node['image'].casefold()==plan['node']['path'].casefold()
            assert browser['parent']==node['pid'] and browser['image'].casefold()==plan['browser']['path'].casefold()
            assert report['heldBrowserBirth']==browser['created']>=node['created']>0
            before=child.lstat()
            assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not child.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400,'helper log reparse/alias'
            assert 0<before.st_size<=4096,'helper log byte bound'
            with child.open('rb') as stream:raw=stream.read(4097)
            assert len(raw)==before.st_size
            digest=hashlib.sha256(raw).hexdigest()
            pairs=json.loads(raw,object_pairs_hook=list)
            assert isinstance(pairs,list) and len(pairs)==4 and all(isinstance(pair,tuple) and len(pair)==2 for pair in pairs)
            value=dict(pairs)
            assert set(value)=={'logTime','correlationVector','action','result'}
            assert re.fullmatch(r'[0-9]{4}/[0-9]{6}',value['logTime']) and re.fullmatch(r'[0-9A-F]{32}',value['correlationVector'])
            assert value['action']=='FETCH_UX_CONFIG' and value['result']==''
            assert stamp(child.lstat())==stamp(before),'helper log changed'
            retained.append(dict(path=child,before=before,sha256=digest))
    visit(path,0) # Validate the complete small tree before any removal.
    if retained:
        assert callable(retain_cache),'known helper cache retention primitive required'
        original_rows=rows[:];original_files=retained[:]
        cache=retain_cache(path,expected,report)
        rows.clear();retained.clear();visit(path,0)
        assert {row['path']:row['identity'] for row in rows}=={row['path']:row['identity'] for row in original_rows},'helper cache directory changed'
        signature=lambda values:{str(row['path']):(stamp(row['before']),row['sha256']) for row in values}
        assert signature(retained)==signature(original_files),'helper log changed'
        wanted={(str(Path(row['path']).relative_to(path)),True,0) for row in rows[1:]}
        wanted.update((str(row['path'].relative_to(path)),False,row['before'].st_size) for row in retained)
        assert {(row['path'],row['directory'],row['bytes']) for row in cache['entries']}==wanted,'helper cache membership changed'
        assert time.monotonic()<end and dir_identity(path)==root_id
        cache['knownBrowserLogs']=[dict(path=str(row['path'].relative_to(path)),bytes=row['before'].st_size,sha256=row['sha256']) for row in retained]
        cache['note']='Only the observed bounded Edge FETCH_UX_CONFIG log admitted after owned EOF/reap; retained and charged, no empty/deletion credit.'
        return cache
    for row in reversed(rows[1:]):
        assert time.monotonic()<end and dir_identity(path)==root_id,'helper cleanup identity/deadline'
        q=Path(row['path']);assert dir_identity(q)==row['identity']
        q.rmdir() # Atomic empty-only removal; a newly appearing file causes failure.
    assert dir_identity(path)==root_id and not list(path.iterdir())
    return dict(complete=True,root=str(path),identity=root_id,removed=rows[1:],emptyOnly=True)


def growth_gate(size,baseline):
    assert type(baseline) is int and baseline>=0
    assert size<STOP_BYTES and size-baseline<FUTURE_BYTES,'approved aggregate growth/owned stop'

def node_exit_gate(code,eof,empty,closed,started,now):
    # The pipe reader may enqueue browser-closed after poll observes process exit.
    if eof=={'stdout':True,'stderr':True} and empty:
        assert code==0,'Node failed; retained stderr'
        assert closed is True,'Node exited without close event'
    else:
        assert now-started<3,'Node capture EOF/close drain deadline'


def verify_output(path,expected,empty=True):
    path=Path(path)
    assert path==Path(NATIVE_ROOT)/'attempt1'/'output','fresh output namespace'
    assert dir_identity(path)==expected,'fresh output directory identity changed'
    if empty:assert not list(path.iterdir()),'fresh output destination must remain empty before Run'
    return expected

def committed_snapshot(output,birth,public_path):
    verify_export(output,birth,public_path)
    folder=public_path.split('/')[1];dest=Path(output)/folder
    return dict(name=folder,identity=dir_identity(dest),files=inventory(dest))

def verify_preserved_export(output,birth,preserved,extra=None):
    import re
    assert re.fullmatch(r'chopper-results-[0-9a-f-]{36}',preserved['name'])
    verify_output(output,birth,empty=False)
    expected=[preserved['name']]+([] if extra is None else [extra])
    assert len(set(expected))==len(expected) and sorted(p.name for p in Path(output).iterdir())==sorted(expected), 'unexpected output beside preserved commit'
    dest=Path(output)/preserved['name']
    assert dir_identity(dest)==preserved['identity'] and inventory(dest)==preserved['files'], 'committed hosted export changed'
    return True


def verify_export(output,birth,public_path,*,preserved=None):
    import re
    output=Path(output);verify_output(output,birth,empty=False)
    match=re.fullmatch(r'output/(chopper-results-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})',public_path)
    assert match,'unexpected public result path'
    def entry_names(path,limit):
        names=[]
        for entry in path.iterdir():
            assert len(names)<limit,'export directory entry ceiling'
            names.append(entry.name)
        return names
    folder=match[1]
    expected_folders=[folder]
    if preserved is not None:
        verify_preserved_export(output,birth,preserved,extra=folder);expected_folders.append(preserved['name'])
    assert sorted(entry_names(output,2))==sorted(expected_folders),'unexpected result directory/output residue'
    dest=output/folder;identity=dir_identity(dest)
    names={'part-00000001.csv','part-00000002.csv','manifest.jsonl','CHOPPER-COMPLETE.json'}
    assert set(entry_names(dest,5))==names,'missing/extra export files'
    raw={};total=0
    for name in sorted(names):
        assert dir_identity(dest)==identity and dir_identity(output)==birth,'export ancestry changed'
        p=dest/name;before=p.lstat();assert __import__('stat').S_ISREG(before.st_mode) and before.st_nlink==1 and not p.is_symlink() and not getattr(before,'st_file_attributes',0)&0x400
        assert before.st_size<=65536;total+=before.st_size;assert total<=131072
        raw[name]=p.read_bytes();after=p.lstat()
        stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        assert stamp(before)==stamp(after) and len(raw[name])==before.st_size
    assert raw['CHOPPER-COMPLETE.json']==b'{"complete":true,"files":3,"engine":"chopper-browser","version":1}\n','marker bytes differ from pinned Product639 writer'
    marker=json.loads(raw['CHOPPER-COMPLETE.json']);assert type(marker.get('complete')) is bool and type(marker.get('files')) is int and type(marker.get('version')) is int;assert marker==dict(complete=True,files=3,engine='chopper-browser',version=1) and len(raw['CHOPPER-COMPLETE.json'])<=256,'incomplete browser completion marker'
    expected=[b'id,text,tag\r\n3,"say ""hi""",\xe6\xbc\xa2\r\n',b'id,text,tag\r\n4,"line\nfeed",\xf0\x9f\x99\x82\r\n']
    for n,value in enumerate(expected,1):assert raw[f'part-{n:08d}.csv']==value and len(value)==33 and len(raw[f'part-{n:08d}.csv'])<=40,'wrong or oversized CSV'
    import csv,io
    fields=[]
    for n in (1,2):
        decoded=list(csv.reader(io.StringIO(raw[f'part-{n:08d}.csv'].decode('utf-8'),newline='')))
        assert decoded[0]==['id','text','tag']
        fields.extend(decoded[1:])
    assert fields==[['3','say "hi"','漢'],['4','line\nfeed','🙂']], 'decoded CSV fields/order'
    rows=[json.loads(line) for line in raw['manifest.jsonl'].decode('utf-8').splitlines()];assert len(rows)==3
    job=rows[0];assert job['type']=='job' and job['schema_version']==1 and job['config']['limits']==dict(rows=None,bytes=40,compressed_bytes=None)
    assert job['config']['operations']==[] and job['config']['compression']=='none' and job['config']['seed']=='issue105-6069cef-tiny-v1'
    expected_job=document('job.json')
    for key in ('version','zip_member','input_csv','output_csv','compression','operations','limits','seed'):assert job['config'][key]==expected_job[key],'manifest configuration drift'
    for key,wanted in expected_job['resources'].items():
        if key!='temp_dir':assert job['config']['resources'][key]==wanted,'manifest resource configuration drift'
    analysis=job['analysis'];assert analysis['rows']==2 and analysis['output_files']==2 and analysis['output_csv_bytes']==66 and analysis['header']==['id','text','tag']
    assert analysis['logical_digest']=='bf97e5d6a4e6d5f0c11ce01927bd9af53b05ccfc05a66481a95704f374abe3ad'
    for n,row in enumerate(rows[1:],1):
        assert row['type']=='output' and row['path']==f'part-{n:08d}.csv' and row['rows']==1 and row['csv_bytes']==row['stored_bytes']==33 and row['compressed_target_exceeded'] is False
    assert set(entry_names(dest,5))==names and sorted(entry_names(output,2))==sorted(expected_folders),'export namespace changed while reading'
    assert dir_identity(dest)==identity and dir_identity(output)==birth
    return dict(complete=True,publicPath=public_path,marker=marker,files={n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in raw.items()},rows=2,csvBytes=66,strictCsvCapBytes=40)
