"""Narrow native Windows Job and process identity queries; no name enumeration."""
import ctypes
import os
import stat
import time
from ctypes import wintypes as W
from functools import cache
from pathlib import Path

MAX_PIDS = 256


class ControlFileError(OSError):
    def __init__(self, api, path, handle=None, winerror=None, detail=''):
        super().__init__(f'{api}: path={path}; handle={handle}; winerror={winerror}; {detail}')
        self.api, self.path, self.handle, self.winerror = api, str(path), handle, winerror
        self.pid = os.getpid()


class ControlFileCloseError(ControlFileError):
    process_handle_close_uncertain = True


@cache
def _control_api():
    from scale_acceptance import _native_file
    dll, _, attributes, _ = _native_file._windows_api()
    dll.SetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    dll.SetFileInformationByHandle.restype = ctypes.c_int
    return dll, attributes


def _control_ancestors(path):
    values = []
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ControlFileError('metadata', parent, detail='control ancestor is not a plain directory')
        values.append((info.st_dev, info.st_ino))
    return values


def _control_close(fd, handle, path):
    try:
        os.close(fd)
    except OSError as error:
        raise ControlFileCloseError('close', path, handle, getattr(error, 'winerror', error.errno), str(error)) from error


def _control_open(path, access):
    import msvcrt
    dll, attributes = _control_api()
    handle = dll.CreateFileW(str(path), access, 7, None, 3, 0x200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ControlFileError('CreateFileW', path, winerror=ctypes.get_last_error())
    try:
        value = attributes()
        if not dll.GetFileInformationByHandleEx(handle, 9, ctypes.byref(value), ctypes.sizeof(value)):
            raise ControlFileError('GetFileInformationByHandleEx', path, handle, ctypes.get_last_error())
        if value.attributes & (0x400 | 0x10):
            raise ControlFileError('metadata', path, handle, detail='control handle is reparse/directory')
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), handle
    except BaseException:
        if not dll.CloseHandle(handle):
            raise ControlFileCloseError('CloseHandle', path, handle, ctypes.get_last_error())
        raise


def read_control_snapshot(path, maximum, *, charge=None):
    """Read one bounded immutable file version without blocking its publisher."""
    if type(maximum) is not int or not 0 < maximum <= 1024**2:
        raise ValueError('Control snapshot byte bound')
    path = Path(path).absolute()
    ancestors = _control_ancestors(path)
    if charge is not None:charge(None)  # Admit the open attempt before native acquisition.
    if os.name == 'nt':
        fd, handle = _control_open(path, 0x80000000)
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        handle = fd
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink > 1:
            raise ControlFileError('metadata', path, handle, detail='regular control snapshot without hardlinks required')
        if charge is not None:charge(before.st_size)  # Charge this held version before reading.
        raw = os.read(fd, maximum+1)
        after = os.fstat(fd)
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
        if (len(raw) > maximum or len(raw) != before.st_size or after.st_nlink > 1
                or any(getattr(before, k) != getattr(after, k) for k in keys)):
            raise ControlFileError('read', path, handle, detail='oversized, short, hardlinked or changed control snapshot')
    except OSError as error:
        if isinstance(error, ControlFileError):
            raise
        raise ControlFileError('read', path, handle, getattr(error, 'winerror', error.errno), str(error)) from error
    finally:
        _control_close(fd, handle, path)
    if _control_ancestors(path) != ancestors:
        raise ControlFileError('metadata', path, detail='control ancestor identity changed')
    return raw


