"""Durable sequential validation; see docs/validation-runner.md."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import traceback
from typing import Callable, Literal, NamedTuple


_SESSION_JOB = None


def contain_session():
    """Windows controller crash containment. Children inherit this unnamed Job.

    Keep its non-inheritable handle until process exit: closing the last handle
    kills remaining members even when Python finally blocks never execute.
    Ordinary runner callers keep their existing lifecycle.
    """
    global _SESSION_JOB
    if os.name != 'nt' or _SESSION_JOB is not None:
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                    ('max_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling', wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    _SESSION_JOB = handle


def owned_windows_job():
    """Native census of this session's held Job; unsupported callers deny.

    The handle is only for duplication by the SMALL supervisor, which must
    independently query it and retain its duplicate through cleanup.
    """
    if os.name != 'nt' or _SESSION_JOB is None:
        raise OSError('No owned native Windows session Job')
    import importlib.util
    spec = importlib.util.spec_from_file_location('small_windows', Path(__file__).with_name('browser-small-windows.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.query_job(_SESSION_JOB), handle=int(_SESSION_JOB))


def write_json(path, value, *, replace=None):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    (os.replace if replace is None else replace)(temporary, path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity_key(root, filename, *, absolute):
    """The runner's absolute or root-relative record key, for either host spelling."""
    import ntpath
    import posixpath
    from pathlib import PureWindowsPath
    root, filename = str(root), str(filename)
    windows = PureWindowsPath(root).is_absolute()
    paths = ntpath if windows else posixpath
    if not paths.isabs(root) or (windows and ntpath.splitdrive(filename)[0] and not ntpath.isabs(filename)):
        raise ValueError('absolute identity root and unambiguous file path required')
    full = paths.normpath(paths.join(root, filename))
    return full if absolute else paths.relpath(full, root)


def identity_record(root, records, filename):
    """Consume current absolute and historical relative keys without alias ambiguity."""
    import ntpath
    from pathlib import PureWindowsPath
    windows = PureWindowsPath(str(root)).is_absolute()
    def key(name):
        value = identity_key(root, name, absolute=True)
        return ntpath.normcase(value) if windows else value
    wanted = key(filename)
    matches = [value for name, value in records.items()
               if not name.startswith(('missing:', 'error:')) and key(name) == wanted]
    if (len(matches) != 1 or not isinstance(matches[0], dict) or 'sha256' not in matches[0]
            or matches[0].get('directory')):
        raise ValueError('one exact runner file identity required: '+str(filename))
    record = matches[0]
    if 'resolved' in record and key(record['resolved']) != wanted:
        raise ValueError('runner resolved file identity mismatch: '+str(filename))
    return record


def identity(root, patterns):
    files = {}
    for pattern in patterns:
        absolute = Path(pattern).is_absolute()
        matches = ({Path(pattern)} if Path(pattern).exists() else set()) if absolute else set(root.glob(pattern))
        if not matches:
            files['missing:' + pattern] = None
        paths = set(matches)
        for path in matches:
            if (not absolute and path.is_dir() and not path.is_symlink()
                    and not any(parent in matches for parent in path.parents)):
                def traversal_error(error):
                    raise error

                try:
                    for folder, directories, filenames in os.walk(path, onerror=traversal_error):
                        paths.update(Path(folder) / name for name in directories + filenames)
                except OSError as error:
                    files['error:' + str(path.relative_to(root))] = str(error)
        for path in sorted(paths):
            name = identity_key(root, path, absolute=absolute)
            try:
                if path.is_dir():
                    if absolute:
                        raise OSError('absolute patterns must name regular files')
                    if path.is_symlink():
                        raise OSError('directory symlinks require explicit file inputs')
                    files[name] = {'directory': True}
                elif path.is_file():
                    before = path.stat()
                    hashed = digest(path)
                    after = path.stat()
                    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                    if any(getattr(before, key) != getattr(after, key) for key in fields):
                        raise OSError('file changed while hashing')
                    files[name] = {'sha256': hashed, 'mtime_ns': after.st_mtime_ns,
                                   'ctime_ns': after.st_ctime_ns, 'size': after.st_size,
                                   'device': after.st_dev, 'inode': after.st_ino,
                                   'resolved': str(path.resolve())}
                else:
                    raise OSError('not a regular file or directory')
            except OSError as error:
                files['error:' + name] = str(error)
    return dict(sorted(files.items()))


def incomplete_identity(value):
    return any(key.startswith(('missing:', 'error:')) for key in value)


def stop(process):
    if sys.platform == 'linux':
        if process.returncode is not None:
            return  # A reaped leader no longer anchors this numeric group ID.
        try:
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        except ChildProcessError as error:
            raise OSError('command was reaped outside its owning runner') from error
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def linux_process_identity(pid):
    with open(f'/proc/{pid}/stat', 'rb') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096 or b')' not in raw:
        raise OSError('cannot establish owned process identity')
    fields = raw.rsplit(b')', 1)[1].split()
    if len(fields) < 20 or not fields[2].isdigit() or not fields[19].isdigit():
        raise OSError('cannot establish owned process identity')
    return {'pid': pid, 'process_group': int(fields[2]), 'linux_start_ticks': int(fields[19])}


