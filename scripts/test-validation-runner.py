"""Tiny real subprocess controls for durable validation and resume."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('validation-runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PYTHON = str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable


class RunnerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned-group completion control')
    def test_abandoned_non_detached_helper_fails_and_is_terminated(self):
        import ctypes
        import signal
        # The fixture adopts/reaps its orphan. Production does not install a
        # process-global subreaper or claim ownership of other callers' children.
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        leader = None
        helper = None
        helper_reaped = False
        try:
            self.plan['steps'][0]['argv'] = [PYTHON, '-c',
                'import subprocess,sys; from pathlib import Path; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                'Path("output").write_text(str(p.pid))']
            self.path.write_text(json.dumps(self.plan))
            children = []
            try:
                result = runner.run(self.path, self.batch, on_process=children.append)
                leader = children[-1]
                helper = int((self.root / 'output').read_text())
                self.assertEqual(result, 1)
                attempt = self.status()['attempts'][0]
                self.assertEqual(attempt['status'], 'failed')
                self.assertIn('abandoned owned process group', attempt['error'])
                waited, code = os.waitpid(helper, 0)
                self.assertEqual(waited, helper)
                helper = None
                helper_reaped = True
                self.assertTrue(os.WIFSIGNALED(code))
                self.assertEqual(os.WTERMSIG(code), signal.SIGKILL)
                self.assertEqual(leader.returncode, 0)
            finally:
                if children and children[-1] is not None:
                    leader = children[-1]
                if not helper_reaped and helper is None and (self.root / 'output').exists():
                    helper = int((self.root / 'output').read_text())
                if leader is not None and helper is not None:
                    try: os.killpg(leader.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                if leader is not None and leader.returncode is None:
                    runner.stop(leader)
                if helper is not None:
                    try: os.waitpid(helper, 0)
                    except ChildProcessError: pass
        finally:
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned-group completion control')
    def test_joined_helper_passes_and_an_unrelated_group_survives(self):
        import subprocess
        other = subprocess.Popen([PYTHON, '-c', 'import time;time.sleep(30)'], start_new_session=True)
        try:
            self.plan['steps'][0]['argv'] = [PYTHON, '-c',
                'import subprocess,sys; '
                'p=subprocess.Popen([sys.executable,"-c","print(123)"]); p.wait(); '
                'open("output","w").write("joined")']
            self.assertEqual(self.execute(), 0)
            self.assertEqual(self.status()['summary'], {'passed': 1, 'incomplete': 0})
            self.assertIsNone(other.poll())
        finally:
            other.kill()
            other.wait()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux non-reaping completion control')
    def test_group_signal_keeps_leader_identity_and_census_failure_denies(self):
        import signal
        original_signal = os.killpg
        original_scan = os.scandir
        signals = []
        def anchored(group, number):
            self.assertEqual(number, signal.SIGKILL)
            info = os.waitid(os.P_PID, group, os.WEXITED | os.WNOWAIT | os.WNOHANG)
            self.assertIsNotNone(info)
            self.assertEqual(info.si_pid, group)
            signals.append(group)
            return original_signal(group, number)
        with patch.object(runner.os, 'killpg', side_effect=anchored):
            self.assertEqual(self.execute(), 0)
        self.assertEqual(len(signals), 1)
        def denied(path):
            if str(path) == '/proc':
                raise PermissionError('injected owned-group census denial')
            return original_scan(path)
        # Make the passed attempt non-reusable, then fail at the real post-exit boundary.
        (self.root / 'input').write_text('changed')
        with patch.object(runner.os, 'scandir', side_effect=denied), \
                patch.object(runner.os, 'killpg', side_effect=anchored):
            self.assertEqual(self.execute(), 1)
        self.assertEqual(len(signals), 2)
        self.assertEqual(self.status()['attempts'][-1]['exit_code'], 0)
        self.assertIn('census denial', self.status()['attempts'][-1]['error'])

    def test_resume_requires_the_owning_runner_implementation_identity(self):
        self.assertEqual(self.execute(), 0)
        for absent in [True, False]:
            state = self.status()
            runtime = state['attempts'][-1]['runtime']
            self.assertEqual(runtime['runner_sha256'], runner.digest(Path(runner.__file__).resolve()))
            if absent:
                del runtime['runner_sha256']
            else:
                runtime['runner_sha256'] = '0' * 64
            runner.write_json(self.batch / 'status.json', state)
            self.assertEqual(self.execute(), 0)
            self.assertEqual(len(self.status()['attempts']), len(state['attempts']) + 1)

    def cleanup_failure_control(self, fault):
        import subprocess
        children = []
        (self.root / 'input').write_text('sleep' if fault == 'signal' else 'complete')
        self.plan['steps'][0].update(timeout_seconds=0.2, argv=[PYTHON, '-c',
            'import time; from pathlib import Path; '
            'Path("output").write_text("partial"); '
            'time.sleep(30 if Path("input").read_text()=="sleep" else 0)'])
        self.path.write_text(json.dumps(self.plan))
        if fault == 'signal':
            injected = patch.object(runner.os, 'killpg', side_effect=PermissionError('injected signal denial'))
        else:
            injected = patch.object(runner.subprocess.Popen, 'wait',
                side_effect=lambda process=None, **kwargs: (_ for _ in ()).throw(
                    subprocess.TimeoutExpired('injected reap', 10)))
        try:
            with injected as operation:
                self.assertEqual(runner.run(self.path, self.batch, on_process=children.append), 1)
                self.assertEqual(operation.call_count, 1)
            child = children[-1]
            state = self.status()
            attempt = state['attempts'][0]
            self.assertEqual(attempt['status'], 'failed')
            self.assertEqual(state['summary'], {'passed': 0, 'incomplete': 1})
            self.assertEqual(attempt['artifacts'], {})
            self.assertIn('skipped', attempt['identity_recheck'])
            held = attempt['cleanup_unresolved']
            self.assertEqual(held['process_identity']['pid'], child.pid)
            self.assertEqual(held['process_identity']['process_group'], child.pid)
            self.assertGreater(held['process_identity']['linux_start_ticks'], 0)
            self.assertIn('injected', held['error'])
            self.assertIn('Traceback', held['traceback'])
            self.assertTrue((self.batch / 'runner.lock').exists())
            # A failed closer cannot unlock a new command or issue a reusable pass.
            with patch.object(runner.subprocess, 'Popen') as launch:
                with self.assertRaises(FileExistsError):
                    runner.run(self.path, self.batch)
            launch.assert_not_called()
        finally:
            if children and children[-1] is not None and children[-1].returncode is None:
                runner.stop(children[-1])
        # Only this fixture's positive reap permits removal of its retained lock.
        self.assertIsNotNone(children[-1].returncode)
        (self.batch / 'runner.lock').unlink()
        (self.root / 'input').write_text('complete')
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 2)
        self.assertIn('cleanup_unresolved', self.status()['attempts'][0])
        self.assertFalse((self.batch / 'runner.lock').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux real signal-denial control')
    def test_signal_denial_is_durable_and_retains_the_batch_lock(self):
        self.cleanup_failure_control('signal')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux real unreaped-leader control')
    def test_reap_timeout_is_durable_and_retains_the_batch_lock(self):
        self.cleanup_failure_control('reap')

    def test_absolute_external_file_inputs_and_artifacts_use_the_owning_runner(self):
        with tempfile.TemporaryDirectory() as external:
            source=Path(external)/'source';source.write_bytes(b'original')
            output=Path(external)/'output'
            self.plan['steps'][0].update(inputs=[str(source)],artifacts=[str(output)],
                argv=[PYTHON,'-c',f'from pathlib import Path;Path({str(output)!r}).write_bytes(b"done")'])
            self.assertEqual(self.execute(),0)
            attempt=self.status()['attempts'][0]
            self.assertEqual(set(attempt['inputs']),{str(source)})
            self.assertEqual(set(attempt['artifacts']),{str(output)})
            before=runner.identity(self.root,[str(source)])
            source.write_bytes(b'changed')
            self.assertNotEqual(runner.identity(self.root,[str(source)]),before)

    def test_identity_record_matches_absolute_and_legacy_relative_keys_without_aliases(self):
        for root, filename, relative in (
                ('/selected/root', '/selected/fixture/input.json', '../fixture/input.json'),
                (r'C:\selected\root', r'C:\selected\fixture\input.json', r'..\fixture\input.json')):
            with self.subTest(root=root):
                value = dict(sha256='a'*64, resolved=filename)
                for name in (filename, relative):
                    self.assertEqual(runner.identity_record(root, {name: value}, filename), value)
                    self.assertEqual(runner.identity_key(root, filename, absolute=False), relative)
                for records in ({relative: value, filename: value},
                                {relative: dict(value, resolved=filename+'.other')},
                                {relative+'.other': value},
                                {relative: dict(value, directory=True)},
                                {relative: None}):
                    with self.assertRaises(ValueError):
                        runner.identity_record(root, records, filename)
                with self.assertRaises(ValueError):
                    runner.identity_record(root+'/wrong-root', {relative: value}, filename)
        # Real producer output has the same file binding with either declaration shape.
        source=self.root/'input';source.write_bytes(b'owning bytes')
        for declared in ('input',str(source)):
            records=runner.identity(self.root,[declared])
            self.assertEqual(runner.identity_record(self.root,records,source)['sha256'],runner.digest(source))

    def test_retained_r3_native_preflight_absolute_plan_and_worker_artifact_keys(self):
        # Exact declarations and custody fields from passed R3 status 58ed3274... .
        root = r'C:\chopper-native178-source-r2\h-native103-r3'
        plan = r'C:\chopper-native178-tiny-r2\full-native103-qual-r3\tiny-plan.json'
        worker = r'C:\chopper-native178-tiny-r2\full-native103-qual-r3\preflight\worker-result.json'
        records = {plan: dict(sha256='a696055ec910318ded938f8c4e7600d2964ec12e416891407f52653b5e05d609',
                             resolved=plan.replace('\\', '\\\\')),
                   worker: dict(sha256='55fb2336fd12872b1f4c315f3bad22dc2c8993f7fa7b458a9877a6990d743a7e',
                               resolved=worker.replace('\\', '\\\\'))}
        for filename, record in records.items():
            self.assertEqual(runner.identity_record(root, {filename: record}, filename), record)
            relative = runner.identity_key(root, filename, absolute=False)
            self.assertEqual(runner.identity_record(root, {relative: record}, filename), record)

    def test_missing_absolute_file_and_absolute_directory_deny(self):
        with tempfile.TemporaryDirectory() as external:
            missing=str(Path(external)/'missing')
            self.assertTrue(runner.incomplete_identity(runner.identity(self.root,[missing])))
            self.assertTrue(runner.incomplete_identity(runner.identity(self.root,[external])))
            (Path(external)/'found.txt').write_bytes(b'not an absolute glob match')
            self.assertTrue(runner.incomplete_identity(runner.identity(self.root,[str(Path(external)/'*.txt')])))
            self.plan['steps'][0]['inputs']=[missing]
            with patch.object(runner.subprocess,'Popen') as launch:
                self.assertEqual(self.execute(),1)
            launch.assert_not_called()

    def test_process_hook_failure_stops_the_real_returned_child(self):
        self.plan['steps'][0]['argv']=[PYTHON,'-c','import time;time.sleep(30)']
        self.path.write_text(json.dumps(self.plan));seen=[]
        def observe(process):
            seen.append(process)
            if process is not None:raise RuntimeError('injected returned-process observer failure')
        with self.assertRaisesRegex(RuntimeError,'returned-process observer'):
            runner.run(self.path,self.batch,on_process=observe)
        self.assertIsNone(seen[0]);self.assertEqual(len(seen),2)
        self.assertIsNotNone(seen[1].poll())

    def test_process_constructor_failure_has_prelaunch_hook_and_no_returned_child(self):
        self.path.write_text(json.dumps(self.plan));seen=[]
        with patch.object(runner.subprocess,'Popen',side_effect=FileNotFoundError('known no-start fixture')):
            self.assertEqual(runner.run(self.path,self.batch,on_process=seen.append),1)
        self.assertEqual(seen,[None])
        self.assertIn('known no-start',self.status()['attempts'][0]['error'])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'input').write_text('original')
        self.plan = {'root': str(self.root), 'batch_timeout_seconds': 10,
                     'estimated_seconds': 1, 'estimated_disk_bytes': 1024,
                     'toolchains': {'python': sys.version}, 'features': [], 'fixtures': ['input'],
                     'steps': [{'id': 'first', 'inputs': ['input'], 'artifacts': ['output'],
                                'argv': [PYTHON, '-c', "print('ok'); open('output','w').write('ok')"],
                                'timeout_seconds': 3}]}
        self.path = self.root / 'plan.json'
        self.batch = self.root / 'batch'

    def execute(self):
        self.path.write_text(json.dumps(self.plan), encoding='utf-8')
        return runner.run(self.path, self.batch)

    def status(self):
        return json.loads((self.batch / 'status.json').read_text())

    def test_observation_is_detached_immutable_and_ordinary_status_is_complete(self):
        self.path.write_text(json.dumps(self.plan))
        snapshots = []
        def observe(value):
            snapshots.append(value)
            with self.assertRaises(AttributeError):
                value.terminal = True
            if value.attempts:
                with self.assertRaises(AttributeError):
                    value.attempts[0].status = 'forged'
                self.assertEqual(value.attempts[0]._fields, ('id', 'attempt', 'status'))
        self.assertEqual(runner.run(self.path, self.batch, observe=observe), 0)
        self.assertEqual([(v.terminal, [a.status for a in v.attempts]) for v in snapshots],
                         [(False, []), (False, ['running']), (False, ['passed']), (True, ['passed'])])
        self.assertIn('input', self.status()['attempts'][0]['inputs'])
        self.assertIn('output', self.status()['attempts'][0]['artifacts'])
        self.assertEqual(json.loads((self.batch/'manifest.json').read_text()), self.plan)
        # Ordinary resume remains supported, with no additional attempts.
        self.assertEqual(runner.run(self.path, self.batch), 0)
        self.assertEqual(len(self.status()['attempts']), 1)

    def test_observation_failure_propagates_with_full_completed_attempt_retained(self):
        self.path.write_text(json.dumps(self.plan))
        def fail(value):
            if value.attempts and value.attempts[-1].status == 'passed':
                raise OSError('observation publication failed')
        with self.assertRaisesRegex(OSError, 'observation publication failed'):
            runner.run(self.path, self.batch, observe=fail)
        self.assertEqual(self.status()['attempts'][0]['status'], 'passed')
        self.assertIn('input', self.status()['attempts'][0]['inputs'])
        self.assertFalse((self.batch/'runner.lock').exists())
        self.assertIn('ok', (self.batch/'1-stdout.log').read_text())

    def test_terminal_observation_includes_final_input_invalidation(self):
        self.plan['steps'].append(dict(self.plan['steps'][0], id='second', depends=['first'],
            inputs=['output'], artifacts=[], argv=[PYTHON, '-c', "open('input','w').write('changed')"]))
        self.path.write_text(json.dumps(self.plan))
        snapshots = []
        self.assertEqual(runner.run(self.path, self.batch, observe=snapshots.append), 1)
        self.assertTrue(snapshots[-1].terminal)
        self.assertEqual([a.status for a in snapshots[-1].attempts], ['invalidated', 'invalidated'])
        self.assertEqual(snapshots[-2].attempts[0].status, 'passed')

    def test_owned_windows_job_requires_native_held_session(self):
        if os.name != 'nt':
            with self.assertRaisesRegex(OSError, 'No owned native Windows'):
                runner.owned_windows_job()
        else:
            with patch.object(runner, '_SESSION_JOB', None):
                with self.assertRaisesRegex(OSError, 'No owned native Windows'):
                    runner.owned_windows_job()

    def test_resume_and_source_artifact_invalidation(self):
        self.assertEqual(self.execute(), 0)
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 1)
        (self.root / 'output').write_text('changed')
        self.assertEqual(self.execute(), 0)
        (self.root / 'input').write_text('changed')
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 3)
        self.assertIn('ok', (self.batch / '1-stdout.log').read_text())

    def test_failure_preserved_and_dependents_stopped(self):
        self.plan['steps'][0]['argv'] = [PYTHON, '-c', 'import sys; print("failure",file=sys.stderr); sys.exit(7)']
        self.plan['steps'].append(dict(self.plan['steps'][0], id='second', depends=['first']))
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.execute(), 1)
        attempts = self.status()['attempts']
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]['exit_code'], 7)
        self.assertEqual(attempts[1]['status'], 'failed')

    def test_timeout_and_mutation(self):
        self.plan['steps'][0].update(argv=[PYTHON, '-c', 'import time; time.sleep(5)'], timeout_seconds=.1)
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.status()['attempts'][0]['status'], 'timeout')

    def test_missing_artifact_fails(self):
        self.plan['steps'][0]['argv'] = [PYTHON, '-c', 'pass']
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.status()['attempts'][0]['error'], 'declared artifact missing')

    def test_directory_inputs_and_artifacts_are_recursive(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'nested').mkdir()
        member = source / 'nested' / 'file'
        member.write_text('one')
        self.plan['steps'][0].update(inputs=['source'], artifacts=['products'],
                                    argv=[PYTHON, '-c', "from pathlib import Path; Path('products').mkdir(exist_ok=True); Path('products/file').write_text('ok')"])
        self.assertEqual(self.execute(), 0)
        member.write_text('two')
        self.assertEqual(self.execute(), 0)
        (self.root / 'products/file').unlink()
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 3)

    def test_each_input_pattern_must_match_before_launch(self):
        self.plan['steps'][0]['inputs'] = ['input', 'absent*']
        self.plan['steps'].append(dict(self.plan['steps'][0], id='independent', inputs=['input']))
        self.assertEqual(self.execute(), 1)
        self.assertFalse((self.root / 'output').exists())
        self.assertEqual(self.status()['attempts'][0]['error'], 'declared input missing')
        self.assertEqual(len(self.status()['attempts']), 1)

    def test_glob_directory_membership_changes_invalidate_resume(self):
        folder = self.root / 'sources'
        folder.mkdir()
        (folder / 'one').write_text('one')
        self.plan['steps'][0]['inputs'] = ['sources/*']
        self.assertEqual(self.execute(), 0)
        (folder / 'two').write_text('two')
        self.assertEqual(self.execute(), 0)
        (folder / 'one').unlink()
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 3)

    def test_file_changes_while_hashing_fail_closed(self):
        original = runner.digest
        changed = False

        def mutate(path):
            nonlocal changed
            result = original(path)
            if path == self.root / 'input' and not changed:
                changed = True
                path.write_text('different size')
            return result

        with patch.object(runner, 'digest', mutate):
            self.assertEqual(self.execute(), 1)
        self.assertFalse((self.root / 'output').exists())
        self.assertIn('error:input', self.status()['attempts'][0]['inputs'])

    def test_relative_executable_is_resolved_from_root(self):
        self.plan['steps'][0]['argv'][0] = os.path.relpath(PYTHON, self.root)
        self.assertEqual(self.execute(), 0)
        self.assertEqual(Path(self.status()['attempts'][0]['runtime']['executable']), Path(PYTHON).resolve())

    def test_later_step_cannot_mutate_an_earlier_steps_inputs(self):
        self.plan['steps'].append(dict(self.plan['steps'][0], id='second', depends=['first'],
                                      inputs=['output'], artifacts=[],
                                      argv=[PYTHON, '-c', "open('input','w').write('changed')"]))
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.status()['attempts'][0]['status'], 'invalidated')
        self.assertEqual(self.status()['summary']['incomplete'], 2)

    def test_wait_error_stops_child(self):
        original = runner.wait_command
        child = None

        def fail_once(process, *args, **kwargs):
            nonlocal child
            if child is None:
                child = process
                raise OSError('wait failed')
            return original(process, *args, **kwargs)

        self.plan['steps'][0]['argv'] = [PYTHON, '-c', 'import time; time.sleep(5)']
        try:
            with patch.object(runner, 'wait_command', fail_once):
                self.assertEqual(self.execute(), 1)
            self.assertIsNotNone(child.returncode)
            attempt = self.status()['attempts'][0]
            self.assertEqual(attempt['status'], 'failed')
            self.assertEqual(attempt['error'], 'wait failed')
            self.assertNotIn('cleanup_unresolved', attempt)
            self.assertFalse((self.batch / 'runner.lock').exists())
        finally:
            if child is not None and child.poll() is None:
                runner.stop(child)

    def test_dependency_reruns_after_parent_artifact_change(self):
        self.plan['steps'].append(dict(self.plan['steps'][0], id='second', depends=['first'], artifacts=[]))
        self.assertEqual(self.execute(), 0)
        (self.root / 'output').write_text('changed')
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 4)

    def test_changes_during_command_invalidate_success(self):
        self.plan['steps'][0]['argv'] = [PYTHON, '-c', "open('input','w').write('new')"]
        self.assertEqual(self.execute(), 1)
        self.assertEqual(self.status()['attempts'][0]['status'], 'invalidated')

    def test_abandoned_running_attempt_is_never_reused(self):
        self.assertEqual(self.execute(), 0)
        state = self.status()
        state['attempts'][0]['status'] = 'running'
        runner.write_json(self.batch / 'status.json', state)
        self.assertEqual(self.execute(), 0)
        self.assertEqual(len(self.status()['attempts']), 2)

    def test_interrupt_stops_child_and_records_attempt(self):
        from unittest.mock import patch
        original = runner.wait_command
        calls = 0

        def interrupt_once(process, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt()
            return original(process, *args, **kwargs)

        self.plan['steps'][0]['argv'] = [PYTHON, '-c', 'import time; time.sleep(5)']
        with patch.object(runner, 'wait_command', interrupt_once):
            self.assertEqual(self.execute(), 1)
        self.assertEqual(self.status()['attempts'][0]['status'], 'interrupted')
        self.assertNotIn('cleanup_unresolved', self.status()['attempts'][0])
        self.assertFalse((self.batch / 'runner.lock').exists())

    def test_declared_stdin_preserves_bytes_and_invalidation(self):
        (self.root / 'prompt').write_bytes(b'first\nsecond\x00\xff')
        self.plan['steps'][0].update(stdin_file='prompt', inputs=['input', 'prompt'],
            argv=[PYTHON, '-c', "import sys; open('output','wb').write(sys.stdin.buffer.read())"])
        self.assertEqual(self.execute(), 0)
        self.assertEqual((self.root / 'output').read_bytes(), b'first\nsecond\x00\xff')
        (self.root / 'prompt').write_bytes(b'changed input')
        self.assertEqual(self.execute(), 0)
        self.assertEqual((self.root / 'output').read_bytes(), b'changed input')
        self.assertEqual(len(self.status()['attempts']), 2)

    def test_undeclared_stdin_rejected_before_launch(self):
        self.plan['steps'][0]['stdin_file'] = 'untracked-prompt'
        with self.assertRaisesRegex(ValueError, 'declared input'):
            self.execute()
        self.assertFalse(self.batch.exists())


if __name__ == '__main__':
    unittest.main()

