"""Narrow native ownership: shared CI lock, bounded census and external caretaker.

No process-name enumeration. Runtime calls require explicit parent approval;
unit controls replace OS interfaces and never probe a real group/Job.
"""
import copy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import traceback
from types import SimpleNamespace
from . import native_scale_windows as windows_bootstrap
from .verify import require, read_json, unique_object
from .native_scale_control import create
from .native_scale_identity import stamp

HERE = Path(__file__).resolve().parents[1]
_calls = set()
_calls_mutex = threading.Lock()


def pending_calls():
    with _calls_mutex:
        return [thread for thread in _calls if thread.is_alive()]


def native_windows():
    return os.name == 'nt'


def module(name, *, scripts=None):
    root = HERE if scripts is None else Path(scripts)
    spec = importlib.util.spec_from_file_location('native_'+name.replace('-', '_'), root / (name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class HostLock:
    """Same local-ci lock; Linux inherits fd, Windows owner survives supervisor."""
    def __enter__(self):
        self.path = module('local-ci').host_lock_path()
        existing = getattr(self, 'existing', False)
        if not existing:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if native_windows():
            self.owner = WindowsLockOwner(self.path, existing=True) if existing else WindowsLockOwner(self.path)
            return self
        self.fd = os.open(self.path, os.O_RDWR | (os.O_NOFOLLOW if existing else os.O_CREAT), 0o600)
        try:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check()
        except BaseException:
            os.close(self.fd)
            raise
        return self

    def check(self):
        if getattr(self, 'owner', None):
            return self.owner.check()
        require(os.path.samestat(os.fstat(self.fd), self.path.stat()), 'held host lock replaced')

    def proof(self):
        self.check()
        if getattr(self, 'owner', None):
            return copy.deepcopy(self.owner.proof)
        return dict(path=str(self.path), owner_pid=os.getpid(), stat=stamp(self.path),
                    mechanism='flock-exclusive')

    def start_caretaker(self, plan, operation, directory):
        pool = getattr(self, 'source_pool', None)
        if pool is not None:
            pool.check()
            require(pool.ready and not pool.inflight, 'source prime must complete before caretaker')
        return self.owner.request(dict(command='start', plan=str(plan), operation=str(operation), directory=str(directory)))['pid']

    def register_source_pool(self, pool):
        require(getattr(self, 'owner', None) is not None and
                getattr(self, 'source_pool', None) is None, 'original Windows source owner required')
        self.source_pool = pool
        # EOF must retain authority even if this acknowledgement is lost.
        self.owner.request(dict(command='source-arm'))

    def close_source_pool(self):
        pool = getattr(self, 'source_pool', None)
        if pool is not None:
            pool.close()
            self.owner.request(dict(command='source-closed'))
            self.source_pool = None

    def __exit__(self, *args):
        if pending_calls() or getattr(self, 'cleanup_uncertain', False):
            retain_host_lock('native asynchronous operation')
            raise OSError('owned asynchronous cleanup unproven')
        if getattr(self, 'owner', None):
            try:
                self.close_source_pool()
            except BaseException:
                # Keep this process and its writer alive; EOF alone is unsafe.
                retain_host_lock('Windows source')
                raise
            self.owner.close()
            self.released = dict(self.owner.proof, original_descriptor_closed=True, capture_eof_joined=True)
            return
        self.check()
        self.released = self.proof()
        os.close(self.fd)  # never unlink; never use reservation bytes as proof
        self.released['original_descriptor_closed'] = True
        s = self.path.stat()
        device_inode = f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}'
        require(not any(parts[1:5] == ['FLOCK', 'ADVISORY', 'WRITE', str(os.getpid())] and
                        parts[5] == device_inode
                        for parts in (line.split() for line in Path('/proc/locks').read_text().splitlines())),
                'original flock still held after owned cleanup')
        self.released['original_owner_lock_absent'] = True


class WindowsLockOwner:
    """RPC to the process that locks byte zero and owns caretaker parent pipes."""
    def __init__(self, path, *, existing=False):
        self.path = path
        self.process = subprocess.Popen([sys.executable, '-B', str(HERE/'native-scale-runner.py'),
                                         '_lock_owner', str(path), *(['--existing'] if existing else [])], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, bufsize=1,
                                        creationflags=0x01000000)  # CREATE_BREAKAWAY_FROM_JOB; no fallback
        self.responses = queue.Queue()
        self.rpc_lock = threading.Lock()
        self.failed = False
        self.capture_eof = False
        def reader():
            try:
                for line in self.process.stdout:
                    self.responses.put(json.loads(line))
                self.capture_eof = True
            finally:
                self.responses.put(None)
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            ready = self.receive()
            self.metadata = stamp(path)
            actual = module('browser-small-windows').process_identity(self.process.pid)
            self.proof = dict(path=str(path), owner_pid=self.process.pid, stat=self.metadata,
                              mechanism='msvcrt-byte-0', owner_identity=actual)
            require(ready.get('lock') == self.proof and actual['pid'] == self.process.pid
                    and type(actual['created']) is int and actual['created'] > 0,
                    'Windows lock owner startup identity mismatch')
        except BaseException as error:
            try:
                self.process.stdin.close()  # no caretaker RPC can precede construction
                code = self.process.wait(timeout=4)
                self.reader.join(timeout=2)
                require(not self.reader.is_alive(), 'Windows failed-start capture EOF/join missing')
                self.process.stdout.close()
                require(self.capture_eof and type(code) is int and not pending_calls(),
                        'Windows failed-start quiescence unproven')
                windows = module('browser-small-windows')
                dll, handle = windows.kernel(), self.process._handle
                require(dll.WaitForSingleObject(handle, 0) == 0, 'Windows failed-start keeper not signaled')
                birth = windows._held_birth(dll, handle)
                require(type(birth) is int and birth > 0, 'Windows failed-start held birth missing')
                handle.Close()
                error.native_owner_no_start_closed = dict(schema='native-windows-owner-closed-start-v1',
                    pid=self.process.pid, created=birth, code=code, keeper_reaped=True,
                    capture_eof_joined=True, captures_closed=True, process_handle_closed=True,
                    caretaker_requests=0, original_closed_after_keeper_reap=True)
            except BaseException as cleanup_error:
                try:
                    error.add_note('Windows owner failed-start cleanup unproven: '+repr(cleanup_error))
                except BaseException:
                    pass
            raise

    def check(self):
        require(not self.failed and self.process.poll() is None and stamp(self.path) == self.metadata,
                'external Windows host lock lost')

    def receive(self, sample=lambda: None, seconds=4):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            sample()
            remaining = until-time.monotonic()
            if remaining <= 0:
                break
            try:
                result = self.responses.get(timeout=min(.2, remaining))
            except queue.Empty:
                continue
            if time.monotonic() >= until:
                break
            require(result is not None and result.get('ok') is True, 'Windows host lock handoff failed')
            return result
        raise OSError('Windows host lock handoff timed out')

    def request(self, value, sample=lambda: None, seconds=4):
        # A late reply after timeout must never satisfy the next RPC.
        with self.rpc_lock:
            require(not self.failed, 'Windows lock owner protocol already failed')
            try:
                self.check()
                challenge = secrets.token_hex(32)
                self.process.stdin.write(json.dumps(dict(value, challenge=challenge))+'\n')
                self.process.stdin.flush()
                result = self.receive(sample, seconds)
                require(result.get('challenge') == challenge and result.get('lock') == self.proof,
                        'Windows live lock observation mismatch')
                self.check()
                return {k: v for k, v in result.items() if k not in ('challenge', 'lock')}
            except BaseException:
                self.failed = True
                raise

    def close(self):
        # Seal the owner's response capture while it still holds the original
        # lock. Only joined EOF permits normal parent EOF/release afterwards.
        self.request(dict(command='close'))
        self.reader.join(timeout=2)
        require(not self.reader.is_alive(), 'Windows lock owner capture EOF/join missing')
        self.process.stdout.close()
        self.process.stdin.close()
        require(self.process.wait(timeout=15) == 0, 'Windows host lock cleanup failed')


def stop_locked_caretaker(process, directory):
    """A pipe flush failure cannot skip independent stop/reap/cleanup proof."""
    errors = []
    try:process.stdin.close()
    except BaseException as error:errors.append(error)
    try:code = process.wait(timeout=12)
    except BaseException as error:errors.append(error);code = None
    try:
        result = read_json(Path(directory)/'cleanup.json')
        require(result['remaining'] == [] and result['cleanup_errors'] == [] and
                result.get('monitor_threads_joined') is True and result.get('capture_writers_reaped') is True and
                process.stdin.closed is True and type(code) is int,
                'Windows lock owner cannot prove owned cleanup')
    except BaseException as error:
        errors.append(error)
        result = None
    proof = dict(caretaker_pid=process.pid,code=code,stdin_closed=True,
                 cleanup_proven=True) if result is not None else None
    if errors:
        primary = errors[0]
        for error in errors[1:]:
            try:primary.add_note('caretaker cleanup: '+repr(error))
            except BaseException:pass
        if proof is not None:primary.caretaker_cleanup_closed = proof
        raise primary
    return proof


def lock_owner_loop(stream, reply, launch, stop, retain, observe, seal_capture=lambda: None):
    """Injectable protocol control; only the OS entry point owns a real lock."""
    active = None
    source_armed = False
    sealed = False
    failed_phase = None
    def stopped_failure(primary):
        try:proof = stop(*active)
        except BaseException as error:
            proof = getattr(error,'caretaker_cleanup_closed',None)
            if proof is None:raise
            try:primary.add_note('caretaker close: '+repr(error))
            except BaseException:pass
        require(proof and proof['cleanup_proven'],'failed caretaker cleanup unproven')
        value=dict(caretaker_failed=True,error=str(primary)[:4096],**proof)
        try:
            create(Path(active[1])/'lock-owner-stop-failure.json',dict(value,source_armed=source_armed,
                traceback=''.join(traceback.format_exception(primary))[-8192:]))
        except BaseException as diagnostic_error:
            try:primary.add_note('owner failure diagnostic unavailable: '+repr(diagnostic_error))
            except BaseException:pass
        return value
    try:
        for line in stream:
            require(not sealed, 'Windows owner capture already sealed; only EOF allowed')
            value = json.loads(line)
            challenge = value.get('challenge')
            require(isinstance(challenge, str) and len(challenge) == 64 and
                    all(c in '0123456789abcdef' for c in challenge),
                    'Windows lock observation challenge required')
            observe()  # Deny drift before launching or forwarding any command.
            def ack(result):
                reply(dict(result, challenge=challenge, lock=observe()))
            if value['command'] == 'source-arm':
                require(not source_armed and active is None, 'source fence must precede work')
                source_armed = True
                ack(dict(ok=True))
            elif value['command'] == 'source-closed':
                require(source_armed and active is None, 'source cleanup must follow owned stop')
                source_armed = False
                ack(dict(ok=True))
            elif value['command'] == 'start':
                require(active is None, 'caretaker already active')
                active = launch(value)
                ack(dict(ok=True, pid=active[0].pid))
            elif value['command'] == 'observe':
                require(active is None and not source_armed, 'idle owner observation requires no active work')
                ack(dict(ok=True, idle=True))
            elif value['command'] == 'pulse':
                require(active is not None, 'no active caretaker')
                if failed_phase is None:
                    try:
                        active[0].stdin.write(b'.')
                        active[0].stdin.flush()
                    except BaseException as error:
                        failed_phase = stopped_failure(error)
                ack(dict(ok=True,**(failed_phase or {})))
            elif value['command'] == 'finish':
                require(active is not None, 'no active caretaker')
                try:stop(*active)
                except BaseException as error:
                    if not getattr(error,'caretaker_cleanup_closed',None):raise
                    if failed_phase is None:failed_phase=stopped_failure(error)
                active = None
                ack(dict(ok=True,**(failed_phase or {})))
                failed_phase = None
            elif value['command'] == 'close':
                require(active is None and not source_armed, 'Windows owner close before owned cleanup')
                ack(dict(ok=True))
                seal_capture()
                sealed = True
            else:
                raise ValueError('invalid Windows lock owner command')
    finally:
        try:
            if active is not None:
                stop(*active)
        except BaseException as error:
            # Record the actual stop failure before retain can block forever.
            try:
                value=dict(error=repr(error)[:4096],caretaker_pid=active[0].pid,
                    notes=[str(note)[:1024] for note in getattr(error,'__notes__',())[:8]],
                    traceback=''.join(traceback.format_exception(error))[-8192:],source_armed=source_armed)
                create(Path(active[1])/'lock-owner-stop-failure.json',value)
            except BaseException as diagnostic_error:
                try:error.add_note('owner stop diagnostic unavailable: '+repr(diagnostic_error))
                except BaseException:pass
            retain()
            raise
        finally:
            if source_armed:
                retain()  # Supervisor death cannot prove its handle cleanup.


def retain_host_lock(platform):
    try:
        os.write(2, (platform+' host lock retained: owned cleanup unproven; parent intervention required\n').encode())
    except OSError:
        pass
    while True:
        time.sleep(1)


def independent_windows_lock_owner(backend=None):
    """A supervisor Job close must not terminate the shared-lock owner."""
    from ctypes import wintypes as W
    dll = backend or ctypes.WinDLL('kernel32', use_last_error=True)
    dll.GetCurrentProcess.restype = W.HANDLE
    dll.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
    dll.IsProcessInJob.restype = W.BOOL
    assigned = W.BOOL()
    require(dll.IsProcessInJob(dll.GetCurrentProcess(), None, ctypes.byref(assigned))
            and not assigned.value, 'Windows lock owner must be outside inherited Jobs')


def seal_response_capture():
    descriptor = sys.stdout.fileno()
    sys.stdout.flush()
    sys.stdout.close()
    # CPython's standard FileIO has closefd=False; its wrapper cannot signal EOF.
    os.close(descriptor)


def windows_lock_owner(lock_path, *, existing=False):
    require(native_windows(), 'Windows lock owner requires native Windows')
    independent_windows_lock_owner()  # before lock acknowledgement or caretaker launch
    import msvcrt
    lock_path = Path(lock_path)
    fd = os.open(lock_path, os.O_RDWR | (0 if existing else os.O_CREAT), 0o600)
    def observe():
        require(os.path.samestat(os.fstat(fd), lock_path.stat()) and stamp(lock_path) == metadata,
                'held host lock replaced')
        return dict(path=str(lock_path), owner_pid=os.getpid(), stat=metadata,
                    mechanism='msvcrt-byte-0', owner_identity=owner_identity)
    def reply(value):
        observe()
        print(json.dumps(value), flush=True)
    def launch(value):
        directory = Path(value['directory'])
        command = [sys.executable, '-B', str(HERE/'native-scale-runner.py'), '_caretaker',
                   value['plan'], value['operation'], str(directory)]
        with (directory/'caretaker-stdout.log').open('wb') as out, (directory/'caretaker-stderr.log').open('wb') as err:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err)
        return process, directory
    def retain():
        retain_host_lock('Windows')
    try:
        metadata = stamp(lock_path)
        owner_identity = module('browser-small-windows').process_identity(os.getpid())
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        reply(dict(ok=True, lock=observe()))
        lock_owner_loop(sys.stdin, reply, launch, stop_locked_caretaker, retain, observe, seal_response_capture)
    finally:
        os.close(fd)


