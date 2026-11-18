"""Tiny real-process checks for experiment gates, compact packets and resume."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name('experiment-cycle.py')
spec = importlib.util.spec_from_file_location('experiment_cycle', MODULE_PATH)
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)
PYTHON = str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'input.txt').write_text('input', encoding='utf-8')
        self.path = self.root / 'plan.json'
        self.batch = self.root / 'batch'
        self.plan = {
            'root': str(self.root), 'batch_timeout_seconds': 10,
            'estimated_seconds': 1, 'estimated_disk_bytes': 1024,
            'toolchains': {'python': sys.version}, 'features': [], 'fixtures': ['input.txt'],
            'experiment': {
                'question': 'Does the tiny control complete?', 'hypothesis': 'Both steps pass.',
                'decision_rule': 'Inspect verified output, not orchestration duration.',
                'stop_rule': 'Stop on first failure.', 'cohort': 'development',
            },
            'steps': [
                {'id': 'measure', 'phase': 'measure', 'inputs': ['input.txt'],
                 'artifacts': ['result.txt'], 'timeout_seconds': 3,
                 'argv': [PYTHON, '-c', "from pathlib import Path; print('RAW_LOG_' * 10000); Path('result.txt').write_text('ok')"]},
                {'id': 'verify', 'phase': 'verify', 'depends': ['measure'],
                 'inputs': ['input.txt', 'result.txt'], 'artifacts': [], 'timeout_seconds': 3,
                 'argv': [PYTHON, '-c', "from pathlib import Path; assert Path('result.txt').read_text() == 'ok'"]},
            ],
        }

    def execute(self):
        self.path.write_text(json.dumps(self.plan), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            return cycle.run(self.path, self.batch)

    def test_complete_packet_is_compact_and_resume_keeps_attempts(self):
        self.assertEqual(self.execute(), 0)
        result = cycle.packet(self.batch)
        self.assertEqual(result['outcome'], 'ready_for_interpretation')
        self.assertEqual(result['recommended_reasoning']['reasoningEffort'], 'high')
        self.assertEqual(result['attempts_retained'], 2)
        self.assertNotIn('RAW_LOG_', json.dumps(result))
        self.assertIn('RAW_LOG_', (self.batch / '1-stdout.log').read_text())
        self.assertIn('not complete-job', result['notice'])
        self.assertEqual(self.execute(), 0)
        self.assertEqual(cycle.packet(self.batch)['attempts_retained'], 2)

    def test_failure_preserves_exit_and_stops_verification(self):
        self.plan['steps'][0]['argv'] = [PYTHON, '-c', 'raise SystemExit(7)']
        self.assertEqual(self.execute(), 1)
        result = cycle.packet(self.batch)
        self.assertEqual(result['outcome'], 'incomplete')
        self.assertEqual(result['steps'][0]['exit_code'], 7)
        self.assertEqual(result['steps'][1]['status'], 'pending')
        self.assertEqual(result['recommended_reasoning']['reasoningEffort'], 'medium')

    def test_failed_verification_never_yields_interpretation_packet(self):
        self.plan['steps'][1]['argv'] = [PYTHON, '-c', 'raise SystemExit(8)']
        self.assertEqual(self.execute(), 1)
        result = cycle.packet(self.batch, limit=1)
        self.assertEqual(result['steps'][0]['phase'], 'verify')
        self.assertEqual(result['steps'][0]['exit_code'], 8)
        self.assertEqual(result['steps_omitted'], 1)
        self.assertEqual(result['outcome'], 'incomplete')

    def test_heldout_requires_frozen_rules_and_predictions_before_launch(self):
        self.plan['experiment']['cohort'] = 'held-out'
        with self.assertRaisesRegex(ValueError, 'frozen_rules'):
            self.execute()
        self.assertFalse(self.batch.exists())
        self.plan['experiment']['frozen_rules'] = 'rule version 1'
        with self.assertRaisesRegex(ValueError, 'predictions'):
            self.execute()
        self.plan['experiment']['predictions'] = 'Both steps pass.'
        self.assertEqual(self.execute(), 0)

    def test_changed_question_requires_new_batch(self):
        self.assertEqual(self.execute(), 0)
        self.plan['experiment']['question'] = 'A different question'
        with self.assertRaisesRegex(ValueError, 'original plan'):
            self.execute()
        self.assertFalse((self.batch / 'runner.lock').exists())

    def test_changed_driver_requires_new_batch_without_losing_evidence(self):
        self.assertEqual(self.execute(), 0)
        with patch.object(cycle, 'driver_identity', return_value={'changed': 'version'}):
            with self.assertRaisesRegex(ValueError, 'original plan'):
                self.execute()
        self.assertEqual(cycle.packet(self.batch)['attempts_retained'], 2)
        self.assertTrue((self.batch / '1-stdout.log').exists())

    def test_invalid_metadata_rejected_before_launch(self):
        self.plan['experiment'] = []
        with self.assertRaisesRegex(ValueError, 'must be an object'):
            self.execute()
        self.assertFalse(self.batch.exists())

    def test_missing_verifier_rejected_and_artifact_changes_rerun(self):
        original = self.plan['steps'].pop()
        with self.assertRaisesRegex(ValueError, 'verification'):
            self.execute()
        self.plan['steps'].append(original)
        self.assertEqual(self.execute(), 0)
        (self.root / 'result.txt').write_text('tampered', encoding='utf-8')
        self.assertEqual(self.execute(), 0)
        self.assertEqual(cycle.packet(self.batch)['attempts_retained'], 4)

    def test_cli_policy_and_packet_do_not_execute_commands(self):
        result = subprocess.run([PYTHON, str(MODULE_PATH), 'policy'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['execute'], {'executor': 'code'})
        self.assertFalse(self.batch.exists())
        self.assertEqual(self.execute(), 0)
        result = subprocess.run([PYTHON, str(MODULE_PATH), 'packet', str(self.batch)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['attempts_retained'], 2)


if __name__ == '__main__':
    unittest.main()
