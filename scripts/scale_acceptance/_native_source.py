"""Private sealed Windows source component; not Windows session admission."""
import ctypes as C
from collections import deque
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading
from ._native_file import _windows_api
from .verify import require


def _metadata(s):
    # Keep Python's full (possibly 128-bit) file ID namespace.
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns)


class _SourcePool:
    def __init__(self, lock, roots, entries):
        """entries is the parent's exact sealed directory AND regular-file census.

        This internal adapter consumes stat-like values, not a new manifest schema.
        The root owns descriptor admission; constructing this cannot admit a Run.
        """
        require(os.name == 'nt', 'source handles require Windows')
        self.lock = lock
        self.roots = tuple(Path(p) for p in roots)
        self.entries = {Path(p): _metadata(s) for p, s in entries.items()}
        require(self.roots and len(set(self.roots)) == len(self.roots) and
                all(p.is_absolute() for p in self.roots), 'exact absolute source roots required')
        require(not any(a != b and a.is_relative_to(b) for a in self.roots for b in self.roots),
                'overlapping source roots')
        require(all(p in self.entries and stat.S_ISDIR(self.entries[p][2]) for p in self.roots) and
                all(any(p.is_relative_to(r) for r in self.roots) for p in self.entries) and
                all(v[1] and (stat.S_ISDIR(v[2]) or stat.S_ISREG(v[2])) for v in self.entries.values()),
                'invalid sealed source census')
        self.pending = deque(p for p, s in self.entries.items() if stat.S_ISREG(s[2]))
        self.handles, self.primed_charge = {}, 0
        self.mutex = threading.RLock()
        self.inflight = 0
        self.poisoned = self.closed = self.ready = self.uncertain = False
        # Registration arms the ORIGINAL external owner before any native call.
        self.bounded(lambda: lock.register_source_pool(self))

    def poison(self):
        with self.mutex:
            self.poisoned = True

    def check(self):
        with self.mutex:
            require(not self.poisoned and not self.closed, 'source pool poisoned/closed')

    @contextmanager
    def operation(self, closing=False):
        with self.mutex:
            require(self.inflight == 0 and not self.closed, 'source operation not quiescent')
            if not closing:
                self.check()
            self.inflight += 1
        try:
            yield
            if not closing:
                self.check()
        except BaseException:
            self.poison()
            raise
        finally:
            with self.mutex:
                self.inflight -= 1

    def bounded(self, call, *, closing=False):
        from .native_scale_host import bounded
        def invoke():
            with self.operation(closing=closing):
                return call()
        return bounded(invoke, fence=self)

    def _ancestry(self):
        for root in self.roots:
            for p in (root, *root.parents):
                s = p.lstat()
                require(stat.S_ISDIR(s.st_mode) and not getattr(s, 'st_file_attributes', 0) & 0x400,
                        'source ancestor reparse/special file')

    def _census(self):
        self.check()
        self._ancestry()
        seen = {}
        def visit(p):
            s = p.lstat()
            require(not getattr(s, 'st_file_attributes', 0) & 0x400 and
                    (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)), 'source reparse/special file')
            require(_metadata(s) == self.entries.get(p), 'sealed source identity/metadata/name drift')
            seen[p] = _metadata(s)
            return s
        def error(value):
            raise value
        for root in self.roots:
            visit(root)
            for folder, directories, files in os.walk(root, onerror=error, followlinks=False):
                # Recheck the actual directory immediately before using its children.
                require(stat.S_ISDIR(visit(Path(folder)).st_mode), 'source directory drift')
                for name in directories + files:
                    visit(Path(folder, name))
        self._ancestry()
        require(seen == self.entries, 'sealed source namespace drift')
        self.check()

    def _close_handle(self, handle):
        # On failure the numeric value may already have been reused: never retry.
        try:
            kernel = _windows_api()[0]
            if not kernel.CloseHandle(handle):
                raise C.WinError(C.get_last_error())
        except BaseException:
            self.uncertain = True
            raise

    def _open(self, p):
        import msvcrt
        kernel = _windows_api()[0]
        for q in (p, *p.parents):
            require(not getattr(q.lstat(), 'st_file_attributes', 0) & 0x400, 'source reparse point')
        self.check()
        fd, duplicate = None, C.c_void_p()
        invalid = C.c_void_p(-1).value
        handle = kernel.CreateFileW(str(p), 0x80, 7, None, 3, 0x200000, None)
        if handle == invalid:
            raise C.WinError(C.get_last_error())
        # This operation remains in flight across late returns and all transfers.
        try:
            self.check()
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_NOINHERIT)
            opened = os.fstat(fd)
            expected = self.entries[p]
            # Windows derives execute bits from path names, but omits them in fstat.
            require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) ==
                    (expected[0], expected[1], expected[3], expected[4]) and
                    stat.S_ISREG(opened.st_mode) and opened.st_ino,
                    'source native file identity/metadata drift')
            process = kernel.GetCurrentProcess()
            self.check()
            if not kernel.DuplicateHandle(process, handle, process, C.byref(duplicate), 0, False, 2):
                raise C.WinError(C.get_last_error())
            self.check()
            require(duplicate.value, 'missing source duplicate')
            require(_metadata(p.lstat()) == self.entries[p], 'source opening path binding drift')
            for q in (p, *p.parents):
                require(not getattr(q.lstat(), 'st_file_attributes', 0) & 0x400, 'source reparse point')
            self.handles[p] = duplicate.value
            duplicate.value = None
        finally:
            try:
                if fd is None:
                    self._close_handle(handle)
                else:
                    try:
                        os.close(fd)
                    except BaseException:
                        self.uncertain = True
                        raise
            finally:
                if duplicate.value:
                    self._close_handle(duplicate.value)

    def allocation(self, p, observed):
        """Fresh queries on the bound object; caller owns a complete census operation."""
        self.check()
        require(self.inflight == 1 and _metadata(observed) == self.entries.get(p), 'source sample binding drift')
        kernel, Standard, Attributes, Compression = _windows_api()
        handle = self.handles[p]
        def query(kind, value):
            self.check()
            if not kernel.GetFileInformationByHandleEx(handle, kind, C.byref(value), C.sizeof(value)):
                raise C.WinError(C.get_last_error())
            self.check()
            return value
        attributes = query(9, Attributes()).attributes
        require(not attributes & 0x400, 'source reparse point')
        info = query(1, Standard())
        require(not info.directory and not info.deleted and info.size == observed.st_size and
                info.size >= 0 and info.allocation >= 0, 'invalid source allocation')
        allocated = query(8, Compression()).allocated if attributes & (0x200 | 0x800) else info.allocation
        after = p.lstat()
        require(allocated >= 0 and not getattr(after, 'st_file_attributes', 0) & 0x400 and
                _metadata(after) == self.entries[p], 'source allocation/path binding drift')
        self.check()
        return allocated

    def prime_step(self, checkpoint):
        """One <=256-file chunk, within the ordinary two-second operation bound.

        checkpoint runs lock/deadline/volume/free/partial-capacity admission before
        AND after the chunk. Full census is separately bounded by finish_prime.
        """
        def prime():
            self.lock.check()
            checkpoint(self.primed_charge)
            for _ in range(min(256, len(self.pending))):
                p = self.pending[0]
                self._open(p)
                s = p.lstat()
                self.primed_charge += max(s.st_size, self.allocation(p, s))
                self.pending.popleft()
            self.lock.check()
            checkpoint(self.primed_charge)
            return not self.pending
        return self.bounded(prime)

    def finish_prime(self, checkpoint):
        def finish():
            require(not self.pending, 'incomplete source prime')
            self.lock.check()
            checkpoint(self.primed_charge)
            self._census()
            self.lock.check()
            checkpoint(self.primed_charge)
            self.ready = True
        return self.bounded(finish)

    def sample(self, roots):
        require(tuple(roots) == self.roots and self.ready, 'complete prepared source roots required')
        self._census()
        charges = {}
        for p in self.handles:
            s = p.lstat()
            charges[(str(p), s.st_dev, s.st_ino)] = max(s.st_size, self.allocation(p, s))
        self._census()  # Final namespace/reparse checks precede receipt publication.
        return charges

    def close(self):
        def close():
            require(not self.uncertain, 'source close ownership uncertain')
            self.ready = False
            while self.handles:
                p, handle = self.handles.popitem()
                self._close_handle(handle)
            self.closed = True
        if not self.closed:
            self.bounded(close, closing=True)
        require(self.closed and not self.inflight and not self.uncertain, 'source cleanup unproven')