def bounded(call, seconds=2, *, fence=None, poll=None):
    deadline = time.monotonic()+seconds
    def blocked():
        error = OSError('bounded operation blocked/stale')
        try:
            code = getattr(call, '__code__', None)
            error.add_note('call='+getattr(call, '__qualname__', type(call).__name__)+
                           ' file='+str(getattr(code, 'co_filename', None))+
                           ' line='+str(getattr(code, 'co_firstlineno', None))+
                           ' seconds='+str(seconds)+' elapsed='+str(time.monotonic()-(deadline-seconds)))
        except BaseException:
            pass  # Keep the primary timeout and pending-call fence if notes fail.
        return error
    result = queue.Queue(1)
    def invoke():
        try:
            result.put((True, call()))
        except BaseException as error:
            result.put((False, error))
        finally:
            with _calls_mutex:
                _calls.discard(threading.current_thread())
    thread = threading.Thread(target=invoke, daemon=True)
    with _calls_mutex:
        _calls.add(thread)
    thread.start()
    poll_failed = False
    try:
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            try:
                ok, value = result.get(timeout=min(.1, remaining) if poll else remaining)
                break
            except queue.Empty:
                if poll is None or time.monotonic() >= deadline:
                    raise
                try:poll()
                except Exception:
                    poll_failed = True
                    raise
    except BaseException as primary:
        if fence is not None:
            fence.poison()
        if poll_failed:
            try:
                thread.join(timeout=max(0, deadline-time.monotonic()))
            except BaseException as drain_error:
                try:primary.add_note('bounded failure drain: '+repr(drain_error))
                except BaseException:pass
        if isinstance(primary, queue.Empty) and not poll_failed:
            raise blocked() from None
        raise
    thread.join(timeout=max(0, deadline-time.monotonic()))
    if thread.is_alive() or time.monotonic() >= deadline:
        if fence is not None:
            fence.poison()
        raise blocked()
    if not ok:
        if fence is not None:
            fence.poison()
        raise value
    return value


