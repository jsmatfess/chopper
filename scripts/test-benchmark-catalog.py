"""Regression tests for benchmark provenance and inventory boundaries."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('benchmark_catalog', Path(__file__).with_name('benchmark-catalog.py'))
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def test_generated_navigation_uses_lf_and_check_rejects_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / catalog.ARTIFACTS
            artifacts.mkdir(parents=True)
            (root / 'docs/performance.md').write_bytes(b'## Test\n')
            with mock.patch.object(catalog, 'ROOT', root), mock.patch('sys.argv', ['catalog']), \
                    mock.patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(catalog.main(), 0)
            for name in ['catalog.json', 'INDEX.md']:
                self.assertNotIn(b'\r', (artifacts / name).read_bytes())
            with mock.patch.object(catalog, 'ROOT', root), mock.patch('sys.argv', ['catalog', '--check']), \
                    mock.patch('sys.stdout', new_callable=io.StringIO), \
                    mock.patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(catalog.main(), 0)
                path = artifacts / 'INDEX.md'
                path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
                self.assertEqual(catalog.main(), 1)

    def test_export_preserves_locations_values_and_report_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / catalog.ARTIFACTS
            artifacts.mkdir(parents=True)
            raw = artifacts / 'raw.jsonl'
            raw.write_text('\n{"event":"environment","workers":4}\n\n'
                           '{"type":"measurement","seconds":0.5,"verified":false}\nnull\n')
            (artifacts / 'report.json').write_text('{"tests":[{"seconds":1},{"seconds":2}]}')
            (artifacts / 'failure.log').write_text('interrupted')
            # Generated navigation must never be re-exported as evidence.
            (artifacts / 'catalog.json').write_text('{"artifacts":[]}')
            stream = io.StringIO()
            catalog.export_records(root, '*', stream)
            exported = [json.loads(line) for line in stream.getvalue().splitlines()]
            samples = [row for row in exported if row['source'].endswith('raw.jsonl')]
            self.assertEqual([row['line'] for row in samples], [2, 4, 5])
            self.assertEqual(samples[1]['data'], {'type': 'measurement', 'seconds': 0.5, 'verified': False})
            self.assertIsNone(samples[2]['data'])
            self.assertEqual(samples[0]['kind'], 'environment')
            self.assertEqual(len(exported), 4)
            self.assertEqual(exported[-1]['pointer'], '')
            self.assertEqual(len(exported[-1]['data']['tests']), 2)
            original_hash = samples[0]['source_sha256']
            raw.write_text(raw.read_text() + '{}\n')
            stream = io.StringIO()
            catalog.export_records(root, 'raw.*', stream)
            self.assertNotEqual(json.loads(stream.getvalue().splitlines()[0])['source_sha256'], original_hash)

    def test_inventory_is_deterministic_and_includes_logs_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / catalog.ARTIFACTS
            artifacts.mkdir(parents=True)
            (root / 'docs/performance.md').write_text('## Experiment (2026-10-19)\n'
                '[raw](benchmarks/raw.jsonl)\n```sh\n## Not a section\n'
                'python3 scripts/benchmark-example.py\n```\n')
            (artifacts / 'raw.jsonl').write_text('{"type":"environment","workers":4}\n')
            (artifacts / 'copy.jsonl').write_bytes((artifacts / 'raw.jsonl').read_bytes())
            (artifacts / 'failure.log').write_text('failure')
            (artifacts / '.gitignore').write_text('*.jsonl\n')
            first = catalog.build_catalog(root)
            self.assertEqual(first, catalog.build_catalog(root))
            self.assertEqual(len(first['artifacts']), 3)
            self.assertEqual(len(first['experiments']), 1)
            self.assertEqual(first['experiments'][0]['scripts'], ['scripts/benchmark-example.py'])
            self.assertEqual(first['experiments'][0]['evidence'], 'docs/performance.md#experiment-2026-10-19')
            self.assertEqual(first['identical_content'], [['docs/benchmarks/copy.jsonl', 'docs/benchmarks/raw.jsonl']])
            raw = first['artifacts'][-1]
            self.assertEqual(raw['context_records'], [{'line': 1, 'kind': 'environment'}])
            self.assertEqual(raw['record_counts'], {'environment': 1})
            self.assertIn('workers', raw['fields'])
            self.assertIn('failure.log', catalog.render_index(first))

    def test_malformed_json_fails_with_source_location(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.jsonl'
            path.write_text('{}\n\n{broken}\n')
            with self.assertRaisesRegex(ValueError, r'bad.jsonl:3:'):
                list(catalog.records(path))

    def test_removed_harness_navigation_routes_to_preserved_source_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / catalog.ARTIFACTS).mkdir(parents=True)
            (root / 'docs/performance.md').write_text('## Historical\npython scripts/validate-parallel-groups.py\n')
            result = catalog.build_catalog(root)
            self.assertEqual(result['experiments'][0]['scripts'], ['scripts/validate-parallel-groups.py'])
            self.assertIn('../../docs/history/rejected-parallel-groups-2026-10-25/validate-parallel-groups.py',
                          catalog.render_index(result))


if __name__ == '__main__':
    unittest.main()
