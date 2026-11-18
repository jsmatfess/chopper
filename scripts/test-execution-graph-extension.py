"""Exact bootstrap and provenance regressions for one retained-data extension."""
import importlib.util
import itertools
import hashlib
import json
import subprocess
import sys
import tempfile
import math
from pathlib import Path
import statistics
import unittest


def load_statistics():
    path = Path(__file__).with_name('execution_graph_statistics.py')
    spec = importlib.util.spec_from_file_location('execution_graph_statistics', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExactBootstrapTests(unittest.TestCase):
    def test_weighted_distribution_matches_every_ordered_six_block_resample(self):
        baseline = [45, 45, 48, 45, 53, 55]
        enabled = [45, 45, 45, 55, 64, 63]
        ratios = sorted(
            statistics.median(enabled[i] for i in indices)
            / statistics.median(baseline[i] for i in indices) - 1
            for indices in itertools.product(range(6), repeat=6)
        )
        expected = ratios[math.ceil(.95 * len(ratios)) - 1]
        self.assertEqual(load_statistics().paired_bootstrap_upper95(baseline, enabled), expected)

    def test_twelve_blocks_preserve_known_effect(self):
        self.assertAlmostEqual(
            load_statistics().paired_bootstrap_upper95([100] * 12, [104] * 12), .04
        )

    def test_old_regression_is_retained_when_six_faster_blocks_are_added(self):
        values = [110] * 6 + [104] * 6
        self.assertGreater(statistics.median(values) / 100 - 1, .05)
        self.assertGreater(load_statistics().paired_bootstrap_upper95([100] * 12, values), .05)

    def test_conservative_simulation_preserves_known_eighteen_block_effect(self):
        result = load_statistics().paired_bootstrap_conservative_upper95(
            [100] * 18, [104] * 18, resamples=20000, seed=735780)
        self.assertAlmostEqual(result['upper95_slowdown'], .04)
        self.assertGreater(result['sampled_quantile_level'], .95)
        self.assertEqual(result['simulation_error_probability'], 1e-6)
        self.assertEqual(result['runtime']['implementation'], sys.implementation.name)
        self.assertEqual(result['runtime']['python_version'], sys.version)
        self.assertEqual(len(result['runtime']['random_module']['sha256']), 64)
        with self.assertRaises(ValueError):
            load_statistics().paired_bootstrap_conservative_upper95([100], [104], resamples=1000001, seed=735780)

    def test_conservative_simulation_covers_exact_six_block_reference(self):
        module = load_statistics()
        baseline = [45, 45, 48, 45, 53, 55]
        enabled = [45, 45, 45, 55, 64, 63]
        exact = module.paired_bootstrap_upper95(baseline, enabled)
        result = module.paired_bootstrap_conservative_upper95(
            baseline, enabled, resamples=20000, seed=735780)
        self.assertGreaterEqual(result['upper95_slowdown'], exact)
        self.assertGreaterEqual(result['upper95_slowdown'], result['estimated_upper95_slowdown'])

    def test_reject_unmatched_or_unbounded_inputs(self):
        calculate = load_statistics().paired_bootstrap_upper95
        for baseline, enabled in [([100], []), ([0], [1]), ([100] * 13, [102] * 13)]:
            with self.assertRaises(ValueError):
                calculate(baseline, enabled)


def cohort(root, name, workload_ids, old_regression=False, changed_asset=False, changed_seed=False, changed_browser=False, changed_fixture=False, changed_artifact=False):
    plan = {'job_deadline_seconds': 300, 'workloads': [{'id': w} for w in workload_ids], 'blocks': []}
    for index, modes in enumerate(itertools.permutations(['disabled', 'collapsed', 'expanded'])):
        for w in workload_ids:
            plan['blocks'].append({'id': f'{w}-{index}', 'workload': w, 'modes': list(modes)})
    path = root / (name + '-plan.json')
    path.write_text(json.dumps(plan))
    records = [{'kind': 'context', 'plan_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'assets': {'engine.wasm': 'changed' if changed_asset else 'fixed'},
                'harness_sha256': 'fixed-harness', 'fixtures': {w: {'sha256': ('changed-' if changed_fixture else 'fixture-') + w} for w in workload_ids},
                'environment': {'browser_executable': 'test-browser', 'browser_executable_sha256': 'b' * 64}}]
    for block in plan['blocks']:
        records.append({'kind': 'browser_identity', 'block': block['id'], 'executable': 'test-browser',
                        'sha256': 'b' * 64, 'version': 'changed-version' if changed_browser else 'test-version'})
        for mode in block['modes']:
            w = block['workload']
            common = {'sample': block['id'] + '-' + mode, 'block': block['id'], 'workload': w,
                      'mode': mode, 'browserVersion': 'changed-version' if changed_browser else 'test-version'}
            job = {'seed': ('changed-' if changed_seed else 'fixed-') + w, 'output': name + block['id']}
            records.append({'kind': 'attempt', **common, 'job': job,
                            'job_sha256': hashlib.sha256(json.dumps(job, separators=(',', ':')).encode()).hexdigest()})
            seconds = 100 if mode == 'disabled' else 110 if old_regression and w == '3' and mode == 'expanded' else 104
            records.append({'kind': 'measurement', **common, 'status': 'COMPLETE', 'elapsed_seconds': seconds})
            records.append({'kind': 'verification', **common, 'ordered_artifact_sha256': ('changed-' if changed_artifact else 'artifact-') + w})
    records.append({'kind': 'batch_complete'})
    raw = root / (name + '-raw.jsonl')
    raw.write_text(''.join(json.dumps(row) + '\n' for row in records).replace('\n', '\n\n', 1))
    return path, raw


class ExtensionProvenanceTests(unittest.TestCase):
    def run_extension(self, change=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = cohort(root, 'old', ['0', '1', '2', '3'], old_regression=True)
            new = old if change == 'duplicate' else cohort(
                root, 'new', ['3'], changed_asset=change == 'asset', changed_seed=change == 'seed', changed_browser=change == 'browser',
                changed_fixture=change == 'fixture', changed_artifact=change == 'artifact')
            if change == 'reencoded':
                new_raw = root / 'reencoded.jsonl'
                new_raw.write_text(''.join(json.dumps(json.loads(line), separators=(',', ':')) + '\n' for line in old[1].read_text().splitlines() if line.strip()))
                new = (old[0], new_raw)
            out = root / 'summary.json'
            script = Path(__file__).with_name('extend-execution-graph-analysis.py')
            result = subprocess.run([sys.executable, str(script), *map(str, old), *map(str, new), str(out)],
                                    capture_output=True, text=True)
            return result, json.loads(out.read_text()) if out.exists() else None

    def test_retains_all_old_samples_and_does_not_replace_failed_cell(self):
        result, summary = self.run_extension()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary['verified_jobs'], 90)
        self.assertEqual(summary['samples'][0]['raw_line'], 5)
        self.assertFalse(summary['gate_pass'])
        cell = next(c for c in summary['cells'] if c['workload'] == '3' and c['mode'] == 'expanded')
        self.assertEqual(cell['n'], 12)
        self.assertEqual(cell['enabled_seconds'], [110] * 6 + [104] * 6)
        self.assertAlmostEqual(cell['median_slowdown'], .07)

    def test_rejects_changed_build(self):
        result, summary = self.run_extension('asset')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('build', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_changed_configuration(self):
        result, summary = self.run_extension('seed')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('configuration', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_changed_fixture(self):
        result, summary = self.run_extension('fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fixture', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_changed_seeded_artifacts(self):
        result, summary = self.run_extension('artifact')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('artifact', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_changed_actual_browser_version(self):
        result, summary = self.run_extension('browser')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('browser', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_reencoded_duplicate_observations(self):
        result, summary = self.run_extension('reencoded')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr.lower())
        self.assertIsNone(summary)

    def test_rejects_duplicated_original_as_new_observations(self):
        result, summary = self.run_extension('duplicate')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr.lower())
        self.assertIsNone(summary)


class FinalPrecisionTests(unittest.TestCase):
    def run_final(self, duplicate=False, already_passed=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = cohort(root, 'old', ['0', '1', '2', '3'], old_regression=not already_passed)
            added = cohort(root, 'added', ['3'])
            final = added if duplicate else cohort(root, 'final', ['3'])
            out = root / 'final-summary.json'
            script = Path(__file__).with_name('final-execution-graph-analysis.py')
            result = subprocess.run([sys.executable, str(script), *map(str, old), *map(str, added),
                                     *map(str, final), str(out), '--resamples=10000'],
                                    capture_output=True, text=True)
            return result, json.loads(out.read_text()) if out.exists() else None

    def test_final_analysis_keeps_every_old_sample_and_conservative_bound(self):
        result, summary = self.run_final()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary['verified_jobs'], 108)
        self.assertEqual(len(summary['samples']), 108)
        cell = next(c for c in summary['cells'] if c['workload'] == '3' and c['mode'] == 'expanded')
        self.assertEqual(cell['n'], 18)
        self.assertEqual(cell['enabled_seconds'], [110] * 6 + [104] * 12)
        self.assertGreaterEqual(cell['paired_bootstrap_upper95_slowdown'], .10 - 1e-12)
        self.assertFalse(cell['gate_pass'])
        self.assertEqual(cell['bootstrap_simulation']['seed'], 735780)
        self.assertEqual(summary['samples'][0]['raw_line'], 5)

    def test_final_analysis_cannot_extend_an_already_accepted_workload(self):
        result, summary = self.run_final(already_passed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('still-unmet', result.stderr.lower())
        self.assertIsNone(summary)

    def test_final_analysis_rejects_reused_extension_as_new_jobs(self):
        result, summary = self.run_final(duplicate=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr.lower())
        self.assertIsNone(summary)


if __name__ == '__main__':
    unittest.main()
