"""Maintained R31 actual-picker controller. Root alone schedules native execution."""
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = OUT = None
NODE = None
PLAN = None
CONFIG_PATH = None
CONFIG_SHA = None
PREPARATION = None
LIMIT = 256 * 1024**2
_CAPTURE_BYTES = 0
_CAPTURE_LOCK = threading.Lock()
MODULES = {}


def document(name):
    return json.loads(Path(PLAN['documents'][name]).read_text())


def bind(config_path, digest, preparation=None):
    global ROOT, OUT, NODE, PLAN, CONFIG_PATH, CONFIG_SHA, PREPARATION, LIMIT
    sys.path.insert(0, str(HERE))
    import config
    assert hashlib.sha256(Path(config_path).read_bytes()).hexdigest() == digest, 'reviewed config changed'
    PLAN = config.read(config_path)
    config.storage_stop(PLAN)
    LIMIT = PLAN['owned_cap_bytes']
    CONFIG_PATH, CONFIG_SHA, PREPARATION = str(config_path), digest, preparation
    ROOT, OUT, NODE = Path(PLAN['root']), Path(PLAN['root']) / 'attempt1', PLAN['node']['path']
    assert PLAN['schema'] == 'chopper-hosted-picker-qualification-v1'


def load(name):
    if name in MODULES:
        return MODULES[name]
    import types
    shared = name in ('browser-small-windows', 'validation-runner')
    path = (HERE.parent if shared else HERE) / (name + '.py')
    raw = path.read_bytes()
    if PLAN is not None:
        entries = [e for e in PLAN['inputs'] if e['path'] == str(path)]
        assert len(entries) == 1 and hashlib.sha256(raw).hexdigest() == entries[0]['sha256'], 'helper source changed'
    m = types.ModuleType(name.replace('-', '_')); m.__file__ = str(path)
    sys.modules[name.replace('-', '_')] = m
    exec(compile(raw, str(path), 'exec'), m.__dict__)
    if PLAN is not None:
        if name == 'suite':
            m.NATIVE_ROOT, m.PROFILE, m.REUSED_INPUT = str(ROOT), PLAN['profile']['path'], PLAN['input']['path']
            m.INPUT_BYTES, m.INPUT_SHA256 = PLAN['input'].get('bytes',53), PLAN['input'].get('sha256',m.INPUT_SHA256)
            m.FUTURE_BYTES, m.document, m.PLAN = PLAN['growth_bytes'], document, PLAN
            m.CONFIG_BINDING, m.PREFLIGHT_BINDING = dict(path=CONFIG_PATH,sha256=CONFIG_SHA), PREPARATION
            import config
            m.STOP_BYTES = config.storage_stop(PLAN)
        elif name == 'selection':
            m.PATH, m.OUTPUT = PLAN['input']['path'], str(OUT / 'output')
        elif name == 'reservation':
            m.EXPECTED_LOCK = PLAN['original_lock']
    MODULES[name] = m
    return m


def storage_size(root):
    if root.is_symlink() or getattr(root.lstat(), 'st_file_attributes', 0) & 0x400:
        raise OSError('owned root reparse/alias')
    total = 0
    def fail(error):
        raise error
    for base, dirs, files in os.walk(root, onerror=fail):
        for name in dirs + files:
            p = Path(base)/name
            try:
                s = p.lstat()
            except FileNotFoundError:
                continue
            if getattr(s, 'st_file_attributes', 0) & 0x400 or p.is_symlink():
                raise OSError('owned storage reparse/alias')
            if p.is_file():
                total += s.st_size
    return total

def owned_roots(root, custody):
    roots = [root, *(Path(p) for p in custody['ownedRoots'])]
    assert len({str(p.resolve()).casefold() for p in roots}) == len(roots)
    for p in roots:
        assert p.is_absolute() and p.parent == Path('C:/') and p.is_dir(), 'owned root missing/nonflat'
    discovered = {p.resolve() for p in Path('C:/').iterdir() if p.name.casefold().startswith(
        ('desktop105-', 'hosted105-', 'native105-', 'chopper-native105-'))}
    assert discovered <= {p.resolve() for p in roots}, 'undeclared #105 root'
    return roots


def owned_size():
    return sum(storage_size(path) for path in owned_roots(ROOT, document('custody.json')))


def disk_snapshot():
    transient = profile = 0
    if OUT.exists():
        transient = sum(storage_size(p) for p in OUT.iterdir() if p.is_dir() and (p.name in ('temp','helper-temp') or p.name.startswith('.chopper-')))
        if Path(load('suite').PROFILE).exists():
            profile = storage_size(Path(load('suite').PROFILE))
    return dict(owned=owned_size(), transient=transient, profile=profile,
                free=shutil.disk_usage('C:/').free)


def disk_observer():
    from scale_acceptance.guard import DiskObservation
    return DiskObservation(disk_snapshot)


def disk_guard(values):
    import config
    limits = config.storage_limits(PLAN)
    assert values['transient'] < limits['temp'], 'combined native temp/staging sampled stop'
    assert values['profile'] < limits['profile'], 'continued profile sampled stop'
    if LIMIT == 32*1024**3:
        assert values['free'] >= 128*1024**3, 'physical C: free capacity floor'
    custody=document('custody.json')
    load('suite').growth_gate(values['owned'],custody['sampledOwnedBytes'])
    if values['owned'] >= limits['stop']:
        raise OSError('owned storage stop threshold')


def guard_check(now, deadline, size, failed, disk=None):
    if failed or now >= deadline-10:
        raise OSError('overall deadline/capture guard')
    values = dict(disk_snapshot() if disk is None else disk, owned=size)
    disk_guard(values)


def json_write(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')

def native_volume():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetVolumeInformationW.argtypes = [W.LPCWSTR, W.LPWSTR, W.DWORD, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD), W.LPWSTR, W.DWORD]
    k.GetVolumeInformationW.restype = W.BOOL
    serial, maximum, flags = W.DWORD(), W.DWORD(), W.DWORD()
    label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    assert k.GetVolumeInformationW('C:\\', label, 261, ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags), fs, 261)
    assert fs.value == 'NTFS', 'ordinary C: NTFS destination required'
    return dict(root='C:\\', filesystem=fs.value, serial=serial.value)

