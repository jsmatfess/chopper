"""Private suspended bootstrap; no worker instruction runs before Job admission."""
import ctypes
from ctypes import wintypes as W
import os
import subprocess
import time


def kernel():
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
        'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
        'ResumeThread': ([W.HANDLE], W.DWORD),
        'PeekNamedPipe': ([W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.c_void_p, ctypes.POINTER(W.DWORD), ctypes.c_void_p], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(dll, name).argtypes = args
        getattr(dll, name).restype = result
    return dll


def create_job(windows):
    dll = kernel()
    handle = windows.checked(dll.CreateJobObjectW(None, None))
    try:
        info = windows.Extended()
        info.basic.flags = 0x2000  # kill on last close, no breakaway
        windows.checked(dll.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)))
        return handle
    except BaseException:
        windows.close(handle)
        raise


class SuspendedWorker:
    def __init__(self, api=None, dll=None, handles=None, stdio=()):
        if api is None:
            import _winapi
            api = _winapi
        self.api, self.dll = api, dll if dll is not None else kernel()
        self.stdio = list(stdio)
        self.handles = handles
        self.creation_started = handles is not None
        self.start_called = handles is not None
        self.resume_attempted = False
        self.controller_ack_attempted = False
        self.controller_entry_deadline = None
        self.controller_job = None
        self.controller_preparation_deadline = None
        self.controller_no_start_closed = None

    @property
    def handle(self):
        return self.handles[0] if self.handles is not None else None

    @property
    def thread(self):
        return self.handles[1] if self.handles is not None else None

    @property
    def pid(self):
        return self.handles[2] if self.handles is not None else None

    def known_process(self):
        if self.handles is None and self.creation_started:
            raise OSError('Windows bootstrap creation ownership unknown')
        return self.handles is not None

    def start(self, command, out, err, env, stdin=None):
        import msvcrt
        if self.start_called:
            raise OSError('Windows bootstrap already attempted')
        self.start_called = True
        try:
            with open(os.devnull, 'rb') as null:
                for stream in (null if stdin is None else stdin, out, err):
                    self.stdio.append(self.api.DuplicateHandle(self.api.GetCurrentProcess(),
                        msvcrt.get_osfhandle(stream.fileno()), self.api.GetCurrentProcess(),
                        0, True, 2))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = self.stdio
            startup.lpAttributeList = dict(handle_list=self.stdio)
            self.creation_started = True
            try:
                # The caretaker already owns this object, including ambiguous API failure.
                self.handles = self.api.CreateProcess(command[0], subprocess.list2cmdline(command),
                    None, None, True, 0x4 | 0x400, env, None, startup)
            except OSError:
                self.creation_started = False  # Win32 creation denial: no process returned.
                raise
        except BaseException:
            self.close_stdio()
            raise

    def start_controller(self, command, out, err, env, stderr, windows, token, record):
        """The owning session/qualify caller retains this object on any uncertain failure."""
        started = time.monotonic()
        self.controller_preparation_deadline = started+180
        child_env = dict(env, CHOPPER_NATIVE_STARTUP_TOKEN=token,
                         CHOPPER_NATIVE_PREPARATION_UNTIL=str(started+180))
        self.controller_job = create_job(windows)
        try:
            readfd, writefd = os.pipe()
            with os.fdopen(readfd, 'rb') as reader, os.fdopen(writefd, 'wb') as writer:
                self.start(command, out, err, child_env, stdin=reader)
                record('created', dict(identity=windows._held_identity(windows.kernel(),self.handle,self.pid),
                    process_handle=int(self.handle), thread_handle=int(self.thread)))
                if time.monotonic() >= started+30:
                    raise OSError('controller creation exceeded startup deadline')
                self.assign(self.controller_job)
                if time.monotonic() >= started+30:
                    raise OSError('controller assignment exceeded startup deadline')
                self.resume()
                ready = self.wait_controller_entry(stderr,token,started+30)
                record('entry-ready',ready)
                def write_ack(line):
                    writer.write(line.encode('ascii'))
                    writer.flush()
                self.acknowledge_controller(self.controller_job,windows,token,write_ack,
                    lambda value:record('ack-intent',value))
        except BaseException:
            if not self.controller_ack_attempted:
                proof = self.abort_controller_startup(self.controller_job,windows)
                windows.close(self.controller_job)
                self.controller_no_start_closed = proof
            raise

    def wait_controller_entry(self, stderr, token, deadline):
        markers = [b'CHOPPER_NATIVE_STARTUP_'+name+b' '+token.encode('ascii')+b'\n'
                   for name in (b'ENTRY', b'IMPORTS_COMPLETE', b'READY')]
        captured = b''
        while time.monotonic() < deadline:
            if self.poll() is not None:
                raise OSError('controller exited before startup acknowledgement')
            with stderr.open('rb') as stream:
                stream.seek(len(captured))
                captured += stream.read(65537-len(captured))
            if len(captured) > 65536:
                raise OSError('controller startup capture ceiling')
            observed = captured.replace(b'\r\n', b'\n')
            lines = observed.split(b'\n')[:-1]
            positions = [lines.index(marker[:-1]) if marker[:-1] in lines else -1 for marker in markers]
            if all(position >= 0 for position in positions):
                if positions != sorted(positions) or time.monotonic() >= deadline:
                    raise OSError('controller startup markers stale/out of order')
                self.controller_entry_deadline = deadline
                return dict(stderr_bytes=len(captured), entry=True, imports_complete=True, ready=True)
            time.sleep(.02)
        raise OSError('controller Python entry/imports deadline exceeded')

    def acknowledge_controller(self, job, windows, token, write_ack, record):
        """Only this barrier permits a controller to create its independent keeper."""
        if self.controller_job != job:
            raise OSError('owned controller Job required')
        if len(token) != 64 or set(token)-set('0123456789abcdef'):
            raise OSError('invalid controller startup token')
        if self.controller_entry_deadline is None or time.monotonic() >= self.controller_entry_deadline:
            raise OSError('fresh controller entry observation required')
        if self.controller_ack_attempted or not self.known_process() or self.poll() is not None:
            raise OSError('live unacknowledged controller required')
        before = windows.query_job(job)
        if before['flags'] != 0x2000 or before['pids'] != [self.pid]:
            raise OSError('strict controller startup Job required')
        member = W.BOOL()
        if not windows.kernel().IsProcessInJob(self.handle, job, ctypes.byref(member)) or not member.value:
            raise OSError('held controller Job membership required')
        created = windows._held_birth(windows.kernel(), self.handle)
        record(dict(pid=self.pid, created=created, strict_job=before, acknowledgement_intent=True))
        if time.monotonic() >= self.controller_entry_deadline:
            raise OSError('controller startup intent stale')
        info = windows.Extended()
        # After ACK, parent death must not kill pending queries; the keeper breaks away.
        info.basic.flags = 0x800
        if not self.dll.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError('controller keeper breakaway transition failed')
        after = windows.query_job(job)
        if after['flags'] != 0x800 or after['pids'] != [self.pid] or windows._held_birth(windows.kernel(), self.handle) != created:
            raise OSError('controller startup Job transition drift')
        if time.monotonic() >= self.controller_entry_deadline:
            raise OSError('controller startup transition stale')
        self.controller_ack_attempted = True  # The callback can fail after partial or complete delivery.
        write_ack(token+'\n')
        if time.monotonic() >= self.controller_entry_deadline:
            raise OSError('controller startup acknowledgement delivery stale')
        return dict(pid=self.pid, created=created, job=after, acknowledged=True)

    def finish_controller(self, windows):
        """A self-exited controller may release its Job only after complete quiescence."""
        if self.controller_job is None:
            raise OSError('owned controller Job required')
        if self.poll() is None:
            raise OSError('live controller cleanup requires retention')
        code = self.wait(0)
        self.close()
        until = time.monotonic()+3
        while True:
            try:
                census = windows.query_job(self.controller_job)
            except windows.IncompleteJobCensus:
                if time.monotonic() >= until:
                    raise
            else:
                if not census['pids']:
                    break
                if time.monotonic() >= until:
                    raise OSError('controller Job remains occupied')
            time.sleep(.02)
        windows.close(self.controller_job)
        return dict(code=code, job=census, handles_closed=True)

    def abort_controller_startup(self, job, windows):
        if self.controller_job != job:
            raise OSError('owned controller Job required')
        if self.controller_ack_attempted:
            raise OSError('acknowledged controller cleanup requires quiescence proof')
        direct_stop = False
        if self.known_process() and self.poll() is None:
            member = W.BOOL()
            if not windows.kernel().IsProcessInJob(self.handle,job,ctypes.byref(member)):
                raise OSError('controller startup membership unknown')
            if not member.value:
                if self.resume_attempted:
                    raise OSError('uncontained resumed controller')
                self.kill()  # Positively held, never resumed after failed assignment.
                direct_stop = True
        windows.terminate(job)
        code = self.wait(10)
        self.close()
        until = time.monotonic()+3
        while True:
            try:
                census = windows.query_job(job)
            except windows.IncompleteJobCensus:
                if time.monotonic() >= until:
                    raise
            else:
                if not census['pids']:
                    break
                if time.monotonic() >= until:
                    raise OSError('controller startup Job did not drain')
            time.sleep(.02)
        return dict(code=code, job=census, handles_closed=True, no_ack=True,
                    direct_never_resumed_stop=direct_stop)

    def close_stdio(self):
        while self.stdio:
            self.api.CloseHandle(self.stdio[-1])
            self.stdio.pop()

    def assign(self, job):
        if not self.known_process():
            raise OSError('Windows bootstrap process not created')
        self.close_stdio()  # caller already holds the suspended process if close fails
        if not self.dll.AssignProcessToJobObject(job, self.handle):
            raise OSError('Windows bootstrap Job assignment failed')

    def resume(self):
        self.resume_attempted = True
        if self.dll.ResumeThread(self.thread) != 1:
            raise OSError('Windows bootstrap primary thread resume failed')

    def poll(self):
        try:
            return self.wait(0)
        except subprocess.TimeoutExpired:
            return None

    def wait(self, timeout):
        if not self.known_process():
            return 0
        result = self.api.WaitForSingleObject(self.handle, int(timeout*1000))
        if result == 258:
            raise subprocess.TimeoutExpired('native worker', timeout)
        if result != 0:
            raise OSError('Windows worker wait failed')
        return self.api.GetExitCodeProcess(self.handle)

    def kill(self):
        if self.known_process():
            self.api.TerminateProcess(self.handle, 91)

    def close(self):
        self.close_stdio()
        if self.known_process():
            self.api.CloseHandle(self.thread)
            self.api.CloseHandle(self.handle)