def read_control_json(file, limit=1024**2):
    """Only live owned capacity/census snapshots; immutable records use read_json."""
    if not native_windows():return read_json(file,limit)
    from . import native_tiny
    budget = getattr(native_tiny,'budget',None)
    def charge(size):
        if budget is not None:
            with budget.mutex:
                if size is None:budget.visits += 1
                else:budget.read_bytes += size
                budget.check()
    raw = module('browser-small-windows').read_control_snapshot(file,limit,charge=charge)
    return json.loads(raw,object_pairs_hook=unique_object)


def publish(file, value, *, mutable=False):
    """Atomic IPC publication; campaign/approval records remain exclusive."""
    from .guard import load_runner
    def write():
        deadline = time.monotonic()+1
        runner = load_runner()
        while True:
            try:
                if mutable and native_windows():
                    return runner.write_json(file,value,replace=module('browser-small-windows').replace_control_snapshot)
                return runner.write_json(file,value)
            except OSError as error:
                if (mutable or getattr(error,'process_handle_close_uncertain',False) or
                        not native_windows() or getattr(error, 'winerror', None) not in (5, 32)
                        or time.monotonic() >= deadline):
                    raise
                time.sleep(.01)
                if time.monotonic() >= deadline:
                    raise
    return bounded(write)


