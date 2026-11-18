"""Selected Native UI smoke using the retained controller lifecycle; explicit configuration only."""
import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
SCRIPTS=HERE.parent
ROOT=OUT=PLAN=CONFIG_PATH=CONFIG_SHA=PREPARATION=None
MODULES={}
EXE = Path(r'C:\chopper-focused-639-package-r1\extracted\chopper.exe')
NODE = None  # The verified plan supplies the executable before any launch.
SHA = '42772aa8bb8a76e27fe9d7a0e479b445250e164bdcb4da25fdae88a83536c5d2'
LIMIT = 32 * 1024**3
STOP_BYTES = 24 * 1024**3
FREE_FLOOR = 128 * 1024**3
_CAPTURE_BYTES = 0
_CAPTURE_LOCK = threading.Lock()
RETAINED = [Path('C:/')/name for name in ('desktop105-owned-dialog-control', 'desktop105-owned-dialog-control-r2', 'desktop105-owned-dialog-control-r3', 'desktop105-native-export-control', 'desktop105-picker-inspection', 'desktop105-picker-inspection-r2', 'desktop105-native-export-control-r2', 'desktop105-native-export-control-r4', 'desktop105-native-export-control-r5')]


def bindings_for_inspection(plan):
    global ROOT,OUT,PLAN
    PLAN=plan;ROOT=Path(plan['root']);OUT=ROOT/'attempt1';MODULES.clear()

def document(name):
    from native_smoke import config
    return config.read(PLAN['documents'][name])

def bind(path,digest,preflight):
    global ROOT,OUT,PLAN,CONFIG_PATH,CONFIG_SHA,PREPARATION,EXE,NODE
    sys.path[:0]=[str(HERE),str(SCRIPTS)]
    from native_smoke import config
    assert config.digest(path)==digest, 'reviewed Native UI definition changed'
    PLAN=config.read(path);CONFIG_PATH=str(path);CONFIG_SHA=digest;PREPARATION=preflight
    ROOT=Path(PLAN['root']);OUT=ROOT/'attempt1';EXE=Path(PLAN['exe']['path']);NODE=PLAN['node']['path']
    MODULES.clear()

def load(name):
    if name in MODULES:return MODULES[name]
    import types,importlib
    paths={'browser-small-windows':SCRIPTS/'browser-small-windows.py','validation-runner':SCRIPTS/'validation-runner.py',
           'guard':SCRIPTS/'scale_acceptance/guard.py','reservation':SCRIPTS/'hosted_picker/reservation.py'}
    path=paths.get(name,HERE/(name+'.py'));raw=path.read_bytes()
    expected={row['path']:row['sha256'] for row in PLAN['inputs']}
    assert expected[str(path)]==hashlib.sha256(raw).hexdigest(), 'selected helper source changed: '+str(path)
    if name=='guard':
        m=importlib.import_module('scale_acceptance.guard')
        assert Path(m.__file__).resolve()==path.resolve()
    else:
        m=types.ModuleType('native_smoke_'+name.replace('-','_'));m.__file__=str(path)
        exec(compile(raw,str(path),'exec'),m.__dict__)
    if name=='reservation':m.EXPECTED_LOCK=PLAN['original_lock']
    if name=='suite':
        from hosted_picker import suite as helpers
        helpers.NATIVE_ROOT=str(ROOT);helpers.PLAN=PLAN;helpers.document=document
        m.NATIVE_ROOT=str(ROOT);m.PLAN=PLAN;m.document=document;m.helpers=helpers
        m.CONFIG_SHA=CONFIG_SHA;m.PREPARATION=PREPARATION
    MODULES[name]=m;return m

def verify_sources():
    from native_smoke import config
    if PREPARATION is None:return config.validate(PLAN,fresh=False)
    from scale_acceptance import hosted_qualification
    proof=hosted_qualification.preflight(PREPARATION,CONFIG_PATH,'native-ui')
    config.check(PLAN);return proof