def native_session(pid):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.ProcessIdToSessionId.argtypes = [W.DWORD, ctypes.POINTER(W.DWORD)]
    k.ProcessIdToSessionId.restype = W.BOOL
    session = W.DWORD()
    if not k.ProcessIdToSessionId(pid, ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    return session.value

def verify_sources():
    import config
    if PREPARATION is None:
        return config.validate(PLAN, fresh=False)
    sys.path.insert(0, str(HERE.parent))  # Trusted selected scripts root, including under -I.
    from scale_acceptance.hosted_qualification import preflight
    # The same exact actual-host parent/worker preflight body-hash proof admits
    # both processes; every use refreshes the complete metadata/membership set.
    checked = preflight(PREPARATION, CONFIG_PATH, 'actual-picker')
    config.check(PLAN)
    return checked


def verify_custody():
    binding=load('assets') # Verify exact archive/asset code before use.
    spec=document('package-binding.json')
    candidate={k:spec[k] for k in ('source_commit','source_tree','runtime_build_commit')}
    custody=document('custody.json')
    row=load('integration').require_custody(custody,spec['package'],candidate)
    assert native_volume()['filesystem']=='NTFS'
    binding.read_package(row['path'],spec)
    load('uia').runtime(document('uia-binding.json'))
    return custody


class Capture:
    """Concurrent complete pipe drains, capped before writing; EOF is explicit."""
    def __init__(self, p, name, events, failure):
        self.threads = []
        self.name = name
        self.eof = {}
        for key in ('stdout', 'stderr'):
            def drain(key=key):
                global _CAPTURE_BYTES
                count = 0
                try:
                    with getattr(p, key) as stream, (OUT/(name+'.'+key+'.log')).open('xb') as sink:
                        while line := stream.readline(65537):
                            count += len(line)
                            with _CAPTURE_LOCK:
                                _CAPTURE_BYTES += len(line)
                                if _CAPTURE_BYTES > 512*1024:
                                    failure.set(); raise OSError("aggregate capture cap")
                            if len(line) > 65536 or count > 2*1024**2:
                                failure.set()
                                raise OSError('capture ceiling; full capture cannot continue')
                            sink.write(line); sink.flush()
                            if key == 'stdout':
                                events.put((name, line.decode('utf-8-sig').rstrip()))
                    self.eof[key] = True
                except BaseException as e:
                    self.eof[key] = str(e); failure.set()
            t = threading.Thread(target=drain, daemon=True)
            t.start(); self.threads.append(t)
    def finish(self, deadline=None):
        for t in self.threads:
            t.join(timeout=3 if deadline is None else max(0, min(3, deadline-time.monotonic())))
        if any(t.is_alive() for t in self.threads) or self.eof != {'stdout': True, 'stderr': True}:
            raise OSError('capture EOF not established: '+self.name+' '+str(self.eof))
        return self.eof


def require_private_cleanup(report):
    assert 'liveCustodyDiskStopError' not in report, 'private live custody disk stop failed'
    assert not report.get('liveCustodyDiskStarted') or report.get('liveCustodyDiskStopped') is True, 'private live custody disk not joined'
    cleanup = report.get('privateCleanup', {})
    assert cleanup.get('complete') is True, 'private capture/reap completion not established'
    names = report.get('captureNames')
    assert isinstance(names, list) and len(names) == len(set(names)), 'private capture namespace missing/duplicate'
    assert set(cleanup.get('eof', {})) == set(names), 'private capture EOF namespace incomplete'
    assert all(value == {'stdout': True, 'stderr': True} for value in cleanup['eof'].values()), 'private pipe EOF missing'
    assert cleanup.get('reaped') == len(names) == len(report.get('childExitCodes', [])), 'private children not reaped'
    assert all(type(code) is int for code in report['childExitCodes']), 'child exit not established'
    assert cleanup.get('jobPids') == [cleanup.get('owner')] and type(cleanup.get('owner')) is int, 'private descendants remain'


def finish_private(processes, captures, stop_descendants, deadline):
    # Descendants may inherit private pipe writers even after their immediate parent exits.
    job_pids = stop_descendants()
    for p in reversed(processes):
        p.wait(timeout=max(0, min(3, deadline-time.monotonic())))
        if p.stdin and not p.stdin.closed:
            p.stdin.close()
    eof = {}
    errors = []
    for capture in captures:
        try:
            eof[capture.name] = capture.finish(deadline)
        except OSError as error:
            errors.append(str(error))
    return dict(complete=not errors, eof=eof, errors=errors,
                reaped=len(processes), owner=os.getpid(), jobPids=job_pids)


def worker_inputs():
    custody=verify_custody()
    package=load('assets').read_package(custody['selectedZIP']['path'],document('package-binding.json'))
    ports=load('integration').retained_ports([p for p in owned_roots(ROOT,custody) if p!=ROOT])
    return custody,package,ports


def live_custody(phase,baseline,disk):
    """Reobserve launch custody; the frozen plan still owns accounting/history."""
    import config
    windows,suite=load('browser-small-windows'),load('suite')
    started=time.time();marker=time.monotonic()
    observer=windows.process_identity(os.getpid())
    assert observer['image'].casefold()==PLAN['python']['path'].casefold(), 'live observer image mismatch'
    custody=verify_custody()
    suite.verify_reused_input(Path(PLAN['input']['path']),custody['reusedInput'])
    retained=suite.input_inventory(custody,owned_roots(ROOT,custody),PLAN['input']['path'])
    assert suite.baseline_completed(ROOT)==baseline, 'retained completed export drift during live custody'
    declared={row['path']:row for row in PLAN['inputs']}
    executables=[]
    for key in ('python','node','browser'):
        row=declared[PLAN[key]['path']];before=config.stamp(row['path'])
        assert before==row['stat'], 'live executable metadata drift'
        with Path(row['path']).open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256'], 'live executable hash drift'
        assert config.stamp(row['path'])==before, 'live executable changed during read'
        executables.append(dict(row))
    lock=config.path(PLAN['original_lock']['path']).stat()
    assert [lock.st_dev,lock.st_ino]==PLAN['original_lock']['identity'], 'live original lock drift'
    runtime=document('uia-binding.json');volume=native_volume()
    assert list(sys.getwindowsversion())==runtime['windowsVersion'] and volume==custody['capacityObservation']['volume'], 'live host/volume drift'
    free=config.physical_capacity(PLAN)
    observed=disk.after(marker) # A new complete owned/capacity census, not its old publication time.
    config.check(PLAN) # Deny source/input or membership drift during the real observation.
    context=dict(phase=phase,config=dict(path=CONFIG_PATH,sha256=CONFIG_SHA),preflight=PREPARATION,
        original_custody=dict(path=PLAN['documents']['custody.json'],sha256=declared[PLAN['documents']['custody.json']]['sha256']),observer=observer)
    value=dict(schema='hosted-picker-live-custody-v1',context=context,started_unix=started,finished_unix=time.time(),
        accounting_baseline=dict(sampledOwnedBytes=custody['sampledOwnedBytes'],growthBytes=PLAN['growth_bytes'],retainedFixtureBytes=custody['retainedFixtureBytes'],extraRetainedSourceFixtureBytes=custody['extraRetainedSourceFixtureBytes']),
        input=custody['reusedInput'],selectedZIP=custody['selectedZIP'],retained_inputs=retained,baseline_completed=baseline,
        executables=executables,uia=[runtime['powershell'],*runtime['assemblies'].values(),*runtime['nativeImages'].values()],
        windows_version=list(sys.getwindowsversion()),volume=volume,original_lock=PLAN['original_lock'],physical_free_bytes=free,
        disk=dict(started_unix=started+observed['started']-marker,finished_unix=started+observed['finished']-marker,value=observed['value']))
    assert windows.process_identity(os.getpid())==observer, 'live observer identity changed'
    value['finished_unix']=time.time()
    target=OUT/(phase+'-live-custody.json')
    with target.open('x',encoding='utf-8') as stream:stream.write(json.dumps(value,indent=2)+'\n')
    binding=dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    return binding,context,observed['value']['owned']


def before_browser(disk):
    import config
    config.check(PLAN)
    baseline=load('suite').baseline_completed(ROOT)
    return live_custody('worker',baseline,disk)


def worker(deadline):
    windows,runner=load('browser-small-windows'),load('validation-runner')
    model,assets,integration=load('model'),load('assets'),load('integration')
    runner.contain_session();job=runner._SESSION_JOB
    print(json.dumps({'job':int(job),'owner':windows.process_identity(os.getpid())}),flush=True)
    if sys.stdin.readline()!='go\n':raise OSError('no parent owned-Job readiness')
    events,failure=queue.Queue(),threading.Event()
    processes,captures=[],[]
    report=dict(acceptance=False,selectionEnabled=True,observationComplete=False,retry=PLAN['case']=='malformed-retry',automaticRetry=False,runs=0,selections=0)
    server=None;chrome_handle=None;node=None;chrome_id=None;forest=None;forests=[];live_disk=None
    def check():
        if failure.is_set() or time.monotonic()>=deadline-8:raise OSError('worker deadline/capture failure')
        if server and server.failure is not None:raise OSError('server failure')
    def spawn(argv,name,env=None):
        check()
        p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           cwd=OUT,creationflags=subprocess.CREATE_NO_WINDOW,env=env)
        processes.append(p);captures.append(Capture(p,name,events,failure))
        identity=windows.process_identity(p.pid)
        assert p.pid in windows.query_job(job)['pids']
        json_write(OUT/(name+'.birth.json'),identity)
        return p,identity
    def send(p,value):
        check();p.stdin.write((json.dumps(value)+'\n').encode());p.stdin.flush()
    try:
        custody,package,ports=worker_inputs()
        # Every retained origin was audited before binding a fresh port.
        server=integration.OwnedServer(package,ports,assets.handler)
        report['serverReady']=server.start();json_write(OUT/'server-ready.json',report['serverReady'])
        profile=Path(load('suite').PROFILE);load('suite').verify_profile(profile,PLAN['profile'] if PLAN['profile']['reuse'] else json.loads((OUT/'profile-birth.json').read_text()))
        live_disk=disk_observer();report['liveCustodyDiskStarted']=True;live_disk.start()
        live,context,current=before_browser(live_disk)
        live_disk.stop();report['liveCustodyDiskStopped']=not live_disk.pending
        load('suite').preflight(ROOT,current,time.time(),observation=live,context=context)
        report['liveCustodyBeforeBrowser']=live
        node,node_id=spawn([NODE,str(HERE/'driver.cjs')],'browser')
        send(node,dict(phase='hosted-tiny-qualification',channel=PLAN['channel'],case=PLAN['case'],browser=PLAN['browser']['path'],playwrightRoot=PLAN['playwright_root'],nodeVersion=PLAN['toolchains']['node_version'],parentReviewed=True,
                      layoutReviewComplete=True,freshProfile=not PLAN['profile']['reuse'],continuedIssue105Profile=PLAN['profile']['reuse'],profileChannel=PLAN['channel'],freshOrigin=True,profile=str(profile),url=server.url,
                      expectedVersion=PLAN['browser_version'],malformedName=Path(PLAN['malformed_input']['path']).name if PLAN['case']=='malformed-retry' else None,inputName=Path(PLAN['input']['path']).name,job=document('job.json'),
                      runJob=load('suite').cancellation_job(document('job.json'),PLAN['case']) if PLAN['case'] in ('processing-cancel','export-cancel') else document('job.json')))
        chrome_id=None;observation_value=None;result=False;node_exit_seen=None
        session=native_session(os.getpid())
        seen=set()
        while not report.get('browserClosed') or node.poll() is None:
            check()
            try:name,line=events.get(timeout=.05)
            except queue.Empty:name,line=None,None
            if name=='browser':
                value=json.loads(line);kind=value['kind'];stage=value.get('stage')
                repeated=kind in ('repeat-browse-start','repeat-browse-clicked','repeat-input-selected')
                if repeated:
                    assert PLAN['case']=='malformed-retry' and stage in ('malformed','retry') and report.get('expectedStage')==stage
                    kind=kind.removeprefix('repeat-')
                def event_tag(name):return stage+':'+name if value['kind'].startswith('repeat-') else name
                event_key=event_tag(kind+':'+str(value.get('mode','')))
                assert event_key not in seen, 'duplicate browser event'
                seen.add(event_key);seen.add(kind)
                if kind=='browser-launched':
                    assert value['version']==PLAN['browser_version']
                    assert windows.process_identity(node.pid)==node_id
                    candidates=[]
                    for pid in windows.query_job(job)['pids']:
                        try:i=windows.process_identity(pid)
                        except OSError:continue
                        if i['parent']==node.pid and i['image'].casefold()==model.IMAGES[PLAN['channel']].casefold():candidates.append(i)
                    assert len(candidates)==1, 'unique direct Node-child Chrome root required'
                    chrome_id=candidates[0]
                    model.browser_owner(windows.process_identity(chrome_id['pid']),chrome_id,windows.query_job(job)['pids'],PLAN['channel'],node.pid)
                    assert native_session(chrome_id['pid'])==session
                    k=windows.kernel()
                    chrome_handle=windows.checked(k.OpenProcess(0x100000|0x1000,False,chrome_id['pid']))
                    stamps=[W.FILETIME() for _ in range(4)]
                    k.GetProcessTimes.argtypes=[W.HANDLE]+[ctypes.POINTER(W.FILETIME)]*4
                    windows.checked(k.GetProcessTimes(chrome_handle,*(ctypes.byref(v) for v in stamps)))
                    assert stamps[0].dwHighDateTime<<32|stamps[0].dwLowDateTime==chrome_id['created']
                    assert windows.process_identity(chrome_id['pid'])==chrome_id
                    member=W.BOOL();windows.checked(k.IsProcessInJob(chrome_handle,job,ctypes.byref(member)))
                    assert member.value
                    report['browserIdentity']=chrome_id;report['heldBrowserBirth']=chrome_id['created']
                    send(node,dict(ownedBrowserBound=True))
                elif kind=='capabilities':
                    assert chrome_id and value['origin']==server.url
                    for key in ('secure','isolated','shared','open','directory','locks','storage'):assert value[key] is True
                    report['capabilities']=value
                elif kind=='browse-start':
                    assert chrome_id and 'capabilities' in seen and value['mode'] in ('input','output')
                    if value['mode']=='output':assert report.get('inputSelectedPublicUI') is True
                    assert event_tag('browse-clicked:'+value['mode']) not in seen
                elif kind=='browse-clicked':
                    mode=value['mode']
                    if repeated:assert mode=='input'
                    assert event_tag('browse-start:'+mode) in seen and mode in ('input','output')
                    if mode=='output':assert report.get('inputSelectedPublicUI') is True
                    def held_check():
                        check()
                        assert windows.process_identity(node.pid)==node_id
                        assert windows.kernel().WaitForSingleObject(chrome_handle,0)==258
                        model.browser_owner(windows.process_identity(chrome_id['pid']),chrome_id,windows.query_job(job)['pids'],PLAN['channel'],node.pid)
                        assert windows.held_identity(chrome_handle,chrome_id['pid'])==dict(chrome_id,session=session)
                        member=W.BOOL();windows.checked(windows.kernel().IsProcessInJob(chrome_handle,job,ctypes.byref(member)))
                        assert member.value
                    diagnostic=load('diagnostics')
                    # Publish each allocated forest immediately, including partial capture failures.
                    def retain(value):
                        nonlocal forest
                        forest=value
                        if value is not None:forests.append(value)
                    observation_value=diagnostic.input_tree(windows,job,chrome_id,node_id,session,held_check,
                        diagnostic.NativeWindows(),model.observation,retain,
                        rebind_membership=mode=='input' and not report.get('nativeInputClick'))
                    observation_value['mode']='observe-'+mode
                    observation_value['channel']=PLAN['channel']
                    prefix=stage+'-' if repeated else ''
                    json_write(OUT/(prefix+mode+'-observation.json'),observation_value)
                    report[prefix+mode+'Observation']=observation_value
                    if PLAN['case']=='observe-'+mode:
                        send(node,{mode+'Observed':True})
                    elif mode=='input':
                        selection=load('selection');api=diagnostic.NativeWindows()
                        selected_path=PLAN['malformed_input']['path'] if repeated and stage=='malformed' else PLAN['input']['path']
                        api.message=selection.NativeMessages(api.user,path=selected_path).message
                        def verify_input():
                            if repeated and stage=='malformed':load('suite').verify_malformed_input(PLAN['malformed_input'])
                            else:load('suite').verify_reused_input(Path(load('suite').REUSED_INPUT),custody['reusedInput'])
                        report[prefix+'nativeInputClick']=selection.choose(api,forest,observation_value,
                            document('input-layout.json'),verify_input,held_check,path=selected_path)
                        send(node,dict(selected='input'))
                    else:
                        selection=load('selection');api=diagnostic.NativeWindows()
                        api.message=selection.NativeMessages(api.user).message
                        def verify_output():load('suite').verify_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()))
                        report['nativeOutputClick']=selection.choose_output(api,forest,observation_value,
                            document('output-layout.json'),verify_output,held_check)
                        report['postOutputClickObservation']=load('postclick').observe(windows,job,chrome_id,node_id,session,
                            held_check,api,retain,document('output-layout.json'),
                            publish=lambda value:json_write(OUT/'postclick-window-metadata.json',value))
                        json_write(OUT/'post-output-click-observation.json',report['postOutputClickObservation'])
                        send(node,dict(postClickObserved=True))
                elif kind=='input-selected':
                    prefix=stage+'-' if repeated else ''
                    selected_path=PLAN['malformed_input']['path'] if repeated and stage=='malformed' else PLAN['input']['path']
                    assert report.get(prefix+'nativeInputClick') and value['filename']==Path(selected_path).name
                    assert value['output']==('output' if repeated else '') and value['acceptance'] is False and value['byteConsumptionProven'] is False
                    if repeated and stage=='malformed':load('suite').verify_malformed_input(PLAN['malformed_input'])
                    else:load('suite').verify_reused_input(Path(load('suite').REUSED_INPUT),custody['reusedInput'])
                    report[prefix+'inputSelectedPublicUI']=True;report['selections']+=1
                    report[prefix+'inputSelectedDOM']=value
                    json_write(OUT/(prefix+'input-selected-dom.json'),value)
                    send(node,dict(inputVerified=True))
                elif kind=='post-click-dom':
                    assert report.get('nativeOutputClick') and report.get('postOutputClickObservation')
                    assert value['acceptance'] is False and value['runs']==0 and value['outputConfirmationRequired'] is False
                    report['postClickDOM']=value
                    json_write(OUT/'post-click-dom.json',value)
                    assert report.get('uiaLaunchCount',0)==0,'one UIA helper maximum'
                    def fresh_permission_forest(guard):
                        fresh=load('diagnostics').HeldForest(windows,job,chrome_id,node_id,session,guard)
                        retain(fresh)
                        fresh.capture()
                        return fresh
                    report['uiaObservation']=load('uia').run(document('uia-binding.json'),
                        report['postOutputClickObservation'],forest,chrome_id,session,held_check,spawn,send,events,
                        windows,native_session,job,OUT/'helper-temp',HERE/'uia.ps1',permission=dict(scriptSha256=next(e['sha256'] for e in PLAN['inputs'] if e['path']==str(HERE/'uia.ps1')),observeOnly=PLAN['case']=='observe-permission',freshForest=fresh_permission_forest,origin=server.url,layout=dict(document('permission-layout.json'),channel=PLAN['channel']),
                            verifyOutput=lambda:load('suite').verify_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()))))
                    report['uiaLaunchCount']=int(report['uiaObservation'].get('helperLaunched',False))
                    assert report['uiaLaunchCount']==1 and report['uiaObservation']['actions']==(0 if PLAN['case']=='observe-permission' else 1)
                    json_write(OUT/'uia-observation.json',report['uiaObservation'])
                    send(node,dict(permissionObserved=True) if PLAN['case']=='observe-permission' else dict(permissionInvoked=True))
                elif kind=='ready-to-run':
                    assert report.get('uiaObservation',{}).get('actions')==1 and report.get('inputSelectedPublicUI') is True
                    assert value==dict(kind='ready-to-run',runs=0,output='output',permissionConfirmed=True) and report['runs']==0
                    load('suite').verify_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()))
                    report['outputSelectedPublicUI']=True;report['permissionActions']=1;report['runApproved']=True
                    send(node,dict(runApproved=True))
                elif kind=='run-clicked':
                    assert report.get('runApproved') is True and value==dict(kind='run-clicked',runs=1) and report['runs']==0
                    report['runs']=1
                elif kind=='repeat-ready-to-run':
                    assert PLAN['case']=='malformed-retry' and stage==report['expectedStage'] and stage in ('malformed','retry')
                    assert report.get(stage+'-inputSelectedPublicUI') and report['runs']==(1 if stage=='malformed' else 2)
                    assert value['runs']==report['runs'] and value['output']=='output'
                    load('suite').verify_preserved_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),report['committedBaseline'])
                    report['approvedStage']=stage;send(node,dict(runApproved=True))
                elif kind=='repeat-run-clicked':
                    assert stage==report.get('approvedStage')==report.get('expectedStage')
                    assert report['runs']==(1 if stage=='malformed' else 2) and value['runs']==report['runs']+1
                    report['runs']+=1
                elif kind=='baseline-export-complete':
                    assert PLAN['case']=='malformed-retry' and report['runs']==value['runs']==1 and report['selections']==1
                    assert value['status']=='COMPLETE' and value['acceptance'] is False
                    report['baselineOracle']=load('suite').verify_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),value['output'])
                    report['baselinePublicPath']=value['output']
                    report['committedBaseline']=load('suite').committed_snapshot(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),value['output'])
                    json_write(OUT/'committed-baseline.json',report['committedBaseline'])
                    report['expectedStage']='malformed';send(node,dict(baselineVerified=True))
                elif kind=='malformed-failure-complete':
                    assert PLAN['case']=='malformed-retry' and report.get('expectedStage')=='malformed' and report['runs']==value['runs']==2 and report['selections']==2
                    assert value['status']=='FAILED' and 'CSV record 4 has 2 fields, expected 3' in value['error'] and 'cleanup failed' not in value['error'].lower()
                    assert value['cleanup']==dict(workspaces=[],locks=[])
                    load('suite').verify_preserved_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),report['committedBaseline'])
                    report['malformedFailure']=value;json_write(OUT/'malformed-failure.json',value)
                    report['expectedStage']='retry';send(node,dict(malformedVerified=True))
                elif kind=='retry-export-complete':
                    assert PLAN['case']=='malformed-retry' and report.get('expectedStage')=='retry' and report['runs']==value['runs']==3 and report['selections']==3
                    assert value['status']=='COMPLETE' and value['acceptance'] is False and report.get('malformedFailure')
                    report['exportOracle']=load('suite').verify_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),value['output'],preserved=report['committedBaseline'])
                    report['publicOutputPath']=value['output'];report['malformedRetryComplete']=True;result=True
                elif kind=='picker-observation-complete':
                    assert PLAN['case'].startswith('observe-') and value['case']==PLAN['case'] and value['runs']==0 and report['runs']==0
                    assert report.get('inputObservation')
                    if PLAN['case']!='observe-input':assert report.get('outputObservation')
                    if PLAN['case']=='observe-permission':assert report.get('uiaObservation',{}).get('actions')==0
                    report['diagnosticComplete']=True;result=True
                elif kind=='controlled-failure-complete':
                    assert PLAN['case']=='failure' and report['runs']==1 and value['status']=='FAILED'
                    assert value['cleanup']==dict(workspaces=[],locks=[])
                    load('suite').verify_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()))
                    report['controlledFailureComplete']=True;report['failureCleanup']=value
                    result=True
                elif kind=='cancel-active-observed':
                    assert PLAN['case'] in ('processing-cancel','export-cancel') and report['runs']==1
                    assert value['case']==PLAN['case'] and value['active']['status']=='RUNNING'
                    report['cancelActiveObserved']=value
                    json_write(OUT/'cancel-active.json',value)
                elif kind=='cancel-click-observed':
                    assert report.get('cancelActiveObserved') and report['runs']==1
                    report['cancelClickObservation']=value
                    json_write(OUT/'cancel-click.json',value)
                    load('suite').cancellation_click(value,PLAN['case'])
                elif kind=='cancellation-complete':
                    assert PLAN['case'] in ('processing-cancel','export-cancel') and report['runs']==1
                    assert report.get('cancelActiveObserved') and value['case']==PLAN['case'] and value['status']=='CANCELLED' and value['cancelClicked'] is True
                    assert value['cleanup']==dict(workspaces=[],locks=[])
                    assert value['active']==report['cancelActiveObserved']['active']
                    assert report.get('cancelClickObservation') and value['capture']==report['cancelClickObservation']['capture']
                    load('suite').cancellation_click(value,PLAN['case'])
                    report['cancelledOutput']=load('suite').verify_cancelled_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),PLAN['case'])
                    report['cancellationComplete']=True;report['cancellation']=value;result=True
                elif kind=='tiny-export-complete':
                    assert PLAN['case']=='success'
                    assert report['runs']==1 and value['runs']==1 and value['status']=='COMPLETE' and value['acceptance'] is False
                    report['exportOracle']=load('suite').verify_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),value['output'])
                    report['tinyExportComplete']=True;report['publicOutputPath']=value['output']
                    result=True
                elif kind=='browser-closed':
                    assert result, 'browser closed before observation result'
                    report['browserClosed']=True
                else:raise OSError('unknown browser event')
            elif name is not None:raise OSError('unknown capture namespace')
            if node.poll() is not None:
                if node_exit_seen is None:node_exit_seen=time.monotonic()
                capture=next(c for c in captures if c.name=='browser')
                load('suite').node_exit_gate(node.returncode,capture.eof,events.empty(),
                    report.get('browserClosed',False),node_exit_seen,time.monotonic())
        report['nodeExit']=node.wait(timeout=1)
        assert result and observation_value and report['browserClosed'] and report['nodeExit']==0
        report['observationComplete']=True
        report['postClickObservationComplete']=bool(report.get('postOutputClickObservation'))
    except BaseException as error:
        report['error']=str(error)
        raise
    finally:
        report['captureNames']=[c.name for c in captures]
        report['uiaLaunchCount']=report['captureNames'].count('uia')
        try:
            if not report['observationComplete'] and node is not None:
                # A failed observation still asks Node to unwind its owned context first.
                # If Node is stuck, exact-Job bounded termination remains the fallback.
                try:
                    if node.poll() is None:
                        node.stdin.write(b'{"stop":true,"failed":true}\n');node.stdin.flush()
                    end=min(deadline-4,time.monotonic()+3)
                    while time.monotonic()<end and (node.poll() is None or not report.get('failureBrowserClosed')):
                        try:name,line=events.get(timeout=.05)
                        except queue.Empty:continue
                        if name=='browser' and json.loads(line).get('kind')=='browser-closed':
                            report['failureBrowserClosed']=True
                except BaseException as error:
                    report['failureContextCloseError']=str(error)
            if live_disk is not None:
                try:
                    live_disk.stop();report['liveCustodyDiskStopped']=not live_disk.pending
                except BaseException as error:
                    report['liveCustodyDiskStopError']=str(error)
            # Server closes before private EOF and before the parent can release its lock.
            try:report['serverStopped']=True if server is None else server.stop()
            finally:
                report['privateCleanup']=finish_private(processes,captures,
                    lambda:windows.stop_descendants(job,os.getpid(),deadline),deadline)
                report['childExitCodes']=[p.returncode for p in processes]
                require_private_cleanup(report)
                if report.get('uiaLaunchCount')==1:
                    report['helperTempCleanup']=load('uia').retain_cache(OUT/'helper-temp',
                        json.loads((OUT/'helper-temp-birth.json').read_text()),report)
                else:
                    report['helperTempCleanup']=load('suite').cleanup_helper(OUT/'helper-temp',report,
                        json.loads((OUT/'helper-temp-birth.json').read_text()),retain_cache=load('uia').retain_cache)
            assert report.get('serverStopped') is True
        except BaseException as error:
            report['observationComplete']=False;report['cleanupError']=str(error);raise
        finally:
            # Keep the real Chrome handle alive through descendant wait and private EOF.
            try:
                if forests:
                    errors=[]
                    for held in forests:
                        try:
                            held.close()
                            if getattr(held,'cleanup_failed',False):raise OSError('Earlier diagnostic close failed')
                        except BaseException as error:errors.append(str(error))
                    if errors:raise OSError('Diagnostic forest cleanup incomplete: '+'; '.join(errors))
            except BaseException as error:
                report['diagnosticHandleCleanupError']=str(error)
                report['observationComplete']=False
                raise
            finally:
                try:
                    if chrome_handle is not None:windows.close(chrome_handle)
                except BaseException as error:
                    report['diagnosticHandleCleanupError']=str(error)
                    report['observationComplete']=False
                    raise
                finally:
                    report['diagnosticForests']=[held.evidence() for held in forests]
                    json_write(OUT/'worker-result.json',report)
    return 0 if report['observationComplete'] else 1