class Freshness:
    def __init__(self, clock=time.monotonic, stale=5):
        self.clock, self.stale, self.last = clock, stale, clock()

    def completed(self):
        self.check()
        self.last = self.clock()

    def check(self):
        require(0 <= self.clock()-self.last < self.stale, 'missing/stale/blocked monitor')


def capacity_fresh(sample, now=None):
    """Age starts at the oldest observation, never at its completion or pulse."""
    from .native_scale_control import LIMITS
    now = time.monotonic() if now is None else now
    started, completed = sample['sample_started_monotonic'], sample['sample_completed_monotonic']
    require(type(started) in (int, float) and type(completed) in (int, float) and
            0 <= completed-started < LIMITS['disk_observation_seconds'] and
            completed <= now and 0 <= now-started < LIMITS['stale_seconds'],
            'disk capacity observation missing/stale/unfinished')


class Caretaker:
    """Out-of-worker safety process; pipe EOF detects controller death during hashes."""
    def __init__(self, plan, operation, directory, lock):
        self.directory = Path(directory)
        self.directory.mkdir()
        command = [sys.executable, '-B', str(HERE/'native-scale-runner.py'), '_caretaker',
                   str(plan), str(operation), str(self.directory)]
        self.lock_owner = lock.owner if native_windows() else None
        require(not native_windows() or self.lock_owner is not None, 'Windows external lock owner required')
        if self.lock_owner is not None:
            pid = lock.start_caretaker(plan, operation, self.directory)
            self.process = SimpleNamespace(pid=pid)
        else:
            with (self.directory/'caretaker-stdout.log').open('wb') as out, (self.directory/'caretaker-stderr.log').open('wb') as err:
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                                pass_fds=(lock.fd,))
        self.freshness = Freshness()
        self.created = time.monotonic()
        self.backup_job = None
        self.backup_cgroup = None

    def pulse(self, capacity=None):
        self.freshness.completed()
        if capacity is not None:
            capacity_fresh(capacity)
            publish(self.directory/'capacity-sample.json', {
                key:capacity[key] for key in ('sample_started_monotonic', 'sample_completed_monotonic')},mutable=True)
        self.capture()
        if getattr(self, 'lock_owner', None):
            self.lock_owner.check()
        else:
            require(self.process.poll() is None, 'caretaker lost')
        ack = self.directory/'supervisor-ready.json'
        if not ack.exists() and (getattr(self, 'backup_job', None) or getattr(self, 'backup_cgroup', None)):
            publish(ack, dict(caretaker_pid=self.process.pid))
        observed = self.directory/'owner-sample.json'
        if observed.exists():
            require(0 <= time.monotonic()-read_control_json(observed)['monotonic'] < 5, 'caretaker census stale')
        else:
            require(time.monotonic()-self.created < 5, 'caretaker census missing')
        if getattr(self, 'lock_owner', None):
            result = self.lock_owner.request(dict(command='pulse'))
            if result.get('caretaker_failed'):
                require(result.get('cleanup_proven') is True and result.get('caretaker_pid') == self.process.pid,
                        'failed caretaker closure identity mismatch')
                self.phase_failed = result
                error = OSError('caretaker failed: '+result['error'])
                error.caretaker_failed = True
                raise error
        else:
            self.process.stdin.write(b'.')
            self.process.stdin.flush()

    def ready(self, capacity, hot_check):
        """Complete the existing fast ownership handshake before a disk wait."""
        deadline = time.monotonic()+4
        while not (self.directory/'ready.json').exists():
            require(time.monotonic() < deadline, 'caretaker ownership handoff timed out')
            bounded(hot_check)
            self.pulse(capacity)
            time.sleep(.02)
        bounded(hot_check)
        self.pulse(capacity)

    def capture(self):
        proof = self.directory/'containment.json'
        if proof.exists() and getattr(self, 'backup_job', None) is None and getattr(self, 'backup_cgroup', None) is None:
            value = read_json(proof)
            if native_windows():
                windows = module('browser-small-windows')
                self.backup_job = windows.duplicate_job(self.process.pid, value['job_handle'])
                census = windows.query_job(self.backup_job)
                require(census['kill_on_close'] and census['pids'] == [value['worker_pid']], 'supervisor Job handoff failed')
            else:
                self.backup_cgroup = Path(value['cgroup'])
                self.backup_cgroup_stat = self.backup_cgroup.stat()
                require([self.backup_cgroup_stat.st_dev, self.backup_cgroup_stat.st_ino] == value['cgroup_identity'],
                        'actual cgroup ownership handoff mismatch')

    def finish(self, sample=lambda: None):
        self.cleanup_proven = False
        if getattr(self, 'lock_owner', None):
            stopped = self.lock_owner.request(dict(command='finish'), sample, seconds=15)
            if self.backup_job:
                windows = module('browser-small-windows')
                require(not bounded(lambda: windows.query_job(self.backup_job))['pids'], 'backup Job not empty')
                windows.close(self.backup_job)
            result = read_json(self.directory/'cleanup.json')
            require(result['cleanup_errors'] == [] and result['remaining'] == [], 'owned cleanup unproven')
            self.cleanup_proven = True
            require(not stopped.get('caretaker_failed') and not getattr(self,'phase_failed',None) and
                    result['errors'] == [] and result['remaining'] == [], 'owned cleanup failed')
            return
        errors = []
        close_error = None
        try:self.process.stdin.close()
        except BaseException as error:
            close_error = error
            errors.append(str(error))
        try:
            try:
                self.capture()
            except BaseException as error:
                errors.append(str(error))
            until = time.monotonic()+12
            while True:
                try:
                    bounded(sample)
                except BaseException as error:
                    errors.append(str(error))
                try:
                    code = self.process.wait(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= until:
                        errors.append('caretaker cleanup deadline')
                        code = 1
                        break
            # Independently held queried ownership survives caretaker failure. Close
            # the Job only after stop/census, and kill only this recorded cgroup.
            if getattr(self, 'backup_job', None):
                windows = module('browser-small-windows')
                bounded(lambda: windows.terminate(self.backup_job))
                require(not bounded(lambda: windows.query_job(self.backup_job))['pids'], 'backup Job not empty')
                windows.close(self.backup_job)
            if getattr(self, 'backup_cgroup', None):
                require(os.path.samestat(self.backup_cgroup_stat, self.backup_cgroup.stat()), 'cgroup identity drift')
                bounded(lambda: (self.backup_cgroup/'cgroup.kill').write_text('1'))
                require(not bounded(lambda: census_linux(self.backup_cgroup)), 'backup cgroup not empty')
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=1)
            try:
                result = read_json(self.directory/'cleanup.json')
            except (OSError, ValueError) as error:
                raise ValueError('owned stop/reap/caretaker failure; cleanup proof missing: '+str(error)) from error
            require(result['cleanup_errors'] == [] and result['remaining'] == [] and
                    all(result.get(key) is True for key in ('controller_eof','monitor_threads_joined','capture_writers_reaped')) and
                    self.process.stdin.closed is True, 'owned cleanup unproven')
            require(self.process.poll() is not None, 'caretaker reap unproven')
            self.cleanup_proven = True
            if close_error is not None:
                for note in errors[1:]:
                    try:close_error.add_note('caretaker cleanup: '+note)
                    except BaseException:pass
                raise close_error
            require(not errors, '; '.join(errors))
            require(code == 0, 'owned stop/reap/caretaker failure')
            require(result['errors'] == [] and result['remaining'] == [], 'owned cleanup failed')
        except BaseException as cleanup_error:
            if close_error is not None and cleanup_error is not close_error:
                try:close_error.add_note('caretaker cleanup proof: '+repr(cleanup_error)[:2048])
                except BaseException:pass
                raise close_error from cleanup_error
            raise