def fresh_custody(disk,reservation):
    """Genuine observations after cold validation, without changing accounting baseline."""
    from native_smoke import config
    start=time.time();suite=load('suite');custody=document('custody.json')
    config.check(PLAN);reservation.check()
    suite.verify_reused_input(Path(suite.REUSED_INPUT),custody['reusedInput'])
    retained=suite.input_inventory(custody,owned_roots());baseline=suite.baseline_completed(ROOT)
    volume=native_volume();disk_value=disk.after(time.monotonic())
    assert disk_value['value']['free_bytes']-suite.FUTURE_BYTES>=FREE_FLOOR
    config.check(PLAN)
    value=dict(schema='native-ui-live-custody-v1',started_unix=start,finished_unix=time.time(),
        configSha256=CONFIG_SHA,preflight=PREPARATION,originalCustodySha256=config.digest(PLAN['documents']['custody.json']),
        observer=load('browser-small-windows').process_identity(os.getpid()),input=custody['reusedInput'],
        retained_inputs=retained,baseline=baseline,volume=volume,disk=disk_value,
        accounting_baseline=dict(sampledOwnedBytes=custody['sampledOwnedBytes'],retainedFixtureBytes=custody['retainedFixtureBytes'],extraRetainedSourceFixtureBytes=custody['extraRetainedSourceFixtureBytes']))
    json_write(OUT/'parent-live-custody.json',value)
    suite.authorize(ROOT,time.time(),observation=value)
    return value


def storage_size(root):
    if root.is_symlink() or getattr(root.lstat(), 'st_file_attributes', 0) & 0x400:
        raise OSError('owned root reparse/alias')
    total = 0
    for base, dirs, files in os.walk(root):
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

def owned_roots():
    extra=document('custody.json')['extraOwnedRoots']
    assert isinstance(extra,list) and len(extra)==len(set(extra))
    roots=[ROOT,*RETAINED,*(Path(p) for p in extra)]
    assert len({str(p.resolve()).casefold() for p in roots})==len(roots)
    for p in roots:
        assert p.is_absolute() and p.parent==Path('C:/') and p.is_dir(), 'owned root missing/nonflat'
    discovered={p.resolve() for p in Path('C:/').iterdir() if p.name.casefold().startswith(('desktop105-','hosted105-','native105-','chopper-native105-'))}
    assert discovered <= {p.resolve() for p in roots}, 'undeclared #105 root'
    return roots


def owned_size():
    return sum(storage_size(path) for path in owned_roots())


def hot_check(now, deadline, failed):
    if failed or now >= deadline-10:
        raise OSError('overall deadline/capture guard')


def disk_sample():
    import shutil
    size = owned_size()
    if OUT.exists():
        transient = sum(storage_size(p) for p in OUT.iterdir() if p.is_dir() and (p.name in ('temp','helper-temp') or p.name.startswith('.chopper-')))
        assert transient < 512*1024**2, 'combined native temp/staging sampled stop'
        if (OUT/'profile').exists():
            assert storage_size(OUT/'profile') < 2*1024**3, 'profile sampled stop'
    if size >= STOP_BYTES:
        raise OSError('owned storage stop threshold')
    free = shutil.disk_usage('C:/').free
    assert free >= FREE_FLOOR, 'physical free-space floor'
    return dict(owned_bytes=size, free_bytes=free)


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

def after_browser_queue_timeout(events, capture, closed, exited):
    """Drain queued terminal stdout before treating process exit as a denial."""
    if not exited:
        return None
    if closed:
        return True
    if capture.eof.get('stdout') is not True:
        return None
    try:
        return events.get_nowait()
    except queue.Empty:
        raise OSError('browser ended before closed event') from None


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


def failure_details(error):
    """Keep the original assertion/API boundary in bounded current-case diagnostics."""
    import traceback
    return dict(type=type(error).__name__,message=str(error)[:8192],
        traceback=''.join(traceback.format_exception(error))[-16384:],
        notes=[str(note)[:2048] for note in getattr(error,'__notes__',())[:8]],
        api=getattr(error,'api',None),pid=getattr(error,'pid',None),winerror=getattr(error,'winerror',None))