def record_job_census(windows,outer,inner,worker_pid,report):
    outer_now=windows.query_job(outer)
    inner_now=windows.query_job(inner) if inner is not None else None
    sample=dict(outer=outer_now,workerJob=inner_now,workerPid=worker_pid)
    report['jobCensusLast']=sample
    report.setdefault('jobCensusInitial',sample)
    known={os.getpid(),worker_pid}|set(inner_now['pids'] if inner_now else [])
    first=report.setdefault('extraOuterFirstSeen',{})
    for pid in outer_now['pids']:
        if pid in known or str(pid) in first:continue
        assert len(first)<32, 'extra outer PID diagnostic bound exceeded'
        row=dict(pid=pid,monotonic=time.monotonic(),census=sample)
        try:row['identity']=windows.process_identity(pid)
        except OSError as error:row['identityError']=str(error)[:512]
        first[str(pid)]=row
    # Write before a guard can kill the worker; all records remain diagnostic only.
    diagnostic=dict(initial=report['jobCensusInitial'],last=sample,firstSeen=first)
    assert len(json.dumps(diagnostic).encode('utf-8'))<=256*1024, 'Job census diagnostic byte bound exceeded'
    json_write(OUT/'job-census.json',diagnostic)


def parent_admission():
    import config
    # The exact same-host supervised preflight hashed the complete selected
    # inputs. Refresh every identity and namespace; do not hash them twice again
    # while their real custody sample ages. The private worker still validates.
    assert PREPARATION is not None, 'matching actual-host preflight required'
    if 'execution_kind' in PLAN or 'frozen_batch' in PLAN:
        from scale_acceptance.hosted_qualification import batch_admission
        batch_admission(PLAN,'actual-picker',PLAN['channel'])
    verify_sources()
    suite = load('suite')
    suite.authorize_history(ROOT, time.time())
    config.physical_capacity(PLAN)
    OUT.mkdir()  # Permanent exclusive attempt sentinel, before original lock.
    if PLAN['profile']['reuse']:
        suite.verify_profile(Path(PLAN['profile']['path']), PLAN['profile'])
    else:
        assert not config.path(PLAN['profile']['path']).exists(), 'fresh profile already exists'
    baseline = suite.baseline_completed(ROOT)
    custody = document('custody.json')
    retained = suite.input_inventory(custody, owned_roots(ROOT,custody), PLAN['input']['path'])
    json_write(OUT/'retained-input-inventory.json', retained)
    suite.check_inputs_storage(ROOT, owned_size())
    verify_custody()  # Real package/runtime/volume observations, not a restamp.
    return dict(baseline=baseline, custody=custody, retained=retained, volume=native_volume())