def pipe_available(fd):
    import msvcrt
    available = W.DWORD()
    if not kernel().PeekNamedPipe(msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None):
        code = ctypes.get_last_error()
        if code in (109, 232):  # broken pipe / no data (writer closed)
            return -1
        raise OSError('Windows controller pipe query failed: '+str(code))
    return available.value


def controller_entry(token, stream, emit):
    """No main/HostLock code runs until the owning startup supervisor acknowledges."""
    if len(token) != 64 or set(token)-set('0123456789abcdef'):
        raise OSError('invalid controller startup token')
    emit('CHOPPER_NATIVE_STARTUP_READY '+token)
    if stream.readline(130) != token+'\n':
        raise OSError('controller startup acknowledgement missing')
    emit('CHOPPER_NATIVE_STARTUP_ACKNOWLEDGED '+token)


def supervise(definition_path, exact_sha, *, execute=False):
    """Run the selected Tiny protocol; stdin transitions require exact parent grants.

    This is the reviewed native operator moved into its owning harness. No
    definition-supplied executable, private wrapper or automatic retry is added.
    """
    import copy
    import json
    from pathlib import Path
    import sys
    from .verify import read_json as read, require as need, sha256 as sha

    need(os.name == 'nt' or sys.platform.startswith('linux'), 'maintained Tiny supervision requires Windows or Linux')
    need(sha(definition_path) == exact_sha, 'definition review digest mismatch')
    definition = read(definition_path)
    need(definition['schema'] in ('native-tiny-operator-v1','native-scale-operator-v1'), 'maintained native operator schema')
    for key in ('disabled_plan', 'source_maps', 'authorization'):
        item = definition[key]
        need(sha(item['path']) == item['sha256'], key+' pin drift')
    plan = read(definition['disabled_plan']['path'])
    need(str(Path(sys.executable).resolve()) == plan['python']['path'], 'selected real private Python required')
    from .native_preflight import attempt_root
    need(Path(definition['namespace']) == attempt_root(plan, Path), 'operator attempt/plan path mismatch')
    source_maps = read(definition['source_maps']['path'])
    need(source_maps == {key: plan[key] for key in ('product','harness','dependencies')},
         'operator complete source/runtime map mismatch')
    # Normalize exactly once, before digest; all dispatched children inherit this.
    os.environ['_'] = str(Path(sys.executable).resolve())
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    scripts = Path(plan['harness']['root'])/'scripts'
    need(Path(__file__).resolve().parent == scripts/'scale_acceptance',
         'operator must run from selected harness')
    sys.path.insert(0, str(scripts))
    from scale_acceptance.native_scale_control import create, validate, approve as approve_proposal
    from scale_acceptance.native_scale_identity import environment_digest, git, host, stamp
    from scale_acceptance.native_scale_host import module
    from scale_acceptance import native_tiny as tiny
    from scale_acceptance.native_scale_control import validate_preparation
    large = definition['schema'] == 'native-scale-operator-v1'
    need((tiny.enabled(plan) if not large else plan['os'] == 'Windows' and not tiny.enabled(plan)) and
         plan['actions_enabled'] is False and plan['parent_scheduled'] is False,
         'supervise only a disabled complete Tiny plan')
    validate_preparation(plan)
    meter = (tiny.ReadBudget(dict(qualification=dict(metadata_per_process={k:definition['metadata_grant'][k]
        for k in ('read_bytes','visits')})),Path(definition['disabled_plan']['path'])) if large else
        tiny.ReadBudget(plan,Path(definition['disabled_plan']['path'])) if os.name != 'nt' else None)
    namespace = Path(definition['namespace'])
    plan_file = namespace/('scale-plan.json' if large else 'tiny-plan.json')
    frozen = prepared = launched = False
    child = None
    controller_finished = False
    terminal_owner_closed = False
    next_stage = 0
    from .native_scale_identity import execution_shapes
    stages = tuple(shape+'-'+stage for shape in execution_shapes(plan) for stage in ('generation','Run'))+(() if large else ('failure',))
    execution = plan['windows_execution'] if large else plan['qualification']
    result_file = Path(plan['owned_root'])/('scale-result.json' if large else 'qualification-result.json')
    def launch_check():
        need(time.time() < execution['launch_cutoff_unix'], 'original native launch cutoff expired')
    def check_clock():
        need(time.time() < execution['stop_unix'], 'original native absolute stop expired')
    def owner_release(qualification):
        original = qualification['original_lock']
        actual = read(Path(plan['owned_root'])/'reservation.json')['actual_lock']
        platform_release = (original.get('capture_eof_joined') is True if os.name == 'nt'
                            else original.get('original_owner_lock_absent') is True)
        return (qualification['plan_sha256'] == sha(plan_file) and
            original.get('original_descriptor_closed') is True and platform_release and
            all(original.get(key) == value for key,value in actual.items()) and
            original['path'] == plan['reservation']['lock_path'] and
            original['stat'] == execution['original_lock_stat'])
    def failure_diagnostic(error):
        import traceback
        value = dict(error=repr(error)[:2048],
            notes=[str(note)[:512] for note in getattr(error, '__notes__', ())[:8]],
            traceback=''.join(traceback.format_exception(type(error), error, error.__traceback__))[-4096:],
            qualification=False, controller_pid=child.pid if child is not None else None)
        try:
            print(json.dumps(dict(native_tiny_operator_failure=value)), file=sys.stderr, flush=True)
        except BaseException as diagnostic_error:
            try:error.add_note('operator stderr diagnostic unavailable: '+repr(diagnostic_error)[:512])
            except BaseException:pass
        return value
    def linux_failed_release():
        # One exact owned child signal; no group action or renewed worker timer.
        import signal
        until = min(time.monotonic()+43, time.monotonic()+max(0,
            execution['stop_unix']-time.time()))
        if child.poll() is None:
            try:
                child.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
        code = child.wait(timeout=max(0, until-time.monotonic()))
        qualification = read(result_file)
        actual = read(Path(plan['owned_root'])/'reservation.json')['actual_lock']
        need(actual.get('owner_pid') == child.pid and actual.get('mechanism') == 'flock-exclusive' and
             qualification.get('passed') is False and qualification.get('scale_acceptance') is False and
             qualification.get('scale_slots_consumed') == 0 and type(code) is int and code != 0 and
             owner_release(qualification), 'positive failed Linux Original release required')
        create(namespace/'qualify-failed-exit.json', dict(code=code, original_release_proven=True,
            qualification_sha256=sha(result_file)))
        return True
    def requests():
        if not execute:
            for line in sys.stdin:
                yield read_request(line)
            return
        yield dict(command='freeze', definition_sha256=exact_sha,
            accept_metadata_grant=definition['metadata_grant'], runtime_sufficiency_reviewed=True)
        yield dict(command='preflight', plan_sha256=sha(plan_file), request_sha256=sha(namespace/'request.json'))
        yield dict(command='qualify', plan_sha256=sha(plan_file), preflight_sha256=sha(namespace/'preflight/result.json'))
        for stage in stages:
            proposal = Path(plan['owned_root'])/(stage+'-proposal.json')
            ready = None
            while child.poll() is None:
                launch_check()
                if proposal.exists():
                    # Exclusive durable records can be visible before their writer
                    # finishes. Only a complete JSON record ending in its newline
                    # can become an exact approval; the payload is checked below.
                    need(proposal.stat().st_size <= 64*1024**2, 'bounded Tiny proposal metadata')
                    raw = proposal.read_bytes()
                    if raw.endswith(b'\n'):
                        try:
                            json.loads(raw)
                        except ValueError:
                            pass
                        else:
                            ready = sha(proposal)
                            break
                time.sleep(.02)
            if child.poll() is not None:
                break
            yield dict(command='approve', stage=stage, sha256=ready)
        while child.poll() is None:
            check_clock()
            time.sleep(.02)
        yield dict(command='finish')
    def read_request(line):
        return json.loads(line)
    print(json.dumps(dict(status='waiting-for-explicit-Root-freeze', definition_sha256=exact_sha)), flush=True)
    try:
        for request in requests():
            verb = request['command']
            need(sha(definition['authorization']['path']) == definition['authorization']['sha256'], 'original authorization changed')
            if frozen:
                need(environment_digest() == plan['environment_sha256'], 'persistent operator environment drift')
            if verb == 'freeze':
                need(not frozen and child is None, 'single fresh freeze only')
                need(request['definition_sha256'] == exact_sha and
                     request['accept_metadata_grant'] == definition['metadata_grant'] and
                     request['runtime_sufficiency_reviewed'] is True, 'exact Root grant/scope acceptance required')
                need(time.time() < execution['launch_cutoff_unix'], 'original cutoff expired; no renewal')
                need(not namespace.exists(), 'fresh Tiny namespace only; no retries')
                h = Path(plan['harness']['root'])
                need(git(h, 'rev-parse', 'HEAD') == plan['harness']['commit'] and
                     git(h, 'rev-parse', 'HEAD^{tree}') == plan['harness']['tree'] and
                     git(h, 'status', '--porcelain') == '', 'selected frozen checkout drift')
                for name, expected in plan['harness']['sha256'].items():
                    need(sha(h/name) == expected, 'selected source byte drift: '+name)
                need(host() == plan['host'], 'actual selected native host drift')
                need(stamp(Path(plan['reservation']['lock_path'])) == execution['original_lock_stat'], 'original lock identity drift')
                plan = copy.deepcopy(plan)
                plan.update(actions_enabled=True, parent_scheduled=True, approved=True, enabled=True,
                            environment_sha256=environment_digest())
                validate(plan)  # source/schema validation, not actual-host preflight
                namespace.mkdir(mode=0o700)
                create(plan_file, plan)
                create(namespace/'request.json', dict(schema='chopper-acceptance-preflight-v1', profile='native',
                    host_os=plan['os'], plan=str(plan_file), plan_sha256=sha(plan_file), limits=definition['preflight_limits']))
                module('acceptance-preflight').request(namespace/'request.json')
                create(namespace/'Root-freeze.json', dict(operator_identity=(module('browser-small-windows').process_identity(os.getpid()) if os.name=='nt' else None),request=request, definition_sha256=exact_sha,
                    plan_sha256=sha(plan_file), environment_sha256=plan['environment_sha256'],
                    source_maps=definition['source_maps'], authorization=definition['authorization']))
                frozen = True
                print(json.dumps(dict(status='frozen-only', plan_sha256=sha(plan_file), request_sha256=sha(namespace/'request.json'))), flush=True)
            elif verb == 'preflight':
                need(frozen and not prepared and child is None, 'one explicit preflight only')
                need(request['plan_sha256'] == sha(plan_file) and request['request_sha256'] == sha(namespace/'request.json'), 'exact preflight approval required')
                launch_check()
                argv = [sys.executable, '-B', str(scripts/'acceptance-preflight.py'), 'preflight', str(namespace/'request.json'), str(namespace/'preflight')]
                create(namespace/'preflight-invocation.json', dict(argv=argv, retries=0))
                with (namespace/'preflight-stdout.log').open('xb') as out, (namespace/'preflight-stderr.log').open('xb') as err:
                    code = subprocess.run(argv, stdout=out, stderr=err).returncode
                create(namespace/'preflight-exit.json', dict(code=code))
                need(code == 0, 'preflight failed; terminal attempt, no retry')
                tiny.preflight(plan_file, plan, namespace/'preflight/result.json', sha(namespace/'preflight/result.json'))
                prepared = True
                print(json.dumps(dict(status='preflight-passed-only', preflight_sha256=sha(namespace/'preflight/result.json'))), flush=True)
            elif verb == 'qualify':
                need(prepared and not launched and child is None, 'single separately approved qualify only')
                need(request['plan_sha256'] == sha(plan_file) and request['preflight_sha256'] == sha(namespace/'preflight/result.json'), 'exact matching launch approval required')
                launch_check()
                argv = [sys.executable, '-B', str(scripts/'native-scale-runner.py'), 'session' if large else 'qualify', str(plan_file),
                        '--sha256', request['plan_sha256'], '--preflight', str(namespace/'preflight/result.json'),
                        '--preflight-sha256', request['preflight_sha256']]
                create(namespace/'qualify-invocation.json', dict(argv=argv, retries=0))
                try:
                    with (namespace/'qualify-stdout.log').open('xb') as out, (namespace/'qualify-stderr.log').open('xb') as err:
                        if os.name == 'nt':
                            from scale_acceptance import native_scale_windows as bootstrap
                            from scale_acceptance.native_scale_host import module
                            windows = module('browser-small-windows')
                            child = bootstrap.SuspendedWorker()
                            def record_startup(event, value):
                                create(namespace/('controller-startup-'+event+'.json'),value)
                                if event == 'created':
                                    create(namespace/'controller-pid.json',dict(pid=child.pid,identity=value['identity']))
                            child.start_controller(argv,out,err,dict(os.environ),namespace/'qualify-stderr.log',
                                windows,__import__('secrets').token_hex(32),record_startup)
                            prelock = {'selected plan read','metadata budget','qualification mode','plan stat',
                                'plan hash','plan read','plan validation','preflight custody','original lock stat',
                                'retained history','root absence'}
                            raw=b''
                            while True:
                                with (namespace/'qualify-stderr.log').open('rb') as capture:
                                    capture.seek(len(raw))
                                    raw+=capture.read(65537-len(raw))
                                need(len(raw)<=65536,'bounded preparation diagnostics')
                                records=[]
                                for line in raw.splitlines():
                                    try:record=json.loads(line)
                                    except ValueError:continue
                                    if isinstance(record,dict):records.append(record)
                                if any(record.get('native_preparation_complete') is True for record in records):
                                    break
                                code=child.poll()
                                if code is not None:
                                    failure=next((record for record in reversed(records)
                                        if record.get('native_preparation_failed') in prelock),None)
                                    owner_closed = next((record for record in reversed(records)
                                        if record.get('native_preparation_failed') == 'HostLock' and
                                        record.get('pending_calls') is False and
                                        record.get('no_worker_owner_closed', {}).get('schema') ==
                                            'native-windows-owner-closed-start-v1'), None)
                                    if failure is not None or owner_closed is not None:
                                        if owner_closed is not None:
                                            closed = owner_closed['no_worker_owner_closed']
                                            need(all(closed.get(key) is True for key in
                                                ('keeper_reaped','capture_eof_joined','captures_closed',
                                                 'process_handle_closed','original_closed_after_keeper_reap')) and
                                                closed.get('caretaker_requests') == 0,
                                                'positive closed keeper startup proof required')
                                        proof=child.finish_controller(windows)
                                        controller_finished = True
                                        child.controller_no_start_closed=dict(proof,prelock_failure=failure,
                                            closed_keeper=owner_closed, no_ack=False,
                                            original_never_acquired=owner_closed is None)
                                    elif result_file.exists():
                                        break  # Existing finish/audit consume the actual failed qualification.
                                    raise OSError('controller exited before preparation completed')
                                need(time.monotonic()<child.controller_preparation_deadline,
                                    'shared Windows preparation deadline exceeded; retain ownership')
                                time.sleep(.02)
                        else:
                            child = subprocess.Popen(argv, stdout=out, stderr=err)
                            create(namespace/'controller-pid.json',dict(pid=child.pid,identity=None))
                except BaseException as error:
                    if os.name != 'nt':
                        raise
                    # ACK delivery uncertainty or incomplete closure keeps the process/Job handles here.
                    proof = getattr(child,'controller_no_start_closed',None)
                    causes, seen, current = [], set(), error
                    for _ in range(4):
                        if current is None or id(current) in seen:
                            break
                        seen.add(id(current))
                        causes.append(dict(error=repr(current)[:1024],
                            notes=[str(note)[:512] for note in getattr(current,'__notes__',())[:4]]))
                        current = current.__cause__ or current.__context__
                    try:
                        create(namespace/'controller-startup-failure.json',dict(error=repr(error),cause_chain=causes,
                            no_start_closed=proof,ack_delivery_started=bool(getattr(child,'controller_ack_attempted',False)),
                            qualification=False))
                    except BaseException:
                        pass
                    if proof is not None:
                        create(namespace/'qualify-exit.json',dict(code=proof['code']))
                        print(json.dumps(dict(status='startup-failed-clean',qualification=False)),flush=True)
                        return 1
                    if controller_finished:
                        raise  # A later receipt failure cannot resurrect a closed actor.
                    failure_diagnostic(error)
                    try:print(json.dumps(dict(status='startup-failed-retained',error=repr(error),qualification=False)),flush=True)
                    except BaseException:pass
                    while True:
                        time.sleep(1)
                launched = True
                print(json.dumps(dict(controller_pid=child.pid)), flush=True)
            elif verb == 'approve':
                need(child is not None and child.poll() is None and next_stage < len(stages), 'live controller and next stage required')
                launch_check()
                name = stages[next_stage]
                need(request['stage'] == name, 'separate ordered stage approval required')
                proposal = namespace/'data'/(name+'-proposal.json')
                approval = namespace/'data'/(name+'-approved.json')
                need(request['sha256'] == sha(proposal), 'exact reviewed proposal SHA required')
                maintained = module('native-scale-runner')
                maintained.tiny_proposal_binding(plan,plan_file,name,request['sha256'])

                create(namespace/(name+'-approval-invocation.json'), dict(call='native_scale_control.approve',
                    proposal=str(proposal), approval=str(approval), sha256=request['sha256'], retries=0))
                approve_proposal(proposal,approval,request['sha256'])
                next_stage += 1
                print(json.dumps(dict(approved=name)), flush=True)
            elif verb == 'finish':
                need(child is not None and child.poll() is not None, 'controller must exit after owned cleanup before finish')
                code = child.wait(0) if os.name == 'nt' else child.wait()
                if os.name != 'nt':
                    controller_finished = True
                if os.name == 'nt':
                    try:
                        proof=child.finish_controller(windows)
                        controller_finished = True
                        create(namespace/'controller-job-closed.json',proof)
                    except BaseException as error:
                        if controller_finished:
                            raise
                        failure_diagnostic(error)
                        try:print(json.dumps(dict(status='controller-cleanup-retained',error=repr(error))),flush=True)
                        except BaseException:pass
                        while True:time.sleep(1)
                create(namespace/'qualify-exit.json', dict(code=code))
                qualification = read(result_file)
                terminal_owner_closed = owner_release(qualification)
                need(qualification['plan_sha256'] == sha(plan_file) and
                     qualification['passed'] is (code == 0) and qualification['scale_acceptance'] is (large and code == 0) and
                     (qualification['scale_slots_consumed'] == (len(execution_shapes(plan)) if large else 0) if code == 0 else
                      qualification['scale_slots_consumed'] in ((None,0,1,2) if large else (0,))) and
                     qualification['original_lock']['original_descriptor_closed'] is True and
                     terminal_owner_closed,
                     'complete Tiny terminal/Original-release receipt required')
                print(json.dumps(dict(controller_exit=code, after_exit_proofs_still_required=True)), flush=True)
                return code
            else:
                raise ValueError('freeze, preflight, qualify, explicit approve, terminal finish only')
    except BaseException as error:
        diagnostic = failure_diagnostic(error)  # Observable before cleanup or any retained wait.
        try:
            create(namespace/'operator-failure.json', diagnostic)
        except BaseException as diagnostic_error:
            try:error.add_note('operator failure file unavailable: '+repr(diagnostic_error)[:512])
            except BaseException:pass
        if os.name != 'nt' and child is not None and not controller_finished:
            try:
                terminal_owner_closed = linux_failed_release()
                controller_finished = True
            except BaseException as cleanup_error:
                error.add_note('Linux failed-release proof: '+repr(cleanup_error)[:1024])
                failure_diagnostic(error)
        if controller_finished and not terminal_owner_closed:
            try:terminal_owner_closed = owner_release(read(result_file))
            except BaseException:pass
        if child is not None and not (controller_finished and terminal_owner_closed) and getattr(child, 'controller_no_start_closed', None) is None:
            # Unknown keeper/callback ownership stays retained, including an exited actor.
            while True:
                time.sleep(1)
        raise
    finally:
        if meter is not None:
            try:
                print(json.dumps(dict(native_tiny_operator_metadata_usage=dict(
                    read_bytes=meter.read_bytes,visits=meter.visits,failed=meter.failed))),file=sys.stderr,flush=True)
            except BaseException:
                pass  # A closed diagnostic stream cannot replace failure or cleanup proof.
    need(child is None or child.poll() is not None, 'keep operator stdin alive through cleanup; inspect retained owner on protocol failure')
    return 0