def worker(deadline):
    windows, runner, suite = load('browser-small-windows'), load('validation-runner'), load('suite')
    runner.contain_session()
    job = runner._SESSION_JOB
    print(json.dumps({'job': int(job), 'owner': windows.process_identity(os.getpid())}), flush=True)
    if sys.stdin.readline() != 'go\n':
        raise OSError('no parent owned-Job readiness')
    events, failure = queue.Queue(), threading.Event()
    processes, captures = [], []
    report = {'acceptance': False, 'automaticRetry': False, 'cases': []}
    def check():
        assert not failure.is_set() and time.monotonic() < deadline-8, 'worker deadline/capture failure'
    def spawn(argv, name):
        check()
        assert name not in [c.name for c in captures], 'unique child/capture namespace'
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=OUT, creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(p); captures.append(Capture(p, name, events, failure))
        report.setdefault('owned_pids',[]).append(p.pid)
        identity = windows.process_identity(p.pid)
        report.setdefault('process_identities',[]).append(identity)
        assert p.pid in windows.query_job(job)['pids']
        json_write(OUT/(name+'.birth.json'), identity)
        return p, identity
    try:
        completed = {}
        verify_sources()
        from native_smoke import config
        live=config.read(OUT/'parent-live-custody.json',expected_sha256=os.environ.pop('CHOPPER_NATIVE_SMOKE_CUSTODY_SHA'))
        assert live['observer']==windows.process_identity(os.getppid()), 'live custody observer birth mismatch'
        suite.authorize(ROOT,time.time(),observation=live)
        server, _ = spawn([str(EXE), 'serve', '--port', '0'], 'server')
        end = min(deadline-8, time.monotonic()+10); url = None
        while url is None:
            check(); assert time.monotonic() < end, 'server URL deadline'
            try: name, line = events.get(timeout=.05)
            except queue.Empty: continue
            if name != 'server': continue
            if line.startswith('Chopper local UI: '):
                url = line[len('Chopper local UI: '):]
                assert url.startswith('http://127.0.0.1:') and '/#token=' in url
        node, _ = spawn([NODE, str(HERE/'browser.cjs')], 'browser')
        node.stdin.write((json.dumps(dict(url=url, profile=str(OUT/'profile'), cases=suite.cases(ROOT), phase='native-ui-smoke',browserVersion=PLAN['browser_version'],browser=PLAN['browser']['path'],playwrightRoot=PLAN['playwright_root'],nodeVersion=PLAN['toolchains']['node_version']))+'\n').encode()); node.stdin.flush()
        seen = []; closed = False
        while node.poll() is None or not closed:
            check()
            try: name, line = events.get(timeout=.05)
            except queue.Empty:
                pending = after_browser_queue_timeout(events, next(c for c in captures if c.name == 'browser'), closed, node.poll() is not None)
                if pending is True:
                    break
                if pending is None:
                    continue
                name, line = pending
            if name != 'browser': continue
            value = json.loads(line)
            if value['kind'] == 'browser-version': report['chromeVersion'] = value['version']
            elif value['kind'] == 'cancel-race':
                report['cancelRace'] = value
            elif value['kind'] == 'case-result':
                case = suite.cases(ROOT)[len(seen)]
                assert value['case'] == case['name']
                seen.append(value['case']); report['cases'].append(value)
                value['fileObservation'] = suite.observe_case(case, OUT)
                json_write(OUT/'observed-cases.json', report['cases'])
                # File verification occurs even if UI timing missed cancellation; then stop, no retry.
                suite.verify_case(case, value, OUT, completed)
                node.stdin.write((json.dumps({'verified':case['name']})+'\n').encode()); node.stdin.flush()
            elif value['kind'] == 'suite-result':
                assert value['runs'] == 1 and value['cancels'] == 1 and value['picks'] == 0
                assert type(value.get('headerReads')) is int and 0<=value['headerReads']<=2
                if PLAN['case']=='processing-cancel':assert value['headerReads']>=1
                report['counter'] = value
            elif value['kind'] == 'browser-closed': closed = True
            else: raise OSError('unknown browser event')
        assert node.wait(timeout=2) == 0 and seen == [case['name'] for case in suite.cases(ROOT)]
        assert report.get('counter')
        suite.clean(OUT, [OUT/'cancel-output'])
        report['acceptance'] = True
    except BaseException as error:
        report['error']=failure_details(error)
        raise
    finally:
        report['captureNames'] = [c.name for c in captures]
        try:
            report['privateCleanup'] = finish_private(processes, captures,
                lambda: windows.stop_descendants(job, os.getpid(), deadline), deadline)
            report['childExitCodes'] = [p.returncode for p in processes]
            report['finalFileObservation'] = suite.observe_case(suite.cases(ROOT)[0], OUT)
            if report['finalFileObservation']['destinationExists']:
                report['acceptance'] = False
                try:report['retainedCompletedOrPartialFiles'] = suite.diagnose_destination(OUT/'cancel-output')
                except BaseException as diagnostic_error:
                    report['retainedDestinationDiagnosticError'] = failure_details(diagnostic_error)
                    # Diagnostic failure must not skip required helper cleanup.
            require_private_cleanup(report)
            report['browserHelperCleanup'] = suite.clean_browser_helpers(OUT/'helper-temp',report,json.loads((OUT/'helper-temp-birth.json').read_text()))
        except BaseException as error:
            report['acceptance'] = False; report['cleanupError'] = failure_details(error)
            raise
        finally: json_write(OUT/'worker-result.json', report)
    return 0