def parent_live_checks(admitted):
    import config
    config.check(PLAN)
    suite = load('suite')
    custody = admitted['custody']
    assert suite.input_inventory(custody, owned_roots(ROOT,custody), PLAN['input']['path']) == admitted['retained'], 'retained input inventory changed'
    assert suite.baseline_completed(ROOT) == admitted['baseline'], 'retained completed export changed'
    current = admitted['disk'].read()['value']['owned'] if admitted.get('disk') else owned_size()
    suite.check_inputs_storage(ROOT, current)


def no_worker_release_gate(launch_attempted, process, capture, inner, outer, watch_alive):
    assert launch_attempted is False, 'worker launch attempted without process/cleanup proof'
    assert process is None and capture is None and inner is None, 'unexpected private worker state'
    assert outer['kill_on_close'] and outer['pids'] == [os.getpid()], 'unexpected descendants before worker launch'
    assert not watch_alive, 'watchdog not joined before release'


def parent(owner):
    assert os.name == 'nt' and sys.flags.isolated and sys.flags.dont_write_bytecode
    assert not sys.flags.optimize, 'assertions are release gates'
    sys.path.insert(0, str(HERE.parent))
    accounting = document('accounting.json')
    from datetime import datetime
    stop = datetime.fromisoformat(accounting['absolute_stop_utc'].replace('Z', '+00:00')).timestamp()
    assert time.time()+180 <= stop, 'original window cannot fit attempt; no reset'
    started = time.monotonic(); deadline = started+180
    preflight_stop = min(started+30, deadline-10)
    preflight_timer = threading.Timer(max(0, preflight_stop-time.monotonic()), lambda: os._exit(91))
    preflight_timer.daemon = True
    preflight_timer.start()
    import config
    try:
        admitted = parent_admission()
        custody = admitted['custody']
        windows, runner, reservation_module = load('browser-small-windows'), load('validation-runner'), load('reservation')
    finally:
        preflight_timer.cancel(); preflight_timer.join()
    runner.contain_session()
    outer = runner._SESSION_JOB
    assert windows.query_job(outer)['pids'] == [os.getpid()]
    assert windows.query_job(outer)['kill_on_close']
    inner = None
    p = None
    launch_attempted = False
    failure = threading.Event()
    events = queue.Queue()
    capture = None
    report = {'acceptance': False, 'selectionEnabled': True, 'limits': {'seconds': 180, 'ownedBytes': LIMIT},
              'baselineCompletedBefore': admitted['baseline'],
              'launchBudget': {'servers': 1, 'browsers': 1, 'browse':4 if PLAN['case']=='malformed-retry' else 2, 'uiCancels':1 if PLAN['case'] in ('processing-cancel','export-cancel') else 0, 'uiRuns': 0 if PLAN['case'].startswith('observe-') else 3 if PLAN['case']=='malformed-retry' else 1, 'cancel':1 if PLAN['case'] in ('processing-cancel','export-cancel') else 0, 'cliRuns': 0, 'uiaHelpers': 1, 'automaticRetry': False}}
    stopped = threading.Event()
    def watchdog():
        if not stopped.wait(max(0, deadline-10-time.monotonic())):
            failure.set()
            if inner is not None:
                windows.terminate(inner)
            elif p is not None and p.poll() is None:
                p.kill()
    watch = threading.Thread(target=watchdog, daemon=True)
    watch_started = False
    load('suite').authorize_history(ROOT, time.time())
    assert time.monotonic() < preflight_stop and time.time()+10 < stop, 'preflight budget expired; no launch'
    disk = disk_observer()
    marker = time.monotonic()
    try:
        disk.start()
        observed = disk.after(marker)
        admitted['disk'] = disk
        config.physical_capacity(PLAN)
        load('suite').authorize_history(ROOT, time.time())
        reservation = reservation_module.Reservation(windows)
    except BaseException:
        disk.stop()
        raise
    owner[0] = reservation
    try:
        watch.start(); watch_started = True
        report['reservation'] = reservation.receipt()
        report['volume'] = admitted['volume']
        report['windowsVersion'] = list(sys.getwindowsversion())
        report['issueAccounting'] = accounting
        env = os.environ.copy()
        for key in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        env['CHOPPER_HOSTED_PICKER_WORKER_CONFIG_SHA256']=CONFIG_SHA
        env['CHOPPER_HOSTED_PICKER_SUPERVISOR_PID']=str(os.getpid())
        env['TEMP'] = env['TMP'] = str(OUT/'helper-temp')
        (OUT/'temp').mkdir()
        (OUT/'helper-temp').mkdir()
        (OUT/'output').mkdir()
        json_write(OUT/'output-birth.json',load('suite').dir_identity(OUT/'output'))
        json_write(OUT/'helper-temp-birth.json',load('suite').dir_identity(OUT/'helper-temp'))
        if not PLAN['profile']['reuse']:
            Path(PLAN['profile']['path']).mkdir()
            json_write(OUT/'profile-birth.json', dict(PLAN['profile'], nativeIdentity=load('suite').dir_identity(PLAN['profile']['path'])))
        assert not any((OUT/name).exists() for name in ('export','tiny.csv'))
        observed = disk.read()
        guard_check(time.monotonic(), deadline, observed['value']['owned'], failure.is_set(), observed['value'])
        load('suite').verify_profile(Path(load('suite').PROFILE),PLAN['profile'] if PLAN['profile']['reuse'] else json.loads((OUT/'profile-birth.json').read_text()))
        parent_live_checks(admitted)
        live,context,current=live_custody('parent',admitted['baseline'],disk)
        load('suite').preflight(ROOT,current,time.time(),observation=live,context=context)
        reservation.check()
        report['liveCustodyBeforeWorker']=live
        argv = [sys.executable, '-I', '-B', str(HERE/'control.py'), '--worker', CONFIG_PATH, CONFIG_SHA, str(deadline-12), PREPARATION['path'], PREPARATION['sha256']]
        launch_attempted = True  # A failing Popen may have created an unknown child.
        p = subprocess.Popen(argv,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=OUT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        birth = windows.process_identity(p.pid)
        report['workerBirth']=birth
        capture = Capture(p, 'worker', events, failure)
        while p.poll() is None:
            reservation.check()
            record_job_census(windows,outer,inner,p.pid,report)
            observed = disk.read()
            size = observed['value']['owned']
            # Hot ownership/capture polling continues while a disk call is pending.
            guard_check(time.monotonic(), deadline, size, failure.is_set(), observed['value'])
            report['observedOwnedHighwater'] = max(report.get('observedOwnedHighwater', 0), size)
            try:
                name, line = events.get(timeout=.05)
            except queue.Empty:
                continue
            assert inner is None and name == 'worker', 'one inner Job handshake only'
            value = json.loads(line)
            assert windows.process_identity(p.pid) == birth == value['owner']
            inner = windows.duplicate_job(p.pid, value['job'])
            census = windows.query_job(inner)
            assert census['kill_on_close'] and census['pids'] == [p.pid]
            report['innerInitial'] = census
            p.stdin.write(b'go\n'); p.stdin.flush()
        p.wait(timeout=1)
        assert p.returncode == 0, f'private worker exited {p.returncode}; inspect worker-result.json and worker capture'
        private_result=json.loads((OUT/'worker-result.json').read_text())
        report['observationComplete'] = private_result.get('observationComplete') is True
        report['postClickObservationComplete'] = private_result.get('postClickObservationComplete') is True
        assert report['observationComplete']
        if PLAN['case'] in ('success','failure','observe-permission','processing-cancel','export-cancel','malformed-retry'):
            assert report['postClickObservationComplete']
        if PLAN['case'].startswith('observe-'):
            assert private_result['runs']==0 and private_result.get('diagnosticComplete') is True
            report['diagnosticComplete']=True
        else:
            expected_count=3 if PLAN['case']=='malformed-retry' else 1
            assert private_result['runs']==expected_count and private_result['selections']==expected_count
            report['runs']=private_result['runs'];report['selections']=private_result['selections']
            expected='malformedRetryComplete' if PLAN['case']=='malformed-retry' else 'cancellationComplete' if PLAN['case'] in ('processing-cancel','export-cancel') else 'tinyExportComplete' if PLAN['case']=='success' else 'controlledFailureComplete'
            assert private_result.get(expected) is True
            assert private_result.get('nativeOutputClick',{}).get('clicks')==1
            if PLAN['case']=='success':
                report['exportOracle']=load('suite').verify_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),private_result['publicOutputPath'])
                report['tinyExportComplete']=True
            elif PLAN['case']=='malformed-retry':
                assert private_result.get('malformedFailure')
                report['committedBaseline']=private_result['committedBaseline']
                report['exportOracle']=load('suite').verify_export(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),private_result['publicOutputPath'],preserved=report['committedBaseline'])
                report['malformedRetryComplete']=True;report['malformedFailure']=private_result['malformedFailure']
            elif PLAN['case'] in ('processing-cancel','export-cancel'):
                report['cancelledOutput']=load('suite').verify_cancelled_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()),PLAN['case'])
                report['cancellationComplete']=True;report['cancellation']=private_result['cancellation']
            else:
                load('suite').verify_output(OUT/'output',json.loads((OUT/'output-birth.json').read_text()))
                report['controlledFailureComplete']=True
    except BaseException as e:
        report['error'] = str(e)
    finally:
        try:record_job_census(windows,outer,inner,p.pid if p else None,report)
        except BaseException as error:
            report['acceptance']=False; report['diagnosticError']=str(error)[:512]
        if inner is not None:
            windows.terminate(inner)
        elif p is not None and p.poll() is None:
            p.kill() # Before readiness no product descendants can exist.
        if p is not None:
            p.wait(timeout=3)
            p.stdin.close()
        if capture is not None:
            try:
                report['parentPipeEOF'] = capture.finish(deadline-1)
            except OSError as e:
                report['error'] = str(e); report['acceptance'] = False
        end = min(deadline-1, time.monotonic()+5)
        while inner and windows.query_job(inner)['pids'] and time.monotonic() < end:
            time.sleep(.02)
        stopped.set()
        if watch_started:
            watch.join(timeout=1)
        report['innerFinal'] = windows.query_job(inner) if inner else None
        report['outerFinal'] = windows.query_job(outer)
        # Record the bounded receipt bytes before the final post-write census.
        json_write(OUT/'receipt.json', report)
        try:
            final_disk = disk.after(time.monotonic())
            report['finalOwnedBytes'] = final_disk['value']['owned']
            disk_guard(final_disk['value'])
        except BaseException as error:
            report['finalOwnedBytes'] = LIMIT+1
            report.setdefault('error', 'final disk observation: '+str(error))
        try:
            disk.stop()
        except BaseException as error:
            report['diskStopError'] = str(error)
        report['diskSamplerJoined']=not disk.pending and 'diskStopError' not in report
        report['watchdogJoined']=watch_started and not watch.is_alive()
        report['elapsed'] = time.monotonic()-started
        if report['elapsed'] > 180 or report['finalOwnedBytes'] > LIMIT:
            report['acceptance'] = False
            report.setdefault('error', 'final envelope exceeded')
        report['storageCoverage'] = 'all declared roots; completed disk observation <=30s, start cadence <=45s, oldest-start capacity age <=90s; hot ownership polling 50ms; sampled logical accounting, not a filesystem quota'
        report['scope'] = 'actual input/output pickers; exact selected-channel folder permission; one public Run; selected success or controlled-failure case; no cross-channel/profile or scale acceptance'
        if PLAN['case'].startswith('observe-'):
            report['scope'] = PLAN['case']+' read-only actual layout observation; zero Runs and zero permission invocations; no qualification'
        try:
            reservation.check()
            assert not disk.pending and 'diskStopError' not in report, 'disk observation still owns a pending call'
            assert watch_started and not watch.is_alive(), 'watchdog start/join not established before release'
            assert not inner or report['innerFinal']['pids'] == []
            assert report['outerFinal']['pids'] == [os.getpid()]
            if p is not None:
                load('suite').verify_reused_input(Path(load('suite').REUSED_INPUT), custody['reusedInput'])
                load('suite').verify_profile(Path(load('suite').PROFILE),PLAN['profile'] if PLAN['profile']['reuse'] else json.loads((OUT/'profile-birth.json').read_text()))
                assert load('suite').baseline_completed(ROOT) == report['baselineCompletedBefore'], 'retained R5 completed export changed'
                config.check(PLAN)
                assert hashlib.sha256(Path(CONFIG_PATH).read_bytes()).hexdigest() == CONFIG_SHA, 'config changed during execution'
                assert report.get('parentPipeEOF') == {'stdout': True, 'stderr': True}, 'parent capture EOF missing'
                private = json.loads((OUT/'worker-result.json').read_text())
                require_private_cleanup(private)
                assert private['privateCleanup']['owner'] == p.pid, 'private cleanup worker mismatch'
                report['privateCleanup'] = private['privateCleanup']
                assert 'diagnosticHandleCleanupError' not in private
                assert private.get('serverStopped') is True
                assert private.get('helperTempCleanup',{}).get('complete') is True
                if report.get('observationComplete'):
                    assert private.get('browserClosed') is True and private.get('nodeExit')==0
                load('suite').private_release_gate(private, report['parentPipeEOF'], report['innerFinal']['pids'], report['outerFinal']['pids'], p.pid, watch.is_alive())
            else:
                no_worker_release_gate(launch_attempted, p, capture, inner, report['outerFinal'], watch.is_alive())
                report['noWorkerLaunched'] = True
        except BaseException as error:
            report['acceptance'] = False
            report['releaseBlocked'] = str(error)
            report['originalReservationClosedAfterQuiescence'] = False
            json_write(OUT/'receipt.json', report)
            raise
        if inner:
            windows.close(inner)
        os.close(reservation.fd)
        report['originalReservationClosedAfterQuiescence'] = True
        if p is not None:
            report['browserProfile'] = dict(path=PLAN['profile']['path'], channel=PLAN['channel'],
                nativeIdentity=load('suite').dir_identity(PLAN['profile']['path']))
        report['acceptance']=False
        report['tinyCaseQualified']=bool(PLAN['case'] in ('success','failure') and report.get('tinyExportComplete' if PLAN['case']=='success' else 'controlledFailureComplete') and report.get('observationComplete') and not report.get('error'))
        report['smokeCaseQualified']=bool((PLAN['case']=='malformed-retry' and report.get('malformedRetryComplete') or PLAN['case'] in ('processing-cancel','export-cancel') and report.get('cancellationComplete')) and report.get('observationComplete') and not report.get('error'))
        report.update(profile='actual-picker',channel=PLAN['channel'],case=PLAN['case'],scaleAcceptance=False,configSha256=CONFIG_SHA,preflight=PREPARATION)
        json_write(OUT/'receipt.json', report)
    return 0 if report.get('observationComplete') and not report.get('error') else 1

