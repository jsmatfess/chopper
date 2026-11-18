"""Controls for normalized metrics, reviewed populations and historical receipts."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('views', Path(__file__).with_name('evidence-views.py'))
views = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(views)


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'docs/performance').mkdir(parents=True)
        (self.root / 'docs/benchmarks').mkdir()
        (self.root / 'docs/validation.md').write_text('# Validation\n\n## Scope\n')
        self.config = views.read_json(views.ROOT / views.CONFIG)
        self.config['comparison_bindings'] = []
        self.config['validation_bindings'] = []
        self.entries = []
        self.save()

    def save(self):
        (self.root / views.CONFIG).write_text(json.dumps(self.config))
        (self.root / 'docs/benchmarks/catalog.json').write_text(json.dumps({'artifacts': self.entries}))

    def artifact(self, name, data, raw=False):
        path = self.root / 'docs/benchmarks' / name
        path.write_text(data if raw else json.dumps(data))
        entry = {'path': path.relative_to(self.root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                 'bytes': path.stat().st_size, 'format': path.suffix[1:]}
        self.entries.append(entry)
        self.save()
        return entry

    def rows(self, name='*'):
        return list(views.sources(self.root, name))

    def binding(self, entry, baseline, candidate):
        return {'id': 'reviewed', 'source': entry['path'], 'sha256': entry['sha256'],
                'timing_scope': 'Complete job; explicit exclusions.', 'runtime': 'native-windows',
                'clock_pointer': '/seconds',
                'review': {'source': views.CONFIG.as_posix(), 'basis': 'Reviewed selectors'},
                'baseline': baseline, 'candidate': candidate}

    def test_jsonl_physical_lines_units_unknown_context_and_distinct_record_classes(self):
        self.artifact('raw.jsonl', '\n{"type":"environment","workers":4}\n\n'
                      '{"type":"measurement","seconds":1,"peak_rss_kib":2,"verified":false}\n'
                      '{"type":"allocation","seconds":3}\n'
                      '{"type":"contract","seconds":4,"ok":true}\n'
                      '{"type":"summary","seconds":{"median":1}}\n', raw=True)
        _, observations, validations, _, _ = self.rows()[0]
        self.assertEqual([r['location']['line'] for r in observations], [4, 5, 6])
        first = observations[0]
        self.assertEqual(first['metrics'][1]['value'], 2048)
        self.assertEqual(first['metrics'][1]['source_value'], 2)
        self.assertEqual(first['metrics'][1]['source_pointer'], '/peak_rss_kib')
        self.assertIsNone(first['dimensions']['workers'])
        self.assertIsNone(first['dimensions']['runtime'])
        self.assertFalse(first['verification'])
        self.assertEqual(first['eligibility'], 'unreviewed')
        self.assertEqual([r['classification'] for r in observations], ['measurement', 'allocation-census', 'contract-duration'])
        self.assertEqual(validations[0]['status'], 'passed')

    def test_document_adapters_use_exact_nested_pointers_without_summary_duplication(self):
        self.artifact('report.json', {'native': {'complete_jobs': [
            {'type': 'complete_job', 'seconds': .25, 'candidate': False}]},
            'summaries': {'samples': [.25]}, 'checks': [{'id': 'check', 'status': 'passed', 'exit_code': 0}]})
        _, observations, validations, _, _ = self.rows()[0]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['location'], {'pointer': '/native/complete_jobs/0'})
        self.assertEqual(validations[0]['location'], {'pointer': '/checks/0'})
        self.assertIsNone(validations[0]['runtime'])

    def test_projected_graph_timings_stay_summary_and_do_not_inherit_context(self):
        self.artifact('graph.json', {'kind': 'summary', 'cohorts': [{'binary_sha256': 'not-a-row-fact'}],
                      'samples': [{'elapsed_seconds': 2, 'mode': 'collapsed', 'workload': 'external',
                                   'raw_sha256': 'a' * 64, 'raw_line': 7}]})
        _, observations, _, layouts, _ = self.rows()[0]
        self.assertEqual(len(observations), 1)
        row = observations[0]
        self.assertEqual(row['location'], {'pointer': '/samples/0'})
        self.assertEqual(row['classification'], 'summary')
        self.assertEqual(row['eligibility'], 'unreviewed')
        self.assertIsNone(row['dimensions']['binary_sha256'])
        self.assertEqual(row['dimensions']['observation_mode'], 'collapsed')
        self.assertEqual(row['metrics'][0]['source_pointer'], '/elapsed_seconds')
        self.assertIn('/cohorts', [ref['pointer'] for ref in row['metadata_refs']])

    def test_graph_diagnostic_runs_and_projected_samples_are_ineligible_for_speed(self):
        self.artifact('diagnostic.json', {'runs': [{'elapsed_seconds': 1}]})
        self.assertEqual(self.rows('diagnostic.json')[0][1][0]['classification'], 'diagnostic')
        entry = self.artifact('graph.json', {'samples': [{'elapsed_seconds': 1}, {'elapsed_seconds': 2}]})
        binding = self.binding(entry, [{'pointer': '/samples/0'}], [{'pointer': '/samples/1'}])
        binding['clock_pointer'] = '/elapsed_seconds'
        self.config['comparison_bindings'] = [binding]
        self.save()
        with self.assertRaisesRegex(ValueError, 'excluded record class'):
            self.rows('graph.json')

    def test_compact_batch_commands_keep_missing_status_unknown(self):
        self.artifact('receipt.json', {'batches': [{'summary': {'passed': 1}, 'commands': [
            {'id': 'check', 'exit_code': 0}]}]})
        _, _, validations, _, _ = self.rows()[0]
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0]['status'], 'unknown')
        self.assertEqual(validations[0]['location'], {'pointer': '/batches/0/commands/0'})
        self.assertIsNone(validations[0]['runtime'])
        self.assertIsNone(validations[0]['latest'])

    def test_identical_aliases_are_one_canonical_observation(self):
        self.artifact('first.jsonl', '{"type":"measurement","seconds":1}\n', raw=True)
        self.artifact('second.jsonl', '{"type":"measurement","seconds":1}\n', raw=True)
        self.assertEqual(len(self.rows()), 1)
        all_row = self.rows()[0][1][0]
        alias_row = self.rows('second.jsonl')[0][1][0]
        self.assertEqual(all_row['id'], alias_row['id'])
        self.assertEqual(len(alias_row['aliases']), 2)

    def test_present_corrupt_raw_fails_instead_of_using_catalog_metadata(self):
        entry = self.artifact('raw.json', {'tests': [{'seconds': 1}]})
        (self.root / entry['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'differs from catalog'):
            self.rows()

    def test_named_populations_are_explicit_and_cannot_overlap_arms(self):
        entry = self.artifact('raw.jsonl', '{"type":"measurement","seconds":1}\n'
                              '{"type":"measurement","seconds":2}\n', raw=True)
        self.config['comparison_bindings'] = [self.binding(entry, [{'line': 1, 'pointer': ''}], [{'line': 2, 'pointer': ''}])]
        self.save()
        rows = self.rows()[0][1]
        self.assertEqual([r['comparisons'][0]['role'] for r in rows], ['baseline', 'candidate'])
        self.assertTrue(all(r['eligibility'] == 'reviewed-for-named-comparisons-only' for r in rows))
        self.config['comparison_bindings'][0]['candidate'] = [{'line': 1, 'pointer': ''}]
        self.save()
        with self.assertRaisesRegex(ValueError, 'both arms'):
            self.rows()

    def test_allocation_censuses_cannot_enter_named_speed_comparisons(self):
        entry = self.artifact('raw.jsonl', '{"type":"allocation","seconds":1}\n'
                              '{"type":"measurement","seconds":2}\n', raw=True)
        self.config['comparison_bindings'] = [self.binding(entry, [{'line': 1, 'pointer': ''}], [{'line': 2, 'pointer': ''}])]
        self.save()
        with self.assertRaisesRegex(ValueError, 'excluded record class'):
            self.rows()

    def test_named_comparison_uses_its_reviewed_clock_when_two_clocks_exist(self):
        entry = self.artifact('raw.jsonl', '{"type":"measurement","seconds":1,"wall_seconds":20}\n'
                              '{"type":"measurement","seconds":2,"wall_seconds":30}\n', raw=True)
        self.config['comparison_bindings'] = [self.binding(entry, [{'line': 1, 'pointer': ''}], [{'line': 2, 'pointer': ''}])]
        self.save()
        output = io.StringIO()
        with mock.patch('sys.stdout', output):
            self.assertEqual(views.main(['--source', 'raw.jsonl', '--comparison', 'reviewed', '--metric', 'wall_time', '--all'], self.root), 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['metrics'][0]['value'] for r in rows], [1, 2])
        self.assertTrue(all(len(r['metrics']) == 1 for r in rows))

    def test_missing_comparison_selectors_fail_inventory_generation(self):
        entry = self.artifact('raw.jsonl', '{"type":"measurement","seconds":1}\n', raw=True)
        self.config['comparison_bindings'] = [self.binding(entry, [{'line': 1, 'pointer': ''}], [{'line': 9, 'pointer': ''}])]
        self.save()
        with self.assertRaisesRegex(ValueError, 'not extracted'):
            views.generate_index(self.root)

    def test_explicit_failed_verification_is_never_an_eligible_speed_sample(self):
        entry = self.artifact('raw.jsonl', '{"type":"measurement","seconds":1,"verified":false}\n'
                              '{"type":"measurement","seconds":2}\n', raw=True)
        self.config['comparison_bindings'] = [self.binding(entry, [{'line': 1, 'pointer': ''}], [{'line': 2, 'pointer': ''}])]
        self.save()
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            self.rows()

    def test_pointer_escaping_and_wildcards_do_not_walk_object_keys(self):
        value = {'a/b': {'~key': [1, 2]}, 'object': {'0': 5}}
        self.assertEqual(views.pointer(value, '/a~1b/~0key/1'), 2)
        self.assertEqual(list(views.select(value, '/a~1b/~0key/*')), [('/a~1b/~0key/0', 1), ('/a~1b/~0key/1', 2)])
        self.assertEqual(list(views.select(value, '/object/*')), [])
        self.assertIs(views.pointer([1, 2], '/-1'), views.MISSING)
        self.assertIs(views.pointer([1, 2], '/01'), views.MISSING)
        self.assertIs(views.pointer({'x~2': 5}, '/x~2'), views.MISSING)

    def test_source_record_queries_retain_null_and_do_not_hydrate_unrelated_artifacts(self):
        entry = self.artifact('raw.jsonl', '\n{"value":null}\n', raw=True)
        missing = self.artifact('unavailable.json', {'tests': [{'seconds': 1}]})
        (self.root / missing['path']).unlink()
        row = list(views.raw_records(self.root, 'raw.jsonl', '/value', 2))[0]
        self.assertIsNone(row['data'])
        self.assertEqual(row['source_sha256'], entry['sha256'])
        self.assertEqual(row['location'], {'line': 2, 'pointer': '/value'})
        self.assertEqual(len(self.rows('raw.jsonl')), 1)
        with self.assertRaisesRegex(ValueError, 'Missing source pointer'):
            list(views.raw_records(self.root, 'raw.jsonl', '/missing', 2))

    def test_invalid_metrics_fail_and_failed_cpu_query_is_not_a_measurement(self):
        for bad in [True, -1, float('nan'), 'unknown']:
            with self.assertRaisesRegex(ValueError, 'Invalid scalar metric'):
                views.metrics({'seconds': bad}, self.config)
        self.assertEqual(views.metrics({'cpu': {'ok': False, 'total_seconds': 9}}, self.config), [])

    def test_statuses_and_runtime_are_reported_without_batch_name_inference(self):
        entry = self.artifact('checks.json', {'checks': [
            {'id': 'pass', 'status': 'passed', 'exit_code': 0, 'platform': 'linux'},
            {'id': 'fail', 'status': 'failed', 'exit_code': 7},
            {'id': 'blocked', 'status': 'blocked'}, {'id': 'running', 'status': 'running'},
            {'id': 'unknown', 'batch': 'linux'}]})
        rows = self.rows()[0][2]
        self.assertEqual([r['status'] for r in rows], ['passed', 'failed', 'blocked', 'incomplete', 'unknown'])
        self.assertEqual(rows[0]['runtime'], 'native-linux')
        self.assertIsNone(rows[-1]['runtime'])
        with self.assertRaisesRegex(ValueError, 'nonzero exit'):
            views.validation(entry, {'pointer': ''}, {'status': 'passed', 'exit_code': 1}, self.config, [])
        for status in ('incomplete', 'unknown'):
            self.assertEqual(views.normalized_status({'status': status}), status)
            self.assertEqual(views.normalized_status({'status': status, 'ok': True, 'passed': True}), status)
        for status in ('new-unsupported-status', {'state': 'incomplete'}):
            self.assertEqual(views.normalized_status({'status': status, 'ok': True}), 'unknown')

    def test_validation_binding_pins_source_and_exact_check(self):
        entry = self.artifact('checks.json', {'checks': [{'id': 'focused', 'status': 'passed'}]})
        self.config['validation_bindings'] = [{
            'source': entry['path'], 'sha256': entry['sha256'], 'location': {'pointer': '/checks/0'},
            'check_id': 'focused', 'contract': 'cleanup', 'contract_refs': ['docs/validation.md#scope'],
            'runtime': 'native-windows', 'browser': None, 'features': []}]
        self.save()
        self.assertEqual(self.rows()[0][2][0]['contract'], 'cleanup')
        self.config['validation_bindings'][0]['check_id'] = 'different'
        self.save()
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.rows()

    def test_validation_binding_on_identical_alias_survives_canonicalization(self):
        data = {'checks': [{'id': 'focused', 'status': 'passed'}]}
        canonical = self.artifact('aaa.json', data)
        alias = self.artifact('zzz.json', data)
        self.config['validation_bindings'] = [{
            'source': alias['path'], 'sha256': alias['sha256'], 'location': {'pointer': '/checks/0'},
            'check_id': 'focused', 'contract': 'cleanup', 'contract_refs': ['docs/validation.md#scope'],
            'runtime': 'native-windows', 'browser': None, 'features': []}]
        self.save()
        for pattern in ('*', 'aaa.json', 'zzz.json'):
            rows = self.rows(pattern)
            self.assertEqual(len(rows), 1)
            row = rows[0][2][0]
            self.assertEqual(row['source'], canonical['path'])
            self.assertEqual(row['contract'], 'cleanup')
            self.assertEqual(row['runtime'], 'native-windows')

    def test_inventory_rejects_an_unconsumed_validation_binding(self):
        entry = self.artifact('unsupported.log', 'legacy text', raw=True)
        self.config['validation_bindings'] = [{
            'source': entry['path'], 'sha256': entry['sha256'], 'location': {'pointer': '/checks/0'},
            'check_id': 'focused', 'contract': 'cleanup', 'contract_refs': ['docs/validation.md#scope'],
            'runtime': 'native-windows', 'browser': None, 'features': []}]
        self.save()
        with self.assertRaisesRegex(ValueError, 'not consumed'):
            views.generate_index(self.root)

    def test_runner_import_preserves_failed_attempts_unrun_steps_and_snapshot_identity(self):
        batch = self.root / 'batch'
        batch.mkdir()
        manifest = {'features': ['opt-in'], 'steps': [
            {'id': 'first', 'argv': ['never-execute'], 'coverage': {'contract': 'cleanup', 'runtime': 'native-linux'}},
            {'id': 'second', 'argv': ['never-execute']}]}
        (batch / 'manifest.json').write_text(json.dumps(manifest))
        (batch / 'status.json').write_text(json.dumps({'attempts': [
            {'id': 'first', 'attempt': 1, 'status': 'passed', 'exit_code': 0, 'inputs': {'x': {'sha256': 'a'}}},
            {'id': 'first', 'attempt': 2, 'status': 'failed', 'exit_code': 7}]}))
        rows = list(views.runner_receipts(batch))
        self.assertEqual([r['status'] for r in rows], ['passed', 'failed', 'unrun'])
        self.assertEqual([r['latest'] for r in rows], [False, True, True])
        self.assertEqual(rows[0]['contract'], 'cleanup')
        self.assertIsNone(rows[2]['runtime'])
        self.assertIn('sha256', rows[0]['manifest'])
        self.assertEqual(rows[0]['attempt_key'], list(views.runner_receipts(batch))[0]['attempt_key'])
        self.assertEqual(rows[0]['build_identity']['inputs']['x']['sha256'], 'a')
        (batch / 'status.json').unlink()
        self.assertEqual([r['status'] for r in views.runner_receipts(batch)], ['unrun', 'unrun'])

    def test_real_runner_round_trip_retains_coverage_and_failure_history(self):
        spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('validation-runner.py'))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        (self.root / 'input').write_text('declared')
        first = {'id': 'first', 'inputs': ['input'], 'artifacts': [], 'timeout_seconds': 3,
                 'argv': [sys.executable, '-c', 'pass'],
                 'coverage': {'contract': 'tiny-control', 'runtime': 'native-linux'}}
        second = {**first, 'id': 'second', 'depends': ['first'], 'argv': [sys.executable, '-c', 'raise SystemExit(7)']}
        third = {**first, 'id': 'third', 'depends': ['second']}
        plan = {'root': str(self.root), 'batch_timeout_seconds': 10, 'estimated_seconds': 1,
                'estimated_disk_bytes': 1024, 'toolchains': {'python': sys.version}, 'features': [],
                'fixtures': ['tiny'], 'steps': [first, second, third]}
        path, batch = self.root / 'plan.json', self.root / 'batch'
        path.write_text(json.dumps(plan))
        with mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(runner.run(path, batch), 1)
        rows = list(views.runner_receipts(batch))
        self.assertEqual([r['status'] for r in rows], ['passed', 'failed', 'unrun'])
        self.assertEqual(rows[1]['exit_code'], 7)
        self.assertEqual(rows[0]['contract'], 'tiny-control')
        self.assertIn('input', rows[0]['build_identity']['inputs'])
        self.assertIsNotNone(rows[0]['runtime_identity']['executable_sha256'])
        self.assertTrue(rows[0]['logs']['stdout']['available'])
        self.assertEqual(rows[0]['logs']['stdout']['sha256'], hashlib.sha256(b'').hexdigest())

    def test_unsupported_artifacts_are_visible_and_generated_checks_reject_drift(self):
        self.artifact('unknown.json', {'other': {'value': 5}})
        (self.root / 'docs/validation.md').write_text('## Scope\nNo status inferred.\n')
        with mock.patch('sys.stdout', io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(views.main(['--build'], self.root), 0)
            self.assertEqual(views.main(['--check'], self.root), 0)
            index = views.read_json(self.root / views.INDEX)
            self.assertEqual(index['sources'][0]['coverage'], 'not-adapted')
            self.assertEqual(index['validation_narratives'][0]['status'], 'not-inferred-from-prose')
            path = self.root / views.INDEX
            path.write_text('stale\n')
            self.assertEqual(views.main(['--check'], self.root), 1)
            self.assertEqual(path.read_text(), 'stale\n')


if __name__ == '__main__':
    unittest.main()