def record_job_census(windows,outer,inner,worker_pid,report):
    outer_now=windows.query_job(outer)
    inner_now=windows.query_job(inner) if inner is not None else None
    sample=dict(outer=outer_now,workerJob=inner_now,workerPid=worker_pid)
    report['jobCensusLast']=sample
    observed=set(report.get('census_pids',[]))|set(outer_now['pids'])|set(inner_now['pids'] if inner_now else [])
    assert len(observed)<=4096,'current Job PID diagnostic bound'
    report['census_pids']=sorted(observed)
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


def pre_original_failure(error,windows,runner,outer,timer):
    """Retain real no-start diagnostics without claiming an Original descriptor close."""
    value=dict(pid=os.getpid(),profile='native-ui',case=PLAN['case'],configSha256=CONFIG_SHA,
        preflight=PREPARATION,acceptance=False,originalAcquired=False,
        originalReservationClosedAfterQuiescence=False,noWorkerLaunched=True,
        error=failure_details(error))
    try:
        assert windows is not None and runner is not None and outer is not None
        job=windows.query_job(outer);assert job['kill_on_close'] and job['pids']==[os.getpid()]
        identity=windows.process_identity(os.getpid())
        assert not timer.is_alive() and type(identity['created']) is int and identity['created']>0
        value.update(process_identities=[identity],outerFinal=job,innerFinal=None,
            original_lock_identity=PLAN['original_lock']['identity'],released_after_supervision=True,
            setupCleanup=dict(complete=True,worker_launch_attempted=False,capture_created=False,
                preflight_timer_joined=True,disk_started=False,watchdog_started=False,
                owned_job_pids=[os.getpid()],acceptance=False))
    except BaseException as diagnostic:
        value['setupCleanupError']=dict(type=type(diagnostic).__name__,message=str(diagnostic)[:2048],
            api=getattr(diagnostic,'api',None),pid=getattr(diagnostic,'pid',None),winerror=getattr(diagnostic,'winerror',None),
            process_handle_close_uncertain=bool(getattr(diagnostic,'process_handle_close_uncertain',False)))
    try:json_write(OUT/'receipt.json',value)
    except BaseException as diagnostic:error.add_note('no-worker diagnostic write failed: '+repr(diagnostic)[:2048])


