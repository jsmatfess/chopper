"""Fake-only SMALL supervisor controls. --native-probe is explicit and parent-owned."""
import sys
sys.dont_write_bytecode = True

import ctypes
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

selected_runner = Path(__file__).with_name('browser-small-runner.py')
if ((len(sys.argv) == 10 and sys.argv[1] == '--native-cancel-control')
        or (len(sys.argv) == 11 and sys.argv[1] == '--native-node-control-io')
        or (len(sys.argv) == 9 and sys.argv[1] in ('--native-control-io-stress','--native-sealed-job-control','--native-storage-rescan-control','--native-receipt-census-control','--native-browser-scale-control','--native-browser-scale-capacity','--native-browser-scale-after-exit'))):
    import hashlib
    selected_runner = Path(sys.argv[2])
    with selected_runner.open('rb') as source: selected_body=source.read(1024**2+1)
    assert len(selected_body)<=1024**2 and hashlib.sha256(selected_body).hexdigest() == sys.argv[3], 'Selected runtime SHA256'
    if sys.argv[1] in ('--native-sealed-job-control','--native-storage-rescan-control','--native-receipt-census-control','--native-node-control-io','--native-browser-scale-control','--native-browser-scale-capacity','--native-browser-scale-after-exit'):
        map_index=9 if sys.argv[1]=='--native-node-control-io' else 6
        bound=1024**2 if sys.argv[1].startswith('--native-browser-scale') else 65536
        with Path(sys.argv[map_index]).open('rb') as source:raw=source.read(bound+1)
        assert len(raw)<=bound and hashlib.sha256(raw).hexdigest()==sys.argv[map_index+1], 'Component source map SHA256/bound'
        control_sources=json.loads(raw)
        assert control_sources['schema']==('chopper-browser-scale-control-v1' if sys.argv[1].startswith('--native-browser-scale') else 'chopper-small-sealed-job-control-v1' if sys.argv[1]=='--native-sealed-job-control' else 'chopper-small-storage-rescan-control-v1' if sys.argv[1]=='--native-storage-rescan-control' else 'chopper-node-control-io-v1' if sys.argv[1]=='--native-node-control-io' else 'chopper-small-receipt-census-control-v1')
        total=0
        for row in control_sources['code']+[control_sources['python']]:
            with Path(row['path']).open('rb') as source:body=source.read(16*1024**2+1)
            total+=len(body)
            assert total<=16*1024**2 and hashlib.sha256(body).hexdigest()==row['sha256'], 'Component dependency SHA256/bound'
        assert Path(control_sources['python']['path'])==Path(sys.executable), 'Selected actual Python'
        key='after_root' if sys.argv[1]=='--native-browser-scale-after-exit' else 'root'
        assert Path(control_sources[key])==Path(sys.argv[8]), 'Component output declaration'
    selected_scripts = selected_runner.resolve().parent
    for name, loaded in tuple(sys.modules.items()):
        if name == 'scale_acceptance' or name.startswith('scale_acceptance.'):
            origins = [loaded.__file__] if getattr(loaded, '__file__', None) else list(loaded.__path__)
            assert all(Path(origin).resolve().is_relative_to(selected_scripts / 'scale_acceptance')
                       for origin in origins), 'Selected runtime helper origin: ' + name
    sys.path.insert(0, str(selected_scripts))
spec = importlib.util.spec_from_file_location('small', selected_runner)
small = importlib.util.module_from_spec(spec)
spec.loader.exec_module(small)