class ControllerInput:
    """Own a raw read end; poll without a buffered-stdin reader at shutdown."""
    def __init__(self):
        self.fd = os.dup(sys.stdin.fileno())

    def read(self, timeout=.1):
        if native_windows():
            until = time.monotonic()+timeout
            while True:
                available = windows_bootstrap.pipe_available(self.fd)
                if available < 0:
                    return b''
                if available:
                    return os.read(self.fd, 1)
                if time.monotonic() >= until:
                    return None
                time.sleep(.01)
        import select
        return os.read(self.fd, 1) if select.select([self.fd], [], [], timeout)[0] else None

    def close(self):
        os.close(self.fd)


def caretaker(plan_path, operation, directory):
    """Own worker lifetime. Never accepts an arbitrary argv or uses global names."""
    plan = read_json(plan_path, 64*1024**2)
    directory = Path(directory)
    job, nested_job, cgroup, process, remaining, errors = None, None, None, None, [], []
    incoming = None
    controller_eof = False
    worker_reaped = False
    identity_handles_uncertain = False
    worker_assigned = False
    windows = module('browser-small-windows') if native_windows() else None
    beat, stopped = [time.monotonic()], threading.Event()
    def emergency_stop():
        # Independent from blocking filesystem/Job census/receipt operations.
        while not stopped.wait(.05):
            if time.monotonic()-beat[0] >= 5:
                try:
                    if job:
                        bounded(lambda: windows.terminate(job))
                    elif cgroup:
                        bounded(lambda: (cgroup/'cgroup.kill').write_text('1'))
                    if process and ((windows and not worker_assigned) or (not windows and not cgroup)):
                        bounded(process.kill)  # held suspended child, or Linux pre-handoff child
                except BaseException as error:
                    os.write(2, ('emergency owned stop failed: '+str(error)+'\n').encode())
                return
    watchdog = threading.Thread(target=emergency_stop, daemon=True)
    watchdog.start()
    try:
        incoming = ControllerInput()
        if windows:
            independent_windows_lock_owner()  # caretaker also stays outside worker Jobs
            job = windows_bootstrap.create_job(windows)
        if windows is None:
            # Parent must provide an actual delegated cgroup-v2 root; never fall
            # back to killpg alone (runner commands create their own sessions).
            parent = Path(plan['linux_cgroup_parent'])
            require(parent.is_absolute() and not parent.is_symlink() and
                    (parent/'cgroup.controllers').is_file(), 'delegated cgroup-v2 required')
            require_cgroup_v2(parent)
            cgroup = parent / ('chopper-native-'+str(os.getpid()))
            cgroup.mkdir()
            require((cgroup/'cgroup.kill').exists(), 'kernel cgroup.kill required')
            libc = ctypes.CDLL(None, use_errno=True)
            require(libc.prctl(36, 1, 0, 0, 0) == 0, 'subreaper unavailable')
        env = dict(os.environ, CHOPPER_NATIVE_WORKER='1', CHOPPER_NATIVE_CARETAKER_PID=str(os.getpid()))
        with (directory/'worker-stdout.log').open('wb') as out, (directory/'worker-stderr.log').open('wb') as err:
            command = [sys.executable, '-B', str(HERE/'native-scale-runner.py'),
                       '_worker', str(plan_path), str(operation), str(directory)]
            if windows:
                process = windows_bootstrap.SuspendedWorker()
                process.start(command, out, err, env)
                process.assign(job)
                worker_assigned = True
                process.resume()
            else:
                process = subprocess.Popen(command, env=env, stdout=out, stderr=err,
                                           start_new_session=True)
        deadline = time.monotonic()+4
        while not (directory/'startup.json').exists():
            require(process.poll() is None and time.monotonic() < deadline, 'containment startup failed')
            time.sleep(.02)
        startup = read_json(directory/'startup.json')
        require(startup['pid'] == process.pid, 'worker PID handoff mismatch')
        if windows:
            nested_job = windows.duplicate_job(process.pid, startup['handle'])
            nested = bounded(lambda: windows.query_job(nested_job))
            require(nested['kill_on_close'] and nested['pids'] == [process.pid], 'real nested Job ownership required')
            census = bounded(lambda: windows.query_job(job))
            require(census['kill_on_close'] and census['pids'] == [process.pid], 'real Job ownership required')
            actual = bounded(lambda: windows.process_identity(process.pid))
            require(actual['parent'] == os.getpid() and
                    Path(actual['image']).resolve() == Path(sys.executable).resolve(), 'actual worker process identity mismatch')
        else:
            (cgroup/'cgroup.procs').write_text(str(process.pid))
            require(bounded(lambda: census_linux(cgroup)) == [process.pid], 'actual cgroup handoff failed')
        publish(directory/'containment.json', dict(worker_pid=process.pid,
                cgroup=str(cgroup) if cgroup else None, job_census=census if windows else None,
                cgroup_identity=[cgroup.stat().st_dev, cgroup.stat().st_ino] if cgroup else None,
                job_handle=job if windows else None))
        publish(directory/'owner-sample.json', dict(monotonic=time.monotonic(), pids=[process.pid]),mutable=True)
        beat[0] = time.monotonic()
        until = time.monotonic()+4
        while not (directory/'supervisor-ready.json').exists():
            require(process.poll() is None and time.monotonic() < until, 'supervisor ownership handoff timed out')
            time.sleep(.02)
        publish(directory/'ready.json', dict(pid=process.pid))
        last = time.monotonic()
        complete = False
        previous_identities = [actual] if windows else []
        while True:
            pulse = incoming.read()
            if pulse == b'':
                controller_eof = True
                require(complete or (directory/'worker-result.json').exists(), 'controller death/pipe closed before cleanup')
                break
            if pulse is not None:
                last = time.monotonic()
            require(time.monotonic()-last < 5, 'controller census/identity/hash monitor stale')
            # Hot identity pulses cannot manufacture a new capacity observation.
            capacity_fresh(read_control_json(directory/'capacity-sample.json'))
            if windows:
                value = bounded(lambda: windows.query_job(job))
                require(value['kill_on_close'], 'Job containment drift')
                remaining = value['pids']
                identity_deadline = time.monotonic()+2
                observed = bounded(lambda: windows.job_processes(job,value,previous_identities,
                    deadline=identity_deadline),seconds=max(0,identity_deadline-time.monotonic()))
                remaining = observed['census']['pids']
                identities = observed['processes']
                previous_identities = identities
            else:
                remaining = bounded(lambda: census_linux(cgroup))
                identities = bounded(lambda: linux_processes(remaining))
            # Use the maintained atomic writer; the independent watchdog above
            # remains armed while this filesystem operation blocks.
            observation = dict(monotonic=time.monotonic(), pids=remaining, processes=identities)
            publish(directory/'owner-sample.json', observation,mutable=True)
            with (directory/'process-census.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(observation)+'\n')
            # The watchdog pulse is from a completed real process census.
            # Pipe traffic from the controller cannot keep a blocked census alive.
            beat[0] = time.monotonic()
            if (directory/'worker-result.json').exists():
                complete = True
            require(process.poll() is None or complete, 'worker died without result')
    except BaseException as error:
        errors.append(str(error))
        identity_handles_uncertain = bool(getattr(error, 'process_handle_close_uncertain', False))
        try:
            failure_traceback = ''.join(traceback.format_exception(type(error), error, error.__traceback__))[-8192:]
            create(directory/'caretaker-failure.json', dict(error=str(error), traceback=failure_traceback))
        except BaseException as diagnostic_error:
            errors.append('caretaker failure diagnostic unavailable: '+str(diagnostic_error))
    finally:
        cleanup_errors = ['process identity handle close unproven'] if identity_handles_uncertain else []
        def attempt(call):
            try:
                return bounded(call)
            except BaseException as error:
                errors.append(str(error))
                cleanup_errors.append(str(error))
        if job:
            attempt(lambda: windows.terminate(job))
        if cgroup:
            attempt(lambda: (cgroup/'cgroup.kill').write_text('1'))
        if process:
            if (windows and not worker_assigned) or (not windows and cgroup is None):
                if attempt(process.poll) is None:
                    attempt(process.kill)  # also owns a possibly unassigned suspended child
            def reap():
                nonlocal worker_reaped
                process.wait(timeout=1)
                worker_reaped = True
            attempt(reap)
        def owned_census():
            if windows:
                require(job is not None, 'missing owned bootstrap Job')
                value = windows.query_job(job)
                require(value['kill_on_close'], 'bootstrap Job containment drift')
                return value['pids']
            return census_linux(cgroup)
        until = time.monotonic()+8
        while time.monotonic() < until:
            remaining = attempt(owned_census)
            if not remaining:
                break
            beat[0] = time.monotonic()
            time.sleep(.05)
        if remaining is None or remaining:
            errors.append('owned descendants not proven empty')
            cleanup_errors.append('owned descendants not proven empty')
        if windows is None:
            # Reap adopted descendants, in addition to Popen's direct child.
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if not pid:
                        errors.append('adopted child not reaped')
                        cleanup_errors.append('adopted child not reaped')
                        break
                except ChildProcessError:
                    break
        if nested_job:
            attempt(lambda: windows.close(nested_job))
        if windows and process:
            attempt(process.close)
        if job:
            attempt(lambda: windows.close(job))
        if incoming:
            attempt(incoming.close)
        stopped.set()
        watchdog.join(timeout=.2)
        if watchdog.is_alive() or pending_calls():
            errors.append('caretaker monitor threads not joined')
            cleanup_errors.append('caretaker monitor threads not joined')
        try:
            from .native_tiny import budget_usage
            create(directory/'cleanup.json', dict(errors=errors, remaining=remaining, cleanup_errors=cleanup_errors,
                   controller_eof=controller_eof, monitor_threads_joined=not watchdog.is_alive() and not pending_calls(),
                   capture_writers_reaped=worker_reaped, metadata_usage=budget_usage()))
        except BaseException as error:
            errors.append('cleanup proof retention failed: '+str(error))
            cleanup_errors.append('cleanup proof retention failed: '+str(error))
        if windows is None and cleanup_errors:
            # After controller death this process owns the last inherited flock.
            # Exiting here would admit competing work before cleanup is proven.
            retain_host_lock('Linux')
    return int(bool(errors))


def census_linux(cgroup):
    require(cgroup is not None, 'missing owned cgroup')
    result = set()
    require(cgroup.is_dir() and not cgroup.is_symlink(), 'owned cgroup disappeared')
    def error(value):
        raise value
    for folder, directories, _ in os.walk(cgroup, onerror=error):
        require(all(not Path(folder, name).is_symlink() for name in directories), 'cgroup descendant symlink')
        values = Path(folder, 'cgroup.procs').read_text().split()
        result.update(int(v) for v in values)
        require(len(result) <= 256, 'owned process census bound')
    return sorted(result)


def require_cgroup_v2(parent):
    """Kernel filesystem identity, not a directory with fabricated cgroup files."""
    require(all(not p.is_symlink() for p in (parent, *parent.parents)), 'cgroup symlink ancestry')
    libc = ctypes.CDLL(None, use_errno=True)
    buffer = (ctypes.c_long * 32)()
    require(libc.statfs(os.fsencode(parent), ctypes.byref(buffer)) == 0 and buffer[0] == 0x63677270,
            'actual cgroup-v2 filesystem required')


def linux_processes(pids):
    result = []
    for pid in pids:
        try:
            # comm may contain spaces and parentheses; fields follow the last ).
            fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        except FileNotFoundError:
            continue
        result.append(dict(pid=pid, parent=int(fields[1]), process_group=int(fields[2]),
                           session=int(fields[3]), started_ticks=int(fields[19])))
    return result