def _control_rename_information(target):
    encoded = str(target).encode('utf-16-le')
    if not encoded or len(encoded) > 65534 or '\0' in str(target):
        raise ValueError('Control rename path bound')
    # FileNameLength excludes NUL; the Win32 filename still needs a terminator
    # inside the submitted buffer, independent of structure alignment padding.
    class Rename(ctypes.Structure):
        _fields_ = [('flags', ctypes.c_uint32), ('root', ctypes.c_void_p),
                    ('length', ctypes.c_uint32), ('name', ctypes.c_uint16 * (len(encoded)//2+1))]
    if ctypes.sizeof(ctypes.c_void_p) != 8 or (Rename.root.offset, Rename.length.offset, Rename.name.offset) != (8, 16, 20):
        raise OSError('Control rename requires Windows x64 ABI')
    info = Rename(flags=3, root=None, length=len(encoded))
    ctypes.memmove(ctypes.addressof(info)+20, encoded, len(encoded))
    return info, ctypes.sizeof(info)


def replace_control_snapshot(source, destination):
    """Replace only an explicit owned mutable-control leaf, preserving old readers."""
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if source.parent != destination.parent or source == destination:
        raise ControlFileError('rename', source, detail='distinct same-directory control names required')
    ancestors = _control_ancestors(source)
    for path in (source, destination):
        if path.exists() or path.is_symlink():
            value = path.lstat()
            if (not stat.S_ISREG(value.st_mode) or value.st_nlink > 1
                    or getattr(value, 'st_file_attributes', 0) & 0x400):
                raise ControlFileError('metadata', path, detail='plain control file without hardlinks required')
    if os.name != 'nt':
        os.replace(source, destination)
    else:
        dll, _ = _control_api()
        fd, handle = _control_open(source, 0x10080)  # DELETE | READ_ATTRIBUTES
        try:
            before, held = source.lstat(), os.fstat(fd)
            keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
            if (not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400
                    or before.st_nlink > 1 or held.st_nlink > 1
                    or not stat.S_ISREG(held.st_mode) or any(getattr(before, k) != getattr(held, k) for k in keys)):
                raise ControlFileError('metadata', source, handle, detail='source handle identity mismatch')
            info, size = _control_rename_information(destination)
            if not dll.SetFileInformationByHandle(handle, 22, ctypes.byref(info), size):
                raise ControlFileError('SetFileInformationByHandle', source, handle, ctypes.get_last_error(), 'destination='+str(destination))
            current = destination.lstat()
            if (source.exists() or source.is_symlink() or not stat.S_ISREG(current.st_mode)
                    or current.st_nlink > 1 or getattr(current, 'st_file_attributes', 0) & 0x400
                    or current.st_ino != held.st_ino):
                raise ControlFileError('rename', destination, handle, detail='exact source identity not moved')
        except OSError as error:
            if isinstance(error, ControlFileError):
                raise
            raise ControlFileError('rename', source, handle, getattr(error, 'winerror', error.errno), str(error)) from error
        finally:
            _control_close(fd, handle, source)
    if _control_ancestors(destination) != ancestors:
        raise ControlFileError('metadata', destination, detail='control ancestor identity changed')


class Basic(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', W.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                ('active', W.DWORD), ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]


class Extended(ctypes.Structure):
    _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('memory', ctypes.c_size_t * 4)]


class PBI(ctypes.Structure):
    _fields_ = [('reserved', ctypes.c_void_p), ('peb', ctypes.c_void_p),
                ('reserved2', ctypes.c_void_p * 2), ('pid', ctypes.c_size_t), ('parent', ctypes.c_size_t)]


@cache
def ntdll():
    dll = ctypes.WinDLL('ntdll')
    dll.NtQueryInformationProcess.argtypes = [W.HANDLE, W.ULONG, ctypes.c_void_p, W.ULONG, ctypes.c_void_p]
    dll.NtQueryInformationProcess.restype = W.LONG
    return dll


@cache
def kernel():
    if os.name != 'nt':
        raise OSError('SMALL requires native Windows')
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'QueryInformationJobObject': ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p], W.BOOL),
        'GetProcessTimes': ([W.HANDLE] + [ctypes.POINTER(W.FILETIME)] * 4, W.BOOL),
        'GetProcessId': ([W.HANDLE], W.DWORD),
        'GetExitCodeProcess': ([W.HANDLE, ctypes.POINTER(W.DWORD)], W.BOOL),
        'ProcessIdToSessionId': ([W.DWORD, ctypes.POINTER(W.ULONG)], W.BOOL),
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'GetCurrentProcess': ([], W.HANDLE),
        'DuplicateHandle': ([W.HANDLE, W.HANDLE, W.HANDLE, ctypes.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'IsProcessInJob': ([W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)], W.BOOL),
        'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
        'TerminateJobObject': ([W.HANDLE, W.UINT], W.BOOL),
        'QueryFullProcessImageNameW': ([W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(dll, name).argtypes = args
        getattr(dll, name).restype = result
    return dll


def checked(value, *, api=None, pid=None):
    if not value:
        code = ctypes.get_last_error() if os.name == 'nt' else None
        error = OSError('Windows API failed: ' + str(code if code is not None else 'fake backend'))
        if api is not None:
            error.api, error.pid, error.winerror = api, pid, code
            error.add_note(f'Windows observation: api={api}, pid={pid}, winerror={code}')
        raise error
    return value


class IncompleteJobCensus(OSError):
    def __init__(self, assigned, count):
        self.assigned=assigned; self.count=count
        super().__init__('Job census incomplete: assigned='+str(assigned)+' count='+str(count))


def query_job(handle, max_pids=MAX_PIDS, backend=None):
    if type(max_pids) is not int or not 1 <= max_pids <= MAX_PIDS:
        raise OSError('Job census buffer limit')
    dll = backend or kernel()
    info = Extended()
    checked(dll.QueryInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info), None))
    class Census(ctypes.Structure):
        _fields_ = [('assigned', W.DWORD), ('count', W.DWORD), ('pids', ctypes.c_size_t * max_pids)]
    census = Census()
    checked(dll.QueryInformationJobObject(handle, 3, ctypes.byref(census), ctypes.sizeof(census), None))
    if census.assigned > max_pids or census.count > max_pids:
        raise OSError('Job census oversized')
    if census.count > census.assigned:
        raise OSError('Invalid Job census counts')
    pids = list(census.pids[:census.count])
    if len(set(pids)) != len(pids) or any(pid <= 0 for pid in pids):
        raise OSError('Invalid Job census')
    if census.count < census.assigned:
        raise IncompleteJobCensus(int(census.assigned), int(census.count))
    # Breakaway flags are forbidden even if kill-on-close is also present.
    return {'kill_on_close': bool(info.basic.flags & 0x2000) and not bool(info.basic.flags & 0x1800),
            'flags': int(info.basic.flags), 'pids': pids}


def duplicate_job(pid, handle):
    dll = kernel()
    process = checked(dll.OpenProcess(0x40, False, pid))  # PROCESS_DUP_HANDLE
    duplicate = W.HANDLE()
    try:
        checked(dll.DuplicateHandle(process, handle, dll.GetCurrentProcess(), ctypes.byref(duplicate), 0, False, 2))
    finally:
        dll.CloseHandle(process)
    return duplicate.value


class ProcessImageQueryError(OSError):
    def __init__(self, winerror, pid=None):
        super().__init__('QueryFullProcessImageNameW failed: '+str(winerror)+'; pid='+str(pid))
        self.winerror = winerror
        self.api, self.pid = 'QueryFullProcessImageNameW', pid


def _held_identity(dll, handle, pid):
    image = ctypes.create_unicode_buffer(32768)
    length = W.DWORD(len(image))
    if not dll.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
        raise ProcessImageQueryError(ctypes.get_last_error(), pid)
    # NtQueryInformationProcess returns the inherited PID and creation time
    # comes from GetProcessTimes; both are queried on the same held handle.
    info = PBI()
    if ntdll().NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None) != 0:
        raise OSError('Process parent query failed')
    stamps = [W.FILETIME() for _ in range(4)]
    checked(dll.GetProcessTimes(handle, *(ctypes.byref(value) for value in stamps)),
            api='GetProcessTimes', pid=pid)
    return {'pid': pid, 'parent': int(info.parent), 'image': image.value,
            'created': stamps[0].dwHighDateTime << 32 | stamps[0].dwLowDateTime}


def _held_birth(dll, handle, pid=None):
    stamps = [W.FILETIME() for _ in range(4)]
    checked(dll.GetProcessTimes(handle, *(ctypes.byref(value) for value in stamps)),
            api='GetProcessTimes', pid=pid)
    return stamps[0].dwHighDateTime << 32 | stamps[0].dwLowDateTime


def held_identity(handle,pid):
    dll=kernel()
    if dll.WaitForSingleObject(handle,0)!=258:raise OSError('Held process not current')
    image = ctypes.create_unicode_buffer(32768)
    length = W.DWORD(len(image))
    checked(dll.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)))
    # NtQueryInformationProcess returns the inherited PID and creation time
    # comes from GetProcessTimes; both are queried on the same held handle.
    info = PBI()
    if ntdll().NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None) != 0:
        raise OSError('Process parent query failed')
    stamps = [W.FILETIME() for _ in range(4)]
    checked(dll.GetProcessTimes(handle, *(ctypes.byref(value) for value in stamps)))
    session=W.ULONG()
    checked(dll.ProcessIdToSessionId(pid,ctypes.byref(session)))
    if int(info.pid)!=pid or dll.WaitForSingleObject(handle,0)!=258:
        raise OSError('Held process disappeared or PID mismatch')
    return {'pid': pid, 'parent': int(info.parent), 'image': image.value, 'session':int(session.value),
            'created': stamps[0].dwHighDateTime << 32 | stamps[0].dwLowDateTime}


