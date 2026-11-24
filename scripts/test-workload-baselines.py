"""Independent small fixtures and corruption controls for workload baselines."""
import csv
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workload_entities import HEADER, generate, row_at, sha256

spec = importlib.util.spec_from_file_location('baselines', Path(__file__).with_name('workload-baselines.py'))
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
PARAMETERS = {'rows': 40, 'seed': 'test-v1', 'regions': 3, 'hot_percent': 30,
              'notes_min': 32, 'notes_max': 64}


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'data'
        baseline.prepare(self.root, PARAMETERS)

    def fixture(self, case='ordered', browser=False):
        job_path = self.root / (case + '.json')
        job = baseline.read_json(job_path)
        folder = Path(job['output'])
        folder.mkdir()
        with (self.root / 'entities.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.reader(stream))[1:]
        entries = []
        if case == 'ordered':
            groups = [(rows, [])]
        else:
            groups = []
            for region in sorted({r[1] for r in rows}):
                for arm in ('treatment', 'control'):
                    # A deliberately simple partition of test rows: verifier
                    # must not enforce 80/20 quotas for probabilistic allocation.
                    selected = [r for r in rows if r[1] == region] if arm == 'treatment' else []
                    groups.append((list(reversed(selected)), [
                        {'operation': 0, 'values': [region]}, {'operation': 1, 'allocation': arm}]))
        for index, (selected, lineage) in enumerate(groups):
            path = folder / f'part-{index:08}.csv'
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(HEADER)
                writer.writerows(selected)
            entries.append({'type': 'output', 'path': path.name, 'rows': len(selected),
                            'csv_bytes': path.stat().st_size, 'stored_bytes': path.stat().st_size,
                            'lineage': lineage})
        records = [{'type': 'job', 'algorithm_version': 'test-v1', 'config': job,
                    'analysis': {'rows': len(rows)}}] + entries
        self.save_manifest(folder, records)
        if browser:
            baseline.write_new(folder / 'CHOPPER-COMPLETE.json',
                               {'complete': True, 'engine': 'chopper-browser', 'version': 1, 'files': len(entries) + 1})
        return job_path, folder, records

    def save_manifest(self, folder, records):
        (folder / 'manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')

    def test_generation_replay_prefix_stability_and_csv_edge_fields(self):
        other = self.root / 'other.csv'
        generate(other, PARAMETERS)
        self.assertEqual(sha256(other), sha256(self.root / 'entities.csv'))
        self.assertEqual(sha256(other), '877cb459a416f5be6107414685e45c76c4215abc3a4193c2230376733c70e488')
        extended = dict(PARAMETERS, rows=100)
        self.assertEqual(row_at(17, PARAMETERS), row_at(17, extended))
        self.assertIn('\n', row_at(17, PARAMETERS)[6])
        self.assertIn('"', row_at(1, PARAMETERS)[5])
        with self.assertRaises(FileExistsError):
            generate(other, PARAMETERS)

    def test_ordered_output_fields_and_manifest(self):
        job, _, _ = self.fixture()
        self.assertEqual(baseline.verify(job)['rows'], PARAMETERS['rows'])

    def test_field_corruption_detected_even_with_matching_sizes(self):
        job, folder, _ = self.fixture()
        path = next(folder.glob('*.csv'))
        content = path.read_bytes().replace(b'Market', b'Markex', 1)
        path.write_bytes(content)
        with self.assertRaisesRegex(ValueError, 'field values changed'):
            baseline.verify(job)

    def test_reordered_rows_rejected_for_ordered_export(self):
        job, folder, records = self.fixture()
        path = folder / records[1]['path']
        with path.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.reader(stream))
        rows[1], rows[2] = rows[2], rows[1]
        with path.open('w', encoding='utf-8', newline='') as stream:
            csv.writer(stream, lineterminator='\n').writerows(rows)
        with self.assertRaisesRegex(ValueError, 'row order'):
            baseline.verify(job)

    def test_campaign_empty_arms_conservation_and_partition_lineage(self):
        job, folder, records = self.fixture('campaign')
        result = baseline.verify(job)
        self.assertTrue(any(group['rows'] == 0 for group in result['populations']))
        records[1]['lineage'][0]['values'] = ['wrong-region']
        self.save_manifest(folder, records)
        with self.assertRaisesRegex(ValueError, 'wrong region'):
            baseline.verify(job)

    def test_missing_empty_named_arm_detected(self):
        job, folder, records = self.fixture('campaign')
        missing = next(r for r in records[1:] if r['rows'] == 0)
        records.remove(missing)
        (folder / missing['path']).unlink()
        self.save_manifest(folder, records)
        with self.assertRaisesRegex(ValueError, 'missing named group'):
            baseline.verify(job)

    def test_browser_marker_required_and_unlisted_output_rejected(self):
        job, folder, _ = self.fixture(browser=True)
        self.assertTrue(baseline.verify(job, browser=True)['verified'])
        (folder / 'extra.csv').write_text('unexpected', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unlisted'):
            baseline.verify(job, browser=True)
        (folder / 'extra.csv').unlink()
        (folder / 'CHOPPER-COMPLETE.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'completion marker'):
            baseline.verify(job, browser=True)

    def test_invalid_generation_and_baseline_limits(self):
        with self.assertRaises(ValueError):
            generate(self.root / 'bad.csv', dict(PARAMETERS, notes_min=80, notes_max=10))
        self.assertFalse((self.root / 'bad.csv').exists())
        with self.assertRaises(ValueError):
            baseline.prepare(self.root / 'too-large', dict(PARAMETERS, rows=10**9))

    def test_independent_encoder_empty_unicode_quote_and_multiline(self):
        self.assertEqual(baseline.csv_bytes(['', 'a,b', 'q"r', 'é', 'new\nline']),
                         b'"","a,b","q""r",\xc3\xa9,"new\nline"\n')

    def test_strict_caps_are_checked_against_encoded_output(self):
        job_path, folder, records = self.fixture()
        job = baseline.read_json(job_path)
        job['limits']['bytes'] = 100
        job_path.write_text(json.dumps(job), encoding='utf-8')
        records[0]['config'] = job
        self.save_manifest(folder, records)
        with self.assertRaisesRegex(ValueError, 'strict serialized byte cap'):
            baseline.verify(job_path)

    def test_runtime_plans_have_independent_owned_fixtures_and_verifiers(self):
        workspace = self.root.parent
        with patch.object(baseline, 'ROOT', workspace):
            path = workspace / 'scratch/plans'
            baseline.make_plans(path, workspace / 'chopper', 'node', PARAMETERS)
        plans = [baseline.read_json(path / (runtime + '-plan.json')) for runtime in ('native', 'browser')]
        generated = [plan['steps'][0]['argv'][3] for plan in plans]
        self.assertNotEqual(*generated)
        for plan in plans:
            self.assertEqual(len(plan['steps']), 5)
            self.assertEqual([step['phase'] for step in plan['steps']],
                             ['prepare', 'measure', 'verify', 'measure', 'verify'])
            self.assertEqual(plan['experiment']['cohort'], 'development')

        for runtime in ('native', 'browser'):
            build = baseline.read_json(path / (runtime + '-build-plan.json'))
            inputs = build['steps'][0]['inputs']
            self.assertTrue({'Cargo.toml', 'Cargo.lock', 'crates', 'vendor'} <= set(inputs))
            self.assertFalse(any(item.startswith('ui/') for item in inputs))
            if runtime == 'browser':
                hosted = build['steps'][1]['inputs']
                self.assertTrue({'ui/src', 'ui/index.html', 'ui/style.css',
                    'ui/package.json', 'ui/package-lock.json', 'ui/dist/engine.wasm',
                    'scripts/build-hosted.mjs', 'scripts/browser-artifacts.mjs',
                    'scripts/hosted-theme.mjs', 'docs/releases/native-usage.txt',
                    'docs/formula-functions.md'} <= set(hosted))

    def test_cross_runtime_parity_checks_recipe_and_output_bytes(self):
        first, _, _ = self.fixture()
        second_root = self.root.parent / 'browser'
        baseline.prepare(second_root, PARAMETERS)
        self.root = second_root
        second, output, _ = self.fixture(browser=True)
        self.assertTrue(baseline.parity(first, second, output)['parity_verified'])
        job = baseline.read_json(second)
        job['seed'] = 'different'
        second.write_text(json.dumps(job), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'identical semantic/seeded recipes'):
            baseline.parity(first, second, output)

    def test_premature_chunk_boundary_rejected(self):
        job, folder, records = self.fixture()
        path = folder / records[1]['path']
        with path.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.reader(stream))
        midpoint = len(rows) // 2
        records = records[:1]
        for index, selected in enumerate((rows[1:midpoint], rows[midpoint:])):
            path = folder / f'part-{index:08}.csv'
            path.write_bytes(baseline.csv_bytes(HEADER) + b''.join(baseline.csv_bytes(r) for r in selected))
            records.append({'type': 'output', 'path': path.name, 'rows': len(selected),
                            'csv_bytes': path.stat().st_size, 'stored_bytes': path.stat().st_size, 'lineage': []})
        self.save_manifest(folder, records)
        with self.assertRaisesRegex(ValueError, 'greedy chunk boundaries'):
            baseline.verify(job)

    def test_build_record_must_match_the_actual_artifact(self):
        artifact = self.root / 'engine.bin'
        artifact.write_bytes(b'engine')
        build = self.root / 'build'
        build.mkdir()
        baseline.write_new(build / 'manifest.json', {'root': str(self.root)})
        baseline.write_new(build / 'status.json', {'summary': {'incomplete': 0}, 'attempts': [
            {'id': 'build', 'status': 'passed', 'artifacts': {'engine.bin': {'sha256': sha256(artifact)}}}]})
        self.assertEqual(baseline.build_reference(build / 'status.json', artifact)['status'], str(build / 'status.json'))
        artifact.write_bytes(b'changed engine')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            baseline.build_reference(build / 'status.json', artifact)


if __name__ == '__main__':
    unittest.main()