def wait_command(process, timeout, deadline):
    if sys.platform != 'linux':
        return process.wait(timeout=timeout)
    # Retain the exited leader as a zombie until group cleanup. Reaping first
    # would allow PID/PGID reuse before a later killpg.
    import select
    descriptor = os.pidfd_open(process.pid)
    try:
        if not select.select([descriptor], [], [], timeout)[0]:
            raise subprocess.TimeoutExpired(process.args, timeout)
        ended = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
        abandoned = False
        with os.scandir('/proc') as entries:
            for entry in entries:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(process.args, timeout)
                if not entry.name.isdecimal() or entry.name == str(process.pid):
                    continue
                try:
                    member = linux_process_identity(int(entry.name))
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if member['process_group'] == process.pid:
                    abandoned = True
                    break
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        if abandoned:
            raise OSError('command exited with an abandoned owned process group')
        # The one cleanup boundary in run() signals/reaps this retained leader.
        return ended.si_status if ended.si_code == os.CLD_EXITED else -ended.si_status
    finally:
        os.close(descriptor)


AttemptStatus = Literal['running', 'passed', 'failed', 'timeout', 'interrupted', 'invalidated']


class AttemptObservation(NamedTuple):
    id: str
    attempt: int
    status: AttemptStatus


class StatusObservation(NamedTuple):
    """Detached immutable checkpoint; no provenance maps or mutable state escape."""
    attempts: tuple[AttemptObservation, ...]
    terminal: bool


