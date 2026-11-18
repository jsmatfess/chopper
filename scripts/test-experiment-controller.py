"""Tiny real subprocess acceptance controls. Evidence is retained in scratch/."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import experiment_session as session
import experiment_codex

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable
SCRIPT = ROOT / 'scripts/experiment-controller.py'
EVIDENCE = Path(tempfile.mkdtemp(prefix='controller-tests-', dir=ROOT / 'scratch'))


@unittest.skipUnless(os.name == 'nt', 'native Windows is the supported controller runtime')
class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.root = EVIDENCE / self._testMethodName
        self.root.mkdir()
        self.directory = self.root / 'session'
        (self.root / 'fixture').write_text('tiny control')
        self.config_path = self.root / 'config.json'
        self.config = {'schema_version': 1, 'root': str(self.root), 'provider': 'file',
                       'first': 'a', 'seconds': 30, 'storage_bytes': 4 * 1024**2,
                       'max_batches': 3, 'max_runs': 3, 'max_decisions': 3, 'batches': []}
        for index, name in enumerate(('a', 'b', 'c')):
            output = f'session/data-{name}'
            record = output + '/sample.json'
            plan = {'root': str(self.root), 'batch_timeout_seconds': 5, 'estimated_seconds': 1,
                    'estimated_disk_bytes': 1024, 'toolchains': {'python': PYTHON},
                    'features': [], 'fixtures': ['fixture'],
                    'experiment': {'question': 'Does the tiny process control finish?',
                                   'hypothesis': 'The declared control is independently verified.',
                                   'decision_rule': 'No performance claim; stop after controls.',
                                   'stop_rule': 'Stop on any failure.', 'cohort': 'development'},
                    'steps': [
                        {'id': 'measure', 'phase': 'measure', 'inputs': ['fixture'],
                         'artifacts': [output], 'timeout_seconds': 3,
                         'argv': [PYTHON, '-c', f"from pathlib import Path; p=Path({record!r}); p.parent.mkdir(); p.write_text('{{\"elapsed_seconds\":0.01}}'); print('retained raw control log')"]},
                        {'id': 'verify', 'phase': 'verify', 'inputs': ['fixture', record],
                         'artifacts': [], 'timeout_seconds': 2, 'depends': ['measure'],
                         'argv': [PYTHON, '-c', f"import json; assert json.load(open({record!r}))['elapsed_seconds']==0.01"]}]}
            path = self.root / f'{name}.json'
            path.write_text(json.dumps(plan))
            self.config['batches'].append({'id': name, 'kind': 'initial' if index == 0 else 'repeat',
                'parent': None if index == 0 else ('a', 'b')[index-1], 'plan': str(path),
                'outputs': [output], 'storage_reserve_bytes': 16384,
                'metrics': [{'path': record, 'pointer': '/elapsed_seconds', 'unit': 'seconds',
                             'scope': 'synthetic orchestration control; not benchmark time', 'cell': 'control'}]})

    def launch(self, initial=True, choice=None):
        argv = [PYTHON, str(SCRIPT), 'run', str(self.directory)]
        if initial:
            self.config_path.write_text(json.dumps(self.config))
            argv += ['--config', str(self.config_path)]
        if choice is not None:
            path = self.root / 'decision.json'
            path.write_text(json.dumps(choice))
            argv += ['--decision', str(path)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        number = len(list(self.root.glob('call-*.log')))
        (self.root / f'call-{number}.log').write_text(result.stdout + '\nSTDERR\n' + result.stderr)
        return result

    def state(self):
        return session.read(self.directory / 'controller-status.json')

    def choice(self, action='repeat', target='b', assessment='useful'):
        packet = self.directory / self.state()['packet']
        return {'action': action, 'target': target, 'assessment': assessment, 'reason': 'tiny control decision',
                'packet_sha256': hashlib.sha256(packet.read_bytes()).hexdigest()}

    def mutate_plan(self, fn):
        path = Path(self.config['batches'][0]['plan'])
        plan = session.read(path)
        fn(plan)
        path.write_text(json.dumps(plan))

    def test_offline_resume_metrics_and_preservation(self):
        self.assertEqual(self.launch().returncode, 0)
        state = self.state()
        self.assertEqual(state['status'], 'decision-needed')
        packet = session.read(self.directory / state['packet'])
        self.assertLessEqual((self.directory / state['packet']).stat().st_size, 32768)
        self.assertEqual(packet['metrics']['summaries'][0]['n'], 1)
        self.assertEqual(packet['metrics']['summaries'][0]['median'], .01)
        log = self.directory / 'batch-a/1-stdout.log'
        original = log.read_bytes()
        self.assertEqual(self.launch(False, self.choice()).returncode, 0)
        self.assertEqual(self.state()['runs'], 2)
        self.assertEqual(log.read_bytes(), original)
        self.assertEqual(self.launch(False, self.choice('stop', None)).returncode, 0)
        self.assertEqual(self.state()['status'], 'stopped')

    def test_predeclared_unattended_queue(self):
        self.config['provider'] = 'predeclared'
        self.config['decisions'] = [dict(action='repeat', target='b', assessment='useful', reason='control'),
                                    dict(action='stop', target=None, assessment='useful', reason='done')]
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.state()['launched'], ['a', 'b'])
        self.assertEqual(self.state()['status'], 'stopped')

    def test_time_budget_is_cumulative_across_resume(self):
        self.assertEqual(self.launch().returncode, 0)
        state = self.state()
        state['started_unix'] -= 60
        session.write(self.directory / 'controller-status.json', state)
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'time-budget')
        self.assertEqual(self.state()['runs'], 1)

    def test_run_budget_across_resume(self):
        self.config['max_runs'] = 1
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice()).returncode, 1)
        self.assertEqual(self.state()['status'], 'run-or-batch-budget')

    def test_storage_real_census_and_preservation(self):
        self.assertEqual(self.launch().returncode, 0)
        spill = self.directory / 'unexpected.bin'
        spill.write_bytes(b'x' * self.config['storage_bytes'])
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'storage-budget')
        self.assertTrue(spill.exists())

    def test_live_storage_guard_stops_process(self):
        self.mutate_plan(lambda p: p['steps'][0].update(argv=[PYTHON, '-c',
            "from pathlib import Path; import time; Path('session/big').write_bytes(b'x'*5000000); time.sleep(10)"]))
        self.assertEqual(self.launch().returncode, 1)
        self.assertEqual(self.state()['status'], 'storage-budget')
        self.assertTrue((self.directory / 'big').exists())

    def test_exclusive_ownership(self):
        self.directory.mkdir()
        with session.ownership(self.directory):
            result = self.launch()
            self.assertEqual(result.returncode, 2)
            self.assertFalse((self.directory / 'controller-status.json').exists())

    def test_crash_recovery_never_relaunches_ambiguous_attempt(self):
        self.assertEqual(self.launch().returncode, 0)
        state = self.state()
        state['status'] = 'running'
        state['events'].append({'kind': 'launch', 'unix': time.time()})
        session.write(self.directory / 'controller-status.json', state)
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'interrupted-review-required')
        self.assertEqual(len(session.read(self.directory / 'batch-a/status.json')['attempts']), 2)

    def test_malformed_decision_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        choice = self.choice()
        choice['arbitrary_command'] = 'forbidden'
        self.assertEqual(self.launch(False, choice).returncode, 1)
        self.assertEqual(self.state()['status'], 'invalid-decision-or-manifest')

    def test_out_of_scope_decision_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice('challenger', 'b')).returncode, 1)
        self.assertEqual(self.state()['runs'], 1)

    def test_repeated_decision_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice()).returncode, 0)
        self.assertEqual(self.launch(False, self.choice()).returncode, 1)
        self.assertIn('repeated identical', self.state()['events'][-2]['error'])

    def test_inconclusive_loop_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice(assessment='inconclusive')).returncode, 0)
        self.assertEqual(self.launch(False, self.choice(target='c', assessment='inconclusive')).returncode, 1)
        self.assertEqual(self.state()['status'], 'diminishing-value')
        self.assertEqual(self.state()['runs'], 2)

    def test_verification_failure_is_not_sample(self):
        self.mutate_plan(lambda p: p['steps'][1].update(argv=[PYTHON, '-c', 'raise SystemExit(7)']))
        self.assertEqual(self.launch().returncode, 1)
        self.assertEqual(self.state()['status'], 'correctness-failure')
        self.assertNotIn('packet', self.state())
        self.assertTrue((self.directory / 'batch-a/2-stderr.log').exists())

    def test_infrastructure_failure_does_not_label_pending_verify(self):
        self.mutate_plan(lambda p: p['steps'][0].update(argv=['nonexistent-controller-test-command']))
        self.assertEqual(self.launch().returncode, 1)
        self.assertEqual(self.state()['status'], 'infrastructure-failure')
        self.assertNotIn('packet', self.state())

    def test_source_invalidation_stops_without_overwrite(self):
        self.assertEqual(self.launch().returncode, 0)
        (self.root / 'fixture').write_text('changed')
        self.assertEqual(self.launch(False).returncode, 2)
        self.assertEqual(self.state()['status'], 'source-or-artifact-invalidated')
        self.assertTrue((self.directory / 'batch-a/1-stdout.log').exists())

    def test_artifact_invalidation_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        (self.directory / 'data-a/sample.json').write_text('{}')
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'source-or-artifact-invalidated')

    def test_copy_path_mismatch_rejected_before_launch(self):
        self.mutate_plan(lambda p: p['steps'][0].update(artifacts=['old-copy/result.json']))
        self.assertEqual(self.launch().returncode, 2)
        self.assertFalse((self.directory / 'batch-a').exists())

    def test_stop_command(self):
        self.assertEqual(self.launch().returncode, 0)
        subprocess.run([PYTHON, str(SCRIPT), 'stop', str(self.directory)], check=True)
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'stop-request')

    @unittest.skipUnless(os.name == 'nt', 'Windows native controller crash containment')
    def test_hard_crash_kills_child_and_resume_preserves_attempt(self):
        self.mutate_plan(lambda p: p['steps'][0].update(argv=[PYTHON, '-c',
            "from pathlib import Path; import os,time; Path('session/child.pid').write_text(str(os.getpid())); time.sleep(60)"]))
        self.config_path.write_text(json.dumps(self.config))
        with (self.root / 'crash-stdout.log').open('w') as out, (self.root / 'crash-stderr.log').open('w') as err:
            process = subprocess.Popen([PYTHON, str(SCRIPT), 'run', str(self.directory), '--config', str(self.config_path)],
                                       stdout=out, stderr=err)
            try:
                deadline = time.monotonic() + 8
                while not (self.directory / 'child.pid').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue((self.directory / 'child.pid').exists())
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                child = kernel.OpenProcess(0x100000, False, int((self.directory / 'child.pid').read_text()))
                self.assertTrue(child)
                try:
                    process.kill()
                    process.wait(timeout=5)
                    self.assertEqual(kernel.WaitForSingleObject(child, 5000), 0)
                finally:
                    kernel.CloseHandle(child)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'interrupted-review-required')
        self.assertEqual(self.state()['runs'], 1)
        self.assertEqual(len(session.read(self.directory / 'batch-a/status.json')['attempts']), 1)

    def test_packet_tampering_stops(self):
        self.assertEqual(self.launch().returncode, 0)
        choice = self.choice()
        packet = self.directory / self.state()['packet']
        packet.write_text('{}')
        self.assertEqual(self.launch(False, choice).returncode, 1)
        self.assertEqual(self.state()['runs'], 1)

    def test_native_job_copy_mismatch_rejected_before_launch(self):
        job_path = self.root / 'job.json'
        job_path.write_text(json.dumps({'output': str(self.root / 'old/output'),
            'input': str(self.root / 'fixture'), 'resources': {'temp_dir': str(self.directory / 'data-a/temp')}}))
        self.mutate_plan(lambda p: p['steps'][0].update(argv=[PYTHON, 'workload-baselines.py', 'run-native',
            PYTHON, str(job_path), '--record', str(self.directory / 'data-a/sample.json')]))
        self.assertEqual(self.launch().returncode, 2)
        self.assertFalse((self.directory / 'batch-a').exists())

    def test_invalid_decision_hash_and_scientific_rejection(self):
        self.assertEqual(self.launch().returncode, 0)
        choice = self.choice()
        choice['packet_sha256'] = 'bad'
        self.assertEqual(self.launch(False, choice).returncode, 1)
        self.assertEqual(self.state()['runs'], 1)

    def test_model_settings_do_not_change_runtime(self):
        self.assertEqual(self.launch().returncode, 0)
        choice = self.choice()
        choice['model'] = 'unasked-model'
        self.assertEqual(self.launch(False, choice).returncode, 1)

    def test_scientific_rejection_stops_without_infrastructure_label(self):
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice(assessment='rejected')).returncode, 1)
        self.assertEqual(self.state()['status'], 'scientific-rejection')
        self.assertEqual(self.state()['runs'], 1)

    def test_decision_budget_across_resume(self):
        self.config['max_decisions'] = 1
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice()).returncode, 1)
        self.assertEqual(self.state()['status'], 'decision-budget')
        self.assertEqual(self.state()['runs'], 2)

    def test_missing_dependent_verifier_and_duplicate_samples_rejected(self):
        self.mutate_plan(lambda p: p['steps'][1].update(depends=[]))
        self.assertEqual(self.launch().returncode, 2)
        self.assertFalse((self.directory / 'batch-a').exists())

    def test_copied_duplicate_metrics_are_not_extra_observations(self):
        self.config['batches'][0]['metrics'] *= 2
        self.assertEqual(self.launch().returncode, 2)
        self.assertFalse((self.directory / 'batch-a').exists())

    def test_missing_source_resume_stops_and_journals(self):
        self.assertEqual(self.launch().returncode, 0)
        (self.root / 'fixture').unlink()
        self.assertEqual(self.launch(False).returncode, 2)
        self.assertEqual(self.state()['status'], 'source-or-artifact-invalidated')
        self.assertEqual(self.state()['events'][-1]['kind'], 'manifest-revalidation-failed')

    def test_setup_rejection_keeps_initial_accounting(self):
        self.config['storage_bytes'] = 0
        self.assertEqual(self.launch().returncode, 2)
        before = self.state()['started_unix']
        self.assertEqual(self.launch(False).returncode, 2)
        self.assertEqual(self.state()['started_unix'], before)

    def test_codex_adapter_fake_subprocess_retains_response_and_usage(self):
        self.assertEqual(self.launch().returncode, 0)
        settings = {'executable': PYTHON, 'model': 'fake-test-model', 'reasoning_effort': 'high', 'timeout_seconds': 5}
        code = ("import sys,json,re; from pathlib import Path; p=sys.stdin.read(); "
                "h=re.search('Set packet_sha256 to ([0-9a-f]{64})',p).group(1); "
                "Path('response.json').write_text(json.dumps(dict(action='stop',target=None,assessment='inconclusive',"
                "reason='FAKE provider test only',packet_sha256=h))); "
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':3}}))")
        with patch.object(experiment_codex, 'command', return_value=[PYTHON, '-c', code]):
            choice, metadata = experiment_codex.run(settings, self.directory / self.state()['packet'],
                self.directory / 'fake-provider', session.cycle.runner, lambda: None)
        self.assertEqual(choice['action'], 'stop')
        self.assertEqual(metadata['usage'], {'input_tokens': 12, 'output_tokens': 3})
        self.assertIsNone(metadata['returned_model'])
        self.assertTrue((self.directory / 'fake-provider/runner/1-stdout.log').exists())

    def test_codex_adapter_failure_is_retained_without_fallback(self):
        self.assertEqual(self.launch().returncode, 0)
        settings = {'executable': PYTHON, 'model': 'fake-test-model', 'reasoning_effort': 'high', 'timeout_seconds': 5}
        with patch.object(experiment_codex, 'command', return_value=[PYTHON, '-c', 'raise SystemExit(9)']):
            with self.assertRaisesRegex(OSError, 'Codex decision invocation failed'):
                experiment_codex.run(settings, self.directory / self.state()['packet'],
                    self.directory / 'failed-provider', session.cycle.runner, lambda: None)
        self.assertIsNone(session.read(self.directory / 'failed-provider/provider-record.json')['usage'])
        self.assertTrue((self.directory / 'failed-provider/runner/1-stderr.log').exists())

    def test_codex_requires_explicit_settings_and_xhigh_escalation(self):
        self.config['provider'] = 'codex'
        self.assertEqual(self.launch().returncode, 2)
        self.config['codex'] = {'executable': PYTHON, 'model': 'fake-test-model',
                                'reasoning_effort': 'xhigh', 'timeout_seconds': 5}
        self.assertEqual(self.launch().returncode, 2)

    def test_predeclared_provider_does_not_mislabel_file_override(self):
        self.config['provider'] = 'predeclared'
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual(self.launch(False, self.choice()).returncode, 1)
        self.assertEqual(self.state()['status'], 'invalid-decision-or-manifest')

    def test_interrupted_provider_request_is_not_reissued(self):
        self.assertEqual(self.launch().returncode, 0)
        state = self.state()
        state['events'].append({'kind': 'provider-request', 'unix': time.time()})
        session.write(self.directory / 'controller-status.json', state)
        self.assertEqual(self.launch(False).returncode, 1)
        self.assertEqual(self.state()['status'], 'interrupted-review-required')
        self.assertEqual(self.state()['runs'], 1)


if __name__ == '__main__':
    print('Retained controller test evidence:', EVIDENCE, flush=True)
    unittest.main()
