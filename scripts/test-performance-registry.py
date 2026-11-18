"""Controls for interpretation drift, provenance, supersession and offline queries."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('performance_registry', Path(__file__).with_name('performance-registry.py'))
registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / registry.RECORDS).mkdir(parents=True)
        (self.root / 'docs/benchmarks').mkdir()
        shutil.copyfile(registry.ROOT / registry.SCHEMA, self.root / registry.SCHEMA)
        self.performance = self.root / 'docs/performance.md'
        self.performance.write_text('# Performance\n\n## Test\n\nReviewed decision.\n')
        (self.root / 'docs/specification.md').write_text('# Specification\n\n## Contract\n')
        self.raw = self.root / 'docs/benchmarks/raw.json'
        self.raw.write_text('{"tests":[{"seconds":1}]}\n')
        self.record = {
            'schema_version': 1, 'id': 'test', 'title': 'Test decision', 'date': '2026-11-05',
            'subsystem': 'storage', 'question': 'Is this variant useful?', 'disposition': 'retain-experimental',
            'outcome': 'inconclusive', 'delivery': 'unapplied', 'summary': 'Keep evidence without activation.',
            'scope': {'runtimes': ['native-windows'], 'workloads': ['Tiny fixture'], 'measurement': 'complete-run'},
            'validation': {'runtimes': ['native-windows'], 'summary': 'Exact bytes in this fixture.'},
            'limitations': ['One workload.'], 'exclusions': ['Contract duration is not a speedup.'],
            'reopen_when': None, 'supersedes': [],
            'sources': [{'section': 'docs/performance.md#test',
                         'sha256': registry.section_hash(registry.section_index(self.performance)['test'])}],
            'artifacts': [{'path': 'docs/benchmarks/raw.json', 'sha256': hashlib.sha256(self.raw.read_bytes()).hexdigest()}],
            'contracts': ['docs/specification.md#contract']}
        self.write(self.record)
        self.catalog_path = self.root / 'docs/benchmarks/catalog.json'
        self.catalog_path.write_text(json.dumps({
            'artifacts': self.record['artifacts'],
            'experiments': [{'evidence': 'docs/performance.md#test', 'artifacts': ['docs/benchmarks/raw.json']}]}))

    def write(self, record):
        (self.root / registry.RECORDS / (record['id'] + '.json')).write_text(json.dumps(record))

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch('sys.stdout', stdout), mock.patch('sys.stderr', stderr):
            result = registry.main(list(args), self.root)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_queries_work_without_archived_raw_files_and_do_not_write(self):
        self.raw.unlink()
        self.assertEqual(len(registry.load_records(self.root)), 1)
        code, output, _ = self.run_cli('--query', '--runtime', 'native-windows', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['records'], [self.record])
        self.assertFalse((self.root / registry.OVERVIEW).exists())
        code, output, _ = self.run_cli('--query', '--runtime', 'native-linux', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['records'], [])

    def test_source_edit_requires_review_but_unrelated_preamble_does_not(self):
        self.performance.write_text('New navigation.\n\n' + self.performance.read_text())
        self.assertEqual(len(registry.load_records(self.root)), 1)
        self.performance.write_text(self.performance.read_text().replace('Reviewed decision.', 'Changed conclusion.'))
        with self.assertRaisesRegex(ValueError, 'source section changed'):
            registry.load_records(self.root)

    def test_stale_catalog_and_present_corrupt_raw_are_rejected(self):
        self.raw.write_text('changed raw bytes')
        with self.assertRaisesRegex(ValueError, 'local artifact hash mismatch'):
            registry.load_records(self.root)
        self.raw.unlink()
        self.record['artifacts'][0]['sha256'] = '0' * 64
        self.write(self.record)
        with self.assertRaisesRegex(ValueError, 'identity differs from catalog'):
            registry.load_records(self.root)

    def test_unrelated_catalog_artifact_is_not_evidence_for_a_decision(self):
        catalog = json.loads(self.catalog_path.read_text())
        catalog['experiments'][0]['artifacts'] = []
        self.catalog_path.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError, 'artifact not linked'):
            registry.load_records(self.root)

    def test_missing_source_and_contract_anchors_fail(self):
        self.performance.write_text('## Renamed\n')
        with self.assertRaisesRegex(ValueError, 'Missing source section'):
            registry.load_records(self.root)
        self.performance.write_text('# Performance\n\n## Test\n\nReviewed decision.\n')
        self.record['contracts'] = ['docs/specification.md#missing']
        self.write(self.record)
        with self.assertRaisesRegex(ValueError, 'Missing H2 anchor'):
            registry.load_records(self.root)

    def test_unknown_fields_versions_types_and_missing_scope_fail(self):
        for edit in [lambda r: r.update(extra=True), lambda r: r.update(schema_version=2),
                     lambda r: r.update(schema_version=True), lambda r: r.pop('scope'),
                     lambda r: r['scope'].update(runtimes=['unrecorded-platform'])]:
            record = copy.deepcopy(self.record)
            edit(record)
            self.write(record)
            with self.assertRaises(ValueError):
                registry.load_records(self.root)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / registry.RECORDS / 'test.json'
        path.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaisesRegex(ValueError, 'duplicate key'):
            registry.load_records(self.root)

    def test_rejected_variant_cannot_claim_default_delivery(self):
        self.record.update(disposition='reject', delivery='default')
        self.write(self.record)
        with self.assertRaisesRegex(ValueError, 'must be unapplied'):
            registry.load_records(self.root)

    def test_superseded_decisions_remain_explicitly_queryable(self):
        successor = copy.deepcopy(self.record)
        successor.update(id='replacement', supersedes=['test'], disposition='adopt', delivery='opt-in')
        self.write(successor)
        code, output, _ = self.run_cli('--query', '--json')
        self.assertEqual(code, 0)
        self.assertEqual([r['id'] for r in json.loads(output)['records']], ['replacement'])
        _, output, _ = self.run_cli('--query', '--include-superseded', '--json')
        self.assertEqual(len(json.loads(output)['records']), 2)
        _, output, _ = self.run_cli('--show', 'test')
        self.assertEqual(json.loads(output), self.record)
        _, output, _ = self.run_cli('--query', '--delivery', 'opt-in', '--subsystem', 'storage', '--json')
        self.assertEqual([r['id'] for r in json.loads(output)['records']], ['replacement'])

    def test_missing_supersession_targets_cycles_and_backward_dates_fail(self):
        self.record['supersedes'] = ['missing']
        self.write(self.record)
        with self.assertRaisesRegex(ValueError, 'unknown superseded ID'):
            registry.load_records(self.root)
        self.record['supersedes'] = ['replacement']
        self.write(self.record)
        successor = copy.deepcopy(self.record)
        successor.update(id='replacement', supersedes=['test'])
        self.write(successor)
        with self.assertRaisesRegex(ValueError, 'Supersession cycle'):
            registry.load_records(self.root)
        successor.update(supersedes=[], date='2026-11-06')
        self.write(successor)
        with self.assertRaisesRegex(ValueError, 'supersedes a later decision'):
            registry.load_records(self.root)

    def test_overview_keeps_decision_and_delivery_independent_without_omissions(self):
        self.record.update(disposition='adopt', delivery='unapplied')
        self.write(self.record)
        output = registry.render(registry.load_records(self.root), self.root)
        self.assertIn('Adopted, awaiting delivery', output)
        self.assertEqual(output.count('[Test decision]'), 1)
        self.record.update(disposition='retain-experimental', delivery='opt-in')
        self.write(self.record)
        output = registry.render(registry.load_records(self.root), self.root)
        self.assertIn('Delivered as opt-in', output)
        self.assertEqual(output.count('[Test decision]'), 1)

    def test_overview_check_is_read_only_and_rejects_drift_and_crlf(self):
        self.assertEqual(self.run_cli()[0], 0)
        path = self.root / registry.OVERVIEW
        original = path.read_bytes()
        self.assertEqual(self.run_cli('--check')[0], 0)
        for replacement in [original.replace(b'\n', b'\r\n'), b'stale\n']:
            path.write_bytes(replacement)
            code, _, error = self.run_cli('--check')
            self.assertEqual(code, 1)
            self.assertIn('stale', error)
            self.assertEqual(path.read_bytes(), replacement)

    def test_unsafe_contract_paths_and_unknown_schema_assertions_fail_closed(self):
        self.record['contracts'] = ['../outside.md']
        self.write(self.record)
        with self.assertRaisesRegex(ValueError, 'Unsafe repository path'):
            registry.load_records(self.root)
        with self.assertRaisesRegex(ValueError, 'unsupported schema assertion'):
            registry.validate_schema('text', {'type': 'string', 'maxLength': 2}, {}, 'test')


if __name__ == '__main__':
    unittest.main()
