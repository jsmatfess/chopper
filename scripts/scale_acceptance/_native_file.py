"""Private metadata-only allocation measurement for native storage accounting."""
import os
import ntpath
import stat
from functools import cache
from .verify import require

def _allocated_bytes(p, observed):
    if os.name != 'nt':
        return getattr(observed, 'st_blocks', 0)*512
    return _windows_allocation(p, observed)



class _AllocationChange(ValueError):
    """Checked mutable observation race; default callers still deny it."""
    def __init__(self, path, samples, *, kind='replacement', query=None):
        super().__init__('native file identity/metadata drift')
        self.filename, self.samples, self.kind = str(path), samples, kind
        fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_nlink','st_file_attributes')
        self.add_note(repr(dict(api='GetFileInformationByHandleEx/fstat/lstat',path=str(path)[:768],kind=kind))[:1024])
        if query is not None:self.add_note('allocation_query='+repr(query)[:1000])
        for label,(value,allocated) in zip(('observed','opened','after'),samples):
            self.add_note(repr(dict(snapshot=label,stat={name:getattr(value,name,None) for name in fields},
                                   allocated=allocated))[:1024])

def _directory_size(p, observed):
    """Directory logical EOF from a bound handle, separate from file allocation."""
    if os.name != 'nt':
        return observed.st_size
    import ctypes as C
    import msvcrt

    require(stat.S_ISDIR(observed.st_mode), 'directory EOF requires directory')
    paths = (p, *p.parents)
    for path in paths:
        require(not path.lstat().st_file_attributes & 0x400, 'owned reparse point')
    kernel, Standard, Attributes, _ = _windows_api()
    handle = kernel.CreateFileW(str(p), 0x80, 7, None, 3, 0x2200000, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    fd = None
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_NOINHERIT)
        def query(kind, value):
            if not kernel.GetFileInformationByHandleEx(handle, kind, C.byref(value), C.sizeof(value)):
                raise C.WinError(C.get_last_error())
            return value
        attributes = query(9, Attributes()).attributes
        require(attributes & 0x10 and not attributes & 0x400, 'directory handle reparse/type drift')
        before = query(1, Standard())
        opened, after = os.fstat(fd), p.lstat()
        fields = ('st_dev', 'st_ino', 'st_mtime_ns', 'st_nlink')
        # Windows path ctime retains creation time, available as descriptor birthtime.
        require(opened.st_ino and stat.S_ISDIR(opened.st_mode) and stat.S_ISDIR(after.st_mode) and
                after.st_mode == observed.st_mode and
                getattr(opened, 'st_birthtime_ns', opened.st_ctime_ns) ==
                after.st_ctime_ns == observed.st_ctime_ns and
                all(all(getattr(value, name) == getattr(observed, name) for name in fields)
                    for value in (opened, after)), 'directory native identity/metadata drift')
        final = query(1, Standard())
        require(before.directory and final.directory and not before.deleted and not final.deleted and
                before.size == final.size >= 0 and before.links == final.links == observed.st_nlink,
                'directory EOF/metadata drift')
        for path in paths:
            require(not path.lstat().st_file_attributes & 0x400, 'owned reparse point')
        return final.size
    finally:
        if fd is not None:
            os.close(fd)
        elif not kernel.CloseHandle(handle):
            raise C.WinError(C.get_last_error())


@cache
def _windows_api():
    """Cache only FFI setup, never file attributes, identity or allocation."""
    import ctypes as C

    class Standard(C.Structure):
        _fields_ = [('allocation', C.c_int64), ('size', C.c_int64),
                    ('links', C.c_uint32), ('deleted', C.c_ubyte), ('directory', C.c_ubyte)]

    class Attributes(C.Structure):
        _fields_ = [('attributes', C.c_uint32), ('tag', C.c_uint32)]

    class Compression(C.Structure):
        _fields_ = [('allocated', C.c_int64), ('format', C.c_uint16),
                    ('unit', C.c_ubyte), ('chunk', C.c_ubyte), ('cluster', C.c_ubyte),
                    ('reserved', C.c_ubyte*3)]

    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [C.c_wchar_p, C.c_uint32, C.c_uint32, C.c_void_p,
                                  C.c_uint32, C.c_uint32, C.c_void_p]
    kernel.CreateFileW.restype = C.c_void_p
    kernel.GetFileInformationByHandleEx.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint32]
    kernel.GetFileInformationByHandleEx.restype = C.c_int
    kernel.CloseHandle.argtypes = [C.c_void_p]
    kernel.CloseHandle.restype = C.c_int
    kernel.GetCurrentProcess.restype = C.c_void_p
    kernel.DuplicateHandle.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p,
                                      C.POINTER(C.c_void_p), C.c_uint32, C.c_int, C.c_uint32]
    kernel.DuplicateHandle.restype = C.c_int
    return kernel, Standard, Attributes, Compression


def _windows_ancestry_names(p):
    """Build immutable names once; every use still queries fresh metadata."""
    names = [str(p)]
    while (parent := ntpath.dirname(names[-1])) != names[-1]:
        if not parent:
            if names[-1] != '.':
                names.append('.')
            break
        names.append(parent)
    return names