class Controls(unittest.TestCase):
    def test_component_original_and_exact_subprocess_under_real_audit(self):
        from scale_acceptance.native_scale_host import module
        checker=module('acceptance-preflight');ci=module('local-ci')
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);output=base/'output';output.mkdir()
            lock=base/'original.lock';lock.touch();escape=base/'forbidden'
            budget=checker.Budget(dict(seconds=10,read_bytes=8*1024**2,visits=10000,
                capture_bytes=65536,storage_bytes=1024**2),output)
            budget.install()
            try:
                with patch.object(ci,'host_lock_path',return_value=lock):
                    with self.assertRaisesRegex(ValueError,'preflight mutation denied'):
                        with ci.host_lock():pass
                    with component_original(ci,budget):
                        self.assertTrue(budget.active)
                        with self.assertRaisesRegex(ValueError,'preflight source mutation denied'):
                            escape.write_bytes(b'no')
                        argv=[sys.executable.replace(os.sep,os.sep+os.sep),'-B','-c','pass']
                        with self.assertRaisesRegex(ValueError,'unexpected preparation subprocess'):
                            subprocess.run(argv,check=True,timeout=3)
                        plan=output/'plan.json'
                        plan.write_text(json.dumps(dict(root=str(output),batch_timeout_seconds=3,
                            estimated_seconds=1,estimated_disk_bytes=65536,
                            toolchains={},features=[],fixtures=[],steps=[dict(id='real-command',argv=argv,
                            inputs=['plan.json'],artifacts=[],depends=[],timeout_seconds=3)])))
                        # Use the owning runner, which resolves executable spelling
                        # before its Popen audit event (including Windows separators).
                        key=budget.command_key([str(Path(argv[0]).resolve()),*argv[1:]])
                        budget.allowed_commands.add(key)
                        try:self.assertEqual(small.runner.run(plan,output/'runner'),0)
                        finally:budget.allowed_commands.discard(key)
                self.assertFalse(escape.exists())
            finally:budget.active=False
            with patch.object(ci,'host_lock_path',return_value=lock),ci.host_lock():pass

    def test_independent_original_probe_has_only_exact_open_audit_exception(self):
        from scale_acceptance.native_scale_host import module
        from scale_acceptance import hosted_qualification as q
        from types import SimpleNamespace
        checker=module('acceptance-preflight')
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);output=base/'output';output.mkdir()
            original=base/'original';original.write_bytes(b'original')
            stamp=original.stat();outside=base/'forbidden'
            budget=checker.Budget(dict(seconds=5,read_bytes=1024**2,visits=1000),output)
            budget.install()
            def locking(fd,operation,count):
                self.assertTrue(budget.active)
                self.assertEqual(os.read(fd,8),b'original')
                with self.assertRaisesRegex(ValueError,'source mutation denied'):outside.write_bytes(b'no')
            try:
                with self.assertRaisesRegex(ValueError,'source mutation denied'):os.open(original,os.O_RDWR)
                with patch.dict(sys.modules,msvcrt=SimpleNamespace(locking=locking,LK_NBLCK=1)):
                    result=q.independent_observation(None,[],dict(released_after_supervision=True,
                        original_lock_identity=[stamp.st_dev,stamp.st_ino]),original,time.monotonic()+5,{},budget=budget)
                self.assertTrue(result['probe_closed']);self.assertTrue(result['original_byte0_available'])
                self.assertTrue(budget.active);self.assertFalse(outside.exists())
            finally:budget.active=False
        facts=q.current_process_facts([dict(process_identities=[dict(pid=1,created=10),dict(pid=2,created=20)])])
        self.assertEqual(facts,[dict(pid=1,created=[10]),dict(pid=2,created=[20])])

    def test_node_control_uses_exact_owning_atomic_function(self):
        body=Path(__file__).with_name('scale_acceptance').joinpath('browser-scale-driver.mjs').read_text()
        source=node_control_writer(body)
        start=body.index('  const atomic = async (name, value) => {')
        atomic=body[start:body.index('  let context, browser, page, server, watcher, stopping = false;',start)]
        self.assertIn(atomic,source)
        self.assertNotIn('launchPersistentContext',source)
        with self.assertRaises(OSError):node_control_writer(body+body)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_qualification_denies_before_supervisor_on_missing_preflight_or_config_drift(self):
        plan=self.root/'plan.json';config=self.root/'config.json'
        config.write_text('{}');plan.write_text(json.dumps(dict(config=dict(changed=True))))
        with patch('scale_acceptance.hosted_qualification.preflight', side_effect=ValueError('failed preflight')), patch.object(small,'supervise') as launch:
            with self.assertRaisesRegex(ValueError,'failed preflight'):
                small.qualify(plan,'a'*64,config,{})
            launch.assert_not_called()
        with patch('scale_acceptance.hosted_qualification.preflight'),patch.object(small,'supervise') as launch:
            with self.assertRaisesRegex(OSError,'config/plan mismatch'):
                small.qualify(plan,'a'*64,config,{})
            launch.assert_not_called()

    def test_first_command_control_is_scoped_and_normal_qualification_requires_all_fifteen(self):
        plan_path=self.root/'plan.json';config_path=self.root/'config.json';owned=self.root/'owned'
        config=dict(channel='chrome',owned_root=str(owned),commands=small.command_specs(first_only=True))
        def write():
            config_path.write_text(json.dumps(config));plan_path.write_text(json.dumps(dict(config=config,frozen=[],inventories={})))
        write()
        with patch('scale_acceptance.hosted_qualification.preflight'),patch.object(small,'supervise') as launch:
            with self.assertRaisesRegex(OSError,'Full fifteen-command'):small.qualify(plan_path,'a'*64,config_path,{})
            launch.assert_not_called()
        config['commands']=small.command_specs()[1:2];write()
        with patch('scale_acceptance.hosted_qualification.preflight'),patch.object(small,'supervise') as launch:
            with self.assertRaisesRegex(OSError,'Exact first-command'):
                small.qualify(plan_path,'a'*64,config_path,{},first_command_control=True)
            launch.assert_not_called()
        config['commands']=small.command_specs(first_only=True);write()
        def completed(*args):
            owned.mkdir();(owned/'result.json').write_text('{"passed":true}')
            (owned/'reservation-released.json').write_text('{"passed":true}')
            return 0
        with patch('scale_acceptance.hosted_qualification.preflight'),patch.object(small,'supervise',side_effect=completed):
            self.assertEqual(small.qualify(plan_path,'a'*64,config_path,{},first_command_control=True),0)
        result=json.loads((owned/'component-result.json').read_text())
        self.assertFalse(result['qualification']);self.assertTrue(result['passed'])
        self.assertFalse((owned/'tiny-qualification.json').exists())

    def test_full_qualification_keeps_authoritative_fifteen_selection(self):
        self.assertEqual(len(small.command_specs()),15)
        self.assertEqual(small.command_specs(first_only=True),small.command_specs()[:1])
        self.assertEqual(sum(c['timeout_seconds'] for c in small.command_specs()),6750)

    def test_timed_out_operation_remains_owned_until_actual_thread_exit(self):
        release=threading.Event()
        try:
            with self.assertRaisesRegex(OSError,'late/blocked'):
                small.bounded_cleanup(lambda:release.wait(),timeout=.01)
            self.assertTrue(any(t.is_alive() for t in small.OPERATIONS))
        finally:
            release.set()
            for thread in small.OPERATIONS:thread.join(1)
        self.assertFalse(any(t.is_alive() for t in small.OPERATIONS))

    def test_probe_imports_preserve_source_namespace_without_inherited_bytecode_setting(self):
        import shutil
        for name in ('test-browser-small-runner.py', 'browser-small-runner.py',
                     'browser-small-windows.py', 'validation-runner.py'):
            shutil.copyfile(Path(__file__).with_name(name), self.root / name)
        environment = dict(os.environ)
        environment.pop('PYTHONDONTWRITEBYTECODE', None)
        result = subprocess.run([sys.executable, '-c',
            'import runpy,sys; runpy.run_path(sys.argv[1], run_name="probe_import_control")',
            str(self.root / Path(__file__).name)], env=environment,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.root.rglob('*.pyc')), [])
        self.assertEqual(list(self.root.rglob('__pycache__')), [])

    def test_transfer_probe_launches_python_with_bytecode_disabled(self):
        class Captured(Exception):
            pass
        with patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
             patch.object(subprocess, 'Popen', side_effect=Captured) as launch:
            with self.assertRaises(Captured):
                native_transfer_probe(self.root)
        self.assertEqual(launch.call_args.args[0],
                         [sys.executable, '-B', str(self.root / 'transfer-worker.py')])

    def observation_fixture(self, count=2):
        steps = [dict(id=f'contract-{i+1}') for i in range(count)]
        writer = small.StatusWriter(self.root/'runner-observation.json', 123, 'a'*64, 'unique-owner', steps)
        reader = small.StatusReader(123, 'a'*64, 'unique-owner', steps)
        def publish(statuses=(), terminal=False):
            snapshot = small.runner.StatusObservation(tuple(small.runner.AttemptObservation(
                steps[i]['id'], i+1, status) for i, status in enumerate(statuses)), terminal)
            writer(snapshot)
            return reader.read(writer.path)
        return writer, reader, publish

    def test_observation_transitions_coalescing_replay_substitution_and_terminal(self):
        writer, reader, publish = self.observation_fixture()
        first = publish()
        running = publish(['running'])
        # Coalesce intermediate pass/start checkpoints, just like a slow reader.
        writer(small.runner.StatusObservation((small.runner.AttemptObservation('contract-1', 1, 'passed'),), False))
        value = publish(['passed', 'running'])
        self.assertEqual(reader.read(writer.path), value)  # unchanged read, no new progress
        with self.assertRaisesRegex(OSError, 'replay'):
            reader.accept(running)
        with self.assertRaises(OSError):
            reader.accept(dict(value, attempts=[dict(value['attempts'][0]), dict(value['attempts'][1], status='failed')]))
        completed = publish(['passed', 'passed'])
        with self.assertRaisesRegex(OSError, 'checkpoint substitution'):
            reader.accept(dict(completed, attempts=[dict(completed['attempts'][0]), dict(completed['attempts'][1], status='failed')]))
        final = publish(['passed', 'passed'], True)
        with self.assertRaises(OSError):
            reader.accept(first)
        with self.assertRaises(OSError):
            reader.accept(dict(final, sequence=7))
        self.assertLess(writer.path.stat().st_size, small.OBSERVATION_BYTES)

    def test_observation_rejects_unknown_malformed_bindings_prefixes_and_types(self):
        import copy
        writer, reader, publish = self.observation_fixture()
        initial = publish()
        cases = [dict(initial, runner_pid=999), dict(initial, runner_pid=True),
                 dict(initial, runner_plan_sha256='b'*64), dict(initial, owner='old-owner'),
                 dict(initial, schema='unknown'), dict(initial, extra='unknown'),
                 dict(initial, terminal=1), dict(initial, sequence=True),
                 dict(initial, attempts={}), dict(initial, attempts=[{}])]
        for entry in [dict(id='wrong', attempt=1, status='running'),
                      dict(id='contract-1', attempt=True, status='running'),
                      dict(id='contract-1', attempt=2, status='running'),
                      dict(id='contract-1', attempt=1, status='unknown'),
                      dict(id='contract-1', attempt=1, status=[]),
                      dict(id='contract-1', attempt=1, status='running', extra=1)]:
            cases.append(dict(initial, sequence=2, attempts=[entry]))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(OSError):
                reader.accept(copy.deepcopy(value))
        for raw in [b'{', b'null', b'[]', b'\xff', b' '* (small.OBSERVATION_BYTES+1),
                    b'{"schema":1,"schema":2}']:
            writer.path.write_bytes(raw)
            with self.subTest(raw=raw[:30]), self.assertRaises(OSError):
                reader.read(writer.path)
        writer.path.unlink()
        with self.assertRaises(OSError):
            reader.read(writer.path)

    def test_observation_failed_prefix_regression_and_terminal_coverage(self):
        writer, reader, publish = self.observation_fixture()
        publish()
        publish(['running'])
        passed = publish(['passed'])
        for statuses, terminal in [(['passed'], True), (['running'], True),
                                    (['failed', 'running'], False), (['running', 'running'], False)]:
            attempts = [dict(id=f'contract-{i+1}', attempt=i+1, status=v) for i, v in enumerate(statuses)]
            with self.subTest(statuses=statuses), self.assertRaises(OSError):
                reader.accept(dict(passed, attempts=attempts, terminal=terminal, sequence=4))
        with self.assertRaises(OSError):
            reader.accept(dict(passed, attempts=[dict(passed['attempts'][0], status='failed')], terminal=True, sequence=4))
        for status in ('failed', 'timeout', 'interrupted', 'invalidated'):
            other = small.StatusReader(123, 'a'*64, 'unique-owner', [dict(id='contract-1'), dict(id='contract-2')])
            self.assertEqual(other.accept(dict(passed, attempts=[dict(passed['attempts'][0], status=status)],
                                              terminal=True, sequence=4))['attempts'][0]['status'], status)

    def test_mutable_control_errors_are_not_retried_or_suppressed(self):
        writer, reader, publish = self.observation_fixture()
        publish()
        for code in (5, 32, 123):
            error = PermissionError('genuine control I/O failure')
            error.winerror = code
            with patch.object(small.windows, 'read_control_snapshot', side_effect=error) as read:
                with self.assertRaises(PermissionError) as raised:
                    reader.read(writer.path)
                self.assertIs(raised.exception, error)
                read.assert_called_once()
            writer, _, _ = self.observation_fixture()
            with patch.object(small.windows, 'replace_control_snapshot', side_effect=error) as replace:
                with self.assertRaises(PermissionError) as raised:
                    writer(small.runner.StatusObservation((), False))
                self.assertIs(raised.exception, error)
                replace.assert_called_once()

    def test_control_rename_buffer_has_explicit_utf16_terminator(self):
        import ctypes
        for name in ['C:/t/'+'x'*n for n in range(1,5)]+['C:/t/é😀']:
            encoded=str(Path(name)).encode('utf-16-le')
            info,size=small.windows._control_rename_information(Path(name))
            end=20+len(encoded)
            self.assertGreaterEqual(size,end+2,'Terminator must be inside the submitted buffer')
            self.assertLessEqual(size,ctypes.sizeof(info))
            raw=ctypes.string_at(ctypes.addressof(info),size)
            self.assertEqual(info.length,len(encoded))
            self.assertEqual(raw[20:end],encoded)
            self.assertEqual(raw[end:end+2],b'\0\0')

    def test_control_snapshots_bound_bytes_and_reject_foreign_path_shapes(self):
        windows = small.windows
        path = self.root/'guard.json'
        small.write_control_json(path, dict(epoch=1))
        self.assertEqual(json.loads(windows.read_control_snapshot(path, 64)), dict(epoch=1))
        small.write_control_json(path, dict(epoch=2))
        self.assertEqual(json.loads(windows.read_control_snapshot(path, 64)), dict(epoch=2))
        path.write_bytes(b'x'*65)
        with self.assertRaisesRegex(OSError, 'oversized'):
            windows.read_control_snapshot(path, 64)
        for bound in (0, True, 1024**2+1):
            with self.assertRaises(ValueError):windows.read_control_snapshot(path, bound)
        source = self.root/'source.tmp';source.write_text('new')
        other = self.root/'other';other.mkdir()
        with self.assertRaisesRegex(OSError, 'same-directory'):
            windows.replace_control_snapshot(source, other/'guard.json')
        with self.assertRaisesRegex(OSError, 'plain control'):
            windows.replace_control_snapshot(source, other)
        self.assertEqual(source.read_text(), 'new')
        link = self.root/'foreign-link.json'
        try:
            link.symlink_to(path)
        except OSError:
            return  # native symlink creation may require a developer privilege
        with self.assertRaises(OSError):windows.read_control_snapshot(link, 64)
        with self.assertRaisesRegex(OSError, 'plain control'):
            windows.replace_control_snapshot(source, link)
        self.assertEqual(source.read_text(), 'new')

    def test_control_hardlinks_deny_and_replaced_old_snapshot_can_be_unlinked(self):
        windows=small.windows
        source=self.root/'source.tmp';source.write_bytes(b'new')
        target=self.root/'guard.json';target.write_bytes(b'old')
        link=self.root/'hardlink';os.link(source,link)
        with self.assertRaises(OSError):windows.replace_control_snapshot(source,target)
        with self.assertRaises(OSError):windows.read_control_snapshot(source,64)
        link.unlink();os.link(target,link)
        with self.assertRaises(OSError):windows.replace_control_snapshot(source,target)
        link.unlink()
        original=os.read;links=[]
        def read(fd,size):
            links.append(os.fstat(fd).st_nlink)
            windows.replace_control_snapshot(source,target)
            links.append(os.fstat(fd).st_nlink)
            return original(fd,size)
        with patch.object(windows.os,'read',side_effect=read):
            self.assertEqual(windows.read_control_snapshot(target,64),b'old')
        self.assertEqual(links,[1,0])
        self.assertEqual(windows.read_control_snapshot(target,64),b'new')

    def test_control_snapshot_close_failure_keeps_primary_and_retains_empty_job(self):
        from types import SimpleNamespace
        windows = small.windows
        path = self.root/'guard.json';path.write_bytes(b'owned')
        opened = []
        real_open, real_close = os.open, os.close
        def open_file(*args):
            fd=real_open(*args);opened.append(fd);return fd
        try:
            with patch.object(windows.os, 'open', side_effect=open_file), \
                 patch.object(windows, '_control_open', side_effect=lambda *args:(open_file(str(path), os.O_RDONLY), 2**40)), \
                 patch.object(windows.os, 'read', side_effect=OSError('primary read failure')), \
                 patch.object(windows.os, 'close', side_effect=OSError('close uncertain')):
                with self.assertRaises(windows.ControlFileCloseError) as caught:
                    windows.read_control_snapshot(path, 64)
            reservation = {}
            causes = small.error_causes(caught.exception, reservation)
            self.assertTrue(reservation['process_handle_close_uncertain'])
            self.assertEqual(causes[0]['path'], str(path))
            self.assertEqual(causes[0]['api'], 'close')
            self.assertIn('primary read failure', str(caught.exception.__cause__.__context__))
        finally:
            for fd in opened:real_close(fd)
        process = SimpleNamespace(returncode=91, poll=lambda:91, wait=lambda timeout:91)
        with patch.object(windows,'query_job',return_value=dict(pids=[])), \
             patch.object(windows,'terminate'),patch.object(windows,'close'):
            errors=small.finish_supervision({}, self.root, process, 123, reservation, None, None, 'failed I/O')
        self.assertIn('Parent handle close unproven', errors)
        self.assertFalse(reservation['release_safe'])

    def test_control_json_override_is_explicit_and_immutable_default_unchanged(self):
        source = self.root/'default.json'
        real_replace = small.os.replace
        with patch.object(small.os, 'replace', wraps=real_replace) as default, \
             patch.object(small.windows, 'replace_control_snapshot', wraps=small.windows.replace_control_snapshot) as control:
            small.runner.write_json(source, dict(immutable=True))
            control.assert_not_called()
            self.assertEqual(default.call_count, 1)
            small.write_control_json(self.root/'guard.json', dict(allowed=True))
            control.assert_called_once()
        info, size = small.windows._control_rename_information('C:\\owned\\guard-\U0001f4c4.json')
        self.assertEqual(info.flags, 3)
        self.assertGreaterEqual(size, 20+info.length+2)

    def test_representative_large_metadata_keeps_full_provenance_and_small_observations(self):
        # Three real tiny subprocesses; synthetic 14730-entry identity maps only.
        # No browser, engine, WASM, frozen workspace, or installed-channel launch.
        executable = str(Path(sys.base_prefix)/'python.exe') if os.name == 'nt' else sys.executable
        steps = [dict(id=f'contract-{i+1}', inputs=['declared'], artifacts=[],
            argv=[executable, '-c', 'pass'], timeout_seconds=3,
            depends=[f'contract-{i}'] if i else []) for i in range(3)]
        plan = dict(root=str(self.root), batch_timeout_seconds=30, estimated_seconds=1,
            estimated_disk_bytes=32*1024**2, toolchains={}, features=[], fixtures=['synthetic metadata'], steps=steps)
        path = self.root/'runner-plan.json'
        small.runner.write_json(path, plan)
        writer = small.StatusWriter(self.root/'runner-observation.json', os.getpid(), small.runner.digest(path), 'large-control', steps)
        metadata = {f'input-{i:05}': dict(sha256='b'*64, size=i, mtime_ns=123, ctime_ns=456,
                    device=1, inode=i, resolved=str(self.root/f'input-{i:05}')) for i in range(14730)}
        lengths = []
        def observe(value):
            writer(value)
            lengths.append(writer.path.stat().st_size)
        with patch.object(small.runner, 'identity', side_effect=lambda root, patterns: metadata if patterns else {}):
            self.assertEqual(small.runner.run(path, self.root/'batch', observe=observe), 0)
        state = json.loads((self.root/'batch/status.json').read_text())
        self.assertEqual(len(state['attempts']), 3)
        self.assertTrue(all(a['inputs'] == metadata and a['artifacts'] == {} for a in state['attempts']))
        self.assertGreater((self.root/'batch/status.json').stat().st_size, 10*1024**2)
        self.assertLess(max(lengths), small.OBSERVATION_BYTES)
        self.assertEqual(len(lengths), 8)
        self.assertEqual(json.loads((self.root/'batch/manifest.json').read_text()), plan)
        final = small.StatusReader(os.getpid(), small.runner.digest(path), 'large-control', steps).read(writer.path)
        self.assertTrue(final['terminal'])
        self.assertTrue(all(a['status'] == 'passed' for a in final['attempts']))
        print(json.dumps(dict(control='synthetic metadata only', attempts=3, inputs_per_attempt=14730,
            rich_status_bytes=(self.root/'batch/status.json').stat().st_size,
            compact_max_bytes=max(lengths), callbacks=len(lengths))))

    def supervision_fixture(self, *, terminal=True, cleanup=True):
        from types import SimpleNamespace
        writer, reader, publish = self.observation_fixture(1)
        publish()
        publish(['running'])
        publish(['passed'])
        if terminal:
            publish(['passed'], True)
        (self.root/'worker-result.json').write_text('{"code":0}')
        resources = dict(storage=SimpleNamespace(), pinned=[dict(path=str(self.root/'runner-plan.json'), sha256='a'*64)],
                         last_progress_ms=small.now_ms()-1000)
        plan = dict(config=dict(node='fake-node'), runner_plan=dict(steps=[dict(id='contract-1')]),
                    packets=[dict(value=dict(receipt='fake-receipt'))], reservation='unique-owner',
                    storage_method='fake high-water', batch_started_ms=resources['last_progress_ms'])
        process = SimpleNamespace(pid=123, poll=lambda: None)
        watchdog = SimpleNamespace(pulse=lambda: None)
        class Receipt:
            cleaned = False
            pending_exit = None
            def read(self, *args, **kwargs):
                self.cleaned = cleanup
        return resources, plan, process, watchdog, Receipt

    def test_live_supervision_reads_only_compact_status_and_progress_requires_cleanup(self):
        resources, plan, process, watchdog, receipt = self.supervision_fixture()
        # A rich audit file is deliberately unreadable JSON; live code must never decode it.
        (self.root/'batch').mkdir()
        (self.root/'batch/status.json').write_text('rich audit never read')
        original = Path.open
        def no_rich(path, *args, **kwargs):
            self.assertNotEqual(path, self.root/'batch/status.json')
            return original(path, *args, **kwargs)
        with patch.object(small, 'Receipts', receipt), patch.object(small, 'sample_resources',
                return_value=(dict(pids=[123], kill_on_close=True, flags=8192), [], [], 0)), \
                patch.object(small, 'census_child', return_value=None), patch.object(Path, 'open', no_rich):
            small.run_supervision(plan, self.root, process, 1, {}, watchdog, {}, resources)
        self.assertGreater(resources['last_progress_ms'], plan['batch_started_ms'])
        self.assertTrue((self.root/'guard.json').exists())

    def test_live_missing_failed_terminal_and_missing_cleanup_fail_closed(self):
        for fault in ('missing', 'malformed', 'terminal', 'cleanup', 'failure'):
            with self.subTest(fault=fault):
                # Each case owns independent observer/receipt state and retains its files.
                resources, plan, process, watchdog, receipt = self.supervision_fixture(
                    terminal=fault != 'terminal', cleanup=fault != 'cleanup')
                path = self.root/'runner-observation.json'
                if fault == 'missing':
                    path.unlink()
                elif fault == 'malformed':
                    path.write_text('{')
                elif fault == 'failure':
                    value = json.loads(path.read_text())
                    value['attempts'][0]['status'] = 'failed'
                    path.write_text(json.dumps(value))
                previous = resources['last_progress_ms']
                with patch.object(small, 'Receipts', receipt), patch.object(small, 'sample_resources',
                        return_value=(dict(pids=[123], kill_on_close=True, flags=8192), [], [], 0)), \
                        patch.object(small, 'census_child', return_value=None), self.assertRaises(OSError):
                    small.run_supervision(plan, self.root, process, 1, {}, watchdog, {}, resources)
                self.assertEqual(resources['last_progress_ms'], previous)

    def test_observation_bounded_reader_never_loads_oversized_payload(self):
        writer, reader, publish = self.observation_fixture()
        writer.path.write_bytes(b' '*(small.OBSERVATION_BYTES*10))
        sizes = []
        original = os.read
        def read(fd,size):
            sizes.append(size)
            return original(fd,size)
        with patch.object(small.windows.os, 'read', side_effect=read):
            with self.assertRaisesRegex(OSError, 'oversized'):
                reader.read(writer.path)
        self.assertEqual(sizes, [small.OBSERVATION_BYTES+1])

    def test_reconciliation_uses_original_hot_endpoint_including_launch_delay(self):
        resources,plan,process,watchdog,_ = self.supervision_fixture()
        original=small.operation
        launched,observed=[],[]
        def delayed(action):
            launched.append(time.monotonic())
            time.sleep(.03)
            return original(action)
        def sample(*args,**kwargs):
            observed.append((kwargs['deadline'],time.monotonic()))
            raise OSError('end bounded fake sample')
        with patch.object(small,'operation',side_effect=delayed), \
             patch.object(small,'sample_resources',side_effect=sample):
            with self.assertRaisesRegex(OSError,'end bounded fake sample'):
                small.run_supervision(plan,self.root,process,1,{},watchdog,{},resources)
        self.assertEqual(len(observed),1)
        endpoint,entered=observed[0]
        self.assertLessEqual(endpoint,launched[0]+.8)
        self.assertGreaterEqual(entered+.8-endpoint,.02,'Launch delay must consume the original budget')

    def test_running_metadata_and_quota_samples_do_not_refresh_progress(self):
        resources, plan, process, watchdog, receipt = self.supervision_fixture()
        (self.root/'worker-result.json').unlink()
        writer, reader, publish = self.observation_fixture(1)
        publish()
        publish(['running'])
        previous = resources['last_progress_ms']
        def pulse():
            raise OSError('stop fake heartbeat after running sample')
        watchdog.pulse = pulse
        with patch.object(small, 'Receipts', receipt), patch.object(small, 'sample_resources',
                return_value=(dict(pids=[123], kill_on_close=True, flags=8192), [], [], 12345)), \
                patch.object(small, 'census_child', return_value=None):
            with self.assertRaisesRegex(OSError, 'stop fake heartbeat'):
                small.run_supervision(plan, self.root, process, 1, {}, watchdog, {}, resources)
        self.assertEqual(resources['last_progress_ms'], previous)

    def test_blocked_observation_is_inside_existing_sample_bound(self):
        resources, plan, process, watchdog, receipt = self.supervision_fixture()
        release, finished = threading.Event(), threading.Event()
        def blocked(*args):
            release.wait()
            finished.set()
            raise OSError('released after observation denial')
        watchdog.pulse = lambda: self.fail('blocked observation published heartbeat')
        try:
            with patch.object(small, 'sample_resources', return_value=(dict(pids=[123]), [], [], 0)), \
                    patch.object(small.StatusReader, 'read', side_effect=blocked):
                with self.assertRaisesRegex(OSError, 'guard sample late/blocked'):
                    small.run_supervision(plan, self.root, process, 1, {}, watchdog, {}, resources)
            self.assertEqual(resources['sample_trace'][-1]['phase'], 'runner-observation')
            self.assertEqual(resources['sample_trace'][-1]['event'], 'start')
            self.assertFalse((self.root/'guard.json').exists())
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_command_handshake_publishes_once_per_attempt_and_never_replaces_prior(self):
        published = set()
        original = small.runner.write_json
        with patch.object(small.runner, 'write_json', wraps=original) as write:
            small.publish_command_ready(self.root, 1, published)
            first = small.command_ready_path(self.root, 1)
            before = (first.stat().st_ino, first.stat().st_mtime_ns, first.read_bytes())
            for _ in range(3):
                small.publish_command_ready(self.root, 1, published)
            self.assertEqual(write.call_count, 1)
            small.publish_command_ready(self.root, 2, published)
            small.publish_command_ready(self.root, 2, published)
            self.assertEqual(write.call_count, 2)
        self.assertEqual(before, (first.stat().st_ino, first.stat().st_mtime_ns, first.read_bytes()))
        self.assertEqual(json.loads(small.command_ready_path(self.root, 2).read_text()), dict(attempt=2))
        self.assertEqual(published, {1, 2})

    def test_failed_handshake_publication_and_outside_selection_deny(self):
        published = set()
        with patch.object(small.runner, 'write_json', side_effect=PermissionError('native write denied')):
            with self.assertRaisesRegex(PermissionError, 'native write denied'):
                small.publish_command_ready(self.root, 1, published)
        self.assertFalse(published)
        for attempt in (0, 16, True):
            with self.subTest(attempt=attempt), self.assertRaisesRegex(OSError, 'outside fixed selection'):
                small.command_ready_path(self.root, attempt)

    def test_worker_handshake_rejects_stale_leaf_and_wrong_attempt_without_retrying_access(self):
        import ast
        from types import SimpleNamespace
        tree = ast.parse(Path(small.__file__).read_bytes())
        worker = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'worker')
        guard = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == 'guard')
        overall = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == 'check_overall')
        # Execute the actual nested worker guard; bind its closure as a tiny enclosing function.
        enclosing = ast.FunctionDef(name='make', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
            body=[ast.Assign(targets=[ast.Name(id='last_attempt', ctx=ast.Store())], value=ast.Constant(0)), overall, guard,
                  ast.Return(value=ast.Name(id='guard', ctx=ast.Load()))], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[enclosing], type_ignores=[]))
        small.runner.write_json(small.command_ready_path(self.root, 1), dict(attempt=1))
        for wrong in (False, True):
            if wrong:
                small.runner.write_json(small.command_ready_path(self.root, 2), dict(attempt=1))
            scope = dict(stop=None,writer=SimpleNamespace(current=SimpleNamespace(attempts=[1, 2])), owned=self.root,
                         command_ready_path=small.command_ready_path, need=small.need, json=json,
                         time=SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 6]), sleep=Mock()))
            exec(compile(module, '<actual-worker-handshake>', 'exec'), scope)
            with self.assertRaisesRegex(OSError, 'handshake timed out'):
                scope['make']()()
        scope['stop']=0
        scope['time'].monotonic=Mock(return_value=0)
        with self.assertRaisesRegex(OSError,'Worker overall deadline'):scope['make']()()
        scope['stop']=None
        scope['time'].monotonic = Mock(return_value=0)
        scope['time'].sleep = Mock()
        with patch.object(Path, 'read_text', side_effect=PermissionError('read denied')):
            with self.assertRaisesRegex(PermissionError, 'read denied'):
                scope['make']()()
        scope['time'].sleep.assert_not_called()

    def test_worker_uses_callback_snapshot_for_guard_and_publishes_before_ready(self):
        path = self.root/'runner-plan.json'
        steps = [dict(id='contract-1')]
        small.runner.write_json(path, dict(steps=steps, small_observation_owner='unique-owner'))
        small.runner.write_json(self.root/'command-ready-1.json', dict(attempt=1))
        small.runner.write_json(self.root/'guard.json', dict(allowed=True, sampled_ms=small.now_ms(), runner_pid=os.getpid()))
        original_write = small.runner.write_json
        def publish(path, value):
            original_write(path, value)
            if path.name == 'job.json':
                # The parent may start reading immediately after this signal.
                # Do not pre-create ready: initial observation must exist first.
                initial = small.StatusReader(os.getpid(), small.runner.digest(self.root/'runner-plan.json'),
                                             'unique-owner', steps).read(self.root/'runner-observation.json')
                self.assertEqual(initial['sequence'], 1)
                self.assertEqual(initial['attempts'], [])
                self.assertFalse((self.root/'ready.json').exists())
        def run(plan, batch, *, guard, observe):
            observe(small.runner.StatusObservation((), False))
            self.assertTrue((self.root/'ready.json').exists(), 'No command attempt before parent readiness')
            self.assertTrue((self.root/'runner-observation.json').exists())
            observe(small.runner.StatusObservation((small.runner.AttemptObservation('contract-1', 1, 'running'),), False))
            guard()  # no rich status exists; guard must use the immutable snapshot
            observe(small.runner.StatusObservation((small.runner.AttemptObservation('contract-1', 1, 'passed'),), False))
            observe(small.runner.StatusObservation((small.runner.AttemptObservation('contract-1', 1, 'passed'),), True))
            return 0
        def sleep(seconds):
            if seconds == .025:
                self.assertTrue((self.root/'job.json').exists())
                self.assertFalse((self.root/'ready.json').exists())
                if not (self.root/'job-owned.json').exists():
                    original_write(self.root/'job-owned.json', dict(runner_pid=os.getpid(), supervisor_pid=os.getppid(),
                        handle=456, execution_sha256=small.runner.digest(path)))
                else:
                    close.assert_called_once_with(456)
                    original_write(self.root/'ready.json', dict(runner_pid=os.getpid()))
                return
            self.assertEqual(seconds, .1)
            raise OSError('end fake cleanup wait')
        with patch.dict(os.environ, CHOPPER_SMALL_WORKER_PLAN_SHA256=small.runner.digest(path)), \
                patch.object(small, 'validate_worker_plan'), patch.object(small.runner, 'contain_session'), \
                patch.object(small.runner, 'owned_windows_job', return_value=dict(handle=456)), \
                patch.object(small.windows, 'close') as close, patch.object(small.runner, 'run', side_effect=run), \
                patch.object(small.runner, 'write_json', side_effect=publish), \
                patch.object(small.time, 'sleep', side_effect=sleep):
            with self.assertRaisesRegex(OSError, 'end fake cleanup wait'):
                small.worker(path, self.root)
        close.assert_called_once_with(456)
        self.assertEqual(json.loads((self.root/'worker-result.json').read_text()), dict(code=0))
        state = small.StatusReader(os.getpid(), small.runner.digest(path), 'unique-owner', steps).read(self.root/'runner-observation.json')
        self.assertTrue(state['terminal'])

    def test_graph_codec_explicit_library_and_ordinary_discovery(self):
        import io
        import runpy
        from unittest.mock import Mock
        helper = Path(__file__).with_name('graph-codec-fixtures.py')
        for mode in ('zstd-input', 'zstd-output'):
            for explicit in (None, str(self.root / 'declared-zstd.dll')):
                codec = Mock()
                codec.ZSTD_isError.return_value = 0
                codec.ZSTD_compressBound.return_value = 64
                codec.ZSTD_compress.return_value = 0
                codec.ZSTD_decompress.return_value = 0
                output = io.BytesIO()
                argv = [str(helper), mode] + ([explicit] if explicit else [])
                with patch.object(sys, 'argv', argv), \
                     patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'id\n1\n'))), \
                     patch.object(sys, 'stdout', io.TextIOWrapper(output)), \
                     patch('ctypes.util.find_library', return_value='system-zstd') as find, \
                     patch('ctypes.CDLL', return_value=codec) as load:
                    runpy.run_path(str(helper), run_name='__main__')
                    load.assert_called_once_with(explicit or 'system-zstd')
                    if explicit:
                        find.assert_not_called()
                    else:
                        find.assert_called_once_with('zstd')

        with patch.object(sys, 'argv', [str(helper), 'zstd-input', str(self.root / 'missing.dll')]), \
             patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'id\n1\n'))), \
             patch('ctypes.util.find_library') as find, \
             patch('ctypes.CDLL', side_effect=OSError('DLL missing')):
            with self.assertRaisesRegex(OSError, 'DLL missing'):
                runpy.run_path(str(helper), run_name='__main__')
            find.assert_not_called()

    def test_prepare_emits_exact_inert_manifest_and_rejects_variants_hashes_retries(self):
        root = self.root
        for name in ('scripts', 'ui/dist', 'ui/src', 'ui/tests', 'ui/node_modules'):
            (root / name).mkdir(parents=True, exist_ok=True)
        files = ['Cargo.toml', 'ui/package.json', 'ui/package-lock.json', 'ui/src/app.ts',
                 'ui/tests/resource-contract-tests.ts', 'ui/tests/resource-contract-worker.ts',
                 'node.exe', 'python.exe', 'browser.exe', 'zstd.dll']
        support = ['browser-small-runner.py', 'browser-small-windows.py', 'browser-small-bootstrap.mjs',
                   'browser-small-contract.mjs', 'browser-small-observer.mjs', 'browser-launch.mjs',
                   'browser-artifacts.mjs', 'browser-acceptance.mjs', 'serve-hosted.mjs',
                   'validation-runner.py', 'local-ci.py', 'test-browser.mjs', 'build-browser-tests.mjs',
                   'test-browser-graph.mjs', 'browser-graph-codec.mjs', 'graph-codec-fixtures.py']
        files += ['scripts/'+name for name in support]
        files += ['ui/dist/asset'+str(i) for i in range(7)] + ['package'+str(i)+'.zip' for i in range(3)]
        for name in files:
            (root / name).write_text('product UI' if name == 'ui/src/app.ts' else 'fake immutable bytes')
        assets = [str(root / ('ui/dist/asset'+str(i))) for i in range(7)]
        zips = [str(root / ('package'+str(i)+'.zip')) for i in range(3)]
        receipt = root / 'receipt.json'
        receipt.write_text(json.dumps(dict(release_source_tree=small.PRODUCT_TREE,
            hosted={Path(p).name: dict(sha256=small.runner.digest(Path(p))) for p in assets},
            packages={Path(p).name: dict(sha256=small.runner.digest(Path(p))) for p in zips})))
        files += ['receipt.json']
        config = dict(schema='chopper-small-runner-config-v1', root=str(root), owned_root=str(root / 'owned'),
            channel='chrome', limits=small.LIMITS, source_commit=small.PRODUCT, harness_commit=small.HARNESS,
            source_tree=small.PRODUCT_TREE, browser_version='fake', package_receipt=str(receipt), product_assets=assets, package_zips=zips,
            node=str(root / 'node.exe'), python=str(root / 'python.exe'), browser=str(root / 'browser.exe'),
            product_source=[dict(path=str(root / name), git_path=name) for name in ('Cargo.toml', 'ui/src/app.ts')],
            harness_source=[dict(path=str(root / name), git_path=name) for name in files if name.startswith(('scripts/', 'ui/tests/'))],
            inputs=[dict(path=str(root / name), sha256=small.runner.digest(root / name)) for name in files],
            input_directories=[str(root / name) for name in ('scripts', 'ui/src', 'ui/dist', 'ui/node_modules')],
            history_roots=[], volumes=[str(root.anchor)],
            commands=[dict(script='test-browser.mjs', flags=[], origin='http://127.0.0.1:8422', timeout_seconds=600)])
        def git(argv, **kwargs):
            self.assertEqual(kwargs['timeout'], 4)
            if 'ls-tree' in argv:
                return 'Cargo.toml\nui/src/app.ts\n'
            if argv[-1].endswith(':ui/src/app.ts'):
                return b'product UI' if argv[-1].startswith(small.PRODUCT + ':') else b'harness UI'
            return b'fake immutable bytes'
        with patch.object(small, 'HERE', root / 'scripts'), patch.object(small, 'PACKAGE_RECEIPT_SHA256', small.runner.digest(receipt)), patch.object(small.subprocess, 'check_output', side_effect=git):
            paths_before = sorted(str(path) for path in root.rglob('*'))
            before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            with patch.object(small, 'now_ms', side_effect=AssertionError('acceptance clock started')), \
                 patch.object(small.uuid, 'uuid4', side_effect=AssertionError('reservation minted')):
                validated = small.validate_config(config)
            self.assertEqual(sorted(str(path) for path in root.rglob('*')), paths_before)
            self.assertEqual({str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}, before)
            self.assertEqual(set(validated), {'frozen', 'inventories'})
            # A reviewed new harness revision is proved by exact Git blobs, not
            # forced to the original baseline label when observer bytes change.
            selected = dict(config, harness_commit='f'*40)
            with patch.object(small.subprocess, 'check_output', side_effect=git) as selected_git:
                small.validate_config(selected)
                self.assertTrue(any(call.args[0][-1].startswith('f'*40+':scripts/') for call in selected_git.call_args_list))
            with self.assertRaisesRegex(OSError,'Exact selected harness commit'):
                small.validate_config(dict(config,harness_commit='unproved-label'))

            with patch.object(small.subprocess, 'check_output', side_effect=subprocess.TimeoutExpired('git', 4)), \
                 patch.object(small, 'now_ms', side_effect=AssertionError('acceptance clock started')), \
                 patch.object(small.uuid, 'uuid4', side_effect=AssertionError('reservation minted')), \
                 self.assertRaises(subprocess.TimeoutExpired):
                small.prepare(config)
            plan = small.prepare(config)
            self.assertEqual(validated['frozen'], plan['frozen'])
            self.assertEqual(validated['inventories'], plan['inventories'])
            self.assertFalse((root / 'owned').exists())
            self.assertEqual(plan['runner_plan']['steps'][0]['argv'][1], str(root / 'scripts/browser-small-bootstrap.mjs'))
            self.assertEqual(plan['packets'][0]['value']['batch_started_ms'], plan['batch_started_ms'])
            self.assertEqual(plan['runner_plan']['external_input_manifest'], plan['frozen'])
            import copy
            def reject(changed, message):
                with patch.object(small, 'now_ms', side_effect=AssertionError('acceptance clock started')), \
                     patch.object(small.uuid, 'uuid4', side_effect=AssertionError('reservation minted')), \
                     self.assertRaisesRegex(OSError, message):
                    small.prepare(changed)
            manifest = root / 'origin.json'
            manifest.write_text(json.dumps(dict(schema='chopper-small-retained-origin-v1',
                additional_retained_bytes=100, adopted_roots=[str(root / 'ui/src')], metadata={})))
            bridged = copy.deepcopy(config)
            bridged['retained_origin_manifest'] = str(manifest)
            reject(bridged, 'Undeclared retained origin manifest')
            bridged['inputs'].append(dict(path=str(manifest), sha256=small.runner.digest(manifest)))
            bridge_plan = small.prepare(bridged)
            identity = small.freeze(manifest)
            self.assertIn(identity, bridge_plan['frozen'])
            self.assertIn(dict(path=str(manifest), sha256=identity['sha256']), bridge_plan['packets'][0]['value']['inputs'])
            self.assertIn(os.path.relpath(manifest, root), bridge_plan['runner_plan']['steps'][0]['inputs'])
            self.assertNotIn('retained_origin_manifest', plan['config'])
            small.check_inputs(bridge_plan)
            manifest.write_text('{}')
            reject(bridged, 'manifest hash mismatch')
            with self.assertRaisesRegex(OSError, 'drift'):
                small.check_inputs(bridge_plan)
            manifest.unlink()
            changed = copy.deepcopy(config)
            changed['product_source'].pop()
            reject(changed, 'Incomplete actual frozen product source manifest')
            changed = copy.deepcopy(config)
            changed['product_source'][-1]['git_path'] = 'UI/src/app.ts'
            reject(changed, 'Source blob mismatch|Incomplete actual frozen product source manifest')
            changed = copy.deepcopy(config)
            changed['product_source'][-1]['path'] = str(root / 'ui/tests/resource-contract-tests.ts')
            reject(changed, 'Source blob mismatch')
            changed = copy.deepcopy(config)
            changed['harness_source'].append(dict(path=str(root / 'ui/src/app.ts'), git_path='ui/src/app.ts'))
            reject(changed, 'Source blob mismatch')
            # Even refreshing a declared hash cannot make main's UI the candidate UI.
            app = root / 'ui/src/app.ts'
            app.write_text('harness UI')
            changed = copy.deepcopy(config)
            next(e for e in changed['inputs'] if e['path'] == str(app))['sha256'] = small.runner.digest(app)
            reject(changed, 'Source blob mismatch')
            app.write_text('product UI')
            # A valid PRODUCT blob in custody cannot stand in for the live UI mapping.
            custody = root / 'custody-app.ts'
            custody.write_text('product UI')
            changed = copy.deepcopy(config)
            changed['product_source'][-1]['path'] = str(custody)
            reject(changed, 'actual frozen product UI source proof')
            custody.unlink()
            extra = root / 'ui/src/hosted-workspace.ts'
            extra.write_text('harness-only UI')
            reject(config, 'actual frozen product UI source proof')
            extra.unlink()
            changed = copy.deepcopy(config)
            changed['source_tree'] = 't'*40
            reject(changed, 'Product tree mismatch')
            changed = copy.deepcopy(config)
            changed['source_commit'] = '6069cef178f0b49cf45c2d5db94665c62d43ccc8'
            reject(changed, 'Frozen product source reference')
            original_receipt = receipt.read_text()
            receipt.write_text('old frozen606 package receipt')
            reject(config, 'Frozen package receipt mismatch')
            receipt.write_text(original_receipt)
            asset = Path(assets[0])
            asset.write_text('drift')
            reject(config, 'Frozen artifact drift')
            asset.write_text('fake immutable bytes')
            # A good package copy cannot conceal drift in the separately served file.
            package_asset = root / asset.name
            package_asset.write_text('fake immutable bytes')
            changed = copy.deepcopy(config)
            changed['product_assets'][0] = str(package_asset)
            changed['inputs'].append(dict(path=str(package_asset), sha256=small.runner.digest(package_asset)))
            asset.write_text('served drift')
            reject(changed, 'Served product differs from frozen package')
            asset.write_text('fake immutable bytes')
            package_asset.unlink()
            original_commands = config['commands']
            config['commands'] = [dict(original_commands[0], flags=flags) for flags in (
                ['--resource-contracts'], ['--resource-contracts', '--shuffle-partition'])]
            resource_plan = small.prepare(config)
            self.assertEqual(len(resource_plan['packets']), 2)
            changed = copy.deepcopy(config)
            changed['harness_source'] = [e for e in changed['harness_source']
                                         if e['git_path'] != 'ui/tests/resource-contract-worker.ts']
            reject(changed, 'actual selected harness source proof')
            changed = copy.deepcopy(config)
            next(e for e in changed['harness_source'] if e['git_path'] == 'ui/tests/resource-contract-worker.ts')['git_path'] = 'ui/tests/resource-contract-tests.ts'
            reject(changed, 'actual selected harness source proof')
            self.assertEqual(resource_plan['batch_started_ms'], resource_plan['packets'][1]['value']['batch_started_ms'])
            config['commands'] = [dict(script='test-browser-graph.mjs', flags=[], origin='http://127.0.0.1:8423', timeout_seconds=600)]
            reject(config, 'Explicit Graph zstd_dll required')
            config['zstd_dll'] = str(root / 'zstd.dll')
            graph_plan = small.prepare(config)
            graph_packet = graph_plan['packets'][0]['value']
            self.assertEqual(graph_packet['python'], config['python'])
            self.assertEqual(graph_packet['zstd_dll'], config['zstd_dll'])
            for name in ('python.exe', 'zstd.dll', 'scripts/graph-codec-fixtures.py', 'scripts/browser-graph-codec.mjs'):
                changed = copy.deepcopy(config)
                changed['inputs'] = [e for e in changed['inputs'] if e['path'] != str(root / name)]
                reject(changed, 'Undeclared required input')
            for name in ('scripts/graph-codec-fixtures.py', 'scripts/browser-graph-codec.mjs'):
                changed = copy.deepcopy(config)
                changed['harness_source'] = [e for e in changed['harness_source'] if e['git_path'] != name]
                reject(changed, 'actual selected harness source proof')
            changed = copy.deepcopy(config)
            next(e for e in changed['inputs'] if e['path'] == config['zstd_dll'])['sha256'] = '0'*64
            reject(changed, 'Input hash mismatch')
            changed = copy.deepcopy(config)
            changed['python'] = 'python3'
            reject(changed, 'Undeclared required input')
            config['commands'] = original_commands
            config['commands'].append(dict(config['commands'][0]))
            reject(config, 'repeats')
            config['commands'].pop()
            config['commands'][0]['flags'] = ['--unapproved']
            reject(config, 'Unsupported')
            config['commands'][0]['flags'] = []
            for key, value, message in [('timeout_seconds', 901, 'deadline'),
                                        ('origin', 'http://127.0.0.1:8423', 'origin mismatch')]:
                changed = copy.deepcopy(config)
                changed['commands'][0][key] = value
                reject(changed, message)
            config['inputs'][0]['sha256'] = '0'*64
            with self.assertRaisesRegex(OSError, 'hash mismatch'):
                small.prepare(config)
            owned = root / 'owned'
            owned.mkdir()
            for packet in plan['packets']:
                small.runner.write_json(Path(packet['path']), packet['value'])
            small.validate_worker_plan(plan['runner_plan'], owned)
            plan['runner_plan']['steps'][0]['argv'][1] = 'arbitrary-shell'
            with self.assertRaisesRegex(OSError, 'maintained bootstrap'):
                small.validate_worker_plan(plan['runner_plan'], owned)

    def test_job_query_native_buffer_limits_flags_and_backend_failures(self):
        class Fake:
            def QueryInformationJobObject(self, handle, kind, pointer, size, unused):
                value = pointer._obj
                if kind == 9:
                    value.basic.flags = self.flags
                else:
                    value.assigned, value.count = self.assigned, self.count
                    for i in range(min(self.count, len(value.pids))):
                        value.pids[i] = i+10
                return self.success
        backend = Fake()
        backend.flags, backend.assigned, backend.count, backend.success = 0x2000, 2, 2, True
        self.assertEqual(small.windows.query_job(123, 2, backend)['pids'], [10, 11])
        for flag in (0, 0x2800, 0x3000):
            backend.flags = flag
            self.assertFalse(small.windows.query_job(123, 2, backend)['kill_on_close'])
        backend.assigned = 3
        with self.assertRaises(OSError):
            small.windows.query_job(123, 2, backend)
        backend.success = False
        with self.assertRaises(OSError):
            small.windows.query_job(123, 2, backend)
        for limit in (0, 257, True, 1.5):
            with self.assertRaises(OSError):
                small.windows.query_job(123, limit, backend)
        backend.success, backend.assigned, backend.count = True, 0, 0
        self.assertEqual(small.windows.query_job(123, 2, backend)['pids'], [])
        if os.name != 'nt':
            with self.assertRaises(OSError):
                small.windows.query_job(123)
            with self.assertRaises(OSError):
                small.runner.owned_windows_job()

    def test_sealed_census_root_birth_and_direct_child_not_live_parent_labels(self):
        census = dict(kill_on_close=True, pids=[10, 20, 30])
        identities = [dict(pid=10, parent=1, image='python', created=1),
                      dict(pid=20, parent=10, image='node', created=2),
                      dict(pid=30, parent=20, image='browser', created=3)]
        self.assertEqual(small.census_child(census, identities, 10, 'node', runner_birth=1)['pid'], 20)
        for edit in [dict(kill_on_close=False, pids=census['pids']), dict(kill_on_close=True, pids=[20, 30])]:
            with self.assertRaises(OSError):
                small.census_child(edit, identities, 10, 'node', runner_birth=1)
        for index, change in [(1, dict(image='shell')), (2, dict(parent=10))]:
            wrong = [dict(p) for p in identities]
            wrong[index].update(change)
            with self.assertRaises(OSError):
                small.census_child(census, wrong, 10, 'node', runner_birth=1)
        with self.assertRaises(OSError):
            small.census_child(census, identities, 10, 'node', dict(identities[1], created=99), runner_birth=1)
        # The kernel Job remains the ownership authority after an intermediate
        # exits; no weak PID/history cache is used to infer its old birth.
        orphan = [identities[0], identities[2]]
        self.assertIsNone(small.census_child(dict(kill_on_close=True, pids=[10,30]), orphan,
                                           10, 'node', runner_birth=1))
        for rows, pids, birth in [(identities[:-1], [10,20,30], 1),
                                  (identities+[identities[1]], [10,20,30], 1),
                                  (identities, [10,20,30], 99),
                                  (identities, [10,20,30], None)]:
            with self.subTest(rows=len(rows), pids=pids, birth=birth), self.assertRaises(OSError):
                small.census_child(dict(kill_on_close=True,pids=pids), rows, 10, 'node', runner_birth=birth)

    def test_sealed_census_denial_preserves_bounded_actual_facts(self):
        root=dict(pid=10,parent=1,image='python',created=1)
        wrong=dict(pid=20,parent=10,image='x'*5000,created=2)
        with self.assertRaisesRegex(OSError,'Unexpected direct') as caught:
            small.census_child(dict(kill_on_close=True,pids=[10,20]),[root,wrong],10,'node',runner_birth=1)
        row=small.error_causes(caught.exception,{})[0]
        self.assertEqual(row['pid'],20)
        facts=row['census_child_observation']
        self.assertEqual((facts['pids'],facts['identity_pids'],facts['chain']),([10,20],[10,20],[20,10]))
        self.assertEqual(facts['process']['created'],2)
        self.assertEqual(len(facts['process']['image']),4096)

    def origin_fixture(self):
        owned, adopted, history = [self.root / name for name in ('owned', 'adopted', 'history')]
        for path in (owned, adopted, history):
            path.mkdir()
        for name in ('reservation.json', 'runner-plan.json', 'source-manifest.json'):
            (owned / name).write_text('{}')
        (history / 'storage-ledger.json').write_text(json.dumps(dict(method='original', cumulative_owned_bytes=12345)))
        manifest = self.root / 'origin.json'
        value = dict(schema='chopper-small-retained-origin-v1', additional_retained_bytes=54321,
                     adopted_roots=[str(adopted)], metadata=dict(derivation='parent-reviewed original metrics'))
        manifest.write_text(json.dumps(value))
        plan = dict(config=dict(owned_root=str(owned), history_roots=[str(history)],
                    volumes=[self.root.anchor], retained_origin_manifest=str(manifest),
                    inputs=[dict(path=str(manifest), sha256=small.runner.digest(manifest))]),
                    frozen=[small.freeze(manifest)], inventories={}, packets=[],
                    storage_method='original', batch_started_ms=small.now_ms())
        return plan, owned, adopted, history, manifest, value

    def test_initial_resource_state_joins_inputs_before_pinning_and_separates_disk(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        approval = small.freeze(manifest)
        checked = threading.Event()
        check, freeze = small.check_inputs, small.freeze
        def inputs(value):
            check(value)
            checked.set()
        def pin(value):
            self.assertTrue(checked.is_set())
            return freeze(value)
        with patch.object(small, 'check_inputs', inputs), patch.object(small.Storage, 'sample') as sample, patch.object(small, 'freeze', pin):
            state = small.resource_state(plan, owned, approval)
            sample.assert_not_called()
        self.assertIsNone(state['disk'].thread)
        marker = time.monotonic()
        state['disk'].start()
        try:
            self.assertGreater(state['disk'].after(marker, 1)['value']['total'], 54321)
        finally:
            state['disk'].stop(1)

    def test_initial_resource_state_joins_inputs_and_rejects_census_failure(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        approval = small.freeze(manifest)
        threads = []
        def inputs(value):
            threads.append(threading.current_thread())
            raise OSError('input census failed')
        with patch.object(small, 'check_inputs', inputs):
            with self.assertRaisesRegex(OSError, 'input census failed'):
                small.resource_state(plan, owned, approval)
        self.assertTrue(threads and all(not thread.is_alive() for thread in threads))

    def test_blocked_initial_input_thread_keeps_outer_operation_owned(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        approval = small.freeze(manifest)
        release, sampling, checked = threading.Event(), threading.Event(), threading.Event()
        children = []
        def inputs(value):
            children.append(threading.current_thread())
            release.wait()
            checked.set()
        def storage(value):
            sampling.set()
            return 0
        try:
            with patch.object(small, 'check_inputs', inputs), patch.object(small.Storage, 'sample', storage), patch.object(small, 'freeze') as pin:
                with self.assertRaisesRegex(OSError, 'late/blocked'):
                    small.bounded_cleanup(lambda: small.resource_state(plan, owned, approval), timeout=.01)
                self.assertFalse(sampling.is_set())
                self.assertTrue(any(thread.is_alive() for thread in small.OPERATIONS))
                self.assertTrue(children and children[0].is_alive())
                pin.assert_not_called()
                release.set()
                for thread in small.OPERATIONS:
                    thread.join(1)
        finally:
            release.set()
            for thread in small.OPERATIONS:
                thread.join(1)
        self.assertTrue(checked.is_set())
        self.assertFalse(any(thread.is_alive() for thread in [*children, *small.OPERATIONS]))

    def test_retained_origin_adds_original_debit_and_live_adopted_growth(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        path = adopted / 'cache'
        path.write_text('old')
        legacy = small.Storage([owned, history])
        baseline = legacy.sample()
        state = small.resource_state(plan, owned, small.freeze(manifest))
        storage = state['storage']
        self.assertEqual(storage.sample(), baseline + 12345 + 54321 + 8192)
        first = storage.total
        path.write_bytes(b'x'*9000)
        self.assertEqual(legacy.sample(), baseline)  # capsule/history alone misses this growth
        self.assertEqual(storage.sample(), first + 8192)
        high = storage.total
        path.write_text('shrunk')
        self.assertEqual(storage.sample(), high)
        replacement = self.root / 'replacement'
        replacement.write_text('new identity')
        # Allocate before unlink so inode-reusing filesystems keep identities distinct.
        self.assertNotEqual(path.stat().st_ino, replacement.stat().st_ino)
        path.unlink()
        self.assertEqual(storage.sample(), high)
        replacement.replace(path)
        self.assertEqual(storage.sample(), high + 8192)
        adopted.rename(self.root / 'retired')
        with self.assertRaises(OSError):
            storage.sample()
        adopted.mkdir()
        (adopted / 'new-cache').write_text('replacement root')
        self.assertEqual(storage.sample(), high + 16384)

    def primed_origin_fixture(self):
        plan, owned, fresh, covered, manifest, value = self.origin_fixture()
        manifest.unlink()
        manifest = fresh / 'origin.json'
        ledger = covered / 'storage-ledger.json'
        method = 'sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny'
        ledger.write_text(json.dumps(dict(method=method, cumulative_owned_bytes=1024**2)))
        value.update(additional_retained_bytes=0, adopted_roots=[str(covered), str(fresh)],
            metadata=dict(storage_priming=dict(covered_roots=[str(covered)], fresh_roots=[str(owned), str(fresh)],
                ledger=dict(path=str(ledger), sha256=small.runner.digest(ledger), cumulative_owned_bytes=1024**2))))
        manifest.write_text(json.dumps(value))
        plan['config'].update(root=str(fresh), history_roots=[], retained_origin_manifest=str(manifest),
            inputs=[dict(path=str(p), sha256=small.runner.digest(p)) for p in (manifest, ledger)])
        plan.update(frozen=[small.freeze(p) for p in (manifest, ledger)], storage_method=method)
        return plan, owned, fresh, covered, manifest, value

    def test_primed_origin_bound_history_preserves_strict_shapes_and_old_method_denial(self):
        from scale_acceptance import hosted_qualification as qualification
        plan, owned, fresh, covered, manifest, value = self.primed_origin_fixture()
        ledger_path=Path(value['metadata']['storage_priming']['ledger']['path'])
        prior=json.loads(ledger_path.read_text());prior.pop('method');ledger_path.write_text(json.dumps(prior))
        priming=value['metadata']['storage_priming'];priming['ledger']['sha256']=small.runner.digest(ledger_path)
        history=dict(ledger=dict(path=str(ledger_path),sha256=priming['ledger']['sha256']))
        value['metadata']['history']=history
        config=plan['config']
        def publish():
            manifest.write_text(json.dumps(value))
            config['inputs']=[dict(path=str(p),sha256=small.runner.digest(p))for p in (manifest,ledger_path)]
        publish()
        with patch.object(qualification,'retained_storage_ledger',return_value=(prior,[str(covered)]))as inherited:
            small.retained_origin(config);inherited.assert_called_once_with(history, declared=config['inputs'])
            for key,bad in (('sha256','0'*64),('path',str(fresh/'wrong.json'))):
                original=history['ledger'][key];history['ledger'][key]=bad;publish()
                with self.assertRaisesRegex(OSError,'history binding'):small.retained_origin(config)
                history['ledger'][key]=original
            publish()
            with patch.object(qualification,'retained_storage_ledger',return_value=(dict(prior,cumulative_owned_bytes=0),[str(covered)])):
                with self.assertRaisesRegex(OSError,'history aggregate/root'):small.retained_origin(config)
            with patch.object(qualification,'retained_storage_ledger',return_value=(prior,[])):
                with self.assertRaisesRegex(OSError,'history aggregate/root'):small.retained_origin(config)
        del value['metadata']['history'];publish()
        with self.assertRaisesRegex(OSError,'aggregate/method'):small.retained_origin(config)
        value['metadata']['storage_priming']['history']=history;publish()
        with self.assertRaisesRegex(OSError,'Storage priming schema'):small.retained_origin(config)

    def test_primed_storage_preserves_floor_and_charges_fresh_roots_without_restacking(self):
        plan, owned, fresh, covered, manifest, value = self.primed_origin_fixture()
        old = covered / 'old-cache'
        old.write_bytes(b'x'*9000)
        fresh_metric = small.Storage([owned, fresh]).sample()
        state = small.resource_state(plan, owned, small.freeze(manifest))
        storage = state['storage']
        self.assertEqual(storage.total, 1024**2)
        self.assertEqual(storage.sample(), 1024**2 + fresh_metric)
        peak = storage.total
        old.write_text('shrunk')
        self.assertEqual(storage.sample(), peak)
        replacement = self.root / 'replacement'
        replacement.write_text('new identity')
        self.assertNotEqual(old.stat().st_ino, replacement.stat().st_ino)
        old.unlink()
        self.assertEqual(storage.sample(), peak)
        replacement.replace(old)
        self.assertEqual(storage.sample(), peak + 8192)
        (fresh / 'new-source').write_bytes(b'x'*9000)
        self.assertEqual(storage.sample(), peak + 8192 + 16384)
        old.write_bytes(b'x'*9000)
        self.assertEqual(storage.sample(), peak + 8192 + 16384 + 8192)

    def test_existing_disjoint_uncovered_root_is_charged_after_immutable_floor(self):
        covered=self.root/'covered';covered.mkdir()
        (covered/'old').write_bytes(b'old')
        component=self.root/'component';component.mkdir()
        (component/'result.json').write_bytes(b'actual closed component')
        future=self.root/'future'
        partition=dict(covered_roots=[str(covered)],fresh_roots=[str(component),str(future)],
            ledger=dict(cumulative_owned_bytes=1024**2))
        storage=small.primed_storage(partition,[])
        self.assertEqual(storage.total,1024**2)
        storage.roots.append(component)
        self.assertEqual(storage.sample(),1024**2+8192)
        (component/'result.json').unlink()
        self.assertEqual(storage.sample(),1024**2+8192)
        self.assertFalse(future.exists())

    def test_primed_storage_preserves_higher_visible_union_and_rejects_bad_partition_or_ledger(self):
        plan, owned, fresh, covered, manifest, value = self.primed_origin_fixture()
        (covered / 'large').write_bytes(b'x'*(2*1024**2))
        visible = small.Storage([covered]).sample()
        self.assertGreater(visible, 1024**2)
        state = small.resource_state(plan, owned, small.freeze(manifest))
        self.assertEqual(state['storage'].total, visible)
        import copy
        for fault in ('missing-root', 'overlap', 'floor', 'hash', 'stacked-debit'):
            bad = copy.deepcopy(value)
            priming = bad['metadata']['storage_priming']
            if fault == 'missing-root': priming['fresh_roots'].remove(str(owned))
            elif fault == 'overlap': priming['fresh_roots'].append(str(covered))
            elif fault == 'floor': priming['ledger']['cumulative_owned_bytes'] += 1
            elif fault == 'hash': priming['ledger']['sha256'] = '0'*64
            else: bad['additional_retained_bytes'] = 1
            manifest.write_text(json.dumps(bad))
            config = copy.deepcopy(plan['config'])
            config['inputs'][0]['sha256'] = small.runner.digest(manifest)
            with self.subTest(fault=fault), self.assertRaises(OSError):
                small.retained_origin(config)
        manifest.write_text(json.dumps(value))
        plan['config']['inputs'][0]['sha256'] = small.runner.digest(manifest)
        (covered / 'storage-ledger.json').write_text('changed actual ledger')
        with self.assertRaisesRegex(OSError, 'ledger drift'):
            small.retained_origin(plan['config'])

    def test_retained_origin_legacy_path_and_original_method_check(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        del plan['config']['retained_origin_manifest']
        baseline = small.Storage([owned, history]).sample()
        state = small.resource_state(plan, owned, small.freeze(manifest))
        self.assertEqual(state['storage'].total, 12345)  # legacy still samples lazily
        self.assertEqual(state['storage'].sample(), baseline + 12345)
        plan['config']['retained_origin_manifest'] = str(manifest)
        (history / 'storage-ledger.json').write_text(json.dumps(dict(method='different', cumulative_owned_bytes=12345)))
        with self.assertRaisesRegex(OSError, 'Invalid retained storage ledger'):
            small.resource_state(plan, owned, small.freeze(manifest))

    def test_retained_origin_manifest_validation_and_runtime_pin(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        config = plan['config']
        def publish(raw):
            manifest.write_bytes(raw)
            config['inputs'][0]['sha256'] = small.runner.digest(manifest)
        for raw in (b'null', b'[]', b'{', b'\xff', b' ' * 1024**2,
                    b'{"schema":1,"schema":2}'):
            publish(raw)
            with self.subTest(raw=raw[:20]), self.assertRaises(OSError):
                small.retained_origin(config)
        for change in (dict(schema='unknown'), dict(schema=True), dict(extra=1),
                       dict(additional_retained_bytes=True), dict(additional_retained_bytes=-1),
                       dict(additional_retained_bytes=2**64), dict(additional_retained_bytes=1.0),
                       dict(additional_retained_bytes=float('inf')), dict(additional_retained_bytes=None),
                       dict(adopted_roots='wrong'), dict(adopted_roots=[True]), dict(metadata=[])):
            publish(json.dumps(dict(value, **change)).encode())
            with self.subTest(change=change), self.assertRaises(OSError):
                small.retained_origin(config)
        publish(json.dumps(value).encode())
        config['inputs'][0]['sha256'] = '0'*64
        with self.assertRaisesRegex(OSError, 'hash mismatch'):
            small.retained_origin(config)
        config['inputs'] = []
        with self.assertRaisesRegex(OSError, 'Undeclared'):
            small.retained_origin(config)
        config['inputs'] = [dict(path=str(manifest), sha256=small.runner.digest(manifest))]
        plan['frozen'] = [small.freeze(manifest)]
        state = small.resource_state(plan, owned, small.freeze(manifest))
        self.assertIn(plan['frozen'][0], state['pinned'])
        manifest.write_text(json.dumps(dict(value, additional_retained_bytes=1)))
        with self.assertRaisesRegex(OSError, 'drift'):
            small.resource_state(plan, owned, small.freeze(manifest))
        plan['frozen'] = []
        config['inputs'][0]['sha256'] = small.runner.digest(manifest)
        with self.assertRaisesRegex(OSError, 'must be frozen'):
            small.resource_state(plan, owned, small.freeze(manifest))
        manifest.unlink()
        with self.assertRaises(OSError):
            small.retained_origin(config)

    def test_retained_origin_roots_overlap_alias_missing_volume_and_cap(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        config = plan['config']
        nested = adopted / 'nested'
        nested.mkdir()
        for roots in ([str(adopted)]*2, [str(adopted), str(nested)], [str(owned)],
                      [str(history)], [str(self.root)], [str(adopted / 'missing')],
                      ['relative'], [str(manifest)]):
            manifest.write_text(json.dumps(dict(value, adopted_roots=roots)))
            config['inputs'][0]['sha256'] = small.runner.digest(manifest)
            with self.subTest(roots=roots), self.assertRaises(OSError):
                small.retained_origin(config)
        manifest.write_text(json.dumps(value))
        config['inputs'][0]['sha256'] = small.runner.digest(manifest)
        config['volumes'] = []
        with self.assertRaisesRegex(OSError, 'volume'):
            small.retained_origin(config)
        config['volumes'] = [self.root.anchor]
        if os.name != 'nt':
            alias = self.root / 'alias'
            alias.symlink_to(adopted, target_is_directory=True)
            manifest.write_text(json.dumps(dict(value, adopted_roots=[str(alias)])))
            config['inputs'][0]['sha256'] = small.runner.digest(manifest)
            with self.assertRaises(OSError):
                small.retained_origin(config)
        # Exactly the cap, including whole old ledger and live baseline, denies.
        baseline = small.Storage([owned, history, adopted]).sample()
        value['additional_retained_bytes'] = small.LIMITS['owned_bytes'] - 12345 - baseline
        manifest.write_text(json.dumps(value))
        config['inputs'][0]['sha256'] = small.runner.digest(manifest)
        plan['frozen'] = [small.freeze(manifest)]
        with patch.object(small.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(OSError, 'storage ceiling'):
                state = small.resource_state(plan, owned, small.freeze(manifest))
                state['storage'].sample()
            launch.assert_not_called()

    def test_retained_origin_adopts_source_custody_without_relaxing_freeze(self):
        plan, owned, adopted, history, manifest, value = self.origin_fixture()
        source = adopted / 'source.py'
        source.write_text('frozen source')
        plan['frozen'].append(small.freeze(source))
        plan['inventories'][str(adopted)] = small.inventory(adopted)
        state = small.resource_state(plan, owned, small.freeze(manifest))
        self.assertIn(adopted, state['storage'].roots)
        source.write_text('changed source')
        self.assertGreater(state['storage'].sample(), 0)
        with self.assertRaisesRegex(OSError, 'drift'):
            small.check_inputs(plan)

    def test_mutable_storage_real_atomic_publication_rescans_and_retains_highs(self):
        target = self.root / 'storage-ledger.json'
        target.write_bytes(b'x' * 12000)
        storage = small.Storage([self.root])
        charged = storage.sample()
        temporary = target.with_suffix('.tmp')
        temporary.write_bytes(b'new')
        original = Path.lstat
        moved = []
        def reading(path, *args, **kwargs):
            if path == temporary and not moved:
                small.runner.write_json(target, dict(actual=True))
                moved.append(True)
            return original(path, *args, **kwargs)
        endpoint = time.monotonic() + 30
        with patch.object(Path, 'lstat', reading):
            total = storage.sample(mutable_roots=[self.root], deadline=endpoint)
        self.assertTrue(moved)
        self.assertEqual(len(storage.rescans), 1)
        self.assertEqual(storage.rescans[0]['unobserved_allocation'], 'UNKNOWN')
        self.assertGreaterEqual(total, charged + 8192)
        self.assertEqual(storage.sample(), total)

    def test_mutable_storage_sealed_and_closed_names_still_deny(self):
        for mutable, sealed in ((False, False), (True, True)):
            path = self.root / 'sealed.tmp'
            path.write_bytes(b'x')
            original = Path.lstat
            def reading(value, *args, **kwargs):
                if value == path and path.exists():
                    path.unlink()
                return original(value, *args, **kwargs)
            with patch.object(Path, 'lstat', reading), self.assertRaises(OSError):
                small.Storage([self.root]).sample(mutable_roots=[self.root] if mutable else [],
                    immutable_paths=[path] if sealed else [], deadline=time.monotonic()+30)

    def test_mutable_storage_exhaustion_preserves_partial_charge_and_original_deadline(self):
        stable = self.root / 'a-kept'
        stable.write_bytes(b'x' * 10000)
        storage = small.Storage([self.root])
        charged = storage.sample()
        missing = self.root / 'z-transient'
        missing.write_bytes(b'x')
        original = Path.lstat
        def reading(path, *args, **kwargs):
            if path == missing:
                raise FileNotFoundError(2, 'controlled persistent namespace race', str(path))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', reading), self.assertRaisesRegex(OSError, 'exhausted') as caught:
            storage.sample(mutable_roots=[self.root], deadline=time.monotonic()+30)
        self.assertEqual(len(storage.rescans), 8)
        self.assertGreater(storage.total, 0)
        self.assertEqual(caught.exception.storage_observation['partial_total'], storage.total)
        self.assertFalse(caught.exception.storage_observation['complete'])
        causes = small.error_causes(caught.exception, {})
        self.assertEqual(causes[0]['storage_observation']['partial_total'], storage.total)
        with self.assertRaisesRegex(OSError, 'deadline'):
            small.Storage([self.root]).sample(mutable_roots=[self.root], deadline=time.monotonic()-1)

    def test_mutable_storage_pinned_ancestor_and_nonmissing_errors_deny(self):
        folder = self.root / 'pinned'
        folder.mkdir()
        pin = folder / 'source'
        pin.write_bytes(b'x')
        original = Path.lstat
        for error in (FileNotFoundError(2, 'ancestor lost', str(folder)),
                      PermissionError(13, 'access denied', str(folder))):
            def reading(path, *args, **kwargs):
                if path == folder:
                    raise error
                return original(path, *args, **kwargs)
            storage = small.Storage([self.root])
            with patch.object(Path, 'lstat', reading), self.assertRaises(OSError):
                storage.sample(mutable_roots=[self.root], immutable_paths=[pin], deadline=time.monotonic()+30)
            self.assertFalse(storage.rescans)
        alias = self.root / 'alias'
        os.link(pin, alias)
        with self.assertRaisesRegex(OSError, 'single-link'):
            small.Storage([self.root]).sample(mutable_roots=[self.root], deadline=time.monotonic()+30)

    def test_mutable_storage_final_root_check_must_finish_before_original_deadline(self):
        original = small.InputMetadata.read
        expired = []
        def reading(metadata, path):
            value = original(metadata, path)
            if Path(path) == self.root:
                expired.append(True)
            return value
        with patch.object(small.InputMetadata, 'read', reading), patch.object(small.time, 'monotonic',
                side_effect=lambda: 31 if len(expired) >= 3 else 0):
            with self.assertRaisesRegex(OSError, 'deadline'):
                small.Storage([self.root]).sample(mutable_roots=[self.root], deadline=30)

    def test_storage_monotonic_across_deletion_shrink_and_prior_retained_roots(self):
        old = self.root / 'old'
        old.mkdir()
        fresh = self.root / 'new'
        fresh.mkdir()
        path = old / 'retained.log'
        path.write_bytes(b'x'*10000)
        accounting = small.Storage([old, fresh])
        first = accounting.sample()
        path.write_bytes(b'x')
        self.assertEqual(accounting.sample(), first)
        path.unlink()
        self.assertEqual(accounting.sample(), first)
        (fresh / 'profile').write_bytes(b'x'*9000)
        self.assertGreater(accounting.sample(), first)
        self.assertEqual(accounting.sample(), accounting.total)

    def test_storage_rejects_symlink_and_keeps_known_deletion_race_charge(self):
        path = self.root / 'file'
        path.write_text('old')
        accounting = small.Storage([self.root])
        total = accounting.sample()
        original = Path.lstat
        def racing(value, *args, **kwargs):
            if value == path:
                raise FileNotFoundError('deleted during census')
            return original(value, *args, **kwargs)
        with patch.object(Path, 'lstat', racing):
            self.assertEqual(accounting.sample(), total)
        if os.name != 'nt':
            (self.root / 'link').symlink_to(path)
            with self.assertRaises(OSError):
                accounting.sample()

    def test_canonical_check_deletion_retains_only_previously_charged_paths(self):
        path = self.root / 'file'
        path.write_text('old')
        accounting = small.Storage([self.root])
        charged = accounting.sample()
        original = Path.lstat
        def deleted(value):
            if value == path:
                raise FileNotFoundError('deleted before canonical check completed')
            return original(value)
        with patch.object(Path, 'lstat', deleted):
            self.assertEqual(accounting.sample(), charged)
            with self.assertRaisesRegex(OSError, 'Unbounded unseen storage deletion race'):
                small.Storage([self.root]).sample()

    def test_storage_fresh_lstat_order_including_directory_and_root_postchecks(self):
        root = self.root/'owned'
        child = root/'nested'
        child.mkdir(parents=True)
        leaf = child/'file'
        leaf.write_text('bytes')
        storage = small.Storage([root])
        chain = list(reversed([root, *root.parents]))
        expected = chain + chain + [child] + chain + chain + [child, leaf] + chain + [child] + chain
        original = Path.lstat
        calls = []
        def counted(path, *args, **kwargs):
            calls.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', counted):
            first = storage.sample()
            self.assertEqual(calls, expected)
            calls.clear()
            self.assertEqual(storage.sample(), first)
            self.assertEqual(calls, expected)

    def test_input_metadata_reuses_safe_path_objects_without_reconstruction(self):
        path = self.root/'file'
        path.write_text('bytes')
        metadata = small.InputMetadata()
        metadata.file(path)
        original = Path.__new__
        calls = []
        def constructed(cls, *args, **kwargs):
            calls.append(args)
            return original(cls, *args, **kwargs)
        with patch.object(Path, '__new__', constructed):
            metadata.file(path)
            metadata.file(path)
        self.assertEqual(calls, [], 'already parsed Path objects must be reused')
        for invalid in ('relative', str(self.root/'..'/'file')):
            with self.assertRaisesRegex(OSError, 'Absolute canonical'):
                metadata.read(invalid)

    def test_shared_lexical_cache_never_reuses_metadata_or_accepts_invalid_paths(self):
        path = self.root/'file'
        path.write_text('bytes')
        parents = {}
        small.InputMetadata(parents).file(path)
        self.assertEqual(parents[str(path)], path.parent, 'cache keys must preserve exact path spelling')
        original = Path.lstat
        calls = []
        def counted(value, *args, **kwargs):
            calls.append(value)
            return original(value, *args, **kwargs)
        # Warm lexical entries need no validation/parsing, but all stats recur.
        with patch.object(Path, 'is_absolute', side_effect=AssertionError('reparsed safe path')), \
             patch.object(Path, 'lstat', counted):
            small.InputMetadata(parents).file(path)
        self.assertEqual(calls, list(reversed([path, *path.parents])))
        for invalid in (Path('relative'), self.root/'..'/'file'):
            for _ in range(2):
                with self.assertRaisesRegex(OSError, 'Absolute canonical'):
                    small.InputMetadata(parents).read(invalid)
                self.assertNotIn(str(invalid), parents)
        # At capacity, uncached paths still validate and get fresh metadata.
        full = dict.fromkeys(range(200000))
        small.InputMetadata(full).file(path)
        self.assertEqual(len(full), 200000)
        with self.assertRaisesRegex(OSError, 'Absolute canonical'):
            small.InputMetadata(full).read('relative')
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            small.InputMetadata(parents).file(path)

    def test_input_metadata_keeps_windows_case_sensitive_entries_distinct(self):
        import stat
        from pathlib import PureWindowsPath
        from types import SimpleNamespace
        calls = []
        class WindowsPath(PureWindowsPath):
            def lstat(self):
                calls.append(str(self))
                return SimpleNamespace(st_mode=stat.S_IFREG if self.name in ('file', 'FILE') else stat.S_IFDIR,
                    st_file_attributes=0, st_ino=2 if self.name == 'FILE' else 1)
        lower, upper = WindowsPath('C:/case/file'), WindowsPath('C:/case/FILE')
        self.assertEqual(lower, upper, 'Windows Path equality folds case')
        with patch.object(small, 'Path', WindowsPath):
            metadata = small.InputMetadata()
            self.assertEqual(metadata.read(lower).st_ino, 1)
            self.assertEqual(metadata.read(upper).st_ino, 2)
            self.assertEqual(metadata.read(upper).st_ino, 2)
        self.assertEqual(calls.count(str(lower)), 1)
        self.assertEqual(calls.count(str(upper)), 1)

    def test_frozen_readonly_hardlinks_preserve_drift_and_owned_storage_denials(self):
        source = self.root/'tool'
        source.write_bytes(b'fixed tool')
        alias = self.root/'tool-alias'
        os.link(source, alias)
        plan = dict(frozen=[small.freeze(source)], inventories={})
        small.check_inputs(plan)
        with self.assertRaisesRegex(OSError, 'single-link'):
            small.Storage([self.root]).sample()
        alias.write_bytes(b'moved tool')
        info = alias.stat()
        os.utime(alias, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        with self.assertRaisesRegex(OSError, 'Source/tool/binary drift'):
            small.check_inputs(plan)

    def test_storage_warm_lexical_cache_denies_late_ancestor_reparse_or_missing(self):
        from types import SimpleNamespace
        root = self.root/'owned'
        root.mkdir()
        leaf = root/'file'
        leaf.write_text('bytes')
        storage = small.Storage([root])
        storage.sample()
        original = Path.lstat
        for target in (root, root.parent):
            for missing in (False, True):
                with self.subTest(target=target, missing=missing):
                    changed = [False]
                    def replaced(path, *args, **kwargs):
                        info = original(path, *args, **kwargs)
                        if path == leaf:
                            changed[0] = True
                        if path == target and changed[0]:
                            if missing:
                                raise FileNotFoundError('late ancestor deletion')
                            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                        return info
                    with patch.object(Path, 'lstat', replaced):
                        with self.assertRaises(OSError):
                            storage.sample()

    def test_owned_input_observation_slow_complete_proof_does_not_block_hot_guard(self):
        resources, plan, process, watchdog, receipt = self.supervision_fixture()
        leaf = self.root/'immutable';leaf.write_text('bytes')
        inputs = dict(frozen=[small.freeze(leaf)], inventories={str(self.root):small.inventory(self.root)})
        tick, wall = [10.0], [10000]
        observation = small.InputObservation(inputs, clock=lambda:tick[0], wall=lambda:wall[0])
        real_check = small.check_inputs
        calls = []
        def scan(value, parents):
            real_check(value, parents)
            calls.append(threading.current_thread())
            tick[0] += .95;wall[0] += 950
            observation.done.set()  # One completed .95s task, no timing hook in production.
        with patch.object(small, 'check_inputs', side_effect=scan):
            observation.initial();observation.thread.join(1)
        self.assertEqual(len(calls),1)
        self.assertEqual(observation.read(),10000)
        resources['inputs'] = observation
        pulse = Mock();watchdog.pulse = pulse
        with patch.object(small, 'Receipts', receipt), patch.object(small, 'sample_resources',
                return_value=(dict(pids=[123],kill_on_close=True,flags=8192),[],[],0)), \
                patch.object(small, 'census_child', return_value=None), patch.object(small,'now_ms',return_value=10950):
            plan['batch_started_ms']=resources['last_progress_ms']=10000
            small.run_supervision(plan,self.root,process,1,{},watchdog,{},resources)
        pulse.assert_called_once()
        self.assertEqual(json.loads((self.root/'guard.json').read_text())['sampled_ms'],10000,
                         'Hot publication must retain oldest completed input start')
        observation.stop()

    def test_input_observation_pending_stale_error_and_wall_rewind_deny(self):
        tick, wall = [11.0],[11000]
        observation=small.InputObservation({},clock=lambda:tick[0],wall=lambda:wall[0])
        observation.started=10.5;observation.completed=(10,10000)
        self.assertEqual(observation.read(),10000)
        tick[0]=12.501
        with self.assertRaisesRegex(OSError,'late/blocked'):observation.read()
        observation.started=10
        tick[0]=15.001
        with self.assertRaisesRegex(OSError,'oldest start'):observation.read()
        tick[0]=11;wall[0]=9999
        with self.assertRaisesRegex(OSError,'wall timestamp'):observation.read()
        wall[0]=11000;tick[0]=9
        with self.assertRaisesRegex(OSError,'oldest start'):observation.read()
        tick[0]=11;observation.error=OSError('completed input drift')
        with self.assertRaisesRegex(OSError,'completed input drift'):observation.read()

    def test_owned_input_task_never_overlaps_and_failed_join_retains_original(self):
        from types import SimpleNamespace
        entered, release=threading.Event(),threading.Event()
        observation=small.InputObservation({})
        def scan(*args):entered.set();release.wait()
        reservation={}
        try:
            with patch.object(small,'check_inputs',side_effect=scan):
                observation.start();self.assertTrue(entered.wait(1))
                with self.assertRaisesRegex(OSError,'already started'):observation.start()
                resources=dict(inputs=observation,storage=SimpleNamespace(total=0),pinned=[],last_progress_ms=small.now_ms())
                process=SimpleNamespace(returncode=91,poll=lambda:91,wait=lambda timeout:91)
                # Simulate an OS call that does not join: retain its real tracked thread.
                with patch.object(observation.thread,'join'),patch.object(small,'sample_resources',
                        return_value=(dict(pids=[]),[],[],0)),patch.object(small.windows,'terminate'), \
                        patch.object(small.windows,'close') as close:
                    errors=small.finish_supervision(dict(batch_started_ms=small.now_ms(),storage_method='test'),
                        self.root,process,123,reservation,None,resources,'input task blocked')
                self.assertFalse(reservation['release_safe'])
                self.assertTrue(any('pending call' in value for value in errors))
                close.assert_not_called()
                self.assertTrue(observation.thread.is_alive())
        finally:
            release.set();observation.stop()

    def test_input_pending_deadline_stops_job_independently_of_live_hot_pulses(self):
        from types import SimpleNamespace
        observation=small.InputObservation({},clock=lambda:12.501,wall=lambda:12501)
        observation.completed=(10,10000);observation.started=10.5
        terminate=Mock();process=SimpleNamespace(wait=Mock())
        watchdog=small.Watchdog(123,process,terminate=terminate,inputs=observation)
        watchdog.pulse()
        watchdog.thread.start();watchdog.thread.join(1)
        self.assertFalse(watchdog.thread.is_alive())
        self.assertIn('Input census late/blocked',watchdog.error)
        terminate.assert_called_once_with(123);process.wait.assert_called_once_with(timeout=10)
        with self.assertRaises(OSError):watchdog.pulse()

    def test_complete_input_observation_rejects_late_completion_and_error(self):
        for fault in ('late','error'):
            tick=[10.0]
            observation=small.InputObservation({},clock=lambda:tick[0],wall=lambda:10000)
            def scan(*args):
                if fault=='error':raise OSError('full census failed')
                tick[0]=12.001
            with patch.object(small,'check_inputs',side_effect=scan):
                observation.start();observation.thread.join(1)
            self.assertIsNone(observation.completed)
            with self.assertRaisesRegex(OSError,'late/blocked' if fault=='late' else 'full census failed'):
                observation.read()
            with self.assertRaises(OSError):observation.stop()

    def test_input_cache_keeps_complete_fresh_file_and_membership_checks(self):
        leaf=self.root/'immutable';leaf.write_text('bytes')
        plan=dict(frozen=[small.freeze(leaf)],inventories={str(self.root):small.inventory(self.root)})
        parents={}
        small.check_inputs(plan,parents)
        self.assertTrue(parents)
        leaf.write_text('drift')
        with self.assertRaisesRegex(OSError,'drift'):small.check_inputs(plan,parents)
        plan['frozen']=[small.freeze(leaf)]
        (self.root/'new-member').write_text('new')
        with self.assertRaisesRegex(OSError,'inventory drift'):small.check_inputs(plan,parents)
        (self.root/'new-member').unlink()
        original=Path.lstat
        from types import SimpleNamespace
        def reparse(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400) if path==self.root else value
        with patch.object(Path,'lstat',reparse),self.assertRaisesRegex(OSError,'reparse'):
            small.check_inputs(plan,parents)

    def test_profile_growth_overlaps_full_input_scan_within_unchanged_sample_budget(self):
        # Launch-preflight creates a profile while the immutable scan still costs
        # .55s. Charge every actual metadata syscall in a deterministic I/O model:
        # repeated ancestors used to push this combined sample past .8s.
        from types import SimpleNamespace
        profile = self.root/'temp'/'playwright_chromiumdev_profile-fake'/'Default'
        for index in range(150):
            directory = profile/('cache'+str(index % 10))
            directory.mkdir(parents=True, exist_ok=True)
            (directory/str(index)).write_text('profile bytes')
        storage = small.Storage([self.root])
        elapsed = [0.0]
        original_stat, original_lstat = os.stat, os.lstat
        def charged(call):
            def invoke(*args, **kwargs):
                elapsed[0] += .0002
                return call(*args, **kwargs)
            return invoke
        def inputs(plan):
            elapsed[0] += .55
        plan = dict(config=dict(volumes=['fake-volume']))
        with patch.object(small, 'check_inputs', side_effect=inputs), patch.object(small, 'stamp_lock', return_value=[1, 2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])), patch.object(small.shutil, 'disk_usage', return_value=SimpleNamespace(free=200*small.GIB)), patch.object(os, 'stat', charged(original_stat)), patch.object(os, 'lstat', charged(original_lstat)):
            result = small.sample_resources(plan, [], dict(lock_identity=[1, 2]), 123, storage, False)
        self.assertGreater(result[3], 0)
        self.assertLess(elapsed[0], .8, 'full input scan plus launch-profile storage census exceeded .8s')

    @unittest.skipIf(os.name == 'nt', 'Actual symlink creation requires Windows privileges')
    def test_storage_rejects_root_or_ancestor_replaced_after_walk_begins(self):
        original_walk = os.walk
        for replace_ancestor in (False, True):
            with self.subTest(replace_ancestor=replace_ancestor):
                base = self.root/str(replace_ancestor)
                root = base/'parent'/'owned'
                root.mkdir(parents=True)
                (root/'original').write_text('owned')
                external = base/'external'
                (external/'owned').mkdir(parents=True)
                (external/'owned'/'unowned').write_text('external')
                replacement = root.parent if replace_ancestor else root
                target = external if replace_ancestor else external/'owned'
                def changed_walk(path, *args, **kwargs):
                    replacement.rename(base/'retired')
                    replacement.symlink_to(target, target_is_directory=True)
                    yield from original_walk(path, *args, **kwargs)
                with patch.object(os, 'walk', changed_walk):
                    with self.assertRaisesRegex(OSError, 'Symlink/reparse'):
                        small.Storage([root]).sample()

    def test_storage_rejects_reparse_metadata_changed_while_reading_entries(self):
        from types import SimpleNamespace
        root = self.root/'owned'
        root.mkdir()
        (root/'file').write_text('owned')
        original = Path.lstat
        changed = [False]
        def replaced(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == root/'file':
                changed[0] = True
            if path == root and changed[0]:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, 'lstat', replaced):
            with self.assertRaisesRegex(OSError, 'Symlink/reparse'):
                small.Storage([root]).sample()

    def test_storage_scan_refreshes_namespace_roots_and_reparse_and_link_checks(self):
        from types import SimpleNamespace
        root = self.root/'owned'
        root.mkdir()
        source = root/'file'
        source.write_text('bytes')
        storage = small.Storage([root])
        first = storage.sample()
        extra = root/'new-profile-file'
        extra.write_bytes(b'x'*9000)
        self.assertGreater(storage.sample(), first)
        alias = self.root/'alias'
        os.link(source, alias)
        with self.assertRaisesRegex(OSError, 'single-link'):
            storage.sample()
        alias.unlink()
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == root else info
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(OSError, 'Symlink/reparse'):
                storage.sample()
        if os.name != 'nt':
            moved = self.root/'moved'
            root.rename(moved)
            root.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(OSError, 'Symlink/reparse'):
                storage.sample()

    def test_resource_censuses_overlap_without_skipping_input_failure(self):
        from types import SimpleNamespace
        for fail_inputs in (False, True):
            with self.subTest(fail_inputs=fail_inputs):
                entered, storage_started = threading.Event(), threading.Event()
                def inputs(plan):
                    entered.set()
                    self.assertTrue(storage_started.wait(1), 'storage cannot start behind a full input scan')
                    if fail_inputs:
                        raise OSError('injected input drift')
                def storage():
                    self.assertTrue(entered.wait(1))
                    storage_started.set()
                    return 17
                with patch.object(small, 'check_inputs', side_effect=inputs), patch.object(small, 'stamp_lock', return_value=[1, 2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])):
                    sample = lambda: small.sample_resources(dict(config=dict(volumes=[])), [], dict(lock_identity=[1, 2]), 123, SimpleNamespace(sample=storage), False)
                    if fail_inputs:
                        with self.assertRaisesRegex(OSError, 'injected input drift'):
                            sample()
                    else:
                        self.assertEqual(sample()[3], 17)

    def test_blocked_guard_retains_phase_and_denies_without_publishing_heartbeat(self):
        from types import SimpleNamespace
        entered, release = threading.Event(), threading.Event()
        finished = threading.Event()
        def blocked_storage():
            entered.set()
            release.wait()
            finished.set()
            raise OSError('blocked storage scan released after denial')
        resources = dict(storage=small.Storage([self.root]), pinned=[])
        plan = dict(config=dict(volumes=[]), packets=[], batch_started_ms=small.now_ms())
        watchdog = SimpleNamespace(pulse=lambda: self.fail('blocked sample published a heartbeat'))
        try:
            with patch.object(small, 'check_inputs'), patch.object(small, 'stamp_lock', return_value=[1, 2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])), patch.object(resources['storage'], 'sample', side_effect=blocked_storage):
                with self.assertRaisesRegex(OSError, 'guard sample late/blocked'):
                    small.run_supervision(plan, self.root, SimpleNamespace(poll=lambda: None), 123, dict(lock_identity=[1, 2]), watchdog, {}, resources)
                self.assertTrue(entered.is_set())
                events = {(e['phase'], e['event']) for e in resources['sample_trace']}
                self.assertIn(('storage', 'start'), events)
                self.assertNotIn(('storage', 'complete'), events)
                self.assertTrue(any(e['phase'] == 'inputs' and e['event'] == 'complete' for e in resources['sample_trace']))
                self.assertFalse((self.root/'guard.json').exists())
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_blocked_input_scan_cannot_publish_parallel_storage_as_a_guard(self):
        from types import SimpleNamespace
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def blocked_inputs(plan):
            entered.set()
            release.wait()
            finished.set()
            raise OSError('input scan released after denial')
        resources = dict(storage=SimpleNamespace(sample=lambda: 0), pinned=[])
        plan = dict(config=dict(volumes=[]), packets=[], batch_started_ms=small.now_ms())
        watchdog = SimpleNamespace(pulse=lambda: self.fail('incomplete inputs published a heartbeat'))
        try:
            with patch.object(small, 'check_inputs', side_effect=blocked_inputs), patch.object(small, 'stamp_lock', return_value=[1, 2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])):
                with self.assertRaisesRegex(OSError, 'guard sample late/blocked'):
                    small.run_supervision(plan, self.root, SimpleNamespace(poll=lambda: None), 123, dict(lock_identity=[1, 2]), watchdog, {}, resources)
                self.assertTrue(entered.is_set())
                events = {(e['phase'], e['event']) for e in resources['sample_trace']}
                self.assertIn(('storage', 'complete'), events)
                self.assertNotIn(('inputs', 'complete'), events)
                self.assertFalse((self.root/'guard.json').exists())
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_input_census_reads_each_shared_ancestor_once_and_refreshes_next_scan(self):
        directory = self.root/'inputs'
        directory.mkdir()
        paths = [directory/'a', directory/'b']
        for path in paths:
            path.write_text('original')
        plan = dict(frozen=[small.freeze(p) for p in paths], inventories={str(directory): small.inventory(directory)})
        calls = {}
        original = Path.lstat
        def counted(path, *args, **kwargs):
            calls[path] = calls.get(path, 0)+1
            return original(path, *args, **kwargs)
        with patch.object(Path, 'lstat', counted):
            small.check_inputs(plan)
        self.assertEqual(set(calls.values()), {1})
        self.assertTrue(all(p in calls for p in paths))
        paths[0].write_text('different')
        with self.assertRaisesRegex(OSError, 'Source/tool/binary drift'):
            small.check_inputs(plan)

    def test_input_census_rejects_new_names_and_replaced_ancestors(self):
        directory = self.root/'inputs'
        directory.mkdir()
        path = directory/'source'
        path.write_text('original')
        plan = dict(frozen=[small.freeze(path)], inventories={str(directory): small.inventory(directory)})
        small.check_inputs(plan)
        extra = directory/'unexpected'
        extra.write_text('new')
        with self.assertRaisesRegex(OSError, 'Source inventory drift'):
            small.check_inputs(plan)
        extra.unlink()
        if os.name != 'nt':
            moved = self.root/'moved'
            directory.rename(moved)
            directory.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(OSError, 'Symlink/reparse input'):
                small.check_inputs(plan)

    def test_input_census_rejects_windows_reparse_metadata_and_missing_sources(self):
        from types import SimpleNamespace
        path = self.root/'source'
        path.write_text('original')
        plan = dict(frozen=[small.freeze(path)], inventories={})
        original = Path.lstat
        def reparse(value, *args, **kwargs):
            actual = original(value, *args, **kwargs)
            return SimpleNamespace(st_mode=actual.st_mode, st_file_attributes=0x400) if value == path else actual
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(OSError, 'Symlink/reparse input'):
                small.check_inputs(plan)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            small.check_inputs(plan)

    def test_source_packet_reservation_and_inventory_drift(self):
        path = self.root / 'source'
        path.write_text('frozen')
        plan = dict(frozen=[small.freeze(path)], inventories={str(self.root): small.inventory(self.root)})
        small.check_inputs(plan)
        path.write_text('mutated')
        with self.assertRaisesRegex(OSError, 'drift'):
            small.check_inputs(plan)
        plan['frozen'] = [small.freeze(path)]
        (self.root / 'new').write_text('new')
        with self.assertRaisesRegex(OSError, 'inventory drift'):
            small.check_inputs(plan)

    def test_atomic_replacement_preserves_previous_on_error(self):
        path = self.root / 'guard.json'
        small.runner.write_json(path, dict(allowed=True))
        with patch.object(os, 'replace', side_effect=OSError('replacement failed')):
            with self.assertRaises(OSError):
                small.runner.write_json(path, dict(allowed=False))
        self.assertTrue(json.loads(path.read_text())['allowed'])
        small.runner.write_json(path, dict(allowed=False))
        self.assertFalse(json.loads(path.read_text())['allowed'])

    def test_actual_guard_producer_preserves_two_hot_variants_at_one_input_start(self):
        from types import SimpleNamespace
        resources,plan,process,watchdog,_=self.supervision_fixture()
        (self.root/'worker-result.json').unlink()
        (self.root/'batch').mkdir();(self.root/'batch/runner.lock').write_text('123')
        packet=dict(origin='http://127.0.0.1:8422',child_pid=20,runner_pid=123,argv=['test-browser.mjs'],
                    receipt=str(self.root/'actual-receipt.jsonl'))
        plan['packets']=[dict(value=packet)]
        plan['batch_started_ms']=resources['last_progress_ms']=10000
        resources['inputs']=SimpleNamespace(read=lambda:10000)
        calls,produced=[],[]
        def sample(*args,**kwargs):
            calls.append(True)
            if len(calls)==3:(self.root/'worker-result.json').write_text('{"code":0}')
            return (dict(pids=[123,20,30]+([31] if len(calls)>1 else []),kill_on_close=True,flags=8192),[],[],0)
        def state(*args):
            return dict(attempts=[dict(status='passed' if len(calls)==3 else 'running')],terminal=len(calls)==3)
        original_write=small.write_control_json
        def write(path,value):
            original_write(path,value);produced.append(value)
        actual=small.Receipts()
        class Receipt:
            cleaned=False
            pending_exit=None
            def read(inner,path,p,now,owned,guards,**kwargs):
                if len(calls)!=3:return
                self.assertEqual(guards[10000],produced)
                self.assertEqual(len(produced),2)
                self.assertNotEqual(produced[0],produced[1])
                events=[dict(type='binding',sampled_ms=10950,actual=dict(pid=30,parentPid=20))]
                for capacity in produced:
                    events += [dict(type='quota-start',sampled_ms=10950,observation_started_ms=10950),
                        dict(type='sample',sampled_ms=10950,capacity=capacity,quota=dict(sampled_ms=10950,
                            origin=packet['origin'],secure=True,isolated=True,usage=0,quota=10*small.GIB,
                            persisted=False,persistence_permission='prompt'))]
                Path(path).write_text(''.join(json.dumps(v)+'\n' for v in events))
                actual.read(Path(path),p,now,owned,guards)
                self.assertTrue(actual.sampled)
                forged=dict(produced[0],cumulative_owned_bytes=99)
                events[-1]['capacity']=forged
                Path(path).write_text(''.join(json.dumps(v)+'\n' for v in events))
                with self.assertRaisesRegex(OSError,'historical Job census'):
                    type(actual)().read(Path(path),p,now,owned,guards)
                events[-1]['capacity']=produced[0]
                Path(path).write_text(''.join(json.dumps(v)+'\n' for v in events))
                # Even genuine retained variants expire; a fresh event does not restamp capacity.
                for value in events:
                    value['sampled_ms']=16001
                    if value['type']=='quota-start':value['observation_started_ms']=16001
                Path(path).write_text(''.join(json.dumps(v)+'\n' for v in events))
                with self.assertRaisesRegex(OSError,'Stale historical Job census'):
                    type(actual)().read(Path(path),p,16001,owned,guards)
                inner.cleaned=True
        with patch.object(small,'Receipts',Receipt),patch.object(small,'sample_resources',side_effect=sample), \
                patch.object(small,'StatusReader',return_value=SimpleNamespace(read=state)), \
                patch.object(small,'census_child',return_value=dict(pid=20)), \
                patch.object(small,'write_control_json',side_effect=write), \
                patch.object(small,'now_ms',return_value=10950),patch.object(small.time,'sleep'):
            small.run_supervision(plan,self.root,process,1,{},watchdog,{},resources)
        self.assertEqual(len(produced),3)
        self.assertTrue(all(v['sampled_ms']==10000 for v in produced))

    def test_actual_worker_guard_expires_oldest_input_start_despite_fresh_publication(self):
        import ast
        from types import SimpleNamespace
        tree=ast.parse(Path(small.__file__).read_bytes())
        worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='worker')
        guard=next(n for n in worker.body if isinstance(n,ast.FunctionDef) and n.name=='guard')
        overall=next(n for n in worker.body if isinstance(n,ast.FunctionDef) and n.name=='check_overall')
        enclosing=ast.FunctionDef(name='make',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
            body=[ast.Assign(targets=[ast.Name(id='last_attempt',ctx=ast.Store())],value=ast.Constant(1)),overall,guard,
                  ast.Return(value=ast.Name(id='guard',ctx=ast.Load()))],decorator_list=[])
        code=compile(ast.fix_missing_locations(ast.Module(body=[enclosing],type_ignores=[])),'<actual-worker-input-age>','exec')
        wall=[10950]
        value=dict(allowed=True,sampled_ms=10000,runner_pid=os.getpid())
        scope=dict(stop=None,writer=SimpleNamespace(current=SimpleNamespace(attempts=[1])),owned=self.root,
            need=small.need,json=json,time=small.time,now_ms=lambda:wall[0],os=os,
            windows=SimpleNamespace(read_control_snapshot=lambda *args:json.dumps(value)))
        exec(code,scope);guard=scope['make']()
        guard()
        for _ in range(3):guard()  # Re-reading/publication does not change the old proof.
        wall[0]=15001
        with self.assertRaisesRegex(OSError,'Supervisor denied/stale'):guard()
        wall[0]=8999
        with self.assertRaisesRegex(OSError,'Supervisor denied/stale'):guard()

    def test_quota_start_gap_and_blocked_pending_are_not_hidden_by_capacity_age(self):
        packet = dict(origin='http://127.0.0.1:8422',child_pid=20,runner_pid=10,argv=['test-browser.mjs'])
        capacity=dict(sampled_ms=1000,child_pid=20,runner_pid=10,owned_pids=[10,20,30])
        quota=dict(sampled_ms=1000,origin=packet['origin'],secure=True,isolated=True,usage=0,quota=10*small.GIB,persisted=False,persistence_permission='prompt')
        path=self.root/'quota.jsonl'
        initial=[dict(type='binding',sampled_ms=1000,actual=dict(pid=30,parentPid=20)),
            dict(type='quota-start',sampled_ms=1000,observation_started_ms=1000),
            dict(type='sample',sampled_ms=1000,capacity=capacity,quota=quota)]
        path.write_text(''.join(json.dumps(value)+'\n' for value in initial))
        receipts=small.Receipts();receipts.read(path,packet,1000,[10,20,30],{1000:capacity})
        with self.assertRaisesRegex(OSError,'start cadence'):
            receipts.read(path,packet,47000,[10,20,30],{})
        with path.open('a') as stream:stream.write(json.dumps(dict(type='quota-start',sampled_ms=2000,observation_started_ms=2000))+'\n')
        receipts.read(path,packet,2000,[10,20,30],{})
        self.assertEqual(receipts.quota_at,1000,'Starting a pending observation must not refresh completed capacity')
        with self.assertRaisesRegex(OSError,'pending/blocked'):
            receipts.read(path,packet,32001,[10,20,30],{})

    def test_quota_append_is_judged_at_completed_receipt_read_without_future_tolerance(self):
        packet=dict(origin='http://127.0.0.1:8422',child_pid=20,runner_pid=10,argv=['test-browser.mjs'])
        capacity=dict(sampled_ms=1000,child_pid=20,runner_pid=10,owned_pids=[10,20,30])
        quota=dict(sampled_ms=1001,origin=packet['origin'],secure=True,isolated=True,usage=0,
            quota=10*small.GIB,persisted=False,persistence_permission='prompt')
        events=[dict(type='binding',sampled_ms=1000,actual=dict(pid=30,parentPid=20)),
            dict(type='quota-start',sampled_ms=1000,observation_started_ms=1000),
            dict(type='sample',sampled_ms=1002,capacity=capacity,quota=quota)]
        path=self.root/'append.jsonl';path.write_text(''.join(json.dumps(v)+'\n' for v in events))
        with self.assertRaisesRegex(OSError,'Quota capacity/staleness') as denied:
            small.Receipts().read(path,packet,1000,[10,20,30],{1000:capacity})
        witness=small.error_causes(denied.exception,{})[0]['receipt_observation']
        self.assertEqual((witness['now_ms'],witness['quota_sampled_ms'],witness['age_ms']),(1000,1001,-1))
        self.assertEqual(witness['path'],str(path));self.assertEqual(witness['pid'],30)
        completed=[False];read=Path.read_bytes
        def snapshot(value):
            data=read(value);completed[0]=True;return data
        def now():
            self.assertTrue(completed[0],'The receipt snapshot must finish before sampling its clock')
            return 1002
        with patch.object(Path,'read_bytes',snapshot),patch.object(small,'now_ms',side_effect=now):
            accepted=small.Receipts();accepted.read(path,packet,None,[10,20,30],{1000:capacity})
        self.assertTrue(accepted.sampled)
        quota['sampled_ms']=1003;path.write_text(''.join(json.dumps(v)+'\n' for v in events))
        with patch.object(small,'now_ms',return_value=1002),self.assertRaisesRegex(OSError,'Quota capacity/staleness'):
            small.Receipts().read(path,packet,None,[10,20,30],{1000:capacity})

    def test_start_then_raise_worker_launch_retains_original_without_handle(self):
        entered,release=threading.Event(),threading.Event()
        threads=[]
        def launch():
            thread=threading.Thread(target=lambda:(entered.set(),release.wait(2)),daemon=True)
            threads.append(thread);thread.start()
            raise OSError('launch returned no handle')
        reservation={'worker_launch_attempted':True}
        try:
            with self.assertRaisesRegex(OSError,'no handle'):launch()
            self.assertTrue(entered.wait(1))
            errors=small.finish_supervision(dict(storage_method='fake'),self.root,None,None,reservation,None,None,'launch returned no handle')
            self.assertFalse(reservation['release_safe'])
            self.assertTrue(any('launch ownership uncertain' in error for error in errors))
        finally:
            release.set()
            for thread in threads:thread.join(1)

    def test_receipt_quota_chatter_does_not_update_actual_progress(self):
        path = self.root / 'quota.jsonl'
        receipts = small.Receipts()
        packet = dict(origin='http://127.0.0.1:8422', child_pid=20, runner_pid=10, argv=['test-browser.mjs'])
        events = [dict(type='binding', sampled_ms=1000, actual=dict(pid=30, parentPid=20))]
        def append(event):
            with path.open('a') as out:
                out.write(json.dumps(event)+'\n')
        for event in events:
            append(event)
        receipts.read(path, packet, 1000, [10, 20, 30], {})
        for tick in (2000, 3000):
            append(dict(type='quota-start',sampled_ms=tick,observation_started_ms=tick))
            append(dict(type='sample', sampled_ms=tick, capacity=dict(sampled_ms=tick, child_pid=20, runner_pid=10, owned_pids=[10,20,30]), quota=dict(
                sampled_ms=tick, origin=packet['origin'], secure=True, isolated=True, usage=0, quota=10*small.GIB,
                persisted=False, persistence_permission='prompt')))
            receipts.read(path, packet, tick, [10, 20, 30], {tick:dict(sampled_ms=tick, child_pid=20, runner_pid=10, owned_pids=[10,20,30])})
        self.assertFalse(hasattr(receipts, 'last_progress_ms'))
        with self.assertRaisesRegex(OSError, 'stale'):
            receipts.read(path, packet, 93001, [10, 20, 30], {})
        with self.assertRaisesRegex(OSError, 'absence'):
            receipts.read(path, packet, 3000, [10, 20], {})
        path.unlink()
        with self.assertRaisesRegex(OSError, 'lost'):
            receipts.read(path, packet, 3000, [10, 20], {})

    def test_expected_kill_is_explicit_and_does_not_exempt_other_failures(self):
        packet = dict(origin='http://127.0.0.1:8422', child_pid=20, runner_pid=10, argv=['test-browser-termination.mjs', '--persistent', '--process-kill'])
        path = self.root / 'kill.jsonl'
        receipt = small.Receipts()
        events = [dict(type='binding', sampled_ms=1000, actual=dict(pid=30, parentPid=20)),
                  dict(type='quota-start',sampled_ms=1000,observation_started_ms=1000),
                  dict(type='sample', sampled_ms=1000, capacity=dict(sampled_ms=1000, child_pid=20, runner_pid=10, owned_pids=[10,20,30]), quota=dict(sampled_ms=1000, origin=packet['origin'], secure=True, isolated=True, usage=0, quota=10*small.GIB, persisted=False, persistence_permission='prompt')),
                  dict(type='deliberate-process-kill-armed', sampled_ms=1000, pid=30),
                  dict(type='deliberate-process-kill-observed', sampled_ms=1000, pid=30),
                  dict(type='monitor-cleanup', sampled_ms=1000, errors=[])]
        path.write_text('\n'.join(json.dumps(e) for e in events)+'\n')
        receipt.read(path, packet, 1001, [10, 20], {1000:events[2]['capacity']}, census_started_ms=1001)
        self.assertTrue(receipt.cleaned)
        packet['argv'] = ['test-browser-termination.mjs']
        with self.assertRaisesRegex(OSError, 'Unapproved'):
            small.Receipts().read(path, packet, 1000, [10, 20], {1000:events[2]['capacity']})

    def test_kill_receipt_requires_strictly_newer_census_and_defers_cleanup_and_binding(self):
        path=self.root/'kill-order.jsonl'
        receipt=small.Receipts()
        receipt.pid=30;receipt.armed=True;receipt.sampled=True;receipt.quota_at=1000
        packet=dict(child_pid=20,argv=['--process-kill'])
        observed=dict(type='deliberate-process-kill-observed',sampled_ms=1020,pid=30)
        cleanup=dict(type='monitor-cleanup',sampled_ms=1021,errors=[])
        binding=dict(type='binding',sampled_ms=1022,actual=dict(pid=31,parentPid=20))
        path.write_text(''.join(json.dumps(v)+'\n' for v in (observed,cleanup,binding)))
        for start in (1000,1020):
            receipt.read(path,packet,1030,[20,30],{},census_started_ms=start)
            self.assertEqual(receipt.pending_exit,1020)
            self.assertFalse(receipt.observed);self.assertFalse(receipt.cleaned)
            self.assertEqual(receipt.offset,0)
            self.assertEqual(receipt.pid,30,'Later binding must not be consumed before independent exit')
        receipt.read(path,packet,1030,[20,31],{},census_started_ms=1023)
        self.assertIsNone(receipt.pending_exit)
        self.assertEqual(receipt.pid,31)
        self.assertFalse(receipt.observed,'Verified old exit cannot leak into new lifecycle')
        self.assertFalse(receipt.cleaned,'New lifecycle still requires its own complete cleanup')
        self.assertTrue(receipt.active)

    def test_kill_receipt_new_census_live_wrongpid_missing_and_stale_remain_strict(self):
        packet=dict(argv=['--process-kill'])
        for fault in ('live','wrongpid','missing-start','stale'):
            receipt=small.Receipts();receipt.pid=30;receipt.armed=True;receipt.sampled=True
            path=self.root/(fault+'.jsonl')
            event=dict(type='deliberate-process-kill-observed',sampled_ms=1020,pid=31 if fault=='wrongpid' else 30)
            path.write_text(json.dumps(event)+'\n')
            kwargs={} if fault=='missing-start' else dict(census_started_ms=1021 if fault!='stale' else 7000)
            with self.subTest(fault=fault),self.assertRaises(OSError) as caught:
                receipt.read(path,packet,7001 if fault=='stale' else 1030,[20,30],{},**kwargs)
            self.assertFalse(receipt.cleaned)
            if fault=='live':
                facts=small.error_causes(caught.exception,{})[0]['receipt_observation']
                self.assertEqual(facts,dict(pid=30,event_ms=1020,census_started_ms=1021,pids=[20,30]))

    def test_pending_exit_blocks_progress_and_next_command_until_new_complete_guard(self):
        resources,plan,process,watchdog,_=self.supervision_fixture()
        (self.root/'worker-result.json').unlink()
        _,_,publish=self.observation_fixture(2)
        publish();publish(['running']);publish(['passed']);publish(['passed','running'])
        plan['runner_plan']['steps']=[dict(id='contract-1'),dict(id='contract-2')]
        plan['packets']*=2
        previous=resources['last_progress_ms'];instances=[];samples=[];pulses=[]
        class Receipt:
            cleaned=False
            pending_exit=None
            def __init__(self):self.index=len(instances);self.reads=0;instances.append(self)
            def read(self,*args,**kwargs):
                self.reads+=1
                if self.index==0:
                    self.pending_exit=1020 if self.reads==1 else None
                    self.cleaned=self.reads>1
        def sample(*args,**kwargs):
            samples.append(True)
            if len(samples)==3:raise OSError('end bounded pending-exit control')
            return dict(pids=[123],kill_on_close=True,flags=8192),[],[],0
        def pulse():
            pulses.append(True)
            if len(pulses)==1:
                self.assertEqual(resources['last_progress_ms'],previous)
                self.assertFalse((self.root/'command-ready-2.json').exists())
        watchdog.pulse=pulse
        with patch.object(small,'Receipts',Receipt),patch.object(small,'sample_resources',side_effect=sample), \
             patch.object(small,'census_child',return_value=None),patch.object(small.time,'sleep'):
            with self.assertRaisesRegex(OSError,'end bounded pending-exit'):
                small.run_supervision(plan,self.root,process,1,{},watchdog,{},resources)
        self.assertEqual(len(pulses),2,'Both pulses require an actual completed full guard')
        self.assertGreater(resources['last_progress_ms'],previous)
        self.assertTrue((self.root/'command-ready-2.json').exists())

    def test_receipt_component_assignment_failure_stops_exact_child_before_reap_and_close(self):
        from types import SimpleNamespace
        from scale_acceptance import native_scale_windows as bootstrap
        import hashlib
        old=self.root/'old.py';old.write_bytes(b'class Receipts: pass\n')
        root=self.root/'component'
        events=[];active=[True]
        class Child:
            handles=(101,102,333)
            handle=101
            pid=333
            creation_started=True
            def start(self,*args):
                events.append('start')
                with bootstrap.open(os.devnull,'rb') as stream:
                    self_outer.assertFalse(stream.closed)
                with bootstrap.open(old,'rb') as stream:
                    self_outer.assertEqual(stream.read(),b'class Receipts: pass\n')
            def assign(self,*args):events.append('assign');raise OSError('assignment denied')
            def resume(self):raise AssertionError('Unassigned child resumed')
            def wait(self,timeout):
                self_outer.assertFalse(active[0]);events.append('reap');return 91
            def close(self):events.append('close-child')
        self_outer=self
        def terminate(handle,code):
            self.assertEqual(handle,101);active[0]=False;events.append('terminate-exact');return 1
        kernel=SimpleNamespace(GetCurrentProcess=lambda:-1,WaitForSingleObject=lambda h,t:258 if active[0] else 0,
                               TerminateProcess=terminate)
        checker=small.module('acceptance-preflight')
        proxy=SimpleNamespace(**dict(os.__dict__,name='nt'))
        with patch.dict(native_receipt_census_control.__globals__,{'os':proxy}), \
             patch.object(small,'module',return_value=checker),patch.object(checker.Budget,'install'), \
             patch.object(small.shutil,'disk_usage',return_value=SimpleNamespace(free=256*small.GIB)), \
             patch.object(small.runner,'contain_session'),patch.object(small.runner,'_SESSION_JOB',888), \
             patch.object(bootstrap,'create_job',return_value=777),patch.object(bootstrap,'SuspendedWorker',return_value=Child()), \
             patch.object(small.windows,'kernel',return_value=kernel), \
             patch.object(small.windows,'held_identity',return_value=dict(pid=os.getpid(),created=1)), \
             patch.object(small.windows,'query_job',side_effect=lambda job:dict(kill_on_close=True,pids=[] if job==777 else [os.getpid()])), \
             patch.object(small.windows,'terminate',side_effect=lambda _:events.append('terminate-inner')), \
             patch.object(small.windows,'close'),patch.object(small.windows,'checked',side_effect=lambda value,**kw:value):
            code=native_receipt_census_control(str(old),hashlib.sha256(old.read_bytes()).hexdigest(),'unused','a'*64,str(root))
        self.assertEqual(code,1)
        report=json.loads((root/'result.json').read_text())
        self.assertEqual(report['error'],'assignment denied')
        self.assertTrue(report['child_reaped']);self.assertTrue(report['child_handles_closed'])
        self.assertEqual(report['cleanup_errors'],[])
        self.assertLess(events.index('terminate-exact'),events.index('reap'))
        self.assertLess(events.index('reap'),events.index('close-child'))
        self.assertEqual(events.count('close-child'),1)

    def test_independent_watchdog_stops_reaps_blocked_owner_and_keeps_partial_logs(self):
        log = self.root / 'partial.log'
        log.write_text('partial failure retained')
        calls = []
        class Worker:
            def wait(self, timeout):
                calls.append(('reap', timeout))
        watchdog = small.Watchdog(123, Worker(), timeout=.05, terminate=lambda job: calls.append(('kill', job)))
        watchdog.thread.start()
        watchdog.thread.join(timeout=2)
        self.assertEqual(calls, [('kill', 123), ('reap', 10)])
        self.assertIn('late/blocked', watchdog.error)
        self.assertEqual(log.read_text(), 'partial failure retained')
        with self.assertRaises(OSError):
            watchdog.pulse()

    def test_overall_deadline_clips_batch_with_cleanup_and_legacy_stays7200(self):
        plan=dict(batch_started_ms=1000,config={})
        self.assertEqual(small.execution_deadline_ms(plan),7201000)
        plan['config']['overall_deadline_ms']=500000
        self.assertEqual(small.execution_deadline_ms(plan),380000)
        with patch.object(small,'now_ms',return_value=379999):small.check_execution_deadline(plan)
        with patch.object(small,'now_ms',return_value=380000),self.assertRaisesRegex(OSError,'overall/channel'):
            small.check_execution_deadline(plan)
        plan['config']['overall_deadline_ms']=10000000
        self.assertEqual(small.execution_deadline_ms(plan),7201000)

    def test_overall_watchdog_deadline_is_not_renewed_by_live_pulses_or_wall_clock(self):
        calls=[]
        process=Mock();process.wait.side_effect=lambda timeout:calls.append(('reap',timeout))
        endpoint=time.monotonic()+.08
        watchdog=small.Watchdog(123,process,timeout=10,terminate=lambda job:calls.append(('stop',job)),deadline=endpoint)
        watchdog.thread.start()
        with patch.object(small,'now_ms',return_value=-100000):
            for _ in range(20):
                if watchdog.error:break
                watchdog.pulse();time.sleep(.01)
        watchdog.thread.join(timeout=1)
        self.assertFalse(watchdog.thread.is_alive())
        self.assertEqual(watchdog.deadline,endpoint)
        self.assertEqual(calls,[('stop',123),('reap',10)])
        self.assertIn('overall execution deadline',watchdog.error)

    def test_overall_deadline_failure_still_reaps_closes_and_proves_release_safety(self):
        events,watchdog,process,resources,plan=self.cleanup_fixture();reservation={}
        plan['config']=dict(overall_deadline_ms=small.now_ms()+120000)
        watchdog.error='Independent watchdog: overall execution deadline'
        with patch.object(small,'sample_resources',return_value=(dict(pids=[]),[],[],0)), \
             patch.object(small.windows,'terminate')as stop,patch.object(small.windows,'close')as close:
            errors=small.finish_supervision(plan,self.root,process,123,reservation,watchdog,resources,watchdog.error)
        stop.assert_called_once_with(123);close.assert_called_once_with(123)
        self.assertIn('reap',events);self.assertTrue(reservation['release_safe'])
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])
        self.assertTrue(watchdog.done.is_set())

    def test_watchdog_retains_kill_error(self):
        def fail(job):
            raise OSError('cleanup failed')
        watchdog = small.Watchdog(123, None, timeout=.01, terminate=fail)
        watchdog.thread.start()
        watchdog.thread.join(timeout=2)
        self.assertIn('cleanup failed', watchdog.error)

    def test_process_identity_errors_keep_exact_api_pid_and_close_cause(self):
        from types import SimpleNamespace
        windows = small.windows
        for api in ('OpenProcess', 'GetProcessTimes', 'CloseHandle', 'dual'):
            dll = SimpleNamespace(OpenProcess=Mock(return_value=0 if api == 'OpenProcess' else 2**40),
                QueryFullProcessImageNameW=Mock(return_value=1), GetProcessTimes=Mock(return_value=0),
                CloseHandle=Mock(return_value=0 if api in ('CloseHandle', 'dual') else 1))
            with self.subTest(api=api), patch.object(windows, 'kernel', return_value=dll), \
                    patch.object(windows, 'ntdll', return_value=SimpleNamespace(NtQueryInformationProcess=lambda *args: 0)), \
                    patch.object(windows.os, 'name', 'nt'), \
                    patch.object(windows.ctypes, 'get_last_error', side_effect=[87, 6] if api == 'dual' else [87], create=True):
                if api == 'CloseHandle':
                    with patch.object(windows, '_held_identity', return_value=dict(pid=20, created=200)):
                        with self.assertRaises(windows.ProcessHandleCloseError) as raised:
                            windows.process_identity(20)
                else:
                    with self.assertRaises(OSError) as raised:
                        windows.process_identity(20)
                error = raised.exception
                self.assertEqual(error.api, 'CloseHandle' if api == 'dual' else api)
                self.assertEqual(error.pid, 20)
                self.assertEqual(error.winerror, 6 if api == 'dual' else 87)
                if api == 'OpenProcess':
                    dll.CloseHandle.assert_not_called()
                else:
                    dll.CloseHandle.assert_called_once_with(2**40)
                if api in ('CloseHandle', 'dual'):
                    self.assertTrue(error.process_handle_close_uncertain)
                    self.assertEqual(error.__cause__.api, 'CloseHandle')
                if api == 'dual':
                    self.assertEqual(error.__cause__.__context__.api, 'GetProcessTimes')
                    self.assertEqual(error.__cause__.__context__.winerror, 87)
                    trace, reservation = [], dict(lock_identity=[1,2])
                    with patch.object(small, 'check_inputs'), \
                            patch.object(small, 'module', return_value=SimpleNamespace(host_lock_path=lambda: 'lock')), \
                            patch.object(small, 'stamp_lock', return_value=[1,2]), \
                            patch.object(windows, 'query_job', return_value=dict(pids=[20])), \
                            patch.object(windows, 'job_processes', side_effect=error):
                        with self.assertRaises(windows.ProcessHandleCloseError) as repeated:
                            small.sample_resources(dict(config={}), [], reservation, 123, None, False, trace=trace)
                    self.assertIs(repeated.exception, error)
                    row = next(v for v in json.loads(json.dumps(trace)) if v['event']=='error')
                    self.assertEqual([v['api'] for v in row['causes']], ['CloseHandle','CloseHandle','GetProcessTimes'])
                    self.assertEqual([v['winerror'] for v in row['causes']], [6,6,87])
                    self.assertTrue(reservation['process_handle_close_uncertain'])

    def test_owning_kernel_binds_process_observation_handle_apis_once(self):
        windows = small.windows
        windows.kernel.cache_clear()
        dll = Mock()
        try:
            with patch.object(windows.os, 'name', 'nt'), \
                    patch.object(windows.ctypes, 'WinDLL', return_value=dll, create=True) as load:
                self.assertIs(windows.kernel(), dll)
                self.assertIs(windows.kernel(), dll)
                load.assert_called_once_with('kernel32', use_last_error=True)
                self.assertEqual(dll.GetProcessId.argtypes, [windows.W.HANDLE])
                self.assertIs(dll.GetProcessId.restype, windows.W.DWORD)
                self.assertEqual(dll.GetExitCodeProcess.argtypes,
                                 [windows.W.HANDLE, windows.ctypes.POINTER(windows.W.DWORD)])
                self.assertIs(dll.GetExitCodeProcess.restype, windows.W.BOOL)
        finally:
            windows.kernel.cache_clear()

    def test_process_identity_failure_serializes_partial_births_and_rethrows_same_error(self):
        from types import SimpleNamespace
        error = OSError('actual API failure')
        error.api, error.pid, error.winerror = 'OpenProcess', 20, 87
        error.completed_processes = [dict(pid=10, created=100, image='not duplicated')]
        error.retired_snapshots = [dict(pid=9, previous_birth=None, api='OpenProcess', winerror=87, fresh_census=dict(pids=[10,20],kill_on_close=True))]
        # Diagnostic chains are bounded even if a future caller adds wrappers.
        cause = error
        for index in range(6):
            cause.__cause__ = OSError('cause '+str(index))
            cause = cause.__cause__
        trace, reservation, joined = [], dict(lock_identity=[1, 2]), threading.Event()
        first = dict(pid=10, created=100, parent=1, image='do not duplicate image payload')
        with patch.object(small, 'check_inputs', side_effect=lambda plan: joined.set()), \
                patch.object(small, 'module', return_value=SimpleNamespace(host_lock_path=lambda: 'lock')), \
                patch.object(small, 'stamp_lock', return_value=[1,2]), \
                patch.object(small.windows, 'query_job', return_value=dict(pids=[10,20])), \
                patch.object(small.windows, 'job_processes', side_effect=error):
            with self.assertRaises(OSError) as raised:
                small.sample_resources(dict(config={}), [], reservation, 123, None, False, trace=trace)
        self.assertIs(raised.exception, error)
        self.assertTrue(joined.is_set())
        path = self.root/'control-failure.json'
        small.runner.write_json(path, dict(error=str(error), sample_trace=trace))
        row = next(row for row in json.loads(path.read_text())['sample_trace'] if row['event']=='error')
        self.assertEqual(row['pid'], 20)
        self.assertEqual(row['census_pids'], [10,20])
        self.assertEqual(row['completed_processes'], [dict(pid=10, created=100)])
        self.assertEqual((row['causes'][0]['api'], row['causes'][0]['winerror']), ('OpenProcess', 87))
        self.assertEqual(len(row['causes']), 4)
        self.assertEqual(row['retired_snapshots'], error.retired_snapshots)
        self.assertNotIn('process_handle_close_uncertain', reservation)

    def test_uncertain_process_close_retains_original_despite_empty_reaped_job(self):
        from types import SimpleNamespace
        error = small.windows.ProcessHandleCloseError('CloseHandle failed')
        error.api, error.pid, error.winerror = 'CloseHandle', 20, 6
        reservation = dict(lock_identity=[1,2])
        with patch.object(small, 'check_inputs'), \
                patch.object(small, 'module', return_value=SimpleNamespace(host_lock_path=lambda: 'lock')), \
                patch.object(small, 'stamp_lock', return_value=[1,2]), \
                patch.object(small.windows, 'query_job', return_value=dict(pids=[20])), \
                patch.object(small.windows, 'job_processes', side_effect=error):
            with self.assertRaises(small.windows.ProcessHandleCloseError) as raised:
                small.sample_resources(dict(config={}), [], reservation, 123, None, False)
        self.assertIs(raised.exception, error)
        self.assertTrue(reservation['process_handle_close_uncertain'])
        process = SimpleNamespace(returncode=91, poll=lambda: 91, wait=lambda timeout: 91)
        with patch.object(small.windows, 'query_job', return_value=dict(pids=[])), \
                patch.object(small.windows, 'terminate'), patch.object(small.windows, 'close'):
            errors = small.finish_supervision({}, self.root, process, 123, reservation, None, None, str(error))
        self.assertIn('Parent handle close unproven', errors)
        self.assertFalse(reservation['release_safe'])
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])

    def test_job_snapshot_absence_requires_complete_exclusion_and_bounds_every_attempt(self):
        from types import SimpleNamespace
        windows = small.windows
        good = lambda pids: dict(kill_on_close=True, flags=8192, pids=pids)
        cases = [
            ('unknown-absent', [1], [good([]),good([])], {1}, 87, (), None),
            ('known-absent', [1], [good([]),good([])], {1}, 87, [dict(pid=1,created=1001)], None),
            ('still-current', [1], [good([1])], {1}, 87, (), 'error'),
            ('flags', [1], [dict(kill_on_close=False,pids=[])], {1}, 87, (), 'error'),
            ('incomplete', [1], [windows.IncompleteJobCensus(2,1)], {1}, 87, (), 'error'),
            ('access-denied', [1], [], {1}, 5, (), 'error'),
            ('new-member', [1], [good([2]),good([2]),good([2])], {1}, 87, (), None),
            ('intermediate-reappearance', [1,2], [good([2]),good([1]),good([])], {1,2}, 87, (), 'error'),
            ('bounded-absent-attempts', [1], [good([]),good([2]),good([]),good([3])], {1,2,3}, 87, (), 'error'),
        ]
        for name, initial, snapshots, missing, code, previous, denial in cases:
            opened, closed = [], []
            def open_process(access, inherit, pid):
                opened.append(pid)
                return 0 if pid in missing else 1000+pid
            def member(handle, job, output):
                output._obj.value = 1
                return 1
            dll = SimpleNamespace(OpenProcess=open_process, IsProcessInJob=member,
                CloseHandle=lambda handle:(closed.append(handle) or 1), WaitForSingleObject=lambda *args:0)
            with self.subTest(case=name), patch.object(windows.os,'name','nt'), \
                    patch.object(windows.ctypes,'get_last_error',return_value=code,create=True), \
                    patch.object(windows,'MAX_PIDS',2 if name=='bounded-absent-attempts' else 256), \
                    patch.object(windows,'query_job',side_effect=snapshots) as fresh, \
                    patch.object(windows,'_held_birth',side_effect=lambda dll,handle,pid=None:1000+pid), \
                    patch.object(windows,'_held_identity',side_effect=lambda dll,handle,pid:dict(pid=pid,created=1000+pid,parent=99,image='python')):
                if denial:
                    with self.assertRaises(OSError) as caught:
                        windows.job_processes(7,good(initial),previous,backend=dll)
                    if name=='access-denied':
                        self.assertEqual(caught.exception.api,'OpenProcess')
                        self.assertEqual(caught.exception.winerror,5)
                        fresh.assert_not_called()
                    if name=='bounded-absent-attempts':
                        self.assertNotIn(3,opened)
                    if name=='intermediate-reappearance':
                        self.assertIn('reappearing',str(caught.exception))
                else:
                    value=windows.job_processes(7,good(initial),previous,backend=dll)
                    retired=value['retired_snapshots'][0]
                    self.assertEqual(retired['pid'],1)
                    self.assertEqual(retired['previous_birth'],1001 if previous else None)
                    self.assertEqual(retired['winerror'],87)
                    if name=='new-member':
                        self.assertEqual(value['census']['pids'],[2])
                        self.assertEqual([v['pid'] for v in value['processes']],[2])
                        self.assertIn(2,opened)
                        self.assertIn(1002,closed)
                    else:
                        self.assertEqual(value['census']['pids'],[])
                        self.assertEqual(value['processes'],[])

    def test_job_snapshot_preserves_held_identity_rules_and_closes_other_handles_on_failure(self):
        from types import SimpleNamespace
        windows=small.windows
        good=lambda pids:dict(kill_on_close=True,flags=8192,pids=pids)
        for mode in ('normal','held-exited','held-live','foreign','reused','dual-close'):
            closed=[]
            def member(handle,job,output):
                output._obj.value=0 if mode=='foreign' else 1
                return 1
            dll=SimpleNamespace(OpenProcess=lambda access,inherit,pid:1000+pid,IsProcessInJob=member,
                WaitForSingleObject=lambda *args:258 if mode=='held-live' else 0,
                GetExitCodeProcess=lambda handle,out:(setattr(out._obj,'value',259 if mode=='held-live' else 0) or 1),
                CloseHandle=lambda handle:(closed.append(handle) or (0 if mode=='dual-close' and handle==1002 else 1)))
            def identity(dll,handle,pid):
                if mode in ('held-exited','held-live'):raise windows.ProcessImageQueryError(31,pid)
                if mode=='dual-close' and pid==2:
                    error=OSError('GetProcessTimes failed');error.api,error.pid,error.winerror='GetProcessTimes',pid,87
                    raise error
                return dict(pid=pid,created=1000+pid,parent=99,image='python')
            initial=[1,2] if mode=='dual-close' else [1]
            previous=[dict(pid=1,created=999)] if mode=='reused' else ()
            snapshots=[good([]),good([])] if mode in ('held-exited','held-live') else [good([1])]
            with self.subTest(mode=mode), patch.object(windows.os,'name','nt'), \
                    patch.object(windows.ctypes,'get_last_error',return_value=6,create=True), \
                    patch.object(windows,'query_job',side_effect=snapshots), \
                    patch.object(windows,'_held_birth',side_effect=lambda dll,handle,pid=None:1000+pid), \
                    patch.object(windows,'_held_identity',side_effect=identity):
                if mode in ('normal','held-exited'):
                    value=windows.job_processes(7,good(initial),previous,backend=dll)
                    self.assertNotIn('retired_snapshots',value)
                    self.assertEqual(value['census']['pids'],[] if mode=='held-exited' else [1])
                else:
                    with self.assertRaises(OSError) as caught:
                        windows.job_processes(7,good(initial),previous,backend=dll)
                    if mode=='dual-close':
                        self.assertTrue(caught.exception.process_handle_close_uncertain)
                        self.assertEqual((caught.exception.api,caught.exception.pid,caught.exception.winerror),('CloseHandle',2,6))
                        self.assertEqual(caught.exception.__context__.api,'GetProcessTimes')
                        self.assertEqual(caught.exception.completed_processes,[dict(pid=1,created=1001)])
            self.assertEqual(set(closed),{1000+pid for pid in initial})

    def test_image_query_errors_publish_held_state_without_changing_retirement_rules(self):
        from types import SimpleNamespace
        windows = small.windows
        good = lambda ids: dict(kill_on_close=True, flags=8192, pids=ids)
        for mode in ('live', 'ended-listed', 'ended-excluded'):
            error = windows.ProcessImageQueryError(5, 1)
            closed = []
            def member(handle, job, output):
                output._obj.value = 1
                return 1
            dll = SimpleNamespace(OpenProcess=lambda *args: 1001, IsProcessInJob=member,
                WaitForSingleObject=lambda *args: 258 if mode=='live' else 0,
                GetExitCodeProcess=lambda handle,out:(setattr(out._obj,'value',259 if mode=='live' else 0) or 1),
                CloseHandle=lambda handle: (closed.append(handle) or 1))
            fresh = good([1] if mode=='ended-listed' else [])
            with self.subTest(mode=mode), patch.object(windows.os, 'name', 'nt'),                     patch.object(windows, 'query_job', side_effect=[fresh, good([])]),                     patch.object(windows, '_held_birth', return_value=1001),                     patch.object(windows, '_held_identity', side_effect=error):
                if mode == 'ended-excluded':
                    self.assertEqual(windows.job_processes(7, good([1]), backend=dll), dict(census=good([]), processes=[]))
                else:
                    with self.assertRaises(windows.ProcessImageQueryError) as caught:
                        windows.job_processes(7, good([1]), backend=dll)
                    self.assertIs(caught.exception, error)
            self.assertEqual((error.api, error.pid, error.winerror), ('QueryFullProcessImageNameW', 1, 5))
            self.assertEqual(error.held_observation, dict(pid=1, birth=1001, member=True,
                previous_birth=None, wait_state=258 if mode=='live' else 0, image_error=5))
            self.assertEqual(error.fresh_census, fresh)
            self.assertEqual(error.post_census_held_observation, dict(pid=1,birth=1001,wait_state=258 if mode=='live' else 0,exit_api=True,exit_error=None,exit_code=259 if mode=='live' else 0))
            self.assertEqual(closed, [1001])

    def test_image_query_held_facts_survive_bounded_serialized_failure_trace(self):
        from types import SimpleNamespace
        error = small.windows.ProcessImageQueryError(5, 20)
        error.held_observation = dict(pid=20, birth=200, member=True, previous_birth=None, wait_state=0, image_error=5)
        error.fresh_census = dict(kill_on_close=True, flags=8192, pids=[10,20])
        error.post_census_held_observation = dict(pid=20,birth=200,wait_state=0,exit_api=True,exit_error=None,exit_code=0,extra='not copied')
        error.add_note('held observation: actual captured values')
        error.add_note('x'*5000)
        error.add_note('third note must not expand publication')
        trace = []
        with patch.object(small, 'check_inputs'),                 patch.object(small, 'module', return_value=SimpleNamespace(host_lock_path=lambda:'lock')),                 patch.object(small, 'stamp_lock', return_value=[1,2]),                 patch.object(small.windows, 'query_job', return_value=dict(pids=[10,20])),                 patch.object(small.windows, 'job_processes', side_effect=error):
            with self.assertRaises(small.windows.ProcessImageQueryError) as caught:
                small.sample_resources(dict(config={}), [], dict(lock_identity=[1,2]), 7, None, False, trace=trace)
        self.assertIs(caught.exception, error)
        path = self.root/'serialized-image-error.json'
        small.runner.write_json(path, dict(sample_trace=trace))
        row = next(v for v in json.loads(path.read_text())['sample_trace'] if v['event']=='error')
        self.assertEqual(row['pid'], 20)
        cause = row['causes'][0]
        self.assertEqual((cause['api'], cause['pid'], cause['winerror']), ('QueryFullProcessImageNameW',20,5))
        self.assertEqual(cause['held_observation'], error.held_observation)
        self.assertEqual(cause['fresh_census'], error.fresh_census)
        self.assertEqual(cause['post_census_held_observation'], {key:error.post_census_held_observation[key]
            for key in ('pid','birth','wait_state','exit_api','exit_error','exit_code')})
        self.assertEqual(len(cause['notes']), 2)
        self.assertEqual(len(cause['notes'][1]), 4096)

    def test_sampler_uses_matching_fresh_census_and_identities_and_records_unknown_retirement(self):
        from types import SimpleNamespace
        initial=dict(pids=[10,20],kill_on_close=True)
        latest=dict(pids=[10],kill_on_close=True)
        identities=[dict(pid=10,created=100,parent=1,image='owner')]
        retired=[dict(pid=20,previous_birth=None,api='OpenProcess',winerror=87,fresh_census=latest)]
        disk=SimpleNamespace(read=lambda:dict(started_ms=small.now_ms(),value=dict(capacity=[],total=123)))
        trace=[]
        endpoint=time.monotonic()+.2
        with patch.object(small,'check_inputs'), \
                patch.object(small,'module',return_value=SimpleNamespace(host_lock_path=lambda:'lock')), \
                patch.object(small,'stamp_lock',return_value=[1,2]), \
                patch.object(small.windows,'query_job',return_value=initial), \
                patch.object(small.windows,'job_processes',return_value=dict(census=latest,processes=identities,retired_snapshots=retired)) as reconcile:
            value=small.sample_resources(dict(config={}),[],dict(lock_identity=[1,2]),7,None,False,trace=trace,disk=disk,deadline=endpoint)
        reconcile.assert_called_once_with(7,initial,deadline=endpoint)
        self.assertIs(value[0],latest)
        self.assertIs(value[1],identities)
        row=next(v for v in trace if v['event']=='snapshot-retired')
        self.assertEqual(row['retired_snapshots'],retired)
        self.assertIsNone(row['retired_snapshots'][0]['previous_birth'])

    def test_hot_identity_and_job_checks_continue_during_pending_disk(self):
        from types import SimpleNamespace
        from scale_acceptance.guard import DiskObservation
        entered, release = threading.Event(), threading.Event()
        calls = []
        def disk_sample():
            calls.append(1)
            if len(calls)>1:
                entered.set()
                release.wait(2)
            return dict(capacity=[dict(path='C:/', free_bytes=200*small.GIB)], total=123)
        disk = DiskObservation(disk_sample).start()
        try:
            disk.after(0, 1)
            disk.wake.set()
            self.assertTrue(entered.wait(1))
            plan = dict(config={}, frozen=[], inventories={})
            with patch.object(small, 'check_inputs') as inputs, patch.object(small, 'stamp_lock', return_value=[1,2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])) as census:
                storage = SimpleNamespace(sample=Mock(side_effect=AssertionError('hot path must not walk disk')))
                value = small.bounded_cleanup(lambda: small.sample_resources(plan, [], dict(lock_identity=[1,2]), 123, storage, False, disk=disk))
                self.assertEqual(value[3], 123)
                inputs.assert_called_once_with(plan)
                census.assert_called_once_with(123)
                storage.sample.assert_not_called()
        finally:
            release.set()
            disk.stop(1)

    def test_physical_capacity_and_source_reservation_packet_drift_independent_of_origin(self):
        from types import SimpleNamespace
        source = self.root / 'source'
        source.write_text('source')
        pinned = self.root / 'reservation.json'
        pinned.write_text('held')
        plan = dict(config=dict(volumes=['volume']), frozen=[small.freeze(source)], inventories={})
        reservation = dict(lock_identity=[1, 2])
        storage = small.Storage([self.root])
        with patch.object(small, 'stamp_lock', return_value=[1, 2]), patch.object(small.windows, 'query_job', return_value=dict(pids=[])), patch.object(small.shutil, 'disk_usage', return_value=SimpleNamespace(free=200*small.GIB)):
            self.assertEqual(small.sample_resources(plan, [small.freeze(pinned)], reservation, 123, storage, True)[2][0]['free_bytes'], 200*small.GIB)
            with patch.object(small.shutil, 'disk_usage', return_value=SimpleNamespace(free=191*small.GIB)):
                with self.assertRaisesRegex(OSError, 'capacity'):
                    small.sample_resources(plan, [], reservation, 123, storage, True)
                small.sample_resources(plan, [], reservation, 123, storage, False)
            with patch.object(small.shutil, 'disk_usage', return_value=SimpleNamespace(free=127*small.GIB)):
                with self.assertRaisesRegex(OSError, 'capacity'):
                    small.sample_resources(plan, [], reservation, 123, storage, False)
            with patch.object(small, 'stamp_lock', return_value=[9, 9]):
                with self.assertRaisesRegex(OSError, 'reservation'):
                    small.sample_resources(plan, [], reservation, 123, storage, False)
            original = small.freeze(pinned)
            pinned.write_text('drift')
            with self.assertRaisesRegex(OSError, 'Packet/reservation'):
                small.sample_resources(plan, [original], reservation, 123, storage, False)
            source.write_text('source drift')
            with self.assertRaisesRegex(OSError, 'Source/tool'):
                small.sample_resources(plan, [], reservation, 123, storage, False)

    def test_no_progress_watchdog_uses_fixed_batch_clock_before_any_origin(self):
        from types import SimpleNamespace
        owned = self.root
        for name in ('reservation.json', 'runner-plan.json', 'source-manifest.json', 'approval.json'):
            (owned / name).write_text('{}')
        plan = dict(config=dict(history_roots=[]), packets=[], batch_started_ms=small.now_ms()-600001)
        process = SimpleNamespace(poll=lambda: None)
        with self.assertRaisesRegex(OSError, 'actual contract progress'):
            small.run_supervision(plan, owned, process, 123, {}, None, small.freeze(owned / 'approval.json'))
        plan['batch_started_ms'] = small.now_ms()-7200001
        with self.assertRaisesRegex(OSError, 'channel deadline'):
            small.run_supervision(plan, owned, process, 123, {}, None, small.freeze(owned / 'approval.json'))

    def test_execution_non_windows_and_null_configuration_denied(self):
        with self.assertRaisesRegex(OSError, 'Null'):
            small.no_nulls(dict(value=None))
        if os.name != 'nt':
            with self.assertRaisesRegex(OSError, 'native Windows'):
                small.supervise(self.root / 'missing', '0'*64)

    def test_constructor_finishes_before_live_watchdog_is_armed(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        owned = self.root / 'owned'
        plan = dict(schema='chopper-small-runner-plan-v1', config=dict(owned_root=str(owned),
                    python=str(Path(sys.executable).resolve())), reservation='startup-owner',
                    frozen=[], inventories={}, packets=[], runner_plan=dict(small_observation_owner='startup-owner'),
                    storage_method='test', batch_started_ms=small.now_ms())
        path = self.root / 'plan.json'
        small.runner.write_json(path, plan)
        lock = self.root / 'original.lock';lock.write_text('')
        events, resources = [], dict(test='initialized', disk=Mock(), inputs=Mock())
        @contextmanager
        def held():
            yield
            events.append('host-closed')
        process = SimpleNamespace(pid=123, _handle=111, returncode=None, poll=lambda: None)
        def spawn(*args, **kwargs):
            small.runner.write_json(owned/'job.json', dict(pid=123, handle=456))
            small.runner.write_json(owned/'runner-observation.json', dict(attempts=[]))
            return process
        original_need = small.need
        def need(condition, message):
            if not message.startswith('Execution requires native Windows'):
                original_need(condition, message)
        with patch.object(small, 'write_capacity'), patch.object(small, 'need', side_effect=need), patch.object(small, 'prepare', return_value=json.loads(json.dumps(plan))), \
                patch.object(small, 'module', return_value=SimpleNamespace(host_lock=held, host_lock_path=lambda: lock)), \
                patch.object(small.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(small.subprocess, 'Popen', side_effect=spawn), \
                patch.object(small.windows, 'kernel'), patch.object(small.windows, '_held_birth', return_value=77), \
                patch.object(small.windows, 'duplicate_job', return_value=789), patch.object(small.windows,'query_job',return_value=dict(kill_on_close=True,pids=[123])), patch.object(small, 'Watchdog') as watchdog:
            def constructor(*args):
                self.assertFalse(watchdog.called, 'No live watchdog while workload is blocked on ready')
                self.assertFalse((owned/'ready.json').exists())
                self.assertTrue((owned/'job-owned.json').exists(),'Fast ownership ACK precedes any initial disk wait')
                self.assertEqual(set(json.loads((owned/'job-owned.json').read_text())),
                    {'runner_pid','supervisor_pid','handle','execution_sha256'},
                    'Ownership ACK must retain the worker-validated wire schema')
                # Real filesystem setup may exceed the hot guard deadline.
                time.sleep(.85)
                self.assertFalse((owned/'ready.json').exists())
                self.assertFalse(watchdog.called)
                events.append('constructor')
                return resources
            def live(*args):
                self.assertEqual(events, ['constructor'])
                resources['disk'].start.assert_called_once_with()
                args_after, kwargs_after = resources['disk'].after.call_args
                self.assertEqual(len(args_after), 1)
                self.assertGreater(kwargs_after['timeout'], 0)
                self.assertLess(kwargs_after['timeout'], 29.2)
                resources['inputs'].initial.assert_called_once_with()
                watchdog.return_value.thread.start.assert_called_once_with()
                self.assertIs(args[-1], resources)
                self.assertEqual(args[4]['worker_birth'],77)
                self.assertFalse((owned/'ready.json').exists())
                events.append('full-initial-sample')
            def finish(plan, owned, process, job, reservation, *args):
                reservation['release_safe'] = True
                return []
            with patch.object(small, 'resource_state', side_effect=constructor), \
                    patch.object(small, 'run_supervision', side_effect=live), patch.object(small, 'finish_supervision', side_effect=finish):
                self.assertEqual(small.supervise(path, small.runner.digest(path)), 0)
        self.assertEqual(events, ['constructor', 'full-initial-sample', 'host-closed'])
        self.assertTrue(json.loads((owned/'reservation-released.json').read_text())['released_after_supervision'])

    def test_parent_setup_io_close_failure_latches_original_retention(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        for secondary in (False,True):
            owned=self.root/('owned-secondary' if secondary else 'owned-primary')
            plan=dict(schema='chopper-small-runner-plan-v1',config=dict(owned_root=str(owned),
                python=str(Path(sys.executable).resolve())),reservation='test-owner',frozen=[],inventories={},
                packets=[],runner_plan=dict(small_observation_owner='test-owner'),storage_method='test',batch_started_ms=small.now_ms())
            path=self.root/('plan-secondary.json' if secondary else 'plan-primary.json');small.runner.write_json(path,plan)
            lock=self.root/'original.lock';lock.write_text('')
            @contextmanager
            def held():yield  # fake descriptor only; no actual Original in this unit control
            process=SimpleNamespace(pid=123,_handle=111,returncode=91,poll=lambda:91,wait=lambda timeout:91)
            def spawn(*args,**kwargs):
                small.runner.write_json(owned/'job.json',dict(pid=123,handle=456))
                small.runner.write_json(owned/'runner-observation.json',dict(attempts=[]))
                return process
            original_need,real_finish=small.need,small.finish_supervision
            def need(condition,message):
                if not message.startswith('Execution requires native Windows'):original_need(condition,message)
            error=small.windows.ControlFileCloseError('close',owned/'guard.json',2**40,6,'uncertain')
            primary=OSError('primary setup failure') if secondary else error
            if secondary:primary.api='primary-setup'
            observed=[]
            def finish(plan,owned,process,job,reservation,*args):
                self.assertTrue(reservation['process_handle_close_uncertain'])
                if secondary:
                    self.assertEqual(reservation['failure_causes'][0]['api'],'primary-setup')
                    self.assertEqual(reservation['retention_failure_causes'][0]['handle'],2**40)
                else:self.assertEqual(reservation['failure_causes'][0]['handle'],2**40)
                with patch.object(small.windows,'query_job',return_value=dict(pids=[])):
                    errors=real_finish(plan,owned,process,job,reservation,None,None,str(error))
                self.assertFalse(reservation['release_safe'],'Empty Job/reaped worker cannot waive parent handle uncertainty')
                observed.append(errors)
                reservation['release_safe']=True  # exit the intentional retain loop with this fake-only host context
                return errors
            with patch.object(small,'need',side_effect=need),patch.object(small,'write_capacity'), \
                 patch.object(small,'prepare',return_value=json.loads(json.dumps(plan))), \
                 patch.object(small,'module',return_value=SimpleNamespace(host_lock=held,host_lock_path=lambda:lock)), \
                 patch.object(small.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(small.subprocess,'Popen',side_effect=spawn), \
                 patch.object(small.windows,'kernel'),patch.object(small.windows,'_held_birth',return_value=77), \
                 patch.object(small.windows,'duplicate_job',return_value=789), \
                 patch.object(small.windows,'query_job',return_value=dict(kill_on_close=True,pids=[123])), \
                 patch.object(small.windows,'terminate'),patch.object(small.windows,'close'), \
                 patch.object(small,'resource_state',side_effect=primary),patch.object(small,'finish_supervision',side_effect=finish), \
                 patch.object(small,'write_control_json',side_effect=error if secondary else small.write_control_json):
                self.assertEqual(small.supervise(path,small.runner.digest(path)),1)
            self.assertEqual(observed,[['Parent handle close unproven']])


    def test_constructor_failure_cleanup_needs_no_watchdog_and_retains_pending_calls(self):
        from types import SimpleNamespace
        for blocked in (False, True):
            release = threading.Event()
            if blocked:
                small.operation(lambda: release.wait())
            reservation = {}
            process = SimpleNamespace(returncode=91, poll=lambda: 91, wait=lambda timeout: 91)
            try:
                with self.subTest(blocked=blocked), patch.object(small.windows, 'terminate') as stop, \
                        patch.object(small.windows, 'query_job', return_value=dict(pids=[])), \
                        patch.object(small.windows, 'close') as close:
                    errors = small.finish_supervision(dict(storage_method='test'), self.root, process, 123,
                                                     reservation, None, None, 'constructor failed')
                    stop.assert_called_once_with(123)
                    self.assertEqual(reservation['release_safe'], not blocked)
                    if blocked:
                        close.assert_not_called()
                    else:
                        close.assert_called_once_with(123)
                        self.assertEqual(errors, [])
                    self.assertFalse((self.root/'ready.json').exists())
                    self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])
            finally:
                release.set()
                for thread in small.OPERATIONS:
                    thread.join(1)

    def cleanup_fixture(self):
        from types import SimpleNamespace
        events, done = [], threading.Event()
        def pulse():
            self.assertFalse(done.is_set(), 'watchdog stopped before cleanup completed')
            events.append('pulse')
        watchdog = SimpleNamespace(done=done, error=None, pulse=pulse,
            thread=SimpleNamespace(join=lambda timeout: events.append('join'), is_alive=lambda: False))
        process = SimpleNamespace(returncode=0, poll=lambda: 0,
            wait=lambda timeout: events.append('reap'))
        resources = dict(storage=small.Storage([self.root]), pinned=[], last_progress_ms=small.now_ms())
        plan = dict(batch_started_ms=small.now_ms(), storage_method='fake sampled high-water')
        return events, watchdog, process, resources, plan

    def test_cleanup_guards_through_reap_and_final_metadata_and_retains_ledger(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        def sample(*args, **kwargs):
            self.assertFalse(watchdog.done.is_set())
            self.assertFalse(kwargs['processes'])
            events.append('final-sample' if (self.root/'result.json').exists() else 'sample')
            return dict(pids=[]), [], [], resources['storage'].sample()
        def terminate(job):
            self.assertFalse(watchdog.done.is_set())
            events.append('terminate')
        def close(job):
            self.assertFalse(watchdog.done.is_set())
            self.assertEqual(process.returncode, 0)
            events.append('close')
        with patch.object(small, 'sample_resources', side_effect=sample), patch.object(small.windows, 'terminate', side_effect=terminate), patch.object(small.windows, 'close', side_effect=close):
            errors = small.finish_supervision(plan, self.root, process, 123, {}, watchdog, resources, None)
        self.assertEqual(errors, [])
        self.assertLess(events.index('reap'), events.index('final-sample'))
        self.assertLess(events.index('final-sample'), events.index('close'))
        self.assertLess(events.index('close'), events.index('join'))
        self.assertTrue(watchdog.done.is_set())
        self.assertTrue(json.loads((self.root/'result.json').read_text())['passed'])
        ledger = json.loads((self.root/'storage-ledger.json').read_text())
        self.assertGreaterEqual(ledger['cumulative_owned_bytes'], resources['storage'].sample())

    def test_post_write_capacity_failure_prevents_success_and_still_releases_job(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        def sample(*args, **kwargs):
            if (self.root/'result.json').exists():
                raise OSError('Final physical capacity floor')
            return dict(pids=[]), [], [], resources['storage'].sample()
        with patch.object(small, 'sample_resources', side_effect=sample), patch.object(small.windows, 'terminate'), patch.object(small.windows, 'close') as close:
            errors = small.finish_supervision(plan, self.root, process, 123, {}, watchdog, resources, None)
        self.assertTrue(any('Final physical capacity' in value for value in errors))
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])
        close.assert_called_once_with(123)

    def test_resource_denial_does_not_prevent_independent_job_quiescence_proof(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        reservation = {}
        with patch.object(small, 'sample_resources', side_effect=OSError('capacity denied')), \
             patch.object(small.windows, 'terminate'), \
             patch.object(small.windows, 'query_job', return_value=dict(pids=[])) as census, \
             patch.object(small.windows, 'close') as close:
            errors = small.finish_supervision(plan, self.root, process, 123, reservation, watchdog, resources, None)
        self.assertTrue(any('capacity denied' in value for value in errors))
        census.assert_called(); close.assert_called_once_with(123)
        self.assertTrue(reservation['release_safe'])
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])

    def test_blocked_native_cleanup_is_bounded_and_not_success(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        blocked = threading.Event()
        original = small.bounded_cleanup
        def sample(*args, **kwargs):
            return dict(pids=[]), [], [], resources['storage'].sample()
        try:
            reservation = {}
            with patch.object(small, 'sample_resources', side_effect=sample), patch.object(small.windows, 'terminate', side_effect=lambda job: blocked.wait()), patch.object(small.windows, 'close') as close, patch.object(small, 'bounded_cleanup', side_effect=lambda action: original(action, timeout=.05)):
                started = time.monotonic()
                errors = small.finish_supervision(plan, self.root, process, 123, reservation, watchdog, resources, None)
                self.assertLess(time.monotonic()-started, 1)
                close.assert_not_called()
                self.assertFalse(reservation['release_safe'])
            self.assertTrue(any('late/blocked' in value for value in errors))
            self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])
        finally:
            blocked.set()

    def test_cleanup_progress_deadline_fails_closed(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        resources['last_progress_ms'] -= 600001
        with patch.object(small.windows, 'terminate'), patch.object(small.windows, 'close'):
            errors = small.finish_supervision(plan, self.root, process, 123, {}, watchdog, resources, None)
        self.assertTrue(any('progress deadline' in value for value in errors))
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])

    def test_final_metadata_allowance_must_fit_remaining_owned_capacity(self):
        events, watchdog, process, resources, plan = self.cleanup_fixture()
        resources['storage'].total = small.LIMITS['owned_bytes']-1000
        def sample(*args, **kwargs):
            return dict(pids=[]), [], [], resources['storage'].total
        with patch.object(small, 'sample_resources', side_effect=sample), patch.object(small.windows, 'terminate'), patch.object(small.windows, 'close'):
            errors = small.finish_supervision(plan, self.root, process, 123, {}, watchdog, resources, None)
        self.assertTrue(any('Final metadata storage ceiling' in value for value in errors))
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])