def process_identity(pid):
    dll = kernel()
    handle = checked(dll.OpenProcess(0x1000, False, pid), api='OpenProcess', pid=pid)
    try:
        return _held_identity(dll, handle, pid)
    finally:
        try:
            checked(dll.CloseHandle(handle), api='CloseHandle', pid=pid)
        except OSError as error:
            failure = ProcessHandleCloseError(str(error))
            failure.api, failure.pid, failure.winerror = error.api, error.pid, error.winerror
            raise failure from error


class ProcessHandleCloseError(OSError):
    process_handle_close_uncertain = True


def job_processes(job, census, previous=(), backend=None, *, deadline=None):
    """Return identities for a fresh exact Job, reconciling ended snapshots."""
    dll = backend or kernel()
    known = {value['pid']: value['created'] for value in previous}
    identities, held, attempted, retired = {}, {}, set(), []
    def fresh_census():
        value = query_job(job, backend=dll)
        if set(value['pids']) & {row['pid'] for row in retired}:
            raise OSError('Job identity reconciliation reappearing member')
        return value
    pending = census['pids']
    try:
        while True:
            for pid in pending:
                if deadline is not None and time.monotonic() >= deadline:
                    raise OSError('Job identity reconciliation deadline')
                if pid in attempted or len(attempted) >= MAX_PIDS:
                    raise OSError('Job identity reconciliation bound/reappearing member')
                attempted.add(pid)
                try:
                    handle = checked(dll.OpenProcess(0x101000, False, pid), api='OpenProcess', pid=pid)
                except OSError as error:
                    if getattr(error, 'winerror', None) != 87:
                        raise
                    fresh = fresh_census()
                    if not fresh['kill_on_close'] or pid in fresh['pids']:
                        raise
                    # No held object exists here. Record only snapshot retirement;
                    # every current member still needs a full held identity below.
                    retired.append(dict(pid=pid, previous_birth=known.get(pid), api='OpenProcess',
                                        winerror=87, fresh_census=fresh))
                    continue
                held[pid] = handle
                birth = _held_birth(dll, handle, pid)
                if pid in known and birth != known[pid]:
                    raise OSError('Job member PID reused')
                member = W.BOOL()
                checked(dll.IsProcessInJob(handle, job, ctypes.byref(member)))
                if not member.value and known.get(pid) != birth:
                    raise OSError('Unknown held process outside exact Job')
                try:
                    value = _held_identity(dll, handle, pid)
                except ProcessImageQueryError as error:
                    state = dll.WaitForSingleObject(handle, 0)
                    error.held_observation = dict(pid=pid, birth=birth, member=bool(member.value),
                        previous_birth=known.get(pid), wait_state=state, image_error=error.winerror)
                    error.add_note('held observation: '+str(error.held_observation))
                    fresh = fresh_census()
                    error.fresh_census = fresh
                    error.add_note('fresh exact Job: '+str(fresh))
                    # A process may exit during the fresh Job query. Reobserve
                    # this same held object after the census, never reuse state.
                    try:
                        post_state = dll.WaitForSingleObject(handle, 0)
                        exit_code = W.DWORD()
                        exit_ok = bool(dll.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
                        exit_error = ctypes.get_last_error() if not exit_ok and os.name == 'nt' else None
                        post_birth = _held_birth(dll, handle, pid)
                    except BaseException as proof_error:
                        error.add_note('post-census held proof failed: '+repr(proof_error))
                        raise error from proof_error
                    error.post_census_held_observation = dict(pid=pid, birth=post_birth,
                        wait_state=post_state, exit_api=exit_ok, exit_error=exit_error, exit_code=exit_code.value)
                    error.add_note('post-census held observation: '+str(error.post_census_held_observation))
                    first = dict(error.post_census_held_observation)
                    rounds = 0
                    while (deadline is not None and time.monotonic() < deadline-.05 and
                           exit_ok and exit_code.value != 259 and post_birth == birth and
                           fresh['kill_on_close'] and post_state in (0,258) and
                           (post_state != 0 or pid in fresh['pids'])):
                        # Reserve the endpoint for checked handle closure; this is
                        # the caller's existing deadline, never a fresh wait budget.
                        left = deadline-.05-time.monotonic()
                        if left <= 0:break
                        if post_state == 258:
                            dll.WaitForSingleObject(handle,min(20,max(1,int(left*1000))))
                        else:
                            time.sleep(min(.01,left))
                        fresh = fresh_census()
                        post_state = dll.WaitForSingleObject(handle,0)
                        exit_ok = bool(dll.GetExitCodeProcess(handle,ctypes.byref(exit_code)))
                        exit_error = ctypes.get_last_error() if not exit_ok and os.name == 'nt' else None
                        post_birth = _held_birth(dll,handle,pid)
                        rounds += 1
                    error.fresh_census = fresh
                    error.post_census_held_observation = dict(pid=pid,birth=post_birth,
                        wait_state=post_state,exit_api=exit_ok,exit_error=exit_error,exit_code=exit_code.value)
                    if deadline is not None:
                        error.add_note('bounded exit reconciliation: '+str(dict(first=first,
                            last=error.post_census_held_observation,fresh_census=fresh,
                            observations=rounds,deadline=deadline,expired=time.monotonic() >= deadline-.05)))
                    if (post_state != 0 or not exit_ok or exit_code.value == 259 or post_birth != birth or
                            pid in fresh['pids'] or not fresh['kill_on_close']):
                        raise
                    continue
                if not member.value or value['created'] != birth:
                    raise OSError('Held live Job identity mismatch')
                identities[pid] = value
            fresh = fresh_census()
            if not fresh['kill_on_close']:
                raise OSError('Job containment drift during identity census')
            for pid in set(identities) - set(fresh['pids']):
                if (dll.WaitForSingleObject(held[pid], 0) != 0 or
                        _held_birth(dll, held[pid], pid) != identities[pid]['created']):
                    raise OSError('Disappeared Job member not proven exited')
                del identities[pid]
            pending = sorted(set(fresh['pids']) - set(identities))
            if not pending:
                if deadline is not None and time.monotonic() >= deadline:
                    raise OSError('Job identity reconciliation deadline')
                result = dict(census=fresh, processes=list(identities.values()))
                if retired:
                    result['retired_snapshots'] = retired
                return result
    except BaseException as error:
        error.completed_processes = [dict(pid=v['pid'], created=v['created']) for v in identities.values()]
        error.retired_snapshots = list(retired)
        raise
    finally:
        failures = []
        for pid, handle in reversed(list(held.items())):
            try:
                checked(dll.CloseHandle(handle), api='CloseHandle', pid=pid)
            except OSError as error:
                failures.append(dict(pid=pid, winerror=error.winerror))
        if failures:
            error = ProcessHandleCloseError('Job identity handle close unproven: '+str(failures))
            error.api, error.pid, error.winerror = 'CloseHandle', failures[0]['pid'], failures[0]['winerror']
            error.completed_processes = [dict(pid=v['pid'], created=v['created']) for v in identities.values()]
            error.retired_snapshots = list(retired)
            raise error


def terminate(handle):
    checked(kernel().TerminateJobObject(handle, 91))


def close(handle):
    checked(kernel().CloseHandle(handle))


def stop_descendants(job, owner, deadline):
    """Stop exact held Job members, preserving the worker that owns private readers."""
    dll = kernel()
    while True:
        pids = query_job(job)['pids']
        if pids == [owner]:
            return pids
        if owner not in pids or time.monotonic() >= deadline:
            raise OSError('Private cleanup Job census/deadline failed')
        for pid in pids:
            if pid == owner:
                continue
            if time.monotonic() >= deadline:
                raise OSError('Private descendant cleanup deadline')
            handle = dll.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
            if not handle:
                if pid not in query_job(job)['pids']:
                    continue
                raise OSError('Cannot hold owned descendant for cleanup')
            try:
                status = dll.WaitForSingleObject(handle, 0)
                if status == 0:
                    continue
                if status != 258:
                    raise OSError('Owned descendant wait failed')
                member = W.BOOL()
                checked(dll.IsProcessInJob(handle, job, ctypes.byref(member)))
                if not member.value:
                    raise OSError('Cleanup handle no longer belongs to exact Job')
                terminated = dll.TerminateProcess(handle, 91)
                error = ctypes.get_last_error() if not terminated and os.name == 'nt' else None
                # An exiting process can reject termination before its handle signals.
                remaining = max(0, min(1000, int((deadline-time.monotonic())*1000)))
                if dll.WaitForSingleObject(handle, remaining) != 0:
                    raise OSError('Owned descendant not reaped before cleanup deadline; termination error='+str(error))
            finally:
                checked(dll.CloseHandle(handle))
        time.sleep(.01)