def parent(owner, *, setup_failure=False):
    assert os.name == 'nt' and sys.flags.isolated and sys.flags.dont_write_bytecode
    assert not sys.flags.optimize, 'assertions are release gates'
    assert PREPARATION is not None,'matching native-ui preflight required'
    verify_sources()
    load('suite').authorize_history(ROOT,time.time())
    from datetime import datetime
    accounting = document('accounting.json')
    stop = datetime.fromisoformat(accounting['absolute_stop_utc'].replace('Z', '+00:00')).timestamp()
    assert accounting['expired_window_seconds_charged'] >= 17100
    assert accounting['window_start_utc'] != '2026-11-07T16:16:09Z', 'fresh separately reviewed window required'
    assert accounting['historical_absolute_stop_utc'] == '2026-11-07T11:20:53Z' and accounting['historical_window_seconds_charged'] == 5400
    assert time.time()+180 <= stop, 'reviewed renewed issue105 window cannot fit attempt; no reset'
    started = time.monotonic(); deadline = started+180
    # Preflight has no reservation or children; a stalled read may stop this process.
    preflight_stop = min(started+30, deadline-10)
    preflight_timer = threading.Timer(max(0, preflight_stop-time.monotonic()), lambda: os._exit(91))
    preflight_timer.daemon = True
    preflight_timer.start()
    # Exclusive directory creation is the single-attempt sentinel; never delete/retry it.
    setup_created=False;setup_error=None;windows=runner=outer=None
    try:
        OUT.mkdir();setup_created=True
        from native_smoke import config
        config.check(PLAN)
        chrome_version=PLAN['browser_version']
        windows, runner, reservation_module = load('browser-small-windows'), load('validation-runner'), load('reservation')
        runner.contain_session()
        outer = runner._SESSION_JOB
        assert windows.query_job(outer)['pids'] == [os.getpid()]
        assert windows.query_job(outer)['kill_on_close']
        suite = load('suite')
        custody = document('custody.json')
        baseline_before = suite.baseline_completed(ROOT)
        retained_inputs = suite.input_inventory(custody, owned_roots())
        suite.preflight(ROOT,owned_size(),time.time(),require_fresh=False)
        assert hashlib.sha256(EXE.read_bytes()).hexdigest() == SHA
        assert time.monotonic() < preflight_stop and time.time()+10 < stop, 'preflight budget expired; no launch'
    except BaseException as error:
        setup_error=error
        raise
    finally:
        preflight_timer.cancel();preflight_timer.join()
        if setup_error is not None and setup_created:
            pre_original_failure(setup_error,windows,runner,outer,preflight_timer)
    inner = None
    p = None
    launch_attempted = False
    failure = threading.Event()
    events = queue.Queue()
    capture = None
    report = {'acceptance': False, 'limits': {'seconds': 180, 'ownedBytes': LIMIT},
              'launchBudget': {'servers': 1, 'browsers': 1, 'browse': 0, 'uiRuns': 1, 'cancel': 1, 'readHeaders': 2, 'cliRuns': 0, 'automaticRetry': False}}
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
    disk = load('guard').DiskObservation(disk_sample)
    disk_started = False
    reservation = reservation_module.Reservation(windows)
    owner[0] = reservation
    try:
        watch.start(); watch_started = True
        report['reservation'] = reservation.receipt()
        report['process_identities']=[report['reservation']['owner']]
        report['volume'] = native_volume()
        report['windowsVersion'] = list(sys.getwindowsversion())
        report['issueAccounting'] = accounting
        report['baselineCompletedBefore'] = baseline_before
        assert suite.baseline_completed(ROOT) == baseline_before, 'retained export drift after admission'
        retained_inputs = suite.input_inventory(custody, owned_roots())
        json_write(OUT/'retained-input-inventory.json', retained_inputs)
        load('suite').preflight(ROOT,owned_size(),time.time(),require_fresh=False)
        assert hashlib.sha256(EXE.read_bytes()).hexdigest() == SHA
        env = os.environ.copy()
        for key in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME'):
            env.pop(key, None)
        env['TEMP'] = env['TMP'] = str(OUT/'helper-temp')
        (OUT/'temp').mkdir()
        (OUT/'helper-temp').mkdir()
        json_write(OUT/'helper-temp-birth.json',suite.helpers.dir_identity(OUT/'helper-temp'))
        assert not any((OUT/name).exists() for name in ('cancel-output',))
        hot_check(time.monotonic(), deadline, failure.is_set())
        disk_started = True
        marker = time.monotonic()
        disk.start()
        initial_disk = disk.after(marker)
        assert initial_disk['value']['free_bytes']-suite.FUTURE_BYTES >= FREE_FLOOR, 'projected free-space floor'
        report['initialDiskObservation'] = initial_disk
        # Disk admission may consume30s; it cannot renew custody or launch authority.
        report['liveCustody']=fresh_custody(disk,reservation)
        suite.preflight(ROOT,initial_disk['value']['owned_bytes'],time.time(),observation=report['liveCustody'])
        suite.input_inventory(custody, owned_roots())
        assert suite.baseline_completed(ROOT) == baseline_before, 'retained export drift during disk admission'
        hot_check(time.monotonic(), deadline, failure.is_set())
        reservation.check()
        if setup_failure:
            report['infrastructureControl'] = 'forced pre-worker setup failure; no product run'
            raise OSError('controlled pre-worker setup failure')
        env['CHOPPER_NATIVE_SMOKE_PARENT']=str(os.getpid())
        env['CHOPPER_NATIVE_SMOKE_CUSTODY_SHA']=config.digest(OUT/'parent-live-custody.json')
        launch_attempted = True
        p = subprocess.Popen([sys.executable, '-I', '-B', str(HERE/'control.py'), '--worker', CONFIG_PATH, CONFIG_SHA, str(deadline-12), PREPARATION['path'], PREPARATION['sha256']],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=OUT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        birth = windows.process_identity(p.pid)
        report['workerBirth']=birth
        report['process_identities'].append(birth)
        capture = Capture(p, 'worker', events, failure)
        while p.poll() is None:
            reservation.check()
            record_job_census(windows,outer,inner,p.pid,report)
            hot_check(time.monotonic(), deadline, failure.is_set())
            observation = disk.read()
            size = observation['value']['owned_bytes']
            report['latestDiskObservation'] = observation
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
        assert p.returncode == 0
        report['acceptance'] = json.loads((OUT/'worker-result.json').read_text())['acceptance']
    except BaseException as e:
        report['error'] = failure_details(e)
    finally:
        try:
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
                    report['cleanupError']=failure_details(e)
                    report.setdefault('error',report['cleanupError']);report['acceptance'] = False
            end = min(deadline-1, time.monotonic()+5)
            while inner and windows.query_job(inner)['pids'] and time.monotonic() < end:
                time.sleep(.02)
            report['innerFinal'] = windows.query_job(inner) if inner else None
            report['outerFinal'] = windows.query_job(outer)
            report['elapsed'] = time.monotonic()-started
            report['diskSamplerJoined'] = False
            try:
                if disk_started:
                    report['finalDiskObservation'] = disk.after(time.monotonic())
                    report['finalOwnedBytes'] = report['finalDiskObservation']['value']['owned_bytes']
                else:
                    report['finalOwnedBytes'] = owned_size()
            except BaseException as error:
                report['acceptance'] = False
                report['diskError'] = str(error)
            finally:
                try:
                    disk.stop()
                    report['diskSamplerJoined'] = not disk.pending
                except BaseException as error:
                    report['acceptance'] = False
                    report['diskJoinError'] = str(error)
            stopped.set()
            if watch_started:
                watch.join(timeout=1)
            report['watchdogJoined'] = watch_started and not watch.is_alive()
            report['elapsed'] = time.monotonic()-started
            if report['elapsed'] > 180 or report.get('finalOwnedBytes', LIMIT+1) > LIMIT:
                report['acceptance'] = False
                report['error'] = 'final envelope exceeded'
            report['storageCoverage'] = 'all declared disjoint native/hosted/custody/audit roots; disk30s/15s target/45s maxstart/90s oldest-start age;32GiB combined/24GiB stop/8GiB headroom;128GiB free floor; sampled, not filesystem quota'
            report['scope'] = 'one selected public Native UI '+PLAN['case']+'; no full issue105 acceptance'
            try:
                reservation.check()
                if p is not None:
                    suite.verify_reused_input(Path(suite.REUSED_INPUT), custody['reusedInput'])
                    assert suite.baseline_completed(ROOT) == report['baselineCompletedBefore'], 'retained R5 completed export changed'
                assert report['diskSamplerJoined'] and not disk.pending, 'disk sampler pending before release'
                assert report['watchdogJoined'], 'watchdog not joined before release'
                assert not inner or report['innerFinal']['pids'] == []
                assert report['outerFinal']['pids'] == [os.getpid()]
                if p is None:
                    suite.setup_release_gate(launch_attempted=launch_attempted, capture_created=capture is not None, inner=report['innerFinal'], outer=report['outerFinal']['pids'], owner=os.getpid(), watchdog_joined=report['watchdogJoined'], acceptance=report['acceptance'])
                    report['setupCleanup'] = dict(complete=True, worker_launch_attempted=False, capture_created=False, watchdog_joined=True, owned_job_pids=report['outerFinal']['pids'], acceptance=False)
                else:
                    assert report.get('parentPipeEOF') == {'stdout': True, 'stderr': True}, 'parent capture EOF missing'
                    private = json.loads((OUT/'worker-result.json').read_text())
                    require_private_cleanup(private)
                    assert private['privateCleanup']['owner'] == p.pid, 'private cleanup worker mismatch'
                    report['privateCleanup'] = private['privateCleanup']
                    report['privateCaptureNames']=private['captureNames']
                    report['privateChildExitCodes']=private['childExitCodes']
                    report['owned_pids']=private.get('owned_pids',[])
                    report['process_identities'].extend(private.get('process_identities',[]))
                    report['browserHelperCleanup'] = private.get('browserHelperCleanup')
                    if report['acceptance']:
                        assert report['browserHelperCleanup'] and report['browserHelperCleanup']['complete'] is True, 'browser helper cleanup unproved'
                    load('suite').private_release_gate(private, report['parentPipeEOF'], report['innerFinal']['pids'], report['outerFinal']['pids'], p.pid, watch.is_alive())
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
            report['released_after_supervision']=True
            report['original_lock_identity']=report['reservation']['identity']
            report.update(profile='native-ui',case=PLAN['case'],configSha256=CONFIG_SHA,preflight=PREPARATION,scaleAcceptance=False)
            json_write(OUT/'receipt.json', report)
        finally:
            # Even failed reaping must stop future observations without releasing ownership.
            try:
                disk.stop()
            except BaseException as error:
                report['acceptance'] = False
                report['diskJoinError'] = str(error)
            stopped.set()
            if watch_started:
                watch.join(timeout=1)
    return 0 if report['acceptance'] and not report.get('error') else 1

def retain_owner(reservation,error=None):
    # Process exit would close the original descriptor without its cleanup proofs.
    try:
        json_write(OUT/'owner-retained.json', dict(pid=os.getpid(), fd=reservation.fd,
            release=False, reason='post-acquisition failure; original cleanup proofs required',error=None if error is None else dict(type=type(error).__name__,message=str(error)[:2048])))
    except BaseException:
        pass
    while True:
        try:
            time.sleep(1)
        except BaseException:
            pass


def execute_parent(*, setup_failure=False):
    owner = [None]
    try:
        return parent(owner, setup_failure=setup_failure)
    finally:
        if owner[0] is not None:
            try:
                os.fstat(owner[0].fd)
            except BaseException as error:
                import errno
                if not isinstance(error, OSError) or error.errno != errno.EBADF:
                    retain_owner(owner[0],sys.exception())
            else:
                retain_owner(owner[0],sys.exception())


def after_exit_release(value):
    """Failed cases may be audited only after the same positive ownership proofs."""
    assert value['configSha256']==CONFIG_SHA and value['preflight']==PREPARATION
    if value.get('originalAcquired') is False:
        assert value.get('noWorkerLaunched') is True and value.get('acceptance') is False
        assert value['originalReservationClosedAfterQuiescence'] is False
        assert value['released_after_supervision'] is True and not value.get('setupCleanupError')
        assert value['original_lock_identity']==PLAN['original_lock']['identity']
        assert len(value['process_identities'])==1
        identity=value['process_identities'][0];owner=identity['pid']
        assert type(identity['created']) is int and identity['created']>0
        assert value['outerFinal']['kill_on_close'] and value['outerFinal']['pids']==[owner]
        assert value['innerFinal'] is None and not value.get('releaseBlocked')
        assert value['setupCleanup']==dict(complete=True,worker_launch_attempted=False,capture_created=False,
            preflight_timer_joined=True,disk_started=False,watchdog_started=False,owned_job_pids=[owner],acceptance=False)
        assert not any(key in value for key in ('reservation','workerBirth','privateCleanup'))
        from scale_acceptance import hosted_qualification
        return hosted_qualification.current_process_facts([value])
    assert value['originalReservationClosedAfterQuiescence'] and value['released_after_supervision']
    assert value['original_lock_identity']==PLAN['original_lock']['identity']
    owner=value['reservation']['owner']['pid']
    assert not value.get('releaseBlocked') and value['outerFinal']['pids']==[owner]
    assert value['diskSamplerJoined'] and value['watchdogJoined']
    if 'setupCleanup' in value:
        setup=value['setupCleanup']
        assert setup==dict(complete=True,worker_launch_attempted=False,capture_created=False,watchdog_joined=True,owned_job_pids=[owner],acceptance=False)
        assert value['innerFinal'] is None and not value['acceptance']
        assert 'workerBirth' not in value and 'privateCleanup' not in value
    else:
        assert value['innerFinal']['pids']==[] and value['parentPipeEOF']=={'stdout':True,'stderr':True}
        require_private_cleanup(dict(privateCleanup=value['privateCleanup'],captureNames=value['privateCaptureNames'],childExitCodes=value['privateChildExitCodes']))
    from scale_acceptance import hosted_qualification
    facts=hosted_qualification.current_process_facts([value])
    assert facts, 'recorded actual current processes required'
    return facts


def after_exit(receipt_path,receipt_sha,output):
    """Independent current-process/Original observation; never reruns a Native UI case."""
    assert os.name=='nt' and sys.flags.isolated and sys.flags.dont_write_bytecode and not sys.flags.optimize
    from native_smoke import config
    from scale_acceptance import hosted_qualification as qualification
    import importlib.util
    file=SCRIPTS/'acceptance-preflight.py';spec=importlib.util.spec_from_file_location('native_smoke_preparation',file)
    checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
    verify_sources()
    windows=load('browser-small-windows');runner=load('validation-runner');runner.contain_session()
    destination=config.path(output)
    assert destination.parent==ROOT and not destination.exists(), 'fresh independent artifact directory inside selected root required'
    assert Path(receipt_path)==OUT/'receipt.json'
    destination.mkdir()
    budget=checker.Budget(dict(seconds=30,read_bytes=128*1024**2,visits=200000,capture_bytes=65536,storage_bytes=1024**2),destination)
    timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',profile='native-ui',qualification=False,configSha256=CONFIG_SHA,receiptSha256=receipt_sha)
    try:
        budget.install()
        value=config.read(receipt_path,expected_sha256=receipt_sha)
        facts=after_exit_release(value)
        qualification.independent_observation(windows,facts,value,PLAN['original_lock']['path'],budget.started+30,result,budget=budget)
        result.update(status='passed-after-exit',case_qualification_passed=value['acceptance'],generated_input_bytes=0)
    except BaseException as error:
        result['error']=dict(type=type(error).__name__,message=str(error)[:2048]);raise
    finally:
        budget.active=False;timer.cancel();timer.join()
        result.update(usage=budget.usage(),timerJoined=not timer.is_alive())
        assert result['timerJoined']
        json_write(destination/'result.json',result)
    return 0


if __name__ == '__main__':
    sys.path[:0]=[str(HERE),str(SCRIPTS)]
    if len(sys.argv)==7 and sys.argv[1]=='--worker':
        assert os.name=='nt' and sys.flags.isolated and sys.flags.dont_write_bytecode and not sys.flags.optimize
        assert os.environ.pop('CHOPPER_NATIVE_SMOKE_PARENT',None)==str(os.getppid()), 'bound supervisor required'
        bind(sys.argv[2],sys.argv[3],dict(path=sys.argv[5],sha256=sys.argv[6]))
        raise SystemExit(worker(float(sys.argv[4])))
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config');parser.add_argument('--approve-sha256',required=True)
    parser.add_argument('--preflight',required=True);parser.add_argument('--preflight-sha256',required=True)
    parser.add_argument('--after-exit-receipt');parser.add_argument('--receipt-sha256');parser.add_argument('--output')
    args=parser.parse_args();bind(args.config,args.approve_sha256,dict(path=args.preflight,sha256=args.preflight_sha256))
    if args.after_exit_receipt:
        assert args.receipt_sha256 and args.output
        raise SystemExit(after_exit(args.after_exit_receipt,args.receipt_sha256,args.output))
    assert args.receipt_sha256 is None and args.output is None
    raise SystemExit(execute_parent())