def run(plan_path, directory, guard=None, observe: Callable[[StatusObservation], None] | None = None,
        on_process=None):
    """Emit optional detached checkpoints after durable writes; callback errors propagate.

    Observation work scales with attempts, never with input/artifact map sizes.
    Optional on_process receives None immediately before Popen and the returned
    object immediately afterward, so an owning caller can fence uncertain spawn
    and retain handles until its cleanup. Defaults preserve standalone behavior.
    """
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    root = Path(plan['root']).resolve()
    steps = plan['steps']
    ids = [step['id'] for step in steps]
    if len(ids) != len(set(ids)) or any(not name.replace('-', '').replace('_', '').isalnum() for name in ids):
        raise ValueError('step IDs must be unique simple names')
    for index, step in enumerate(steps):
        if any(dep not in ids[:index] for dep in step.get('depends', [])):
            raise ValueError('dependencies must precede their step')
        if step['timeout_seconds'] <= 0 or not step['inputs']:
            raise ValueError('positive timeout and explicit inputs required')
        if step.get('stdin_file') is not None and step['stdin_file'] not in step['inputs']:
            raise ValueError('stdin_file must be a declared input')
    if plan['batch_timeout_seconds'] <= 0:
        raise ValueError('positive batch deadline required')
    # Scheduling estimates and provenance are mandatory even for tiny batches.
    for key in ('estimated_seconds', 'estimated_disk_bytes', 'toolchains', 'features', 'fixtures'):
        if key not in plan:
            raise ValueError('missing plan field: ' + key)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / 'runner.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode('ascii'))
    os.close(descriptor)
    retain_lock = False
    try:
        manifest = directory / 'manifest.json'
        if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')) != plan:
            raise ValueError('resume requires the original plan; use a new batch directory')
        write_json(manifest, plan)
        status_path = directory / 'status.json'
        state = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {'attempts': []}
        def checkpoint(terminal=False):
            if observe is not None:
                observe(StatusObservation(tuple(AttemptObservation(a['id'], a['attempt'], a['status'])
                                                for a in state['attempts']), terminal))
        if observe is not None:
            write_json(status_path, state)
        checkpoint()
        started = time.monotonic()
        environment = hashlib.sha256(json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest()
        runner_hash = digest(Path(__file__).resolve())
        passed = {}
        for step in steps:
            before = identity(root, step['inputs'])
            command = step['argv'][0]
            executable = shutil.which(str(root / command) if os.path.dirname(command) else command)
            executable = str(Path(executable).resolve()) if executable else None
            try:
                executable_hash = digest(Path(executable)) if executable else None
            except OSError as error:
                raise ValueError('cannot hash executable; select its real installed path, not an OS app alias: ' + str(executable)) from error
            runtime = {'environment_sha256': environment, 'executable': executable,
                       'executable_sha256': executable_hash, 'runner_sha256': runner_hash}
            dependencies = {dep: passed.get(dep) for dep in step.get('depends', [])}
            if any(value is None for value in dependencies.values()):
                break
            previous = next((a for a in reversed(state['attempts']) if a['id'] == step['id']), None)
            if (previous and previous['status'] == 'passed' and previous['inputs'] == before
                    and not incomplete_identity(before)
                    and previous.get('runtime') == runtime
                    and previous['dependencies'] == dependencies
                    and previous['artifacts'] == identity(root, step.get('artifacts', []))):
                passed[step['id']] = previous['attempt']
                continue
            remaining = plan['batch_timeout_seconds'] - (time.monotonic() - started)
            if remaining <= 0:
                break
            number = len(state['attempts']) + 1
            attempt = {'id': step['id'], 'attempt': number, 'status': 'running',
                       'inputs': before, 'dependencies': dependencies, 'started_unix': time.time(),
                       'argv': step['argv'], 'artifacts': {}}
            attempt['runtime'] = runtime
            state['attempts'].append(attempt)
            state['summary'] = {'passed': len(passed), 'incomplete': len(steps) - len(passed)}
            write_json(status_path, state)
            checkpoint()
            process = None
            tick = time.monotonic()
            try:
                if incomplete_identity(before):
                    raise OSError('declared input missing')
                if guard is not None:
                    guard()
                input_stream = ((root / step['stdin_file']).open('rb') if step.get('stdin_file')
                                else contextlib.nullcontext(None))
                with (directory / f'{number}-stdout.log').open('wb') as stdout, (directory / f'{number}-stderr.log').open('wb') as stderr, input_stream as stdin:
                    if on_process is not None:on_process(None)
                    process = subprocess.Popen([executable or command, *step['argv'][1:]], cwd=root, stdin=stdin, stdout=stdout, stderr=stderr,
                                               start_new_session=os.name != 'nt',
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if on_process is not None:on_process(process)
                    attempt['process_identity'] = {'pid': process.pid, 'owner_pid': os.getpid()}
                    if sys.platform == 'linux':
                        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                        attempt['process_identity'].update(linux_process_identity(process.pid))
                    try:
                        deadline = time.monotonic() + min(step['timeout_seconds'], remaining)
                        while True:
                            if guard is not None:
                                guard()
                            left = deadline - time.monotonic()
                            if left <= 0:
                                raise subprocess.TimeoutExpired(process.args, 0)
                            try:
                                code = wait_command(process, min(left, 0.2) if guard else left, deadline)
                                break
                            except subprocess.TimeoutExpired:
                                if time.monotonic() >= deadline:
                                    raise
                        attempt.update(exit_code=code, status='passed' if code == 0 else 'failed')
                    except subprocess.TimeoutExpired:
                        attempt.update(status='timeout', exit_code=None)
            except KeyboardInterrupt:
                attempt.update(status='interrupted', exit_code=None)
            except OSError as error:
                attempt.update(status='failed', error=str(error),
                               exit_code=process.returncode if process else None)
            finally:
                if process is not None:
                    try:
                        if sys.platform == 'linux':
                            if process.returncode is None:
                                stop(process)
                        elif process.poll() is None:
                            stop(process)
                    except BaseException as error:
                        # Set this before any fallible evidence write or callback.
                        retain_lock = True
                        attempt['cleanup_unresolved'] = {
                            'process_identity': attempt.get('process_identity', {'pid': process.pid}),
                            'error_type': type(error).__name__, 'error': str(error),
                            'traceback': traceback.format_exc(),
                        }
                        attempt.update(status='failed', error=attempt.get('error', 'owned command cleanup unresolved'))
                    if attempt.get('exit_code') is None:
                        attempt['exit_code'] = process.returncode
                attempt['duration_seconds'] = time.monotonic() - tick
                if retain_lock:
                    attempt['artifacts'] = {}
                    attempt['identity_recheck'] = 'skipped: owned command cleanup unresolved'
                else:
                    attempt['artifacts'] = identity(root, step.get('artifacts', []))
                    if attempt['status'] == 'passed' and incomplete_identity(attempt['artifacts']):
                        attempt.update(status='failed', error='declared artifact missing')
                    if identity(root, step['inputs']) != before:
                        attempt['status'] = 'invalidated'
                completed = len(passed) + (attempt['status'] == 'passed')
                state['summary'] = {'passed': completed, 'incomplete': len(steps) - completed}
                write_json(status_path, state)
                checkpoint()
            if attempt['status'] != 'passed':
                break
            passed[step['id']] = number
        # A later command can mutate inputs belonging to an earlier successful step.
        for step in steps:
            if step['id'] not in passed:
                continue
            attempt = next(a for a in state['attempts'] if a['attempt'] == passed[step['id']])
            if (retain_lock or identity(root, step['inputs']) != attempt['inputs']
                    or any(dep not in passed for dep in step.get('depends', []))):
                attempt.update(status='invalidated', error='batch cleanup unresolved' if retain_lock
                               else 'batch inputs or dependencies changed')
                del passed[step['id']]
        state['summary'] = {'passed': len(passed), 'incomplete': len(steps) - len(passed)}
        write_json(status_path, state)
        checkpoint(terminal=True)
        print(json.dumps(state['summary']))
        return 0 if len(passed) == len(steps) else 1
    finally:
        if not retain_lock:
            lock.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.plan, args.directory.resolve()))