def retain_owner(reservation):
    # Process exit would close the original descriptor without its cleanup proofs.
    try:
        json_write(OUT/'owner-retained.json', dict(pid=os.getpid(), fd=reservation.fd,
            release=False, reason='post-acquisition failure; original cleanup proofs required'))
    except BaseException:
        pass
    while True:
        try:
            time.sleep(1)
        except BaseException:
            pass


def execute_parent():
    owner = [None]
    try:
        return parent(owner)
    finally:
        if owner[0] is not None:
            try:
                os.fstat(owner[0].fd)
            except BaseException as error:
                import errno
                if not isinstance(error, OSError) or error.errno != errno.EBADF:
                    retain_owner(owner[0])
            else:
                retain_owner(owner[0])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('--approve-sha256', required=True)
    parser.add_argument('--preflight', required=True)
    parser.add_argument('--preflight-sha256', required=True)
    if len(sys.argv) in (5, 7) and sys.argv[1] == '--worker':
        assert os.name == 'nt' and sys.flags.isolated and sys.flags.dont_write_bytecode and not sys.flags.optimize
        assert os.environ.pop('CHOPPER_HOSTED_PICKER_WORKER_CONFIG_SHA256',None)==sys.argv[3], 'supervisor-bound internal worker required'
        assert os.environ.pop('CHOPPER_HOSTED_PICKER_SUPERVISOR_PID',None)==str(os.getppid()), 'original supervisor parent required'
        binding = dict(path=sys.argv[5], sha256=sys.argv[6]) if len(sys.argv) == 7 else None
        bind(sys.argv[2], sys.argv[3], binding); verify_sources()
        raise SystemExit(worker(float(sys.argv[4])))
    args = parser.parse_args()
    bind(args.config, args.approve_sha256, dict(path=args.preflight, sha256=args.preflight_sha256))
    raise SystemExit(execute_parent())