def _windows_allocation(p, observed):
    import ctypes as C
    import msvcrt

    paths = _windows_ancestry_names(p)
    # OPEN_REPARSE_POINT protects the leaf; reject junctions in its ancestry too.
    _reparse_ancestry(paths)
    require(stat.S_ISREG(observed.st_mode), 'allocation requires regular file')
    kernel, Standard, Attributes, Compression = _windows_api()
    # READ_ATTRIBUTES, share read/write/delete, OPEN_EXISTING, OPEN_REPARSE_POINT.
    handle = kernel.CreateFileW(str(paths[0]), 0x80, 7, None, 3, 0x200000, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    fd = None
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        def query(kind, value):
            if not kernel.GetFileInformationByHandleEx(handle, kind, C.byref(value), C.sizeof(value)):
                raise C.WinError(C.get_last_error())
            return value
        attributes = query(9, Attributes()).attributes  # FileAttributeTagInfo
        require(not attributes & 0x400, 'owned reparse point')
        info = query(1, Standard())  # FileStandardInfo
        require(not info.directory and info.size >= 0 and info.allocation >= 0,
                'invalid native file allocation')
        allocated = info.allocation
        if attributes & (0x200 | 0x800):  # sparse or compressed: physical allocation
            allocated = query(8, Compression()).allocated  # FileCompressionInfo
        require(allocated >= 0, 'invalid native file allocation')
        # fstat uses Python's own Windows volume/file-ID representation (including
        # 128-bit IDs), avoiding a second, incompatible identity namespace.
        try:
            opened, after = os.fstat(fd), p.lstat()
            matched = (opened.st_ino != 0 and stat.S_ISREG(opened.st_mode) and
                       all((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) ==
                           (observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns)
                           for s in (opened, after)) and info.size == opened.st_size)
            # Even a retryable observation must complete the second fresh ancestry pass.
            _reparse_ancestry(paths)
        except FileNotFoundError:
            require(not info.deleted, 'invalid native file allocation')
            raise
        if info.deleted:
            identity = lambda value: (value.st_dev, value.st_ino)
            replaced_after_open = (info.links == 0 and observed.st_nlink == after.st_nlink == 1 and
                opened.st_nlink in (0, 1) and all(stat.S_ISREG(value.st_mode) and value.st_ino != 0
                    for value in (observed, opened, after)) and
                not (observed.st_file_attributes | opened.st_file_attributes | after.st_file_attributes) & 0x400 and
                observed.st_dev == opened.st_dev == after.st_dev and
                observed.st_mode == opened.st_mode == after.st_mode and
                identity(observed) == identity(opened) != identity(after) and
                observed.st_size == info.size == opened.st_size and
                observed.st_mtime_ns == opened.st_mtime_ns)
            require(replaced_after_open, 'invalid native file allocation')
            # Only the mutable sampler may retry; preserve the retired handle's
            # measured charge and require a complete fresh visible-root census.
            raise _AllocationChange(p, ((observed, 0), (opened, allocated), (after, 0)),
                kind='retired-replacement',query=dict(size=info.size,allocation=info.allocation,links=info.links,deleted=bool(info.deleted),attributes=attributes))
        if not matched:
            identity = lambda value: (value.st_dev, value.st_ino)
            regular = all(stat.S_ISREG(value.st_mode) and value.st_ino != 0 and
                          value.st_nlink == 1 for value in (observed, opened, after)) and all(
                              not value.st_file_attributes & 0x400 for value in (observed, opened, after))
            same_volume = observed.st_dev == opened.st_dev == after.st_dev
            stable_mode = observed.st_mode == opened.st_mode == after.st_mode
            bound_current = identity(opened) == identity(after)
            replacement = (identity(observed) != identity(opened) and
                           info.size == opened.st_size == after.st_size and
                           opened.st_mtime_ns == after.st_mtime_ns)
            growth = (identity(observed) == identity(opened) and
                      observed.st_ctime_ns == after.st_ctime_ns and
                      0 <= observed.st_size <= info.size <= opened.st_size <= after.st_size and
                      observed.st_mtime_ns <= opened.st_mtime_ns <= after.st_mtime_ns)
            if regular and same_volume and stable_mode and info.links == 1 and bound_current and (replacement or growth):
                # Preserve measured handle allocation and every observed logical highwater.
                # An old replacement's unqueried allocation remains unknown, never zero.
                raise _AllocationChange(p, ((observed, 0), (opened, allocated), (after, 0)),
                                        kind='growth' if growth else 'replacement',
                                        query=dict(size=info.size,allocation=info.allocation,links=info.links,deleted=bool(info.deleted),attributes=attributes))
            require(False, 'native file identity/metadata drift')
        return allocated
    finally:
        if fd is not None:
            os.close(fd)
        elif not kernel.CloseHandle(handle):
            raise C.WinError(C.get_last_error())


def _reparse_ancestry(paths):
    for path in paths:
        require(not os.lstat(path).st_file_attributes & 0x400, 'owned reparse point')
