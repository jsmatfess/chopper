"""Allocation controls; --native DIRECTORY uses only fresh tiny Windows files."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from contextlib import ExitStack
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scale_acceptance import _native_file as allocation
from scale_acceptance import native_scale_identity as identity
from scale_acceptance.native_scale_monitor import Storage, Monitor, _prepare_source
from scale_acceptance import native_scale_monitor as monitor
from scale_acceptance import _native_source as source
from scale_acceptance import native_scale_host as host
from scale_acceptance import guard


def observed_close(held, kind, close, failures):
    """A component close failure keeps the existing original lock owner."""
    def run(value):
        try:
            result = close(value)
        except BaseException as error:
            held.cleanup_uncertain = True
            failures.append(dict(kind=kind, value=value, error=repr(error)))
            raise
        if kind == 'HANDLE' and not result:
            held.cleanup_uncertain = True
            failures.append(dict(kind=kind, value=value, error=C.get_last_error()))
        return result
    return run


class AllocationControls(unittest.TestCase):
    def setUp(self):
        allocation._windows_api.cache_clear()
        self.addCleanup(allocation._windows_api.cache_clear)
        self.real_lstat = Path.lstat
        self.observed = NS(st_dev=3, st_ino=2**90, st_size=1, st_mtime_ns=4,
                           st_mode=stat.S_IFREG | 0o600, st_file_attributes=0, st_nlink=1, st_ctime_ns=5)
        self.p = Mock(parents=[])
        self.p.__str__ = Mock(return_value="C:\\file")
        self.p.lstat.return_value = self.observed
        self.kernel = NS(CreateFileW=Mock(return_value=123), CloseHandle=Mock(return_value=1),
                         GetCurrentProcess=Mock(return_value=456), DuplicateHandle=Mock(),
                         GetFileInformationByHandleEx=Mock(side_effect=self.query))
        self.attributes, self.allocated = 0, 4096
        self.calls = []
        self.os = NS(name='nt', O_RDONLY=0, O_NOINHERIT=0x80, fstat=Mock(return_value=self.observed), close=Mock(),
                     lstat=Mock(side_effect=lambda name: self.p.lstat() if name == str(self.p) else self.observed))
        for context in (patch.object(C, 'WinDLL', return_value=self.kernel, create=True),
                        patch.object(C, 'WinError', side_effect=lambda code: OSError(code, 'native failure'), create=True),
                        patch.object(C, 'get_last_error', return_value=5, create=True),
                        patch.dict(sys.modules, msvcrt=NS(open_osfhandle=Mock(return_value=7))),
                        patch.object(allocation, 'os', self.os)):
            context.start()
            self.addCleanup(context.stop)

    def query(self, handle, kind, pointer, size):
        self.calls.append(kind)
        value = pointer._obj
        self.assertEqual(size, C.sizeof(value))
        self.assertEqual(size, {9: 8, 1: 24, 8: 16}[kind])
        if kind == 9:
            value.attributes = self.attributes
        elif kind == 1:
            value.size, value.allocation, value.links = 1, 4096, 1
        elif kind == 8:
            value.allocated = self.allocated
        else:
            self.fail('unexpected query')
        return 1

    def measure(self):
        return allocation._allocated_bytes(self.p, self.observed)

    def test_normal_sparse_compressed_and_large_allocation(self):
        self.assertEqual(self.measure(), 4096)
        for attributes, allocated in ((0x200, 0), (0x800, 8192), (0x200, 2**40)):
            self.attributes, self.allocated = attributes, allocated
            self.assertEqual(self.measure(), allocated)
        self.assertIn(8, self.calls)
        self.assertEqual(self.os.close.call_count, 4)
        self.kernel.CreateFileW.assert_called_with(str(self.p), 0x80, 7, None, 3, 0x200000, None)

    def test_recursive_snapshot_matches_full_metadata_and_walks_each_directory_once(self):
        from collections import Counter
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ('[top]/nested/deeper', 'second', '.hidden'):
                (root/name).mkdir(parents=True)
            names = ['[top]/nested/value', 'second/a[1]', 'a]', '.hidden/value']
            if os.name != 'nt':
                names += ['literal*', 'literal?']
            for name in names:
                (root/name).write_bytes(b'x')
            expected = guard.frozen_metadata(root, ['**/*'])
            walked = Counter()
            real_walk = os.walk
            def walk(*args, **kwargs):
                for folder, directories, files in real_walk(*args, **kwargs):
                    walked[str(folder)] += 1
                    yield folder, directories, files
            with patch.object(identity, 'os', NS(name='posix')), patch.object(guard.os, 'walk', side_effect=walk):
                self.assertEqual(identity.frozen_metadata(root, ['**/*']), expected)
            self.assertTrue(walked)
            self.assertTrue(all(count == 1 for count in walked.values()), walked)
            with patch.object(identity, 'os', NS(name='posix')):
                self.assertEqual(identity.frozen_metadata(root, ['second/*']),
                                 guard.frozen_metadata(root, ['second/*']))

    def test_recursive_snapshot_preserves_empty_symlink_and_special_file_denials(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(identity, 'os', NS(name='posix')):
            root = Path(directory).resolve()
            with self.assertRaisesRegex(ValueError, 'frozen input missing'):
                identity.frozen_metadata(root, ['**/*'])
            target = root/'target'
            target.mkdir()
            try:
                (root/'link').symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symlink creation unavailable')
            for function in (guard.frozen_metadata, identity.frozen_metadata):
                with self.assertRaisesRegex(ValueError, 'symlink/escape'):
                    function(root, ['**/*'])
            (root/'link').unlink()
            if hasattr(os, 'mkfifo'):
                os.mkfifo(root/'fifo')
                with self.assertRaisesRegex(ValueError, 'regular file/directory'):
                    identity.frozen_metadata(root, ['**/*'])

    def directory(self):
        self.observed = NS(st_dev=3, st_ino=2**90, st_size=0, st_mtime_ns=4, st_ctime_ns=5,
                           st_nlink=1, st_mode=stat.S_IFDIR | 0o777, st_file_attributes=0x10)
        self.p.lstat.return_value = self.observed
        self.p.stat.return_value = self.observed
        self.os.fstat.return_value = NS(**{**vars(self.observed), 'st_mode': stat.S_IFDIR | 0o666})
        self.attributes, self.directory_eof = 0x10, 8192
        def query(handle, kind, pointer, size):
            result = self.query(handle, kind, pointer, size)
            if kind == 1:
                pointer._obj.directory, pointer._obj.links, pointer._obj.size = 1, 1, self.directory_eof
            return result
        self.kernel.GetFileInformationByHandleEx.side_effect = query

    def test_directory_seals_use_bound_eof_across_raw_python_sizes(self):
        self.directory()
        self.os.fstat.return_value = NS(**{**vars(self.os.fstat.return_value),
            'st_ctime_ns': 99, 'st_birthtime_ns': self.observed.st_ctime_ns})
        expected = dict(path='directory', stat=identity.stat_fields(self.observed, 0))
        expected['stat']['size'] = 8192
        root = MagicMock()
        root.__truediv__.return_value = self.p
        with patch.object(identity, 'os', NS(name='nt')), patch.object(identity, 'path', return_value=self.p):
            for raw in (0, 8192):
                self.observed.st_size = raw
                self.assertIs(identity.sealed_stat(expected), self.p)
                self.assertEqual(identity.stamp(self.p)[2], 8192)
                for extra in ((), (self.observed.st_nlink, self.observed.st_file_attributes)):
                    snapshot = (3, 2**90, raw, 4, 5, self.observed.st_mode, *extra)
                    with patch.object(identity, 'raw_frozen_metadata', return_value={'directory': snapshot}):
                        actual = identity.frozen_metadata(root, ['directory'])['directory']
                        self.assertEqual(actual[2], 8192)
                        self.assertEqual(actual[6:], extra)
            self.directory_eof = 16384
            with self.assertRaisesRegex(ValueError, 'sealed stat drift'):
                identity.sealed_stat(expected)
        self.kernel.CreateFileW.assert_called_with(str(self.p), 0x80, 7, None, 3, 0x2200000, None)
        sys.modules['msvcrt'].open_osfhandle.assert_called_with(123, 0x80)

    def test_directory_handle_identity_and_non_size_metadata_drift_denied(self):
        self.directory()
        for field in ('st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink'):
            changed = NS(**{**vars(self.observed), field: 99})
            self.os.fstat.return_value = changed
            with self.assertRaisesRegex(ValueError, 'identity/metadata'):
                allocation._directory_size(self.p, self.observed)
            self.os.fstat.return_value = self.observed
        changed = NS(**{**vars(self.observed), 'st_mode': stat.S_IFDIR | 0o555})
        self.p.lstat.side_effect = [self.observed, changed]
        with self.assertRaisesRegex(ValueError, 'identity/metadata'):
            allocation._directory_size(self.p, self.observed)

    def test_directory_reparse_and_inflight_eof_change_denied(self):
        self.directory()
        self.attributes = 0x410
        with self.assertRaisesRegex(ValueError, 'reparse'):
            allocation._directory_size(self.p, self.observed)
        self.attributes = 0x10
        query = self.kernel.GetFileInformationByHandleEx.side_effect
        calls = 0
        def drift(handle, kind, pointer, size):
            nonlocal calls
            result = query(handle, kind, pointer, size)
            if kind == 1:
                calls += 1
                if calls == 2:
                    pointer._obj.size += 8192
            return result
        self.kernel.GetFileInformationByHandleEx.side_effect = drift
        with self.assertRaisesRegex(ValueError, 'EOF/metadata'):
            allocation._directory_size(self.p, self.observed)

    def test_directory_deleted_type_links_and_negative_eof_denied(self):
        self.directory()
        query = self.kernel.GetFileInformationByHandleEx.side_effect
        for field, value in (('deleted', 1), ('directory', 0), ('links', 2), ('size', -1)):
            def changed(handle, kind, pointer, size):
                result = query(handle, kind, pointer, size)
                if kind == 1:
                    setattr(pointer._obj, field, value)
                return result
            self.kernel.GetFileInformationByHandleEx.side_effect = changed
            with self.assertRaisesRegex(ValueError, 'EOF/metadata'):
                allocation._directory_size(self.p, self.observed)

    def test_directory_conversion_query_and_close_failures_close_exact_owner(self):
        self.directory()
        query = self.kernel.GetFileInformationByHandleEx.side_effect
        self.kernel.GetFileInformationByHandleEx.side_effect = lambda *args: 0
        with self.assertRaises(OSError):
            allocation._directory_size(self.p, self.observed)
        self.os.close.assert_called_once_with(7)
        self.kernel.GetFileInformationByHandleEx.side_effect = query
        self.os.close.side_effect = OSError('directory close denied')
        with self.assertRaisesRegex(OSError, 'directory close denied'):
            allocation._directory_size(self.p, self.observed)
        sys.modules['msvcrt'].open_osfhandle.side_effect = OSError('conversion denied')
        self.kernel.CloseHandle.return_value = 0
        with self.assertRaises(OSError):
            allocation._directory_size(self.p, self.observed)
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_storage_baseline_and_seal_use_native_allocation(self):
        # File-allocation integration uses real paths; directory EOF is a separate API.
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(identity,'_directory_size',side_effect=lambda p,s:s.st_size), \
                patch.object(allocation, '_windows_allocation', return_value=65536) as native:
            root = Path(directory).resolve()
            p = root/'file'
            p.write_bytes(b'x')
            s = p.stat()
            sealed = dict(path=str(p), stat=dict(dev=s.st_dev, ino=s.st_ino, allocated_bytes=65536))
            identity.sealed_stat(sealed)
            prior = dict(sum_bytes=65536, entry_count=1, carry_bytes=70000,
                         prior_sampled_aggregate_highwater_bytes=70000)
            baseline = dict(entries=[{**sealed, 'charge_bytes': 65536}], sum_bytes=65536,
                            roots=[dict(path=str(root), stat={})])
            storage = Storage(baseline, prior)
            self.assertEqual(storage.sample([root]), 70000)
            native.return_value = 131072
            self.assertEqual(storage.sample([root]), 70000+65536)
            native.return_value = 0
            p.unlink()
            self.assertEqual(storage.sample([root]), 70000+65536)
            native.side_effect = PermissionError('native allocation denied')
            p.write_bytes(b'x')
            with self.assertRaises(PermissionError): storage.sample([root])
            with self.assertRaises(PermissionError): identity.sealed_stat(sealed)

    def test_open_and_each_query_error_fail_closed(self):
        self.kernel.CreateFileW.return_value = C.c_void_p(-1).value
        with self.assertRaises(OSError): self.measure()
        self.os.close.assert_not_called()
        self.kernel.CreateFileW.return_value = 123
        self.attributes = 0x200
        for failed in (9, 1, 8):
            def query(handle, kind, pointer, size):
                return 0 if kind == failed else self.query(handle, kind, pointer, size)
            self.kernel.GetFileInformationByHandleEx.side_effect = query
            with self.assertRaises(OSError): self.measure()
        self.assertEqual(self.os.close.call_count, 3)

    def test_fstat_conversion_and_path_read_errors_close_handle(self):
        self.os.fstat.side_effect = OSError('fstat failed')
        with self.assertRaises(OSError): self.measure()
        self.os.close.assert_called_once_with(7)
        sys.modules['msvcrt'].open_osfhandle.side_effect = OSError('conversion failed')
        with self.assertRaises(OSError): self.measure()
        self.kernel.CloseHandle.assert_called_once_with(123)
        self.p.lstat.side_effect = PermissionError('metadata denied')
        with self.assertRaises(PermissionError): self.measure()

    def test_missing_path_fails_closed_before_open(self):
        error = FileNotFoundError(2, 'delete-pending name unavailable')
        self.p.lstat.side_effect = error
        with self.assertRaises(FileNotFoundError) as denied:
            self.measure()
        self.assertIs(denied.exception, error)
        self.kernel.CreateFileW.assert_not_called()

    def test_handle_and_path_replacement_fail_closed(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'):
            changed = NS(**{**vars(self.observed), field: 99})
            self.os.fstat.return_value = changed
            with self.assertRaisesRegex(ValueError, 'identity/metadata'): self.measure()
            self.os.fstat.return_value = self.observed
            self.p.lstat.side_effect = [self.observed, changed, changed]
            with self.assertRaisesRegex(ValueError, 'identity/metadata'): self.measure()
            self.p.lstat.side_effect = None

    def test_typed_mutable_change_still_denies_default_and_checks_post_ancestry(self):
        changed = NS(**{**vars(self.observed), 'st_ino': 2**110})
        self.os.fstat.return_value = changed
        self.p.lstat.return_value = changed
        with self.assertRaises(allocation._AllocationChange) as caught:
            self.measure()
        self.assertEqual(caught.exception.samples[1][1], 4096)
        self.assertEqual(caught.exception.samples[1][0].st_ino, 2**110)
        self.os.close.assert_called_once_with(7)
        reparse = NS(**{**vars(changed), 'st_file_attributes': 0x400})
        self.p.lstat.side_effect = [changed, changed, reparse]
        with self.assertRaisesRegex(ValueError, 'reparse') as denied:self.measure()
        self.assertNotIsInstance(denied.exception, allocation._AllocationChange)
        self.p.lstat.side_effect = None
        for field, value in (('st_nlink', 2), ('st_mode', stat.S_IFDIR|0o600), ('st_dev', 99)):
            self.p.lstat.return_value = NS(**{**vars(changed),field:value})
            with self.assertRaises(ValueError) as denied:self.measure()
            self.assertNotIsInstance(denied.exception, allocation._AllocationChange)
        self.p.lstat.return_value = changed
        self.os.close.side_effect = OSError('owned close not proven')
        with self.assertRaisesRegex(OSError, 'close not proven'):self.measure()

    def test_checked_growth_has_explicit_kind_and_bounded_three_snapshot_diagnostic(self):
        opened=NS(**{**vars(self.observed),'st_size':2,'st_mtime_ns':self.observed.st_mtime_ns+1})
        after=NS(**{**vars(opened),'st_size':3,'st_mtime_ns':opened.st_mtime_ns+1})
        self.os.fstat.return_value=opened;self.p.lstat.return_value=after
        with self.assertRaises(allocation._AllocationChange) as caught:self.measure()
        self.assertEqual(caught.exception.kind,'growth')
        self.assertEqual([sample[0].st_size for sample in caught.exception.samples],[1,2,3])
        self.assertIn('GetFileInformationByHandleEx/fstat/lstat',caught.exception.__notes__[0])
        self.assertTrue(all(len(note)<=1024 for note in caught.exception.__notes__))
        self.assertTrue(any("'snapshot': 'after'" in note for note in caught.exception.__notes__))
        self.assertTrue(any('allocation_query=' in note for note in caught.exception.__notes__))
        self.os.close.assert_called_once_with(7)
        self.os.fstat.return_value=NS(**{**vars(opened),'st_file_attributes':0x400})
        with self.assertRaises(ValueError) as denied:self.measure()
        self.assertNotIsInstance(denied.exception,allocation._AllocationChange)

    def test_deleted_old_handle_is_typed_only_with_fresh_singlelink_replacement(self):
        held=NS(**{**vars(self.observed),'st_nlink':0})
        current=NS(**{**vars(self.observed),'st_ino':2**110,'st_size':2})
        self.os.fstat.return_value=held
        self.p.lstat.side_effect=[self.observed,current,current]
        def deleted(handle,kind,pointer,size):
            value=self.query(handle,kind,pointer,size)
            if kind==1:pointer._obj.deleted=1;pointer._obj.links=0
            return value
        self.kernel.GetFileInformationByHandleEx.side_effect=deleted
        with self.assertRaises(allocation._AllocationChange)as caught:self.measure()
        self.assertEqual(caught.exception.samples,((self.observed,0),(held,4096),(current,0)))
        self.os.close.assert_called_once_with(7)
        self.attributes,self.allocated=0x800,7
        self.p.lstat.side_effect=[self.observed,current,current]
        with self.assertRaises(allocation._AllocationChange)as compressed:self.measure()
        self.assertEqual(compressed.exception.samples[1][1],7)
        self.attributes=0
        late=NS(**{**vars(current),'st_file_attributes':0x400})
        self.p.lstat.side_effect=[self.observed,current,late]
        with self.assertRaisesRegex(ValueError,'reparse')as denied:self.measure()
        self.assertNotIsInstance(denied.exception,allocation._AllocationChange)
        for sequence in ([self.observed,FileNotFoundError(2,'no replacement')],
                         [self.observed,current,FileNotFoundError(2,'replacement vanished')]):
            self.p.lstat.side_effect=sequence
            with self.assertRaisesRegex(ValueError,'invalid native file allocation')as denied:self.measure()
            self.assertNotIsInstance(denied.exception,allocation._AllocationChange)
        for field,value in (('st_ino',self.observed.st_ino),('st_dev',99),('st_nlink',2),
                            ('st_mode',stat.S_IFDIR|0o600),('st_file_attributes',0x400)):
            bad=NS(**{**vars(current),field:value})
            self.p.lstat.side_effect=[self.observed,bad,bad]
            with self.assertRaises(ValueError)as denied:self.measure()
            self.assertNotIsInstance(denied.exception,allocation._AllocationChange)
        for field,value in (('st_ino',2**111),('st_size',2),('st_mtime_ns',99),('st_nlink',2),('st_file_attributes',0x400)):
            self.os.fstat.return_value=NS(**{**vars(held),field:value})
            self.p.lstat.side_effect=[self.observed,current,current]
            with self.assertRaises(ValueError)as denied:self.measure()
            self.assertNotIsInstance(denied.exception,allocation._AllocationChange)
        self.os.fstat.return_value=held
        self.p.lstat.side_effect=[self.observed,current,current]
        self.os.close.side_effect=OSError('owned close unproven')
        with self.assertRaisesRegex(OSError,'close unproven'):self.measure()

    def test_typed_growth_requires_same_identity_monotone_size_and_path_birth(self):
        self.os.fstat.return_value = self.observed
        grown = NS(**{**vars(self.observed),'st_size':2,'st_mtime_ns':5})
        self.p.lstat.side_effect = [self.observed,grown,grown]
        with self.assertRaises(allocation._AllocationChange) as caught:self.measure()
        self.assertEqual(caught.exception.samples[-1][0].st_size,2)
        for field, value in (('st_size',0),('st_mtime_ns',3),('st_ctime_ns',99)):
            bad=NS(**{**vars(grown),field:value})
            self.p.lstat.side_effect=[self.observed,bad,bad]
            with self.assertRaises(ValueError) as denied:self.measure()
            self.assertNotIsInstance(denied.exception,allocation._AllocationChange)

    def test_unknown_identity_denied(self):
        self.observed.st_ino = 0
        with self.assertRaisesRegex(ValueError, 'identity/metadata'): self.measure()

    def test_reparse_leaf_ancestor_and_handle_denied(self):
        reparse = NS(**{**vars(self.observed), 'st_file_attributes': 0x400})
        self.os.lstat.return_value = reparse
        self.os.lstat.side_effect = None
        with self.assertRaisesRegex(ValueError, 'reparse'): self.measure()
        self.os.lstat.side_effect = lambda name: reparse if name == 'C:\\' else self.observed
        with self.assertRaisesRegex(ValueError, 'reparse'): self.measure()
        self.os.lstat.side_effect = lambda name: self.observed
        self.attributes = 0x400
        with self.assertRaisesRegex(ValueError, 'reparse'): self.measure()
        self.os.close.assert_called_once()

    def test_string_ancestor_names_match_pathlib(self):
        from pathlib import PureWindowsPath
        for raw in ('file', '.', 'a/b', '../file', 'C:foo',
                    'C:/a/b', 'C:/', 'C:/a/../b', 'C:/雪/[name]/x',
                    '//server/share/a/b', '//server/share/',
                    '//?/C:/a/b', '//?/UNC/server/share/a/b', '//?/UNC/server/share/'):
            path = PureWindowsPath(raw)
            self.assertEqual(allocation._windows_ancestry_names(path),
                             [str(path), *map(str, path.parents)], raw)

    def test_string_ancestry_reobserves_every_name_and_denies_late_reparse(self):
        self.assertEqual(self.measure(), 4096)
        self.assertEqual([call.args[0] for call in self.os.lstat.call_args_list],
                         ['C:\\file', 'C:\\', 'C:\\file', 'C:\\'])
        self.os.lstat.reset_mock()
        self.os.lstat.side_effect = [self.observed, self.observed, self.observed,
            NS(**{**vars(self.observed), 'st_file_attributes': 0x400})]
        with self.assertRaisesRegex(ValueError, 'reparse'):
            self.measure()
        self.assertEqual(self.os.close.call_count, 2)

    def test_uncertain_comparison_close_retains_original_owner(self):
        for kind, close in (('HANDLE', Mock(return_value=0)),
                            ('CRT descriptor', Mock(side_effect=OSError('close denied')))):
            held = host.HostLock()
            held.owner = Mock()
            held.cleanup_uncertain = False
            failures = []
            if kind == 'HANDLE':
                self.assertEqual(observed_close(held, kind, close, failures)(123), 0)
            else:
                with self.assertRaises(OSError):
                    observed_close(held, kind, close, failures)(7)
            self.assertTrue(held.cleanup_uncertain)
            self.assertEqual(len(failures), 1)
            with patch.object(host, 'retain_host_lock', side_effect=OSError('retained')):
                with self.assertRaisesRegex(OSError, 'retained'):
                    held.__exit__(None, None, None)
            held.owner.close.assert_not_called()


    def test_compiler_cleanup_uses_exact_held_job_and_reaps(self):
        windows = host.module('browser-small-windows')
        dll = NS(OpenProcess=Mock(return_value=77), CloseHandle=Mock(return_value=1),
                 WaitForSingleObject=Mock(side_effect=[258, 0]), TerminateProcess=Mock(return_value=1))
        def member(handle, job, result):
            self.assertEqual((handle, job), (77, 9))
            result._obj.value = True
            return 1
        dll.IsProcessInJob = Mock(side_effect=member)
        with patch.object(windows, 'kernel', return_value=dll), patch.object(windows, 'query_job',
                side_effect=[dict(pids=[1, 2]), dict(pids=[1])]), patch.object(
                windows.time, 'monotonic', return_value=0), patch.object(windows.time, 'sleep'):
            self.assertEqual(windows.stop_descendants(9, 1, 10), [1])
        dll.OpenProcess.assert_called_once_with(0x101001, False, 2)
        dll.TerminateProcess.assert_called_once_with(77, 91)
        dll.CloseHandle.assert_called_once_with(77)

    def test_compiler_cleanup_denies_foreign_or_unreaped_members(self):
        windows = host.module('browser-small-windows')
        for member in (False, True):
            dll = NS(OpenProcess=Mock(return_value=77), CloseHandle=Mock(return_value=1),
                     WaitForSingleObject=Mock(side_effect=[258, 258]), TerminateProcess=Mock(return_value=1))
            def membership(handle, job, result):
                result._obj.value = member
                return 1
            dll.IsProcessInJob = Mock(side_effect=membership)
            with patch.object(windows, 'kernel', return_value=dll), patch.object(windows, 'query_job',
                    return_value=dict(pids=[1, 2])), patch.object(windows.time, 'monotonic', return_value=0):
                with self.assertRaisesRegex(OSError, 'not reaped|no longer belongs'):
                    windows.stop_descendants(9, 1, 10)
            self.assertEqual(dll.TerminateProcess.call_count, int(member))
            dll.CloseHandle.assert_called_once_with(77)


    def test_invalid_allocation_and_delete_pending_denied(self):
        self.attributes, self.allocated = 0x200, -1
        with self.assertRaisesRegex(ValueError, 'allocation'): self.measure()
        for field in ('deleted', 'directory', 'size', 'allocation'):
            def query(handle, kind, pointer, size):
                result = self.query(handle, kind, pointer, size)
                if kind == 1: setattr(pointer._obj, field, 1 if field in ('deleted', 'directory') else -1)
                return result
            self.kernel.GetFileInformationByHandleEx.side_effect = query
            with self.assertRaisesRegex(ValueError, 'allocation'): self.measure()


    def source_pool(self, count=1):
        self.kernel.CreateFileW.reset_mock()
        self.kernel.GetFileInformationByHandleEx.side_effect = self.query
        self.os.close.reset_mock()
        self.attributes = 0
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        files = [root/str(i) for i in range(count)]
        for p in files:
            p.write_bytes(b'x')
        real_lstat = self.real_lstat
        self.source_stats = {p: NS(**vars(self.observed)) for p in files}
        def lstat(p, *args, **kwargs):
            return self.source_stats[p] if p in self.source_stats else real_lstat(p, *args, **kwargs)
        context = patch.object(Path, 'lstat', lstat)
        context.start()
        self.addCleanup(context.stop)
        source_os = NS(name='nt', O_RDONLY=os.O_RDONLY, O_NOINHERIT=128,
                       fstat=self.os.fstat, close=self.os.close, walk=os.walk)
        context = patch.object(source, 'os', source_os)
        context.start()
        self.addCleanup(context.stop)
        self.next_handle = 1000
        def duplicate(*args):
            self.next_handle += 1
            args[3]._obj.value = self.next_handle
            return 1
        self.kernel.DuplicateHandle.side_effect = duplicate
        lock = host.HostLock()
        lock.owner = Mock()
        lock.check = Mock()
        pool = source._SourcePool(lock, [root], {root: root.lstat(), **self.source_stats})
        self.assertIs(lock.source_pool, pool)
        lock.owner.request.assert_called_once_with(dict(command='source-arm'))
        self.kernel.CreateFileW.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'prime must complete'):
            lock.start_caretaker('plan', 'operation', 'directory')
        return pool, lock, root, files

    def prime_source(self, pool):
        checkpoint = Mock()
        while not pool.prime_step(checkpoint):
            pass
        pool.finish_prime(checkpoint)
        return checkpoint

    def sample_source(self, pool):
        return pool.bounded(lambda: pool.sample(pool.roots))

    def test_source_executable_fd_mode_differs_but_path_mode_stays_sealed(self):
        self.observed.st_mode = stat.S_IFREG | 0o777
        pool, lock, root, files = self.source_pool()
        self.os.fstat.return_value = NS(**{**vars(self.observed), 'st_mode': stat.S_IFREG | 0o666})
        self.prime_source(pool)
        self.assertTrue(pool.ready)
        self.assertEqual(self.sample_source(pool)[(str(files[0]), 3, 2**90)], 4096)
        self.source_stats[files[0]].st_mode = stat.S_IFREG | 0o666
        with self.assertRaisesRegex(ValueError, 'identity/metadata'):
            self.sample_source(pool)
        lock.close_source_pool()

    def test_source_fd_directory_rejected_even_with_same_identity_fields(self):
        pool, lock, root, files = self.source_pool()
        self.os.fstat.return_value = NS(**{**vars(self.observed), 'st_mode': stat.S_IFDIR | 0o777})
        with self.assertRaisesRegex(ValueError, 'identity/metadata'):
            pool.prime_step(Mock())
        self.assertTrue(pool.poisoned)
        self.os.close.assert_called_once_with(7)
        lock.close_source_pool()

    def test_source_one_open_fresh_sparse_compressed_queries_and_no_crt_retention(self):
        pool, lock, root, files = self.source_pool()
        self.prime_source(pool)
        self.kernel.CreateFileW.assert_called_once()
        self.kernel.DuplicateHandle.assert_called_once()
        self.assertFalse(self.kernel.DuplicateHandle.call_args.args[5])
        self.os.close.assert_called_once_with(7)
        self.assertEqual(len(pool.handles), 1)
        storage = Storage(source_pool=pool)
        def sample():
            return storage.sample([root])
        self.assertEqual(pool.bounded(sample), 4096)
        self.attributes, self.allocated = 0x800, 8192
        self.assertEqual(pool.bounded(sample), 8192)
        self.attributes, self.allocated = 0x200, 0
        self.assertEqual(pool.bounded(sample), 8192)  # no refund
        self.assertEqual(self.calls.count(9), 4)
        self.assertEqual(self.calls.count(8), 2)
        self.kernel.CreateFileW.assert_called_once()
        self.os.close.assert_called_once()
        lock.close_source_pool()
        self.assertTrue(pool.closed)
        lock.owner.request.assert_called_with(dict(command='source-closed'))
        self.kernel.CloseHandle.assert_called_once_with(1001)
        with self.assertRaises(ValueError): self.sample_source(pool)

    def test_source_chunk_admission_before_open_and_complete_prime_required(self):
        pool, lock, root, files = self.source_pool(257)
        checkpoint = Mock()
        self.assertFalse(pool.prime_step(checkpoint))
        self.assertEqual(len(pool.handles), 256)
        self.assertFalse(pool.ready)
        with self.assertRaisesRegex(ValueError, 'complete prepared'):
            pool.sample([root])
        checkpoint.side_effect = ValueError('deadline/volume/free/capacity drift')
        with self.assertRaisesRegex(ValueError, 'capacity drift'):
            pool.prime_step(checkpoint)
        self.assertEqual(self.kernel.CreateFileW.call_count, 256)
        pool.close()
        self.assertEqual(self.os.close.call_count, 256)
        self.assertEqual(self.kernel.CloseHandle.call_count, 256)

    def test_source_sealed_names_missing_replaced_mutated_and_reparse_denied(self):
        for drift in ('new', 'missing', 'st_ino', 'st_dev', 'st_size', 'st_mtime_ns', 'reparse', 'directory'):
            with self.subTest(drift=drift):
                pool, lock, root, files = self.source_pool()
                self.prime_source(pool)
                p = files[0]
                if drift == 'new': (root/'new').write_bytes(b'x')
                elif drift == 'missing': p.unlink()
                elif drift == 'reparse': self.source_stats[p].st_file_attributes = 0x400
                elif drift == 'directory': self.source_stats[p].st_mode = stat.S_IFDIR
                else: setattr(self.source_stats[p], drift, 99)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.sample_source(pool)
                self.assertTrue(pool.poisoned)
                pool.close()

    def test_source_after_path_binding_and_fresh_query_errors(self):
        for failure in (9, 1, 8, 'after', 'deleted'):
            with self.subTest(failure=failure):
                pool, lock, root, files = self.source_pool()
                self.prime_source(pool)
                self.attributes = 0x800
                def query(handle, kind, pointer, size):
                    result = self.query(handle, kind, pointer, size)
                    if failure == kind: return 0
                    if failure == 'deleted' and kind == 1: pointer._obj.deleted = 1
                    if failure == 'after' and kind == 8: self.source_stats[files[0]].st_ino = 2**91
                    return result
                self.kernel.GetFileInformationByHandleEx.side_effect = query
                with self.assertRaises((ValueError, OSError)): self.sample_source(pool)
                pool.close()
                self.kernel.GetFileInformationByHandleEx.side_effect = self.query

    def test_source_transfer_failures_close_exact_owned_resources(self):
        for failure in ('convert', 'fstat', 'duplicate', 'close'):
            with self.subTest(failure=failure):
                pool, lock, root, files = self.source_pool()
                self.kernel.CloseHandle.reset_mock()
                self.os.close.reset_mock()
                if failure == 'convert': sys.modules['msvcrt'].open_osfhandle.side_effect = OSError('convert')
                if failure == 'fstat': self.os.fstat.side_effect = OSError('fstat')
                if failure == 'duplicate': self.kernel.DuplicateHandle.return_value = 0; self.kernel.DuplicateHandle.side_effect = None
                if failure == 'close': self.os.close.side_effect = OSError('unknown close')
                with self.assertRaises(OSError): pool.prime_step(Mock())
                self.assertTrue(pool.poisoned)
                if failure == 'convert': self.kernel.CloseHandle.assert_called_once_with(123)
                elif failure == 'close':
                    self.assertTrue(pool.uncertain)
                    with self.assertRaises(ValueError): pool.close()
                else: self.os.close.assert_called_once_with(7)
                if failure != 'close': pool.close()
                sys.modules['msvcrt'].open_osfhandle.side_effect = None
                self.os.fstat.side_effect = None
                self.os.close.side_effect = None

    def test_source_timeout_late_open_duplicate_query_and_close_fence_original_owner(self):
        original_bounded = host.bounded
        for stage in ('open', 'duplicate', 'query', 'close'):
            with self.subTest(stage=stage):
                pool, lock, root, files = self.source_pool()
                if stage in ('query', 'close'): self.prime_source(pool)
                entered, release, done = threading.Event(), threading.Event(), threading.Event()
                finished = threading.Event()
                target = {'open': self.kernel.CreateFileW, 'duplicate': self.kernel.DuplicateHandle,
                          'query': self.kernel.GetFileInformationByHandleEx, 'close': self.kernel.CloseHandle}[stage]
                saved = target.side_effect
                result = target.return_value
                def block(*args):
                    entered.set()
                    release.wait(2)
                    try:
                        return saved(*args) if callable(saved) else result
                    finally:
                        done.set()
                target.side_effect = block
                def fast(call, seconds=2, *, fence=None):
                    def invoke():
                        try:
                            return call()
                        finally:
                            finished.set()
                    return original_bounded(invoke, .02, fence=fence)
                with patch.object(host, 'bounded', fast):
                    action = pool.close if stage == 'close' else (lambda: self.sample_source(pool)) if stage == 'query' else (lambda: pool.prime_step(Mock()))
                    with self.assertRaisesRegex(OSError, 'blocked/stale'): action()
                    self.assertTrue(entered.is_set())
                    self.assertTrue(pool.poisoned)
                    self.assertEqual(pool.inflight, 1)
                    with patch.object(host, 'retain_host_lock', side_effect=RuntimeError('retained')) as retain:
                        with self.assertRaisesRegex(RuntimeError, 'retained'): lock.__exit__(None, None, None)
                    retain.assert_called_once()
                    lock.owner.close.assert_not_called()
                    self.assertEqual(lock.owner.request.call_count, 1)
                    target.side_effect = saved
                    release.set()
                    self.assertTrue(done.wait(1))
                self.assertTrue(finished.wait(1))
                self.assertEqual(pool.inflight, 0)
                pool.close()
                with self.assertRaises(ValueError): self.sample_source(pool)

    def test_source_close_failure_is_never_retried_or_unlocks(self):
        pool, lock, root, files = self.source_pool()
        self.prime_source(pool)
        self.kernel.CloseHandle.return_value = 0
        with self.assertRaises(OSError): pool.close()
        count = self.kernel.CloseHandle.call_count
        with patch.object(host, 'retain_host_lock', side_effect=RuntimeError('retained')):
            with self.assertRaises(RuntimeError): lock.__exit__(None, None, None)
        self.assertEqual(self.kernel.CloseHandle.call_count, count)
        lock.owner.close.assert_not_called()

    def test_source_real_monitor_component_uses_pool_and_whole_operation_fence(self):
        pool, lock, root, files = self.source_pool()
        self.prime_source(pool)
        m = Monitor.__new__(Monitor)
        m.disk_operation = threading.Lock()
        m.source_pool, m.lock, m.campaign = pool, lock, Mock()
        m.source_storage, m.storage = Storage(source_pool=pool), Mock()
        m.storage.sample.return_value = 17
        m.runtime, m.lineage = 'runtime', None
        m.groups, m.git_freezes, m.dependencies, m.roots, m.volumes = [], [], [], [], []
        m.externals = {}
        m.clock, m.last_progress, m.deadline = lambda: 0, 0, float('inf')
        m.plan = dict(host={}, source_reservation=dict(roots=[str(root)], bytes=65536),
                      owned_root=str(Path(__file__).resolve().parent/'fake-owned'),
                      campaign=str(Path(__file__).resolve().parent/'fake-campaign'))
        m.log = Mock()
        with patch.object(monitor.identity, 'runtime_requirements', return_value='runtime'), \
                patch.object(monitor, 'host', return_value={}):
            result = m.sample()
        self.assertEqual(result['source_sampled_highwater'], 4096)
        self.assertEqual(result['owned_sampled_highwater'], 17)
        m.log.open.assert_not_called()  # No component callback can publish an acceptance receipt.
        self.kernel.CreateFileW.assert_called_once()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(1)
        m.campaign.check.side_effect = blocked
        original_bounded = host.bounded
        def fast(call, seconds=2, *, fence=None):
            def invoke():
                try:
                    return call()
                finally:
                    finished.set()
            return original_bounded(invoke, .02, fence=fence)
        with patch.object(monitor.identity, 'runtime_requirements', return_value='runtime'), \
                patch.object(host, 'bounded', fast):
            with self.assertRaisesRegex(OSError, 'blocked/stale'): m.sample()
            self.assertTrue(entered.is_set())
            self.assertEqual(pool.inflight, 1)
            self.assertTrue(pool.poisoned)
            self.kernel.CloseHandle.assert_not_called()
            release.set()
            self.assertTrue(finished.wait(1))
        self.assertEqual(pool.inflight, 0)
        m.campaign.check.side_effect = None
        # The failed monitor must not publish or permit reuse.
        with self.assertRaises(ValueError): m.sample()
        lock.close_source_pool()

    def test_linux_allocation_uses_observed_blocks_without_windows_setup(self):
        with patch.object(allocation, 'os', NS(name='posix')), \
                patch.object(allocation, '_windows_api') as api:
            self.assertEqual(allocation._allocated_bytes(self.p, NS(st_blocks=9)), 4608)
            api.assert_not_called()

    def test_source_root_and_ancestor_reparse_changes_deny_retained_handles(self):
        for target_parent in (False, True):
            pool, lock, root, files = self.source_pool()
            self.prime_source(pool)
            previous = Path.lstat
            target = root.parent if target_parent else root
            def reparse(p, *args, **kwargs):
                return NS(st_mode=stat.S_IFDIR, st_file_attributes=0x400) if p == target else previous(p, *args, **kwargs)
            with patch.object(Path, 'lstat', reparse):
                with self.assertRaisesRegex(ValueError, 'reparse'):
                    self.sample_source(pool)
            pool.close()

    def test_source_prepare_hook_checks_capacity_before_any_open(self):
        pool, lock, root, files = self.source_pool()
        # Exercise actual preparation with the same sealed adapter and original lock.
        lock.close_source_pool()
        plan = dict(source_reservation=dict(roots=[str(root)], bytes=65536),
                    host={}, volumes=[dict(path=str(root), device=root.stat().st_dev)])
        entries = {root: root.lstat(), **self.source_stats}
        with patch.object(monitor, 'host', return_value={}), \
                patch.object(monitor.shutil, 'disk_usage', return_value=NS(free=0)):
            with self.assertRaisesRegex(ValueError, 'free capacity'):
                _prepare_source(plan, lock, Mock(), entries, 10, lambda: 0)
        self.kernel.CreateFileW.assert_not_called()
        lock.close_source_pool()

    def test_source_final_prime_rechecks_absolute_deadline_and_denies_caretaker(self):
        pool, lock, root, files = self.source_pool()
        lock.close_source_pool()
        lock.owner.request.reset_mock()
        now = [0.5]
        plan = dict(source_reservation=dict(roots=[str(root)], bytes=65536),
                    host={}, volumes=[dict(path=str(root), device=root.stat().st_dev)])
        entries = {root: root.lstat(), **self.source_stats}
        original = source._SourcePool._census
        def slow_census(value):
            original(value)
            now[0] += 0.8  # Below the two-second call bound, beyond the OS deadline.
        try:
            with patch.object(monitor, 'host', return_value={}), \
                    patch.object(monitor.shutil, 'disk_usage', return_value=NS(free=2**50)), \
                    patch.object(source._SourcePool, '_census', slow_census):
                with self.assertRaisesRegex(ValueError, 'OS deadline'):
                    _prepare_source(plan, lock, Mock(), entries, 1, lambda: now[0])
            current = lock.source_pool
            self.assertTrue(current.poisoned)
            self.assertFalse(current.ready)
            self.assertEqual(current.inflight, 0)
            with self.assertRaisesRegex(ValueError, 'poisoned/closed'):
                lock.start_caretaker('plan', 'operation', 'directory')
            lock.owner.request.assert_called_once_with(dict(command='source-arm'))
        finally:
            lock.close_source_pool()
        self.assertTrue(current.closed)

    def test_source_checkpoint_capacity_work_cannot_open_after_deadline(self):
        pool, lock, root, files = self.source_pool()
        lock.close_source_pool()
        now = [0.5]
        plan = dict(source_reservation=dict(roots=[str(root)], bytes=65536),
                    host={}, volumes=[dict(path=str(root), device=root.stat().st_dev)])
        entries = {root: root.lstat(), **self.source_stats}
        def slow_capacity(_):
            now[0] += 0.8
            return NS(free=2**50)
        try:
            with patch.object(monitor, 'host', return_value={}), \
                    patch.object(monitor.shutil, 'disk_usage', side_effect=slow_capacity):
                with self.assertRaisesRegex(ValueError, 'OS deadline'):
                    _prepare_source(plan, lock, Mock(), entries, 1, lambda: now[0])
            self.kernel.CreateFileW.assert_not_called()
            self.assertTrue(lock.source_pool.poisoned)
            self.assertFalse(lock.source_pool.ready)
            self.assertEqual(lock.source_pool.inflight, 0)
        finally:
            lock.close_source_pool()

    def test_source_owner_eof_retains_until_explicit_quiescent_close(self):
        import io
        import json
        def commands(*names):
            return io.StringIO(''.join(json.dumps(dict(command=n, challenge='a'*64))+'\n' for n in names))
        for names, retained in ((('source-arm',), True), (('source-arm', 'source-closed'), False), ((), False)):
            retain = Mock()
            host.lock_owner_loop(commands(*names), Mock(), Mock(), Mock(), retain, Mock())
            self.assertEqual(retain.called, retained)


class NativeReadOnlyControls(unittest.TestCase):
    output = None
    options = None

    def test_complete_storage_inventory_equivalence(self):
        from scale_acceptance import native_tiny as tiny
        self.assertTrue(sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize)
        self.assertEqual(Path(allocation.__file__).resolve(), Path(__file__).resolve().parent/'scale_acceptance/_native_file.py')
        started = time.monotonic()
        output = type(self).output
        self.assertIsNotNone(output)
        options = type(self).options
        evidence_owner = options.evidence_owner.resolve()
        self.assertTrue(str(evidence_owner).lower().startswith('\\\\wsl.localhost\\'))
        self.assertTrue(output.is_relative_to(evidence_owner) and '..' not in output.parts, 'Linux evidence owner required')
        output.mkdir(exist_ok=False)
        budget = tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=256*1024**2, visits=2_000_000))), Path(__file__))
        def check():
            budget.check()
            self.assertLess(time.monotonic()-started, 60, 'component cooperative deadline')
        write_lock = threading.Lock()
        completed_files = []
        def write(name, value):
            raw = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()
            with write_lock:
                self.assertLessEqual(sum(p.stat().st_size for p in output.iterdir())+len(raw), 49152)
                with (output/name).open('xb') as stream:
                    stream.write(raw)
                completed_files.append(name)
        def read_pin(path, digest):
            path = Path(path)
            before = identity.stamp(path)
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest, str(path))
            self.assertEqual(identity.stamp(path), before)
            return json.loads(raw)
        host.module('local-ci')
        windows = host.module('browser-small-windows')
        operator = windows.process_identity(os.getpid())
        write('preflight-started.json', dict(component_only=True, operator_identity=operator, owner_acquired=False))
        census = read_pin(*options.baseline)
        plan = read_pin(*options.plan)
        binding = read_pin(*options.bindings)
        previous = read_pin(*options.previous_result)
        self.assertIsNone(previous['failure'])
        self.assertFalse(previous.get('live_records_uninspected', False))
        self.assertTrue(previous['original_lock']['original_descriptor_closed'] and
                        previous['original_lock']['capture_eof_joined'])
        helper, helper_sha = options.control_helper
        helper = Path(helper)
        helper_stamp = identity.stamp(helper)
        self.assertEqual(identity.sha256(helper), helper_sha)
        spec = importlib.util.spec_from_file_location('scale_acceptance._allocation_control', helper)
        control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(control)
        self.assertEqual(identity.stamp(helper), helper_stamp)
        self.assertEqual(identity.sha256(helper), helper_sha)
        os.environ['_'] = str(Path(sys.executable).resolve())
        os.environ['GIT_OPTIONAL_LOCKS'] = '0'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        self.assertEqual(identity.host(), plan['host'])
        self.assertEqual(identity.environment_digest(), plan['environment_sha256'])
        self.assertEqual(Path(sys.executable).resolve(), Path(plan['python']['path']))
        self.assertEqual(sys.version, plan['python']['version'])
        allocation._windows_api()
        source_roots = [Path(r) for r in plan['source_reservation']['roots']]
        point_additions = {}
        for name, digest in options.point_addition:
            path = Path(name)
            self.assertTrue(any(path.is_relative_to(root) for root in source_roots))
            self.assertNotIn(str(path), point_additions)
            before = identity.stamp(path)
            self.assertEqual(identity.sha256(path), digest)
            self.assertEqual(identity.stamp(path), before)
            point_additions[str(path)] = digest
        # Hash current bytes against retained runtime pins; new test imports are explicit additions.
        groups = {Path(g['root']):dict(g['sha256']) for g in binding['dependencies']}
        expected = {root/name:digest for root, files in groups.items() for name, digest in files.items()}
        runtime = identity.runtime_requirements()
        additions = []
        allowed_additions = {Path(path):digest for path,digest in options.runtime_addition}
        for path in sorted(runtime[1]-set(expected)):
            self.assertTrue(path in allowed_additions, 'unreviewed runtime image '+str(path))
            if path.parent not in groups:
                self.assertTrue(any(path.is_relative_to(root) for root in source_roots), 'unadmitted runtime directory')
                groups[path.parent] = {}
            before = identity.stamp(path)
            digest = identity.sha256(path)
            self.assertEqual(digest, allowed_additions[path], str(path))
            self.assertEqual(identity.stamp(path), before)
            groups[path.parent][path.name] = digest
            additions.append(dict(path=str(path), sha256=digest, stat=identity.stamp(path)))
        for path, digest in expected.items():
            check()
            before = identity.stamp(path)
            self.assertEqual(identity.sha256(path), digest, str(path))
            self.assertEqual(identity.stamp(path), before)
        dependencies = [dict(root=str(root), inputs=sorted(files), sha256=files) for root, files in groups.items()]
        frozen_runtime = identity.dependency_metadata(dependencies, runtime)
        images = {path:identity.stamp(path) for path in runtime[1]}
        source_roots = [Path(r) for r in plan['source_reservation']['roots']]
        native_roots = [Path(r['path']) for r in census['baselines']['native']['roots']]
        namespace = Path(plan['qualification']['namespace'])
        self.assertTrue(source_roots and native_roots)
        self.assertFalse(any(output.is_relative_to(root) for root in [*source_roots,*native_roots,namespace]))
        def snapshot():
            result = {}
            for root in [*source_roots, *native_roots, namespace]:
                check()
                root_stat = root.lstat()
                self.assertFalse(root_stat.st_file_attributes & 0x400)
                children = list(root.iterdir())
                entries = identity.frozen_metadata(root, [identity.glob.escape(p.name) for p in children]) if children else {}
                result[str(root)] = (identity.stat_fields(root_stat, 0, root), entries)
            return result
        def record_summary(exclude=()):
            return {label:{phase:dict(files=len(values),
                successful_charge_sum=sum(max(v['size'],v['allocated_bytes']) for v in values.values()),
                digest=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest())
                for phase, original in phases.items()
                for values in [{name:value for name,value in original.items() if name not in exclude}]}
                for label,phases in records.items()}
        write('preflight.json', dict(passed=True, component_only=True, qualification=False,
            runtime_additions=additions, source_files={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (Path(__file__).resolve(), Path(allocation.__file__).resolve())},
            source_roots=len(source_roots), native_roots=len(native_roots),
            baseline_entries={key:len(value['entries']) for key,value in census['baselines'].items()}))
        held = host.HostLock()
        held.existing = True
        rows, records = {}, {}
        failure = None
        try:
            with held as lock:
                self.assertEqual(lock.proof()['stat'], plan['qualification']['original_lock_stat'])
                write('started.json', dict(component_only=True, qualification=False, original_owner=lock.proof(),
                    operator_identity=operator,
                    runtime_additions=additions, input_entry_counts={k:len(v['entries']) for k,v in census['baselines'].items()},
                    source_files={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (Path(__file__).resolve(), Path(allocation.__file__).resolve())}))
                held.cleanup_uncertain = False
                current_phase = dict(backend=None, phase='snapshot-before')
                uncertain_closes = []
                def observe():
                    before_threads = set(threading.enumerate())
                    original_close = os.close
                    close_fd = observed_close(held, 'CRT descriptor', original_close, uncertain_closes)
                    try:
                        with ExitStack() as closing:
                            closing.enter_context(patch.object(os, 'close', close_fd))
                            for backend in (control, allocation):
                                kernel = backend._windows_api()[0]
                                closing.enter_context(patch.object(kernel, 'CloseHandle',
                                    observed_close(held, 'HANDLE', kernel.CloseHandle, uncertain_closes)))
                            before = snapshot()
                            expected_names = {label:{str(root/name)
                                for root in roots for name,value in before[str(root)][1].items()
                                if stat.S_ISREG(value[5])} for label,roots in (
                                    ('sample-native', native_roots), ('sample-source', source_roots),
                                    ('sample-tiny', [namespace]))}
                            for label, backend in (('control', control._allocated_bytes),
                                                   ('candidate', allocation._allocated_bytes)):
                                rows[label], records[label] = {}, {}
                                phase = None
                                def measure(path, observed):
                                    try:
                                        allocated = backend(path, observed)
                                    except BaseException as error:
                                        error.add_note(label+' '+phase+' '+str(path))
                                        raise
                                    records[label][phase][str(path)] = identity.stat_fields(observed, allocated)
                                    if len(records[label][phase]) % 256 == 0:
                                        check()
                                    return allocated
                                with patch.object(monitor, '_allocated_bytes', measure):
                                    for pool in ('native', 'source'):
                                        check()
                                        phase = 'admit-'+pool
                                        current_phase.update(backend=label, phase=phase)
                                        records[label][phase] = {}
                                        tick = time.monotonic()
                                        storage = Storage(census['baselines'][pool], census['prior_storage'][pool])
                                        rows[label][phase] = dict(seconds=time.monotonic()-tick,
                                            files=len(records[label][phase]), carry_bytes=storage.carry)
                                        self.assertEqual(len(records[label][phase]), len(census['baselines'][pool]['entries']))
                                        if pool == 'native':
                                            native_storage = storage
                                        else:
                                            source_storage = storage
                                    tiny_storage = Storage(prior=dict(carry_bytes=options.tiny_origin_carry,
                                        prior_sampled_aggregate_highwater_bytes=options.tiny_origin_carry))
                                    for phase, storage, roots, limit in (
                                            ('sample-native', native_storage, native_roots, plan['limits']['owned_bytes']),
                                            ('sample-source', source_storage, source_roots, plan['source_reservation']['bytes']),
                                            ('sample-tiny', tiny_storage, [namespace], 64*1024**2)):
                                        check()
                                        current_phase.update(backend=label, phase=phase)
                                        records[label][phase] = {}
                                        tick = time.monotonic()
                                        charged = storage.sample(roots)
                                        self.assertLessEqual(charged, limit)
                                        rows[label][phase] = dict(seconds=time.monotonic()-tick,
                                            files=len(records[label][phase]), sampled_bytes=charged)
                                        self.assertTrue(set(records[label][phase]) == expected_names[phase],
                                                        'full recorded inventory missing '+phase)
                                if label == 'control':
                                    self.assertEqual(record_summary(exclude=point_additions)['control'], previous['partial_records']['control'],
                                        'prior complete point inventory drift; no candidate or debt rebasing')
                                write(label+'.json', dict(component_only=True, qualification=False, phases=rows[label],
                                    record_digests={p:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()
                                        for p,v in records[label].items()}))
                            for phase in records['control']:
                                self.assertTrue(records['control'][phase].keys() == records['candidate'][phase].keys(),
                                                'record membership drift '+phase)
                                for path, value in records['control'][phase].items():
                                    self.assertEqual(value, records['candidate'][phase][path], path)
                            current_phase.update(backend=None, phase='snapshot-after')
                            self.assertTrue(snapshot() == before, 'complete input namespace drift')
                            self.assertEqual(identity.runtime_requirements(), runtime)
                            self.assertTrue(all(identity.stamp(path) == stamp for path, stamp in images.items()))
                            self.assertTrue(all(identity.frozen_metadata(root, patterns) == values
                                for root, patterns, values in frozen_runtime))
                            check()
                    finally:
                        if set(threading.enumerate())-before_threads:
                            held.cleanup_uncertain = True
                try:
                    remaining = 60-(time.monotonic()-started)
                    self.assertGreater(remaining, 0)
                    host.bounded(observe, seconds=remaining)
                    self.assertFalse(host.pending_calls())
                except BaseException as error:
                    if host.pending_calls():
                        held.cleanup_uncertain = True
                    write('failure-under-owner.json', dict(error=repr(error), cleanup_uncertain=held.cleanup_uncertain,
                        original_owner=lock.proof(), operator_identity=operator, current_phase=current_phase.copy(),
                        completed_files=list(completed_files), uncertain_closes=list(uncertain_closes),
                        live_records_uninspected=bool(host.pending_calls())))
                    raise
        except BaseException as error:
            failure = str(error)
            raise
        finally:
            pending = bool(host.pending_calls())
            write('result.json', dict(component_only=True, qualification=False, failure=failure,
                phases={} if pending else rows, live_records_uninspected=pending,
                original_lock=getattr(held, 'released', None), operator_identity=operator,
                metadata=dict(read_bytes=budget.read_bytes, visits=budget.visits),
                order='control first; cache/order effects remain; one pair only',
                independent_after_exit_required=True, product_runs=0, slots=0, default_adoption=False,
                partial_records={} if pending else record_summary(),
                point_additions={} if pending else {name:dict(sha256=digest, stat=records.get('control', {}).get(
                    'sample-source', {}).get(name)) for name,digest in point_additions.items()},
                seconds=time.monotonic()-started))
        candidate = rows['candidate']
        admission = candidate['admit-native']['seconds']+candidate['admit-source']['seconds']
        sample = sum(candidate[p]['seconds'] for p in ('sample-native','sample-source','sample-tiny'))
        print(json.dumps(dict(component_only=True, qualification=False, equivalent=True,
            candidate_admission_seconds=admission, candidate_full_storage_seconds=sample,
            necessary_live_storage_bound_pass=sample < monitor.LIMITS['disk_observation_seconds'],
            disk_observation_bound_seconds=monitor.LIMITS['disk_observation_seconds'])), flush=True)


def exited_births(expected_births):
    """Prove exact native process births exited without erasing Win32 errors."""
    windows = host.module('browser-small-windows')
    kernel = windows.kernel()
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.WaitForSingleObject.restype = W.DWORD
    kernel.GetProcessTimes.argtypes = [W.HANDLE]+[C.POINTER(W.FILETIME)]*4
    kernel.GetProcessTimes.restype = W.BOOL
    births = []
    for expected in expected_births:
        C.set_last_error(0)
        handle = kernel.OpenProcess(0x101000, False, expected['pid'])
        if not handle:
            error = C.get_last_error()
            identity.require(error == 87, 'process absence unproven')
            births.append(dict(identity=expected, absent=True, error=error))
            continue
        try:
            times = [W.FILETIME() for _ in range(4)]
            windows.checked(kernel.GetProcessTimes(handle, *(C.byref(t) for t in times)))
            birth = times[0].dwHighDateTime<<32 | times[0].dwLowDateTime
            state = kernel.WaitForSingleObject(handle, 0)
            identity.require(birth != expected['created'] or state == 0, 'recorded birth still running')
            births.append(dict(identity=expected, absent=True, observed_birth=birth, signaled=state == 0))
        finally:
            windows.checked(kernel.CloseHandle(handle))
    return births


def comparison_after_exit(output, result_sha):
    """Independent exact-owner absence and original byte-zero release control."""
    import msvcrt
    started = time.monotonic()
    result_path = output/'result.json'
    identity.require(result_path.stat().st_size <= 49152, 'bounded component result required')
    raw = result_path.read_bytes()
    identity.require(len(raw) <= 49152 and hashlib.sha256(raw).hexdigest() == result_sha,
                     'exact bounded component result required')
    result = json.loads(raw)
    original = result['original_lock']
    identity.require(original['original_descriptor_closed'] and original['capture_eof_joined'],
                     'original owner release protocol incomplete')
    births = exited_births((result['operator_identity'], original['owner_identity']))
    lock = Path(original['path'])
    before = identity.stamp(lock)
    identity.require(before == original['stat'], 'original lock drift')
    fd = os.open(lock, os.O_RDWR)
    acquired = False
    try:
        value = os.fstat(fd)
        identity.require([value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns] == before[:4],
                         'original descriptor drift')
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        acquired = True
        identity.require(identity.stamp(lock) == before, 'original lock drift under probe')
    finally:
        if acquired:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)
    identity.require(identity.stamp(lock) == before and time.monotonic()-started < 30,
                     'after-exit deadline/stat drift')
    raw = (json.dumps(dict(complete=True, component_only=True, qualification=False, owned_births=births,
        original_byte_zero_available=True, independent_probe_released=True, original_lock_stat=before,
        administrative_recovery=False, seconds=time.monotonic()-started), indent=2)+'\n').encode()
    identity.require(sum(path.stat().st_size for path in output.iterdir())+len(raw) <= 49152,
                     'comparison output ceiling')
    with (output/'after-exit.json').open('xb') as stream:
        stream.write(raw)
    print(json.dumps(dict(after_exit=True, sha256=hashlib.sha256(raw).hexdigest())), flush=True)


class NativeControls(unittest.TestCase):
    root = None

    def test_fresh_metadata_controls(self):
        p = self.root/'normal'
        p.write_bytes(b'x'*8192)
        s = p.stat()
        allocated = allocation._allocated_bytes(p, s)
        self.assertGreater(allocated, 0)
        storage = Storage()
        charged = storage.sample([self.root])
        self.assertEqual(charged, max(s.st_size, allocated))
        sealed = dict(path=str(p), stat=dict(dev=s.st_dev, ino=s.st_ino, allocated_bytes=allocated))
        identity.sealed_stat(sealed)
        prior = dict(sum_bytes=charged, entry_count=1, carry_bytes=charged+4096,
                     prior_sampled_aggregate_highwater_bytes=charged+4096)
        baseline = dict(entries=[{**sealed, 'charge_bytes': charged}], roots=[dict(path=str(self.root), stat={})],
                        sum_bytes=charged)
        retained = Storage(baseline, prior)
        self.assertEqual(retained.sample([self.root]), prior['carry_bytes'])
        p.write_bytes(b'')
        self.assertEqual(storage.sample([self.root]), charged)
        p.rename(self.root/'retired')
        p.write_bytes(b'replacement')
        with self.assertRaisesRegex(ValueError, 'identity/metadata'):
            allocation._allocated_bytes(p, s)
        with self.assertRaisesRegex(ValueError, 'sealed stat'):
            identity.sealed_stat(sealed)
        self.assertGreater(storage.sample([self.root]), charged)

    def test_sparse(self):
        import msvcrt
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.DeviceIoControl.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32,
                                          C.c_void_p, C.c_uint32, C.c_void_p, C.c_void_p]
        kernel.DeviceIoControl.restype = C.c_int
        p = self.root/'sparse'
        with p.open('w+b') as stream:
            returned = C.c_uint32()
            if not kernel.DeviceIoControl(msvcrt.get_osfhandle(stream.fileno()), 0x900c4,
                                          None, 0, None, 0, C.byref(returned), None):
                self.skipTest('FSCTL_SET_SPARSE unsupported: '+str(C.get_last_error()))
            stream.truncate(65536)
            # Zero writes/truncate need not preserve holes on Windows.
            zero_range = (C.c_int64*2)(0, 65536)
            if not kernel.DeviceIoControl(msvcrt.get_osfhandle(stream.fileno()), 0x980c8,
                                          zero_range, C.sizeof(zero_range), None, 0,
                                          C.byref(returned), None):
                raise C.WinError(C.get_last_error())
            stream.flush()
            os.fsync(stream.fileno())
        s = p.stat()
        self.assertTrue(s.st_file_attributes & 0x200)
        measured = allocation._allocated_bytes(p, s)
        print(f'{p.name}: logical={s.st_size} allocated={measured} attributes={s.st_file_attributes:#x}',
              file=sys.stderr)
        self.assertLess(measured, s.st_size)

    def test_compressed(self):
        import msvcrt
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.DeviceIoControl.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32,
                                          C.c_void_p, C.c_uint32, C.c_void_p, C.c_void_p]
        kernel.DeviceIoControl.restype = C.c_int
        p = self.root/'compressed'
        with p.open('w+b') as stream:
            returned, compression = C.c_uint32(), C.c_uint16(1)
            if not kernel.DeviceIoControl(msvcrt.get_osfhandle(stream.fileno()), 0x9c040,
                                          C.byref(compression), 2, None, 0, C.byref(returned), None):
                self.skipTest('FSCTL_SET_COMPRESSION unsupported: '+str(C.get_last_error()))
            stream.write(b'0'*65536)
            stream.flush()
            os.fsync(stream.fileno())
        s = p.stat()
        self.assertTrue(s.st_file_attributes & 0x800)
        measured = allocation._allocated_bytes(p, s)
        print(f'{p.name}: logical={s.st_size} allocated={measured} attributes={s.st_file_attributes:#x}',
              file=sys.stderr)
        self.assertLess(measured, s.st_size)

    def test_reparse(self):
        p, link = self.root/'target', self.root/'link'
        p.write_bytes(b'x')
        try:
            link.symlink_to(p)
        except OSError as error:
            self.skipTest('symlink privilege/support unavailable: '+str(error))
        with self.assertRaisesRegex(ValueError, 'reparse'):
            allocation._allocated_bytes(link, p.stat())
        with self.assertRaises(ValueError): Storage().sample([self.root])
        link.unlink()

    def test_delete_pending(self):
        p = self.root/'delete-pending'
        p.write_bytes(b'x')
        s = p.stat()
        # Hold our fresh file alive after unlink marks it delete-pending.
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [C.c_wchar_p, C.c_uint32, C.c_uint32, C.c_void_p,
                                      C.c_uint32, C.c_uint32, C.c_void_p]
        kernel.CreateFileW.restype = C.c_void_p
        handle = kernel.CreateFileW(str(p), 0x10080, 7, None, 3, 0, None)
        if handle == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
        kernel.CloseHandle.argtypes = [C.c_void_p]
        kernel.CloseHandle.restype = C.c_int
        try:
            class Standard(C.Structure):
                _fields_ = [('allocation', C.c_int64), ('size', C.c_int64),
                            ('links', C.c_uint32), ('deleted', C.c_ubyte), ('directory', C.c_ubyte)]
            kernel.GetFileInformationByHandleEx.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint32]
            kernel.GetFileInformationByHandleEx.restype = C.c_int
            p.unlink()
            info = Standard()
            if not kernel.GetFileInformationByHandleEx(handle, 1, C.byref(info), C.sizeof(info)):
                raise C.WinError(C.get_last_error())
            self.assertTrue(info.deleted)
            with self.assertRaises(OSError) as denied:
                allocation._allocated_bytes(p, s)
            print('delete-pending allocation denied:', repr(denied.exception), file=sys.stderr)
            # POSIX unlink can hide the name while the held handle is delete-pending.
            self.assertIn(denied.exception.winerror, (2, 5, 303))
            with self.assertRaises(OSError):
                identity.sealed_stat(dict(path=str(p), stat={}))
        finally:
            if not kernel.CloseHandle(handle): raise C.WinError(C.get_last_error())
        self.assertFalse(p.exists())

    def setUp(self):
        self.root = type(self).root/self._testMethodName
        self.root.mkdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    native = parser.add_mutually_exclusive_group()
    native.add_argument('--native', type=Path, metavar='FRESH_DIRECTORY')
    parser.add_argument('--point-addition', nargs=2, action='append', default=[], metavar=('PATH', 'SHA256'))
    native.add_argument('--after-exit', type=Path, metavar='COMPLETED_LINUX_OUTPUT')
    parser.add_argument('--result-sha256')
    native.add_argument('--native-metadata', type=Path, metavar='FRESH_LINUX_OUTPUT', help='complete recorded-inventory Storage comparison')
    parser.add_argument('--baseline', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--plan', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--bindings', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--previous-result', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--control-helper', nargs=2, metavar=('PATH', 'SHA256'))
    parser.add_argument('--runtime-addition', nargs=2, action='append', default=[], metavar=('PATH', 'SHA256'))
    parser.add_argument('--evidence-owner', type=Path)
    parser.add_argument('--tiny-origin-carry', type=int)
    args = parser.parse_args()
    cases = (AllocationControls,)
    if (args.native or args.native_metadata or args.after_exit) and os.name != 'nt':
        parser.error('native controls require native Windows Python')
    if args.after_exit:
        if not args.result_sha256 or not sys.flags.isolated or not sys.dont_write_bytecode or sys.flags.optimize:
            parser.error('exact result hash and isolated -I -B execution required')
        comparison_after_exit(args.after_exit, args.result_sha256)
        raise SystemExit(0)
    if args.native:
        args.native.mkdir(parents=True, exist_ok=False)
        NativeControls.root = args.native.absolute()
        cases = (NativeControls,)
    elif args.native_metadata:
        if not all((args.baseline, args.plan, args.bindings, args.previous_result, args.control_helper,
                    args.evidence_owner, args.tiny_origin_carry is not None)) or args.tiny_origin_carry < 0:
            parser.error('complete pinned comparison inputs and original carry required')
        NativeReadOnlyControls.options = args
        NativeReadOnlyControls.output = args.native_metadata.absolute()
        cases = (NativeReadOnlyControls,)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