def native_transfer_probe(root):
    """Actual cross-process handle transfer and reap; no browser/product code."""
    script = root / 'transfer-worker.py'
    script.write_text("""import importlib.util,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('small',Path(%r))
small=importlib.util.module_from_spec(spec);spec.loader.exec_module(small)
root=Path(%r)
small.runner.contain_session()
session=small.runner.owned_windows_job()
small.runner.write_json(root/'transfer-job.json',dict(pid=os.getpid(),**session))
deadline=time.monotonic()+5
while not (root/'transfer-ack.json').exists():
    small.need(time.monotonic()<deadline,'Transfer acknowledgement timeout')
    time.sleep(.025)
small.windows.close(session['handle'])
small.runner.write_json(root/'transfer-closed.json',dict(pid=os.getpid()))
while True:time.sleep(.1)
""" % (str(small.HERE / 'browser-small-runner.py'), str(root)))
    duplicate = None
    with (root/'transfer-stdout.log').open('wb') as out, (root/'transfer-stderr.log').open('wb') as err:
        child = subprocess.Popen([sys.executable, '-B', str(script)], stdout=out, stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+5
            while not (root/'transfer-job.json').exists():
                small.need(child.poll() is None and time.monotonic()<deadline, 'Transfer Job startup timeout/failure')
                time.sleep(.025)
            session = json.loads((root/'transfer-job.json').read_text())
            small.need(session['pid'] == child.pid, 'Transfer child identity mismatch')
            duplicate = small.windows.duplicate_job(child.pid, session['handle'])
            census = small.windows.query_job(duplicate)
            small.need(census['kill_on_close'] and child.pid in census['pids'], 'Actual transferred Job proof')
            small.runner.write_json(root/'transfer-ack.json', dict(pid=child.pid))
            deadline = time.monotonic()+5
            while not (root/'transfer-closed.json').exists():
                small.need(child.poll() is None and time.monotonic()<deadline, 'Original Job handle release timeout/failure')
                time.sleep(.025)
            small.windows.terminate(duplicate)
            child.wait(timeout=5)
            small.need(not small.windows.query_job(duplicate)['pids'], 'Transferred Job not empty')
            small.runner.write_json(root/'transfer-result.json', dict(passed=True, child_pid=child.pid,
                actual_job_flags=census['flags'], original_handle_released=True, final_pids=[]))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            if duplicate is not None:
                small.windows.close(duplicate)


def native_probe(directory):
    """Safe native Job/bootstrap integration only. No browser/product imported."""
    small.need(os.name == 'nt', 'Native Windows probe only')
    node = str(Path(shutil.which('node')).resolve())
    root = Path(directory).resolve()
    small.need(not root.exists(), 'Fresh retained probe directory required')
    root.mkdir()
    with small.module('local-ci').host_lock():
        small.runner.contain_session()
        native_transfer_probe(root)
        plan_path = root / 'plan.json'
        source = root / 'fake.mjs'
        source.write_text("import {handshake} from " + json.dumps((small.HERE / 'browser-small-bootstrap.mjs').as_uri()) + ";\n" +
            "import {readFile} from 'node:fs/promises';\nconst p=JSON.parse(await readFile(process.argv[2])); await handshake(p); console.log('OWN_PID_HANDSHAKE_OK');\n")
        packet = dict(reservation='native-fake-probe', batch_started_ms=small.now_ms(), limits=small.LIMITS,
                      volumes=[str(root.anchor)], guard=str(root / 'guard.json'))
        small.runner.write_json(root / 'packet.json', packet)
        plan = dict(root=str(root), batch_timeout_seconds=15, estimated_seconds=5, estimated_disk_bytes=1048576,
                    toolchains=dict(node=node), features=[], fixtures=['safe Node fake; no browser'], steps=[dict(
                    id='native-probe', argv=[node, str(source), str(root / 'packet.json')], timeout_seconds=10,
                    inputs=['fake.mjs', 'packet.json'], artifacts=[])])
        small.runner.write_json(plan_path, plan)
        runner_birth = small.windows._held_birth(small.windows.kernel(), small.windows.kernel().GetCurrentProcess(), os.getpid())
        def guard():
            census = small.runner.owned_windows_job()
            identities = [small.windows.process_identity(pid) for pid in census['pids']]
            child = small.census_child(census, identities, os.getpid(), node, runner_birth=runner_birth)
            small.runner.write_json(root / 'guard.json', dict(schema='chopper-small-contract-guard-v1', allowed=True,
                sampled_ms=small.now_ms(), last_progress_ms=packet['batch_started_ms'], runner_pid=os.getpid(),
                child_pid=child['pid'] if child else None, owned_pids=census['pids'], reservation=packet['reservation'],
                reservation_held=True, windows_job_kill_on_close=census['kill_on_close'], batch_started_ms=packet['batch_started_ms'],
                cumulative_owned_bytes=0, volumes=[dict(path=str(root.anchor), free_bytes=200*small.GIB)]))
        code = small.runner.run(plan_path, root / 'batch', guard=guard)
        print((root / 'batch/1-stdout.log').read_text())
        small.need(code == 0, 'Native fake probe failed')


class NativeCancelBoundaryControl(unittest.TestCase):
    def test_interrupts_only_initial_ready_after_real_guard_evidence(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owned, output = root / 'owned', root / 'control'
            plan = root / 'plan.json'
            plan.write_text(json.dumps(dict(config=dict(owned_root=str(owned), commands=small.command_specs(first_only=True)))))
            def qualify(*args, **kwargs):
                owned.mkdir()
                small.runner.write_json(owned / 'guard.json', dict(allowed=True, reservation_held=True,
                    windows_job_kill_on_close=True, owned_pids=[123]))
                (owned / 'guard-history.jsonl').write_text('{}\n')
                with self.assertRaisesRegex(KeyboardInterrupt, 'controlled initial-ready cancellation'):
                    small.runner.write_json(owned / 'ready.json', dict(runner_pid=123))
                small.runner.write_json(owned / 'cleanup.json', dict(errors=[], worker_returncode=91))
                small.runner.write_json(owned / 'reservation-released.json', dict(released_after_supervision=True, passed=False))
                small.runner.write_json(owned / 'result.json', dict(passed=False, error='controlled initial-ready cancellation'))
                return 1
            with patch.object(sys.modules[__name__], 'os', SimpleNamespace(name='nt')), \
                 patch.object(small, 'qualify', side_effect=qualify), \
                 patch.object(small.windows, 'process_identity', return_value=dict(pid=123, created=456)):
                self.assertEqual(native_cancel_control(plan, '0'*64, root/'config', root/'pref', '1'*64, output), 0)
            self.assertFalse((owned / 'ready.json').exists())
            self.assertEqual(json.loads((owned / 'cancel-injected.json').read_text())['worker']['created'], 456)
            self.assertFalse(json.loads((output/'result.json').read_text())['qualification'])


def native_cancel_control(plan_path, approval, config_path, preflight_path, preflight_sha, output):
    """Real initial-readiness interruption; no browser-work cancellation claim."""
    small.need(os.name == 'nt', 'Native Windows required')
    plan_path, config_path, output = Path(plan_path), Path(config_path), Path(output)
    plan = json.loads(plan_path.read_text())
    owned = Path(plan['config']['owned_root'])
    small.need(not output.exists() and not owned.exists(), 'Fresh control outputs required')
    small.need(plan['config']['commands'] == small.command_specs(first_only=True), 'First-command plan required')
    output.mkdir()
    write = small.runner.write_json
    injected = []
    def interrupt_ready(path, value, **kwargs):
        if Path(path) == owned / 'ready.json':
            small.need(not injected, 'Exactly one initial-ready interruption')
            guard = json.loads((owned / 'guard.json').read_text())
            small.need(guard['allowed'] and guard['reservation_held'] and guard['windows_job_kill_on_close'], 'Real full guard required')
            small.need((owned / 'guard-history.jsonl').stat().st_size > 0, 'Completed guard history required')
            worker = small.windows.process_identity(value['runner_pid'])
            small.need(guard['owned_pids'] == [worker['pid']], 'Waiting worker only; no Node/browser')
            marker = dict(boundary='initial-ready-before-publication', worker=worker, guard=guard,
                          qualification=False, browser_work_started=False)
            write(owned / 'cancel-injected.json', marker)
            injected.append(marker)
            raise KeyboardInterrupt('controlled initial-ready cancellation')
        return write(path, value, **kwargs)
    with patch.object(small.runner, 'write_json', side_effect=interrupt_ready):
        code = small.qualify(plan_path, approval, config_path,
            dict(path=str(preflight_path), sha256=preflight_sha), first_command_control=True)
    cleanup = json.loads((owned / 'cleanup.json').read_text())
    released = json.loads((owned / 'reservation-released.json').read_text())
    result = json.loads((owned / 'result.json').read_text())
    small.need(code == 1 and len(injected) == 1 and not result['passed'], 'Expected controlled failure required')
    small.need(result['error'] == 'controlled initial-ready cancellation', 'Exact cancellation cause required')
    small.need(not cleanup['errors'] and released['released_after_supervision'] and not released['passed'], 'Normal failed cleanup/release required')
    small.need(not (owned / 'ready.json').exists() and not (owned / 'owner-retained.json').exists(), 'No readiness or retained owner')
    write(output / 'result.json', dict(status='passed', qualification=False, scope='initial-ready supervisor cancellation before Node/browser',
        injected=injected[0], controller=result, cleanup=cleanup, release=released))
    return 0


def node_control_writer(body):
    """Use the exact owning Node publication function, without launching its browser."""
    start = '  const atomic = async (name, value) => {'
    end = '  let context, browser, page, server, watcher, stopping = false;'
    small.need(body.count(start) == 1 and body.find(end, body.index(start)) >= 0, 'Exact Node atomic boundary required')
    atomic = body[body.index(start):body.index(end, body.index(start))]
    return ("import {writeFile, rename} from 'node:fs/promises';\n"
            "import {join} from 'node:path';\nconst work = process.argv[2];\n" + atomic +
            "try { await atomic(process.argv[3], JSON.parse(process.argv[4])); console.log(JSON.stringify({passed:true})); }\n"
            "catch (e) { console.log(JSON.stringify({passed:false,code:e.code,errno:e.errno,syscall:e.syscall})); }\n")


@contextmanager
def component_original(ci, budget):
    # Canonical lock acquisition is a fixed, reserved ownership operation outside
    # the component output tree. Restore the body audit before yielding work.
    budget.check()
    active=budget.active
    budget.active=False
    try:
        with ci.host_lock():
            budget.active=active
            budget.check()
            yield
    finally:
        budget.active=active


def browser_scale_control_modules(definition):
    modules={}
    for key,name in (('guard','scale_acceptance.guard'),('watchdog','scale_acceptance.browser_scale_watchdog'),
                     ('runner','bscale_control_runner'),('controller','scale_acceptance.browser_scale_guard_control'),
                     ('observer','scale_acceptance.hosted_qualification_control')):
        row=definition[key]
        small.need(small.runner.digest(Path(row['path']))==row['sha256'],'Selected component module SHA: '+key)
        source=importlib.util.spec_from_file_location(name,row['path'])
        value=importlib.util.module_from_spec(source);sys.modules[name]=value;source.loader.exec_module(value)
        modules[key]=value
    return modules


def native_browser_scale_control(controller_path, controller_sha, source_map, source_sha, directory, *, after=False, capacity_only=False):
    """Real append I/O and Original lifecycle helpers; never a profile qualification."""
    import hashlib
    import shutil
    from types import SimpleNamespace
    small.need(os.name=='nt','Native Windows component required')
    definition=control_sources
    capacity_only=capacity_only or definition.get('capacity_only',False)
    body_seconds=60 if capacity_only and not after else 30
    output_limit=128*1024**2 if capacity_only and not after else 1024**2
    if after:small.need(controller_path==definition['result_path'],'Selected primary result path')
    else:small.need(definition['controller']==dict(path=controller_path,sha256=controller_sha),'Selected controller binding')
    root=Path(directory);small.need(not root.exists(),'Fresh component root required')
    small.need(root.is_absolute() and root.drive.upper()=='C:' and '..' not in root.parts,'Native C component output')
    small.need(shutil.disk_usage('C:/').free-output_limit>=128*small.GIB,'Physical C floor')
    loaded=browser_scale_control_modules(definition)
    small.need(loaded['observer'].host()==definition['host'],'Actual component host binding')
    core,base,runner=loaded['controller'],loaded['guard'],loaded['runner']
    ci=core.module('local-ci');windows=small.windows
    runner.contain_session();job=runner._SESSION_JOB
    small.need(windows.query_job(job)['pids']==[os.getpid()],'Initial owner-only Job')
    root.mkdir()
    checker=small.module('acceptance-preflight')
    limit=128*1024**2 if after else 2*1024**3 if capacity_only else 320*1024**2
    budget=checker.Budget(dict(seconds=body_seconds,read_bytes=limit,visits=200000,capture_bytes=65536,storage_bytes=output_limit),root)
    if not after:budget.read_bytes=64*1024**2  # conservative ownership-cleanup reserve
    null=open(os.devnull,'rb');expired=threading.Event()
    timer=threading.Timer(body_seconds,expired.set);timer.daemon=True;timer.start()
    report=dict(status='failed',qualification=False,scale_slots=0,scope='capacity-only real browser; no CSV or Run' if capacity_only else 'append/Original helper component; no browser/product',
        observer=dict(pid=os.getpid(),created=windows._held_birth(windows.kernel(),windows.kernel().GetCurrentProcess(),os.getpid())))
    budget.install()
    try:
        frozen=[]
        rows={row['path']:row for row in definition['code']+[definition['python']]+definition['runtime']+
              (definition['capacity_runtime'] if capacity_only and not after else [])
              if not after or row['path']!=definition['node']['path']}
        for row in rows.values():
            item=small.freeze(row['path']);small.need(item['sha256']==row['sha256'],'Runtime/source pin')
            frozen.append(item);budget.check()
        if after:
            value=loaded['observer'].bound_json(dict(path=definition['result_path'],sha256=controller_sha))
            small.need(value['released_after_supervision'] and
                value['original_lock_identity']==definition['original_lock_identity'] and value.get('phases') and all(
                phase['released_after_supervision'] and phase['cleanup']['original_release_safe'] for phase in value['phases']),
                'Positive primary cleanup/release required')
            report.update(primary_status=value['status'],primary_sha256=controller_sha)
            facts=loaded['observer'].current_process_facts([dict(process_identities=[value['observer'],
                *(row for phase in value['phases'] for row in phase['cleanup']['processes'])])])
            small.need(facts and all(row['created'] for row in facts),'Explicit current component births required')
            loaded['observer'].independent_observation(windows,facts,value,ci.host_lock_path(),budget.started+30,report,budget=budget)
            report['status']='passed-after-exit'
        else:
            if capacity_only:
                script=Path(definition['node_driver']['path'])
                capacity_definition=root/'capacity-definition.json'
                capacity_definition.write_bytes(Path(source_map).read_bytes())
                small.need(small.runner.digest(capacity_definition)==source_sha,'Copied capacity definition binding')
                frozen.append(small.freeze(capacity_definition))
            else:
                node_source=Path(definition['node_driver']['path']).read_text(encoding='utf-8')
                start='export function observationPublisher(work) {';end='export async function streamIdentity(path) {'
                small.need(node_source.count(start)==node_source.count(end)==1,'Exact owning publisher boundary')
                factory=node_source[node_source.index(start):node_source.index(end)]
                script=root/'node-writer.mjs'
                script.write_text("import assert from 'node:assert/strict';\nimport {writeFile,rename,appendFile,lstat} from 'node:fs/promises';\nimport {constants} from 'node:fs';\nimport {join} from 'node:path';\n"+factory+
                    "const work=process.argv[2],publish=observationPublisher(work);await publish('quota',{epoch:0});\n"
                    "await writeFile(join(work,'ready'),'ready',{flag:'wx'});const end=Date.now()+20000;\n"
                    "while(!await lstat(join(work,'go')).then(()=>true,e=>{if(e.code!=='ENOENT')throw e;return false;})){assert(Date.now()<end);await new Promise(r=>setTimeout(r,1));}\n"
                    "for(let epoch=1;epoch<=32;epoch++){await publish('quota',{epoch});await publish('progress',{epoch});await new Promise(r=>setTimeout(r,1));}\n"
                    "await publish.stop();console.log(JSON.stringify({passed:true,quota_publications:33,progress_publications:32}));\n",encoding='utf-8')
                frozen.append(small.freeze(script))
            report['phases']=[]
            storage=small.Storage([root])
            for negative in ((False,) if capacity_only else (True,False)):
                case=root/('no-worker' if negative else 'normal');case.mkdir()
                ownership=dict(processes=[],runner_active=False,launch_pending=False,handle_uncertain=False)
                disk=None
                def capacity():
                    return dict(owned=storage.sample(mutable_roots=[root],immutable_paths=[script],deadline=disk.started+disk.seconds),
                                free=[shutil.disk_usage('C:/').free])
                disk=base.DiskObservation(capacity)
                policy=dict(version=1,owned_bytes=1 if negative else output_limit,start_free_bytes=128*small.GIB,
                    stop_free_bytes=128*small.GIB,deadline_seconds=body_seconds,no_progress_seconds=600,sample_seconds=1,
                    owned_roots=[str(root)],volumes=['C:/'],progress_paths=[str(root/'progress.jsonl')])
                controls=[];stop_end=[None]
                def stop_owned():
                    if stop_end[0] is None:stop_end[0]=time.monotonic()+10
                    return windows.stop_descendants(job,os.getpid(),stop_end[0])
                def hot():
                    budget.check();small.check_inputs(dict(frozen=frozen,inventories=definition['runtime_directories']))
                    census=windows.query_job(job);small.need(census['kill_on_close'] and os.getpid()in census['pids'],'Owned complete Job')
                    if not controls:controls.append(base.Guard(policy,case/'capacity.jsonl',disk=disk))
                    else:controls[0]()
                watch=loaded['watchdog'].Watchdog(hot,case/'watch-failure.json',terminate=stop_owned)
                snapshot=None;initial=b'';quota_state=None;values=[];reader_errors=[]
                phase=dict(expected_denial=negative);phase_error=None
                stamp=None;original=dict(path=str(ci.host_lock_path()))
                budget.check()
                phase_entered=phase_released=False
                try:
                    with component_original(ci,budget):
                        phase_entered=True
                        try:
                            stamp=ci.host_lock_path().stat();original.update(device=stamp.st_dev,inode=stamp.st_ino)
                            small.need([stamp.st_dev,stamp.st_ino]==definition['original_lock_identity'],'Same original inode required')
                            marker=time.monotonic();disk.start();disk.after(marker);watch.start()
                            small.need(watch.initial.wait(5),'Initial complete guard did not pass');watch.check()
                            def observe_quota():
                                nonlocal quota_state
                                if snapshot is None:return
                                value,quota_state=core.read_quota_journal(root/'quota.jsonl',quota_state)
                                small.need(type(value['epoch'])is int and 0<=value['epoch']<=32,'Actual bounded epoch')
                                if not values or values[-1]!=value['epoch']:values.append(value['epoch'])
                                small.need(len(values)<=33 and values==sorted(values),'Monotonic complete observations')
                            def capture(process):
                                nonlocal snapshot,initial
                                core.capture_process(process,ownership,windows)
                                if process is None or capacity_only:return
                                while not (root/'ready').exists():
                                    budget.check();watch.check();time.sleep(.005)
                                snapshot=(root/'quota.jsonl').open('rb')
                                initial=snapshot.read(1024**2+1)
                                small.need(len(initial)<=1024**2 and json.loads(initial)==dict(epoch=0),'Initial complete snapshot')
                                observe_quota()
                                (root/'go').write_bytes(b'go')
                            def guard():watch.check();observe_quota()
                            argv=[definition['node']['path'],str(script),*(['--capacity-control',str(capacity_definition),source_sha] if capacity_only else [str(root)])]
                            plan=case/'plan.json';runner.write_json(plan,dict(root=str(root),batch_timeout_seconds=body_seconds,
                                estimated_seconds=1,estimated_disk_bytes=output_limit,toolchains={'node':definition['node']['sha256']},features=[],fixtures=[],
                                steps=[dict(id='node-append',argv=argv,inputs=['capacity-definition.json'] if capacity_only else [script.name],artifacts=['capacity-observation.json'] if capacity_only else ['quota.jsonl','progress.jsonl'],depends=[],timeout_seconds=body_seconds)]))
                            command=budget.command_key([str(Path(argv[0]).resolve()),*argv[1:]])
                            budget.allowed_commands.add(command)
                            ownership['runner_active']=True
                            try:
                                phase['code']=runner.run(plan,case/'batch',guard=guard,on_process=capture)
                                observe_quota()
                            finally:
                                ownership['runner_active']=False
                                budget.allowed_commands.discard(command)
                        except BaseException as error:phase_error=error;phase['error']=repr(error)
                        finally:
                            if snapshot is not None:
                                try:
                                    snapshot.seek(0)
                                    small.need(snapshot.read(len(initial))==initial,'Held initial prefix changed')
                                except BaseException as error:reader_errors.append(repr(error))
                                finally:
                                    try:snapshot.close()
                                    except BaseException as error:
                                        ownership['handle_uncertain']=True;reader_errors.append(repr(error))
                            timer.cancel();timer.join(timeout=1)
                            if timer.is_alive():ownership['handle_uncertain']=True
                            # Body exhaustion cannot block mandatory ownership cleanup.
                            # The fixed reserve above covers this <=1MiB tree/receipts;
                            # pending calls retain Original rather than being killed.
                            budget.active=False
                            try:
                                cleanup=core.finish_scale(ownership,windows,job,watch,disk,controls,stop_owned)
                                core.record_cleanup(runner,case,cleanup,ownership,original,ci.host_lock_path(),stamp,
                                    windows._held_birth(windows.kernel(),windows.kernel().GetCurrentProcess(),os.getpid()))
                            except BaseException as error:
                                for close in (watch.stop,disk.stop):
                                    try:close()
                                    except BaseException:pass
                                core.retain_original(runner,case,dict(pid=os.getpid(),error=repr(error)))
                    phase_released=True
                except BaseException as error:
                    if phase_entered and not phase_released:
                        core.retain_original(runner,case,dict(pid=os.getpid(),error=repr(error),original_close_unproved=True))
                    raise
                budget.active=True
                phase.update(released_after_supervision=True,cleanup=cleanup,reader_errors=reader_errors)
                phase['original_lock_identity']=[stamp.st_dev,stamp.st_ino]
                report['phases'].append(phase)
                report.update(released_after_supervision=True,original_lock_identity=[stamp.st_dev,stamp.st_ino])
                if negative:small.need(watch.failure and 'owned-tree capacity'in watch.failure and not ownership['processes'],'Real no-worker guard rejection required')
                elif capacity_only:
                    small.need(phase_error is None and phase.get('code')==0,'Actual capacity command terminal')
                    observed=json.loads((root/'capacity-observation.json').read_bytes())
                    small.need(observed['status']=='observed-capacity' and observed['cleanup_complete'] and not observed['failures'],'Real capacity observation/cleanup')
                    report['capacity_observation']=observed
                else:small.need(phase_error is None and phase.get('code')==0 and not reader_errors and values[-1:]==[32]
                               and values==sorted(values),'Actual append/reader result')
            report.update(status='passed',released_after_supervision=True,original_lock_identity=[stamp.st_dev,stamp.st_ino],
                observer=windows.process_identity(os.getpid()),epochs=values,
                owned_sampled_high_bytes=storage.total,final_metadata_allowance_bytes=65536,
                unseen_allocations='UNKNOWN; sampled logical charges are not a physical peak or every transient write')
    except BaseException as error:report['error']=repr(error)
    finally:
        budget.active=False
        try:null.close()
        except BaseException as error:report.update(status='failed-cleanup',null_close_error=repr(error))
        timer.cancel();timer.join()
        report['timer_joined']=not timer.is_alive();report['usage']=budget.usage()
        small.need(len((json.dumps(report)+'\n').encode())<=65536,'Component result memory/capture bound')
        small.need(small.Storage([root]).sample()+65536<=output_limit,'Component output allowance')
        small.runner.write_json(root/'result.json',report)
    return 0 if report['status'] in ('passed','passed-after-exit') and report['timer_joined'] else 1


def native_control_io_stress(windows_path, windows_sha, writer_path, writer_sha, directory,
                             node_definition=None, node_definition_sha=None):
    """Real owned-reader/publication overlap using the production I/O helpers."""
    small.need(os.name == 'nt', 'Native Windows required')
    import hashlib
    from types import SimpleNamespace
    modules = []
    for name, path, expected in (('_control_io', windows_path, windows_sha), ('_control_writer', writer_path, writer_sha)):
        path = Path(path)
        small.need(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Exact control implementation SHA256')
        source = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(source)
        sys.modules[name] = value
        source.loader.exec_module(value)
        modules.append(value)
    io, writer = modules
    root = Path(directory).resolve()
    small.need(not root.exists(), 'Fresh control stress required')
    small.need(root.drive.upper() == 'C:' and small.shutil.disk_usage(root.parent).free-1024**2 >= 128*small.GIB,
               'Fresh physical C capacity floor')
    small.runner.contain_session()
    io._control_api()  # bind the selected native_file FFI before starting the reader
    checker = small.module('acceptance-preflight')
    root.mkdir()
    budget = checker.Budget(dict(seconds=30,read_bytes=128*1024**2,visits=200000,capture_bytes=65536,storage_bytes=1024**2),root)
    node = script = None
    null_input = open(os.devnull, 'rb') if node_definition else None
    timer = threading.Timer(30,lambda:os._exit(97));timer.daemon=True;timer.start()
    budget.install()
    path = root/'guard.json'
    opened, release = threading.Event(), threading.Event()
    values, errors, held = [], [], []
    original_os = io.os
    observed_os = SimpleNamespace(**vars(original_os))
    def held_read(fd, size):
        if threading.current_thread() is reader:
            held.append(dict(inode=original_os.fstat(fd).st_ino, links_before=original_os.fstat(fd).st_nlink))
            opened.set()
            remaining = max(.001,30-(time.monotonic()-budget.started)) if node else 5
            small.need(release.wait(remaining), 'Owned reader release timed out')
            held[-1]['links_after'] = original_os.fstat(fd).st_nlink
        return original_os.read(fd,size)
    observed_os.read = held_read
    io.os = observed_os
    def read():
        try:values.append(json.loads(io.read_control_snapshot(path,8192)))
        except BaseException as error:errors.append(error)
    reader = threading.Thread(target=read,daemon=True)
    initial = dict(epoch=0,data='x'*4096)
    report = dict(qualification=False,original_acquired=False,scope='real production mutable-control I/O overlap; no child/product')
    def node_publish(target, value, name):
        argv = [node,str(script),str(root),target.name,json.dumps(value)]
        output = root/(name+'.log')
        budget.allowed_commands.add(budget.command_key(argv))
        try:
            with output.open('wb') as capture:
                done = subprocess.run(argv,stdin=null_input,stdout=capture,stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,timeout=max(.001,min(5,30-(time.monotonic()-budget.started))))
            small.need(done.returncode==0 and output.stat().st_size<=8192,'Node writer terminal/capture')
            return json.loads(output.read_bytes())
        finally:
            budget.allowed_commands.discard(budget.command_key(argv))
    try:
        if node_definition:
            with Path(node_definition).open('rb') as source:raw=source.read(65537)
            small.need(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==node_definition_sha, 'Node control definition SHA')
            definition=json.loads(raw)
            for key in ('node','driver'):
                row=definition[key]
                checker_path=Path(row['path'])
                small.need(checker_path.is_absolute() and all(not p.is_symlink() and not p.is_junction()
                    for p in (checker_path,*checker_path.parents)), 'Node control source alias')
                before=checker_path.stat()
                with checker_path.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
                after=checker_path.stat()
                small.need(actual==row['sha256'] and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns), 'Node control source pin: '+key)
            node=definition['node']['path']
            with Path(definition['driver']['path']).open('rb') as source:body=source.read(1024**2+1)
            small.need(len(body)<=1024**2, 'Node driver source bound')
            script=root/'node-writer.mjs'
            script.write_text(node_control_writer(body.decode('utf-8')),encoding='utf-8')
        writer.write_json(path,initial,replace=io.replace_control_snapshot)
        if node:
            ordinary = root/'ordinary.json'
            writer.write_json(ordinary,initial)
            with ordinary.open('rb') as snapshot:
                report['ordinary_node_publication'] = node_publish(ordinary,dict(epoch=1),'ordinary-node')
                small.need(json.loads(snapshot.read())==initial,'Ordinary held snapshot coherence')
            report['scope']='Exact BrowserScale Node atomic writer/canonical snapshot reader; no Original/browser/product'
        alias = root/'hardlink.json'
        os.link(path,alias)
        alias_identity = (alias.lstat().st_dev, alias.lstat().st_ino)
        hardlink_denials, verified_alias = [], False
        try:
            for action in (lambda:io.read_control_snapshot(path,8192),
                           lambda:writer.write_json(path,dict(epoch=-1),replace=io.replace_control_snapshot)):
                try:action()
                except io.ControlFileError as error:
                    if error.api != 'metadata' or getattr(error,'process_handle_close_uncertain',False):raise
                    hardlink_denials.append(dict(api=error.api,path=error.path))
            small.need(len(hardlink_denials)==2 and alias.stat().st_ino==path.stat().st_ino
                       and path.stat().st_nlink==2,'Real hardlink read/publication denials required')
            verified_alias = True
        finally:
            if verified_alias:
                small.need((alias.lstat().st_dev,alias.lstat().st_ino)==alias_identity and not alias.is_symlink(),
                           'Negative fixture alias identity changed')
                alias.unlink()  # only this new, verified owned negative fixture alias
        report['hardlink_denials'] = hardlink_denials
        budget.read_bytes += 2*8193  # both native FD snapshots bypass Python's open audit
        budget.check()
        reader.start()
        small.need(opened.wait(5), 'Actual reader did not reach held ReadFile boundary')
        published_epoch=0
        for epoch in range(1,33):
            value = dict(epoch=epoch,data=initial['data'])
            if node:
                publication=node_publish(path,value,'node-'+str(epoch))
                report['last_node_publication']=publication
                if publication.get('passed') is not True:break
            else:
                writer.write_json(path,value,replace=io.replace_control_snapshot)
            published_epoch=epoch
        release.set();reader.join(timeout=5)
        small.need(not reader.is_alive() and not errors, 'Reader failed or did not close')
        small.need(values == [initial], 'Held snapshot changed across publication')
        current = json.loads(io.read_control_snapshot(path,8192))
        small.need(current == dict(epoch=published_epoch,data=initial['data'])
                   and (published_epoch==0 or path.stat().st_ino!=held[0]['inode']), 'Fresh complete snapshot required')
        report.update(status='passed-discriminator' if node else 'passed',publications=1+published_epoch,
                      node_publications=published_epoch if node else None,
                      canonical_node_supported=published_epoch==32 if node else None,held_epoch=0,fresh_epoch=current['epoch'],
                      held_snapshot=held[0],fresh_inode=path.stat().st_ino,reader_joined=True,close_uncertain=False)
    except BaseException as error:
        report.update(status='failed',error=str(error),api=getattr(error,'api',None),
            close_uncertain=bool(getattr(error,'process_handle_close_uncertain',False)))
    finally:
        release.set()
        if reader.ident is not None:reader.join(timeout=5)
        io.os = original_os
        budget.active=False
        if null_input is not None:
            try:null_input.close()
            except BaseException as error:errors.append(error)
        timer.cancel();timer.join(timeout=1)
        report.update(reader_joined=not reader.is_alive(),timer_joined=not timer.is_alive(),
            reader_errors=[str(error) for error in errors],usage=budget.usage())
        if reader.is_alive() or timer.is_alive() or errors:report['status']='failed'
    report['observer']=small.windows.process_identity(os.getpid())
    report['job']=small.runner.owned_windows_job()
    small.need(report['job']['kill_on_close'] and report['job']['pids']==[os.getpid()], 'Owner-only Job required')
    small.runner.write_json(root/'result.json',report)
    return 0 if report['status'] in ('passed','passed-discriminator') else 1


def native_sealed_job_control(old_runner, old_sha, source_map, source_sha, directory):
    """Real inherited Job membership survives an intermediate's intended exit."""
    import ast
    import hashlib
    import shutil
    small.need(os.name=='nt','Native sealed-Job component only')
    with Path(old_runner).open('rb') as source:raw=source.read(1024**2+1)
    small.need(len(raw)<=1024**2 and hashlib.sha256(raw).hexdigest()==old_sha,'Historical census source SHA256')
    old_node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='census_child')
    scope=dict(need=small.need,os=os)
    exec(compile(ast.Module(body=[old_node],type_ignores=[]),str(old_runner),'exec'),scope)
    old_census_child=scope['census_child']
    root=Path(directory).absolute()
    checker=small.module('acceptance-preflight')
    checker.check_evidence_destination(root,[selected_runner,Path(old_runner),Path(source_map)])
    small.need(not root.exists(),'Fresh component output required')
    small.need(shutil.disk_usage('C:/').free-1024**2>=128*small.GIB,'Physical component write floor')
    root.mkdir()
    body_deadline=time.monotonic()+30
    timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    budget=checker.Budget(dict(seconds=30,read_bytes=192*1024**2,visits=200000,
        capture_bytes=65536,storage_bytes=1024**2),root)
    budget.read_bytes=64*1024**2
    small.runner.contain_session()
    kernel=small.windows.kernel()
    job=small.runner._SESSION_JOB
    own=small.windows.held_identity(kernel.GetCurrentProcess(),os.getpid())
    small.need(small.windows.query_job(job)['pids']==[os.getpid()],'Initial owner-only Job required')
    middle=None;grand=None;out=err=null=None;reaped=closed=close_attempted=False;errors=[]
    def close_middle():
        nonlocal closed,close_attempted
        close_attempted=True
        try:middle._handle.Close();closed=True
        except OSError as error:raise small.windows.ProcessHandleCloseError('Intermediate handle close unproven') from error
    report=dict(status='failed',qualification=False,Original=False,browser=False,product=False,
        observer=own,source_map_sha256=source_sha,historical_census_sha256=hashlib.sha256(ast.dump(old_node).encode()).hexdigest())
    try:
        grand_source=root/'grandchild.py'
        grand_source.write_text("from pathlib import Path\nimport time\np=Path(__file__).parent/'release-grandchild'\nd=time.monotonic()+15\nwhile not p.exists():\n if time.monotonic()>d:raise SystemExit(92)\n time.sleep(.005)\n")
        middle_source=root/'intermediate.py'
        middle_source.write_text("from pathlib import Path\nimport subprocess,sys,os,time,json\nr=Path(__file__).parent\np=subprocess.Popen([sys.executable,'-I','-B',str(r/'grandchild.py')],stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)\n(r/'grandchild.tmp').write_text(json.dumps(dict(pid=p.pid)))\nos.replace(r/'grandchild.tmp',r/'grandchild.json')\nd=time.monotonic()+10\nwhile not (r/'exit-intermediate').exists():\n if time.monotonic()>d:os._exit(92)\n time.sleep(.005)\nos._exit(0)\n")
        out=(root/'child-stdout.log').open('xb');err=(root/'child-stderr.log').open('xb');null=open(os.devnull,'rb')
        argv=[sys.executable,'-I','-B',str(middle_source)]
        budget.allowed_commands.add(budget.command_key(argv));budget.install()
        middle=subprocess.Popen(argv,stdin=null,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+5
        while not (root/'grandchild.json').exists():
            small.need(middle.poll() is None and time.monotonic()<deadline,'Intermediate startup deadline')
            small.need(all(os.fstat(s.fileno()).st_size<=65536 for s in (out,err)),'Component capture bound')
            time.sleep(.005)
        pid=json.loads((root/'grandchild.json').read_text())['pid']
        grand=small.windows.checked(kernel.OpenProcess(0x101000,False,pid),api='OpenProcess',pid=pid)
        held=small.windows.held_identity(grand,pid)
        small.need(held['parent']==middle.pid and Path(held['image'])==Path(sys.executable),'Held grandchild provenance')
        first=small.windows.job_processes(job,small.windows.query_job(job),deadline=time.monotonic()+.8)
        direct=small.census_child(first['census'],first['processes'],os.getpid(),sys.executable,runner_birth=own['created'])
        small.need(direct['pid']==middle.pid and next(p for p in first['processes'] if p['pid']==pid)==
                   {k:held[k] for k in ('pid','parent','image','created')},
                   'Initial complete actual lineage')
        report.update(intermediate=direct,grandchild=held,before=first)
        (root/'exit-intermediate').write_text('exit')
        small.need(middle.wait(timeout=5)==0,'Intermediate did not exit normally');reaped=True
        close_middle()
        after=small.windows.job_processes(job,small.windows.query_job(job),deadline=time.monotonic()+.8)
        small.need(middle.pid not in after['census']['pids'] and pid in after['census']['pids'],'Exited intermediate absent/held grandchild present')
        small.need(small.windows._held_birth(kernel,grand,pid)==held['created'] and kernel.WaitForSingleObject(grand,0)==258,
                   'Same held grandchild must remain live')
        try:old_census_child(after['census'],after['processes'],os.getpid(),sys.executable)
        except OSError as error:
            small.need(str(error)=='Job descendant parent identity unavailable','Unexpected historical denial')
            report['historical_denial']=str(error)
        else:raise OSError('Historical live-parent requirement did not deny actual orphan')
        child=small.census_child(after['census'],after['processes'],os.getpid(),sys.executable,runner_birth=own['created'])
        small.need(child is None,'No new direct child after intermediate exit')
        report.update(status='passed',after=after,held_grandchild_live=True)
    except BaseException as error:
        report.update(status='failed',error=str(error),causes=small.error_causes(error,{}))
    finally:
        def attempt(phase,action):
            try:return action()
            except BaseException as error:errors.append(dict(phase=phase,error=repr(error)))
        attempt('release-grandchild',lambda:(root/'release-grandchild').write_text('exit'))
        attempt('release-intermediate',lambda:(root/'exit-intermediate').write_text('exit'))
        if middle is not None and not reaped:
            code=attempt('intermediate-wait',lambda:middle.wait(timeout=5));reaped=code==0
        if middle is not None and not close_attempted and reaped:
            attempt('intermediate-close',close_middle)
        if close_attempted and not closed:
            errors.append(dict(phase='intermediate-close-unproven',error='A failed close is not retried or credited'))
        if grand is not None:
            wait=attempt('grandchild-wait',lambda:kernel.WaitForSingleObject(grand,5000))
            if wait!=0:errors.append(dict(phase='grandchild-signaled',error=str(wait)))
            code=small.windows.W.DWORD()
            ok=attempt('grandchild-exit-code',lambda:small.windows.checked(
                kernel.GetExitCodeProcess(grand,ctypes.byref(code)),api='GetExitCodeProcess',pid=pid))
            if not ok or code.value!=0:errors.append(dict(phase='grandchild-exit-code',error=str(code.value)))
            report['grandchild_exit_code']=code.value if ok else None
            attempt('grandchild-close',lambda:small.windows.checked(kernel.CloseHandle(grand),api='CloseHandle',pid=pid))
        for stream in (out,err,null):
            if stream is not None:attempt('capture-close',stream.close)
        def drain():
            known={row['pid']:row for row in [own]+report.get('before',{}).get('processes',[])+report.get('after',{}).get('processes',[])}
            polls=0
            while True:
                census=small.windows.query_job(job)
                report['final_drain']=dict(polls=polls,last_census=census)
                small.need(not set(census['pids'])-set(known),'Unexpected fixture cleanup Job member')
                sampled=small.windows.job_processes(job,census,list(known.values()),deadline=body_deadline-.05)
                census=sampled['census']
                small.census_child(census,sampled['processes'],os.getpid(),sys.executable,runner_birth=own['created'])
                report['final_drain'].update(last_census=census,identities=sampled['processes'])
                if census['pids']==[os.getpid()]:return census
                left=body_deadline-time.monotonic()
                small.need(left>0,'Fixture cleanup Job drain deadline')
                time.sleep(min(.005,left));polls+=1
        proof=attempt('final-job',drain)
        if proof is None or not proof['kill_on_close'] or proof['pids']!=[os.getpid()]:errors.append(dict(phase='owner-only-final',error=str(proof)))
        budget.active=False;timer.cancel();timer.join()
        report.update(intermediate_reaped=reaped,intermediate_closed=closed,final_job=proof,
            captures_closed=all(s is None or s.closed for s in (out,err,null)),timer_joined=not timer.is_alive(),cleanup_errors=errors,usage=budget.usage())
        if errors:report['status']='failed-cleanup'
        small.need(len((json.dumps(report,indent=2)+'\n').encode())<=65536,'Component result memory bound')
        small.need(sum(((p.stat().st_size+4095)//4096+1)*4096 for p in root.iterdir())+65536<=1024**2,
                   'Component output allowance')
        small.runner.write_json(root/'result.json',report)
    return 0 if report['status']=='passed' else 1


def native_storage_rescan_control(old_runner, old_sha, source_map, source_sha, directory):
    """Real NTFS enumerate/atomic-publish overlap; no workload or Original lock."""
    import ast
    import hashlib
    small.need(os.name == 'nt', 'Native storage component only')
    with Path(old_runner).open('rb') as stream: raw = stream.read(1024**2+1)
    small.need(len(raw)<=1024**2 and hashlib.sha256(raw).hexdigest()==old_sha, 'Historical storage source SHA256')
    old_node = next(n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='Storage')
    scope = dict(vars(small))
    exec(compile(ast.Module(body=[old_node],type_ignores=[]),str(old_runner),'exec'),scope)
    root = Path(directory).absolute()
    checker = small.module('acceptance-preflight')
    checker.check_evidence_destination(root,[selected_runner,Path(old_runner),Path(source_map)])
    small.need(not root.exists(), 'Fresh storage component output')
    small.need(small.shutil.disk_usage('C:/').free-1024**2>=128*small.GIB, 'Physical write floor')
    root.mkdir()
    deadline = time.monotonic()+30
    timer = threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    budget = checker.Budget(dict(seconds=30,read_bytes=192*1024**2,visits=200000,
        capture_bytes=65536,storage_bytes=1024**2),root)
    budget.read_bytes = 64*1024**2
    small.runner.contain_session()
    kernel = small.windows.kernel()
    job = small.runner._SESSION_JOB
    own = small.windows.held_identity(kernel.GetCurrentProcess(),os.getpid())
    report = dict(status='failed',qualification=False,Original=False,browser=False,product=False,
        observer=own,source_map_sha256=source_sha,metric='SMALL rounded files plus descendant directories',
        unobserved_transient_allocation='UNKNOWN')
    errors=[]
    try:
        small.need(small.windows.query_job(job)['pids']==[os.getpid()], 'Owner-only initial Job')
        budget.install()
        def schedule(label, implementation):
            workspace = root/label;workspace.mkdir()
            ledger = workspace/'storage-ledger.json'
            ledger.write_bytes(b'x'*12000)
            storage = implementation([workspace])
            before = storage.sample()
            temporary = ledger.with_suffix('.tmp');temporary.write_bytes(b'new')
            original = Path.lstat
            publications=[]
            def reading(path,*args,**kwargs):
                if path==temporary and not publications:
                    small.runner.write_json(ledger,dict(publication=label))
                    publications.append(dict(source=str(temporary),destination=str(ledger)))
                return original(path,*args,**kwargs)
            caught=None
            started=time.monotonic()
            try:
                with patch.object(Path,'lstat',reading):
                    total = storage.sample(mutable_roots=[workspace],deadline=deadline) if implementation is small.Storage else storage.sample()
            except OSError as error:
                caught=error;total=storage.total
            small.need(len(publications)==1 and not temporary.exists(), 'Actual owning atomic writer transition')
            return dict(denied=caught is not None,error=str(caught) if caught else None,
                causes=small.error_causes(caught,{}) if caught else [],before=before,total=total,
                rescans=getattr(storage,'rescans',[]),publication=publications[0],seconds=time.monotonic()-started)
        report['old']=schedule('old',scope['Storage'])
        small.need(report['old']['denied'] and report['old']['error']=='Unbounded unseen storage deletion race',
                   'Historical unseen-temp denial counterfactual')
        report['current']=schedule('current',small.Storage)
        current=report['current']
        small.need(not current['denied'] and len(current['rescans'])==1 and current['total']>=current['before']+8192,
                   'Current complete rescan retains prior charge plus new identity')
        small.need(time.monotonic()<deadline,'Original component deadline')
        report['status']='passed'
    except BaseException as error:
        report.update(error=str(error),causes=small.error_causes(error,{}))
    finally:
        try:
            census=small.windows.query_job(job)
            small.need(census['kill_on_close'] and census['pids']==[os.getpid()],'Final owner-only Job')
            small.need(small.windows.held_identity(kernel.GetCurrentProcess(),os.getpid())==own,'Held owner identity')
            report['final_job']=census
        except BaseException as error:errors.append(str(error))
        budget.active=False;timer.cancel();timer.join()
        report.update(cleanup_errors=errors,timer_joined=not timer.is_alive(),usage=budget.usage())
        if errors:report['status']='failed-cleanup'
        small.need(len((json.dumps(report,indent=2)+'\n').encode())<=65536,'Bounded component result')
        small.need(small.Storage([root]).sample()+65536<=1024**2,'Component output allowance')
        small.runner.write_json(root/'result.json',report)
    return 0 if report['status']=='passed' else 1


def native_receipt_census_control(old_runner, old_sha, source_map, source_sha, directory):
    """Real process end/report after an old census, then an independent new census."""
    import ast
    import hashlib
    from scale_acceptance import native_scale_windows as bootstrap
    from scale_acceptance.native_scale_windows import create_job, SuspendedWorker
    small.need(os.name=='nt','Native receipt-census component only')
    with Path(old_runner).open('rb') as stream:raw=stream.read(1024**2+1)
    small.need(len(raw)<=1024**2 and hashlib.sha256(raw).hexdigest()==old_sha,'Historical receipt source SHA256')
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='Receipts')
    scope=dict(vars(small));exec(compile(ast.Module(body=[node],type_ignores=[]),str(old_runner),'exec'),scope)
    root=Path(directory).absolute();checker=small.module('acceptance-preflight')
    checker.check_evidence_destination(root,[selected_runner,Path(old_runner),Path(source_map)])
    small.need(not root.exists(),'Fresh receipt component root')
    small.need(small.shutil.disk_usage('C:/').free-1024**2>=128*small.GIB,'Physical write floor')
    root.mkdir();deadline=time.monotonic()+30
    timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    budget=checker.Budget(dict(seconds=30,read_bytes=192*1024**2,visits=200000,
        capture_bytes=65536,storage_bytes=1024**2),root);budget.read_bytes=64*1024**2
    small.runner.contain_session();kernel=small.windows.kernel();outer=small.runner._SESSION_JOB
    own=small.windows.held_identity(kernel.GetCurrentProcess(),os.getpid())
    child=inner=out=err=null_input=null_duplicate=None;reaped=closed=close_attempted=False;errors=[]
    report=dict(status='failed',qualification=False,Original=False,browser=False,product=False,
        observer=own,source_map_sha256=source_sha,scope='Isolated armed-receipt state; no quota/browser/product assertion credit')
    def attempt(phase,action):
        try:return action()
        except BaseException as error:errors.append(dict(phase=phase,error=str(error)));return None
    def close_child():
        nonlocal closed,close_attempted
        close_attempted=True
        child.close();closed=True
    try:
        # NUL is a declared stdin role, not a regular evidence input. Supply its
        # pre-opened duplicate only to the helper's exact fixed open(NUL,'rb').
        null_input=open(os.devnull,'rb')
        null_duplicate=os.fdopen(os.dup(null_input.fileno()),'rb')
        used_null=False
        original_open=getattr(bootstrap,'open',open)
        def bootstrap_open(path,mode='r',*args,**kwargs):
            nonlocal used_null
            if path==os.devnull and mode=='rb' and not args and not kwargs:
                small.need(not used_null,'Fixed helper stdin role opened twice')
                used_null=True
                return null_duplicate
            return original_open(path,mode,*args,**kwargs)
        budget.install();inner=create_job(small.windows);child=SuspendedWorker()
        out=(root/'child.stdout.log').open('xb');err=(root/'child.stderr.log').open('xb')
        argv=[sys.executable,'-E','-s','-B','-c','import time;time.sleep(20)']
        with patch.object(bootstrap,'open',bootstrap_open,create=True):
            child.start(argv,out,err,dict(os.environ))
        small.need(used_null and null_duplicate.closed,'Fixed helper consumed/closed pre-opened stdin duplicate')
        report['preopened_null_consumed_closed']=True
        child.assign(inner);child.resume()
        held=small.windows.held_identity(child.handle,child.pid)
        small.need(held['parent']==os.getpid() and Path(held['image'])==Path(sys.executable),'Exact real child provenance')
        report['child']=held;report['argv']=argv
        def census():
            started=small.now_ms();value=small.windows.query_job(inner)
            small.need(value['kill_on_close'],'Exact nonbreakaway child Job required')
            return started,value
        old_start,old_census=census();small.need(old_census['pids']==[child.pid],'Genuine live child census')
        small.need(kernel.WaitForSingleObject(child.handle,0)==258,'Actual child live before negative')
        def receipt(implementation):
            value=implementation();value.pid=child.pid;value.armed=True;value.sampled=True
            return value
        packet=dict(argv=['--process-kill'])
        false_ms=small.now_ms();negative=root/'live-negative.jsonl'
        negative.write_text(json.dumps(dict(type='deliberate-process-kill-observed',sampled_ms=false_ms,pid=child.pid))+'\n')
        time.sleep(.5)  # one ordinary supervisor cadence; never a new hot deadline
        fresh_start,live=census();live_error=None
        try:receipt(small.Receipts).read(negative,packet,small.now_ms(),live['pids'],{},census_started_ms=fresh_start)
        except OSError as error:live_error=error
        small.need(live_error is not None and str(live_error)=='Deliberate kill not actually exited','Fresh live false-report must deny')
        report['live_negative']=small.error_causes(live_error,{})
        small.windows.checked(kernel.TerminateProcess(child.handle,93),api='TerminateProcess',pid=child.pid)
        code=child.wait(min(5,max(0,deadline-time.monotonic())));reaped=True
        small.need(code==93 and kernel.WaitForSingleObject(child.handle,0)==0,'Actual held child ended/reaped')
        small.need(small.windows._held_birth(kernel,child.handle,child.pid)==held['created'],'Same held birth after real termination')
        close_child()
        event_ms=small.now_ms();path=root/'receipt.jsonl'
        path.write_text(''.join(json.dumps(row)+'\n' for row in (
            dict(type='deliberate-process-kill-observed',sampled_ms=event_ms,pid=held['pid']),
            dict(type='monitor-cleanup',sampled_ms=event_ms,errors=[]))))
        old_error=None
        try:receipt(scope['Receipts']).read(path,packet,small.now_ms(),old_census['pids'],{})
        except OSError as error:old_error=error
        small.need(old_error is not None and str(old_error)=='Deliberate kill not actually exited','Old pre-exit census counterfactual must deny')
        current=receipt(small.Receipts)
        current.read(path,packet,small.now_ms(),old_census['pids'],{},census_started_ms=old_start)
        small.need(current.pending_exit==event_ms and current.offset==0 and not current.cleaned and not current.observed,
                   'New parser must defer exact old snapshot without accepting cleanup')
        time.sleep(.5)
        final_start,ended=census();small.need(ended['pids']==[],'Independent fresh complete child Job exclusion')
        current.read(path,packet,small.now_ms(),ended['pids'],{},census_started_ms=final_start)
        small.need(current.cleaned and current.observed and current.pending_exit is None and current.offset==path.stat().st_size,
                   'Only newer exact census may complete exit/cleanup')
        small.need(time.monotonic()<deadline,'Original component endpoint')
        report.update(status='passed',old_census=old_census,old_start_ms=old_start,observed_ms=event_ms,
            old_denial=str(old_error),deferred_before_fresh=True,fresh_start_ms=final_start,fresh_census=ended,
            child_exit_code=code,new_cleanup_accepted=True)
    except BaseException as error:report.update(error=str(error),causes=small.error_causes(error,{}))
    finally:
        if child is not None and not closed:
            if close_attempted:
                errors.append(dict(phase='close-child',error='Prior child handle closure unproven; no retry'))
            elif child.handles is not None:
                if not reaped:
                    attempt('stop-owned-inner',lambda:small.windows.terminate(inner))
                    def stop_exact_child():
                        state=kernel.WaitForSingleObject(child.handle,0)
                        small.need(state in (0,258),'Owned child wait state unknown')
                        if state==258:
                            small.windows.checked(kernel.TerminateProcess(child.handle,91),api='TerminateProcess',pid=child.pid)
                    attempt('stop-exact-child',stop_exact_child)
                    reaped=attempt('reap-child',lambda:child.wait(max(0,min(5,deadline-time.monotonic())))) is not None
                attempt('close-child',close_child)
            elif child.creation_started:errors.append(dict(phase='spawn',error='Unknown child creation ownership'))
        if inner is not None:
            proof=attempt('empty-inner',lambda:small.windows.query_job(inner))
            if proof is None or proof['pids']:errors.append(dict(phase='empty-inner',error=str(proof)))
            attempt('close-inner',lambda:small.windows.close(inner))
        for stream in (out,err,null_duplicate,null_input):
            if stream is not None:attempt('close-capture',stream.close)
        proof=attempt('owner-only-outer',lambda:small.windows.query_job(outer))
        if proof is None or not proof['kill_on_close'] or proof['pids']!=[os.getpid()]:errors.append(dict(phase='owner-only-outer',error=str(proof)))
        budget.active=False;timer.cancel();timer.join()
        report.update(child_reaped=reaped,child_handles_closed=closed,cleanup_errors=errors,
            captures_closed=all(stream is None or stream.closed for stream in (out,err,null_duplicate,null_input)),
            final_job=proof,timer_joined=not timer.is_alive(),usage=budget.usage())
        if errors:report['status']='failed-cleanup'
        small.need(len((json.dumps(report,indent=2)+'\n').encode())<=65536,'Bounded component result')
        small.need(small.Storage([root]).sample()+65536<=1024**2,'Component output allowance')
        small.runner.write_json(root/'result.json',report)
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--native-probe':
        import shutil
        native_probe(sys.argv[2])
    elif len(sys.argv) == 10 and sys.argv[1] == '--native-cancel-control':
        raise SystemExit(native_cancel_control(*sys.argv[4:]))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-control-io-stress':
        raise SystemExit(native_control_io_stress(*sys.argv[4:]))
    elif len(sys.argv) == 11 and sys.argv[1] == '--native-node-control-io':
        raise SystemExit(native_control_io_stress(*sys.argv[4:]))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-browser-scale-control':
        raise SystemExit(native_browser_scale_control(*sys.argv[4:]))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-browser-scale-capacity':
        raise SystemExit(native_browser_scale_control(*sys.argv[4:],capacity_only=True))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-browser-scale-after-exit':
        raise SystemExit(native_browser_scale_control(*sys.argv[4:],after=True))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-receipt-census-control':
        raise SystemExit(native_receipt_census_control(*sys.argv[4:]))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-storage-rescan-control':
        raise SystemExit(native_storage_rescan_control(*sys.argv[4:]))
    elif len(sys.argv) == 9 and sys.argv[1] == '--native-sealed-job-control':
        raise SystemExit(native_sealed_job_control(*sys.argv[4:]))
    else:
        unittest.main()
